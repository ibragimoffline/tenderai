#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: INSON TASDIG'I — DALIL BILAN, YORLIQ BILAN EMAS
=======================================================

O'LCHANGAN NUQSON (2026-09-02)
------------------------------
Tayyorlik auditi "inson halqasi kod tasdig'ida 73.4% to'lgan" deb
ko'rsatardi. Raqam `catalog_product_code.tasdiqlandi` dan kelardi.
Tekshirilganda:

    tasdiqlagan     qator   turli sekund   tezlik
    kompaniya         581              2   ~290 qator/sek
    tizim:auto        467             14    ~34 qator/sek

1 048 ta "tasdiq" atigi 16 ta turli sekundda yozilgan va
`tasdiqlagan` da atigi ikki qiymat bor — ikkalasi ham odam nomi
emas. Hammasida `qaror_id IS NULL`, ya'ni hech biri inson qaroriga
bog'lanmagan. `kod_qaror` jadvalida esa 0 ta qator.

Ya'ni MASHINA CHIQISHI INSON TASDIG'I sifatida sanalgan.

SABAB: yagona qo'riqchi `tasdiqlagan` ustuni bo'sh bo'lmasligini
tekshirardi. "Bo'sh bo'lmagan satr" ODAM DEGANI EMAS.

BU SINOV NIMANI HIMOYA QILADI
-----------------------------
  1. Mashina chiqishi inson tasdig'i bo'lib sanalmasin.
  2. Inson qarorida AKTOR va VAQT bo'lsin (baza majburlasin).
  3. Ko'ruvchi shubhasini ayta olsin (`uncertain`) — aks holda
     shubha "tasdiq" bo'lib yozilardi.
  4. Tarix o'chmasin (audit append-only).
  5. Kichik namunadan FOIZ uydirilmasin.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\inson_dalil_test.py
    .venv\\Scripts\\python.exe _tests\\inson_dalil_test.py --bazasiz
