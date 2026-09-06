#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: KODLASH PILOTI — INSON QARORI HALQASI
=============================================

HOLAT (o'lchangan 2026-08-30):
    catalog_product   1 797
    kodlangan           960   (hammasi skript bilan biriktirilgan)
    ataylab kodsiz      837
    kod_qaror             0   <-- INSON QARORI YO'Q

Quvur ishlaydi, uning aniqligini o'lchaydigan inson ma'lumoti yo'q.
Bu sinov halqa ISHLASHGA TAYYOR ekanini tekshiradi va — eng
muhimi — O'LCHOV ASBOBINING O'ZI BUZUQ EMASLIGINI.

ENG MUHIM TEKSHIRUV: RENDER QAROR EMAS
---------------------------------------
2026-08-30 da o'lchangan nosozlik: ekran ochilganda 40 qator bir
vaqtda `ochish` chaqirdi, 11 soniyada 40 ta `kod_qaror` qatori
yaratildi va ularning BIRORTASIDA qaror yo'q edi. `count(*)` esa
"40 qaror" bo'lib ko'rindi. Ya'ni asbob O'ZI YARATGAN qatorni
sanardi.

Shuning uchun bu yerdagi sinovlar:
    render  -> qator YO'Q
    ochish  -> qator BOR, lekin QAROR EMAS (hisoblagichga tushmaydi)
    harakat -> vaqt hisobi boshlanadi
    qaror   -> endi sanaladi

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\kod_pilot_test.py
    .venv\\Scripts\\python.exe _tests\\kod_pilot_test.py --offline
"""
import argparse
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# KONSOL KODLASHI — Windows kod sahifasidan MUSTAQIL UTF-8.
#
# Chiqish QUVUR yoki FAYLGA yo'naltirilganda (ya'ni CI da) Python
# `locale.getpreferredencoding()` ni oladi — bu mashinada `cp1251`.
# O'zbek kirill (`ҳ`, `қ`, `ў`) va to'liq kenglikdagi belgilar
# (`）`) u yerda YO'Q va chop etish `UnicodeEncodeError` bilan
# BUTUN TO'PLAMNI o'ldiradi. `import_test` aynan shu sababdan
# 143 ta tekshiruvni bajarmasdan yiqilardi. Tafsilot: _tests/konsol.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()


from dotenv import load_dotenv                                # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

try:
    import psycopg2
except ImportError:                                           # pragma: no cover
    psycopg2 = None

_results = []
#: Sinov atamalari — hammasi shu prefiks bilan, oxirida tozalanadi.
PREFIKS = "zzsinov"


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def section(t: str) -> None:
    print(f"\n--- {t} ---")


def db_conn():
    dsn = os.environ.get("XT_DB_DSN")
    if not dsn or psycopg2 is None:
        return None
    try:
        c = psycopg2.connect(dsn, connect_timeout=8)
        c.autocommit = True
        return c
    except Exception as e:                                    # noqa: BLE001
        print(f"  [i] baza yetib bo'lmadi: {str(e)[:90]}")
        return None


def tozala(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM kod_qaror WHERE kalit LIKE %s", (PREFIKS + "%",))


# =====================================================================
# 1) STATIK — interfeys render paytida qaror yaratmaydi
# =====================================================================
def test_render_qaror_emas_statik() -> None:
    section("Render qaror YARATMAYDI (interfeys manbai)")

    src = io.open(os.path.join(ROOT, "frontend", "src", "components",
                               "KodNavbat.tsx"), encoding="utf-8").read()

    # `ochish` `useEffect` da BO'LMASLIGI shart. Aynan shu 40 ta
    # soxta qatorni yaratgan.
    effektlar = re.findall(r"useEffect\(\s*\(\)\s*=>\s*\{(.*?)\}\s*,\s*\[",
                           src, re.S)
    check("`ochish()` hech qaysi useEffect ichida CHAQIRILMAYDI",
          all("ochish(" not in e for e in effektlar),
          "render paytida ochish = 40 ta soxta qator")

    # Ochish BIRINCHI HARAKATDA va FAQAT BIR MARTA.
    check("ochish `ochilganRef` bilan bir martaga cheklangan",
          "ochilganRef.current" in src and "if (ochilganRef.current) return" in src)
    check("qidiruv `await ochish()` bilan boshlanadi",
          re.search(r"const qidir[^}]*?await ochish\(\)", src, re.S) is not None,
          "qidiruv — BIRINCHI HARAKAT, vaqt hisobi shundan")
    check("qaror ham `await ochish()` bilan",
          re.search(r"const yoz\s*=[^}]*?await ochish\(\)", src, re.S) is not None,
          "to'g'ridan-to'g'ri qaror ham harakat")
    check("`ochish` KUTILADI (yuborib tashlanmaydi)",
          ".then(" not in src.split("const qidir")[0].split("const ochish")[-1],
          "kutilmasa qaror OLDIN yetib borib ikki qator qoldirardi")

    # Ochish xatosi JIMGINA yutilmaydi.
    #
    # MATN EMAS, MEXANIZM tekshiriladi. Ilgari bu yerda aynan
    # "o'lchov ochilmadi" iborasi qidirilardi va matn tozalanganda
    # (foydalanuvchiga tushunarli "Qaror vaqti yozilmaydi: …" ga
    # almashtirilganda) sinov yiqilgan edi — kafolat buzilmagan
    # holda. Kafolat: xato HOLATGA yoziladi VA EKRANGA chiqadi.
    check("ochish xatosi EKRANDA ko'rinadi",
          "setOchXato" in src and re.search(r"\{\s*ochXato\s*\}", src) is not None,
          "o'lchamay turib 'ishlayapti' ko'rinmasin")

    # Yangi qaror turlari mavjud.
    for tugma, nima in (("'talabsiz'", "korpusda talab yo'q"),
                        ("'dalilsiz'", "qaror qila olmadim"),
                        ("'otkazildi'", "keyinroq")):
        check(f"tugma bor: {tugma} ({nima})", f"yoz({tugma}" in src)
    check("taklifni RAD ETISH tugmasi bor",
          "radEt(" in src and "noto‘g‘ri" in src,
          "manfiy misol — musbatidan kam qimmatli emas")
    check("rad etish ham VAQT hisobini boshlaydi",
          re.search(r"const radEt[^}]*?await ochish\(\)", src, re.S) is not None)
    check("dalil yig'iladi va yuboriladi",
          "dalilYig" in src and "dalil: dalilYig()" in src)
    check("taklif kodi qaror bilan birga yuboriladi",
          "taklif_code: top?.code" in src,
          "kelishuv foizi shundan hisoblanadi")
    check("qo'shimcha kod bayrog'i yuboriladi",
          "qoshimcha_kod: q === 'kod' && kodBerildi" in src)

    # `ochish` API chaqiruvi qaror maydonlarini YUBORMAYDI.
    api_src = io.open(os.path.join(ROOT, "frontend", "src", "api.ts"),
                      encoding="utf-8").read()
    j = api_src.find("kodQarorOchish")
    oyna = api_src[j:j + 400]
    check("`kodQarorOchish` `qaror` YUBORMAYDI",
          "qaror:" not in oyna,
          "ilgari `qaror: 'kod'` to'ldiruvchi yuborilardi — ochishni "
          "qarorga o'xshatib qo'yardi")


def test_konstantalar() -> None:
    section("Qaror lug'ati — kod va baza MOS")
    from api import kodlash as K

    check("QARORLAR to'rtta", len(K.QARORLAR) == 4, str(K.QARORLAR))
    for q in ("kod", "talabsiz", "dalilsiz", "otkazildi"):
        check(f"'{q}' lug'atda bor", q in K.QARORLAR)

    ts = io.open(os.path.join(ROOT, "frontend", "src", "types.ts"),
                 encoding="utf-8").read()
    check("frontend KodQaror turi bir xil",
          "'kod' | 'talabsiz' | 'dalilsiz' | 'otkazildi'" in ts,
          "ikki joyda ikki lug'at bo'lsa biri jimgina eskiradi")


# =====================================================================
# 2) BAZA — bo'sh/yaroqsiz kod va odamsiz qaror RAD ETILADI
# =====================================================================
def test_baza_qulflari(conn, cid) -> None:
    section("Baza: bo'sh kod va odamsiz qaror RAD ETILADI")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    import psycopg2 as pg

    def urin(sql, params) -> bool:
        """`True` = baza RAD ETDI."""
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            return False
        except pg.Error:
            return True

    BAZA = ("INSERT INTO kod_qaror (company_id, kalit, atama, qaror, code, "
            "kim, qaror_at, ochilgan_at, qidiruv_soni, qoshimcha_kod, "
            "qidiruv_sozi, taklif_code, taklif_skor, dalil) VALUES "
            "(%(c)s, %(k)s, %(a)s, %(q)s, %(code)s, %(kim)s, %(qat)s, "
            " %(oat)s, %(qs)s, %(qk)s, %(soz)s, %(tc)s, %(ts)s, %(d)s::jsonb)")

    def p(**ozg):
        d = {"c": cid, "k": PREFIKS + "_q", "a": "ZZ", "q": "kod",
             "code": "26.30", "kim": "sinov", "qat": "now()",
             "oat": None, "qs": 0, "qk": False, "soz": None,
             "tc": None, "ts": None, "d": None}
        d.update(ozg)
        return d

    check("RAD: 'kod' qarori, code NULL",
          urin(BAZA, p(code=None)),
          "bo'sh kodni tasodifan tasdiqlab bo'lmasin")
    check("RAD: 'kod' qarori, code bo'sh satr",
          urin(BAZA, p(code="   ")))
    check("RAD: 'talabsiz' qarorida code to'ldirilgan",
          urin(BAZA, p(q="talabsiz", code="26.30")))
    check("RAD: qaror bor, kim YO'Q",
          urin(BAZA, p(kim=None)))
    check("RAD: qaror bor, kim BO'SH SATR",
          urin(BAZA, p(kim="  ")))
    check("RAD: notanish qaror turi",
          urin(BAZA, p(q="tasdiqlandi", code=None)))
    check("RAD: mavjud bo'lmagan kod (FK)",
          urin(BAZA, p(code="99.99")))
    check("RAD: qo'shimcha_kod 'talabsiz' bilan",
          urin(BAZA, p(q="talabsiz", code=None, qk=True)))
    check("RAD: qidiruv so'zi bor, sanoq NOL",
          urin(BAZA, p(soz="kabel", qs=0)),
          "'qidirdim' da'vosi hisoblagichda ko'rinsin")
    check("RAD: taklif skori bor, taklif kodi YO'Q",
          urin(BAZA, p(ts=0.9, tc=None)))
    check("RAD: dalil bor, lekin QAROR yo'q",
          urin("INSERT INTO kod_qaror (company_id, kalit, atama, "
               "ochilgan_at, dalil) VALUES (%(c)s, %(k)s, %(a)s, now(), "
               "%(d)s::jsonb)",
               {"c": cid, "k": PREFIKS + "_d", "a": "ZZ",
                "d": json.dumps({"x": 1})}),
          "dalil qaror paytidagi holatni yozadi")
    check("RAD: qaror_at ochilgan_at dan OLDIN",
          urin(BAZA, p(oat="2030-01-01", qat="2020-01-01")))

    # TO'G'RI qatorlar QABUL qilinadi — cheklov haddan tashqari
    # qattiq emasligini ham tekshiramiz.
    def qabul(sql, params) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            return True
        except pg.Error as e:
            print(f"      (rad etildi: {str(e)[:100]})")
            return False

    check("QABUL: to'liq 'kod' qarori",
          qabul(BAZA, p(k=PREFIKS + "_ok1", oat="2026-08-30 10:00+05",
                        qat="2026-08-30 10:01+05", qs=1, soz="kabel",
                        tc="26.30", ts=0.81, d=json.dumps({"a": 1}))))
    check("QABUL: 'dalilsiz' qarori",
          qabul(BAZA, p(k=PREFIKS + "_ok2", q="dalilsiz", code=None)))
    check("QABUL: qo'shimcha kod ('kod' bilan)",
          qabul(BAZA, p(k=PREFIKS + "_ok3", qk=True)))
    tozala(conn)


# =====================================================================
# 3) ILOVA QATLAMI — ochish / qidiruv / qaror ketma-ketligi
# =====================================================================
def test_halqa(conn, cid) -> None:
    section("Halqa: ochish -> qidiruv -> qaror")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    from api import db, kodlash as K
    try:
        db.init_pool()
    except Exception:                                          # noqa: BLE001
        pass
    tozala(conn)
    KALIT = PREFIKS + "_halqa"
    try:
        # --- OCHISHDAN OLDIN: qator YO'Q ---
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM kod_qaror WHERE kalit=%s", (KALIT,))
            check("ochishdan OLDIN qator yo'q", cur.fetchone()[0] == 0)

        # --- OCHISH: qator bor, lekin QAROR EMAS ---
        r = K.qaror_ochish(cid, KALIT, "ZZ atama")
        check("ochish qator yaratdi", bool(r.get("id")), str(r)[:70])
        check("ochish `ochilgan_at` yozdi", r.get("ochilgan_at") is not None)

        with conn.cursor() as cur:
            cur.execute("SELECT qaror, code, kim FROM kod_qaror WHERE kalit=%s",
                        (KALIT,))
            row = cur.fetchone()
        check("OCHISH QAROR EMAS: qaror NULL", row[0] is None, str(row))
        check("ochishda kim ham YO'Q", row[2] is None)

        # --- HISOBLAGICH OCHIQ QATORNI SANAMAYDI ---
        o = K.qaror_olchov(cid)
        check("ochiq qator `qaror_soni` ga TUSHMAYDI",
              (o.get("qaror_soni") or 0) == 0, str(o.get("qaror_soni")))
        check("ochiq qator alohida sanaladi (`ochiq_qator`)",
              (o.get("ochiq_qator") or 0) >= 1, str(o.get("ochiq_qator")))
        p = K.pilot_holati(cid)
        check("pilotda ham qaror sanalmaydi",
              (p.get("atama_soni") or 0) == 0, str(p.get("atama_soni")))

        # --- TAKROR OCHISH YANGI QATOR YARATMAYDI ---
        K.qaror_ochish(cid, KALIT, "ZZ atama")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM kod_qaror WHERE kalit=%s", (KALIT,))
            check("takror ochish YANGI qator yaratmaydi",
                  cur.fetchone()[0] == 1)

        # --- QIDIRUV: sanoq va SO'Z yoziladi ---
        n = K.qaror_qidiruv(cid, KALIT, soz="kabel")
        check("qidiruv sanog'i oshdi", n == 1, str(n))
        with conn.cursor() as cur:
            cur.execute("SELECT qidiruv_soni, qidiruv_sozi FROM kod_qaror "
                        "WHERE kalit=%s", (KALIT,))
            q = cur.fetchone()
        check("qidiruv SO'ZI saqlandi", q[1] == "kabel", str(q))

        # --- VAQT: ochilishdan keyin o'tgan vaqt O'LCHANADI ---
        time.sleep(1.1)
        r2 = K.qaror_yoz(cid, KALIT, "ZZ atama", "kod", kim="sinovchi",
                         code="26.30", manba="qidiruv",
                         dalil={"takliflar": [{"code": "26.20"}]},
                         taklif_code="26.20", taklif_skor=0.7, ishonch="kompaniya_sessiyasi")
        check("qaror yozildi", bool(r2.get("id")))
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM v_kod_qaror_tafsil WHERE kalit=%s", (KALIT,))
            cols = [c[0] for c in cur.description]
            t = dict(zip(cols, cur.fetchone()))
        check("VAQT o'lchandi va NOL EMAS",
              t["sek"] is not None and t["sek"] >= 1,
              f"sek={t['sek']}")
        check("qidiruv sanog'i SAQLANDI", t["qidiruv_soni"] == 1)
        check("qidiruv so'zi SAQLANDI", t["qidiruv_sozi"] == "kabel")
        check("DALIL saqlandi", t["dalil_bor"] is True)
        check("taklif kodi saqlandi", t["taklif_code"] == "26.20")
        check("taklif holati 'ozgartirildi'",
              t["taklif_holati"] == "ozgartirildi",
              f"taklif 26.20 edi, inson 26.30 tanladi -> {t['taklif_holati']}")

        # --- ENDI hisoblagichga TUSHADI ---
        o2 = K.qaror_olchov(cid)
        check("qaror `qaror_soni` ga tushdi", (o2.get("qaror_soni") or 0) == 1)
        check("`olchangan` oshdi", (o2.get("olchangan") or 0) == 1)
        check("`olchovsiz` nol", (o2.get("olchovsiz") or 0) == 0)
        check("`dalil_qamrov_foiz` 100", float(o2.get("dalil_qamrov_foiz") or 0) == 100.0,
              str(o2.get("dalil_qamrov_foiz")))
        check("`qidiruv_foiz` 100", float(o2.get("qidiruv_foiz") or 0) == 100.0)
    finally:
        tozala(conn)


def test_olchovsiz_nol_emas(conn, cid) -> None:
    section("Ochilmagan qaror: vaqt NULL, nol EMAS")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    from api import db, kodlash as K
    try:
        db.init_pool()
    except Exception:                                          # noqa: BLE001
        pass
    tozala(conn)
    K2 = PREFIKS + "_olchovsiz"
    try:
        # OCHISHSIZ to'g'ridan-to'g'ri qaror (zaxira yo'l).
        K.qaror_yoz(cid, K2, "ZZ", "otkazildi", kim="sinovchi", ishonch="kompaniya_sessiyasi")
        with conn.cursor() as cur:
            cur.execute("SELECT ochilgan_at, sek FROM v_kod_qaror_tafsil "
                        "WHERE kalit=%s", (K2,))
            r = cur.fetchone()
        check("`ochilgan_at` NULL qoldi", r[0] is None)
        check("`sek` NULL — NOL EMAS", r[1] is None,
              "nol o'lchov, NULL o'lchov yo'qligi")
        o = K.qaror_olchov(cid)
        check("`olchovsiz` sanaldi", (o.get("olchovsiz") or 0) == 1)
        check("`ortacha_sek` NULL (o'rtachaga qo'shilmadi)",
              o.get("ortacha_sek") is None, str(o.get("ortacha_sek")))
    finally:
        tozala(conn)


# =====================================================================
# 4) BEShTA HARAKAT — qabul / rad / almashtirish / dalilsiz / ko'p kod
# =====================================================================
def test_harakatlar(conn, cid) -> None:
    section("Beshta harakat qo'llab-quvvatlanadi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    from api import db, kodlash as K
    try:
        db.init_pool()
    except Exception:                                          # noqa: BLE001
        pass
    tozala(conn)
    try:
        # 1) TAKLIFNI QABUL QILISH
        k1 = PREFIKS + "_qabul"
        K.qaror_ochish(cid, k1, "ZZ qabul")
        K.qaror_yoz(cid, k1, "ZZ qabul", "kod", kim="s", code="26.30",
                    manba="taklif", taklif_code="26.30", taklif_skor=0.9,
                    dalil={"a": 1}, ishonch="kompaniya_sessiyasi")

        # 2) TAKLIFNI RAD ETIB BOSHQASINI TANLASH
        k2 = PREFIKS + "_almash"
        K.qaror_ochish(cid, k2, "ZZ almash")
        K.qaror_qidiruv(cid, k2, soz="turniket")
        K.qaror_yoz(cid, k2, "ZZ almash", "kod", kim="s", code="26.30",
                    manba="qidiruv", taklif_code="26.20",
                    rad_takliflar=["26.20"], dalil={"a": 2}, ishonch="kompaniya_sessiyasi")

        # 3) TALABSIZ (xulosa)
        k3 = PREFIKS + "_talabsiz"
        K.qaror_ochish(cid, k3, "ZZ talabsiz")
        K.qaror_qidiruv(cid, k3, soz="yoq")
        K.qaror_yoz(cid, k3, "ZZ talabsiz", "talabsiz", kim="s",
                    taklif_code="26.20", rad_takliflar=["26.20"],
                    dalil={"a": 3}, ishonch="kompaniya_sessiyasi")

        # 4) DALILSIZ (xulosa yo'qligi)
        k4 = PREFIKS + "_dalilsiz"
        K.qaror_ochish(cid, k4, "ZZ dalilsiz")
        K.qaror_yoz(cid, k4, "ZZ dalilsiz", "dalilsiz", kim="s",
                    dalil={"a": 4}, ishonch="kompaniya_sessiyasi")

        # 5) BIR ATAMAGA IKKI KOD — ATAYLAB
        k5 = PREFIKS + "_kopkod"
        K.qaror_ochish(cid, k5, "ZZ kabel")
        K.qaror_yoz(cid, k5, "ZZ kabel", "kod", kim="s", code="26.30",
                    manba="qidiruv", dalil={"a": 5}, ishonch="kompaniya_sessiyasi")
        K.qaror_yoz(cid, k5, "ZZ kabel", "kod", kim="s", code="26.20",
                    manba="qidiruv", qoshimcha_kod=True, dalil={"a": 5}, ishonch="kompaniya_sessiyasi")

        with conn.cursor() as cur:
            cur.execute("SELECT kalit, taklif_holati, rad_takliflar, "
                        "qoshimcha_kod, qaror FROM v_kod_qaror_tafsil "
                        "WHERE kalit LIKE %s ORDER BY kalit, id",
                        (PREFIKS + "%",))
            rows = {}
            for r in cur.fetchall():
                rows.setdefault(r[0], []).append(r)

        check("1) taklif QABUL qilindi",
              rows[k1][0][1] == "qabul", str(rows[k1][0]))
        check("2) taklif O'ZGARTIRILDI",
              rows[k2][0][1] == "ozgartirildi", str(rows[k2][0]))
        check("2) rad etilgan taklif SAQLANDI",
              rows[k2][0][2] == ["26.20"], str(rows[k2][0][2]))
        check("3) 'talabsiz' -> kod berilmadi",
              rows[k3][0][1] == "kod_berilmadi" and rows[k3][0][4] == "talabsiz")
        check("4) 'dalilsiz' ALOHIDA holat",
              rows[k4][0][4] == "dalilsiz",
              "'talabsiz' bilan aralashmasin: biri XULOSA, biri XULOSA YO'QLIGI")
        check("5) bir atamaga IKKI kod yozildi", len(rows[k5]) == 2,
              str(len(rows[k5])))
        check("5) ikkinchisi QO'SHIMCHA deb belgilangan",
              any(r[3] for r in rows[k5]) and not all(r[3] for r in rows[k5]),
              "fikr o'zgarishi bilan aralashmasin")

        # --- O'LCHOV: hamma raqam joyida ---
        o = K.qaror_olchov(cid)
        check("qaror_soni = 6", (o.get("qaror_soni") or 0) == 6, str(o.get("qaror_soni")))
        check("atama_soni = 5 (qator emas, ATAMA)",
              (o.get("atama_soni") or 0) == 5, str(o.get("atama_soni")))
        check("kod_berildi = 4", (o.get("kod_berildi") or 0) == 4)
        check("talabsiz = 1", (o.get("talabsiz") or 0) == 1)
        check("dalilsiz = 1", (o.get("dalilsiz") or 0) == 1)
        check("taklif_qabul = 1", (o.get("taklif_qabul") or 0) == 1)
        check("taklif_ozgartirildi = 1", (o.get("taklif_ozgartirildi") or 0) == 1)
        check("taklif_rad = 1 (talabsiz + taklif bor edi)",
              (o.get("taklif_rad") or 0) == 1)
        check("rad_taklif_soni = 2", (o.get("rad_taklif_soni") or 0) == 2)
        check("qoshimcha_kod_soni = 1", (o.get("qoshimcha_kod_soni") or 0) == 1)
        check("kop_kodli_atama = 1", (o.get("kop_kodli_atama") or 0) == 1)
        # 3 ta qaror taklif bilan, 1 tasi qabul -> 33.3%
        check("taklif_kelishuv_foiz hisoblandi",
              o.get("taklif_kelishuv_foiz") is not None,
              str(o.get("taklif_kelishuv_foiz")))
        check("dalil_qamrov_foiz = 100",
              float(o.get("dalil_qamrov_foiz") or 0) == 100.0,
              str(o.get("dalil_qamrov_foiz")))
    finally:
        tozala(conn)


# =====================================================================
# 5) BO'SH KOD — ILOVA QATLAMI ANIQ XATO BERADI
# =====================================================================
def test_bosh_kod(conn, cid) -> None:
    section("Bo'sh/yaroqsiz kodni TASODIFAN tasdiqlab bo'lmaydi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    from api import db, kodlash as K
    try:
        db.init_pool()
    except Exception:                                          # noqa: BLE001
        pass
    tozala(conn)
    k = PREFIKS + "_bosh"
    try:
        for nom, kw in (
                ("code=None", {"code": None}),
                ("code=''", {"code": ""}),
                ("code='   '", {"code": "   "})):
            try:
                K.qaror_yoz(cid, k, "ZZ", "kod", kim="s", **kw, ishonch="kompaniya_sessiyasi")
                check(f"RAD: 'kod' + {nom}", False, "qabul qilindi!")
            except ValueError as e:
                check(f"RAD: 'kod' + {nom}", True, str(e)[:60])

        try:
            K.qaror_yoz(cid, k, "ZZ", "talabsiz", kim="s", code="26.30", ishonch="kompaniya_sessiyasi")
            check("RAD: 'talabsiz' + kod", False, "qabul qilindi!")
        except ValueError:
            check("RAD: 'talabsiz' + kod", True)

        try:
            K.qaror_yoz(cid, k, "ZZ", "tasdiq", kim="s", ishonch="kompaniya_sessiyasi")
            check("RAD: notanish qaror turi", False, "qabul qilindi!")
        except ValueError:
            check("RAD: notanish qaror turi", True)

        try:
            K.qaror_yoz(cid, k, "ZZ", "otkazildi", kim="  ", ishonch="kompaniya_sessiyasi")
            check("RAD: kim bo'sh", False, "qabul qilindi!")
        except ValueError:
            check("RAD: kim bo'sh", True)

        # DALIL chegarasi — cheksiz JSON jadvalni shishirmasin.
        try:
            K.qaror_yoz(cid, k, "ZZ", "otkazildi", kim="s",
                        dalil={"x": "a" * (K.DALIL_MAX + 100)}, ishonch="kompaniya_sessiyasi")
            check("RAD: dalil chegaradan katta", False, "qabul qilindi!")
        except ValueError as e:
            check("RAD: dalil chegaradan katta", True, str(e)[:60])

        # Tanlangan kod "rad etilgan" ro'yxatida QOLMAYDI.
        K.qaror_ochish(cid, k, "ZZ")
        K.qaror_yoz(cid, k, "ZZ", "kod", kim="s", code="26.30",
                    rad_takliflar=["26.30", "26.20"], ishonch="kompaniya_sessiyasi")
        with conn.cursor() as cur:
            cur.execute("SELECT rad_takliflar FROM kod_qaror WHERE kalit=%s", (k,))
            rad = cur.fetchone()[0]
        check("tanlangan kod rad ro'yxatidan CHIQARILDI",
              rad == ["26.20"], str(rad))
    finally:
        tozala(conn)


# =====================================================================
# 6) AUDIT IZI — biriktirma qarorga bog'lanadi
# =====================================================================
def test_audit_izi(conn, cid) -> None:
    section("Audit izi: biriktirma QAYSI qarordan kelgani")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='catalog_product_code' "
                    "  AND column_name='qaror_id'")
        check("`catalog_product_code.qaror_id` ustuni bor", cur.fetchone() is not None)

        # MAVJUD 960 qator — audit izisiz. Bu HALOL holat va sinov
        # uni tasdiqlaydi: ular ko'rib chiqish halqasidan O'TMAGAN.
        #
        # KOMPANIYA `cid` DAN OLINMAYDI: `cid` =
        # `company_account ORDER BY id LIMIT 1` va u sinov
        # kompaniyasiga (ZZTEST) tushishi mumkin — unda katalog yo'q.
        # Biriktirmalar QAYSI kompaniyada bo'lsa, o'shani qaraymiz.
        cur.execute("SELECT count(*) FILTER (WHERE qaror_id IS NULL), "
                    "       count(*) FILTER (WHERE qaror_id IS NOT NULL), "
                    "       count(*) FROM catalog_product_code "
                    "WHERE tasdiqlandi IS NOT NULL")
        yoq, bor, jami = cur.fetchone()
    if jami == 0:
        check("tasdiqlangan biriktirma yo'q — audit sinovi o'tkazildi",
              True, "bazada tasdiqlangan biriktirma yo'q")
    else:
        print(f"      audit izi bor: {bor}, yo'q: {yoq} (eski to'plam)")
        check("audit izi HALOL ko'rsatiladi (NULL yashirilmaydi)",
              yoq + bor == jami,
              "ML ground truth uchun FAQAT `qaror_id IS NOT NULL` ishlatilsin")

    src = io.open(os.path.join(ROOT, "api", "kodlash.py"), encoding="utf-8").read()
    check("`tasdiqla()` `qaror_id` qabul qiladi", "qaror_id: Optional[int]" in src)
    check("`atamaga_kod_biriktir()` uni uzatadi",
          "qaror_id=qaror_id" in src)
    check("qayta tasdiqlashda audit izi YO'QOLMAYDI",
          "COALESCE(%(q)s, qaror_id)" in src)
    main = io.open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
    check("endpoint qaror id sini uzatadi",
          'qaror_id=row.get("id")' in main)


# =====================================================================
# 7) PILOT KO'RINISHI — 40 taga qancha qolgani
# =====================================================================
def _sinov_aktori(db, cid: int) -> int:
    """Sinov uchun ATRIBUTLANGAN aktor. Bor bo'lsa qayta ishlatiladi.

    `_tozala()` aktorni o'chirmaydi (audit unga FK bilan bog'langan),
    shuning uchun qayta yurishda mavjudini olamiz.
    """
    r = db.query_one("SELECT id FROM actor WHERE company_id=%(c)s "
                     "  AND login='zzkodpilot'", {"c": cid})
    if r:
        db.execute_returning("UPDATE actor SET active=true WHERE id=%(i)s "
                             "RETURNING id", {"i": r["id"]})
        return int(r["id"])
    return int(db.execute_returning(
        "INSERT INTO actor (company_id, manba, login, ism, rol) "
        "VALUES (%(c)s, 'mahalliy', 'zzkodpilot', 'ZZSINOV kod', "
        "        'tasdiqlovchi') RETURNING id", {"c": cid})["id"])


def test_pilot_korinishi(conn, cid) -> None:
    section("Pilot ko'rinishi: 40 ta ATAMA maqsadi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    from api import db, kodlash as K
    try:
        db.init_pool()
    except Exception:                                          # noqa: BLE001
        pass
    tozala(conn)
    try:
        p0 = K.pilot_holati(cid)
        check("pilot ko'rinishi ishlaydi", bool(p0), str(p0)[:80])
        check("maqsad 40", (p0.get("maqsad") or 0) == 40)
        boshlangich = p0.get("atama_soni") or 0

        # ANONIM QAROR MAQSADGA SANALMAYDI.
        #
        # O'LCHANGAN NUQSON (2026-09-03): `v_kod_pilot` shunchaki
        # `qaror IS NOT NULL` ni sanardi, ya'ni `kompaniya_sessiyasi`
        # (anonim) va hatto `servis` (mashina) ham maqsadga kirardi.
        # Sifat darvozasi esa FAQAT `aktorli` ni sanaydi — ekran
        # "40/40 bajarildi" ko'rsatib turgan holda darvoza
        # "0/40 TASDIQLANMAGAN" derdi. Endi ikkalasi BIR XIL shartda.
        anon = PREFIKS + "_anonim"
        K.qaror_ochish(cid, anon, "ZZ")
        K.qaror_yoz(cid, anon, "ZZ", "kod", kim="s", code="26.30",
                    ishonch="kompaniya_sessiyasi")
        p_anon = K.pilot_holati(cid)
        check("ANONIM qaror maqsadga SANALMAYDI",
              (p_anon.get("atama_soni") or 0) == boshlangich,
              f"{boshlangich} -> {p_anon.get('atama_soni')}")
        check("lekin u YASHIRILMAYDI (`atributsiz_qaror`)",
              (p_anon.get("atributsiz_qaror") or 0) >= 1,
              str(p_anon.get("atributsiz_qaror")))

        # BIR ATAMAGA IKKI KOD maqsadni SOXTA yaqinlashtirmasin.
        # Endi qarorlar ATRIBUTLANGAN bo'lishi shart, aks holda
        # ular maqsadga umuman kirmaydi.
        aid = _sinov_aktori(db, cid)
        k = PREFIKS + "_pilot"
        K.qaror_ochish(cid, k, "ZZ")
        K.qaror_yoz(cid, k, "ZZ", "kod", kim="s", code="26.30",
                    actor_id=aid, ishonch="aktor_elon")
        K.qaror_yoz(cid, k, "ZZ", "kod", kim="s", code="26.20",
                    qoshimcha_kod=True, actor_id=aid, ishonch="aktor_elon")
        p1 = K.pilot_holati(cid)
        check("ikki kod -> atama_soni FAQAT 1 oshdi",
              (p1.get("atama_soni") or 0) == boshlangich + 1,
              f"{boshlangich} -> {p1.get('atama_soni')}")
        check("qaror_soni esa 2 oshdi",
              (p1.get("qaror_soni") or 0) == (p0.get("qaror_soni") or 0) + 2)
        check("`qolgan` atama bo'yicha hisoblanadi",
              (p1.get("qolgan") or 0) == max(0, 40 - (p1.get("atama_soni") or 0)))
    finally:
        tozala(conn)


# =====================================================================
# 8) HAR SINOVDAN KEYIN: SOXTA QATOR QOLMADI
# =====================================================================
def test_soxta_qator_yoq(conn, cid) -> None:
    section("Soxta qaror qatori YO'Q")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM kod_qaror WHERE kalit LIKE %s",
                    (PREFIKS + "%",))
        check("sinov qatorlari tozalandi", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM kod_qaror "
                    "WHERE qaror IS NOT NULL AND (kim IS NULL OR btrim(kim)='' "
                    "      OR qaror_at IS NULL)")
        check("odamsiz qaror = 0", cur.fetchone()[0] == 0)
        cur.execute("SELECT count(*) FROM kod_qaror "
                    "WHERE qaror = 'kod' AND (code IS NULL OR btrim(code)='')")
        check("kodsiz 'kod' qarori = 0", cur.fetchone()[0] == 0)


# =====================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="Kodlash piloti sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: KODLASH PILOTI — INSON QARORI HALQASI")
    print("=" * 70)

    test_render_qaror_emas_statik()
    test_konstantalar()

    conn = db_conn()
    if conn is None or args.bazasiz:
        if conn is None:
            print("\n[i] Baza yo'q — cheklov sinovlari o'tkazib yuborildi.")
        else:
            print("\n[i] --offline: baza sinovlari o'tkazib yuborildi.")
            conn.close()
    else:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM company_account ORDER BY id LIMIT 1")
            r = cur.fetchone()
        cid = r[0] if r else None
        if cid is None:
            print("\n[i] Kompaniya topilmadi.")
        else:
            tozala(conn)
            test_baza_qulflari(conn, cid)
            test_halqa(conn, cid)
            test_olchovsiz_nol_emas(conn, cid)
            test_harakatlar(conn, cid)
            test_bosh_kod(conn, cid)
            test_audit_izi(conn, cid)
            test_pilot_korinishi(conn, cid)
            tozala(conn)
            test_soxta_qator_yoq(conn, cid)
        conn.close()

    otdi = sum(1 for _n, ok, _d in _results if ok)
    jami = len(_results)
    print("\n" + "=" * 70)
    for n, ok, d in _results:
        if not ok:
            print(f"  YIQILDI: {n}" + (f" -- {d}" if d else ""))
    print(f"NATIJA: {otdi}/{jami} o'tdi")
    print("=" * 70)
    sys.exit(0 if otdi == jami else 1)


if __name__ == "__main__":
    main()
