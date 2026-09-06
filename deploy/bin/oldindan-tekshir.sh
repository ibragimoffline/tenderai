#!/usr/bin/env bash
# =============================================================================
# Tender AI — JOYLASHTIRISHDAN OLDINGI TEKSHIRUV
# =============================================================================
#     oldindan-tekshir.sh <staging|production>
#
# NEGA KERAK
# ----------
# `bootstrap.sh` muhit faylini NAMUNADAN nusxalaydi va shu holda
# qoldiradi. Ya'ni serverda `password=REPLACE`, `example.uz` va
# namunaviy bcrypt xeshi bilan turgan sozlama BUTUNLAY NORMAL
# ko'rinadi — hech narsa uni "to'ldirilmagan" deb belgilamaydi.
#
# `deploy.sh` bu qiymatlarni KECH ushlaydi: `venv` qurilgan,
# `npm ci` yurgan, frontend qurilgan — VA SHUNDAN KEYIN migratsiya
# `password=REPLACE` bilan bazaga ulanolmay to'xtaydi. Bu ~4-5
# daqiqa va yarim reliz katalogi.
#
# Undan ham yomoni JIM QOLADIGANLARI: `example.uz` domeni bilan
# qurilgan reliz MUVAFFAQIYATLI tugaydi va bildirishnoma
# havolalari mavjud bo'lmagan domenga ketaveradi.
#
# Shu skript SHULARNI birinchi soniyalarda aytadi.
#
# UCH DARAJA — va ular ATAYLAB ajratilgan:
#
#   [TO'SIQ]         joylashtirish TO'XTAYDI. Bu qiymat bilan
#                    xizmat ishlamaydi yoki noto'g'ri ishlaydi.
#   [ogohlantirish]  joylashtirish DAVOM ETADI. Xizmat ishlaydi,
#                    lekin biror himoya qatlami yo'q.
#   [tekshirilmadi]  O'LCHAB BO'LMADI (asbob yo'q). Bu "o'tdi"
#                    EMAS — `production_gate.py` dagi
#                    `BLOKLANGAN` bilan ayni mantiq.
#
# BIRINCHI XATODA TO'XTAMAYDI. Operator hamma bo'shliqni BIR
# YURISHDA ko'rsin: har safar bittasini tuzatib qayta yurgizish
# serverda eng ko'p vaqt yeydigan halqa.
#
# SIR CHOP ETMAYDI: qiymatlar emas, faqat KALIT NOMLARI yoziladi
# (chiqish jurnalga tushadi va u ko'p qo'ldan o'tadi). Istisno —
# `APP_PUBLIC_URL`: u ta'rifi bo'yicha ommaviy.
# =============================================================================
set -uo pipefail

MUHIT="${1:?foydalanish: oldindan-tekshir.sh <staging|production>}"
case "$MUHIT" in
    staging|production) ;;
    *) echo "Noma'lum muhit: $MUHIT"; exit 2 ;;
esac

# Yo'llar ALMASHTIRILADI — `deploy.sh` va `health-check.sh` dagi
# bilan ayni sabab: qotirilgan yo'l skriptni serverdan tashqarida
# mashq qilib bo'lmaydigan qiladi, va aynan shuning uchun
# joylashtirish skriptlari uzoq vaqt HECH QACHON bajarilmagan edi.
ENVFILE="${TENDERAI_ENVFILE:-/etc/tenderai/${MUHIT}.env}"
CADDYFILE="${TENDERAI_CADDYFILE:-/etc/caddy/Caddyfile}"

TOSIQ=0
OGOH=0
OLCHANMAGAN=0

tosiq() { printf "  [TO'SIQ]         %s\n" "$*"; TOSIQ=$((TOSIQ + 1)); }
ogoh()  { printf '  [ogohlantirish]  %s\n' "$*"; OGOH=$((OGOH + 1)); }
yoq()   { printf '  [tekshirilmadi]  %s\n' "$*"; OLCHANMAGAN=$((OLCHANMAGAN + 1)); }
ok()    { printf '  [ok]             %s\n' "$*"; }
bolim() { printf '\n%s\n' "$*"; }

echo "=============================================================="
echo "JOYLASHTIRISHDAN OLDINGI TEKSHIRUV — ${MUHIT}"
echo "=============================================================="
echo "muhit fayli : $ENVFILE"
echo "caddy fayli : $CADDYFILE"

