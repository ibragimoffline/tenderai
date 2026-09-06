#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: AKTOR KIMLIGI, RUXSAT VA AUDIT (auth-6)
===============================================

NIMA TEKSHIRILADI VA NEGA

  1. XARITA, KIMLIK OMBORI EMAS. `actor` jadvalida parol/token/sessiya
     ustunlari BO'LMASLIGI kerak. Ular paydo bo'lsa bu ikkinchi
     kimlik tizimi bo'lardi — aynan `schema_patch_auth_2.sql` olib
     tashlagan narsa.

  2. IJARACHILARARO SOXTALASHTIRISH MUMKIN EMAS. Ikki darajada
     o'lchanadi:
       a) BAZA — kompozit FK `(company_id, actor_id)`;
       b) API  — `X-Actor` bilan boshqa ijarachining aktorini
          ko'rsatishga urinish.
     Ikkalasi ham HAQIQIY qatorlarda sinaladi: bo'sh to'plamda
     "rad etildi" degan xulosa YOLG'ON bo'lardi.

  3. AUDIT QAYTA YOZILMAYDI. `UPDATE`/`DELETE` bazada to'silgan.
     Kaskad yo'l ham tekshiriladi.

  4. YORLIQ DALILDAN OSHMAYDI. `ishonch` va `actor_id` bir-biriga
     zid bo'la olmaydi.

  5. RUXSAT. Rol matritsasi amalda ishlaydi; `servis` (ERP kaliti)
     inson qarorini qo'ya olmaydi.

XAVFSIZLIK. Sinov O'Z ijarachilarini yaratadi (`zztest_aktor_`
prefiksi) va oxirida ularni FAOLSIZLANTIRADI. HAQIQIY ijarachining
qatorlariga TEGMAYDI — bu sinovda ilgari haqiqiy ma'lumot
yo'qotilgan (`requirement_test`, 2026-08-30), shuning uchun bu yerda
har o'zgarish faqat SINOV yaratgan id larga tegadi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\aktor_test.py
    .venv\\Scripts\\python.exe _tests\\aktor_test.py --offline
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []
#: Sinov yaratgan id lar — FAQAT shular tozalanadi.
_yaratilgan = {"company": [], "actor": [], "tender": [], "requirement": [],
               "routing": []}


class SoxtaRequest:
    """`aktor.aniqla()` uchun minimal so'rov.

    YAGONA STUB. Ilgari `test_api` ichida mahalliy nusxasi bor edi va
    13-bo'lim yana bittasini yaratgan edi — ikki stub vaqt o'tishi
    bilan HAR XIL xatti-harakat qilib, sinovlar bir-biriga zid
    natija berardi. `aniqla()` `headers` va `state` ni o'qiydi.
    """

    def __init__(self, headers, service=False):
        self.headers = headers

        class S:
            pass
        self.state = S()
        self.state.service = service
        self.state.account = None if service else {"id": 1}


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
# 1. STATIK
# =====================================================================
def test_manba():
    bolim("1. Manba — xarita, kimlik ombori EMAS")
    sql = io.open(os.path.join(ROOT, "schema_patch_aktor.sql"),
                  encoding="utf-8").read()
    # Izohlarni olib tashlaymiz: izohda "parol" so'zi BOR (nega yo'qligi
    # yozilgan) va u DDL bilan adashmasligi kerak.
    kod = re.sub(r"--[^\n]*", " ", sql)
    jadval = kod[kod.index("CREATE TABLE IF NOT EXISTS actor"):]
    jadval = jadval[:jadval.index(");")]
    for yomon in ("password", "parol", "token", "session", "secret"):
        check(f"`actor` da `{yomon}` ustuni YO'Q", yomon not in jadval.lower())
    check("kompozit unikal kalit bor (ijarachi izolyatsiyasi uchun)",
          "UNIQUE (company_id, id)" in jadval)

    for nom, naqsh in (
            ("kompozit FK — talab", "tender_requirement_aktor_fk"),
            ("kompozit FK — yo'naltirish", "tender_routing_aktor_fk"),
            ("kompozit FK — kodlash", "kod_qaror_aktor_fk"),
            ("kompozit FK — audit", "audit_jurnal_aktor_fk"),
            ("audit append-only trigger", "audit_jurnal_ozgarmas_trg"),
            ("ishonch lug'ati funksiyasi", "ishonch_yaroqli"),
            ("atribut sifati ko'rinishi", "v_atribut_sifati")):
        check(nom, naqsh in kod)


def test_lugat_mosligi():
    bolim("2. Lug'at — Python va SQL BIR XIL")
    from api import aktor
    sql = io.open(os.path.join(ROOT, "schema_patch_aktor.sql"),
                  encoding="utf-8").read()
    fn = sql[sql.index("CREATE OR REPLACE FUNCTION ishonch_yaroqli"):]
    fn = fn[:fn.index("$$", fn.index("SELECT"))]
    sqlda = set(re.findall(r"'([a-z_]+)'", fn))
    check("ishonch darajalari MOS", sqlda == set(aktor.ISHONCH),
          f"sql={sorted(sqlda)} py={sorted(aktor.ISHONCH)}")

    rol_fn = sql[sql.index("actor_rol_chk"):]
    rol_fn = rol_fn[:rol_fn.index("END IF")]
    check("rollar MOS", set(re.findall(r"'([a-z_]+)'", rol_fn)) -
          {"actor_rol_chk"} == set(aktor.ROLLAR))

    # Matritsadagi HAR rol lug'atda bo'lishi shart.
    hamma = {r for rr in aktor.RUXSAT.values() for r in rr}
    check("matritsadagi rollar lug'atda bor", hamma <= set(aktor.ROLLAR),
          str(hamma - set(aktor.ROLLAR)))
    # `admin` HAR amalni bajara olishi kerak — aks holda ijarachi
    # o'z sozlamasini o'zgartira olmay qolardi.
    check("admin HAR amalni bajaradi",
          all("admin" in r for r in aktor.RUXSAT.values()))
    # `kuzatuvchi` HECH BIR o'zgartiruvchi amalni bajara olmasligi kerak.
    check("kuzatuvchi faqat ko'radi",
          all("kuzatuvchi" not in r for a, r in aktor.RUXSAT.items()
              if a != "korish"))


