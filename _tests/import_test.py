"""
Sinov — katalog importi (P0-4) va ombor qoldig'i tekshiruvi (P0-6).

Ishga tushirish (loyiha ildizidan):
    .venv/Scripts/python.exe _tests/import_test.py

Serverni ISHGA TUSHIRISH SHART EMAS — modullar va TestClient to'g'ridan-to'g'ri
chaqiriladi. Sinov oxirida bazadagi BARCHA sinov yozuvlari o'chiriladi
(foydalanuvchining haqiqiy mahsulotlariga TEGILMAYDI — sinov nomlari
"ZZTEST " prefiksi bilan yaratiladi).
"""
import io
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# KONSOL KODLASHI — BU SINOV UMUMAN YURMAYDIGAN HOLATDA EDI.
#
# O'lchangan (2026-08-30): `cleanup()` bazadan kelgan mahsulot nomlarini
# chop etayotganda yiqilardi:
#
#     UnicodeEncodeError: 'charmap' codec can't encode character
#     '）' in position 17317: character maps to <undefined>
#
# To'plam BIRORTA tekshiruv natijasini bermasdan o'lardi — ya'ni
# "yiqilgan" emas, "YURMAGAN". Bu yomonroq: 143 ta tekshiruv bor edi
# va ularning hech biri bajarilmasdi, qizil chiroq ham yonmasdi.
#
# NOSOZLIK AYNAN CI SHAROITIDA CHIQADI. Windows'da Python HAQIQIY
# konsolga `WriteConsoleW` bilan yozadi va yiqilmaydi; chiqish QUVUR
# yoki FAYLGA yo'naltirilganda esa `locale.getpreferredencoding()`
# (bu mashinada `cp1251`) ishlatiladi. Shuning uchun odam terminalda
# yurgizganda muammo KO'RINMASDI.
#
# UNICODE CHIQISH OLIB TASHLANMAYDI — kodlash ANIQ belgilanadi:
# mahsulot nomlari uch alifboda keladi va ular chiqishning MAZMUNI.
# Tafsilot: `_tests/konsol.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import konsol                                       # noqa: E402

konsol.sozla()

from dotenv import load_dotenv                       # noqa: E402

load_dotenv(ROOT / ".env")

from api import db, importer, stock                  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
PREFIX = "ZZTEST "          # sinov mahsulotlari shu bilan boshlanadi

#: SINOV TENDERI — haqiqiy manba identifikatorlaridan UZOQ
#: (ular ~11 xonali). Tozalash `_silent_cleanup()` da.
SINOV_TENDER_ID = 9000000000001

# J1.6: katalog KOMPANIYAGA bog'landi. Sinov mavjud faol hisobdan
# foydalanadi — o'zi hisob yaratmaydi (auth sinovi buni alohida qiladi).
TEST_COMPANY_ID = None   # main() da to'ldiriladi

_passed = 0
_failed = []


def check(name, cond, detail=""):
    global _passed
    if cond:
        _passed += 1
        print(f"  OK   {name}")
    else:
        _failed.append(name)
        print(f"  FAIL {name} {detail}")


def eq(name, got, want):
    check(name, got == want, f"-> kutilgan {want!r}, kelgan {got!r}")


# =========================================================================
# 0. Namunaviy fayllar
# =========================================================================
def make_fixtures():
    FIX.mkdir(parents=True, exist_ok=True)
    from openpyxl import Workbook

    # --- (a) TO'G'RI fayl: o'zbekcha sarlavhalar, .xlsx, 1-qatorda izoh ---
    wb = Workbook()
    ws = wb.active
    ws.append(["Mahsulot katalogi — 2026-yil iyul"])          # izoh qatori
    ws.append(["Nomi", "Xususiyatlari", "O‘lchov birligi", "Qoldiq",
               "Tannarx (UZS)", "Sotuv narxi", "Kategoriya"])  # 2-qator sarlavha
    ws.append([PREFIX + "Noutbuk Lenovo V15", "15.6 dyum; 8GB RAM", "dona",
               12, 6500000, 7800000, "elektronika"])
    ws.append([PREFIX + "Ofis stoli", "LDSP; oq", "dona", "1 250", "850 000",
               "1 150 000", ""])
    ws.append([PREFIX + "A4 qog‘oz", "500 varaq", "quti", "12,5", "42000",
               "55000", ""])
    ws.append([None, None, None, None, None, None, None])      # bo'sh qator
    ws.append([PREFIX + "Sichqoncha", "optik; USB", "шт", 200,
               75000, 95000, "elektronika"])
    wb.save(FIX / "katalog_togri.xlsx")

    # --- (b) XATOLI qatorlar (CSV, nuqtali vergul, ruscha sarlavhalar) ---
    # Qator raqamlari (fayldagi HAQIQIY raqam):
    #   1 sarlavha | 2 to'g'ri | 3 nom bo'sh | 4 qoldiq son emas
    #   5 tannarx manfiy | 6 nom takrorlangan (2-qator) | 7 diapazon
    #   8 noto'g'ri valyuta | 9 to'g'ri, noma'lum kategoriya
    (FIX / "katalog_xatoli.csv").write_bytes(
        "\r\n".join([
            "Наименование;Характеристики;Ед. изм.;Остаток;Себестоимость;Валюта;Категория",
            f"{PREFIX}Printer HP;lazerli;шт;5;1200000;UZS;elektronika",
            ";izohsiz;шт;3;100000;UZS;",
            f"{PREFIX}Skaner;A4;шт;ko‘p;900000;UZS;",
            f"{PREFIX}Monitor;24 dyum;шт;7;-50000;UZS;",
            f"{PREFIX}Printer HP;takror;шт;9;1200000;UZS;",
            f"{PREFIX}Kabel;UTP;м;10-15;5000;UZS;",
            f"{PREFIX}Klaviatura;USB;шт;30;150000;so‘m;",
            f"{PREFIX}Flesh 64GB;USB 3.0;шт;44;95000;UZS;yoq-bunday-kategoriya",
        ]).encode("utf-8-sig"))

    # --- (c) NOTO'G'RI FORMAT: .xlsx deb nomlangan, aslida matn ---
    (FIX / "notogri_format.xlsx").write_bytes(b"Bu Excel emas, oddiy matn.\n")

    # --- (d) SARLAVHASIZ: "Nomi" ustuni yo'q ---
    (FIX / "sarlavhasiz.csv").write_bytes(
        "Kod,Summa\r\n1,100\r\n2,200\r\n".encode("utf-8"))

    # --- (e) CP1251 kodlangan CSV (Excel/Windows eksporti) ---
    (FIX / "katalog_cp1251.csv").write_bytes(
        "\r\n".join([
            "Наименование;Ед. изм.;Остаток;Себестоимость",
            f"{PREFIX}Кабель UTP;м;500;5000",
        ]).encode("cp1251"))


