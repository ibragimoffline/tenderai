#!/usr/bin/env bash
# =============================================================================
# Tender AI — FAYL YUKLASH uchidan-uchiga sinovi (HAQIQIY HTTP)
# =============================================================================
#     e2e-fayl.sh <bazaviy-url> <login> <parol> [--ai] [--begona <login> <parol>]
#
# MISOL:
#     e2e-fayl.sh https://staging.example.uz/api broker 'parol' --ai
#     e2e-fayl.sh http://127.0.0.1:8000 zztest 'parol'
#
# NEGA BU SKRIPT BOR. `_tests/yuklama_test.py` `TestClient` bilan
# yuradi: u ASGI ilovasini TO'G'RIDAN-TO'G'RI chaqiradi va tarmoqqa
# umuman chiqmaydi. Ya'ni u quyidagilarni O'LCHAMAYDI:
#
#   * teskari proksi (Caddy) tana chegarasi — 26 MB haqiqatan
#     o'tkazadimi va 30 MB ni to'xtatadimi;
#   * `Content-Disposition` va `Content-Type` proksidan o'tgach
#     saqlanadimi;
#   * cookie/CSRF haqiqiy brauzer qoidalari bilan ishlaydimi;
#   * `StreamingResponse` haqiqiy tarmoq ustida to'liq keladimi.
#
# BU SKRIPT BRAUZER SINOVI EMAS. U tugma bosishni, fayl tanlash
# dialogini va UI holatini tekshirmaydi — ular ODAM tomonidan yoki
# brauzer avtomatizatsiyasi bilan sinaladi. Bu farq ATAYLAB
# yozilgan: "E2E o'tdi" degan xulosa "interfeys ishlaydi" degani
# EMAS.
# =============================================================================
set -euo pipefail

URL="${1:?foydalanish: e2e-fayl.sh <url> <login> <parol> [--ai]}"
LOGIN="${2:?login kerak}"
PAROL="${3:?parol kerak}"
shift 3

AI=0
B_LOGIN=""
B_PAROL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --ai) AI=1; shift ;;
        --begona) B_LOGIN="${2:?}"; B_PAROL="${3:?}"; shift 3 ;;
        *) echo "Noma'lum argument: $1" >&2; exit 2 ;;
    esac
done

URL="${URL%/}"
ISH="$(mktemp -d)"
trap 'rm -rf "$ISH"' EXIT