def test_mijoz_aktor_yubormaydi():
    bolim("3. Mijoz aktorni O'ZI yoza olmaydi")
    main = io.open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
    rd = main[main.index("class RoutingDecisionIn"):]
    rd = rd[:rd.index("@app.post")]
    # ILGARI `broker: Optional[str] = None` bor edi va u
    # `routing.qaror(broker=body.broker)` ga tushardi.
    check("`RoutingDecisionIn` da `broker` maydoni YO'Q",
          not re.search(r"^\s*broker\s*:", rd, re.M), rd.strip()[:80])
    check("`body.broker` hech qayerda ishlatilmaydi",
          "body.broker" not in main)

    rt = io.open(os.path.join(ROOT, "api", "routing.py"), encoding="utf-8").read()
    q = rt[rt.index("def qaror("):]
    q = q[:q.index("\n\n\n")]
    # 20-vazifadan keyin xatolar KOD bilan ko'tariladi (javob uch
    # tilli interfeysga bog'lanishi uchun) — tekshiruv ham kod
    # bo'yicha: u tarjima o'zgarganda yiqilmaydi.
    check("`routing.qaror` ishonch darajasini TALAB qiladi",
          'Xato("TRUST_LEVEL_INVALID"' in q)
    check("`routing.qaror` aktorsiz `aktor_elon` ni rad etadi",
          'Xato("ACTOR_REQUIRED_FOR_TRUST"' in q)


# =====================================================================
# BAZALI
# =====================================================================
def _db():
    from api import db
    db.init_pool()
    return db


def _tozala(db):
    """FAQAT sinov yaratgan qatorlarni oladi.

    AUDIT QATORLARI O'CHIRILMAYDI — jadval append-only va bu
    ATAYLAB. Sinov ijarachilari o'chirilmaydi, FAOLSIZLANTIRILADI
    (`auth_test` bilan bir xil qoida).

    PUL QAYTA OCHILADI: `TestClient(app)` kontekstdan chiqqanda
    `lifespan` ni yopadi va u DB pulini ham yopadi. Tozalash undan
    KEYIN yuradi, ya'ni pulsiz qolardi va sinov qatorlari BAZADA
    QOLIB KETARDI.
    """
    try:
        db.init_pool()
    except Exception:                                         # noqa: BLE001
        pass
    for rid in _yaratilgan["requirement"]:
        db.execute_returning("DELETE FROM tender_requirement WHERE id=%(i)s "
                             "RETURNING id", {"i": rid})
    for rid in _yaratilgan["routing"]:
        db.execute_returning("DELETE FROM tender_routing WHERE id=%(i)s "
                             "RETURNING id", {"i": rid})
    for aid in _yaratilgan["actor"]:
        db.execute_returning("UPDATE actor SET active=false WHERE id=%(i)s "
                             "RETURNING id", {"i": aid})
    for cid in _yaratilgan["company"]:
        db.execute_returning(
            "UPDATE company_account SET active=false, aktor_majburiy=false "
            "WHERE id=%(i)s RETURNING id", {"i": cid})


def _ijarachi(db, login):
    r = db.query_one("SELECT id FROM company_account WHERE username=%(u)s",
                     {"u": login})
    if r:
        db.execute_returning(
            "UPDATE company_account SET active=true, aktor_majburiy=false "
            "WHERE id=%(i)s RETURNING id", {"i": r["id"]})
        # QAYTA YURISHDA HAM RO'YXATGA TUSHADI. Busiz ikkinchi
        # yurishdan keyin sinov ijarachisi FAOL qolib ketardi
        # (o'lchandi: birinchi tuzatishdan keyin `active=true`).
        _yaratilgan["company"].append(r["id"])
        return r["id"]
    r = db.execute_returning(
        "INSERT INTO company_account(username, company_name, password_hash, active) "
        "VALUES (%(u)s, %(n)s, '!sinov-yaroqsiz-xesh', true) RETURNING id",
        {"u": login, "n": f"SINOV {login}"})
    _yaratilgan["company"].append(r["id"])
    return r["id"]


def _aktor(db, cid, login, rol):
    r = db.query_one("SELECT id FROM actor WHERE company_id=%(c)s AND login=%(l)s",
                     {"c": cid, "l": login})
    if r:
        db.execute_returning(
            "UPDATE actor SET active=true, rol=%(r)s WHERE id=%(i)s RETURNING id",
            {"i": r["id"], "r": rol})
        _yaratilgan["actor"].append(r["id"])
        return r["id"]
    r = db.execute_returning(
        "INSERT INTO actor(company_id, manba, login, ism, rol) "
        "VALUES (%(c)s, 'mahalliy', %(l)s, %(n)s, %(r)s) RETURNING id",
        {"c": cid, "l": login, "n": f"Sinov {login}", "r": rol})
    _yaratilgan["actor"].append(r["id"])
    return r["id"]


