#!/usr/bin/env bash
# =============================================================================
# STAGING E2E HISOBLARI — yaratish / parolni yangilash
# =============================================================================
#     e2e-hisob-sozla.sh            # yaratadi yoki parolni yangilaydi
#
# ROOT SIFATIDA YURGIZILADI. Sabab: muhit faylini (`640 root:tenderai`)
# faqat root yozadi. Yangi NOPASSWD o'rama QO'SHILMAYDI -- imtiyozli
# yuzani kengaytirmaslik uchun buni operator bir marta o'zi yurgizadi.
#
# NEGA ALOHIDA HISOBLAR. E2E ijarachi chegarasini o'lchaydi, ya'ni unga
# IKKI KOMPANIYA kerak. Haqiqiy foydalanuvchi hisobini olish ikki
# sababdan yaramaydi: uning paroli boshqa joyda ishlatilishi mumkin,
# va E2E uning ma'lumotiga hujjat yozadi.
#
# PAROL BU YERDA YASHALADI VA HECH QAYERGA CHIQARILMAYDI:
#   * ekranga bosilmaydi;
#   * buyruq argumentiga tushmaydi (`create_company.py` uni STDIN dan
#     `getpass` bilan oladi), ya'ni `ps` da ko'rinmaydi;
#   * buyruq tarixiga tushmaydi;
#   * jurnalga tushmaydi;
#   * Git ga tushmaydi -- u faqat `640 root:tenderai` muhit faylida.
#
# IDEMPOTENT: qayta yurgizsa parollar YANGILANADI va muhit fayli
# ularga moslanadi. Ya'ni "parol qayerdadir eskirib qoldi" holati
# bitta buyruq bilan tuzatiladi.
#
# FAQAT STAGING. Production da bu hisoblar BO'LMASLIGI kerak: ular
# sinov ma'lumoti yozadi va ularning paroli muhit faylida turadi.
# =============================================================================
set -euo pipefail
set +x                      # parol trace ga tushmasin
umask 077

MUHIT="${1:-staging}"
ENVFILE="/etc/tenderai/${MUHIT}.env"

# Foydalanuvchi nomlari ANIQ va O'ZGARMAS. Tasodifiy nom har yurishda
# yangi hisob yaratardi va staging asta-sekin axlatga to'lardi.
A_LOGIN="zze2e_a"
B_LOGIN="zze2e_b"
A_KOMPANIYA="ZZE2E Kompaniya A"
B_KOMPANIYA="ZZE2E Kompaniya B"

xato() { echo "XATO: $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || xato "root sifatida yurgizing (muhit fayliga yozadi)."
[ "$MUHIT" = "staging" ] || xato "faqat staging. Berilgan: '$MUHIT'
   Bu hisoblar sinov ma'lumoti yozadi va paroli muhit faylida turadi."
[ -f "$ENVFILE" ] || xato "muhit fayli yo'q: $ENVFILE"
command -v tender-kompaniya >/dev/null || xato "tender-kompaniya o'rami topilmadi."

# --- PAROL YASASH ------------------------------------------------------------
# `python3 -c secrets` ishlatiladi: `openssl` har mashinada bo'lmasligi
# mumkin, python esa ilovaning O'ZI uchun ham shart.
yangi_parol() {
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
}

# --- HISOB YARATISH YOKI PAROLNI YANGILASH -----------------------------------
# Parol STDIN orqali beriladi (`--parol-stdin`).
#
# `getpass` ISHLATILMAYDI: u avval `/dev/tty` ni ochadi va terminal
# bo'lsa AYNAN O'SHANDAN o'qiydi -- quvurdan berilgan parolni
# ko'rmay operator oldida OSILIB qolardi. `--parol-stdin` esa
# aniq va bir marta so'raydi.
hisob_sozla() {
    local login="$1" kompaniya="$2" parol="$3" chiq
    if tender-kompaniya "$MUHIT" --list 2>/dev/null | grep -qE "^[[:space:]]*${login}[[:space:]]"; then
        chiq="$(printf '%s\n' "$parol" \
                | tender-kompaniya "$MUHIT" "$login" --password --parol-stdin 2>&1)" \
            || { echo "$chiq" | grep -vi parol >&2; xato "$login: parol yangilanmadi"; }
        echo "  $login — parol yangilandi"
    else
        chiq="$(printf '%s\n' "$parol" \
                | tender-kompaniya "$MUHIT" "$login" "$kompaniya" --parol-stdin 2>&1)" \
            || { echo "$chiq" | grep -vi parol >&2; xato "$login: yaratilmadi"; }
        echo "  $login — yaratildi ($kompaniya)"
    fi
}

# --- MUHIT FAYLIGA YOZISH — ATOMAR -------------------------------------------
# Vaqtinchalik fayl AYNI KATALOGDA yasaladi: `/tmp` boshqa fayl
# tizimida bo'lishi mumkin va `mv` o'shanda atomar BO'LMAYDI.
env_yoz() {
    local vaqt
    vaqt="$(mktemp "${ENVFILE}.zze2e.XXXXXX")"
    # Egalik va rejim NUSXALANADI, qayta o'ylab topilmaydi.
    chown --reference="$ENVFILE" "$vaqt"
    chmod --reference="$ENVFILE" "$vaqt"
    grep -vE '^(E2E_URL|E2E_LOGIN|E2E_PAROL|E2E_BEGONA_LOGIN|E2E_BEGONA_PAROL)=' \
        "$ENVFILE" > "$vaqt"
    {
        echo ""
        echo "# --- STAGING E2E (e2e-hisob-sozla.sh yozgan) ---"
        echo "# Parollar SKRIPT yasagan va hech qayerda chop etilmagan."
        echo "E2E_URL=http://localhost:8091/api"
        echo "E2E_LOGIN=${A_LOGIN}"
        echo "E2E_PAROL=${1}"
        echo "E2E_BEGONA_LOGIN=${B_LOGIN}"
        echo "E2E_BEGONA_PAROL=${2}"
        # PULLIK QATLAM — MAVJUD TANLOV SAQLANADI.
        # Bu skript hisoblar uchun. Agar operator AI ni ataylab
        # yoqib qo'ygan bo'lsa, uni JIMGINA o'chirish "hisob-kitob
        # xulqini bildirmasdan o'zgartirish" bo'lardi. Shuning
        # uchun qator YO'Q bo'lgandagina yoziladi.
        if ! grep -qE '^E2E_AI_ENABLED=' "$ENVFILE"; then
            echo "# Pullik AI E2E. 1 -> har tasdiqda model chaqiriladi."
            echo "E2E_AI_ENABLED=0"
        fi
    } >> "$vaqt"
    mv -f "$vaqt" "$ENVFILE"
}

echo "STAGING E2E hisoblari sozlanmoqda ($ENVFILE)"
A_PAROL="$(yangi_parol)"
B_PAROL="$(yangi_parol)"
hisob_sozla "$A_LOGIN" "$A_KOMPANIYA" "$A_PAROL"
hisob_sozla "$B_LOGIN" "$B_KOMPANIYA" "$B_PAROL"
env_yoz "$A_PAROL" "$B_PAROL"
unset A_PAROL B_PAROL

echo "Muhit fayli yangilandi: E2E_URL, E2E_LOGIN, E2E_PAROL,"
echo "                        E2E_BEGONA_LOGIN, E2E_BEGONA_PAROL"
echo "Parollar CHOP ETILMADI. Ular faqat $ENVFILE da ($(stat -c '%a %U:%G' "$ENVFILE"))."