OTDI=0
YIQILDI=0
log()  { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
ok()   { OTDI=$((OTDI+1));   printf '  [OK  ] %s\n' "$*"; }
fail() { YIQILDI=$((YIQILDI+1)); printf '  [XATO] %s\n' "$*"; }
check() { if [ "$1" = "1" ]; then ok "$2"; else fail "$2 ${3:+-- $3}"; fi; }

# JSON MAYDONINI PYTHON BILAN OLAMIZ.
#
# `jq` ATAYLAB ISHLATILMAYDI: u har serverda bo'lmaydi va yo'qligi
# skriptni `set -e` bilan JIMGINA yiqitardi. Python esa ilovaning
# O'ZI uchun ham shart, ya'ni u BOR.
#
# NOM QIDIRILADI, QOTIRILMAYDI. `python3` Linuxda bor, lekin
# Windowsda (ishlab chiqish mashinasi) YO'Q — u yerda `python`.
# Qotirilgan nom skriptni birinchi qadamdayoq yiqitdi va sabab
# `curl` xatosiga o'xshab ko'rindi. Topilmasa BAQIRIB to'xtaymiz:
# jimgina davom etish har shartni yolg'on qilardi.
PY_BIN=""
for k in "${E2E_PYTHON:-}" python3 python; do
    [ -n "$k" ] || continue
    if command -v "$k" >/dev/null 2>&1 && "$k" -c 'import json' >/dev/null 2>&1; then
        PY_BIN="$k"; break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "XATO: python topilmadi (python3/python). \`E2E_PYTHON\` bilan ko'rsating." >&2
    exit 2
fi
jsonf() { "$PY_BIN" -c '
import json, sys
d = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    if d is None: break
    d = d[int(k)] if isinstance(d, list) else d.get(k)
print("" if d is None else d)
' "$1"; }

# --- SINOV FAYLLARI ---------------------------------------------------------
# Matn ANIQ BILINADIGAN: javobni tekshirish uchun. Raqamlar ataylab
# g'ayrioddiy — ular ommaviy korpusda uchramasligi kerak, aks holda
# "fayldan topildi" bilan "korpusdan topildi" ni ajratib bo'lmasdi.
cat > "$ISH/zz_e2e.txt" <<'TXT'
ZZE2E TEXNIK TOPSHIRIQ
Kafolat muddati: 41 oy.
Yetkazib berish: 73 kun.
Oldindan tolov: 17 foiz.
Sertifikat: ZZE2E-9001 talab qilinadi.
TXT
SHA_KUTILGAN="$(sha256sum "$ISH/zz_e2e.txt" | cut -d' ' -f1)"

log "manzil: $URL"
log "sinov fayli: $(wc -c < "$ISH/zz_e2e.txt") bayt  sha=${SHA_KUTILGAN:0:16}"
echo

# =============================================================================
# 1. KIRISH
# =============================================================================
echo "--- 1. Kirish ---"
KOD="$(curl -sS -o "$ISH/login.json" -w '%{http_code}' \
    -c "$ISH/cookies" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$LOGIN\",\"password\":\"$PAROL\"}" \
    "$URL/auth/login")"
check "$([ "$KOD" = "200" ] && echo 1 || echo 0)" "login -> 200" "$KOD"
[ "$KOD" = "200" ] || { echo "Kirish yiqildi, davom etib bo'lmaydi."; exit 1; }

CSRF="$(jsonf csrf < "$ISH/login.json")"
check "$([ -n "$CSRF" ] && echo 1 || echo 0)" "CSRF tokeni berildi"
# SESSIYA TOKENI TANADA QAYTMASLIGI SHART (auth-4): u `HttpOnly`
# cookie'da. Tanada qaytsa uni JavaScript o'qiy olardi.
check "$(grep -qi '"token"' "$ISH/login.json" && echo 0 || echo 1)" \
      "sessiya tokeni TANADA qaytmaydi (HttpOnly cookie)"

K=(-b "$ISH/cookies" -c "$ISH/cookies" -H "X-CSRF-Token: $CSRF")

# =============================================================================
# 2. KOMPANIYA HUJJATI
# =============================================================================
echo
echo "--- 2. Kompaniya hujjati ---"
curl -sS "${K[@]}" -o "$ISH/doc.json" -H 'Content-Type: application/json' \
    -d '{"doc_type":"guarantee_letter","name":"ZZE2E kafolat"}' \
    "$URL/company/documents" >/dev/null
DID="$(jsonf id < "$ISH/doc.json")"
check "$([ -n "$DID" ] && echo 1 || echo 0)" "hujjat yaratildi" "id=$DID"

KOD="$(curl -sS "${K[@]}" -o "$ISH/up.json" -w '%{http_code}' \
    -F "file=@$ISH/zz_e2e.txt" \
    "$URL/company/documents/$DID/fayl")"
check "$([ "$KOD" = "200" ] && echo 1 || echo 0)" "fayl yuklandi -> 200" "$KOD"

# JAVOBDA SERVER YO'LI BO'LMASLIGI SHART.
check "$(grep -qiE '"kalit"|/opt/|/var/|[A-Za-z]:\\\\' "$ISH/up.json" \
         && echo 0 || echo 1)" "javobda SERVER YO'LI yo'q"

# --- HOLAT KUZATUVI ---
HOLAT=""
for _ in $(seq 1 40); do
    curl -sS "${K[@]}" -o "$ISH/holat.json" "$URL/company/documents/$DID/fayl" >/dev/null
    HOLAT="$(jsonf holat < "$ISH/holat.json")"
    case "$HOLAT" in yuklandi|ajratilmoqda) sleep 1 ;; *) break ;; esac
