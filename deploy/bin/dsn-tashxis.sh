#!/usr/bin/env bash
# =============================================================================
# DSN TASHXISI — QAYSI QATLAMDA YIQILADI
# =============================================================================
#     dsn-tashxis.sh <staging|production> [DSN_NOMI]
#
# Standart `DSN_NOMI` — `XT_DB_DSN_OWNER`.
#
# NEGA ALOHIDA ASBOB. `oldindan-tekshir.sh` faqat "ULANMADI" deydi va
# bu YETARLI EMAS: sabab tarmoq, `pg_hba`, parol, baza nomi yoki rol
# bo'lishi mumkin va ularning TUZATISHI butunlay boshqacha. "Parol
# eskirgan" deb taxmin qilib parolni almashtirish esa eng xatarli
# yo'l -- klaster rollari IKKALA muhitga umumiy, ya'ni production
# uchun qilingan almashtirish staging ni ham sindiradi.
#
# SIR CHIQMAYDI. Skript DSN ni tahlil qiladi va FAQAT quyidagilarni
# bosadi: host, port, baza, rol, sslmode va parol BOR-YO'QLIGI.
# Parolning o'zi hech qachon, hech qayerga chiqmaydi -- ekranga ham,
# jurnalga ham, xato matniga ham.
#
# HECH NARSA O'ZGARTIRMAYDI. Faqat o'qiydi va ulanib ko'radi.
# =============================================================================
set -euo pipefail

MUHIT="${1:?foydalanish: dsn-tashxis.sh <staging|production> [DSN_NOMI]}"
NOM="${2:-XT_DB_DSN_OWNER}"
case "$MUHIT" in staging|production) ;; *) echo "Noma'lum muhit: $MUHIT" >&2; exit 2 ;; esac
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"

[ "$(id -u)" = "0" ] || { echo "root kerak (muhit fayli 0640 root:tenderai)" >&2; exit 1; }
[ -f "$ENVFILE" ] || { echo "muhit fayli yo'q: $ENVFILE" >&2; exit 1; }

echo "=============================================================="
echo "DSN TASHXISI — ${MUHIT} / ${NOM}"
echo "manba: $ENVFILE"
echo "=============================================================="

set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a
eval "DSN=\${${NOM}:-}"

if [ -z "${DSN:-}" ]; then
    echo "1. QIYMAT     : YO'Q (o'zgaruvchi bo'sh yoki e'lon qilinmagan)"
    echo
    echo "QATLAM: DSN_CONFIG"
    exit 1
fi

# --- 1) TAHLIL — SIRSIZ -------------------------------------------------------
# Python ishlatiladi: DSN ikki shaklda bo'lishi mumkin (kalit=qiymat
# va URI) va ularni qobiqda ajratish jimgina xato qilardi.
python3 - "$DSN" <<'PY'
import sys, urllib.parse as up
d = sys.argv[1].strip()
f = {}
if d.startswith(("postgres://", "postgresql://")):
    u = up.urlparse(d)
    f["host"] = u.hostname or ""
    f["port"] = str(u.port or "")
    f["dbname"] = (u.path or "/").lstrip("/")
    f["user"] = u.username or ""
    f["password"] = u.password or ""
    f.update({k: v[0] for k, v in up.parse_qs(u.query).items()})
    shakl = "URI"
else:
    for qism in d.split():
        if "=" in qism:
            k, _, v = qism.partition("=")
            f[k.strip()] = v.strip().strip("'\"")
    shakl = "kalit=qiymat"

