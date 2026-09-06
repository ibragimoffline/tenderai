#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: ERP GA TOPSHIRIQ (yo'naltirish oqimi, HTTP'siz)
======================================================

NIMA TEKSHIRILADI VA NEGA

  1. CHEGARA. `api/topshiriq.py` `erp.*` ga YOZMAYDI va umuman
     tegmaydi. Bu ikki loyihaning asosiy shartnomasi
     (`docs/erp_kimlik.md`, ERP `erp_arxitektura_2.md`): har tomon
     o'z jadvaliga yozadi, qarshi tomon VIEW dan o'qiydi.

  2. IJARACHI IZOLYATSIYASI. Boshqa ijarachining aktorini topshiriqqa
     yozib bo'lmaydi — kompozit FK BAZADA to'sadi. HAQIQIY qatorlar
     bilan sinaladi: bo'sh to'plamdagi "rad etildi" yolg'on PASS
     bo'lardi.

  3. TAHLIL — SNAPSHOT VA CHIDAMLI. Bir bo'lim yiqilsa qolganlari
     yoziladi va sabab KO'RINADI (jimgina tashlab ketilmaydi).
     Hajm chegarasi ham tekshiriladi.

  4. TAKRORLANMAYDI. Bitta qarordan bitta topshiriq
     (`UNIQUE (routing_id)`); qayta yozilsa YANGILANADI va bekor
     bo'lsa TIRILADI.

  5. XABAR. `pg_notify('erp_topshiriq', id)` haqiqatan yuboriladi —
     ERP kutib o'tirmasin. LISTEN bilan o'lchanadi.

  6. VIEW SHAKLI. ERP aynan shu ustunlarni o'qiydi
     (`erp: api/erp/topshiriq.py`). Ustun nomi o'zgarsa ERP jimgina
     buziladi, shuning uchun shakl shu yerda QULFLANGAN.

XAVFSIZLIK. Sinov O'Z ijarachisini yaratadi (`zztest_topshiriq_`) va
faqat O'ZI yaratgan id larni tozalaydi. Haqiqiy ijarachining
qatorlariga TEGMAYDI — ERP tomonidagi tinglovchi sinov topshirig'ini
karta qilib ochib yubormasligi uchun ham (ERP faqat sozlangan
`tai_company_id` ni qabul qiladi).

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\topshiriq_test.py
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []
_yaratilgan = {"company": [], "actor": [], "routing": [], "topshiriq": []}

PREFIX = "zztest_topshiriq"


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
# 1. MANBA — chegara va shartnoma kodda
# =====================================================================
def test_manba():
    bolim("1. Manba — chegara qoidasi va migratsiya")
    kod = io.open(os.path.join(ROOT, "api", "topshiriq.py"),
                  encoding="utf-8").read()
    # Izohlarda "erp" so'zi BOR (nega yozilmasligi tushuntirilgan),
    # shuning uchun IZOHSIZ matn tekshiriladi.
    sof = "\n".join(q for q in kod.split("\n")
                    if not q.strip().startswith("#"))
    for yomon in ("erp.opportunity", "INSERT INTO erp", "UPDATE erp",
                  "DELETE FROM erp"):
        check(f"`{yomon}` YO'Q — ERP jadvaliga yozilmaydi", yomon not in sof)

    sql = io.open(os.path.join(ROOT, "schema_patch_topshiriq.sql"),
                  encoding="utf-8").read()
    for nom, naqsh in (
            ("kompozit FK — hodim", "REFERENCES actor (company_id, id)"),
            ("bitta qarordan bitta topshiriq", "UNIQUE (routing_id)"),
            ("tahlil JSONB", "tahlil         JSONB"),
            ("shartnoma-view", "CREATE OR REPLACE VIEW v_erp_topshiriq"),
            ("xabar triggeri", "erp_topshiriq_xabar_trg"),
            ("pg_notify kanali", "pg_notify('erp_topshiriq'")):
        check(nom, naqsh in sql)


# =====================================================================
# 2. VIEW SHAKLI — ERP shunga bog'lanadi
# =====================================================================
VIEW_USTUNLARI = ["id", "company_id", "routing_id", "tender_id",
                  "hodim_app_user_id", "hodim_ism", "yonaltirgan_app_user_id",
                  "yonaltirgan_ism", "ishonch", "ustuvorlik", "izoh",
                  "muddat", "tahlil", "yaratilgan_at", "bekor_at"]


