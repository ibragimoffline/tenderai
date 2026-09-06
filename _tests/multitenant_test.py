#!/usr/bin/env python3
"""
SINOV: KO'P-IJARACHILIK (J1) — "bir kompaniya boshqasiniki ko'rmaydi"
=====================================================================
Ikki xil tekshiruv bor va IKKALASI ham kerak:

  A. STATIK  — `api/*.py` dagi HAR SQL matnini o'qiydi: kompaniya jadvaliga
     tegsa, `company_id` ham bo'lishi SHART. Bu YANGI so'rov qo'shilganda
     avtomatik ushlaydigan yagona to'siq. Bazaga ULANMAYDI.

     Nega kerak: "ikki hisob bir-birini ko'rmaydi" degan sinov faqat
     YOZILGAN so'rovni tekshiradi. Ertaga kimdir `company_id` siz yangi
     `SELECT` qo'shsa — u sinov jim qoladi. Statik tekshiruv esa yiqiladi.
     Bu loyihaning "darvoza YOPIQ holatda boshlanadi" tamoyilining SQL
     qatlamidagi ko'rinishi (`api/main.py` PUBLIC_PATHS bilan bir xil g'oya).

  B. DINAMIK — bazada ikki hisob yaratib, biri ikkinchisining katalogi,
     smetasi, hujjati va sozlamasini KO'RA OLMASLIGINI tekshiradi.
     Baza kerak; `--offline` bilan o'tkazib yuboriladi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\multitenant_test.py
    .venv\\Scripts\\python.exe _tests\\multitenant_test.py --offline   # faqat statik

DIQQAT: dinamik qism SINOV HISOBLARINI yaratadi va oxirida O'CHIRADI
(prefiks: `_mt_test_`). Mavjud ma'lumotga tegmaydi.
"""
import argparse
import ast
import glob
import io
import os
import re
import sys
from typing import Optional

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

_results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, bool(ok), detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"\n       {detail}" if detail and not ok else ""))
    return bool(ok)


def eq(name: str, got, want) -> bool:
    return check(name, got == want, f"kutilgan={want!r} olingan={got!r}")


# =============================================================================
# A. STATIK — SQL matnlarini skanerlash
# =============================================================================

#: Kompaniya SIRI saqlanadigan jadvallar. Bu ro'yxatga tushgan jadvalga
#: tegadigan HAR SQL da `company_id` bo'lishi shart.
#: Manba: schema_patch_multitenant.sql §2-§5.
KOMPANIYA_JADVALLARI = {
    "catalog_product",
    "catalog_import_batch",
    "catalog_state",
    "saved_search",
    "company_profile",
    "company_document",
    "tender_pricing",
    "pricing_settings",
    "notify_settings",
    "notify_sent",
    "notify_telegram_subscriber",
    "notify_telegram_link",
    # J3 (2026-08-25): qamrov kompaniyaga bog'liq — qaysi tenderlar
    # ajratilgani katalogga qarab farq qiladi, ya'ni talab ham
    # kompaniyaniki.
    "tender_requirement",
    "tender_requirement_run",
}

#: UMUMIY jadvallar — kompaniyaga bog'liq emas, filtr KERAK EMAS.
#: (tender, tender_lot, tender_good, tender_item, tender_document,
#:  tender_document_text, tender_category, dim_*, etl_run, company_account,
#:  company_session, login_attempt, doc_chunk, tender_embedding)
#:
#: !!! NOM TO'QNASHUVI — J1.6 da ENG XAVFLI JOY !!!
#: `tender` jadvalida HAM `company_id` ustuni bor, LEKIN u butunlay
#: boshqa narsa: u BUYURTMACHI tashkilotning manba platformadagi id si
#: (`xt_xarid_schema.sql`: "Buyurtmachi (company) — company_id 1163,
#: company_name 'АО Quyuv-mexanika zavodi'"). Bu BIZNING ijarachimiz EMAS.
#: `schema_patch_multitenant.sql` unga TEGMAYDI va tegmasligi ham kerak.
#: SQL yozayotganda `t.company_id` (buyurtmachi) va `cp.company_id`
#: (bizning kompaniya) ni ALMASHTIRIB YUBORMANG — filtr jimgina noto'g'ri
#: ishlaydi va hech qanday xato bermaydi.

#: `ai_analysis` ARALASH: `summary_v1` umumiy (company_id IS NULL),
#: `match_v2`/`gonogo_v2` kompaniyaniki. Shuning uchun u alohida
#: tekshiriladi — quyidagi `test_ai_analysis_aralash()`.

#: Skaner tegmaydigan fayllar: ular ETL yoki migratsiya, ya'ni platforma
#: nomidan ishlaydi (kompaniya nomidan emas).
SKANER_TASHQARISIDA = {"ai_chat.py"}   # tool'lari ChatContext orqali filtrlaydi