done
check "$([ "$HOLAT" = "tayyor" ] && echo 1 || echo 0)" \
      "holat \`tayyor\` ga o'tdi" "$HOLAT"
BELGI="$(jsonf matn_belgi < "$ISH/holat.json")"
check "$([ -n "$BELGI" ] && [ "$BELGI" -gt 0 ] 2>/dev/null && echo 1 || echo 0)" \
      "matn HAQIQATAN ajratildi" "$BELGI belgi"

# --- YUKLAB OLISH VA BAYT TENGLIGI ---
curl -sS "${K[@]}" -o "$ISH/olingan.bin" -D "$ISH/sarlavha.txt" \
    "$URL/company/documents/$DID/download" >/dev/null
SHA_OLINGAN="$(sha256sum "$ISH/olingan.bin" | cut -d' ' -f1)"
check "$([ "$SHA_OLINGAN" = "$SHA_KUTILGAN" ] && echo 1 || echo 0)" \
      "yuklab olingan BAYT yuklanganiga TENG" "${SHA_OLINGAN:0:16}"
check "$(grep -qi 'content-disposition: attachment' "$ISH/sarlavha.txt" \
         && echo 1 || echo 0)" "\`attachment\` sifatida beriladi"
check "$(grep -qi 'x-content-type-options: nosniff' "$ISH/sarlavha.txt" \
         && echo 1 || echo 0)" "\`nosniff\` sarlavhasi bor"
check "$(grep -qi 'cache-control:.*no-store' "$ISH/sarlavha.txt" \
         && echo 1 || echo 0)" "kesh O'CHIQ (proksi boshqasiga bermasin)"

# --- CHEGARA: PROKSI QATLAMI HAM SINALADI ---
# Bu `TestClient` da MUMKIN EMAS: u tarmoqqa chiqmaydi va Caddy
# umuman yo'lda turmaydi.
head -c $((30 * 1024 * 1024)) /dev/zero | tr '\0' 'a' > "$ISH/katta.txt"
KOD="$(curl -sS "${K[@]}" -o /dev/null -w '%{http_code}' \
    -F "file=@$ISH/katta.txt" \
    "$URL/company/documents/$DID/fayl" || echo "000")"
check "$([ "$KOD" = "413" ] && echo 1 || echo 0)" \
      "30 MB rad etiladi -> 413 (ilova yoki proksi)" "$KOD"

# SOXTA KENGAYTMA UCHUN ALOHIDA FAYL.
#
# curl ning `;filename=` va `;type=` qo'shimchalari ba'zi
# qurilmalarda (mingw/Windows) YO'LNING bir qismi deb o'qiladi va
# so'rov `(26) Failed to open/read local data` bilan yiqiladi --
# sabab esa SERVERGA o'xshab ko'rinadi. Nusxa olish portativ.
#
# `;type=` umuman kerak emas: server mijoz bergan MIME ga
# ISHONMAYDI (`sniff_magic` baytlarga qaraydi), ya'ni uni yuborish
# hech narsani o'lchamasdi.
cp "$ISH/zz_e2e.txt" "$ISH/zz.exe"
KOD="$(curl -sS "${K[@]}" -o /dev/null -w '%{http_code}' \
    -F "file=@$ISH/zz.exe" \
    "$URL/company/documents/$DID/fayl")"
check "$([ "$KOD" = "422" ] && echo 1 || echo 0)" \
      "qo'llab-quvvatlanmaydigan tur -> 422" "$KOD"

