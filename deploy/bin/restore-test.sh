#!/usr/bin/env bash
# =============================================================================
# Tender AI — TIKLASH MASHQI
# =============================================================================
#     restore-test.sh <staging|production>
#
# SINALMAGAN ZAXIRA — ZAXIRA EMAS. "Fayl bor" degani "tiklanadi"
# degani emas: dump buzuq bolishi, sxema tiklanmasligi, yoki
# tiklash tasavvurdan uzun davom etishi mumkin. Bularning hammasi
# AYNAN falokat paytida bilinardi.
#
# BU SKRIPT HAR HAFTA:
#   1. eng oxirgi zaxirani oladi;
#   2. VAQTINCHALIK bazaga tiklaydi;
#   3. jadval sonini, qator sonini va migratsiya holatini TEKSHIRADI;
#   4. tiklash VAQTINI olchaydi (RTO uchun haqiqiy raqam);
#   5. vaqtinchalik bazani TASHLAYDI.
#
# ISHLAB CHIQARISH BAZASIGA TEGMAYDI. Nom tekshiruvi bor va u
# bajarilmasa skript TOXTAYDI.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: restore-test.sh <staging|production>}"
# MUHIT FAYLI YO'LI ALMASHTIRILISHI MUMKIN — `TENDERAI_ENVFILE`.
#
# NEGA (o'lchangan 2026-09-01, B-1): yo'l `/etc/tenderai/` ga
# QOTIRILGAN edi va u FAQAT tayyorlangan serverda mavjud. Natijada
# skriptlar HECH QACHON, HECH QAYERDA yurgizilmagan — ular faqat
# `deploy_test` da MATN sifatida tekshirilardi (114 tekshiruv,
# hammasi statik).
#
# "Yozilgan, lekin bir marta ham bajarilmagan skript" —
# joylashtirish kunidagi eng qimmat noma'lum. Endi mashq qilish
# mumkin: yo'l berilsa o'sha ishlatiladi.
#
# Standart qiymat O'ZGARMADI — serverdagi xulq bir xil qoladi.
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
[ -f "$ENVFILE" ] || { echo "muhit fayli yoq: $ENVFILE"; exit 2; }

set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a

: "${XT_DB_DSN_OWNER:?tiklash mashqi uchun XT_DB_DSN_OWNER kerak}"
KATALOG="${BACKUP_DIR:-/var/backups/tenderai}/${MUHIT}"
SINOV_BAZA="tenderai_restore_test_${MUHIT}"

log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
xato() { printf '[%s] XATO: %s\n' "$(date '+%F %T')" "$*" >&2; exit 1; }

# --- XAVFSIZLIK: ishlab chiqarish bazasiga TEGMASLIK -------------------------
# Bu tekshiruv JIMGINA OTKAZIB YUBORILMAYDI. U bajarilmasa skript
# toxtaydi: vaqtinchalik baza nomi haqiqiysiga teng bolsa, mashq
# ishlab chiqarishni YOQ QILARDI.
ASOSIY_BAZA="$(printf '%s' "$XT_DB_DSN_OWNER" | tr ' ' '\n' \
               | grep -E '^dbname=' | cut -d= -f2 || true)"
[ -n "$ASOSIY_BAZA" ] || xato "DSN dan dbname olinmadi"
[ "$ASOSIY_BAZA" != "$SINOV_BAZA" ] || xato "sinov bazasi nomi asosiy baza bilan BIR XIL"
log "asosiy baza: $ASOSIY_BAZA   sinov bazasi: $SINOV_BAZA"

# Admin DSN — `postgres` bazasiga ulanib CREATE/DROP qilish uchun.
ADMIN_DSN="$(printf '%s' "$XT_DB_DSN_OWNER" | sed "s/dbname=${ASOSIY_BAZA}/dbname=postgres/")"

# --- 1) Eng oxirgi zaxira ----------------------------------------------------
ZAXIRA="$(find "$KATALOG" -maxdepth 1 -name '*.dump' -printf '%T@ %p\n' 2>/dev/null \
          | sort -rn | head -1 | cut -d' ' -f2- || true)"