# FAQAT SHU MAYDONLAR BOSILADI. Ro'yxat YOPIQ: yangi maydon
# qo'shilsa u O'Z-O'ZIDAN chiqmaydi -- sir tasodifan sizib
# ketmasligi uchun.
print(f"1. SHAKL      : {shakl}")
print(f"   host       : {f.get('host') or '(berilmagan -> unix soket)'}")
print(f"   port       : {f.get('port') or '(berilmagan -> 5432)'}")
print(f"   db         : {f.get('dbname') or '(berilmagan)'}")
print(f"   user       : {f.get('user') or '(berilmagan -> OS foydalanuvchisi)'}")
print(f"   sslmode    : {f.get('sslmode') or '(berilmagan -> prefer)'}")
print(f"   password   : {'BOR' if f.get('password') else 'YO_Q'}")
# Keyingi bosqichlar uchun -- sirsiz.
import io, os
io.open(os.environ.get("ZZ_OUT", "/dev/null"), "w").write(
    "\n".join([f.get("host", ""), f.get("port", "") or "5432",
               f.get("dbname", ""), f.get("user", "")]))
PY

ZZ_TMP="$(mktemp)"; trap 'rm -f "$ZZ_TMP"' EXIT
ZZ_OUT="$ZZ_TMP" python3 - "$DSN" >/dev/null <<'PY'
import sys, io, os, urllib.parse as up
d = sys.argv[1].strip(); f = {}
if d.startswith(("postgres://", "postgresql://")):
    u = up.urlparse(d)
    f = {"host": u.hostname or "", "port": str(u.port or ""),
         "dbname": (u.path or "/").lstrip("/"), "user": u.username or ""}
else:
    for q in d.split():
        if "=" in q:
            k, _, v = q.partition("="); f[k.strip()] = v.strip().strip("'\"")
io.open(os.environ["ZZ_OUT"], "w").write("\n".join([
    f.get("host", ""), f.get("port", "") or "5432",
    f.get("dbname", ""), f.get("user", "")]))
PY
HOST="$(sed -n 1p "$ZZ_TMP")"; PORT="$(sed -n 2p "$ZZ_TMP")"
DBNAME="$(sed -n 3p "$ZZ_TMP")"; ROL="$(sed -n 4p "$ZZ_TMP")"

# --- 2) TARMOQ / SOKET --------------------------------------------------------
echo
echo "2. TARMOQ / SOKET"
if [ -z "$HOST" ] || [ "${HOST#/}" != "$HOST" ]; then
    SOK="${HOST:-/var/run/postgresql}/.s.PGSQL.${PORT}"
    if [ -S "$SOK" ]; then echo "   unix soket : BOR ($SOK)"
    else echo "   unix soket : YO'Q ($SOK)"; echo; echo "QATLAM: SOCKET"; exit 1; fi
else
    case "$HOST" in
        *[!0-9.]*)
            if getent hosts "$HOST" >/dev/null 2>&1; then
                echo "   DNS        : hal bo'ldi"
            else
                echo "   DNS        : HAL BO'LMADI"; echo; echo "QATLAM: DNS"; exit 1
            fi ;;
        *) echo "   DNS        : (IP manzil, kerak emas)" ;;
    esac
    if timeout 5 bash -c "exec 3<>/dev/tcp/${HOST}/${PORT}" 2>/dev/null; then
        echo "   TCP ${PORT}   : OCHIQ"
    else
        echo "   TCP ${PORT}   : YETIB BORMADI"; echo; echo "QATLAM: NETWORK"; exit 1
    fi
fi

# --- 3) ULANIB KO'RAMIZ -------------------------------------------------------
echo
echo "3. ULANISH"
XATO_FAYL="$(mktemp)"; trap 'rm -f "$ZZ_TMP" "$XATO_FAYL"' EXIT
if PGCONNECT_TIMEOUT=8 psql "$DSN" -tAc 'select 1' >/dev/null 2>"$XATO_FAYL"; then
    echo "   natija     : ULANDI"
    echo
    echo "QATLAM: (yiqilish yo'q)"
    exit 0
fi
# XATO MATNI DSN NI O'Z ICHIGA OLMAYDI: `psql` xatosi faqat sabab
# yozadi. Baribir ehtiyot bo'lamiz va matnni FILTRLAB bosamiz.
SABAB="$(tr -d '\r' < "$XATO_FAYL" | grep -v '^$' | head -3)"
echo "   natija     : ULANMADI"
printf '   sabab      : %s\n' "$SABAB"

