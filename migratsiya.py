#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MIGRATSIYA YURGIZUVCHISI — QO'LLANGANI ANIQ MA'LUM BO'LSIN
===========================================================

NEGA BU FAYL BOR
----------------
Loyihada 53 ta `schema_patch_*.sql` bor edi va ularni qo'llashning
yagona usuli shu edi:

    Get-ChildItem schema_patch_*.sql | ForEach-Object { psql -f $_ }

Bu uchta narsani JIMGINA buzadi (o'lchandi, 2026-08-31):

  1. TARTIB. `Get-ChildItem` ALFAVIT beradi, alfavit esa
     bog'liqlikni BILMAYDI. O'lchandi (2026-08-31): fayllardan
     chiqarilgan bog'liqlik grafida alfavit tartibi 67 TA YOYNI
     TESKARI qo'yadi. Ikkita aniq misol:

       `schema_patch_notify_subscribers.sql` o'z sarlavhasida
       "OLDIN `schema_patch_notify_telegram.sql` qo'llanilgan
       bo'lishi kerak" deb YOZGAN. Alfavitda esa `_subscribers`
       `_telegram` dan OLDIN keladi — ya'ni fayl o'zi yozgan
       talab alfavit bilan BUZILADI.

       `schema_patch_catalog.sql` `dim_category_uz` jadvalini
       ishlatadi, uni esa `schema_patch_categories.sql` yaratadi.
       Alfavitda `catalog` `categories` dan oldin.

     Va bu natijaga TA'SIR QILADI: 8 ta obyektni bir nechta patch
     yaratadi (`v_requirement_review` ni TO'RTTA), ya'ni oxirgi
     qo'llangani yutadi.

  2. QAYTA QO'LLASH. Patchlar idempotent, lekin idempotentlik DDL
     uchun ishlaydi, MA'LUMOT KO'CHIRISH uchun emas.
     `schema_patch_requirement_8.sql` 1 487 qatorni ko'chirdi va
     "oldin/keyin" suratini yozdi; qayta yurgizilsa surat
     yangilanardi va haqiqiy boshlang'ich holat YO'QOLARDI.

  3. FARQ. Fayl tahrirlansa, bazadagi holat bilan repozitoriydagi
     matn orasidagi farqni hech narsa ko'rsatmasdi.

NIMA QILADI
-----------
  - `migratsiya_manifest.tsv` dagi MUZLATILGAN tartibni o'qiydi.
  - Har fayl uchun SHA-256 hisoblaydi.
  - `schema_migration` jurnaliga qaraydi va ALLAQACHON muvaffaqiyatli
    yozilganini QAYTA YURGIZMAYDI. Bu qoida bazada ham qulflangan
    (qisman unikal indeks) — ya'ni kod xato qilsa ham yozilmaydi.
  - Yurgizishdan OLDIN "boshlandi" qatorini ALOHIDA ulanishda yozadi
    va DARHOL commit qiladi. Shuning uchun jarayon o'ldirilsa ham
    qator QOLADI va uzilish KO'RINADI.
  - `psql` ni chaqiradi (`ON_ERROR_STOP=1` bilan). psycopg2 emas:
    4 ta patch psql meta-buyruqlarini ishlatadi, `multitenant.sql`
    esa `\\if :{?tenant_id}` — psql O'ZGARUVCHISI.

ISHGA TUSHIRISH
---------------
    python migratsiya.py --holat          # nima qo'llangan, nima yo'q
    python migratsiya.py --reja           # nima yuriladi (yurgizmaydi)
    python migratsiya.py --qolla          # qo'llash
    python migratsiya.py --bootstrap      # mavjud bazani ro'yxatga olish
    python migratsiya.py --tekshir        # checksum va butunlik
    python migratsiya.py --manifest-yasa  # tartibni qayta chiqarish

CHIQISH KODI: 0 — hammasi joyida; 1 — xato; 2 — odam aralashuvi kerak.
"""
from __future__ import annotations

import argparse
import getpass
import glob
import hashlib
import io
import os
import re
import socket
import subprocess
import sys
import time
from typing import Dict, List, Optional, Sequence, Set, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(ROOT, "migratsiya_manifest.tsv")
JURNAL_PATCH = "schema_patch_migratsiya.sql"

MULTITENANT_XABAR = (
    "Bu patch mavjud ma'lumotni QAYSI kompaniyaga biriktirishni\n"
    '        bilishi kerak va buni FAOL `company_account` dan oladi.\n'
    "        Hozir faol hisob YO'Q.\n"
    '\n'
    "        Bo'sh bazada: avval kompaniya hisobi yarating.\n"
    "        Mavjud bazada: aniq ko'rsating —\n"
    '            python migratsiya.py --qolla --var tenant_id=<id>\n'
    '\n'
    "        NEGA AVTOMATIK TANLANMAYDI: patch o'z izohida yozgan —\n"
    "        eng kichik `id` O'CHIRILGAN SINOV hisobiga tegishli\n"
    "        bo'lishi mumkin va butun kompaniya ma'lumoti noto'g'ri\n"
    '        egaga biriktirilardi.')

#: Maslahat qulfi kaliti. `etl_ishonch.py` boshqa kalitdan foydalanadi —
#: migratsiya va ETL bir-birini to'smasligi kerak.
QULF_KALIT = 848213771

#: Bitta patchning yuqori vaqt chegarasi. Osilgan migratsiya butun
#: joylashtirishni to'sib qo'ymasin.
TIMEOUT = int(os.environ.get("MIGRATSIYA_TIMEOUT", "1800"))

#: USTUN DARAJASIDAGI BOG'LIQLIKLAR — QO'LDA, O'LCHANGAN.
#:
#: Avtomatik tahlil JADVAL darajasida ishlaydi: "bu patch qaysi
#: jadvalga tegadi". USTUN darajasini u KO'RMAYDI — `ALTER TABLE t
#: ADD COLUMN c` bilan qo'shilgan ustunga keyingi patch murojaat
#: qilsa, graf buni sezmaydi.
#:
#: Bu yoylar TAXMIN EMAS: har biri BO'SH BAZADA qurish sinovidagi
#: AYNAN BITTA psql xatosidan chiqqan va o'sha xato yoniga yozilgan.
#: Ular `--manifest-yasa` da grafga qo'shiladi.
QOLDA_YOY: List[Tuple[str, str, str]] = [
    ("schema_patch_source.sql", "schema_patch_multiplatform.sql",
     'psql: "source_platform" ustuni yo`q (multiplatform.sql:37)'),
]

#: MA'LUMOTGA BOG'LIQ MIGRATSIYALAR.
#:
#: Ba'zi patchlar sof DDL emas — ular BAZADA MA'LUMOT borligini
#: talab qiladi. Bunday patch bo'sh bazada `RAISE EXCEPTION` bilan
#: yiqiladi va xom psql xatosi sababni tushuntirmaydi.
#:
#: Bu yerda shart OLDINDAN tekshiriladi va odam o'qiy oladigan xabar
#: beriladi. Shart bajarilmasa migratsiya UMUMAN BOSHLANMAYDI —
#: yarim qo'llangan holat yaratilmaydi.
#:
#: Format: fayl -> (bitta butun son qaytaruvchi SQL, eng kam qiymat,
#:                  xabar)
MALUMOTGA_BOGLIQ: Dict[str, Tuple[str, int, str]] = {
    "schema_patch_multitenant.sql": (
        "SELECT count(*) FROM company_account WHERE active", 1, MULTITENANT_XABAR),
}

sys.path.insert(0, os.path.join(ROOT, "_tests"))
try:
    import konsol
    konsol.sozla()
except Exception:                                             # pragma: no cover
    pass


# =====================================================================
# psql ni topish
# =====================================================================
def psql_top() -> str:
    """`psql` yo'lini qaytaradi yoki BALAND OVOZDA yiqiladi.

    Bu mashinada `psql` PATH da YO'Q (o'lchandi 2026-08-31), shuning
    uchun standart o'rnatish kataloglari ham qaraladi. Topilmasa
    jimgina davom etmaydi — migratsiya yurgizuvchisi psql'siz hech
    narsa qila olmaydi va buni darhol aytishi kerak.
    """
    berilgan = os.environ.get("PSQL")
    if berilgan:
        if os.path.exists(berilgan):
            return berilgan
        raise SystemExit(f"PSQL='{berilgan}' ko'rsatilgan, lekin bunday fayl YO'Q")

    from shutil import which
    y = which("psql")
    if y:
        return y

    naqshlar = [
        r"C:\Program Files\PostgreSQL\*\bin\psql.exe",
        r"C:\Program Files (x86)\PostgreSQL\*\bin\psql.exe",
        "/usr/bin/psql", "/usr/local/bin/psql", "/opt/homebrew/bin/psql",
    ]
    topildi: List[str] = []
    for n in naqshlar:
        topildi.extend(glob.glob(n))
    if topildi:
        # Eng YANGI versiya (yo'ldagi raqam bo'yicha), aks holda
        # 12-versiya 18-dan oldin tanlanardi.
        def ver(p: str) -> Tuple[int, ...]:
            return tuple(int(x) for x in re.findall(r"\d+", p)) or (0,)
        return sorted(topildi, key=ver)[-1]

    raise SystemExit(
        "psql TOPILMADI. PATH ga qo'shing yoki PSQL o'zgaruvchisida "
        "to'liq yo'lni bering:\n"
        r'    $env:PSQL = "C:\Program Files\PostgreSQL\18\bin\psql.exe"')


def dsn_qismlari(dsn: str) -> Dict[str, str]:
    """`key=value` shaklidagi DSN ni lug'atga aylantiradi."""
    if dsn.strip().startswith(("postgres://", "postgresql://")):
        from urllib.parse import urlparse, unquote
        u = urlparse(dsn)
        return {k: v for k, v in {
            "host": u.hostname or "", "port": str(u.port or 5432),
            "user": unquote(u.username or ""),
            "password": unquote(u.password or ""),
            "dbname": (u.path or "/").lstrip("/"),
        }.items() if v}
    d: Dict[str, str] = {}
    for bolak in dsn.split():
        if "=" in bolak:
            k, v = bolak.split("=", 1)
            d[k.strip()] = v.strip().strip("'\"")
    return d


def psql_muhit(dsn: str) -> Dict[str, str]:
    q = dsn_qismlari(dsn)
    env = dict(os.environ)
    for kalit, nom in (("host", "PGHOST"), ("port", "PGPORT"),
                       ("user", "PGUSER"), ("password", "PGPASSWORD"),
                       ("dbname", "PGDATABASE")):
        if q.get(kalit):
            env[nom] = q[kalit]
    # psql chiqishi UTF-8 bo'lsin: bu mashinada konsol kod sahifasi
    # cp1251 va xato matni buzilib kelardi.
    env["PGCLIENTENCODING"] = "UTF8"
    return env


# =====================================================================
# Checksum va fayl xossalari
# =====================================================================
def normalla(matn: str) -> str:
    """Checksum uchun matnni normallashtiradi.

    FAQAT qator oxiri va oxirgi bo'shliqlar tozalanadi. IZOHLAR
    ATAYLAB QOLDIRILADI: bu loyihada izoh QARORNI va O'LCHOVNI
    saqlaydi, ya'ni u ham faylning bir qismi. Izoh o'zgarsa checksum
    o'zgaradi va yurgizuvchi to'xtaydi — bu to'g'ri xulq: fayl
    o'zgargani KO'RINISHI kerak. O'zgarish xavfsiz ekani tasdiqlansa
    `--checksum-yangila` bilan qayta muhrlanadi va bu ham jurnalga
    yoziladi, ya'ni jimgina o'tmaydi.
    """
    qatorlar = [q.rstrip() for q in matn.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while qatorlar and not qatorlar[-1]:
        qatorlar.pop()
    return "\n".join(qatorlar) + "\n"


def checksum(yol: str) -> str:
    matn = io.open(yol, encoding="utf-8", errors="strict").read()
    return hashlib.sha256(normalla(matn).encode("utf-8")).hexdigest()


def _kodsiz(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r"--[^\n]*", " ", s)


def tranzaksionmi(matn: str) -> bool:
    """Fayl O'Z `BEGIN`/`COMMIT` ini olib yuradimi.

    Bu uzilgan migratsiyani hal qilishda HAL QILUVCHI: tranzaksion
    fayl o'ldirilsa PostgreSQL hammasini qaytaradi (yarim qo'llanish
    yo'q), tranzaksiyasiz fayl esa YARIM qolishi mumkin.
    """
    s = _kodsiz(matn).lower()
    return bool(re.search(r"^\s*begin\s*;", s, re.M)) and \
        bool(re.search(r"^\s*commit\s*;", s, re.M))


def tranzaksiyaga_yaramaydi(matn: str) -> List[str]:
    """Tranzaksiya ichida YURA OLMAYDIGAN buyruqlarni sanaydi.

    Bularni `--single-transaction` bilan o'rash PostgreSQL xatosi
    beradi. Yurgizuvchi bunday faylni o'ramaydi va SABABINI aytadi.
    """
    s = _kodsiz(matn).lower()
    sabab = []
    if re.search(r"create\s+(unique\s+)?index\s+concurrently", s):
        sabab.append("CREATE INDEX CONCURRENTLY")
    if re.search(r"\balter\s+type\s+\w+\s+add\s+value", s):
        sabab.append("ALTER TYPE ... ADD VALUE")
    if re.search(r"\bvacuum\b", s):
        sabab.append("VACUUM")
    if re.search(r"\b(create|drop)\s+database\b", s):
        sabab.append("CREATE/DROP DATABASE")
    if re.search(r"\breindex\s+.*concurrently", s):
        sabab.append("REINDEX CONCURRENTLY")
    return sabab


def obyektlar(matn: str) -> Tuple[Set[Tuple[str, str]], Set[Tuple[str, str]]]:
    """(yaratiladigan, tashlanadigan) obyektlar to'plamini qaytaradi.

    `bootstrap` tekshiruvi uchun kerak. Sxema prefiksi olib tashlanadi
    (`public.login_attempt` -> `login_attempt`), aks holda bir obyekt
    ikki xil nom bilan hisoblanardi — bu haqiqiy xato bo'lgan:
    dastlabki tahlil `public` ni JADVAL NOMI deb o'qigan.
    """
    s = _kodsiz(matn).lower()
    ID = r"(?:[a-z_][a-z0-9_]*\.)?([a-z_][a-z0-9_]*)"
    yar: Set[Tuple[str, str]] = set()
    tash: Set[Tuple[str, str]] = set()
    for rx, tur, hedef in (
        (rf"create\s+table\s+(?:if\s+not\s+exists\s+)?{ID}", "table", yar),
        (rf"create\s+(?:or\s+replace\s+)?view\s+{ID}", "view", yar),
        (rf"create\s+(?:or\s+replace\s+)?function\s+{ID}", "func", yar),
        (rf"create\s+type\s+{ID}", "type", yar),
        (rf"drop\s+table\s+(?:if\s+exists\s+)?{ID}", "table", tash),
        (rf"drop\s+view\s+(?:if\s+exists\s+)?{ID}", "view", tash),
        (rf"drop\s+function\s+(?:if\s+exists\s+)?{ID}", "func", tash),
    ):
        for m in re.finditer(rx, s):
            hedef.add((tur, m.group(1)))
    return yar, tash


# =====================================================================
# Manifest
# =====================================================================
class Yozuv:
    __slots__ = ("tartib", "mid", "fayl")

    def __init__(self, tartib: int, mid: str, fayl: str):
        self.tartib, self.mid, self.fayl = tartib, mid, fayl

    @property
    def yol(self) -> str:
        return os.path.join(ROOT, self.fayl)


def manifest_oqi() -> List[Yozuv]:
    if not os.path.exists(MANIFEST):
        raise SystemExit(
            f"Manifest YO'Q: {MANIFEST}\n"
            "`python migratsiya.py --manifest-yasa` bilan yarating.")
    yozuvlar: List[Yozuv] = []
    korilgan: Set[str] = set()
    for n, qator in enumerate(io.open(MANIFEST, encoding="utf-8"), 1):
        qator = qator.rstrip("\n")
        if not qator.strip() or qator.lstrip().startswith("#"):
            continue
        bolak = qator.split("\t")
        if len(bolak) != 3:
            raise SystemExit(f"{MANIFEST}:{n}: 3 ta ustun kutilgandi, "
                             f"{len(bolak)} ta topildi")
        tartib, mid, fayl = bolak[0].strip(), bolak[1].strip(), bolak[2].strip()
        if mid in korilgan:
            raise SystemExit(f"{MANIFEST}:{n}: `{mid}` TAKRORLANGAN")
        korilgan.add(mid)
        yozuvlar.append(Yozuv(int(tartib), mid, fayl))
    # Tartib qat'iy o'suvchi bo'lishi SHART — aks holda "qaysi oldin"
    # savoliga manifest javob bermasdi.
    for a, b in zip(yozuvlar, yozuvlar[1:]):
        if b.tartib <= a.tartib:
            raise SystemExit(f"Manifest tartibi o'smaydi: {a.tartib} -> {b.tartib}")
    return yozuvlar


def manifest_yasa() -> List[Yozuv]:
    """Bog'liqliklardan topologik tartib chiqaradi.

    NATIJA MUZLATILADI: `migratsiya_manifest.tsv` ga yozilib,
    repozitoriyga commit qilinadi. Yurgizuvchi tartibni HECH QACHON
    ish paytida qayta chiqarmaydi — aks holda yangi fayl qo'shilishi
    eski tartibni jimgina siljitishi mumkin edi.
    """
    from collections import defaultdict
    import heapq

    fayllar = ["xt_xarid_schema.sql"] + sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "schema_patch_*.sql")))
    # Jurnal patchi HAR DOIM birinchi: usiz jurnal jadvali yo'q.
    if JURNAL_PATCH in fayllar:
        fayllar.remove(JURNAL_PATCH)

    xom: Dict[str, str] = {}
    yar: Dict[str, Set[Tuple[str, str]]] = {}
    tegadi: Dict[str, Set[str]] = {}
    elon: Dict[str, List[str]] = {}
    for f in fayllar:
        matn = io.open(os.path.join(ROOT, f), encoding="utf-8", errors="replace").read()
        xom[f] = matn
        yar[f] = obyektlar(matn)[0]
        s = _kodsiz(matn).lower()
        ID = r"(?:[a-z_][a-z0-9_]*\.)?([a-z_][a-z0-9_]*)"
        t: Set[str] = set()
        for rx in (rf"alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{ID}",
                   rf"references\s+{ID}",
                   rf"\b(?:from|join)\s+{ID}",
                   rf"\b(?:insert\s+into|update)\s+(?:only\s+)?{ID}",
                   rf"create\s+(?:unique\s+)?index\s+(?:concurrently\s+)?"
                   rf"(?:if\s+not\s+exists\s+)?[a-z0-9_]+\s+on\s+{ID}"):
            t.update(m.group(1) for m in re.finditer(rx, s))
        tegadi[f] = t
        elon[f] = re.findall(
            r"(schema_patch_[a-z0-9_]+\.sql)",
            "\n".join(q for q in matn.splitlines()
                      if re.match(r"^\s*--\s*(Talab|OLDIN|Oldin)", q)))

    yoy: Dict[str, Set[str]] = defaultdict(set)

    def qoy(a: str, b: str) -> None:
        if a != b and a in yar and b in yar:
            yoy[a].add(b)

    for f in fayllar:                                  # asosiy sxema birinchi
        qoy("xt_xarid_schema.sql", f)
    for f, talablar in elon.items():                   # e'lon qilingan talab
        for t in talablar:
            qoy(t, f)
    for oldin, keyin, _sabab in QOLDA_YOY:             # o'lchangan ustun yoylari
        qoy(oldin, keyin)
    oila: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for f in fayllar:                                  # raqamli suffiks
        m = re.match(r"schema_patch_(.+?)(?:_(\d+))?\.sql$", f)
        if m:
            oila[m.group(1)].append((int(m.group(2) or 1), f))
    for lst in oila.values():
        lst.sort()
        for (_n1, f1), (_n2, f2) in zip(lst, lst[1:]):
            qoy(f1, f2)
    kim: Dict[str, List[str]] = defaultdict(list)      # obyekt bog'liqligi
    for f in fayllar:
        for _t, nom in yar[f]:
            kim[nom].append(f)
    for f in fayllar:
        oz = {n for _t, n in yar[f]}
        for o in tegadi[f] - oz:
            for g in kim.get(o, []):
                qoy(g, f)

    def gsana(f: str) -> int:
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%ct", "-1", "--", f],
                           capture_output=True, text=True, cwd=ROOT)
        return int((r.stdout or "0").strip() or 0)

    kalit = {f: (gsana(f), f) for f in fayllar}
    kirish = {f: 0 for f in fayllar}
    for a, bs in yoy.items():
        for b in bs:
            kirish[b] += 1
    navbat = [(kalit[f], f) for f in fayllar if kirish[f] == 0]
    heapq.heapify(navbat)
    tartib: List[str] = []
    while navbat:
        _, f = heapq.heappop(navbat)
        tartib.append(f)
        for b in sorted(yoy[f]):
            kirish[b] -= 1
            if kirish[b] == 0:
                heapq.heappush(navbat, (kalit[b], b))
    if len(tartib) != len(fayllar):
        qolgan = [f for f in fayllar if f not in tartib]
        raise SystemExit("Bog'liqlik SIKLI bor, tartib chiqmadi:\n  " +
                         "\n  ".join(qolgan))

    # Jurnal patchi 1-o'rinda.
    tolik = [JURNAL_PATCH] + tartib

    # `migratsiya_id` MAVJUD MANIFESTDAN OLINADI, POZITSIYADAN EMAS.
    #
    # O'LCHANGAN NUQSON (2026-09-06). Bu yerda id POZITSIYADAN
    # chiqarilardi (`f"{i:04d}_{nom}"`), ya'ni bitta yangi fayl
    # o'rtaga tushsa undan KEYINGI HAMMA id siljirdi. Manifest
    # sarlavhasi esa buning TESKARISINI e'lon qiladi:
    #
    #     `migratsiya_id` BARQAROR: fayl qayta nomlansa ham
    #     o'zgartirilmaydi, aks holda jurnal tarixi uzilardi.
    #
    # Ya'ni vosita o'z shartnomasiga zid ishlardi. Narxi nazariy
    # emas: jurnal (`schema_migration`) aynan `migratsiya_id`
    # bo'yicha kalitlanadi (`Jurnal.qollangan()`), ya'ni id
    # siljigach yurgizuvchi ALLAQACHON QO'LLANGAN migratsiyani
    # "qo'llanmagan" deb ko'rib QAYTA YURGIZARDI. Ishlab
    # chiqarishda bu ma'lumot yo'qotishi bilan tugaydi.
    #
    # Aynan shu sabab 2026-09-06 dagi `main` birlashmasida
    # `--manifest-yasa` CHAQIRILMAGAN va manifest QO'LDA
    # birlashtirilgan edi. Endi vositaning o'zi xavfsiz.
    #
    # QOIDA: fayl nomi manifestda bor -> id O'ZGARMAYDI.
    #        Yangi fayl -> eng katta raqamdan KEYINGI raqam.
    # Fayl QAYTA NOMLANSA baribir yangi id oladi (moslik nom
    # bo'yicha) — bu holat qo'lda tuzatiladi, sarlavha shuni aytadi.
    mavjud: Dict[str, str] = {}
    band: Set[int] = set()
    if os.path.exists(MANIFEST):
        for y in manifest_oqi():
            mavjud[y.fayl] = y.mid
            m = re.match(r"^(\d+)_", y.mid)
            if m:
                band.add(int(m.group(1)))
    keyingi = max(band) + 1 if band else 1

    yozuvlar = []
    korilgan: Set[str] = set()
    for i, f in enumerate(tolik, 1):
        mid = mavjud.get(f)
        if mid is None:
            nom = re.sub(r"^schema_patch_|\.sql$", "", f) or f
            mid = f"{keyingi:04d}_{nom}"
            keyingi += 1
        # TAKROR — JIM O'TMAYDI. Manifest qo'lda tahrirlanganda
        # ikki fayl bir id ga ega bo'lib qolishi mumkin va u
        # holda jurnal ikkalasini BITTA deb hisoblardi.
        if mid in korilgan:
            raise SystemExit(
                f"`migratsiya_id` TAKRORLANDI: {mid} ({f}). "
                f"{MANIFEST} ni qo'lda tuzating.")
        korilgan.add(mid)
        yozuvlar.append(Yozuv(i * 10, mid, f))
    return yozuvlar


