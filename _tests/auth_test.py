"""
KIMLIK sinovi — KOMPANIYA hisobi.

Ishga tushirish (loyiha ildizidan):
    .venv/Scripts/python.exe _tests/auth_test.py

NIMA TEKSHIRILADI VA NEGA: tender-ai ga KOMPANIYA kiradi, odam emas.
Hodimlar — ERP ning tushunchasi va ular u yerda (`erp.app_user`). Bu
sinov shu chegarani ham tekshiradi: bu yerda rol ham, `broker_id` ham
bo'lmasligi kerak, aks holda auth-1 dagi xato qaytib keladi.

  1) Parol: PBKDF2 formati, qisqa parol rad etiladi, buzuq xesh
     yiqilmaydi.
  2) MODEL: hisobda ROL va HODIM ustunlari YO'Q; `public.app_user`
     jadvali ham yo'q (ERP ga ko'chgan).
  3) LOGIN: noto'g'ri parol 401 va xato matni QAYSI BIRI xato ekanini
     AYTMAYDI; to'g'ri parol token beradi; xom token bazada saqlanmaydi.
  4) TOKEN: `/auth/me` kompaniyani aytadi; yaroqsiz token 401.
  5) PAROL ALMASHTIRISH: yangi parol ishlaydi, eskisi yo'q.
  6) CHIQISH: token bekor bo'ladi.
  7) DARVOZA (auth-2): endpointlar tokensiz 401; ochiq qolganlar
     sanoqli va ataylab.
  8) SERVICE KALITI: ERP kerakli eshiklarga kiradi, qolganiga 403;
     noto'g'ri kalit 401.
  9) ERP HOLATI: `GET /tenders/{id}/erp-status` — VIEW orqali, HTTP siz.
 9b) OMBOR: qoldiq ERP niki (`erp.v_stock_balance`), o'qish faqat SQL.
 9c) COOKIE (auth-4): sessiya `HttpOnly` cookie'da, javobda token
     yo'q; o'zgartiruvchi so'rov CSRF sarlavhasisiz 403.
 10) CHEGARA: tender-ai `erp.*` ga YOZMAYDI — faqat SHARTNOMA-VIEW ni
     o'qiydi.

Sinov hisobi 'zztest_' prefiksi bilan yaratiladi va oxirida
FAOLSIZLANTIRILADI (o'chirilmaydi).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# KONSOL KODLASHI — Windows kod sahifasidan MUSTAQIL UTF-8.
#
# Chiqish QUVUR yoki FAYLGA yo'naltirilganda (ya'ni CI da) Python
# `locale.getpreferredencoding()` ni oladi — bu mashinada `cp1251`.
# O'zbek kirill (`ҳ`, `қ`, `ў`) va to'liq kenglikdagi belgilar
# (`）`) u yerda YO'Q va chop etish `UnicodeEncodeError` bilan
# BUTUN TO'PLAMNI o'ldiradi. `import_test` aynan shu sababdan
# 143 ta tekshiruvni bajarmasdan yiqilardi. Tafsilot: _tests/konsol.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import konsol
import rejim  # noqa: E402

konsol.sozla()


from dotenv import load_dotenv

load_dotenv()

from api import auth as A  # noqa: E402
from api import db  # noqa: E402

USERNAME = "zztest_kompaniya"
PASSWORD = "zzSinov12345"

_fail = 0
_pass = 0


def check(cond, msg, extra=""):
    global _fail, _pass
    if cond:
        _pass += 1
        print(f"  OK   {msg}")
    else:
        _fail += 1
        print(f"  XATO {msg}" + (f"\n       -> {extra}" if extra else ""))


def eq(msg, got, want):
    check(got == want, msg, f"olindi={got!r} kutildi={want!r}")


def head(t):
    print(f"\n=== {t} ===")


def _seed():
    """Sinov hisobi. Qayta yurishga chidamli: mavjud bo'lsa yoqiladi va
    paroli tiklanadi."""
    cur = db.query_one(A.ACC_BY_NAME_SQL, {"username": USERNAME})
    if cur:
        A.update_account(cur["id"], {"company_name": "ZZTEST MChJ",
                                     "active": True})
        A.set_password(cur["id"], PASSWORD)
        return A.shape(db.query_one(A.ACC_BY_ID_SQL, {"id": cur["id"]}))
    return A.create_account(USERNAME, "ZZTEST MChJ", PASSWORD)


def _clean_attempts():
    """Kirish urinishlari jurnalidan SINOV izlarini o'chirish.

    Bu shunchaki tozalik emas: cheklov 15 daqiqalik oynada ishlaydi,
    ya'ni tozalanmasa sinovni ketma-ket ikki marta yurgizish o'zini
    o'zi bloklab qo'yardi."""
    if not A._attempts_ready():
        return
    # Namuna NOMLI parametr bilan: SQL matnidagi tik '%' psycopg2 uchun
    # o'rin belgisi bo'lib ko'rinadi va so'rov yiqiladi.
    db.execute_returning(
        "DELETE FROM public.login_attempt "
        "WHERE username LIKE %(p)s OR ip <<= '203.0.113.0/24'::inet "
        "RETURNING id", {"p": "zztest%"})


def _disable():
    row = db.query_one(A.ACC_BY_NAME_SQL, {"username": USERNAME})
    if not row:
        return False
    A.update_account(row["id"], {"company_name": row["company_name"],
                                 "active": False})
    return True


# ---------------------------------------------------------------------------
# 1. Parol — bazasiz
# ---------------------------------------------------------------------------
def test_parol():
    head("1. Parol (bazasiz)")
    h = A.hash_password(PASSWORD)
    check(h.startswith("pbkdf2_sha256$"), "xesh formati", h[:20])
    check(PASSWORD not in h, "xeshda ochiq parol YO'Q")
    check(A.verify_password(PASSWORD, h), "to'g'ri parol tasdiqlanadi")
    check(not A.verify_password("boshqa", h), "noto'g'ri parol rad etiladi")
    check(not A.verify_password(PASSWORD, "buzuq-xesh"),
          "buzuq xesh yiqilmaydi, False qaytaradi")
    # Bir xil parol har safar BOSHQA xesh beradi (tuz tasodifiy).
    check(A.hash_password(PASSWORD) != h, "tuz har safar yangi")
    try:
        A.hash_password("qisqa")
        check(False, "qisqa parol rad etilishi kerak")
    except A.AuthError as e:
        eq("qisqa parol -> 400", e.code, 400)

    # Rol tushunchasi BU YERDA BO'LMASLIGI kerak: huquq taqsimoti odamlar
    # orasida bo'ladi, odamlar esa ERP da.
    check(not hasattr(A, "ROLES"), "modulda ROLES yo'q")
    check(not hasattr(A, "require_role"), "modulda require_role yo'q")
    check(not hasattr(A, "create_user"), "modulda create_user yo'q")


# ---------------------------------------------------------------------------
# 2-7. Haqiqiy baza
# ---------------------------------------------------------------------------
ERP_SNAPSHOT_SQL = """
SELECT (SELECT count(*) FROM erp.app_user)          AS u_n,
       (SELECT max(updated_at) FROM erp.app_user)   AS u_max,
       (SELECT count(*) FROM erp.opportunity)       AS o_n
