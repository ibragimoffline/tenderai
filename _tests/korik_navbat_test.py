#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: KO'RIK TUGAGACH NAVBAT YANGILANADIMI
============================================

O'LCHANGAN MUAMMO (2026-09-03): "Talablar" bo'limida talab
tasdiqlangach zanjir UZILARDI.

    tasdiq -> tender_requirement           YOZILARDI
           -> tender_routing               TEGILMASDI

`tender_routing` faqat `run_etl.py` ning post-qadamida yoki
brokerning "Yangilash" tugmasida qayta hisoblanardi. Ya'ni talab
tuzatildi, `qualification` natijasi o'zgardi, broker esa navbatda
ESKI ballni ko'rib turaverdi.

IKKINCHI, JIDDIYROQ NUQSON SHU YO'LDA TOPILDI. `yonaltir()` `no_go`
da MAVJUD yozuvni ham tegmay qaytarardi:

    if not barchasi and decision not in NAVBAT_QARORLARI:
        return None            # <- UPSERT ga umuman yetib borilmasdi

Natijada `SQL_UPSERT` izohi va'da qilgan himoya -- "`go` `no_go` ga
o'tdi, broker xabar topsin" (`ai_ozgardi`) -- HECH QACHON ishlamasdi.
O'LCHANDI: 347 yozuvdan 48 tasining `ai_qaror` i eskirgan, shundan
11 tasida inson qarori bor va 5 tasi "olindi".

Bu `ai_ozgardi` ustunining o'zi bilan BIR XIL sinf: izoh himoyani
va'da qilgan, himoya esa yo'q edi (`schema_patch_routing_2.sql`).

SINOV OLTITA NARSANI QO'RIQLAYDI:

  1. `korik_tugadi` bor va natijasi YOPIQ ro'yxatdan;
  2. YOPIQ tender baholanmaydi (`SQL_NOMZODLAR` bilan AYNI qoida);
  3. yangi `no_go` navbatga QO'SHILMAYDI;
  4. MAVJUD yozuv `no_go` ga o'tsa YANGILANADI va `ai_ozgardi`
     yoqiladi (asosiy tuzatish);
  5. `navbatga_tushdi` sanog'i `no_go` bilan SHISHMAYDI;
  6. endpoint natijani QAYTARADI va yiqilsa ko'rikni BUZMAYDI.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\korik_navbat_test.py
    .venv\\Scripts\\python.exe _tests\\korik_navbat_test.py --bazasiz
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


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
def test_manba():
    bolim("1. Manba — funksiya va qoidalar")
    from api import routing
    check("`korik_tugadi` bor", hasattr(routing, "korik_tugadi"))
    check("holatlar yopiq ro'yxat",
          set(routing.KORIK_HOLATLARI)
          == {"navbatda", "no_go", "yopiq", "tender_yoq"},
          str(routing.KORIK_HOLATLARI))

    src = io.open(os.path.join(ROOT, "api", "routing.py"),
                  encoding="utf-8").read()
    # ASOSIY TUZATISH: `no_go` mavjud yozuvni yangilaydi.
    check("`SQL_MAVJUD` e'loni `yonaltir` dan OLDIN",
          "SQL_MAVJUD" in src
          and src.index("SQL_MAVJUD") < src.index("def yonaltir("))
    i = src.index("def yonaltir(")
    tana = src[i:i + 2500]
    check("`yonaltir` `SQL_MAVJUD` ni so'raydi", "SQL_MAVJUD" in tana)
    check("nuqson sababi izohda yozilgan",
          "ai_ozgardi" in tana and "yetib borilmasdi" in tana)
    # YOPIQ TENDER QOIDASI IKKI JOYDA TAKRORLANMAYDI.
    check("`korik_tugadi` yopiqlikni SQL bilan tekshiradi",
          "SQL_OCHIQMI" in src)
    check("`navbatga_tushdi` faqat go/review ni sanaydi",
          'if out["decision"] in NAVBAT_QARORLARI:' in src)


def test_endpoint_manba():
    bolim("2. API — ikkala tasdiq yo'li ham ulangan")
    src = io.open(os.path.join(ROOT, "api", "main.py"),
                  encoding="utf-8").read()
    check("`_navbatni_yangila` yordamchisi bor",
          "def _navbatni_yangila" in src)
    check("yordamchi `korik_tugadi` ni chaqiradi",
          "routing.korik_tugadi" in src)
    # YIQILSA KO'RIK BUZILMAYDI.
    j = src.index("def _navbatni_yangila")
    check("xato ushlanadi (500 ga aylanmaydi)",
          "except Exception" in src[j:j + 1400])
    check("xato sababi javobda qaytadi",
          '"holat": "xato"' in src[j:j + 1400])
    # IKKALA ENDPOINT.
    b = src.index("def requirement_review(")
    check("bitta talab yo'li ulangan",
          "_navbatni_yangila" in src[b:b + 4200]
          and '"yonaltirish": yonaltirish' in src[b:b + 4200])
    o = src.index("def requirements_review_all(")
    check("ommaviy yo'l ulangan",
          "_navbatni_yangila" in src[o:o + 2200])
    # ORALIQ TASDIQDA CHAQIRILMAYDI: faqat `if not qolgan` ichida.
    k = src.index("_navbatni_yangila(row[", b)
    check("faqat KO'RIK TUGAGANDA chaqiriladi",
          "if not qolgan:" in src[b:k])


