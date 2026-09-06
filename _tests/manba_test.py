#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: KELIB CHIQISH (provenance) — har yozuv manbaga bog'lanadi
=================================================================

`docs/legal-data-map.md` "har saqlangan ommaviy yozuvning kelib
chiqishi bor" deb da'vo qiladi. Bu sinov o'sha da'voni qo'riqlaydi:
yangi ETL yo'li kelib chiqishsiz qator yozsa — bu yerda to'xtaydi.

NEGA MUHIM: kelib chiqish yo'qolishi JIMGINA sodir bo'ladi. Qator
bazada turadi, interfeys uni ko'rsatadi, lekin "qayerdan olindi"
savoliga javob yo'q. Huquqiy tekshiruv aynan shu savoldan boshlanadi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\manba_test.py
    .venv\\Scripts\\python.exe _tests\\manba_test.py --offline
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
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
def test_statik():
    bolim("1. Havola naqshi BITTA joyda")
    sql = io.open(os.path.join(ROOT, "schema_patch_manba_url.sql"),
                  encoding="utf-8").read()
    for nom, naqsh in (
            ("`manba_url()` funksiyasi bor", "FUNCTION manba_url"),
            ("`v_tender_manba` ko'rinishi", "v_tender_manba"),
            ("`v_hujjat_manba` ko'rinishi", "v_hujjat_manba"),
            ("`v_manba_qamrov` o'lchovi", "v_manba_qamrov"),
            ("xt-xarid naqshi", "xt-xarid.uz/procedure/"),
            ("uzex naqshi", "etender.uzex.uz/lot/")):
        check(nom, naqsh in sql)

    # NOMA'LUM PLATFORMA UCHUN NULL — taxminiy havola BERILMAYDI.
    check("noma'lum platforma uchun NULL", "ELSE NULL" in sql)

    # Frontend va baza BIR XIL naqshni ishlatishi kerak. Ular
    # ajralib ketsa interfeys bir havolani, audit boshqasini
    # ko'rsatardi va qaysi biri to'g'ri ekani bilinmasdi.
    fe = io.open(os.path.join(ROOT, "frontend", "src", "format.ts"),
                 encoding="utf-8").read()
    for naqsh in ("xt-xarid.uz/procedure/", "etender.uzex.uz/lot/"):
        check(f"frontend va baza mos: `{naqsh}`", naqsh in fe and naqsh in sql)

    # MANBADAGI ASL id ishlatilsin — ichki `tender.id` manba saytida
    # MAVJUD EMAS va u bilan qurilgan havola YOLG'ON bo'lardi.
    check("manbadagi ASL id ishlatiladi (izohda sabab bor)",
          "source_id" in sql and "ofset" in sql)


def test_hujjat():
    bolim("2. Huquqiy hujjat — faktlar va NOMA'LUMLAR ajratilgan")
    yol = os.path.join(ROOT, "docs", "legal-data-map.md")
    check("`docs/legal-data-map.md` mavjud", os.path.exists(yol))
    if not os.path.exists(yol):
        return
    d = io.open(yol, encoding="utf-8").read()
    check("huquqiy xulosa BERILMAGANI aytilgan",
          "huquqiy xulosa" in d.lower() and "yuristning ishi" in d.lower())
    check("NOMA'LUMLAR bo'limi bor", "NOMA'LUM" in d)
    check("manba shartlari NOMA'LUM deb belgilangan",
          "foydalanish shartlari" in d.lower() and "noma'lum" in d.lower())
    check("tashqi AI oqimi yozilgan", "Anthropic" in d and "Telegram" in d)
    check("pullik AI holati tasdiqlangan", "paid_allowed()" in d)
    check("saqlash muddati holati aytilgan", "muddat" in d.lower())
    check("tekshirish buyruqlari berilgan", "v_manba_qamrov" in d)


