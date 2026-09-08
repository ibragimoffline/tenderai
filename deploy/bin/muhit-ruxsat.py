#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Konteynerga uzatiladigan muhit kalitlarining RUXSAT RO'YXATI.

NEGA UMUMAN FILTR
=================
Staging muhit faylida konteynerga KERAK BO'LMAGAN sirlar bor:

    XT_DB_DSN_OWNER    -- MIGRATSIYA roli. Ilova undan foydalanmaydi,
                          lekin u sxemani o'zgartira oladi.
    E2E_PAROL          -- sinov hisobining paroli.
    BACKUP_REMOTE_CMD  -- tashqi nusxa uchun buyruq.

Butun faylni `--env-file` bilan uzatish bularning HAMMASINI konteynerga
berardi. Ilova jarayoni buzilsa, hujumchi migratsiya roli DSN sini
o'qiy olardi va `tai_service` ga CREATEDB bermaslik qoidasi ma'nosiz
bo'lardi.

NEGA RO'YXAT QO'LDA YOZILMAYDI
==============================
Qo'lda yozilgan ro'yxat SURILIB KETADI: kodga yangi sozlama qo'shiladi,
ro'yxat unutiladi va ilova ishlab chiqarishda "sozlama o'qilmadi" deb
sinadi. Yomoni — bu sukut qiymat bilan JIMGINA yuz beradi.

Shuning uchun ro'yxat KODDAN hosil qilinadi: kod qaysi kalitni
o'qiyotgan bo'lsa, o'sha uzatiladi. Ro'yxatning o'zi versiyalanmaydi,
u har safar shu SHA dagi koddan hisoblanadi.

NEGA `ast`, REGEX EMAS
======================
Regex `os.environ.get("APP_PUBLIC_URL")` ni topadi, lekin

    ENV_ASOSIY = "APP_PUBLIC_URL"
    os.environ.get(ENV_ASOSIY)

ni TOPMAYDI. Aynan shu uchta kalit (`APP_PUBLIC_URL`, `PUBLIC_BASE_URL`,
`AI_PAID_ENABLED`) shu tarzda o'qiladi va regex bilan qurilgan ro'yxat
ularni tushirib qoldirardi -- ilova ishga tushmasdi.

FOYDALANISH
===========
    muhit-ruxsat.py royxat
    muhit-ruxsat.py filtr <manba.env> <chiqish.env>

`filtr` QIYMATLARNI CHOP ETMAYDI — faqat kalit nomlari va sanoq.
"""
import ast
import io
import os
import sys

# Kod SKANERLANADIGAN fayllar. Ilova ijrosiga kiradiganlar, xolos:
# `deploy/` skriptlari konteynerda YURMAYDI.
MANBALAR = ("api", "run_etl.py")

O_QISH = {"getenv", "environ"}

# ULARSIZ ILOVA ISHGA TUSHMAYDI. Qolgan kalitlarning sukut qiymati bor
# va faylda bo'lmasligi MUAMMO EMAS -- shuning uchun ular sanaladi,
# lekin nomma-nom sanalmaydi: 60 ta nomni har yurishda chop etish
# haqiqiy ogohlantirishni ko'mib yuborardi.
MAJBURIY = ("APP_ENV", "APP_PUBLIC_URL", "XT_DB_DSN")


def _kalitlar_fayldan(yol):
    """Bitta fayl o'qiydigan muhit kalitlari."""
    try:
        daraxt = ast.parse(io.open(yol, encoding="utf-8").read(), yol)
    except (SyntaxError, UnicodeDecodeError):
        return set()

    # Modul darajasidagi `NOM = "MATN"` — bilvosita o'qish uchun.
    doim = {}
    for tugun in daraxt.body:
        if isinstance(tugun, ast.Assign) and len(tugun.targets) == 1:
            t = tugun.targets[0]
            if isinstance(t, ast.Name) and isinstance(tugun.value, ast.Constant) \
                    and isinstance(tugun.value.value, str):
                doim[t.id] = tugun.value.value

    def _matn(tugun):
        if isinstance(tugun, ast.Constant) and isinstance(tugun.value, str):
            return tugun.value
        if isinstance(tugun, ast.Name):
            return doim.get(tugun.id)
        return None

    topildi = set()
    for tugun in ast.walk(daraxt):
        # os.getenv(X) / os.environ.get(X)
        if isinstance(tugun, ast.Call) and isinstance(tugun.func, ast.Attribute):
            f = tugun.func
            nom = f.attr
            asos = getattr(f.value, "attr", None) or getattr(f.value, "id", None)
            if (nom == "getenv" and asos == "os") or \
               (nom == "get" and asos == "environ"):
                if tugun.args:
                    k = _matn(tugun.args[0])
                    if k:
                        topildi.add(k)
        # os.environ["X"]
        if isinstance(tugun, ast.Subscript):
            v = tugun.value
            if getattr(v, "attr", None) == "environ":
                k = _matn(tugun.slice)
                if k:
                    topildi.add(k)
    return topildi