# =========================================================================
# 1. Ustun tanish
# =========================================================================
def test_columns():
    print("\n[1] Ustun sarlavhalarini tanish")
    m, _ = importer.detect_columns(
        ["Nomi", "Xususiyatlari", "O‘lchov birligi", "Qoldiq", "Tannarx (UZS)"])
    eq("uz sarlavhalar", sorted(m), ["cost_price", "keywords", "name", "stock_qty", "unit"])

    m, _ = importer.detect_columns(
        ["Наименование", "Характеристики", "Ед. изм.", "Остаток", "Себестоимость"])
    eq("ru sarlavhalar", sorted(m), ["cost_price", "keywords", "name", "stock_qty", "unit"])

    m, _ = importer.detect_columns(
        ["NAME", "features", "Unit", "QTY", "Cost Price", "Price"])
    eq("en sarlavhalar (katta harf)", sorted(m),
       ["cost_price", "keywords", "name", "price", "stock_qty", "unit"])

    m, _ = importer.detect_columns(["Tannarx, so‘m", "Sotuv narxi", "Nomi"])
    check("tannarx != narx", m.get("cost_price") == 0 and m.get("price") == 1,
          f"-> {m}")

    m, u = importer.detect_columns(["Nomi", "Ombor ID", "Qoldiq"])
    eq("tanilmagan ustun ro‘yxatga tushdi", u, ["Ombor ID"])


# =========================================================================
# 2. Son o'qish (import)
# =========================================================================
def test_parse_number():
    print("\n[2] parse_number — import kataklari")
    cases = [
        ("120", Decimal(120)), (12, Decimal(12)), (12.5, Decimal("12.5")),
        ("1 250", Decimal(1250)), ("1 234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")), ("12,5", Decimal("12.5")),
        ("1,234", Decimal(1234)), ("1.234.567", Decimal(1234567)),
        ("120 dona", Decimal(120)), ("", None), ("-", None), (None, None),
        ("нет", None),
    ]
    for raw, want in cases:
        got, err = importer.parse_number(raw)
        eq(f"parse_number({raw!r})", got, want)
        check(f"parse_number({raw!r}) xatosiz", err is None, f"-> {err}")

    for raw in ["ko‘p", "10-15", "2 x 3", "1 23 456", True]:
        got, err = importer.parse_number(raw)
        check(f"parse_number({raw!r}) -> xato", got is None and err, f"-> {got!r}/{err}")


# =========================================================================
# 3. amount_text -> son (P0-6 chekka holatlari)
# =========================================================================
def test_amount_text():
    print("\n[3] parse_amount_text — tender_item.amount_text (MATN)")
    ok_cases = [
        (" 660.00 шт", Decimal("660.00")),
        ("3 000.00 т", Decimal("3000.00")),
        ("3 720 порция", Decimal(3720)),
        ("1 порция", Decimal(1)),
        ("1.00 усл. ед", Decimal("1.00")),
        ("1.00 компл.", Decimal("1.00")),
        ("3482 шт", Decimal(3482)),
        ("150.00 дона", Decimal("150.00")),
        ("1 000 000.50 kg", Decimal("1000000.50")),
        ("12,5 kg", Decimal("12.5")),
    ]
    for raw, want in ok_cases:
        got, note = parse_or_none(raw)
        eq(f"amount({raw!r})", got, want)

    bad_cases = ["", None, "-", "по требованию", "10-15 шт", "2 x 3 шт",
                 "шт 5", "1 23 456 шт"]
    for raw in bad_cases:
        got, note = stock.parse_amount_text(raw)
        check(f"amount({raw!r}) -> noma’lum", got is None and note, f"-> {got!r}")


