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
# MAHALLIY MANZIL: STAGING da RUXSAT, PRODUCTION da QAT'IY TO'SIQ.
#
# QAROR (2026-09-07, B varianti). Bu o'rnatmada staging ga domen
# ATAYLAB berilmagan: nginx bloki `listen 127.0.0.1:8091` da turadi
# va unga SSH tunnel orqali kiriladi (`_server/bin/11-nginx.sh`
# izohi). Ya'ni mahalliy `APP_PUBLIC_URL` -- xato emas, SHU
# ARXITEKTURANING O'ZI.
#
# Ilgari tekshiruv muhitni ajratmasdi va staging ni HAR SAFAR
# to'sardi. Natijasi eng yomon turdagi darvoza bo'lardi: u hech
# qachon o'tmaydi, demak undan CHETLAB O'TISHNI o'rganishadi.
#
# PRODUCTION UCHUN HECH NARSA YUMSHATILMADI: u yerda mahalliy
# manzil ham, HTTPS bo'lmagani ham, namunaviy domen ham TO'SIQ.
# Staging da esa mahalliy manzil OGOHLANTIRISH bo'lib qoladi --
# jim emas, lekin to'smaydi.
URL="$(qiy APP_PUBLIC_URL)"
MAHALLIY=0
printf '%s' "$URL" | grep -qE 'localhost|127\.0\.0\.1' && MAHALLIY=1
if [ -z "$URL" ]; then
    tosiq "APP_PUBLIC_URL bo'sh — xizmat UMUMAN ishga tushmaydi"
elif [ "$MAHALLIY" = "1" ] && [ "$MUHIT" = "production" ]; then
    tosiq "APP_PUBLIC_URL MAHALLIY manzil — production da MUMKIN EMAS"
elif [ "$MAHALLIY" = "1" ]; then
    ogoh "APP_PUBLIC_URL mahalliy ($URL) — staging tashqariga chiqmaydi, \
bu shu o'rnatmaning tanlovi; havolalar faqat SSH tunnelda ochiladi"
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

# --- YUKLASH ILDIZI — QUMDON BILAN MOS BO'LSIN --------------------
# O'LCHANGAN NUQSON (2026-09-09, birinchi haqiqiy asosiy E2E).
# Fayl yuklash `STORAGE_WRITE_FAILED` bilan 500 qaytardi. Sabab
# sozlamada emas, uning YO'QLIGIDA edi:
#
#     systemd:  ProtectSystem=strict
#               ReadWritePaths=/opt/tenderai/<muhit>/var
#     ilova  :  UPLOAD_ROOT sozlanmagan -> standart qiymat
#               <reliz>/.runtime/uploads
#
# Ya'ni ilova o'zi uchun FAQAT O'QILADIGAN katalogga yozmoqchi
# bo'lardi. Bu HECH QAYERDA ko'rinmasdi: `yuklama_test` qumdondan
# TASHQARIDA (darvoza root sifatida) yuradi va o'sha katalogga
# bemalol yozadi, ya'ni sinov YASHIL, ish vaqti esa SINGAN.
#
# Reliz katalogi ichi BARIBIR yaramaydi: har reliz yangi katalog,
# ya'ni yuklangan fayllar keyingi joylashtiruvda YO'QOLARDI.
UPROOT="$(qiy UPLOAD_ROOT)"
# ILDIZ `deploy.sh` bilan BIR XIL qoidada aniqlanadi -- aks holda
# tekshiruv haqiqiy joylashtiruvdan boshqa yo'lni o'lchardi.
ILDIZ_YOL="${TENDERAI_ILDIZ:-/opt/tenderai/${MUHIT}}"
YOZILADIGAN="${ILDIZ_YOL}/var"
XIZMAT_USER="${TENDERAI_USER:-tenderai}"
#: Bo'sh joy chegaralari. Disk yuklangan fayllar, baza dumpi va
#: zaxira saqlanishi bilan BO'LINADI, ya'ni "yuklashga joy bor" degan
#: savol yolg'iz turmaydi.
DISK_TOSIQ_GB=2
DISK_OGOH_GB=10

