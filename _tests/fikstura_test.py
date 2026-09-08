#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`_tests/fikstura.py` — umumiy fikstura yordamchisining O'ZI.

NEGA YORDAMCHIGA SINOV KERAK
============================
Bu modul ettita to'plamga domen holati beradi. Undagi jimgina nuqson
ettita joyda "sinov ma'lumoti yo'q" bo'lib ko'rinardi va har safar
boshqa sababga yoziladi. Ya'ni yordamchi sinovsiz bo'lsa, u nosozlikni
TARQATADI.

ENG MUHIM TEKSHIRUV — TOZALASH. Qoldiq qolsa darvozaning sizish
qo'riqchasi ("faol zz* hisoblar") qizil beradi va buni KEYINGI
to'plamlar ko'radi, ya'ni ayb boshqa joyga yozilardi.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import fikstura  # noqa: E402
from api import db  # noqa: E402

konsol.sozla()

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


def _son(sql, args=None):
    return db.scalar(sql, args or {})


def test_yaratish_va_tozalash():
    bolim("1. Yaratadi, keyin IZSIZ tozalaydi")

    oldin_hisob = _son("SELECT count(*) FROM company_account "
                       "WHERE username LIKE %(p)s", {"p": fikstura.PREFIKS + "%"})
    check("boshlanishda qoldiq yo'q", oldin_hisob == 0, f"{oldin_hisob} ta")

    with fikstura.Domen(db) as f:
        cid = f.kompaniya("a")
        check("kompaniya yaratildi", isinstance(cid, int) and cid > 0, str(cid))

        # `company_id=2` TAXMINI YO'Q: qaytgan ID ishlatiladi.
        check("qaytgan ID haqiqiy qatorga tegishli",
              _son("SELECT count(*) FROM company_account WHERE id=%(c)s",
                   {"c": cid}) == 1)

        tid = f.tender(0)
        check("tender yaratildi",
              _son("SELECT count(*) FROM tender WHERE id=%(t)s", {"t": tid}) == 1,
              str(tid))

        f.pozitsiya(tid, "zzfix_mahsulot", amount_text="500.00 шт")
        check("pozitsiya miqdori SINOVNIKI",
              db.scalar("SELECT amount_text FROM tender_item "
                        "WHERE tender_id=%(t)s", {"t": tid}) == "500.00 шт")

        pid = f.mahsulot(cid, "m", stock_qty=200)
        check("mahsulot yaratildi",
              _son("SELECT count(*) FROM catalog_product WHERE id=%(p)s",
                   {"p": pid}) == 1, str(pid))

        f.yonaltirish(cid, tid, ai_qaror="no_go")
        check("`no_go` yo'naltirish bor",
              _son("SELECT count(*) FROM tender_routing "
                   "WHERE tender_id=%(t)s AND ai_qaror='no_go'", {"t": tid}) == 1)

        # `kod_tasdigi` QATLAMI — lug'at bo'sh bo'lsa HALOL aytiladi.
        kod = f.kod_taklifi(cid, pid)
        if kod is None:
            check("kod lug'ati bo'sh — qatlam O'LCHANMADI (soxta kod yaratilmadi)",
                  True, "dim_good_code bo'sh")
        else:
            check("`kod_tasdigi` qatori bor",
                  _son("SELECT count(*) FROM catalog_product_code "
                       "WHERE product_id=%(p)s", {"p": pid}) == 1, kod)

    # --- CHIQISHDA HAMMASI O'CHGAN ---
    for jadval, sql, args in [
            ("company_account",
             "SELECT count(*) FROM company_account WHERE username LIKE %(p)s",
             {"p": fikstura.PREFIKS + "%"}),
            ("tender",
             "SELECT count(*) FROM tender WHERE source_platform='zzfix'", {}),
            ("catalog_product",
             "SELECT count(*) FROM catalog_product WHERE name LIKE %(p)s",
             {"p": fikstura.PREFIKS + "%"})]:
        n = _son(sql, args)
        check(f"tozalandi: {jadval}", n == 0, f"{n} ta qoldi")


def test_istisnoda_ham_tozalanadi():
    bolim("2. ISTISNO bo'lsa ham tozalanadi")

    # Yordamchi `finally` ga tayanadi. Agar u ishlamasa, qoldiq
    # KEYINGI to'plamga o'tadi va ayb o'sha yerga yozilardi.
    try:
        with fikstura.Domen(db) as f:
            f.kompaniya("b")
            f.tender(1)
            raise RuntimeError("ataylab")
    except RuntimeError:
        pass

    n = _son("SELECT count(*) FROM company_account WHERE username LIKE %(p)s",
             {"p": fikstura.PREFIKS + "%"})
    check("istisnodan keyin hisob qolmadi", n == 0, f"{n} ta")
    n = _son("SELECT count(*) FROM tender WHERE source_platform='zzfix'")
    check("istisnodan keyin tender qolmadi", n == 0, f"{n} ta")


def test_darvoza_qoriqchasi_koradi():
    bolim("3. Prefiks darvoza qo'riqchasiga MOS")

    # Darvoza `zz` bilan boshlanadigan FAOL hisoblarni sanaydi. Agar
    # fikstura boshqa prefiks ishlatsa, tozalanmagan qoldiq JIM
    # qolardi -- qo'riqcha uni ko'rmasdi.
    check("prefiks `zz` bilan boshlanadi",
          fikstura.PREFIKS.startswith("zz"), fikstura.PREFIKS)

    # Tender identifikatori haqiqiy diapazondan uzoq bo'lsin.
    eng_katta = _son("SELECT COALESCE(max(id), 0) FROM tender "
                     "WHERE source_platform <> 'zzfix'") or 0
    check("sinov tender ID si haqiqiy diapazondan YUQORI",
          fikstura.TENDER_BAZA > eng_katta,
          f"fikstura={fikstura.TENDER_BAZA} korpus_max={eng_katta}")


def main():
    print("=" * 70)
    print("FIKSTURA YORDAMCHISI")
    print("=" * 70)
    db.init_pool()
    try:
        test_yaratish_va_tozalash()
        test_istisnoda_ham_tozalanadi()
        test_darvoza_qoriqchasi_koradi()
    finally:
        # OXIRGI ZAXIRA: sinovning o'zi yiqilsa ham qoldiq qolmasin.
        fikstura.Domen(db).tozala()

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
