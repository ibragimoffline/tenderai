#!/usr/bin/env bash
# =============================================================================
# Tender AI — RELIZ DARVOZASI
# =============================================================================
#     relis-darvoza.sh [ildiz]
#
# Reliz shu darvozadan o'tmasa CHIQMAYDI. Darvoza YIQILADI, agar:
#
#   1. talab qilingan backend to'plamlaridan BIRORTASI yiqilsa;
#   2. frontend qurilishi (yoki tip tekshiruvi) yiqilsa;
#   3. to'plam UMUMAN BAJARILMASA (eng xavflisi — pastga qarang);
#   4. migratsiya butunligi tekshiruvi yiqilsa.
#
# NEGA "BAJARILMADI" ALOHIDA HOLAT
# --------------------------------
# Yiqilgan sinov KO'RINADI. Bajarilmagan sinov esa "0 yiqildi" bo'lib
# ko'rinadi va aynan shu sababli xavfliroq: darvoza yashil, tekshiruv
# esa yo'q. Loyihada bu ALLAQACHON sodir bo'lgan — `run_tests.py`
# izohida yozilgani kabi, `import_test` kodlash xatosi tufayli 143 ta
# tekshiruvni BAJARMASDAN yiqilardi va buni hech kim payqamagan.
#
# Shuning uchun bu yerda chiqish kodiga ISHONILMAYDI: xulosa qatori
# O'QILADI va to'plamlar SONI kutilgan chegaradan past bo'lsa darvoza
# yopiladi. "Hech narsa yurmadi" holati "hammasi o'tdi" bo'lib
# o'tolmaydi.
#
# CI da ham, `deploy.sh` ichida ham shu bitta skript chaqiriladi —
# ikki xil "haqiqat" bo'lmasin.
# =============================================================================
set -euo pipefail

ILDIZ="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ILDIZ"

#: Kutilgan eng kam to'plam soni. Yangi to'plam qo'shilsa OSHIRILADI.
#: Pasaysa — demak nimadir yurmay qolgan va buni bilish kerak.
KUTILGAN="${TENDERAI_KUTILGAN_TOPLAM:-35}"

#: Python: joylashtirishda virtual muhit, mahalliyda tizimdagisi.
PY="${TENDERAI_PY:-}"
if [ -z "$PY" ]; then
    if   [ -x "${ILDIZ}/.venv/bin/python" ];       then PY="${ILDIZ}/.venv/bin/python"
    elif [ -x "${ILDIZ}/.venv/Scripts/python.exe" ]; then PY="${ILDIZ}/.venv/Scripts/python.exe"
    elif command -v python3 >/dev/null 2>&1;        then PY="python3"
    else PY="python"
    fi
fi

log()  { printf '[darvoza] %s\n' "$*"; }
xato() { printf '[darvoza] YIQILDI: %s\n' "$*" >&2; exit 1; }

log "ildiz : $ILDIZ"
log "python: $PY"

# --- 1) BACKEND TO'PLAMLARI --------------------------------------------------
# Chiqish faylga yoziladi: xulosa qatorini O'QIYMIZ, chunki chiqish
# kodining o'zi "bajarildimi" degan savolga javob bermaydi.
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

log "backend sinovlari yuritilmoqda (bu bir necha daqiqa)…"
set +e
"$PY" run_tests.py >"$LOG" 2>&1
KOD=$?
set -e

XULOSA="$(grep -E '^JAMI: [0-9]+ to.plam' "$LOG" | tail -1 || true)"
if [ -z "$XULOSA" ]; then
    tail -30 "$LOG" >&2
    xato "xulosa qatori yo'q — to'plam UMUMAN BAJARILMADI (chiqish kodi $KOD)"
fi

JAMI="$(printf '%s' "$XULOSA"   | sed -E 's/^JAMI: ([0-9]+).*/\1/')"
YIQILGAN="$(printf '%s' "$XULOSA" | sed -E 's/.*o.tdi, ([0-9]+) yiqildi.*/\1/')"
# Yiqilgan bo'lmasa yurgizuvchi bu qismni chop etmaydi -> raqam chiqmaydi.
case "$YIQILGAN" in ''|*[!0-9]*) YIQILGAN=0 ;; esac

log "xulosa: $XULOSA"

[ "$JAMI" -ge "$KUTILGAN" ] || {
    tail -30 "$LOG" >&2
    xato "faqat $JAMI to'plam yurdi, kutilgan >= $KUTILGAN — qolgani BAJARILMADI"
}
[ "$YIQILGAN" -eq 0 ] || {
    grep -E '^\s*\[XATO\]|^YIQILGAN:' "$LOG" >&2 || true
    xato "$YIQILGAN ta to'plam yiqildi"
}
[ "$KOD" -eq 0 ] || {
    tail -30 "$LOG" >&2
    xato "run_tests.py chiqish kodi $KOD"
}
log "backend: $JAMI to'plam, 0 yiqildi"

# --- 2) FRONTEND: TIP, BIRLIK SINOVLARI, QURILISH ----------------------------
# `test:colors` ATAYIN alohida chaqiriladi: u `typecheck` skriptiga
# kirmaydi va shu sababli hech qachon avtomatik yurmasdi.
log "frontend: tip tekshiruvi va birlik sinovlari"
( cd frontend && npm run typecheck )  || xato "frontend tip tekshiruvi/sinovlari"
( cd frontend && npm run test:colors ) || xato "frontend rang sinovlari"

# QURISHNI O'TKAZIB YUBORISH — FAQAT `deploy.sh` uchun.
# U darvozadan OLDIN frontendni ishlab chiqarish sozlamasi
# (`.env.production`) bilan allaqachon quradi va `dist/` ni tekshiradi.
# Ikkinchi marta qurish shu qiymatni takrorlardi, xolos.
# Standart — QURILADI: CI da va qo'lda yurgizishda darvoza to'liq.
if [ "${TENDERAI_DARVOZA_FRONTEND:-1}" = "0" ]; then
    log "frontend: qurilish o'tkazib yuborildi (deploy.sh o'zi qurdi)"
else
    log "frontend: ishlab chiqarish qurilishi"
    ( cd frontend && npm run build ) || xato "frontend qurilishi"
fi

# --- 3) MIGRATSIYA BUTUNLIGI -------------------------------------------------
# DSN bo'lmasa STATIK butunlik (manifest, checksum, fayllar) baribir
# tekshiriladi — u bazasiz ham ma'noli va aynan "diskda bor, manifestda
# yo'q" nuqsonini ushlaydi.
log "migratsiya butunligi"
if [ -n "${XT_DB_DSN_OWNER:-}" ]; then
    "$PY" migratsiya.py --tekshir --dsn "$XT_DB_DSN_OWNER" \
        || xato "migratsiya butunligi (baza bilan)"
else
    "$PY" migratsiya.py --tekshir || xato "migratsiya butunligi (statik)"
fi

log "HAMMA TEKSHIRUV O'TDI — reliz chiqishi mumkin"
