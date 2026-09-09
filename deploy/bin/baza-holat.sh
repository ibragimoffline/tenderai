#!/usr/bin/env bash
# =============================================================================
# BAZA HOLATI — FAQAT O'QISH
# =============================================================================
#     baza-holat.sh <staging|production>
#
# NEGA ALOHIDA ASBOB. `darvoza-baza.sh` darvoza uchun yozilgan: unda
# `yarat` va `tozala` amallari bor va u staging DSN lariga bog'langan.
# Ishlab chiqarish holatini o'qish uchun O'ZGARTIRA OLADIGAN asbobni
# ishlatish noto'g'ri bo'lardi -- xato amal bilan chalkashtirish
# ehtimoli bor joyda "faqat qarayapman" degan niyat yetarli emas.
#
# BU SKRIPT HECH NARSANI O'ZGARTIRMAYDI. Faqat `SELECT`. `CREATE`,
# `ALTER`, `DROP`, `GRANT`, `REVOKE`, `INSERT`, `UPDATE`, `DELETE`
# umuman yo'q va buni `_tests/deploy_test.py` qo'riqlaydi.
#
# CHIQISH KODI: siljish topilsa 1, toza bo'lsa 0. Ya'ni uni
# joylashtiruvdan oldingi DALIL sifatida ishlatsa bo'ladi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: baza-holat.sh <staging|production>}"
case "$MUHIT" in staging|production) ;; *) echo "Noma'lum muhit: $MUHIT" >&2; exit 2 ;; esac
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
[ "$(id -u)" = "0" ] || { echo "root kerak (muhit fayli 0640 root:tenderai)" >&2; exit 1; }
[ -f "$ENVFILE" ] || { echo "muhit fayli yo'q: $ENVFILE" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a
# `${VAR:?xabar}` ISHLATILMAYDI: xabardagi apostrof (`bo'sh`) bash
# uchun tirnoq ochadi va skript SINTAKSIS xatosi bilan yiqiladi.
# Bu tuzoq loyihada `backup.sh` da allaqachon bir marta tuzatilgan.
if [ -z "${XT_DB_DSN_OWNER:-}" ]; then
    echo "XATO: XT_DB_DSN_OWNER bo'sh ($ENVFILE)" >&2
    exit 1
fi

SILJISH=0
belgi() { SILJISH=1; printf '  [SILJISH] %s\n' "$*"; }
ok()    { printf '  [ok]      %s\n' "$*"; }
q()     { psql "$XT_DB_DSN_OWNER" -v ON_ERROR_STOP=1 -qtA -c "$1"; }

echo "=============================================================="
echo "BAZA HOLATI — ${MUHIT}  (FAQAT O'QISH)"
echo "=============================================================="

# --- 1) MIGRATSIYA ------------------------------------------------------------
echo
echo "1. MIGRATSIYA"
JADVAL="$(q "SELECT count(*) FROM information_schema.tables
              WHERE table_schema='public' AND table_name='schema_migration'")"
if [ "$JADVAL" != "1" ]; then
    belgi "schema_migration jadvali YO'Q — migratsiya tarixi yuritilmagan"
else
    ok "schema_migration jadvali bor"
    echo "  qo'llangan     : $(q "SELECT count(*) FROM schema_migration WHERE holat IN ('ok','bootstrap')")"
    echo "  oxirgi         : $(q "SELECT coalesce(max(migratsiya_id),'-') FROM schema_migration WHERE holat IN ('ok','bootstrap')")"
    UZILGAN="$(q "SELECT count(*) FROM schema_migration WHERE holat='boshlandi'")"
    [ "$UZILGAN" = "0" ] && ok "uzilgan migratsiya yo'q" \
        || belgi "UZILGAN migratsiya: ${UZILGAN} ta (holat='boshlandi')"
    XATOLI="$(q "SELECT count(*) FROM schema_migration WHERE holat='xato'")"
    [ "$XATOLI" = "0" ] && ok "xatoli migratsiya yo'q" \
        || belgi "XATOLI migratsiya: ${XATOLI} ta"
    for M in 0084_erp_chegara 0085_auth_eski_tozalash; do
        H="$(q "SELECT coalesce(max(holat),'yoq') FROM schema_migration
                 WHERE migratsiya_id = '${M}'")"
        case "$H" in
            ok|bootstrap) ok "${M}: ${H}" ;;
            yoq)          belgi "${M}: QO'LLANMAGAN" ;;
            *)            belgi "${M}: holat=${H}" ;;
        esac
    done
fi

