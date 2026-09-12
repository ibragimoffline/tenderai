#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SINOV: LAZY KOMPONENT SUSPENSE CHEGARASIDA BO'LSIN

--- O'LCHANGAN NOSOZLIK (2026-09-12) ---------------------------------
"Kodlarni ko'rib chiqish" bo'limi ochilganda butun bo'lim xato
ekraniga tushdi:

    Minified React error #426

`KodKorik` `lazy()` bilan yuklanadi, lekin uning render joyi
`<Suspense>` ichida EMAS edi. Yon menyudan bosish -- SINXRON
yangilanish; komponent o'sha paytda uzilib qoladi va React butun
daraxtni xato holatiga o'tkazadi.

App.tsx da BOSHQA hamma lazy ko'rinish o'z chegarasiga o'ralgan
edi (`RequirementReview`, `BrokerQueue`, `StatsView`). Ya'ni naqsh
to'g'ri, faqat YANGI qo'shilgani undan chetda qolgan.

--- NEGA SKANER, NEGA BITTA TEKSHIRUV EMAS ---------------------------
Bu xato `tsc` dan ham, `vite build` dan ham, xulq sinovlaridan ham
O'TIB KETDI: komponentning o'zi to'g'ri, xato faqat JOYLASHUVIDA.
Uni faqat brauzerda ochib ko'rgandagina bilib bo'ladi.

Shuning uchun tekshiruv BITTA komponentga emas, QOIDAGA yozilgan:
App.tsx dagi HAR BIR lazy komponent Suspense ichida bo'lishi kerak.
Keyingi qo'shiladigani ham shu qoidaga tushadi.

CHIQISH KODI: 0 -- muvaffaqiyat; 1 -- xato.
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "frontend", "src", "App.tsx")

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


def suspense_oraliqlari(src: str):
    """`<Suspense ...>` ... `</Suspense>` oraliqlari (ichma-ich hisobga
    olinadi). Qaytaradi: (boshi, oxiri) juftliklari ro'yxati."""
    oraliq = []
    stek = []
    for m in re.finditer(r"<Suspense\b|</Suspense>", src):
        if m.group(0).startswith("</"):
            if stek:
                oraliq.append((stek.pop(), m.end()))
        else:
            stek.append(m.start())
    return oraliq


def ichidami(poz: int, oraliq) -> bool:
    return any(a <= poz < b for a, b in oraliq)


def main() -> int:
    print("=" * 70)
    print("LAZY KOMPONENT -- SUSPENSE CHEGARASI")
    print("=" * 70)

    check("App.tsx topildi", os.path.exists(APP), APP)
    if not os.path.exists(APP):
        print(f"\nNATIJA: {pass_}/{pass_ + fail_} o'tdi")
        return 1

    src = io.open(APP, encoding="utf-8").read()

    # IZOH VA JSX IZOHI HISOBGA OLINMAYDI: izoh ichidagi `<KodKorik />`
    # haqiqiy render emas. Bugun matn qidiruvi o'z izohini ushlab
    # yolg'on natija bergani BIR NECHA MARTA uchradi.
    toza = re.sub(r"\{/\*[\s\S]*?\*/\}", " ", src)
    toza = re.sub(r"/\*[\s\S]*?\*/", " ", toza)
    toza = re.sub(r"//[^\n]*", " ", toza)

    lazylar = re.findall(r"const\s+(\w+)\s*=\s*lazy\(", toza)
    check("App.tsx da lazy komponentlar bor", bool(lazylar), str(lazylar))
    print(f"  topildi: {', '.join(lazylar)}")

    oraliq = suspense_oraliqlari(toza)
    check("Suspense chegaralari topildi", bool(oraliq), str(len(oraliq)))

    ochiq = []
    for nom in lazylar:
        for m in re.finditer(r"<" + re.escape(nom) + r"[\s/>]", toza):
            if not ichidami(m.start(), oraliq):
                qator = toza[:m.start()].count("\n") + 1
                ochiq.append(f"{nom} (App.tsx:{qator})")

    check("HAR BIR lazy komponent Suspense ichida",
          not ochiq, "; ".join(ochiq))

    # Skanerning o'zi ishlayotganini tasdiqlaymiz: Suspense ni olib
    # tashlagan nusxada kamida bitta ochiq holat topilishi SHART.
    buzuq = toza.replace("<Suspense", "<div").replace("</Suspense>", "</div>")
    b_oraliq = suspense_oraliqlari(buzuq)
    b_ochiq = [n for n in lazylar
               if any(not ichidami(m.start(), b_oraliq)
                      for m in re.finditer(r"<" + re.escape(n) + r"[\s/>]", buzuq))]
    check("skaner ishlaydi (Suspense olib tashlansa ushlaydi)",
          len(b_ochiq) >= 1, str(b_ochiq))

    print("\n" + "=" * 70)
    print(f"NATIJA: {pass_}/{pass_ + fail_} o'tdi")
    print("=" * 70)
    return 1 if fail_ else 0


if __name__ == "__main__":
    sys.exit(main())