def test_interfeys():
    bolim("3. Interfeys — natija JIM QOLMAYDI")
    f = os.path.join(ROOT, "frontend", "src", "components",
                     "RequirementReview.tsx")
    src = io.open(f, encoding="utf-8").read()
    check("xabar hisoblanadi", "yonaltirishMatni" in src)
    check("banner chiziladi", "navbatXabar" in src)
    # ENG SHOSHILINCH HOLAT BIRINCHI TEKSHIRILADI.
    i = src.index("function yonaltirishMatni")
    tana = src[i:i + 1600]
    check("eskirgan qaror BIRINCHI tekshiriladi",
          tana.index("inson_qarori_eskirdi") < tana.index("'yopiq'"))
    check("ikki xil `no_go` farqlanadi",
          "req.route.left" in tana and "req.route.nogo" in tana)
    for lok in ("uz", "ru", "en"):
        p = os.path.join(ROOT, "frontend", "src", "locales", f"{lok}.ts")
        t = io.open(p, encoding="utf-8").read()
        yoq = [k for k in ("req.route.queued", "req.route.nogo",
                           "req.route.left", "req.route.stale",
                           "req.route.same", "req.route.closed",
                           "req.route.missing", "req.route.failed")
               if f"'{k}'" not in t]
        check(f"`{lok}` tarjimalari to'liq", not yoq, str(yoq))


# =====================================================================
def test_baza(db):
    bolim("4. Haqiqiy ma'lumot — yopiq tender baholanmaydi")
    from api import auth, routing
    cid = auth.sole_company_id()

    yopiq = db.query_one(
        "SELECT t.id FROM tender t JOIN tender_requirement r "
        "    ON r.tender_id = t.id AND r.company_id = %(c)s "
        " WHERE t.close_at IS NOT NULL AND t.close_at <= now() "
        " LIMIT 1", {"c": cid})
    if yopiq:
        oldin = db.scalar(
            "SELECT count(*) FROM tender_routing "
            "WHERE company_id=%(c)s AND tender_id=%(t)s",
            {"c": cid, "t": yopiq["id"]})
        r = routing.korik_tugadi(yopiq["id"], cid)
        keyin = db.scalar(
            "SELECT count(*) FROM tender_routing "
            "WHERE company_id=%(c)s AND tender_id=%(t)s",
            {"c": cid, "t": yopiq["id"]})
        check("yopiq tender -> holat 'yopiq'", r["holat"] == "yopiq",
              str(r))
        check("yopiq tenderga YOZUV OCHILMADI", oldin == keyin,
              f"{oldin} -> {keyin}")
    else:
        print("        [i] yopiq tender topilmadi — tekshiruv yo'q")

    check("mavjud bo'lmagan tender -> 'tender_yoq'",
          routing.korik_tugadi(-1, cid)["holat"] == "tender_yoq")