def test_baza_qulflari(db):
    bolim("4. BAZA — ijarachilararo soxtalashtirish JISMONAN mumkin emas")
    a_cid = _ijarachi(db, "zztest_aktor_a")
    b_cid = _ijarachi(db, "zztest_aktor_b")
    check("ikki sinov ijarachisi yaratildi", a_cid != b_cid, f"{a_cid} / {b_cid}")

    a_aktor = _aktor(db, a_cid, "zzt_a_admin", "admin")
    b_aktor = _aktor(db, b_cid, "zzt_b_koruvchi", "koruvchi")

    # HAQIQIY qator kerak: bo'sh to'plamdagi UPDATE "muvaffaqiyatli"
    # bo'ladi va sinov YOLG'ON PASS berardi.
    t = db.query_one("SELECT id FROM tender ORDER BY id LIMIT 1")
    if not t:
        check("sinov uchun tender kerak", False, "tender jadvali bo'sh")
        return a_cid, b_cid, a_aktor, b_aktor
    tid = t["id"]

    r = db.execute_returning(
        "INSERT INTO tender_requirement(company_id, tender_id, source, name, "
        "method, review_status, mashina_holat) "
        "VALUES (%(c)s, %(t)s, 'api', 'ZZTEST aktor talabi', 'naqsh', "
        "        'pending_review', 'ajratilgan') RETURNING id",
        {"c": b_cid, "t": tid})
    b_req = r["id"]
    _yaratilgan["requirement"].append(b_req)
    check("B ijarachisida haqiqiy talab qatori bor", bool(b_req), f"id={b_req}")

    def yoz(sql, p):
        """Yozadi; xato matnini qaytaradi (yoki None).

        `db.execute_returning()` RETURNING ni TALAB qiladi (aks holda
        `no results to fetch`), shuning uchun har SQL da u bor.
        """
        try:
            db.execute_returning(sql, p)
            return None
        except Exception as e:                                # noqa: BLE001
            return str(e)

    # AKTOR INSON QARORI BILAN BIRGA yoziladi. Yolg'iz `reviewed_actor_id`
    # ni `pending_review` qatoriga yozib bo'lmaydi va bu KUTILGAN:
    # `tender_requirement_mashina_aktor_chk` mashina holatida aktor izi
    # qolishini taqiqlaydi. (Birinchi urinishda sinov aynan shu yerda
    # yiqildi va u SINOVNING xatosi edi, cheklovniki emas.)
    INSON = ("SET review_status='approved', reviewed_by=%(c)s, "
             "reviewed_at=now(), review_action='approve', "
             "reviewed_ishonch='aktor_elon', reviewed_actor_id=%(a)s ")

    xato = yoz("UPDATE tender_requirement " + INSON +
               "WHERE id=%(i)s RETURNING id",
               {"a": a_aktor, "c": b_cid, "i": b_req})
    check("B ijarachisi A ning aktorini talabga YOZA OLMAYDI",
          xato is not None and "aktor_fk" in (xato or ""),
          (xato or "QABUL QILINDI")[:60])

    xato = yoz("UPDATE tender_requirement " + INSON +
               "WHERE id=%(i)s RETURNING id",
               {"a": b_aktor, "c": b_cid, "i": b_req})
    check("B ijarachisi O'Z aktorini yoza oladi", xato is None, (xato or "")[:60])

    # MASHINA HOLATIDA AKTOR IZI QOLMASLIGI ham tekshiriladi.
    xato = yoz("UPDATE tender_requirement SET review_status='pending_review', "
               "reviewed_by=NULL, reviewed_at=NULL, review_action=NULL, "
               "reviewed_actor_id=%(a)s, reviewed_ishonch='aktor_elon' "
               "WHERE id=%(i)s RETURNING id", {"a": b_aktor, "i": b_req})
    check("mashina holatida AKTOR IZI qololmaydi", xato is not None,
          (xato or "QABUL QILINDI")[:60])

    xato = yoz("INSERT INTO audit_jurnal(company_id, actor_id, ishonch, amal, "
               "entity, entity_id) VALUES (%(c)s, %(a)s, 'aktor_elon', "
               "'sinov', 'tender_requirement', %(i)s) RETURNING id",
               {"c": b_cid, "a": a_aktor, "i": b_req})
    check("B ijarachisi A ning aktorini AUDITGA yoza olmaydi",
          xato is not None, (xato or "QABUL QILINDI")[:60])

    xato = yoz("INSERT INTO audit_jurnal(company_id, actor_id, ishonch, amal, "
               "entity, entity_id) VALUES (%(c)s, %(a)s, 'aktor_elon', "
               "'sinov', 'tender_requirement', %(i)s) RETURNING id",
               {"c": b_cid, "a": b_aktor, "i": b_req})
    check("B ijarachisi O'Z aktori bilan auditga yozadi", xato is None,
          (xato or "")[:60])

    bolim("5. Yorliq dalildan OSHMAYDI")
    for nom, ish, aid in (
            ("`servis` darajasi AKTOR bilan", "servis", b_aktor),
            ("`kompaniya_sessiyasi` AKTOR bilan", "kompaniya_sessiyasi", b_aktor)):
        xato = yoz("INSERT INTO audit_jurnal(company_id, actor_id, ishonch, "
                   "amal, entity, entity_id) VALUES (%(c)s, %(a)s, %(s)s, "
                   "'sinov', 'x', 1) RETURNING id", {"c": b_cid, "a": aid, "s": ish})
        check(nom + " RAD ETILADI", xato is not None)
    xato = yoz("INSERT INTO audit_jurnal(company_id, ishonch, amal, entity, "
               "entity_id) VALUES (%(c)s, 'aktor_elon', 'sinov', 'x', 1) "
               "RETURNING id",
               {"c": b_cid})
    check("`aktor_elon` AKTORSIZ rad etiladi", xato is not None)
    xato = yoz("INSERT INTO audit_jurnal(company_id, ishonch, amal, entity, "
               "entity_id) VALUES (%(c)s, 'ishonaman', 'sinov', 'x', 1) "
               "RETURNING id",
               {"c": b_cid})
    check("noma'lum ishonch darajasi rad etiladi", xato is not None)

    bolim("6. AUDIT qayta yozilmaydi")
    r = db.query_one("SELECT id FROM audit_jurnal WHERE company_id=%(c)s "
                     "ORDER BY id DESC LIMIT 1", {"c": b_cid})
    if not r:
        check("audit qatori kerak", False, "yozilmadi")
    else:
        aid = r["id"]
        for nom, sql in (
                ("UPDATE bloklanadi",
                 f"UPDATE audit_jurnal SET amal='boshqa' WHERE id={aid} RETURNING id"),
                ("DELETE bloklanadi",
                 f"DELETE FROM audit_jurnal WHERE id={aid} RETURNING id"),
                ("vaqt tamg'asini surish bloklanadi",
                 f"UPDATE audit_jurnal SET at=now()-interval '1 year' WHERE id={aid} RETURNING id"),
                ("ishonch darajasini ko'tarish bloklanadi",
                 f"UPDATE audit_jurnal SET ishonch='erp_sessiya' WHERE id={aid} RETURNING id")):
            xato = yoz(sql, {})
            check(nom, xato is not None and "APPEND-ONLY" in (xato or "").upper()
                  or (xato is not None), (xato or "QABUL QILINDI")[:50])

        # KASKAD YO'L HAM TO'SILADI. Bu MUHIM: ijarachini o'chirish
        # `ON DELETE CASCADE` orqali audit qatorlarini olib ketardi va
        # append-only kafolati aylanma yo'l bilan buzilardi.
        xato = yoz("DELETE FROM company_account WHERE id=%(i)s RETURNING id",
                   {"i": b_cid})
        check("ijarachini o'chirish orqali AUDIT ham o'chmaydi (kaskad)",
              xato is not None, (xato or "KASKAD O'TDI — AUDIT YO'QOLARDI")[:60])

    return a_cid, b_cid, a_aktor, b_aktor


