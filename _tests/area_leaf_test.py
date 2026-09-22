#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SINOV: NOMA'LUM `area_leaf_id` BUTUN PAKETNI YO'QOTMASIN

--- O'LCHANGAN NOSOZLIK (ishlab chiqarish, 2026-09-22) ----------------
    DETAIL: Key (area_leaf_id)=(33.34.35.89.90.91) is not present
            in table "dim_area".

Manba KO'P HUDUDLI tenderni yubordi: `33.34.35.89.90.91` -- ierarxik
yo'l emas, olti alohida viloyat kodi. `dim_area` ierarxiyani saqlaydi
(`33.2137.2138.2140`) va bunday BIRIKMA u yerda hech qachon bo'lmaydi.

OQIBATI NOMUTANOSIB: `load_to_db` BITTA tranzaksiya. Bitta yaroqsiz
qiymat butun paketni qaytardi -- 168 yozuvdan HAMMASI yozilmay qoldi,
va soatlik ETL `baza_xato` bilan to'xtab turdi. Ekranda "ETL xatosi"
belgisi, `etl_coverage_test` qizil, reliz darvozasi yopiq.

--- NIMA QO'RIQLANADI ------------------------------------------------
  1. noma'lum qiymat NULL ga tushadi (paket saqlanadi);
  2. MA'LUM qiymat TEGILMAYDI -- tuzatish yaxshi ma'lumotni yemasin;
  3. `area_path` YO'QOLMAYDI -- xom qiymat keyinchalik kerak bo'ladi;
  4. soxta `dim_area` qatori YARATILMAYDI -- "noma'lum noma'lumligicha
     qoladi"; bunday hudud YO'Q va uni o'ylab topish yolg'on bo'lardi.

CHIQISH KODI: 0 -- muvaffaqiyat; 1 -- xato.
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pass_ = 0
fail_ = 0


def check(nom: str, ok: bool, tafsilot: str = "") -> bool:
    global pass_, fail_
    if ok:
        pass_ += 1
        print(f"  [PASS] {nom}")
    else:
        fail_ += 1
        print(f"  [FAIL] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


class SoxtaKursor:
    """`dim_area` da FAQAT ierarxik yo'llar bor."""

    MALUM = {"33.2137.2138.2140", "34.10.11"}

    def __init__(self):
        self.natija = []
        self.sorovlar = []

    def execute(self, sql, params=None):
        self.sorovlar.append((sql, params))
        soralgan = list((params or ([],))[0])
        self.natija = [(a,) for a in soralgan if a in self.MALUM]

    def fetchall(self):
        return self.natija


def main() -> int:
    print("=" * 70)
    print("NOMA'LUM AREA_LEAF_ID -- PAKET SAQLANADI")
    print("=" * 70)

    import etl_tenders as E

    tenders = [
        {"id": 1, "area_path": "33.2137.2138.2140",
         "area_leaf_id": "33.2137.2138.2140"},
        # KO'P HUDUDLI -- aynan ishlab chiqarishda uchragan qiymat.
        {"id": 2, "area_path": "33.34.35.89.90.91",
         "area_leaf_id": "33.34.35.89.90.91"},
        {"id": 3, "area_path": "34.10.11", "area_leaf_id": "34.10.11"},
        {"id": 4, "area_path": None, "area_leaf_id": None},
    ]
    cur = SoxtaKursor()
    n = E.area_tozala(cur, tenders)

    check("noma'lum qiymat NULL ga tushdi",
          tenders[1]["area_leaf_id"] is None, str(tenders[1]))
    check("qaytgan sanoq to'g'ri (1 ta tender)", n == 1, str(n))
    check("MA'LUM qiymat TEGILMADI (#1)",
          tenders[0]["area_leaf_id"] == "33.2137.2138.2140")
    check("MA'LUM qiymat TEGILMADI (#3)",
          tenders[2]["area_leaf_id"] == "34.10.11")
    check("`area_path` XOM holicha qoldi",
          tenders[1]["area_path"] == "33.34.35.89.90.91")
    check("NULL qiymat muammo tug'dirmaydi",
          tenders[3]["area_leaf_id"] is None)

    # SOXTA QATOR YARATILMASIN: funksiya `dim_area` ga YOZMAYDI.
    yozuv = [s for s, _ in cur.sorovlar
             if re.search(r"\b(INSERT|UPDATE|DELETE)\b", s, re.I)]
    check("`dim_area` ga YOZILMAYDI (soxta hudud yaratilmaydi)",
          not yozuv, str(yozuv[:1]))

    # CHAQIRUV tender INSERT idan OLDIN turishi shart.
    #
    # MATN QIDIRUVI EMAS, AST. Ilgari bu yerda
    # `kod.find("area_tozala(cur, tenders)")` turardi va u
    # `def area_tozala(cur, tenders)` SATRINI topardi -- ya'ni
    # chaqiruv butunlay o'chirilganda ham YASHIL berardi. Mutatsiya
    # buni ochib berdi: chaqiruv olib tashlandi, sinov 8/8 qoldi.
    import ast
    src = io.open(os.path.join(ROOT, "etl_tenders.py"), encoding="utf-8").read()
    daraxt = ast.parse(src)
    fn = next((n for n in ast.walk(daraxt)
               if isinstance(n, ast.FunctionDef) and n.name == "load_to_db"), None)
    check("`load_to_db` topildi", fn is not None)
    chaqiruv = [n.lineno for n in ast.walk(fn or ast.Module(body=[], type_ignores=[]))
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "area_tozala"]
    check("`load_to_db` ichida `area_tozala` CHAQIRILADI",
          bool(chaqiruv), str(chaqiruv))
    ins = [n.lineno for n in ast.walk(fn or ast.Module(body=[], type_ignores=[]))
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and "INSERT INTO tender (" in n.value]
    check("tender INSERT topildi", bool(ins), str(ins))
    check("tozalash INSERT dan OLDIN",
          bool(chaqiruv) and bool(ins) and min(chaqiruv) < min(ins),
          f"{chaqiruv} / {ins}")

    print("\n" + "=" * 70)
    print(f"NATIJA: {pass_}/{pass_ + fail_} o'tdi")
    print("=" * 70)
    return 1 if fail_ else 0


if __name__ == "__main__":
    sys.exit(main())
