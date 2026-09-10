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

MUHIT="${1:?foydalanish: zaxira-uzoq-sinov.sh <staging|production>}"
case "$MUHIT" in staging|production) ;; *) echo "Noma'lum muhit: $MUHIT" >&2; exit 2 ;; esac
[ "$(id -u)" = "0" ] || { echo "root kerak" >&2; exit 1; }

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
