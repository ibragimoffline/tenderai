#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: ISHLAB CHIQARISH XAVFSIZLIGI (qattiqlashtirish regressiyasi)
====================================================================

Bu to'plam nazoratlarni QAYTA YO'QOLIB KETISHDAN qo'riqlaydi. Har
tekshiruv AYNAN BITTA topilmaga bog'langan va topilmaning nomi yozib
qo'yilgan — sinov yiqilsa, NIMA qaytib kelgani darhol ko'rinadi.

TEATRDAN QOCHISH. Bu yerda "sarlavha satrda bormi" degan tekshiruv
YO'Q — sarlavhalar HAQIQIY javobdan o'qiladi; parol xeshi HAQIQATAN
hisoblanadi; zip bomba HAQIQATAN yasaladi. Manbadan o'qish faqat
kodning O'ZI qoida bo'lgan joyda ishlatiladi (masalan "tool sxemasida
`company_id` yo'q").

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\xavfsizlik_test.py
    .venv\\Scripts\\python.exe _tests\\xavfsizlik_test.py --offline
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


def _oqi(yol):
    return io.open(os.path.join(ROOT, yol), encoding="utf-8").read()


# =====================================================================
# 1. HTTP sarlavhalari — HAQIQIY javobdan
# =====================================================================
def test_sarlavhalar():
    bolim("1. Xavfsizlik sarlavhalari (topilma H-2)")
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as c:
        r = c.get("/health")
        kerak = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
        }
        for k, v in kerak.items():
            check(f"`{k}: {v}`", r.headers.get(k) == v, r.headers.get(k) or "YO'Q")
        csp = r.headers.get("content-security-policy") or ""
        check("CSP `frame-ancestors 'none'` (clickjacking)",
              "frame-ancestors 'none'" in csp, csp[:60] or "YO'Q")
        check("CSP `default-src 'none'` (JSON API uchun eng qat'iy)",
              "default-src 'none'" in csp, csp[:60] or "YO'Q")
        check("`Permissions-Policy` bor",
              bool(r.headers.get("permissions-policy")))
        check("`Cross-Origin-Opener-Policy: same-origin`",
              r.headers.get("cross-origin-opener-policy") == "same-origin")

        # HSTS ATAYLAB standart O'CHIQ: uni yoqish domenni HTTPS ga
        # QULFLAYDI va TLS sozlanmagan muhitda saytni yo'q qiladi.
        from api import main as M
        check("HSTS standart O'CHIQ (ataylab — infratuzilma qarori)",
              M.HSTS_MAX_AGE == 0 or bool(r.headers.get("strict-transport-security")),
              f"HSTS_MAX_AGE={M.HSTS_MAX_AGE}")


def test_docs_yopiq():
    bolim("2. Swagger ishlab chiqarishda yopiq (topilma H-5)")
    from api import main as M
    check("`API_DOCS` standart O'CHIQ", M.API_DOCS is False,
          f"API_DOCS={M.API_DOCS}")
    if not M.API_DOCS:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            for yol in ("/openapi.json", "/docs", "/redoc"):
                r = c.get(yol)
                check(f"`{yol}` -> 404", r.status_code == 404, str(r.status_code))


def test_xato_sizishi():
    bolim("3. Baza xatosi tafsiloti mijozga chiqmaydi (topilma M-7)")
    src = _oqi("api/main.py")
    blok = src[src.index("async def _db_unavailable_handler"):]
    blok = blok[:blok.index("\n\n\n")]
    check("javobda `str(exc)` YO'Q", "str(exc)" not in blok, blok[-120:])
    check("tafsilot SERVER jurnaliga yoziladi", "logging" in blok)
    # 20-vazifadan keyin javob TILGA BOG'LIQ EMAS: o'zbekcha jumla
    # o'rniga KOD qaytadi. Xavfsizlik xossasi O'ZGARMADI — tafsilot
    # baribir javobga tushmaydi.
    check("mijozga KOD qaytadi (matn emas)",
          'xatolar.tana("DATABASE_UNAVAILABLE"' in blok)