[ -n "$ZAXIRA" ] || xato "zaxira topilmadi: $KATALOG"
log "zaxira: $(basename "$ZAXIRA")  ($(du -h "$ZAXIRA" | cut -f1))"

# --- 2) SHA-256 tekshiruvi ---------------------------------------------------
if [ -f "${ZAXIRA}.sha256" ]; then
    if sha256sum -c "${ZAXIRA}.sha256" >/dev/null 2>&1; then
        log "sha256 mos"
    else
        xato "sha256 MOS KELMADI — zaxira ozgargan yoki buzilgan"
    fi
else
    log "OGOH: sha256 fayli yoq — butunlik tekshirilmadi"
fi

# --- 3) Vaqtinchalik bazaga tiklash -----------------------------------------
tozala() {
    psql "$ADMIN_DSN" -q -c "DROP DATABASE IF EXISTS \"${SINOV_BAZA}\";" >/dev/null 2>&1 || true
}
trap tozala EXIT

tozala
psql "$ADMIN_DSN" -q -c "CREATE DATABASE \"${SINOV_BAZA}\";"
SINOV_DSN="$(printf '%s' "$XT_DB_DSN_OWNER" | sed "s/dbname=${ASOSIY_BAZA}/dbname=${SINOV_BAZA}/")"

log "tiklash boshlandi"
T0="$(date +%s)"
# `--no-owner`: rollar boshqacha bolishi mumkin.
# `-j 4`: parallel — RTO ni qisqartiradi.
# Xatolar YUTILMAYDI: chiqish kodi tekshiriladi.
if ! pg_restore --dbname="$SINOV_DSN" --no-owner --no-privileges -j 4 "$ZAXIRA" \
        > /tmp/restore.$$ 2>&1; then
    log "pg_restore chiqish kodi nolga teng emas; oxirgi qatorlar:"
    tail -20 /tmp/restore.$$ || true
    rm -f /tmp/restore.$$
    xato "TIKLASH YIQILDI"
fi
rm -f /tmp/restore.$$
T1="$(date +%s)"
DAVOM=$((T1 - T0))
log "tiklandi: ${DAVOM} s  (RTO uchun haqiqiy raqam)"

# --- 4) TEKSHIRUVLAR — "tiklandi" degani "tori" degani emas ------------------
jadval() { psql "$SINOV_DSN" -Atqc "$1" 2>/dev/null || echo 0; }

N_JADVAL="$(jadval "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")"
N_TENDER="$(jadval "SELECT count(*) FROM tender")"
N_CHUNK="$(jadval "SELECT count(*) FROM doc_chunk")"
N_MIGR="$(jadval "SELECT count(*) FROM schema_migration WHERE holat IN ('ok','bootstrap')")"

log "tekshiruv: jadval=$N_JADVAL  tender=$N_TENDER  bolak=$N_CHUNK  migratsiya=$N_MIGR"

muammo=0
[ "$N_JADVAL" -ge 40 ] || { log "XATO: jadval soni juda kam ($N_JADVAL)"; muammo=1; }
[ "$N_TENDER" -ge 1 ]  || { log "XATO: tender jadvali bosh"; muammo=1; }
[ "$N_MIGR"   -ge 1 ]  || { log "XATO: migratsiya jurnali bosh"; muammo=1; }

# pgvector kengaytmasi tiklandimi — usiz semantik qidiruv olmaydi.
N_VEC="$(jadval "SELECT count(*) FROM pg_extension WHERE extname='vector'")"
[ "$N_VEC" = "1" ] || { log "XATO: pgvector kengaytmasi tiklanmadi"; muammo=1; }

if [ "$muammo" -ne 0 ]; then
    xato "TIKLASH MASHQI OTMADI"
fi

log "TIKLASH MASHQI OTDI. RTO=${DAVOM}s, zaxira=$(basename "$ZAXIRA")"
