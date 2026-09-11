#!/usr/bin/env python3
"""KOD TAKLIFI TASHXISI — nega nomzod topilmadi.

    python kod_tashxis.py --company 1 --limit 5
    python kod_tashxis.py --company 1 --product 1486

FAQAT O'QIYDI. Hech narsa yozmaydi: `taklif_yoz()` ham,
`tasdiqla()` ham chaqirilmaydi. Shuning uchun uni ishlab
chiqarishda bemalol yurgizsa bo'ladi.

--- NEGA KERAK -------------------------------------------------------
O'LCHANGAN NARX (2026-09-11). Tasdiqlash ekrani bo'sh qaytdi va
sababni topish uchun bazaga to'rt marta so'rov yuborishga to'g'ri
keldi. Har safar javob "hammasi joyida" bo'ldi:

    lug'at 910 kod · 842/842 vektor markazlangan
    SQL_SEM uchun nomzod 457 · embedder yuklangan

Ekran esa bo'sh edi. Yetishmagan narsa — `takliflar()` ni AYNAN
o'sha mahsulot uchun yurgizib, HAR SHOXNI alohida ko'rish.
Interfeys buni qila olmaydi (u faqat yakuniy ro'yxatni oladi),
bazadan ham ko'rinmaydi (naqshlar Python da quriladi).

MODEL MAHALLIY — pullik chaqiruv yo'q.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from api import db, kodlash, queries  # noqa: E402


def _mahsulotlar(company_id: int, product_id: int | None, limit: int):
    if product_id:
        p = db.query_one(queries.CATALOG_GET_SQL,
                         {"company_id": company_id, "product_id": product_id})
        return [p] if p else []
    return db.query(
        "SELECT id, name, category_code, keywords FROM catalog_product "
        "WHERE company_id = %(c)s ORDER BY id LIMIT %(n)s",
        {"c": company_id, "n": limit})


def main() -> int:
    ap = argparse.ArgumentParser(description="Kod taklifi tashxisi")
    ap.add_argument("--company", type=int, required=True)
    ap.add_argument("--product", type=int, default=0)
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()

    # HAVZA ANIQ ISHGA TUSHIRILADI. `db.query()` uni O'ZI ko'tarmaydi
    # va "DB pool ishga tushmagan" deb yiqiladi -- xabar to'g'ri,
    # lekin sabab skriptda. `catalog_kodla.py` bilan ayni qadam.
    db.init_pool()

    rows = _mahsulotlar(a.company, a.product or None, a.limit)
    if not rows:
        print("Mahsulot topilmadi.")
        return 1

    # --- MUHIT: signal ishlashi uchun kerak bo'lgan shartlar ---
    lugat = db.query_one("SELECT count(*) AS n FROM dim_good_code") or {}
    vek = db.query_one(
        "SELECT count(*) FILTER (WHERE embedding_c IS NOT NULL) AS n "
        "FROM good_code_embedding") or {}
    sem = db.query_one(
        "SELECT count(*) AS n FROM good_code_embedding ge "
        "JOIN dim_good_code d ON d.code = ge.code "
        "WHERE ge.embedding_c IS NOT NULL AND d.level = 8 "
        "  AND d.n_tender_open > 0") or {}
    print(f"lug'at {lugat.get('n', 0)} kod · markazlangan vektor "
          f"{vek.get('n', 0)} · SQL_SEM nomzodi {sem.get('n', 0)}")
    print("-" * 70)

    for p in rows:
        pd = dict(p)
        print(f"\n#{pd['id']}  {str(pd.get('name'))[:58]}")
        print(f"  kategoriya : {pd.get('category_code') or '(yo`q)'}")
        kw = pd.get("keywords") or []
        print(f"  kalit so'z : {len(kw)} ta")

        # NAQSHLAR — leksik shox aynan shulardan qidiradi.
        juft = kodlash._lexical_patterns(pd)
        yolgiz = [n for n, _g in juft if " " not in n]
        print(f"  naqsh      : {len(juft)} ta "
              f"(so'z darajasi: {len(yolgiz)})")
        if juft:
            print(f"               {', '.join(n for n, _g in juft[:6])}")

        qmatn = kodlash._query_text(pd)
        print(f"  so'rov matni uzunligi: {len(qmatn)}")

        for daraja, nom in ((8, "aniq"), (5, "keng")):
            tx: dict = {}
            natija = kodlash.takliflar(pd, level=daraja, limit=6, tashxis=tx)
            print(f"  [{nom}] nomzod={len(natija)}  "
                  f"leksik={tx.get('leksik')}  semantik={tx.get('semantik')}")
            for x in natija[:3]:
                print(f"         {x['code']:<10} {str(x['name_ru'])[:34]:<34} "
                      f"ochiq={x['n_tender_open']}  {','.join(x['signallar'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