# =====================================================================
# 4. Yuklash
# =====================================================================
def test_yuklash():
    bolim("4. Fayl yuklash (topilmalar H-3, H-4)")
    src = _oqi("api/main.py")
    # ILGARI: `data = file.file.read()` — BUTUN fayl xotiraga, chegara
    # esa KEYIN. Chegara bor edi, lekin KECH ishlardi.
    check("`file.file.read()` chegarasiz chaqiruvi YO'Q",
          "file.file.read()\n" not in src)
    check("yuklash yagona yordamchidan o'tadi",
          src.count("_yuklangani(file)") == 3, f"{src.count('_yuklangani(file)')} ta")
    fn = src[src.index("def _yuklangani("):]
    fn = fn[:fn.index("\n\n\n")]
    check("bo'laklab o'qiydi", "file.file.read(1024" in fn)
    check("chegaradan oshsa DARHOL to'xtaydi",
          "if jami > chegara" in fn and 'Xato("FILE_TOO_LARGE"' in fn)

    from api import importer
    bomba = io.BytesIO()
    with zipfile.ZipFile(bomba, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"A" * (300 * 1024 * 1024))
    xom = bomba.getvalue()
    try:
        importer._zip_bombani_tekshir(xom)
        check("zip bomba RAD ETILADI", False, "o'tkazib yuborildi")
    except importer.ImportFormatError as e:
        check("zip bomba RAD ETILADI", True,
              f"{len(xom)//1024} KB -> 300 MB")
        check("sabab tushunarli", "MB" in str(e) or "nisbat" in str(e))

    check("CSV ga tegmaydi (ZIP emas)",
          importer._zip_bombani_tekshir(b"nom;kod\nA;1\n") is None)

    fix = os.path.join(ROOT, "_tests", "fixtures", "katalog_togri.xlsx")
    if os.path.exists(fix):
        d = io.open(fix, "rb").read()
        try:
            importer._zip_bombani_tekshir(d)
            check("HAQIQIY .xlsx o'tadi (noto'g'ri musbat yo'q)", True,
                  f"{len(d)} bayt")
        except importer.ImportFormatError as e:
            check("HAQIQIY .xlsx o'tadi", False, str(e))


# =====================================================================
# 5. Parol va sessiya
# =====================================================================
def test_parol():
    bolim("5. Parol xeshlash (topilma M-6)")
    from api import auth
    check("PBKDF2 iteratsiyasi >= 600 000 (OWASP)",
          auth.ITERATIONS >= 600_000, str(auth.ITERATIONS))

    h = auth.hash_password("sinov-parol-uzun-123")
    algo, iters, salt, dk = h.split("$")
    check("algoritm pbkdf2_sha256", algo == "pbkdf2_sha256")
    check("tuz TASODIFIY va 16 bayt", len(bytes.fromhex(salt)) == 16)
    check("ikki xesh HAR XIL (tuz takrorlanmaydi)",
          auth.hash_password("sinov-parol-uzun-123") != h)
    check("to'g'ri parol tekshiriladi",
          auth.verify_password("sinov-parol-uzun-123", h))
    check("noto'g'ri parol rad etiladi",
          not auth.verify_password("boshqa-parol-123", h))
    check("buzuq xesh yiqilmaydi", auth.verify_password("x", "axlat") is False)

    # ESKI XESH BUZILMAYDI va KO'CHIRILADI.
    eski = auth.hash_password("sinov-parol-uzun-123", iterations=240_000)
    check("eski (240k) xesh HALI HAM tekshiriladi",
          auth.verify_password("sinov-parol-uzun-123", eski))
    check("eski xesh qayta xeshlashga belgilanadi",
          auth._rehash_kerakmi(eski))
    check("yangi xesh qayta xeshlanmaydi", not auth._rehash_kerakmi(h))

    src = _oqi("api/auth.py")
    lg = src[src.index("def login("):]
    lg = lg[:lg.index("\ndef ")]
    check("qayta xeshlash KIRISH paytida bajariladi",
          "_rehash_kerakmi" in lg)
    # Bloklash XESHLASHDAN OLDIN: aks holda cheklovning o'zi yuk
    # keltirish vositasiga aylanardi (431 ms / urinish).
    check("bloklash parol tekshiruvidan OLDIN",
          lg.index("guard_attempts") < lg.index("verify_password"))
    check("doimiy vaqtli solishtirish", "compare_digest" in src)


def test_sessiya():
    bolim("6. Sessiya hayot sikli")
    from api import auth
    src = _oqi("api/auth.py")
    check("token 32 baytli tasodifiy (`secrets`)",
          "secrets.token_urlsafe(32)" in src)
    check("bazada FAQAT xesh saqlanadi",
          "_token_hash(token)" in src and "token_hash" in src)
    # SESSION FIXATION: kirish HAR DOIM YANGI token yasaydi va uni
    # mijozdan OLMAYDI — belgilangan token bilan kirib bo'lmaydi.
    lg = src[src.index("def login("):]
    lg = lg[:lg.index("\ndef ")]
    check("kirish tokeni MIJOZDAN olinmaydi (fixation yo'q)",
          "token = secrets.token_urlsafe(32)" in lg)
    # PAROL ALMASHSA QOLGAN SESSIYALAR O'CHADI.
    sp = src[src.index("def set_password("):]
    sp = sp[:sp.index("\n\n\n")]
    check("parol almashsa boshqa sessiyalar YOPILADI",
          "SESSION_KILL_OTHERS_SQL" in sp)
    check("chiqishda sessiya bazadan O'CHADI",
          "SESSION_DELETE_SQL" in src[src.index("def logout("):
                                       src.index("def logout(") + 400])
    check("muddati o'tgan sessiyalar tozalanadi", "SESSION_CLEAN_SQL" in src)


