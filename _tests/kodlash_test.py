#!/usr/bin/env python3
"""
SINOV: KOD-ASOSLI MOSLASHTIRISH (api/kodlash.py)
================================================

Ikki qism:

  A. STATIK / SOF — bazasiz. Sxema matnlari va sof funksiyalar.
     Bu qism CI da doim yuriladi.

  B. DINAMIK — baza kerak. Struktura kafolatlarini HAQIQATAN
     majburlashini tekshiradi (CHECK, FK, ko'rinish).
     `--offline` bilan o'tkazib yuboriladi.

NEGA STRUKTURA SINOVLARI: bu loyihada "tasdiqlanmaganini ishlatmang"
qoidasi IZOH bilan himoya qilinganda buzilgan — `tender_requirement` da
1514 qator `review_status='approved'` bo'lib turibdi va ularni hech kim
ko'rmagan. Shu sababli bu yerda qoida CHECK va VIEW bilan qulflangan, va
quyidagi sinovlar aynan o'sha qulflarni sinaydi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\kodlash_test.py
    .venv\\Scripts\\python.exe _tests\\kodlash_test.py --offline
"""
import argparse
import os
import re
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


_results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, bool(ok)))
    print(f"  {'OK  ' if ok else 'XATO'} {name}" +
          (f"\n       {detail}" if detail and not ok else ""))
    return bool(ok)


def section(t: str) -> None:
    print(f"\n=== {t} ===")


# =====================================================================
# A. STATIK — bazasiz
# =====================================================================
def test_prior():
    """Kategoriya -> NACE bo'limlari (teskari OKED_MAP)."""
    section("A. Kategoriya priori")
    from api import kodlash

    tib = kodlash.divisions_for_category("tibbiyot")
    check("tibbiyot -> 21/32/86/87/88",
          set(tib) == {"21", "32", "86", "87", "88"}, str(tib))

    check("kategoriyasiz -> bo'sh", kodlash.divisions_for_category(None) == [])
    check("noma'lum kategoriya -> bo'sh",
          kodlash.divisions_for_category("yoq-bunday") == [])

    # Parent berilsa ichkilari ham qamralsin: 'transport' -> avto+xizmat...
    tr = kodlash.divisions_for_category("transport")
    check("parent 'transport' ichki bo'limlarni ham oladi",
          "29" in tr and "49" in tr, str(tr))
    # Ichki berilsa ham butun oila (bir xil parent) qamraladi.
    tra = kodlash.divisions_for_category("transport/avto")
    check("'transport/avto' oilasi bir xil", set(tra) == set(tr))


def test_query_matn():
    """So'rov matni nom + kalit so'zlardan quriladi."""
    section("A. So'rov matni")
    from api import kodlash

    q = kodlash._query_text({"name": "dori", "keywords": ["ampula", "tabletka"]})
    check("nom va kalit so'zlar birga", q == "dori, ampula, tabletka", q)
    check("bo'sh mahsulot -> bo'sh", kodlash._query_text({"name": "", "keywords": []}) == "")
    # Bo'sh kalit so'z qatorga qo'shilmasin (", , " hosil bo'lmasin).
    q2 = kodlash._query_text({"name": "dori", "keywords": ["", "  "]})
    check("bo'sh kalit so'z tashlanadi", q2 == "dori", q2)


def test_leksik_naqsh():
    """Leksik naqshlar IKKI alifboda quriladi."""
    section("A. Leksik naqshlar")
    from api import kodlash

    n = kodlash._lexical_patterns({"name": "kamera", "keywords": []})
    check("naqsh bor", len(n) > 0, str(n))
    check("kirill varianti ham bor",
          any(any("Ѐ" <= ch <= "ӿ" for ch in v) for v in n), str(n))
    # 1-2 belgili naqsh hamma narsaga mos keladi — foydasiz.
    check("qisqa naqsh tashlanadi", all(len(v) >= 3 for v in n), str(n))


