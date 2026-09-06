#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: DB HOVUZI — band bo'lish 503 GA aylanmasin
==================================================

O'LCHANGAN NUQSON (2026-09-02). "Sizga mos" sahifasida
`POST /catalog/seen` takror-takror **503** berardi.

SABAB. `ThreadedConnectionPool.getconn()` hovuz to'lgan bo'lsa
DARHOL `PoolError` chiqaradi. U `psycopg2.Error` avlodi, ya'ni
`DBUnavailable` ga o'raladi va mijozga 503 ketadi. Foydalanuvchi
buni "server ishlamayapti" deb o'qiydi -- aslida server
ISHLAYAPTI, shunchaki band edi.

O'LCHANDI (tuzatishdan oldin):

    12 parallel so'rov, hovuz 8 ta  ->  4 tasi DARHOL 503

Sahifa bir necha so'rovni birga yuboradi va ular BIR-BIRINI
yiqitardi. FastAPI sync-endpointlarni ~40 ipda yuritadi, DB
hovuzi esa 8 ta -- ya'ni 32 ip hech qachon ulanish ola olmasdi.

TUZATISH: hovuz bo'shashini `DB_POOL_WAIT_SEC` gacha KUTADI.

KUTISH -- YASHIRISH EMAS. Chegara tugagach xato BARIBIR
chiqariladi va xabar SABABINI aytadi ("band"), toza `PoolError`
emas. Haqiqiy ortiqcha yuklama ko'rinib turishi kerak -- aks
holda bu tuzatish nosozlikni yashirgan bo'lardi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\hovuz_test.py
    .venv\\Scripts\\python.exe _tests\\hovuz_test.py --bazasiz
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import threading
import time

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


def test_kod():
    bolim("1. KOD — hovuz KUTADIMI")
    src = io.open(os.path.join(ROOT, "api", "db.py"), encoding="utf-8").read()
    check("`PoolError` ALOHIDA ushlanadi", "except PoolError" in src)
    check("kutish MUDDATI bor", "DB_POOL_WAIT_SEC" in src)
    # "Hovuz to'la" DAN BOSHQA `PoolError` ni kutish MA'NOSIZ --
    # u boshqa nosozlik (masalan hovuz yopilgan).
    check("faqat `exhausted` holati kutiladi",
          '"exhausted" not in str(e).lower()' in src)
    # ENG MUHIMI: chegara tugagach xato YUTILMASIN.
    check("chegara tugagach xato CHIQARILADI",
          "bo'shamadi" in src and "raise DBUnavailable" in src)
    check("xabar SABABINI aytadi (`band`)", "band" in src)


def test_haqiqiy_yuk(db):
    bolim("2. HAQIQIY PARALLEL YUK")
    import psycopg2.pool

    mx = int(os.environ.get("DB_POOL_MAX", "8"))
    print(f"      hovuz o'lchami: {mx}")

    xatolar = []
    tayyor = threading.Barrier(mx * 2)

    def yur():
        # HAMMASI BIR VAQTDA uradi -- aks holda sinov hovuzni
        # to'ldirmasdan o'tib ketardi va HECH NARSANI o'lchamasdi.
        tayyor.wait()
        try:
            db.scalar("SELECT pg_sleep(0.25), 1")
        except Exception as e:                               # noqa: BLE001
            xatolar.append(str(e)[:90])

    th = [threading.Thread(target=yur) for _ in range(mx * 2)]
    t0 = time.perf_counter()
    for x in th:
        x.start()
    for x in th:
        x.join()
    ketdi = time.perf_counter() - t0

    # Hovuzdan IKKI BARAVAR ko'p so'rov -- kutishsiz yarmi
    # DARHOL yiqilardi.
    check(f"hovuzdan 2x ko'p so'rov ({mx * 2} ta) XATOSIZ o'tdi",
          not xatolar, f"{len(xatolar)} xato: {xatolar[:2]}")
    # Kutish HAQIQATAN bo'lganini isbotlaydi: bitta to'lqin
    # 0.25s, ikkinchisi ham -- ya'ni ~0.5s dan kam bo'lolmaydi.
    check("so'rovlar NAVBATDA kutdi (bir vaqtda hammasi emas)",
          ketdi >= 0.4, f"{ketdi:.2f}s")


def test_haqiqiy_ortiqcha(db):
    bolim("3. HAQIQIY ORTIQCHA YUKLAMA YASHIRILMAYDI")
    # Kutish chegarasini QISQA qilib, haqiqiy tiqilishni yuzaga
    # keltiramiz. Xato CHIQISHI SHART -- aks holda tuzatish
    # nosozlikni yashirgan bo'lardi.
    eski = db._KUTISH_SEK
    db._KUTISH_SEK = 0.2
    xatolar = []
    mx = int(os.environ.get("DB_POOL_MAX", "8"))
    tayyor = threading.Barrier(mx * 3)

    def yur():
        tayyor.wait()
        try:
            db.scalar("SELECT pg_sleep(1.0), 1")
        except Exception as e:                               # noqa: BLE001
            xatolar.append(str(e)[:90])

    th = [threading.Thread(target=yur) for _ in range(mx * 3)]
    try:
        for x in th:
            x.start()
        for x in th:
            x.join()
    finally:
        db._KUTISH_SEK = eski

    check("chegara tugagach xato CHIQDI (yutilmadi)",
          len(xatolar) > 0, f"{len(xatolar)} xato")
    check("xato xabari SABABINI aytadi",
          any("bo'shamadi" in e or "band" in e for e in xatolar),
          xatolar[0] if xatolar else "")


def main():
    ap = argparse.ArgumentParser(description="DB hovuzi sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: DB HOVUZI — band bo'lish 503 ga aylanmasin")
    print("=" * 70)

    test_kod()

    if getattr(args, "bazasiz", False):
        print("\n  [i] --bazasiz: parallel yuk O'LCHANMADI.")
        print("      Bu SINOV EMAS — asosiy tekshiruv aynan shu.")
    else:
        from api import db
        db.init_pool()
        test_haqiqiy_yuk(db)
        test_haqiqiy_ortiqcha(db)

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