def parse_or_none(raw):
    v, n = stock.parse_amount_text(raw)
    return v, n


# =========================================================================
# 4. Import: dry-run, xato qatorlar, format xatosi
# =========================================================================
def test_import_dry_run():
    print("\n[4] Import — DRY-RUN (bazaga yozilmaydi)")
    before = db.scalar("SELECT count(*) FROM catalog_product")
    batches_before = db.scalar("SELECT count(*) FROM catalog_import_batch")
    data = (FIX / "katalog_togri.xlsx").read_bytes()
    res = importer.import_catalog(data, "katalog_togri.xlsx", TEST_COMPANY_ID, dry_run=True)

    eq("sarlavha 2-qatorda topildi", res["header_row"], 2)
    eq("qabul qilingan qatorlar", res["rows_ok"], 4)
    eq("xato qatorlar", res["rows_error"], 0)
    eq("prognoz: qo‘shiladi", res["inserted"], 4)
    eq("prognoz: yangilanadi", res["updated"], 0)
    eq("batch yaratilmadi", res["batch_id"], None)
    eq("bazaga yozilmadi", db.scalar("SELECT count(*) FROM catalog_product"), before)
    eq("import partiyasi yozilmadi",
       db.scalar("SELECT count(*) FROM catalog_import_batch"), batches_before)

    p = {r["name"]: r for r in res["preview"]}
    eq("“1 250” -> 1250", p[PREFIX + "Ofis stoli"]["stock_qty"], 1250.0)
    eq("“850 000” -> 850000", p[PREFIX + "Ofis stoli"]["cost_price"], 850000.0)
    eq("“12,5” -> 12.5", p[PREFIX + "A4 qog‘oz"]["stock_qty"], 12.5)
    eq("xususiyatlar ; bo‘yicha bo‘lindi",
       p[PREFIX + "Noutbuk Lenovo V15"]["keywords"], ["15.6 dyum", "8GB RAM"])


def test_import_errors():
    print("\n[5] Import — XATOLAR QATOR BO‘YICHA")
    data = (FIX / "katalog_xatoli.csv").read_bytes()
    res = importer.import_catalog(data, "katalog_xatoli.csv", TEST_COMPANY_ID, dry_run=True)

    eq("qabul qilingan", res["rows_ok"], 2)      # faqat 2- va 9-qatorlar
    eq("xato qatorlar soni", res["rows_error"], 6)
    eq("jami qatorlar", res["rows_total"], 8)

    by_row = {e["row"]: e for e in res["errors"]}
    check("3-qator: nom bo‘sh", 3 in by_row and "nomi bo‘sh" in by_row[3]["message"].lower(),
          f"-> {by_row.get(3)}")
    check("4-qator: qoldiq son emas",
          4 in by_row and by_row[4]["field"] == "stock_qty", f"-> {by_row.get(4)}")
    check("5-qator: manfiy tannarx",
          5 in by_row and by_row[5]["field"] == "cost_price"
          and "manfiy" in by_row[5]["message"], f"-> {by_row.get(5)}")
    check("6-qator: takrorlangan nom",
          6 in by_row and "takror" in by_row[6]["message"].lower(), f"-> {by_row.get(6)}")
    check("7-qator: diapazon",
          7 in by_row and by_row[7]["field"] == "stock_qty", f"-> {by_row.get(7)}")
    check("8-qator: valyuta kodi",
          8 in by_row and by_row[8]["field"] == "currency", f"-> {by_row.get(8)}")
    check("2-qator xatosiz", 2 not in by_row, f"-> {by_row.get(2)}")

    warn_rows = {w["row"] for w in res["warnings"]}
    check("9-qator: noma’lum kategoriya = OGOHLANTIRISH (xato emas)",
          9 in warn_rows and 9 not in by_row, f"-> {res['warnings']}")

    check("xato xabarida ustun nomi bor",
          all(e["column"] for e in res["errors"]), "")
    print("     namuna xato:", by_row[4]["row"], "|", by_row[4]["column"], "|",
          by_row[4]["message"])


def test_format_errors():
    print("\n[6] Import — FORMAT XATOLARI (butun fayl)")
    for fname, hint in [("notogri_format.xlsx", "ochilmadi"),
                        ("sarlavhasiz.csv", "Sarlavha")]:
        data = (FIX / fname).read_bytes()
        try:
            importer.import_catalog(data, fname, TEST_COMPANY_ID, dry_run=True)
            check(f"{fname} -> xato", False, "-> xato chiqmadi")
        except importer.ImportFormatError as e:
            check(f"{fname} -> ImportFormatError", hint.lower() in str(e).lower(), f"-> {e}")

    try:
        importer.import_catalog(b"x", "hisobot.xls", TEST_COMPANY_ID, dry_run=True)
        check(".xls rad etildi", False)
    except importer.ImportFormatError as e:
        # 20-vazifadan keyin foydalanuvchiga ko'rsatiladigan maslahat
        # (".xlsx ga saqlang") TARJIMADA, xato matnida emas — u uch
        # tilli. Shu sababli KOD tekshiriladi.
        check(".xls rad etildi", e.kod == "FILE_FORMAT_UNSUPPORTED",
              f"-> kod={e.kod!r}")


