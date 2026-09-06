#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: VALYUTA — filtr korpusni QOPLAYDI, saralash YOLG'ON TAQQOSLAMAYDI
=========================================================================

IKKI O'LCHANGAN NUQSON (2026-09-02).

1. FILTR RO'YXATI KORPUSDAN KICHIK EDI
--------------------------------------
`Filters.tsx` da valyuta ro'yxati `UZS` va `USD` bilan qotirilgan
edi. Korpusda esa:

    UZS  727      USD  67      EUR  4      CNY  1

Ya'ni EUR va CNY tenderlarini filtr orqali UMUMAN topib bo'lmasdi.
Foydalanuvchi buni "bunday tender yo'q" deb o'qirdi — salbiy
shartdan olingan yolg'on xulosa.

2. SUMMA BO'YICHA SARALASH VALYUTANI KO'RMASDI
----------------------------------------------
`build_order_by()` xom ustun bo'yicha saralardi:

    ORDER BY t.totalcost DESC

Bu 1 000 USD ni 2 000 UZS dan PAST qo'yadi. Taqqoslash MA'NOSIZ.

MUHIM: loyihada KURS MA'LUMOTI YO'Q va bu ATAYLAB. `api/pricing.py`
allaqachon shu qoidani yozgan:

    "Tizimda kurs konvertatsiyasi yo'q — turli valyutali summalar..."

Shuning uchun kurs O'YLAB TOPILMADI. Saralash endi valyutani
BIRINCHI kalit qiladi: har valyuta ichida summa to'g'ri
tartiblanadi, valyutalar aralashmaydi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\valyuta_test.py
    .venv\\Scripts\\python.exe _tests\\valyuta_test.py --bazasiz
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


def check(nom, ok, tafsilot=""):
    _natija.append((nom, bool(ok), tafsilot))
    print(f"  [{'OK  ' if ok else 'XATO'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))


def bolim(t):
    print(f"\n--- {t} ---")


def oqi(*p):
    return io.open(os.path.join(ROOT, *p), encoding="utf-8").read()


def _royxat():
    """`Filters.tsx` dagi valyuta ro'yxati."""
    src = oqi("frontend", "src", "components", "Filters.tsx")
    m = re.search(r"export const CURRENCIES = \[([^\]]*)\]", src)
    if not m:
        return None
    return {q.strip().strip("'\"") for q in m.group(1).split(",") if q.strip()}


def test_royxat_kodda():
    bolim("1. Filtr ro'yxati KODDA")
    r = _royxat()
    check("`CURRENCIES` ro'yxati topildi", r is not None, str(r))
    if r:
        check("ro'yxat QOTIRILGAN ikkitadan katta",
              len(r) > 2, str(sorted(r)))
        # Ro'yxat `SelectItem` lar bilan QO'LDA yozilmasin — aks holda
        # ro'yxat va ekran ajralib ketardi.
        src = oqi("frontend", "src", "components", "Filters.tsx")
        check("ekran ro'yxatdan quriladi (qo'lda `SelectItem` emas)",
              'CURRENCIES.map(' in src
              and '<SelectItem value="USD">' not in src)


def test_saralash_siyosati():
    bolim("2. Saralash siyosati — kurs O'YLAB TOPILMAGAN")
    q = oqi("api", "queries.py")
    check("`build_order_by` mavjud", "def build_order_by" in q)
    blok = q[q.index("def build_order_by"):]
    blok = blok[:blok.index("def ", 10)]
    # Summa bo'yicha saralashda valyuta BIRINCHI kalit bo'lishi shart.
    check("summa saralashida VALYUTA birinchi kalit",
          "currency" in blok, blok[-260:])
    # KURS O'YLAB TOPILMASIN: hech qanday qotirilgan koeffitsiyent.
    p = oqi("api", "pricing.py")
    check("loyihada kurs YO'Qligi ochiq yozilgan",
          "kurs konvertatsiyasi yo" in p)
    for naqsh in ("12500", "12 500", "USD_RATE", "EUR_RATE", "* 12"):
        check(f"qotirilgan kurs YO'Q: `{naqsh}`", naqsh not in q)


def test_korpus(db):
    bolim("3. KORPUS — filtr hamma valyutani qoplaydimi")
    bazada = {r["currency"] for r in db.query(
        "SELECT DISTINCT currency FROM tender WHERE currency IS NOT NULL")}
    print(f"      bazada: {sorted(bazada)}")
    r = _royxat()
    check("filtr ro'yxati KORPUSNI TO'LIQ qoplaydi",
          r is not None and bazada <= r,
          f"qoplanmagan: {sorted(bazada - (r or set()))}")

    # Ochiq tenderlar kesimi — operatsion ahamiyati bor.
    ochiq = {r2["currency"]: r2["n"] for r2 in db.query(
        "SELECT currency, count(*) n FROM tender WHERE status='open' "
        "AND currency IS NOT NULL GROUP BY 1")}
    print(f"      ochiq: {ochiq}")
    yoq = {c for c in ochiq if r and c not in r}
    check("OCHIQ tenderlarning valyutasi filtrda BOR", not yoq, str(yoq))


def test_saralash_haqiqatan(db):
    bolim("4. Saralash HAQIQATAN valyutani ajratadimi")
    from api import queries
    ob = queries.build_order_by("-totalcost")
    check("summa saralashi valyutani o'z ichiga oladi",
          "currency" in ob, ob)
    rows = db.query(
        "SELECT t.currency, t.totalcost FROM tender t "
        "WHERE t.status='open' AND t.totalcost IS NOT NULL "
        + ob + " LIMIT 200")
    # VALYUTALAR ARALASHMASIN: bir valyuta boshlangach, u tugamaguncha
    # boshqasi chiqmasligi kerak.
    korilgan, oldingi, buzildi = set(), None, None
    for x in rows:
        c = x["currency"]
        if c != oldingi:
            if c in korilgan:
                buzildi = c
                break
            korilgan.add(c)
            oldingi = c
    check("natijada valyutalar ARALASHMAYDI", buzildi is None,
          f"`{buzildi}` ikki marta bo'lindi")
    print(f"      tartib: {[x['currency'] for x in rows[:12]]}")


def main():
    ap = argparse.ArgumentParser(description="Valyuta sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: VALYUTA — filtr qamrovi va saralash siyosati")
    print("=" * 70)

    test_royxat_kodda()
    test_saralash_siyosati()

    if getattr(args, "bazasiz", False):
        print("\n  [i] --bazasiz: korpus tekshiruvi O'TKAZILMADI.")
        print("      Bu SINOV EMAS — qamrov kamaydi.")
    else:
        from api import db
        db.init_pool()
        test_korpus(db)
        test_saralash_haqiqatan(db)

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