def manifest_yoz(yozuvlar: Sequence[Yozuv]) -> None:
    with io.open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "# MIGRATSIYA MANIFESTI — MUZLATILGAN TARTIB\n"
            "#\n"
            "# Ustunlar: tartib <TAB> migratsiya_id <TAB> fayl\n"
            "#\n"
            "# Bu tartib bog'liqliklardan CHIQARILGAN (e'lon qilingan\n"
            "# talablar, raqamli suffikslar, obyekt bog'liqliklari) va\n"
            "# BO'SH BAZADA qurish bilan TEKSHIRILGAN.\n"
            "#\n"
            "# Yurgizuvchi tartibni ish paytida QAYTA CHIQARMAYDI —\n"
            "# faqat shu fayldan o'qiydi. Sabab: yangi patch qo'shilishi\n"
            "# eski tartibni jimgina siljitmasin.\n"
            "#\n"
            "# Yangi patch qo'shish: fayl nomini oxiriga yozing, tartibga\n"
            "# oldingisidan katta raqam bering (10 lik qadam ataylab —\n"
            "# orasiga qo'yish uchun joy qoladi).\n"
            "#\n"
            "# `migratsiya_id` BARQAROR: fayl qayta nomlansa ham\n"
            "# o'zgartirilmaydi, aks holda jurnal tarixi uzilardi.\n"
            "#\n")
        for y in yozuvlar:
            f.write(f"{y.tartib}\t{y.mid}\t{y.fayl}\n")


