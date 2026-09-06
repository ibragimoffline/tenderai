#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: MIGRATSIYA VERSIYALASH
==============================

To'rtta stsenariy o'lchanadi (foydalanuvchi talabi bo'yicha):

  1. BO'SH BAZA -> JORIY SXEMA. Manifest tartibi HAQIQATAN ishlaydimi.
     Bu yagona haqiqiy isbot: tartib bog'liqliklardan CHIQARILGAN,
     ya'ni u faqat qurib ko'rilgandagina tasdiqlanadi.

  2. MAVJUD BAZA -> QAYTA QO'LLASH YO'Q. Bootstrap qilingan bazada
     `--qolla` HECH NARSA qilmasligi va HECH BIR qator o'zgarmasligi
     kerak.

  3. UZILGAN MIGRATSIYA. Jarayon o'ldirilganda qoladigan holat
     keyingi yurishni TO'XTATADIMI.

  4. CHECKSUM O'ZGARISHI. Qo'llangan fayl tahrirlansa yurgizuvchi
     to'xtaydimi.

XAVFSIZLIK. Sinov O'Z bazasini yaratadi (`SINOV_BAZA`) va oxirida
tashlaydi. Ishlab chiqarish bazasiga HECH QACHON yozmaydi — nom
tekshiruvi bor va u bajarilmasa sinov yiqiladi, jimgina o'tmaydi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\migratsiya_test.py
    .venv\\Scripts\\python.exe _tests\\migratsiya_test.py --offline
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import migratsiya as M  # noqa: E402

try:
    import psycopg2
except ImportError:                                           # pragma: no cover
    psycopg2 = None

#: Sinov bazasi. Nomi ATAYLAB o'ziga xos — ishlab chiqarish bazasi
#: bilan adashib ketmasin.
SINOV_BAZA = "xt_migratsiya_sinov"

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
# STATIK — bazasiz
# =====================================================================
def test_manifest():
    bolim("Manifest — shakli va to'liqligi")
    y = M.manifest_oqi()
    check("manifest o'qildi", len(y) > 0, f"{len(y)} ta migratsiya")
    check("jurnal patchi BIRINCHI", y[0].fayl == M.JURNAL_PATCH, y[0].fayl)

    tartiblar = [z.tartib for z in y]
    check("tartib QAT'IY o'suvchi",
          all(b > a for a, b in zip(tartiblar, tartiblar[1:])))
    check("migratsiya_id lar TAKRORSIZ",
          len({z.mid for z in y}) == len(y))
    check("fayllar TAKRORSIZ", len({z.fayl for z in y}) == len(y))

    yoq = [z.fayl for z in y if not os.path.exists(z.yol)]
    check("manifestdagi HAR fayl diskda BOR", not yoq, str(yoq[:3]))

    import glob
    diskda = {os.path.basename(p) for p in
              glob.glob(os.path.join(ROOT, "schema_patch_*.sql"))}
    diskda.add("xt_xarid_schema.sql")
    yetim = sorted(diskda - {z.fayl for z in y})
    # DISKDA BOR, MANIFESTDA YO'Q — bu jimgina qo'llanmay qoladigan
    # patch degani. Aynan shu nuqson uchun tekshiriladi.
    check("diskdagi HAR patch manifestda BOR", not yetim, str(yetim))


def test_manifest_yasa_barqaror():
    """`--manifest-yasa` MAVJUD `migratsiya_id` larni SILJITMAYDI.

    O'LCHANGAN NUQSON (2026-09-06). `manifest_yasa()` id ni
    POZITSIYADAN chiqarardi (`f"{i:04d}_{nom}"`). Ya'ni o'rtaga
    bitta yangi patch tushsa undan keyingi HAMMA id bir pog'ona
    siljirdi — manifest sarlavhasi id ni BARQAROR deb e'lon
    qilgan bo'lsa ham.

    NARXI: jurnal (`schema_migration`) `migratsiya_id` bo'yicha
    kalitlanadi. Id siljigach yurgizuvchi ALLAQACHON QO'LLANGAN
    migratsiyani "qo'llanmagan" deb ko'rib QAYTA YURGIZARDI.
    Ishlab chiqarishda bu ma'lumot yo'qotishi bilan tugaydi.

    Nuqson `main` birlashmasida ANIQ ZARAR keltirishi mumkin edi:
    `0069_huquq_2` va `0070_dim_area_seed` ishlab chiqarishda
    qo'llangan, birlashmada esa ularning oldiga yangi fayllar
    tushardi.

    Bu sinov IKKI narsani o'lchaydi:
      1. hozirgi manifest uchun regeneratsiya HECH NIMANI
         o'zgartirmaydi;
      2. SUN'IY holatda — o'rtaga yangi patch qo'shilganda —
         eskilarning id si baribir joyida qoladi.
    Ikkinchisi asosiy: birinchisi tasodifan ham o'tishi mumkin.
    """
    bolim("Manifest — `--manifest-yasa` id ni SILJITMAYDI")

    # DIQQAT — QUYIDAGI IKKI SHART NIMANI O'LCHAMAYDI.
    #
    # "Haqiqiy manifest uchun regeneratsiya id larni o'zgartirmadi"
    # degan shart YOZILGAN edi va u YIQILA OLMASDI: `manifest_yasa()`
    # id ni aynan `manifest_oqi()` dan oladi, ya'ni shart
    # `manifest_oqi()` ni O'ZI bilan solishtirardi (1-sinf: asbob
    # o'zini o'lchaydi). Yashil chiqishi kafolatlangan va shuning
    # uchun u YOLG'ON ISHONCH berardi.
    #
    # Olib tashlandi. O'rniga YIQILA OLADIGAN shart: regeneratsiya
    # birorta id ni YANGIDAN yasamasin. Diskda manifestda yo'q patch
    # paydo bo'lsa u yangi id oladi -- va bu jimgina qo'llanmaydigan
    # migratsiya belgisi.
    #
    # ASOSIY QO'RIQCHI QUYIDA, sun'iy holatda: faqat o'sha yerda
    # manifest va regeneratsiya MUSTAQIL ravishda qurilib
    # solishtiriladi.
    hozir = {z.fayl: z.mid for z in M.manifest_oqi()}
    qayta = {z.fayl: z.mid for z in M.manifest_yasa()}
    yangi_id = {f: qayta[f] for f in qayta if f not in hozir}
    check("regeneratsiya YANGI id yasamaydi (hammasi manifestdan)",
          not yangi_id,
          "; ".join(f"{f}={i}" for f, i in list(yangi_id.items())[:3]))
    check("regeneratsiya fayl YO'QOTMAYDI",
          not (set(hozir) - set(qayta)),
          str(sorted(set(hozir) - set(qayta))[:3]))

    # --- SUN'IY HOLAT: o'rtaga YANGI patch tushadi ---
    #
    # HAQIQIY manifestga tegilmaydi. `ROOT` va `MANIFEST` vaqtinchalik
    # katalogga ko'chiriladi, oxirida QAYTARILADI. Aks holda sinov
    # o'zi qo'riqlayotgan faylni buzardi.
    import shutil
    import tempfile
    e_root, e_manifest = M.ROOT, M.MANIFEST
    vaqt = tempfile.mkdtemp(prefix="manifest_yasa_")
    try:
        # Ikkita mustaqil patch: `a` jadval yaratadi, `b` unga tegadi.
        # Bog'liqlik SHU orqali chiqadi, ya'ni tartib aniq.
        io.open(os.path.join(vaqt, "xt_xarid_schema.sql"), "w",
                encoding="utf-8").write("CREATE TABLE t_bir (id int);")
        io.open(os.path.join(vaqt, M.JURNAL_PATCH), "w",
                encoding="utf-8").write(
                    "CREATE TABLE schema_migration (id int);")
        io.open(os.path.join(vaqt, "schema_patch_aaa.sql"), "w",
                encoding="utf-8").write("CREATE TABLE t_aaa (id int);")
        io.open(os.path.join(vaqt, "schema_patch_zzz.sql"), "w",
                encoding="utf-8").write(
                    "ALTER TABLE t_aaa ADD COLUMN x int;")

        M.ROOT = vaqt
        M.MANIFEST = os.path.join(vaqt, "migratsiya_manifest.tsv")
        birinchi = M.manifest_yasa()
        M.manifest_yoz(birinchi)
        oldin = {z.fayl: z.mid for z in birinchi}

        # ENDI O'RTAGA yangi patch qo'shiladi: u `t_aaa` ga tegadi,
        # ya'ni `aaa` dan KEYIN, lekin nomi bo'yicha `zzz` dan OLDIN
        # turadi — pozitsiyaga tayangan id aynan shunda siljirdi.
        io.open(os.path.join(vaqt, "schema_patch_mmm.sql"), "w",
                encoding="utf-8").write(
                    "ALTER TABLE t_aaa ADD COLUMN y int;")
        keyin = {z.fayl: z.mid for z in M.manifest_yasa()}

        siljigan = {f: (oldin[f], keyin[f])
                    for f in oldin if oldin[f] != keyin.get(f)}
        check("yangi patch ESKI id larni siljitmaydi",
              not siljigan,
              "; ".join(f"{f}: {a}->{b}" for f, (a, b) in
                        list(siljigan.items())[:3]))
        yangi_id = keyin.get("schema_patch_mmm.sql")
        check("yangi patch YANGI id oladi",
              bool(yangi_id) and yangi_id not in oldin.values(),
              str(yangi_id))
        check("yangi id band raqamdan KEYIN keladi",
              bool(yangi_id) and yangi_id.startswith("0005_"),
              f"{yangi_id} (oldingilar: {sorted(oldin.values())})")
        check("id lar TAKRORSIZ qoladi",
              len(set(keyin.values())) == len(keyin), str(len(keyin)))
    finally:
        M.ROOT, M.MANIFEST = e_root, e_manifest
        shutil.rmtree(vaqt, ignore_errors=True)


def test_checksum():
    bolim("Checksum — barqaror va sezgir")
    y = M.manifest_oqi()[1]
    a = M.checksum(y.yol)
    check("64 ta hex belgi", len(a) == 64 and all(c in "0123456789abcdef" for c in a))
    check("takroriy hisob BIR XIL", M.checksum(y.yol) == a)

    # Qator oxiri normallashtiriladi: CRLF/LF farqi checksumni
    # o'zgartirmasligi kerak, aks holda Windows va Linux'da bir xil
    # fayl IKKI XIL checksum berardi va yurgizuvchi doim to'xtardi.
    matn = io.open(y.yol, encoding="utf-8").read()
    check("CRLF va LF BIR XIL checksum beradi",
          M.normalla(matn.replace("\n", "\r\n")) == M.normalla(matn))
    check("oxirgi bo'sh qatorlar ta'sir qilmaydi",
          M.normalla(matn + "\n\n\n") == M.normalla(matn))

    # MAZMUN o'zgarsa checksum O'ZGARISHI SHART.
    ozgargan = matn + "\nSELECT 1;\n"
    check("mazmun o'zgarsa checksum O'ZGARADI",
          M.normalla(ozgargan) != M.normalla(matn))
    # IZOH ham mazmun deb hisoblanadi — bu ATAYLAB (docstring'da
    # sababi yozilgan).
    check("izoh o'zgarsa ham checksum O'ZGARADI",
          M.normalla("-- yangi izoh\n" + matn) != M.normalla(matn))


def test_xossalar():
    bolim("Fayl xossalari — tranzaksionlik va obyektlar")
    tranz = notranz = 0
    for z in M.manifest_oqi():
        matn = io.open(z.yol, encoding="utf-8", errors="replace").read()
        if M.tranzaksionmi(matn):
            tranz += 1
        else:
            notranz += 1
    check("tranzaksion fayllar ANIQLANDI", tranz > 0, f"{tranz} ta")
    check("tranzaksiyasiz fayllar ham BOR", notranz > 0,
          f"{notranz} ta — ular `--single-transaction` bilan o'raladi")

    # HAR fayl yo o'z tranzaksiyasida, yo o'ralishi mumkin bo'lishi
    # SHART. Uchinchi holat — o'z tranzaksiyasi ICHIDA tranzaksiyaga
    # yaramaydigan buyruq — psql xatosi beradi.
    yomon = []
    for z in M.manifest_oqi():
        matn = io.open(z.yol, encoding="utf-8", errors="replace").read()
        if M.tranzaksionmi(matn) and M.tranzaksiyaga_yaramaydi(matn):
            yomon.append(z.fayl)
    check("o'z tranzaksiyasi ichida yaramas buyruq YO'Q", not yomon, str(yomon))

    # Obyekt chiqarish sxema prefiksini tushirishi kerak.
    yar, _t = M.obyektlar("CREATE TABLE IF NOT EXISTS public.foo (id INT);")
    check("sxema prefiksi tushiriladi", ("table", "foo") in yar, str(yar))
    _y, tash = M.obyektlar("DROP FUNCTION IF EXISTS bar(TEXT, BOOLEAN);")
    check("argumentli DROP FUNCTION aniqlanadi", ("func", "bar") in tash, str(tash))


def test_jurnal_mexanizmi():
    bolim("Jurnal mexanizmi — uzilishdan omon qolish sharti")
    manba = io.open(os.path.join(ROOT, "migratsiya.py"), encoding="utf-8").read()
    # UZILGAN MIGRATSIYA KO'RINISHINING YAGONA SABABI: jurnal
    # ALOHIDA ulanishda va `autocommit` bilan yoziladi. Bu shart
    # buzilsa "boshlandi" qatori migratsiya bilan birga qaytarilardi
    # va uzilish IZSIZ yo'qolardi.
    check("jurnal ulanishi autocommit", "self.conn.autocommit = True" in manba)
    check("`boshlandi` yurgizishdan OLDIN yoziladi",
          manba.index("sid = j.boshla(") < manba.index("kod, chiqish = psql_yurgiz(psql, env, y.yol, oz"))
    check("maslahat qulfi ishlatiladi", "pg_try_advisory_lock" in manba)


def test_patch_qulflari():
    bolim("Jurnal patchi — qoidalar CHECK da, izohda emas")
    sql = io.open(os.path.join(ROOT, M.JURNAL_PATCH), encoding="utf-8").read()
    kerak = [
        ("qisman unikal indeks (qayta qo'llash to'sig'i)",
         "schema_migration_bir_marta"),
        ("bir vaqtda bitta ochiq yurish", "schema_migration_bitta_ochiq"),
        ("holat lug'ati CHECK", "schema_migration_holat_chk"),
        ("tugash vaqti CHECK", "schema_migration_tugadi_chk"),
        ("xato DALIL talab qiladi", "schema_migration_xato_dalil_chk"),
        ("bootstrap IZOH talab qiladi", "schema_migration_izoh_chk"),
        ("checksum shakli CHECK", "schema_migration_checksum_chk"),
        ("uzilganlar ko'rinishi", "v_migratsiya_uzilgan"),
    ]
    for nom, naqsh in kerak:
        check(nom, naqsh in sql)


# =====================================================================
# BAZALI STSENARIYLAR
# =====================================================================
def _dsn_qism():
    dsn = os.environ.get("XT_DB_DSN", "")
    return M.dsn_qismlari(dsn) if dsn else {}


def _sinov_dsn():
    q = dict(_dsn_qism())
    q["dbname"] = SINOV_BAZA
    return " ".join(f"{k}={v}" for k, v in q.items())


def _admin_kon():
    q = dict(_dsn_qism())
    q["dbname"] = "postgres"
    c = psycopg2.connect(" ".join(f"{k}={v}" for k, v in q.items()),
                         connect_timeout=8)
    c.autocommit = True
    return c


def _baza_amal(sqllar):
    """`CREATE`/`DROP DATABASE` ni yurgizadi.

    `with conn:` ATAYLAB ISHLATILMAYDI: psycopg2 da u tranzaksiya
    bloki ochadi va PostgreSQL `DROP DATABASE` ni tranzaksiya ichida
    RAD ETADI ("не может выполняться внутри блока транзакции").
    Ulanish qo'lda ochilib yopiladi.
    """
    c = _admin_kon()
    try:
        cur = c.cursor()
        for sql in sqllar:
            cur.execute(sql)
        cur.close()
    finally:
        c.close()


def _baza_qayta_yarat():
    _baza_amal([
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname='{SINOV_BAZA}' AND pid<>pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{SINOV_BAZA}"',
        f'CREATE DATABASE "{SINOV_BAZA}"',
    ])


def _baza_tashla():
    try:
        _baza_amal([
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{SINOV_BAZA}' AND pid<>pg_backend_pid()",
            f'DROP DATABASE IF EXISTS "{SINOV_BAZA}"',
        ])
    except Exception as e:                                    # noqa: BLE001
        print(f"  [i] sinov bazasini tashlab bo'lmadi: {str(e)[:70]}")


def _yurgiz(*args, dsn=None):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "migratsiya.py"),
                        *args, "--dsn", dsn or _sinov_dsn()],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="backslashreplace", cwd=ROOT, timeout=1800)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _sinov_kon():
    c = psycopg2.connect(_sinov_dsn(), connect_timeout=8)
    c.autocommit = True
    return c