def test_nogo_mavjud_yozuvni_yangilaydi(db):
    bolim("5. ASOSIY TUZATISH: `no_go` mavjud yozuvni YANGILAYDI")
    from api import auth, routing
    cid = auth.sole_company_id()

    # SINOV QATORI — haqiqiy yozuvga TEGILMAYDI. Malakasi `no_go`
    # chiqadigan tender TANLANADI: aks holda sinov "o'tdi" deb
    # ko'rinib, asosiy yo'lni umuman o'lchamasdi.
    from api import qualification
    nomzod = None
    for r in db.query(
            "SELECT DISTINCT t.id FROM tender t "
            "  JOIN tender_requirement q ON q.tender_id = t.id "
            "                           AND q.company_id = %(c)s "
            " WHERE NOT EXISTS (SELECT 1 FROM tender_routing g "
            "                    WHERE g.tender_id=t.id "
            "                      AND g.company_id=%(c)s) "
            " ORDER BY t.id DESC LIMIT 40", {"c": cid}):
        try:
            if qualification.check(r["id"], cid)["decision"] == "no_go":
                nomzod = r["id"]
                break
        except Exception:                                     # noqa: BLE001
            continue
    if nomzod is None:
        check("malakasi `no_go` chiqadigan sinov tenderi topildi", False,
              "sinov ma'lumoti yetarli emas")
        return

    rid = None
    try:
        # Broker `go` ni ko'rgan va "olindi" degan.
        r0 = db.execute_returning(routing.SQL_UPSERT, {
            "c": cid, "t": nomzod, "q": "go", "b": 1.0,
            "m": "malaka", "s": "ZZTEST boshlangich"})
        rid = r0["id"]
        db.execute_returning(
            # `qaror_ishonch` + `qaror_vaqti` MAJBURIY (ikkita CHECK):
            # inson qarori atributsiz yozilmaydi.
            "UPDATE tender_routing SET inson_qaror='olindi', "
            "       qaror_ishonch='kompaniya_sessiyasi', "
            "       qaror_vaqti=now() "
            "WHERE id=%(i)s RETURNING id", {"i": rid})

        # ENDI AI `no_go` deydi. ILGARI shu yerda HECH NARSA bo'lmasdi.
        out = routing.yonaltir(nomzod, cid)
        check("`yonaltir` mavjud yozuvda `None` QAYTARMAYDI",
              out is not None, str(out))

        e = db.query_one("SELECT ai_qaror, ai_ozgardi, ai_qaror_eski, "
                         "       inson_qaror FROM tender_routing "
                         "WHERE id=%(i)s", {"i": rid})
        check("`ai_qaror` `no_go` ga YANGILANDI",
              e["ai_qaror"] == "no_go", str(e["ai_qaror"]))
        check("`ai_ozgardi` YOQILDI (broker xabar topadi)",
              e["ai_ozgardi"] is True, str(e))
        check("`ai_qaror_eski` = 'go' (inson KO'RGAN qaror)",
              e["ai_qaror_eski"] == "go", str(e["ai_qaror_eski"]))

        # `korik_tugadi` shuni "navbatdan CHIQDI" deb aytadimi.
        k = routing.korik_tugadi(nomzod, cid)
        check("`korik_tugadi` holati `no_go`", k["holat"] == "no_go", str(k))
    finally:
        if rid:
            db.execute_returning("DELETE FROM tender_routing "
                                 "WHERE id=%(i)s RETURNING id", {"i": rid})
            print("        (sinov qatori o'chirildi)")


def test_yangi_nogo_qoshilmaydi(db):
    bolim("6. Yangi `no_go` navbatga QO'SHILMAYDI")
    from api import auth, qualification, routing
    cid = auth.sole_company_id()
    nomzod = None
    for r in db.query(
            "SELECT DISTINCT t.id FROM tender t "
            "  JOIN tender_requirement q ON q.tender_id = t.id "
            "                           AND q.company_id = %(c)s "
            " WHERE NOT EXISTS (SELECT 1 FROM tender_routing g "
            "                    WHERE g.tender_id=t.id "
            "                      AND g.company_id=%(c)s) "
            " ORDER BY t.id DESC LIMIT 40", {"c": cid}):
        try:
            if qualification.check(r["id"], cid)["decision"] == "no_go":
                nomzod = r["id"]
                break
        except Exception:                                     # noqa: BLE001
            continue
    if nomzod is None:
        print("        [i] mos tender yo'q — tekshiruv o'tkazilmadi")
        return
    out = routing.yonaltir(nomzod, cid)
    check("yozuvi YO'Q `no_go` uchun `None` qaytadi", out is None, str(out))
    check("navbatga YOZUV OCHILMADI",
          not db.scalar("SELECT count(*) FROM tender_routing "
                        "WHERE company_id=%(c)s AND tender_id=%(t)s",
                        {"c": cid, "t": nomzod}))


def test_eskirgan_yozuvlar(db):
    bolim("7. O'LCHOV: hozir nechta yozuv ESKIRGAN")
    from api import auth, qualification
    cid = auth.sole_company_id()
    rows = db.query("SELECT tender_id, ai_qaror, inson_qaror "
                    "FROM tender_routing WHERE company_id=%(c)s", {"c": cid})
    eskirgan = insonli = 0
    for r in rows:
        try:
            d = qualification.check(r["tender_id"], cid)["decision"]
        except Exception:                                     # noqa: BLE001
            continue
        if d != r["ai_qaror"]:
            eskirgan += 1
            if r["inson_qaror"]:
                insonli += 1
    print(f"        {len(rows)} yozuvdan {eskirgan} tasi eskirgan, "
          f"shundan {insonli} tasida INSON qarori bor")
    # BU YIQITMAYDI — u O'LCHOV. Tuzatish keyingi ETL yurishida
    # qo'llanadi va raqam nolga intilishi kerak.
    check("o'lchov olindi", True, f"eskirgan={eskirgan} insonli={insonli}")


# =====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Ko'rik tugagach navbat yangilanishi sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: KO'RIK TUGAGACH NAVBAT YANGILANADIMI")
    print("=" * 70)

    test_manba()
    test_endpoint_manba()
    test_interfeys()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Bazali tekshiruvlar o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_baza(db)
            test_nogo_mavjud_yozuvni_yangilaydi(db)
            test_yangi_nogo_qoshilmaydi(db)
            test_eskirgan_yozuvlar(db)
        except Exception as e:                                # noqa: BLE001
            check("bazali tekshiruv", False, str(e)[:110])

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