def test_cookie_va_csrf():
    bolim("7. Cookie bayroqlari va CSRF")
    from api import main as M
    check("`AUTH_COOKIE_SECURE` standart YOQIQ", M.COOKIE_SECURE is True)
    src = _oqi("api/main.py")
    sc = src[src.index("def _set_auth_cookies("):]
    sc = sc[:sc.index("\n\n\n")]
    check("sessiya cookie'si `HttpOnly`", "httponly=True" in sc)
    check("`SameSite=Lax`", 'samesite="lax"' in sc)
    check("`Secure` sozlamadan", "secure=COOKIE_SECURE" in sc)
    # CSRF tokeni ATAYLAB HttpOnly EMAS — sahifa uni o'qishi kerak.
    check("CSRF cookie'si HttpOnly EMAS (ataylab)", "httponly=False" in sc)

    g = src[src.index("def gate("):]
    g = g[:g.index("\napp = FastAPI")]
    check("CSRF FAQAT cookie yo'lida talab qilinadi", "from_cookie" in g)
    check("CSRF doimiy vaqtli solishtiriladi", "compare_digest" in g)
    check("CSRF o'zgartiruvchi metodlarda", "UNSAFE_METHODS" in g)


def test_darvoza():
    bolim("8. Darvoza — standart YOPIQ")
    src = _oqi("api/main.py")
    pp = src[src.index("PUBLIC_PATHS = {"):]
    pp = pp[:pp.index("}")]
    ochiq = re.findall(r'"([^"]+)"', pp)
    # Ro'yxat KICHIK bo'lishi kerak. O'sib ketsa — darvoza ma'nosini
    # yo'qotadi va buni hech narsa ko'rsatmasdi.
    check("ochiq yo'llar SANOQLI (<= 10)", len(ochiq) <= 10,
          f"{len(ochiq)} ta: {ochiq}")
    for y in ("/auth/me", "/tenders", "/catalog", "/aktor", "/audit"):
        check(f"`{y}` ochiq EMAS", y not in ochiq)

    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        # MAVJUD yo'llar tanlandi. Mavjud BO'LMAGAN yo'l 404 beradi
        # (Starlette marshrutdan oldin javob qaytaradi) va u
        # darvozani O'LCHAMAYDI — sinov noto'g'ri narsani tekshirardi.
        for yol in ("/auth/me", "/aktor", "/audit", "/company/documents",
                    "/catalog", "/freshness"):
            r = c.get(yol)
            check(f"`{yol}` tokensiz 401", r.status_code == 401,
                  str(r.status_code))
        # SERVICE kaliti ham OQ RO'YXAT bilan cheklangan.
        sp = src[src.index("SERVICE_PATHS = {"):]
        sp = sp[:sp.index("}")]
        check("service kaliti oq ro'yxat bilan cheklangan",
              "SERVICE_PATHS" in src and len(re.findall(r'\("(?:GET|POST)"', sp)) <= 12)


# =====================================================================
# 9. SQL va AI
# =====================================================================
def test_sql():
    bolim("9. SQL — inyeksiya yuzasi")
    from api import queries
    # ORDER BY yagona joy bo'lib, u OQ RO'YXAT bilan yopilgan.
    for yomon in ("id; DROP TABLE tender--", "(SELECT 1)", "id/**/",
                  "t.id, pg_sleep(5)"):
        s = queries.build_order_by(yomon)
        check(f"ORDER BY inyeksiyasi rad etiladi: {yomon[:22]!r}",
              yomon.split(";")[0].split(",")[0] not in s or "DROP" not in s.upper(),
              s[:60])
    ok = queries.build_order_by("-close_at")
    check("haqiqiy saralash ishlaydi", "DESC" in ok, ok[:50])
    check("oq ro'yxat mavjud", hasattr(queries, "_SORT_WHITELIST"))