# =============================================================================
# 3. AI CHAT BIRIKTIRMASI
# =============================================================================
echo
echo "--- 3. AI chat biriktirmasi ---"
curl -sS "${K[@]}" -o "$ISH/sess.json" -H 'Content-Type: application/json' \
    -d '{"manba":"global"}' "$URL/chat/sessions" >/dev/null
SID="$(jsonf session_id < "$ISH/sess.json")"
check "$([ -n "$SID" ] && echo 1 || echo 0)" "bo'sh sessiya ochildi" "$SID"

KOD="$(curl -sS "${K[@]}" -o "$ISH/chatup.json" -w '%{http_code}' \
    -F "file=@$ISH/zz_e2e.txt" \
    "$URL/chat/sessions/$SID/fayl")"
check "$([ "$KOD" = "201" ] && echo 1 || echo 0)" "chatga yuklandi -> 201" "$KOD"
YID="$(jsonf id < "$ISH/chatup.json")"
BOSH_HOLAT="$(jsonf holat < "$ISH/chatup.json")"
# "READY" DARHOL QAYTMASLIGI SHART: u faqat matn ajratilgach keladi.
check "$([ "$BOSH_HOLAT" != "tayyor" ] && echo 1 || echo 0)" \
      "javob DARHOL \`tayyor\` EMAS" "$BOSH_HOLAT"

HOLAT=""
for _ in $(seq 1 40); do
    curl -sS "${K[@]}" -o "$ISH/chatholat.json" "$URL/chat/sessions/$SID/fayl" >/dev/null
    HOLAT="$(jsonf 0.holat < "$ISH/chatholat.json")"
    case "$HOLAT" in yuklandi|ajratilmoqda) sleep 1 ;; *) break ;; esac
done
check "$([ "$HOLAT" = "tayyor" ] && echo 1 || echo 0)" \
      "biriktirma \`tayyor\`" "$HOLAT"
CHUNK="$(jsonf 0.chunk_soni < "$ISH/chatholat.json")"
check "$([ -n "$CHUNK" ] && [ "$CHUNK" -gt 0 ] 2>/dev/null && echo 1 || echo 0)" \
      "bo'lak yaratildi" "$CHUNK"

# =============================================================================
# 4. IJARACHI CHEGARASI — BOSHQA KOMPANIYA
# =============================================================================
echo
echo "--- 4. Ijarachi chegarasi ---"
if [ -n "$B_LOGIN" ]; then
    KOD="$(curl -sS -o /dev/null -w '%{http_code}' -c "$ISH/c2" \
        -H 'Content-Type: application/json' \
        -d "{\"username\":\"$B_LOGIN\",\"password\":\"$B_PAROL\"}" \
        "$URL/auth/login")"
    if [ "$KOD" = "200" ]; then
        K2=(-b "$ISH/c2")
        check "$([ "$(curl -sS "${K2[@]}" -o /dev/null -w '%{http_code}' \
              "$URL/company/documents/$DID/download")" = "404" ] && echo 1 || echo 0)" \
              "BEGONA kompaniya hujjatni yuklab ololmaydi -> 404"
        check "$([ "$(curl -sS "${K2[@]}" -o /dev/null -w '%{http_code}' \
              "$URL/chat/fayl/$YID/download")" = "404" ] && echo 1 || echo 0)" \
              "BEGONA kompaniya chat faylini ololmaydi -> 404"
        check "$([ "$(curl -sS "${K2[@]}" -o /dev/null -w '%{http_code}' \
              "$URL/chat/sessions/$SID/fayl")" = "404" ] && echo 1 || echo 0)" \
              "BEGONA kompaniya sessiyani ko'rmaydi -> 404"
    else
        fail "ikkinchi kompaniya kirolmadi ($KOD)"
    fi
else
    # JIM O'TMAYDI. Ijarachi chegarasi — eng qimmat invariant va uni
    # o'lchamasdan "E2E o'tdi" deyish YOLG'ON bo'lardi.
    fail "ijarachi chegarasi O'LCHANMADI — \`--begona <login> <parol>\` bering"