"""
from __future__ import annotations

import argparse
import io
import os
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

#: Sinov hisobi — `zz` prefiksi tozalashda adashmaslik uchun.
LOGIN = "zzdalil_a"
PAROL = "zzSinovDalil12345"

#: Mashina ishonchi — bular INSON EMAS.
MASHINA = ("servis", "kuzatuvdan_oldin")
#: Aktorli inson ishonchi — KIM ekani ma'lum.
AKTORLI = ("erp_sessiya", "aktor_elon")


def check(nom, ok, tafsilot=""):
    _natija.append((nom, bool(ok), tafsilot))
    belgi = "OK  " if ok else "XATO"
    print(f"  [{belgi}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))


def bolim(t):
    print(f"\n--- {t} ---")


def oqi(*p):
    return io.open(os.path.join(ROOT, *p), encoding="utf-8").read()


# =====================================================================
# 1. PHASE 1 — MASHINA HOLATI VA INSON HOLATI AJRALGANMI
# =====================================================================
def test_ajratish(db):
    bolim("1. MASHINA holati va INSON holati AJRALGAN")

    ust = {r["table_name"] + "." + r["column_name"]
           for r in db.query(
               "SELECT table_name, column_name FROM information_schema.columns "
               "WHERE table_schema='public'")}

    # Har uch qatlamda mashina qiymati va inson qarori ALOHIDA
    # ustunlarda tursin. Bitta ustunda bo'lsa "kim qaror qildi"
    # savoli tuzilma darajasida javobsiz bo'lardi.
    for jadval, mashina, inson in (
            ("tender_requirement", "mashina_holat", "review_status"),
            ("tender_routing", "ai_qaror", "inson_qaror"),
            ("catalog_product_code", "manba", "tasdiq_ishonch")):
        check(f"`{jadval}`: mashina va inson ustunlari ALOHIDA",
              f"{jadval}.{mashina}" in ust and f"{jadval}.{inson}" in ust)

    # Aktor va vaqt — har qatlamda.
    for jadval, aktor, vaqt in (
            ("tender_requirement", "reviewed_actor_id", "reviewed_at"),
            ("tender_routing", "qaror_actor_id", "qaror_vaqti"),
            ("catalog_product_code", "tasdiq_actor_id", "tasdiqlandi")):
        check(f"`{jadval}`: aktor va vaqt ustunlari bor",
              f"{jadval}.{aktor}" in ust and f"{jadval}.{vaqt}" in ust)


def test_cheklovlar(db):
    bolim("2. BAZA CHEKLOVLARI — mashina inson bo'lib yoza olmasin")

    defs = {}
    for r in db.query("""SELECT rel.relname t, con.conname nom,
                                pg_get_constraintdef(con.oid) def
                           FROM pg_constraint con
                           JOIN pg_class rel ON rel.oid=con.conrelid
                           JOIN pg_namespace n ON n.oid=rel.relnamespace
                          WHERE n.nspname='public'"""):
        defs[r["nom"]] = (r["t"], r["def"])

    # --- Tasdiq MANBASIZ yozilmasin ---
    check("`catalog_product_code` tasdiq MANBASI majburiy",
          "catalog_product_code_tasdiq_manba_chk" in defs)
    check("`catalog_product_code` aktor izchilligi bor",
          "catalog_product_code_aktor_izchil_chk" in defs)
    # IJARACHI: A kompaniya B ning aktorini ko'rsata olmasin.
    fk = defs.get("catalog_product_code_tasdiq_actor_fk", ("", ""))[1]
    check("tasdiq aktori KOMPOZIT FK bilan (ijarachi ajratilishi)",
          "company_id, tasdiq_actor_id" in fk and "actor" in fk, fk[:110])

    # --- Yo'naltirishda VAQT majburiy ---
    rt = defs.get("tender_routing_inson_vaqt_chk", ("", ""))[1]
    check("`tender_routing` inson qarorida VAQT majburiy",
          "qaror_vaqti IS NOT NULL" in rt, rt[:110])

    # --- `uncertain` ham to'liq inson qarori ---
    tr = defs.get("tender_requirement_inson_qarori_chk", ("", ""))[1]
    check("`uncertain` ham aktor+vaqt+amal talab qiladi",
          "uncertain" in tr and "reviewed_at IS NOT NULL" in tr, tr[:130])
    amal = defs.get("tender_requirement_amal_chk", ("", ""))[1]
    check("`uncertain` amali holatga MOS bo'lishi shart",
          "uncertain" in amal, amal[:130])

    # --- Audit O'ZGARMAS ---
    trig = {r["tgname"] for r in db.query(
        "SELECT tg.tgname FROM pg_trigger tg JOIN pg_class c ON c.oid=tg.tgrelid "
        "WHERE NOT tg.tgisinternal AND c.relname='audit_jurnal'")}
    check("`audit_jurnal` O'ZGARMAS (trigger)",
          any("ozgarmas" in t for t in trig), str(sorted(trig)))


def test_qorovul_haqiqatan(db):
    """Cheklov MAVJUDLIGI yetarli emas — u ISHLASHI kerak."""
    bolim("3. QO'RIQCHILAR HAQIQATAN RAD ETADIMI")

    hedef = db.query_one(
        "SELECT product_id, company_id, code FROM catalog_product_code "
        "WHERE tasdiqlandi IS NULL AND rad_etildi IS NULL LIMIT 1")
    if not hedef:
        check("sinov uchun navbatdagi qator bor", False,
              "hamma qator allaqachon qaror qilingan")
        return

    W = (" WHERE product_id=%(p)s AND code=%(c)s AND company_id=%(k)s"
         " RETURNING product_id")
    par = {"p": hedef["product_id"], "c": hedef["code"],
           "k": hedef["company_id"]}

    def urin(sql):
        try:
            db.execute_returning(sql + W, par)
            return None
        except Exception as e:                               # noqa: BLE001
            return str(e)

    B = "UPDATE catalog_product_code SET tasdiqlandi=now(), tasdiqlagan='tizim:auto'"
    try:
        x = urin(B)
        check("MANBASIZ tasdiq RAD ETILDI",
              x is not None and "tasdiq_manba_chk" in x, (x or "YOZILDI!")[:90])

        x = urin(B + ", tasdiq_ishonch='aktor_elon'")
        check("AKTORSIZ inson tasdig'i RAD ETILDI",
              x is not None and "aktor_izchil" in x, (x or "YOZILDI!")[:90])

        x = urin(B + ", tasdiq_ishonch='aktor_elon', tasdiq_actor_id=999999999")
        check("BEGONA aktor RAD ETILDI (ijarachi ajratilishi)",
              x is not None, (x or "YOZILDI!")[:90])

        # Avtomatika YOZA OLADI, lekin `servis` deb BELGILANADI —
        # taqiq emas, OSHKORALIK. U inson ulushiga kirmaydi.
        x = urin(B + ", tasdiq_ishonch='servis'")
        check("MASHINA yoza oladi, lekin `servis` deb belgilanadi",
              x is None, (x or "")[:90])
        n = db.scalar(
            "SELECT count(*) FROM v_inson_dalil d WHERE d.qatlam='kod_tasdigi'"
            " AND d.company_id=%(k)s AND d.aktorli > 0", {"k": hedef["company_id"]})
        check("`servis` tasdig'i INSON ulushiga KIRMADI", (n or 0) == 0)
    finally:
        # SINOV MA'LUMOTNI QAYTARADI. Aks holda keyingi yurish
        # boshqa holatdan boshlanardi va natija takrorlanmasdi.
        db.execute_returning(
            "UPDATE catalog_product_code SET tasdiqlandi=NULL, "
            "tasdiqlagan=NULL, tasdiq_ishonch=NULL, tasdiq_actor_id=NULL" + W,
            par)


# =====================================================================
# 4. PHASE 2 — KO'RIB CHIQISH OQIMI
# =====================================================================
def test_oqim():
    bolim("4. KO'RUVCHI QILA OLADIGAN AMALLAR")

    req = oqi("api", "requirement.py")
    check("talab: tasdiqlash/rad/tuzatish/shubha — TO'RTALASI",
          all(a in req for a in ('"approved"', '"rejected"',
                                 '"corrected"', '"uncertain"')))
    # `uncertain` KO'RILMAGAN DEGANI EMAS — u inson qarori.
    check("`uncertain` INSON_QARORLARI ichida", "INSON_QARORLARI" in req
          and "uncertain" in req[req.index("INSON_QARORLARI"):
                                 req.index("INSON_QARORLARI") + 400])
    # Amal moslik lug'ati BITTA joyda bo'lsin.
    check("holat->amal mosligi BITTA manbadan (SQL da CASE yo'q)",
          "review_action   = %(amal)s" in req
          and "WHEN 'corrected' THEN 'correct'" not in req)

    main = oqi("api", "main.py")
    check("API `uncertain` ni qabul qiladi",
          '"corrected", "uncertain"' in main)

    kod = oqi("api", "kodlash.py")
    check("kod tasdig'ida `ishonch` MAJBURIY (standart qiymat yo'q)",
          "*, \n" not in kod and "ishonch: str," in kod)
    check("rad etish ham `ishonch` talab qiladi",
          "def rad_et" in kod
          and "ishonch: str" in kod[kod.index("def rad_et"):
                                    kod.index("def rad_et") + 700])
    # Izoh/dalil va muqobil qidirish yo'llari.
    check("kod qarorida IZOH maydoni bor", "izoh" in kod)
    check("muqobil kod QIDIRISH yo'li bor", "/kod/qidir" in main)
    check("rad etilgan takliflar SAQLANADI", "rad_takliflar" in kod)


# =====================================================================
# 5. PHASE 3 — AUDIT
# =====================================================================
def test_audit(db):
    bolim("5. AUDIT — har inson qarori iz qoldiradi")

    ust = {r["column_name"] for r in db.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='audit_jurnal'")}
    # Phase 3 ro'yxati.
    for nom, u in (("ijarachi", "company_id"), ("aktor", "actor_id"),
                   ("ishonch darajasi", "ishonch"), ("amal", "amal"),
                   ("obyekt", "entity"), ("obyekt id", "entity_id"),
                   ("eski qiymat", "oldin"), ("yangi qiymat", "keyin"),
                   ("dalil/izoh", "izoh"), ("vaqt", "at")):
        check(f"audit: {nom} yoziladi", u in ust)

    main = oqi("api", "main.py")
    # HAR uch qatlam audit yozsin — biri unutilsa o'sha qatlamda
    # tarix bo'lmasdi.
    for amal in ('amal=f"talab_{body.status}"', 'amal=f"yonaltirish_',
                 'amal=f"kod_{body.qaror}"', 'amal="kod_tasdiq"',
                 'amal="kod_rad"'):
        check(f"audit yoziladi: {amal[:34]}", amal in main)

    # O'ZGARMASLIK — HAQIQATAN sinaladi, trigger MAVJUDLIGI emas.
    r = db.query_one("SELECT id FROM audit_jurnal ORDER BY id DESC LIMIT 1")
    if r:
        xato = None
        try:
            db.execute_returning(
                "UPDATE audit_jurnal SET izoh='buzildi' WHERE id=%(i)s "
                "RETURNING id", {"i": r["id"]})
        except Exception as e:                               # noqa: BLE001
            xato = str(e)
        check("audit yozuvini O'ZGARTIRIB BO'LMAYDI",
              xato is not None, (xato or "O'ZGARTIRILDI!")[:90])
    else:
        check("audit yozuvini O'ZGARTIRIB BO'LMAYDI", False,
              "audit bo'sh — sinab bo'lmadi")


# =====================================================================
# 6. PHASE 5 — METRIKALAR
# =====================================================================
def test_metrikalar(db):
    bolim("6. METRIKALAR — hisoblanadimi")

    mavjud = {r["table_name"] for r in db.query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='VIEW'")}
    for v in ("v_inson_dalil", "v_sifat_darvoza", "v_kod_qaror_olchov",
              "v_routing_kelishuv", "v_review_disagreement",
              "v_requirement_review"):
        check(f"ko'rinish `{v}` mavjud", v in mavjud)

    # KODLASH metrikalari.
    kq = db.query_one("SELECT pg_get_viewdef('v_kod_qaror_olchov'::regclass,true) d")["d"]
    for nom, ust in (("ko'rilgan soni", "qaror_soni"),
                     ("mashina-inson kelishuvi", "taklif_qabul"),
                     ("o'zgartirilgan ulushi", "taklif_ozgartirildi"),
                     ("dalilsiz/noaniq", "dalilsiz")):
        check(f"kodlash metrikasi: {nom}", ust in kq)

    # YO'NALTIRISH — to'liq 2x2 matritsa.
    rk = db.query_one("SELECT pg_get_viewdef('v_routing_kelishuv'::regclass,true) d")["d"]
    for ust in ("go_olindi", "go_rad", "nogo_olindi", "nogo_rad",
                "go_kutilsin"):
        check(f"yo'naltirish matritsasi: {ust}", ust in rk)

    # HAR ko'rinish HAQIQATAN yuradi (sintaksis emas, IJRO).
    for v in ("v_inson_dalil", "v_sifat_darvoza", "v_kod_qaror_olchov",
              "v_routing_kelishuv"):
        try:
            db.query(f"SELECT * FROM {v} LIMIT 1")
            check(f"`{v}` HAQIQATAN yuradi", True)
        except Exception as e:                               # noqa: BLE001
            check(f"`{v}` HAQIQATAN yuradi", False, str(e)[:90])


# =====================================================================
# 7. PHASE 6 — SIFAT DARVOZASI
# =====================================================================
def test_darvoza(db):
    bolim("7. SIFAT DARVOZASI — kichik namunadan foiz uydirilmasin")

    qatorlar = db.query("SELECT * FROM v_sifat_darvoza")
    check("darvoza uch qatlamni ham qamraydi",
          {r["qatlam"] for r in qatorlar} >= {"kod_tasdigi", "talab_korigi",
                                              "yonaltirish"},
          str(sorted({r["qatlam"] for r in qatorlar})))

    for r in qatorlar:
        # ENG MUHIM QOIDA: chegaradan o'tmagan qatlam FOIZ BERMASIN.
        # 3 ta qarordan "67% aniqlik" chiqarish yolg'on bo'lardi.
        if r["holat"] != "INSON_TASDIQLADI":
            check(f"{r['qatlam']}: chegaradan o'tmagan -> FOIZ YO'Q",
                  r["ulush_foiz"] is None,
                  f"holat={r['holat']} foiz={r['ulush_foiz']}")
        check(f"{r['qatlam']}: holat yorlig'i to'g'ri",
              r["holat"] in ("INSON_TASDIQLADI", "YETARLI_EMAS",
                             "TASDIQLANMAGAN"), str(r["holat"]))
        # Mashina qatorlari aktorli ulushga KIRMASIN.
        check(f"{r['qatlam']}: mashina va aktorli ALOHIDA sanaladi",
              r["mashina"] is not None and r["aktorli"] is not None)

    # HISOBLAGICH HALOL: eski `v_inson_halqasi` 1 048 mashina
    # qatorini inson deb sanardi.
    kod = db.query_one(
        "SELECT * FROM v_inson_halqasi WHERE qatlam='kod_tasdigi' "
        "ORDER BY jami DESC LIMIT 1")
    if kod:
        check("`v_inson_halqasi` mashina qatorini INSON deb sanamaydi",
              int(kod["inson_qarori"] or 0) == 0 or int(kod["mashina"] or 0) == 0,
              f"inson={kod['inson_qarori']} mashina={kod['mashina']}")


# =====================================================================
# 8. HAQIQIY OQIM — ilova orqali to'liq inson qarori
# =====================================================================
def test_uchidan_uchiga(db):
    """Inson qarorini ILOVA ORQALI to'liq kiritish MUMKINMI.

    Bu sinovsiz "ko'rib chiqish ishlaydi" degan da'vo tekshirilmagan
    bo'lardi: sxema to'g'ri, lekin endpoint yiqilishi mumkin.

    SINOV IJARACHISI ALOHIDA: haqiqiy kompaniyaning pilot raqamiga
    sinov qarorlari QO'SHILMASIN.
    """
    bolim("8. HAQIQIY OQIM — ilova orqali (sinov ijarachisi)")

    from fastapi.testclient import TestClient

    from api import auth as A
    from api.main import app

    r = db.query_one(A.ACC_BY_NAME_SQL, {"username": LOGIN})
    if r:
        db.execute_returning("UPDATE company_account SET active=TRUE "
                             "WHERE id=%(id)s RETURNING id", {"id": r["id"]})
        A.set_password(r["id"], PAROL)
        cid = int(r["id"])
    else:
        cid = int(A.create_account(LOGIN, "SINOV dalil", PAROL)["id"])

    token = A.login(LOGIN, PAROL)["token"]
    H = {"Authorization": f"Bearer {token}"}

    try:
        with TestClient(app) as c:
            # --- Qaror OCHILADI (vaqt o'lchovi shu yerdan boshlanadi) ---
            r = c.post("/kod/qaror/ochish", headers=H,
                       json={"kalit": "zzsinov_atama", "atama": "ZZ sinov atamasi"})
            check("qaror ochish -> 2xx", r.status_code < 300,
                  f"{r.status_code}: {str(r.text)[:110]}")

            # --- Inson QARORI yoziladi ---
            r = c.post("/kod/qaror", headers=H,
                       json={"kalit": "zzsinov_atama", "atama": "ZZ sinov atamasi",
                             "qaror": "dalilsiz", "manba": "qolda",
                             "izoh": "sinov: dalil yetarli emas"})
            check("inson qarori yozildi -> 2xx", r.status_code < 300,
                  f"{r.status_code}: {str(r.text)[:110]}")

            if r.status_code < 300:
                row = db.query_one(
                    "SELECT qaror, kim, qaror_at, actor_id, ishonch, izoh "
                    "FROM kod_qaror WHERE company_id=%(c)s "
                    "ORDER BY id DESC LIMIT 1", {"c": cid})
                check("qarorda VAQT bor", row and row["qaror_at"] is not None)
                check("qarorda KIM bor", row and bool(row["kim"]))
                check("qarorda ISHONCH darajasi bor",
                      row and row["ishonch"] is not None, str(row and row["ishonch"]))
                check("izoh (dalil) saqlandi", row and bool(row["izoh"]))
                # AUDIT izi HAQIQATAN yozildimi.
                n = db.scalar(
                    "SELECT count(*) FROM audit_jurnal WHERE company_id=%(c)s "
                    "AND entity='kod_qaror'", {"c": cid})
                check("audit izi yozildi", (n or 0) > 0, f"{n} yozuv")

            # --- AKTORLI QAROR — darvoza AYNAN shuni sanaydi ---
            # Bu yo'l sinalmasa "halqa tayyor" degan da'vo tekshirilmagan
            # bo'lardi: anonim qaror ishlashi darvozani QONDIRMAYDI.
            r = c.post("/aktor", headers=H,
                       json={"login": "zzkoruvchi", "ism": "ZZ Ko'ruvchi",
                             "rol": "tasdiqlovchi", "manba": "mahalliy"})
            aktor_id = None
            if r.status_code < 300:
                aktor_id = (r.json() or {}).get("id")
            else:
                # TAKRORIY YURISH: aktor oldingi yurishdan qolgan va
                # u FAOLSIZ — tozalash uni shunday qoldiradi, chunki
                # `audit_jurnal` FK si o'chirishga yo'l bermaydi.
                # Faolsiz aktor bilan qaror qo'yib bo'lmaydi
                # (`ACTOR_INACTIVE`), ya'ni qayta faollashtirish
                # SHART. Bu ham API orqali — `PATCH /aktor/{id}`
                # yo'li aynan shu yerda sinaladi.
                mavjud = db.query_one(
                    "SELECT id FROM actor WHERE company_id=%(c)s "
                    "AND login='zzkoruvchi'", {"c": cid})
                aktor_id = mavjud and mavjud["id"]
                if aktor_id:
                    rp = c.patch(f"/aktor/{aktor_id}", headers=H,
                                 json={"active": True})
                    check("faolsiz aktor API orqali QAYTA FAOLLASHTIRILDI",
                          rp.status_code < 300,
                          f"{rp.status_code}: {str(rp.text)[:100]}")
            check("aktor API orqali qo'shildi (SQL kerak emas)",
                  aktor_id is not None, f"{r.status_code}: {str(r.text)[:100]}")

            if aktor_id:
                HA = dict(H)
                HA["X-Actor"] = str(aktor_id)
                c.post("/kod/qaror/ochish", headers=HA,
                       json={"kalit": "zzaktor_atama", "atama": "ZZ aktor atamasi"})
                r = c.post("/kod/qaror", headers=HA,
                           json={"kalit": "zzaktor_atama",
                                 "atama": "ZZ aktor atamasi",
                                 "qaror": "talabsiz", "manba": "qolda",
                                 "izoh": "sinov: aktorli qaror"})
                check("AKTORLI qaror yozildi -> 2xx", r.status_code < 300,
                      f"{r.status_code}: {str(r.text)[:110]}")
                row = db.query_one(
                    "SELECT actor_id, ishonch FROM kod_qaror "
                    "WHERE company_id=%(c)s AND kalit='zzaktor_atama' "
                    "ORDER BY id DESC LIMIT 1", {"c": cid})
                check("qaror AKTORGA bog'landi",
                      row and row["actor_id"] == aktor_id,
                      str(row and dict(row)))
                check("ishonch darajasi AKTORLI",
                      row and row["ishonch"] in AKTORLI,
                      str(row and row["ishonch"]))

            # --- SERVICE kaliti odam emas: qaror qo'ya olmasin ---
            r = c.post("/kod/qaror",
                       json={"kalit": "zzsinov_atama2", "atama": "ZZ 2",
                             "qaror": "dalilsiz", "manba": "qolda"})
            check("kimliksiz so'rov qaror QO'YA OLMAYDI",
                  r.status_code in (401, 403), str(r.status_code))

    finally:
        # --- TOZALASH: sinov ijarachisining izlari qolmasin ---
        # `TestClient` kontekstidan chiqishda `shutdown` hodisasi baza
        # hovuzini YOPADI — tozalash uchun uni qayta ochish SHART.
        db.init_pool()
        db.execute_returning(
            "DELETE FROM kod_qaror WHERE company_id=%(c)s RETURNING id", {"c": cid})
        # AKTOR O'CHIRILMAYDI: `audit_jurnal` unga FK bilan bog'langan va
        # o'chirish tarixni buzardi (`audit_jurnal_aktor_fk` shuni
        # to'xtatadi — bu qo'riqchi TO'G'RI ishlayapti). Faol emas deb
        # belgilanadi.
        db.execute_returning(
            "UPDATE actor SET active=FALSE WHERE company_id=%(c)s "
            "AND login='zzkoruvchi' RETURNING id", {"c": cid})
        # HISOB FAOL QOLMASIN: boshqa to'plamlar "faqat bitta faol
        # kompaniya" shartini tekshiradi va faol sinov hisobi ularni
        # yiqitardi.
        db.execute_returning(
            "UPDATE company_account SET active=FALSE WHERE id=%(c)s "
            "RETURNING id", {"c": cid})


# =====================================================================
# 9. HUJJAT
# =====================================================================
def test_hujjat():
    bolim("9. Hujjat")
    p = os.path.join(ROOT, "docs", "inson_dalil.md")
    if not os.path.exists(p):
        check("`docs/inson_dalil.md` mavjud", False)
        return
    d = oqi("docs", "inson_dalil.md")
    check("`docs/inson_dalil.md` mavjud", True)
    for nom, naqsh in (("o'lchangan nuqson", "1 048"),
                       ("mashina/inson farqi", "tizim:auto"),
                       ("sifat darvozasi", "INSON_TASDIQLADI"),
                       ("eng kam namuna", "eng kam"),
                       ("pilotni ishga tushirish", "pilot")):
        check(f"hujjatda `{nom}` bor", naqsh in d)


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Inson tasdig'i sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: INSON TASDIG'I — DALIL BILAN")
    print("=" * 70)

    test_oqim()
    test_hujjat()

    bazasiz = getattr(args, "bazasiz", False)
    if bazasiz:
        print("\n  [i] --bazasiz: baza tekshiruvlari O'TKAZILMADI.")
        print("      Bu SINOV EMAS — qamrov kamaydi.")
    else:
        from api import db
        db.init_pool()
        test_ajratish(db)
        test_cheklovlar(db)
        test_qorovul_haqiqatan(db)
        test_audit(db)
        test_metrikalar(db)
        test_darvoza(db)
        test_uchidan_uchiga(db)

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
