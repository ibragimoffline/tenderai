#!/usr/bin/env bash
# =============================================================================
# Tender AI — joylashtirish (STAGING BIRINCHI)
# =============================================================================
#     deploy.sh staging    <git-ref>
#     deploy.sh production <git-ref>
#
# ISHLAB CHIQARISHGA TO'G'RIDAN-TO'G'RI JOYLASHTIRIB BO'LMAYDI: shu
# ref STAGING da tekshirilgan bo'lishi SHART. Tasdiq `.verified`
# faylida va uni shu skriptning O'ZI yozadi — staging joylashtiruvi
# sog'liq tekshiruvidan o'tgach.
#
# NEGA SIMVOLIK HAVOLA (`current`): orqaga qaytarish BITTA atomar
# amal bo'ladi (`ln -sfn`), ya'ni "qaytardim, lekin yarmi eski yarmi
# yangi" holati yuzaga kelmaydi.
#
# BU SKRIPTDA SIR YO'Q. Sirlar `/etc/tenderai/<muhit>.env` da va u
# repozitoriyaga tushmaydi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: deploy.sh <staging|production> <git-ref>}"
REF="${2:?git ref (tag yoki commit) kerak}"

case "$MUHIT" in
    staging|production) ;;
    *) echo "Noma'lum muhit: $MUHIT"; exit 2 ;;
esac

# MASHQ UCHUN YOL ALMASHTIRILADI. Sabab `TENDERAI_ENVFILE` dagi
# bilan AYNI: yol qotirilgan bolsa skriptni serverdan tashqarida
# UMUMAN yurgizib bolmaydi -- va aynan shuning uchun bu skript
# hech qachon BAJARILMAGAN edi, faqat OQILGAN edi.
#
# Standart qiymat ozgarmaydi. Ozgaruvchini qoya oladigan kishi
# allaqachon `tenderai` foydalanuvchisi sifatida qobiqda -- yani
# yangi imtiyoz berilmayapti.
ILDIZ="${TENDERAI_ILDIZ:-/opt/tenderai/${MUHIT}}"
RELIZLAR="${ILDIZ}/releases"
JORIY="${ILDIZ}/current"
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
REPO="${TENDERAI_REPO:-/opt/tenderai/repo.git}"

