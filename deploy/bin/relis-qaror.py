#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RELIZ QARORI — TOIFAGA ASOSLANGAN, sanoqqa emas.

NEGA
====
Darvoza "hamma to'plam yashil bo'lsin" qoidasida edi. Bu qoida
ikkita butunlay boshqa narsani BIR XIL ko'rsatadi:

    xavfsizlik regressiyasi          -> reliz to'xtashi KERAK
    korpusda hujjat yo'qligi         -> to'xtatish MA'NOSIZ

Natijada darvoza doim qizil bo'lib qoladi va uning oqibati bitta:
undan chetlab o'tishni o'rganishadi. Qoida qanchalik qat'iy
bo'lsa, chetlab o'tish shunchalik odatiy bo'ladi.

Shuning uchun qaror TOIFA bo'yicha chiqariladi. Sanoq (masalan
"30/45 yetarli") ISHLATILMAYDI: u ham xuddi shu ikki narsani
aralashtirardi, faqat boshqa nisbatda.

QARORNI NIMA BELGILAYDI
=======================
Jurnal MATNI EMAS. `run_tests.py` yozadigan `xulosa.json` va
repozitoriyadagi `deploy/relis-tasnif.tsv`. Matn tahlili "chiqish
formati o'zgardi -> siyosat jimgina o'zgardi" degan bog'liqlik
yaratardi.

FAIL CLOSED
===========
Tasnifi yo'q yiqilish -> UNKNOWN -> TO'XTAYDI.
Artefakt buzuq          -> TO'XTAYDI.
To'plam yo'qolgan       -> TO'XTAYDI.
Takroriy natija         -> TO'XTAYDI.
Kritik to'plam qizil    -> TO'XTAYDI (yorlig'idan QAT'I NAZAR).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

#: Yopiq ro'yxat. Noma'lum satr QABUL QILINMAYDI va o'xshashlik
#: bo'yicha moslashtirilmaydi -- "SECURITY_ISH" kabi xato yozuv
#: jimgina to'smaydigan toifaga tushib ketardi.
TOSIQ = {
    "CODE_BUG", "MIGRATION", "SECURITY", "TENANT_ISOLATION",
    "AUDIT_BUG", "DATA_CORRUPTION", "STARTUP", "READINESS",
    "API_CONTRACT", "BACKUP_INTEGRITY", "ROLLBACK",
    "RUNTIME_PRIVILEGE", "UNKNOWN",
}
TOSMAYDI = {
    "TEST_FIXTURE", "CROSS_SUITE_DEPENDENCY", "CORPUS_MISSING",
    "QUALITY_UNMEASURED", "NON_BLOCKING_ENVIRONMENT",
    "NON_BLOCKING_EXTERNAL_DEPENDENCY",
}
#: `PASS` = o'tishi KUTILADI. Yiqilsa UNKNOWN bo'ladi va to'xtatadi.
BARCHA_TOIFA = TOSIQ | TOSMAYDI | {"PASS"}

#: IKKINCHI, MUSTAQIL QO'RIQCHA. Bu to'plamlar qizil bo'lsa reliz
#: to'xtaydi -- kimdir ularni xato bilan `TEST_FIXTURE` deb
#: belgilagan bo'lsa ham. Bitta qatlamga ishonish yetarli emas:
#: tasnif fayli inson yozadi, inson esa adashadi.
KRITIK = {
    "migratsiya_test", "xavfsizlik_test", "auth_test", "deploy_test",
    "multitenant_test", "fikstura_test",
}


class Qaror:
    def __init__(self) -> None:
        self.tosiqlar: List[Tuple[str, str, str]] = []   # (to'plam, toifa, sabab)
        self.tosmaydi: List[Tuple[str, str, str]] = []
        self.otdi: List[str] = []
        self.xatolar: List[str] = []                     # artefakt/qamrov xatosi

    @property
    def ruxsat(self) -> bool:
        return not self.tosiqlar and not self.xatolar


def tasnif_oqi(yol: str) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """TSV ni o'qiydi. `({toplam: (toifa, dalil)}, xatolar)`."""
    xato: List[str] = []
    jadval: Dict[str, Tuple[str, str]] = {}
    if not yol or not os.path.isfile(yol):
        return {}, [f"tasnif artefakti YO'Q: {yol or '<berilmagan>'}"]
    for n, satr in enumerate(
            io.open(yol, encoding="utf-8").read().splitlines(), 1):
        if not satr.strip() or satr.lstrip().startswith("#"):
            continue
        qism = satr.split("\t")
        if len(qism) < 3:
            xato.append(f"{n}-qator: uchta ustun kerak (TAB bilan)")
            continue
        nom, toifa, dalil = qism[0].strip(), qism[1].strip(), qism[2].strip()
        if not nom:
            xato.append(f"{n}-qator: to'plam nomi bo'sh")
            continue
        if nom in jadval:
            xato.append(f"{n}-qator: TAKRORIY to'plam: {nom}")
            continue
        if toifa not in BARCHA_TOIFA:
            xato.append(f"{n}-qator: noma'lum toifa: {toifa!r}")
            continue
        # DALIL MAJBURIY: "to'smaydi" degan qaror sababsiz bo'lmaydi.
        if toifa in TOSMAYDI and len(dalil) < 15:
            xato.append(f"{n}-qator: {nom} — dalil yetarli emas")
            continue
        jadval[nom] = (toifa, dalil)
    return jadval, xato


