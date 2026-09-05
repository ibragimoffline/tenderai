# -*- coding: utf-8 -*-
"""
SINOV REJIMI — BAZA va TARMOQ ALOHIDA BAYROQLAR

O'LCHANGAN MUAMMO (2026-09-01)
------------------------------
`run_tests.py` standart holatda har sinovga `--offline` uzatardi va
`--offline` IKKI XIL narsani bir vaqtda o'chirardi:

    22 ta sinovda   `--offline` = BAZASIZ
     3 ta sinovda   `--offline` = TARMOQSIZ
       (doctext, etl_coverage, etl_ishonch)

Ya'ni standart yurgizishda BAZALI tekshiruvlarning HAMMASI
o'tkazib yuborilardi — aynan haqiqiy ma'lumot nuqsonlarini
ushlaydiganlari. "O'tkazib yuborilgan sinov — sinov emas".

BU ALLAQACHON ZARAR KELTIRDI. Ikki misol o'lchandi:

    review_butunlik_test   11-vazifadan beri IKKI tekshiruv
                           yiqilib turgan (eskirgan fikstura)
    doc_qamrov_test        26 ta hujjat DALILSIZ `ok` deb
                           belgilangani ko'rinmagan

Ikkalasi ham faqat `--online` da chiqardi va hech kim
`--online` yurgizmagan.

O'LCHOV (2026-09-01):

    --offline   33 to'plam, 33 o'tdi              246 s
    --online    33 to'plam, 31 o'tdi, 2 YIQILDI   502 s

YECHIM: IKKI MUSTAQIL O'Q
--------------------------
    --bazasiz     bazali tekshiruvlar o'tkaziladi
    --tarmoqsiz   tarmoqqa chiqadigan tekshiruvlar o'tkaziladi
    --offline     ESKI nom — IKKALASI ham (moslik uchun)

Standart yurgizish endi `--tarmoqsiz`: baza MAHALLIY va har doim
bor, tarmoq esa tashqi xizmatga bog'liq. Ya'ni ma'lumot nuqsoni
ko'rinadi, tashqi uzilish esa to'plamni bloklamaydi.
"""
from __future__ import annotations

import argparse
import os

#: ILOVA ROLI — `run_tests.py:ILOVA_ROL` bilan AYNI bo'lishi shart.
#: Ikki joyda turgani ataylab emas, lekin `_tests/` paketi ildizdagi
#: modulni import qilmaydi; `nom_butunlik_test` ikkalasini solishtiradi.
ILOVA_ROL = os.environ.get("TEST_ILOVA_ROL", "tai_app")