def test_product_matches():
    """Moslik qoidasi: KOD birlamchi, KATEGORIYA moslik EMAS, so'z chegarasi.

    Uchala qoida ham EKRANDA ko'rilgan soxta mosliklardan keyin
    qo'yilgan — har biri aniq holatni qaytaradi.
    """
    section("A. Moslik qoidasi")
    from api import matching

    tender = {"name": "Kompyuter xaridi", "goods_blob": "monoblok",
              "category_codes": ["elektronika"],
              "good_codes": ["26.20.11.000-00001"]}

    # --- KOD birlamchi ---
    p_kod = {"name": "ish stansiyasi", "keywords": [], "codes": ["26.20"]}
    check("kod mos kelsa -> 'kod'",
          matching.product_matches(tender, p_kod) == "kod")

    # --- Kodi BOR mahsulot uchun MATNGA TUSHILMAYDI ---
    # "Bemor monitori" -> "Axborot xavfsizligi monitoringi" aynan shu
    # yo'l bilan chiqqandi.
    p_kod_bosh = {"name": "kompyuter", "keywords": [], "codes": ["99.99"]}
    check("kodi bor, kod mos emas -> matnga TUSHMAYDI",
          matching.product_matches(tender, p_kod_bosh) is None,
          str(matching.product_matches(tender, p_kod_bosh)))

    # --- KATEGORIYA moslik EMAS ---
    p_kat = {"name": "beton", "keywords": [], "codes": [],
             "category_code": "elektronika"}
    check("kategoriya tengligi MOSLIK EMAS",
          matching.product_matches(tender, p_kat) is None,
          str(matching.product_matches(tender, p_kat)))

    # --- NOM: faqat kodsiz mahsulot uchun ---
    p_nom = {"name": "kompyuter", "keywords": [], "codes": []}
    check("kodsiz mahsulot -> nom bo'yicha",
          matching.product_matches(tender, p_nom) == "nom")

    # --- SO'Z CHEGARASI ---
    t_ichki = {"name": "Superkompyuter markazi", "goods_blob": "xizmat",
               "category_codes": [], "good_codes": []}
    check("so'z O'RTASIDAN moslik yo'q ('kompyuter' c 'Superkompyuter')",
          matching.product_matches(t_ichki, p_nom) is None)

    # --- MA'LUM CHEKLOV, yashirilmaydi ---
    # `\b` faqat so'z O'RTASIDAN himoya qiladi. "Столб" (ustun) esa
    # "стол" bilan BOSHLANADI, ya'ni chegara uni ushlamaydi — xuddi
    # "monitor" -> "monitoringi" kabi. O'lchandi: qo'shimcha uzunligi
    # to'g'ri va xato holatlarni ajratmaydi
    #     monitor -> monitoring(+3) XATO, nasos -> насосини(+3) TO'G'RI
    # ya'ni buni matn darajasida hal qilib bo'lmaydi (morfologiya kerak).
    #
    # YUMSHATISH: matn mosligi IKKILAMCHI — u faqat kodi YO'Q mahsulot
    # uchun ishlaydi va 100 emas, 60 ball beradi. Sinov shu HOLATNI
    # qulflaydi: xatti-harakat o'zgarsa (yaxshi tomonga ham) bu yerda
    # ko'rinadi.
    t_stolb = {"name": "Столб освещения", "goods_blob": "",
               "category_codes": [], "good_codes": []}
    p_stol = {"name": "stol", "keywords": [], "codes": []}
    check("MA'LUM CHEKLOV: 'stol' hali 'столб' ni topadi (prefiks)",
          matching.product_matches(t_stolb, p_stol) == "nom",
          "xatti-harakat o'zgargan bo'lsa izohni yangilang")
    check("...lekin kodi BOR mahsulotda bu yo'l umuman ochilmaydi",
          matching.product_matches(t_stolb,
                                   dict(p_stol, codes=["31.01"])) is None)

    # Qo'shimchali TO'G'RI moslik saqlanadi (so'z BOSHIDAN).
    t_nasos = {"name": "Насосы для воды", "goods_blob": "",
               "category_codes": [], "good_codes": []}
    p_nasos = {"name": "nasos", "keywords": [], "codes": []}
    check("'nasos' -> 'Насосы' (qo'shimcha bilan) TOPILADI",
          matching.product_matches(t_nasos, p_nasos) == "nom")


def test_atribut():
    """Pozitsiyaga mahsulot biriktirish — TRANSLIT bilan, signalsiz TAXMIN YO'Q."""
    section("A. Atribut o'xshashligi")
    from api import kodlash

    # Xom belgi taqqoslash HAR DOIM 0 beradi (lotin <-> kirill), shuning
    # uchun translit majburiy. Bu tekshiruv shuni qulflaydi.
    s_togri = kodlash._ozgarish("Ofis kreslosi", "Кресло офисное")
    s_xato = kodlash._ozgarish("Metall javon", "Кресло офисное")
    check("translit bilan to'g'ri mahsulot yuqori",
          s_togri > s_xato and s_togri > kodlash.ATRIBUT_CHEGARA,
          f"togri={s_togri:.3f} xato={s_xato:.3f}")

    s_shkaf = kodlash._ozgarish("Tibbiy shkaf", "Шкаф медицинский")
    s_monitor = kodlash._ozgarish("Bemor monitori", "Шкаф медицинский")
    check("'Шкаф медицинский' -> 'Tibbiy shkaf', 'Bemor monitori' EMAS",
          s_shkaf > s_monitor, f"shkaf={s_shkaf:.3f} monitor={s_monitor:.3f}")

    # Chegara shovqin bilan eng zaif to'g'ri moslik ORASIDA bo'lsin.
    check("chegara shovqindan yuqori",
          kodlash.ATRIBUT_CHEGARA > s_monitor,
          f"chegara={kodlash.ATRIBUT_CHEGARA} shovqin={s_monitor:.3f}")
    check("chegara to'g'ri moslikdan past",
          kodlash.ATRIBUT_CHEGARA < min(s_togri, s_shkaf))

    # Umuman bog'liq bo'lmagan juftlik chegaradan past.
    check("bog'liqsiz juftlik chegaradan past",
          kodlash._ozgarish("Tibbiy shkaf", "Трибуна") < kodlash.ATRIBUT_CHEGARA)


def test_sxema_qulflari():
    """Sxema matnida STRUKTURAVIY qulflar bormi.

    Bu izoh emas, fayl matnini o'qiydi: kimdir qulfni olib tashlasa
    sinov yiqiladi.
    """
    section("A. Sxema qulflari")
    p = os.path.join(ROOT, "schema_patch_goodcode.sql")
    sql = open(p, encoding="utf-8").read()

    check("tasdiq ODAMSIZ yozilmaydi (CHECK)",
          "catalog_product_code_tasdiq_odam" in sql
          and "tasdiqlandi IS NULL OR tasdiqlagan IS NOT NULL" in sql)
    check("bir vaqtda tasdiq+rad bo'lmaydi (CHECK)",
          "catalog_product_code_bir_qaror" in sql)
    check("ko'p-ijarachilik kompozit FK bilan",
          "REFERENCES catalog_product (id, company_id)" in sql)
    check("faol ko'rinish tasdiqlanganini FILTRLAYDI",
          re.search(r"CREATE OR REPLACE VIEW v_catalog_code_active.*?"
                    r"WHERE pc\.tasdiqlandi IS NOT NULL", sql, re.S) is not None)
    check("kodsizlar uchun alohida ko'rinish bor",
          "v_catalog_kodsiz" in sql)

    p2 = os.path.join(ROOT, "schema_patch_semantik.sql")
    sql2 = open(p2, encoding="utf-8").read()
    check("markaz sovuq-startdan himoyalangan (n>=50)",
          "embed_centroid_min_source" in sql2 and "n_source >= 50" in sql2)
    check("markazlangan vektor markazni YOZIB BORADI",
          "tender_embedding_c_needs_centroid" in sql2)
    check("eskirganlik ko'rinishi bor", "v_centroid_stale" in sql2)