def test_cp1251():
    print("\n[7] Import — CP1251 kodlangan CSV")
    data = (FIX / "katalog_cp1251.csv").read_bytes()
    res = importer.import_catalog(data, "katalog_cp1251.csv", TEST_COMPANY_ID, dry_run=True)
    eq("1 qator o‘qildi", res["rows_ok"], 1)
    eq("kirill buzilmadi", res["preview"][0]["name"], PREFIX + "Кабель UTP")


# =========================================================================
# 8. Haqiqiy yozish + yangilash
# =========================================================================
def test_import_write():
    print("\n[8] Import — HAQIQIY YOZISH va QAYTA IMPORT (yangilash)")
    data = (FIX / "katalog_togri.xlsx").read_bytes()
    res = importer.import_catalog(data, "katalog_togri.xlsx", TEST_COMPANY_ID, dry_run=False)
    eq("qo‘shildi", res["inserted"], 4)
    eq("yangilandi", res["updated"], 0)
    check("batch_id qaytdi", bool(res["batch_id"]), "")

    row = db.query_one(
        "SELECT stock_qty, stock_unit, cost_price, price, keywords, "
        "       stock_updated_at, import_batch_id "
        "FROM catalog_product WHERE name = %(n)s",
        {"n": PREFIX + "Noutbuk Lenovo V15"})
    eq("qoldiq yozildi", float(row["stock_qty"]), 12.0)
    eq("qoldiq birligi", row["stock_unit"], "dona")
    eq("tannarx yozildi", float(row["cost_price"]), 6500000.0)
    eq("sotuv narxi alohida", float(row["price"]), 7800000.0)
    eq("kalit so‘zlar", row["keywords"], ["15.6 dyum", "8GB RAM"])
    check("stock_updated_at to‘ldi", row["stock_updated_at"] is not None, "")
    check("import izi bor", str(row["import_batch_id"]) == res["batch_id"], "")

    # --- Qayta import: qoldiq o'zgargan fayl -> YANGILANISH (dublikat emas) ---
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Nomi", "Qoldiq"])
    ws.append([(PREFIX + "Noutbuk Lenovo V15").upper(), 99])   # KATTA HARF
    buf = io.BytesIO(); wb.save(buf)
    res2 = importer.import_catalog(buf.getvalue(), "qayta.xlsx", TEST_COMPANY_ID, dry_run=False)
    eq("qayta import: yangilandi", res2["updated"], 1)
    eq("qayta import: qo‘shilmadi", res2["inserted"], 0)

    row2 = db.query_one(
        "SELECT name, stock_qty, cost_price, keywords FROM catalog_product "
        "WHERE lower(name) = lower(%(n)s)", {"n": PREFIX + "Noutbuk Lenovo V15"})
    eq("qoldiq yangilandi", float(row2["stock_qty"]), 99.0)
    eq("faylda yo‘q ustun saqlandi (tannarx)", float(row2["cost_price"]), 6500000.0)
    eq("faylda yo‘q ustun saqlandi (kalit so‘z)", row2["keywords"], ["15.6 dyum", "8GB RAM"])
    eq("dublikat yaratilmadi",
       db.scalar("SELECT count(*) FROM catalog_product WHERE lower(name)=lower(%(n)s)",
                 {"n": PREFIX + "Noutbuk Lenovo V15"}), 1)

    eq("partiya yozuvi saqlandi",
       db.scalar("SELECT rows_ok FROM catalog_import_batch WHERE id=%(i)s",
                 {"i": res["batch_id"]}), 4)