def test_izchillik(db, a_cid, a_aktor):
    """`ishonch` va `actor_id` ZID bo'la olmaydi — BAZA darajasida (M-2)."""
    bolim("5. ISHONCH <-> AKTOR IZCHILLIGI (M-2)")

    # Qoida `audit_jurnal` da CHECK bilan himoyalangan edi, QAROR
    # jadvallarida esa FAQAT KODDA. Ya'ni to'g'ridan-to'g'ri SQL
    # zid qator yozishi mumkin edi.
    for jadval in ("tender_routing", "tender_requirement", "kod_qaror"):
        n = db.scalar("""SELECT count(*) FROM pg_constraint
                          WHERE conrelid = %(t)s::regclass
                            AND conname LIKE %(p)s""",
                      {"t": jadval, "p": "%aktor_izchil%"})
        check(f"`{jadval}` da izchillik CHECK bor", n == 1, f"{n} ta")

    t = db.query_one("SELECT id FROM tender ORDER BY id LIMIT 1")
    if not t:
        check("sinov uchun tender kerak", False, "tender jadvali bo'sh")
        return
    r = db.execute_returning(
        "INSERT INTO tender_requirement(company_id, tender_id, source, name, "
        "method, review_status, mashina_holat) "
        "VALUES (%(c)s, %(t)s, 'api', 'ZZTEST izchillik', 'naqsh', "
        "        'pending_review', 'ajratilgan') RETURNING id",
        {"c": a_cid, "t": t["id"]})
    rid = r["id"]
    _yaratilgan["requirement"].append(rid)

    def urin(nom, ishonch, actor_id):
        """Zid juftlikni yozishga urinadi. `True` = RAD ETILDI."""
        try:
            db.execute_returning(
                "UPDATE tender_requirement SET review_status='approved', "
                "  reviewed_by=%(c)s, reviewed_at=now(), review_action='approve', "
                "  reviewed_ishonch=%(i)s, reviewed_actor_id=%(a)s "
                "WHERE id=%(id)s RETURNING id",
                {"c": a_cid, "i": ishonch, "a": actor_id, "id": rid})
            return False, "qabul qilindi"
        except Exception as e:                                # noqa: BLE001
            # AYNAN izchillik cheklovi ishlashi kerak — boshqa xato
            # (masalan FK) ham "rad etildi" ko'rinardi, lekin
            # qo'riqchini ISBOTLAMASDI.
            m = str(e)
            return ("aktor_izchil" in m), m.splitlines()[0][:90]

    ok, d = urin("erp_sessiya aktorSIZ", "erp_sessiya", None)
    check("`erp_sessiya` + aktorSIZ RAD ETILADI", ok, d)
    ok, d = urin("kompaniya_sessiyasi AKTOR bilan", "kompaniya_sessiyasi", a_aktor)
    check("`kompaniya_sessiyasi` + AKTOR bilan RAD ETILADI", ok, d)

    # MUSBAT TOMONI HAM: to'g'ri juftlik O'TISHI kerak. Busiz
    # cheklov "hech narsani o'tkazmaydi" holatida ham sinovdan
    # o'tardi.
    try:
        db.execute_returning(
            "UPDATE tender_requirement SET review_status='approved', "
            "  reviewed_by=%(c)s, reviewed_at=now(), review_action='approve', "
            "  reviewed_ishonch='aktor_elon', reviewed_actor_id=%(a)s "
            "WHERE id=%(id)s RETURNING id",
            {"c": a_cid, "a": a_aktor, "id": rid})
        check("`aktor_elon` + AKTOR bilan QABUL QILINADI", True)
    except Exception as e:                                    # noqa: BLE001
        check("`aktor_elon` + AKTOR bilan QABUL QILINADI", False,
              str(e).splitlines()[0][:90])

    # ESKI YORLIQ MUZLATILGAN. `kuzatuvdan_oldin` — MIGRATSIYA
    # yorlig'i: u "kim ekani noma'lum" degani va YANGI qaror unga
    # yozilsa, javobsizlik qonuniylashtirilardi.
    eski = {r["jadval"]: r["soni"]
            for r in db.query("SELECT * FROM v_aktor_eski_yorliq")}
    print(f"      eski yorliq: {eski}")
    check("`kuzatuvdan_oldin` FAQAT `tender_routing` da",
          eski.get("tender_requirement", 0) == 0, str(eski))
    # 11-vazifa migratsiyasi 30 ta qatorni belgilagan. Bu son
    # O'SMASLIGI kerak — o'ssa yangi qaror eski yorliq ortiga
    # yashiringan.
    check("`tender_routing` dagi eski yorliq soni 30 dan OSHMAGAN",
          eski.get("tender_routing", 0) <= 30,
          f"{eski.get('tender_routing')} ta (11-vazifa migratsiyasi 30 ta "
          f"qatorni belgilagan; oshgani yangi qaror eski yorliq ortiga "
          f"yashiringanini bildiradi)")

    src = io.open(os.path.join(ROOT, "api", "routing.py"),
                  encoding="utf-8").read()
    q = src[src.index("def qaror("):]
    q = q[:q.index(chr(10) * 3)]
    check("`routing.qaror()` `kuzatuvdan_oldin` ni QABUL QILMAYDI",
          "kuzatuvdan_oldin" not in q,
          "u migratsiya yorlig'i — ish yo'lidan yozilmasin")


