#!/usr/bin/env bash
# =============================================================================
# Tender-AI — IZOLYATSIYALANGAN DARVOZA BAZASI
# =============================================================================
#     darvoza-baza.sh yarat   <manba-baza>    # nusxa + migratsiya
#     darvoza-baza.sh tashla  <darvoza-baza>
#     darvoza-baza.sh nom                     # yangi nom chop etadi
#     darvoza-baza.sh tekshir                 # ulanish + rol (sirsiz)
#
# NEGA BU FAYL BOR — RELIZ TIQILINCHI
# -----------------------------------
# `deploy.sh` tartibi: 5b) reliz darvozasi -> 6) migratsiya.
# Backend sinovlari esa YANGI sxemani talab qiladi
# (`schema_patch_topshiriq.sql`, manifest 730/0071_topshiriq).
#
#     sinov yangi sxemani talab qiladi
#       -> migratsiya hali yurmagan
#       -> darvoza yiqiladi
#       -> 6-qadamga YETIB BORILMAYDI
#       -> keyingi joylashtiruv AYNI holatdan boshlanadi
#
# Ya'ni yangi migratsiya olib keladigan HECH QANDAY reliz chiqa
# olmaydi va bu holat o'z-o'zidan tuzalmaydi.
#
# YECHIM: darvoza HAQIQIY staging bazasiga TEGMAYDI. U izolyatsiyalangan
# nusxa yasaydi, migratsiyani O'SHA YERDA qo'llaydi, sinovlarni o'sha
# yerda yurgizadi va nusxani tashlaydi. Haqiqiy bazaga migratsiya
# faqat darvoza YASHIL bo'lgandan keyin tushadi.
#
# NEGA ALOHIDA ROL (`tai_test_admin`)
# -----------------------------------
# `tai_service` — ILOVA roli va unda `CREATEDB` ATAYLAB YO'Q. Sinov
# qulayligi uchun ilova roliga baza yaratish huquqini berish — eng
# kam imtiyoz qoidasini sinov uchun buzish demak. Shuning uchun
# ajratilgan `tai_test_admin` ishlatiladi va u FAQAT staging da
# sozlanadi.
# =============================================================================
set -euo pipefail

AMAL="${1:?foydalanish: darvoza-baza.sh <yarat|tashla|nom> [baza]}"

# --- QO'RIQCHI 1: NOM NAQSHI -------------------------------------------------
# Buzuvchi amal FAQAT shu naqshga tushgan nomga tegadi. Naqsh
# `deploy.sh` dagi `TOZA_REF` bilan bir uslubda: aniq prefiks +
# cheklangan belgilar.
#
# NEGA BU BIRINCHI QO'RIQCHI: `DROP DATABASE` ni muhit tekshiruvidan
# oldin nomga bog'lash kerak — muhit o'zgaruvchisi ADASHTIRILISHI
# mumkin, nom esa buyruq qatorida KO'RINIB turadi.
DARVOZA_PREFIKS="tenderai_gate_"

nom_tekshir() {
    local n="$1"
    case "$n" in
        "${DARVOZA_PREFIKS}"[0-9a-z_]*) ;;
        *) echo "XATO: '$n' darvoza bazasi EMAS." >&2
           echo "      Buzuvchi amal faqat '${DARVOZA_PREFIKS}*' ga ruxsat etiladi." >&2
           exit 2 ;;
    esac
    # ATAYLAB TAKROR: prefiksga tushgan, lekin haqiqiy baza nomiga
    # o'xshash qiymat ham to'siladi. Ikkinchi qo'riqcha birinchisi
    # noto'g'ri yozilganda ishlaydi.
    case "$n" in
        tenderai_production|tenderai_staging|xtxarid|postgres|template*)
            echo "XATO: '$n' — HAQIQIY baza. To'xtatildi." >&2; exit 2 ;;
    esac
}

