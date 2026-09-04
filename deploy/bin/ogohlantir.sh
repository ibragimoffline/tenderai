#!/usr/bin/env bash
# =============================================================================
# Tender AI — NOSOZLIK OGOHLANTIRISHI (O-3)
# =============================================================================
#     ogohlantir.sh <muhit> <birlik-nomi> [qo'shimcha matn]
#
# NEGA KERAK (o'lchangan bo'shliq O-3): `systemd` xizmatni qayta
# ko'taradi, ETL taymeri qayta uradi — LEKIN BUNI HECH KIM
# BILMAYDI. `/ready` bor, uni SO'RAYDIGAN narsa yo'q edi. Ya'ni
# xizmat soatlab yiqilib turishi va buni faqat foydalanuvchi
# payqashi mumkin edi.
#
# MAVJUD KANAL ISHLATILADI, YANGISI QURILMAYDI. Loyihada
# allaqachon Telegram boti va SMTP bor — ogohlantirish uchun
# ikkinchi tizim qo'shish yangi sozlama, yangi sir va yangi
# nosozlik yuzasi bo'lardi.
#
# `systemd` bilan bog'lanish `OnFailure=` orqali:
#
#     [Unit]
#     OnFailure=tenderai-ogohlantirish@%i:%n.service
#
# JIM QOLMAYDI: kanal sozlanmagan bo'lsa ham skript BUNI AYTADI va
# `journald` ga yozadi. "Ogohlantirish yuborilmadi" holati
# ko'rinmasdan qolmasin.
#
# BU SKRIPT HECH QACHON NOLDAN BOSHQA KOD QAYTARMAYDI: u
# `OnFailure=` dan chaqiriladi va uning yiqilishi asl nosozlikni
# yashirib qo'yardi.
# =============================================================================
set -uo pipefail

# BIR YOKI IKKI ARGUMENT.
#
# `systemd` da `%i` bitta parametr, shuning uchun u
# `<muhit>:<birlik>` ko'rinishida keladi va SHU YERDA bo'linadi.
# Bo'linishni birlik faylidagi `sh -c` ichida qilish `%` belgisini
# ikki marta qochirishni talab qilardi va u OSON BUZILADI.
ARG1="${1:?foydalanish: ogohlantir.sh <muhit>[:<birlik>] [birlik] [matn]}"
case "$ARG1" in
    *:*)
        MUHIT="${ARG1%%:*}"
        BIRLIK="${ARG1#*:}"
        QOSHIMCHA="${2:-}"
        ;;
    *)
        MUHIT="$ARG1"
        BIRLIK="${2:-nomalum}"
        QOSHIMCHA="${3:-}"
        ;;
esac

ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
if [ -f "$ENVFILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENVFILE"
    set +a
fi

log() { printf '[%s] ogohlantir: %s\n' "$(date '+%F %T')" "$*"; }

# --- XABAR MATNI -------------------------------------------------------------
# Qisqa va ANIQ: nima, qayerda, qachon. Tafsilot `journalctl` da —
# uni xabarga tiqish xabarni o'qilmas qiladi.
HOST="$(hostname 2>/dev/null || echo '?')"
VAQT="$(date '+%F %T %Z')"
MATN="TENDER AI NOSOZLIK
muhit : ${MUHIT}
birlik: ${BIRLIK}
host  : ${HOST}
vaqt  : ${VAQT}"
[ -n "$QOSHIMCHA" ] && MATN="${MATN}
izoh  : ${QOSHIMCHA}"
MATN="${MATN}

Tafsilot:
  journalctl -u ${BIRLIK} -n 50 --no-pager"

log "birlik=${BIRLIK} muhit=${MUHIT}"

YUBORILDI=0

# --- 1) TELEGRAM -------------------------------------------------------------
# `ALERT_TELEGRAM_CHAT` ATAYLAB alohida sozlama: bildirishnoma
# obunachilari MIJOZLAR, nosozlik xabari esa OPERATORGA ketishi
# kerak. Ularni aralashtirish mijozga texnik xabar yuborardi.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${ALERT_TELEGRAM_CHAT:-}" ]; then
    if curl -fsS --max-time 15 \
         -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
         --data-urlencode "chat_id=${ALERT_TELEGRAM_CHAT}" \
         --data-urlencode "text=${MATN}" \
         -o /dev/null; then
        log "Telegram: yuborildi"
        YUBORILDI=1
    else
        log "Telegram: YUBORILMADI (curl xatosi)"
    fi
else
    log "Telegram: sozlanmagan (TELEGRAM_BOT_TOKEN / ALERT_TELEGRAM_CHAT)"
fi

# --- 2) EMAIL ----------------------------------------------------------------
# Python orqali: `sendmail` serverda bo'lmasligi mumkin, SMTP
# rekvizitlari esa allaqachon `.env` da.
if [ -n "${ALERT_EMAIL:-}" ] && [ -n "${SMTP_HOST:-}" ]; then
    # Tartib: ANIQ berilgan -> reliz venv i -> tizimdagi python.
    # `TENDERAI_PYTHON` mashq uchun ham, reliz yo'li boshqacha
    # bo'lgan o'rnatishlar uchun ham kerak.
    PY="${TENDERAI_PYTHON:-}"
    [ -n "$PY" ] || PY="/opt/tenderai/${MUHIT}/current/.venv/bin/python"
    [ -x "$PY" ] || PY="$(command -v python3 || command -v python || true)"
    if [ -n "$PY" ] && MATN="$MATN" BIRLIK="$BIRLIK" MUHIT="$MUHIT" \
        "$PY" - <<'PYEOF'
import os, smtplib, ssl, sys
from email.message import EmailMessage

xabar = EmailMessage()
xabar["Subject"] = f"[TENDER AI] NOSOZLIK: {os.environ['BIRLIK']} ({os.environ['MUHIT']})"
xabar["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER", "")
xabar["To"] = os.environ["ALERT_EMAIL"]
xabar.set_content(os.environ["MATN"])
host = os.environ["SMTP_HOST"]
port = int(os.environ.get("SMTP_PORT", "587"))
try:
    with smtplib.SMTP(host, port, timeout=20) as s:
        if os.environ.get("SMTP_USE_TLS", "1") not in ("0", "false", "no"):
            s.starttls(context=ssl.create_default_context())
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(xabar)
except Exception as e:                                        # noqa: BLE001
    print(f"email xatosi: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
    then
        log "Email: yuborildi -> ${ALERT_EMAIL}"
        YUBORILDI=1
    else
        log "Email: YUBORILMADI"
    fi
else
    log "Email: sozlanmagan (ALERT_EMAIL / SMTP_HOST)"
fi

# --- 3) HECH QAYERGA KETMADI -------------------------------------------------
# BU ENG XAVFLI HOLAT: nosozlik bor, xabar yo'q. U `journald` ga
# BALAND OVOZDA yoziladi — hech bo'lmaganda jurnalda iz qolsin.
if [ "$YUBORILDI" -eq 0 ]; then
    log "OGOHLANTIRISH HECH QAYERGA YUBORILMADI — kanal sozlanmagan yoki yiqildi"
    log "sozlash: ALERT_TELEGRAM_CHAT yoki ALERT_EMAIL (+ SMTP_HOST)"
fi

# HAR DOIM 0: bu skript `OnFailure=` dan chaqiriladi va uning
# yiqilishi ASL nosozlikni yashirib qo'yardi.
exit 0