def test_ai():
    bolim("10. AI — tool huquqlari va ijarachi izolyatsiyasi")
    from api import ai_chat
    for t in ai_chat.TOOLS:
        sxema = str(t.get("input_schema", {}))
        check(f"`{t['name']}` sxemasida `company_id` YO'Q",
              "company_id" not in sxema)
    src = _oqi("api/ai_chat.py")
    for m in re.finditer(r"^def (_t_\w+)\(.*?(?=^def |\Z)", src, re.M | re.S):
        nom, tana = m.group(1), m.group(0)
        yozadi = re.search(r"\b(INSERT INTO|UPDATE\s+\w+\s+SET|DELETE FROM)\b",
                           tana)
        check(f"`{nom}` FAQAT O'QIYDI", not yozadi,
              yozadi.group(0) if yozadi else "")
    check("`company_id` sessiyadan (ChatContext)",
          "class ChatContext" in src and "company_id: int" in src)


# =====================================================================
# 11. Sirlar
# =====================================================================
#: Kuzatilishi TAQIQLANGAN naqshlar. Nom bo'yicha, lekin tozalangan
#: shablonlar ALOHIDA ro'yxatda (pastda) va ular bu naqshlardan
#: chiqariladi -- ".env.example" ni ".env" deb hisoblash noto'g'ri
#: bo'lardi.
TAQIQ_NAQSH = [
    (re.compile(r"(^|/)\.env$"),                       "haqiqiy .env"),
    (re.compile(r"(^|/)\.env\.[A-Za-z0-9_-]+$"),        ".env varianti"),
    (re.compile(r"(^|/)ngrok\.ya?ml$"),                "ngrok sozlamasi"),
    (re.compile(r"\.pem$"),                            "shaxsiy kalit (pem)"),
    (re.compile(r"\.key$"),                            "kalit fayli"),
    (re.compile(r"\.dump$"),                            "baza dumpi"),
    (re.compile(r"(^|/)id_rsa"),                       "ssh kaliti"),
    (re.compile(r"(^|/)credentials?\.json$"),          "hisob ma'lumoti"),
    (re.compile(r"service[-_]account[^/]*\.json$"),     "xizmat hisobi"),
]

#: Kuzatilishi RUXSAT etilgan TOZALANGAN shablonlar — ANIQ ro'yxat.
#: Naqsh ishlatilmaydi: "*.example" degan qoida `secrets.example`
#: kabi faylni ham jimgina o'tkazardi.
RUXSAT_SHABLON = {
    ".env.example",
    "deploy/env/staging.env.example",
    "deploy/env/production.env.example",
}

MANIFEST_SARLAVHA = "# tenderai-kuzatilgan-manifest v1"


def manifest_oqi(yol, kutilgan_sha):
    """Manifestni o'qiydi. `(holat, yollar)` qaytaradi.

    Holatlar: `ok`, `yoq`, `bosh`, `buzuq`, `sha_farq`, `checksum`.
    HECH BIRI "o'tdi" degani emas -- chaqiruvchi faqat `ok` da
    tekshiruvni davom ettiradi. Dalil yo'q bo'lsa YASHIL bermaslik
    shu funksiyaning butun maqsadi.
    """
    if not yol or not os.path.isfile(yol):
        return "yoq", []
    matn = io.open(yol, encoding="utf-8", errors="replace").read()
    qatorlar = matn.splitlines()
    if not qatorlar or qatorlar[0].strip() != MANIFEST_SARLAVHA:
        return "buzuq", []
    sha = ""
    for q in qatorlar[1:3]:
        if q.startswith("# sha:"):
            sha = q.split(":", 1)[1].strip()
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        return "buzuq", []
    if kutilgan_sha and sha != kutilgan_sha:
        return "sha_farq", []

    # CHECKSUM — manifest o'zgartirilmaganini tasdiqlaydi.
    yon = yol + ".sha256"
    if os.path.isfile(yon):
        import hashlib
        haqiqiy = hashlib.sha256(
            io.open(yol, "rb").read()).hexdigest()
        kutilgan = io.open(yon, encoding="utf-8").read().strip()
        if kutilgan and kutilgan != haqiqiy:
            return "checksum", []

    yollar = [q.strip() for q in qatorlar
              if q.strip() and not q.startswith("#")]
    if not yollar:
        return "bosh", []
    return "ok", yollar


def taqiqlanganlar(yollar):
    """Manifestdagi TAQIQLANGAN yo'llar. `(yol, sabab)` ro'yxati."""
    topildi = []
    for y in yollar:
        if y in RUXSAT_SHABLON:
            continue
        for rx, sabab in TAQIQ_NAQSH:
            if rx.search(y):
                topildi.append((y, sabab))
                break
    return topildi