def bayroqlar(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Uchala bayroqni qo'shadi. Har sinov `main()` ida chaqiriladi."""
    ap.add_argument("--bazasiz", action="store_true",
                    help="Bazali tekshiruvlarni O'TKAZIB YUBORADI")
    ap.add_argument("--tarmoqsiz", action="store_true",
                    help="Tarmoqqa chiqadigan tekshiruvlarni O'TKAZIB YUBORADI")
    ap.add_argument("--offline", action="store_true",
                    help="ESKI nom: `--bazasiz --tarmoqsiz` bilan bir xil")
    return ap


def moslash(args: argparse.Namespace) -> argparse.Namespace:
    """`--offline` ni ikkala yangi bayroqqa yoyadi.

    Eski buyruqlar (`... --offline`) o'z ma'nosini SAQLAB QOLADI:
    ular haqiqatan ham hech narsaga chiqmasin degan niyat bilan
    yozilgan.
    """
    if getattr(args, "offline", False):
        args.bazasiz = True
        args.tarmoqsiz = True
    return args


# =====================================================================
# ILOVA ROLI — HUQUQ SHOXI SINALSIN
# =====================================================================
def rol_tekshir(db) -> None:
    """Sinov SUPERUSER bilan yurayotgan bo'lsa — YIQILADI.

    O'LCHANGAN NUQSON (2026-09-04). `.env` `postgres` (superuser)
    bilan ulanadi. Superuser huquq tekshiruvlarini CHETLAB o'tadi,
    ya'ni grant asosidagi himoyalar HECH QACHON sinalmagan.

    `auth_test` da ERP chegarasi uchun IKKI shox bor:

        erp_yopiq = True   huquq bilan yopiq -> surat KERAK EMAS
        erp_yopiq = False  sanoqni solishtirish (ZAIF)

    Superuser tufayli DOIM ikkinchisi ishlagan. Ya'ni yashil natija
    haqiqiy chegarani emas, uning ZAXIRA yo'lini tasdiqlagan.
    Bu `tsc --noEmit -p tsconfig.json` bilan bir sinf, faqat
    xavfliroq: u yerda tekshiruv yo'q edi, bu yerda tekshiruv bor,
    lekin HIMOYASIZ shox tekshirilgan.

    NEGA `skip` EMAS, `fail`: `skip` — "jimgina o'tkazib yuborish"
    ning aynan o'zi va u bir hafta ichida e'tiborsiz qolinadi
    (2-sinf).

    CHIQISH YO'LI: `DB_SET_ROLE=tai_app`. `tai_app` LOGIN QILA
    OLMAYDI (`rolcanlogin = false`), shuning uchun u bilan ulanib
    bo'lmaydi — `SET ROLE` esa ulanishni talab qilmaydi va
    superuser imtiyozini shu sessiya uchun tushiradi.
    """
    kim = db.query_one(
        "SELECT current_user AS u, "
        "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS s")
    if not kim or not kim["s"]:
        return

    # AVVAL O'ZI TO'G'RILASHGA URINADI.
    #
    # O'LCHANGAN NUQSON (2026-09-06). Bu qo'riqchi ishlagan, lekin
    # narxi noto'g'ri joyga tushgan: `run_tests.py` to'liq yurishida
    # `auth_test` va `xavfsizlik_test` YIQILDI va darvoza "sinov
    # buzilgan" deb ko'rindi, holbuki buzilgani MUHIT edi.
    # `DB_SET_ROLE` na `.env` da, na `.env.example` da bor edi —
    # ya'ni uni har safar buyruq satrida eslab qolish kerak edi.
    # Bu eslab qolinmaydi va aynan shu sababdan to'liq yurish
    # oxirgi marta 2026-09-04 da to'g'ri rejimda bo'lgan.
    #
    # `SET ROLE` uchun ULANISH kerak emas va `tai_app` login qila
    # olmaydi, ya'ni bu yagona yo'l. A'zolik bo'lmasa — eski xatti
    # harakat: TO'XTAYDI. Jimgina `skip` YO'Q.
    #
    # To'g'rilash BAQIRIB aytiladi: qaysi rejimda o'lchanganini
    # bilmasdan sonlarni solishtirib bo'lmaydi.
    if not (os.environ.get("DB_SET_ROLE") or "").strip():
        a = db.query_one(
            "SELECT (SELECT count(*) FROM pg_roles WHERE rolname=%(r)s) AS bor, "
            "       pg_has_role(current_user, %(r)s, 'MEMBER') AS azo",
            {"r": ILOVA_ROL}) or {}
        if a.get("bor") and a.get("azo"):
            db.rol_ornat(ILOVA_ROL)
            yangi_kim = db.query_one("SELECT current_user AS u")
            print(f"  [rejim] superuser `{kim['u']}` aniqlandi -> "
                  f"`SET ROLE {ILOVA_ROL}` qo'llandi "
                  f"(joriy rol: `{yangi_kim['u']}`).")
            return

    qatorlar = [
        "",
        "SINOV SUPERUSER BILAN YURMOQDA — TO'XTATILDI.",
        f"  joriy rol: {kim['u']} (superuser)",
        "  Superuser huquq tekshiruvlarini chetlab o'tadi, ya'ni",
        "  grant asosidagi himoyalar (ERP chegarasi, IDOR) SINALMAYDI.",
        "  Tuzatish:  DB_SET_ROLE=tai_app <buyruq>",
        "  yoki `XT_DB_DSN` ni ilova roliga o'tkazing.",
        "",
    ]
    raise SystemExit("\n".join(qatorlar))