if [ -z "$UPROOT" ]; then
    tosiq "UPLOAD_ROOT bo'sh — yuklangan fayllar reliz katalogiga tushardi,
   u esa systemd qumdonida FAQAT O'QILADIGAN (ProtectSystem=strict).
   Fayl yuklash 500 STORAGE_WRITE_FAILED beradi.
   Qo'ying: UPLOAD_ROOT=${YOZILADIGAN}/uploads"
elif [ "${UPROOT#/}" = "$UPROOT" ]; then
    tosiq "UPLOAD_ROOT nisbiy yo'l ('$UPROOT') — ish katalogiga bog'liq bo'ladi"
elif [ "$UPROOT" != "${UPROOT#*/releases/}" ] \
     || [ "$UPROOT" != "${UPROOT%/releases}" ]; then
    # RELIZ KATALOGI O'ZGARMAS. Har joylashtiruv yangi katalog
    # yasaydi, ya'ni u yerdagi fayllar keyingisida YO'QOLARDI.
    tosiq "UPLOAD_ROOT RELIZ katalogi ichida: $UPROOT
   Har joylashtiruv yangi katalog yasaydi — fayllar YO'QOLARDI.
   Reliz daraxti o'zgarmas bo'lishi kerak."
elif [ "${UPROOT#${YOZILADIGAN}/}" = "$UPROOT" ] && [ "$UPROOT" != "$YOZILADIGAN" ]; then
    # Qumdon ro'yxatidan tashqarida bo'lsa yozib bo'lmaydi.
    tosiq "UPLOAD_ROOT qumdondan TASHQARIDA: $UPROOT
   systemd faqat '${YOZILADIGAN}' ga yozishga ruxsat beradi
   (ReadWritePaths). Boshqa joy 500 beradi."
elif [ ! -d "$UPROOT" ]; then
    tosiq "UPLOAD_ROOT katalogi YO'Q: $UPROOT
   Yasang: sudo install -d -o ${XIZMAT_USER} -g ${XIZMAT_USER} -m 0755 '$UPROOT'"
else
    # --- MAVJUD KATALOG: EGASI, REJIMI, BO'SH JOYI ------------------
    UP_EGA="$(stat -c '%U' "$UPROOT" 2>/dev/null || echo '?')"
    UP_REJIM="$(stat -c '%a' "$UPROOT" 2>/dev/null || echo '?')"
    UP_XATO=""
    # Xizmat roli yoza olishi SHART. Egalik tekshiriladi, `-w` emas:
    # `-w` TEKSHIRUVNI YURGIZAYOTGAN foydalanuvchi uchun javob
    # beradi (odatda root), xizmat uchun emas.
    [ "$UP_EGA" = "$XIZMAT_USER" ] || UP_XATO="egasi '$UP_EGA' — '${XIZMAT_USER}' bo'lishi kerak"
    # HAMMA UCHUN YOZILADIGAN BO'LMASIN: serverdagi har qanday
    # foydalanuvchi yuklangan hujjatni almashtira olardi.
    case "$UP_REJIM" in
        *[2367]) UP_XATO="${UP_XATO:+$UP_XATO; }rejim $UP_REJIM — HAMMA uchun yoziladi" ;;
    esac
    if [ -n "$UP_XATO" ]; then
        tosiq "UPLOAD_ROOT ($UPROOT): $UP_XATO"
    else
        ok "UPLOAD_ROOT=$UPROOT (qumdon ichida, $UP_EGA, $UP_REJIM)"
    fi

    BOSH_GB="$(df -BG --output=avail "$UPROOT" 2>/dev/null | tail -1 | tr -dc '0-9')"
    if [ -z "$BOSH_GB" ]; then
        ogoh "bo'sh joy O'LCHANMADI: $UPROOT"
    elif [ "$BOSH_GB" -lt "$DISK_TOSIQ_GB" ]; then
        tosiq "diskda ${BOSH_GB} GB bo'sh joy — zaxira dumpi ham shu diskda"
    elif [ "$BOSH_GB" -lt "$DISK_OGOH_GB" ]; then
        ogoh "diskda ${BOSH_GB} GB bo'sh joy (${DISK_OGOH_GB} GB dan kam)"
    else
        ok "bo'sh joy: ${BOSH_GB} GB"
    fi