# --- 0) MUHIT FAYLI BORMI --------------------------------------------------
if [ ! -f "$ENVFILE" ]; then
    bolim "0. MUHIT FAYLI"
    tosiq "muhit fayli YO'Q: $ENVFILE  (avval: sudo bootstrap.sh $MUHIT)"
    echo
    echo "TO'SIQ: 1 — davom etib bo'lmaydi"
    exit 1
fi

# --- 1) TIRNOQ: BITTA FAYL, IKKI PARSER ------------------------------------
# O'LCHANGAN NUQSON (2026-09-01, B-1 mashqi). `XT_DB_DSN` tirnoqsiz
# edi va u IKKI XIL o'qilardi:
#
#   systemd `EnvironmentFile=`  butun qatorni oladi   -> TO'G'RI
#   shell `. envfile`           BIRINCHI bo'shliqda   -> BUZILADI
#                               kesadi
#
# Ya'ni API to'g'ri DSN olardi, `backup.sh` / `restore-test.sh` /
# `deploy.sh` esa `dbname=...` ni — user, parol va host YO'QOLGAN
# holda. Qolgani (`user=...`) shellda O'ZGARUVCHI TAYINLASH bo'lib
# ketardi, ya'ni XATO HAM BERMASDI.
#
# O'sha safar faqat `XT_DB_DSN` tuzatilgan edi. Bu yerda tekshiruv
# UMUMLASHTIRILDI: bo'shliqli HAR QANDAY tirnoqsiz qiymat aynan shu
# tarzda buziladi (`BACKUP_REMOTE_CMD=rclone copy {fayl} ...` ham).
bolim "1. TIRNOQ (systemd va shell bir xil o'qisin)"
TIRNOQSIZ=""
while IFS= read -r qator; do
    case "$qator" in
        [A-Z_]*=*) ;;
        *) continue ;;
    esac
    kalit="${qator%%=*}"
    qiymat="${qator#*=}"
    case "$qiymat" in
        '"'*|"'"*) continue ;;          # tirnoqda — ikkala parser ham to'g'ri
        *' '*) TIRNOQSIZ="$TIRNOQSIZ $kalit" ;;
    esac
done < "$ENVFILE"
if [ -n "$TIRNOQSIZ" ]; then
    tosiq "bo'shliqli qiymat TIRNOQSIZ (shell birinchi bo'shliqda KESADI):$TIRNOQSIZ"
else
    ok "bo'shliqli qiymatlar tirnoqda"
fi

# --- 2) HUQUQLAR -----------------------------------------------------------
bolim "2. MUHIT FAYLINING HUQUQLARI"
if HOLAT="$(stat -c '%a %U %G' "$ENVFILE" 2>/dev/null)"; then
    REJIM="${HOLAT%% *}"
    EGA="$(printf '%s' "$HOLAT" | awk '{print $2":"$3}')"
    # Oxirgi raqam ("boshqalar") noldan katta bo'lsa — serverdagi
    # HAR QANDAY foydalanuvchi DSN parolini o'qiy oladi.
    #
    # NEGA TO'SIQ EMAS: skriptning O'Z ta'rifi bo'yicha TO'SIQ —
    # "bu qiymat bilan xizmat ishlamaydi". Ochiq huquq bilan xizmat
    # BEKAM-KO'ST ishlaydi, himoya qatlami esa yo'q — bu aynan
    # ogohlantirish ta'rifi. Ta'rifni jiddiylikka qarab egib
    # yuborsak, uch daraja ma'nosini yo'qotardi.
    #
    # Amalda ham shunday: `bootstrap.sh` faylni 0640 bilan yaratadi,
    # ya'ni bu birinchi o'rnatish darvozasi emas, KEYINCHALIK
    # o'zgargan huquqni ushlaydigan sezgi.
    case "$REJIM" in
        *[1-7]) ogoh "muhit fayli BOSHQALAR uchun ochiq ($REJIM) — serverdagi HAR QANDAY foydalanuvchi DSN parolini o'qiydi; chmod 0640" ;;
        *)      ok "rejim $REJIM · egasi $EGA" ;;
    esac
else
    yoq "huquqlarni o'qib bo'lmadi (stat yo'q) — qo'lda: chmod 0640, chown root:tenderai"
fi

# --- 3) QIYMATLAR ----------------------------------------------------------
# SHELL BILAN o'qiladi — `deploy.sh`, `backup.sh` va `restore-test.sh`
# ham xuddi shunday o'qiydi. Boshqacha o'qisak, tekshirayotgan
# narsamiz ishlatiladigan narsa BO'LMASDI.
set -a
# shellcheck disable=SC1090
. "$ENVFILE"
set +a

bor() { eval "[ -n \"\${$1:-}\" ]"; }
qiy() { eval "printf '%s' \"\${$1:-}\""; }

