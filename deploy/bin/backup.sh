#!/usr/bin/env bash
# =============================================================================
# Tender AI — baza zaxirasi
# =============================================================================
#     backup.sh <staging|production>
#
# `pg_dump` MAXSUS formatda (`-Fc`): u siqilgan, parallel tiklanadi
# va TANLAB tiklashga imkon beradi (bitta jadval). Oddiy SQL matni
# 134 MB hujjat matni bilan ulkan bolardi.
#
# ZAXIRA O'ZI YETARLI EMAS. Uchta narsa qilinadi:
#   1. dump olinadi;
#   2. DARHOL `pg_restore --list` bilan OCHILISHI tekshiriladi —
#      buzuq faylni haftalab saqlab yurmaslik uchun;
#   3. SHA-256 yoziladi — keyinchalik fayl ozgarganini bilish uchun.
#
# YUKLANGAN FAYLLAR ALOHIDA ARXIVLANADI.
#
# NEGA: `pg_dump` faqat BAZANI oladi. Foydalanuvchi yuklagan hujjat
# esa DISKDA yotadi (`UPLOAD_ROOT`) va bazada faqat KALIT saqlanadi.
# Ya'ni faqat baza zaxirasi bilan tiklangan tizimda har hujjat
# "bor" deb ko'rinardi va ochilganda TOPILMASDI — eng yomon shakl,
# chunki yo'qotish faqat foydalanuvchi bosganda bilinadi.
#
# HAQIQIY TIKLASH MASHQI alohida: `restore-test.sh` (haftalik).
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: backup.sh <staging|production>}"
# MUHIT FAYLI YO'LI ALMASHTIRILISHI MUMKIN — `TENDERAI_ENVFILE`.
#
# NEGA (o'lchangan 2026-09-01, B-1): yo'l `/etc/tenderai/` ga
# QOTIRILGAN edi va u FAQAT tayyorlangan serverda mavjud. Natijada
# skriptlar HECH QACHON, HECH QAYERDA yurgizilmagan — ular faqat
# `deploy_test` da MATN sifatida tekshirilardi (114 tekshiruv,
# hammasi statik).
#
# "Yozilgan, lekin bir marta ham bajarilmagan skript" —
# joylashtirish kunidagi eng qimmat noma'lum. Endi mashq qilish
# mumkin: yo'l berilsa o'sha ishlatiladi.
#
# Standart qiymat O'ZGARMADI — serverdagi xulq bir xil qoladi.
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
[ -f "$ENVFILE" ] || { echo "muhit fayli yoq: $ENVFILE"; exit 2; }

set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a

: "${XT_DB_DSN:?XT_DB_DSN kerak}"
KATALOG="${BACKUP_DIR:-/var/backups/tenderai}/${MUHIT}"
KUN="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
FAYL="${KATALOG}/tenderai-${MUHIT}-${STAMP}.dump"

mkdir -p "$KATALOG"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

log "zaxira boshlandi -> $FAYL"
# `--no-owner --no-privileges`: tiklash BOSHQA rol bilan ham ishlasin
# (tiklash mashqi vaqtinchalik bazaga tiklaydi).
pg_dump "$XT_DB_DSN" \
    --format=custom \
    --compress=6 \
    --no-owner --no-privileges \
    --file="$FAYL"

HAJM="$(du -h "$FAYL" | cut -f1)"
log "olindi: $HAJM"

# --- OCHILISHI DARHOL TEKSHIRILADI ------------------------------------------
# Buzuq dump faqat tiklash paytida bilinardi — yani AYNAN eng yomon
# paytda. Bu tekshiruv arzon va u shu holatni oldini oladi.
if ! pg_restore --list "$FAYL" > /dev/null 2>&1; then
    log "XATO: dump OCHILMADI — fayl ochirildi"
    rm -f "$FAYL"
    exit 1
fi
JADVALLAR="$(pg_restore --list "$FAYL" | grep -c 'TABLE DATA' || true)"
log "ochildi: $JADVALLAR ta jadval malumoti"