# =====================================================================
# Jurnal — ALOHIDA ulanishda, o'ldirilsa ham saqlanadi
# =====================================================================
class Jurnal:
    """`schema_migration` ga yozadi.

    ALOHIDA ULANISH va `autocommit`. Bu ataylab: migratsiya psql
    ichida O'Z tranzaksiyasida yuradi, jurnal esa undan MUSTAQIL
    yozilishi kerak. Aks holda migratsiya qaytarilganda jurnal
    qatori ham qaytarilardi va uzilish IZSIZ yo'qolardi — bu
    loyihada `etl_run` bilan aynan shu bo'lgan.
    """

    def __init__(self, dsn: str):
        import psycopg2
        self.conn = psycopg2.connect(dsn, connect_timeout=10)
        self.conn.autocommit = True
        self.kim = f"{getpass.getuser()}@{socket.gethostname()}"

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:                                     # pragma: no cover
            pass

    # ---- qulf ----
    def qulfla(self) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (QULF_KALIT,))
            return bool(cur.fetchone()[0])

    def qulfni_bosh(self) -> None:
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (QULF_KALIT,))
        except Exception:                                     # pragma: no cover
            pass

    # ---- o'qish ----
    def jadval_bormi(self) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.schema_migration')")
            return cur.fetchone()[0] is not None

    def qollangan(self) -> Dict[str, Tuple[str, str]]:
        """migratsiya_id -> (holat, checksum) — faqat ok/bootstrap."""
        if not self.jadval_bormi():
            return {}
        with self.conn.cursor() as cur:
            cur.execute("SELECT migratsiya_id, holat, checksum FROM schema_migration "
                        "WHERE holat IN ('ok','bootstrap')")
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    def uzilganlar(self) -> List[Tuple[str, str, Optional[bool], str]]:
        if not self.jadval_bormi():
            return []
        with self.conn.cursor() as cur:
            cur.execute("SELECT migratsiya_id, fayl, tranzaksion, "
                        "to_char(boshlandi_at,'YYYY-MM-DD HH24:MI:SS') "
                        "FROM schema_migration WHERE holat='boshlandi' "
                        "ORDER BY boshlandi_at")
            return list(cur.fetchall())

    def urinishlar(self, mid: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migration "
                        "WHERE migratsiya_id=%s AND holat='xato'", (mid,))
            return cur.fetchone()[0]

    # ---- yozish ----
    def boshla(self, y: Yozuv, ck: str, tranz: bool) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migration "
                "(migratsiya_id, fayl, tartib, checksum, holat, tranzaksion, yurgizuvchi) "
                "VALUES (%s,%s,%s,%s,'boshlandi',%s,%s) RETURNING id",
                (y.mid, y.fayl, y.tartib, ck, tranz, self.kim))
            return cur.fetchone()[0]

    def tugat(self, sid: int, holat: str, ms: int, kod: int,
              xato: Optional[str]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE schema_migration SET holat=%s, tugadi_at=now(), "
                "davomiylik_ms=%s, chiqish_kod=%s, xato=%s WHERE id=%s",
                (holat, ms, kod, xato, sid))

    def ozini_yoz(self, y: Yozuv, ck: str, tranz: bool, ms: int) -> None:
        """Jurnal patchining O'ZINI tugallangan `ok` qator sifatida yozadi.

        TOVUQ-TUXUM: jurnal jadvalini yaratadigan patch uchun
        "boshlandi" qatorini OLDINDAN yozib bo'lmaydi — jadval hali
        yo'q. Shuning uchun u yurgizilgandan KEYIN bir marta yoziladi.

        Holat `ok` (`bootstrap` emas), chunki fayl HAQIQATAN
        yurgizildi. Farqi izohda ochiq yozib qo'yiladi: bu yagona
        migratsiya bo'lib, uzilishi jurnalda ko'rinmasdi — lekin u
        o'z tranzaksiyasida yuradi, ya'ni uzilsa jadval umuman
        yaratilmaydi va keyingi yurish shu yerdan qayta boshlaydi.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migration "
                "(migratsiya_id, fayl, tartib, checksum, holat, tranzaksion, "
                " tugadi_at, davomiylik_ms, chiqish_kod, yurgizuvchi, izoh) "
                "VALUES (%s,%s,%s,%s,'ok',%s,now(),%s,0,%s,%s)",
                (y.mid, y.fayl, y.tartib, ck, tranz, ms, self.kim,
                 "jurnalning o'zini qurgan patch: `boshlandi` qatori "
                 "yozilmadi, chunki jadval hali mavjud emas edi"))

    def bootstrap_yoz(self, y: Yozuv, ck: str, tranz: bool, izoh: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migration "
                "(migratsiya_id, fayl, tartib, checksum, holat, tranzaksion, "
                " tugadi_at, davomiylik_ms, yurgizuvchi, izoh) "
                "VALUES (%s,%s,%s,%s,'bootstrap',%s,now(),0,%s,%s)",
                (y.mid, y.fayl, y.tartib, ck, tranz, self.kim, izoh))

    def checksum_yangila(self, y: Yozuv, yangi: str, izoh: str) -> None:
        """Eski `ok` qatorini `otkazildi` ga o'tkazib, yangi checksum
        bilan yangi `bootstrap` qator qo'yadi.

        Eski qator O'CHIRILMAYDI — u nima qo'llangani haqidagi dalil.
        Qayta muhrlash JURNALDA ko'rinadi, jimgina o'tmaydi.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE schema_migration SET holat='otkazildi', "
                "izoh = coalesce(izoh,'') || %s "
                "WHERE migratsiya_id=%s AND holat IN ('ok','bootstrap')",
                (f" [checksum qayta muhrlandi {time.strftime('%Y-%m-%d')}]", y.mid))
            cur.execute(
                "INSERT INTO schema_migration "
                "(migratsiya_id, fayl, tartib, checksum, holat, tugadi_at, "
                " davomiylik_ms, yurgizuvchi, izoh) "
                "VALUES (%s,%s,%s,%s,'bootstrap',now(),0,%s,%s)",
                (y.mid, y.fayl, y.tartib, yangi, self.kim, izoh))

    # ---- baza obyektlari ----
    def mavjud_obyektlar(self) -> Set[Tuple[str, str]]:
        s: Set[Tuple[str, str]] = set()
        with self.conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_type='BASE TABLE'")
            s |= {("table", r[0]) for r in cur.fetchall()}
            cur.execute("SELECT table_name FROM information_schema.views "
                        "WHERE table_schema='public'")
            s |= {("view", r[0]) for r in cur.fetchall()}
            cur.execute("SELECT p.proname FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname='public'")
            s |= {("func", r[0]) for r in cur.fetchall()}
            cur.execute("SELECT t.typname FROM pg_type t "
                        "JOIN pg_namespace n ON n.oid=t.typnamespace "
                        "WHERE n.nspname='public' AND t.typtype='e'")
            s |= {("type", r[0]) for r in cur.fetchall()}
        return s