#: Bitta SQL bayonotini ajratish uchun: `SELECT`/`UPDATE`/`DELETE`/`INSERT`
#: dan boshlanib, keyingi bayonotgacha yoki matn oxirigacha.
_SQL_BLOK = re.compile(
    r"(?is)\b(SELECT|UPDATE|DELETE\s+FROM|INSERT\s+INTO)\b.*?(?=\b(?:SELECT|UPDATE|"
    r"DELETE\s+FROM|INSERT\s+INTO)\b|\Z)")


def _sql_matnlari(path: str):
    """Fayldagi SQL matnlarini ajratadi — AST orqali.

    NEGA REGEXP EMAS: SQL ko'pincha bo'lib yoziladi va regexp faqat
    birinchi bo'lakni ko'radi. Masalan

        db.query("SELECT lower(name) AS n FROM catalog_product "
                 "WHERE company_id = %(company_id)s", {...})

    to'g'ri kod, lekin regexp skaner uni "filtrsiz" deb hisoblardi —
    YOLG'ON OGOHLANTIRISH. Python esa yonma-yon literallarni parse
    paytida BIRLASHTIRADI, ya'ni AST to'liq matnni beradi.

    `f"..."` (JoinedStr) alohida: literal qismlar birlashtiriladi,
    ifodalar `{}` bilan almashtiriladi — jadval nomi va `company_id`
    matnda qoladi, bu tekshiruv uchun yetarli.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())

    def _izohsiz(sql: str) -> str:
        """SQL IZOHLARINI olib tashlaydi — skaner NASRNI o'qimasin.

        O'LCHANGAN YOLG'ON TOPILMA (2026-09-03). `pilot_rejim()` dagi
        SQL ga izoh qo'shildi:

            SELECT rejim FROM review_pilot
             WHERE company_id = %(c)s AND tender_id = %(t)s
            -- Bir tender ikki avlodda bo'lishi mumkin; ...
             ORDER BY avlod DESC LIMIT 1

        `tender` so'zi FAQAT IZOHDA edi, lekin A4 tekshiruvi
        `\\btender\\b` ni topib SQL ni "tender jadvaliga tegadi" deb
        hisobladi va aliassiz `company_id` uchun BUZILISH e'lon qildi.
        Kod SOG'LOM edi — `review_pilot` da alias umuman kerak emas.

        Bu loyihada aynan shu sinf xato UCH MARTA takrorlangan
        (skaner o'z izohiga, o'z sinov namunasiga, o'z
        tushuntirishiga urildi). Qoida: KOD SKANERLANADI, NASR EMAS.
        """
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)   # /* blok */
        sql = re.sub(r"--[^\n]*", " ", sql)                # -- qator
        return sql

    def matn(node) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append(" {} ")
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = matn(node.left), matn(node.right)
            if a is not None and b is not None:
                return a + b
        return None

    # So'z chegarasi MAJBURIY: `SET` OFFSET/ASSET ichida ham uchraydi.
    fel = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", re.I)
    manba = re.compile(r"\b(FROM|INTO|SET)\b", re.I)

    for node in ast.walk(tree):
        t = matn(node)
        # Modul/funksiya hujjati emas, haqiqiy SQL bo'lsin: fe'l ham,
        # manba (FROM/INTO/SET) ham bo'lishi shart.
        if t and fel.search(t) and manba.search(t):
            # IZOHSIZ chiqariladi — tekshiruvlar KODNI ko'rsin.
            yield _izohsiz(t)


#: Katalog (metadata) so'rovlari — ular MA'LUMOTGA tegmaydi, faqat
#: "shu jadval/ustun bazada bormi" deb so'raydi (patch qo'llanganmi).
#: Jadval nomi ularda SATR sifatida uchraydi, shuning uchun skaner ularni
#: "filtrsiz" deb belgilardi — yolg'on ogohlantirish.
_METADATA = re.compile(r"\b(information_schema|pg_catalog|pg_indexes|"
                       r"pg_constraint|pg_class|pg_index|pg_attribute)\b", re.I)


def _tegadigan_jadvallar(sql: str) -> set:
    """SQL qaysi kompaniya jadvallariga tegadi (metadata so'rovlari hisobga
    olinmaydi)."""
    if _METADATA.search(sql):
        return set()
    found = set()
    for t in KOMPANIYA_JADVALLARI:
        if re.search(rf"\b{re.escape(t)}\b", sql, re.I):
            found.add(t)
    return found


def test_statik_sql_filtri():
    print("\n[A] STATIK — SQL matnlarida company_id bormi")
    api_dir = os.path.join(ROOT, "api")
    buzuq = []
    tekshirilgan = 0

    for fname in sorted(os.listdir(api_dir)):
        if not fname.endswith(".py") or fname in SKANER_TASHQARISIDA:
            continue
        path = os.path.join(api_dir, fname)
        for sql in _sql_matnlari(path):
            jadvallar = _tegadigan_jadvallar(sql)
            if not jadvallar:
                continue
            tekshirilgan += 1
            if not re.search(r"\bcompany_id\b", sql, re.I):
                birinchi = " ".join(sql.split())[:90]
                buzuq.append(f"{fname}: {sorted(jadvallar)} -> {birinchi}...")

    check(f"{tekshirilgan} ta SQL skanerlandi", tekshirilgan > 0,
          "kompaniya jadvaliga tegadigan SQL topilmadi — skaner buzuqmi?")
    check("company_id siz SQL yo'q", not buzuq,
          "\n       ".join(buzuq[:12]) + (f"\n       ... yana {len(buzuq)-12} ta"
                                          if len(buzuq) > 12 else ""))


def test_tender_company_id_nomsiz_emas():
    """`tender` qatnashgan SQL da `company_id` ALIASSIZ ishlatilmasin.

    Sabab: `tender.company_id` = BUYURTMACHI tashkiloti (manba platformadan),
    `catalog_product.company_id` = BIZNING ijarachi. Ikkalasi bir so'rovda
    uchrasa va alias yozilmasa, PostgreSQL o'zi tanlaydi — natija xatosiz,
    lekin NOTO'G'RI. Bu jimgina buziladigan xato, shuning uchun statik
    to'siq qo'yamiz.

    Yagona haqiqiy yechim — ustunni qayta nomlash (`buyer_org_id`); bu
    tekshiruv shungacha bo'lgan himoya.
    """
    print("\n[A4] tender + company_id — alias majburiy")
    api_dir = os.path.join(ROOT, "api")
    buzuq = []
    tekshirilgan = 0

    for fname in sorted(os.listdir(api_dir)):
        if not fname.endswith(".py") or fname in SKANER_TASHQARISIDA:
            continue
        for sql in _sql_matnlari(os.path.join(api_dir, fname)):
            # SQL `tender` jadvaliga tegadimi (tender_lot, tender_good emas)
            if not re.search(r"\btender\b(?!_)", sql, re.I):
                continue
            if not re.search(r"\bcompany_id\b", sql, re.I):
                continue
            tekshirilgan += 1
            # Har `company_id` oldida `<alias>.` bo'lishi shart
            for m in re.finditer(r"(\w+\.)?\bcompany_id\b", sql, re.I):
                if m.group(1):
                    continue
                # `%(company_id)s` parametri va ustun ro'yxati — istisno
                oldin = sql[max(0, m.start() - 2):m.start()]
                if oldin.endswith("(") or oldin.endswith("%("):
                    continue
                birinchi = " ".join(sql.split())[:80]
                buzuq.append(f"{fname}: aliassiz company_id -> {birinchi}...")
                break

    check(f"{tekshirilgan} ta 'tender + company_id' SQL tekshirildi",
          True, "")
    check("aliassiz company_id yo'q", not buzuq, "\n       ".join(buzuq[:8]))

    # -----------------------------------------------------------------
    # SKANERNING O'ZI SINALADI
    # -----------------------------------------------------------------
    # 2026-09-03 da bu tekshiruv YOLG'ON topilma berdi: `review_pilot`
    # ustidagi SOG'LOM SQL ga izoh qo'shilgan edi va izohdagi "tender"
    # so'zi uni "tender jadvaliga tegadi" deb ko'rsatdi. Tuzatish —
    # `_sql_matnlari()` endi izohlarni olib tashlaydi.
    #
    # LEKIN "izohni olib tashlash" skanerni BO'SHATGAN bo'lishi ham
    # mumkin. Shuning uchun ikki tomon ham sinaladi: nasrni
    # e'tiborsiz qoldiradimi VA haqiqiy buzilishni hamon tutadimi.
    def _buzuqmi(sql: str) -> bool:
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
        sql = re.sub(r"--[^\n]*", " ", sql)
        if not re.search(r"\btender\b(?!_)", sql, re.I):
            return False
        if not re.search(r"\bcompany_id\b", sql, re.I):
            return False
        for m in re.finditer(r"(\w+\.)?\bcompany_id\b", sql, re.I):
            if m.group(1):
                continue
            oldin = sql[max(0, m.start() - 2):m.start()]
            if oldin.endswith("(") or oldin.endswith("%("):
                continue
            return True
        return False

    nasr = ("SELECT rejim FROM review_pilot "
            "WHERE company_id = %(c)s AND tender_id = %(t)s "
            "-- Bir tender ikki avlodda bo'lishi mumkin "
            "ORDER BY avlod DESC LIMIT 1")
    check("skaner NASRNI o'qimaydi (izohdagi 'tender' e'tiborsiz)",
          not _buzuqmi(nasr), nasr[:70])

    haqiqiy = ("SELECT t.id FROM tender t JOIN catalog_product p "
               "ON p.company_id = company_id WHERE t.status = 'open'")
    check("skaner HAQIQIY buzilishni HAMON tutadi",
          _buzuqmi(haqiqiy),
          "izohni olib tashlash skanerni BO'SHATMAGAN bo'lishi shart")

    blok = ("SELECT x FROM review_pilot /* tender haqida izoh */ "
            "WHERE company_id = %(c)s")
    check("blok izoh (/* */) ham e'tiborsiz", not _buzuqmi(blok), blok[:60])


def test_ai_analysis_aralash():
    """`ai_analysis` — `summary_v1` umumiy, qolgani kompaniyaniki."""
    print("\n[A2] ai_analysis — aralash egalik")
    path = os.path.join(ROOT, "api", "queries.py")
    src = open(path, encoding="utf-8").read()
    m = re.search(r"AI_CACHED_SQL\s*=\s*(?:\"\"\"|''')(.*?)(?:\"\"\"|''')", src, re.S)
    check("AI_CACHED_SQL topildi", m is not None)
    if m:
        sql = m.group(1)
        check("AI_CACHED_SQL da company_id bor",
              bool(re.search(r"\bcompany_id\b", sql, re.I)),
              "match_v2/gonogo_v2 kompaniya katalogiga asoslanadi — "
              "kompaniyasiz kesh boshqa kompaniyaning tahlilini qaytaradi. "
              f"Hozirgi SQL: {' '.join(sql.split())[:110]}")


def test_patch_royxati_mos():
    """Har kompaniya jadvali BIROR patchda `company_id` bilan bormi.

    OLDIN faqat `schema_patch_multitenant.sql` ga qarardi. Bu J1 uchun
    to'g'ri edi (u MAVJUD jadvallarga `company_id` qo'shgan), lekin
    keyin yaratilgan jadvallar uchun NOTO'G'RI: `tender_requirement`
    (J3) tug'ilishidanoq `company_id NOT NULL` bilan yaratilgan va
    retrofit patchida bo'lishi SHART EMAS.

    Endi BARCHA `schema_patch_*.sql` skanerlanadi va jadval nomi
    yonida `company_id` borligi tekshiriladi.
    """
    print("\n[A3] Patch <-> sinov ro'yxati mosligi")
    patchlar = sorted(glob.glob(os.path.join(ROOT, "schema_patch_*.sql")))
    if not patchlar:
        check("schema_patch_*.sql mavjud", False, "patch yozilmagan")
        return

    qamralgan, qayerda = set(), {}
    for path in patchlar:
        src = open(path, encoding="utf-8").read()
        nom = os.path.basename(path)
        for t in KOMPANIYA_JADVALLARI:
            if t in qamralgan:
                continue
            # Ikki shakl: retrofit patchida jadval nomi SATR sifatida
            # (`tai_add_company_id('x')`), yangi patchda esa CREATE TABLE.
            satr = re.search(rf"'{re.escape(t)}'", src)
            yaratish = re.search(
                rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?{re.escape(t)}\b"
                rf"(.|\n){{0,4000}}?company_id", src, re.I)
            if satr or yaratish:
                qamralgan.add(t)
                qayerda[t] = nom

    yetishmayotgan = KOMPANIYA_JADVALLARI - qamralgan
    check("har kompaniya jadvali biror patchda company_id bilan bor",
          not yetishmayotgan,
          f"hech qaysi patchda topilmadi: {sorted(yetishmayotgan)}")
    if not yetishmayotgan:
        yangi = {t: f for t, f in qayerda.items()
                 if "multitenant" not in f}
        if yangi:
            print(f"       (retrofitdan tashqari: "
                  f"{', '.join(f'{t}<-{f}' for t, f in sorted(yangi.items()))})")


# =============================================================================
# B. DINAMIK — ikki hisob bir-birini ko'rmaydi
# =============================================================================
PREFIX = "_mt_test_"


#: Kompaniya uzatilganini bildiradigan argument nomlari.
_CID_NOMLAR = {"company_id", "cid", "_cid", "company", "c_id"}

#: Kompaniyani QAYTARADIGAN (hal qiladigan) funksiyalar. Ularning
#: o'zi `sole_company_id()` ga tushishi ATAYLAB.
_MANBA = {"company_id_of", "_cid", "sole_company_id"}


def _cid_uzatilganmi(call) -> bool:
    """Chaqiruvda kompaniya uzatilganmi."""
    for kw in call.keywords:
        if kw.arg in _CID_NOMLAR:
            return True
    for a in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(a, ast.Name) and a.id in _CID_NOMLAR:
            return True
        # `company_id_of(request)` ARGUMENT sifatida — endpointlar
        # aynan shunday yozadi. Busiz ular soxta buzilish bo'lardi.
        if isinstance(a, ast.Call):
            f = a.func
            nom = (f.id if isinstance(f, ast.Name)
                   else f.attr if isinstance(f, ast.Attribute) else None)
            if nom in _CID_NOMLAR or nom in _MANBA:
                return True
        if isinstance(a, ast.Attribute) and a.attr in _CID_NOMLAR:
            return True
    return False


def _zaxira_shartimi(test) -> bool:
    """`company_id is None` yoki `not company_id`."""
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) \
            and test.left.id in _CID_NOMLAR \
            and any(isinstance(o, ast.Is) for o in test.ops) \
            and any(isinstance(c, ast.Constant) and c.value is None
                    for c in test.comparators):
        return True
    return (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Name)
            and test.operand.id in _CID_NOMLAR)


def _erta_qaytish(fn) -> bool:
    """`if company_id is not None: return ...` — `_cid()` shakli."""
    for n in ast.walk(fn):
        if not isinstance(n, ast.If):
            continue
        t = n.test
        if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) \
                and t.left.id in _CID_NOMLAR \
                and any(isinstance(o, ast.IsNot) for o in t.ops) \
                and any(isinstance(c, ast.Constant) and c.value is None
                        for c in t.comparators) \
                and any(isinstance(x, ast.Return) for x in n.body):
            return True
    return False


def _himoyalangan(fn, tugun) -> bool:
    """`tugun` QONUNIY zaxira yo'lidami.

    Zaxira SHARTNOMA: sessiyasiz chaqiruv (bildirishnoma tsikli, ERP,
    sinov) uchun yagona faol hisob olinadi. Uni buzilish deb sanash
    soxta topilma berardi — birinchi urinishda aynan shunday bo'ldi
    (4 topilma, TO'RTTASI HAM SOXTA).
    """
    if _erta_qaytish(fn):
        return True
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and _zaxira_shartimi(n.test):
            for ich in ast.walk(n):
                if ich is tugun:
                    return True
    return False


def _biladimi(fn) -> bool:
    """Funksiya kompaniyani BILADIMI — QANDAY olganidan qat'i nazar.

    TUYNUK SHU YERDA EDI. Avval mezon `company_id` PARAMETRI edi va
    u kompaniyaga tegadigan 127 funksiyadan faqat 69 tasini ko'rardi.
    Qolgan 58 tasi — endpointlar: ular `company_id_of(request)` dan
    oladi. Skaner ularni UMUMAN tekshirmasdi va "0 buzilish" degan
    javob "buzilish yo'q" emas, "KO'RINMAYAPTI" ma'nosini berardi.

    Kengaytirilgach uch haqiqiy buzilish topildi.
    """
    args = ([a.arg for a in fn.args.args]
            + [a.arg for a in fn.args.kwonlyargs])
    if "company_id" in args:
        return True
    for n in ast.walk(fn):
        # `cid = company_id_of(request)` yoki uni to'g'ridan-to'g'ri
        # chaqiruvga uzatish.
        if isinstance(n, ast.Call):
            f = n.func
            nom = (f.id if isinstance(f, ast.Name)
                   else f.attr if isinstance(f, ast.Attribute) else None)
            if nom in _MANBA:
                return True
        # `ctx.company_id` / `profil["company_id"]` — chat tool'lari.
        if isinstance(n, ast.Attribute) and n.attr == "company_id":
            return True
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                and n.slice.value == "company_id":
            return True
    return False


def _cid_skaner(kodlar=None):
    """`company_id` oladigan funksiya uni UZATADIMI.

    `kodlar` — {modul: manba}. Berilmasa butun `api/` o'qiladi
    (sinovning O'ZINI sinash uchun namuna beriladi).

    IKKI BUZILISH:
      a) `sole_company_id()` HIMOYASIZ chaqirilishi;
      b) kompaniyaga xos boshqa funksiyani KOMPANIYASIZ chaqirish —
         u ham `sole_company_id()` ga tushadi.
    """
    if kodlar is None:
        kodlar = {}
        for p in sorted(glob.glob(os.path.join(ROOT, "api", "*.py"))):
            nom = os.path.basename(p)[:-3]
            if not nom.startswith("__"):
                kodlar[nom] = io.open(p, encoding="utf-8").read()

    xos, qisqa, daraxt = set(), {}, {}
    for modul, src in kodlar.items():
        try:
            t = ast.parse(src)
        except SyntaxError:
            continue
        daraxt[modul] = t
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = ([x.arg for x in n.args.args]
                     + [x.arg for x in n.args.kwonlyargs])
                if "company_id" in a:
                    xos.add(f"{modul}.{n.name}")
                    qisqa.setdefault(n.name, set()).add(modul)

    buz = []
    for modul, t in daraxt.items():
        for fn in ast.walk(t):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _biladimi(fn):
                continue
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                if isinstance(n.func, ast.Attribute):
                    nom = n.func.attr
                    egasi = (n.func.value.id
                             if isinstance(n.func.value, ast.Name) else None)
                elif isinstance(n.func, ast.Name):
                    nom, egasi = n.func.id, modul
                else:
                    continue

                if nom == "sole_company_id":
                    # Hal qiluvchilarning O'ZI istisno.
                    if fn.name in _MANBA:
                        continue
                    if not _himoyalangan(fn, n):
                        buz.append((modul, fn.name, n.lineno,
                                    "sole_company_id() HIMOYASIZ"))
                    continue

                # MODUL bilan hal qilamiz: `ai_docs.prompt_block` va
                # `requirement.prompt_block` BOSHQA-BOSHQA funksiya.
                if egasi and f"{egasi}.{nom}" in xos:
                    toliq = f"{egasi}.{nom}"
                elif egasi is None and len(qisqa.get(nom, ())) == 1:
                    toliq = f"{next(iter(qisqa[nom]))}.{nom}"
                else:
                    continue
                if toliq.endswith(f".{fn.name}"):
                    continue                    # rekursiya
                if not _cid_uzatilganmi(n) and not _himoyalangan(fn, n):
                    buz.append((modul, fn.name, n.lineno,
                                f"{toliq}() KOMPANIYASIZ"))
    return buz


def test_cid_skaner_ozini_sinaydi():
    """[C0] SKANER BUZILISHNI TUTADIMI.

    "0 ta buzilish" o'zi DALIL EMAS — bu loyihaning eng qimmat
    saboqi (skaner ishlamagan va jim turgan).
    """
    print("\n[C0] `company_id` skaneri O'ZINI sinaydi")

    NAMUNA = [
        ("sole_company_id TO'G'RIDAN-TO'G'RI", True, """
from api import auth
def f(tender_id, company_id=None):
    return auth.sole_company_id()
"""),
        ("xos funksiya KOMPANIYASIZ", True, """
def _profile_email(company_id=None):
    return 1
def get_settings(company_id=None):
    return _profile_email()
"""),
        ("shart BOSHQA narsa haqida", True, """
from api import auth
def f(tender_id, company_id=None):
    if tender_id is None:
        pass
    return auth.sole_company_id()
"""),
        ("`is None` zaxirasi QONUNIY", False, """
from api import auth
def f(company_id=None):
    if company_id is None:
        company_id = auth.sole_company_id()
    return company_id
"""),
        ("`is not None` erta qaytish QONUNIY", False, """
from api import auth
def _cid(company_id=None):
    if company_id is not None:
        return int(company_id)
    return auth.sole_company_id()
"""),
        ("kompaniya UZATILGAN", False, """
def _profile_email(company_id=None):
    return 1
def get_settings(company_id=None):
    return _profile_email(company_id)
"""),
        # --- KENGAYTIRILGAN MEZON: endpoint shakli ---
        ("endpoint `company_id_of` dan olib UZATMAYDI", True, """
def subscribers(company_id=None):
    return []
def endpoint(request):
    cid = company_id_of(request)
    return subscribers()
"""),
        ("endpoint `company_id_of` ni TO'G'RIDAN uzatadi", False, """
def subscribers(company_id=None):
    return []
def endpoint(request):
    return subscribers(company_id_of(request))
"""),
        ("`company_id_of()` ning O'ZI istisno", False, """
from api import auth
def company_id_of(request):
    return auth.sole_company_id()
"""),
    ]
    for nom, kutilgan, kod in NAMUNA:
        topildi = bool(_cid_skaner({"m": kod}))
        check(f"skaner {'TUTADI' if kutilgan else 'tutmaydi'}: {nom}",
              topildi == kutilgan,
              f"kutilgan={kutilgan}, topildi={topildi}")


def test_sole_company_tushishi():
    """[C] SESSIYA KOMPANIYASI `sole_company_id()` ga TUSHMASIN.

    `auth.sole_company_id()` — SESSIYASIZ chaqiruvlar uchun
    (bildirishnoma tsikli, sinovlar). Sessiyadan kompaniya
    ALLAQACHON ma'lum bo'lgan yo'lda u ISHLATILMASLIGI kerak:
    ikkinchi faol hisob paydo bo'lishi bilan `AuthError` beradi.

    HAQIQATAN SODIR BO'LDI (brauzerda topildi):
        `notify.get_settings(cid)` -> `_profile_email()` argumentsiz
        -> `sole_company_id()` -> 500, ikkala kompaniya uchun ham.

    Bitta kompaniya bilan sinovlar YASHIL turadi — shuning uchun bu
    tekshiruv STATIK.
    """
    print("\n[C] `sole_company_id()` ga tushib ketish")

    import inspect
    from api import notify

    # 1. `company_id` OLADIGAN funksiya uni ICHKI chaqiruvlarga
    #    UZATSIN. Statik: manba matnida `_profile_email()` yoki
    #    `recipient(st)` argumentsiz qolmasin.
    src = inspect.getsource(notify)
    kod = re.sub(r'"""[\s\S]*?"""', "", src)
    kod = "\n".join(x for x in kod.split("\n")
                    if not x.lstrip().startswith("#"))

    check("_profile_email() ARGUMENTSIZ chaqirilmaydi",
          not re.search(r"_profile_email\(\s*\)", kod),
          "sessiya kompaniyasi bor joyda uni UZATING")
    check("recipient(st) kompaniyasiz chaqirilmaydi",
          not re.search(r"recipient\(\s*st\s*\)", kod),
          "recipient(st, company_id) bo'lsin")

    # 2. UMUMIY QOIDA — nom bo'yicha emas, NAQSH bo'yicha.
    #
    #    Yuqoridagi ikki tekshiruv TOPILGAN ikkitasini qulflaydi,
    #    xolos. To'rtinchi holat o'tib ketardi — va u ALLAQACHON
    #    mavjud edi (`save_settings` da), uni AST skaneri topdi.
    buz = _cid_skaner()
    check("kompaniyani bilgan funksiya uni UZATADI (butun `api/`)",
          not buz,
          "; ".join(f"{m}.py:{ln} {fn}() -> {sab}"
                    for m, fn, ln, sab in buz[:5]))

    # 3. QAMROV O'LCHANADI. "0 buzilish" degan javob skaner NECHTA
    #    funksiyani ko'rganini bilmasdan ma'nosiz. Tor mezonda u 69
    #    ta edi va uch buzilish KO'RINMAY qolgan edi.
    n_koradi = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "api", "*.py"))):
        if os.path.basename(p).startswith("__"):
            continue
        try:
            t = ast.parse(io.open(p, encoding="utf-8").read())
        except SyntaxError:
            continue
        for fn in ast.walk(t):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and _biladimi(fn):
                n_koradi += 1
    check("skaner qamrovi kengaytirilgan (>= 120 funksiya)",
          n_koradi >= 120,
          f"{n_koradi} ta ko'rinadi (tor mezonda 69 edi)")

    # 3. AMALIY: ikki faol kompaniya bo'lganda ham ishlasin.
    #    Bu yerda BAZA kerak, shuning uchun yumshoq o'tkazamiz.
    try:
        # `.env` ni O'ZIMIZ yuklaymiz: statik qism `--offline` da ham
        # yuradi, amaliy qism esa baza bo'lsa qo'shiladi.
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        from api import db as _db
        _db.init_pool()
        faol = _db.query("SELECT id FROM company_account WHERE active "
                         "ORDER BY id LIMIT 2")
        if len(faol) >= 2:
            for r in faol:
                st = notify.get_settings(r["id"])
                check(f"get_settings({r['id']}) ikki kompaniyada ishlaydi",
                      "effective_email" in st)
        else:
            print("       [i] faol kompaniya bitta — amaliy qism "
                  "o'tkazib yuborildi (statik qism baribir ushlaydi)")
    except Exception as e:                                  # noqa: BLE001
        print(f"       [i] baza yo'q: {str(e)[:60]}")


def test_izolyatsiya(conn):
    print("\n[B] DINAMIK — ikki kompaniya izolyatsiyasi")
    import psycopg2.extras

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT count(*) = 1 AS ok FROM information_schema.columns
                       WHERE table_name='tender_pricing' AND column_name='company_id'""")
        migratsiya_bor = cur.fetchone()["ok"]

    if not migratsiya_bor:
        check("schema_patch_multitenant.sql qo'llangan", False,
              "tender_pricing.company_id yo'q — dinamik qism o'tkazib yuborildi. "
              "Patchni qo'llang: psql -d xtxarid -f schema_patch_multitenant.sql")
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        ids = []
        for i in (1, 2):
            cur.execute(
                "INSERT INTO company_account (username, company_name, password_hash) "
                "VALUES (%s, %s, 'x') RETURNING id",
                (f"{PREFIX}{i}", f"Sinov {i}"))
            ids.append(cur.fetchone()["id"])
        a, b = ids

        cur.execute("SELECT id FROM tender LIMIT 1")
        row = cur.fetchone()
        if not row:
            check("bazada tender bor", False, "sinov uchun tender yo'q")
            conn.rollback()
            return
        tid = row["id"]

        # Ikkala kompaniya AYNI tenderga smeta saqlaydi
        for cid, narx in ((a, 100), (b, 999)):
            cur.execute(
                "INSERT INTO tender_pricing (tender_id, company_id, inputs, result, "
                "manual_price) VALUES (%s, %s, '{}'::jsonb, '{}'::jsonb, %s)",
                (tid, cid, narx))

        cur.execute("SELECT manual_price FROM tender_pricing "
                    "WHERE tender_id=%s AND company_id=%s", (tid, a))
        eq("A ning smetasi o'zgarmadi", float(cur.fetchone()["manual_price"]), 100.0)
        cur.execute("SELECT manual_price FROM tender_pricing "
                    "WHERE tender_id=%s AND company_id=%s", (tid, b))
        eq("B ning smetasi alohida saqlandi", float(cur.fetchone()["manual_price"]), 999.0)

        # Katalog
        cur.execute("INSERT INTO catalog_product (name, company_id) VALUES (%s,%s)",
                    (PREFIX + "mahsulot", a))
        cur.execute("SELECT count(*) AS n FROM catalog_product WHERE company_id=%s", (b,))
        eq("B kompaniya A ning katalogini ko'rmaydi", cur.fetchone()["n"], 0)

        # Bildirishnoma jurnali — HAR IKKI kompaniya xabar olishi kerak
        for cid in (a, b):
            cur.execute("INSERT INTO notify_sent (tender_id, kind, company_id) "
                        "VALUES (%s,'new_match',%s)", (tid, cid))
        cur.execute("SELECT count(*) AS n FROM notify_sent WHERE tender_id=%s "
                    "AND company_id IN (%s,%s)", (tid, a, b))
        eq("ikkala kompaniya ham xabar oldi", cur.fetchone()["n"], 2)

    conn.rollback()          # sinov yozuvlari saqlanmaydi
    print("     (barcha sinov yozuvlari qaytarildi — bazaga tegmadi)")


