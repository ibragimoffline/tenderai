#!/usr/bin/env bash
# =============================================================================
# FAZA 2 — STAGING KONTEYNERI (nginx va PostgreSQL TEGILMAYDI)
# =============================================================================
#     staging-docker.sh ishga  <imij-tegi>
#     staging-docker.sh sogliq
#     staging-docker.sh toxtat
#     staging-docker.sh holat
#
# ARXITEKTURA:
#     Internet -> HOST nginx -> Docker backend -> HOST PostgreSQL
#
# nginx ham, PostgreSQL ham HOSTDA qoladi. Konteynerga faqat ILOVA
# ijrosi ko'chadi.
#
# --- NEGA BOSHQA PORT (8012) -------------------------------------------------
# Mavjud systemd relizi 8011 da ishlashda DAVOM ETADI. Konteyner
# YONIDA ko'tariladi va nginx UNGA TEGMAYDI. Ya'ni bu qadam
# QAYTARILADIGAN: konteyner yiqilsa ham foydalanuvchi hech narsa
# sezmaydi, chunki trafik hamon 8011 da.
#
# nginx ni almashtirish ALOHIDA va ONGLI qadam (`tender-nginx`), u bu
# skriptda YO'Q — ataylab.
#
# --- BAZA ROLI ---------------------------------------------------------------
# `XT_DB_DSN` allaqachon `tai_service` — eng kam imtiyozli ILOVA roli
# (`CREATEDB` yo'q, superuser emas; `tekshir` buni har yurishda
# o'lchaydi). Ya'ni konteyner uchun YANGI ROL KERAK EMAS va uni
# yaratish faqat yana bitta sir bo'lardi.
# =============================================================================
set -euo pipefail

NOM=tenderai-staging          # konteyner nomi — QOTIRILGAN
PORT="${STAGING_DOCKER_PORT:-8012}"
KESH="${HF_KESH:-/opt/tenderai/staging/var/hf}"
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/staging.env}"

AMAL="${1:?foydalanish: staging-docker.sh <ishga|sogliq|toxtat|holat> [teg]}"

sogliq_tekshir() {
    local kod
    kod="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
           "http://127.0.0.1:${PORT}/health" 2>/dev/null || echo 000)"
    echo "  /health : $kod"
    kod="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
           "http://127.0.0.1:${PORT}/ready" 2>/dev/null || echo 000)"
    echo "  /ready  : $kod"
    [ "$kod" = "200" ]
}

case "$AMAL" in
ishga)
    TEG="${2:?imij tegi kerak, masalan f2dc19e2bce7}"
    # TEG QO'RIQCHASI: faqat qisqa SHA. Ixtiyoriy matn imij nomiga
    # tushmasin.
    case "$TEG" in
        [0-9a-f][0-9a-f]*) ;;
        *) echo "XATO: teg qisqa SHA bo'lishi kerak: '$TEG'" >&2; exit 2 ;;
    esac
    case "$TEG" in *[!0-9a-f]*) echo "XATO: tegda begona belgi." >&2; exit 2 ;; esac
    IMIJ="tenderai-backend:${TEG}"
    docker image inspect "$IMIJ" >/dev/null 2>&1 \
        || { echo "XATO: imij yo'q: $IMIJ" >&2; exit 1; }
    [ -r "$ENVFILE" ] || { echo "XATO: muhit fayli o'qilmadi: $ENVFILE" >&2; exit 1; }

    # Eski nusxa bo'lsa olib tashlanadi — FAQAT shu nom.
    docker rm -f "$NOM" >/dev/null 2>&1 || true

    # --- NEGA HOST TARMOG'I -------------------------------------------
    # PostgreSQL FAQAT `127.0.0.1` da tinglaydi va u shunday QOLADI.
    # Ko'prik tarmog'idan konteyner unga YETA OLMAYDI, chunki ko'prik
    # darvozasi (172.17.0.1) da hech kim tinglamaydi. Uch yo'l bor edi:
    #
    #   1. PostgreSQL ni ko'prikka ochish  -> BAZANI KENGROQ OCHADI, yo'q.
    #   2. PG unix soketini mount qilish   -> DSN ni qayta yozishni
    #      talab qiladi, ya'ni sirni qayta ishlash. Ortiqcha xatar.
    #   3. Host tarmog'i                   -> TANLANDI.
    #
    # Host tarmog'i YANGI HECH NARSA OCHMAYDI, chunki quyidagi
    # `API_HOST=127.0.0.1` xizmatni faqat loopback ga bog'laydi —
    # systemd relizi (`127.0.0.1:8011`) bilan AYNAN BIR XIL ko'rinish.
    # Agar `API_HOST` `0.0.0.0` bo'lib qolsa, xizmat butun internetga
    # chiqib ketardi; shuning uchun u shu yerda ATAYLAB qotirilgan.
    docker run -d --name "$NOM" \
        --restart unless-stopped \
        --network host \
        --cap-drop ALL \
        --security-opt no-new-privileges:true \
        --env-file "$ENVFILE" \
        -e API_HOST=127.0.0.1 \
        -e API_PORT="$PORT" \
        -e HF_HOME=/model-kesh \
        -v "${KESH}:/model-kesh:ro" \
        "$IMIJ" >/dev/null

    echo "[staging-docker] $NOM ko'tarildi: $IMIJ -> 127.0.0.1:${PORT}"
    echo "[staging-docker] systemd relizi 8011 da TEGILMAGAN holda ishlayapti"
    sleep 8
    sogliq_tekshir || { echo "[staging-docker] sog'liq O'TMADI — jurnal:" >&2
                        docker logs --tail 20 "$NOM" >&2; exit 1; }
    ;;

sogliq)  sogliq_tekshir ;;

toxtat)
    docker rm -f "$NOM" >/dev/null 2>&1 && echo "[staging-docker] $NOM olib tashlandi" \
        || echo "[staging-docker] $NOM ishlamayapti"
    ;;

holat)
    docker ps -a --filter "name=^${NOM}$" \
        --format '{{.Names}} {{.Status}} {{.Image}} {{.Ports}}' || true
    ;;

*) echo "Noma'lum amal: $AMAL" >&2; exit 2 ;;
esac