def royxat(ildiz):
    """Kod o'qiydigan BARCHA muhit kalitlari, saralangan."""
    hammasi = set()
    for m in MANBALAR:
        yol = os.path.join(ildiz, m)
        if os.path.isfile(yol):
            hammasi |= _kalitlar_fayldan(yol)
        elif os.path.isdir(yol):
            for k, _d, fayllar in os.walk(yol):
                for f in fayllar:
                    if f.endswith(".py"):
                        hammasi |= _kalitlar_fayldan(os.path.join(k, f))
    # FAQAT MUHIT KO'RINISHIDAGI nomlar. `ast` tasodifan boshqa matnni
    # ushlab qolsa (masalan `os.environ.get(rejim)`), u bu yerda tushadi.
    return sorted(k for k in hammasi
                  if k and k[0].isalpha() and k.isupper()
                  and k.replace("_", "").isalnum())


def _tirnoq_yech(q):
    """`KEY="v"` -> `KEY=v`.

    `docker --env-file` qiymatni SHELL DEB O'QIMAYDI: tirnoqlar
    qiymatning O'ZIDA qoladi. Muhit faylida `XT_DB_DSN="host=..."`
    yozilgan bo'lsa, konteyner DSN ni tirnoq bilan olardi va ulanish
    tushunarsiz xato bilan yiqilardi. systemd `EnvironmentFile` esa
    tirnoqni yechadi -- ya'ni systemd relizi ISHLAB, konteyner
    YIQILARDI va sabab ko'rinmasdi.
    """
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'":
        return q[1:-1]
    return q


def filtr(ildiz, manba, chiqish):
    ruxsat = set(royxat(ildiz))
    olindi, tashlandi, tirnoqli = [], [], 0
    satrlar = []
    with io.open(manba, encoding="utf-8", errors="replace") as f:
        for satr in f:
            satr = satr.rstrip("\n").rstrip("\r")
            if not satr.strip() or satr.lstrip().startswith("#"):
                continue
            if satr.startswith("export "):
                satr = satr[len("export "):]
            if "=" not in satr:
                continue
            kalit, _s, qiymat = satr.partition("=")
            kalit = kalit.strip()
            if kalit not in ruxsat:
                tashlandi.append(kalit)
                continue
            yangi = _tirnoq_yech(qiymat)
            if yangi != qiymat:
                tirnoqli += 1
            olindi.append(kalit)
            satrlar.append("%s=%s" % (kalit, yangi))

    # 0600, ROOT niki. `umask` ga tayanilmaydi -- ochiq holda yaratib
    # keyin `chmod` qilish poyga oynasini ochardi.
    bayroq = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(chiqish, bayroq, 0o600)
    with io.open(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(satrlar) + "\n")

    # QIYMAT CHOP ETILMAYDI. Faqat nomlar va sanoq.
    print("ruxsat ro'yxati : %d kalit (koddan hisoblandi)" % len(ruxsat))
    print("uzatildi        : %d" % len(olindi))
    print("TASHLANDI       : %d -- %s" % (len(tashlandi), ", ".join(sorted(tashlandi)) or "yo'q"))
    if tirnoqli:
        print("tirnoqdan yechildi: %d qiymat" % tirnoqli)
    yoq = sorted(ruxsat - set(olindi))
    if yoq:
        print("faylda yo'q      : %d (sukut qiymat ishlatiladi)" % len(yoq))
    majburiy_yoq = [k for k in MAJBURIY if k not in olindi]
    if majburiy_yoq:
        print("MAJBURIY YO'Q    : %s" % ", ".join(majburiy_yoq), file=sys.stderr)
        return 1
    return 0


def main(argv):
    # Skript `<ildiz>/deploy/bin/` da turadi.
    ildiz = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "royxat":
        for k in royxat(ildiz):
            print(k)
        return 0
    if argv[0] == "filtr":
        if len(argv) != 3:
            print("foydalanish: muhit-ruxsat.py filtr <manba.env> <chiqish.env>", file=sys.stderr)
            return 2
        return filtr(ildiz, argv[1], argv[2])
    print("noma'lum amal: %s" % argv[0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