def test_qaror_sxema_qulflari():
    """`kod_qaror` sxemasining qulflari — MATN bo'yicha.

    Bu sinov shu sababli bor: birinchi patch (`schema_patch_kod_qaror.sql`)
    hech qanday sinovda tekshirilmasdi. Uni ochib qo'yish, CHECK ni
    olib tashlash yoki ko'rinishni buzish HECH QANDAY sinovni
    yiqitmasdi — 67/67 yashil qolardi.

    NASR EMAS, KOD skanerlanadi: izoh qatorlari olib tashlanadi, aks
    holda skaner o'z tushuntirishini "qulf bor" deb o'qirdi.
    """
    section("A. kod_qaror sxema qulflari")

    def kodsiz(matn: str) -> str:
        """`--` izohlarini olib tashlaydi (satr ichidagisini ham)."""
        return "\n".join(q.split("--")[0] for q in matn.splitlines())

    p1 = os.path.join(ROOT, "schema_patch_kod_qaror.sql")
    p2 = os.path.join(ROOT, "schema_patch_kod_qaror_2.sql")
    check("ikkinchi patch mavjud", os.path.exists(p2), p2)
    if not os.path.exists(p2):
        return
    s1 = kodsiz(open(p1, encoding="utf-8").read())
    s2 = kodsiz(open(p2, encoding="utf-8").read())

    # --- Birinchi patchning qulflari joyida ---
    check("qaror ODAMSIZ yozilmaydi (CHECK)",
          "kod_qaror_odam" in s1 and "kim IS NOT NULL" in s1)
    check("'kod' qarorida kod BOR, boshqasida YO'Q (CHECK)",
          "kod_qaror_kod_mos" in s1
          and "(qaror = 'kod') = (code IS NOT NULL)" in s1)
    check("bir atamaga BITTA ochiq qator (qisman UNIQUE indeks)",
          "kod_qaror_ochiq_uq" in s1 and "WHERE qaror IS NULL" in s1)

    # --- Ikkinchi patch: "o'lchanmadi" != "0 soniya" ---
    check("ochilgan_at NULL bo'la oladi (o'lchanmadi ifodalanadi)",
          "ALTER COLUMN ochilgan_at DROP NOT NULL" in s2)
    check("DEFAULT now() olib tashlangan",
          "ALTER COLUMN ochilgan_at DROP DEFAULT" in s2,
          "default qolsa har INSERT jimgina 0 soniya yozardi")
    check("ochiq qatorda soat MAJBURIY (CHECK)", "kod_qaror_ochiq_soat" in s2)
    check("qaror ochilishdan oldin bo'lmaydi (CHECK)",
          "kod_qaror_vaqt_tartibi" in s2)
    # O'rtacha O'LCHANMAGAN qatorni nol deb sanamasin.
    check("ortacha_sek FAQAT o'lchangan qatorlar bo'yicha",
          re.search(r"avg\(extract.*?FILTER \(WHERE qaror IS NOT NULL\s*"
                    r"AND ochilgan_at IS NOT NULL\)", s2, re.S) is not None,
          "filtrsiz bo'lsa o'lchanmagan qator o'rtachani nolga tortadi")
    check("o'lchanmaganlar alohida sanaladi", "AS olchovsiz" in s2)
    check("takror bosish ajratiladi (atama_soni)",
          "AS atama_soni" in s2 and "count(DISTINCT kalit)" in s2)


def test_navbat_qaror_filtri_kodda():
    """`navbat()` `kod_qaror` ni O'QIYDI — statik tekshiruv.

    Kimdir filtrni olib tashlasa navbat yana tugamas holga qaytardi.
    Dinamik sinov bazani talab qiladi, bu esa CI da doim yuriladi.
    """
    section("A. Navbat qaror filtri")
    import inspect
    from api import kodlash

    src = inspect.getsource(kodlash.navbat)
    # IZOHLAR OLIB TASHLANADI: aks holda skaner o'z tushuntirishidagi
    # "kod_qaror" so'zini topib, filtr bor deb yolg'on gapirardi.
    kod = "\n".join(q.split("#")[0] for q in src.splitlines())
    check("navbat() kod_qaror dan o'qiydi", "kod_qaror" in kod,
          "izohsiz manbada topilmadi")
    check("faqat QAROR QILINGANLARI (qaror IS NOT NULL)",
          "qaror IS NOT NULL" in kod)
    check("company_id bo'yicha filtrlaydi (ko'p-ijarachilik)",
          "company_id = %(c)s" in kod)


def test_moslik_sql_faol_korinishdan():
    """Moslashtirish SQL i FAQAT `v_catalog_code_active` dan o'qiydi.

    Agar kimdir uni `catalog_product_code` ga o'zgartirsa,
    TASDIQLANMAGAN takliflar jimgina moslikka aylanadi.
    """
    section("A. Moslik manbai")
    from api import kodlash

    sql = kodlash.SQL_MOSLIK
    check("v_catalog_code_active dan o'qiydi", "v_catalog_code_active" in sql)
    check("xom jadvaldan O'QIMAYDI",
          "catalog_product_code" not in sql.replace("v_catalog_code_active", ""))
    check("company_id bo'yicha filtrlaydi", "company_id = %(company_id)s" in sql)


