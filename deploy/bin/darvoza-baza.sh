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
    # BEGONA BELGI YO'Q. Glob dagi `*` YANGI QATORNI HAM oladi,
    # ya'ni "tenderai_gate_1\nDROP DATABASE ..." naqshga TUSHARDI.
    # Shuning uchun avval belgilar to'plami qattiq tekshiriladi:
    # faqat kichik harf, raqam va pastki chiziq.
    case "$n" in
        *[!0-9a-z_]*)
            echo "XATO: nomda begona belgi bor (bo'shliq/yangi qator?)." >&2
            echo "      Ruxsat: faqat [0-9a-z_]." >&2
            exit 2 ;;
    esac
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
# PYTHON — BOG'LIQLIKLARI BOR MUHIT KERAK.
#
# O'LCHANGAN (2026-09-07): darvoza vaqtinchalik katalogda yuradi va
# u yerda `venv` YO'Q. Zaxira `python3` esa tizimniki —
#
#     ModuleNotFoundError: No module named 'psycopg2'
#
# Reliz `venv` i (`/opt/tenderai/<muhit>/current/.venv`) — ilova
# HAQIQATAN yuradigan muhit, ya'ni darvoza uni ishlatsa sinov
# ishlab chiqarishdagi bilan AYNI to'plamda yuradi. Bu tasodifiy
# tanlov emas: boshqa `venv` da o'tgan sinov ishlab chiqarishda
# yiqilishi mumkin va aksincha.
PY="${TENDERAI_PY:-}"
if [ -z "$PY" ]; then
    for _p in "${ILDIZ}/.venv/bin/python" \
              "/opt/tenderai/${APP_ENV:-staging}/current/.venv/bin/python"; do
        if [ -x "$_p" ]; then PY="$_p"; break; fi
    done
    PY="${PY:-python3}"
fi

psql_() { psql "$XT_DB_DSN_TEST_ADMIN" -v ON_ERROR_STOP=1 -qtA "$@"; }

# --- TO'LIQ DARAXT: DARVOZA ILDIZDAGI FAYLLARGA MUHTOJ ----------------------
# O'ramaning arxivi `deploy` bilan CHEKLANGAN (`git archive "$SHA" deploy`),
# darvoza esa ildizdagi `migratsiya.py` va `run_tests.py` ga muhtoj.
#
# O'LCHANGAN NUQSON (2026-09-07): nusxa muvaffaqiyatli olingandan
# KEYIN migratsiya qadami
#
#     python3: can't open file '/tmp/tender-darvoza.XXXX/migratsiya.py'
#
# bilan yiqildi — ya'ni nosozlik BAZA YARATILGANDAN keyin chiqdi va
# darvoza bazasi qolib ketdi.
#
# YECHIM AYNI SNAPSHOTDAN. O'rama `RELEASE_SHA` ni eksport qiladi,
# ya'ni biz TAXMIN QILMAYMIZ: ayni o'sha o'zgarmas kommitdan to'liq
# daraxtni ochamiz. `main` QAYTA O'QILMAYDI — u harakatlanuvchi va
# uni bu yerda ishlatish "bir snapshot" invariantini buzardi.
ILDIZ_TOLIQ="${ILDIZ}"
darvoza_ildiz() {
    # Kerakli fayllar shu daraxtda bormi?
    _yetarli() {
        [ -f "$1/migratsiya.py" ] && [ -f "$1/run_tests.py" ] \
            && [ -f "$1/migratsiya_manifest.tsv" ] \
            && [ -d "$1/api" ] && [ -d "$1/_tests" ]
    }
    if _yetarli "$ILDIZ"; then ILDIZ_TOLIQ="$ILDIZ"; return 0; fi

    if [ -n "${RELEASE_SHA:-}" ]; then
        local repo="${TENDERAI_REPO:-/opt/tenderai/repo.git}"
        local kat="${ILDIZ}/.toliq"
        mkdir -p "$kat"
        log "arxiv faqat deploy/ ni o'z ichiga olgan — to'liq daraxt ochilmoqda"
        log "manba: $repo @ ${RELEASE_SHA}"
        if git --git-dir="$repo" archive "$RELEASE_SHA" | tar -x -C "$kat" 2>/dev/null \
           && _yetarli "$kat"; then
            ILDIZ_TOLIQ="$kat"
            log "to'liq daraxt tayyor"
            return 0
        fi
    fi

    # BAZA YARATILISHIDAN OLDIN TO'XTAYMIZ. Yetishmagan fayl NOMMA-NOM
    # aytiladi: "can't open file" degan xabar qaysi qadam yiqilganini
    # ham, nima yetishmayotganini ham tushuntirmasdi.
    echo "XATO: darvoza uchun zarur fayllar YO'Q." >&2
    for f in migratsiya.py run_tests.py migratsiya_manifest.tsv api _tests; do
        [ -e "${ILDIZ}/$f" ] || echo "      yetishmaydi: $f" >&2
    done
    echo "      RELEASE_SHA='${RELEASE_SHA:-<berilmagan>}'" >&2
    echo "      O'rama arxivi to'liq daraxtni chiqarishi kerak:" >&2
    echo "      git archive \"\$SHA\"   (\`deploy\` cheklovisiz)" >&2
    exit 1
}