# =========================================================================
# 9. P0-6 — qoldiq tekshiruvi (sof mantiq)
# =========================================================================
def test_stock_logic():
    print("\n[9] P0-6 — qoldiq tekshiruvi mantig‘i")
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)

    products = [
        {"id": 1, "name": "Noutbuk", "keywords": [], "unit": "dona",
         "stock_qty": Decimal(50), "stock_unit": "dona", "stock_updated_at": now,
         "cost_price": None, "price": None, "currency": "UZS"},
        {"id": 2, "name": "Printer", "keywords": ["Принтер"], "unit": "dona",
         "stock_qty": Decimal(2), "stock_unit": "шт", "stock_updated_at": now,
         "cost_price": None, "price": None, "currency": "UZS"},
        {"id": 3, "name": "Sement", "keywords": [], "unit": "kg",
         "stock_qty": Decimal(1000), "stock_unit": "кг", "stock_updated_at": now,
         "cost_price": None, "price": None, "currency": "UZS"},
        {"id": 4, "name": "Skaner", "keywords": [], "unit": "dona",
         "stock_qty": None, "stock_unit": None, "stock_updated_at": None,
         "cost_price": None, "price": None, "currency": "UZS"},
    ]
    rows = [
        {"lot_id": 1, "item_id": 1, "name": "Noutbuk 15.6", "unit": "дона",
         "amount_text": "10.00 дона", "spec": None},                 # yetarli
        {"lot_id": 1, "item_id": 2, "name": "Принтер lazerli", "unit": "шт",
         "amount_text": " 5.00 шт", "spec": None},                   # yetishmaydi (2<5)
        {"lot_id": 1, "item_id": 3, "name": "Sement M400", "unit": "т",
         "amount_text": "3.00 т", "spec": None},                     # birlik mos emas
        {"lot_id": 1, "item_id": 4, "name": "Skaner A4", "unit": "шт",
         "amount_text": "2.00 шт", "spec": None},                    # qoldiq yo'q
        {"lot_id": 2, "item_id": 5, "name": "Noutbuk 17", "unit": "дона",
         "amount_text": "по требованию", "spec": None},              # miqdor noma'lum
        {"lot_id": 2, "item_id": 6, "name": "Betonomeshalka", "unit": "шт",
         "amount_text": "1.00 шт", "spec": None},                    # katalogda yo'q
    ]
    res = stock.build_check({"id": 999, "name": "Sinov tenderi"}, rows, products)

    eq("mos pozitsiyalar", res["summary"]["matched"], 5)
    eq("mos kelmagan", res["summary"]["unmatched"], 1)
    eq("yetarli", res["summary"]["ok"], 1)
    eq("yetishmayapti", res["summary"]["short"], 1)
    eq("noma’lum", res["summary"]["unknown"], 3)
    eq("yetishmaydiganlar alohida ro‘yxatda", len(res["shortages"]), 1)
    eq("yetishmayotgan pozitsiya", res["shortages"][0]["name"], "Принтер lazerli")
    eq("yetishmayotgan miqdor", res["shortages"][0]["shortfall_qty"], 3.0)

    by_name = {i["name"]: i for i in res["items"]}
    eq("dona<->дона tenglashdi", by_name["Noutbuk 15.6"]["status"], "yetarli")
    eq("kg<->т farqi -> noma’lum", by_name["Sement M400"]["status"], "nomalum")
    check("birlik farqi izohlangan",
          "birligi mos emas" in (by_name["Sement M400"]["reason"] or ""), "")
    eq("qoldiq kiritilmagan -> noma’lum", by_name["Skaner A4"]["status"], "nomalum")
    eq("miqdor o‘qilmadi -> noma’lum", by_name["Noutbuk 17"]["status"], "nomalum")
    eq("qoldiq yangi -> dastlabki emas", res["preliminary"], False)

    # --- Bitta mahsulot bir necha qatorga: qoldiq TAQSIMLANADI ---
    rows2 = [
        {"lot_id": 1, "item_id": 1, "name": "Noutbuk A", "unit": "dona",
         "amount_text": "30 dona", "spec": None},
        {"lot_id": 1, "item_id": 2, "name": "Noutbuk B", "unit": "dona",
         "amount_text": "30 dona", "spec": None},
    ]
    r2 = stock.build_check({"id": 998, "name": "T2"}, rows2, products[:1])
    eq("1-qator yetarli", r2["items"][0]["status"], "yetarli")
    eq("2-qator yetishmaydi (50-30=20 qoldi)", r2["items"][1]["status"], "yetishmaydi")
    eq("yetishmagan miqdor", r2["items"][1]["shortfall_qty"], 10.0)

    # --- Eskirgan qoldiq -> "dastlabki" ---
    old = [{**products[0], "stock_updated_at": now - timedelta(days=stock.STALE_DAYS + 5)}]
    r3 = stock.build_check({"id": 997, "name": "T3"}, rows2[:1], old)
    eq("eskirgan -> preliminary", r3["preliminary"], True)
    check("eskirgan -> ogohlantirish", "DASTLABKI" in (r3["stock"]["warning"] or ""),
          f"-> {r3['stock']['warning']}")

    # --- Qoldiq umuman yuklanmagan -> "dastlabki" ---
    r4 = stock.build_check({"id": 996, "name": "T4"}, rows[3:4], products)
    eq("yuklanmagan -> preliminary", r4["preliminary"], True)


