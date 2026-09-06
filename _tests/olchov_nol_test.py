#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SKANER: O'LCHOV MAYDONI `?? 0` BILAN NOLGA AYLANTIRILMASIN
===========================================================

O'LCHANGAN MUAMMO (2026-09-04). Broker ekranida `review: 0.0%`
turgan edi va u UCH QATLAMNING birgalikdagi natijasi:

    1. `v_routing_agreement` formulasi `review` ni qamramaydi
       -> nol STRUKTURA bo'yicha kafolatlangan;
    2. `MOSLIK_MIN` darvozasi JAMIGA qo'yilgan, qatorga emas
       -> 7 ta kuzatuvdan `71.4%` chiqardi;
    3. frontend `{r.moslik_foiz ?? 0}%` qilardi
       -> NULL ham `0%` bo'lib ko'rinardi.

Uchtasi ham alohida kichik. Birgalikda — inson qaroriga ta'sir
qiladigan, ISHONCHLI KO'RINADIGAN noto'g'ri raqam.

Bu skaner UCHINCHI qatlamni qulflaydi: o'lchov maydoni (`foiz`,
`median`, `avg`, `score`, `ball`, `rate`) `?? 0` yoki `|| 0`
bilan nolga aylantirilmaydi.

SANOQ MAYDONI BUNDAN MUSTASNO. `doc_count ?? 0`, `lots.length || 0`
QONUNIY: yo'q ro'yxatda haqiqatan nol element bor. Farq shundaki,
o'lchov "hisoblanmadi" degan uchinchi holatga EGA, sanoq esa yo'q.

IKKI TOMONGA ADASHADI — ikkalasi ham yomon:

    median_hours ?? 0  ->  "0 soat kechikish"  = ENG YAXSHI natija
    score ?? 0         ->  "0/100 moslik"      = ENG YOMON natija

QAMROV AYTILADI (9-sinf). Skaner nechta faylni ko'rgani va nechta
nomzod ifoda tekshirilgani chop etiladi: `0 buzilish` bilan
`0 fayl, 0 buzilish` bir xil ko'rinmasin.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\olchov_nol_test.py
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

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
#: O'LCHOV MAYDONI NOMLARI. Ro'yxat KENG: soxta topilma skanerni
#: shovqinli qiladi, lekin o'tkazib yuborilgan o'lchov JIMGINA
#: noto'g'ri raqam beradi. Ikkinchisi qimmatroq.
OLCHOV = re.compile(
    r"(foiz|pct|percent|median|mediana|avg|ortacha|score|ball"
    r"|rate|sur.?at|kechikish|lag)", re.IGNORECASE)

#: `X ?? 0` yoki `X || 0`. `0.5`, `0px` kabi davomlar TUTILMAYDI.
NOLGA = re.compile(r"([A-Za-z_$][\w.?\[\]$]*)\s*(\?\?|\|\|)\s*0(?![.\w])")

#: Blok izohlar. Skaner NASRNI O'QIMAYDI (9-sinf) — aks holda
#: nuqsonni TASVIRLAGAN izoh skanerni yiqitardi. Bu shu sessiyada
#: haqiqatan sodir bo'ldi.
BLOK_IZOH = re.compile(r"/\*.*?\*/", re.DOTALL)


def _fayllar():
    baza = os.path.join(ROOT, "frontend", "src")
    for dp, dirs, fs in os.walk(baza):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in fs:
            if not f.endswith((".ts", ".tsx")):
                continue
            # Sinov fayllari ATAYLAB tashqarida: ular soxta
            # qiymatlarni ataylab yasaydi.
            if ".test." in f:
                continue
            yield os.path.join(dp, f)


def skaner():
    """(buzilishlar, korilgan_fayl, korilgan_ifoda) qaytaradi."""
    buzilish, n_fayl, n_ifoda = [], 0, 0
    for p in _fayllar():
        n_fayl += 1
        src = BLOK_IZOH.sub(" ", io.open(p, encoding="utf-8").read())
        for i, ln in enumerate(src.split("\n"), 1):
            if ln.lstrip().startswith("//"):
                continue
            for m in NOLGA.finditer(ln):
                n_ifoda += 1
                if OLCHOV.search(m.group(1)):
                    buzilish.append(
                        (os.path.relpath(p, ROOT), i, m.group(0).strip()))
    return buzilish, n_fayl, n_ifoda


# =====================================================================
def test_skaner_ozini_sinaydi():
    bolim("1. Skaner O'ZINI sinaydi")
    # TUTISHI SHART.
    for matn, izoh in [
            ("{data.median_hours ?? 0}", "mediana"),
            ("scoreClass(m?.score ?? 0)", "ball"),
            ("const p = r.moslik_foiz ?? 0", "foiz"),
            ("x.within_1h_pct || 0", "pct"),
    ]:
        m = NOLGA.search(matn)
        check(f"TUTADI: {izoh}",
              bool(m) and bool(OLCHOV.search(m.group(1))), matn)

    # TUTMASLIGI SHART — sanoq maydoni QONUNIY.
    for matn, izoh in [
            ("{t.doc_count ?? 0}", "sanoq"),
            ("lots?.length ?? 0", "ro'yxat uzunligi"),
            ("{value || 0}%", "umumiy nom — o'lchov emas"),
            ("q.aktorli ?? 0", "aktor soni"),
    ]:
        m = NOLGA.search(matn)
        check(f"TUTMAYDI: {izoh}",
              not m or not OLCHOV.search(m.group(1)), matn)

    # IZOHNI O'QIMAYDI (9-sinf).
    izohli = "/* ilgari bu yerda `median_hours ?? 0` turardi */\nconst a = 1"
    check("skaner NASRNI o'qimaydi",
          not NOLGA.search(BLOK_IZOH.sub(" ", izohli)))