# --- QO'RIQCHI 2: MUHIT ------------------------------------------------------
# `production` da bu skript UMUMAN ishlamaydi va CHETLAB O'TISH
# BAYROG'I YO'Q (`--force`, `--tasdiq` va h.k.). Sabab: bunday
# bayroq bir marta yozilsa, u jurnalda ham, skriptda ham "normal"
# bo'lib ko'rinadi va qo'riqchi o'z-o'zini o'chiradi.
muhit_tekshir() {
    local m="${APP_ENV:-}"
    case "$m" in
        staging|test) ;;
        *) echo "XATO: darvoza bazasi faqat APP_ENV=staging|test da." >&2
           echo "      Hozir: APP_ENV='${m:-<berilmagan>}'" >&2
           echo "      Chetlab o'tish bayrog'i YO'Q va bo'lmaydi." >&2
           exit 2 ;;
    esac
}

# --- QO'RIQCHI 3: DSN ALOHIDA ------------------------------------------------
# Ilova roli (`XT_DB_DSN`) bilan baza yaratib bo'lmaydi va SINAB
# HAM KO'RILMAYDI: agar kimdir `tai_service` ga `CREATEDB` bersa,
# bu skript baribir uni ISHLATMAYDI.
: "${XT_DB_DSN_TEST_ADMIN:?XT_DB_DSN_TEST_ADMIN kerak (tai_test_admin, faqat staging)}"

ILDIZ="${ILDIZ:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PY="${TENDERAI_PY:-}"
if [ -z "$PY" ]; then
    if [ -x "${ILDIZ}/.venv/bin/python" ]; then PY="${ILDIZ}/.venv/bin/python"
    else PY="python3"; fi
fi

psql_() { psql "$XT_DB_DSN_TEST_ADMIN" -v ON_ERROR_STOP=1 -qtA "$@"; }
log() { printf '[darvoza-baza] %s\n' "$*"; }

# --- DSN dagi bazani ALMASHTIRISH -------------------------------------------
# Darvoza bazasi uchun alohida DSN yozilmaydi: mavjud DSN dagi
# `dbname=` almashtiriladi. Sabab — SIR TAKRORLANMASIN: parol allaqachon
# bitta joyda (`/etc/tenderai/staging.env`), ikkinchi nusxa esa uni
# eskirishi va ajralib ketishi mumkin bo'lgan joyga ko'chirardi.
dsn_baza() {
    printf '%s' "$1" | sed -E "s/dbname=[A-Za-z0-9_]+/dbname=$2/"
}

case "$AMAL" in
tekshir)
    # ULANISH VA ROLNI TASDIQLAYDI — SIR CHOP ETMASDAN.
    #
    # DSN chiqishga TUSHMAYDI: u parol saqlaydi va bu skriptning
    # chiqishi jurnalga hamda ko'p qo'ldan o'tadigan hisobotlarga
    # ketadi. Faqat rol nomi, baza nomi va `CREATEDB` bayrog'i
    # ko'rsatiladi — qaror uchun shuncha yetadi.
    #
    # `rolcreatedb` ALOHIDA tekshiriladi: rol mavjudligi uning
    # baza YARATA OLISHINI bildirmaydi va bu farq aynan shu
    # skript uchun hal qiluvchi.
    psql_ -c "SELECT 'rol=' || current_user
                  || '  baza=' || current_database()
                  || '  createdb=' || (SELECT rolcreatedb FROM pg_roles
                                        WHERE rolname = current_user)"
    # `tai_service` da CREATEDB PAYDO BO'LIB QOLMAGANINI ham
    # o'lchaymiz: bu loyihaning qat'iy qoidasi va uni "eslab
    # qolishga" tayanib qoldirib bo'lmaydi.
    psql_ -c "SELECT 'tai_service.createdb=' || COALESCE(
                  (SELECT rolcreatedb::text FROM pg_roles
                    WHERE rolname = 'tai_service'), '<rol yo''q>')"
    ;;

