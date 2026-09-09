#!/usr/bin/env bash
# =============================================================================
# `.verified` MUHRI — YAGONA YOZUVCHI
# =============================================================================
#     tasdiq-yoz.sh <ildiz> <sha>
#
# NEGA ALOHIDA SKRIPT. Muhr ikki yo'ldan yoziladi: oddiy reliz
# (`deploy.sh`) va joriy relizni tasdiqlash (`tasdiqla-joriy.sh`).
# Ikkita nusxa bo'lsa ular ASTA-SEKIN AJRALARDI -- bu loyihada
# allaqachon bir marta yuz bergan (manifest faqat `sinov` yo'liga
# ulangan, reliz yo'liga ulanmagan edi).
#
# MUHR NIMANI ANGLATADI: "AYNAN SHU 40 belgili kommit haqiqiy HTTP
# ustida majburiy tekshiruvdan o'tdi". Shuning uchun:
#
#   * FAQAT 40 belgili o'n oltilik SHA yoziladi. `main`, `staging`,
#     `latest`, reliz katalogi nomi -- HECH BIRI EMAS. O'LCHANGAN
#     NUQSON: faylda `main` turardi va u qaysi kod tekshirilganini
#     AYTMASDI.
#   * Yoziladigan SHA `current` ko'rsatayotgan reliz SHA si bilan
#     BIR XIL bo'lishi shart. Aks holda muhr boshqa kodni
#     tasdiqlagan bo'lardi.
#   * Yozuv ATOMAR: vaqtinchalik fayl + `mv`. Yarim yozilgan muhr
#     "ehtimol tasdiqlangan" degan ma'noga ega bo'lardi, bunday
#     ma'no esa yo'q.
#
# FAIL CLOSED: har qanday nomuvofiqlikda muhr YOZILMAYDI.
# =============================================================================
set -euo pipefail

ILDIZ="${1:?foydalanish: tasdiq-yoz.sh <ildiz> <sha>}"
SHA="${2:?sha kerak}"

xato() { echo "TASDIQ YOZILMADI: $*" >&2; exit 1; }

# --- 1) SHA SHAKLI -----------------------------------------------------------
case "$SHA" in
    *[!0-9a-f]* | "") xato "SHA o'n oltilik emas: '$SHA'" ;;
esac
[ "${#SHA}" -eq 40 ] || xato "SHA 40 belgi emas (${#SHA}): '$SHA'"

# --- 2) `current` QAYSI RELIZGA ISHORA QILADI --------------------------------
JORIY="${ILDIZ}/current"
[ -L "$JORIY" ] || xato "'$JORIY' simlink emas"
RELIZ="$(readlink -f "$JORIY")"
[ -d "$RELIZ" ] || xato "reliz katalogi yo'q: $RELIZ"

# --- 3) RELIZNING O'Z SHA SI --------------------------------------------------
# Manba: `.kuzatilgan-manifest` sarlavhasi. Katalog NOMI ishlatilmaydi
# -- u `20260909-050102-main` ko'rinishida bo'lib, SHOX nomini
# saqlaydi va kommitni aytmaydi.
MANIFEST="${RELIZ}/.kuzatilgan-manifest"
[ -f "$MANIFEST" ] || xato "relizda manifest yo'q: $MANIFEST"
RELIZ_SHA="$(sed -n '2s/^# sha: *//p' "$MANIFEST")"
[ -n "$RELIZ_SHA" ] || xato "manifest sarlavhasida sha yo'q: $MANIFEST"

[ "$RELIZ_SHA" = "$SHA" ] || xato "SHA MOS EMAS:
   so'ralgan          : $SHA
   joriy reliz ($RELIZ): $RELIZ_SHA"

# --- 4) ATOMAR YOZUV ---------------------------------------------------------
VAQT="$(mktemp "${ILDIZ}/.verified.XXXXXX")"
trap 'rm -f "$VAQT"' EXIT
printf '%s\n' "$SHA" > "$VAQT"
chmod 644 "$VAQT"
mv -f "$VAQT" "${ILDIZ}/.verified"
trap - EXIT

echo "tasdiq yozildi: ${ILDIZ}/.verified <- $SHA"