def test_semantik_hublik():
    """Semantik shox XOM kosinusni emas, hublik tuzatmasini ishlatadi."""
    section("A. Hublik tuzatmasi")
    from api import kodlash

    check("hub_bias ayiriladi", "hub_bias" in kodlash.SQL_SEM)
    check("markazlangan ustun ishlatiladi", "embedding_c" in kodlash.SQL_SEM)
    check("xom `embedding` ishlatilmaydi",
          not re.search(r"\bge\.embedding\b(?!_c)", kodlash.SQL_SEM))
    # Prior — RANG emas, A'ZOLIK. Rang bo'lsa hub kodlar yana ko'tariladi.
    check("prior ROW_NUMBER ishlatmaydi (a'zolik)",
          "ROW_NUMBER" not in kodlash.SQL_PRIOR)
    check("prior bonusi bitta 1-o'ringa teng",
          abs(kodlash.PRIOR_BONUS - 1.0 / (kodlash.RRF_K + 1)) < 1e-12)
    # Hajm hech qachon hal qiluvchi bo'lmasin.
    check("hajm koeffitsienti RRF o'rnidan KICHIK",
          50 * kodlash.VOLUME_EPS < 1.0 / (kodlash.RRF_K + 1))


# =====================================================================
# B. DINAMIK — baza kerak
# =====================================================================
def test_baza_qulflari(cid: int):
    """CHECK/FK/VIEW HAQIQATAN majburlaydimi."""
    section("B. Baza qulflari")
    import psycopg2
    from api import db

    # --- Tasdiq odamsiz yozilmaydi ---
    prod = db.query_one(
        "SELECT id FROM catalog_product WHERE company_id=%(c)s LIMIT 1", {"c": cid})
    if not prod:
        check("sinov mahsuloti bor", False, "katalog bo'sh")
        return
    kod = db.query_one("SELECT code FROM dim_good_code WHERE level=5 LIMIT 1")
    if not kod:
        check("lug'at to'ldirilgan", False, "dim_good_code bo'sh")
        return

    db.execute_returning(
        "INSERT INTO catalog_product_code (product_id, company_id, code, manba) "
        "VALUES (%(p)s,%(c)s,%(k)s,'taklif') "
        "ON CONFLICT (product_id, code) DO NOTHING RETURNING product_id",
        {"p": prod["id"], "c": cid, "k": kod["code"]})

    xato = None
    try:
        db.execute_returning(
            "UPDATE catalog_product_code SET tasdiqlandi=now(), tasdiqlagan=NULL "
            "WHERE product_id=%(p)s AND code=%(k)s RETURNING product_id",
            {"p": prod["id"], "k": kod["code"]})
    except Exception as e:                                   # noqa: BLE001
        xato = str(e)
    # IKKI QO'RIQCHI bor va HAR IKKALASI ham shu yozuvni rad etadi:
    #   tasdiq_odam       — `tasdiqlagan` bo'sh
    #   tasdiq_manba_chk  — `tasdiq_ishonch` bo'sh (2026-09-02)
    # Qaysi biri birinchi ishlashi baza ixtiyorida, shuning uchun
    # NOMI emas, RAD ETILGANI tekshiriladi — aks holda ikkinchi
    # qo'riqcha qo'shilganda sinov "himoya yo'qoldi" deb yolg'on
    # signal berardi.
    check("tasdiq ODAMSIZ yozilmadi (CHECK ushladi)",
          xato is not None
          and ("tasdiq_odam" in xato or "tasdiq_manba_chk" in xato),
          xato or "yozildi!")

    # --- MANBASIZ tasdiq (2026-09-02) ---
    # O'LCHANGAN NUQSON: bazada 1 048 ta "inson tasdig'i" bor edi va
    # hammasi mashina yozgan (16 ta turli sekundda, ~34 va ~290
    # qator/sek). Yagona shart `tasdiqlagan` bo'sh bo'lmasligi edi —
    # 'tizim:auto' esa bo'sh emas.
    xato_m = None
    try:
        db.execute_returning(
            "UPDATE catalog_product_code "
            "SET tasdiqlandi=now(), tasdiqlagan='tizim:auto' "
            "WHERE product_id=%(p)s AND code=%(k)s RETURNING product_id",
            {"p": prod["id"], "k": kod["code"]})
    except Exception as e:                                   # noqa: BLE001
        xato_m = str(e)
    check("MANBASIZ tasdiq yozilmadi (bo'sh bo'lmagan satr != odam)",
          xato_m is not None and "tasdiq_manba_chk" in (xato_m or ""),
          xato_m or "yozildi!")

    # --- INSON ishonchi, lekin AKTORSIZ ---
    xato_a = None
    try:
        db.execute_returning(
            "UPDATE catalog_product_code SET tasdiqlandi=now(), "
            "tasdiqlagan='x', tasdiq_ishonch='aktor_elon' "
            "WHERE product_id=%(p)s AND code=%(k)s RETURNING product_id",
            {"p": prod["id"], "k": kod["code"]})
    except Exception as e:                                   # noqa: BLE001
        xato_a = str(e)
    check("AKTORSIZ inson tasdig'i yozilmadi",
          xato_a is not None and "aktor_izchil" in (xato_a or ""),
          xato_a or "yozildi!")

    # --- Begona kompaniya bog'lay olmaydi ---
    xato2 = None
    try:
        db.execute_returning(
            "INSERT INTO catalog_product_code (product_id, company_id, code, manba) "
            "VALUES (%(p)s, %(c)s, %(k)s, 'qol') RETURNING product_id",
            {"p": prod["id"], "c": cid + 9999, "k": kod["code"]})
    except Exception as e:                                   # noqa: BLE001
        xato2 = str(e)
    check("begona company_id FK bilan rad etildi", xato2 is not None,
          xato2 or "yozildi!")

    # --- Faol ko'rinish tasdiqlanmaganini KO'RSATMAYDI ---
    n = db.scalar(
        "SELECT count(*) FROM v_catalog_code_active v "
        "JOIN catalog_product_code pc USING (product_id, code) "
        "WHERE pc.tasdiqlandi IS NULL")
    check("faol ko'rinishda tasdiqlanmagan YO'Q", n == 0, f"topildi {n}")

    # Tozalash
    db.execute_returning(
        "DELETE FROM catalog_product_code WHERE product_id=%(p)s AND code=%(k)s "
        "AND tasdiqlandi IS NULL RETURNING product_id",
        {"p": prod["id"], "k": kod["code"]})


