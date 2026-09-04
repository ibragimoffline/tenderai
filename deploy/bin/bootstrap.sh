#!/usr/bin/env bash
# =============================================================================
# Tender AI — serverni BIR MARTA tayyorlash
# =============================================================================
#     sudo bootstrap.sh <staging|production>
#
# Bu skript SIR YARATMAYDI va SIR SORAMAYDI. U faqat katalog, rol va
# xizmat fayllarini joyiga qoyadi. Sirlarni operator ozi
# `/etc/tenderai/<muhit>.env` ga yozadi (namuna: deploy/env/).
#
# QAYTA YURGIZSA BOLADI (idempotent).
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: bootstrap.sh <staging|production>}"
case "$MUHIT" in staging|production) ;; *) echo "Nomalum muhit"; exit 2 ;; esac

[ "$(id -u)" = "0" ] || { echo "root kerak: sudo $0 $MUHIT"; exit 1; }

BU="$(cd "$(dirname "$0")/.." && pwd)"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

# --- 1) Xizmat foydalanuvchisi (kirish YOQ) ---------------------------------
if ! id tenderai >/dev/null 2>&1; then
    useradd --system --home-dir /opt/tenderai --shell /usr/sbin/nologin tenderai
    log "tenderai foydalanuvchisi yaratildi (nologin)"
fi

# --- 2) Kataloglar -----------------------------------------------------------
install -d -o tenderai -g tenderai -m 0755 \
    "/opt/tenderai/${MUHIT}/releases" \
    "/opt/tenderai/${MUHIT}/var/hf" \
    "/opt/tenderai/${MUHIT}/var/cache" \
    "/var/backups/tenderai/${MUHIT}" \
    /var/log/caddy
install -d -o root -g tenderai -m 0750 /etc/tenderai
log "kataloglar tayyor"

# --- 3) Muhit fayli NAMUNASI (mavjudini USTIGA YOZMAYDI) --------------------
if [ ! -f "/etc/tenderai/${MUHIT}.env" ]; then
    install -o root -g tenderai -m 0640 \
        "${BU}/env/${MUHIT}.env.example" "/etc/tenderai/${MUHIT}.env"
    log "MUHIM: /etc/tenderai/${MUHIT}.env yaratildi — QIYMATLARNI TOLDIRING"
else
    log "/etc/tenderai/${MUHIT}.env allaqachon bor — tegilmadi"
fi

# --- 4) systemd birliklari ---------------------------------------------------
install -m 0644 "${BU}"/systemd/*.service "${BU}"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
log "systemd birliklari ornatildi"

# --- 5) Sudo: joylashtirish skripti xizmatni qayta yurgiza olsin ------------
# ANIQ royxat — `NOPASSWD: ALL` emas.
cat > /etc/sudoers.d/tenderai <<SUDO
tenderai ALL=(root) NOPASSWD: /bin/systemctl restart tenderai-api@staging
tenderai ALL=(root) NOPASSWD: /bin/systemctl restart tenderai-api@production
tenderai ALL=(root) NOPASSWD: /bin/systemctl enable --now tenderai-etl@staging.timer
tenderai ALL=(root) NOPASSWD: /bin/systemctl enable --now tenderai-etl@production.timer
tenderai ALL=(root) NOPASSWD: /bin/systemctl enable --now tenderai-backup@staging.timer
tenderai ALL=(root) NOPASSWD: /bin/systemctl enable --now tenderai-backup@production.timer
tenderai ALL=(root) NOPASSWD: /bin/systemctl enable --now tenderai-restore-test@staging.timer
tenderai ALL=(root) NOPASSWD: /bin/systemctl enable --now tenderai-restore-test@production.timer
SUDO
chmod 0440 /etc/sudoers.d/tenderai
visudo -c -f /etc/sudoers.d/tenderai >/dev/null
log "sudo qoidalari (aniq royxat)"

# --- 6) Bare repozitoriya ----------------------------------------------------
if [ ! -d /opt/tenderai/repo.git ]; then
    git init --bare /opt/tenderai/repo.git
    chown -R tenderai:tenderai /opt/tenderai/repo.git
    log "bare repo: /opt/tenderai/repo.git (push shu yerga)"
fi

echo
log "TAYYOR. Keyingi qadamlar:"
echo "  1. /etc/tenderai/${MUHIT}.env ni TOLDIRING (APP_PUBLIC_URL, XT_DB_DSN, ...)"
echo "  2. Bazani va tai_app rolini tayyorlang (docs/deploy.md §6)"
echo "  3. Caddyfile dagi domenlarni almashtiring va: systemctl reload caddy"
echo "  4. Kodni push qiling va: deploy/bin/deploy.sh ${MUHIT} <ref>"
