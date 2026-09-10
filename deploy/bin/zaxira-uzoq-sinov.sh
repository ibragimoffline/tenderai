#!/usr/bin/env bash
# =============================================================================
# TASHQI ZAXIRA — ULANISH ZONDI
# =============================================================================
#     zaxira-uzoq-sinov.sh <staging|production>
#
# NEGA KERAK. Ishlab chiqarish bazasining dumpini birinchi marta
# yuborib, keyin "ishladimi?" deb qarash noto'g'ri tartib: nosozlik
# 25 MB o'tkazmadan KEYIN, va ehtimol yarim yuklangan obyekt bilan
# chiqardi. Avval SHARTNOMA sinaladi, keyin ma'lumot yuboriladi.
#
# NIMA SINALADI (uchidan-uchiga, HAQIQIY yo'l bilan):
#   * TLS ulanish va endpoint;
#   * chelak yetib boradimi va kalit yozishga ruxsat beradimi;
#   * obyekt QAYTA O'QILADIMI (tiklash uchun shart);
#   * qaytib kelgan baytlarning sha256 i mahalliy bilan TENGMI.
#
# YON KANAL ISHLATILMAYDI. Zond aynan `tender-backup-remote`
# orqali yuboriladi -- kalitlar, kalit sxemasi va butunlik
# tekshiruvi zaxira yo'li bilan BIR XIL bo'lsin. `rclone` ni
# to'g'ridan chaqirib sinash "boshqa narsani" isbotlardi.
#
# ZOND KICHIK va MAZMUNSIZ: tasodifiy o'n olti bayt. Hech qanday
# ishlab chiqarish ma'lumoti yuborilmaydi.
#
# UZOQDAGI ZOND O'CHIRILMAYDI: ilova kalitida `Delete` huquqi
# ATAYLAB yo'q. U bir necha o'nlab bayt va lifecycle qoidasi uni
# o'z vaqtida oladi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: zaxira-uzoq-sinov.sh <staging|production> [--sozlama]}"
case "$MUHIT" in staging|production) ;; *) echo "Noma'lum muhit: $MUHIT" >&2; exit 2 ;; esac
[ "$(id -u)" = "0" ] || { echo "root kerak" >&2; exit 1; }

# --- `--sozlama`: FAQAT TO'LDIRILGANLIGINI aytadi ----------------------------
# NEGA ALOHIDA REJIM. Sozlama fayli `0600 root:root` va uni
# ko'rish uchun root bo'lish kerak. Lekin "to'ldirilganmi?" degan
# savolga javob berish uchun QIYMATLARNI ko'rish SHART EMAS --
# faqat bo'sh yoki bo'sh emasligi.
#
# Bu farq muhim: sozlashda yordam berayotgan odam (yoki asbob)
# qiymatlarni KO'RMASLIGI kerak. Chiqishda maydon NOMI va
# `ha`/`yo'q` dan boshqa hech narsa yo'q.
if [ "${2:-}" = "--sozlama" ]; then
    SZ="${TENDER_BACKUP_REMOTE_CONF:-/etc/tenderai/backup-remote.conf}"
    if [ ! -f "$SZ" ]; then
        echo "sozlama_fayli=YO'Q ($SZ)"
        exit 1
    fi
    echo "sozlama_fayli   : $SZ"
    echo "egasi/rejim     : $(stat -c '%U:%G %a' "$SZ")"
    set -a
    # shellcheck disable=SC1090
    . "$SZ"
    set +a
    YETISHMAYDI=0
    # NAMUNA QIYMATI TO'LDIRILGAN EMAS.
    #
    # O'LCHANGAN YOLG'ON YASHIL (2026-09-10). Sozlama fayli namunadan
    # nusxa qilib o'rnatilgan edi va uning ichida `zaxira.example.uz`
    # kabi o'rin-egalari turardi. Asbob "bo'sh emas" deb sanadi va
    # `sozlama TO'LIQ` dedi -- ya'ni namunani sozlama deb ko'rsatdi.
    #
    # "Bo'sh emas" va "to'ldirilgan" -- ikki xil narsa. Loyihaning
    # `oldindan-tekshir.sh` i buni allaqachon biladi (`password=REPLACE`,
    # `example.uz`); shu qoida bu yerga ham keltirildi.
    namuna_mi() {
        case "$1" in
            *example.uz*|*example.com*|*EXAMPLE*) return 0 ;;
            "<"*">"|*REPLACE*|*"o'rin-egasi"*)     return 0 ;;
        esac
        return 1
    }
    bor() {
        eval "v=\${${1}:-}"
        if [ -z "$v" ]; then
            echo "${2}=yo'q"; YETISHMAYDI=$((YETISHMAYDI+1))
        elif namuna_mi "$v"; then
            echo "${2}=NAMUNA"; YETISHMAYDI=$((YETISHMAYDI+1))
        else
            echo "${2}=ha"
        fi
    }
    # FAYL YO'LI UCHUN: mavjudligi ham tekshiriladi. Yo'l yozilgani
    # fayl BORLIGINI anglatmaydi va kalit yo'q bo'lsa zond baribir
    # yiqilardi -- buni oldinroq bilish arzonroq.
    bor_fayl() {
        eval "v=\${${1}:-}"
        if [ -z "$v" ]; then
            echo "${2}=yo'q"; YETISHMAYDI=$((YETISHMAYDI+1))
        elif namuna_mi "$v"; then
            echo "${2}=NAMUNA"; YETISHMAYDI=$((YETISHMAYDI+1))
        elif [ ! -f "$v" ]; then
            echo "${2}=FAYL_YO'Q"; YETISHMAYDI=$((YETISHMAYDI+1))
        else
            echo "${2}=ha"
        fi
    }
    echo "usul            : ${USUL:-(berilmagan -> ssh)}"
    if [ "${USUL:-ssh}" = "s3" ]; then
        bor S3_ENDPOINT          endpoint_present
        bor S3_REGION            region_present
        bor S3_BUCKET            bucket_present
        bor S3_PREFIX            prefix_present
        bor S3_ACCESS_KEY_ID     access_key_present
        bor S3_SECRET_ACCESS_KEY secret_key_present
        # ENDPOINT SHAKLI — QIYMATSIZ. HTTPS emasligi sozlash
        # xatosi va uni zonddan OLDIN bilish arzonroq.
        case "${S3_ENDPOINT:-}" in
            https://*) echo "endpoint_https=ha" ;;
            "")        echo "endpoint_https=(berilmagan)" ;;
            *)         echo "endpoint_https=YO'Q"; YETISHMAYDI=$((YETISHMAYDI+1)) ;;
        esac
    else
        bor UZOQ_HOST  host_present
        bor UZOQ_USER  user_present
        bor UZOQ_YOL   yol_present
        bor_fayl SSH_KALIT kalit_present
    fi
    echo
    if [ "$YETISHMAYDI" -eq 0 ]; then
        echo "NATIJA: sozlama TO'LIQ"
        exit 0
    fi
    echo "NATIJA: ${YETISHMAYDI} ta maydon yetishmaydi"
    exit 1