def test_qamrov():
    bolim("2. Qamrov — skaner NECHTA narsani ko'rdi")
    buzilish, n_fayl, n_ifoda = skaner()
    print(f"        {n_fayl} fayl, {n_ifoda} ta `?? 0` / `|| 0` ifodasi")
    # `0 buzilish` va `0 fayl, 0 buzilish` BIR XIL KO'RINMASIN.
    check("skaner fayllarni ko'rdi", n_fayl >= 30, f"{n_fayl} fayl")
    check("nomzod ifodalar topildi", n_ifoda >= 10, f"{n_ifoda} ifoda")


def test_buzilish_yoq():
    bolim("3. O'lchov maydoni nolga aylantirilmagan")
    buzilish, _, _ = skaner()
    for f, i, kod in buzilish:
        print(f"        {f}:{i}  {kod}")
    check("o'lchov maydonida `?? 0` YO'Q", not buzilish,
          f"{len(buzilish)} ta topildi")


def test_tuzatilganlar():
    bolim("4. Tuzatilgan uch joy QAYTMAGAN")
    for nisbiy, yoq, bor in [
            ("frontend/src/components/Freshness.tsx",
             "median_hours ?? 0", "fresh.lagNone"),
            ("frontend/src/components/TenderDrawer.tsx",
             "match.score ?? 0", "table.scoreNone"),
            ("frontend/src/components/TenderTable.tsx",
             "score ?? 0)", "BALL_YOQ"),
    ]:
        src = io.open(os.path.join(ROOT, nisbiy), encoding="utf-8").read()
        kod = BLOK_IZOH.sub(" ", src)
        nom = os.path.basename(nisbiy)
        check(f"{nom}: `{yoq}` qaytmagan", yoq not in kod)
        check(f"{nom}: o'rniga sabab ko'rsatiladi", bor in src)

    # TARJIMALAR — uch tilda.
    for lok in ("uz", "ru", "en"):
        t = io.open(os.path.join(ROOT, "frontend", "src", "locales",
                                 f"{lok}.ts"), encoding="utf-8").read()
        yoq = [k for k in ("table.scoreNone", "fresh.lagNone")
               if f"'{k}'" not in t]
        check(f"`{lok}` tarjimalari to'liq", not yoq, str(yoq))


def test_tekshiruv_buyrugi():
    bolim("5. SINOV BUYRUG'I loyihadan olinadi, qo'lda yozilmaydi")
    # O'LCHANGAN NUQSON (2026-09-04, interaktiv seansda). Qo'lda
    # `npx tsc --noEmit -p tsconfig.json` yozilgan va u BUTUN SEANS
    # davomida `exit 0` bergan. `frontend/tsconfig.json` da
    # `"files": []` va faqat `references` bor -- bu buyruq HECH
    # NARSANI tekshirmaydi.
    #
    # O'LCHANDI:
    #     tsc -p tsconfig.json       ->   0 loyiha fayli
    #     tsc -p tsconfig.app.json   ->  76 loyiha fayli
    #
    # 5-sinfning eng toza namunasi: konfiguratsiya to'g'ri, buyruq
    # to'g'ri, chiqish kodi to'g'ri, QAMROV NOL. Yashil raqam
    # hisobotga chiqdi va unga tayanib qaror qabul qilindi.
    import json
    tsc = json.load(io.open(os.path.join(ROOT, "frontend", "tsconfig.json"),
                            encoding="utf-8"))
    check("`tsconfig.json` faqat `references` (ya'ni `-p` bilan BO'SH)",
          tsc.get("files") == [] and bool(tsc.get("references")),
          str(tsc.get("files")))

    pkg = json.load(io.open(os.path.join(ROOT, "frontend", "package.json"),
                            encoding="utf-8"))
    skript = pkg.get("scripts", {})
    check("`gate` skripti `package.json` da yozilgan", "gate" in skript)
    # Loyihaning O'Z buyrug'i `-b` ishlatadi (butun graf).
    check("loyiha buyrug'i `tsc -b` (bo'sh `-p` EMAS)",
          "tsc -b" in skript.get("typecheck", ""),
          skript.get("typecheck", ""))

    src = io.open(os.path.join(ROOT, "production_gate.py"),
                  encoding="utf-8").read()
    kod = re.sub(r"#.*", "", src)
    check("darvoza `npm run gate` ni chaqiradi",
          '"npm", "run", "gate"' in kod)
    check("darvoza qo'lda `tsc -p` yozmaydi",
          "tsc\", \"-p\", \"tsconfig.json" not in kod)
    # QAMROV RAQAMI AYTILADI.
    check("darvoza tsc QAMROVINI o'lchaydi", "_tsc_qamrovi" in kod)
    check("qamrov chegarasi tekshiriladi",
          "TSC_ENG_KAM_FAYL" in kod and "n_fayl < TSC_ENG_KAM_FAYL" in kod)
    check("o'lchay olmaslik `0` ga aylantirilmaydi",
          "return -1" in src)


# =====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="O'lchov maydoni nolga aylantirilmasin")
    rejim.bayroqlar(ap)
    rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SKANER: O'LCHOV MAYDONI `?? 0` QILINMASIN")
    print("=" * 70)

    test_skaner_ozini_sinaydi()
    test_qamrov()
    test_buzilish_yoq()
    test_tuzatilganlar()
    test_tekshiruv_buyrugi()

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