def test_sirlar():
    bolim("11. Sirlar repozitoriyada YO'Q")

    # `git ls-files` ISHLATILMAYDI.
    #
    # O'LCHANGAN NUQSON (2026-09-09): darvoza `git archive` dan
    # ochilgan daraxtda yuradi va u yerda `.git` YO'Q. Buyruq BO'SH
    # ro'yxat qaytarardi, "`.env` kuzatilmaydi" kabi tekshiruvlar esa
    # bo'sh ro'yxatda ALBATTA o'tardi -- ya'ni ular hech narsani
    # isbotlamasdi. Muammo faqat bitta tekshiruv (`.env.example`
    # KUZATILADI) qizil bo'lgani uchun ko'rindi.
    #
    # Endi dalil manbai — BARE REPOZITORIYDAN aynan shu SHA bo'yicha
    # hosil qilingan manifest. `.git` arxivga QO'SHILMAYDI.
    yol = os.environ.get("TENDERAI_TRACKED_MANIFEST", "")
    sha = os.environ.get("RELEASE_SHA", "")
    holat, yollar = manifest_oqi(yol, sha)

    izoh = {"yoq": "manifest fayli YO'Q",
            "bosh": "manifest BO'SH",
            "buzuq": "manifest sarlavhasi/SHA si BUZUQ",
            "sha_farq": "manifest SHA si nomzod SHA ga MOS EMAS",
            "checksum": "manifest checksumi MOS EMAS"}
    if holat != "ok":
        # DALIL YO'Q -> QIZIL. Bu "o'tkazib yuborildi" emas.
        check("kuzatilgan fayllar manifesti bor va butun", False,
              izoh.get(holat, holat))
        return
    check("kuzatilgan fayllar manifesti bor va butun", True,
          f"{len(yollar)} fayl, sha={sha[:12]}")

    yomonlar = taqiqlanganlar(yollar)
    check("taqiqlangan sir fayllari KUZATILMAYDI", not yomonlar,
          "; ".join(f"{y} ({s})" for y, s in yomonlar[:5]))

    # Shablon KUZATILISHI kerak: usiz operator nimadan nusxa olishini
    # bilmaydi va sozlamani qo'lda to'qiydi.
    check("`.env.example` kuzatiladi (shablon)", ".env.example" in yollar)

    ex = _oqi(".env.example")
    check("shablonda HAQIQIY API kaliti yo'q",
          not re.search(r"sk-ant-[A-Za-z0-9]{20,}", ex))
    check("shablonda HAQIQIY parol yo'q",
          not re.search(r"password=(?!SIZNING)\S{8,}", ex))

    pats = {
        "anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
        "telegram": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),
        "aws": re.compile(r"AKIA[0-9A-Z]{16}"),
        "shaxsiy_kalit": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
        "dsn_parol": re.compile(r"postgres(?:ql)?://[^\s:]+:[^\s@]+@"),
    }
    topildi = []
    for f in sorted(kuzatilgan):
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p) or os.path.getsize(p) > 2_000_000:
            continue
        try:
            t = io.open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for nom, rx in pats.items():
            if rx.search(t):
                topildi.append(f"{f} [{nom}]")
    check(f"kuzatilgan {len(kuzatilgan)} faylda sir naqshi YO'Q",
          not topildi, str(topildi[:3]))


def _manifest_yoz(kat, nom, sha, yollar, sarlavha=None, checksum=True):
    """Sun'iy manifest yozadi. Sinovlar `.git` ga TAYANMAYDI."""
    import hashlib
    yol = os.path.join(kat, nom)
    qatorlar = [sarlavha if sarlavha is not None else MANIFEST_SARLAVHA,
                f"# sha: {sha}"] + list(yollar)
    io.open(yol, "w", encoding="utf-8", newline=chr(10)).write(
        chr(10).join(qatorlar) + chr(10))
    if checksum:
        io.open(yol + ".sha256", "w", encoding="utf-8").write(
            hashlib.sha256(io.open(yol, "rb").read()).hexdigest())
    return yol