def test_view(db):
    bolim("2. View shakli — ERP aynan shularni o'qiydi")
    cols = [r["column_name"] for r in db.query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'v_erp_topshiriq' ORDER BY ordinal_position")]
    check("ustunlar va TARTIB shartnomadagidek", cols == VIEW_USTUNLARI,
          f"{cols}")


# =====================================================================
# 3. TAHLIL — chidamli va chegaralangan
# =====================================================================
def test_tahlil(db):
    bolim("3. Tahlil snapshoti")
    from api import topshiriq

    r = db.query_one("SELECT id, company_id, tender_id, ai_qaror, ai_ball, "
                     "ai_manba, ai_sabab FROM tender_routing ORDER BY id LIMIT 1")
    if not r:
        check("tahlil uchun yo'naltirish kerak", False, "tender_routing bo'sh")
        return
    t = topshiriq.tahlil_yig(r["tender_id"], r["company_id"], r)
    for bolim_nomi in topshiriq.BOLIMLAR_TARTIBI:
        b = t.get(bolim_nomi)
        check(f"`{bolim_nomi}` bo'limi bor va holati aytilgan",
              isinstance(b, dict) and "ok" in b)
    check("moslik qaror paytidagi balldan olinadi",
          t["moslik"]["ok"] and t["moslik"]["data"]["ball"] == float(r["ai_ball"] or 0))

    # YIQILGAN BO'LIM — sabab bilan, jimgina emas.
    def _yiqil():
        raise RuntimeError("sinov: ataylab yiqildi")
    q = topshiriq._qism("sinov", _yiqil)
    check("yiqilgan bo'lim sababi bilan yoziladi",
          q["ok"] is False and "sinov: ataylab" in q["xato"])

    # HAJM CHEGARASI — og'ir bo'lim tashlanadi, sababi qoladi.
    katta = {b: {"ok": True, "data": {"x": "y" * 20000}}
             for b in topshiriq.BOLIMLAR_TARTIBI}
    kesilgan = topshiriq._sigdir(dict(katta))
    hajm = len(json.dumps(kesilgan, default=str).encode("utf-8"))
    check("hajm chegarasi ishlaydi", hajm <= topshiriq.MAX_BAYT, f"{hajm} bayt")
    tashlangan = [b for b in topshiriq.BOLIMLAR_TARTIBI
                  if not kesilgan[b]["ok"]]
    check("tashlangan bo'lim sababini aytadi",
          bool(tashlangan) and "hajm" in kesilgan[tashlangan[0]]["xato"])

    # Uzun ro'yxat kesiladi va NECHTASI qolgani aytiladi.
    kes = topshiriq._kes([{"i": i} for i in range(100)], 5)
    check("uzun ro'yxat kesiladi va qoldig'i aytiladi",
          len(kes) == 6 and kes[-1]["_qolgan"] == 95)


# =====================================================================
# 4. YOZISH, TAKRORLANMASLIK, BEKOR
# =====================================================================
def _ijarachi(db, login):
    r = db.query_one("SELECT id FROM company_account WHERE username=%(u)s",
                     {"u": login})
    if r:
        db.execute_returning("UPDATE company_account SET active=true "
                             "WHERE id=%(i)s RETURNING id", {"i": r["id"]})
        _yaratilgan["company"].append(r["id"])
        return r["id"]
    r = db.execute_returning(
        "INSERT INTO company_account(username, company_name, password_hash, "
        "active) VALUES (%(u)s, %(n)s, '!sinov-yaroqsiz-xesh', true) "
        "RETURNING id", {"u": login, "n": f"SINOV {login}"})
    _yaratilgan["company"].append(r["id"])
    return r["id"]


def _aktor(db, cid, login, rol="admin"):
    r = db.query_one("SELECT id FROM actor WHERE company_id=%(c)s AND login=%(l)s",
                     {"c": cid, "l": login})
    if r:
        db.execute_returning("UPDATE actor SET active=true WHERE id=%(i)s "
                             "RETURNING id", {"i": r["id"]})
        _yaratilgan["actor"].append(r["id"])
        return r["id"]
    r = db.execute_returning(
        "INSERT INTO actor(company_id, manba, login, ism, rol) "
        "VALUES (%(c)s, 'mahalliy', %(l)s, %(n)s, %(r)s) RETURNING id",
        {"c": cid, "l": login, "n": f"Sinov {login}", "r": rol})
    _yaratilgan["actor"].append(r["id"])
    return r["id"]


def _routing(db, cid, tender_id):
    """Yo'naltirish qatori. QAYTA YURISHGA CHIDAMLI: `tender_routing`
    da `UNIQUE (company_id, tender_id)` bor, ya'ni bitta tenderga
    ikkinchi qator yozib bo'lmaydi."""
    bor = db.query_one("SELECT id FROM tender_routing WHERE company_id=%(c)s "
                       "AND tender_id=%(t)s", {"c": cid, "t": tender_id})
    if bor:
        _yaratilgan["routing"].append(bor["id"])
        return bor["id"]
    r = db.execute_returning(
        # `ai_manba` LUG'ATDAN: 'malaka' | 'gonogo' (CHECK bazada).
        "INSERT INTO tender_routing(company_id, tender_id, ai_qaror, ai_ball, "
        "ai_manba, ai_sabab) VALUES (%(c)s, %(t)s, 'go', 0.9, 'malaka', "
        "'sinov qatori') RETURNING id", {"c": cid, "t": tender_id})
    _yaratilgan["routing"].append(r["id"])
    return r["id"]


def test_yozish(db):
    bolim("4. Yozish, takrorlanmaslik va bekor qilish")
    from api import topshiriq

    # IKKI tender kerak: izolyatsiya tekshiruvi ikkinchi
    # yo'naltirish qatorini talab qiladi, bitta tenderga esa bitta
    # qator yoziladi (UNIQUE company_id, tender_id).
    tlar = db.query("SELECT id FROM tender ORDER BY id LIMIT 2")
    if len(tlar) < 2:
        check("sinov uchun ikki tender kerak", False, f"{len(tlar)} ta")
        return
    t, t2 = tlar[0], tlar[1]
    cid = _ijarachi(db, PREFIX + "_a")
    begona_cid = _ijarachi(db, PREFIX + "_b")
    hodim = _aktor(db, cid, PREFIX + "_hodim")
    boshliq = _aktor(db, cid, PREFIX + "_boshliq")
    begona = _aktor(db, begona_cid, PREFIX + "_begona")
    rid = _routing(db, cid, t["id"])

    row = topshiriq.yarat(rid, cid, t["id"], hodim_actor_id=hodim,
                          yonaltirgan_actor_id=boshliq, ishonch="aktor_elon",
                          ustuvorlik="high", izoh="sinov izohi",
                          muddat=None, tahlil={"sinov": True})
    _yaratilgan["topshiriq"].append(row["id"])
    check("topshiriq yozildi", bool(row["id"]))
    check("ustuvorlik saqlandi", row["ustuvorlik"] == "high")

    v = db.query_one("SELECT * FROM v_erp_topshiriq WHERE id=%(i)s",
                     {"i": row["id"]})
    check("view da ism ko'rinadi (ERP tarixga yozadi)",
          v["hodim_ism"] == f"Sinov {PREFIX}_hodim", str(v["hodim_ism"]))
    check("view aktor id EMAS, erp_user_id beradi",
          "hodim_app_user_id" in v and v["hodim_app_user_id"] is None)

    # QAYTA yozish — YANGILAYDI, ikkinchi qator yaratmaydi.
    row2 = topshiriq.yarat(rid, cid, t["id"], hodim_actor_id=boshliq,
                           yonaltirgan_actor_id=boshliq, ishonch="aktor_elon",
                           ustuvorlik="low", tahlil={"sinov": 2})
    check("takror qaror ikkinchi topshiriq yaratmaydi", row2["id"] == row["id"])
    check("qayta yozilganda yangilanadi", row2["ustuvorlik"] == "low")

    # BEKOR — yozuv o'chmaydi.
    b = topshiriq.bekor(rid, cid)
    check("bekor qilindi", bool(b) and b["bekor_at"] is not None)
    check("yozuv O'CHMAYDI",
          db.scalar("SELECT count(*) FROM tender_topshiriq WHERE id=%(i)s",
                    {"i": row["id"]}) == 1)
    # Qayta "olindi" — TIRILADI.
    row3 = topshiriq.yarat(rid, cid, t["id"], hodim_actor_id=hodim,
                           yonaltirgan_actor_id=boshliq, ishonch="aktor_elon",
                           tahlil={"sinov": 3})
    check("qayta olinganda bekor bekor bo'ladi", row3["bekor_at"] is None)

    # IJARACHI IZOLYATSIYASI — BAZA to'sadi.
    try:
        topshiriq.yarat(_routing(db, cid, t2["id"]), cid, t2["id"],
                        hodim_actor_id=begona, yonaltirgan_actor_id=boshliq,
                        ishonch="aktor_elon", tahlil={})
        check("begona ijarachining aktori RAD etiladi", False, "yozib ketdi")
    except Exception as e:                      # noqa: BLE001
        check("begona ijarachining aktori RAD etiladi",
              "foreign key" in str(e).lower() or "fk" in str(e).lower(),
              type(e).__name__)

    # Noma'lum ustuvorlik — kodda to'siladi.
    try:
        topshiriq.yarat(rid, cid, t["id"], hodim_actor_id=hodim,
                        yonaltirgan_actor_id=boshliq, ishonch="aktor_elon",
                        ustuvorlik="shoshilinch", tahlil={})
        check("noma'lum ustuvorlik RAD etiladi", False, "o'tib ketdi")
    except Exception as e:                      # noqa: BLE001
        check("noma'lum ustuvorlik RAD etiladi", True, type(e).__name__)


# =====================================================================
# 5. XABAR — ERP kutib o'tirmasin
# =====================================================================
def test_xabar(db):
    bolim("5. pg_notify — ERP darhol xabar oladi")
    import select

    from api import topshiriq

    t = db.query_one("SELECT id FROM tender ORDER BY id LIMIT 1")
    if not t:
        check("sinov uchun tender kerak", False, "tender jadvali bo'sh")
        return
    cid = _ijarachi(db, PREFIX + "_a")
    hodim = _aktor(db, cid, PREFIX + "_hodim")
    # O'sha yo'naltirish qatori: `yarat` uni YANGILAYDI va trigger
    # UPDATE da ham ishlaydi — aynan shu ham tekshiriladi.
    rid = _routing(db, cid, t["id"])

    with db.get_conn() as conn:
        conn.set_isolation_level(0)             # avtokommit — LISTEN uchun
        with conn.cursor() as cur:
            cur.execute("LISTEN erp_topshiriq")
        row = topshiriq.yarat(rid, cid, t["id"], hodim_actor_id=hodim,
                              yonaltirgan_actor_id=hodim,
                              ishonch="aktor_elon", tahlil={"sinov": "xabar"})
        _yaratilgan["topshiriq"].append(row["id"])
        select.select([conn], [], [], 5)
        conn.poll()
        xabarlar = [n.payload for n in conn.notifies]
        conn.notifies.clear()
    check("xabar yuborildi", str(row["id"]) in xabarlar, str(xabarlar[:5]))


# =====================================================================
# Tozalash
# =====================================================================
def tozala(db):
    bolim("Tozalash — faqat sinov yaratgan qatorlar")
    for tid in _yaratilgan["topshiriq"]:
        db.execute_returning("DELETE FROM tender_topshiriq WHERE id=%(i)s "
                             "RETURNING id", {"i": tid})
    for rid in _yaratilgan["routing"]:
        db.execute_returning("DELETE FROM tender_topshiriq WHERE routing_id=%(i)s "
                             "RETURNING id", {"i": rid})
        db.execute_returning("DELETE FROM tender_routing WHERE id=%(i)s "
                             "RETURNING id", {"i": rid})
    for aid in _yaratilgan["actor"]:
        db.execute_returning("UPDATE actor SET active=false WHERE id=%(i)s "
                             "RETURNING id", {"i": aid})
    for cid in _yaratilgan["company"]:
        db.execute_returning("UPDATE company_account SET active=false "
                             "WHERE id=%(i)s RETURNING id", {"i": cid})
    qoldi = db.scalar(
        "SELECT count(*) FROM tender_topshiriq t JOIN company_account c "
        "ON c.id = t.company_id WHERE c.username LIKE %(p)s",
        {"p": PREFIX + "%"})
    check("sinov topshiriqlari qolmadi", qoldi == 0, str(qoldi))


def main():
    from api import db
    db.init_pool()
    test_manba()
    try:
        test_view(db)
        test_tahlil(db)
        test_yozish(db)
        test_xabar(db)
    finally:
        try:
            tozala(db)
        except Exception as e:                  # noqa: BLE001
            check("tozalash", False, f"{type(e).__name__}: {e}")

    otdi = sum(1 for _, ok, _ in _natija if ok)
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
