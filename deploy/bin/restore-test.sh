#!/usr/bin/env bash
# =============================================================================
# Tender AI — TIKLASH MASHQI
# =============================================================================
#     restore-test.sh <staging|production>
#
# SINALMAGAN ZAXIRA — ZAXIRA EMAS. "Fayl bor" degani "tiklanadi"
# degani emas: dump buzuq bolishi, sxema tiklanmasligi, yoki
# tiklash tasavvurdan uzun davom etishi mumkin. Bularning hammasi
# AYNAN falokat paytida bilinardi.
#
# BU SKRIPT HAR HAFTA:
#   1. eng oxirgi zaxirani oladi;
#   2. VAQTINCHALIK bazaga tiklaydi;
#   3. jadval sonini, qator sonini va migratsiya holatini TEKSHIRADI;
#   4. tiklash VAQTINI olchaydi (RTO uchun haqiqiy raqam);
#   5. vaqtinchalik bazani TASHLAYDI.
#
# ISHLAB CHIQARISH BAZASIGA TEGMAYDI. Nom tekshiruvi bor va u
# bajarilmasa skript TOXTAYDI.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: restore-test.sh <staging|production>}"
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

: "${XT_DB_DSN_OWNER:?tiklash mashqi uchun XT_DB_DSN_OWNER kerak}"
KATALOG="${BACKUP_DIR:-/var/backups/tenderai}/${MUHIT}"
SINOV_BAZA="tenderai_restore_test_${MUHIT}"

