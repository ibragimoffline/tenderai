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
# DSN MAJBURIY. Ilgari bu yerda "DSN bo'lmasa STATIK butunlik baribir
# tekshiriladi" deb yozilgan va `else` shoxi `migratsiya.py --tekshir`
# ni DSN siz chaqirardi.
#
# DA'VO YOLG'ON EDI (o'lchandi 2026-09-07):
#
#     $ python migratsiya.py --tekshir
#     XT_DB_DSN o'rnatilmagan (.env ni tekshiring)     -> kod 1
#
# `migratsiya.py` da statik rejim UMUMAN yo'q: `main()` har qanday
# holatda `Jurnal(dsn)` quradi va u `psycopg2` ni import qiladi.
# Ya'ni "statik tekshiruv o'tdi" degan xabar HECH QACHON chiqmagan;
# `else` shoxiga tushgan yurish shunchaki tushunarsiz xato bilan
# yiqilardi va sabab "migratsiya butunligi (statik)" deb ko'rinardi.
#
# NEGA YECHIM "STATIK REJIM QO'SHISH" EMAS. Darvozaning vazifasi --
# bazadagi holat repozitoriydagi matnga MOS ekanini tasdiqlash.
# Faylni faylning o'zi bilan solishtirish bu savolga javob bermaydi.
# Ya'ni statik rejim bo'lganda ham u DARVOZA uchun yetarli bo'lmasdi.
#
# Shuning uchun: DSN bo'lmasa darvoza YIQILADI va NIMA yetishmayotgani
# aytiladi. "Tekshirdim" deb yolg'on aytmaydi.
log "migratsiya butunligi"
DSN_M="${XT_DB_DSN_OWNER:-${XT_DB_DSN:-}}"
[ -n "$DSN_M" ] || xato "migratsiya butunligi TEKSHIRILMADI: XT_DB_DSN_OWNER
   ham, XT_DB_DSN ham yo'q. Bu 'o'tdi' EMAS — o'lchanmagan.
   \`deploy.sh\` muhit faylini 4-bo'limda o'qiydi; darvoza qo'lda
   yurgizilsa DSN ni muhitda bering."
"$PY" migratsiya.py --tekshir --dsn "$DSN_M" \
    || xato "migratsiya butunligi"

log "HAMMA TEKSHIRUV O'TDI — reliz chiqishi mumkin"