fi

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
    EGA_ULANDI=0
    for D in XT_DB_DSN XT_DB_DSN_OWNER; do
        V="$(qiy "$D")"
        [ -n "$V" ] || continue
        if PGCONNECT_TIMEOUT=5 psql "$V" -tAc 'select 1' >/dev/null 2>&1; then
            ok "$D ulanadi"
            [ "$D" = "XT_DB_DSN_OWNER" ] && EGA_ULANDI=1
        else
            tosiq "$D ULANMADI (host, rol, parol yoki pg_hba)"
        fi
    done
    # pgvector — migratsiyalar va RAG shunga tayanadi.
    #
    # BOG'LIQ TEKSHIRUV, MUSTAQIL EMAS. So'rov AYNAN
    # `XT_DB_DSN_OWNER` orqali yuriydi. Ulanish yiqilganda so'rov
    # ham bo'sh qaytadi va natija "pgvector YO'Q" bo'lib ko'rinardi.
    #
    # O'LCHANGAN CHALG'ISH (2026-09-09, production preflighti):
    # egalik DSN i ulanmadi va hisobot ikkita MUSTAQIL to'siq
    # ko'rsatdi -- ulanish va pgvector. Ikkinchisi esa YOLG'ON edi:
    # ishlab chiqarish bazasi tirik va RAG ishlayapti, ya'ni
    # kengaytma O'RNATILGAN. Operator `CREATE EXTENSION vector`
    # izidan ketardi -- mavjud narsani "yo'q" deb.
    #
    # O'LCHANMAGAN NARSA YIQILGAN EMAS. Uchinchi holat ishlatiladi.
    if [ -z "$(qiy XT_DB_DSN_OWNER)" ]; then
        :
    elif [ "$EGA_ULANDI" != "1" ]; then
        yoq "pgvector TEKSHIRILMADI — so'rov XT_DB_DSN_OWNER orqali yuriydi,
   u esa ulanmadi. Avval ulanishni tuzating, keyin qayta yurgizing."
    elif PGCONNECT_TIMEOUT=5 psql "$(qiy XT_DB_DSN_OWNER)" -tAc \
             "select 1 from pg_extension where extname='vector'" 2>/dev/null | grep -q 1; then
        ok "pgvector o'rnatilgan"
    else
        tosiq "pgvector YO'Q — CREATE EXTENSION vector (docs/deploy.md §4)"
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
#
# ISHLAB CHIQARISHDA MAJBURIY. `backup.sh` ning o'zi ham buni
# talab qiladi va sozlanmagan bo'lsa 1 bilan tugaydi -- lekin u
# joylashtiruvdan KEYIN, timer yurganda ishlaydi. Bu yerda
# to'xtatish arzonroq.
BRC="$(qiy BACKUP_REMOTE_CMD)"
if [ -z "$BRC" ]; then
    if [ "$MUHIT" = "production" ]; then
        tosiq "BACKUP_REMOTE_CMD bo'sh — zaxira BITTA diskda.
   Disk yo'qolsa (yoki shifrlovchi dastur tegsa) zaxira ham u bilan
   ketadi, ya'ni himoya YO'Q. Ishlab chiqarishda bu SHART.
   Sozlang: BACKUP_REMOTE_CMD='/usr/local/sbin/tender-backup-remote {fayl}'"
    else
        ogoh "BACKUP_REMOTE_CMD bo'sh — zaxira BITTA diskda, disk yo'qolsa u ham ketadi"
    fi
