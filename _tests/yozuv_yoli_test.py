#!/usr/bin/env python3
"""SINOV: YOZUV FAQAT YOZUV YO'LIDAN O'TSIN

`api/db.py` da ikki xil yo'l bor va ular ATAYLAB farq qiladi:

    query() / query_one() / scalar()   ->  conn.rollback()
    execute_returning()                ->  conn.commit()

`query()` ning izohi aniq: "faqat o'qish — tranzaksiyani ochiq
qoldirmaymiz".

--- NEGA BU SINOV BOR (o'lchangan, 2026-09-11) ------------------------
Katalogni ommaviy o'chirish `db.query()` orqali yozilgandi.
`RETURNING id` qatorlarni BARIBIR qaytaradi, shuning uchun son
to'g'ri chiqdi: ekran "1796 ta mahsulot o'chirildi" dedi.
Keyin `rollback()` ishladi va bazada HECH NARSA o'zgarmadi.

Qaytarib bo'lmaydigan amal haqida YOLG'ON MUVAFFAQIYAT — eng
yomon sinf. Foydalanuvchi ma'lumot ketdi deb ishonadi, u esa
joyida; teskari holatda esa aksincha bo'lardi.

O'sha skanerda IKKINCHI holat ham topildi:
`requirement.review_bulk()` — ommaviy talab tasdig'i. U ham
`query()` orqali `UPDATE` qilardi VA parametrlar lug'ati to'liq
emas edi. Ya'ni funksiya hech qachon ishlamagan, audit esa
"N ta talab bir amalda" deb yozib kelgan.

--- SKANER NIMANI YECHADI --------------------------------------------
SQL uch xil ko'rinishda beriladi va uchalasi ham tekshiriladi:

    db.query("DELETE ...")            xom satr
    db.query(MENING_SQL)              shu fayldagi doimiy
    db.query(queries.CATALOG_CLEAR)   BOSHQA moduldagi doimiy

Uchinchisi muhim: aynan o'sha ko'rinish nuqsonni yashirgan edi.

Ishga tushirish:
    python _tests/yozuv_yoli_test.py
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Bu funksiyalar ROLLBACK qiladi — ularga yozuv berilmaydi.
OQISH_YOLI = {"query", "query_one", "scalar"}

#: Yozuv fe'llari. `WITH ... AS (DELETE ...)` ham YOZUV: CTE ichidagi
#: o'zgarish ham tranzaksiyaga tegishli va rollback uni bekor qiladi.
#
# OXIRIDA `\b` YO'Q -- va bu ataylab. Birinchi yozuvda naqsh
# `...|UPDATE\s+\w|...)\b` edi: `UPDATE\s+\w` jadval nomining
# BIRINCHI HARFIDA tugaydi, keyingi `\b` esa so'z O'RTASIDA
# turadi va HECH QACHON mos kelmaydi.
#
# Nuqson yashiringan edi, chunki skanerning o'z namunasida
# jadval nomi bitta harf edi ("UPDATE y SET ...") -- unda
# chegara tasodifan to'g'ri kelardi. Mutatsiya ochdi: haqiqiy
# `UPDATE tender_requirement` ushlanmadi.
YOZUV_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE\s+[\w\"]|DELETE\s+FROM|TRUNCATE\b)", re.I)

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


def _modul_doimiylari(daraxt: ast.Module) -> dict:
    """Modul darajasidagi `NOM = "SQL"` doimiylari."""
    out = {}
    for n in daraxt.body:
        if not isinstance(n, ast.Assign):
            continue
        v = n.value
        matn = None
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            matn = v.value
        elif isinstance(v, (ast.JoinedStr,)):
            matn = "".join(x.value for x in v.values
                           if isinstance(x, ast.Constant)
                           and isinstance(x.value, str))
        elif isinstance(v, ast.BinOp) or isinstance(v, ast.Tuple):
            matn = " ".join(x.value for x in ast.walk(v)
                            if isinstance(x, ast.Constant)
                            and isinstance(x.value, str))
        if matn is None:
            continue
        for t in n.targets:
            if isinstance(t, ast.Name):
                out[t.id] = matn
    return out


def _py_fayllar(kok: str):
    for dp, _d, fs in os.walk(os.path.join(ROOT, kok)):
        if "__pycache__" in dp:
            continue
        for f in sorted(fs):
            if f.endswith(".py"):
                yield os.path.join(dp, f)


def main() -> int:
    print("=" * 70)
    print("SINOV: YOZUV FAQAT YOZUV YO'LIDAN O'TSIN")
    print("=" * 70)

    # --- Konvensiyaning O'ZI joyidami ---
    db_src = io.open(os.path.join(ROOT, "api", "db.py"), encoding="utf-8").read()
    check("`query()` rollback qiladi",
          "conn.rollback()" in db_src.split("def query(")[1].split("def ")[0])
    check("`execute_returning()` commit qiladi",
          "conn.commit()" in db_src.split("def execute_returning(")[1])

    # --- BARCHA MODULLARNING doimiylari (moduldan-modulga havola uchun) ---
    global_doimiy: dict = {}
    daraxtlar: dict = {}
    for yol in list(_py_fayllar("api")) + [
            os.path.join(ROOT, f) for f in sorted(os.listdir(ROOT))
            if f.endswith(".py")]:
        try:
            t = ast.parse(io.open(yol, encoding="utf-8").read())
        except SyntaxError:
            continue
        daraxtlar[yol] = t
        modul = os.path.splitext(os.path.basename(yol))[0]
        for nom, sql in _modul_doimiylari(t).items():
            global_doimiy[f"{modul}.{nom}"] = sql

    check("skaner doimiy topdi", len(global_doimiy) > 20,
          f"{len(global_doimiy)} ta")

    # --- SKAN ---
    buzuq = []
    chaqiruv = 0
    for yol, t in daraxtlar.items():
        mahalliy = _modul_doimiylari(t)
        for n in ast.walk(t):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            f = n.func
            nom = (f.attr if isinstance(f, ast.Attribute)
                   else f.id if isinstance(f, ast.Name) else None)
            if nom not in OQISH_YOLI:
                continue
            chaqiruv += 1
            a = n.args[0]
            sql = None
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                sql = a.value
            elif isinstance(a, ast.Name):
                sql = mahalliy.get(a.id)
            elif isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name):
                sql = global_doimiy.get(f"{a.value.id}.{a.attr}")
            elif isinstance(a, ast.BinOp) or isinstance(a, ast.JoinedStr):
                sql = " ".join(x.value for x in ast.walk(a)
                               if isinstance(x, ast.Constant)
                               and isinstance(x.value, str))
            if sql and YOZUV_RE.search(sql):
                buzuq.append(f"{os.path.relpath(yol, ROOT)}:{n.lineno} "
                             f"{nom}() <- {' '.join(sql.split())[:64]}")

    check(f"{chaqiruv} ta o'qish chaqiruvi skanerlandi", chaqiruv > 30,
          f"{chaqiruv} ta — skaner buzuqmi?")
    check("o'qish yo'lidan YOZUV o'tmaydi", not buzuq,
          "\n         ".join(buzuq[:6]))

    # --- SKANER O'ZINI SINAYDI ---
    # Yolg'on yashil bo'lmasin: uchala ko'rinish ham ushlanishi shart.
    namuna = '''
MENING_SQL = "DELETE FROM x WHERE id=%(i)s RETURNING id"
def f():
    db.query(MENING_SQL)
    db.query("UPDATE tender_requirement SET a=1 RETURNING id")
    db.query_one(queries.CATALOG_CLEAR_SQL)
    db.query("SELECT 1")
'''
    t = ast.parse(namuna)
    mahalliy = _modul_doimiylari(t)
    topildi = []
    for n in ast.walk(t):
        if not isinstance(n, ast.Call) or not n.args:
            continue
        f = n.func
        nom = f.attr if isinstance(f, ast.Attribute) else None
        if nom not in OQISH_YOLI:
            continue
        a = n.args[0]
        sql = None
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            sql = a.value
        elif isinstance(a, ast.Name):
            sql = mahalliy.get(a.id)
        elif isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name):
            sql = global_doimiy.get(f"{a.value.id}.{a.attr}")
        if sql and YOZUV_RE.search(sql):
            topildi.append(n.lineno)
    check("skaner: shu fayldagi doimiyni ushlaydi", len(topildi) >= 1)
    check("skaner: xom satrni ushlaydi", len(topildi) >= 2)
    check("skaner: BOSHQA moduldagi doimiyni ushlaydi", len(topildi) >= 3,
          f"{len(topildi)} ta ushlandi (3 kutilgan)")
    check("skaner: SELECT ni ushlamaydi", len(topildi) == 3, str(topildi))

    print("\n" + "=" * 70)
    print(f"NATIJA: {pass_}/{pass_ + fail_} o'tdi")
    print("=" * 70)
    return 1 if fail_ else 0


if __name__ == "__main__":
    sys.exit(main())
