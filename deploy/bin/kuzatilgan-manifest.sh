#!/usr/bin/env bash
# =============================================================================
# KUZATILGAN FAYLLAR MANIFESTI — bare repozitoriydan, O'ZGARMAS SHA bo'yicha
# =============================================================================
#     kuzatilgan-manifest.sh <40-belgili-SHA> <chiqish-fayli>
#
# NEGA UMUMIY SKRIPT: manifest IKKI yo'lda kerak --
#   `darvoza-baza.sh sinov`  (mustaqil darvoza)
#   `relis-darvoza.sh`       (reliz yo'li)
#
# O'LCHANGAN NUQSON (2026-09-09): u faqat BIRINCHISIGA ulangan edi.
# Reliz yo'lida manifest yo'q edi, `xavfsizlik_test` fail-closed
# qoidasi bo'yicha QIZIL berdi va reliz to'xtadi. Siyosat to'g'ri
# ishladi -- manifest noto'g'ri joyda edi. Ikki nusxa o'rniga bitta
# manba.
#
# `.git` ARXIVGA QO'SHILMAYDI: manifest bare repozitoriydan olinadi.
# Shu sababli u Docker darvozasida ham ishlaydi -- ijro muhitida
# `git` bo'lishi SHART EMAS, manifest tashqarida yasaladi.
# =============================================================================
set -euo pipefail

SHA="${1:?40 belgili SHA kerak}"
CHIQISH="${2:?chiqish fayli kerak}"
REPO="${TENDERAI_REPO:-/opt/tenderai/repo.git}"

case "$SHA" in
    ????????????????????????????????????????) ;;
    *) echo "XATO: SHA 40 belgili bo'lishi kerak: '$SHA'" >&2; exit 2 ;;
esac
case "$SHA" in *[!0-9a-f]*)
    echo "XATO: SHA da begona belgi." >&2; exit 2 ;;
esac

{
    echo "# tenderai-kuzatilgan-manifest v1"
    echo "# sha: ${SHA}"
    git --git-dir="$REPO" ls-tree -r --name-only "$SHA"
} > "$CHIQISH"

# BO'SH MANIFEST — DALIL EMAS. Uni qoldirish "hech narsa kuzatilmagan"
# degan yolg'on xulosaga olib kelardi; sinov esa uni QIZIL deb
# baholaydi. Shuning uchun bu yerda ham to'xtaymiz.
if [ "$(wc -l < "$CHIQISH")" -le 2 ]; then
    echo "XATO: manifest bo'sh — SHA repozitoriyada bormi? $SHA" >&2
    rm -f "$CHIQISH"
    exit 1
fi

sha256sum "$CHIQISH" | cut -d' ' -f1 > "${CHIQISH}.sha256"
echo "$(($(wc -l < "$CHIQISH") - 2))"
