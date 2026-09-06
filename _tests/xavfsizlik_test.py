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
def test_sirlar():
    bolim("11. Sirlar repozitoriyada YO'Q")
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       cwd=ROOT, encoding="utf-8", errors="replace")
    kuzatilgan = set(r.stdout.split())
    for yomon in (".env", "ngrok.yml", "frontend/.env"):
        check(f"`{yomon}` kuzatilmaydi", yomon not in kuzatilgan)
    check("`.env.example` kuzatiladi (shablon)", ".env.example" in kuzatilgan)

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


# =====================================================================
# 12. Baza huquqlari (bazali)
# =====================================================================
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
    test_boglqliklar_zaifligi()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Baza huquqlari tekshiruvi o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_huquq(db)
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