def _obyektlar(c):
    s = set()
    with c.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE'")
        s |= {("table", r[0]) for r in cur.fetchall()}
        cur.execute("SELECT table_name FROM information_schema.views "
                    "WHERE table_schema='public'")
        s |= {("view", r[0]) for r in cur.fetchall()}
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema='public'")
        s |= {("ustun", f"{r[0]}.{r[1]}") for r in cur.fetchall()}
    return s


def test_xavfsizlik():
    bolim("Xavfsizlik — ishlab chiqarish bazasiga TEGILMAYDI")
    q = _dsn_qism()
    check("XT_DB_DSN o'qildi", bool(q.get("dbname")), str(q.get("dbname")))
    # BU TEKSHIRUV JIMGINA O'TKAZIB YUBORILMAYDI. Sinov bazasi nomi
    # ishlab chiqarishnikiga teng bo'lsa — sinov o'z bazasini
    # tashlaganda ishlab chiqarish YO'QOLARDI.
    check("sinov bazasi ishlab chiqarishdan FARQ QILADI",
          q.get("dbname") != SINOV_BAZA,
          f"ishlab chiqarish={q.get('dbname')} sinov={SINOV_BAZA}")


def test_1_bosh_bazadan_qurish():
    bolim("1) BO'SH BAZA -> JORIY SXEMA")
    _baza_qayta_yarat()

    kod, chiqish = _yurgiz("--qolla")
    # `multitenant` ma'lumot talab qiladi va u yerda TO'XTAYDI (kod 2).
    # Bu KUTILGAN xulq va u yerda urug' hisob yaratiladi.
    check("birinchi bosqich ma'lumot shartida TO'XTADI", kod == 2,
          f"chiqish kodi {kod}")
    check("to'xtash SABABI tushuntirildi",
          "company_account" in chiqish and "tenant_id" in chiqish)
    check("to'xtaganda YARIM qo'llangan holat yaratilmadi",
          "TO'XTATILDI" in chiqish and "XATO (kod" not in chiqish.split("TO'XTATILDI")[-1])

    c = _sinov_kon()
    with c.cursor() as cur:
        cur.execute("INSERT INTO company_account(username,company_name,"
                    "password_hash,active) VALUES('sinov_uruq','Sinov uruq',"
                    "'!yaroqsiz',true) ON CONFLICT (username) DO NOTHING")
    kod, chiqish = _yurgiz("--qolla")
    check("urug'dan keyin qurish TUGADI", kod == 0, f"chiqish kodi {kod}")

    kod, chiqish = _yurgiz("--holat")
    check("hamma migratsiya qo'llangan", "Qo'llanmagan: 0" in chiqish,
          [q for q in chiqish.splitlines() if "Qo'llanmagan" in q][:1])
    check("checksum farqi YO'Q", "Checksum FARQI: 0" in chiqish)

    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migration "
                    "WHERE holat IN ('ok','bootstrap')")
        n = cur.fetchone()[0]
    check("jurnalda HAR migratsiya yozilgan", n == len(M.manifest_oqi()),
          f"{n} / {len(M.manifest_oqi())}")

    # ISHLAB CHIQARISH BILAN SOLISHTIRISH — asosiy isbot.
    try:
        p = psycopg2.connect(os.environ["XT_DB_DSN"], connect_timeout=8)
        p.autocommit = True
        prod, qurilgan = _obyektlar(p), _obyektlar(c)
        p.close()
        yoq = sorted(prod - qurilgan)
        check("ishlab chiqarishdagi HAR obyekt qurilgan bazada BOR",
              not yoq, f"{len(yoq)} ta yetishmaydi: {yoq[:5]}")
        # Ortiqchalar KUTILGAN va ular NOMMA-NOM tekshiriladi —
        # "ortiqcha bo'lsa mayli" deb o'tkazib yuborilmaydi.
        ortiq = {n for _t, n in (qurilgan - prod)}
        kutilgan_ortiq = {"schema_migration", "v_migratsiya_holat",
                          "v_migratsiya_uzilgan", "app_user", "app_session"}
        begona = sorted(n for n in ortiq
                        if n.split(".")[0] not in kutilgan_ortiq)
        check("kutilmagan ORTIQCHA obyekt yo'q", not begona,
              f"{begona[:5]}")
    except Exception as e:                                    # noqa: BLE001
        check("ishlab chiqarish bilan solishtirish", False, str(e)[:80])
    c.close()