# =====================================================================
# Yurgizish
# =====================================================================
def psql_yurgiz(psql: str, env: Dict[str, str], yol: str,
                oramaymiz: bool, ozgaruvchilar: Sequence[str]) -> Tuple[int, str]:
    """Bitta faylni psql orqali yurgizadi. -> (chiqish_kodi, chiqish)."""
    args = [psql, "-v", "ON_ERROR_STOP=1", "--no-psqlrc", "-q"]
    # FAYL O'Z TRANZAKSIYASINI OLIB YURSA `--single-transaction`
    # QO'SHILMAYDI. Aks holda ichkaridagi `COMMIT` tashqi
    # tranzaksiyani ERTA yopardi va undan keyingi xato QAYTARILMASDAN
    # qolardi — ya'ni "tranzaksion" degan da'vo YOLG'ON bo'lardi.
    if not oramaymiz:
        args.append("--single-transaction")
    for o in ozgaruvchilar:
        args += ["-v", o]
    args += ["-f", yol]
    try:
        r = subprocess.run(args, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="backslashreplace",
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT: {TIMEOUT} s ichida tugamadi"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


# =====================================================================
# Buyruqlar
# =====================================================================
def _dsn() -> str:
    dsn = os.environ.get("XT_DB_DSN")
    if not dsn:
        raise SystemExit("XT_DB_DSN o'rnatilmagan (.env ni tekshiring)")
    return dsn


def _holat_jadval(yozuvlar: Sequence[Yozuv], j: Jurnal) -> Tuple[int, int, int]:
    qollangan = j.qollangan()
    ok = yoq = farq = 0
    print(f"{'#':>4}  {'migratsiya_id':<34} {'holat':<10} {'checksum':<9} tranz")
    print("-" * 78)
    for y in yozuvlar:
        bor = os.path.exists(y.yol)
        ck = checksum(y.yol) if bor else ""
        h, saqlangan = qollangan.get(y.mid, ("—", ""))
        if not bor:
            belgi, ck_belgi = "FAYL YO'Q", "—"
        elif h == "—":
            belgi, ck_belgi = "qo'llanmagan", "—"
            yoq += 1
        elif saqlangan != ck:
            belgi, ck_belgi = h, "FARQ !!"
            farq += 1
            ok += 1
        else:
            belgi, ck_belgi = h, "mos"
            ok += 1
        tr = ""
        if bor:
            tr = "ha" if tranzaksionmi(io.open(y.yol, encoding="utf-8",
                                               errors="replace").read()) else "yo'q"
        print(f"{y.tartib:>4}  {y.mid:<34} {belgi:<10} {ck_belgi:<9} {tr}")
    return ok, yoq, farq


def buyruq_holat(yozuvlar: Sequence[Yozuv], j: Jurnal) -> int:
    if not j.jadval_bormi():
        print("`schema_migration` jadvali YO'Q — jurnal hali qurilmagan.")
        print("Mavjud baza uchun:  python migratsiya.py --bootstrap")
        print("Bo'sh baza uchun:   python migratsiya.py --qolla")
        return 2
    ok, yoq, farq = _holat_jadval(yozuvlar, j)
    print("-" * 78)
    print(f"Qo'llangan: {ok}   Qo'llanmagan: {yoq}   Checksum FARQI: {farq}")
    uz = j.uzilganlar()
    if uz:
        print(f"\n!!! UZILGAN MIGRATSIYA: {len(uz)} ta")
        for mid, fayl, tranz, vaqt in uz:
            nima = ("tranzaksion edi -> DDL qaytarilgan, baza toza"
                    if tranz else
                    "TRANZAKSIYASIZ edi -> YARIM qo'llangan bo'lishi MUMKIN")
            print(f"    {mid}  ({vaqt})  {nima}")
        return 2
    return 0 if (yoq == 0 and farq == 0) else 1


def buyruq_tekshir(yozuvlar: Sequence[Yozuv], j: Jurnal) -> int:
    """Butunlikni tekshiradi. Yurgizmaydi."""
    xato = 0
    print("=== 1) Manifest fayllari mavjudmi ===")
    for y in yozuvlar:
        if not os.path.exists(y.yol):
            print(f"  YO'Q: {y.fayl}  ({y.mid})"); xato += 1
    print(f"  {len(yozuvlar) - xato}/{len(yozuvlar)} topildi")

    print("\n=== 2) Diskda bor, manifestda YO'Q ===")
    manifestda = {y.fayl for y in yozuvlar}
    diskda = {os.path.basename(p) for p in
              glob.glob(os.path.join(ROOT, "schema_patch_*.sql"))}
    diskda.add("xt_xarid_schema.sql")
    yetim = sorted(diskda - manifestda)
    for f in yetim:
        print(f"  MANIFESTDA YO'Q: {f}")
        xato += 1
    if not yetim:
        print("  (yo'q)")

    print("\n=== 3) Tranzaksiyaga yaramaydigan buyruqlar ===")
    top = 0
    for y in yozuvlar:
        if not os.path.exists(y.yol):
            continue
        matn = io.open(y.yol, encoding="utf-8", errors="replace").read()
        sabab = tranzaksiyaga_yaramaydi(matn)
        if sabab:
            oz = tranzaksionmi(matn)
            print(f"  {y.fayl}: {', '.join(sabab)}"
                  f"{'  (o`z tranzaksiyasi ICHIDA — XATO BERADI)' if oz else ''}")
            top += 1
            if oz:
                xato += 1
    if not top:
        print("  (yo'q — hammasi tranzaksiyada yura oladi)")

    print("\n=== 4) Jurnal bilan checksum mosligi ===")
    if not j.jadval_bormi():
        print("  jurnal jadvali yo'q — o'tkazib yuborildi")
    else:
        q = j.qollangan()
        farq = 0
        for y in yozuvlar:
            if y.mid in q and os.path.exists(y.yol):
                if q[y.mid][1] != checksum(y.yol):
                    print(f"  FARQ: {y.mid} ({y.fayl})")
                    farq += 1
        print(f"  {farq} ta farq" if farq else "  hammasi mos")
        xato += farq

    print("\n=== 5) Uzilgan migratsiya ===")
    uz = j.uzilganlar() if j.jadval_bormi() else []
    if uz:
        for mid, fayl, tranz, vaqt in uz:
            print(f"  {mid} ({vaqt}) tranzaksion={tranz}")
        xato += len(uz)
    else:
        print("  (yo'q)")

    print("\n" + ("TEKSHIRUV O'TDI" if not xato else f"MUAMMO: {xato} ta"))
    return 0 if not xato else 1


def buyruq_bootstrap(yozuvlar: Sequence[Yozuv], j: Jurnal, psql: str,
                     env: Dict[str, str], quruq: bool) -> int:
    """Mavjud bazani ro'yxatga oladi — FAYLLARNI YURGIZMASDAN.

    Har patch uchun uning obyektlari BAZADA BORLIGI tekshiriladi.
    Faqat shunda "qo'llangan" deb yoziladi. Bu farq muhim: `ok`
    "yurgizildi" degani, `bootstrap` esa "obyektlari bor ekani
    O'LCHANDI" degani. Ikkisi bir xil emas va jurnal buni
    yashirmaydi.

    IKKI NOZIK JOY. Birinchisi: patch O'ZI yaratgan yordamchi
    obyektni O'ZI tashlashi mumkin (`multitenant.sql` ->
    `tai_add_company_id()`). Ikkinchisi: keyingi patch oldingisining
    obyektini ATAYLAB tashlashi mumkin. O'lchangan misol: `schema_patch_auth.sql`
    `app_user`/`app_session` yaratadi, `schema_patch_auth_2.sql` esa
    ularni ataylab tashlaydi (hisoblar `erp.app_user` ga ko'chgan).
    Shuning uchun kutilayotgan obyektlar = YARATILGANLAR minus
    KEYINGI patchlar TASHLAGANLAR. Busiz bootstrap `auth.sql` ni
    "yetishmayapti" deb NOTO'G'RI aytardi.
    """
    # Jurnal patchi HAQIQATAN yurgiziladi va `ok` deb yoziladi.
    # `bootstrap` deb yozish YOLG'ON bo'lardi: `bootstrap` "yurgizilmadi,
    # obyektlari tekshirildi" degani, bu esa yurgizildi.
    print("[1/2] Jurnal jadvali")
    if j.jadval_bormi():
        print("      allaqachon bor")
    else:
        kod = _jurnalni_taminla(yozuvlar, j, psql, env, quruq)
        if kod != 0:
            return kod

    # QURUQ YURISHDA JURNAL YO'Q BO'LSA HAM REJA KO'RSATILADI.
    # Aks holda `--bootstrap --quruq` aynan eng kerakli holatda —
    # jurnal hali qurilmagan bazada — hech narsa ko'rsatmasdi.
    # `qollangan()` jadval yo'q bo'lsa bo'sh lug'at qaytaradi.
    mavjud = j.mavjud_obyektlar()
    qollangan = j.qollangan()

    # Keyingi patchlar nimani tashlaydi
    tashlar: Dict[int, Set[Tuple[str, str]]] = {}
    kesh: Dict[str, Tuple[Set, Set]] = {}
    for y in yozuvlar:
        if os.path.exists(y.yol):
            kesh[y.mid] = obyektlar(io.open(y.yol, encoding="utf-8",
                                            errors="replace").read())
    for i, y in enumerate(yozuvlar):
        keyingi: Set[Tuple[str, str]] = set()
        for z in yozuvlar[i + 1:]:
            if z.mid in kesh:
                keyingi |= kesh[z.mid][1]
        tashlar[i] = keyingi

    print("\n[2/2] Har patchning obyektlari bazada tekshiriladi\n")
    yozildi = otdi = yetishmadi = 0
    muammo: List[Tuple[str, List[str]]] = []
    for i, y in enumerate(yozuvlar):
        if y.mid in qollangan:
            otdi += 1
            continue
        if not os.path.exists(y.yol):
            print(f"  [FAYL YO'Q] {y.mid}")
            continue
        matn = io.open(y.yol, encoding="utf-8", errors="replace").read()
        yar, oz_tash = kesh[y.mid]
        # PATCH O'ZI YARATIB, O'ZI TASHLAGAN obyekt kutilmaydi.
        # O'lchangan misol: `schema_patch_multitenant.sql`
        # `tai_add_company_id()` yordamchi funksiyasini yaratadi,
        # 6 ta jadvalga qo'llaydi va 371-satrda O'ZI tashlaydi. Uni
        # kutilgan deb sanash bootstrap'ni NOTO'G'RI "yetishmayapti"
        # deyishga majbur qilardi — bu haqiqatan sodir bo'ldi.
        kutilgan = (yar - oz_tash) - tashlar[i]
        yoq = sorted(o for o in kutilgan if o not in mavjud)
        if yoq:
            yetishmadi += 1
            muammo.append((y.mid, [f"{t} {n}" for t, n in yoq]))
            print(f"  [YETISHMAYDI] {y.mid:<34} {len(yoq)} obyekt")
            continue
        izoh = (f"bootstrap: {len(kutilgan)} obyekt bazada TEKSHIRILDI "
                f"(yurgizilmadi)" if kutilgan else
                "bootstrap: patch yangi obyekt yaratmaydi "
                "(faqat ALTER/INSERT) — obyekt tekshiruvi qo'llanmaydi")
        if quruq:
            print(f"  [yozilardi]   {y.mid:<34} {izoh}")
        else:
            j.bootstrap_yoz(y, checksum(y.yol), tranzaksionmi(matn), izoh)
            print(f"  [YOZILDI]     {y.mid:<34} {izoh}")
        yozildi += 1

    print(f"\nYozildi: {yozildi}   Allaqachon bor: {otdi}   "
          f"Yetishmaydi: {yetishmadi}")
    if muammo:
        print("\n!!! QUYIDAGI PATCHLAR RO'YXATGA OLINMADI — obyektlari yo'q.")
        print("    Ular HAQIQATAN qo'llanmagan bo'lishi mumkin. `--qolla` bilan")
        print("    yurgizing yoki sababini aniqlang. JIMGINA 'qo'llangan' deb")
        print("    yozilmaydi — dalilsiz yorliq qo'yilmaydi.\n")
        for mid, yoq in muammo:
            print(f"    {mid}")
            for o in yoq[:8]:
                print(f"        {o}")
            if len(yoq) > 8:
                print(f"        ... yana {len(yoq) - 8} ta")
        return 1
    return 0


def _jurnalni_taminla(yozuvlar: Sequence[Yozuv], j: Jurnal, psql: str,
                      env: Dict[str, str], quruq: bool) -> int:
    """Jurnal jadvali yo'q bo'lsa — uni quradi va o'zini ro'yxatga oladi.

    Busiz BO'SH BAZADA `--qolla` birinchi qadamda yiqilardi: jurnal
    qatori jurnal jadvali yaratilishidan OLDIN yozilmoqchi bo'lardi.
    Bu haqiqiy nuqson edi va bo'sh bazada qurish sinovi uni ochdi.
    """
    if j.jadval_bormi():
        return 0
    y = next((z for z in yozuvlar if z.fayl == JURNAL_PATCH), None)
    if y is None:
        print(f"!!! Manifestda `{JURNAL_PATCH}` YO'Q — jurnal qurib bo'lmaydi.")
        return 1
    print(f"  [{y.tartib:>4}] {y.mid:<34} jurnal jadvali quriladi")
    if quruq:
        print("        (quruq yurish — qurilmadi)")
        return 0
    t0 = time.time()
    kod, chiqish = psql_yurgiz(psql, env, y.yol, True, [])
    ms = int((time.time() - t0) * 1000)
    if kod != 0:
        print(f"        XATO (kod {kod})")
        print("        " + "\n        ".join(chiqish.splitlines()[-15:]))
        return 1
    j.ozini_yoz(y, checksum(y.yol), tranzaksionmi(
        io.open(y.yol, encoding="utf-8", errors="replace").read()), ms)
    print(f"        OK  {ms} ms")
    return 0


def buyruq_qolla(yozuvlar: Sequence[Yozuv], j: Jurnal, psql: str,
                 env: Dict[str, str], quruq: bool,
                 ozgaruvchilar: Sequence[str], toxta: bool) -> int:
    kod = _jurnalni_taminla(yozuvlar, j, psql, env, quruq)
    if kod != 0:
        return kod
    if quruq and not j.jadval_bormi():
        print("\n(jurnal jadvali hali yo'q — qolgan reja ko'rsatilmaydi)")
        return 0

    uz = j.uzilganlar() if j.jadval_bormi() else []
    if uz:
        print("!!! UZILGAN MIGRATSIYA BOR — YANGISI BOSHLANMAYDI.\n")
        for mid, fayl, tranz, vaqt in uz:
            print(f"    {mid}  ({fayl})  boshlangan: {vaqt}")
            if tranz:
                print("      Fayl O'Z tranzaksiyasida edi -> PostgreSQL DDL ni")
                print("      TO'LIQ qaytargan. Baza toza. Qatorni yoping va")
                print("      qayta yurgizing:")
            else:
                print("      Fayl TRANZAKSIYASIZ edi -> YARIM qo'llangan")
                print("      BO'LISHI MUMKIN. Avval baza holatini QO'LDA")
                print("      tekshiring, keyin:")
            print(f"      UPDATE schema_migration SET holat='xato', "
                  f"tugadi_at=now(),\n"
                  f"             xato='qo''lda yopildi: jarayon uzilgan'\n"
                  f"       WHERE migratsiya_id='{mid}' AND holat='boshlandi';\n")
        return 2

    qollangan = j.qollangan()
    yuriladi: List[Yozuv] = []
    farqlilar: List[str] = []
    for y in yozuvlar:
        if not os.path.exists(y.yol):
            print(f"!!! Manifestda bor, diskda YO'Q: {y.fayl}")
            return 1
        ck = checksum(y.yol)
        if y.mid in qollangan:
            if qollangan[y.mid][1] != ck:
                farqlilar.append(y.mid)
            continue
        yuriladi.append(y)

    if farqlilar:
        print("!!! CHECKSUM FARQI — QO'LLANGAN FAYL O'ZGARGAN.\n")
        for m in farqlilar:
            print(f"    {m}")
        print("\n    Bu shuni bildiradi: bazaga qo'llangan matn bilan")
        print("    repozitoriydagi matn BIR XIL EMAS. Sxema holati endi")
        print("    fayllardan qayta chiqarib bo'lmaydi.\n")
        print("    Agar o'zgarish sxemaga TEGMASA (izoh, bo'shliq), tasdiqlang:")
        print("        python migratsiya.py --checksum-yangila <migratsiya_id> \\")
        print('             --izoh "nima o`zgardi va nega xavfsiz"\n')
        print("    Agar sxemaga TEGSA — YANGI patch fayli yozing. Qo'llangan")
        print("    faylni tahrirlash tarixni yolg'onga aylantiradi.")
        return 2

    if not yuriladi:
        print("Hammasi qo'llangan — qiladigan ish yo'q.")
        return 0

    print(f"Yuriladi: {len(yuriladi)} ta migratsiya\n")
    var_kalitlar = {o.split("=", 1)[0] for o in ozgaruvchilar}
    for y in yuriladi:
        # MA'LUMOT SHARTI OLDINDAN tekshiriladi. Yiqilib, keyin xom
        # psql xatosini ko'rsatishdan ko'ra — umuman boshlamaslik afzal.
        shart = MALUMOTGA_BOGLIQ.get(y.fayl)
        if shart and not quruq and "tenant_id" not in var_kalitlar:
            sql, eng_kam, xabar = shart
            with j.conn.cursor() as cur:
                cur.execute(sql)
                bor = cur.fetchone()[0]
            if bor < eng_kam:
                print(f"  [{y.tartib:>4}] {y.mid:<34} TO'XTATILDI")
                print(f"        {xabar}")
                print("\n    Oldingi migratsiyalar QO'LLANGAN va jurnalda "
                      "yozilgan.\n    Shart bajarilgach `--qolla` shu yerdan "
                      "DAVOM ETADI.")
                return 2
        matn = io.open(y.yol, encoding="utf-8", errors="replace").read()
        oz = tranzaksionmi(matn)
        yaramas = tranzaksiyaga_yaramaydi(matn)
        rejim = ("o'z tranzaksiyasi" if oz else
                 "TRANZAKSIYASIZ (o'ralmaydi): " + ", ".join(yaramas) if yaramas
                 else "--single-transaction bilan o'raladi")
        print(f"  [{y.tartib:>4}] {y.mid:<34} {rejim}")
        if quruq:
            continue

        if yaramas and not oz:
            # Tranzaksiyaga yaramaydigan buyruq bor va fayl o'zi ham
            # o'ralmagan -> ATOMAR EMAS. Buni AYTAMIZ, yashirmaymiz.
            print("        DIQQAT: bu fayl ATOMAR EMAS. Uzilsa yarim "
                  "qo'llangan qolishi mumkin.")

        sid = j.boshla(y, checksum(y.yol), oz)
        t0 = time.time()
        kod, chiqish = psql_yurgiz(psql, env, y.yol, oz or bool(yaramas),
                                   ozgaruvchilar)
        ms = int((time.time() - t0) * 1000)
        if kod == 0:
            j.tugat(sid, "ok", ms, kod, None)
            print(f"        OK  {ms} ms")
        else:
            j.tugat(sid, "xato", ms, kod, chiqish[-4000:] or f"psql kodi {kod}")
            print(f"        XATO (kod {kod}, {ms} ms)")
            print("        " + "\n        ".join(chiqish.splitlines()[-15:]))
            if toxta:
                print("\nTO'XTATILDI. Keyingi migratsiyalar YURGIZILMADI —")
                print("bog'liqlik tartibi buzilmasin.")
                return 1
    if quruq:
        print("\n(quruq yurish — hech narsa o'zgartirilmadi)")
    return 0


def buyruq_checksum_yangila(yozuvlar: Sequence[Yozuv], j: Jurnal,
                            mid: str, izoh: str) -> int:
    y = next((z for z in yozuvlar if z.mid == mid), None)
    if y is None:
        print(f"Manifestda bunday migratsiya YO'Q: {mid}")
        return 1
    if not izoh.strip():
        print("--izoh MAJBURIY: nima o'zgardi va nega xavfsiz ekani "
              "yozilmasa, qayta muhrlash dalilsiz bo'lardi.")
        return 1
    q = j.qollangan()
    if mid not in q:
        print(f"{mid} jurnalda 'ok'/'bootstrap' emas — qayta muhrlash "
              f"qiladigan narsa yo'q.")
        return 1
    yangi = checksum(y.yol)
    if q[mid][1] == yangi:
        print(f"{mid}: checksum ALLAQACHON mos — o'zgartirish shart emas.")
        return 0
    j.checksum_yangila(y, yangi, f"qayta muhrlandi: {izoh.strip()}")
    print(f"{mid}: qayta muhrlandi.\n"
          f"  eski: {q[mid][1]}\n  yangi: {yangi}\n"
          f"  Eski qator O'CHIRILMADI — 'otkazildi' ga o'tkazildi (audit izi).")
    return 0


# =====================================================================
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sxema migratsiyalarini kuzatuvchi yurgizuvchi")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--holat", action="store_true", help="Nima qo'llangan")
    g.add_argument("--reja", action="store_true", help="Nima yuriladi (quruq)")
    g.add_argument("--qolla", action="store_true", help="Qo'llash")
    g.add_argument("--bootstrap", action="store_true",
                   help="Mavjud bazani ro'yxatga olish (yurgizmasdan)")
    g.add_argument("--tekshir", action="store_true", help="Butunlik tekshiruvi")
    g.add_argument("--manifest-yasa", action="store_true",
                   help="Tartibni bog'liqliklardan qayta chiqarish")
    g.add_argument("--checksum-yangila", metavar="MIGRATSIYA_ID",
                   help="Qo'llangan faylning yangi checksumini muhrlash")
    ap.add_argument("--izoh", default="", help="--checksum-yangila uchun sabab")
    ap.add_argument("--dsn", default="", help="XT_DB_DSN o'rniga")
    ap.add_argument("--var", action="append", default=[],
                    help="psql o'zgaruvchisi, masalan --var tenant_id=2")
    ap.add_argument("--quruq", action="store_true",
                    help="--bootstrap bilan: yozmasdan ko'rsatadi")
    ap.add_argument("--davom", action="store_true",
                    help="Xatodan keyin ham davom etish (STANDART: to'xtaydi)")
    args = ap.parse_args()

    if args.manifest_yasa:
        y = manifest_yasa()
        manifest_yoz(y)
        print(f"{MANIFEST} yozildi — {len(y)} ta migratsiya")
        for z in y:
            print(f"  {z.tartib:>4}  {z.mid}")
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except Exception:                                         # pragma: no cover
        pass

    dsn = args.dsn or _dsn()
    yozuvlar = manifest_oqi()
    psql = psql_top()
    env = psql_muhit(dsn)

    j = Jurnal(dsn)
    try:
        # QULF. Ikkita yurgizuvchi bir vaqtda ketmasin. Bu BIRINCHI
        # to'siq; ikkinchisi — `schema_migration_bitta_ochiq` indeksi,
        # chunki qulf ulanish uzilsa BO'SHAYDI, indeks bo'shamaydi.
        if not args.holat and not args.tekshir:
            if not j.qulfla():
                print("Boshqa migratsiya yurgizuvchisi ISHLAB TURIBDI "
                      "(maslahat qulfi band). To'xtatildi.")
                sys.exit(2)
        if args.holat:
            sys.exit(buyruq_holat(yozuvlar, j))
        if args.tekshir:
            sys.exit(buyruq_tekshir(yozuvlar, j))
        if args.bootstrap:
            sys.exit(buyruq_bootstrap(yozuvlar, j, psql, env, quruq=args.quruq))
        if args.checksum_yangila:
            sys.exit(buyruq_checksum_yangila(yozuvlar, j,
                                             args.checksum_yangila, args.izoh))
        sys.exit(buyruq_qolla(yozuvlar, j, psql, env, quruq=args.reja,
                              ozgaruvchilar=args.var, toxta=not args.davom))
    finally:
        j.qulfni_bosh()
        j.close()


if __name__ == "__main__":
    main()
