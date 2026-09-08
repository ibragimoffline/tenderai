#!/usr/bin/env bash
# =============================================================================
# Tender-AI — IZOLYATSIYALANGAN DARVOZA BAZASI
# =============================================================================
#     MANBA_BAZA=<baza> darvoza-baza.sh yarat  # nusxa + migratsiya
#         (manba MUHIT O'ZGARUVCHISIDAN olinadi, $2 dan EMAS)
#     darvoza-baza.sh tozala  <darvoza-baza>
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

AMAL="${1:?foydalanish: darvoza-baza.sh <tekshir|yarat|sinov|tozala|tasdiq|nom> [baza]}"

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

# --- 0071 TASDIG'I — UCH HOLAT, IKKITA EMAS ---------------------------------
# O'LCHANGAN NUQSON (2026-09-07, meniki): tekshiruv shunday edi —
#
#     psql ... "WHERE id LIKE '0071%'" 2>/dev/null || echo 0
#
# Ikki xato bir joyda:
#   1. Ustun nomi `id` emas, `migratsiya_id` (`migratsiya.py:588`).
#      Ya'ni so'rov HAR SAFAR xato berardi.
#   2. `2>/dev/null || echo 0` o'sha xatoni YUTIB, natijani `0` ga
#      aylantirardi — "o'lchay olmadim" "qo'llanmagan" bo'lib
#      ko'rinardi.
#
# Natijada migratsiya HAQIQATAN qo'llangan bo'lsa ham darvoza
# "0071 qo'llanmadi" deb yiqilardi va SABAB ko'rinmasdi.
#
# UCH HOLAT AJRATILADI:
#   psql o'tdi + 1  -> PASS
#   psql o'tdi + 0  -> FAIL: migratsiya YO'Q
#   psql yiqildi    -> FAIL: O'LCHANMADI  (nol EMAS)
#
# Va JURNAL bilan SXEMA ALOHIDA tekshiriladi: patch ichida `RETURN`
# bo'lsa jurnalda "tugadi" turib, jadval bo'lmasligi mumkin — ERP
# 23-patchida aynan shu bo'lgan.
tasdiq_0071() {
    local dsn="$1" chiq kod

    # `ON_ERROR_STOP=1` + chiqish kodini TEKSHIRISH. Chiqish kodi
    # nolga teng bo'lmasa natija UMUMAN o'qilmaydi.
    # `set -e` OSTIDA `$(...)` YIQILSA SKRIPT DARHOL O'LADI va
    # quyidagi `kod` tekshiruvigacha YETIB BORMAYDI — ya'ni
    # "o'lchanmadi" xabari hech qachon chiqmasdi va uch holat yana
    # ikkitaga qisqarardi. Shuning uchun `errexit` shu ikki
    # chaqiruvda ATAYLAB vaqtincha o'chiriladi.
    # SANOQ EMAS, HOLATNING O'ZI so'raladi.
    #
    # `count(*) ... AND holat = '<literal>'` ikki xil nosozlikni
    # BITTA `0` ga qo'shib yuboradi: "qator umuman yo'q" va "qator
    # bor, lekin holati boshqa". Ikkinchisi esa aynan bilish kerak
    # bo'lgan narsa — va men shu yerda IKKI MARTA adashdim
    # (`id` o'rniga `migratsiya_id`, keyin `tugadi` o'rniga `ok`).
    #
    # HOLAT LITERALLARI KODDAN OLINGAN (`migratsiya.py:1086`):
    #     "ok"          -- bajarildi
    #     "xato"        -- yiqildi
    #     "boshlandi"   -- boshlangan, tugamagan
    #     "otkazildi"   -- O'TKAZIB YUBORILGAN
    #     "bootstrap"   -- mavjud deb belgilangan
    #
    # `otkazildi` ALOHIDA VA MUHIM: "o'tkazib yuborildi" — bajarildi
    # EMAS. Uni muvaffaqiyat deb sanash ERP 23-patchidagi "skip =
    # success" nuqsonining aynan o'zi bo'lardi.
    set +e
    chiq="$(psql "$dsn" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT COALESCE(
                  (SELECT holat FROM schema_migration
                    WHERE migratsiya_id LIKE '0071%'
                    ORDER BY id DESC LIMIT 1), '<qator yo''q>')" 2>&1)"
    kod=$?
    set -e
    if [ "$kod" -ne 0 ]; then
        echo "XATO: 0071 JURNALINI O'QIB BO'LMADI (psql kodi $kod)." >&2
        echo "      Bu 'qo'llanmagan' EMAS — O'LCHANMAGAN." >&2
        printf '      %s\n' "$chiq" >&2
        exit 1
    fi
    case "$chiq" in
        ok) log "0071 jurnal: holat=ok" ;;
        otkazildi)
            echo "XATO: 0071_topshiriq O'TKAZIB YUBORILGAN (holat=otkazildi)." >&2
            echo "      Bu 'bajarildi' EMAS — patch ishga tushmagan." >&2
            exit 1 ;;
        *)  echo "XATO: 0071_topshiriq bajarilmagan. Jurnaldagi holat: '$chiq'" >&2
            echo "      Kutilgan: 'ok' (migratsiya.py:1086)." >&2
            exit 1 ;;
    esac

    # SXEMA SHARTI — jurnaldan MUSTAQIL.
    set +e
    chiq="$(psql "$dsn" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT to_regclass('public.tender_topshiriq') IS NOT NULL" 2>&1)"
    kod=$?
    set -e
    if [ "$kod" -ne 0 ]; then
        echo "XATO: 0071 SXEMASINI O'QIB BO'LMADI (psql kodi $kod)." >&2
        echo "      Bu 'jadval yo'q' EMAS — O'LCHANMAGAN." >&2
        printf '      %s\n' "$chiq" >&2
        exit 1
    fi
    if [ "$chiq" != "t" ]; then
        echo "XATO: jurnal 'tugadi' deydi, \`public.tender_topshiriq\` esa YO'Q." >&2
        echo "      Patch ichida \`RETURN\` bo'lgan bo'lishi mumkin." >&2
        exit 1
    fi
    log "0071 sxema: tender_topshiriq bor"
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
    # BESH INVARIANT — HAMMASI O'LCHANADI, HECH BIRI TAXMIN QILINMAYDI.
    #
    # Ilgari bu yerda faqat ADMIN dsn i tekshirilardi. Natijada
    # `XT_DB_DSN` da `user=tai_test_admin` turgani faqat `sinov`
    # bosqichida, 20+ to'plam "permission denied" bergandan KEYIN
    # ko'rindi (2026-09-08). Sozlama nuqsoni sinov nuqsoni bo'lib
    # ko'rinardi.
    #
    # PAROL CHIQMAYDI: faqat `current_user`, `current_database` va
    # `rolcreatedb`.
    _xato=0

    # --- 1-2) ILOVA DSN i --------------------------------------------------
    : "${XT_DB_DSN:?tekshiruv uchun XT_DB_DSN kerak}"
    set +e
    _app="$(psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT current_user || ' ' || current_database()" 2>&1)"
    _k=$?
    set -e
    if [ "$_k" -ne 0 ]; then
        echo "XATO: XT_DB_DSN ulanmadi (psql $_k) — O'LCHANMADI." >&2
        printf '      %s\n' "$_app" >&2
        exit 1
    fi
    _arol="${_app%% *}"; _abaza="${_app##* }"
    echo "ilova : rol=${_arol}  baza=${_abaza}"
    [ "$_arol" = "tai_service" ] || {
        echo "XATO: XT_DB_DSN roli '${_arol}' — 'tai_service' bo'lishi SHART." >&2
        _xato=1; }
    [ "$_abaza" = "tenderai_staging" ] || {
        echo "XATO: XT_DB_DSN bazasi '${_abaza}' — 'tenderai_staging' bo'lishi SHART." >&2
        _xato=1; }

    # --- 4) ADMIN DSN i ----------------------------------------------------
    _adm="$(psql_ -c "SELECT current_user")"
    echo "admin : rol=${_adm}"
    [ "$_adm" = "tai_test_admin" ] || {
        echo "XATO: XT_DB_DSN_TEST_ADMIN roli '${_adm}' — 'tai_test_admin' kutilgan." >&2
        _xato=1; }

    # --- 3, 5) CREATEDB BAYROQLARI -----------------------------------------
    # Ikkalasi ham AYNI so'rovda: bitta rasm, ikki qiymat.
    _svc="$(psql_ -c "SELECT COALESCE((SELECT rolcreatedb::text FROM pg_roles
                                        WHERE rolname='tai_service'), 'YOQ')")"
    _adm_c="$(psql_ -c "SELECT COALESCE((SELECT rolcreatedb::text FROM pg_roles
                                          WHERE rolname='tai_test_admin'), 'YOQ')")"
    echo "createdb: tai_service=${_svc}  tai_test_admin=${_adm_c}"
    [ "$_svc" = "false" ] || {
        echo "XATO: tai_service da CREATEDB bor — eng kam imtiyoz buzilgan." >&2
        _xato=1; }
    [ "$_adm_c" = "true" ] || {
        echo "XATO: tai_test_admin da CREATEDB yo'q — darvoza ishlamaydi." >&2
        _xato=1; }

    if [ "$_xato" -ne 0 ]; then
        echo "TEKSHIR: FAIL — invariant buzilgan (yuqorida)." >&2
        exit 1
    fi
    # --- QOLGAN DARVOZA BAZALARI ------------------------------------------
    # Darvoza bazasi bir martalik. Qolib ketgani ikki narsani
    # bildiradi: disk yeyilyapti va oldingi yurish tozalanmagan.
    #
    # O'LCHANGAN (2026-09-08): `sinov` nolga teng bo'lmagan kod
    # qaytargach chaqiruvchi qobiq `set -e` bilan to'xtadi va
    # `tozala` UMUMAN yurmadi. Ya'ni tozalash chaqiruvchining
    # intizomiga tayangan edi — endi sanoq shu yerda KO'RINADI.
    _gate="$(psql_ -c "SELECT count(*) FROM pg_database
                        WHERE datname LIKE 'tenderai_gate_%'")"
    _gate_nom="$(psql_ -c "SELECT COALESCE(string_agg(datname, ', '
                                            ORDER BY datname), '-')
                             FROM pg_database
                            WHERE datname LIKE 'tenderai_gate_%'")"
    echo "darvoza bazalari: ${_gate}  (${_gate_nom})"
    [ "$_gate" = "0" ] || {
        echo "OGOHLANTIRISH: ${_gate} ta darvoza bazasi qolgan —" >&2
        echo "               'tozala <nom>' bilan olib tashlang." >&2; }

    # --- ROL ATRIBUTLARI — KLASTER DARAJASI, SIRSIZ -----------------------
    # NEGA KERAK: `schema_patch_huquq.sql` migratsiyasi
    #
    #     ALTER ROLE tai_app NOSUPERUSER NOCREATEDB ...
    #
    # yuboradi va PostgreSQL `SUPERUSER` atributini o'zgartirish uchun
    # -- HATTO OLIB TASHLASH uchun ham -- superuser talab qiladi.
    # Ya'ni bo'sh bazadan tiklash superuser'siz to'xtaydi (o'lchandi
    # 2026-09-09, darvoza).
    #
    # Qaror qabul qilishdan OLDIN rollarning HAQIQIY holatini bilish
    # kerak: agar ular allaqachon qattiqlashtirilgan bo'lsa,
    # migratsiya ularni O'ZGARTIRISHI emas, TEKSHIRISHI kerak.
    #
    # FAQAT METAMA'LUMOT: parol ham, DSN ham chiqmaydi.
    echo "--- rol atributlari (klaster) ---"
    psql_ -c "SELECT rolname
                     || ' super='   || rolsuper
                     || ' createdb='|| rolcreatedb
                     || ' createrole=' || rolcreaterole
                     || ' bypassrls=' || rolbypassrls
                     || ' replication=' || rolreplication
                     || ' login='   || rolcanlogin
                FROM pg_roles
               WHERE rolname IN ('tai_app','tai_service',
                                 'tai_test_admin','tai_owner')
               ORDER BY rolname" 2>/dev/null | sed 's/^/  /' || \
        echo "  (rol atributlari o'qilmadi)"

    # --- IMTIYOZ ZANJIRI — `DARVOZA_HUQUQ=1` bo'lganda -------------------
    # `xavfsizlik_test` `tai_app` ning `erp.app_user` ga SELECT huquqi
    # borligini aytadi. "Nima uchun" degan savolga javob berish uchun
    # ZANJIR kerak: to'g'ridan-to'g'ri grantmi, ota-rol orqalimi,
    # PUBLIC ormi, yoki egalik.
    #
    # Taxmin qilib REVOKE qilish xato bo'lardi: noto'g'ri bo'g'inni
    # uzsak ERP ishlamay qolishi mumkin. Shuning uchun avval o'lchov.
    #
    # IL0VA DSN i ISHLATILADI, admin emas: `erp` sxemasi ILOVA
    # bazasida. O'LCHANGAN NUQSON (2026-09-09): birinchi variant
    # `psql_` ni ishlatardi, u esa `XT_DB_DSN_TEST_ADMIN` bilan
    # BOSHQA bazaga ulanadi -- barcha so'rovlar BO'SH qaytdi va
    # `2>/dev/null` xatoni yashirdi. Endi xato KO'RINADI.
    # `tekshir` DIAGNOSTIKA amali, shuning uchun shartsiz chiqadi.
    # O'ram muhit o'zgaruvchilarini qat'iy ro'yxat bilan uzatadi, ya'ni
    # bayroq bilan yoqib bo'lmasdi. FAQAT metama'lumot — sir yo'q.
    {
        echo "--- imtiyoz zanjiri: tai_app -> erp.app_user ---"
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT 'samarali: schema_usage='
                      || has_schema_privilege('tai_app','erp','USAGE')
                      || ' table_select='
                      || has_table_privilege('tai_app','erp.app_user','SELECT')"                2>&1 | sed 's/^/  /'
        echo "  --- tai_app a'zoligi (kimga a'zo) ---"
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT '  -> ' || r.rolname
                    FROM pg_auth_members m
                    JOIN pg_roles r ON r.oid = m.roleid
                    JOIN pg_roles u ON u.oid = m.member
                   WHERE u.rolname = 'tai_app'" 2>&1 | sed 's/^/  /'
        echo "  --- kim tai_app ga a'zo ---"
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT '  <- ' || u.rolname
                    FROM pg_auth_members m
                    JOIN pg_roles r ON r.oid = m.roleid
                    JOIN pg_roles u ON u.oid = m.member
                   WHERE r.rolname = 'tai_app'" 2>&1 | sed 's/^/  /'
        echo "  --- erp.app_user egasi va ACL ---"
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT 'egasi=' || pg_get_userbyid(c.relowner)
                    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='erp' AND c.relname='app_user'" 2>&1 | sed 's/^/  /'
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT '  ACL: ' || COALESCE(a.grantee::regrole::text,'PUBLIC')
                      || ' ' || a.privilege_type
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid=c.relnamespace,
                         aclexplode(c.relacl) a
                   WHERE n.nspname='erp' AND c.relname='app_user'
                   ORDER BY 1" 2>&1 | sed 's/^/  /'
        echo "  --- TO'LIQ SILJISH: tai_app ga erp da berilgan HAMMA huquq ---"
        # Faqat `app_user` emas: boshqa jadvallarda ham provenansiz
        # grant bo'lishi mumkin. `schema_patch_huquq.sql` FAQAT uchta
        # shartnoma-view ni ruxsat etadi, ERP tomoni ham shuni yozadi.
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c \
            "SELECT '  ' || c.relkind::text || ' erp.' || c.relname
                  || ' -> ' || a.privilege_type
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace,
                     aclexplode(c.relacl) a
               WHERE n.nspname = 'erp'
                 AND a.grantee::regrole::text = 'tai_app'
               ORDER BY c.relname, a.privilege_type" 2>&1 | sed 's/^/  /'
        echo "  (relkind: r=jadval  v=ko'rinish  m=materiallashgan)"
        echo "  --- erp sxemasi ACL ---"
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT '  ' || COALESCE(a.grantee::regrole::text,'PUBLIC')
                      || ' ' || a.privilege_type
                    FROM pg_namespace n, aclexplode(n.nspacl) a
                   WHERE n.nspname='erp' ORDER BY 1" 2>&1 | sed 's/^/  /'
        echo "  --- sukut huquqlar (pg_default_acl) ---"
        # `defaclrole` HAL QILUVCHI: `ALTER DEFAULT PRIVILEGES` ROLGA
        # bog'langan va uni neytrallash uchun AYNAN o'sha rol (yoki
        # superuser) kerak. Rolsiz tuzatish rejasini yozib bo'lmaydi.
        psql "$XT_DB_DSN" -v ON_ERROR_STOP=1 -qtA -c "SELECT '  egasi=' || pg_get_userbyid(d.defaclrole)
                      || ' ' || n.nspname || ' ' || d.defaclobjtype::text
                      || ' ' || COALESCE(a.grantee::regrole::text,'PUBLIC')
                      || ' ' || a.privilege_type
                    FROM pg_default_acl d
                    JOIN pg_namespace n ON n.oid=d.defaclnamespace,
                         aclexplode(d.defaclacl) a
                   WHERE COALESCE(a.grantee::regrole::text,'PUBLIC')
                         IN ('tai_app','PUBLIC') ORDER BY 1" 2>&1 | sed 's/^/  /'
    } || true

    echo "TEKSHIR: PASS — besh invariant ham o'tdi"
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
    # `--no-privileges` OLIB TASHLANDI va sabab O'LCHANGAN (2026-09-08).
    #
    # U bilan nusxada HAMMA GRANT yo'qolardi. Natijada `tai_service`
    # nusxadagi birorta jadvalni ko'ra olmasdi va darvoza 20+ to'plamda
    #
    #     permission denied for table company_account
    #
    # berardi. Bu KOD nuqsoni emas, NUSXANING nuqsoni edi — ya'ni
    # darvoza ishlab chiqarishda yo'q muammoni ko'rsatardi.
    #
    # HUQUQ PATCHI QAYTA YURMAYDI: `schema_patch_huquq.sql` (0057) va
    # `_2` (0069) manifestda bor, lekin ular jurnalda ALLAQACHON
    # "ok" — jurnal staging dan nusxa ko'chgan. Ya'ni jurnal
    # "qo'llangan" deydi, GRANT lar esa yo'q. Bu loyihada takror
    # uchraydigan sinf: JURNAL ≠ SHART.
    #
    # `--no-owner` QOLADI: egalik nusxada `tai_test_admin` ga tushadi
    # va bu maqbul — baza bir martalik. GRANT lar esa rol NOMIGA
    # bog'langan (`tai_service`), ya'ni ular ko'chganda ishlaydi.
    if ! pg_dump "$XT_DB_DSN_OWNER" -Fc --no-owner \
         | pg_restore -d "$NISHON_OWNER" --no-owner \
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

    tasdiq_0071 "$NISHON_OWNER"
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

    # --- KORPUS SENZI — C GURUHI UCHUN YAGONA O'LCHOV --------------------
    # O'n bir to'plam "sinov ma'lumoti yetarli emas" shaklida yiqiladi:
    #   kod_pilot   FK: code=(26.30) `dim_good_code` da yo'q
    #   kodlash     lug'at uch darajada emas / 5-daraja bo'sh
    #   matn_moslik bo'lim 26 asosan TOVAR (>90%, hozir 0) -- 0/225
    #   embed_qamrov qamrov foizi None%
    #   rag_sifat   dalil topilmadi (0/0)
    #   ...
    #
    # Bular ALOHIDA nuqson emas: hammasi NUSXADAGI KORPUSGA bog'liq.
    # `dim_good_code` ning o'zi ham STATIK SEED EMAS — u
    # `rebuild_good_code_dict()` bilan KORPUSDAN qayta quriladi
    # (`schema_patch_goodcode.sql:181`). Ya'ni lug'atda qaysi kod
    # borligi bazadagi ma'lumotdan kelib chiqadi.
    #
    # Shuning uchun taxmin qilish o'rniga SANAYMIZ. Bu FAQAT O'QIYDI.
    log "--- KORPUS SENZI (nusxada) ---"
    psql "$NISHON_OWNER" -v ON_ERROR_STOP=1 -qtA -F' | ' -c "
      SELECT 'dim_good_code jami', count(*)::text FROM dim_good_code
      UNION ALL SELECT 'dim_good_code daraja ' || level::text, count(*)::text
                  FROM dim_good_code GROUP BY level
      UNION ALL SELECT 'dim_good_code 26.30 bor?',
                  (EXISTS(SELECT 1 FROM dim_good_code WHERE code='26.30'))::text
      UNION ALL SELECT 'catalog_product', count(*)::text FROM catalog_product
      UNION ALL SELECT 'catalog_product_code', count(*)::text FROM catalog_product_code
      UNION ALL SELECT 'tender', count(*)::text FROM tender
      UNION ALL SELECT 'doc_chunk', count(*)::text FROM doc_chunk
      ORDER BY 1" 2>&1 | sed 's/^/    /' >&2 || true

    # --- ESKI SINOV HISOBLARI — NUSXADA, AYTIB TOZALANADI -------------------
    # `zztest_*` va `zzyuklama_*` — sinovlar yaratadigan kompaniyalar.
    # Sinovlarning O'ZI ularni oxirida faolsizlantiradi
    # (`topshiriq_test`, `yuklama_test:839`), lekin YIQILGAN yurish
    # buni bajarmaydi va hisob FAOL qolib ketadi.
    #
    # O'LCHANGAN OQIBAT: staging da 4 ta faol qoldiq (id 8..11) va
    # ular `sole_company_id()` ga tayangan to'plamlarni yiqitardi —
    # ya'ni bir sinovning qoldig'i boshqalarini o'ldirardi.
    #
    # BU YERDA — NUSXADA. `tenderai_staging` ga TEGILMAYDI: darvoza
    # o'lchov vositasi, tozalash vositasi emas.
    #
    # JIM EMAS. Topilgan har bir qoldiq NOMI bilan chiqadi: jimgina
    # tozalash buzuq fixture hayot siklini abadiy yashirardi.
    QOLDIQ="$(psql "$NISHON_OWNER" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT string_agg(username, ', ' ORDER BY id)
           FROM company_account WHERE username LIKE 'zz%' AND active")"
    if [ -n "$QOLDIQ" ]; then
        log "NUSXADA eski sinov hisoblari: $QOLDIQ"
        log "  (sabab: yiqilgan yurish tozalamagan; nusxada o'chiriladi)"
        psql "$NISHON_OWNER" -v ON_ERROR_STOP=1 -qtA -c \
            "UPDATE company_account SET active = false
              WHERE username LIKE 'zz%' AND active" >/dev/null
    else
        log "nusxada eski sinov hisobi yo'q"
    fi
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
    # QOLGAN ARGUMENTLAR `run_tests.py` GA UZATILADI.
    #
    # NEGA: bitta to'plamni tuzatayotganda butun 44 to'plamni yurgizish
    # ~4 daqiqa oladi va chiqishni ko'mib yuboradi. `run_tests.py` da
    # `--only <naqsh>` allaqachon bor edi, lekin darvoza uni uzatmasdi.
    #
    #     tender-darvoza sinov <baza> --only import
    #
    # QO'RIQCHALAR O'ZGARMAYDI: `zz*` sanog'i, 0071 tasdig'i va
    # tozalash HAR HOLDA yuradi -- ular argumentga bog'liq emas.
    shift 2 2>/dev/null || shift $#
    nom_tekshir "$BAZA"
    : "${XT_DB_DSN:?sinov uchun XT_DB_DSN kerak (ilova roli)}"
    SINOV_DSN="$(dsn_baza "$XT_DB_DSN" "$BAZA")"
    darvoza_ildiz
    # QAYSI ROL — AYTILADI. §9 talabi: oddiy sinovlar ILOVA roli
    # bilan yurishi kerak. Buni "shunday deb o'ylash" yetarli emas;
    # DSN dan rol nomi ajratib chiqariladi va jurnalga yoziladi.
    # PAROL CHIQMAYDI — faqat `user=` qiymati.
    SINOV_ROL="$(printf '%s' "$SINOV_DSN" | sed -nE 's/.*user=([A-Za-z0-9_]+).*/\1/p')"
    if [ "$SINOV_ROL" = "tai_test_admin" ]; then
        echo "XATO: oddiy sinovlar ADMIN roli bilan yurmaydi." >&2
        echo "      XT_DB_DSN ilova rolini ko'rsatishi kerak." >&2
        exit 2
    fi
    log "sinov bazasi: $BAZA  rol: ${SINOV_ROL:-ANIQLANMADI}"

    # --- PYTHON BOG'LIQLIKLARI — OLDINDAN VA AYTIB ------------------------
    # O'LCHANGAN (2026-09-08): beshta to'plam import da yiqildi —
    #
    #     from dotenv import load_dotenv
    #     ModuleNotFoundError: No module named 'dotenv'
    #
    # Sabab KODDA emas: tanlangan interpretatorda bog'liqlik yo'q edi.
    # Qolgan to'plamlar `dotenv` ni try/except bilan olgani uchun jim
    # o'tib ketardi, ya'ni bitta muhit nuqsoni BESHTA "sinov yiqildi"
    # bo'lib ko'rinardi.
    #
    # Endi interpretator AYTILADI va bog'liqliklar sinovlardan OLDIN
    # tekshiriladi. Yetishmasa darvoza to'xtaydi va QAYSI python,
    # QAYSI modul yetishmayotganini nomma-nom aytadi.
    # INTERPRETATOR ISHONCHLI AYTILADI. `$PY` ning O'ZI yetarli emas:
    # `run_tests.py` bolalarni `sys.executable` bilan yurgizadi va
    # agar u boshqa python bo'lsa, bog'liqlik tekshiruvi BOSHQA
    # muhitni o'lchagan bo'lardi. Shuning uchun `sys.executable` va
    # `dotenv` ning JOYI aynan o'sha interpretatordan so'raladi.
    # --- EMBEDDING MODELI KESHI ------------------------------------------
    # `HF_HOME` FAQAT systemd birligida bor
    # (`Environment=HF_HOME=/opt/tenderai/%i/var/hf`), ya'ni darvoza
    # jarayoniga YETIB KELMAYDI.
    #
    # O'LCHANGAN OQIBAT (2026-09-08): `yuklama_test` modelni HAR
    # YURISHDA huggingface.co dan yuklab olishga urinardi — jurnal
    # o'nlab HTTP so'rov bilan to'lardi, to'plam sekinlashardi va
    # o'ldirilganda `zzyuklama_*` fiksturasi FAOL qolib ketardi.
    # Sizish qo'riqchisi buni to'g'ri ushladi ("KEYIN faol zz*: 2"),
    # lekin sabab tarmoqda edi.
    #
    # Reliz keshida model ALLAQACHON bor (~471 MB) — xizmat uni
    # o'sha yerdan o'qiydi. Darvoza ham AYNI keshni ishlatsa:
    # tarmoq kerak emas, yurish tez va TAKRORLANADIGAN bo'ladi.
    HF_KESH="${HF_HOME:-/opt/tenderai/${APP_ENV:-staging}/var/hf}"
    # OFLAYN. Model keshda bor, lekin kutubxona baribir HF Hub ga
    # metama'lumot uchun boradi: o'lchandi — 17 ta HTTP so'rov,
    # "unauthenticated requests" ogohlantirishi va `yuklama_test`
    # ning sekinlashib o'ldirilishi (fikstura FAOL qolib ketardi).
    # Darvoza tarmoqqa bog'liq bo'lmasligi kerak.
    log "HF_HOME: $HF_KESH  (HF_HUB_OFFLINE=1)"

    log "python: $PY"
    log "sys.executable: $("$PY" -c 'import sys;print(sys.executable)' 2>&1 | tail -1)"
    log "dotenv: $("$PY" -c 'import dotenv;print(dotenv.__file__)' 2>&1 | tail -1)"

    # --- BOLA JARAYONI O'LCHOVI ------------------------------------------
    # `run_tests.py` to'plamlarni `[sys.executable, <yol>]` bilan,
    # `cwd=<ildiz>` va `env=dict(os.environ, ...)` bilan yurgizadi.
    # Ota jarayonda `dotenv` BOR, bola esa "yo'q" deydi — farq
    # qayerdaligini TAXMIN QILMASDAN o'lchaymiz: probe AYNAN o'sha
    # shaklda yurgiziladi.
    cat > "${ILDIZ_TOLIQ}/_darvoza_probe.py" <<'PROBE'
import importlib.util as iu, os, sys
print("uid/gid   :", os.getuid(), os.getgid())
print("cwd       :", os.getcwd())
print("argv0     :", sys.argv[0])
print("executable:", sys.executable)
print("prefix    :", sys.prefix)
print("base_pref :", sys.base_prefix)
print("version   :", sys.version.split()[0])
print("PATH      :", (os.environ.get("PATH") or "")[:160])
print("PYTHONPATH:", os.environ.get("PYTHONPATH"))
print("PYTHONHOME:", os.environ.get("PYTHONHOME"))
print("VIRTUAL_ENV:", os.environ.get("VIRTUAL_ENV"))
print("find_spec(dotenv):", iu.find_spec("dotenv"))
print("sys.path  :")
for q in sys.path:
    print("   ", q or "<bo'sh>")
PROBE
    # PROBE B — AYNAN SUITE JOYIDAN. Birinchi probe ildizdan yuradi va
    # u O'TDI; to'plamlar esa `_tests/` dan yuradi va `sys.path` ga
    # ikkita yo'l qo'shadi. Farq shu ikkisining orasida qoldi,
    # shuning uchun ikkinchi probe AYNAN o'sha ketma-ketlikni
    # takrorlaydi: `_tests/` da turadi, o'sha `sys.path.insert` larni
    # qiladi va `konsol`/`rejim` ni `dotenv` dan OLDIN import qiladi.
    cat > "${ILDIZ_TOLIQ}/_tests/_darvoza_probe2.py" <<'PROBE2'
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
print("B: argv0    :", sys.argv[0])
print("B: executable:", sys.executable)
print("B: prefix   :", sys.prefix)
print("B: path[0..2]:", sys.path[:3])
try:
    import konsol, rejim
    print("B: konsol/rejim OK")
    konsol.sozla()
except Exception as e:
    print("B: konsol/rejim XATO:", type(e).__name__, e)
try:
    from dotenv import load_dotenv
    print("B: dotenv OK")
except Exception as e:
    print("B: dotenv XATO:", type(e).__name__, e)
    print("B: sys.path:")
    for q in sys.path:
        print("     ", q or "<bosh>")
PROBE2
    log "--- BOLA PROBE A (ildizdan) ---"
    ( cd "$ILDIZ_TOLIQ" && PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 \
        "$PY" "${ILDIZ_TOLIQ}/_darvoza_probe.py" 2>&1 | sed 's/^/    /' ) >&2 || true
    # PROBE C — HAQIQIY TO'PLAM, `run_tests.py` bergan AYNI argument
    # bilan. A va B probe lari o'tdi, ya'ni joy ham, ketma-ketlik ham
    # aybdor emas. Qolgan yagona farq — to'plamning O'ZI va unga
    # uzatiladigan bayroq. Bu probe uni bevosita yurgizadi.
    log "--- BOLA PROBE C (aktor_test --tarmoqsiz, bevosita) ---"
    ( cd "$ILDIZ_TOLIQ" && PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 \
        "$PY" "${ILDIZ_TOLIQ}/_tests/aktor_test.py" --tarmoqsiz 2>&1 \
        | tail -12 | sed 's/^/    /' ) >&2 || true

    log "--- BOLA PROBE B (_tests dan, suite ketma-ketligi) ---"
    ( cd "$ILDIZ_TOLIQ" && PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 \
        "$PY" "${ILDIZ_TOLIQ}/_tests/_darvoza_probe2.py" 2>&1 | sed 's/^/    /' ) >&2 || true
    if ! "$PY" -c "import dotenv, psycopg2" >/dev/null 2>&1; then
        _zaxira="/opt/tenderai/${APP_ENV:-staging}/current/.venv/bin/python"
        if [ -x "$_zaxira" ] && "$_zaxira" -c "import dotenv, psycopg2" >/dev/null 2>&1; then
            log "bog'liqlik yo'q edi -> reliz venv iga o'tildi: $_zaxira"
            PY="$_zaxira"
        else
            echo "XATO: sinov interpretatorida bog'liqlik yetishmaydi." >&2
            echo "      python: $PY" >&2
            "$PY" -c "import dotenv" 2>&1 | tail -1 >&2
            echo "      Zaxira ham yaramadi: $_zaxira" >&2
            exit 1
        fi
    fi

    # --- MUHIT SHARTNOMASI ------------------------------------------------
    # `aktor_test`, `inson_dalil_test`, `xavfsizlik_test` ilovaning
    # ishga tushish tekshiruvini chaqiradi va u `APP_PUBLIC_URL` ni
    # TALAB qiladi. Darvoza jarayoniga u YETIB KELMASA uchala to'plam
    # "APP_PUBLIC_URL=https://<domen> kerak" bilan yiqiladi —
    # holbuki sabab KODDA emas, uzatilmagan o'zgaruvchida.
    #
    # QIYMAT O'YLAB TOPILMAYDI. Bu yerda soxta URL qo'yish
    # `xavfsizlik_test` ni ALDAB yashil qilardi — u aynan URL
    # siyosatini o'lchaydi. Shuning uchun yo'q bo'lsa TO'XTAYMIZ va
    # NIMA yetishmayotganini aytamiz.
    if [ -z "${APP_PUBLIC_URL:-}" ]; then
        echo "XATO: darvoza jarayoniga APP_PUBLIC_URL yetib kelmadi." >&2
        echo "      Usiz aktor_test, inson_dalil_test va xavfsizlik_test" >&2
        echo "      ilovaning ishga tushish tekshiruvida yiqiladi — sabab" >&2
        echo "      KODDA emas, uzatilmagan o'zgaruvchida." >&2
        echo "      Qiymat SIR EMAS; o'rama uni uzatishi kerak:" >&2
        echo "        APP_PUBLIC_URL, AUTH_COOKIE_SECURE" >&2
        echo "      Soxta qiymat QO'YILMAYDI: xavfsizlik_test aynan URL" >&2
        echo "      siyosatini o'lchaydi va aldangan yashil bermasin." >&2
        exit 1
    fi

    # --- SIZISH QO'RIQCHISI: OLDIN --------------------------------------
    OLDIN="$(psql "$SINOV_DSN" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT count(*) FROM company_account
          WHERE username LIKE 'zz%' AND active")"
    log "sinovdan OLDIN faol zz* hisoblar: $OLDIN"
    if [ "$OLDIN" != "0" ]; then
        echo "XATO: sinov boshlanishidan OLDIN faol qoldiq bor ($OLDIN)." >&2
        echo "      Nusxa tozalanmagan — darvoza natijasi ishonchsiz." >&2
        exit 1
    fi

    cd "$ILDIZ_TOLIQ"
    # IMTIYOZ AJRATILGAN: oddiy to'plamlar `XT_DB_DSN` (ilova roli)
    # bilan yuradi; `XT_DB_DSN_TEST_ADMIN` ham uzatiladi, lekin undan
    # FAQAT `migratsiya_test` ning baza yaratish/tashlash yordamchisi
    # foydalanadi (`_admin_kon()`). Butun to'plam admin roliga
    # O'TMAYDI.
    ADMIN_DSN="$(dsn_baza "${XT_DB_DSN_TEST_ADMIN:-}" "postgres")"
    set +e
    TENDERAI_DEBUG_LAUNCH=1 \
    TENDERAI_PY="$PY" \
    HF_HOME="$HF_KESH" \
    HF_HUB_OFFLINE=1 \
    XT_DB_DSN="$SINOV_DSN" \
    XT_DB_DSN_TEST_ADMIN="$ADMIN_DSN" \
    APP_ENV=staging \
    APP_PUBLIC_URL="$APP_PUBLIC_URL" \
    AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-1}" \
        "${PY:-python3}" run_tests.py "$@"
    SINOV_KOD=$?
    set -e

    # --- YIQILGAN TO'PLAMLAR TAFSILOTI -----------------------------------
    # `run_tests.py` har to'plam chiqishini `_test_natija/<nom>.log` ga
    # yozadi, lekin darvoza jurnaliga faqat BITTA KESILGAN qator
    # tushadi:
    #
    #     [XATO] kod_pilot_test  XULOSA QATORI YO'Q — DETAIL:  Key (code)=(26.30)...
    #
    # Vaqtinchalik daraxt esa yurish oxirida O'CHIRILADI, ya'ni to'liq
    # traceback HECH QAYERGA yetib bormasdi va har tahlil uchun
    # darvozani qayta yurgizish kerak bo'lardi.
    #
    # CHEGARALANGAN: har to'plamdan oxirgi 25 qator. Maqsad — sababni
    # ko'rsatish, jurnalni to'ldirish emas.
    NAT="${ILDIZ_TOLIQ}/_test_natija"
    if [ "$SINOV_KOD" -ne 0 ] && [ -d "$NAT" ]; then
        log "--- YIQILGAN TO'PLAMLAR: muhim qatorlar (niqoblangan) ---"
        "${PY:-python3}" - "$NAT" <<'PYEOF' >&2 || true