def test_markaz_va_lugat():
    """Markaz va lug'at holati — eskirgan bo'lmasin."""
    section("B. Markaz va lug'at holati")
    from api import db

    st = db.query_one("SELECT * FROM v_centroid_stale")
    if st:
        check("markazlanmagan vektor yo'q", (st.get("markazlanmagan") or 0) == 0,
              str(st))
        check("eskirgan markaz yo'q", (st.get("eskirgan") or 0) == 0, str(st))

    hb = db.query_one("SELECT * FROM v_hub_stale")
    if hb:
        check("hublik tuzatmasi hisoblangan", (hb.get("biassiz") or 0) == 0, str(hb))
        check("hublik tuzatmasi eskirmagan", (hb.get("eskirgan") or 0) == 0, str(hb))

    lv = {r["level"]: r["n"] for r in db.query(
        "SELECT level, count(*) AS n FROM dim_good_code GROUP BY level")}
    check("lug'at uch darajada", set(lv) == {2, 5, 8}, str(lv))
    check("5-daraja bo'sh emas", (lv.get(5) or 0) > 50, str(lv))

    # Har kodning uzunligi darajasiga TENG (CHECK buni majburlaydi, lekin
    # ma'lumot eski patchdan qolgan bo'lishi mumkin).
    yomon = db.scalar("SELECT count(*) FROM dim_good_code WHERE length(code) <> level")
    check("kod uzunligi darajaga teng", yomon == 0, f"buzilgan {yomon}")


def test_moslik_tasdiqsiz_ishlamaydi(cid: int):
    """TASDIQLANMAGAN taklif moslikka AYLANMAYDI — asosiy kafolat."""
    section("B. Tasdiqsiz moslik yo'q")
    from api import db, kodlash

    oldin = len(kodlash.moslik(cid, limit=1000))

    prod = db.query_one(
        "SELECT id FROM catalog_product WHERE company_id=%(c)s "
        "ORDER BY id DESC LIMIT 1", {"c": cid})
    # Ko'p ochiq tenderli kod tanlaymiz: agar tasdiqsiz ham ishlasa,
    # farq ANIQ ko'rinsin.
    kod = db.query_one("SELECT code FROM dim_good_code WHERE level=5 "
                       "ORDER BY n_tender_open DESC LIMIT 1")
    if not (prod and kod):
        check("sinov ma'lumoti bor", False)
        return

    yozildi = kodlash.taklif_yoz(cid, prod["id"], [{"code": kod["code"], "skor": 0.5}])
    keyin = len(kodlash.moslik(cid, limit=1000))
    check("taklif yozilgach moslik O'ZGARMADI", oldin == keyin,
          f"oldin={oldin} keyin={keyin} (kod={kod['code']}, yozildi={yozildi})")

    # Endi tasdiqlaymiz — moslik O'SISHI kerak (aks holda quvur uzilgan).
    kodlash.tasdiqla(cid, prod["id"], kod["code"], kim="kodlash-test",
                     ishonch="servis")
    tasdiqdan = len(kodlash.moslik(cid, limit=1000))
    check("tasdiqdan KEYIN moslik ishladi", tasdiqdan >= keyin,
          f"keyin={keyin} tasdiqdan={tasdiqdan}")

    # Rad etilsa qator QOLADI (takror taklif chiqmasin), lekin moslikdan
    # chiqadi.
    kodlash.rad_et(cid, prod["id"], kod["code"], ishonch="servis")
    raddan = len(kodlash.moslik(cid, limit=1000))
    check("rad etilgach moslikdan chiqdi", raddan <= tasdiqdan,
          f"tasdiqdan={tasdiqdan} raddan={raddan}")
    qator = db.query_one(
        "SELECT rad_etildi FROM catalog_product_code "
        "WHERE product_id=%(p)s AND code=%(k)s", {"p": prod["id"], "k": kod["code"]})
    check("rad etilgan qator O'CHIRILMADI",
          qator is not None and qator.get("rad_etildi") is not None)

    db.execute_returning(
        "DELETE FROM catalog_product_code WHERE product_id=%(p)s AND code=%(k)s "
        "RETURNING product_id", {"p": prod["id"], "k": kod["code"]})


def test_navbat_qoldiqsiz(cid: int):
    """TOIFALASH QOLDIQSIZ — yig'indi JAMIGA teng.

    UMUMIY QOIDA, alohida holat emas. O'lchangan nosozlik: 837 kodsiz
    mahsulotdan 185 tasi na navbatda, na "talabsiz" da ko'rinardi
    (turi 30 belgidan uzun edi). Ular hech qayerda ko'rinmasdi va
    HECH QANDAY XATO CHIQMASDI — bu loyihada shu sinf o'ninchi marta.

    Bitta assert shu sinfni kelajakda ham tutadi.
    """
    section("B. Navbat qoldiqsiz")
    from api import kodlash

    n = kodlash.navbat(cid, limit=5, takliflar_bilan=False)
    check("jami = toifalar yig'indisi",
          n["jami_mahsulot"] == n["toifa_yigindi"],
          f"jami={n['jami_mahsulot']} yig'indi={n['toifa_yigindi']}")
    check("qoldiq toifasi MAVJUD", "turi_aniqmas_jami" in n)
    check("talabsiz toifasi MAVJUD", "talabsiz_jami" in n)
    # Chegaradan tashqaridagilar ham sanaladi — aks holda `limit`
    # o'zgarganda yig'indi buzilardi.
    check("chegaradan tashqaridagilar sanaladi", n["qolgan"] >= 0)