def test_audit_tuzatish(db):
    """Audit artefakti YASHIRILMAYDI, BELGILANADI (M-3)."""
    bolim("6. AUDIT TUZATISHI — append-only buzilmaydi")

    # Jadval append-only. Triggerning O'Z xato matni yo'lni
    # ko'rsatadi: "Tuzatish kerak bo'lsa YANGI qator qo'shing
    # (amal='tuzatish')". Patch aynan shu yo'ldan borgan.
    check("`v_audit_jurnal_haqiqiy` mavjud",
          db.scalar("SELECT to_regclass('public.v_audit_jurnal_haqiqiy') "
                    "IS NOT NULL"))
    check("`v_audit_tuzatish` mavjud",
          db.scalar("SELECT to_regclass('public.v_audit_tuzatish') "
                    "IS NOT NULL"))

    # ARTEFAKT O'CHIRILMAGAN — jurnal to'liq qoladi.
    xom = db.scalar("SELECT count(*) FROM audit_jurnal WHERE id=37")
    check("tuzatilgan qator jurnalda QOLADI", xom == 1,
          "append-only: o'chirish audit jurnalini buzardi")

    # LEKIN u "haqiqiy amallar" ro'yxatidan CHIQARILGAN.
    haqiqiy = db.scalar(
        "SELECT count(*) FROM v_audit_jurnal_haqiqiy WHERE id=37")
    check("tuzatilgan qator HAQIQIY amallardan chiqarilgan", haqiqiy == 0)
    # `tuzatish` yozuvining O'ZI ham chiqariladi — u jurnal haqidagi
    # metama'lumot, ijarachi amali emas.
    check("`tuzatish` yozuvining O'ZI ham chiqarilgan",
          db.scalar("SELECT count(*) FROM v_audit_jurnal_haqiqiy "
                    "WHERE amal='tuzatish'") == 0)

    # TARIXDA BELGILANADI — yashirilmaydi.
    from api import aktor as A
    tarix = {r["id"]: r for r in A.tarix(2, limit=50)}
    check("`tarix()` tuzatilgan qatorni KO'RSATADI", 37 in tarix,
          "yashirish audit jurnalidan qator yo'qolgandek ko'rinardi")
    if 37 in tarix:
        check("`tuzatilgan` bayrog'i qo'yilgan", tarix[37]["tuzatilgan"] is True)
        check("tuzatish SABABI ham keladi",
              "artefakt" in (tarix[37]["tuzatish_izohi"] or ""),
              str(tarix[37]["tuzatish_izohi"])[:70])
    # Haqiqiy amal BELGILANMAGAN bo'lishi kerak — aks holda bayroq
    # hamma qatorga qo'yilayotgan bo'lardi va hech narsani
    # ajratmasdi.
    haqiqiylar = [r for r in tarix.values()
                  if r["amal"] not in ("tuzatish",) and not r["tuzatilgan"]]
    check("haqiqiy amallar BELGILANMAGAN", len(haqiqiylar) >= 1,
          f"{len(haqiqiylar)} ta belgilanmagan qator")

    # APPEND-ONLY O'ZI ISHLAYDIMI — "hech narsa buzilmadi" bilan
    # "qo'riqchi bor" ni ajratamiz.
    for op, sql in (("UPDATE", "UPDATE audit_jurnal SET izoh='x' "
                               "WHERE id=37 RETURNING id"),
                    ("DELETE", "DELETE FROM audit_jurnal "
                               "WHERE id=37 RETURNING id")):
        try:
            db.execute_returning(sql, {})
            check(f"audit_jurnal {op} TAQIQLANGAN", False, "bajarildi!")
        except Exception as e:                                # noqa: BLE001
            # IKKI XIL QO'RIQCHI — IKKALASI HAM QABUL QILINADI.
            #
            # O'LCHANGAN NUQSON (2026-09-04). Shart faqat
            # TRIGGER xabarini ("FAQAT QO'SHISH...") tanirdi.
            # Ilova roli (`tai_app`) bilan yurganda `audit_jurnal`
            # ga UPDATE/DELETE HUQUQ darajasida to'siladi va xato
            # boshqacha keladi ("нет доступа к таблице") — ya'ni
            # himoya KUCHLIROQ, sinov esa YIQILARDI.
            #
            # `auth_test` dagi `erp_yopiq` bilan bir shakl: huquq
            # OLDIN to'sadi, trigger KEYIN aytadi. Sinov "amal
            # bajarilmadimi" ni tekshirsin, QAYSI qatlam to'sganini
            # emas.
            xato = str(e)
            trigger = "FAQAT QO" in xato
            huquq = ("нет доступа" in xato or "permission denied" in xato
                     or "доступ" in xato.lower())
            check(f"audit_jurnal {op} TAQIQLANGAN", trigger or huquq,
                  ("trigger" if trigger else "huquq" if huquq else "?")
                  + ": " + xato.splitlines()[0][:60])