else
    # `{fayl}` MUSTAQIL argument bo'lsin: `backup.sh` shablonni
    # bo'shliq bo'yicha argumentlarga bo'ladi va qobiq ISHTIROK
    # ETMAYDI. Argument ichidagi `{fayl}` almashmasdi.
    BRC_OK=1
    case " $BRC " in
        *" {fayl} "*) ;;
        *) tosiq "BACKUP_REMOTE_CMD da MUSTAQIL \`{fayl}\` argumenti yo'q: $BRC
   U bo'shliq bilan ajratilgan alohida so'z bo'lishi kerak."
           BRC_OK=0 ;;
    esac
    # BIRINCHI SO'Z — BAJARILADIGAN FAYL, qobiq satri emas.
    BRC_BIN="${BRC%% *}"
    if [ "$BRC_OK" = "1" ]; then
        case "$BRC_BIN" in
            /*) ;;
            *) tosiq "BACKUP_REMOTE_CMD birinchi so'zi MUTLAQ yo'l emas: '$BRC_BIN'
   Qobiq ISHLATILMAYDI (quvur, yo'naltirish, o'rniga qo'yish yo'q).
   Belgilangan o'rama bering:
     BACKUP_REMOTE_CMD='/usr/local/sbin/tender-backup-remote {fayl}'"
               BRC_OK=0 ;;
        esac
    fi
    if [ "$BRC_OK" = "1" ]; then
        if [ ! -x "$BRC_BIN" ]; then
            tosiq "BACKUP_REMOTE_CMD dasturi YO'Q yoki bajarilmaydi: $BRC_BIN"
        else
            # O'rama ROOT niki bo'lsin: uni boshqa foydalanuvchi
            # tahrirlay olsa, zaxira yo'li o'sha foydalanuvchining
            # kodini root nomidan yurgizardi.
            # Kutilgan EGA. Haqiqiy mezbonda `root`; mashq muhitida
            # fayllarni sinov foydalanuvchisi yasaydi, shuning uchun
            # `TENDERAI_ILDIZ`/`TENDERAI_USER` bilan AYNI naqshda
            # muhitdan olinadi. Standart qiymat o'zgarmaydi.
            ROOT_USER="${TENDERAI_ROOT:-root}"
            B_EGA="$(stat -c '%U' "$BRC_BIN" 2>/dev/null || echo '?')"
            B_REJIM="$(stat -c '%a' "$BRC_BIN" 2>/dev/null || echo '?')"
            B_XATO=""
            [ "$B_EGA" = "$ROOT_USER" ] || B_XATO="egasi '$B_EGA' — '${ROOT_USER}' bo'lishi kerak"
            case "$B_REJIM" in
                *[2367]) B_XATO="${B_XATO:+$B_XATO; }rejim $B_REJIM — HAMMA uchun yoziladi" ;;
            esac
            if [ -n "$B_XATO" ]; then
                tosiq "BACKUP_REMOTE_CMD dasturi ($BRC_BIN): $B_XATO"
            else
                ok "tashqi nusxa: $BRC_BIN ($B_EGA, $B_REJIM)"
            fi
        fi
    fi
fi

# --- ZAXIRA YANGILIGI VA TIKLASH ISBOTI --------------------------------------
# NEGA. "Zaxira sozlangan" degan xulosa "zaxira BOR va U ISHLAYDI"
# degani emas. Uchta boshqa savol:
#
#   1. oxirgi zaxira QACHON olingan?          (yangilik)
#   2. undan HAQIQATAN tiklab bo'ldimi?        (mashq)
#   3. mashq UZOQ nusxadan olindimi?           (himoya doirasi)
#
# Uchinchisi ayniqsa muhim: mahalliy diskdagi nusxadan tiklash
# MEXANIZMNI isbotlaydi, lekin "disk yo'qolsa tiklanadi" degan
# da'voni ISBOTLAMAYDI. Ishlab chiqarish uchun aynan ikkinchisi
# kerak.
#
# CHEGARALAR timerlardan kelib chiqadi: zaxira kunlik, mashq
# haftalik. Kechikish uchun kichik zaxira vaqti qo'shilgan.
ZAXIRA_YANGILIK_SOAT=30
ISBOT_MUDDAT_KUN=8
ISBOT_FAYL="${ZAXIRA_YOL}/.tiklash-isboti"

if [ -d "$ZAXIRA_YOL" ]; then
    OXIRGI="$(ls -1t "$ZAXIRA_YOL"/*.dump 2>/dev/null | head -1 || true)"
    if [ -z "$OXIRGI" ]; then
        if [ "$MUHIT" = "production" ]; then
            tosiq "zaxira fayli YO'Q ($ZAXIRA_YOL) — joylashtirishdan oldin
   ishlab chiqarish bazasining YANGI nusxasi bo'lishi shart."
        else
            ogoh "zaxira fayli yo'q ($ZAXIRA_YOL)"
        fi
    else
        YOSH_S=$(( $(date +%s) - $(stat -c %Y "$OXIRGI") ))
        YOSH_SOAT=$(( YOSH_S / 3600 ))
        if [ "$YOSH_SOAT" -gt "$ZAXIRA_YANGILIK_SOAT" ]; then
            if [ "$MUHIT" = "production" ]; then
                tosiq "oxirgi zaxira ${YOSH_SOAT} soat oldin olingan
   (chegara ${ZAXIRA_YANGILIK_SOAT} soat). Joylashtirishdan oldin yangi
   zaxira oling: systemctl start tenderai-backup@${MUHIT}.service"
            else
                ogoh "oxirgi zaxira ${YOSH_SOAT} soat oldin"
            fi
        else
            ok "oxirgi zaxira: ${YOSH_SOAT} soat oldin"
        fi
    fi

    # --- TIKLASH ISBOTI ---
    if [ ! -f "$ISBOT_FAYL" ]; then
        if [ "$MUHIT" = "production" ]; then
            tosiq "TIKLASH ISBOTI YO'Q ($ISBOT_FAYL).
   Zaxira olinishi uni TIKLAB bo'lishini isbotlamaydi.
   Yurgizing: systemctl start tenderai-restore-test@${MUHIT}.service"
        else
            ogoh "tiklash isboti yo'q ($ISBOT_FAYL)"
        fi
    else
        I_YOSH_KUN=$(( ( $(date +%s) - $(stat -c %Y "$ISBOT_FAYL") ) / 86400 ))
        I_UZOQ="$(sed -n 's/^uzoq=//p' "$ISBOT_FAYL" | head -1)"
        I_RTO="$(sed -n 's/^rto_s=//p' "$ISBOT_FAYL" | head -1)"
        if [ "$I_YOSH_KUN" -gt "$ISBOT_MUDDAT_KUN" ]; then
            if [ "$MUHIT" = "production" ]; then
                tosiq "tiklash isboti ESKI: ${I_YOSH_KUN} kun (chegara ${ISBOT_MUDDAT_KUN}).
   Eski mashqqa tayanib bo'lmaydi — o'shandan beri sxema ham,
   zaxira yo'li ham o'zgargan bo'lishi mumkin."
            else
                ogoh "tiklash isboti ${I_YOSH_KUN} kunlik"
            fi
        elif [ "$MUHIT" = "production" ] && [ "$I_UZOQ" != "ha" ]; then
            # MAHALLIY MASHQ YETARLI EMAS.
            tosiq "tiklash mashqi MAHALLIY nusxadan olingan (uzoq=${I_UZOQ:-?}).
   Bu mexanizmni isbotlaydi, lekin \"disk yo'qolsa tiklanadi\" degan
   da'voni ISBOTLAMAYDI. Ishlab chiqarish uchun mashq UZOQ nusxadan
   olinishi shart."
        else
            ok "tiklash isboti: ${I_YOSH_KUN} kun oldin, RTO=${I_RTO:-?}s, uzoq=${I_UZOQ:-?}"
        fi
    fi
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