# Bo'sh yoki shubhali kichik dump — signal.
if [ "$JADVALLAR" -lt 10 ]; then
    log "XATO: dump ichida atigi $JADVALLAR ta jadval — shubhali, ochirildi"
    rm -f "$FAYL"
    exit 1
fi

sha256sum "$FAYL" > "${FAYL}.sha256"
log "sha256 yozildi"

# --- YUKLANGAN FAYLLAR ------------------------------------------------------
# `UPLOAD_ROOT` — `api/saqlash.py` bilan AYNI o'zgaruvchi. Standart
# qiymat ham o'sha yerdagidek: reliz ichidagi `.runtime/uploads`.
#
# ISHLAB CHIQARISHDA U RELIZDAN TASHQARIDA bo'lishi SHART
# (`/var/lib/tenderai/uploads`): `deploy.sh` har relizda YANGI
# katalog yasaydi va reliz ichidagi fayllar keyingi joylashtiruvda
# ko'rinmay qolardi. Buni tekshiramiz va jim qolmaymiz.
YUKLAMA_ILDIZ="${UPLOAD_ROOT:-${ILDIZ:-/opt/tenderai/$MUHIT}/current/.runtime/uploads}"
FAYL_ARXIV="${KATALOG}/tenderai-${MUHIT}-${STAMP}-fayllar.tar.gz"

