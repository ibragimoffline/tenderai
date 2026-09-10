#!/usr/bin/env bash
# =============================================================================
# UZOQDAN TIKLASH MASHQI — zaxira B2 dan QAYTARIB OLINADI
# =============================================================================
#     uzoqdan-tiklash.sh <staging|production>
#
# NEGA MAHALLIY NUSXA YARAMAYDI. Mahalliy fayldan tiklash mexanizmni
# isbotlaydi, lekin "disk yo'qolsa tiklanadi" degan da'voni
# ISBOTLAMAYDI -- aynan o'sha disk yo'qolganda mahalliy fayl ham
# yo'q bo'ladi. Shuning uchun bu yerda artefakt UZOQDAN olib
# kelinadi va tiklash AYNAN o'sha nusxadan yuriladi.
#
# O'QISH O'RAMA ORQALI. `rclone` bu yerda to'g'ridan chaqirilmaydi:
# kalitlar `tender-backup-remote` da, va ikkinchi sir ishlovchisi
# yasash -- ikkinchi xatar. O'rama tor, yopiq amallar beradi
# (`--royxat`, `--olib-kel`).
#
# AJRATILGAN JOY. Yuklab olingan fayl faqat `/var/tmp/tenderai-tiklash`
# ostiga tushadi -- zaxira katalogiga emas, reliz daraxtiga emas.
# Tiklash esa ALOHIDA sinov bazasiga boradi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: uzoqdan-tiklash.sh <staging|production>}"
case "$MUHIT" in staging|production) ;; *) echo "Noma'lum muhit: $MUHIT" >&2; exit 2 ;; esac
[ "$(id -u)" = "0" ] || { echo "root kerak" >&2; exit 1; }

ORAMA="${TENDER_BACKUP_ORAMA:-/usr/local/sbin/tender-backup-remote}"
ILDIZ="${TENDER_TIKLASH_ILDIZ:-/var/tmp/tenderai-tiklash}"
TIKLASH_SKRIPT="${TIKLASH_SKRIPT:-$(dirname "$0")/restore-test.sh}"

[ -x "$ORAMA" ] || { echo "o'rama yo'q: $ORAMA" >&2; exit 1; }
[ -x "$TIKLASH_SKRIPT" ] || { echo "restore-test.sh yo'q: $TIKLASH_SKRIPT" >&2; exit 1; }

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
xato() { printf '[%s] XATO: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

install -d -m 0700 -o root -g root "$ILDIZ"
ISH="$(mktemp -d "${ILDIZ}/mashq.XXXXXX")"
chmod 700 "$ISH"
trap 'rm -rf "$ISH"' EXIT

echo "=============================================================="
echo "UZOQDAN TIKLASH MASHQI — ${MUHIT}"
echo "  ajratilgan joy: $ISH"
echo "=============================================================="

# --- 1) UZOQDAGI ENG OXIRGI DUMP ----------------------------------------------
# Kalitlar `<tur>/YYYY/MM/DD/<nom>` shaklida, ya'ni matn bo'yicha
# saralash SANA bo'yicha saralash bilan bir xil.
log "uzoqdagi ro'yxat o'qilmoqda"
DB_YOL="$("$ORAMA" --royxat "$MUHIT" db 2>/dev/null | grep -E '\.dump$' | sort | tail -1 || true)"
[ -n "$DB_YOL" ] || xato "uzoqda dump topilmadi — avval zaxira yuborilganmi?"
DB_NOM="$(basename "$DB_YOL")"
ASOS="${DB_NOM%.dump}"
log "topildi: $DB_NOM"

# --- 2) OLIB KELAMIZ ----------------------------------------------------------
olib() {
    local tur="$1" nom="$2" majburiy="$3"
    if "$ORAMA" --olib-kel "$MUHIT" "$tur" "$nom" "$ISH" >/dev/null 2>&1; then
        log "  olindi: $nom"
        return 0
    fi
    [ "$majburiy" = "ha" ] && xato "olib kelinmadi (majburiy): $tur/$nom"
    log "  yo'q: $nom (ixtiyoriy)"
    return 1
}
log "uzoqdan olib kelinmoqda"
olib db        "$DB_NOM"                  ha
olib checksums "${DB_NOM}.sha256"         ha
ARXIV_NOM="${ASOS}-fayllar.tar.gz"
ARXIV_BOR=0
olib uploads   "$ARXIV_NOM"               yoq && ARXIV_BOR=1
[ "$ARXIV_BOR" = "1" ] && olib checksums "${ARXIV_NOM}.sha256" ha || true
for m in "${ASOS}-meta.json" "${ASOS}-meta.txt"; do
    olib meta "$m" yoq && break || true
done

# --- 3) BUTUNLIK — UZOQDAN KELGAN CHECKSUM BILAN ------------------------------
# Checksum fayli ham UZOQDAN keladi: mahalliy nusxadagi checksumga
# solishtirish "mahalliy fayl mahalliy checksumga mos" degan
# ma'nosiz xulosa bo'lardi.
tekshir() {
    local f="$1"
    local kutilgan hozirgi
    kutilgan="$(cut -d' ' -f1 < "${ISH}/${f}.sha256")"
    hozirgi="$(sha256sum "${ISH}/${f}" | cut -d' ' -f1)"
    [ "$kutilgan" = "$hozirgi" ] || xato "CHECKSUM MOS EMAS: $f
   uzoqdagi checksum: $kutilgan
   olingan fayl     : $hozirgi"
    log "  checksum mos: $f (${hozirgi:0:16}…)"
}
log "butunlik tekshirilmoqda"
tekshir "$DB_NOM"
[ "$ARXIV_BOR" = "1" ] && tekshir "$ARXIV_NOM" || true

# --- 4) TIKLASH — AJRATILGAN BAZAGA -------------------------------------------
# `restore-test.sh` ALOHIDA sinov bazasi yasaydi va uni o'zi
# tozalaydi. Staging va production bazalariga TEGILMAYDI.
OBYEKTLAR="db/${DB_YOL}"
[ "$ARXIV_BOR" = "1" ] && OBYEKTLAR="${OBYEKTLAR},uploads/${ARXIV_NOM}"
log "tiklash mashqi boshlanmoqda (manba: UZOQ)"
TIKLASH_ZAXIRA="${ISH}/${DB_NOM}" \
TIKLASH_MANBA="uzoq" \
TIKLASH_BACKEND="s3" \
TIKLASH_PROVAYDER="backblaze-b2" \
TIKLASH_OBYEKTLAR="$OBYEKTLAR" \
    "$TIKLASH_SKRIPT" "$MUHIT"

echo
echo "=============================================================="
echo "UZOQDAN TIKLASH MASHQI O'TDI"
echo "  manba    : UZOQ (s3 / backblaze-b2)"
echo "  zaxira   : $DB_NOM"
echo "  obyektlar: $OBYEKTLAR"
echo "=============================================================="