"""


def test_db():
    head("2. Model va kirish (haqiqiy baza)")
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as c:
        # HUQUQ SHOXI SINALSIN — superuser bilan u CHETLAB O'TILADI.
        # `rejim.rol_tekshir()` yiqiladi (skip EMAS): sabab va chiqish
        # yo'li matnda. Pastdagi `erp_yopiq` shoxi aynan shunga
        # bog'liq.
        #
        # `TestClient` ICHIDA: hovuz `lifespan` da ochiladi, undan
        # oldin `db` so'rov qabul qilmaydi.
        rejim.rol_tekshir(db)

        if not A.schema_ready():
            print("  SKIP schema_patch_auth_2.sql qo'llanmagan")
            return

        cols = {r["column_name"] for r in db.query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='company_account'")}
        check("company_name" in cols, "hisobda kompaniya nomi bor")
        check("role" not in cols, "hisobda ROL ustuni YO'Q")
        check("broker_id" not in cols, "hisobda HODIM ustuni YO'Q")
        check("full_name" not in cols, "hisobda odam ismi YO'Q")
        check(not db.query_one(
            "SELECT 1 AS x FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='app_user'"),
            "public.app_user yo'q — hodimlar ERP ga ko'chgan")

        # ERP SURATI. Uni o'qib bo'lmasligi XATO EMAS — aksincha:
        # ilova ENG KAM HUQUQLI rol bilan ulangan bo'lsa
        # (`schema_patch_huquq.sql`, `tai_app`), `erp.*` jadvallariga
        # ruxsat UMUMAN yo'q. Bu chegaraning KUCHLIROQ shakli:
        # surat KEYIN aytadi, huquq esa OLDIN to'sadi.
        erp_yopiq = False
        try:
            erp_before = db.query_one(ERP_SNAPSHOT_SQL)
        except Exception as e:                                # noqa: BLE001
            if "erp" in str(e).lower() or "app_user" in str(e).lower() \
                    or "priv" in str(e).lower() or "доступ" in str(e).lower():
                erp_yopiq, erp_before = True, None
                check(True, "erp.* HUQUQ bilan yopiq — chegara "
                            "surat solishtirishdan kuchliroq himoyalangan")
            else:
                raise
        _seed()
        try:
            head("3. Login")
            r = c.post("/auth/login",
                       json={"username": USERNAME, "password": "notogri"})
            eq("noto'g'ri parol -> 401", r.status_code, 401)
            # ILGARI bu yerda O'ZBEKCHA matn ("login yoki parol")
            # tekshirilardi. 20-vazifadan keyin javob TILGA BOG'LIQ
            # EMAS, shuning uchun tekshiruv KOD bo'yicha va u
            # KUCHLIROQ: bir xil kod IKKALA holatda ham qaytishi
            # "qaysi biri xato" ekanini oshkor qilmaslikni
            # ISBOTLAYDI (matn tekshiruvi buni isbotlamasdi).
            kod1 = r.json()["error"]["code"]
            eq("noto'g'ri parol -> AUTH_INVALID_CREDENTIALS", kod1,
               "AUTH_INVALID_CREDENTIALS")
            r2 = c.post("/auth/login",
                        json={"username": "zztest_yoq", "password": PASSWORD})
            eq("mavjud bo'lmagan login -> 401", r2.status_code, 401)
            eq("mavjud bo'lmagan login AYNI kodni beradi",
               r2.json()["error"]["code"], kod1)

            r = c.post("/auth/login",
                       json={"username": USERNAME, "password": PASSWORD})
            eq("to'g'ri parol -> 200", r.status_code, 200)
            body = r.json()
            eq("javobda kompaniya", body["account"]["company_name"], "ZZTEST MChJ")
            check("password" not in str(body).lower(), "javobda parol YO'Q")
            check("role" not in body["account"], "javobda ROL yo'q")
            # AUTH-4: sessiya tokeni javob tanasida QAYTMAYDI (HttpOnly
            # cookie'da), javobda faqat CSRF tokeni.
            check("token" not in body, "javobda sessiya tokeni YO'Q")
            check(body.get("csrf"), "javobda CSRF tokeni bor")

            # Bearer yo'li API mijozlari uchun qoladi — tokenni MODULDAN.
            tok = A.login(USERNAME, PASSWORD)["token"]
            check(len(tok) > 20, "token berildi", f"{len(tok)} belgi")
            eq("xom token bazada saqlanmaydi",
               db.scalar("SELECT count(*) FROM company_session "
                         "WHERE token_hash = %(t)s", {"t": tok}), 0)
            # Login cookie qo'ydi — keyingi bo'limlar Bearer bilan ketishi
            # uchun uni tozalaymiz (ikki kimlik aralashmasin).
            c.cookies.clear()

            head("4. Token")
            H = {"Authorization": f"Bearer {tok}"}
            r = c.get("/auth/me", headers=H)
            eq("me -> 200", r.status_code, 200)
            eq("me: login", r.json()["username"], USERNAME)
            check("password_hash" not in r.json(), "me javobida xesh yo'q")
            eq("tokensiz me -> 401", c.get("/auth/me").status_code, 401)
            eq("yaroqsiz token -> 401",
               c.get("/auth/me",
                     headers={"Authorization": "Bearer yolgon"}).status_code, 401)
            eq("noto'g'ri sarlavha formati -> 401",
               c.get("/auth/me",
                     headers={"Authorization": "Basic xyz"}).status_code, 401)

            head("5. Ma'lumot va parol")
            eq("kompaniya nomini o'zgartirish",
               c.put("/auth/account", headers=H,
                     json={"company_name": "ZZTEST MChJ 2"}
                     ).json()["company_name"], "ZZTEST MChJ 2")
            eq("parolsiz so'rov -> 400",
               c.put("/auth/password", headers=H, json={}).status_code, 400)
            # auth-6: JORIY parol ham majburiy.
            eq("joriy parolsiz -> 400",
               c.put("/auth/password", headers=H,
                     json={"password": PASSWORD + "9"}).status_code, 400)
            eq("parol almashtirildi",
               c.put("/auth/password", headers=H,
                     json={"password": PASSWORD + "9",
                           "current_password": PASSWORD}).status_code, 200)
            eq("yangi parol ishlaydi",
               c.post("/auth/login", json={"username": USERNAME,
                                           "password": PASSWORD + "9"}
                      ).status_code, 200)
            eq("eski parol ishlamaydi",
               c.post("/auth/login", json={"username": USERNAME,
                                           "password": PASSWORD}).status_code, 401)
            eq("tokensiz parol almashtirib bo'lmaydi",
               c.put("/auth/password", json={"password": PASSWORD}).status_code,
               401)

            # --- DARVOZA (auth-2) ---------------------------------------
            head("5b. Darvoza: endpointlar yopiq")
            # Namuna: har bo'limdan bittadan. Darvoza BITTA joyda ishlaydi
            # (`main.py` -> `gate`), shuning uchun hammasini sanash shart
            # emas; muhimi — ro'yxatga tushmagan narsa YOPIQ.
            for p in ("/tenders", "/stats", "/profile", "/catalog",
                      "/company/documents", "/notify/settings", "/searches"):
                eq(f"tokensiz {p} -> 401", c.get(p).status_code, 401)
            for p in ("/health", "/catalog/import/template",
                      "/company/documents/template"):
                eq(f"ochiq {p} -> 200", c.get(p).status_code, 200)
            eq("token bilan /tenders -> 200",
               c.get("/tenders", headers=H).status_code, 200)

            # Yangi endpoint qo'shilsa u AVTOMATIK himoyalanadi: darvoza
            # ro'yxati OCHIQlarni sanaydi, yopiqlarni emas. Shuni
            # tekshiramiz — ochiqlar ro'yxati kutilganidan oshib
            # ketmaganini.
            from api.main import PUBLIC_PATHS, PUBLIC_PREFIXES, SERVICE_PATHS
            eq("ochiq yo'llar soni", len(PUBLIC_PATHS), 9)
            # 8 -> 9: `/ready` ONGLI ravishda qo'shildi (2026-08-31).
            # Sabab: teskari proksi (Caddy `health_uri /ready`) va
            # systemd sog'liq tekshiruvi TOKEN USHLAB TUROLMAYDI.
            # Javob ATAYLAB tafsilotsiz — faqat `ok|ogohlantirish|xato`
            # so'zlari; migratsiya sanog'i va xato matni server
            # jurnalida qoladi (`api/main.py:ready()`).
            eq("`/ready` ochiq ro'yxatda", "/ready" in PUBLIC_PATHS, True)
            # Bu son ATAYLAB qattiq yozilgan: kalit ochadigan eshiklar
            # jimgina ko'payib ketmasin. Yangi endpoint qo'shilsa sinov
            # yiqiladi va uni ONGLI ravishda yangilash kerak bo'ladi.
            # 7 tasi: tender, pricing, compliance, stock-check,
            # document-types, documents/parse, notify/send.
            eq("service kaliti ochadigan endpointlar soni",
               len(SERVICE_PATHS), 7)
            eq("ochiq prefikslar", PUBLIC_PREFIXES, ("/documents/",))

            head("5c. Service kaliti (ERP uchun)")
            KEY = A.SERVICE_KEY
            if not KEY:
                print("  SKIP .env da ERP_SERVICE_KEY yo'q")
            else:
                SH = {"X-Service-Key": KEY}
                eq("kalit bilan /company/document-types -> 200",
                   c.get("/company/document-types", headers=SH).status_code, 200)
                # Kalit HAMMA eshikning kaliti EMAS: ERP ga katalog,
                # qidiruvlar va sozlamalar kerak emas.
                for p in ("/catalog", "/profile", "/notify/settings", "/searches"):
                    eq(f"kalit {p} -> 403",
                       c.get(p, headers=SH).status_code, 403)
                eq("noto'g'ri kalit -> 401",
                   c.get("/tenders",
                         headers={"X-Service-Key": KEY + "x"}).status_code, 401)
                check(not A.verify_service(""), "bo'sh kalit rad etiladi")
                check(not A.verify_service(None), "kalitsiz rad etiladi")

            # --- ERP HOLATI (auth-3) ------------------------------------
            head("5d. ERP holati (erp.v_tender_status)")
            from api import erp_status
            eq("tokensiz /tenders/1/erp-status -> 401",
               c.get("/tenders/1/erp-status").status_code, 401)
            r = c.get("/tenders/1/erp-status", headers=H)
            eq("token bilan -> 200", r.status_code, 200)
            check("ready" in r.json() and "opportunities" in r.json(),
                  "javob shakli: ready + opportunities", str(list(r.json())))
            eq("view topildi", r.json()["ready"], erp_status.ready())

            if erp_status.ready():
                # Haqiqiy karta bo'lsa maydonlar shartnomaga mos kelsinmi.
                row = db.query_one("SELECT tender_id FROM erp.v_tender_status "
                                   "ORDER BY opportunity_id LIMIT 1")
                if not row:
                    print("  SKIP ERP da karta yo'q")
                else:
                    got = c.get(f"/tenders/{row['tender_id']}/erp-status",
                                headers=H).json()["opportunities"]
                    check(len(got) >= 1, "karta topildi", str(len(got)))
                    eq("maydonlar (shartnoma)", set(got[0]),
                       {"opportunity_id", "status", "status_label", "priority",
                        "broker_name", "client_name", "created_at"})
                    # MAXFIYLIK: summa, izoh va tarix BERILMAYDI — tender-ai
                    # ga kerak emas.
                    for hidden in ("amount", "note", "win_probability",
                                   "history", "currency"):
                        check(hidden not in got[0],
                              f"javobda '{hidden}' YO'Q")
                # Bu endpoint ERP GA HTTP SO'ROV QILMAYDI: `erp_status`
                # moduli faqat `db` ni import qiladi.
                import inspect
                src = inspect.getsource(erp_status)
                for bad in ("requests", "urllib", "http"):
                    check(bad not in src,
                          f"erp_status modulida '{bad}' yo'q (HTTP emas, SQL)")

            # --- OMBOR QOLDIG'I (5B-1) ----------------------------------
            head("5e. Ombor qoldig'i (erp.v_stock_balance)")
            from api import erp_stock
            check(erp_stock.ready(), "ERP ombor view i topildi")
            # Qoldiq ERP niki: bu modul ham SQL, HTTP emas.
            import inspect
            src = inspect.getsource(erp_stock)
            for bad in ("requests", "urllib", "http"):
                check(bad not in src,
                      f"erp_stock modulida '{bad}' yo'q (HTTP emas, SQL)")
            check("INSERT" not in src.upper() and "UPDATE " not in src.upper(),
                  "erp_stock FAQAT O'QIYDI (INSERT/UPDATE yo'q)")

            # Ombor ishga tushmagan bo'lsa ESKI xatti-harakat saqlanadi:
            # bo'sh jurnal "hamma qoldiq nol" degani emas.
            prods = [{"id": -1, "stock_qty": 5, "stock_updated_at": None}]
            src_used = erp_stock.apply_to_products(prods)
            if erp_stock.in_use():
                eq("ombor ishlayapti -> manba 'erp'", src_used, "erp")
                check(prods[0]["stock_qty"] is None,
                      "ERP da qaydi yo'q mahsulot -> None (import QOLDIRILMAYDI)")
            else:
                eq("ombor bo'sh -> manba 'import'", src_used, "import")
                eq("import qiymati tegilmadi", prods[0]["stock_qty"], 5)

            # --- COOKIE va CSRF (auth-4) --------------------------------
            head("5f. Cookie va CSRF")
            # Alohida mijoz: `https` — `Secure` cookie faqat shunda
            # saqlanadi. `with` ISHLATILMAYDI: u lifespan'ni qayta
            # yuritib, chiqishda baza pulini yopardi.
            cc = TestClient(app, base_url="https://testserver")
            # DIQQAT: 5-bo'limda parol almashtirilgan — joriysi PASSWORD+"9".
            r = cc.post("/auth/login",
                        json={"username": USERNAME, "password": PASSWORD + "9"})
            eq("cookie bilan kirish -> 200", r.status_code, 200)
            raw = r.headers.get("set-cookie", "")
            check("tai_session" in raw and "HttpOnly" in raw,
                  "sessiya cookie'si HttpOnly")
            check("samesite=lax" in raw.lower(), "SameSite=Lax qo'yilgan",
                  raw[:80])
            csrf_part = [p for p in raw.split(",") if "tai_csrf" in p]
            check(csrf_part and "HttpOnly" not in csrf_part[0],
                  "CSRF cookie'si HttpOnly EMAS (sahifa o'qiydi)")

            csrf = r.json()["csrf"]
            eq("cookie bilan me -> 200", cc.get("/auth/me").status_code, 200)
            eq("cookie bilan GET -> 200", cc.get("/tenders").status_code, 200)
            eq("CSRF sarlavhasiz PUT -> 403",
               cc.put("/auth/account",
                      json={"company_name": "ZZTEST MChJ"}).status_code, 403)
            eq("noto'g'ri CSRF -> 403",
               cc.put("/auth/account", json={"company_name": "ZZTEST MChJ"},
                      headers={"X-CSRF-Token": "yolgon"}).status_code, 403)
            eq("to'g'ri CSRF bilan PUT -> 200",
               cc.put("/auth/account", json={"company_name": "ZZTEST MChJ"},
                      headers={"X-CSRF-Token": csrf}).status_code, 200)

            # SERVICE kaliti cookie EMAS — CSRF unga tegishli emas.
            if A.SERVICE_KEY:
                eq("service kaliti CSRF siz ham ishlaydi",
                   cc.post("/tenders/1/compliance", json={},
                           headers={"X-Service-Key": A.SERVICE_KEY,
                                    "Cookie": ""}).status_code in (200, 404),
                   True)

            r3 = cc.post("/auth/logout")
            eq("chiqish -> 200", r3.status_code, 200)
            check("tai_session=" in r3.headers.get("set-cookie", ""),
                  "chiqishda cookie tozalanadi")
            eq("chiqqandan keyin me -> 401", cc.get("/auth/me").status_code, 401)

            # --- PAROL ALMASHTIRISH (auth-6) --------------------------
            head("5g. Parol: talab va xavfsiz almashtirish")
            # ZAIF parol qabul qilinmaydi — yaratishda ham. Avvalgi
            # yurishdan qolgan hisob bo'lsa o'chiriladi, aks holda
            # javob 400 emas, 409 ("login band") bo'lardi.
            db.execute_returning("DELETE FROM company_account "
                                 "WHERE username = 'zztest_zaif' "
                                 "RETURNING id")
            # ZAIF parol qabul qilinmaydi — yaratishda ham.
            for bad, why in [("qisqa", "qisqa parol"),
                             ("password123", "ko'p uchraydigan parol"),
                             ("zztest_zaif12345", "login nomi ichida")]:
                try:
                    A.create_account("zztest_zaif", "ZZ Zaif", bad)
                    check(False, f"{why} rad etilishi kerak edi")
                except A.AuthError as e:
                    eq(f"{why} -> 400", e.code, 400)

            aid = db.scalar("SELECT id FROM company_account "
                            "WHERE username = %(u)s", {"u": USERNAME})
            # 5-bo'limda parol almashtirilgan — joriysi shu.
            CUR = PASSWORD + "9"
            # BOSHQA uchta qurilmadan ham kirilgan deb faraz qilamiz.
            # Parolni esa ASOSIY sessiya (`H`) almashtiradi.
            ptoks = [A.login(USERNAME, CUR)["token"] for _ in range(3)]
            NEWPW = PASSWORD + "-yangi"
            PH = H

            eq("joriy parolsiz -> 400",
               c.put("/auth/password", headers=PH,
                     json={"password": NEWPW}).status_code, 400)
            eq("noto'g'ri joriy parol -> 400",
               c.put("/auth/password", headers=PH,
                     json={"password": NEWPW,
                           "current_password": "notogri"}).status_code, 400)
            eq("yangi = eski -> 400",
               c.put("/auth/password", headers=PH,
                     json={"password": CUR,
                           "current_password": CUR}).status_code, 400)
            eq("zaif yangi parol -> 400",
               c.put("/auth/password", headers=PH,
                     json={"password": "1234",
                           "current_password": CUR}).status_code, 400)

            rp = c.put("/auth/password", headers=PH,
                       json={"password": NEWPW, "current_password": CUR})
            eq("to'g'ri almashtirish -> 200", rp.status_code, 200)
            check(rp.json().get("closed_sessions", 0) >= 3,
                  "boshqa qurilmalarning sessiyalari yopildi",
                  str(rp.json()))
            # O'Z sessiyasi QOLADI — parol almashtirgan odam tizimdan
            # chiqib ketmasligi kerak.
            eq("o'z sessiyasi ishlaydi",
               c.get("/auth/me", headers=PH).status_code, 200)
            # BOSHQA sessiyalar o'chdi: o'g'irlangan token endi ishlamaydi.
            eq("boshqa qurilma endi ishlamaydi",
               c.get("/auth/me",
                     headers={"Authorization": f"Bearer {ptoks[0]}"}
                     ).status_code, 401)
            eq("yangi parol bilan kirish ishlaydi",
               c.post("/auth/login", json={"username": USERNAME,
                                           "password": NEWPW}).status_code, 200)
            c.cookies.clear()
            # Parolni 5-bo'limdagi holatiga qaytaramiz: keyingi
            # bo'limlar (6, 7) aynan shunga tayanadi. `keep_token` SHART:
            # usiz bu tiklash HAMMA sessiyani yopadi (admin tiklashi
            # shunday ishlaydi) va 6-bo'limdagi chiqish 401 bo'lardi.
            A.set_password(aid, CUR, keep_token=tok)

            head("6. Chiqish")
            eq("logout -> 200", c.post("/auth/logout", headers=H).status_code, 200)
            eq("chiqqandan keyin 401", c.get("/auth/me", headers=H).status_code, 401)

            head("7. Faol emas hisob")
            _disable()
            eq("faol emas hisob kira olmaydi",
               c.post("/auth/login", json={"username": USERNAME,
                                           "password": PASSWORD + "9"}
                      ).status_code, 401)
            # --- PAROL TANLASHDAN HIMOYA (auth-5) ---------------------
            head("8. Parol tanlashdan himoya")
            if not A._attempts_ready():
                print("  SKIP schema_patch_auth_4.sql qo'llanmagan")
            else:
                _seed()                       # 7-bo'lim hisobni o'chirgan edi
                _clean_attempts()
                # 203.0.113.0/24 — TEST-NET-3, hech kimga tegishli emas.
                gname, gip, gip2 = "zztest_guard", "203.0.113.7", "203.0.113.8"

                codes = []
                for _ in range(A.MAX_PER_USER + 2):
                    try:
                        A.login(gname, "notogri", ip=gip)
                        codes.append(200)
                    except A.AuthError as e:
                        codes.append(e.code)
                eq("cheklovgacha 401", codes[:A.MAX_PER_USER],
                   [401] * A.MAX_PER_USER)
                eq("cheklovdan keyin 429", codes[A.MAX_PER_USER:], [429, 429])

                # Bloklangan urinish jurnalga YOZILMAYDI — u parolni ham
                # tekshirmaydi.
                eq("bloklangandan keyin jurnal o'smadi",
                   db.scalar("SELECT count(*) FROM public.login_attempt "
                             "WHERE username = %(u)s", {"u": gname}),
                   A.MAX_PER_USER)

                # HISOB BLOKLANMAYDI. Bu yerda bu qaror ERP dagidan ham
                # muhimroq: kompaniya hisobi BITTA, uni yopish butun
                # kompaniyani tizimdan uzib qo'yardi.
                try:
                    A.login(gname, "notogri", ip=gip2)
                    check(False, "boshqa IP dan javob kelishi kerak edi")
                except A.AuthError as e:
                    eq("boshqa IP dan -> 401 (hisob bloklanmagan)", e.code, 401)

                try:
                    A.login(gname, "notogri", ip=gip)
                    check(False, "429 kutilgan edi")
                except A.AuthError as e:
                    check(getattr(e, "retry_after", 0) > 0,
                          "429 da kutish vaqti bor",
                          str(getattr(e, "retry_after", None)))
                    check("daqiqa" in str(e), "matn kutish vaqtini aytadi",
                          str(e)[:60])

                # PAROL JURNALGA TUSHMAYDI.
                acols = {r["column_name"] for r in db.query(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='login_attempt'")}
                check(not any("pass" in x for x in acols),
                      "jurnalda parol ustuni YO'Q", str(sorted(acols)))

                # TO'G'RI PAROL ZANJIRNI UZADI.
                gip3 = "203.0.113.9"
                for _ in range(A.MAX_PER_USER - 1):
                    try:
                        A.login(USERNAME, "notogri", ip=gip3)
                    except A.AuthError:
                        pass
                try:
                    A.login(USERNAME, PASSWORD, ip=gip3)
                    check(True, "cheklov chegarasida to'g'ri parol o'tdi")
                except A.AuthError as e:
                    check(False, "to'g'ri parol o'tishi kerak edi", str(e))

                after_ok = []
                for _ in range(A.MAX_PER_USER + 1):
                    try:
                        A.login(USERNAME, "notogri", ip=gip3)
                        after_ok.append(200)
                    except A.AuthError as e:
                        after_ok.append(e.code)
                eq("muvaffaqiyatdan keyin hisob NOLDAN boshlandi",
                   after_ok, [401] * A.MAX_PER_USER + [429])

                # HTTP qatlami: 429 va `Retry-After`.
                hname = "zztest_guard3"
                for _ in range(A.MAX_PER_USER):
                    c.post("/auth/login",
                           json={"username": hname, "password": "x"})
                rr = c.post("/auth/login",
                            json={"username": hname, "password": "x"})
                eq("HTTP: cheklovdan keyin 429", rr.status_code, 429)
                check(rr.headers.get("retry-after"),
                      "javobda Retry-After sarlavhasi",
                      str(rr.headers.get("retry-after")))

                # Ro'yxat: kirgan hisob uchun ochiq, tokensiz emas.
                eq("tokensiz urinishlar ro'yxati -> 401",
                   c.get("/auth/attempts").status_code, 401)
                _clean_attempts()
                _seed()
                tok2 = A.login(USERNAME, PASSWORD)["token"]
                rl = c.get("/auth/attempts",
                           headers={"Authorization": f"Bearer {tok2}"})
                eq("kirgan hisobga -> 200", rl.status_code, 200)
                check(isinstance(rl.json(), list), "ro'yxat qaytdi")

                # ERP JURNALI TEGILMAYDI — chegara qoidasi bu yerda ham
                # amal qiladi: har tizim o'z eshigini o'zi qo'riqlaydi.
                # `erp.login_attempt` ni O'QIB BO'LMASLIGI ham xato emas:
                # eng kam huquqli rolda `erp.*` jadvallariga ruxsat YO'Q,
                # ya'ni chegara huquq bilan qulflangan (kuchliroq shakl).
                try:
                    erp_n = db.scalar("SELECT count(*) FROM erp.login_attempt")
                except Exception:                             # noqa: BLE001
                    erp_n = None
                    check(True, "erp.login_attempt HUQUQ bilan yopiq")
                try:
                    A.login("zztest_chegara", "notogri", ip="203.0.113.11")
                except A.AuthError:
                    pass
                if erp_n is not None:
                    eq("erp.login_attempt tegilmadi",
                       db.scalar("SELECT count(*) FROM erp.login_attempt"), erp_n)

        finally:
            head("9. Tozalash va chegara")
            _clean_attempts()
            check(_disable(), "sinov hisobi faolsizlantirildi")
            # Chegara IKKI TOMONLAMA: ERP `public.*` ga yozmagani kabi,
            # tender-ai ham `erp.*` ga yozmaydi. Hodim hisoblari faqat
            # ERP orqali o'zgaradi.
            if erp_yopiq:
                # HUQUQ bilan yopiq — surat solishtirish MUMKIN EMAS va
                # KERAK EMAS: yozish imkoni umuman yo'q.
                check(True, "erp.* surati o'tkazib yuborildi — huquq "
                            "darajasida yozib bo'lmaydi")
            else:
                after = db.query_one(ERP_SNAPSHOT_SQL)
                eq("erp.app_user soni tegilmadi", after["u_n"], erp_before["u_n"])
                eq("erp.app_user yangilanmadi", after["u_max"], erp_before["u_max"])
                eq("erp.opportunity tegilmadi", after["o_n"], erp_before["o_n"])
            # Chegara SIMMETRIK: ERP `public.*` dan o'qiydi va yozmaydi;
            # tender-ai `erp.v_tender_status` dan o'qiydi va yozmaydi.
            # VIEW ning o'zi yozib bo'lmaydigan bo'lishi ham kerak.
            ins = db.query_one(
                "SELECT is_insertable_into FROM information_schema.tables "
                "WHERE table_schema='erp' AND table_name='v_tender_status'")
            if ins:
                eq("view ga yozib bo'lmaydi", ins["is_insertable_into"], "NO")


if __name__ == "__main__":
    test_parol()
    try:
        test_db()
    except Exception as e:                     # noqa: BLE001
        print(f"  DIQQAT: sinov bajarilmadi: {type(e).__name__}: {e}")
        _fail += 1
    print(f"\n{'=' * 50}\nNATIJA: {_pass} ta o'tdi, {_fail} ta xato")
    sys.exit(1 if _fail else 0)