if [ -d "$YUKLAMA_ILDIZ" ]; then
    case "$YUKLAMA_ILDIZ" in
        */current/*|*/releases/*)
            log "OGOHLANTIRISH: yuklama katalogi RELIZ ICHIDA ($YUKLAMA_ILDIZ)."
            log "  Keyingi joylashtiruv yangi katalog yasaydi va fayllar"
            log "  ko'rinmay qoladi. \`UPLOAD_ROOT\` ni relizdan TASHQARIGA"
            log "  qo'ying (masalan /var/lib/tenderai/uploads)."
            ;;
    esac
    # `--warning=no-file-changed`: yuklash arxivlash paytida bo'lsa
    # `tar` 1 qaytaradi va `set -e` butun zaxirani YIQITARDI —
    # holbuki baza dump'i allaqachon olingan va u yaroqli.
    tar -czf "$FAYL_ARXIV" -C "$(dirname "$YUKLAMA_ILDIZ")"         "$(basename "$YUKLAMA_ILDIZ")" 2>/dev/null || {
        log "OGOHLANTIRISH: fayl arxivi to'liq olinmadi (fayl o'zgargan bo'lishi mumkin)"
    }
    if [ -f "$FAYL_ARXIV" ]; then
        sha256sum "$FAYL_ARXIV" > "${FAYL_ARXIV}.sha256"
        SONI="$(tar -tzf "$FAYL_ARXIV" | grep -cv '/$' || true)"
        log "yuklangan fayllar: $SONI ta -> $(du -h "$FAYL_ARXIV" | cut -f1)"
        # BAZADAGI SON BILAN SOLISHTIRAMIZ. Arxiv "olindi" degani
        # "to'liq" degani emas: `UPLOAD_ROOT` noto'g'ri bo'lsa tar
        # BO'SH katalogni muvaffaqiyatli arxivlaydi va zaxira
        # YASHIL ko'rinardi.
        BAZADA="$(psql "$XT_DB_DSN" -tAc             "SELECT count(*) FROM yuklama WHERE arxiv_at IS NULL" 2>/dev/null || echo "?")"
        log "bazada faol yuklama: $BAZADA ta"
        if [ "$BAZADA" != "?" ] && [ "$BAZADA" -gt 0 ] && [ "$SONI" -eq 0 ]; then
            log "XATO: bazada $BAZADA ta fayl bor, arxivda 0 ta."
            log "  \`UPLOAD_ROOT\` noto'g'ri ko'rsatilgan bo'lishi mumkin."
            exit 1
        fi
    fi
else
    # JIM QOLMAYDI. Katalog yo'qligi normal bo'lishi mumkin (hali
    # hech kim fayl yuklamagan), lekin buni AYTISH kerak — aks holda
    # "zaxira to'liq" degan yolg'on xulosa chiqardi.
    log "OGOHLANTIRISH: yuklama katalogi topilmadi ($YUKLAMA_ILDIZ) —"
    log "  fayl zaxirasi OLINMADI. Hali fayl yuklanmagan bo'lsa normal."
fi

# --- TASHQI NUSXA -----------------------------------------------------------
# ZAXIRA BITTA DISKDA — ZAXIRA EMAS. Disk yo'qolsa (yoki shifrlovchi
# dastur tegsa) zaxira ham u bilan ketadi.
#
# NEGA BUYRUQ SHABLONI, "manzil" EMAS: nusxalash usuli har joyda
# boshqacha (rsync, rclone, aws s3, scp, restic). Manzilga qarab
# usulni TAXMIN QILISH noto'g'ri buyruqni jimgina yurgizardi.
# Operator NIMA qilishni ANIQ yozadi.
#
#   BACKUP_REMOTE_CMD='rclone copy {fayl} uzoq:tenderai/'
#   BACKUP_REMOTE_CMD='aws s3 cp {fayl} s3://chelak/tenderai/'
#   BACKUP_REMOTE_CMD='rsync -a {fayl} zaxira@host:/srv/tenderai/'
#
# `{fayl}` dump yo'liga almashadi. `.sha256` ham SHU buyruq bilan
# yuboriladi — butunlikni uzoqda ham tekshirish uchun.
#
# SOZLANMAGANI JIM QOLMAYDI: ogohlantirish YOZILADI. "Zaxira bor"
# degan xulosa "zaxira XAVFSIZ" degani emas.
if [ -n "${BACKUP_REMOTE_CMD:-}" ]; then
    # FAYL ARXIVI HAM UZOQQA KETADI. Aks holda baza uzoqda,
    # fayllar esa faqat mahalliy diskda qolardi — ya'ni disk
    # yo'qolganda hujjatlar ham yo'qolardi.
    for f in "$FAYL" "${FAYL}.sha256"              ${FAYL_ARXIV:+"$FAYL_ARXIV" "${FAYL_ARXIV}.sha256"}; do
        [ -f "$f" ] || continue
        BUYRUQ="${BACKUP_REMOTE_CMD//\{fayl\}/$f}"
        log "tashqi nusxa: $BUYRUQ"
        # XATO YUTILMAYDI. Tashqi nusxa yiqilsa — zaxira HALI HAM
        # bitta diskda, ya'ni himoya yo'q. Buni bilib turish shart.
        if ! eval "$BUYRUQ"; then
            log "XATO: tashqi nusxa YIQILDI — zaxira faqat mahalliy diskda"
            exit 1
        fi
    done
    log "tashqi nusxa OK"
else
    log "OGOH: BACKUP_REMOTE_CMD sozlanmagan — zaxira FAQAT mahalliy diskda"
fi

# --- ESKILARINI TOZALASH ----------------------------------------------------
# TARTIB MUHIM: tashqi nusxa YUQORIDA, tozalash PASTDA. Aks holda
# mahalliy fayl o'chirilib, uzoqqa esa hech narsa ketmagan bo'lishi
# mumkin edi.
# Faqat SHU muhitning fayllari va faqat kutilgan naqsh boyicha.
find "$KATALOG" -maxdepth 1 -name "tenderai-${MUHIT}-*.dump*" \
     -mtime "+${KUN}" -print -delete | while read -r f; do
    log "eski zaxira ochirildi: $(basename "$f")"
done

QOLGAN="$(find "$KATALOG" -maxdepth 1 -name '*.dump' | wc -l)"
log "TUGADI. Katalogda $QOLGAN ta zaxira."