log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
xato() { printf '[%s] XATO: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

# --- XAVFSIZLIK: ishlab chiqarish bazasiga TEGMASLIK -------------------------
# Bu tekshiruv JIMGINA OTKAZIB YUBORILMAYDI. U bajarilmasa skript
# toxtaydi: vaqtinchalik baza nomi haqiqiysiga teng bolsa, mashq
# ishlab chiqarishni YOQ QILARDI.
ASOSIY_BAZA="$(printf '%s' "$XT_DB_DSN_OWNER" | tr ' ' '\n' \
               | grep -E '^dbname=' | cut -d= -f2 || true)"
[ -n "$ASOSIY_BAZA" ] || xato "DSN dan dbname olinmadi"
[ "$ASOSIY_BAZA" != "$SINOV_BAZA" ] || xato "sinov bazasi nomi asosiy baza bilan BIR XIL"
log "asosiy baza: $ASOSIY_BAZA   sinov bazasi: $SINOV_BAZA"

# Admin DSN — `postgres` bazasiga ulanib CREATE/DROP qilish uchun.
ADMIN_DSN="$(printf '%s' "$XT_DB_DSN_OWNER" | sed "s/dbname=${ASOSIY_BAZA}/dbname=postgres/")"

# --- 1) Zaxira: MAHALLIY eng oxirgisi yoki BERILGAN yo'l ---------------------
# `TIKLASH_ZAXIRA` berilsa AYNAN o'sha fayl tiklanadi. Bu uzoqdan
# olib kelingan nusxani tiklash uchun: mahalliy artefaktni qayta
# ishlatish "uzoqdan tiklandi" degan da'voni ISBOTLAMASDI --
# u faqat mahalliy diskni sinardi.
#
# `TIKLASH_MANBA` esa DALILGA yoziladi va uni skript O'ZI
# TAXMIN QILMAYDI: qiymatni faqat uzoqdan olib keladigan yo'l
# qo'yadi.
if [ -n "${TIKLASH_ZAXIRA:-}" ]; then
    ZAXIRA="$TIKLASH_ZAXIRA"
    [ -f "$ZAXIRA" ] || xato "berilgan zaxira topilmadi: $ZAXIRA"
    log "zaxira MANBASI: ${TIKLASH_MANBA:-berilgan} ($ZAXIRA)"
else
    ZAXIRA="$(find "$KATALOG" -maxdepth 1 -name '*.dump' -printf '%T@ %p\n' 2>/dev/null \
              | sort -rn | head -1 | cut -d' ' -f2- || true)"
    [ -n "$ZAXIRA" ] || xato "zaxira topilmadi: $KATALOG"
fi
log "zaxira: $(basename "$ZAXIRA")  ($(du -h "$ZAXIRA" | cut -f1))"

# BO'SH DUMP -- ZAXIRA EMAS.
# O'LCHANGAN (2026-09-08): yiqilgan `pg_dump` katalogda 0 baytli fayl
# qoldirdi va u ENG YANGI bo'lgani uchun aynan shu tanlanardi.
[ -s "$ZAXIRA" ] || xato "zaxira BO'SH (0 bayt): $ZAXIRA
   Bu yiqilgan \`pg_dump\` dan qolgan yarim fayl. Uni o'chiring va
   zaxirani qayta oling; undan TIKLAB BO'LMAYDI."

# --- 2) SHA-256 tekshiruvi ---------------------------------------------------
if [ -f "${ZAXIRA}.sha256" ]; then
    if sha256sum -c "${ZAXIRA}.sha256" >/dev/null 2>&1; then
        log "sha256 mos"
    else
        xato "sha256 MOS KELMADI — zaxira ozgargan yoki buzilgan"
    fi
else
    # CHECKSUMSIZ DUMP RAD ETILADI.
    #
    # Ilgari bu faqat OGOHLANTIRISH edi va tiklash davom etardi.
    # Lekin `backup.sh` sha256 ni dump MUVAFFAQIYATLI olingandan
    # KEYIN yozadi -- ya'ni `.sha256` ning yo'qligi "tekshirilmadi"
    # degani emas, "bu dump tugallanmagan" degani.
    #
    # O'LCHANGAN (2026-09-08): aynan shunday fayl (0 bayt, checksumsiz)
    # katalogda eng yangi bo'lib turardi.
    xato "sha256 fayli YO'Q: ${ZAXIRA}.sha256
   \`backup.sh\` checksumni dump TUGAGACH yozadi, ya'ni uning yo'qligi
   zaxira TUGALLANMAGANINI bildiradi. Bunday fayldan tiklash
   'zaxira bor' degan YOLG'ON ishonch berardi."
fi

# --- 3) Vaqtinchalik bazaga tiklash -----------------------------------------
tozala() {
    psql "$ADMIN_DSN" -q -c "DROP DATABASE IF EXISTS \"${SINOV_BAZA}\";" >/dev/null 2>&1 || true
}
trap tozala EXIT

tozala
psql "$ADMIN_DSN" -q -c "CREATE DATABASE \"${SINOV_BAZA}\";"
SINOV_DSN="$(printf '%s' "$XT_DB_DSN_OWNER" | sed "s/dbname=${ASOSIY_BAZA}/dbname=${SINOV_BAZA}/")"

log "tiklash boshlandi"
T0="$(date +%s)"
# `--no-owner`: rollar boshqacha bolishi mumkin.
# `-j 4`: parallel — RTO ni qisqartiradi.
# Xatolar YUTILMAYDI: chiqish kodi tekshiriladi.
if ! pg_restore --dbname="$SINOV_DSN" --no-owner --no-privileges -j 4 "$ZAXIRA" \
        > /tmp/restore.$$ 2>&1; then
    log "pg_restore chiqish kodi nolga teng emas; oxirgi qatorlar:"
    tail -20 /tmp/restore.$$ || true
    rm -f /tmp/restore.$$
    xato "TIKLASH YIQILDI"
fi
rm -f /tmp/restore.$$
T1="$(date +%s)"
DAVOM=$((T1 - T0))
log "tiklandi: ${DAVOM} s  (RTO uchun haqiqiy raqam)"

# --- 4) TEKSHIRUVLAR — "tiklandi" degani "tori" degani emas ------------------
jadval() { psql "$SINOV_DSN" -Atqc "$1" 2>/dev/null || echo 0; }

N_JADVAL="$(jadval "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")"
N_TENDER="$(jadval "SELECT count(*) FROM tender")"
N_CHUNK="$(jadval "SELECT count(*) FROM doc_chunk")"
N_MIGR="$(jadval "SELECT count(*) FROM schema_migration WHERE holat IN ('ok','bootstrap')")"

log "tekshiruv: jadval=$N_JADVAL  tender=$N_TENDER  bolak=$N_CHUNK  migratsiya=$N_MIGR"

muammo=0
[ "$N_JADVAL" -ge 40 ] || { log "XATO: jadval soni juda kam ($N_JADVAL)"; muammo=1; }
[ "$N_TENDER" -ge 1 ]  || { log "XATO: tender jadvali bosh"; muammo=1; }
[ "$N_MIGR"   -ge 1 ]  || { log "XATO: migratsiya jurnali bosh"; muammo=1; }

# pgvector kengaytmasi tiklandimi — usiz semantik qidiruv olmaydi.
N_VEC="$(jadval "SELECT count(*) FROM pg_extension WHERE extname='vector'")"
[ "$N_VEC" = "1" ] || { log "XATO: pgvector kengaytmasi tiklanmadi"; muammo=1; }

# --- YUKLANGAN FAYLLAR — BAZA YOLG'IZ YETARLI EMAS --------------------------
#
# `yuklama` jadvali tiklanadi, lekin FIZIK FAYL diskda. Ikkisi ajralib
# qolsa tizim eng yomon shaklda buziladi: interfeys hujjatni "bor"
# deb ko'rsatadi, foydalanuvchi bosadi va FAYL TOPILMAYDI. Bu faqat
# bosilganda bilinadi — ya'ni tiklashdan keyin ham UZOQ vaqt
# ko'rinmasligi mumkin.
#
# Shuning uchun mashq FAYL ARXIVINI ham tekshiradi. Arxiv nomi baza
# dump'i bilan AYNI shtamp bo'yicha topiladi.
FAYL_ARXIV="${ZAXIRA%.dump}-fayllar.tar.gz"
N_YUKLAMA="$(jadval "SELECT count(*) FROM yuklama WHERE arxiv_at IS NULL")"
if [ "$N_YUKLAMA" -gt 0 ]; then
    if [ ! -f "$FAYL_ARXIV" ]; then
        log "XATO: bazada $N_YUKLAMA ta faol yuklama bor, FAYL ARXIVI yo'q"
        log "  ($FAYL_ARXIV). Tiklangan tizimda hujjatlar OCHILMAYDI."
        muammo=1
    else
        if [ -f "${FAYL_ARXIV}.sha256" ]            && ! sha256sum -c "${FAYL_ARXIV}.sha256" >/dev/null 2>&1; then
            log "XATO: fayl arxivi sha256 MOS KELMADI"
            muammo=1
        fi
        N_FAYL="$(tar -tzf "$FAYL_ARXIV" 2>/dev/null | grep -cv '/$' || echo 0)"
        log "fayl arxivi: $N_FAYL ta fayl, bazada $N_YUKLAMA ta yozuv"
        # ANIQ TENGLIK TALAB QILINMAYDI: arxiv olingandan keyin yangi
        # fayl yuklangan bo'lishi mumkin va bu NORMAL. Lekin BO'SH
        # arxiv — aniq nuqson.
        [ "$N_FAYL" -gt 0 ] || {
            log "XATO: fayl arxivi BO'SH"; muammo=1; }
    fi
else
    log "yuklangan fayl yo'q — fayl arxivi tekshirilmadi"
fi

if [ "$muammo" -ne 0 ]; then
    xato "TIKLASH MASHQI OTMADI"
fi

# --- TIKLASH ISBOTI — MASHINA O'QIYDIGAN DALIL -------------------------------
# NEGA KERAK. "Tiklash mashqi bor" degan xulosa jurnalda qoladi va
# jurnalni hech kim o'qimaydi. Joylashtirishdan oldingi tekshiruv
# esa DALIL so'rashi kerak: mashq HAQIQATAN yurganmi, QACHON, va
# u ZAXIRANING QAYSI nusxasidan olinganmi.
#
# `uzoq=` maydoni ATAYLAB ajratilgan. Mahalliy diskdagi nusxadan
# tiklash mexanizmni isbotlaydi, LEKIN "disk yo'qolsa tiklanadi"
# degan da'voni isbotlamaydi. Ikkinchisi uchun tiklash UZOQ
# nusxadan olinishi kerak. Ishlab chiqarish tekshiruvi aynan shuni
# talab qiladi (`oldindan-tekshir.sh`).
ISBOT="${KATALOG:-$(dirname "$ZAXIRA")}/.tiklash-isboti"
{
    echo "# tenderai tiklash isboti v1"
    echo "sana=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "muhit=${MUHIT}"
    echo "zaxira=$(basename "$ZAXIRA")"
    echo "zaxira_sha256=$(sha256sum "$ZAXIRA" | cut -d' ' -f1)"
    echo "rto_s=${DAVOM}"
    echo "jadval=${N_JADVAL}"
    echo "migratsiya=${N_MIGR}"
    # MANBA: mahalliy nusxami yoki uzoqdan olib kelinganmi.
    # `TIKLASH_MANBA=uzoq` ni faqat uzoq nusxadan tiklaydigan
    # yo'l qo'yadi -- bu skript o'zi TAXMIN QILMAYDI.
    echo "uzoq=$([ "${TIKLASH_MANBA:-mahalliy}" = "uzoq" ] && echo ha || echo mahalliy)"
    # PROVENANS: qayerdan, qaysi backend, qaysi provayder va
    # QAYSI obyekt kalitlaridan. "Uzoqdan tiklandi" degan yozuv
    # tekshirib bo'lmaydigan bo'lsa u dalil emas.
    echo "manba=${TIKLASH_MANBA:-mahalliy}"
    echo "backend=${TIKLASH_BACKEND:--}"
    echo "provayder=${TIKLASH_PROVAYDER:--}"
    echo "obyekt_kalitlari=${TIKLASH_OBYEKTLAR:--}"
    # Bu nuqtaga FAQAT sha256 mos kelgan va tiklash o'tgan
    # holatda yetib kelinadi -- ya'ni `ok` o'lchovga asoslangan.
    echo "checksum=ok"
    echo "reliz_sha=$(sed -n '2s/^# sha: *//p' \
        "$(readlink -f "${ILDIZ:-/opt/tenderai/$MUHIT}/current" 2>/dev/null)/.kuzatilgan-manifest" \
        2>/dev/null || echo '-')"
} > "$ISBOT"
chmod 640 "$ISBOT" 2>/dev/null || true
# JURNAL FAYL BILAN BIR XIL AYTSIN. Ilgari bu yerda XOM
# `TIKLASH_MANBA` bosilardi va jurnalda `uzoq=uzoq` chiqib,
# faylda esa `uzoq=ha` turardi -- ikki xil so'z, bitta narsa.
log "tiklash isboti yozildi: $ISBOT (manba=${TIKLASH_MANBA:-mahalliy}, uzoq=$([ "${TIKLASH_MANBA:-mahalliy}" = "uzoq" ] && echo ha || echo mahalliy))"

log "TIKLASH MASHQI OTDI. RTO=${DAVOM}s, zaxira=$(basename "$ZAXIRA")"