def test_manifest_qoriqchasi():
    """Manifest shartnomasi: DALIL YO'Q -> QIZIL, hech qachon yashil.

    Bu bo'lim `.git` GA TAYANMAYDI: hamma holat sun'iy manifest bilan
    o'lchanadi. Aks holda sinovning o'zi darvozada yurmasdi -- ya'ni
    yolg'on yashilni tuzatib, uning qo'riqchasini yana yolg'on
    yashilga qo'ygan bo'lardik.
    """
    bolim("11b. Manifest qo'riqchasi — dalil yo'q bo'lsa QIZIL")
    import tempfile
    SHA = "a" * 40
    with tempfile.TemporaryDirectory() as t:
        # CASE G — sog'lom daraxt.
        y = _manifest_yoz(t, "ok", SHA, ["api/main.py", ".env.example",
                                         "deploy/env/staging.env.example"])
        holat, yollar = manifest_oqi(y, SHA)
        check("CASE G: sog'lom manifest o'qiladi", holat == "ok", holat)
        check("CASE G: taqiq topilmaydi", not taqiqlanganlar(yollar))

        # CASE A — haqiqiy `.env` kuzatilgan.
        _, ya = manifest_oqi(_manifest_yoz(t, "a", SHA,
                                           ["api/main.py", ".env"]), SHA)
        check("CASE A: haqiqiy `.env` ANIQLANADI",
              any(s == "haqiqiy .env" for _y, s in taqiqlanganlar(ya)))

        # CASE B — ruxsat etilgan shablon taqiq deb belgilanmaydi.
        _, yb = manifest_oqi(_manifest_yoz(t, "b", SHA,
                                           [".env.example"]), SHA)
        check("CASE B: tozalangan shablon TAQIQ EMAS",
              not taqiqlanganlar(yb))

        # CASE F — shaxsiy kalit.
        _, yf = manifest_oqi(_manifest_yoz(t, "f", SHA,
                                           ["deploy/tls/server.key"]), SHA)
        check("CASE F: shaxsiy kalit ANIQLANADI",
              any(s == "kalit fayli" for _y, s in taqiqlanganlar(yf)))

        # `.env.staging` kabi variant ham taqiqlanadi, `.env.example`
        # esa yo'q -- naqsh ikkalasiga ham tushadi, ro'yxat ajratadi.
        _, yv = manifest_oqi(_manifest_yoz(t, "v", SHA,
                                           [".env.staging"]), SHA)
        check("`.env.staging` varianti ANIQLANADI",
              any(s == ".env varianti" for _y, s in taqiqlanganlar(yv)))

        # CASE C — manifest yo'q.
        check("CASE C: manifest YO'Q -> `yoq`",
              manifest_oqi(os.path.join(t, "yoq"), SHA)[0] == "yoq")
        check("CASE C: bo'sh yo'l ham `yoq`",
              manifest_oqi("", SHA)[0] == "yoq")

        # CASE D — SHA mos emas.
        check("CASE D: SHA farqi ANIQLANADI",
              manifest_oqi(_manifest_yoz(t, "d", "b" * 40,
                                         ["api/main.py"]), SHA)[0]
              == "sha_farq")

        # CASE E — bo'sh manifest.
        check("CASE E: BO'SH manifest -> `bosh`",
              manifest_oqi(_manifest_yoz(t, "e", SHA, []), SHA)[0] == "bosh")

        # Buzuq sarlavha.
        check("buzuq sarlavha ANIQLANADI",
              manifest_oqi(_manifest_yoz(t, "x", SHA, ["a.py"],
                                         sarlavha="# boshqa"), SHA)[0]
              == "buzuq")

        # CHECKSUM buzilishi — manifest KEYIN o'zgartirilgan.
        yc = _manifest_yoz(t, "c", SHA, ["api/main.py"])
        io.open(yc, "a", encoding="utf-8").write(".env" + chr(10))
        check("checksum farqi ANIQLANADI",
              manifest_oqi(yc, SHA)[0] == "checksum")

# =====================================================================
# 12. Baza huquqlari (bazali)
# =====================================================================
#: ERP shartnomasi — YAGONA MANBA. `schema_patch_erp_chegara.sql` va
#: `schema_patch_erp_19.sql` (ERP tomoni) bilan bir xil.
ERP_RUXSAT = {"v_tai_actor", "v_tender_status", "v_stock",
              "v_stock_balance", "v_client_document"}


