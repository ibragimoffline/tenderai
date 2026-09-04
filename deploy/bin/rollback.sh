#!/usr/bin/env bash
# =============================================================================
# Tender AI — ORQAGA QAYTARISH
# =============================================================================
#     rollback.sh <staging|production> [reliz-nomi] [--majburiy]
#     rollback.sh production --royxat      # mavjud relizlar
#
# Reliz berilmasa — OLDINGISIGA qaytadi.
#
# BAZA MIGRATSIYASI QAYTARILMAYDI va bu ATAYLAB:
#
#   - Migratsiyalar QOSHIMCHA (additive): yangi ustun yoki jadval
#     eski kodga XALAQIT BERMAYDI. Eski kod ularni bilmaydi, xolos.
#   - Avtomatik `down` skript esa MALUMOT YOQOTISHNING eng qisqa
#     yoli bolardi va u aynan falokat paytida ishga tushardi.
#   - Migratsiya haqiqatan buzuvchi bolsa — ZAXIRADAN tiklanadi.
#     Bu yol har hafta MASHQ QILINADI (restore-test.sh), yani u
#     "nazariy imkoniyat" emas.
#
# Qaytarish ATOMAR: `current` simvolik havolasi almashtiriladi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: rollback.sh <staging|production> [reliz|--royxat]}"
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

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

[ -d "$RELIZLAR" ] || { echo "Relizlar katalogi yoq: $RELIZLAR"; exit 1; }
HOZIRGI="$(readlink -f "$JORIY" 2>/dev/null || true)"

if [ "${2:-}" = "--royxat" ]; then
    echo "Relizlar (yangisidan eskisiga):"
    ( cd "$RELIZLAR" && ls -1dt */ | sed 's#/$##' ) | while read -r r; do
        belgi=" "
        # IKKALA TOMON HAM YECHILADI. O'LCHANGAN NUQSON (2026-09-02,
        # B-1 mashqi): `$HOZIRGI` `readlink -f` dan keladi va HAMMA
        # qismi yechilgan, `${RELIZLAR}/${r}` esa YECHILMAGAN
        # `$ILDIZ` dan quriladi. Yo'lning istalgan qismi simvolik
        # havola bo'lsa (masalan `/opt -> /srv`, oddiy server
        # tartibi) satrlar teng chiqmasdi va `*` BELGISI YO'QOLARDI
        # — ya'ni uzilish paytida operator QAYSI reliz tirikligini
        # ro'yxatdan BILA OLMASDI.
        [ "$(readlink -f "${RELIZLAR}/${r}" 2>/dev/null)" = "$HOZIRGI" ]             && belgi="*"
        echo "  ${belgi} ${r}"
    done
    echo "  (* — hozirgi)"
    exit 0
fi

HEDEF="${2:-}"
if [ -z "$HEDEF" ]; then
    # Vaqt boyicha tartiblangan royxatda HOZIRGIDAN keyingisi.
    HEDEF="$(cd "$RELIZLAR" && ls -1dt */ | sed 's#/$##' \
        | awk -v h="$(basename "$HOZIRGI")" 'p==h {print; exit} {p=$0}')"
fi

[ -n "$HEDEF" ] || { echo "Qaytariladigan reliz topilmadi"; exit 1; }
[ -d "${RELIZLAR}/${HEDEF}" ] || { echo "Yoq: ${RELIZLAR}/${HEDEF}"; exit 1; }

# --- HEDEF HAQIQIY RELIZMI -- ALMASHTIRISHDAN OLDIN ------------------------
# O'LCHANGAN NUQSON (2026-09-02, B-1 mashqi). Skript `current` ni
# almashtirib, xizmatni QAYTA ISHGA TUSHIRIB, ANDIN keyin sog'liqni
# tekshirardi. Hedef BO'SH katalog bo'lsa (yiqilgan joylashtiruvdan
# qolgan yarim reliz -- mashqda AYNAN shunday katalog qoldi):
#
#     current -> bo'sh katalog     xizmat O'LIK
#     health-check.sh              TOPILMADI (127)
#     chiqish                      "qo'lda qarang", kod 1
#
# Ya'ni TIKLASH VOSITASINING O'ZI uzilish keltirib chiqarardi va
# buni faqat almashtirgandan KEYIN aytardi. Tekshiruv endi
# OLDINDA: `current` ga TEGILMAYDI.
#
# Tekshiriladigan ikkitasi -- skript O'ZI bog'liq bo'lgan fayl va
# ilovaning kirish nuqtasi. Ro'yxatni uzaytirish mumkin edi, lekin
# haddan tashqari qat'iy tekshiruv uzilish paytida operatorni
# QAMAB QO'YARDI -- shuning uchun `--majburiy` chiqish yo'li bor.
# `--majburiy` FAQAT uchinchi argument: reliz nomi ATAYLAB
# yozilgan bo'lishi kerak. "Majburan, lekin qaysi relizga
# bilmayman" -- bu uzilish paytida eng xavfli buyruq bo'lardi.
MAJBURIY="${3:-}"
YETISHMAYDI=""
for zarur in "deploy/bin/health-check.sh" "api/main.py"; do
    [ -s "${RELIZLAR}/${HEDEF}/${zarur}" ] || YETISHMAYDI="${YETISHMAYDI} ${zarur}"
done
if [ -n "$YETISHMAYDI" ]; then
    if [ "$MAJBURIY" = "--majburiy" ]; then
        log "OGOH: hedef relizda yetishmaydi:${YETISHMAYDI}"
        log "OGOH: --majburiy berilgan, DAVOM ETILMOQDA"
    else
        echo "YARIM RELIZ: ${HEDEF}" >&2
        echo "  yetishmaydi:${YETISHMAYDI}" >&2
        echo "  'current' O'ZGARTIRILMADI, xizmat TEGILMADI." >&2
        echo "  Boshqa reliz tanlang: rollback.sh ${MUHIT} --royxat" >&2
        echo "  Yoki majburan: rollback.sh ${MUHIT} ${HEDEF} --majburiy" >&2
        exit 1
    fi
fi

log "hozirgi: $(basename "$HOZIRGI")  ->  hedef: $HEDEF"
ln -sfn "${RELIZLAR}/${HEDEF}" "$JORIY"
sudo systemctl restart "tenderai-api@${MUHIT}"

if "${RELIZLAR}/${HEDEF}/deploy/bin/health-check.sh" "$MUHIT"; then
    log "QAYTARILDI: $HEDEF"
else
    log "DIQQAT: qaytarildi, LEKIN sogliq tekshiruvi otmadi — qolda qarang"
    log "  journalctl -u tenderai-api@${MUHIT} -n 100"
    exit 1
fi
