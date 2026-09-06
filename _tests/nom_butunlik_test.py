#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: ANIQLANMAGAN NOM — "hech qachon bajarilmagan endpoint"
==============================================================

O'LCHANGAN NUQSON (2026-09-02). Ikkita endpoint HTTP 500 berardi va
ikkalasi ham AYNI sinfdan edi — kod hech qachon BAJARILMAGAN:

    POST /tenders/{id}/ai-match
        `company_id` 1806-qatorda ISHLATILARDI,
        1818-qatorda ANIQLANARDI  ->  UnboundLocalError

    POST /tenders/{id}/pricing
        funksiyada `request` parametri YO'Q edi,
        lekin ichida `company_id_of(request)`  ->  NameError

Ikkalasi ham import paytida ko'rinmaydi (Python nomlarni ijro
paytida bog'laydi) va ikkalasi ham sinov bilan qoplanmagan edi.
Ya'ni "yozildi" va "ishlaydi" orasidagi farq HECH NARSA bilan
tekshirilmasdi.

BU SINOV BUTUN SINFNI USHLAYDI, ikkita nuqsonni emas: har
funksiyada aniqlanmagan yoki aniqlanishdan OLDIN o'qilgan nom
qidiriladi.

TEKSHIRUVCHINING O'ZI SINALADI (5-bo'lim). Aks holda u hech
narsa topmasa ham sinov YASHIL bo'lardi — bu loyihadagi eng
takrorlangan nuqson sinfi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\nom_butunlik_test.py
"""
from __future__ import annotations

import argparse
import ast
import builtins
import glob
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, bool(ok), tafsilot))
    print(f"  [{'OK  ' if ok else 'XATO'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))


def bolim(t):
    print(f"\n--- {t} ---")


_BUILTIN = set(dir(builtins)) | {
    # Modul dunder'lari — har modulda mavjud.
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__class__",
}
_FN = (ast.FunctionDef, ast.AsyncFunctionDef)


def _params(fn):
    a = fn.args
    out = {p.arg for p in
           list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
    if a.vararg:
        out.add(a.vararg.arg)
    if a.kwarg:
        out.add(a.kwarg.arg)
    return out


def _tanani_yur(node):
    """Funksiya TANASI — ichki funksiya/lambda/class larsiz."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.Lambda, ast.ClassDef) + _FN):
            continue
        yield child
        yield from _tanani_yur(child)


def _stores(fn):
    """Shu funksiyada tayinlanadigan nomlar -> eng erta qator."""
    out = {}
    def qo(nom, ln):
        out.setdefault(nom, []).append(ln)
    for n in _tanani_yur(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            qo(n.id, n.lineno)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                qo((a.asname or a.name).split(".")[0], n.lineno)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            qo(n.name, n.lineno)
    # Ichki funksiya/class NOMI ham shu qamrovda tayinlanadi.
    for child in ast.iter_child_nodes(fn):
        pass
    for n in ast.walk(fn):
        if n is fn:
            continue
        if isinstance(n, _FN + (ast.ClassDef,)):
            qo(n.name, n.lineno)
    for p in _params(fn):
        qo(p, fn.lineno)
    return out


def _modul_nomlari(tree):
    nomlar = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                nomlar.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, _FN + (ast.ClassDef,)):
            nomlar.add(node.name)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            hedef = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in hedef:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        nomlar.add(n.id)
        elif isinstance(node, (ast.Try, ast.If, ast.For, ast.While, ast.With)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    nomlar.add(sub.id)
    return nomlar


def tekshir(yol):
    tree = ast.parse(io.open(yol, encoding="utf-8").read())
    globallar = _modul_nomlari(tree)
    nuqsonlar = []

    def yur(fn, tashqi):
        """`tashqi` — qamrov zanjiridagi mavjud nomlar."""
        stores = _stores(fn)
        korinadi = set(tashqi) | set(stores)
        glob = set()
        for n in _tanani_yur(fn):
            if isinstance(n, (ast.Global, ast.Nonlocal)):
                glob.update(n.names)

        # Sikl/comprehension ichidagi yuklama tartib bo'yicha
        # tekshirilmaydi: sikl oxirida tayinlangan nom keyingi
        # aylanishda to'g'ri o'qiladi.
        sikl = set()
        for n in _tanani_yur(fn):
            if isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.Try,
                              ast.ListComp, ast.SetComp, ast.DictComp,
                              ast.GeneratorExp)):
                for sub in ast.walk(n):
                    sikl.add(id(sub))

        for n in _tanani_yur(fn):
            if not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)):
                continue
            nom = n.id
            if nom in _BUILTIN or nom in globallar or nom in glob:
                continue
            if nom not in korinadi:
                nuqsonlar.append((fn.name, n.lineno, nom, "ANIQLANMAGAN"))
            elif (nom in stores and nom not in tashqi
                  and id(n) not in sikl and min(stores[nom]) > n.lineno):
                nuqsonlar.append((fn.name, n.lineno, nom,
                                  f"ANIQLANISHDAN OLDIN (tayinlash {min(stores[nom])})"))

        for child in ast.walk(fn):
            if child is fn:
                continue
            if isinstance(child, _FN):
                # Ichki funksiya TASHQI qamrovni ko'radi.
                yur(child, korinadi)

    for node in tree.body:
        if isinstance(node, _FN):
            yur(node, set())
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, _FN):
                    yur(sub, set())
    return nuqsonlar