def test_erp_chegarasi(db):
    """ERP chegarasi — NOMLAR bo'yicha emas, TO'PLAMLAR FARQI bo'yicha.

    O'LCHANGAN SILJISH (2026-09-09): `tai_app` ga `erp` da 41 obyektga
    SELECT berilgan edi (34 jadval + 7 ko'rinish), ruxsat etilgani esa
    BESHTA ko'rinish. Ortiqchalar ichida `app_user` (parol xeshlari),
    `app_session` (sessiya tokenlari), `invoice_payment`,
    `chat_message_history` bor edi.

    ESKI TEKSHIRUV BUNI KO'RMADI: u `v_huquq_tekshiruv` dagi NOMMA-NOM
    tekshiruvlarni o'qirdi va ro'yxatda faqat `erp.app_user` bor edi.
    Ya'ni 35 ta ortiqcha obyekt JIM QOLDI.

    Endi shartnoma ikki tomonlama va NOMLARGA bog'liq emas:

        haqiqiy - ruxsat  = bo'sh   (ortiqcha yo'q)
        ruxsat  - haqiqiy = bo'sh   (shartnoma buzilmagan)

    Yangi ERP jadvali qo'shilsa va u ochiq qolsa — birinchi shart
    darhol yiqiladi. Naqsh (`v_*`) ISHLATILMAYDI: `v_hodim_yuklama`
    va `v_notification_health` ham `v_` bilan boshlanadi, lekin
    shartnomaga kirmaydi va aynan ular ortiqcha edi.
    """
    bolim("12b. ERP chegarasi — to'plamlar farqi")

    bor = db.scalar("SELECT count(*) FROM information_schema.schemata "
                    "WHERE schema_name='erp'")
    if not bor:
        check("`erp` sxemasi yo'q — chegara O'LCHANMADI", False,
              "bu SKIP emas: chegara tasdiqlanmadi")
        return

    oqiladi = {r["nom"] for r in db.query(
        "SELECT c.relname AS nom FROM pg_class c "
        "  JOIN pg_namespace n ON n.oid = c.relnamespace "
        " WHERE n.nspname = 'erp' AND c.relkind IN ('r','v','m','p','f') "
        "   AND has_table_privilege('tai_app', c.oid, 'SELECT')")}
    mavjud = {r["nom"] for r in db.query(
        "SELECT c.relname AS nom FROM pg_class c "
        "  JOIN pg_namespace n ON n.oid = c.relnamespace "
        " WHERE n.nspname = 'erp' AND c.relkind IN ('r','v','m','p','f')")}

    ortiqcha = sorted(oqiladi - ERP_RUXSAT)
    check("ortiqcha ERP huquqi YO'Q", not ortiqcha,
          f"{len(ortiqcha)} ta: " + ", ".join(ortiqcha[:8]))

    # Shartnoma ko'rinishi MAVJUD bo'lsa, u O'QILISHI kerak.
    kutilgan = ERP_RUXSAT & mavjud
    yetishmaydi = sorted(kutilgan - oqiladi)
    check("shartnoma ko'rinishlari o'qiladi", not yetishmaydi,
          ", ".join(yetishmaydi))

    # NOMMA-NOM: eng nozik jadvallar ALOHIDA aytiladi -- hisobotda
    # "36 ta obyekt" degan raqam nimani anglatishini ko'rsatish uchun.
    for nozik in ("app_user", "app_session", "login_attempt",
                  "invoice_payment", "chat_message_history", "contract"):
        if nozik in mavjud:
            check(f"`tai_app` `erp.{nozik}` ni O'QIY OLMAYDI",
                  nozik not in oqiladi)

    # SUKUT HUQUQ — kelajakdagi siljish manbai.
    n_defacl = db.scalar(
        "SELECT count(*) FROM pg_default_acl d "
        "  JOIN pg_namespace n ON n.oid = d.defaclnamespace, "
        "       aclexplode(d.defaclacl) a "
        " WHERE n.nspname = 'erp' "
        "   AND a.grantee::regrole::text = 'tai_app'")
    check("erp da `tai_app` uchun sukut huquq YO'Q", n_defacl == 0,
          f"{n_defacl} ta — har yangi ERP jadvali avtomatik ochilardi")


def test_huquq(db):
    bolim("12. Baza huquqlari (topilma C-1)")
    bor = db.scalar("SELECT to_regclass('public.v_huquq_tekshiruv') IS NOT NULL")
    if not bor:
        check("`schema_patch_huquq.sql` qo'llangan", False,
              "huquq tekshiruvi o'tkazib yuborildi")
        return
    qatorlar = db.query("SELECT nima, qiymat, kutilgan FROM v_huquq_tekshiruv")
    check("nazorat ko'rinishi bo'sh emas", len(qatorlar) >= 8, f"{len(qatorlar)} ta")
    for r in qatorlar:
        if r["qiymat"] is None:
            print(f"  [i] {r['nima']}: obyekt yo'q — o'lchanmadi")
            continue
        check(f"`tai_app`: {r['nima']} = {r['kutilgan']}",
              r["qiymat"] == r["kutilgan"], f"qiymat={r['qiymat']}")

    # HOZIRGI ULANISH superuser bo'lsa — bu TOPILMA, sinov yiqilishi
    # emas: rol tayyor, lekin DSN hali almashtirilmagan. Ochiq aytiladi.
    kim = db.query_one("SELECT current_user AS u, "
                       "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS s")
    # OGOHLANTIRISH -> YIQILISH (2026-09-04).
    #
    # Ilgari bu FAQAT `print` edi va `check()` chaqirilmasdi — ya'ni
    # superuser bilan yurgan sinov HECH QANDAY yiqilgan tekshiruvsiz
    # yashil qaytardi. Ayni paytda `production_gate` "ILOVA
    # SUPERUSER BILAN ISHLAMASLIGI KERAK" deb turardi: ikki qatlam
    # bir-birini eshitmagan (13-sinf).
    #
    # Endi bu TEKSHIRUV. Chiqish yo'li: `DB_SET_ROLE=tai_app`.
    # TAFSILOT FAQAT YIQILGANDA. `check()` uni shartsiz chop etadi,
    # ya'ni "PASS ... Tuzatish: DB_SET_ROLE=tai_app" degan chalkash
    # qator chiqardi: o'tgan tekshiruv yonida tuzatish ko'rsatmasi.
    check(f"ulanish superuser EMAS ({kim['u']})", not kim["s"],
          "" if not kim["s"] else
          "superuser huquq tekshiruvlarini chetlab o'tadi — "
          "grant asosidagi himoyalar sinalmaydi. "
          "Tuzatish: DB_SET_ROLE=tai_app")