import io, json, os, re, sys

# SIR CHIQMAYDI. Bu chiqish jurnalga va hisobotlarga ketadi, ya'ni
# ko'p qo'ldan o'tadi. Niqob QIYMATNI oladi, KALIT NOMINI qoldiradi —
# nosozlik izlash uchun nom yetarli, qiymat esa hech qachon kerak emas.
_SIR = [
    (re.compile(r"(password\s*=\s*)\S+", re.I), r"\1***"),
    (re.compile(r"(passwd\s*=\s*)\S+", re.I), r"\1***"),
    (re.compile(r"(api[_-]?key\s*[=:]\s*)\S+", re.I), r"\1***"),
    (re.compile(r"(token\s*[=:]\s*)\S+", re.I), r"\1***"),
    (re.compile(r"(authorization\s*:\s*)\S+", re.I), r"\1***"),
    (re.compile(r"(service[_-]?key\s*[=:]\s*)\S+", re.I), r"\1***"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-***"),
    (re.compile(r"(postgres(?:ql)?://[^:@\s]+:)[^@\s]+@"), r"\1***@"),
]


def niqob(q):
    for rx, alm in _SIR:
        q = rx.sub(alm, q)
    return q


nat = sys.argv[1]
try:
    x = json.load(io.open(os.path.join(nat, "xulosa.json"), encoding="utf-8"))
except Exception as e:
    print(f"[tafsilot] xulosa.json o'qilmadi: {e}"); raise SystemExit(0)
# `yiqilgan` — yurgizuvchining O'ZI tuzgan ro'yxat (443-qator).
# Uni qayta hisoblash ikkinchi haqiqat manbai bo'lardi.
# CHIQISH KODI SARLAVHAGA CHIQADI.
#
# `subprocess` signaldan o'lgan bolani MANFIY kod bilan qaytaradi
# (`-9` = SIGKILL, `-15` = SIGTERM). Bu farq HAL QILUVCHI: o'z-o'zidan
# yiqilgan sinov (kod 1) va TASHQARIDAN o'ldirilgan sinov (kod -9)
# butunlay boshqa nosozliklar, lekin darvoza jurnalida ikkalasi ham
# "XULOSA QATORI YO'Q" bo'lib ko'rinardi.
_kodlar = {t.get("nom"): t.get("kod") for t in (x.get("toplamlar") or [])}


def _kod_izoh(k):
    if k is None:
        return "kod=?"
    if k < 0:
        _nom = {-9: "SIGKILL", -15: "SIGTERM", -2: "SIGINT",
                -6: "SIGABRT", -11: "SIGSEGV"}.get(k, f"signal {-k}")
        return f"kod={k} ({_nom} — TASHQARIDAN o'ldirilgan)"
    return f"kod={k}"


for nom in x.get("yiqilgan") or []:
    if not nom:
        continue
    yol = os.path.join(nat, f"{nom}.log")
    _bosh = f"===== {nom} [{_kod_izoh(_kodlar.get(nom))}] "
    print("\n" + _bosh + "=" * max(3, 78 - len(_bosh)))
    try:
        qatorlar = io.open(yol, encoding="utf-8", errors="replace").read().splitlines()
    except Exception as e:
        print(f"  [log o'qilmadi: {e}]")
        continue

    # NAQSH BO'YICHA + KONTEKST. Oxirgi N qator YETARLI EMAS: ko'p
    # to'plam yiqilishni O'RTADA chop etadi va oxirida faqat xulosa
    # qoladi — shuning uchun oltita to'plam tasniflanmay qolgandi.
    # `[tashxis]` — ATAYLAB ro'yxatda. Sinov ichidagi tashxis qatorlari
    # naqshga tushmasa, ular yozilgani bilan darvoza jurnaliga
    # YETIB BORMAYDI: aynan shu bo'ldi va `dotenv` sababi yana bir
    # yurishga cho'zildi.
    # QAVSSIZ SHAKL HAM OLINADI. To'plamlar ikki uslubda yozadi:
    # `[XATO] nom` va `XATO  nom: sabab` (masalan `pricing_test`,
    # `notify_test`). Faqat qavslisini qidirish `pricing_test` ning
    # yagona yiqilgan tekshiruvini KO'RINMAS qilgan edi.
    # IKKI BOSQICHLI TANLOV.
    #
    # O'LCHANGAN NUQSON (2026-09-09): naqshda `kutilgan|expected|actual`
    # bor edi va ular O'TGAN tekshiruvlarda ham uchraydi. 422
    # tekshiruvli `deploy_test` da 120 qatorlik byudjet o'sha PASS
    # qatorlari bilan to'lib ketdi va YAGONA yiqilgan tekshiruv
    # kesilib qoldi -- ya'ni tafsilot bor edi, lekin javob yo'q edi.
    #
    # Endi avval FAQAT yiqilish belgilari qidiriladi; "kutilgan/actual"
    # kabi yumshoq naqshlar ularning ATROFIDA kontekst sifatida
    # keladi, o'zi mustaqil sabab bo'lmaydi.
    RX_YIQ = re.compile(r"\[FAIL\]|\[XATO\]|\[tashxis\]|^\s*XATO\s|^\s*FAIL\s"
                        r"|YIQILDI:|Traceback"
                        r"|AssertionError|Error:|error:|Exception")
    RX_YUMSHOQ = re.compile(r"kutilgan|expected|actual")

    def _tanla(rx, atrof):
        t = set()
        for i, q in enumerate(qatorlar):
            if rx.search(q):
                for j in range(max(0, i - atrof), min(len(qatorlar), i + atrof + 1)):
                    t.add(j)
        return t

    tanlangan = _tanla(RX_YIQ, 3)
    if not tanlangan:                      # yiqilish belgisi yo'q -> yumshoq
        tanlangan = _tanla(RX_YUMSHOQ, 2)
    if not tanlangan:                      # hech narsa mos kelmasa — oxiri
        tanlangan = set(range(max(0, len(qatorlar) - 25), len(qatorlar)))

    oxirgi = -2
    chiqarildi = 0
    for i in sorted(tanlangan):
        if chiqarildi >= 120:
            print("  … (chegara: 120 qator)")
            break
        if i != oxirgi + 1:
            print("  ---")
        print("  " + niqob(qatorlar[i]))
        oxirgi = i
        chiqarildi += 1
PYEOF
    fi

    # --- SIZISH QO'RIQCHISI: KEYIN --------------------------------------
    # Sinovlar yiqilgan bo'lsa ham o'lchanadi: sizish AYRIM nosozlik
    # va u yiqilish bilan birga yashirinib qolmasin.
    # NOMI BILAN. Faqat SON berilsa "qaysi to'plam sizdirdi" degan
    # savol ochiq qolardi va uni topish uchun butun jurnalni qayta
    # o'qish kerak bo'lardi. Prefiks to'plam nomini o'zida saqlaydi
    # (`zzyuklama_*` -> `yuklama_test`), ya'ni nom AYBDORNI ko'rsatadi.
    KEYIN_NOM="$(psql "$SINOV_DSN" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT COALESCE(string_agg(username, ', ' ORDER BY id), '-')
           FROM company_account WHERE username LIKE 'zz%' AND active")"
    KEYIN="$(psql "$SINOV_DSN" -v ON_ERROR_STOP=1 -qtA -c \
        "SELECT count(*) FROM company_account
          WHERE username LIKE 'zz%' AND active")"
    log "sinovdan KEYIN faol zz* hisoblar: $KEYIN  ($KEYIN_NOM)"
    if [ "$KEYIN" != "0" ]; then
        echo "XATO: sinov FAOL qoldiq qoldirdi ($KEYIN): $KEYIN_NOM" >&2
        echo "      Odatda bu to'plam O'LDIRILGANINI bildiradi:" >&2
        echo "      \`finally\` tozalashi jarayon tirik bo'lgandagina yuradi." >&2
        echo "      Bu 'jimgina tozalab, PASS' bo'lmaydi: darvoza YIQILADI." >&2
        exit 1
    fi
    exit "$SINOV_KOD"
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

tasdiq)
    # FAQAT SINOV UCHUN. `tender-darvoza` o'ramasi bu amalni
    # ochmaydi (uning ruxsat ro'yxati: tekshir|yarat|sinov|tozala).
    tasdiq_0071 "${2:?dsn kerak}"
    log "TASDIQ: PASS"
    ;;

nom)
    printf '%s%s\n' "$DARVOZA_PREFIKS" "$(date +%Y%m%d_%H%M%S)"
    ;;

*) echo "Noma'lum amal: $AMAL" >&2; exit 2 ;;
esac