def test_2_qayta_qollash_yoq():
    bolim("2) MAVJUD BAZA -> QAYTA QO'LLASH YO'Q")
    c = _sinov_kon()
    with c.cursor() as cur:
        cur.execute("INSERT INTO company_account(id,username,company_name,"
                    "password_hash,active) VALUES(9901,'nazorat','Nazorat',"
                    "'!h',true) ON CONFLICT (id) DO NOTHING")

    def surat():
        s = {}
        with c.cursor() as cur2:
            cur2.execute("SELECT table_name FROM information_schema.tables "
                         "WHERE table_schema='public' AND table_type='BASE TABLE'")
            for (t,) in cur2.fetchall():
                cur2.execute(f'SELECT count(*) FROM public."{t}"')
                s[t] = cur2.fetchone()[0]
        return s

    oldin = surat()
    kod, chiqish = _yurgiz("--qolla")
    check("qayta yurgizish 0 bilan tugadi", kod == 0, f"kod {kod}")
    check("HECH NARSA qilinmadi", "qiladigan ish yo" in chiqish,
          chiqish.strip().splitlines()[-1][:60] if chiqish.strip() else "")
    keyin = surat()
    farq = {k: (oldin[k], keyin.get(k)) for k in oldin if oldin[k] != keyin.get(k)}
    check(f"{len(oldin)} jadvalning HAMMASIDA qator soni o'zgarmadi",
          not farq, str(list(farq.items())[:3]))
    c.close()