bolim "3. MAJBURIY QIYMATLAR"

if [ "$(qiy APP_ENV)" != "$MUHIT" ]; then
    tosiq "APP_ENV='$(qiy APP_ENV)' — '$MUHIT' bo'lishi SHART"
else
    ok "APP_ENV=$MUHIT"
fi

# APP_PUBLIC_URL — bildirishnoma havolalarining YAGONA manbasi
# (`api/ommaviy_url.py`). Berilmasa xizmat ko'tarilmaydi, lekin
# `example.uz` MAHALLIY EMAS va u qo'rovuldan O'TIB KETADI: xizmat
# ko'tariladi, havolalar esa mavjud bo'lmagan domenga ketadi.
URL="$(qiy APP_PUBLIC_URL)"
if [ -z "$URL" ]; then
    tosiq "APP_PUBLIC_URL bo'sh — xizmat UMUMAN ishga tushmaydi"
elif printf '%s' "$URL" | grep -qE 'localhost|127\.0\.0\.1'; then
    tosiq "APP_PUBLIC_URL MAHALLIY manzil"
elif printf '%s' "$URL" | grep -q 'example\.uz'; then
    tosiq "APP_PUBLIC_URL hali NAMUNAVIY domen (example.uz)"
elif ! printf '%s' "$URL" | grep -q '^https://'; then
    tosiq "APP_PUBLIC_URL HTTPS emas: $URL"
else
    ok "APP_PUBLIC_URL=$URL"
fi

# DSN lar. `password=REPLACE` namunadan keladi va u KECH — migratsiya
# qadamida — chiqadi.
for D in XT_DB_DSN XT_DB_DSN_OWNER; do
    V="$(qiy "$D")"
    if [ -z "$V" ]; then
        tosiq "$D bo'sh"
    elif printf '%s' "$V" | grep -q 'password=REPLACE'; then
        tosiq "$D hali NAMUNAVIY (password=REPLACE)"
    elif ! printf '%s' "$V" | grep -q 'password='; then
        tosiq "$D da parol yo'q (yoki tirnoq tufayli KESILGAN)"
    elif ! printf '%s' "$V" | grep -q 'user='; then
        tosiq "$D da rol yo'q (yoki tirnoq tufayli KESILGAN)"
    else
        ok "$D to'ldirilgan"
    fi
done

# Ilova roli EGA bo'lmasin: `tai_app` da DDL huquqi ATAYLAB yo'q
# (`docs/xavfsizlik.md` C-1). Ikkalasi bir xil bo'lsa o'sha himoya
# YO'Q, lekin hech narsa xato bermaydi.
if [ -n "$(qiy XT_DB_DSN)" ] && [ "$(qiy XT_DB_DSN)" = "$(qiy XT_DB_DSN_OWNER)" ]; then
    tosiq "XT_DB_DSN va XT_DB_DSN_OWNER AYNI — ilova DDL huquqi bilan ishlardi"
fi

