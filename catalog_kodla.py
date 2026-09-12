#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KATALOG KODLASH — tahlil, navbat va OMMAVIY qo'llash
=====================================================

NEGA BU FAYL BOR
----------------
`api/catalog_auto.classify_product()` FAQAT bitta mahsulot CRUD idan
chaqiriladi (`api/main.py` da uch joy: yaratish, yangilash, kod
biriktirish). Barcha 1 797 mahsulot 2026-08-27 da OMMAVIY IMPORT
bilan yaratilgan va importer klassifikatsiyani CHAQIRMAYDI.

Natija (o'lchandi 2026-08-31):

    8 belgili ANIQ kod:  0 ta
    5 belgili KENG kod:  960 ta — atigi 3 xil qiymat
                         (26.40 x612, 26.30 x299, 26.20 x49),
                         hammasi bir kunda ommaviy berilgan

Ya'ni qamrov nol, chunki algoritm qattiq emas — u HECH QACHON
YURGIZILMAGAN. Bu skript o'sha yetishmayotgan yo'l.

CHEGARALAR O'ZGARMAYDI
----------------------
`MIN_EVIDENCE=2` va `MIN_SHARE=0.75` shu holicha qoladi. O'lchov
ularni oqlaydi: 837 kodsiz mahsulotdan `noaniq` (ulush past) — 0 ta,
ya'ni `MIN_SHARE` qamrovni TO'SMAYAPTI. Chegarani pasaytirish
precisionni yeydi va bu ATAYLAB qilinmagan.

ISHGA TUSHIRISH
---------------
    python catalog_kodla.py --tahlil      # tahlil + saqlash (KOD YOZMAYDI)
    python catalog_kodla.py --qamrov      # qamrov o'lchovi
    python catalog_kodla.py --navbat      # ko'rib chiqish navbati
    python catalog_kodla.py --qolla       # ISHONCHLI kodlarni qo'llash
    python catalog_kodla.py --qolla --quruq   # nima bo'lardi (yozmaydi)

STANDART — TAHLIL. Kod yozish ANIQ `--qolla` talab qiladi: ommaviy
yozuv qaytarib bo'lmaydigan amal va u tasodifan boshlanmasligi kerak.

CHIQISH KODI: 0 — muvaffaqiyat; 1 — xato.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_tests"))

try:
    import konsol
    konsol.sozla()
except Exception:                                             # pragma: no cover
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api import catalog_auto, db  # noqa: E402

TAHLIL_UPSERT = """
INSERT INTO catalog_kod_tahlil
    (company_id, product_id, sabab, taklif_code, ishonch, dalil, jami,
     nomzod, tokenlar, kodlar, misollar, ochiq_tender, tarixiy_lot,
     kuchsiz_dalil, tahlil_at)
VALUES (%(c)s, %(p)s, %(sabab)s, %(code)s, %(ishonch)s, %(dalil)s, %(jami)s,
        %(nomzod)s, %(tokenlar)s, %(kodlar)s::jsonb, %(misollar)s,
        %(ochiq)s, %(lot)s, %(kuchsiz)s, now())
ON CONFLICT (company_id, product_id) DO UPDATE SET
    sabab = EXCLUDED.sabab, taklif_code = EXCLUDED.taklif_code,
    ishonch = EXCLUDED.ishonch, dalil = EXCLUDED.dalil,
    jami = EXCLUDED.jami, nomzod = EXCLUDED.nomzod,
    tokenlar = EXCLUDED.tokenlar, kodlar = EXCLUDED.kodlar,
    misollar = EXCLUDED.misollar, ochiq_tender = EXCLUDED.ochiq_tender,
    tarixiy_lot = EXCLUDED.tarixiy_lot,
    kuchsiz_dalil = EXCLUDED.kuchsiz_dalil, tahlil_at = now()
RETURNING product_id
"""


def _mahsulotlar(company_id: int, limit: int = 0) -> List[Dict[str, Any]]:
    return db.query(
        "SELECT id, name, category_code, keywords FROM catalog_product "
        "WHERE company_id = %(c)s ORDER BY id"
        + (f" LIMIT {int(limit)}" if limit else ""),
        {"c": company_id})


def qamrov(company_id: int) -> Dict[str, Any]:
    return db.query_one(
        "SELECT * FROM v_catalog_kod_qamrov WHERE company_id = %(c)s",
        {"c": company_id}) or {}


def _qamrov_chop(sarlavha: str, q: Dict[str, Any]) -> None:
    print(f"\n{sarlavha}")
    print(f"  mahsulot           {q.get('mahsulot', 0)}")
    print(f"  ANIQ kod (8+)      {q.get('aniq_kod', 0)}   "
          f"({q.get('aniq_foiz', 0)}%)")
    print(f"  keng kod (5)       {q.get('keng_kod', 0)}")
    print(f"  kodsiz             {q.get('kodsiz', 0)}")
    # ANIQ va KENG ataylab alohida: ularni qo'shib "kodlangan" deyish
    # 26.40 chelagidagi 612 mahsulotni aniq kodlangan qilib ko'rsatardi.
    print(f"  har qanday kod     {q.get('har_qanday_foiz', 0)}%")


def tahlil_yurgiz(company_id: int, limit: int = 0) -> Dict[str, int]:
    """Har mahsulotni tahlil qiladi va SABABI bilan saqlaydi.

    KOD YOZMAYDI. Faqat `catalog_kod_tahlil` ga yozadi.
    """
    rows = _mahsulotlar(company_id, limit)
    print(f"Tahlil: {len(rows)} ta mahsulot")
    sanoq: Dict[str, int] = {}
    t0 = time.time()
    for i, p in enumerate(rows, 1):
        t = catalog_auto.tahlil(p)
        bq = catalog_auto.biznes_qiymati(p)
        sanoq[t["sabab"]] = sanoq.get(t["sabab"], 0) + 1
        db.execute_returning(TAHLIL_UPSERT, {
            "c": company_id, "p": p["id"], "sabab": t["sabab"],
            "code": t["code"] if t["sabab"] == "kod" else t["code"],
            "ishonch": t["confidence"], "dalil": t["evidence"],
            "jami": t["total"], "nomzod": t["nomzod"],
            "tokenlar": t["tokens"],
            "kodlar": json.dumps(t["kodlar"], ensure_ascii=False),
            "misollar": t["examples"],
            "ochiq": bq["ochiq_tender"], "lot": bq["tarixiy_lot"],
            "kuchsiz": bool(t.get("kuchsiz_dalil"))})
        if i % 200 == 0:
            print(f"  ... {i}/{len(rows)}")
    print(f"  tugadi: {time.time() - t0:.1f}s\n")
    print(f"  {'sabab':<18}{'soni':>7}{'ulush':>9}")
    for s, n in sorted(sanoq.items(), key=lambda kv: -kv[1]):
        print(f"  {s:<18}{n:>7}{100 * n / max(len(rows), 1):>8.1f}%")
    return sanoq


def navbat_chop(company_id: int, limit: int = 25, sabab: str = "") -> None:
    shart = "company_id = %(c)s" + (" AND sabab = %(s)s" if sabab else "")
    rows = db.query(
        f"SELECT product_id, left(mahsulot, 40) AS mahsulot, sabab, "
        f"taklif_code, ishonch, dalil, jami, ochiq_tender, tarixiy_lot, "
        f"ustuvorlik, nima_kerak FROM v_catalog_kod_navbat WHERE {shart} "
        f"ORDER BY ustuvorlik DESC, product_id LIMIT {int(limit)}",
        {"c": company_id, "s": sabab})
    if not rows:
        print("Navbat bo'sh (yoki tahlil yurgizilmagan).")
        return
    print(f"\nKO'RIB CHIQISH NAVBATI — biznes qiymati bo'yicha "
          f"({len(rows)} ta ko'rsatildi)")
    print(f"  {'id':>6} {'mahsulot':<40} {'sabab':<16} {'kod':<9}"
          f"{'ochiq':>6}{'lot':>6}")
    for r in rows:
        print(f"  {r['product_id']:>6} {(r['mahsulot'] or ''):<40} "
              f"{r['sabab']:<16} {str(r['taklif_code'] or '-'):<9}"
              f"{r['ochiq_tender']:>6}{r['tarixiy_lot']:>6}")


def qolla(company_id: int, quruq: bool = True, limit: int = 0) -> Dict[str, int]:
    """`sabab='kod'` bo'lgan mahsulotlarga kodni QO'LLAYDI.

    `classify_product()` chaqiriladi — mantiq TAKRORLANMAYDI. U inson
    tasdig'i ustidan yozmaydi va rad etilgan kodni qaytarmaydi.
    """
    rows = db.query(
        "SELECT t.product_id FROM catalog_kod_tahlil t "
        "WHERE t.company_id = %(c)s AND t.sabab = 'kod' "
        # KUCHSIZ DALIL BANDI AVTOMATIK QO'LLANMAYDI — u navbatga
        # boradi. `classify_product()` ham buni rad etadi; bu yerdagi
        # shart faqat bekorga chaqiruv qilmaslik uchun.
        "  AND NOT t.kuchsiz_dalil "
        "  AND NOT EXISTS (SELECT 1 FROM v_catalog_code_active v "
        "                   WHERE v.product_id = t.product_id "
        "                     AND v.company_id = t.company_id "
        "                     AND length(v.code) >= 8) "
        "ORDER BY t.ochiq_tender DESC, t.product_id"
        + (f" LIMIT {int(limit)}" if limit else ""),
        {"c": company_id})
    print(f"Qo'llash: {len(rows)} ta nomzod"
          + ("  (QURUQ — yozilmaydi)" if quruq else ""))
    natija: Dict[str, int] = {}
    for r in rows:
        if quruq:
            natija["quruq"] = natija.get("quruq", 0) + 1
            continue
        h = catalog_auto.classify_product(company_id, r["product_id"])
        natija[h.get("status", "?")] = natija.get(h.get("status", "?"), 0) + 1
    for k, v in sorted(natija.items()):
        print(f"  {k:<14} {v}")
    return natija


def qayta_baho(company_id: int, quruq: bool = True) -> Dict[str, int]:
    """FAOL kodlarni YANGI siyosat bilan qayta baholaydi.

    FAOLLIKNI BEKOR QILMAYDI. O'tmaganlarga `korib_chiqilsin` bayrog'i
    qo'yiladi va kod ISHLASHDA QOLADI.

    NEGA SHUNDAY (2026-09-12 qarori): 187 ta kod siyosat yozilishidan
    OLDIN faollashtirilgan. Yangi siyosat 49 tasini o'tkazmaydi.
    Ular orasida haqiqiy xato bor (server SHKAFI `Сервер` deb
    kodlangan), lekin HAMMASI xato degani emas -- yangi siyosat
    qat'iyroq, xatosiz emas. Birdan o'chirish "Sizga mos" ni 49
    mahsulot bo'yicha kamaytirardi va TO'G'RI kodlarni ham yo'qotardi.
    Bog'lanish faqat INSON rad etganda o'zgaradi.
    """
    rows = db.query(
        "SELECT pc.product_id, pc.code, p.name, p.category_code, p.keywords "
        "  FROM catalog_product_code pc "
        "  JOIN catalog_product p ON p.id = pc.product_id "
        "   AND p.company_id = pc.company_id "
        " WHERE pc.company_id = %(c)s AND pc.tasdiqlandi IS NOT NULL "
        "   AND pc.rad_etildi IS NULL AND pc.tasdiqlagan = %(a)s "
        " ORDER BY pc.product_id",
        {"c": company_id, "a": catalog_auto.SYSTEM_ACTOR})
    print(f"Qayta baholash: {len(rows)} ta FAOL avtomatik kod"
          + ("  (QURUQ -- yozilmaydi)" if quruq else ""))
    natija = {"otdi": 0, "belgilandi": 0}
    for r in rows:
        p = {"id": r["product_id"], "name": r["name"],
             "category_code": r["category_code"], "keywords": r["keywords"]}
        h = catalog_auto.tahlil(p)
        q = catalog_auto.siyosat_qarori(h, p)
        # Kod O'ZGARGAN bo'lsa ham faollikka tegmaymiz -- bu ham
        # odam ko'radigan holat.
        otdi = (q["qaror"] == "auto" and h.get("code") == r["code"])
        if otdi:
            natija["otdi"] += 1
            continue
        natija["belgilandi"] += 1
        sabab = q.get("sabab") or "siyosat"
        if h.get("code") != r["code"]:
            sabab = f"kod_ozgardi:{h.get('code')}|{sabab}"
        if quruq:
            continue
        db.execute_returning(
            "UPDATE catalog_product_code "
            "SET korib_chiqilsin = true, siyosat_sabab = %(s)s, "
            "    siyosat_at = now() "
            "WHERE product_id=%(p)s AND company_id=%(c)s AND code=%(code)s "
            "RETURNING product_id",
            {"p": r["product_id"], "c": company_id, "code": r["code"],
             "s": sabab[:200]})
    for k, v in sorted(natija.items()):
        print(f"  {k:<14} {v}")
    return natija


def main() -> None:
    ap = argparse.ArgumentParser(description="Katalog kodlash")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--tahlil", action="store_true",
                   help="Tahlil qilib saqlaydi (KOD YOZMAYDI) — STANDART")
    g.add_argument("--qolla", action="store_true",
                   help="Ishonchli kodlarni QO'LLAYDI")
    g.add_argument("--qayta-baho", dest="qayta_baho", action="store_true",
                   help="FAOL kodlarni yangi siyosat bilan qayta baholaydi "
                        "(faollikni BEKOR QILMAYDI)")
    g.add_argument("--qamrov", action="store_true", help="Qamrov o'lchovi")
    g.add_argument("--navbat", action="store_true", help="Ko'rib chiqish navbati")
    ap.add_argument("--quruq", action="store_true",
                    help="--qolla bilan: nima bo'lardi, yozmaydi")
    ap.add_argument("--sabab", default="", help="--navbat uchun filtr")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--company", type=int, default=0,
                    help="Ijarachi id (bo'sh: yagona faol hisob)")
    args = ap.parse_args()

    db.init_pool()
    cid = args.company
    if not cid:
        from api import auth
        cid = auth.sole_company_id()
    print(f"Ijarachi: {cid}")

    if args.qayta_baho:
        qayta_baho(cid, quruq=args.quruq)
        return

    if args.qamrov:
        _qamrov_chop("QAMROV", qamrov(cid))
        rows = db.query("SELECT sabab, soni, ulush_foiz, ochiq_tender_jami "
                        "FROM v_catalog_kod_sabab WHERE company_id=%(c)s "
                        "ORDER BY soni DESC", {"c": cid})
        if rows:
            print(f"\n  {'sabab':<18}{'soni':>7}{'ulush':>9}{'ochiq tender':>14}")
            for r in rows:
                print(f"  {r['sabab']:<18}{r['soni']:>7}"
                      f"{r['ulush_foiz']:>8}%{r['ochiq_tender_jami']:>14}")
        else:
            print("\n  (tahlil yurgizilmagan — `--tahlil`)")
        return

    if args.navbat:
        navbat_chop(cid, limit=args.limit or 25, sabab=args.sabab)
        return

    if args.qolla:
        oldin = qamrov(cid)
        _qamrov_chop("QAMROV — OLDIN", oldin)
        qolla(cid, quruq=args.quruq, limit=args.limit)
        if not args.quruq:
            keyin = qamrov(cid)
            _qamrov_chop("QAMROV — KEYIN", keyin)
            print(f"\n  ANIQ kod: {oldin.get('aniq_kod', 0)} -> "
                  f"{keyin.get('aniq_kod', 0)}")
        return

    # Standart — tahlil.
    tahlil_yurgiz(cid, limit=args.limit)
    _qamrov_chop("QAMROV (o'zgarmadi — tahlil kod yozmaydi)", qamrov(cid))


if __name__ == "__main__":
    main()
