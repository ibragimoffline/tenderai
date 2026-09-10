#!/usr/bin/env bash
# =============================================================================
# ZAXIRA OLISH — xizmat nomidan, ko'zgudagi kod bilan
# =============================================================================
#     zaxira-ol.sh <staging|production>
#
# NEGA ALOHIDA SKRIPT, O'RAMA ICHIDA EMAS. O'rnatilgan o'rama
# (`/usr/local/sbin/tender-zaxira`) ko'zgudan OLINMAYDI -- u alohida
# nusxa. Har mantiq o'zgarishi uni QAYTA O'RNATISHNI talab qilardi
# va bu bir necha marta takrorlandi. Shuning uchun o'rama YUPQA:
# argumentni tekshiradi, kodni ko'zgudan chiqaradi va shu yerga
# uzatadi. Mantiq esa ko'zguda -- ya'ni keyingi o'zgarish
# joylashtiruv bilan keladi.
#
# NEGA `tenderai` NOMIDAN. `backup.sh` timer ostida ham shu
# foydalanuvchi bilan yuradi. Root nomidan yurgizsak fayl egaligi
# boshqacha chiqib, keyingi timer o'z fayllariga tega olmasligi
# mumkin edi.
#
# NEGA RELIZDAGI EMAS, KO'ZGUDAGI `backup.sh`. Production relizi
# eski bo'lishi mumkin (hozir 5-sentabr) va u ILOVA roli bilan
# dump olib, tiklash metasini yozmaydi. `backup.sh` xizmatning
# o'zi emas -- TEXNIK XIZMAT asbobi; uni ko'zgudan yurgizish
# relizni o'zgartirmaydi va joylashtiruv hisoblanmaydi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: zaxira-ol.sh <staging|production>}"
case "$MUHIT" in staging|production) ;; *) echo "Noma'lum muhit: $MUHIT" >&2; exit 2 ;; esac
[ "$(id -u)" = "0" ] || { echo "root kerak" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKUP="${HERE}/backup.sh"
[ -x "$BACKUP" ] || { echo "backup.sh yo'q: $BACKUP" >&2; exit 1; }

# ROOT SIFATIDA YURADI -- `sudo` ISHLATILMAYDI.
#
# O'LCHANGAN NUQSON (2026-09-10). Avval bu skript `sudo -u tenderai`
# bilan yurgizardi va o'rama `sudo` orqali root ga ko'tarilardi.
# Systemd birligi esa `NoNewPrivileges=yes` bilan yuradi -- bu
# bayroq SUID ko'tarilishini YADRO darajasida bloklaydi. Ya'ni
# qo'lda yo'l ishlardi, TAYMER yo'li esa yiqilardi.
#
# Endi ikkala yo'l ham root: kalitlar to'g'ridan o'qiladi, SUID
# yo'li umuman yo'q. Qumdon SAQLANADI (`ProtectSystem=strict`,
# `ReadWritePaths`, `NoNewPrivileges`) -- root ham faqat zaxira
# katalogiga yoza oladi.
#
# Fayl egaligi `backup.sh` da katalogdan nusxalanadi, ya'ni kim
# yurgizganidan qat'i nazar bir xil bo'ladi.

# KATALOG XIZMAT ROLI UCHUN OCHILADI.
#
# `mktemp -d` root uchun `0700` yasaydi va `sudo -u tenderai` unga
# KIRA OLMAYDI -- xato esa "command not found" bo'lib ko'rinadi,
# ya'ni sabab yo'l huquqi ekani UMUMAN bilinmaydi.
#
# Bu yerda sir yo'q: katalogda faqat ochiq repozitoriy kodi.
ILDIZ="$(cd "${HERE}/../.." && pwd)"
chmod a+rX "$ILDIZ" "${ILDIZ}/deploy" "$HERE" 2>/dev/null || true
find "$HERE" -maxdepth 1 -type f -name '*.sh' -exec chmod a+rx {} + 2>/dev/null || true

echo "zaxira: ${MUHIT} (kod: ${HERE})  foydalanuvchi: root"
exec "$BACKUP" "$MUHIT"