# =========================================================================
# 10. P0-6 — HAQIQIY tender ustida
# =========================================================================
def test_stock_real_tender():
    print("\n[10] P0-6 — haqiqiy tender (bazadagi ma’lumot)")
    # TENDER SINOVNIKI, ATROFDAGI EMAS.
    #
    # O'LCHANGAN NUQSON (2026-09-09, darvoza): bu yerda
    #
    #     SELECT tender_id FROM tender_item
    #      WHERE name ILIKE '%компьютерная%' LIMIT 1
    #
    # turardi -- `ORDER BY` siz, ya'ni IXTIYORIY qator. Keyin
    # `required_qty` 500.0 deb QAT'IY kutilardi. 500 esa sinov
    # yozilgan kunda tasodifan mos kelgan qatorning xossasi edi.
    #
    # Darvoza nusxasida boshqa qator tanlandi (`amount_text` = "8 …")
    # va TO'RTTA tekshiruv birdan yiqildi: miqdor 8 vs 500, holat
    # "yetarli" vs "yetishmaydi", yetishmagan miqdor None vs 300.
    #
    # TAHLILCHI AYBDOR EMAS: `parse_amount_text` alohida sinaldi --
    # "500 шт"->500, "8 шт"->8, "1 500 шт"->1500, va noaniq matnda
    # ("8 x 500 шт") TAXMIN QILMASDAN rad etadi. 8.0 -- o'sha
    # qatorning TO'G'RI tahlili edi.
    #
    # Endi tender ham, pozitsiya ham SHU SINOVNIKI: 500 talab,
    # 200 qoldiq -> 300 yetishmaydi. Ya'ni tekshiruv atrofdagi
    # ma'lumotga emas, BIZNES QOIDASIGA bog'langan.
    tid = SINOV_TENDER_ID
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tender (id, source_id, source_platform, "
                "  status, close_at, raw_json) "
                "VALUES (%s, %s, 'zztest', 'open', "
                "        now() + interval '7 days', '{}') "
                "ON CONFLICT (id) DO UPDATE SET status='open'",
                (tid, str(tid)))
            cur.execute(
                "INSERT INTO tender_item (tender_id, lot_id, item_id, "
                "  name, unit, amount_text) "
                "VALUES (%s, 1, %s, %s, 'шт', '500.00 шт') "
                "ON CONFLICT DO NOTHING",
                (tid, f"{tid}-1", "Мышь компьютерная"))
        conn.commit()

    # Qoldig'i ATAYIN yetmaydigan sinov mahsuloti
    db.execute_returning(
        "INSERT INTO catalog_product (company_id, name, keywords, unit, "
        "stock_qty, stock_unit, stock_updated_at) "
        "VALUES (%(c)s, %(n)s, %(k)s, 'шт', 200, 'шт', now()) "
        "RETURNING id",
        {"c": TEST_COMPANY_ID, "n": PREFIX + "Sichqoncha ombor", "k": ["Мышь компьютерная"]})

    res = stock.check_tender_stock(int(tid), TEST_COMPANY_ID)
    check("natija qaytdi", res is not None, "")
    eq("manba", res["source"], "tender_item")
    check("pozitsiyalar bor", res["summary"]["positions"] > 0, f"-> {res['summary']}")
    mine = [i for i in res["items"] if i["product"]["name"] == PREFIX + "Sichqoncha ombor"]
    check("sinov mahsuloti mos keldi", len(mine) >= 1, f"-> {res['summary']}")
    if mine:
        it = mine[0]
        eq("so‘ralgan miqdor amount_text dan o‘qildi", it["required_qty"], 500.0)

        # QOLDIQ QAYERDAN KELGANI KUTILGAN NATIJANI O‘ZGARTIRADI.
        # ERP ombori ishga tushgan bo‘lsa (`erp.stock_move` da harakat bor),
        # qoldiqning EGASI — ERP: `erp_stock.apply_to_products()` katalogdagi
        # qiymatni ALMASHTIRADI va ERP da qaydi yo‘q mahsulot `None` bo‘ladi.
        # Bu ataylab: bitta ro‘yxatda "jurnaldan" va "eski Exceldan" kelgan
        # ikki xil haqiqat aralashmasligi kerak (api/erp_stock.py).
        #
        # Sinov ERP sxemasiga YOZMAYDI (u boshqa loyihaniki), shuning uchun
        # bu yerda ikkala holat ham tekshiriladi. Formula mantig‘ining o‘zi
        # [9] bo‘limida `build_check()` ustida deterministik sinaladi.
        src = (res.get("stock") or {}).get("source")
        if src == "erp":
            eq("ERP rejimi: qoldiq noma’lum", it["available_qty"], None)
            eq("ERP rejimi: holat", it["status"], "nomalum")
            check("ERP rejimi: dastlabki deb belgilandi", res["preliminary"] is True,
                  f"-> {res['preliminary']}")
        else:
            eq("ombordagi qoldiq", it["available_qty"], 200.0)
            eq("holat", it["status"], "yetishmaydi")
            eq("yetishmagan miqdor", it["shortfall_qty"], 300.0)
            check("yetishmaganlar ro‘yxatida", any(
                s["item_id"] == it["item_id"] for s in res["shortages"]), "")
        print(f"     namuna: “{it['name']}” — so‘ralgan {it['required_qty']}, "
              f"qoldiq {it['available_qty']}, {it['status_label']} "
              f"(qoldiq manbai: {src})")
    print(f"     xulosa: {res['summary']}, dastlabki={res['preliminary']}")