# VITE_* — brauzerga TUSHADI. `/api` nisbiy bo'lishi shart: sessiya
# cookie'si `SameSite=Lax` va u faqat same-origin so'rovda ketadi.
VB="$(qiy VITE_API_BASE)"
case "$VB" in
    "") ok "VITE_API_BASE bo'sh — zaxira qiymat /api ishlatiladi" ;;
    /*) ok "VITE_API_BASE=$VB" ;;
    *)  tosiq "VITE_API_BASE NISBIY emas ('$VB') — cookie yuborilmaydi" ;;
esac
if bor VITE_ERP_WEB && printf '%s' "$(qiy VITE_ERP_WEB)" | grep -qE 'localhost|127\.0\.0\.1'; then
    tosiq "VITE_ERP_WEB MAHALLIY manzil — qurilma qo'rovuli to'xtatadi"
fi

if [ "$MUHIT" = "production" ]; then
    [ "$(qiy API_DOCS)" = "0" ] || tosiq "API_DOCS!=0 — Swagger butun API yuzasini ochadi"
    [ "$(qiy AUTH_COOKIE_SECURE)" = "1" ] || tosiq "AUTH_COOKIE_SECURE!=1 — sessiya HTTP orqali ketardi"
    [ "$(qiy TRUST_PROXY)" = "1" ] || tosiq "TRUST_PROXY!=1 — proksi ortida HAMMA so'rov bitta IP dan ko'rinadi"
    [ -z "$(qiy CORS_ORIGINS)" ] || ogoh "CORS_ORIGINS bo'sh emas — same-origin sxemada kerak emas"
fi

# --- 4) BAZAGA ULANISH — TAXMIN EMAS, O'LCHOV -------------------------------
# `password=REPLACE` dan boshqa xatolar (noto'g'ri host, yo'q rol,
# `pg_hba` da ruxsat yo'qligi) FAQAT ulanib ko'rilganda chiqadi.
bolim "4. BAZAGA ULANISH"
if command -v psql >/dev/null 2>&1; then
    for D in XT_DB_DSN XT_DB_DSN_OWNER; do
        V="$(qiy "$D")"
        [ -n "$V" ] || continue
        if PGCONNECT_TIMEOUT=5 psql "$V" -tAc 'select 1' >/dev/null 2>&1; then
            ok "$D ulanadi"
        else
            tosiq "$D ULANMADI (host, rol, parol yoki pg_hba)"
        fi
    done
    # pgvector — migratsiyalar va RAG shunga tayanadi.
    if [ -n "$(qiy XT_DB_DSN_OWNER)" ]; then
        if PGCONNECT_TIMEOUT=5 psql "$(qiy XT_DB_DSN_OWNER)" -tAc \
             "select 1 from pg_extension where extname='vector'" 2>/dev/null | grep -q 1; then
            ok "pgvector o'rnatilgan"
        else
            tosiq "pgvector YO'Q — CREATE EXTENSION vector (docs/deploy.md §4)"
        fi
    fi
else
    yoq "psql yo'q — DSN lar HAQIQATAN ulanishi tekshirilmadi"
fi

# --- 5) CADDY --------------------------------------------------------------
bolim "5. CADDY (domen, port, staging qulfi)"
if [ ! -f "$CADDYFILE" ]; then
    yoq "Caddyfile yo'q ($CADDYFILE) — domen, HTTPS va port MOSLIGI tekshirilmadi"
else
    # Izohlar TASHLAB YUBORILADI: namunadagi "ALMASHTIRING:
    # staging.example.uz" izohi soxta xato berardi.
    TOZA="$(grep -vE '^[[:space:]]*#' "$CADDYFILE")"

    if printf '%s\n' "$TOZA" | grep -q 'REPLACE_WITH_YOUR_OWN'; then
        # Bu shunchaki "to'ldirilmagan" emas: yaroqsiz bcrypt xeshi
        # bilan Caddy konfiguratsiyani UMUMAN yuklamaydi — ya'ni
        # HTTPS ikkala domen uchun ham o'lik bo'ladi.
        tosiq "Caddyfile da NAMUNAVIY bcrypt xeshi — Caddy konfiguratsiyani yuklamaydi"
    fi
    if printf '%s\n' "$TOZA" | grep -q 'example\.uz'; then
        tosiq "Caddyfile da NAMUNAVIY domen (example.uz)"
    fi

    HOST="$(printf '%s' "$URL" | sed -E 's#^https?://##; s#[:/].*$##')"
    if [ -n "$HOST" ]; then
        HOST_RX="$(printf '%s' "$HOST" | sed 's/\./\\./g')"
        QATOR="$(grep -nE "^[[:space:]]*${HOST_RX}[[:space:]]*\{" "$CADDYFILE" | head -1 | cut -d: -f1)"
        if [ -z "$QATOR" ]; then
            tosiq "Caddyfile da '$HOST' uchun sayt bloki YO'Q — APP_PUBLIC_URL boshqa domenni ko'rsatadi"
        else
            ok "Caddyfile da '$HOST' bloki bor"
            # PORT MOSLIGI. Nomuvofiqlik JIM: Caddy 502 qaytaradi,
            # xizmat esa SOG'LOM turadi — ikkala tomon ham "menda
            # hammasi joyida" deydi.
            CPORT="$(sed -n "${QATOR},\$p" "$CADDYFILE" \
                     | grep -m1 -oE 'reverse_proxy[[:space:]]+127\.0\.0\.1:[0-9]+' \
                     | grep -oE '[0-9]+$')"
            APORT="$(qiy API_PORT)"; APORT="${APORT:-8000}"
            if [ -z "$CPORT" ]; then
                yoq "'$HOST' blokida reverse_proxy topilmadi — port mosligi tekshirilmadi"
            elif [ "$CPORT" != "$APORT" ]; then
                tosiq "PORT MOS EMAS: Caddy -> $CPORT, API_PORT = $APORT (Caddy 502 beradi)"
            else
                ok "port mos: $APORT"
            fi
            if [ "$MUHIT" = "staging" ]; then
                # Staging ochiq qolsa qidiruv tizimlariga tushadi va
                # SINOV MA'LUMOTI ommaviy bo'ladi.
                if sed -n "${QATOR},\$p" "$CADDYFILE" | sed -n '1,60p' | grep -q 'basic_auth'; then
                    ok "staging basic_auth ortida"
                else
                    tosiq "staging OCHIQ — basic_auth yo'q"
                fi
            fi
        fi
    fi
fi

# --- 6) HIMOYA QATLAMLARI (to'xtatmaydi, lekin JIM QOLMAYDI) ---------------
bolim "6. HIMOYA QATLAMLARI"

# MUHIM: `backup.sh` OTA-katalogga emas, `${BACKUP_DIR}/${MUHIT}`
# ga yozadi (`backup.sh:44`). Ota-katalogni tekshirish soxta
# natija berardi IKKALA yo'nalishda ham:
#
#   soxta TO'SIQ  — `bootstrap.sh` oraliq katalogni root nomidan
#                   yaratadi, ya'ni `tenderai` unga yoza olmaydi,
#                   o'z ichki katalogiga esa BEMALOL yozadi;
#   soxta OK      — ota-katalog yozilsa ham, ichkisi yo'q bo'lishi
#                   mumkin va zaxira BIRINCHI yurishda yiqilardi.
#
# Shuning uchun bu yerda AYNAN `backup.sh` ishlatadigan yo'l
# tekshiriladi.
BD="$(qiy BACKUP_DIR)"
ZAXIRA_YOL="${BD:-/var/backups/tenderai}/${MUHIT}"
if [ -z "$BD" ]; then
    ogoh "BACKUP_DIR bo'sh — zaxira standart yo'lga yoziladi: $ZAXIRA_YOL"
fi
if [ ! -d "$ZAXIRA_YOL" ]; then
    tosiq "zaxira katalogi yo'q: $ZAXIRA_YOL  (sudo bootstrap.sh $MUHIT)"
elif [ ! -w "$ZAXIRA_YOL" ]; then
    tosiq "zaxira katalogiga YOZIB BO'LMAYDI: $ZAXIRA_YOL"
else
    ok "zaxira katalogi yoziladi: $ZAXIRA_YOL"
fi

# ZAXIRA BITTA DISKDA — ZAXIRA EMAS (docs/deploy.md §12b).
if bor BACKUP_REMOTE_CMD; then
    ok "tashqi nusxa sozlangan"
else
    ogoh "BACKUP_REMOTE_CMD bo'sh — zaxira BITTA diskda, disk yo'qolsa u ham ketadi"
fi

# Nosozlik xabari hech kimga bormasa, `systemd` xizmatni qayta
# ko'taradi va buni HECH KIM BILMAYDI (docs/deploy.md §12c).
if ! bor ALERT_TELEGRAM_CHAT && ! bor ALERT_EMAIL; then
    ogoh "ALERT_TELEGRAM_CHAT va ALERT_EMAIL — IKKALASI ham bo'sh: nosozlikni hech kim bilmaydi"
else
    ok "ogohlantirish kanali bor"
fi

bor SMTP_HOST         || ogoh "SMTP_HOST bo'sh — email bildirishnoma ishlamaydi"
bor TELEGRAM_BOT_TOKEN || ogoh "TELEGRAM_BOT_TOKEN bo'sh — Telegram kanali yoqilmaydi"
bor ERP_SERVICE_KEY   || ogoh "ERP_SERVICE_KEY bo'sh — ERP ko'prigi ishlamaydi"

# PULLIK AI: yoqilgan-u kalit yo'q bo'lsa chat va Go/No-Go ishlamaydi.
if [ "$(qiy AI_PAID_ENABLED)" = "1" ]; then
    if bor ANTHROPIC_API_KEY; then
        ogoh "PULLIK AI YOQILGAN — har chaqiruv pul sarflaydi"
    else
        tosiq "AI_PAID_ENABLED=1, lekin ANTHROPIC_API_KEY bo'sh"
    fi
else
    ok "pullik AI o'chiq"
fi

# --- XULOSA ----------------------------------------------------------------
echo
echo "=============================================================="
printf "TO'SIQ: %s · ogohlantirish: %s · tekshirilmadi: %s\n" \
       "$TOSIQ" "$OGOH" "$OLCHANMAGAN"
if [ "$TOSIQ" -gt 0 ]; then
    echo "NATIJA: JOYLASHTIRIB BO'LMAYDI"
    echo "=============================================================="
    exit 1
fi
echo "NATIJA: joylashtirish mumkin"
echo "=============================================================="
exit 0