fi

ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
ORAMA="${TENDER_BACKUP_ORAMA:-/usr/local/sbin/tender-backup-remote}"
[ -f "$ENVFILE" ] || { echo "muhit fayli yo'q: $ENVFILE" >&2; exit 1; }
[ -x "$ORAMA" ] || { echo "o'rama yo'q yoki bajarilmaydi: $ORAMA" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a
if [ -z "${BACKUP_REMOTE_CMD:-}" ]; then
    echo "XATO: BACKUP_REMOTE_CMD bo'sh ($ENVFILE) — tashqi manzil sozlanmagan." >&2
    exit 1
fi

KATALOG="${BACKUP_DIR:-/var/backups/tenderai}/${MUHIT}"
[ -d "$KATALOG" ] || { echo "zaxira katalogi yo'q: $KATALOG" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
ZOND="${KATALOG}/tenderai-${MUHIT}-${STAMP}-zond.txt"
umask 077
head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$ZOND"
trap 'rm -f "$ZOND"' EXIT
SHA="$(sha256sum "$ZOND" | cut -d' ' -f1)"

echo "=============================================================="
echo "TASHQI ZAXIRA ZONDI — ${MUHIT}"
echo "  zond   : $(basename "$ZOND") ($(wc -c < "$ZOND") bayt)"
echo "  sha256 : ${SHA:0:16}…"
echo "=============================================================="

# O'RAMA SHABLONDAGIDEK chaqiriladi: `{fayl}` alohida argument.
# Qobiq ishtirok etmaydi.
ARGV=()
TOPILDI=0
for soz in $BACKUP_REMOTE_CMD; do
    if [ "$soz" = "{fayl}" ]; then ARGV+=("$ZOND"); TOPILDI=1; else ARGV+=("$soz"); fi
done
[ "$TOPILDI" = "1" ] || { echo "XATO: BACKUP_REMOTE_CMD da mustaqil \`{fayl}\` yo'q" >&2; exit 1; }

if "${ARGV[@]}"; then
    echo
    echo "NATIJA: ZOND O'TDI — TLS, chelak, yozish va QAYTA O'QISH ishlaydi."
    echo "  Uzoqdagi zond obyekti QOLADI (kalitda \`Delete\` ataylab yo'q)."
    exit 0
fi
echo
echo "NATIJA: ZOND YIQILDI — yuqoridagi xabarga qarang." >&2
echo "  Ishlab chiqarish dumpini YUBORMANG: avval shartnomani tuzating." >&2
exit 1