yarat)
    # NUSXA + MIGRATSIYA. Haqiqiy staging bazasiga TEGILMAYDI.
    muhit_tekshir
    MANBA="${MANBA_BAZA:-tenderai_staging}"
    case "$MANBA" in
        tenderai_production) echo "XATO: production MANBA sifatida ishlatilmaydi." >&2; exit 2 ;;
    esac
    : "${XT_DB_DSN_OWNER:?nusxa uchun XT_DB_DSN_OWNER kerak (muhit faylida)}"

    YANGI="${DARVOZA_PREFIKS}$(date +%Y%m%d_%H%M%S)"
    nom_tekshir "$YANGI"

    log "manba : $MANBA"
    log "nishon: $YANGI"
    psql_ -c "CREATE DATABASE ${YANGI} ENCODING 'UTF8'" >/dev/null
    log "baza yaratildi"

    # NUSXA — `pg_dump | pg_restore` OQIM bilan: 27 MB+ oraliq fayl
    # diskda qolmaydi va yiqilsa yarim fayl ham qolmaydi.
    #
    # `--no-owner`: nusxada egalik `tai_test_admin` ga tushadi va bu
    # MAYLI — bu baza bir martalik va yurish oxirida tashlanadi.
    NISHON_OWNER="$(dsn_baza "$XT_DB_DSN_OWNER" "$YANGI")"
    log "nusxa olinmoqda (pg_dump | pg_restore)…"
    if ! pg_dump "$XT_DB_DSN_OWNER" -Fc --no-owner --no-privileges \
         | pg_restore -d "$NISHON_OWNER" --no-owner --no-privileges \
                      --exit-on-error 2>/tmp/darvoza-restore.$$; then
        tail -20 /tmp/darvoza-restore.$$ >&2 || true
        rm -f /tmp/darvoza-restore.$$
        psql_ -c "DROP DATABASE IF EXISTS ${YANGI}" >/dev/null
        echo "XATO: nusxa olinmadi — darvoza bazasi tashlandi." >&2
        exit 1
    fi
    rm -f /tmp/darvoza-restore.$$
    log "nusxa tayyor"

    # MIGRATSIYA — AYNAN NUSXAGA. Haqiqiy staging bazasi bu qadamdan
    # butunlay chetda qoladi va tiqilinchning ma'nosi shu.
    log "migratsiya qo'llanmoqda…"
    "${PY:-python3}" "${ILDIZ}/migratsiya.py" --qolla --dsn "$NISHON_OWNER"

    # 0071 TASDIG'I — jurnalga ISHONMAYMIZ, SO'RAYMIZ.
    QOLLANGAN="$(psql "$NISHON_OWNER" -qtA -c \
        "SELECT count(*) FROM schema_migration WHERE id LIKE '0071%'" 2>/dev/null || echo 0)"
    if [ "$QOLLANGAN" != "1" ]; then
        echo "XATO: 0071_topshiriq qo'llanmadi (topildi: $QOLLANGAN)" >&2
        exit 1
    fi
    log "0071_topshiriq TASDIQLANDI"
    printf '%s\n' "$YANGI"
    ;;

sinov)
    # BACKEND DARVOZASI — NUSXA USTIDA, ILOVA ROLI BILAN.
    #
    # `tai_service` ATAYLAB: sinovlar ishlab chiqarishdagi bilan AYNI
    # imtiyozda yurishi kerak. `tai_test_admin` faqat yaratish/tashlash
    # uchun va u bu yerda ISHLATILMAYDI — aks holda darvoza superuser
    # huquqida yashil bo'lib, ishlab chiqarishda qizarardi.
    muhit_tekshir
    BAZA="${2:?darvoza bazasi nomi kerak}"
    nom_tekshir "$BAZA"
    : "${XT_DB_DSN:?sinov uchun XT_DB_DSN kerak (ilova roli)}"
    SINOV_DSN="$(dsn_baza "$XT_DB_DSN" "$BAZA")"
    log "sinov bazasi: $BAZA  (ilova roli)"
    cd "$ILDIZ"
    XT_DB_DSN="$SINOV_DSN" APP_ENV=staging \
        "${PY:-python3}" run_tests.py
    ;;

tozala)
    muhit_tekshir
    BAZA="${2:?tashlanadigan baza nomi kerak}"
    nom_tekshir "$BAZA"
    psql_ -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
              WHERE datname = '${BAZA}' AND pid <> pg_backend_pid()" >/dev/null || true
    psql_ -c "DROP DATABASE IF EXISTS ${BAZA}" >/dev/null
    log "tashlandi: $BAZA"
    ;;

nom)
    printf '%s%s\n' "$DARVOZA_PREFIKS" "$(date +%Y%m%d_%H%M%S)"
    ;;

*) echo "Noma'lum amal: $AMAL" >&2; exit 2 ;;
esac