# --- 2) ESKI AUTH JADVALI -----------------------------------------------------
echo
echo "2. ESKI AUTH JADVALI"
if [ "$(q "SELECT (to_regclass('public.app_user') IS NOT NULL)::text")" = "true" ]; then
    belgi "public.app_user HAMON MAVJUD (0085 qo'llanmagan)"
else
    ok "public.app_user yo'q — 0085 ning kutilgan natijasi"
fi

# --- 3) ERP SHARTNOMASI -------------------------------------------------------
echo
echo "3. ERP SHARTNOMASI (tai_app ga ruxsat etilgan BESH ko'rinish)"
if [ "$(q "SELECT count(*) FROM information_schema.schemata WHERE schema_name='erp'")" = "0" ]; then
    echo "  erp sxemasi yo'q — tekshirilmadi"
else
    RUXSAT="'v_tai_actor','v_tender_status','v_stock','v_stock_balance','v_client_document'"
    echo "  --- tai_app ga erp da berilgan HAMMA huquq ---"
    q "SELECT '    ' || c.relkind::text || ' erp.' || c.relname || ' -> ' || a.privilege_type
         FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
              aclexplode(c.relacl) a
        WHERE n.nspname='erp' AND a.grantee::regrole::text='tai_app'
        ORDER BY c.relname, a.privilege_type" || true
    N_RUXSAT="$(q "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='erp' AND c.relkind IN ('r','v','m','p','f')
                      AND has_table_privilege('tai_app', c.oid, 'SELECT')
                      AND c.relname IN (${RUXSAT})")"
    N_ORTIQ="$(q "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='erp' AND c.relkind IN ('r','v','m','p','f')
                     AND has_table_privilege('tai_app', c.oid, 'SELECT')
                     AND c.relname NOT IN (${RUXSAT})")"
    echo "  ruxsat etilgan  : ${N_RUXSAT} / 5"
    if [ "$N_ORTIQ" = "0" ]; then ok "ortiqcha SELECT obyekt: 0"
    else
        belgi "ORTIQCHA SELECT obyekt: ${N_ORTIQ} ta"
        q "SELECT '    ortiqcha: erp.' || c.relname
             FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='erp' AND c.relkind IN ('r','v','m','p','f')
              AND has_table_privilege('tai_app', c.oid, 'SELECT')
              AND c.relname NOT IN (${RUXSAT}) ORDER BY 1" || true
    fi
    # SUKUT HUQUQ — O'ZINI QAYTA TIKLAYDIGAN SILJISH.
    # Bir martalik REVOKE yetarli emas: sukut huquq qolsa keyingi
    # ERP migratsiyasi siljishni QAYTA yaratardi.
    N_SUKUT="$(q "SELECT count(*) FROM pg_default_acl d
                    JOIN pg_namespace n ON n.oid = d.defaclnamespace,
                         aclexplode(d.defaclacl) a
                   WHERE n.nspname='erp' AND a.grantee::regrole::text='tai_app'")"
    if [ "$N_SUKUT" = "0" ]; then ok "erp da tai_app uchun sukut huquq: 0"
    else belgi "XATARLI SUKUT HUQUQ: erp da tai_app uchun ${N_SUKUT} ta"; fi
fi

# --- 4) ROL INVARIANTLARI -----------------------------------------------------
echo
echo "4. ROL INVARIANTLARI"
rol() { q "SELECT coalesce((SELECT ${2} FROM pg_roles WHERE rolname='${1}')::text,'-')"; }
for R in tai_service tai_app tai_owner tai_test_admin; do
    printf '  %-15s super=%s createdb=%s createrole=%s login=%s\n' "$R" \
        "$(rol "$R" rolsuper)" "$(rol "$R" rolcreatedb)" \
        "$(rol "$R" rolcreaterole)" "$(rol "$R" rolcanlogin)"
done
# ILOVA ROLI HECH QACHON IMTIYOZLI BO'LMASIN.
[ "$(rol tai_service rolsuper)"    = "false" ] && ok "tai_service superuser=false" \
    || belgi "tai_service SUPERUSER"
[ "$(rol tai_service rolcreatedb)" = "false" ] && ok "tai_service createdb=false" \
    || belgi "tai_service CREATEDB"
[ "$(rol tai_app rolcanlogin)"     = "false" ] && ok "tai_app login=false (guruh roli)" \
    || belgi "tai_app LOGIN qila oladi"

echo
echo "=============================================================="
if [ "$SILJISH" -eq 0 ]; then
    echo "NATIJA: SILJISH YO'Q"
else
    echo "NATIJA: SILJISH BOR (yuqorida [SILJISH] deb belgilangan)"
fi
echo "=============================================================="
exit "$SILJISH"