def test_3_uzilgan_migratsiya():
    bolim("3) UZILGAN MIGRATSIYA")
    c = _sinov_kon()
    # O'LDIRILGAN JARAYON AYNAN SHU IZNI QOLDIRADI: `boshlandi`
    # qatori ochiq. Bu yerda o'sha holat ATAYLAB yaratiladi va
    # keyingi yurish uni ko'rib to'xtashi tekshiriladi.
    # (Haqiqiy o'ldirish vaqtga bog'liq bo'lardi; jurnal
    # mexanizmining o'zi `test_jurnal_mexanizmi` da tekshiriladi.)
    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migration WHERE holat='boshlandi'")
        check("boshida ochiq yurish YO'Q", cur.fetchone()[0] == 0)
        cur.execute("INSERT INTO schema_migration(migratsiya_id,fayl,tartib,"
                    "checksum,holat,tranzaksion,yurgizuvchi) VALUES"
                    "('9999_sinov','sinov.sql',99990,%s,'boshlandi',true,'sinov')",
                    ("a" * 64,))

    kod, chiqish = _yurgiz("--qolla")
    check("uzilgan holat KO'RINDI", "UZILGAN" in chiqish, chiqish[:70])
    check("yangi migratsiya BOSHLANMADI", kod == 2, f"kod {kod}")
    check("tranzaksionlik holatiga qarab MASLAHAT berildi",
          "qaytargan" in chiqish or "qaytarilgan" in chiqish)

    # Tranzaksiyasiz fayl uchun MASLAHAT BOSHQACHA bo'lishi kerak —
    # u yerda yarim qo'llanish MUMKIN va odam ko'rishi shart.
    with c.cursor() as cur:
        cur.execute("UPDATE schema_migration SET tranzaksion=false "
                    "WHERE migratsiya_id='9999_sinov'")
    _kod, chiqish2 = _yurgiz("--qolla")
    check("tranzaksiyasiz uchun OGOHLANTIRISH boshqacha",
          "YARIM" in chiqish2, chiqish2[:70])

    # v_migratsiya_uzilgan ko'rinishi ham buni ko'rsatishi kerak.
    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM v_migratsiya_uzilgan")
        check("v_migratsiya_uzilgan uni ko'rsatadi", cur.fetchone()[0] == 1)
        # Tozalash: hujjatda yozilgan yo'l bilan yopiladi.
        cur.execute("UPDATE schema_migration SET holat='xato', tugadi_at=now(), "
                    "xato='sinov: qo''lda yopildi' WHERE migratsiya_id='9999_sinov'")
        cur.execute("SELECT count(*) FROM v_migratsiya_uzilgan")
        check("qo'lda yopilgach ro'yxat bo'shadi", cur.fetchone()[0] == 0)

    kod, _c = _yurgiz("--qolla")
    check("yopilgach yurgizuvchi yana ishlaydi", kod == 0, f"kod {kod}")
    c.close()


