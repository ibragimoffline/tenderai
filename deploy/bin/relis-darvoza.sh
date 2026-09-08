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

# --- REKURSIYA QO'RIQCHASI — CHUQURLIK HISOBLAGICHI -------------------------
# O'LCHANGAN NUQSON (2026-09-08): darvoza o'z-o'zini cheksiz
# chaqirdi. Halqa quyidagicha yopildi:
#
#     relis-darvoza.sh -> run_tests.py -> deploy_test.py
#         -> relis-darvoza.sh -> ...
#
# `deploy_test` ning bir mashqi darvozani ATAYLAB soxta ildiz bilan
# yurgizadi. Lekin `darvoza-baza.sh` ning `darvoza_ildiz()` funksiyasi
# ildizni "yetarli emas" deb topsa va muhitda `RELEASE_SHA` bo'lsa,
# repozitoriydan TO'LIQ daraxtni ochib HAQIQIY `run_tests.py` ni
# yurgizadi -- ya'ni mashq jimgina to'liq darvozaga aylanadi.
#
# NATIJA: 66 jarayon, ~2460 MB RSS. Xost xotirasi tugadi va
# `tenderai-api@production` `oom-kill` bilan yiqildi -- `zynq.uz/api`
# 502 qaytardi. Sinov infratuzilmasi ishlab chiqarishni o'chirdi.
#
# NEGA CHUQURLIK 2 GA RUXSAT: 1 -- haqiqiy darvoza, 2 -- `deploy_test`
# ning nazorat ostidagi mashqi (u soxta ildiz bilan yuradi va o'zi
# rekursiya yasay olmaydi). 3 esa boshqa hech narsani anglatmaydi --
# faqat halqani.
#
# Bu OXIRGI to'siq. Undan oldin ikkita bor: mashq ildizi endi
# `_yetarli` va mashq muhitidan `RELEASE_SHA` olib tashlanadi.
DARVOZA_CHUQURLIK=$(( ${TENDERAI_DARVOZA_CHUQURLIK:-0} + 1 ))
if [ "$DARVOZA_CHUQURLIK" -gt 2 ]; then
    echo "XATO: reliz darvozasi O'Z ICHIDA qayta chaqirildi (chuqurlik $DARVOZA_CHUQURLIK)." >&2
    echo "      Bu halqa: darvoza -> run_tests -> deploy_test -> darvoza." >&2
    echo "      2026-09-08 da u xostni OOM ga olib keldi." >&2
    exit 1
fi
export TENDERAI_DARVOZA_CHUQURLIK="$DARVOZA_CHUQURLIK"

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
# KUZATILGAN FAYLLAR MANIFESTI — sinovlardan OLDIN.
# O'LCHANGAN NUQSON (2026-09-09): manifest faqat `darvoza-baza.sh
# sinov` ga ulangan edi. Reliz yo'li `relis-darvoza.sh` ni TO'G'RIDAN
# chaqiradi, ya'ni u yerda manifest YO'Q edi -- `xavfsizlik_test`
# fail-closed qoidasi bo'yicha QIZIL berdi va reliz to'xtadi.
# Siyosat to'g'ri ishladi; manifest noto'g'ri joyda edi.
MANIFEST="${ILDIZ}/.kuzatilgan-manifest"
if [ -n "${RELEASE_SHA:-}" ]; then
    if _n="$("${ILDIZ}/deploy/bin/kuzatilgan-manifest.sh" \
                "$RELEASE_SHA" "$MANIFEST" 2>&1)"; then
        log "kuzatilgan manifest: ${_n} fayl"
    else
        log "OGOH: manifest yasalmadi (${_n})"
    fi
else
    log "OGOH: RELEASE_SHA yo'q — manifest yasalmadi"
fi

TENDERAI_TRACKED_MANIFEST="$MANIFEST" RELEASE_SHA="${RELEASE_SHA:-}" \
    "$PY" run_tests.py >"$LOG" 2>&1
KOD=$?
set -e

