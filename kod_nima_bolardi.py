#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOSLIK QOIDASI — NIMA BO'LARDI (faqat o'qish, HECH NARSA YOZMAYDI)
===================================================================

NEGA BU FAYL BOR
----------------
`catalog_auto.tahlil()` nomzod lotni qabul qilish uchun MAHSULOT
nomining HAR BIR so'zi lot nomida bo'lishini talab qiladi. Mahsulot
nomi brend va modelni olib yuradi, lot nomi esa qisqa:

    mahsulot : VPN router (marshrutizator) 4G Tp-Link   -> 6 token
    lot      : Маршрутизатор                            -> 1 so'z
    natija   : 1 mos, 5 mos emas -> RAD

O'LCHANGAN OQIBAT (ishlab chiqarish, 2026-09-12, 1840 mahsulot):

    sozlar_mos_emas   1294   70.3%   ortida 14 782 ochiq tender
    kod                  3    0.2%   ortida        4 ochiq tender

Ya'ni avtomatik kodlash 1840 tadan 3 tasini qamraydi.

BU SKRIPT QAROR QABUL QILMAYDI
------------------------------
U faqat "boshqa qoida bilan nima bo'lardi" degan savolga RAQAM
beradi. Chegaralar (`MIN_EVIDENCE`, `MIN_SHARE`) TEGILMAYDI -- ular
soxta moslikka qarshi ikkinchi qavat bo'lib qoladi va bu yerda ham
o'z ishini qiladi.

QAMROV O'ZI YETARLI DALIL EMAS. Shuning uchun har qoida uchun
NAMUNA ham chop etiladi: qamrov o'sib, namunada axlat chiqsa --
qoida yaroqsiz. Namuna TASODIFIY (urug' qat'iy), eng yaxshisi
tanlab olinmaydi.

ISHGA TUSHIRISH
---------------
    python kod_nima_bolardi.py --company 1
    python kod_nima_bolardi.py --company 1 --limit 300     # tez chopish
    python kod_nima_bolardi.py --company 1 --namuna 12

CHIQISH KODI: 0 -- muvaffaqiyat; 1 -- xato.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                             # pragma: no cover
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api import catalog_auto, db  # noqa: E402
from catalog_kodla import _mahsulotlar  # noqa: E402

#: Chop etiladigan sabablar -- `catalog_auto.SABABLAR` tartibida emas,
#: BIZNES tartibida: avval yutuq, keyin yo'qotish sabablari.
USTUNLAR = ("kod", "noaniq", "dalil_kam", "sozlar_mos_emas",
            "nomzodsiz", "tokensiz")


def _ochiq_tender(company_id: int) -> Dict[int, int]:
    """Mahsulot -> ochiq tender soni (oxirgi `--tahlil` dan).

    Qayta hisoblanmaydi: bu son qoidaga bog'liq emas, mahsulotning
    tarixiy lotlariga bog'liq.
    """
    rows = db.query(
        "SELECT product_id, ochiq_tender FROM catalog_kod_tahlil "
        "WHERE company_id = %(c)s", {"c": company_id})
    return {r["product_id"]: (r["ochiq_tender"] or 0) for r in rows}


def olch(company_id: int, qoidalar: List[str], limit: int = 0,
         namuna: int = 8) -> int:
    mahsulotlar = _mahsulotlar(company_id, limit)
    if not mahsulotlar:
        print("Mahsulot topilmadi.")
        return 1
    ochiq = _ochiq_tender(company_id)
    print(f"Mahsulot: {len(mahsulotlar)}   qoida: {', '.join(qoidalar)}")

    jadval: Dict[str, Dict[str, int]] = {}
    qiymat: Dict[str, int] = {}
    kodlangan: Dict[str, List[Dict[str, Any]]] = {}

    for q in qoidalar:
        sanoq: Dict[str, int] = {}
        qiymat[q] = 0
        kodlangan[q] = []
        for p in mahsulotlar:
            h = catalog_auto.tahlil(p, qoida=q)
            sabab = h.get("sabab", "?")
            sanoq[sabab] = sanoq.get(sabab, 0) + 1
            if sabab == "kod":
                qiymat[q] += ochiq.get(p["id"], 0)
                kodlangan[q].append({"p": p, "h": h})
        jadval[q] = sanoq

    kenglik = max(len(q) for q in qoidalar) + 2
    print(f"\n{'qoida':<{kenglik}}" + "".join(f"{u:>17}" for u in USTUNLAR)
          + f"{'qamrov':>9}{'ochiq tender':>14}")
    for q in qoidalar:
        s = jadval[q]
        kod = s.get("kod", 0)
        foiz = 100.0 * kod / len(mahsulotlar)
        print(f"{q:<{kenglik}}"
              + "".join(f"{s.get(u, 0):>17}" for u in USTUNLAR)
              + f"{foiz:>8.1f}%{qiymat[q]:>14}")

    rnd = random.Random(20260912)
    for q in qoidalar:
        rows = kodlangan[q]
        if not rows or q == "hozirgi":
            continue
        print(f"\n--- NAMUNA: {q}  ({len(rows)} ta kodlangandan "
              f"{min(namuna, len(rows))} tasi, TASODIFIY) ---")
        for r in rnd.sample(rows, min(namuna, len(rows))):
            p, h = r["p"], r["h"]
            nom = (p.get("name") or "")[:52]
            print(f"  {nom:<52} -> {h.get('code')}  "
                  f"ishonch {h.get('confidence')}  "
                  f"dalil {h.get('evidence')}/{h.get('total')}")
            for m in (h.get("examples") or [])[:2]:
                print(f"        lot: {m[:64]}")
    return 0