def test_qidiruv_ijarachi(cid: int):
    """QIDIRUV: korpus UMUMIY, mahsulot soni esa IJARACHINIKI.

    Ikkisi ARALASHTIRILMASIN: korpusga filtr qo'yilsa natija bo'shab
    qolardi, mahsulot soniga qo'yilmasa begona katalog ko'rinardi.
    """
    section("B. Qidiruv va ijarachi chegarasi")
    from api import db, kodlash

    r = kodlash.qidir("kabel", limit=5)
    check("korpus natijasi FILTRSIZ keladi", len(r["pozitsiya"]) > 0,
          "korpus umumiy ma'lumot, bo'sh bo'lmasligi kerak")
    check("kalit normallashtirilgan", r["kalit"] == "kabel", r["kalit"])
    # Kirill kirish AYNAN shu natijani bersin — aks holda qidiruv
    # yangi til devorini yaratardi.
    r2 = kodlash.qidir("Кабели", limit=5)
    check("kirill kirish bir xil kalit beradi", r2["kalit"] == r["kalit"],
          f"{r2['kalit']!r} != {r['kalit']!r}")

    # MAHSULOT SONI — begona kompaniyada 0 bo'lsin.
    begona = db.scalar("SELECT COALESCE(max(id), 0) + 1000 "
                       "FROM company_account") or 99999
    n_meniki = db.scalar(
        "SELECT count(*) FROM catalog_product p WHERE p.company_id = %(c)s",
        {"c": begona})
    check("begona kompaniyada mahsulot yo'q", (n_meniki or 0) == 0,
          f"topildi {n_meniki}")

    # NAVBAT begona kompaniyada BO'SH.
    nb = kodlash.navbat(begona, limit=5, takliflar_bilan=False)
    check("begona kompaniya navbati bo'sh",
          nb["jami_mahsulot"] == 0 and not nb["atamalar"],
          str(nb["jami_mahsulot"]))
    # O'z kompaniyasida esa BO'SH EMAS — aks holda yuqoridagi sinov
    # "hamma joyda bo'sh" degan holatni ham o'tkazib yborardi.
    oz = kodlash.navbat(cid, limit=5, takliflar_bilan=False)
    check("o'z kompaniyasida navbat bor", oz["jami_mahsulot"] > 0,
          str(oz["jami_mahsulot"]))


def test_kodsiz_korinadi(cid: int):
    """Kodsiz mahsulot JIMGINA yo'qolmaydi — alohida ro'yxatda ko'rinadi."""
    section("B. Kodsiz mahsulot ko'rinadi")
    from api import kodlash

    h = kodlash.holat(cid)
    kodsiz = kodlash.kodsiz_mahsulotlar(cid)
    check("holat va ro'yxat mos", h["kodsiz"] == len(kodsiz),
          f"holat={h['kodsiz']} ro'yxat={len(kodsiz)}")
    check("qamrov foizi 0..100", h["qamrov_pct"] is None
          or 0 <= h["qamrov_pct"] <= 100, str(h))


def test_qaror_navbatni_kamaytiradi(cid: int):
    """QAROR NAVBATNI KAMAYTIRADI — asosiy kafolat.

    O'lchangan nosozlik (2026-08-30): `talabsiz`/`otkazildi` kod
    BERMAYDI, ya'ni mahsulot kodsiz qoladi. `navbat()` esa faqat
    "kodi yo'q" ni tekshirardi va atama keyingi yuklashda QAYTARDI —
    o'sha joyda, o'sha tartibda. Navbat hech qachon tugamasdi.

    Hech qanday istisno chiqmasdi va 67/67 sinov yashil edi. Shuning
    uchun bu yerda "xato chiqmadi" emas, OLDIN/KEYIN SONI o'lchanadi.
    """
    section("B. Qaror navbatni kamaytiradi")
    from api import db, kodlash

    KIM = "zztest-qaror"
    nav = kodlash.navbat(cid, limit=40, takliflar_bilan=False)
    if not nav["atamalar"]:
        check("sinov uchun navbatda atama bor", False, "navbat bo'sh")
        return
    a = nav["atamalar"][0]
    k, atama = a["kalit"], a["atama"]
    oldin = len(nav["atamalar"])
    oldin_qq = nav["qaror_qilingan_jami"]

    try:
        kodlash.qaror_ochish(cid, k, atama)
        kodlash.qaror_yoz(cid, k, atama, "otkazildi", kim=KIM, ishonch="kompaniya_sessiyasi")

        nav2 = kodlash.navbat(cid, limit=40, takliflar_bilan=False)
        kalitlar = [x["kalit"] for x in nav2["atamalar"]]
        check("qaror qilingan atama navbatdan CHIQDI", k not in kalitlar,
              f"{k!r} hali navbatda")
        check("navbat qatori KAMAYDI yoki o'rniga boshqasi keldi",
              k not in kalitlar and len(nav2["atamalar"]) <= oldin,
              f"oldin={oldin} keyin={len(nav2['atamalar'])}")
        # JIMGINA YO'QOLMASIN: qoldiqsiz toifalash shu yerda ham.
        check("atama YO'QOLMADI — 'qaror_qilingan' toifasida",
              nav2["qaror_qilingan_jami"] == oldin_qq + 1,
              f"oldin={oldin_qq} keyin={nav2['qaror_qilingan_jami']}")
        check("yig'indi HALI HAM jamiga teng",
              nav2["jami_mahsulot"] == nav2["toifa_yigindi"],
              f"jami={nav2['jami_mahsulot']} yig'indi={nav2['toifa_yigindi']}")

        # --- TAKROR bosish qaror sonini SHISHIRMASIN (ko'rinadi) ---
        kodlash.qaror_yoz(cid, k, atama, "otkazildi", kim=KIM, ishonch="kompaniya_sessiyasi")
        o = kodlash.qaror_olchov(cid)
        check("takror bosish `atama_soni` ni oshirmaydi",
              (o.get("qaror_soni") or 0) > (o.get("atama_soni") or 0),
              f"qaror_soni={o.get('qaror_soni')} atama_soni={o.get('atama_soni')}")
    finally:
        db.execute_returning(
            "DELETE FROM kod_qaror WHERE kim = %(kim)s RETURNING id",
            {"kim": KIM})
        db.execute_returning(
            "DELETE FROM kod_qaror WHERE company_id=%(c)s AND kalit=%(k)s "
            "AND qaror IS NULL RETURNING id", {"c": cid, "k": k})