# NAQSH IKKI FORMATNI HAM OLADI va bu O'LCHANGAN SABABGA ega.
#
# `run_tests.py` xulosani "JAMI: 44/44 to'plam yurdi, ..." shaklida
# chop etadi. Eski naqsh `^JAMI: [0-9]+ to.plam` esa raqamdan KEYIN
# darhol bo'shliq kutardi va `44/44` ga MOS KELMASDI.
#
# O'LCHANGAN OQIBAT (2026-09-07, staging joylashtiruvi): 44 to'plam
# HAQIQATAN yurdi va 35 tasi yiqildi, darvoza esa
#
#     "xulosa qatori yo'q — to'plam UMUMAN BAJARILMADI"
#
# dedi. Ya'ni darvozaning BUTUN maqsadi — "yurmadi" ni "yiqildi" dan
# ajratish — aynan shu joyda buzilgan edi: u to'g'ri to'sdi, lekin
# NOTO'G'RI sababni ko'rsatdi va operatorni yurgizuvchining o'zida
# nosozlik bor deb o'ylashga majbur qilardi.
#
# Darvoza to'sdi, demak zarar bo'lmadi — lekin "yashil bo'lib
# ko'ringan yolg'on" ning teskarisi ham xuddi shunday qimmat:
# QIZIL bo'lib ko'ringan YOLG'ON SABAB.
XULOSA="$(grep -E "^JAMI: [0-9]+(/[0-9]+)? to.plam" "$LOG" | tail -1 || true)"
if [ -z "$XULOSA" ]; then
    tail -30 "$LOG" >&2
    xato "xulosa qatori yo'q — to'plam UMUMAN BAJARILMADI (chiqish kodi $KOD)"
fi

# BIRINCHI raqam — YURGAN to'plamlar soni ("44/44" da ham, "44" da ham).
JAMI="$(printf '%s' "$XULOSA"   | sed -E "s@^JAMI: ([0-9]+).*@\\1@")"
YIQILGAN="$(printf '%s' "$XULOSA" | sed -E "s@.*o.tdi, ([0-9]+) yiqildi.*@\\1@")"
# Yiqilgan bo'lmasa yurgizuvchi bu qismni chop etmaydi -> raqam chiqmaydi.
case "$YIQILGAN" in ''|*[!0-9]*) YIQILGAN=0 ;; esac
case "$JAMI" in ''|*[!0-9]*)
    tail -30 "$LOG" >&2
    xato "xulosa qatorini O'QIB BO'LMADI: '$XULOSA'
   Bu 'o'tdi' EMAS — format o'zgargan bo'lsa naqsh ham yangilansin." ;;
esac

log "xulosa: $XULOSA"

[ "$JAMI" -ge "$KUTILGAN" ] || {
    tail -30 "$LOG" >&2
    xato "faqat $JAMI to'plam yurdi, kutilgan >= $KUTILGAN — qolgani BAJARILMADI"
}
# --- RELIZ QARORI — TOIFA BO'YICHA, SANOQ BO'YICHA EMAS ---------------------
# ILGARI shu yerda `[ "$YIQILGAN" -eq 0 ]` turardi. U ikkita butunlay
# boshqa narsani BIR XIL ko'rsatardi:
#
#     xavfsizlik regressiyasi   -> to'xtashi KERAK
#     korpusda hujjat yo'qligi  -> to'xtatish MA'NOSIZ
#
# Natijada darvoza doim qizil bo'lib qolardi, va doim qizil
# darvozaning yagona oqibati -- undan chetlab o'tishni o'rganish.
#
# QAROR JURNAL MATNIDAN CHIQARILMAYDI: `xulosa.json` (mashina o'qiydi)
# va `deploy/relis-tasnif.tsv` (ko'rib chiqilgan artefakt).
#
# FAIL CLOSED: tasnifi yo'q yiqilish, buzuq artefakt, yo'qolgan
# to'plam, takroriy natija yoki KRITIK to'plamning qizilligi -- har
# biri relizni TO'XTATADI. Kritik to'plamlar yorlig'idan qat'i nazar
# to'xtatadi: tasnif faylini inson yozadi.
if [ "$YIQILGAN" -ne 0 ]; then
    grep -E '^\s*\[XATO\]|^YIQILGAN:' "$LOG" >&2 || true
fi
_XULOSA_JSON="${ILDIZ}/_test_natija/xulosa.json"
_TASNIF="${ILDIZ}/deploy/relis-tasnif.tsv"
if ! "${PY:-python3}" "${ILDIZ}/deploy/bin/relis-qaror.py" \
        --xulosa "$_XULOSA_JSON" --tasnif "$_TASNIF" >&2; then
    xato "reliz qarori: TO'XTATILDI (yuqoridagi toifalarga qarang)"
fi
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