# --- YIQILSA DARVOZA BAZASI QOLMASIN ----------------------------------------
# Ilgari faqat `pg_restore` yiqilganda tashlanardi. Migratsiya yoki
# 0071 tasdig'i yiqilsa baza QOLIB KETARDI — o'lchandi
# (`tenderai_gate_20260907_215231`) va uni qo'lda tozalashga to'g'ri keldi.
#
# `MUVAFFAQIYAT` faqat HAMMA qadam o'tgach qo'yiladi. `yarat` muvaffaqiyatli
# tugasa baza ATAYLAB QOLADI — keyingi `sinov "$GATE"` unga muhtoj.
DARVOZA_YARATILDI=0
MUVAFFAQIYAT=0
DARVOZA_NOM=""
tozalash_tuzogi() {
    kod=$?
    if [ "$DARVOZA_YARATILDI" = "1" ] && [ "$MUVAFFAQIYAT" != "1" ] \
       && [ -n "$DARVOZA_NOM" ]; then
        log "yiqildi -> darvoza bazasi tashlanmoqda: $DARVOZA_NOM"
        psql_ -c "DROP DATABASE IF EXISTS ${DARVOZA_NOM}" >/dev/null 2>&1 || true
    fi
    exit "$kod"          # ASL chiqish kodi saqlanadi
}
# JURNAL STDERR GA. `yarat` ning STDOUT i — MASHINA O'QIYDIGAN
# KANAL: u faqat bitta qator, darvoza bazasining nomini beradi.
#
# O'LCHANGAN NUQSON (2026-09-07): `log()` stdout ga yozardi va
#
#     GATE="$(tender-darvoza yarat)"
#
# nomi o'rniga BUTUN JURNALNI ushlab olardi. Keyingi `sinov "$GATE"`
# ko'p qatorli qiymat bilan chaqirilardi.
log() { printf '[darvoza-baza] %s\n' "$*" >&2; }

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

    # FAYLLAR BAZADAN OLDIN TEKSHIRILADI: yetishmasa hech narsa
    # yaratilmaydi va tozalaydigan narsa ham qolmaydi.
    darvoza_ildiz
    trap tozalash_tuzogi EXIT

    YANGI="${DARVOZA_PREFIKS}$(date +%Y%m%d_%H%M%S)"
    nom_tekshir "$YANGI"
    DARVOZA_NOM="$YANGI"

    log "manba : $MANBA"
    log "nishon: $YANGI"
    psql_ -c "CREATE DATABASE ${YANGI} ENCODING 'UTF8'" >/dev/null
    DARVOZA_YARATILDI=1
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
        echo "XATO: nusxa olinmadi — darvoza bazasi tuzoq orqali tashlanadi." >&2
        exit 1
    fi
    rm -f /tmp/darvoza-restore.$$
    log "nusxa tayyor"

    # MIGRATSIYA — AYNAN NUSXAGA. Haqiqiy staging bazasi bu qadamdan
    # butunlay chetda qoladi va tiqilinchning ma'nosi shu.
    log "migratsiya qo'llanmoqda…"
    # Migratsiya yurgizuvchisi ko'p qator chop etadi — STDERR ga.
    "${PY:-python3}" "${ILDIZ_TOLIQ}/migratsiya.py" --qolla --dsn "$NISHON_OWNER" >&2

    # 0071 TASDIG'I — jurnalga ISHONMAYMIZ, SO'RAYMIZ.
    QOLLANGAN="$(psql "$NISHON_OWNER" -qtA -c \
        "SELECT count(*) FROM schema_migration WHERE id LIKE '0071%'" 2>/dev/null || echo 0)"
    QOLLANGAN="$(printf '%s' "$QOLLANGAN" | tr -dc '0-9')"
    if [ "$QOLLANGAN" != "1" ]; then
        echo "XATO: 0071_topshiriq qo'llanmadi (topildi: $QOLLANGAN)" >&2
        exit 1
    fi
    # SXEMA SHARTI — jurnalning O'ZI yetarli emas. `0071` jadval
    # yaratadi; jurnalda yozuv bo'lib, jadval bo'lmasligi mumkin
    # (patch ichida `RETURN` bo'lsa). Shuning uchun IKKALASI ham.
    JADVAL="$(psql "$NISHON_OWNER" -qtA -c \
        "SELECT to_regclass('public.tender_topshiriq') IS NOT NULL" 2>/dev/null || echo f)"
    if [ "$JADVAL" != "t" ]; then
        echo "XATO: 0071 jurnalda bor, lekin \`tender_topshiriq\` jadvali YO'Q." >&2
        exit 1
    fi
    log "0071_topshiriq TASDIQLANDI (jurnal + sxema)"
    MUVAFFAQIYAT=1

    # YAGONA STDOUT YOZUVI. Bundan yuqoridagi hamma narsa stderr ga
    # ketdi, ya'ni `$(...)` aynan shu qatorni oladi.
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
    darvoza_ildiz
    log "sinov bazasi: $BAZA  (ilova roli)"
    cd "$ILDIZ_TOLIQ"
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