def test_olchanmagan_vaqt_nol_emas(cid: int):
    """O'LCHANMAGAN vaqt NOL deb sanalmaydi.

    `qaror_yoz()` ochiq qator topmasa `ochilgan_at` NULL qoladi.
    Ilgari ustunda `DEFAULT now()` bor edi va bunday qator
    `ochilgan_at = qaror_at` bo'lib "0 soniya" deb o'qilardi —
    o'lchandi: uchta qarordan keyin `ortacha_sek = 0`.
    """
    section("B. O'lchanmagan vaqt")
    from api import db, kodlash

    KIM = "zztest-vaqt"
    K = "zztest atama kaliti"
    try:
        # OCHILISHSIZ qaror -> o'lchov YO'Q.
        kodlash.qaror_yoz(cid, K, "ZZTEST atama", "otkazildi", kim=KIM, ishonch="kompaniya_sessiyasi")
        r = db.query_one(
            "SELECT ochilgan_at, qaror_at FROM kod_qaror "
            "WHERE company_id=%(c)s AND kalit=%(k)s", {"c": cid, "k": K})
        check("ochilishsiz qarorda ochilgan_at NULL (o'lchanmadi)",
              r is not None and r["ochilgan_at"] is None,
              str(r))
        o = kodlash.qaror_olchov(cid)
        check("o'lchovsiz qator alohida sanaladi",
              (o.get("olchovsiz") or 0) >= 1, str(o.get("olchovsiz")))
        check("o'lchovsiz qator o'rtachaga QO'SHILMADI",
              (o.get("olchangan") or 0) == 0 and o.get("ortacha_sek") is None,
              f"olchangan={o.get('olchangan')} ortacha={o.get('ortacha_sek')}")

        # Endi OCHIB qaror qilamiz -> o'lchov BOR va u nol emas.
        db.execute_returning("DELETE FROM kod_qaror WHERE kim=%(kim)s "
                             "RETURNING id", {"kim": KIM})
        kodlash.qaror_ochish(cid, K, "ZZTEST atama")
        ochiq = db.query_one("SELECT ochilgan_at FROM kod_qaror "
                             "WHERE company_id=%(c)s AND kalit=%(k)s",
                             {"c": cid, "k": K})
        check("ochilgan qatorda soat ISHGA TUSHDI",
              ochiq is not None and ochiq["ochilgan_at"] is not None)

        # QIDIRUV SANOG'I ochiq qatorga tushadi.
        n = kodlash.qaror_qidiruv(cid, K)
        check("qidiruv sanog'i ochiq qatorga yozildi", n == 1, str(n))

        kodlash.qaror_yoz(cid, K, "ZZTEST atama", "talabsiz", kim=KIM, ishonch="kompaniya_sessiyasi")
        o2 = kodlash.qaror_olchov(cid)
        check("ochilgan qaror O'LCHANDI", (o2.get("olchangan") or 0) >= 1,
              str(o2.get("olchangan")))
        check("qidiruv soni SAQLANDI (talabsiz qidiruvli)",
              (o2.get("talabsiz_qidiruvli") or 0) >= 1, str(o2))
    finally:
        db.execute_returning(
            "DELETE FROM kod_qaror WHERE kim=%(kim)s OR kalit=%(k)s "
            "RETURNING id", {"kim": KIM, "k": K})


def test_ochiq_soat_qulfi(cid: int):
    """OCHIQ qator soatsiz yozilmasin — CHECK majburlaydi.

    `qaror_ochish()` ni chetlab o'tgan kod ochiq qator yaratsa, keyingi
    qaror uchun vaqt yana jimgina o'lchanmasdi.
    """
    section("B. Ochiq qator soat qulfi")
    from api import db

    K = "zztest soat kaliti"
    xato = None
    try:
        db.execute_returning(
            "INSERT INTO kod_qaror (company_id, kalit, atama, ochilgan_at) "
            "VALUES (%(c)s, %(k)s, 'ZZTEST', NULL) RETURNING id",
            {"c": cid, "k": K})
    except Exception as e:                                   # noqa: BLE001
        xato = str(e)
    check("soatsiz OCHIQ qator rad etildi (CHECK ushladi)",
          xato is not None and "ochiq_soat" in (xato or ""),
          xato or "yozildi!")
    db.execute_returning("DELETE FROM kod_qaror WHERE kalit=%(k)s RETURNING id",
                         {"k": K})


