#!/usr/bin/env python3
"""
SINOV: ETL QAMROVI (P0-1 — "1-2 platformani soatiga bir marta kuzatish")
========================================================================
Nima tekshiriladi:
  1. dim_status  — ref_selection_public keltirgan IKKI yangi status lug'atda
                   bormi va nomi bo'sh emasmi (bo'lmasa frontend status
                   filtrida BO'SH nom chiqadi)
  2. status yetimlari — bazadagi har bir tender.status dim_status'da bormi
  3. qamrov      — xt-xarid'da type='selection' va uzex'da type='selection'
                   yozuvlar bazaga tushdimi (ikkinchi reyestrlar ishlayaptimi)
  4. type        — uzex TypeId=1 yozuvlari 'tender' emas, 'selection' bo'ldimi
  5. ID to'qnashuvi — manba darajasida ikki reyestr ID fazolari kesishmaydimi
                   (kesishsa bir yozuv ikkinchisini UPSERT bilan bosib ketardi)
  6. run_etl.py  — XT_DB_DSN muhitda BO'LMAGANDA ham .env dan o'qib ishga
                   tushadimi va bola-jarayon chiqishi YO'QOLMAYDIMI
                   (cp1251 -> UnicodeDecodeError regressiyasi)

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\etl_coverage_test.py
    .venv\\Scripts\\python.exe _tests\\etl_coverage_test.py --offline   # tarmoqsiz
    .venv\\Scripts\\python.exe _tests\\etl_coverage_test.py --skip-orchestrator

DIQQAT: sinov manba API'lariga so'rov yuboradi, lekin REQUEST_DELAY
o'zgartirilmaydi va orkestrator FAQAT --limit 1 bilan yurgiziladi
(to'liq yurish uzex TypeId=1 uchun ~10 daqiqa oladi).
"""
import argparse
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# KONSOL KODLASHI — Windows kod sahifasidan MUSTAQIL UTF-8.
#
# Chiqish QUVUR yoki FAYLGA yo'naltirilganda (ya'ni CI da) Python
# `locale.getpreferredencoding()` ni oladi — bu mashinada `cp1251`.
# O'zbek kirill (`ҳ`, `қ`, `ў`) va to'liq kenglikdagi belgilar
# (`）`) u yerda YO'Q va chop etish `UnicodeEncodeError` bilan
# BUTUN TO'PLAMNI o'ldiradi. `import_test` aynan shu sababdan
# 143 ta tekshiruvni bajarmasdan yiqilardi. Tafsilot: _tests/konsol.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import psycopg2  # noqa: E402

# Tekshiriladigan konstantalar (kod bilan sinxron bo'lishi uchun modullardan)
import etl_tenders  # noqa: E402
import etl_uzex     # noqa: E402

NEW_STATUSES = ("tech_check_docs", "agree_objections")

_results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def db():
    dsn = os.environ.get("XT_DB_DSN")
    if not dsn:
        sys.exit("XATO: XT_DB_DSN topilmadi (.env ni tekshiring).")
    return psycopg2.connect(dsn)


