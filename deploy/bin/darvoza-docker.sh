#!/usr/bin/env bash
# =============================================================================
# DARVOZA — KONTEYNERDA (44 to'plam)
# =============================================================================
#     darvoza-docker.sh <darvoza-bazasi> [run_tests argumentlari...]
#
# Bu skript ROOT O'RAMASI orqali chaqiriladi (`docs/docker.md` §6).
# Sabab: muhit fayli `/etc/tenderai/staging.env` root ga tegishli va
# `docker` guruhi ham root-ekvivalenti. Ikkalasini ham XIZMAT
# HISOBIGA (`tenderai`) berish eng kam imtiyoz chizig'ini buzardi —
# shuning uchun konteynerni O'RAMA ko'taradi, konteyner ichida esa
# root EMAS (uid 10001).
#
# NEGA `network_mode: host`
# -------------------------
# PostgreSQL faqat `127.0.0.1` da tinglaydi va docker ko'prigidan
# (`172.17.0.1`) KO'RINMAYDI — o'lchandi. Ikki yo'ldan:
#   a) Postgres ni ko'prikka ochish  -> BAZANI KENGROQ OCHADI;
#   b) konteynerni host tarmog'iga qo'yish -> YANGI HECH NARSA
#      OCHMAYDI, u shunchaki o'sha loopback ni ko'radi.
# (b) tanlandi.
# =============================================================================
set -euo pipefail

BAZA="${1:?foydalanish: darvoza-docker.sh <tenderai_gate_...> [args...]}"
shift || true

# --- QO'RIQCHA: FAQAT DARVOZA BAZASI ----------------------------------------
# `darvoza-baza.sh` dagi bilan AYNI qoida. Bu yerda takrorlanadi,
# chunki bu skript mustaqil chaqirilishi mumkin va qo'riqcha
# chaqiruvchining intizomiga tayanmasligi kerak.
case "$BAZA" in
    *[!0-9a-z_]*) echo "XATO: nomda begona belgi bor." >&2; exit 2 ;;
esac
case "$BAZA" in
    tenderai_gate_[0-9a-z_]*) ;;
    *) echo "XATO: '$BAZA' darvoza bazasi EMAS (tenderai_gate_*)." >&2; exit 2 ;;
esac

: "${XT_DB_DSN:?XT_DB_DSN kerak (ilova roli)}"
: "${IMIJ:=tenderai-gate:local}"
: "${HF_KESH:=/opt/tenderai/staging/var/hf}"

# DSN dagi bazani darvoza nusxasiga yo'naltiramiz. Sir TAKRORLANMAYDI:
# parol bitta joyda (muhit faylida) qoladi.
SINOV_DSN="$(printf '%s' "$XT_DB_DSN" | sed -E "s/dbname=[A-Za-z0-9_]+/dbname=${BAZA}/")"
ADMIN_DSN="$(printf '%s' "${XT_DB_DSN_TEST_ADMIN:-}" | sed -E "s/dbname=[A-Za-z0-9_]+/dbname=postgres/")"

# ROL TEKSHIRUVI — admin bilan yurgizib qo'ymaylik.
ROL="$(printf '%s' "$SINOV_DSN" | sed -nE 's/.*user=([A-Za-z0-9_]+).*/\1/p')"
if [ "$ROL" = "tai_test_admin" ]; then
    echo "XATO: oddiy sinovlar ADMIN roli bilan yurmaydi (rol=$ROL)." >&2
    exit 2
fi

echo "[darvoza-docker] imij : $IMIJ"
echo "[darvoza-docker] baza : $BAZA   rol: ${ROL:-ANIQLANMADI}"
echo "[darvoza-docker] kesh : $HF_KESH (faqat o'qish, oflayn)"

# `--rm`: konteyner qolmaydi. `--network host`: yuqoridagi izoh.
# `cap-drop ALL` + `no-new-privileges`: imtiyoz oshmasin.
# Docker soketi ULANMAYDI.
exec docker run --rm \
    --network host \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    -v "${HF_KESH}:/model-kesh:ro" \
    -e XT_DB_DSN="$SINOV_DSN" \
    -e XT_DB_DSN_TEST_ADMIN="$ADMIN_DSN" \
    -e APP_ENV=staging \
    -e APP_PUBLIC_URL="${APP_PUBLIC_URL:-}" \
    -e AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-1}" \
    "$IMIJ" "$@"