def test_takror_hisob_yoq():
    """ORTIQCHA HISOB QAYTMASIN — "Sizga mos" sekinligining sababi.

    O'LCHANGAN NUQSON (2026-09-02). `POST /catalog/match` 4.9-8.1 s
    yuklanardi (35 ta natija uchun). Profil: vaqtning 96% i
    `pozitsiya_moslik` da, uning ichida `translit._cyr_readings`
    19 280 marta chaqirilgan va 16 151 990 ta `str.startswith`
    bajarilgan.

    SABAB ALGORITM EMAS, TAKROR HISOB edi: bitta so'rovda
    `variants()` 16 851 marta chaqirilardi, TAKRORSIZ kirish esa
    atigi 1 048 ta — 16 barobar ortiqcha ish.

    BU SINOV VAQTNI O'LCHAMAYDI. Vaqt sinovlari mashinaga bog'liq
    va tebranadi; ular yiqilganda sabab noaniq bo'ladi. O'lchanadigan
    narsa — ORTIQCHA ISH: bir xil kirish qayta hisoblanmasin.
    """
    section("Takror hisob — kesh")
    from api import kodlash as K
    from api import translit as T

    # --- Keshlar mavjud ---
    for nom, fn in (("translit._variants", T._variants),
                    ("translit._cyr_readings", T._cyr_readings),
                    ("translit.fold_cyr", T.fold_cyr),
                    ("kodlash._uchliklar", K._uchliklar),
                    ("kodlash._ozgarish", K._ozgarish)):
        check(f"`{nom}` keshlangan", hasattr(fn, "cache_info"))

    # --- KESH HAQIQATAN ISHLAYDI ---
    # Mavjudligi yetarli emas: `maxsize=0` bo'lsa ham `cache_info`
    # bo'lardi.
    K._ozgarish.cache_clear()
    T._variants.cache_clear()
    nomlar = ["Кресло офисное", "Стол ученический", "Кресло офисное"]
    pozlar = ["Ofis kreslosi", "Ofis kreslosi"]
    for nom in nomlar:
        for poz in pozlar:
            K._ozgarish(nom, poz)
    ci = K._ozgarish.cache_info()
    # 3 nom x 2 pozitsiya = 6 chaqiruv, TAKRORSIZ juftlik = 4.
    check("takroriy juftlik QAYTA hisoblanmaydi",
          ci.hits >= 2 and ci.misses <= 4, str(ci))
    # `variants()` ALOHIDA sinaladi: `_ozgarish` keshi tufayli
    # takroriy juftlik unga umuman YETIB BORMAYDI, ya'ni uni
    # `_ozgarish` orqali sinash keshni emas, boshqa keshni o'lchardi.
    T._variants.cache_clear()
    for _ in range(3):
        T.variants("Кресло офисное")
    vi = T._variants.cache_info()
    check("`variants()` takroriy nomni QAYTA hisoblamaydi",
          vi.hits == 2 and vi.misses == 1, str(vi))

    # --- KESH ZAHARLANMASIN ---
    # Keshlangan funksiya O'ZGARUVCHAN qiymat qaytarsa, chaqiruvchi
    # uni o'zgartirib butun keshni buzardi va xato BUTUNLAY boshqa
    # joyda chiqardi.
    v = T.variants("Кресло офисное")
    check("`variants()` RO'YXAT qaytaradi (chaqiruvchilar shunday kutadi)",
          isinstance(v, list), type(v).__name__)
    v.append("ZAHAR")
    check("qaytgan ro'yxatni o'zgartirish keshni BUZMAYDI",
          "ZAHAR" not in T.variants("Кресло офисное"))
    check("`_variants()` O'ZGARMAS tur qaytaradi",
          isinstance(T._variants("Кресло офисное"), tuple))
    check("`_cyr_readings()` O'ZGARMAS tur qaytaradi",
          isinstance(T._cyr_readings("kreslo"), tuple))
    u = K._uchliklar("Кресло")
    check("`_uchliklar()` O'ZGARMAS tur qaytaradi (frozenset)",
          isinstance(u, frozenset), type(u).__name__)
    # `frozenset` to'plam amallarida `set` bilan bir xil ishlashi shart.
    check("`frozenset` to'plam amallari ishlaydi",
          len(K._uchliklar("abc") & K._uchliklar("abc")) > 0
          and len(K._uchliklar("abc") | K._uchliklar("xyz")) > 0)

    # --- G'OLIB BALLI IKKI MARTA HISOBLANMAYDI ---
    with open(os.path.join(ROOT, "api", "kodlash.py"),
              encoding="utf-8") as f:
        src = f.read()
    check("g'olib balli QAYTA hisoblanmaydi",
          'skor = _ozgarish(eng["product_name"], poz)' not in src,
          "`max(key=...)` dan keyin yana bir chaqiruv bor edi")


def main() -> int:
    ap = argparse.ArgumentParser()
    rejim.bayroqlar(ap)
    ap.add_argument("--company", type=int, default=2)
    args = rejim.moslash(ap.parse_args())

    test_prior()
    test_query_matn()
    test_leksik_naqsh()
    test_product_matches()
    test_atribut()
    test_sxema_qulflari()
    test_qaror_sxema_qulflari()
    test_navbat_qaror_filtri_kodda()
    test_moslik_sql_faol_korinishdan()
    test_semantik_hublik()
    test_takror_hisob_yoq()

    if not args.bazasiz:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(ROOT, ".env"))
            from api import db
            db.init_pool()
            test_markaz_va_lugat()
            test_baza_qulflari(args.company)
            test_moslik_tasdiqsiz_ishlamaydi(args.company)
            test_navbat_qoldiqsiz(args.company)
            test_qidiruv_ijarachi(args.company)
            test_kodsiz_korinadi(args.company)
            test_qaror_navbatni_kamaytiradi(args.company)
            test_olchanmagan_vaqt_nol_emas(args.company)
            test_ochiq_soat_qulfi(args.company)
        except Exception as e:                               # noqa: BLE001
            # BAZA YO'QLIGI SINOVNI "O'TDI" QILMASIN.
            check("dinamik qism yurdi", False, f"{type(e).__name__}: {e}")

    yiqilgan = [n for n, ok in _results if not ok]
    print("\n" + "=" * 62)
    print(f"NATIJA: {len(_results) - len(yiqilgan)}/{len(_results)} o'tdi")
    print("=" * 62)
    for n in yiqilgan:
        print(f"  YIQILDI: {n}")
    return 1 if yiqilgan else 0


if __name__ == "__main__":
    sys.exit(main())
