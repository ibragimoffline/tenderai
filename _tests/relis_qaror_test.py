#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RELIZ QARORI SIYOSATI — chetlab o'tib bo'lmasligi.

NEGA BU SINOV MUHIM
===================
Siyosat "qaysi qizil reliz to'sadi" degan savolga javob beradi.
Undagi nuqson HECH QAYERDA ko'rinmaydi: darvoza yashil bo'ladi va
reliz o'tadi. Ya'ni bu modulda yolg'on yashil eng qimmat turdagi.

Shuning uchun BAXTLI YO'L YETARLI EMAS. Har bir to'sish sababi
alohida sinaladi va har biri uchun MUTATSIYA bor: to'siqni olib
tashlasang sinov yiqilishi kerak.

Bazasiz yuradi.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deploy", "bin"))

import konsol  # noqa: E402
import importlib.util as _iu  # noqa: E402

_sp = _iu.spec_from_file_location(
    "relis_qaror", os.path.join(ROOT, "deploy", "bin", "relis-qaror.py"))
Q = _iu.module_from_spec(_sp)
_sp.loader.exec_module(Q)

konsol.sozla()
_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


def _xulosa(nomlar, yiqilgan, mavjud=None):
    """Sun'iy `xulosa.json` tuzilmasi."""
    return {
        "toplamlar": [{"nom": n, "kod": (1 if n in yiqilgan else 0)}
                      for n in nomlar],
        "yiqilgan": list(yiqilgan),
        "toplam_mavjud": mavjud if mavjud is not None else len(nomlar),
    }


HAQIQIY_TASNIF = os.path.join(ROOT, "deploy", "relis-tasnif.tsv")


def test_haqiqiy_artefakt():
    bolim("1. Repozitoriydagi artefakt HAQIQATAN yaroqli")
    jadval, xato = Q.tasnif_oqi(HAQIQIY_TASNIF)
    check("artefakt xatosiz o'qiladi", not xato, "; ".join(xato[:3]))
    check("artefaktda yozuvlar bor", len(jadval) >= 10, f"{len(jadval)} ta")
    yomon = [n for n, (t, _d) in jadval.items() if t not in Q.BARCHA_TOIFA]
    check("hamma toifa yopiq ro'yxatdan", not yomon, str(yomon))
    # KRITIK to'plam artefaktda to'smaydigan deb belgilanmasin.
    xato_yorliq = [n for n, (t, _d) in jadval.items()
                   if n in Q.KRITIK and t in Q.TOSMAYDI]
    check("kritik to'plam to'smaydigan deb belgilanmagan",
          not xato_yorliq, str(xato_yorliq))


def test_a_baxtli_yol():
    bolim("2. CASE A — 29 o'tdi + 16 yaroqli to'smaydigan -> RUXSAT")
    jadval, xato = Q.tasnif_oqi(HAQIQIY_TASNIF)
    yiqilgan = sorted(jadval)
    otganlar = [f"ok_{i}_test" for i in range(29)] + sorted(Q.KRITIK)
    x = _xulosa(otganlar + yiqilgan, yiqilgan)
    q = Q.qaror_chiqar(x, jadval, xato)
    check("CASE A: RUXSAT", q.ruxsat,
          f"tosiq={len(q.tosiqlar)} xato={len(q.xatolar)}")
    check("CASE A: hammasi to'smaydigan deb sanaldi",
          len(q.tosmaydi) == len(yiqilgan), f"{len(q.tosmaydi)}")


def _tosadi(nom, toifa, dalil="yetarlicha uzun dalil matni"):
    """Bitta yiqilish berilgan toifada -> qaror."""
    jadval = {nom: (toifa, dalil)}
    x = _xulosa([nom] + sorted(Q.KRITIK), [nom])
    return Q.qaror_chiqar(x, jadval, [])


def test_tosuvchi_toifalar():
    bolim("3. CASE B-E — to'suvchi toifalar RELIZNI TO'XTATADI")
    for toifa in ("SECURITY", "CODE_BUG", "MIGRATION", "UNKNOWN",
                  "TENANT_ISOLATION", "AUDIT_BUG", "ROLLBACK",
                  "BACKUP_INTEGRITY", "RUNTIME_PRIVILEGE"):
        q = _tosadi("bir_test", toifa)
        check(f"{toifa} -> TO'XTATADI", not q.ruxsat)

    # Aksincha: to'smaydigan toifa o'tkazadi -- aks holda yuqoridagi
    # tekshiruvlar "hamma narsa to'xtatadi" degan ma'nosiz holatdan
    # ham o'tardi.
    for toifa in sorted(Q.TOSMAYDI):
        q = _tosadi("bir_test", toifa)
        check(f"{toifa} -> ruxsat", q.ruxsat, str(q.tosiqlar))