fi

# TOKENSIZ — har doim sinaladi.
check "$([ "$(curl -sS -o /dev/null -w '%{http_code}' \
      "$URL/company/documents/$DID/download")" = "401" ] && echo 1 || echo 0)" \
      "tokensiz -> 401"

# =============================================================================
# 5. AI JAVOBI — PULLIK, ATAYLAB IXTIYORIY
# =============================================================================
echo
echo "--- 5. AI javobi va iqtibos ---"
if [ "$AI" = "1" ]; then
    curl -sS "${K[@]}" -o "$ISH/javob.txt" -H 'Content-Type: application/json' \
        -d "{\"session_id\":\"$SID\",\"message\":\"Faqat shu fayl asosida javob ber. Kafolat muddati qancha?\",\"lang\":\"uz\"}" \
        "$URL/chat" >/dev/null || true
    # JAVOB VA IQTIBOS AJRATILADI.
    #
    # XOM OQIMDAN `grep 41` YETARLI EMAS: iqtibos hodisasi fayl
    # PARCHASINI ham olib keladi va unda `41` BOR. Yani shart
    # modelning JAVOBINI emas, ozi yuborgan MATNNI topib yashil
    # bolardi -- asbob ozini olchaydi. SSE hodisalari TURIGA
    # kora ajratiladi: `token` -> javob, `citation` -> manba.
    "$PY_BIN" - "$ISH/javob.txt" > "$ISH/ajratilgan.txt" <<'PYSSE'
import io, json, sys
xom = io.open(sys.argv[1], encoding="utf-8", errors="replace").read()
javob, manba, hodisa = [], [], None
for q in xom.splitlines():
    if q.startswith("event:"):
        hodisa = q.split(":", 1)[1].strip()
    elif q.startswith("data:"):
        try:
            j = json.loads(q.split(":", 1)[1].strip())
        except Exception:
            continue
        if hodisa == "token":
            javob.append(j.get("text") or j.get("t") or "")
        elif hodisa == "citation":
            manba.append(j)
print("JAVOB\t" + "".join(javob).replace("\n", " "))
for c in manba:
    print("MANBA\t%s\t%s" % (c.get("manba_turi"), c.get("file_name")))
PYSSE
    JAVOB="$(grep -m1 '^JAVOB' "$ISH/ajratilgan.txt" | cut -f2-)"
    check "$(printf '%s' "$JAVOB" | grep -q '41' && echo 1 || echo 0)" \
          "MODEL JAVOBIDA fayldagi raqam (41 oy) bor" "$(printf '%.60s' "$JAVOB")"
    check "$(grep -qP '^MANBA\tchat_upload' "$ISH/ajratilgan.txt" && echo 1 || echo 0)" \
          "iqtibos \`chat_upload\` manbasidan"
    check "$(grep -q 'zz_e2e.txt' "$ISH/ajratilgan.txt" && echo 1 || echo 0)" \
          "iqtibos YUKLANGAN faylga ishora qiladi"
else
    # SKIP JIM EMAS. Bu bo'lim PULLIK model chaqiradi, shuning uchun
    # ATAYLAB ixtiyoriy — lekin o'lchanmagani AYTILADI.
    fail "AI javobi va IQTIBOS O'LCHANMADI — \`--ai\` bering (PULLIK chaqiruv)"
fi

# =============================================================================
echo
echo "=============================================================="
printf 'NATIJA: %d o%s, %d yiqildi\n' "$OTDI" "'tdi" "$YIQILDI"
echo "=============================================================="
echo "DIQQAT: bu BRAUZER sinovi EMAS. Tugma bosish, fayl tanlash"
echo "dialogi va UI holati (Processing -> Ready) SINALMADI."
[ "$YIQILDI" -eq 0 ]