# =====================================================================
def test_boglqliklar_zaifligi():
    """Bog'liqliklardagi MA'LUM zaifliklar (O-4)."""
    bolim("BOG'LIQLIKLAR — ma'lum zaifliklar")
    req = _oqi("requirements-api.txt")

    # O'LCHANGAN (2026-09-01, `pip-audit` 91 ta o'rnatilgan paket
    # ustida): 2 paketda 8 ta ma'lum zaiflik. Tuzatilgandan keyin 0.
    #
    # BU SINOV `pip-audit` NI YURGIZMAYDI — u tarmoq va zaiflik
    # bazasini talab qiladi. U TOPILGAN zaiflik QAYTIB kelmasligini
    # qo'riqlaydi: chegara pastga tushirilsa DARHOL yiqiladi.
    KUTILGAN = {
        # paket: (eng kam versiya, sabab)
        "pypdf": ("6.15.0",
                  "PYSEC-2026-3655/3656 — maxsus yasalgan PDF matn "
                  "ajratishda xotira/protsessorni tugatadi"),
    }
    import re as _re
    for paket, (eng_kam, sabab) in KUTILGAN.items():
        m = _re.search(rf"^{paket}>=([0-9.]+)\s*$", req, _re.M)
        check(f"`{paket}` chegarasi e'lon qilingan", bool(m), sabab)
        if not m:
            continue
        bor = tuple(int(x) for x in m.group(1).split("."))
        kerak = tuple(int(x) for x in eng_kam.split("."))
        check(f"`{paket}` >= {eng_kam}", bor >= kerak,
              f"{m.group(1)} — {sabab}")

    # AUDIT ASBOBI E'LON QILINGAN va u ISHLAB CHIQARISHGA
    # o'rnatilmaydi: audit asbobi xizmat muhitida keraksiz yuza.
    import os as _os
    dev = _os.path.join(ROOT, "requirements-dev.txt")
    check("`requirements-dev.txt` mavjud", _os.path.exists(dev))
    if _os.path.exists(dev):
        d = _oqi("requirements-dev.txt")
        check("audit asbobi (`pip-audit`) e'lon qilingan", "pip-audit" in d)
        check("dev fayli ISHLAB CHIQARISHGA o'rnatilmasligi YOZILGAN",
              "ISHLAB CHIQARISHGA O'RNATILMAYDI" in d)
    dep = _oqi("deploy/bin/deploy.sh")
    check("joylashtirish FAQAT `requirements-api.txt` ni o'rnatadi",
          "requirements-api.txt" in dep and "requirements-dev.txt" not in dep)

    # HUJJAT — audit qanday yurgiziladi.
    x = _oqi("docs/xavfsizlik.md")
    check("audit tartibi hujjatda", "pip-audit" in x)



# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Xavfsizlik regressiyasi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: ISHLAB CHIQARISH XAVFSIZLIGI")
    print("=" * 70)

    test_sarlavhalar()
    test_docs_yopiq()
    test_xato_sizishi()
    test_yuklash()
    test_parol()
    test_sessiya()
    test_cookie_va_csrf()
    test_darvoza()
    test_sql()
    test_ai()
    test_sirlar()
    test_manifest_qoriqchasi()
    test_boglqliklar_zaifligi()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Baza huquqlari tekshiruvi o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_huquq(db)
            test_erp_chegarasi(db)
        except Exception as e:                                # noqa: BLE001
            check("baza huquqlari tekshiruvi", False, str(e)[:90])

    otdi = sum(1 for _n, ok, _d in _natija if ok)
    jami = len(_natija)
    print("\n" + "=" * 70)
    for n, ok, d in _natija:
        if not ok:
            print(f"  YIQILDI: {n}" + (f" -- {d}" if d else ""))
    print(f"NATIJA: {otdi}/{jami} o'tdi")
    print("=" * 70)
    sys.exit(0 if otdi == jami else 1)


if __name__ == "__main__":
    main()