def test_f_yoqolgan_toplam():
    bolim("4. CASE F — to'plam YURMAGAN -> TO'XTATADI")
    x = _xulosa(sorted(Q.KRITIK), [], mavjud=len(Q.KRITIK) + 3)
    q = Q.qaror_chiqar(x, {}, [])
    check("yurmagan to'plam TO'XTATADI", not q.ruxsat, str(q.xatolar[:1]))

    # Tasnifda bor, lekin yurishda yo'q.
    x2 = _xulosa(sorted(Q.KRITIK), [])
    q2 = Q.qaror_chiqar(x2, {"yoq_test": ("TEST_FIXTURE", "uzun dalil matni")}, [])
    check("tasnifda bor, yurishda yo'q -> TO'XTATADI", not q2.ruxsat)


def test_g_buzuq_artefakt():
    bolim("5. CASE G — BUZUQ artefakt -> TO'XTATADI")
    with tempfile.TemporaryDirectory() as t:
        y = os.path.join(t, "a.tsv")
        io.open(y, "w", encoding="utf-8").write("faqat_bitta_ustun\n")
        _j, x = Q.tasnif_oqi(y)
        check("ustun yetishmasa xato", bool(x), str(x[:1]))

        io.open(y, "w", encoding="utf-8").write("a_test\tYOQ_TOIFA\tdalil\n")
        _j, x = Q.tasnif_oqi(y)
        check("noma'lum toifa xato", bool(x), str(x[:1]))

        io.open(y, "w", encoding="utf-8").write("a_test\tTEST_FIXTURE\tqisqa\n")
        _j, x = Q.tasnif_oqi(y)
        check("CASE I: dalilsiz to'smaydigan xato", bool(x), str(x[:1]))

        io.open(y, "w", encoding="utf-8").write(
            "a_test\tTEST_FIXTURE\tyetarlicha uzun dalil\n"
            "a_test\tTEST_FIXTURE\tyana yetarlicha uzun dalil\n")
        _j, x = Q.tasnif_oqi(y)
        check("CASE J: takroriy yozuv xato", bool(x), str(x[:1]))

    check("artefakt YO'Q bo'lsa xato", bool(Q.tasnif_oqi("/yoq/a.tsv")[1]))
    # Xato bo'lsa qaror TO'XTAYDI.
    q = Q.qaror_chiqar(_xulosa(sorted(Q.KRITIK), []), {}, ["soxta xato"])
    check("artefakt xatosi bo'lsa TO'XTATADI", not q.ruxsat)


def test_h_kritik_notogri_yorliq():
    bolim("6. CASE H — KRITIK to'plam noto'g'ri yorliq bilan -> TO'XTATADI")
    nom = "xavfsizlik_test"
    jadval = {nom: ("TEST_FIXTURE", "kimdir buni to'smaydigan deb yozdi")}
    x = _xulosa(sorted(Q.KRITIK), [nom])
    q = Q.qaror_chiqar(x, jadval, [])
    check("kritik to'plam yorliqdan QAT'I NAZAR to'xtatadi", not q.ruxsat,
          str(q.tosiqlar[:1]))
    check("sabab KRITIK deb ko'rsatiladi",
          any(t == "KRITIK" for _n, t, _s in q.tosiqlar))


def test_j_takroriy_natija():
    bolim("7. CASE J — TAKRORIY natija -> TO'XTATADI")
    x = _xulosa(sorted(Q.KRITIK), [])
    x["toplamlar"].append({"nom": "auth_test", "kod": 0})
    q = Q.qaror_chiqar(x, {}, [])
    check("takroriy natija TO'XTATADI", not q.ruxsat, str(q.xatolar[:1]))


def test_pass_regressiya():
    bolim("8. `PASS` deb belgilangan to'plam yiqilsa -> TO'XTATADI")
    # Ro'yxatni yangilash ESDAN chiqsa ham regressiya to'siqqa aylansin.
    jadval = {"bir_test": ("PASS", "o'tishi kutiladi")}
    x = _xulosa(["bir_test"] + sorted(Q.KRITIK), ["bir_test"])
    q = Q.qaror_chiqar(x, jadval, [])
    check("PASS deb belgilangan yiqilish TO'XTATADI", not q.ruxsat)
    check("u UNKNOWN deb sanaladi",
          any(t == "UNKNOWN" for _n, t, _s in q.tosiqlar), str(q.tosiqlar[:1]))


def test_bosh_xulosa():
    bolim("9. Bo'sh yoki yaroqsiz `xulosa.json` -> TO'XTATADI")
    for x in ({}, {"toplamlar": []}, {"toplamlar": "matn"}):
        check(f"yaroqsiz xulosa TO'XTATADI: {str(x)[:24]}",
              not Q.qaror_chiqar(x, {}, []).ruxsat)


def main():
    print("=" * 70)
    print("SINOV: RELIZ QARORI SIYOSATI")
    print("=" * 70)
    test_haqiqiy_artefakt()
    test_a_baxtli_yol()
    test_tosuvchi_toifalar()
    test_f_yoqolgan_toplam()
    test_g_buzuq_artefakt()
    test_h_kritik_notogri_yorliq()
    test_j_takroriy_natija()
    test_pass_regressiya()
    test_bosh_xulosa()

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