# =====================================================================
def test_baza(db):
    bolim("3. Kelib chiqish QAMROVI — o'lchov")
    if not db.scalar("SELECT to_regclass('public.v_manba_qamrov') IS NOT NULL"):
        check("`schema_patch_manba_url.sql` qo'llangan", False)
        return
    qatorlar = db.query("SELECT * FROM v_manba_qamrov ORDER BY jadval")
    check("qamrov ko'rinishi qator qaytardi", len(qatorlar) >= 3,
          f"{len(qatorlar)} ta")
    for r in qatorlar:
        # HAR USTUN NOL BO'LISHI SHART. Nol emas -> kelib chiqishi
        # yo'q yozuv bor va da'vo yolg'on bo'lardi.
        for ustun in ("platformasiz", "manba_idsiz", "vaqtsiz", "urlsiz"):
            check(f"{r['jadval']}: `{ustun}` = 0",
                  (r[ustun] or 0) == 0, f"{r[ustun]} ta ({r['jami']} dan)")

    bolim("4. Havola HAQIQATAN quriladi")
    for platforma, kutilgan in (("xt-xarid", "xt-xarid.uz/procedure/"),
                                ("uzex", "etender.uzex.uz/lot/")):
        r = db.query_one(
            "SELECT ommaviy_url, manbadagi_id FROM v_tender_manba "
            "WHERE platforma = %(p)s AND ommaviy_url IS NOT NULL LIMIT 1",
            {"p": platforma})
        if not r:
            print(f"  [i] `{platforma}` uchun qator yo'q — o'tkazib yuborildi")
            continue
        check(f"`{platforma}` havolasi to'g'ri naqshda",
              kutilgan in r["ommaviy_url"], r["ommaviy_url"])
        # Havolada MANBADAGI id turishi shart, ichki id emas.
        check(f"`{platforma}` havolasida MANBADAGI id",
              str(r["manbadagi_id"]) in r["ommaviy_url"])

    # Noma'lum platforma -> NULL (taxminiy havola YO'Q).
    check("noma'lum platforma -> NULL",
          db.scalar("SELECT manba_url('yoq_bunday', 123) IS NULL"))
    check("manba id NULL -> NULL",
          db.scalar("SELECT manba_url('uzex', NULL) IS NULL"))

    bolim("5. Hujjat manbaga bog'langan")
    r = db.query_one("SELECT count(*) AS n FROM v_hujjat_manba "
                     "WHERE tender_ommaviy_url IS NULL")
    jami = db.scalar("SELECT count(*) FROM v_hujjat_manba")
    check("har hujjat tender havolasiga bog'langan", (r["n"] or 0) == 0,
          f"{r['n']} / {jami}")

    bolim("6. Pullik AI standart holatda O'CHIQ")
    from api import ai

    # JONLI QIYMAT ISHLATILMAYDI — MAJBURAN O'CHIRILADI.
    #
    # Bu bo'lim STANDART qiymatni ("o'rnatilmagan") tekshiradi, ya'ni
    # "hech kim hech narsa yozmasa, qulf YOPIQ" degan qoidani.
    # Ilgari u jonli muhitni O'QIRDI va shu sababli IKKI nuqsoni bor
    # edi:
    #
    #   1. YOLG'ON YIQILISH. 2026-09-02 da loyiha egasi pullik
    #      so'rovlarga ochiq ruxsat berdi (`.env` da
    #      `AI_PAID_ENABLED=1`). O'shandan keyin sinov yiqila
    #      boshladi — lekin qulf BUZILGANI uchun emas, aksincha u
    #      muhitni TO'G'RI hurmat qilgani uchun. Ya'ni sinov
    #      standartni emas, ishlab chiquvchining mashinasidagi
    #      sozlamani o'lchardi.
    #
    #   2. PUL. Qulf ochiq bo'lganda `ai.get_client()` haqiqiy
    #      mijozni QURADI. "O'zi pul sarflamaydigan" sinov shu yo'l
    #      bilan tashqi xizmatga chiqib qolardi.
    #
    # Naqsh `_tests/paid_guard_test.py` dan olingan (o'sha yerda
    # to'liq izoh): jonli qiymat chop etiladi, jarayon ichida
    # o'chiriladi, oxirida QAYTARILADI.
    jonli = os.environ.get(ai.PAID_ENV)
    print(f"     .env dagi {ai.PAID_ENV} = "
          f"{jonli if jonli is not None else '(o`rnatilmagan)'!r}"
          " — sinov ichida majburan o'chiriladi")
    os.environ.pop(ai.PAID_ENV, None)
    try:
        check("qiymat berilmaganda `paid_allowed()` = False",
              ai.paid_allowed() is False)
        try:
            ai.get_client()
            check("`get_client()` BLOKLANADI", False, "o'tib ketdi")
        except Exception as e:                                # noqa: BLE001
            check("`get_client()` BLOKLANADI", "BLOKLANGAN" in str(e),
                  str(e).splitlines()[0][:60])

        # CHEGARA HOLATI: qulf IKKI TOMONGA ham ishlashi kerak.
        # Busiz yuqoridagi tekshiruv `paid_allowed()` doim `False`
        # qaytarsa ham "o'tdi" bo'lib ko'rinardi — ya'ni buzuq
        # qo'rovulni ushlamasdi.
        # `get_client()` bu yerda CHAQIRILMAYDI: u haqiqiy mijoz
        # quradi va sinov pul sarflardi.
        os.environ[ai.PAID_ENV] = "1"
        check("`AI_PAID_ENABLED=1` da qulf OCHILADI",
              ai.paid_allowed() is True,
              "qo'rovul qiymatni o'qimayapti — u doim yopiq")
        os.environ[ai.PAID_ENV] = "0"
        check("`AI_PAID_ENABLED=0` da qulf YOPIQ",
              ai.paid_allowed() is False)
    finally:
        # Muhit SINOVDAN OLDINGI holatiga qaytariladi: bu funksiya
        # yagona jarayonda boshqa tekshiruvlar bilan birga yuradi.
        if jonli is None:
            os.environ.pop(ai.PAID_ENV, None)
        else:
            os.environ[ai.PAID_ENV] = jonli

    check("embedding provayderi LOKAL",
          os.environ.get("EMBED_PROVIDER", "local") == "local",
          os.environ.get("EMBED_PROVIDER", "local"))


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Kelib chiqish sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: KELIB CHIQISH VA MA'LUMOT XARITASI")
    print("=" * 70)

    test_statik()
    test_hujjat()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Bazali tekshiruvlar o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_baza(db)
        except Exception as e:                                # noqa: BLE001
            check("bazali tekshiruv", False, str(e)[:90])

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