def olch_siyosat(company_id: int, limit: int = 0, namuna: int = 8) -> int:
    """Avtomatik tasdiq SIYOSATINI o'lchaydi (qoidani emas).

    Qoida "qaysi kod" ni hal qiladi; siyosat esa "odam ko'rmasdan
    faollashtirsa bo'ladimi" ni. Bu funksiya ikkinchisini o'lchaydi.
    """
    mahsulotlar = _mahsulotlar(company_id, limit)
    if not mahsulotlar:
        print("Mahsulot topilmadi.")
        return 1
    ochiq = _ochiq_tender(company_id)
    presetlar = list(catalog_auto.SIYOSAT_PRESET)
    print(f"Mahsulot: {len(mahsulotlar)}   siyosat: {', '.join(presetlar)}")

    # `tahlil()` BIR MARTA -- siyosat uni o'zgartirmaydi, faqat
    # natijasini baholaydi. Uni har preset uchun qayta yurgizish
    # 4 barobar bekor ish bo'lardi.
    tahlillar = [(p, catalog_auto.tahlil(p)) for p in mahsulotlar]

    jadval: Dict[str, Dict[str, int]] = {}
    qiymat: Dict[str, int] = {}
    tushgan: Dict[str, List[Any]] = {}
    for s_nom in presetlar:
        sanoq = {"auto": 0, "navbat": 0, "kodsiz": 0}
        qiymat[s_nom] = 0
        tushgan[s_nom] = []
        for p, h in tahlillar:
            q = catalog_auto.siyosat_qarori(h, p, s_nom)
            sanoq[q["qaror"]] += 1
            if q["qaror"] == "auto":
                qiymat[s_nom] += ochiq.get(p["id"], 0)
            elif h.get("sabab") == "kod":
                # Algoritm kod topdi, SIYOSAT to'sdi -- eng qiziq chelak.
                tushgan[s_nom].append((p, h, q))
        jadval[s_nom] = sanoq

    kenglik = max(len(x) for x in presetlar) + 2
    print(f"\n{'siyosat':<{kenglik}}{'auto':>8}{'navbat':>9}{'kodsiz':>9}"
          f"{'auto ochiq tender':>20}")
    for s_nom in presetlar:
        j = jadval[s_nom]
        print(f"{s_nom:<{kenglik}}{j['auto']:>8}{j['navbat']:>9}"
              f"{j['kodsiz']:>9}{qiymat[s_nom]:>20}")

    rnd = random.Random(20260912)
    for s_nom in presetlar:
        rows = tushgan[s_nom]
        if not rows:
            continue
        print(f"\n--- SIYOSAT TO'SGANLARI: {s_nom}  ({len(rows)} ta, "
              f"{min(namuna, len(rows))} tasi TASODIFIY) ---")
        for p, h, q in rnd.sample(rows, min(namuna, len(rows))):
            yiqilgan = [k for k, v in (q.get("tekshiruv") or {}).items() if not v]
            print(f"  {(p.get('name') or '')[:48]:<48} -> {h.get('code')}  "
                  f"ulush {h.get('confidence')}  dalil {h.get('evidence')}"
                  f"/{h.get('total')}  yiqildi: {','.join(yiqilgan)}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Moslik qoidasi -- nima bo'lardi")
    ap.add_argument("--company", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--namuna", type=int, default=8)
    ap.add_argument("--siyosat", action="store_true",
                    help="QOIDA emas, avtomatik tasdiq SIYOSATINI o'lchaydi")
    ap.add_argument("--qoida", default="",
                    help="vergul bilan; standart -- hammasi")
    args = ap.parse_args()

    db.init_pool()
    cid = args.company
    if not cid:
        from api import auth
        cid = auth.sole_company_id()
    print(f"Ijarachi: {cid}")

    if args.siyosat:
        sys.exit(olch_siyosat(cid, args.limit, args.namuna))

    qoidalar = ([q.strip() for q in args.qoida.split(",") if q.strip()]
                or list(catalog_auto.QOIDALAR))
    noma = [q for q in qoidalar if q not in catalog_auto.QOIDALAR]
    if noma:
        print(f"Noma'lum qoida: {', '.join(noma)}")
        sys.exit(1)
    sys.exit(olch(cid, qoidalar, args.limit, args.namuna))


if __name__ == "__main__":
    main()