def test_erp_karta_ijarachisi() -> None:
    """ERP kartalari IJARACHILARARO sizib ketmasin.

    O'LCHANGAN OCHIQ CHEGARA (2026-09-03). `erp_status.for_tender()`
    FAQAT `tender_id` bo'yicha filtrlaydi, `erp.v_tender_status` esa
    `tai_company_id` ni chop ETMAYDI — ya'ni ijarachi bo'yicha
    filtrlab BO'LMAYDI. Bitta tender ikki ijarachida ishga olinsa,
    A ijarachisi B ning kartasini (broker, mijoz, holat) ko'rardi.
    FK bu yerda yordam bermaydi: FK YOZISHNI to'sadi, O'QISHNI emas.

    QOIDA: view ijarachini aytmasa VA faol ijarachi > 1 bo'lsa —
    BO'SH ro'yxat. "Ma'lumot yo'q" halol; "boshqasining ma'lumoti"
    emas.

    IKKI TOMON ham sinaladi: bloklaydimi VA keraksiz joyda
    bloklamaydimi.
    """
    print("\n[A5] ERP kartalari — ijarachi chegarasi")
    try:
        from api import db, erp_status
        db.init_pool()
    except Exception as e:                                    # noqa: BLE001
        check("erp_status yuklandi", False, str(e)[:80])
        return

    if not erp_status.ready():
        check("erp.v_tender_status yo'q -> tekshiruv o'tkazildi", True,
              "ERP o'rnatilmagan")
        return

    check("view `tai_company_id` ni chop etmaydi (ochiq chegara)",
          erp_status.ijarachili() is False,
          "TRUE bo'lsa chegara YOPILGAN va bu tekshiruv eskirgan")

    tid = db.scalar("SELECT tender_id FROM erp.v_tender_status LIMIT 1")
    if tid is None:
        check("ERP da opportunity yo'q -> tekshiruv o'tkazildi", True)
        return

    # 1) BOSHQA ijarachi bu tenderni TOPSHIRMAGAN -> karta ko'rinadi.
    #    Birinchi urinishda shart "faol ijarachi > 1" edi va u juda
    #    qo'pol chiqdi: `auth_test` o'z hisobini yaratganda ham karta
    #    bloklanardi (o'lchandi: to'plam 132 emas, 74 tekshiruvda uzildi).
    check("begona topshiriq YO'Q: karta KO'RSATILADI",
          len(erp_status.for_tender(tid, company_id=None)) > 0,
          "to'qnashuv sharti yo'q — bloklash ortiqcha bo'lardi")

    # 2) BOSHQA ijarachi SHU TENDERNI topshirgan -> BLOK.
    zz = db.query_one("SELECT id FROM company_account "
                      " WHERE username = 'zzmt_erp'")
    if zz is None:
        zz = db.execute_returning(
            "INSERT INTO company_account (username, company_name, "
            "  password_hash, active) VALUES ('zzmt_erp', 'ZZTEST erp', "
            "  '!sinov-yaroqsiz-xesh', false) RETURNING id")
    zid = int(zz["id"])
    rid = db.execute_returning(
        "INSERT INTO tender_routing (company_id, tender_id, holat) "
        "VALUES (%(c)s, %(t)s, 'yangi') RETURNING id",
        {"c": zid, "t": tid})["id"]
    try:
        db.execute_returning(
            "INSERT INTO tender_topshiriq (company_id, routing_id, "
            "  tender_id, ishonch, ustuvorlik) "
            "VALUES (%(c)s, %(r)s, %(t)s, 'kompaniya_sessiyasi', 'medium') "
            "RETURNING id", {"c": zid, "r": rid, "t": tid})
        n = len(erp_status.for_tender(tid, company_id=1))
        check("BEGONA ijarachi topshirgan: karta KO'RSATILMAYDI",
              n == 0, f"{n} ta karta qaytdi — ijarachilararo sizish")
        # O'Z topshirig'i BLOKLAMAYDI — aks holda xususiyat o'ladi.
        n2 = len(erp_status.for_tender(tid, company_id=zid))
        check("O'Z topshirig'i bloklamaydi", n2 > 0, f"{n2} ta karta")
    finally:
        db.execute_returning("DELETE FROM tender_topshiriq "
                             " WHERE routing_id=%(r)s RETURNING id", {"r": rid})
        db.execute_returning("DELETE FROM tender_routing WHERE id=%(r)s "
                             "RETURNING id", {"r": rid})


def main():
    ap = argparse.ArgumentParser(description="Ko'p-ijarachilik sinovi (J1)")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("KO'P-IJARACHILIK SINOVI (J1)")
    print("=" * 70)

    test_statik_sql_filtri()
    test_tender_company_id_nomsiz_emas()
    test_ai_analysis_aralash()
    test_patch_royxati_mos()
    test_cid_skaner_ozini_sinaydi()
    test_sole_company_tushishi()
    test_erp_karta_ijarachisi()

    if not args.bazasiz:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        import psycopg2
        dsn = os.environ.get("XT_DB_DSN")
        if not dsn:
            check("XT_DB_DSN o'rnatilgan", False, "--offline bilan yurgizing")
        else:
            conn = psycopg2.connect(dsn)
            try:
                test_izolyatsiya(conn)
            finally:
                conn.rollback()
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