# ---------------------------------------------------------------------------
# 1-2) Lug'at
# ---------------------------------------------------------------------------
def test_dim_status(conn) -> None:
    print("\n[1] dim_status — yangi statuslar lug'atda bormi")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status_code, COALESCE(name_uz, name_ru) "
            "FROM dim_status WHERE domain='tender' AND status_code = ANY(%s)",
            (list(NEW_STATUSES),))
        found = dict(cur.fetchall())
    for code in NEW_STATUSES:
        check(f"dim_status['{code}'] mavjud", code in found)
        check(f"dim_status['{code}'] nomi bo'sh emas",
              bool((found.get(code) or "").strip()),
              found.get(code) or "(bo'sh)")

    print("\n[2] status yetimlari — har bir tender.status lug'atda bormi")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.status, count(*) FROM tender t
            LEFT JOIN dim_status s
                   ON s.status_code = t.status AND s.domain='tender'
            WHERE t.status IS NOT NULL AND s.status_code IS NULL
            GROUP BY t.status ORDER BY 2 DESC""")
        orphans = cur.fetchall()
    check("lug'atda yo'q status qolmadi", not orphans,
          "; ".join(f"{s}={n}" for s, n in orphans) or "yetim yo'q")


# ---------------------------------------------------------------------------
# 3-4) Qamrov va tur
# ---------------------------------------------------------------------------
def test_coverage(conn) -> None:
    print("\n[3] qamrov — ikkinchi reyestrlar bazaga tushdimi")
    with conn.cursor() as cur:
        cur.execute("SELECT source_platform, type, count(*) FROM tender "
                    "GROUP BY 1,2 ORDER BY 1,2")
        rows = cur.fetchall()
    counts = {(p, t): n for p, t, n in rows}
    for p, t, n in rows:
        print(f"        {p:10s} type={str(t):10s} {n}")

    check("xt-xarid: type='selection' yozuvlar bor",
          counts.get(("xt-xarid", "selection"), 0) > 0,
          f"{counts.get(('xt-xarid', 'selection'), 0)} ta")
    check("xt-xarid: type='tender' yozuvlar saqlanib qoldi",
          counts.get(("xt-xarid", "tender"), 0) > 0,
          f"{counts.get(('xt-xarid', 'tender'), 0)} ta")

    print("\n[4] type — uzex TypeId=1 'tender' emas, 'selection' bo'ldimi")
    check("etl_uzex.TYPE_BY_ID[1] == 'selection'",
          etl_uzex.TYPE_BY_ID.get(1) == "selection",
          str(etl_uzex.TYPE_BY_ID))
    check("etl_uzex.TYPE_BY_ID[2] == 'tender'",
          etl_uzex.TYPE_BY_ID.get(2) == "tender")
    check("uzex: type='selection' yozuvlar bor",
          counts.get(("uzex", "selection"), 0) > 0,
          f"{counts.get(('uzex', 'selection'), 0)} ta")

    # Ochiq lotlar soni - P0-1 ning asosiy o'lchovi
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM tender WHERE status='open'")
        n_open = cur.fetchone()[0]
    check("ochiq lotlar 66 dan ko'p (eski qamrov)", n_open > 66, f"{n_open} ta ochiq")


# ---------------------------------------------------------------------------
# 5) ID to'qnashuvi
# ---------------------------------------------------------------------------
def test_id_collisions(conn, tarmoqsiz: bool) -> None:
    print("\n[5] ID to'qnashuvi — reyestrlar ID fazolari kesishmaydimi")

    # Baza darajasi: uzex ofseti xt-xarid ID diapazoniga tushib qolmasin
    with conn.cursor() as cur:
        cur.execute("SELECT min(id), max(id) FROM tender WHERE source_platform='xt-xarid'")
        xt_lo, xt_hi = cur.fetchone()
        cur.execute("SELECT min(id), max(id) FROM tender WHERE source_platform='uzex'")
        uz_lo, uz_hi = cur.fetchone()
    check("uzex global ID diapazoni xt-xarid bilan kesishmaydi",
          xt_hi is None or uz_lo is None or uz_lo > xt_hi,
          f"xt=[{xt_lo}..{xt_hi}] uzex=[{uz_lo}..{uz_hi}]")

    if tarmoqsiz:
        print("        (--tarmoqsiz: manba darajasidagi tekshiruv "
              "o'tkazib yuborildi)")
        return

    # TASHQI UZILISH BUTUN TO'PLAMNI YIQITMASIN (B-2, 2026-09-01).
    #
    # O'LCHANGAN: manba `ref_selection_public` uchun HTTP 400
    # qaytardi va istisno `main()` gacha ko'tarilib, QOLGAN 50 dan
    # ortiq tekshiruv UMUMAN bajarilmadi — to'plam xulosa qatorisiz
    # o'ldi. Bitta tashqi uzilish butun natijani YO'Q qildi.
    #
    # Endi u YIQILGAN TEKSHIRUV bo'lib qoladi: manba nosozligi
    # KO'RINADI (yashirilmaydi), lekin qolgan tekshiruvlar yuradi.
    try:
        t_ids = {r["id"] for r in
                 etl_tenders.fetch_all_tenders(["open"], "ref_tender_public")}
        s_ids = {r["id"] for r in
                 etl_tenders.fetch_all_tenders(["open"], "ref_selection_public")}
        inter = t_ids & s_ids
        check("xt-xarid: ref_tender_public vs ref_selection_public kesishmaydi",
              not inter,
              f"tender={len(t_ids)}, selection={len(s_ids)}, umumiy={len(inter)}")
    except Exception as e:                                # noqa: BLE001
        check("xt-xarid: manba reyestrlari o'qildi", False,
              f"{type(e).__name__}: {str(e)[:150]}")

    # Manba darajasi: uzex ikki TypeId (faqat ro'yxat, GetTrade chaqirilmaydi)
    try:
        u2 = {int(r["id"]) for r in etl_uzex.fetch_list(2)}
        u1 = {int(r["id"]) for r in etl_uzex.fetch_list(1)}
        inter_u = u1 & u2
        check("uzex: TypeId=1 vs TypeId=2 kesishmaydi",
              not inter_u,
              f"TypeId2={len(u2)}, TypeId1={len(u1)}, umumiy={len(inter_u)}")
    except Exception as e:                                # noqa: BLE001
        check("uzex: manba ro'yxatlari o'qildi", False,
              f"{type(e).__name__}: {str(e)[:150]}")


# ---------------------------------------------------------------------------
# 6) Orkestrator
# ---------------------------------------------------------------------------
def test_orchestrator() -> None:
    print("\n[6] run_etl.py — .env dan DSN + bola-jarayon chiqishi yo'qolmaydi")

    # XT_DB_DSN ni MUHITDAN OLIB TASHLAYMIZ: run_etl.py uni .env dan
    # o'qishi shart (Windows'dagi asosiy regressiya shu edi).
    env = {k: v for k, v in os.environ.items() if k != "XT_DB_DSN"}
    env["PYTHONIOENCODING"] = "utf-8"

    res = subprocess.run(
        [sys.executable, os.path.join(ROOT, "run_etl.py"),
         "--limit", "1", "--skip-categorize"],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900)
    out = (res.stdout or "") + (res.stderr or "")

    check("run_etl.py XT_DB_DSN'siz muhitda ham ishga tushdi",
          "XT_DB_DSN o'rnatilmagan" not in out,
          "chiqishda 'XT_DB_DSN o'rnatilmagan' yo'q")
    check("UnicodeDecodeError chiqmadi",
          "UnicodeDecodeError" not in out)
    check("bola-jarayon chiqishi ko'rinadi (jimgina yo'qolmadi)",
          "etl_tenders.py" in out and "etl_uzex.py" in out)
    check("ikkala ochiq reyestr chaqirildi",
          "ref_tender_public" in out and "ref_selection_public" in out)
    check("uzex ikkala TypeId chaqirildi",
          out.count("etl_uzex.py --type-id") >= 2 or
          ("--type-id 1" in out and "--type-id 2" in out))
    check("etl_run jurnaliga ikkala platforma yozildi",
          "=> xt-xarid:" in out and "=> uzex:" in out)
    check("run_etl.py 0 kod bilan tugadi", res.returncode == 0,
          f"returncode={res.returncode}")

    if res.returncode != 0:
        print("        --- chiqishning oxiri ---")
        for ln in out.strip().splitlines()[-15:]:
            print("        " + ln)


#: Teskari qo'shtirnoq — IQTIBOS belgisi.
BT = chr(96)

#: Ochiq ish belgisi. `§` — hujjatdagi bo'limga HAVOLA.
_TODO_RE = re.compile(r"(TODO|FIXME|XXX|HACK)\s*(\(([^)]*)\))?", re.I)


def test_ochiq_ishlar_belgilangan() -> None:
    """OCHIQ ISH IZOHDA EMAS, BELGIDA bo'lsin.

    Muammoni izohda tasvirlash uni YOPILGANDEK ko'rsatadi.
    `kodlash.py:39-43` da `v_review_disagreement` nosozligi to'liq
    yozilgan edi — sana, ta'sir, misol bilan — va ko'rinish
    tuzatilmagan. Yozilgani uchun ish bajarilgan kabi tuyulgan.

    QOIDA: aniqlangan har muammo ikkitadan biri bo'lsin —
      * `xfail` sinov (yiqilib turadi, tuzatilgach yashillanadi);
      * `TODO(§16.xx)` — bo'limga HAVOLA bilan.

    Bu sinov NOLGA TALAB QILMAYDI: ochiq ish bo'lishi normal.
    U faqat ularni KO'RINADIGAN qiladi va havolasiz belgini
    rad etadi.
    """
    print(chr(10) + "--- Ochiq ishlar belgilangan ---")

    fayllar = []
    for kat in ("api", ".", "_tests"):
        d = os.path.join(ROOT, kat)
        for nom in sorted(os.listdir(d)):
            if nom.endswith(".py") and not nom.startswith("__"):
                fayllar.append(os.path.join(d, nom))

    belgilar, havolasiz = [], []
    for p in fayllar:
        for i, q in enumerate(io.open(p, encoding="utf-8").read().split(chr(10))):
            t = q.strip()
            # FAQAT izoh qatorlari — nasr skanerlanmaydi, lekin
            # belgi ATAYLAB izohda turadi.
            if not t.startswith("#"):
                continue
            m = _TODO_RE.search(t)
            if not m:
                continue
            # Skanerning O'Z ta'rifi hisoblanmasin.
            if "_TODO_RE" in t or "skaner-namuna" in t:
                continue
            # IQTIBOS BELGI EMAS.
            #
            # Uchinchi marta bir xil xato: skaner o'z tushuntirish
            # izohini ochiq ish deb sanadi. Bu loyihada kod nomlari
            # doim `backtick` ichida yoziladi, ya'ni
            # `TODO(...)` — IQTIBOS, haqiqiy belgi esa
            # backticksiz turadi.
            if t[max(0, m.start() - 1)] == "`":
                continue
            yorliq = f"{os.path.basename(p)}:{i + 1}"
            belgilar.append(yorliq)
            if not (m.group(3) or "").strip().startswith("§"):
                havolasiz.append(f"{yorliq}  {t[:56]}")

    print(f"       ochiq ish belgilari: {len(belgilar)}")
    for b in belgilar:
        print(f"         {b}")

    # HAVOLA MAJBURIY: `TODO(§16.xx)` — bo'limsiz belgi keyin
    # nima uchun qo'yilgani unutiladi va yana izohga aylanadi.
    check("har belgi bo'limga HAVOLA qiladi", not havolasiz,
          "; ".join(havolasiz[:4]))

    # SKANERNI SINAYMIZ.
    check("skaner havolasiz belgini TOPADI",
          bool(_TODO_RE.search("# TODO: keyinroq"))
          and not (_TODO_RE.search("# TODO: keyinroq").group(3) or ""))
    m2 = _TODO_RE.search("# TODO(§16.51): sabab")
    check("skaner havolali belgini QABUL qiladi",
          bool(m2) and (m2.group(3) or "").startswith("§"))

    # IQTIBOS tutilmasin — aks holda skaner o'z nasrini sanaydi.
    iqtibos = "# HAVOLA MAJBURIY: " + BT + "TODO(§16.xx)" + BT + " shakli"
    m3 = _TODO_RE.search(iqtibos)
    check("skaner IQTIBOSNI belgi deb sanamaydi",
          bool(m3) and iqtibos[m3.start() - 1] == BT,
          "backtick ichidagi TODO — iqtibos")


def test_quvur_jimgina_otmasin() -> None:
    """QUVUR KAMROQ ISH QILSA — BILINSIN.

    Uch xato bir sinfdan edi: qadam yozilgan, ulangan, lekin AMALDA
    BAJARILMAGAN — va yurish baribir "muvaffaqiyatli" deb tugagan.
    """
    print(chr(10) + "--- Quvur jimgina o'tmasin ---")

    src = io.open(os.path.join(ROOT, "run_etl.py"), encoding="utf-8").read()

    # 1. TARTIB. `sole_company_id()` `load_dotenv()` DAN KEYIN turishi
    #    SHART. Aks holda DSN hali o'qilmagan bo'ladi, `init_pool()`
    #    yiqiladi va `with_requirements` jimgina o'chiriladi. Amalda
    #    HAR SOAT shunday bo'lgan.
    i_env = src.find("load_dotenv(os.path.join(HERE")
    i_com = src.find("auth.sole_company_id()")
    check("load_dotenv() manba ichida topildi", i_env > 0)
    check("sole_company_id() load_dotenv() DAN KEYIN",
          0 < i_env < i_com,
          f"load_dotenv@{i_env}, sole_company_id@{i_com}")

    # 2. POST-QADAM XATOSI chiqish kodiga ta'sir qilsin. Avval `_ok`
    #    tashlab yuborilardi: vektorlash yiqilsa ham "OK" derdi.
    check("post-qadamlar xatosi yig'iladi",
          "post_xatolar.append" in src,
          "post-qadam `_ok` i tashlab yuborilmasin")
    check("chiqish kodi post-qadamlarni hisobga oladi",
          "all(results) and not post_xatolar" in src,
          "`ok = all(results)` yolg'iz YETARLI EMAS")
    n_post = src.count("emit([" + chr(34) + chr(92) + "n===== post:")
    n_xato = src.count("post_xatolar.append")
    check("HAR BIR post-qadam sanaladi",
          n_xato >= n_post,
          f"{n_post} ta qadam, {n_xato} ta xato yig'ish")

    # 3. MAJBURAN TO'XTATILGAN bola bir marta qayta urinilsin.
    #    Jurnalda 14 kunda 100 marta uchradi (~10% yurish) va yangi
    #    tenderlar shu sababli yig'ilmay qolardi.
    check("uzilish kodi nomlangan",
          "UZILISH_KODI = 3221225786" in src)
    check("qayta urinish HAQIQIY Ctrl+C da o'chadi",
          "not _UZILDI" in src,
          "foydalanuvchi to'xtatgan yurish o'jarlik bilan davom etmasin")


def test_musbat_tasdiq(conn) -> None:
    """YURISH ISH QILGANINI ISBOTLASIN — "yiqilmadim" demasin.

    Bu loyihada UCHINCHI marta takrorlangan sinf:
      - `_cheklov_xatosimi()` NOT NULL ni CHECK deb yutgani;
      - skanerning "0 ta buzilish" i (o'zini o'lchagani);
      - `all(results)` post-qadamlarni ko'rmagani.

    Har uchalasida muvaffaqiyat signali SALBIY shartdan olingan
    ("xato chiqmadi") va signalning O'ZI tekshirilmagan.
    """
    print(chr(10) + "--- Musbat tasdiq ---")

    sys.path.insert(0, ROOT)
    import run_etl

    # 1. FUNKSIYA XULQI. Navbat bor edi-yu kamaymasa — XATO.
    x = []
    run_etl.siljish_tekshir("sinov", 10, 10, x)
    check("navbat KAMAYMASA xato beriladi", len(x) == 1, str(x))
    check("xabar sababni aytadi",
          x and "ISH" in x[0].upper() and "10" in x[0], str(x))

    x = []
    run_etl.siljish_tekshir("sinov", 10, 4, x)
    check("navbat kamaysa xato YO'Q", not x, str(x))

    x = []
    run_etl.siljish_tekshir("sinov", 0, 0, x)
    check("navbat BO'SH bo'lsa xato yo'q", not x,
          "qiladigan ish bo'lmasa — nosozlik emas")

    # O'LCHOVSIZLIK ham xato: o'lchamasdan "muvaffaqiyat" deb
    # bo'lmaydi. Aynan shu narsa ikki hafta yashirgan edi.
    x = []
    run_etl.siljish_tekshir("sinov", None, 5, x)
    check("O'LCHANMAGAN holat ham XATO", len(x) == 1, str(x))
    x = []
    run_etl.siljish_tekshir("sinov", 5, None, x)
    check("keyingi o'lchov yo'qligi ham XATO", len(x) == 1, str(x))

    # 2. SO'ROV SINXRONMI. `run_etl.SQL_TALAB_QOLGAN` `api.requirement`
    #    dagi `SQL_PENDING` bilan bir xil shartni sanashi kerak. Ular
    #    ikki faylda yozilgan, ya'ni jimgina ajralib ketishi mumkin.
    from api import db as apidb, requirement as R
    apidb.init_pool()
    cid = apidb.scalar("""SELECT company_id FROM v_requirement_review
                          GROUP BY company_id ORDER BY count(*) DESC LIMIT 1""")
    if cid:
        with conn.cursor() as cur:
            cur.execute(run_etl.SQL_TALAB_QOLGAN,
                        {"company_id": cid, "method": "naqsh"})
            n_etl = int(cur.fetchone()[0])
        n_api = len(R.pending(cid, limit=100000, method="naqsh"))
        check("run_etl va api.requirement BIR XIL navbatni ko'radi",
              n_etl == n_api, f"run_etl={n_etl}, api={n_api}")

    # 3. QUVUR ULARNI CHAQIRADIMI. Funksiya yozilib, ulanmasligi —
    #    aynan shu bo'limdagi 3-nosozlik edi.
    src = io.open(os.path.join(ROOT, "run_etl.py"), encoding="utf-8").read()
    # Q-1 dan keyin quvur IKKALA bepul usulni ham yurgizadi va
    # siljish HAR IKKALASIDA tekshiriladi, shuning uchun chaqiruv
    # f-satr bo'lib qoldi (`f"talab ajratish ({_usul})"`).
    check("talab ajratishdan keyin siljish tekshiriladi",
          'siljish_tekshir(f"talab ajratish' in src)
    check("quvur IKKALA bepul usulni ham yurgizadi",
          'for _usul in ("reyestr", "naqsh")' in src,
          "ilgari faqat `naqsh` yurardi — 3078 tender ishlanmay qolgandi")
    check("vektorlashdan keyin siljish tekshiriladi",
          'siljish_tekshir("vektorlash"' in src)
    check("korpus o'sishi hisobga olinadi (`QUVIB YETDI`)",
          "QUVIB YETDI" in src,
          "korpus o'sib turadi — `tugadi` holati yo'q")


def test_env_qulfi() -> None:
    """IZOH EMAS, QULF.

    1-nosozlikda izoh AYNAN o'sha xatoni tasvirlab turardi va kod
    uning ustiga qo'yildi. Endi `.env` o'qilmasdan bazaga yo'l
    ochilmaydi.
    """
    print(chr(10) + "--- .env qulfi ---")

    sys.path.insert(0, ROOT)
    import run_etl

    eski = run_etl._ENV_YUKLANDI
    try:
        run_etl._ENV_YUKLANDI = False
        xato = None
        try:
            run_etl.db()
        except RuntimeError as e:
            xato = str(e)
        except Exception as e:                              # noqa: BLE001
            xato = "NOTO'G'RI TUR: " + type(e).__name__
        check(".env o'qilmasdan db() OCHILMAYDI", bool(xato), str(xato))
        check("xato sababni tushuntiradi",
              bool(xato) and "load_dotenv" in xato, str(xato)[:120])
    finally:
        run_etl._ENV_YUKLANDI = eski

    # Bayroq YOQILGANDA yo'l ochiq bo'lsin — qulf ishni TO'SMASIN.
    # (Sinov `main()` ni chaqirmaydi, ya'ni modul ichidagi
    # `load_dotenv()` yurmagan — bayroqni qo'lda yoqamiz.)
    run_etl._ENV_YUKLANDI = True
    try:
        conn2 = run_etl.db()
        check("bayroq yoqilgach db() ISHLAYDI", conn2 is not None)
        conn2.close()
    except Exception as e:                                  # noqa: BLE001
        check("bayroq yoqilgach db() ISHLAYDI", False, str(e)[:120])
    finally:
        run_etl._ENV_YUKLANDI = eski

    src = io.open(os.path.join(ROOT, "run_etl.py"), encoding="utf-8").read()
    check("sole_company_id() yo'li ham qulflangan",
          'env_shart("sole_company_id()")' in src)

    # CHIQISH YO'QOLMASIN: seans tugaganda ~5 soniya beriladi.
    check("uzilishda jurnal diskka yuviladi",
          "os.fsync(sys.stdout.fileno())" in src,
          "flush() faqat OT buferigacha olib boradi")
    check("chiqish qator-qator yuviladi",
          "line_buffering=True" in src)
    check("SIGBREAK ham tutiladi",
          "SIGBREAK" in src,
          "Windows'da CTRL_BREAK_EVENT shunga tushadi")


def test_qayta_urinish() -> None:
    """Qayta urinish AMALDA ishlaydimi — soxta bola bilan.

    Statik tekshiruv "kod bor" deydi, "kod ishlaydi" demaydi.
    """
    print(chr(10) + "--- Qayta urinish (soxta bola) ---")

    sys.path.insert(0, ROOT)
    import run_etl

    fix = os.path.join(ROOT, "_tests", "fixtures")
    # KATALOG YARATILADI. `_tests/fixtures/` da kuzatiladigan fayl
    # YO'Q, ya'ni u git da mavjud emas va `git archive` dan chiqqan
    # TOZA daraxtda ham bo'lmaydi.
    #
    # O'LCHANGAN (2026-09-08, izolyatsiyalangan darvoza):
    #   FileNotFoundError: '.../_tests/fixtures/_soxta_bola.py'
    #
    # Ishlab chiquvchi mashinasida katalog oldingi yurishlardan
    # QOLGAN, shuning uchun nuqson faqat toza daraxtda ko'rinadi —
    # "menda ishlayapti" sinfining aynan o'zi.
    os.makedirs(fix, exist_ok=True)
    sanoq = os.path.join(fix, "_urinish.txt")
    bola = os.path.join(fix, "_soxta_bola.py")
    io.open(bola, "w", encoding="utf-8").write(
        "import io, os, sys" + chr(10) +
        "p = os.path.join(os.path.dirname(__file__), '_urinish.txt')" + chr(10) +
        "n = int(io.open(p).read()) if os.path.exists(p) else 0" + chr(10) +
        "io.open(p, 'w').write(str(n + 1))" + chr(10) +
        "print('urinish', n + 1)" + chr(10) +
        # MAJBURIY TO'XTATISH PLATFORMAGA QARAB YASALADI.
        #
        # Ilgari bu yerda `sys.exit(3221225786)` turardi — Windows
        # `STATUS_CONTROL_C_EXIT` (`0xC000013A`). POSIX da chiqish kodi
        # 8 BITGA qisqaradi (`0xC000013A & 0xFF == 58`), ya'ni Linuxda
        # sinov "majburan to'xtatildi" ni UMUMAN yasay olmasdi va
        # `err=chiqish kodi 58` bilan yiqilardi.
        #
        # Linuxda haqiqiy ekvivalent — SIGKILL: `subprocess` uni `-9`
        # deb qaytaradi.
        ("os.kill(os.getpid(), 9) if n == 0 else sys.exit(0)"
         if os.name != "nt" else
         "sys.exit(3221225786 if n == 0 else 0)") + chr(10))
    try:
        # 1-urinish o'ldiriladi, 2-si o'tadi.
        if os.path.exists(sanoq):
            os.remove(sanoq)
        run_etl._UZILDI = False
        ok, err, _dt, out, _kod = run_etl.run_script(
            os.path.join("_tests", "fixtures", "_soxta_bola.py"), [])
        check("majburan to'xtatilgan bola QAYTA urinildi", ok,
              f"err={err}, out={out}")
        check("qayta urinish jurnalda ko'rinadi",
              any("qayta urinilmoqda" in x for x in out), str(out))
        check("sanoq 2 ga yetdi",
              io.open(sanoq).read().strip() == "2",
              io.open(sanoq).read())

        # HAQIQIY Ctrl+C dan keyin qayta urinilmasin.
        os.remove(sanoq)
        run_etl._UZILDI = True
        ok2, _err2, _dt2, out2, _kod2 = run_etl.run_script(
            os.path.join("_tests", "fixtures", "_soxta_bola.py"), [])
        check("Ctrl+C dan keyin QAYTA URINILMAYDI", not ok2,
              "foydalanuvchi to'xtatgan yurish davom etmasin")
        check("faqat bir marta yurgizildi",
              io.open(sanoq).read().strip() == "1",
              io.open(sanoq).read())

        # Oddiy xato (kod 1) qayta urinilmasin — vaqt behuda ketmasin.
        io.open(bola, "w", encoding="utf-8").write(
            "import io, os, sys" + chr(10) +
            "p = os.path.join(os.path.dirname(__file__), '_urinish.txt')" + chr(10) +
            "n = int(io.open(p).read()) if os.path.exists(p) else 0" + chr(10) +
            "io.open(p, 'w').write(str(n + 1))" + chr(10) +
            "sys.exit(1)" + chr(10))
        os.remove(sanoq)
        run_etl._UZILDI = False
        run_etl.run_script(os.path.join("_tests", "fixtures",
                                        "_soxta_bola.py"), [])
        check("oddiy xato QAYTA URINILMAYDI",
              io.open(sanoq).read().strip() == "1",
              "faqat majburiy to'xtatish qayta urinilsin")
    finally:
        run_etl._UZILDI = False
        for f in (bola, sanoq):
            if os.path.exists(f):
                os.remove(f)


def test_etl_run_log(conn) -> None:
    print("\n[7] etl_run jurnali — oxirgi yurishlar sog'lom")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (source_platform)
                   source_platform, status, found, new, finished_at,
                   terminal_reason, processed, succeeded
            FROM etl_run ORDER BY source_platform, started_at DESC""")
        rows = cur.fetchall()
    for p, st, found, new, fin, sabab, proc, succ in rows:
        print(f"        {p:10s} {st:8s} {(sabab or '-'):14s} "
              f"jami={found} yangi={new} ko'rildi={proc} yozildi={succ}")
    check("etl_run'da ikkala platforma bor",
          {r[0] for r in rows} >= {"xt-xarid", "uzex"},
          str(sorted(r[0] for r in rows)))

    # STATUS LUG'ATI KENGAYDI (schema_patch_etl_ishonch.sql):
    #   ok      — to'liq tugadi
    #   partial — vaqt byudjeti tugadi yoki ba'zi yozuv yiqildi;
    #             checkpoint bor va keyingi yurish DAVOM ettiradi.
    #             Bu NOSOZLIK EMAS: ish bajarildi.
    #   running — sinov ETL yurayotganda ishga tushgan
    #   error   — haqiqiy muammo
    check("oxirgi yurishlarda xato yo'q",
          all(r[1] != "error" for r in rows),
          "; ".join(f"{r[0]}={r[1]}"
                    + (f"/{r[5]}" if r[5] else "") for r in rows))

    # QISMAN yurish ISH BAJARGAN bo'lishi kerak. "Qisman" ni hech narsa
    # qilmasdan qaytarish `ok` ni yolg'on qilishning boshqa shakli bo'lardi.
    for r in rows:
        if r[1] == "partial":
            check(f"{r[0]}: qisman yurish ish BAJARDI",
                  (r[6] or 0) > 0,
                  f"ko'rildi={r[6]} — qisman = 'tugamadi', 'hech narsa qilmadi' emas")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="ETL qamrovi sinovi")
    rejim.bayroqlar(ap)
    ap.add_argument("--skip-orchestrator", action="store_true",
                    help="run_etl.py sinovini o'tkazib yubor (u ~1 daqiqa)")
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("ETL QAMROVI SINOVI (P0-1)")
    print("=" * 70)

    conn = db()
    try:
        test_dim_status(conn)
        test_coverage(conn)
        test_id_collisions(conn, args.tarmoqsiz)
        if not (args.skip_orchestrator or args.tarmoqsiz):
            test_orchestrator()
        test_ochiq_ishlar_belgilangan()
        test_quvur_jimgina_otmasin()
        test_musbat_tasdiq(conn)
        test_env_qulfi()
        test_qayta_urinish()
        test_etl_run_log(conn)
    finally:
        conn.close()

    failed = [n for n, ok, _ in _results if not ok]
    print("\n" + "=" * 70)
    print(f"NATIJA: {len(_results) - len(failed)}/{len(_results)} o'tdi")
    for n in failed:
        print(f"  FAIL: {n}")
    print("=" * 70)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