def qaror_chiqar(xulosa: dict, tasnif: Dict[str, Tuple[str, str]],
                 tasnif_xato: Optional[List[str]] = None) -> Qaror:
    """Yagona qaror funksiyasi. Sinovlar buni TO'G'RIDAN chaqiradi."""
    q = Qaror()
    q.xatolar.extend(tasnif_xato or [])

    toplamlar = xulosa.get("toplamlar")
    if not isinstance(toplamlar, list) or not toplamlar:
        q.xatolar.append("xulosa.json: `toplamlar` yo'q yoki bo'sh")
        return q

    nomlar = [t.get("nom") for t in toplamlar]
    if len(nomlar) != len(set(nomlar)):
        takror = sorted({n for n in nomlar if nomlar.count(n) > 1})
        q.xatolar.append(f"TAKRORIY natija: {', '.join(takror)}")

    # QAMROV: mavjud to'plamlarning HAMMASI yurgan bo'lishi kerak.
    # Yurmagan to'plam PASS EMAS.
    mavjud = xulosa.get("toplam_mavjud")
    if isinstance(mavjud, int) and mavjud > len(toplamlar):
        q.xatolar.append(
            f"{mavjud - len(toplamlar)} ta to'plam YURMADI "
            f"({len(toplamlar)}/{mavjud})")

    yiqilgan = set(xulosa.get("yiqilgan") or [])
    korilgan = set()

    for t in toplamlar:
        nom = t.get("nom")
        if not nom:
            q.xatolar.append("nomsiz to'plam natijasi")
            continue
        korilgan.add(nom)
        if nom not in yiqilgan:
            q.otdi.append(nom)
            continue

        # --- YIQILGAN ---
        # KRITIK TO'PLAM: yorliqdan QAT'I NAZAR to'xtatadi.
        if nom in KRITIK:
            q.tosiqlar.append((nom, "KRITIK", "kritik to'plam qizil"))
            continue
        toifa, dalil = tasnif.get(nom, ("UNKNOWN", "tasnif YO'Q"))
        if toifa == "PASS":
            # O'tishi kutilgan to'plam yiqildi -> REGRESSIYA.
            q.tosiqlar.append((nom, "UNKNOWN", "o'tishi kutilgan edi"))
        elif toifa in TOSIQ:
            q.tosiqlar.append((nom, toifa, dalil))
        else:
            q.tosmaydi.append((nom, toifa, dalil))

    # Tasnifda bor, lekin yurishda YO'Q to'plam — yo'qolgan sinov.
    for nom in sorted(set(tasnif) - korilgan):
        q.xatolar.append(f"tasnifda bor, yurishda YO'Q: {nom}")

    return q


def chop_et(q: Qaror) -> None:
    print("=" * 70)
    print("DARVOZA NATIJASI")
    print("=" * 70)
    print(f"  o'tdi                : {len(q.otdi)}")
    print(f"  to'smaydigan yiqilish: {len(q.tosmaydi)}")
    print(f"  TO'SUVCHI yiqilish   : {len(q.tosiqlar)}")
    print(f"  artefakt/qamrov xato : {len(q.xatolar)}")

    if q.tosmaydi:
        print("\n  --- to'smaydigan (toifa bo'yicha) ---")
        for nom, toifa, dalil in sorted(q.tosmaydi, key=lambda x: (x[1], x[0])):
            print(f"    {toifa:32s} {nom}")
            print(f"      {dalil[:96]}")
    if q.tosiqlar:
        print("\n  --- TO'SUVCHI ---")
        for nom, toifa, sabab in q.tosiqlar:
            print(f"    {nom} — {toifa}: {sabab[:80]}")
    if q.xatolar:
        print("\n  --- ARTEFAKT/QAMROV ---")
        for x in q.xatolar:
            print(f"    {x}")

    print("\n" + "=" * 70)
    print("RELIZ QARORI: " + ("STAGING GA RUXSAT" if q.ruxsat
                              else "TO'XTATILDI"))
    print("=" * 70)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Reliz qarori (toifaga asoslangan)")
    ap.add_argument("--xulosa", required=True, help="xulosa.json yo'li")
    ap.add_argument("--tasnif", required=True, help="relis-tasnif.tsv yo'li")
    a = ap.parse_args(argv)

    try:
        xulosa = json.load(io.open(a.xulosa, encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001
        print(f"xulosa.json O'QILMADI: {e}", file=sys.stderr)
        print("RELIZ QARORI: TO'XTATILDI")
        return 2

    jadval, xato = tasnif_oqi(a.tasnif)
    q = qaror_chiqar(xulosa, jadval, xato)
    chop_et(q)
    return 0 if q.ruxsat else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