# --- 4) QATLAM TASNIFI --------------------------------------------------------
echo
QATLAM="OTHER"
case "$SABAB" in
    *"no pg_hba.conf entry"*|*"pg_hba"*)               QATLAM="PG_HBA" ;;
    *"password authentication failed"*)                QATLAM="AUTHENTICATION" ;;
    *"role \""*"\" does not exist"*)                   QATLAM="ROLE_NOT_FOUND" ;;
    *"database \""*"\" does not exist"*)               QATLAM="DATABASE_NOT_FOUND" ;;
    *"SSL"*|*"ssl"*)                                   QATLAM="TLS" ;;
    *"Connection refused"*|*"could not connect"*)      QATLAM="NETWORK" ;;
    *"timeout expired"*|*"timed out"*)                 QATLAM="NETWORK" ;;
    *"is not permitted to log in"*|*"login"*)          QATLAM="ROLE_DISABLED" ;;
esac
echo "QATLAM: $QATLAM"

# --- 5) QO'SHIMCHA DALIL — postgres orqali, FAQAT O'QISH ---------------------
# NEGA QATLAM YORLIG'I YETARLI EMAS. PostgreSQL MAVJUD BO'LMAGAN rol
# uchun ham "password authentication failed" deydi -- bu ataylab
# shunday: xato matni rolning bor-yo'qligini OSHKOR QILMAYDI.
# O'lchandi: `zz_yoq_rol_e2e` uchun ham AYNAN shu xabar keldi.
#
# Ya'ni `AUTHENTICATION` yorlig'i uchta boshqa holatni qoplaydi:
# parol mos emas, rol yo'q, yoki `pg_hba` boshqa usulni talab
# qiladi. Ularni AJRATISH uchun quyidagi dalillar kerak.
#
# `peer` autentifikatsiyasi bilan: parol kerak emas va HECH NARSA
# o'zgartirilmaydi. Huquq bo'lmasa `?` chiqadi -- taxmin emas.
echo
echo "4. QO'SHIMCHA DALIL (postgres, faqat o'qish)"
PQ() { sudo -u postgres psql -tAc "$1" 2>/dev/null || echo "?"; }
echo "   baza bormi        : $(PQ "SELECT count(*) FROM pg_database WHERE datname='${DBNAME}'")"
echo "   rol bormi         : $(PQ "SELECT count(*) FROM pg_roles WHERE rolname='${ROL}'")"
echo "   rol login         : $(PQ "SELECT rolcanlogin FROM pg_roles WHERE rolname='${ROL}'")"
echo "   rol muddati       : $(PQ "SELECT coalesce(rolvaliduntil::text,'(cheksiz)') FROM pg_roles WHERE rolname='${ROL}'")"
echo "   ulanish chegarasi : $(PQ "SELECT rolconnlimit FROM pg_roles WHERE rolname='${ROL}'")"
echo "   parol turi        : $(PQ "SELECT CASE WHEN rolpassword LIKE 'SCRAM-SHA-256%' THEN 'SCRAM-SHA-256' WHEN rolpassword IS NULL THEN '(yo''q)' ELSE 'boshqa/md5' END FROM pg_authid WHERE rolname='${ROL}'")"
echo "   CONNECT huquqi    : $(PQ "SELECT has_database_privilege('${ROL}','${DBNAME}','CONNECT')")"
echo "   baza egasi        : $(PQ "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='${DBNAME}'")"
echo "   klaster parol usuli: $(PQ "SHOW password_encryption")"

echo
echo "5. pg_hba QOIDALARI (faqat mos keladiganlar)"
PQ "SELECT line_number || ': ' || type || ' ' || array_to_string(database,',')
        || ' ' || array_to_string(user_name,',') || ' '
        || coalesce(address,'(local)') || ' ' || auth_method
      FROM pg_hba_file_rules
     WHERE (user_name @> ARRAY['${ROL}'] OR user_name @> ARRAY['all'])
       AND (database @> ARRAY['${DBNAME}'] OR database @> ARRAY['all'])
     ORDER BY line_number"