# =========================================================================
# 11. Endpointlar (docs/integration/import.md dagi kod bilan bir xil)
# =========================================================================
def test_endpoints():
    print("\n[11] Endpointlar — TestClient (uvicorn ISHGA TUSHIRILMAYDI)")
    try:
        from fastapi import FastAPI, File, HTTPException, Query, UploadFile
        from fastapi.responses import Response
        from fastapi.testclient import TestClient
    except ImportError as e:
        print(f"     (o‘tkazib yuborildi: {e})")
        return

    app = FastAPI()

    @app.post("/catalog/import")
    def catalog_import(file: UploadFile = File(...), dry_run: bool = Query(True)):
        data = file.file.read()
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(413, "Fayl 5 MB dan katta.")
        try:
            return importer.import_catalog(data, file.filename or "", TEST_COMPANY_ID, dry_run=dry_run)
        except importer.ImportFormatError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.get("/catalog/import/template")
    def catalog_template(fmt: str = Query("xlsx", pattern="^(xlsx|csv)$")):
        if fmt == "csv":
            return Response(importer.template_csv(), media_type="text/csv")
        return Response(
            importer.template_xlsx(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/tenders/{tender_id}/stock-check")
    def tender_stock_check(tender_id: int):
        res = stock.check_tender_stock(tender_id, TEST_COMPANY_ID)
        if res is None:
            raise HTTPException(404, f"Tender {tender_id} topilmadi.")
        return res

    c = TestClient(app)

    data = (FIX / "katalog_xatoli.csv").read_bytes()
    r = c.post("/catalog/import?dry_run=true",
               files={"file": ("katalog_xatoli.csv", data, "text/csv")})
    eq("POST /catalog/import -> 200", r.status_code, 200)
    eq("dry-run: 2 qabul, 6 xato",
       (r.json()["rows_ok"], r.json()["rows_error"]), (2, 6))

    r = c.post("/catalog/import?dry_run=true",
               files={"file": ("x.xlsx", b"not excel", "application/octet-stream")})
    eq("noto‘g‘ri format -> 422", r.status_code, 422)

    r = c.get("/catalog/import/template")
    eq("shablon .xlsx -> 200", r.status_code, 200)
    check("shablon ZIP (xlsx)", r.content[:2] == b"PK", "")
    back = importer.import_catalog(r.content, "template.xlsx", TEST_COMPANY_ID, dry_run=True)
    eq("shablonning o‘zi xatosiz o‘qiladi", back["rows_error"], 0)
    eq("shablonda 3 namuna qator", back["rows_ok"], 3)

    r = c.get("/catalog/import/template?fmt=csv")
    eq("shablon .csv -> 200", r.status_code, 200)
    eq("csv shablon xatosiz",
       importer.import_catalog(r.content, "t.csv", TEST_COMPANY_ID, dry_run=True)["rows_error"], 0)

    r = c.get("/tenders/999999999/stock-check")
    eq("yo‘q tender -> 404", r.status_code, 404)

    tid = db.scalar("SELECT tender_id FROM tender_item LIMIT 1")
    if tid:
        r = c.get(f"/tenders/{int(tid)}/stock-check")
        eq("GET /tenders/{id}/stock-check -> 200", r.status_code, 200)
        j = r.json()
        check("javobda shortages bor", "shortages" in j and "summary" in j, "")


# =========================================================================
# 12. Tozalash
# =========================================================================
def _silent_cleanup():
    """Sinov yozuvlarini o'chiradi (hisobotsiz)."""
    # DIQQAT: db.query()/scalar() FAQAT O'QISH uchun — ular oxirida rollback
    # qiladi, ya'ni DELETE bekor bo'ladi. Yozish uchun conn + commit kerak.
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM catalog_product WHERE name LIKE %(p)s",
                        {"p": PREFIX + "%"})
            n = cur.rowcount
            # SINOV TENDERI HAM O'CHADI. `tender_item` `ON DELETE CASCADE`
            # bilan bog'langan, ya'ni pozitsiya o'zi ketadi.
            cur.execute("DELETE FROM tender WHERE id = %(t)s",
                        {"t": SINOV_TENDER_ID})
            cur.execute(
                "DELETE FROM catalog_import_batch WHERE filename IN "
                "('katalog_togri.xlsx','katalog_xatoli.csv','qayta.xlsx',"
                " 'katalog_cp1251.csv','template.xlsx','t.csv')")
            b = cur.rowcount
        conn.commit()
    return n, b


def cleanup():
    print("\n[12] Bazani tozalash (sinov yozuvlari)")
    n, b = _silent_cleanup()
    print(f"     o‘chirildi: {n} mahsulot, {b} import partiyasi")

    # FAQAT TEKSHIRUVGA TEGISHLI QATORLAR CHOP ETILADI.
    #
    # Ilgari bu yerda BUTUN katalog chop etilardi:
    #     print(f"bazada qolgan mahsulotlar ({len(left)}):",
    #           [(r["id"], r["name"]) for r in left])
    # Bu 1 797 qator = har yurishda ~75 KB shovqin, va aynan shu
    # qator `UnicodeEncodeError` bilan butun to'plamni o'ldirgan edi.
    #
    # Tekshiruv faqat SINOV prefiksli qatorlar qolganini so'raydi —
    # butun katalogni ko'rsatish unga hech narsa qo'shmaydi, CI
    # jurnalini esa o'qib bo'lmaydigan qiladi.
    qolgan = db.query(
        "SELECT id, name FROM catalog_product "
        "WHERE name LIKE %(p)s ORDER BY id LIMIT 20",
        {"p": PREFIX + "%"})
    jami = db.scalar("SELECT count(*) FROM catalog_product") or 0
    print(f"     katalogda jami: {jami} mahsulot")
    if qolgan:
        print(f"     TOZALANMAGAN sinov qatorlari ({len(qolgan)}):",
              [(r["id"], r["name"]) for r in qolgan])
    check("sinov mahsulotlari qolmadi", not qolgan,
          str([r["name"] for r in qolgan[:5]]))


#: Aynan shu belgilar `import_test` ni o'ldirgan edi (cp1251 da YO'Q):
#:   ）  FULLWIDTH RIGHT PARENTHESIS — katalogdagi mahsulot nomlarida
#:   ҳ  o'zbek kirill "ҳ"
#:   ұ  o'zbek kirill "ұ"
QOTIL_BELGILAR = "）ҳұқўғ№—"


def test_konsol_kodlashi():
    """KODLASH TUZATISHINI REGRESSIYADAN QULFLAYDI.

    Bu sinov IMPORT MANTIQINI tekshirmaydi — u SINOV JABDUQINING
    o'zi ishlashini tekshiradi. Alohida turishi shart: jabduq
    yiqilsa qolgan 143 tekshiruv UMUMAN BAJARILMAYDI va natija
    "yiqildi" emas, "yurmadi" bo'ladi.
    """
    print("\n[0] Konsol kodlashi — jabduq o'zi ishlaydimi")

    check("oqimlar Unicode ni QABUL QILADI", konsol.tekshir(),
          f"stdout.encoding={sys.stdout.encoding}")
    check("stdout UTF-8", (sys.stdout.encoding or "").lower()
          .replace("-", "") in ("utf8", "utf8sig"), str(sys.stdout.encoding))

    # HAQIQIY YOZUV. `encoding` atributiga ishonish yetarli emas —
    # u to'g'ri ko'rinib, yozuv baribir yiqilishi mumkin.
    print(f"     qotil belgilar chop etilmoqda: {QOTIL_BELGILAR}")
    check("qotil belgilar YIQILMASDAN chop etildi", True)

    # ENG MUHIM TEKSHIRUV: BOLA JARAYON, chiqishi QUVURGA,
    # `PYTHONIOENCODING` MAJBURAN cp1251 — ya'ni AYNAN nosozlik
    # sharoiti qayta yaratiladi. `konsol.sozla()` uni yengishi shart.
    kod = (
        "import os, sys\n"
        f"sys.path.insert(0, r{os.path.dirname(os.path.abspath(__file__))!r})\n"
        "import konsol\n"
        "konsol.sozla()\n"
        f"print({QOTIL_BELGILAR!r})\n"
    )
    bola = subprocess.run(
        [sys.executable, "-c", kod],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1251"},
        timeout=60)
    check("cp1251 majburlangan bola jarayon YIQILMADI",
          bola.returncode == 0,
          (bola.stderr or b"").decode("utf-8", "replace")[-200:])
    check("Unicode chiqish YO'QOLMADI (`?` ga almashmadi)",
          QOTIL_BELGILAR.encode("utf-8") in (bola.stdout or b""),
          (bola.stdout or b"")[:80].decode("utf-8", "replace"))

    # NAZORAT: tuzatishsiz o'sha bola HAQIQATAN yiqiladimi.
    # Busiz sinov "hech qachon yiqilmaydigan" bo'lib qolardi va
    # hech narsani isbotlamasdi.
    xom = subprocess.run(
        [sys.executable, "-c", f"print({QOTIL_BELGILAR!r})"],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1251"},
        timeout=60)
    check("tuzatishSIZ o'sha bola YIQILADI (nazorat)",
          xom.returncode != 0
          and b"UnicodeEncodeError" in (xom.stderr or b""),
          f"kod={xom.returncode}")


def main():
    global TEST_COMPANY_ID
    from api import auth

    test_konsol_kodlashi()
    make_fixtures()
    db.init_pool()
    # Pool ko'tarilgandan KEYIN: kompaniya bazadan aniqlanadi.
    TEST_COMPANY_ID = auth.sole_company_id()
    print(f"     (sinov kompaniyasi: id={TEST_COMPANY_ID})")
    # Oldingi yarim qolgan yurishdan qoldiq bo'lsa — tozalab boshlaymiz,
    # aks holda "qo'shildi/yangilandi" hisoblari siljiydi.
    _silent_cleanup()
    try:
        test_columns()
        test_parse_number()
        test_amount_text()
        test_import_dry_run()
        test_import_errors()
        test_format_errors()
        test_cp1251()
        test_import_write()
        test_stock_logic()
        test_stock_real_tender()
        test_endpoints()
    finally:
        try:
            cleanup()
        finally:
            db.close_pool()

    print("\n" + "=" * 62)
    print(f"NATIJA: {_passed} ta tekshiruv o‘tdi, {len(_failed)} ta yiqildi")
    if _failed:
        for f in _failed:
            print("  - " + f)
    print("=" * 62)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