def test_api(db, a_cid, b_cid, a_aktor, b_aktor):
    bolim("7. API — `X-Actor` bilan boshqa ijarachining aktori")
    from fastapi.testclient import TestClient
    from api.main import app
    from api import aktor as A

    # B ijarachisi A ning aktorini KO'RSATADI.
    try:
        A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(a_aktor)}), b_cid)
        check("B ijarachisi A ning aktorini KO'RSATA OLMAYDI", False,
              "qabul qilindi")
    except A.RuxsatXato as e:
        check("B ijarachisi A ning aktorini KO'RSATA OLMAYDI",
              e.code == 404, f"kod {e.code}")
        # JAVOB "topilmadi" BO'LISHI KERAK, "boshqa ijarachiniki" EMAS:
        # aks holda "bu id mavjud" degan ma'lumot sizardi.
        check("javob ID MAVJUDLIGINI SIZDIRMAYDI",
              "boshqa" not in str(e).lower() and "ijarachi" not in str(e).lower(),
              str(e))

    k = A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(b_aktor)}), b_cid)
    check("B ijarachisi O'Z aktorini ko'rsata oladi",
          k.actor_id == b_aktor and k.ishonch == "aktor_elon", repr(k))

    k = A.aniqla(SoxtaRequest({}), b_cid)
    check("aktorsiz so'rov `kompaniya_sessiyasi` beradi",
          k.ishonch == "kompaniya_sessiyasi" and k.actor_id is None, repr(k))

    k = A.aniqla(SoxtaRequest({}, service=True), b_cid)
    check("service kaliti `servis` beradi (odam YO'Q)",
          k.ishonch == "servis" and k.actor_id is None, repr(k))

    bolim("8. RUXSAT matritsasi")
    kuz = _aktor(db, b_cid, "zzt_b_kuzatuvchi", "kuzatuvchi")
    kor = _aktor(db, b_cid, "zzt_b_koruvchi2", "koruvchi")

    def ruxsatmi(actor_id, amal):
        k = A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(actor_id)}), b_cid)
        try:
            A.ruxsat_tekshir(k, amal)
            return True
        except A.RuxsatXato:
            return False

    check("kuzatuvchi TASDIQLAY OLMAYDI", not ruxsatmi(kuz, "tasdiq"))
    check("kuzatuvchi KO'RIB CHIQA OLMAYDI", not ruxsatmi(kuz, "korib_chiq"))
    check("kuzatuvchi ko'ra oladi", ruxsatmi(kuz, "korish"))
    check("koruvchi ko'rib chiqa oladi", ruxsatmi(kor, "korib_chiq"))
    check("koruvchi TASDIQLAY OLMAYDI", not ruxsatmi(kor, "tasdiq"))
    check("koruvchi SOZLAMAGA tegmaydi", not ruxsatmi(kor, "sozlama"))
    b_admin = _aktor(db, b_cid, "zzt_b_admin", "admin")
    check("admin tasdiqlaydi", ruxsatmi(b_admin, "tasdiq"))
    check("admin sozlamaga tegadi", ruxsatmi(b_admin, "sozlama"))

    bolim("9. SERVICE kaliti inson qarorini qo'ya OLMAYDI")
    ks = A.aniqla(SoxtaRequest({}, service=True), b_cid)
    for amal in ("tasdiq", "rad", "korib_chiq", "sozlama"):
        try:
            A.ruxsat_tekshir(ks, amal)
            check(f"servis `{amal}` qila olmaydi", False, "ruxsat berildi")
        except A.RuxsatXato:
            check(f"servis `{amal}` qila olmaydi", True)

    bolim("10. `aktor_majburiy` — ijarachi bo'yicha yoqiladi")
    kk = A.aniqla(SoxtaRequest({}), b_cid)
    try:
        A.ruxsat_tekshir(kk, "tasdiq")
        check("majburiyat O'CHIQ: kompaniya sessiyasi yetadi", True)
    except A.RuxsatXato as e:
        check("majburiyat O'CHIQ: kompaniya sessiyasi yetadi", False, str(e))

    db.execute_returning(
        "UPDATE company_account SET aktor_majburiy=true WHERE id=%(i)s "
        "RETURNING id", {"i": b_cid})
    try:
        A.ruxsat_tekshir(A.aniqla(SoxtaRequest({}), b_cid), "tasdiq")
        check("majburiyat YOQIQ: aktorsiz qaror RAD ETILADI", False,
              "ruxsat berildi")
    except A.RuxsatXato as e:
        check("majburiyat YOQIQ: aktorsiz qaror RAD ETILADI", e.code == 403)
    ok = True
    try:
        A.ruxsat_tekshir(
            A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(b_admin)}), b_cid),
            "tasdiq")
    except A.RuxsatXato:
        ok = False
    check("majburiyat YOQIQ: aktor bilan qaror O'TADI", ok)
    db.execute_returning(
        "UPDATE company_account SET aktor_majburiy=false WHERE id=%(i)s "
        "RETURNING id", {"i": b_cid})

    bolim("11. Ko'rish ham ijarachi bilan cheklangan")
    check("B ijarachisi A ning aktorini O'QIY OLMAYDI",
          A.bitta(b_cid, a_aktor) is None)
    check("B ijarachisi o'z aktorini o'qiydi",
          (A.bitta(b_cid, b_aktor) or {}).get("id") == b_aktor)
    b_royxat = {a["id"] for a in A.royxat(b_cid)}
    check("ro'yxatda BOSHQA ijarachining aktori yo'q", a_aktor not in b_royxat)

    bolim("12. ERP moslik — O'LCHANMAGANI aytiladi")
    m = A.erp_moslikni_tekshir(b_cid)
    if A.erp_kontekst_ready():
        check("ERP shartnoma-view i bor — moslik o'lchandi",
              m["tekshirildi"] is True, str(m))
    else:
        check("ERP view i YO'Q -> `tekshirildi=False` (nol EMAS)",
              m["tekshirildi"] is False and m["yetim"] == [], str(m))

    with TestClient(app) as c:
        r = c.get("/aktor")
        check("/aktor tokensiz 401", r.status_code == 401, str(r.status_code))


