#!/usr/bin/env bash
# =============================================================================
# JORIY RELIZNI TASDIQLASH — qayta joylashtirmasdan
# =============================================================================
#     tasdiqla-joriy.sh [staging]
#
# NEGA BU AMAL BOR. `deploy.sh` relizni almashtirgach E2E yurgizadi va
# muhrni undan KEYIN yozadi. Agar skript oradan uzilsa (o'lchangan
# nuqson, 2026-09-09) reliz JONLI, sog'lom va darvozadan o'tgan
# bo'ladi -- lekin muhrsiz.
#
# O'shanda AYNAN SHU KODNI qayta joylashtirish MA'NOSIZ va xatarli:
# u yangi katalog yasaydi, migratsiyani qayta yurgizadi va ishlaydigan
# xizmatni qayta ishga tushiradi -- hammasi faqat fayl yozish uchun.
# Bu amal o'rniga JONLI tizimni o'lchaydi va muhrni o'sha yerda
# yozadi.
#
# BU MUHRNI "QO'LDA QO'YISH" EMAS. Muhr faqat majburiy tekshiruvlar
# HAQIQATAN o'tganda yoziladi; ular shu yerda yuradi.
#
# ASBOB RELIZNING O'ZIDAN OLINADI. E2E skripti `$JORIY/deploy/bin`
# dan yurgiziladi, tashqi nusxadan EMAS. Aks holda muhr "S kommiti
# T asbobi bilan tekshirildi" degan ma'noga ega bo'lardi va T
# yozilmagani uchun uni keyin hech kim bilolmasdi. Asbob relizga
# bog'langanda muhr O'ZINI-O'ZI tushuntiradi.
# =============================================================================
set -euo pipefail

MUHIT="${1:-staging}"
ILDIZ="${TENDERAI_ILDIZ:-/opt/tenderai/${MUHIT}}"
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
JORIY="${ILDIZ}/current"

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
xato() { echo "XATO: $*" >&2; exit 1; }

[ "$MUHIT" = "staging" ] || xato "faqat staging tasdiqlanadi. Berilgan: '$MUHIT'"
[ "$(id -u)" = "0" ] || xato "root sifatida yurgizing."
[ -L "$JORIY" ] || xato "'$JORIY' simlink emas — tasdiqlanadigan reliz yo'q."

RELIZ="$(readlink -f "$JORIY")"
log "joriy reliz: $RELIZ"

# --- 1) RELIZ KIMLIGI VA BUTUNLIGI -------------------------------------------
MANIFEST="${RELIZ}/.kuzatilgan-manifest"
[ -f "$MANIFEST" ] || xato "manifest yo'q: $MANIFEST"
SHA="$(sed -n '2s/^# sha: *//p' "$MANIFEST")"
case "$SHA" in *[!0-9a-f]*|"") xato "manifestdagi sha yaroqsiz: '$SHA'" ;; esac
[ "${#SHA}" -eq 40 ] || xato "manifestdagi sha 40 belgi emas: '$SHA'"
log "reliz SHA: $SHA"

# Manifest o'zgartirilmaganini tekshiramiz: u xavfsizlik sinovining
# DALIL bazasi va uni jimgina tahrirlash mumkin bo'lmasligi kerak.
SIDECAR="${MANIFEST}.sha256"
if [ -f "$SIDECAR" ]; then
    KUTILGAN="$(cut -d' ' -f1 < "$SIDECAR")"
    HOZIRGI="$(sha256sum "$MANIFEST" | cut -d' ' -f1)"
    [ "$KUTILGAN" = "$HOZIRGI" ] || xato "manifest CHECKSUMI mos emas — reliz o'zgartirilgan."
    log "manifest butunligi: ok"
else
    xato "manifest checksumi yo'q: $SIDECAR"
fi

# --- 2) ASBOB SHARTNOMASI ----------------------------------------------------
# Relizdagi E2E skripti ASOSIY/PULLIK bo'linishini biladimi. Bilmasa
# tasdiqlash uchun PULLIK chaqiruv kerak bo'lardi va bu qoidaga zid.
E2E="${RELIZ}/deploy/bin/e2e-fayl.sh"
[ -x "$E2E" ] || xato "relizda E2E skripti yo'q: $E2E"
grep -q -- '--ai-yoq' "$E2E" || xato "bu reliz ASOSIY/PULLIK bo'linishidan OLDINGI:
   \`$E2E\` \`--ai-yoq\` ni bilmaydi, ya'ni uni tasdiqlash uchun
   PULLIK AI chaqiruvi SHART bo'lardi.
   Yechim: bo'linish kiritilgan kommitni joylashtiring."

# --- 3) MAJBURIY SOZLAMA — NOM BO'YICHA, QIYMATSIZ ---------------------------
[ -f "$ENVFILE" ] || xato "muhit fayli yo'q: $ENVFILE"
set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a

YOQ=""
for k in E2E_URL E2E_LOGIN E2E_PAROL E2E_BEGONA_LOGIN E2E_BEGONA_PAROL; do
    eval "v=\${${k}:-}"
    [ -n "$v" ] || YOQ="${YOQ}
   ${k}"
done
[ -z "$YOQ" ] || xato "E2E_CONFIG_MISSING:${YOQ}

   Qiymatlar CHOP ETILMAYDI — faqat nomlari.
   Sozlash: sudo deploy/bin/e2e-hisob-sozla.sh"

# --- 4) SOG'LIQ VA TAYYORLIK -------------------------------------------------
"${RELIZ}/deploy/bin/health-check.sh" "$MUHIT" || xato "sog'liq tekshiruvi o'tmadi"

# --- 5) ASOSIY E2E — PULLIK AI O'CHIRILGAN -----------------------------------
# `E2E_AI_ENABLED=1` bo'lsagina pullik chaqiruv qilinadi. Standart
# holat: o'chirilgan. Hisob-kitobni JIMGINA o'zgartirmaslik uchun
# rejim ANIQ uzatiladi.
if [ "${E2E_AI_ENABLED:-0}" = "1" ]; then
    AI_REJIM="--ai"
    log "AI E2E: YOQILGAN (PULLIK chaqiruv bo'ladi)"
else
    AI_REJIM="--ai-yoq"
    log "AI E2E: o'chirilgan (ixtiyoriy, pullik)"
fi

log "asosiy E2E (haqiqiy HTTP): $E2E_URL"
"$E2E" "$E2E_URL" "$E2E_LOGIN" "$E2E_PAROL" \
    --begona "$E2E_BEGONA_LOGIN" "$E2E_BEGONA_PAROL" \
    "$AI_REJIM" --proksi \
    || xato "asosiy E2E YIQILDI — tasdiq yozilmadi."

# --- 6) MUHR -----------------------------------------------------------------
"${RELIZ}/deploy/bin/tasdiq-yoz.sh" "$ILDIZ" "$SHA"
log "TUGADI: $MUHIT relizi tasdiqlandi ($SHA)"