def test_4_checksum_ozgarishi():
    bolim("4) CHECKSUM O'ZGARISHI")
    c = _sinov_kon()
    y = M.manifest_oqi()[3]
    with c.cursor() as cur:
        cur.execute("SELECT checksum FROM schema_migration WHERE migratsiya_id=%s "
                    "AND holat IN ('ok','bootstrap')", (y.mid,))
        asl = cur.fetchone()[0]
    check("jurnalda checksum bor", len(asl) == 64)

    # Faylni o'zgartirmasdan, JURNALDAGI checksumni buzamiz —
    # ta'siri bir xil: fayl bilan jurnal MOS EMAS.
    with c.cursor() as cur:
        cur.execute("UPDATE schema_migration SET checksum=%s WHERE migratsiya_id=%s "
                    "AND holat IN ('ok','bootstrap')", ("b" * 64, y.mid))

    kod, chiqish = _yurgiz("--qolla")
    check("farq ANIQLANDI", "CHECKSUM FARQI" in chiqish, chiqish[:70])
    check("yurgizuvchi TO'XTADI", kod == 2, f"kod {kod}")
    check("farq qilgan migratsiya NOMI aytildi", y.mid in chiqish)
    check("nima qilish YOZILDI", "--checksum-yangila" in chiqish)

    kod, chiqish = _yurgiz("--tekshir")
    check("--tekshir ham farqni ko'radi", kod != 0 and "FARQ" in chiqish)

    # IZOHSIZ qayta muhrlash RAD ETILISHI kerak — dalilsiz o'zgarish
    # jimgina o'tmasin.
    kod, chiqish = _yurgiz("--checksum-yangila", y.mid)
    check("izohsiz qayta muhrlash RAD ETILDI", kod != 0, f"kod {kod}")

    kod, chiqish = _yurgiz("--checksum-yangila", y.mid,
                           "--izoh", "sinov: faqat jurnal buzilgan edi")
    check("izoh bilan qayta muhrlandi", kod == 0, chiqish[:70])

    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migration WHERE migratsiya_id=%s",
                    (y.mid,))
        n = cur.fetchone()[0]
        # ESKI QATOR O'CHIRILMAYDI — u nima qo'llangani haqidagi dalil.
        check("eski qator SAQLANDI (audit izi)", n >= 2, f"{n} ta qator")
        cur.execute("SELECT holat FROM schema_migration WHERE migratsiya_id=%s "
                    "ORDER BY id", (y.mid,))
        holatlar = [r[0] for r in cur.fetchall()]
        check("eski qator 'otkazildi' ga o'tdi", "otkazildi" in holatlar,
              str(holatlar))

    kod, chiqish = _yurgiz("--qolla")
    check("qayta muhrlangach yurgizuvchi yana ishlaydi", kod == 0,
          f"kod {kod}")
    c.close()


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Migratsiya versiyalash sinovi")
    rejim.bayroqlar(ap)
    ap.add_argument("--saqla", action="store_true",
                    help="Sinov bazasini tashlamaydi (nosozlik izlash)")
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: MIGRATSIYA VERSIYALASH")
    print("=" * 70)

    test_manifest()
    test_manifest_yasa_barqaror()
    test_checksum()
    test_xossalar()
    test_jurnal_mexanizmi()
    test_patch_qulflari()

    bazali = (not args.bazasiz) and psycopg2 is not None \
        and bool(os.environ.get("XT_DB_DSN"))
    if not bazali:
        sabab = ("--offline berildi" if args.bazasiz else
                 "psycopg2 yo'q" if psycopg2 is None else "XT_DB_DSN yo'q")
        print(f"\n[i] Bazali stsenariylar O'TKAZIB YUBORILDI ({sabab}). "
              f"Ular ~40 s oladi va o'z bazasini yaratadi.")
    else:
        test_xavfsizlik()
        # Xavfsizlik tekshiruvi yiqilsa BAZAGA UMUMAN TEGILMAYDI.
        if all(ok for nom, ok, _d in _natija if "sinov bazasi" in nom):
            try:
                test_1_bosh_bazadan_qurish()
                test_2_qayta_qollash_yoq()
                test_3_uzilgan_migratsiya()
                test_4_checksum_ozgarishi()
            finally:
                if args.saqla:
                    print(f"\n[i] Sinov bazasi SAQLANDI: {SINOV_BAZA}")
                else:
                    _baza_tashla()
        else:
            check("xavfsizlik tekshiruvi o'tmadi — bazaga tegilmadi", False)

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