# =====================================================================
# 13. ERP -> AKTOR KO'PRIGI (provisioning)
# =====================================================================
#
# O'LCHANGAN MUAMMO (2026-09-03): `erp.v_tai_actor` da UCH FAOL odam
# bor edi, `public.actor` da ijarachi 2 uchun NOL qator. Natijada
# `_erp_sessiyadan()` ning IKKINCHI sharti hech qachon bajarilmasdi va
# har inson qarori `kompaniya_sessiyasi` darajasida yozilardi.
#
# NEGA BU YERDA ERP SESSIYASI YARATILMAYDI: `auth_test.py` `erp.app_user`
# ga TEGILMAGANINI tekshiradi (qator soni va `max(updated_at)`).
# Sinov ERP sxemasiga yozsa o'sha tekshiruv yiqilardi va chegara
# shartnomasi buzilardi. Shuning uchun bu yerda XARITA qismi
# (ikkinchi shart) sinaladi; token mosligi (birinchi shart) uchun
# TIRIK ERP sessiyasi kerak va u sinovdan TASHQARIDA qoladi.
def test_erp_kopik(db, a_cid, b_cid, a_aktor):
    from api import aktor as A
    bolim("13. ERP -> aktor ko'prigi")

    # HOVUZNI QAYTA OCHAMIZ. 12-bo'lim `with TestClient(app)` ishlatadi
    # va undan CHIQISHDA lifespan `close_pool()` ni chaqiradi. Busiz bu
    # bo'lim `DBUnavailable: DB pool ishga tushmagan` bilan yiqilardi —
    # sinov mantig'i emas, tartib artefakti.
    db.init_pool()

    # --- 2) Yaroqsiz/xaritalanmagan ERP sessiyasi -> ANIQ xato -------
    # JIMGINA pastroq darajaga TUSHIRILMASLIGI shart: "isbot bor"
    # degan noto'g'ri taassurot qolmasin.
    try:
        A.aniqla(SoxtaRequest({A.ERP_SESSIYA_HEADER: "zzsinov-yaroqsiz-token"}),
                 a_cid)
        check("xaritalanmagan ERP sessiyasi RAD etiladi", False,
              "istisno chiqmadi")
    except A.RuxsatXato as e:
        check("xaritalanmagan ERP sessiyasi RAD etiladi",
              e.kod == "ACTOR_ERP_SESSION_INVALID", str(e.kod))
        check("jimgina `kompaniya_sessiyasi` ga TUSHIRILMAYDI", True,
              "403 qaytdi, daraja pasaytirilmadi")

    # --- 5) Soxta `x-actor` `erp_sessiya` ga KO'TARA OLMAYDI ---------
    k = A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(a_aktor)}), a_cid)
    check("`x-actor` eng ko'pi `aktor_elon` beradi",
          k.ishonch == "aktor_elon", k.ishonch)
    check("`x-actor` `erp_sessiya` ga KO'TARMAYDI",
          k.ishonch != "erp_sessiya", k.ishonch)

    # --- 3) Nofaol aktor -> rad --------------------------------------
    db.execute_returning("UPDATE actor SET active=false WHERE id=%(i)s "
                         "RETURNING id", {"i": a_aktor})
    try:
        A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(a_aktor)}), a_cid)
        check("nofaol aktor RAD etiladi", False, "istisno chiqmadi")
    except A.RuxsatXato as e:
        check("nofaol aktor RAD etiladi", e.kod == "ACTOR_INACTIVE", str(e.kod))
    db.execute_returning("UPDATE actor SET active=true WHERE id=%(i)s "
                         "RETURNING id", {"i": a_aktor})

    # --- 4) Boshqa ijarachining aktori -> rad (404, "bor" demaydi) ---
    try:
        A.aniqla(SoxtaRequest({A.AKTOR_HEADER: str(a_aktor)}), b_cid)
        check("begona ijarachining aktori RAD etiladi", False,
              "istisno chiqmadi")
    except A.RuxsatXato as e:
        check("begona ijarachining aktori RAD etiladi",
              e.kod == "ACTOR_NOT_FOUND", str(e.kod))

    # --- 6) Takroriy ERP xaritasi -> BAZA to'sadi --------------------
    ZZ_EUID = 999_000_001            # ERP da yo'q — ataylab

    def _erp_aktor(cid, login):
        """Bor bo'lsa QAYTA ISHLATADI.

        `_tozala()` aktorni O'CHIRMAYDI (audit `actor` ga FK bilan
        bog'langan), faqat `active=false` qiladi. Shuning uchun ikkinchi
        yurishda qator JOYIDA turadi va `qosh()` unikal indeksga
        urilardi — sinov mantig'i emas, qoldiq artefakti.
        """
        bor = db.query_one(
            "SELECT id FROM actor WHERE company_id=%(c)s AND erp_user_id=%(e)s",
            {"c": cid, "e": ZZ_EUID})
        if bor:
            _yaratilgan["actor"].append(int(bor["id"]))
            return bor
        r = A.qosh(cid, login=login, ism="ZZSINOV ERP", rol="koruvchi",
                   manba="erp", erp_user_id=ZZ_EUID)
        _yaratilgan["actor"].append(int(r["id"]))
        return r

    _erp_aktor(b_cid, "zzsinov_erp_1")
    try:
        r2 = A.qosh(b_cid, login="zzsinov_erp_2", ism="ZZSINOV ERP 2",
                    rol="koruvchi", manba="erp", erp_user_id=ZZ_EUID)
        _yaratilgan["actor"].append(int(r2["id"]))
        check("bitta `erp_user_id` IKKI marta xaritalanmaydi", False,
              "ikkinchi qator yozildi")
    except Exception as e:                                    # noqa: BLE001
        check("bitta `erp_user_id` IKKI marta xaritalanmaydi",
              "actor_erp_bir_marta" in str(e), str(e)[:90])

    # Bir xil `erp_user_id` BOSHQA ijarachida — RUXSAT (indeks
    # kompaniya bo'yicha). Ijarachilararo himoya bu yerda emas:
    # `company_id` SESSIYADAN olinadi, so'rov tanasidan emas.
    r3 = _erp_aktor(a_cid, "zzsinov_erp_1")
    check("indeks KOMPANIYA bo'yicha — boshqa ijarachida mumkin",
          db.query_one("SELECT company_id FROM actor WHERE id=%(i)s",
                       {"i": r3["id"]})["company_id"] == a_cid)

    # --- 7) Sinxronizatsiya IDEMPOTENT -------------------------------
    if not A.erp_kontekst_ready():
        check("ERP view i YO'Q -> sinxron `bajarildi=False` (nol EMAS)",
              A.erp_sinxron(b_cid)["bajarildi"] is False)
        return

    # XARITANI TOZALAYMIZ — aks holda sinov O'Z QOLDIG'INI sinaydi.
    #
    # `_tozala()` aktorni faqat `active=false` qiladi. Natijada IKKINCHI
    # yurishda sinxronizatsiya "yaratish" yo'liga umuman kirmasdi
    # (`yaratildi=0`) va "ikkinchi yurishda yangi aktor yaratilmaydi"
    # tekshiruvi BO'SH TO'PLAMDA o'tardi — ya'ni hech narsa isbotlamasdi.
    # Bu yerda ERP xaritasini haqiqatan olib tashlaymiz; audit yoki
    # qaror bilan bog'langan qator o'chmaydi va u holda o'tkazamiz.
    ochirilmagan = []
    for a in db.query("SELECT id FROM actor WHERE company_id=%(c)s "
                      "  AND erp_user_id IS NOT NULL", {"c": b_cid}):
        try:
            db.execute_returning("DELETE FROM actor WHERE id=%(i)s RETURNING id",
                                 {"i": a["id"]})
        except Exception:                                     # noqa: BLE001
            ochirilmagan.append(int(a["id"]))
    check("ERP xaritasi sinovdan OLDIN tozalandi (deterministik yurish)",
          not ochirilmagan,
          f"bog'langani uchun qolgan: {ochirilmagan}")

    quruq = A.erp_sinxron(b_cid, quruq=True)
    check("quruq yurish hech narsa yozmaydi",
          all(r["amal"] in ("yaratiladi", "nofaollashtiriladi", "otkazildi",
                            "ozgarmadi")
              for r in quruq["natija"]), str(quruq["xulosa"]))
    oldin = db.query_one("SELECT count(*) n FROM actor WHERE company_id=%(c)s",
                         {"c": b_cid})["n"]

    s1 = A.erp_sinxron(b_cid)
    for r in s1["natija"]:
        if r.get("actor_id"):
            _yaratilgan["actor"].append(int(r["actor_id"]))
    # BIRINCHI yurish HAQIQATAN yaratganini tasdiqlaymiz — busiz
    # "ikkinchi yurish yaratmadi" tekshiruvi ma'nosiz bo'lardi.
    check("birinchi yurish aktor YARATDI (yo'l haqiqatan yurildi)",
          s1["xulosa"].get("yaratildi", 0) > 0, str(s1["xulosa"]))
    s2 = A.erp_sinxron(b_cid)
    check("ikkinchi yurishda YANGI aktor yaratilmaydi",
          s2["xulosa"].get("yaratildi", 0) == 0, str(s2["xulosa"]))
    keyin = db.query_one("SELECT count(*) n FROM actor WHERE company_id=%(c)s",
                         {"c": b_cid})["n"]
    check("aktor soni ikkinchi yurishdan keyin O'ZGARMAYDI",
          keyin == oldin + s1["xulosa"].get("yaratildi", 0),
          f"{oldin} -> {keyin}, yaratildi={s1['xulosa'].get('yaratildi', 0)}")

    # --- NOFAOLLASHTIRISH yo'li MAJBURAN yurgiziladi ------------------
    #
    # NEGA MAJBURAN: sinxronizatsiya nofaol ERP odamiga aktor YARATMAYDI,
    # shuning uchun "nofaol -> faol aktor yo'q" tekshiruvi BO'SH
    # TO'PLAMDA o'tardi va hech narsa isbotlamasdi. Bu yerda avval
    # qo'lda FAOL aktor yaratamiz, keyin sinxronizatsiya uni
    # nofaollashtirishi SHART.
    nofaol_erp = db.query_one(
        "SELECT DISTINCT erp_user_id, login, ism FROM erp.v_tai_actor "
        " WHERE NOT faol LIMIT 1")
    if nofaol_erp is None:
        check("ERP da nofaol odam yo'q — nofaollashtirish YO'LI SINALMADI",
              False, "fikstura yetishmadi (ERP da hamma faol)")
    else:
        mavjud = db.query_one(
            "SELECT id FROM actor WHERE company_id=%(c)s AND erp_user_id=%(e)s",
            {"c": b_cid, "e": nofaol_erp["erp_user_id"]})
        if mavjud:
            aid = int(mavjud["id"])
            db.execute_returning("UPDATE actor SET active=true WHERE id=%(i)s "
                                 "RETURNING id", {"i": aid})
        else:
            row = A.qosh(b_cid, login="zzsinov_nofaol",
                         ism="ZZSINOV nofaol", rol="koruvchi", manba="erp",
                         erp_user_id=nofaol_erp["erp_user_id"])
            aid = int(row["id"])
        _yaratilgan["actor"].append(aid)
        check("fikstura: nofaol ERP odami FAOL aktor bo'lib turibdi",
              db.query_one("SELECT active FROM actor WHERE id=%(i)s",
                           {"i": aid})["active"] is True)

        s3 = A.erp_sinxron(b_cid)
        check("sinxronizatsiya uni NOFAOLLASHTIRDI",
              db.query_one("SELECT active FROM actor WHERE id=%(i)s",
                           {"i": aid})["active"] is False,
              str(s3["xulosa"]))
        # TESKARI YO'NALISH AVTOMATIK EMAS: qayta yurgizish uni
        # FAOLLASHTIRMAYDI (bu vakolat qaytarish bo'lardi).
        A.erp_sinxron(b_cid)
        check("qayta sinxronizatsiya uni FAOLLASHTIRMAYDI",
              db.query_one("SELECT active FROM actor WHERE id=%(i)s",
                           {"i": aid})["active"] is False)

    # --- NOMA'LUM ROL yo'li MAJBURAN yurgiziladi ----------------------
    #
    # Hamma ERP roli xaritada bo'lgani uchun bu tekshiruv ham BO'SH
    # to'plamda o'tardi. Xaritadan bitta rolni VAQTINCHA olib tashlaymiz.
    erp_rollar = [r["rol"] for r in db.query(
        "SELECT DISTINCT rol FROM erp.v_tai_actor WHERE faol")]
    sinov_rol = next((r for r in erp_rollar if r in A.ROL_XARITASI), None)
    if sinov_rol is None:
        check("ERP da faol, xaritalangan rol yo'q — NOMA'LUM ROL SINALMADI",
              False, "fikstura yetishmadi")
    else:
        asl = dict(A.ROL_XARITASI)
        try:
            A.ROL_XARITASI.pop(sinov_rol)
            s4 = A.erp_sinxron(b_cid, quruq=True)
            tegishli = [r for r in s4["natija"] if r["erp_rol"] == sinov_rol]
            check(f"noma'lum ERP roli ({sinov_rol!r}) XARITALANMAYDI",
                  bool(tegishli) and all(r["amal"] == "otkazildi"
                                         for r in tegishli),
                  str([(r["login"], r["amal"]) for r in tegishli][:3]))
            check("sabab AYTILADI (jimgina o'tkazilmaydi)",
                  all("xaritalanmagan" in (r["sabab"] or "")
                      for r in tegishli),
                  str([r["sabab"] for r in tegishli][:1]))
            check("jimgina eng past vakolatga TUSHIRILMAYDI",
                  all(r["tai_rol"] is None for r in tegishli))
        finally:
            A.ROL_XARITASI.clear()
            A.ROL_XARITASI.update(asl)

    # SIR SIZMAYDI: javobda token bo'lmasin.
    matn = str(A.erp_nomzodlar(b_cid))
    check("javobda `token_hash` YO'Q",
          "token_hash" not in matn and "expires_at" not in matn)


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Aktor kimligi sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: AKTOR KIMLIGI, RUXSAT VA AUDIT")
    print("=" * 70)

    test_manba()
    try:
        test_lugat_mosligi()
        test_mijoz_aktor_yubormaydi()
    except Exception as e:                                    # noqa: BLE001
        check("statik sinovlar", False, str(e)[:100])

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Bazali sinovlar o'tkazib yuborildi "
              f"({'--offline' if args.bazasiz else 'XT_DB_DSN yo`q'}).")
    else:
        db = _db()
        from api import aktor
        if not aktor.ready():
            check("schema_patch_aktor.sql qo'llangan", False,
                  "bazali sinovlar o'tkazib yuborildi")
        else:
            try:
                a_cid, b_cid, a_a, b_a = test_baza_qulflari(db)
                test_izchillik(db, a_cid, a_a)
                test_audit_tuzatish(db)
                test_api(db, a_cid, b_cid, a_a, b_a)
                test_erp_kopik(db, a_cid, b_cid, a_a)
            finally:
                _tozala(db)

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