log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
xato_izoh() { printf '[%s] %s' "$(date '+%F %T')" "$*" >&2; echo >&2; }
xato() { printf '[%s] XATO: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

[ -f "$ENVFILE" ] || xato "muhit fayli yo'q: $ENVFILE"

# --- 0) SOZLAMA TEKSHIRUVI — QIMMAT QADAMLARDAN OLDIN ------------------------
# ENG BOSHIDA turishining sababi: to'ldirilmagan sozlama ilgari FAQAT
# 6-bo'limda (migratsiya) chiqardi, ya'ni `venv`, `npm ci` va frontend
# qurilmasidan KEYIN — ~4-5 daqiqa va yarim reliz katalogi.
#
# Undan ham yomoni: `example.uz` domeni bilan joylashtirish
# MUVAFFAQIYATLI tugardi va faqat bildirishnoma yuborilganda
# ma'lum bo'lardi.
#
# Skript RELIZDAN emas, DEPLOY.SH YONIDAN olinadi: bu qadam arxiv
# ochilishidan OLDIN yuradi.
BU_KATALOG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${BU_KATALOG}/oldindan-tekshir.sh" "$MUHIT" \
    || xato "sozlamada to'siq bor (yuqorida) — joylashtirish BOSHLANMADI"

# --- 1) ISHLAB CHIQARISH UCHUN STAGING TASDIQI SHART -------------------------
if [ "$MUHIT" = "production" ]; then
    TASDIQ="${TENDERAI_STAGING_ILDIZ:-/opt/tenderai/staging}/.verified"
    [ -f "$TASDIQ" ] || xato "staging tasdigi yoq ($TASDIQ). Avval: deploy.sh staging $REF"
    TASDIQLANGAN="$(cat "$TASDIQ")"
    if [ "$TASDIQLANGAN" != "$REF" ]; then
        xato "staging da BOSHQA ref tekshirilgan: '$TASDIQLANGAN' != '$REF'"
    fi
    log "staging tasdigi topildi: $REF"
fi

# --- 2) Yangi reliz katalogi -------------------------------------------------
STAMP="$(date +%Y%m%d-%H%M%S)"
TOZA_REF="$(printf '%s' "$REF" | tr -c 'A-Za-z0-9._-' '_' | cut -c1-24)"
YANGI="${RELIZLAR}/${STAMP}-${TOZA_REF}"
mkdir -p "$YANGI" "${ILDIZ}/var/hf" "${ILDIZ}/var/cache"
log "reliz: $YANGI"

# YIQILSA YARIM RELIZ QOLMASIN. O'LCHANGAN NUQSON (2026-09-02,
# B-1 mashqi): `git archive` yiqilgach bo'sh reliz katalogi qolardi
# va u `rollback.sh --royxat` da ENG YANGI reliz bo'lib turardi --
# ya'ni yiqilgan joylashtiruvdan keyin tiklanayotgan operatorga
# aynan eng yaroqsiz nishon KO'RSATILARDI.
#
# `trap` faqat ALMASHTIRISHGACHA amal qiladi: `current` yangi
# relizga o'tgach uni o'chirish tirik xizmatni o'ldirardi.
TOZALA="$YANGI"
tozalash() {
    kod=$?
    if [ "$kod" -ne 0 ] && [ -n "$TOZALA" ] && [ -d "$TOZALA" ]; then
        xato_izoh "yiqildi -> yarim reliz olib tashlanmoqda: $TOZALA"
        rm -rf "$TOZALA"
    fi
    exit "$kod"
}
trap tozalash EXIT

git --git-dir="$REPO" archive "$REF" | tar -x -C "$YANGI"

# --- 3) Python muhiti --------------------------------------------------------
log "python muhiti quriladi"
python3 -m venv "${YANGI}/.venv"
"${YANGI}/.venv/bin/pip" install --quiet --upgrade pip
"${YANGI}/.venv/bin/pip" install --quiet -r "${YANGI}/requirements-api.txt"

# --- 4) MUHIT FAYLI O'QILADI -------------------------------------------------
# QURILMADAN OLDIN o'qiladi: frontend qurilmasi ham muhit qiymatlariga
# muhtoj (VITE_API_BASE, APP_ENV). Ilgari bu blok qurilmadan KEYIN edi
# va qurilma sozlamasiz yurardi.
set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a
export APP_ENV="$MUHIT"

# --- 4b) EMBEDDING BOG'LIQLIKLARI — IXTIYORIY --------------------------------
# `EMBED_PROVIDER=local` (STANDART qiymat) ishlashi uchun `torch` va
# `sentence-transformers` kerak. Ular `requirements-api.txt` da yo'q va
# bu ataylab: venv ni ~100 MB dan ~1.5 GB ga oshiradi, `api/ai_chat.py`
# esa ularni funksiya ichida import qiladi — yo'q bo'lsa chat LEKSIK
# qidiruvga tushadi va xizmat yiqilmaydi.
#
# NEGA MUHIT FAYLIDAN BOSHQARILADI: bu QAROR har o'rnatmada bir xil
# emas. Faqat ETL yoki faqat dashboard uchun ko'tarilgan nusxaga 1.4 GB
# ni majburlash noo'rin; semantik qidiruv kerak bo'lgan nusxada esa u
# SHART. `EMBED_INSTALL` shu tanlovni AYTILGAN qiladi.
#
# DIQQAT — DISK. Har reliz o'z venv iga ega va oxirgi 5 tasi saqlanadi
# (11-bo'lim). `EMBED_INSTALL=1` da bu muhit boshiga ~7 GB demak.
# Joy tor bo'lsa 11-bo'limdagi saqlanadigan reliz sonini kamaytiring.
if [ "${EMBED_INSTALL:-0}" = "1" ]; then
    log "embedding bog'liqliklari (torch CPU + sentence-transformers, ~1.4 GB)"
    "${YANGI}/.venv/bin/pip" install --quiet -r "${YANGI}/requirements-embed.txt"
    # QAYD: model FAYLLARI bu yerda tushmaydi — ular birinchi
    # ishlatishda `HF_HOME` ga (`var/hf`) keladi, ya'ni RELIZDAN
    # TASHQARIDA va joylashtirishlar orasida saqlanadi.
else
    log "embedding bog'liqliklari O'TKAZILDI (EMBED_INSTALL=0)"
fi

# --- 5) Frontend QURILADI (dev-server ISHLATILMAYDI) -------------------------
# Vite dev-server 0.0.0.0 ga boglanadi va uning zaifliklari bor
# (docs/xavfsizlik.md M-9). Joylashtirishda faqat statik qurilma.
#
# `.env.production` SHU YERDA YOZILADI. O'LCHANGAN NOSOZLIK: reliz
# `git archive` bilan yasaladi va `frontend/.env` KUZATILMAGAN fayl —
# u relizga TUSHMAYDI. Shu sababli qurilma `VITE_API_BASE` siz yurardi
# va zaxira qiymat (`http://localhost:8000`) qurilmaga SINGIB qolardi:
# ishlab chiqarish sahifasidagi har so'rov foydalanuvchi brauzerida
# `localhost:8000` ga ketardi.
#
# BU FAYLDA SIR YO'Q: `VITE_*` qiymatlari ta'rifi bo'yicha qurilmaga
# tushadi, ya'ni ular OMMAVIY. Sir hech qachon `VITE_` prefiksi bilan
# berilmasin.
log "frontend sozlamasi yoziladi"
cat > "${YANGI}/frontend/.env.production" <<EOF
VITE_API_BASE=${VITE_API_BASE:-/api}
VITE_ERP_WEB=${VITE_ERP_WEB:-}
EOF

log "frontend quriladi"
( cd "${YANGI}/frontend" && npm ci --silent && npm run build )
[ -d "${YANGI}/frontend/dist" ] || xato "frontend/dist yaratilmadi"

# QURILMA TEKSHIRUVI — mahalliy manzil singib qolmaganiga ISHONMAYMIZ,
# QARAYMIZ. `vite.config.ts` dagi qo'rovul sozlamani tekshiradi;
# bu yerda NATIJA tekshiriladi, ya'ni manbaga qaytib kelgan yangi
# qotirilgan `localhost` ham ushlanadi.
if grep -rqE 'localhost|127\.0\.0\.1|0\.0\.0\.0' "${YANGI}/frontend/dist/assets"; then
    grep -roE 'localhost:[0-9]*|127\.0\.0\.1:[0-9]*' "${YANGI}/frontend/dist/assets"         | sort -u | head -20 >&2
    xato "qurilmada MAHALLIY manzil bor (yuqorida) — ommaviy sahifada ishlamaydi"
fi
log "qurilma toza: mahalliy manzil yo'q"

# --- 5b) RELIZ DARVOZASI — QAYTMAS QADAMLARDAN OLDIN -------------------------
# Bu yerda turishining sababi: keyingi qadam (`migratsiya --qolla`)
# bazani O'ZGARTIRADI va undan keyingisi symlink'ni almashtiradi.
# Ikkalasi ham qaytarish narxi yuqori amallar. Sinov esa ULARDAN
# OLDIN yurishi kerak — aks holda "yiqilgan sinov" xabari bazaga
# migratsiya tushgandan keyin keladi.
#
# Frontend allaqachon qurilgan va `dist/` tekshirilgan, shuning uchun
# darvoza uni QAYTA qurmaydi (tip tekshiruvi va sinovlar YURADI).
log "reliz darvozasi"
TENDERAI_DARVOZA_FRONTEND=0 TENDERAI_PY="${YANGI}/.venv/bin/python" \
    "${YANGI}/deploy/bin/relis-darvoza.sh" "$YANGI" \
    || xato "reliz darvozasi yiqildi — joylashtirish TO'XTATILDI"

# --- 6) MIGRATSIYA — EGASI roli bilan ---------------------------------------
# Ilova roli (tai_app) da DDL huquqi ATAYLAB yoq.
: "${XT_DB_DSN_OWNER:?migratsiya uchun XT_DB_DSN_OWNER kerak (env faylda)}"
log "migratsiya holati"
"${YANGI}/.venv/bin/python" "${YANGI}/migratsiya.py" --holat --dsn "$XT_DB_DSN_OWNER" || true
log "migratsiya qollanadi"
"${YANGI}/.venv/bin/python" "${YANGI}/migratsiya.py" --qolla --dsn "$XT_DB_DSN_OWNER"

# --- 7) ALMASHTIRISH (atomar) ------------------------------------------------
# BIRINCHI JOYLASHTIRUVDA `current` HALI YO'Q. O'shanda `readlink -f`
# BO'SH QAYTARMAYDI: u yo'lning FAQAT OXIRGI qismi yetishmasa ham
# kanonik yo'lni chop etadi va nol kod bilan tugaydi. Ya'ni
#
#     ESKI="/opt/tenderai/<muhit>/current"
#
# bo'lib qolardi -- "eski reliz" emas, `current` ning O'ZI.
#
# O'LCHANGAN OQIBAT (2026-09-04, bo'sh serverga birinchi joylashtiruv):
# sog'liq tekshiruvi o'tmagach 9-bo'lim `[ -n "$ESKI" ] && [ -d "$ESKI" ]`
# ni TEKSHIRDI va u O'TDI -- chunki almashtirishdan keyin `current`
# haqiqatan katalogga (yangi relizga) ko'rsatayotgan edi. Keyin:
#
#     ln -sfn /opt/tenderai/staging/current /opt/tenderai/staging/current
#     current -> current          (O'ZI-O'ZIGA)
#
# Xizmat shundan keyin `203/EXEC` bilan yiqiladi va sabab jurnalda
# "Too many levels of symbolic links" bo'lib turadi -- ya'ni ASL
# nosozlik (nima uchun sog'liq tekshiruvi o'tmagani) BUTUNLAY
# KO'MILADI. O'rnatma esa tuzatib bo'lmaydigan holatga tushadi.
ESKI=""
if [ -L "$JORIY" ]; then
    ESKI="$(readlink -f "$JORIY" 2>/dev/null || true)"
fi
ln -sfn "$YANGI" "$JORIY"
# ALMASHTIRILDI: bundan keyin reliz TIRIK, o'chirib bo'lmaydi.
# Keyingi qadamlar yiqilsa 9-bo'lim ORQAGA QAYTARADI -- bu boshqa
# va TO'G'RI mexanizm.
TOZALA=""
log "current -> $YANGI"

# --- 8) Xizmatlar ------------------------------------------------------------
sudo systemctl restart "tenderai-api@${MUHIT}"
sudo systemctl enable --now "tenderai-etl@${MUHIT}.timer"          >/dev/null
sudo systemctl enable --now "tenderai-backup@${MUHIT}.timer"       >/dev/null
sudo systemctl enable --now "tenderai-restore-test@${MUHIT}.timer" >/dev/null

# --- 9) SOGLIQ TEKSHIRUVI — otmasa AVTOMATIK QAYTARILADI ---------------------
if ! "${YANGI}/deploy/bin/health-check.sh" "$MUHIT"; then
    log "sogliq tekshiruvi OTMADI — orqaga qaytarilmoqda"
    # `"$ESKI" != "$JORIY"` -- IKKINCHI QO'RIQCHI. Yuqoridagi `-L`
    # tekshiruvi sababni yopadi, bu esa OQIBATNI: qaytarish nishoni
    # hech qachon `current` ning o'zi bo'lib qolmasin.
    if [ -n "$ESKI" ] && [ -d "$ESKI" ] && [ "$ESKI" != "$JORIY" ]; then
        ln -sfn "$ESKI" "$JORIY"
        sudo systemctl restart "tenderai-api@${MUHIT}"
        xato "qaytarildi -> $ESKI"
    fi
    xato "qaytariladigan eski reliz yoq"
fi

# --- 10) STAGING: UCHIDAN-UCHIGA SINOV -> keyin TASDIQ -----------------------
#
# NEGA MAJBURIY VA NEGA AYNAN SHU YERDA.
#
# `health-check.sh` "xizmat javob beryaptimi" degan savolga javob
# beradi. U fayl yuklash OQIMINI umuman tekshirmaydi: proksi tana
# chegarasi, `Content-Disposition`, cookie/CSRF, `StreamingResponse`
# va ijarachi chegarasi -- hammasi HTTP darajasida va hammasi
# joylashtiruvdan KEYIN buzilishi mumkin.
#
# `_tests/yuklama_test.py` ham buni o'lchamaydi: u `TestClient`
# bilan yuradi va tarmoqqa CHIQMAYDI, ya'ni Caddy yo'lda TURMAYDI.
#
# TASDIQDAN OLDIN: `.verified` yozilishi "bu ref production ga
# chiqishi mumkin" degani. Sinov undan KEYIN yurgizilsa, yiqilgan
# oqim bilan ham tasdiq yozilib qolardi.
#
# SOZLANMAGANI "O'TDI" EMAS. Ilgari loyihada shunga o'xshash
# joylarda "sozlanmagan -> ogohlantirish -> davom" naqshi bor edi
# va u darvozani yolg'on qilardi. Bu yerda sozlanmagani XATO.
if [ "$MUHIT" = "staging" ]; then
    log "uchidan-uchiga sinov (haqiqiy HTTP)"
    : "${E2E_URL:?staging darvozasi uchun E2E_URL kerak (masalan https://staging.example.uz/api)}"
    : "${E2E_LOGIN:?E2E_LOGIN kerak — sinov hisobi}"
    : "${E2E_PAROL:?E2E_PAROL kerak}"
    : "${E2E_BEGONA_LOGIN:?E2E_BEGONA_LOGIN kerak: ijarachi chegarasi shusiz OLCHANMAYDI}"
    : "${E2E_BEGONA_PAROL:?E2E_BEGONA_PAROL kerak}"

    # `--ai` DOIM beriladi: iqtibos zanjiri (fayl -> bo'lak -> javob)
    # eng qimmat invariant va uni o'lchamasdan "reliz tayyor" deb
    # bo'lmaydi. Narxi bitta savol -- joylashtiruv chastotasida bu
    # sezilarli emas, buzilgan iqtibos esa sezilarli.
    if ! "${YANGI}/deploy/bin/e2e-fayl.sh" "$E2E_URL" \
            "$E2E_LOGIN" "$E2E_PAROL" \
            --begona "$E2E_BEGONA_LOGIN" "$E2E_BEGONA_PAROL" --ai --proksi; then
        log "E2E YIQILDI — orqaga qaytarilmoqda"
        if [ -n "$ESKI" ] && [ -d "$ESKI" ] && [ "$ESKI" != "$JORIY" ]; then
            ln -sfn "$ESKI" "$JORIY"
            sudo systemctl restart "tenderai-api@${MUHIT}"
            xato "qaytarildi -> $ESKI"
        fi
        xato "E2E yiqildi, qaytariladigan eski reliz yo'q"
    fi
    log "E2E o'tdi"

    printf '%s' "$REF" > "${ILDIZ}/.verified"
    log "staging tasdigi yozildi: $REF"
fi

# --- 11) Eski relizlar (oxirgi 5 tasi qoladi) -------------------------------
( cd "$RELIZLAR" && ls -1dt */ 2>/dev/null | tail -n +6 | xargs -r rm -rf )

log "TUGADI: ${MUHIT} <- ${REF}"