# =====================================================================
# TEKSHIRUVCHINING O'ZI SINALADI
# =====================================================================
#: Ikki YOMON naqsh — ikkalasi ham HAQIQATDA yuz bergan.
_YOMON = '''
import os


def aniqlanishdan_oldin(a):
    print(kirish)
    kirish = 1


def umuman_aniqlanmagan(a):
    return company_id_of(request)
'''

#: To'rtta QONUNIY naqsh. Ular yiqilsa tekshiruvchi ishlatib
#: bo'lmas darajada shovqinli bo'lardi — birinchi urinishda AYNAN
#: shunday bo'lgan edi (126 ta soxta topilma, hammasi yopilma).
_YAXSHI = '''
import os


def oddiy(a):
    x = 1
    return x + a


def yopilma(a):
    korilgan = set()

    def ichki(b):
        return b in korilgan
    return ichki(a)


def siklda_yigish(items):
    jami = 0
    for it in items:
        jami = jami + it
    return jami


def try_except_ichida(p):
    try:
        v = os.path.join(p)
    except OSError:
        v = None
    return v
'''


def _vaqtinchalik(matn, nom):
    yol = os.path.join(ROOT, "_tests", nom)
    io.open(yol, "w", encoding="utf-8", newline=chr(10)).write(matn)
    return yol


def test_tekshiruvchi():
    bolim("1. TEKSHIRUVCHI HAQIQATAN TOPADIMI")
    yol = _vaqtinchalik(_YOMON, "_zz_yomon_namuna.txt")
    try:
        topildi = tekshir(yol)
    finally:
        os.remove(yol)
    turlar = {nom: tur for _fn, _ln, nom, tur in topildi}
    check("`aniqlanishdan oldin` naqshi TOPILDI",
          "kirish" in turlar and "OLDIN" in turlar["kirish"], str(turlar))
    check("`aniqlanmagan nom` naqshi TOPILDI",
          "request" in turlar and turlar["request"] == "ANIQLANMAGAN",
          str(turlar))

    bolim("2. SOXTA SIGNAL BERMAYDIMI")
    yol = _vaqtinchalik(_YAXSHI, "_zz_yaxshi_namuna.txt")
    try:
        soxta = tekshir(yol)
    finally:
        os.remove(yol)
    # QAMROV ZANJIRI eng muhimi: ichki funksiya tashqi nomni ko'radi.
    check("qonuniy naqshlarda TOPILMA YO'Q (yopilma, sikl, try)",
          not soxta, str(soxta))


def test_kod_bazasi():
    bolim("3. KOD BAZASI TOZAMI")
    yollar = []
    for kok in ("api",):
        for dirpath, _d, files in os.walk(os.path.join(ROOT, kok)):
            if "__pycache__" in dirpath:
                continue
            yollar += [os.path.join(dirpath, f) for f in sorted(files)
                       if f.endswith(".py")]
    yollar += sorted(glob.glob(os.path.join(ROOT, "*.py")))
    yollar += sorted(glob.glob(os.path.join(ROOT, "_tests", "*.py")))

    check("skanerlanadigan fayl BOR", len(yollar) > 30, f"{len(yollar)} fayl")

    nuqsonlar = []
    for yol in yollar:
        for fn, ln, nom, tur in tekshir(yol):
            nuqsonlar.append(f"{os.path.relpath(yol, ROOT)}:{ln} {fn}() "
                             f"`{nom}` {tur}")
    check("aniqlanmagan / erta o'qilgan nom YO'Q",
          not nuqsonlar, "; ".join(nuqsonlar[:4]))


def test_ikki_nuqson():
    """Topilgan IKKI nuqson qaytib kelmasin."""
    bolim("4. TUZATILGAN IKKI ENDPOINT")
    src = io.open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()

    # --- ai-match: ijarachi ISHLATILISHDAN OLDIN aniqlansin ---
    i = src.index("def ai_match_tender(")
    blok = src[i:src.index("@app.", i + 10)]
    aniq = blok.index("company_id = company_id_of(request)")
    ishlat = blok.index('{"company_id": company_id}')
    check("ai-match: `company_id` ISHLATISHDAN OLDIN aniqlanadi",
          aniq < ishlat, f"aniqlash={aniq} ishlatish={ishlat}")
    # SERVICE kaliti yo'lini ham hal qiladigan standart chaqiruv.
    check("ai-match: `company_id_of()` ishlatiladi (ERP yo'li ham to'g'ri)",
          "current_account(request)[\"id\"]" not in blok)

    # --- pricing: `request` PARAMETR sifatida bo'lsin ---
    j = src.index("def post_tender_pricing(")
    imzo = src[j:src.index(":", src.index(")", j))]
    check("pricing: `request` PARAMETR sifatida qabul qilinadi",
          "request: Request" in imzo, imzo[:110])


def main():
    ap = argparse.ArgumentParser(description="Nom butunligi sinovi")
    rejim.bayroqlar(ap)
    rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: ANIQLANMAGAN NOM (hech qachon bajarilmagan kod)")
    print("=" * 70)

    test_tekshiruvchi()
    test_kod_bazasi()
    test_ikki_nuqson()

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
