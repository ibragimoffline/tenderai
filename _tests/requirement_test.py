# -*- coding: utf-8 -*-
"""SINOV: J3 — `tender_requirement` poydevori.

Modelga CHIQMAYDI, PUL SARFLAMAYDI. Barcha yozuvlar sinov oxirida
qaytariladi.

Nima tekshiriladi:
  A. SXEMA   — jadval, cheklovlar va ATAYLAB YO'Q bo'lgan FK
  B. STATIK  — `ON CONFLICT` maqsadi UNIQUE cheklov bilan mos kelishi
  C. AMALIY  — idempotentlik, izolyatsiya, yurish jurnali
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

konsol.sozla()

from dotenv import load_dotenv                              # noqa: E402
load_dotenv(os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), ".env"))

from api import db, requirement as R                        # noqa: E402

PASS = FAIL = 0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_yozilgan = []          # (company_id, tender_id) — oxirida tozalanadi

#: (company_id, tender_id) -> SINOVDAN OLDIN mavjud bo'lgan qator id lari.
#:
#: NEGA KERAK — O'LCHANGAN NUQSON (2026-08-30):
#: `tozala()` `DELETE FROM tender_requirement WHERE company_id=.. AND
#: tender_id=..` qilardi, ya'ni O'SHA JUFTLIKDAGI HAMMA NARSANI.
#: Sinov esa kompaniyani `company_account ORDER BY id LIMIT 2` bilan
#: oladi va u REAL ishlab turgan kompaniya (id=2) ga tushadi, tender
#: ham REAL. Natijada har sinov yurishi PRODUCTION qatorlarini
#: o'chirib yuborardi: 8785 -> 8736 (44 qator, o'lchangan).
#:
#: Nuqson JIMGINA edi — sinov yashil qolardi, chunki u o'chirilgan
#: narsani tekshirmasdi. Endi tozalash FAQAT sinov YARATGAN qatorlarni
#: oladi: oldindan mavjud id lar eslab qolinadi va tegilmaydi.
_oldingi_idlar: dict = {}


def belgila(cid: int, tid: int) -> None:
    """(kompaniya, tender) juftligini tozalash ro'yxatiga qo'shadi.

    Qo'shishdan OLDIN o'sha juftlikda ALLAQACHON turgan qatorlarni
    eslab qoladi — ular sinovniki EMAS va tegilmasligi kerak.
    """
    kalit = (cid, tid)
    if kalit not in _oldingi_idlar:
        _oldingi_idlar[kalit] = {
            r["id"] for r in db.query(
                "SELECT id FROM tender_requirement "
                "WHERE company_id=%(c)s AND tender_id=%(t)s",
                {"c": cid, "t": tid})}
    _yozilgan.append(kalit)


def _cheklov_xatosimi(e: Exception) -> bool:
    """CHECK cheklovi ishladimi.

    Xato MATNIGA bog'lanmaymiz: PostgreSQL xabari TILGA bog'liq
    (ruscha o'rnatishda "ограничение-проверку") va cheklov nomi
    `_chk` ham, `_check` ham bo'lishi mumkin. Ikkalasida ham sinov
    yiqilgan edi — ya'ni u cheklovni emas, XABAR MATNINI o'lchayotgan
    edi.
    """
    matn = str(e).lower()
    # NOT NULL ni CHECK deb QABUL QILMAYMIZ: sinov noto'g'ri sababdan
    # "o'tgan" bo'lib ko'rinardi (aynan shunday bo'ldi — `review_status`
    # qo'shilgach uchta CHECK sinovi NOT NULL ga urildi).
    if "not null" in matn or "not-null" in matn:
        return False
    return (type(e).__name__ == "CheckViolation"
            or "check" in matn or "_chk" in matn)


def check(nom: str, shart: bool, izoh: str = "") -> None:
    global PASS, FAIL
    if shart:
        PASS += 1
        print(f"  OK   {nom}")
    else:
        FAIL += 1
        print(f"  XATO {nom}" + (f"\n       {izoh}" if izoh else ""))


def section(t: str) -> None:
    print(f"\n=== {t} ===")


#: Fikstura tenderi — korpusda BO'LMAYDIGAN, ataylab katta id.
#: Haqiqiy `tender.id` lar 3-11 xonali; bu 15 xonali va `ZZTEST`
#: nomi bilan yuradi, ya'ni jonli qator bilan ARALASHMAYDI.
ZZ_TENDER_ID = 999_000_000_000_001


def _bosh_ochiq_tender():
    """Talabi yo'q OCHIQ tender — fikstura uchun.

    OCHIQLIK SHART. Ko'rik navbati 2026-09-03 dan muddati o'tgan
    tenderlarni standart holda CHIQARADI: ular navbatning BUTUN
    birinchi sahifasini egallab turgan edi (989 dan 534 tasi). Bu
    shartsiz fikstura yopiq tender tanlashi mumkin va sinov
    "navbatga tushmadi" deb yiqilardi — sabab esa FIKSTURADA
    bo'lardi, kodda emas. Bunday yiqilish eng chalg'ituvchi turi.
    """
    tid = db.scalar("""SELECT t.id FROM tender t
        WHERE (t.close_at IS NULL OR t.close_at > now())
          AND NOT EXISTS (SELECT 1 FROM tender_requirement r
                          WHERE r.tender_id = t.id) LIMIT 1""")
    if tid:
        return tid

    # HOVUZ QURISA SINOV O'Z TENDERINI YARATADI.
    #
    # O'LCHANGAN NUQSON (2026-09-04). Fikstura mavjud korpusdan
    # QARZ olardi va shart "ochiq + talabsiz" edi. Vaqt o'tishi
    # bilan bunday tender qolmaydi: o'sha kuni oxirgi 48 soatda
    # 263 ta tender YOPILGAN va hovuz 3 taga tushgan — sinovning
    # oldingi bo'limlari o'shalarni band qilgach, G bo'limi
    # "bo'sh tender topilmadi" deb yiqilgan.
    #
    # Bu YANGI SINF: sinov KODGA emas, HOVUZ HOLATIGA bog'liq.
    # Yiqilish sababi kodda emasligi uni eng chalg'ituvchi turga
    # aylantiradi.
    #
    # `ZZTEST-` prefiksi ATAYLAB: `grill-me` 11-sinfi — belgi
    # QONUNIY qiymat bo'lmasin (`Karimov` 30 ta haqiqiy qatorga
    # tegib ketgan edi).
    yangi = db.execute_returning("""
        INSERT INTO tender (id, name, status, close_at, source_platform,
                            source_id, raw_json, fetched_at, first_seen_at)
        VALUES (%(id)s, 'ZZTEST fikstura — talabsiz ochiq tender',
                'open', now() + interval '30 days', 'uzex',
                %(id)s, '{}'::jsonb, now(), now())
        ON CONFLICT (id) DO UPDATE
           SET close_at = now() + interval '30 days'
        RETURNING id""", {"id": ZZ_TENDER_ID})
    return yangi["id"] if yangi else None


# =====================================================================
def test_sinovni_sinash():
    """0. SINOV VOSITASINING O'ZI to'g'ri ishlaydimi.

    ORTIQCHA KO'RINADI, LEKIN: shu loyihada "sinov o'zi tekshirilmagan"
    xatosi TO'RT MARTA takrorlandi:

      §16.28  leksik qidiruv — rus ekvivalenti unutilgan;
      §16.29  eval baholovchisi — "duch kelinmadi" tanilmagan;
      §16.33  `.doc` sifat mezoni — lotin shakllari yo'q;
      §16.44  `_cheklov_xatosimi()` — NOT NULL ni CHECK deb qabul
              qilib, uchta sinovni YOLG'ON "o'tdi" qilib ko'rsatgan.

    Qoida: HAR NEGATIV yordamchi musbat holatda `True`, salbiy
    holatda `False` qaytarishi ALOHIDA qulflanadi.
    """
    section("0. Sinov vositasining o'zi")

    class SoxtaCheck(Exception):
        pass
    SoxtaCheck.__name__ = "CheckViolation"

    check("CHECK buzilishi -> True", _cheklov_xatosimi(SoxtaCheck("xato")))
    check("xabarda 'check' bo'lsa -> True",
          _cheklov_xatosimi(Exception("violates check constraint x_check")))
    check("cheklov nomi '_chk' bo'lsa -> True",
          _cheklov_xatosimi(Exception("narusheniye ogranicheniya x_method_chk")))
    # ENG MUHIMI: NOT NULL ni CHECK deb QABUL QILMASIN.
    check("NOT NULL -> False (CHECK emas!)",
          not _cheklov_xatosimi(Exception(
              'null value in column "x" violates not-null constraint')))
    check("ruscha NOT NULL -> False",
          not _cheklov_xatosimi(Exception(
              'znachenie NULL narushaet ogranichenie NOT NULL')))
    check("aloqasiz xato -> False",
          not _cheklov_xatosimi(Exception("connection refused")))


# =====================================================================
def test_sxema():
    section("A. SXEMA")

    for jadval in ("tender_requirement", "tender_requirement_run"):
        check(f"{jadval} mavjud",
              bool(db.scalar("SELECT to_regclass(%(t)s)",
                             {"t": "public." + jadval})))

    # `company_id` NOT NULL — J1 qoidasi. DEFAULT bo'lsa J1 dagi
    # "MIN(id) noto'g'ri kompaniyaga yozdi" hodisasi qaytardi.
    r = db.query_one("""SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name='tender_requirement' AND column_name='company_id'""")
    check("company_id NOT NULL", r and r["is_nullable"] == "NO", str(r))
    check("company_id da DEFAULT YO'Q", r and r["column_default"] is None,
          f"default={r and r['column_default']}")

    # ATAYLAB YO'Q: `doc_chunk` ga FK. `etl_embed --chunks` bo'laklarni
    # DELETE+INSERT qiladi — FK bo'lsa talablar CASCADE bilan o'chardi.
    n = db.scalar("""
        SELECT count(*) FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.table_name='tender_requirement'
          AND tc.constraint_type='FOREIGN KEY' AND ccu.table_name='doc_chunk'""")
    check("doc_chunk ga FK YO'Q (qayta bo'laklash talabni o'chirmasin)",
          n == 0, f"{n} ta FK topildi")

    # UNIQUE cheklov — `ON CONFLICT` shunga tayanadi
    r = db.query_one("""
        SELECT string_agg(a.attname, ',' ORDER BY k.ord) AS ustunlar
        FROM pg_constraint c
        JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.conname = 'tender_requirement_uq'""")
    check("tender_requirement_uq mavjud", bool(r and r["ustunlar"]), str(r))
    if r and r["ustunlar"]:
        # `method` 2026-08-25 da QO'SHILDI (schema_patch_requirement_2):
        # naqsh va LLM natijalari bir-birini o'chirmasin.
        check("UNIQUE ustunlari kutilgandek",
              r["ustunlar"]
              == "company_id,tender_id,source,method,position_no,name",
              r["ustunlar"])

    # CHECK: confidence 0..1
    try:
        db.execute_returning("""INSERT INTO tender_requirement
            (company_id, tender_id, source, method, name, confidence,
             review_status)
            VALUES (2, (SELECT id FROM tender LIMIT 1), 'document', 'llm',
                    'x', 1.5, 'pending')
            RETURNING id""")
        check("confidence>1 rad etiladi", False, "qabul qilindi")
    except Exception as e:                                  # noqa: BLE001
        check("confidence>1 rad etiladi", _cheklov_xatosimi(e), str(e)[:70])

    # CHECK: source qiymatlari
    try:
        db.execute_returning("""INSERT INTO tender_requirement
            (company_id, tender_id, source, method, name, review_status)
            VALUES (2, (SELECT id FROM tender LIMIT 1), 'boshqa', 'llm', 'x',
                    'pending')
            RETURNING id""")
        check("noma'lum source rad etiladi", False, "qabul qilindi")
    except Exception as e:                                  # noqa: BLE001
        check("noma'lum source rad etiladi", _cheklov_xatosimi(e),
              str(e)[:70])

    # CHECK: method qiymatlari
    try:
        db.execute_returning("""INSERT INTO tender_requirement
            (company_id, tender_id, source, method, name, review_status)
            VALUES (2, (SELECT id FROM tender LIMIT 1), 'document', 'sehr', 'x',
                    'pending')
            RETURNING id""")
        check("noma'lum method rad etiladi", False, "qabul qilindi")
    except Exception as e:                                  # noqa: BLE001
        check("noma'lum method rad etiladi", _cheklov_xatosimi(e),
              str(e)[:70])

    # `method` DEFAULT bo'lmasligi SHART — har chaqiruvchi aniq aytsin
    r = db.query_one("""SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name='tender_requirement' AND column_name='method'""")
    check("method NOT NULL va DEFAULT yo'q",
          r and r["is_nullable"] == "NO" and r["column_default"] is None,
          str(r))


# =====================================================================
def test_statik():
    section("B. STATIK — ON CONFLICT maqsadi")
    # J1 SABOQI: PK/UNIQUE o'zgarganda `ON CONFLICT` maqsadi ham
    # o'zgarishi kerak. O'sha paytda BESHTA joyda jimgina buzilgan va
    # buni faqat YURGIZIB KO'RISH ochgan edi. Bu yerda statik ushlaymiz.
    m = re.search(r"ON CONFLICT\s*\(([^)]+)\)", R.SQL_UPSERT, re.I)
    check("SQL_UPSERT da ON CONFLICT bor", bool(m))
    if m:
        maqsad = ",".join(x.strip() for x in m.group(1).split(","))
        check("ON CONFLICT maqsadi UNIQUE bilan bir xil",
              maqsad == "company_id,tender_id,source,method,position_no,name",
              maqsad)

    m2 = re.search(r"ON CONFLICT\s*\(([^)]+)\)", R.SQL_RUN_UPSERT, re.I)
    if m2:
        maqsad2 = ",".join(x.strip() for x in m2.group(1).split(","))
        check("run jurnali ON CONFLICT = PK",
              maqsad2 == "company_id,tender_id,method", maqsad2)

    # Har o'qish so'rovida `company_id` bo'lishi SHART
    for nom in ("SQL_LIST", "SQL_RUN_GET", "SQL_PENDING"):
        sql = getattr(R, nom)
        check(f"{nom} da company_id bor",
              bool(re.search(r"\bcompany_id\b", sql, re.I)),
              " ".join(sql.split())[:90])


# =====================================================================
def test_amaliy():
    section("C. AMALIY — idempotentlik va izolyatsiya")
    t = db.query_one("""SELECT g.tender_id, count(*) AS n FROM tender_good g
        GROUP BY 1 HAVING count(*) BETWEEN 3 AND 60 ORDER BY 2 DESC LIMIT 1""")
    if not t:
        check("pozitsiyali tender topildi", False, "tender_good bo'sh")
        return
    tid = t["tender_id"]

    kompaniyalar = [r["id"] for r in
                    db.query("SELECT id FROM company_account ORDER BY id LIMIT 2")]
    if len(kompaniyalar) < 2:
        check("ikki kompaniya bor", False, "izolyatsiya sinovi uchun kerak")
        return
    A, B = kompaniyalar[0], kompaniyalar[1]
    belgila(A, tid); belgila(B, tid)

    r1 = R.from_api(tid, A)
    check("from_api talab yozdi", r1["n"] > 0, str(r1))
    lst1 = R.list_for(tid, A)
    check("list_for o'sha sonni qaytardi", len(lst1) == r1["n"],
          f"{len(lst1)} != {r1['n']}")

    # IDEMPOTENTLIK — ikkinchi yurish dublikat yaratmasin
    R.from_api(tid, A)
    lst2 = R.list_for(tid, A)
    check("ikkinchi yurish dublikat yaratmaydi", len(lst2) == len(lst1),
          f"{len(lst1)} -> {len(lst2)}")

    # IZOLYATSIYA — B kompaniya A ning talablarini ko'rmaydi
    check("B kompaniya A ning talablarini ko'rmaydi",
          len(R.list_for(tid, B)) == 0)
    R.from_api(tid, B)
    check("B o'z talablarini ko'radi", len(R.list_for(tid, B)) > 0)
    check("A ning talablari o'zgarmadi", len(R.list_for(tid, A)) == len(lst1))

    # YURISH JURNALI — "topilmadi" va "ajratilmagan" AJRALADI
    info = R.run_info(tid, A)
    check("yurish jurnali yozildi", info is not None and info["status"] == "ok",
          str(info))
    yoq_tender = db.scalar("""SELECT t.id FROM tender t
        WHERE NOT EXISTS (SELECT 1 FROM tender_good g WHERE g.tender_id=t.id)
        LIMIT 1""")
    if yoq_tender:
        belgila(A, yoq_tender)
        r = R.from_api(yoq_tender, A)
        check("pozitsiyasiz tender: 0 talab, lekin JURNAL bor",
              r["n"] == 0 and R.run_info(yoq_tender, A) is not None, str(r))
        s = R.summary(yoq_tender, A)
        check("summary 'ajratilgan' deb ko'rsatadi",
              s["holat"] == "ok" and s["jami"] == 0, str(s))

    # summary — iste'molchilar uchun
    s = R.summary(tid, A)
    check("summary to'g'ri sanaydi",
          s["jami"] == len(lst1) and s["hujjatdan"] == 0, str(s))

    # pending — ajratilgani QAYTA tanlanmasin
    p = [x["id"] for x in R.pending(A, 2000)]
    check("ajratilgan tender pending da yo'q", tid not in p,
          f"pending: {len(p)} ta")


# =====================================================================
def test_hujjatdan():
    """D. HUJJATDAN AJRATISH — modelga CHIQMAYDI.

    `save()` sof funksiyaga yaqin: model javobini olib jadvalga yozadi.
    Uni soxta javob bilan sinash mumkin — chaqiruvsiz, pulsiz.
    """
    from api import requirement_ai as RA
    section("D. Hujjatdan ajratish (modelsiz)")

    # --- Atama qamrovi: UCH YOZUV ham bo'lishi SHART (§16.34) ---
    tsq = RA._talab_tsquery()
    for atama_ in ("kafolat", "гарант", "sertifikat", "срок", "оплат"):
        check(f"tsquery da {atama_!r} bor", atama_ in tsq, tsq[:100])

    # --- Bo'laklar RAQAMLANADI (§16.32 saboqi) ---
    soxta_chunks = [
        {"file_ref": "a.pdf", "char_start": 100, "char_end": 900,
         "file_name": "shartnoma.pdf", "text": "Kafolat muddati 12 oy."},
        {"file_ref": "b.pdf", "char_start": 50, "char_end": 800,
         "file_name": "texnik.pdf", "text": "ISO 9001 talab qilinadi."},
    ]
    matn = RA.build_input({"id": 1, "name": "Sinov"}, soxta_chunks)
    check("bo'laklar raqamlangan", "[1]" in matn and "[2]" in matn, matn[:80])
    check("fayl nomi ko'rsatilgan", "shartnoma.pdf" in matn)

    # --- Amaliy: soxta javobni saqlash ---
    tid = db.scalar("SELECT id FROM tender LIMIT 1")
    cid = db.scalar("SELECT id FROM company_account ORDER BY id LIMIT 1")
    belgila(cid, tid)

    natija = {"requirements": [
        {"name": "Kafolat muddati", "tur": "kafolat", "qiymat": "12 oy",
         "is_mandatory": True, "manba_raqami": 1,
         "iqtibos": "Kafolat muddati 12 oy.", "confidence": 0.95},
        {"name": "ISO 9001", "tur": "sertifikat", "qiymat": "ISO 9001",
         "is_mandatory": True, "manba_raqami": 2,
         "iqtibos": "ISO 9001 talab qilinadi.", "confidence": 0.90},
    ]}
    r = RA.save(tid, cid, natija, soxta_chunks, "hash1")
    check("ikki talab yozildi", r["n"] == 2, str(r))
    check("status ok (ishonch yuqori)", r["status"] == "ok", str(r))

    yozilgan = [x for x in R.list_for(tid, cid) if x["source"] == "document"]
    kaf = next((x for x in yozilgan if x["name"] == "Kafolat muddati"), None)
    check("manba_raqami=1 -> 1-bo'lak file_ref",
          kaf and kaf["file_ref"] == "a.pdf", str(kaf and kaf["file_ref"]))
    check("manba_raqami=1 -> 1-bo'lak char_start",
          kaf and kaf["char_start"] == 100, str(kaf and kaf["char_start"]))
    iso = next((x for x in yozilgan if x["name"] == "ISO 9001"), None)
    check("manba_raqami=2 -> 2-bo'lak", iso and iso["char_start"] == 50,
          str(iso and iso["char_start"]))
    check("attrs da tur va qiymat bor",
          kaf and (kaf["attrs"] or {}).get("tur") == "kafolat"
          and (kaf["attrs"] or {}).get("qiymat") == "12 oy", str(kaf))

    # --- MODEL O'YLAB TOPGAN RAQAM ---
    # Talab TASHLANMAYDI (ma'lumot yo'qotilmasin), lekin manbasiz qoladi
    # va ishonchi pasaytiriladi — holat KO'RINIB tursin.
    natija2 = {"requirements": [
        {"name": "Yolgon manba", "tur": "boshqa", "qiymat": "x",
         "is_mandatory": False, "manba_raqami": 99,
         "iqtibos": "yo'q", "confidence": 0.95},
    ]}
    r2 = RA.save(tid, cid, natija2, soxta_chunks, "hash2")
    check("mavjud bo'lmagan raqam sanaladi", r2["yolgon_manba"] == 1, str(r2))
    y = next((x for x in R.list_for(tid, cid) if x["name"] == "Yolgon manba"),
             None)
    check("yolgon manbali talab TASHLANMAYDI", y is not None)
    check("manba maydonlari bo'sh", y and y["file_ref"] is None)
    check("ishonch 0.50 ga tushirildi",
          y and float(y["confidence"]) <= 0.50, str(y and y["confidence"]))
    check("attrs da ogohlantirish bor",
          y and "ogohlantirish" in (y["attrs"] or {}), str(y and y["attrs"]))
    check("yurish jurnalida xato qayd etilgan",
          "manba raqami" in ((R.run_info(tid, cid, method="llm") or {})
                             .get("error") or ""),
          str(R.run_info(tid, cid, method="llm")))

    # --- PAST ISHONCH -> needs_review, TASHLANMAYDI (qaror 3.5) ---
    natija3 = {"requirements": [
        {"name": "Bo'sh shablon", "tur": "kafolat",
         "qiymat": "ko'rsatilmagan (_____)", "is_mandatory": True,
         "manba_raqami": 1, "iqtibos": "kafolat muddati _____ ni tashkil",
         "confidence": 0.35},
    ]}
    r3 = RA.save(tid, cid, natija3, soxta_chunks, "hash3")
    check("past ishonch -> needs_review", r3["status"] == "needs_review",
          str(r3))
    b = next((x for x in R.list_for(tid, cid) if x["name"] == "Bo'sh shablon"),
             None)
    check("past ishonchli talab SAQLANADI", b is not None)
    check("ko'rib chiqish ko'rinishida chiqadi",
          db.scalar("""SELECT count(*) FROM v_requirement_review
                       WHERE tender_id=%(t)s AND company_id=%(c)s""",
                    {"t": tid, "c": cid}) > 0)

    # --- DRY RUN pul sarflamaydi va BAZAGA YOZMAYDI ---
    oldin = len(R.list_for(tid, cid))
    d = RA.extract(tid, cid, dry_run=True, force=True)
    check("dry_run status", d["status"] in ("dry_run", "no_text"), str(d))
    check("dry_run bazaga yozmadi", len(R.list_for(tid, cid)) == oldin)
    if d["status"] == "dry_run":
        check("dry_run narxni beradi", d["taxminiy_narx_usd"] > 0, str(d))

    # --- content_hash o'zgarmasa QAYTA AJRATILMAYDI (pul tejash) ---
    RA.save(tid, cid, {"requirements": []}, soxta_chunks, "hash_bir")
    d2 = RA.extract(tid, cid, dry_run=True)
    check("hash mos kelmasa dry_run davom etadi",
          d2["status"] in ("dry_run", "no_text", "skipped"), str(d2))


# =====================================================================
def test_naqsh():
    """E. NAQSH AJRATGICHI — bepul, modelsiz.

    Naqshlar SOF FUNKSIYA ustida sinaladi: matn beriladi, nima
    topilgani tekshiriladi. Bazaga ham, modelga ham tegmaydi.
    """
    from api import requirement_naqsh as N
    section("E. Naqsh ajratgichi (bepul)")

    # --- UCH YOZUV: har uchalasida ham topilishi SHART (§16.34) ---
    HOLATLAR = [
        ("Гарантийный срок на запасные части 12 месяцев с момента",
         "Kafolat muddati", "12 oy", "rus"),
        ("Kafolat muddati 24 oy qilib belgilanadi",
         "Kafolat muddati", "24 oy", "lotin"),
        ("Кафолат муддати 36 ой этиб белгиланади",
         "Kafolat muddati", "36 oy", "kirill"),
        ("Форма платежа – предоплата в 50 % от стоимости",
         "Oldindan to'lov", "50 %", "rus"),
        ("yetkazib berish muddati 30 kun ichida",
         "Yetkazib berish muddati", "30 kun", "lotin"),
    ]
    for matn, kutilgan_nom, kutilgan_qiymat, til in HOLATLAR:
        topildi = False
        for nom, _tur, naqsh, birlik in N.QOIDALAR:
            m = naqsh.search(matn)
            if m and nom == kutilgan_nom:
                if f"{m.group('son')} {birlik}" == kutilgan_qiymat:
                    topildi = True
                    break
        check(f"{til}: {kutilgan_qiymat!r} topildi", topildi, matn[:50])

    # --- ORALIQ: uzun ro'yxatdan keyingi raqam ham olinishi kerak ---
    # O'LCHANGAN: ORALIQ=80 da bu TUSHIB QOLGAN edi (t7475137).
    uzun = ("Гарантийный срок на основные узлы: РМК, генераторы, "
            "электродвигателя, статоры, роторы составляет 24 месяца")
    topildi = any(naqsh.search(uzun) and naqsh.search(uzun).group("son") == "24"
                  for _n, _t, naqsh, b in N.QOIDALAR if b == "oy")
    check("uzun ro'yxatdan keyingi raqam olinadi", topildi, uzun[:60])

    # --- JUMLA CHEGARASI: nuqtadan keyingi raqam OLINMASLIGI kerak ---
    yolgon = "Kafolat muddati alohida kelishiladi. Narxi 500 oy oldin"
    xato_topildi = False
    for _n, _t, naqsh, b in N.QOIDALAR:
        m = naqsh.search(yolgon)
        if m and m.group("son") == "500":
            xato_topildi = True
    check("nuqtadan keyingi raqam OLINMAYDI", not xato_topildi, yolgon)

    # --- BO'SH SHABLON ---
    bosh = "5.5. kafolat muddati Tovar chiqarilgan sanadan boshlab _____ni tashkil"
    check("bo'sh shablon tanildi", bool(N.BOSH_SHABLON.search(bosh)), bosh[:50])
    check("to'ldirilgan shablon shablon deb sanalmaydi",
          not N.BOSH_SHABLON.search("kafolat muddati 12 oyni tashkil etadi"))

    # --- HUJJAT LUG'ATI: uch yozuv ---
    for matn, kutilgan, til in [
        ("сертификат качества товара", "Sifat sertifikati", "rus"),
        ("sifat sertifikati taqdim etilsin", "Sifat sertifikati", "lotin"),
        ("сертификат происхождения", "Kelib chiqish sertifikati", "rus"),
        ("ISO 9001 talab qilinadi", "ISO standarti", "lotin"),
        ("ГОСТ 12.4.011", "GOST talabi", "rus"),
    ]:
        topildi = any(nom == kutilgan and naqsh.search(matn)
                      for nom, naqsh in N.HUJJAT_RE)
        check(f"{til}: {kutilgan!r}", topildi, matn)

    # --- INCOTERMS ---
    m = N.INCOTERMS_RE.search("Yetkazib berish sharti DAP Toshkent")
    check("INCOTERMS DAP tanildi", m and m.group(1).upper() == "DAP",
          str(m and m.group(0)))
    check("tasodifiy so'z INCOTERMS emas",
          not N.INCOTERMS_RE.search("Bu matnda bazis yo'q"))

    # --- ISHONCH: naqsh reyestrdan PAST, chunki kontekstni bilmaydi ---
    check("naqsh ishonchi reyestrdan past", N.CONF_NAQSH < 1.00)
    check("bo'sh shablon ishonchi eng past",
          N.CONF_BOSH_SHABLON < N.CONF_NAQSH)

    # --- TAQQOSLASH mezoni: raqam VA nom bo'yicha ---
    # O'LCHANGAN XATO: avval faqat RAQAM bo'yicha edi va sertifikatlar
    # (raqamsiz) HECH QACHON "qoplangan" deb sanalmasdi — mezon
    # ajratgichni emas, o'zini o'lchayotgan edi.
    check("kalit so'zlar uch yozuvda bir xil kalitga tushadi",
          N._kalit_sozlar("Sifat sertifikati")
          & N._kalit_sozlar("сертификат качества"),
          f"{N._kalit_sozlar('Sifat sertifikati')} vs "
          f"{N._kalit_sozlar('сертификат качества')}")


# =====================================================================
def test_isteemolchilar():
    """F. ISTE'MOLCHILAR — talablar HAQIQATAN ishlatilyaptimi.

    Ajratilgan 3700 ta talab hech qayerda o'qilmasa, ular bo'sh
    mehnat. Bu bo'lim BOG'LANISH uzilmaganini tekshiradi — modelga
    chiqmasdan.
    """
    section("F. Iste'molchilar (ai_gonogo, compare_tenders, get_tender)")

    # --- 1. `ai_gonogo` promptga talab blokini QO'SHADIMI ---
    from api import ai_gonogo
    import inspect
    imzo = inspect.signature(ai_gonogo.build_input).parameters
    check("build_input `talablar` parametrini oladi", "talablar" in imzo,
          str(list(imzo)))

    matn = ai_gonogo.build_input(
        {"id": 1, "name": "Sinov", "detail": {}}, [], None,
        docs="XOM HUJJAT MATNI", talablar="=== TALABLAR ===\nKafolat: 12 oy")
    check("talablar promptga tushdi", "Kafolat: 12 oy" in matn, matn[-200:])
    check("talablar XOM MATNDAN OLDIN",
          matn.index("Kafolat: 12 oy") < matn.index("XOM HUJJAT MATNI"),
          "tuzilgan ma'lumot oldin turishi kerak")
    # Bo'sh bo'lsa blok UMUMAN qo'shilmasin — "talab yo'q" degan
    # yolg'on taassurot bo'lmasin.
    matn2 = ai_gonogo.build_input({"id": 1, "name": "S", "detail": {}}, [],
                                  None, docs="X", talablar="")
    check("bo'sh talablar bloki qo'shilmaydi", "TALABLAR" not in matn2)

    # --- 2. `main.gonogo_cached` blokni UZATADIMI (statik) ---
    ROOT_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mainsrc = io.open(os.path.join(ROOT_, "api", "main.py"),
                      encoding="utf-8").read()
    check("main.py prompt_block ni chaqiradi",
          "prompt_block(tender_id, company_id)" in mainsrc)
    check("main.py talablarni analyze ga uzatadi",
          "talablar=talablar" in mainsrc)

    # --- 3. `compare_tenders` va `get_tender` (statik) ---
    chatsrc = io.open(os.path.join(ROOT_, "api", "ai_chat.py"),
                      encoding="utf-8").read()
    check("compare_tenders talablarni qo'shadi",
          '_req.qisqa(tid, company_id)' in chatsrc)
    # IDENTIFIKATOR BIR JOYDA HAL QILINADI (2026-09-04): barcha
    # tool `_tender_id_ol()` dan o'tadi va `int(args[...])` kodda
    # QOLMAGAN. Shart shunga moslashtirildi — chaqiruv bor-yo'qligi
    # tekshiriladi, uning ESKI SHAKLI emas.
    check("get_tender talablarni qo'shadi",
          '_talab_xulosa(tid, ctx.company_id)' in chatsrc)
    check("tool ta'rifida talablar eslatilgan",
          "AJRATILGAN TALABLAR" in chatsrc)

    # --- 4. `prompt_block` mazmuni ---
    #
    # NOMZOD ATAYLAB IKKITA VA ATAYLAB SHARTLI TANLANADI.
    #
    # O'LCHANGAN NUQSON (2026-09-06). Ilgari bu yerda bitta
    # `... WHERE source='document' LIMIT 1` turardi — `ORDER BY`
    # SIZ, ya'ni nomzodni Postgres rejasi tanlardi. Baza inson
    # tasdig'i bilan to'lgach tanlov `20000508677` ga tushdi va
    # uning 6 ta talabining 6 tasi ham tasdiqlangan edi. Blok esa
    # bunday qatorga ATAYLAB `naqsh`/`model` emas, `INSON
    # TASDIQLAGAN` yozadi (`api/requirement.py`), shuning uchun
    # "usul ko'rsatilgan" sharti yiqildi. Kod TO'G'RI edi — sinov
    # o'z nomzodiga kafolat bermagan edi.
    #
    # Endi ikkala TARMOQ ham o'z nomzodi bilan tekshiriladi va
    # nomzod topilmasa shart JIM O'TMAYDI, `check` yiqiladi.
    # `jami <= PROMPT_LIMIT` sharti kerak: blok `LIMIT` bilan
    # kesiladi va tekshirilayotgan qator kesimdan tashqarida
    # qolishi mumkin edi.
    nomzod = db.query_one("""
        SELECT tender_id, company_id
          FROM tender_requirement
         WHERE source='document' AND review_status <> 'rejected'
         GROUP BY tender_id, company_id
        HAVING count(*) <= %(l)s
           AND count(*) FILTER (
                   WHERE review_status IN ('approved','corrected')
                     AND reviewed_by IS NOT NULL) = 0
         ORDER BY tender_id
         LIMIT 1""", {"l": R.PROMPT_LIMIT})
    if nomzod:
        tid, cid = nomzod["tender_id"], nomzod["company_id"]
        blok = R.prompt_block(tid, cid)
        check("prompt_block matn qaytardi", bool(blok), blok[:60])
        check("qamrov ogohlantirishi bor",
              "BARCHASI emas" in blok, blok[-160:])
        check("usul ko'rsatilgan (naqsh/model)",
              "naqsh]" in blok or "model]" in blok, blok[:200])
        # `ishonch` so'zi izoh SARLAVHASIDA ham bor, ya'ni uni
        # butun blokdan qidirish HECH NARSANI o'lchamasdi. Talab
        # QATORINING o'zida turishi kerak.
        check("ishonch talab QATORIDA ko'rsatilgan",
              any("[ishonch " in q for q in blok.splitlines()),
              "modelga 'bu aniq ma'lumot' degan taassurot bermaymiz")
    else:
        check("tasdiqlanmagan talabli tender topildi", False,
              "nomzod yo'q — 'usul ko'rsatilgan' sharti o'lchanmadi")

    # INSON TASDIG'I TARMOG'I. Bu holat oldin UMUMAN sinalmagan edi
    # va aynan u sinovni yiqitgan edi.
    nomzod2 = db.query_one("""
        SELECT tender_id, company_id
          FROM tender_requirement
         WHERE source='document' AND review_status <> 'rejected'
         GROUP BY tender_id, company_id
        HAVING count(*) <= %(l)s
           AND count(*) FILTER (
                   WHERE review_status IN ('approved','corrected')
                     AND reviewed_by IS NOT NULL) > 0
         ORDER BY tender_id
         LIMIT 1""", {"l": R.PROMPT_LIMIT})
    if nomzod2:
        blok2 = R.prompt_block(nomzod2["tender_id"], nomzod2["company_id"])
        check("inson tasdig'i YORLIQLANADI",
              "INSON TASDIQLAGAN]" in blok2, blok2[:200])
        check("tasdiqlangan qatorda model ishonchi KO'RSATILMAYDI",
              all("[ishonch " not in q
                  for q in blok2.splitlines()
                  if "INSON TASDIQLAGAN]" in q),
              "tasdiqlangan talab model ishonchi bilan bir xil ko'rinmasin")

    # --- 5. BO'SH holat — "yo'q" va "ajratilmagan" AJRALADI ---
    yoq = db.scalar("""SELECT t.id FROM tender t WHERE NOT EXISTS
        (SELECT 1 FROM tender_requirement_run r WHERE r.tender_id=t.id)
        LIMIT 1""")
    if yoq:
        check("ajratilmagan tenderda prompt bloki BO'SH",
              R.prompt_block(yoq, 2) == "")
        x = R.summary(yoq, 2)
        check("summary 'ajratilmagan' deb ogohlantiradi",
              "AJRATILMAGAN" in (x.get("izoh") or ""), str(x.get("izoh")))

    # --- 6. `qisqa()` eng ISHONCHLI qiymatni tanlaydi ---
    # O'LCHANGAN XATO: `max()` alifbo bo'yicha tasodifiy qiymat
    # tanlardi va `tolov` ustuniga jarima stavkasi tushib qolgan edi.
    reqsrc = io.open(os.path.join(ROOT_, "api", "requirement.py"),
                     encoding="utf-8").read()
    check("qisqa() DISTINCT ON ishlatadi (max() emas)",
          "DISTINCT ON (attrs->>'tur')" in reqsrc)
    check("INCOTERMS 'bazis' turida, 'muddat' emas",
          '"tur": "bazis"' in io.open(
              os.path.join(ROOT_, "api", "requirement_naqsh.py"),
              encoding="utf-8").read())


# =====================================================================
def test_review():
    """G. KO'RIB CHIQISH — navbat HARAKATLANADIMI.

    Asosiy shart: tenderning barcha talablari ko'rib chiqilgach u
    `v_requirement_review` dan CHIQIB KETISHI kerak. Aks holda navbat
    raqami o'zgarmaydi va ish qilinganini bilib bo'lmaydi.
    """
    section("G. Ko'rib chiqish navbati")

    kompaniyalar = [r["id"] for r in
                    db.query("SELECT id FROM company_account ORDER BY id LIMIT 2")]
    A = kompaniyalar[0]
    B = kompaniyalar[1] if len(kompaniyalar) > 1 else A

    # --- Sinov uchun O'Z tenderimizni tayyorlaymiz ---
    tid = _bosh_ochiq_tender()
    if not tid:
        check("bo'sh tender topildi", False)
        return
    belgila(A, tid)

    # TURLARI HAR XIL: aks holda `qisqa()` ikkitasidan qaysinisini
    # tanlashi NOANIQ bo'ladi (ikkalasi ham tasdiqlangan, faqat ishonch
    # farq qiladi) va sinov TASODIFIY tartibga tayanib qolardi.
    for i, (nom, conf, tur) in enumerate(
            [("Sinov kafolat", 0.90, "kafolat"),
             ("Sinov shablon", 0.35, "muddat")], 1):
        db.execute_returning(R.SQL_UPSERT, {
            "company_id": A, "tender_id": tid, "lot_id": None,
            "source": "document", "method": "llm", "position_no": i,
            "name": nom,
            "attrs": '{"tur":"' + tur + '","qiymat":"12 oy"}',
            "qty": None, "unit": None, "delivery_days": None,
            "is_mandatory": True, "confidence": conf, "raw_snippet": "matn",
            "file_ref": "a.pdf", "char_start": 100, "char_end": 400,
            "model": "sinov", "review_status": "pending_review",
            "mashina_holat": "ajratilgan"})

    # --- 1. Navbatga TUSHDIMI ---
    nav_a, _ = R.review_queue(A, 500)
    navbat = {x["tender_id"] for x in nav_a}
    check("yangi talablar navbatga tushdi", tid in navbat)

    items = R.review_items(tid, A)
    check("ikkala talab ham 'pending'",
          all(x["review_status"] == "pending_review" for x in items), str(items[:1]))

    # NOM bo'yicha olamiz, INDEKS bo'yicha EMAS.
    # `review_items()` ishonch bo'yicha O'SISH tartibida qaytaradi
    # (past ishonchlisi tepada — ko'rib chiqish shundan boshlanadi).
    # Indeksga tayangan sinov noto'g'ri talabni belgilab, keyin
    # "rad etilgan talab promptda qoldi" deb YOLG'ON xato bergan edi.
    def top(nom):
        return next(x for x in R.review_items(tid, A) if x["name"] == nom)

    kafolat_id = top("Sinov kafolat")["id"]
    shablon_id = top("Sinov shablon")["id"]

    # --- 2. IZOLYATSIYA: B kompaniya bularni ko'rmaydi ---
    nav_b, _ = R.review_queue(B, 500)
    check("B kompaniya navbatida yo'q",
          tid not in {x["tender_id"] for x in nav_b})
    check("B kompaniya talablarni ko'rmaydi",
          len(R.review_items(tid, B)) == 0)

    # --- 3. IDOR: B kompaniya A ning talabini o'zgartira olmaydi ---
    # `by=B` beriladi: `by` endi MAJBURIY (soxta tasdiqqa qarshi), va
    # bu sinov aynan IDOR ni tekshiradi — kim ekani NOMA'LUM emas,
    # boshqa kompaniya. SQL sharti uni baribir topa olmaydi.
    natija = R.review_set(kafolat_id, B, "approved", by=B, ishonch="kompaniya_sessiyasi")
    check("B kompaniya A ning talabini O'ZGARTIRA OLMAYDI",
          natija is None, str(natija))
    check("holat o'zgarmadi",
          top("Sinov kafolat")["review_status"] == "pending_review")

    # --- 4. TASDIQLASH ---
    r1 = R.review_set(kafolat_id, A, "approved", by=A, ishonch="kompaniya_sessiyasi")
    check("tasdiqlash ishladi", r1 and r1["review_status"] == "approved",
          str(r1))
    nav_a2, _ = R.review_queue(A, 500)
    navbat2 = {x["tender_id"]: x["kutayotgan"] for x in nav_a2}
    check("navbat SONI kamaydi", navbat2.get(tid) == 1, str(navbat2.get(tid)))

    # --- 5. TUZATISH — qiymatsiz RAD ETILADI ---
    try:
        R.review_set(shablon_id, A, "corrected", corrected="  ", by=A, ishonch="kompaniya_sessiyasi")
        check("qiymatsiz 'corrected' rad etiladi", False, "qabul qilindi")
    except ValueError:
        check("qiymatsiz 'corrected' rad etiladi", True)

    r2 = R.review_set(shablon_id, A, "corrected", corrected="24 oy", by=A, ishonch="kompaniya_sessiyasi")
    check("tuzatish ishladi", r2 and r2["review_status"] == "corrected",
          str(r2))
    tuzatilgan = [x for x in R.review_items(tid, A)
                  if x["review_status"] == "corrected"][0]
    check("tuzatilgan qiymat saqlandi",
          tuzatilgan["corrected_value"] == "24 oy")
    check("ASL qiymat ham QOLADI (J6 uchun)",
          (tuzatilgan["attrs"] or {}).get("qiymat") == "12 oy",
          str(tuzatilgan["attrs"]))

    # --- 6. ASOSIY SHART: tender navbatdan CHIQDIMI ---
    nav_a3, _ = R.review_queue(A, 500)
    navbat3 = {x["tender_id"] for x in nav_a3}
    check("HAMMASI ko'rib chiqilgach tender NAVBATDAN CHIQDI",
          tid not in navbat3,
          "aks holda navbat raqami o'zgarmaydi va ish ko'rinmaydi")

    # --- 7. TUZATILGAN qiymat iste'molchilarga YETADIMI ---
    q = R.qisqa(tid, A)
    check("qisqa() tuzatilgan qiymatni beradi", q["yetkazish"] == "24 oy",
          str(q["yetkazish"]))
    blok = R.prompt_block(tid, A)
    check("prompt_block tuzatilgan qiymatni beradi", "24 oy" in blok, blok[:150])
    check("prompt_block 'INSON TASDIQLAGAN' deb belgilaydi",
          "INSON TASDIQLAGAN" in blok, blok[:200])

    # --- 8. RAD ETILGAN talab HAMMA JOYDAN chiqadi ---
    R.review_set(kafolat_id, A, "rejected", by=A, ishonch="kompaniya_sessiyasi")
    blok2 = R.prompt_block(tid, A)
    check("rad etilgan talab promptga TUSHMAYDI",
          "Sinov kafolat" not in blok2, blok2[:200])
    check("ishonchli() rad etilganni bermaydi",
          all(x["name"] != "Sinov kafolat" for x in R.ishonchli(tid, A)))

    # --- 9. QAROR QATLAMI chegarasi ---
    ishonchli = R.ishonchli(tid, A)
    check("tuzatilgan talab qaror qatlamiga TUSHADI",
          any(x["name"] == "Sinov shablon" for x in ishonchli),
          "inson tasdiqlagan — ishonch darajasidan qat'iy nazar")
    check("ISHONCH_CHEGARA belgilangan", R.ISHONCH_CHEGARA >= 0.80,
          str(R.ISHONCH_CHEGARA))


# =====================================================================
def test_kirish_yetib_boradimi():
    """N. AJRATGICH YOZILDI — LEKIN KIRISH YETIB BORADIMI?

    Yangi sinf. Qadam yozilgan, ulangan, sinovi o'tgan — lekin
    BOSHQA MODUL kirishni filtrlab tashlaydi va ajratgich ma'lumotni
    umuman ko'rmaydi.

    HAQIQATAN SODIR BO'LDI: `tajriba` qoidasi qo'shildi va ishladi,
    lekin `requirement_ai._talab_tsquery()` da guruhlar QATTIQ
    YOZILGAN ro'yxat edi va unda `tajriba` yo'q edi. Tajriba atamasi
    bor bo'laklar TANLANMAY qoldi.

    O'lchov farqi ko'rsatdi: bo'lak skani 50 tenderda talab bor
    dedi, ajratgich 22 ta topdi.
    """
    section("N. Kirish ajratgichga yetib boradimi")

    from api import atama, requirement_ai, requirement_naqsh

    # 1. HAR QOIDA TURI tanlash ro'yxatida bormi.
    #
    #    To'g'ridan-to'g'ri `tur` -> guruh mosligi yo'q (masalan
    #    `moliyaviy` turi `zakalat` guruhidan keladi), shuning uchun
    #    qoidalar ISHLATGAN atama guruhlarini tekshiramiz.
    kerak = set()
    for _nom, _tur, naqsh, _b in requirement_naqsh.QOIDALAR:
        for guruh, prefikslar in atama.GURUH_PREFIKS.items():
            if any(p in naqsh.pattern for p in prefikslar):
                kerak.add(guruh)
    yoq = sorted(kerak - set(atama.TALAB_GURUHLARI))
    check("qoidalar ishlatgan HAR guruh tanlash ro'yxatida",
          not yoq,
          f"ro'yxatda yo'q: {yoq} -> bunday bo'lak TANLANMAYDI")

    # 2. Ro'yxat YAGONA manbadan o'qilsin.
    src = io.open(os.path.join(ROOT, "api", "requirement_ai.py"),
                  encoding="utf-8").read()
    check("tanlash ro'yxati `atama.py` dan keladi",
          "atama.TALAB_GURUHLARI" in src,
          "qattiq yozilgan ro'yxat yangilanmay qolardi")

    # 3. Ro'yxatdagi nomlar HAQIQIY guruh bo'lsin. `.get(g, [])`
    #    noma'lum nomni JIMGINA e'tiborsiz qoldirardi.
    notogri = [g for g in atama.TALAB_GURUHLARI
               if g not in atama.GURUHLAR]
    check("ro'yxatda noma'lum guruh yo'q", not notogri, str(notogri))

    # 4. NAQSH BYUDJETI LLM dan KATTA bo'lsin — u bepul.
    #
    #    O'lchandi: `k = 40` da tajriba talabi bo'lagida BOR 50 ta
    #    ochiq tenderdan 30 tasi ajratildi, 20 tasi tanlovga umuman
    #    tushmadi. `k = 400` da 50/50.
    check("naqsh byudjeti LLM byudjetidan katta",
          requirement_naqsh.NAQSH_K > requirement_ai.TOP_CHUNKS,
          f"naqsh={requirement_naqsh.NAQSH_K}, "
          f"llm={requirement_ai.TOP_CHUNKS} — naqsh BEPUL, "
          "cheklov faqat token sarflaydigan yo'lga kerak")

    # 5. AMALDA: tanlangan bo'lak soni haqiqatan ko'proqmi.
    tid = db.scalar("""SELECT c.tender_id FROM doc_chunk c
        JOIN tender t ON t.id = c.tender_id
        WHERE t.close_at > now()
        GROUP BY c.tender_id HAVING count(*) > 60 LIMIT 1""")
    if tid:
        oz = len(requirement_ai.select_chunks(tid, k=40))
        kop = len(requirement_ai.select_chunks(
            tid, k=requirement_naqsh.NAQSH_K))
        check("katta byudjet KO'PROQ bo'lak beradi", kop > oz,
              f"k=40 -> {oz}, k={requirement_naqsh.NAQSH_K} -> {kop}")


# =====================================================================
def test_inson_mehnati_olchovi():
    """O. `reviewed` va `not pending` BIR NARSA EMAS.

    `tender_requirement` da 1 514 qator `review_status = 'approved'`
    va ularni HECH KIM ko'rmagan — reyestr pozitsiyalari
    AVTO-tasdiqlanadi.

    Ular `review_status <> 'pending'` shartiga QONUNIY tushadi.
    Xato mantiqda emas: "tekshirilgan" va "kutayotgan emas" ni bir
    narsa deb hisoblashda.

    IKKI JOYDA topildi va IKKALASI HAM inson foydasiga og'ardi:

      `v_review_disagreement` : "0% kelishmovchilik" — model
          hech qachon xato qilmaydi degan xulosa;
      vaqt o'lchovi           : `n_reviewed` shishib,
          `sekund_talabga` kam chiqardi.

    Uchinchisi bo'lmasin.
    """
    section("O. Inson mehnati o'lchovi")

    # 1. HOLAT: avto-tasdiq HAQIQATAN bor.
    n_avto = db.scalar("""SELECT count(*) FROM tender_requirement
        WHERE review_status <> 'pending_review'
          AND reviewed_by IS NULL""") or 0
    n_inson = db.scalar("""SELECT count(*) FROM tender_requirement
        WHERE reviewed_by IS NOT NULL""") or 0
    check("avto-tasdiqlangan qatorlar bor (sinov ma'noli)",
          n_avto > 0, f"avto={n_avto}, inson={n_inson}")

    # 2. INSON MEHNATINI o'lchaydigan joylar `reviewed_by` ishlatsin.
    #
    #    STATIK: `n_reviewed` ga son beradigan chaqiruv atrofida
    #    `reviewed_by` bo'lishi SHART.
    src = io.open(os.path.join(ROOT, "api", "main.py"),
                  encoding="utf-8").read()
    i = src.find("review_tugadi(")
    check("`review_tugadi` chaqiruvi topildi", i > 0)
    if i > 0:
        # IZOH QATORLARI OLIB TASHLANADI.
        #
        # Birinchi yurishda skaner O'Z TUSHUNTIRISHINI o'qidi: yangi
        # izohda "Ilgari ... `<> pending` edi" deb yozilgan va skaner
        # uni buzilish deb topdi.
        atrof = "\n".join(
            x for x in src[max(0, i - 1400):i].split("\n")
            if not x.lstrip().startswith("#"))
        check("vaqt o'lchovi `reviewed_by` ni sanaydi",
              "reviewed_by IS NOT NULL" in atrof,
              "`review_status <> 'pending'` avto-tasdiqni ham sanardi")
        check("vaqt o'lchovi `<> 'pending'` bilan SANAMAYDI",
              "review_status <> 'pending'" not in atrof,
              str(atrof[-200:]))

    # 3. KELISHMOVCHILIK ko'rinishi ham.
    sql = io.open(os.path.join(ROOT, "schema_patch_requirement_7.sql"),
                  encoding="utf-8").read()
    # SQL izohlari ham olib tashlanadi — patch sarlavhasida
    # "Ilgari ... edi" deb TUSHUNTIRILGAN.
    kod = "\n".join(x for x in sql.split("\n")
                    if not x.lstrip().startswith("--"))
    # `COMMENT ON` matni ham izoh — u shart emas.
    j2 = kod.find("COMMENT ON VIEW")
    if j2 > 0:
        kod = kod[:j2]
    check("kelishmovchilik ko'rinishi `reviewed_by` ni talab qiladi",
          "r.reviewed_by IS NOT NULL" in kod)
    check("kelishmovchilik ko'rinishi `<> 'pending'` ni ISHLATMAYDI",
          "review_status <> 'pending'" not in kod,
          "avto-tasdiq kelishuv deb sanalardi")

    # 4. `review_bulk` INSON harakati — `reviewed_by` yozsin.
    rsrc = io.open(os.path.join(ROOT, "api", "requirement.py"),
                   encoding="utf-8").read()
    j = rsrc.find("def review_bulk")
    # Bo'shliqlar NORMALLASHTIRILADI va oyna funksiya OXIRIGACHA
    # cho'ziladi: sinov FORMATLASHGA emas, QOIDAGA bog'liq bo'lsin.
    # (Bu tekshiruv 2026-08-30 da aynan shu sababdan yolg'on yiqildi:
    # kod `reviewed_by   = %(by)s` deb tekislangan edi.)
    oyna = rsrc[j:rsrc.find("\ndef ", j + 10)] if j > 0 else ""
    tekis = " ".join(oyna.split())
    check("`review_bulk` `reviewed_by` yozadi",
          "reviewed_by = %(by)s" in tekis,
          "ommaviy tasdiqlash HAM inson harakati")
    check("`review_bulk` `review_action` ham yozadi",
          "review_action = %(amal)s" in tekis,
          "amal holatga MOS bo'lishini baza CHECK bilan talab qiladi")
    check("`review_bulk` `by` siz ISHLAMAYDI",
          "by is None or int(by) <= 0" in tekis,
          "ommaviy amal soxta tasdiq uchun eng qulay yo'l edi")

    # 5. SKANERNI SINAYMIZ.
    yomon = "korilgan = count WHERE review_status <> 'pending'"
    yaxshi = "korilgan = count WHERE reviewed_by IS NOT NULL"
    check("skaner yomon shaklni TOPADI",
          "review_status <> 'pending'" in yomon)
    check("skaner to'g'ri shaklni tutmaydi",
          "review_status <> 'pending'" not in yaxshi)


# =====================================================================
def test_pilot():
    """M. PILOT — namuna aralash va YOPIQ rejim.

    IKKI XAVFNI yumshatadi:

    1. ANCHORING. Interfeys model javobini oldindan ko'rsatsa, inson
       TEKSHIRMAYDI — TASDIQLAYDI. Hujjatda "12 oy (ehtiyot qismlar)"
       va "24 oy (asosiy uzellar)" bo'lsa, birinchisini topib
       tasdiqlab ketadi va MODEL XATOSI GROUND TRUTH ga aylanadi.

    2. NAMUNA QIYSHIQLIGI. Navbat muddat bo'yicha saralangan; tez
       yopiladigan tenderlar ma'lum turdagi bo'lishi mumkin. Shunda
       "6 talab har tenderga" degan o'rtacha ham qiyshiq chiqadi.
    """
    section("M. Pilot to'plami va yopiq rejim")

    # NAVBATI ENG KATTA kompaniya. `ORDER BY id LIMIT 1` NOTO'G'RI
    # bo'lardi: birinchi kompaniyaning navbatida bittagina tender bor,
    # va u holda uchala guruh ham o'sha bitta tenderga qulab tushadi —
    # sinov aralashuvni umuman o'lchamagan bo'lardi.
    A = db.scalar("""
        SELECT company_id FROM v_requirement_review
        GROUP BY company_id ORDER BY count(*) DESC LIMIT 1""")
    n_navbat = db.scalar("""SELECT count(*) FROM v_requirement_review
                            WHERE company_id = %(c)s""", {"c": A}) or 0

    r = R.pilot_yarat(A)
    check("pilot yaratildi", r["jami"] > 0, str(r))
    p = R.pilot_royxat(A)
    check("ro'yxat qaytdi", len(p) == r["jami"], f"{len(p)} != {r['jami']}")

    # --- NAMUNA ARALASH ---
    # Uchala guruh FAQAT navbat yetarlicha katta bo'lganda ajraladi.
    # Kichik navbatda uchala so'rov bir xil tenderlarni qaytaradi va
    # `korilgan` ularni birlashtiradi — bu KUTILGAN xatti-harakat, xato
    # emas. Shuning uchun shart navbat hajmiga bog'langan.
    guruhlar = {x["guruh"] for x in p}
    if n_navbat >= 3 * R.GURUH_N:
        check("uchala guruh ham bor",
              guruhlar == {"muddat", "tasodif", "summa"},
              f"navbat={n_navbat}, guruhlar={guruhlar}")
    else:
        check("kichik navbatda guruhlar qulaydi (kutilgan)",
              len(guruhlar) >= 1, f"navbat={n_navbat}")

    # --- YOPIQ rejim har uch guruhdan ARALASH ---
    # Aks holda kelishmovchilik darajasi bitta guruhning xususiyatini
    # ko'rsatardi, umumiy holatni emas.
    blind = [x for x in p if x["rejim"] == "blind"]
    check("yopiq rejim tenderlari bor", len(blind) > 0, str(len(blind)))
    if len(guruhlar) == 3:
        check("yopiq rejim UCH GURUHDAN aralash",
              {x["guruh"] for x in blind} == guruhlar,
              str({x["guruh"] for x in blind}))
    check("yopiq rejim birinchi tartiblarda",
          max(x["tartib"] for x in blind) <= R.BLIND_N,
          str(sorted(x["tartib"] for x in blind)))

    # --- TO'PLAM MUZLAGAN ---
    # `ON CONFLICT DO NOTHING` o'zi YETARLI EMAS edi: navbat vaqt
    # bilan o'zgaradi (muddatlar o'tadi, ETL qo'shadi, `random()`
    # boshqa qatorlar ustida ishlaydi), shuning uchun ertasi kuni
    # qayta chaqiruv BOSHQA tanlov qildi va 30 ta to'plam 50 ga
    # o'sdi, yopiq ulush 10 dan 16 ga suzdi. Endi mavjud pilot
    # QAYTA HISOBLANMAYDI.
    r2 = R.pilot_yarat(A)
    check("qayta yaratish DUBLIKAT bermaydi", r2["qoshildi"] == 0, str(r2))
    check("mavjud pilot QAYTA HISOBLANMAYDI", r2.get("mavjud") is True,
          str(r2))
    check("to'plam o'zgarmadi", len(R.pilot_royxat(A)) == len(p))
    check("yopiq ulush suzmadi", r2["blind"] == len(blind),
          f"{r2['blind']} != {len(blind)}")

    # Kod xatosi jimgina o'tmasin — qoida BAZADA ham turadi.
    check("tartib NOYOB (baza cheklovi)", bool(db.scalar("""
        SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        WHERE c.relname = 'review_pilot_tartib_idx' AND i.indisunique""")),
        "review_pilot_tartib_idx UNIQUE bo'lishi kerak")
    # TARTIB AVLOD ICHIDA noyob. Avlodlar ORASIDA takrorlanishi
    # SHART — har pilot o'z 1..N tartibini oladi. Guruhlash `avlod`
    # siz bo'lsa ikkinchi avlod paydo bo'lishi bilan sinov YOLG'ON
    # yiqilardi.
    check("takror tartib yo'q (avlod ichida)", not db.query("""
        SELECT 1 FROM review_pilot GROUP BY company_id, avlod, tartib
        HAVING count(*) > 1 LIMIT 1"""))

    # --- AVLOD HAYOT SIKLI ---
    #
    # O'LCHANGAN NUQSON (2026-09-03): `pilot_yarat()` shartи
    # `count(*) > 0` edi va jadvalda holat ustuni UMUMAN YO'Q edi.
    # Ya'ni bitta qator ham yangi pilotni ABADIY to'sardi va yagona
    # yechim tarixiy dalilni SQL bilan o'chirish bo'lardi — bu esa
    # namunani va "30 tenderda mediana" maxrajini yo'q qiladi.
    #
    # Sinov HAQIQIY pilotga TEGMAYDI: o'z sinov kompaniyasini va
    # sintetik avlodlarini ishlatadi.
    ZZ_CID = db.scalar("""
        SELECT id FROM company_account WHERE username = 'zztest_pilot'""")
    if ZZ_CID is None:
        ZZ_CID = db.execute_returning("""
            INSERT INTO company_account (username, company_name,
                                         password_hash, active)
            VALUES ('zztest_pilot', 'ZZTEST pilot',
                    '!sinov-yaroqsiz-xesh', false) RETURNING id""")["id"]
    zz_tid = db.scalar("SELECT id FROM tender WHERE status='open' "
                       " AND close_at > now() LIMIT 1")
    try:
        db.execute_returning("""
            INSERT INTO review_pilot_avlod (company_id, avlod, yaratgan)
            VALUES (%(c)s, 1, 'sinov')
            ON CONFLICT (company_id, avlod) DO NOTHING RETURNING avlod""",
            {"c": ZZ_CID})
        db.execute_returning("""
            INSERT INTO review_pilot (company_id, avlod, tender_id,
                                      guruh, rejim, tartib)
            VALUES (%(c)s, 1, %(t)s, 'tasodif', 'blind', 1)
            ON CONFLICT (company_id, avlod, tender_id) DO NOTHING
            RETURNING tender_id""", {"c": ZZ_CID, "t": zz_tid})

        h = db.query_one("""SELECT holat, tenderlar FROM v_pilot_avlod
                            WHERE company_id=%(c)s AND avlod=1""",
                         {"c": ZZ_CID})
        check("ochiq tenderli avlod -> 'faol'", h["holat"] == "faol",
              str(h))
        r3 = R.pilot_yarat(ZZ_CID)
        check("FAOL avlod bor -> yangisi OCHILMAYDI",
              r3.get("mavjud") is True and r3.get("avlod") == 1, str(r3))

        # ARXIVLASH — qatorlar O'CHIRILMAYDI.
        oldingi_qatorlar = db.scalar("""SELECT count(*) FROM review_pilot
            WHERE company_id=%(c)s AND avlod=1""", {"c": ZZ_CID})
        R.pilot_arxivla(ZZ_CID, 1, kim="sinov")
        h2 = db.query_one("""SELECT holat FROM v_pilot_avlod
                             WHERE company_id=%(c)s AND avlod=1""",
                          {"c": ZZ_CID})
        check("arxivlangach holat 'arxivlandi'",
              h2["holat"] == "arxivlandi", str(h2))
        check("ARXIVLASH QATORLARNI O'CHIRMAYDI (tarix saqlanadi)",
              db.scalar("""SELECT count(*) FROM review_pilot
                  WHERE company_id=%(c)s AND avlod=1""",
                  {"c": ZZ_CID}) == oldingi_qatorlar,
              f"{oldingi_qatorlar} qator")

        # IKKINCHI AVLOD — `tartib` unikal indeksi to'smasligi kerak.
        # 0076 da bu indeks unutilgan edi va ikkinchi avlod JIMGINA
        # yozilmasdi (`ON CONFLICT DO NOTHING` xato ham bermasdi).
        db.execute_returning("""
            INSERT INTO review_pilot_avlod (company_id, avlod, yaratgan)
            VALUES (%(c)s, 2, 'sinov')
            ON CONFLICT (company_id, avlod) DO NOTHING RETURNING avlod""",
            {"c": ZZ_CID})
        yozildi = db.execute_returning("""
            INSERT INTO review_pilot (company_id, avlod, tender_id,
                                      guruh, rejim, tartib)
            VALUES (%(c)s, 2, %(t)s, 'tasodif', 'blind', 1)
            ON CONFLICT (company_id, avlod, tender_id) DO NOTHING
            RETURNING tender_id""", {"c": ZZ_CID, "t": zz_tid})
        check("IKKINCHI avlod yoziladi (tartib indeksi to'smaydi)",
              yozildi is not None, "1-avlodda ham tartib=1 bor edi")
        check("ikkala avlod ham KO'RINADI",
              db.scalar("""SELECT count(*) FROM v_pilot_avlod
                  WHERE company_id=%(c)s""", {"c": ZZ_CID}) == 2)
        # Bir tender IKKI avlodda — rejim ENG YANGISIDAN olinadi.
        check("pilot_rejim eng yangi avloddan oladi",
              R.pilot_rejim(zz_tid, ZZ_CID) == "blind")
    finally:
        db.execute_returning("""DELETE FROM review_pilot
            WHERE company_id=%(c)s RETURNING tender_id""", {"c": ZZ_CID})
        db.execute_returning("""DELETE FROM review_pilot_avlod
            WHERE company_id=%(c)s RETURNING avlod""", {"c": ZZ_CID})

    # --- REJIM serverdan keladi ---
    if blind:
        tid = blind[0]["tender_id"]
        check("pilot_rejim 'blind' qaytaradi",
              R.pilot_rejim(tid, A) == "blind")
    yoq = db.scalar("""SELECT t.id FROM tender t WHERE NOT EXISTS
        (SELECT 1 FROM review_pilot p WHERE p.tender_id = t.id) LIMIT 1""")
    if yoq:
        check("pilotda bo'lmagan tender 'anchored'",
              R.pilot_rejim(yoq, A) == "anchored")

    # --- BLIND_VALUE bir marta yozilgach O'ZGARMAYDI ---
    # Model javobi ochilgach inson fikrini o'zgartirsa ham, ASL
    # mustaqil javob qolishi kerak — aks holda kelishmovchilik
    # darajasi YOLG'ON chiqadi.
    # PILOTDAN TASHQARI tender ustida — pilot tenderlarining talablari
    # sinov oxirida O'CHIRILADI, va inson ochganda bo'sh tender ko'rardi.
    # `blind_value` yozilishi rejimdan qat'i nazar ishlaydi, shuning
    # uchun invariantni istalgan tenderda tekshirish mumkin.
    tashqari = db.scalar("""
        SELECT v.tender_id FROM v_requirement_review v
        WHERE v.company_id = %(c)s AND NOT EXISTS
          (SELECT 1 FROM review_pilot p
            WHERE p.company_id = v.company_id AND p.tender_id = v.tender_id)
        LIMIT 1""", {"c": A})
    if tashqari:
        tid = tashqari
        # O'Z QATORIMIZNI YARATAMIZ, mavjudini O'ZGARTIRMAYMIZ.
        #
        # O'LCHANGAN NUQSON (2026-08-30): ilgari bu blok
        # `R.review_items(tid, A)` dan MAVJUD qatorni olib, unga
        # `approved` keyin `corrected="24 oy"` yozardi. Qator
        # sinovniki emas edi va `tozala()` uni tiklamasdi (u faqat
        # YANGI qatorlarni o'chiradi), ya'ni o'zgarish ABADIY qolardi.
        #
        # Natijada bazada "Litsenziya" talabi `corrected_value='24 oy'`
        # bo'lib turardi — inson tuzatgan deb ko'rinadigan, lekin
        # hech kim yozmagan qiymat. Ya'ni sinovning o'zi aynan shu
        # fayl tekshirayotgan nuqson sinfini ISHLAB CHIQARARDI.
        #
        # Qaysi kompaniyaga tegishi TARTIBGA bog'liq edi: `A` =
        # `company_account ORDER BY id LIMIT 1`, va `import_test.py`
        # o'zining ZZTEST kompaniyasini o'chirgan paytda `A` REAL
        # kompaniyaga tushardi.
        belgila(A, tid)
        db.execute_returning(R.SQL_UPSERT, {
            "company_id": A, "tender_id": tid, "lot_id": None,
            "source": "document", "method": "naqsh", "position_no": 9101,
            "name": "[SINOV] yopiq rejim",
            "attrs": json.dumps({"tur": "kafolat", "qiymat": "12 oy"}),
            "qty": None, "unit": None, "delivery_days": None,
            "is_mandatory": False, "confidence": 0.75, "raw_snippet": None,
            "file_ref": None, "char_start": None, "char_end": None,
            "model": None, "review_status": "pending_review",
            "mashina_holat": "ajratilgan"})
        items = [x for x in R.review_items(tid, A)
                 if x["name"] == "[SINOV] yopiq rejim"]
        if items:
            it = items[0]
            R.review_set(it["id"], A, "approved", by=A, blind_value="12 oy", ishonch="kompaniya_sessiyasi")
            keyin = next(x for x in R.review_items(tid, A)
                         if x["id"] == it["id"])
            check("blind_value yozildi", keyin["blind_value"] == "12 oy",
                  str(keyin["blind_value"]))
            R.review_set(it["id"], A, "corrected", corrected="24 oy",
                         by=A, blind_value="boshqa javob", ishonch="kompaniya_sessiyasi")
            keyin2 = next(x for x in R.review_items(tid, A)
                          if x["id"] == it["id"])
            check("blind_value QAYTA yozilmaydi",
                  keyin2["blind_value"] == "12 oy",
                  f"o'zgardi: {keyin2['blind_value']}")
            check("corrected_value esa yangilanadi",
                  keyin2["corrected_value"] == "24 oy")

    # --- KELISHMOVCHILIK ko'rinishi ---
    kel = db.query("""SELECT ishonch_darajasi, jami, kelishmovchilik_foiz
        FROM v_review_disagreement WHERE company_id = %(c)s""", {"c": A})
    check("kelishmovchilik ko'rinishi ishlaydi", isinstance(kel, list),
          str(kel[:1]))

    # AVTO-TASDIQLANGAN QATOR KELISHUV EMAS.
    #
    # O'LCHANGAN XATO: shart `review_status <> 'pending'` edi va u
    # REYESTR pozitsiyalarini tortardi — ular avto-tasdiqlanadi
    # (`approved`, `confidence = 1.00`, `reviewed_by IS NULL`).
    # Natijada ko'rinish "yuqori ishonchda 12 tadan 0%
    # kelishmovchilik" degan SOXTA raqam berdi, holbuki inson
    # tegmagan qator BITTA HAM yo'q edi.
    #
    # Bu pilotning BOSH KO'RSATKICHI: tuzatilmasa, pilot yurganda
    # ham raqam soxta chiqardi va "0%" ishonchli ko'ringani uchun
    # hech kim shubhalanmasdi.
    n_avto = db.scalar("""
        SELECT count(*) FROM tender_requirement r
        JOIN review_pilot p ON p.tender_id = r.tender_id
                           AND p.company_id = r.company_id
        WHERE p.rejim = 'blind' AND r.reviewed_by IS NULL
          AND r.review_status <> 'pending_review'""") or 0
    n_inson = db.scalar("""
        SELECT count(*) FROM tender_requirement r
        JOIN review_pilot p ON p.tender_id = r.tender_id
                           AND p.company_id = r.company_id
        WHERE p.rejim = 'blind' AND r.reviewed_by IS NOT NULL""") or 0
    n_kel = sum(int(x["jami"] or 0) for x in kel)

    check("avto-tasdiqlangan qator KELISHUV deb sanalmaydi",
          n_kel == n_inson,
          f"ko'rinishda {n_kel}, inson ko'rgani {n_inson}, "
          f"avto-tasdiqlangan {n_avto}")
    if n_avto and not n_inson:
        check("inson tegmaganda ko'rinish BO'SH", not kel,
              f"{n_avto} ta avto-tasdiq bor, lekin ko'rinish {kel}")

    # SO'ROVNING O'ZI to'g'ri shartni ishlatadimi.
    src = io.open(os.path.join(ROOT, "schema_patch_requirement_7.sql"),
                  encoding="utf-8").read()
    check("ko'rinish `reviewed_by IS NOT NULL` shartini ishlatadi",
          "r.reviewed_by IS NOT NULL" in src,
          "`review_status <> 'pending'` YETARLI EMAS")

    # --- O'SISH SUR'ATI ---
    sp = R.review_speed(A)
    check("sutkalik o'sish sanaladi", "sutkalik_osish" in sp, str(sp)[:80])
    check("kunlik quvvat maydoni bor", "kunlik_quvvat" in sp)
    check("quvvat yetadimi degan xulosa bor", "quvvat_yetadimi" in sp,
          "navbat qisqaradimi yoki o'sadimi — eng muhim xulosa")

    # SOVUQ START. Birinchi kunlarda "oxirgi 24 soat" butun navbatni
    # qamrab oladi (604 dan 604) — bu sur'at emas, bir martalik
    # to'ldirish. Yorliqsiz qolsa "kuniga 604 ta kelyapti" deb
    # o'qilardi va xulosa TESKARI chiqardi.
    check("o'sish ishonchliligi yorliqlangan", "osish_ishonchli" in sp,
          str(sp.get("osish_ishonchli")))
    if not sp["osish_ishonchli"]:
        check("sovuq startda IZOH beriladi", bool(sp.get("osish_izohi")),
              str(sp.get("osish_izohi")))
        check("sovuq startda XULOSA CHIQARILMAYDI",
              sp["quvvat_yetadimi"] is None,
              f"ishonchsiz ma'lumotdan xulosa: {sp['quvvat_yetadimi']}")


# =====================================================================
def test_vaqt_olchovi():
    """L. KO'RIB CHIQISH VAQTI o'lchanadimi.

    Pilotning yagona noma'lum raqami — bir tenderni ko'rib chiqish
    vaqti. Undan "har talabni inson tasdiqlaydi" modeli ishlaydimi
    degan savolning javobi chiqadi:

        ~2 daqiqa  -> 611 tender = ~20 soat  -> real
        ~10 daqiqa -> ~100 soat              -> namuna asosida

    NEGA ALOHIDA JADVAL: `reviewed_at` faqat OXIRGI bosishni biladi.
    Tenderni ochib, hujjatni o'qib, birinchi tugmani bosgunicha o'tgan
    vaqt — ko'rib chiqishning ENG KATTA qismi — u yerda YO'Q.
    """
    section("L. Ko'rib chiqish vaqti")

    A = db.scalar("SELECT id FROM company_account ORDER BY id LIMIT 1")
    tid = _bosh_ochiq_tender()
    if not tid:
        check("bo'sh tender topildi", False)
        return
    belgila(A, tid)
    db.execute_returning("""DELETE FROM requirement_review_open
        WHERE company_id=%(c)s AND tender_id=%(t)s RETURNING tender_id""",
        {"c": A, "t": tid})

    for i in range(1, 3):
        db.execute_returning(R.SQL_UPSERT, {
            "company_id": A, "tender_id": tid, "lot_id": None,
            "source": "document", "method": "llm", "position_no": i,
            "name": f"Vaqt sinovi {i}",
            "attrs": '{"tur":"kafolat","qiymat":"12 oy"}',
            "qty": None, "unit": None, "delivery_days": None,
            "is_mandatory": False, "confidence": 0.90, "raw_snippet": "m",
            "file_ref": "a.pdf", "char_start": 1, "char_end": 2,
            "model": "sinov", "review_status": "pending_review",
            "mashina_holat": "ajratilgan"})

    # --- OCHILISH yoziladi ---
    R.review_ochildi(tid, A)
    ochildi = db.query_one("""SELECT opened_at, finished_at FROM
        requirement_review_open WHERE company_id=%(c)s AND tender_id=%(t)s""",
        {"c": A, "t": tid})
    check("ochilish vaqti yozildi", ochildi is not None
          and ochildi["opened_at"] is not None)
    check("tugash hali BO'SH", ochildi and ochildi["finished_at"] is None)

    # --- QAYTA ochish vaqtni QAYTARMAYDI ---
    # Aks holda sahifani yangilash o'lchovni nolga tushirardi va
    # natija haqiqiydan PAST chiqardi.
    birinchi = ochildi["opened_at"]
    R.review_ochildi(tid, A)
    ikkinchi = db.scalar("""SELECT opened_at FROM requirement_review_open
        WHERE company_id=%(c)s AND tender_id=%(t)s""", {"c": A, "t": tid})
    check("qayta ochish vaqtni QAYTARMAYDI", birinchi == ikkinchi,
          f"{birinchi} -> {ikkinchi}")

    # --- Tugash ---
    for x in R.review_items(tid, A):
        if x["name"].startswith("Vaqt sinovi"):
            R.review_set(x["id"], A, "approved", by=A, ishonch="kompaniya_sessiyasi")
    R.review_tugadi(tid, A, 2)
    tugadi = db.query_one("""SELECT finished_at, n_reviewed FROM
        requirement_review_open WHERE company_id=%(c)s AND tender_id=%(t)s""",
        {"c": A, "t": tid})
    check("tugash vaqti yozildi", tugadi and tugadi["finished_at"] is not None)
    check("ko'rilgan talab soni yozildi", tugadi and tugadi["n_reviewed"] == 2)

    # --- Hisobotga TUSHADI ---
    tez = db.query_one("""SELECT sekund, sekund_talabga FROM v_review_speed
        WHERE tender_id=%(t)s AND company_id=%(c)s""", {"t": tid, "c": A})
    check("hisobotga tushdi", tez is not None, str(tez))
    check("sekund manfiy emas", tez and float(tez["sekund"]) >= 0)

    # --- `review_speed()` MEDIANA beradi ---
    sp = R.review_speed(A)
    check("o'lchangan tender sanaladi", sp["olchangan_tender"] >= 1, str(sp))
    check("mediana maydoni bor", "mediana_sekund" in sp)
    check("navbatda qolgan sanaladi", sp["navbatda_qolgan"] >= 0)
    # 10 tadan kam bo'lsa OGOHLANTIRADI — bitta o'lchov bilan
    # 611 tenderni bashorat qilish xato bo'lardi.
    if sp["olchangan_tender"] < 10:
        check("kam o'lchovda OGOHLANTIRADI", bool(sp["izoh"]), str(sp["izoh"]))

    db.execute_returning("""DELETE FROM requirement_review_open
        WHERE company_id=%(c)s AND tender_id=%(t)s RETURNING tender_id""",
        {"c": A, "t": tid})


# =====================================================================
def test_eskirish():
    """K. `pending` KIRISH O'ZGARISHINI sezadimi.

    O'LCHANGAN XATO: `pending` faqat "yurgizilganmi" ga qarardi,
    "KIRISH O'ZGARDIMI" ga emas.

    Ssenariy (haqiqatan bo'ldi):
      1. tenderda hujjat matni YO'Q -> naqsh yurishi 'no_text'
      2. keyinroq `etl_doc_text` matnni chiqardi, bo'laklar paydo bo'ldi
      3. `pending` uni "allaqachon yurgizilgan" deb O'TKAZIB YUBORDI
      -> 236 ta tenderning talablari MANGU yo'q bo'lardi

    Bu §16.49 dagi "tender_embedding orqada qoldi" bilan bir sinf:
    quvur ishlaydi, lekin YANGI MA'LUMOTGA YETIB BORMAYDI.
    """
    section("K. Kirish o'zgarishini sezish")

    A = db.scalar("SELECT id FROM company_account ORDER BY id LIMIT 1")

    # Bo'lagi BOR, lekin talabi yo'q, va MUDDATI O'TMAGAN tender.
    #
    # `close_at > now()` SHARTI SHART: `SQL_PENDING` yopilgan tenderni
    # to'g'ri chiqarib tashlaydi, ya'ni yopiq tender tanlansa sinov
    # KOD XATOSI EMAS, TASODIFIY HOLAT tufayli yiqilardi. Aynan
    # shunday bo'ldi: tanlangan tender 13 kun oldin yopilgan edi va
    # sinov "qayta tanlanmadi" deb xato berdi.
    OCHIQ = "(t.close_at IS NULL OR t.close_at > now())"
    tid = db.scalar(f"""SELECT c.tender_id FROM doc_chunk c
        JOIN tender t ON t.id = c.tender_id
        WHERE {OCHIQ}
          AND NOT EXISTS (SELECT 1 FROM tender_requirement_run r
                          WHERE r.tender_id = c.tender_id
                            AND r.company_id = %(a)s)
        LIMIT 1""", {"a": A})
    if not tid:
        # Hammasi ishlangan — sun'iy holat quramiz (baribir OCHIQ).
        tid = db.scalar(f"""SELECT c.tender_id FROM doc_chunk c
            JOIN tender t ON t.id = c.tender_id
            WHERE {OCHIQ} LIMIT 1""")
    if not tid:
        check("bo'lagi bor OCHIQ tender topildi", False,
              "sinov ma'lumoti yo'q — eskirish tekshirilmadi")
        return
    belgila(A, tid)

    # 1. 'no_text' holatini QO'YAMIZ (matn yo'q edi degan holat)
    R._run_yoz(A, tid, "naqsh", "no_text", 0, None, None,
               error="talabga oid bo'lak yo'q")
    check("'no_text' yozildi",
          (R.run_info(tid, A, method="naqsh") or {}).get("status") == "no_text")

    # 2. Endi bo'laklar BOR — `pending` uni QAYTA TANLASHI kerak
    bor = db.scalar("SELECT count(*) FROM doc_chunk WHERE tender_id=%(t)s",
                    {"t": tid})
    check("tenderda bo'lak bor", bor > 0, str(bor))
    navbat = {x["id"] for x in R.pending(A, 5000, method="naqsh")}
    check("'no_text' + bo'lak BOR -> QAYTA tanlanadi", tid in navbat,
          "aks holda talablari mangu yo'q bo'lardi")

    # 3. Muvaffaqiyatli yurishdan keyin QAYTA tanlanmasin
    R._run_yoz(A, tid, "naqsh", "ok", 5, 0.75, "hash1")
    navbat2 = {x["id"] for x in R.pending(A, 5000, method="naqsh")}
    check("'ok' dan keyin qayta tanlanmaydi", tid not in navbat2)


# =====================================================================
def test_yorliqlash():
    """J. HUJJAT TURI yorlig'i — moslashtiruv ground truth i.

    NEGA TASDIQLASH BILAN BIRGA: `compliance` moslashtiruvi
    ("ISO 14001 talab etiladi" -> `doc_type='iso_14001'`) NOANIQ
    vazifa, ya'ni o'z evalini talab qiladi. O'sha evalning manbai —
    inson yorliqlagan to'plam.

    Navbatni yorliqsiz yurgizsak, keyin O'SHA talablarni compliance
    uchun QAYTADAN ko'rish kerak bo'lardi — inson vaqti ikki marta.
    """
    section("J. Hujjat turi yorlig'i")

    # --- Lug'at CHEKLI va compliance bilan bir xil ---
    from api import compliance
    vocab = R.doc_type_vocab()
    check("lug'at compliance.DOC_TYPES dan quriladi",
          all(d["code"] in vocab for d in compliance.DOC_TYPES),
          f"{len(vocab)} tur")
    check("'yoq' va 'boshqa' bor",
          "yoq" in vocab and "boshqa" in vocab, str(vocab[-3:]))
    opts = R.doc_type_options()
    check("har turda o'qiladigan nom bor",
          all(o.get("label") for o in opts), str(opts[:1]))

    # --- Yozish ---
    A = db.scalar("SELECT id FROM company_account ORDER BY id LIMIT 1")
    tid = _bosh_ochiq_tender()
    if not tid:
        check("bo'sh tender topildi", False)
        return
    belgila(A, tid)

    db.execute_returning(R.SQL_UPSERT, {
        "company_id": A, "tender_id": tid, "lot_id": None,
        "source": "document", "method": "llm", "position_no": 1,
        "name": "ISO 14001 sertifikati",
        "attrs": '{"tur":"sertifikat","qiymat":"ISO 14001"}',
        "qty": None, "unit": None, "delivery_days": None,
        "is_mandatory": True, "confidence": 0.90, "raw_snippet": "matn",
        "file_ref": "a.pdf", "char_start": 1, "char_end": 2,
        "model": "sinov", "review_status": "pending_review",
            "mashina_holat": "ajratilgan"})

    def olish():
        return next(x for x in R.review_items(tid, A)
                    if x["name"] == "ISO 14001 sertifikati")

    check("yangi talabda doc_type NULL", olish()["doc_type"] is None)
    check("NULL yorliqlangan to'plamga TUSHMAYDI",
          all(x["requirement_id"] != olish()["id"] for x in R.labeled(A)))

    kod = next(d["code"] for d in compliance.DOC_TYPES)
    R.review_set(olish()["id"], A, "approved", by=A, doc_type=kod, ishonch="kompaniya_sessiyasi")
    x = olish()
    check("yorliq saqlandi", x["doc_type"] == kod, str(x["doc_type"]))
    check("yorliqlangan to'plamga TUSHDI",
          any(y["requirement_id"] == x["id"] for y in R.labeled(A)))

    # --- Yorliq TASODIFAN o'chib ketmasin ---
    R.review_set(x["id"], A, "approved", by=A, ishonch="kompaniya_sessiyasi")          # doc_type BERILMADI
    check("doc_type berilmasa ESKISI qoladi",
          olish()["doc_type"] == kod, str(olish()["doc_type"]))

    # --- Noma'lum qiymat RAD ETILADI ---
    try:
        R.review_set(x["id"], A, "approved", by=A, doc_type="sehrli_hujjat", ishonch="kompaniya_sessiyasi")
        check("noma'lum hujjat turi rad etiladi", False, "qabul qilindi")
    except ValueError:
        check("noma'lum hujjat turi rad etiladi", True)

    # --- 'yoq' NULL DAN FARQ QILADI ---
    # NULL = "hali so'ralmagan", 'yoq' = "inson qaradi va tegishli emas
    # dedi". Bu farq §16.44 dagi "topilmadi va ajratilmagan" bilan
    # bir sinf.
    R.review_set(x["id"], A, "approved", by=A, doc_type="yoq", ishonch="kompaniya_sessiyasi")
    check("'yoq' saqlanadi", olish()["doc_type"] == "yoq")
    check("'yoq' ham YORLIQ — to'plamga tushadi",
          any(y["requirement_id"] == x["id"] and y["doc_type"] == "yoq"
              for y in R.labeled(A)),
          "aks holda 'tegishli emas' javobi yo'qolib ketardi")


# =====================================================================
def test_qayta_ajratish():
    """I. QAYTA AJRATISH insonning ishini buzmasinmi.

    IKKI TUYNUK bor edi, ikkalasi ham `ON CONFLICT DO UPDATE` da:

      1-TUYNUK: `review_status` EXCLUDED dan yangilansa, tasdiqlangan
        talab yana `pending` ga tushardi — butun ko'rib chiqish ishi
        bekor bo'lardi.

      2-TUYNUK (XAVFLIROQ): faqat holatni saqlash YETARLI EMAS.
        Hujjat yangilanib qiymat o'zgarsa, `approved` yorlig'i INSON
        KO'RMAGAN qiymatga o'tadi — va bu navbatda KO'RINMAYDI.

    Bu sinov ikkalasini ham qulflaydi.
    """
    section("I. Qayta ajratish va inson qarori")

    A = db.scalar("SELECT id FROM company_account ORDER BY id LIMIT 1")
    tid = _bosh_ochiq_tender()
    if not tid:
        check("bo'sh tender topildi", False)
        return
    belgila(A, tid)

    def yoz(qiymat: str):
        db.execute_returning(R.SQL_UPSERT, {
            "company_id": A, "tender_id": tid, "lot_id": None,
            "source": "document", "method": "llm", "position_no": 1,
            "name": "Qayta sinov", "attrs":
                '{"tur":"kafolat","qiymat":"' + qiymat + '"}',
            "qty": None, "unit": None, "delivery_days": None,
            "is_mandatory": True, "confidence": 0.90,
            "raw_snippet": "matn", "file_ref": "a.pdf",
            "char_start": 1, "char_end": 2, "model": "sinov",
            "review_status": "pending_review",
            "mashina_holat": "ajratilgan"})

    def olish():
        return next(x for x in R.review_items(tid, A)
                    if x["name"] == "Qayta sinov")

    # --- 1-TUYNUK: qiymat O'ZGARMASA tasdiq SAQLANADI ---
    yoz("12 oy")
    R.review_set(olish()["id"], A, "approved", by=A, ishonch="kompaniya_sessiyasi")
    yoz("12 oy")                                   # aynan o'sha qiymat
    x = olish()
    check("qiymat o'zgarmasa TASDIQ saqlanadi",
          x["review_status"] == "approved", str(x["review_status"]))

    # --- 2-TUYNUK: qiymat O'ZGARSA tasdiq BEKOR ---
    yoz("24 oy")                                   # hujjat yangilandi
    x = olish()
    check("qiymat o'zgarsa tasdiq BEKOR bo'ladi",
          x["review_status"] == "pending_review", str(x["review_status"]))
    check("jurnalga 'qiymat_ozgardi' yozildi",
          "qiymat_ozgardi" in (x["review_note"] or ""), str(x["review_note"]))
    check("izohda ESKI va YANGI qiymat bor",
          "12 oy" in (x["review_note"] or "")
          and "24 oy" in (x["review_note"] or ""), str(x["review_note"]))
    nav_a4, _ = R.review_queue(A, 500)
    check("tender NAVBATGA QAYTDI",
          tid in {q["tender_id"] for q in nav_a4})

    # --- TUZATILGAN qiymat qayta ajratishda YO'QOLMAYDI ---
    R.review_set(olish()["id"], A, "corrected", corrected="36 oy", by=A, ishonch="kompaniya_sessiyasi")
    yoz("48 oy")                                   # yana yangilandi
    x = olish()
    check("inson tuzatgan qiymat SAQLANADI",
          x["corrected_value"] == "36 oy", str(x["corrected_value"]))
    check("lekin qayta ko'rib chiqishga QAYTADI",
          x["review_status"] == "pending_review", str(x["review_status"]))


# =====================================================================
def test_navbat_filtri():
    """KO'RIK NAVBATINING FILTRI — va MUDDATI O'TGAN tender masalasi.

    O'LCHANGAN NUQSON (2026-09-03). `v_requirement_review` da muddat
    sharti YO'Q, tartib esa `close_at` bo'yicha O'SISH — ya'ni eng
    erta yopilganlar ENG TEPADA. Natijada ko'rik navbatining BUTUN
    BIRINCHI SAHIFASI allaqachon yopilgan tenderlardan iborat edi:

        jami 989 · ochiq 455 · MUDDATI O'TGAN 534
        birinchi 10 qatorning 10 tasi ham o'tgan

    Ya'ni ko'ruvchining ko'rinadigan butun ish yuki O'LIK tenderlar
    edi va buni hech narsa ko'rsatmasdi. Broker navbatida bu nuqson
    yo'q (`v_routing_queue` muddatni tekshiradi) — ikki navbat bir
    xil qoidada bo'lsin.
    """
    section("N. Ko'rik navbatining filtri")

    A = db.scalar("""SELECT company_id FROM v_requirement_review
                     GROUP BY company_id ORDER BY count(*) DESC LIMIT 1""")
    check("o'lchov bazasi bor: navbati bor kompaniya topildi", bool(A), str(A))
    if not A:
        return

    # STRUKTURAVIY: qidiruv YAGONA quruvchidan olinsin.
    src = io.open(os.path.join(ROOT, "api", "requirement.py"),
                  encoding="utf-8").read()
    gavda = src[src.index("def _review_queue_where"):
                src.index("def review_queue")]
    check("qidiruv `queries.build_text_search` dan",
          "build_text_search(" in gavda)
    check("navbat o'z `LIKE` ini YOZMAYDI", "LIKE ANY" not in gavda,
          "qidiruv qoidasi ikki joyda ajralib ketardi")

    rows, jami = R.review_queue(A, 500)
    check("filtrsiz navbat bo'sh emas", jami > 0, str(jami))
    if not jami:
        return

    # --- MUDDATI O'TGAN STANDART HOLDA CHIQARILGAN -------------------
    # ASOSIY TEKSHIRUV. Qatorlarning O'ZIDA tekshiriladi, sanoqda
    # emas: "jami kamaydi" `LIMIT` dan ham kelib chiqishi mumkin.
    otgan_id = db.scalar("""
        SELECT v.tender_id FROM v_requirement_review v
        JOIN tender t ON t.id = v.tender_id
        WHERE v.company_id = %(c)s
          AND t.close_at IS NOT NULL AND t.close_at <= now()
        LIMIT 1""", {"c": A})
    check("o'lchov bazasi bor: muddati o'tgan tender navbatda mavjud",
          bool(otgan_id), str(otgan_id))
    if otgan_id:
        check("STANDART holda muddati o'tgan tender navbatda YO'Q",
              otgan_id not in {x["tender_id"] for x in rows},
              "ko'ruvchining ish yuki o'lik tenderlar bo'lardi")
        keng, jami_keng = R.review_queue(A, 500, otgan=True)
        check("`otgan=True` bilan u QAYTADI — yashirilmagan",
              otgan_id in {x["tender_id"] for x in keng})
        check("`otgan=True` qamrovi kengroq", jami_keng >= jami,
              f"{jami_keng} >= {jami}")

    # --- JAMI SAHIFADAN MUSTAQIL -------------------------------------
    kichik, jami_kichik = R.review_queue(A, 3)
    check("`jami` SAHIFA hajmiga bog'liq EMAS", jami_kichik == jami,
          f"limit=3 -> {jami_kichik}, limit=500 -> {jami}")
    check("sahifa chegarani hurmat qiladi", len(kichik) <= 3, str(len(kichik)))

    # --- QIDIRUV -----------------------------------------------------
    nom = None
    for x in rows:
        if x["tender_name"] and len(x["tender_name"].split()) > 1:
            nom = x["tender_name"].split()[0]
            break
    check("o'lchov bazasi bor: qidiriladigan nom topildi", bool(nom), str(nom))
    if nom:
        _, j = R.review_queue(A, 500, q=nom)
        check("qidiruv natija beradi", j > 0, f"q={nom!r} -> {j}")
        check("qidiruv natijani TORAYTIRADI", j <= jami, f"{j} <= {jami}")

    # --- FILTRLAR TORAYTIRADI ----------------------------------------
    _, j_past = R.review_queue(A, 500, faqat_past=True)
    check("`past` natijani toraytiradi", j_past <= jami, f"{j_past} <= {jami}")
    _, j_naqsh = R.review_queue(A, 500, manba="naqsh")
    check("`manba=naqsh` natijani toraytiradi", j_naqsh <= jami)
    _, j_ikki = R.review_queue(A, 500, faqat_past=True, manba="naqsh")
    check("ikki filtr VA bilan bog'lanadi", j_ikki <= j_past,
          f"past+manba={j_ikki} > past={j_past}")

    # --- NOTO'G'RI QIYMAT JIMGINA O'TMASIN ---------------------------
    tutildi = False
    try:
        R.review_queue(A, 5, manba="sehrli")
    except Exception:                                       # noqa: BLE001
        tutildi = True
    check("noto'g'ri `manba` RAD ETILADI", tutildi)

    # --- MANBA SONLARI YOLG'ON GAPIRMASIN ----------------------------
    # O'LCHANGAN NUQSON (2026-09-03). "Manba" filtri ko'rinishdagi
    # `naqshdan`/`modeldan` ustunlariga qarab qo'shilgan edi, lekin
    # ular HAQIQATAN farq qiladimi degan savol berilmagan. Javob:
    # YO'Q — kutayotgan talablarning HAMMASI `naqsh` dan (LLM
    # qatlami pullik va qulflangan). Ya'ni "Naqshdan" jamini
    # o'zgartirmasdi, "Modeldan" esa ro'yxatni bo'shatardi va
    # foydalanuvchi ikkalasini ham BUZUQ deb xabar qildi.
    #
    # Filtr olib tashlanmadi, ROST GAPIRADIGAN qilindi: interfeys
    # har variant yoniga sonini yozadi va nolini o'chiradi.
    #
    # ASOSIY INVARIANT: yorliqdagi son AYNAN o'sha filtr beradigan
    # natija bo'lsin. Ular ajralsa yorliq yolg'on bo'lardi — bu
    # filtrning o'zi ishlamaganidan YOMONROQ.
    manbalar = R.review_queue_manbalar(A)
    for nom in ("naqsh", "llm"):
        _, j = R.review_queue(A, 500, manba=nom)
        check(f"`manbalar[{nom}]` filtr natijasiga TENG",
              manbalar[nom] == j, f"yorliq={manbalar[nom]}, natija={j}")

    # SONLAR BOSHQA FILTRLARNI HISOBGA OLADI: savol "shu manbani
    # tanlasam nechta qoladi", "umuman nechta bor" emas.
    m_past = R.review_queue_manbalar(A, faqat_past=True)
    for nom in ("naqsh", "llm"):
        _, j = R.review_queue(A, 500, manba=nom, faqat_past=True)
        check(f"`past` bilan ham `manbalar[{nom}]` TENG",
              m_past[nom] == j, f"yorliq={m_past[nom]}, natija={j}")
        check(f"`past` bilan `manbalar[{nom}]` kengaymaydi",
              m_past[nom] <= manbalar[nom])

    # INTERFEYS NOLNI O'CHIRSIN — son yozilib, tugma bosiladigan
    # qolsa foydalanuvchi yana "ishlamayapti" deb o'qirdi.
    tsx = io.open(os.path.join(ROOT, "frontend", "src", "components",
                               "RequirementReview.tsx"), encoding="utf-8").read()
    check("interfeys manba sonini KO'RSATADI", "manbalar.naqsh" in tsx
          and "manbalar.llm" in tsx)
    check("interfeys NOL variantni O'CHIRADI",
          "disabled={!manbalar.naqsh}" in tsx
          and "disabled={!manbalar.llm}" in tsx,
          "bosiladigan lekin natijasiz variant BUZUQ deb o'qiladi")

    # --- "SIZGA MOS" FILTRI -------------------------------------------
    # To'plam ta'rifi `kodlash.mos_tender_idlari()` da — bu yerda
    # TAKRORLANMAYDI. Hudud qoidasi ikki joyda yozilgani uchun
    # "Sizga mos" va navbat boshqa-boshqa javob bergan edi.
    from api import kodlash

    src2 = io.open(os.path.join(ROOT, "api", "requirement.py"),
                   encoding="utf-8").read()
    rq = src2[src2.index("def review_queue"):]
    rq = rq[:rq.index("\ndef ", 1)]
    check("ko'rik navbati `mos_tender_idlari()` ni chaqiradi",
          "mos_tender_idlari(" in rq)
    check("ko'rik navbati katalog moslashuvini QAYTA YOZMAYDI",
          "good_code" not in rq and "v_catalog_code_active" not in rq)

    kat = kodlash.mos_tender_idlari(A)
    check("o'lchov bazasi bor: katalogga mos tender topildi",
          len(kat) > 0, f"{len(kat)} ta")
    if kat:
        k_rows, k_jami = R.review_queue(A, 500, katalog=True)
        tashqari = [x["tender_id"] for x in k_rows
                    if x["tender_id"] not in kat]
        check("filtr FAQAT katalogdagilarni qaytaradi", not tashqari,
              f"begona: {tashqari[:5]}")
        # ASOSIY XULQ: navbatda bo'lgan katalog tenderi CHIQSIN.
        kutilgan = kat & {x["tender_id"] for x in rows}
        check("navbatdagi HAR katalog tenderi filtrda CHIQADI",
              kutilgan <= {x["tender_id"] for x in k_rows},
              f"tushib qolgan: "
              f"{sorted(kutilgan - {x['tender_id'] for x in k_rows})[:5]}")
        check("katalog filtri natijani TORAYTIRADI", k_jami <= jami,
              f"{k_jami} <= {jami}")

        # `otgan` BILAN BIRGA: katalog to'plami ham kengaysin.
        # Aks holda ikki filtr birga qo'yilganda natija HAR DOIM
        # bo'sh chiqardi va sabab ko'rinmasdi.
        _, k_otgan = R.review_queue(A, 500, katalog=True, otgan=True)
        check("`katalog + otgan` qamrovi kengroq", k_otgan >= k_jami,
              f"{k_otgan} >= {k_jami}")

    # KATALOGI BO'SH ijarachida filtr NOL bersin — "filtrsiz" EMAS.
    begona = None
    for r in db.query("SELECT id FROM company_account "
                      "WHERE id <> %(c)s ORDER BY id LIMIT 10", {"c": A}):
        if not kodlash.mos_tender_idlari(r["id"]):
            begona = r["id"]
            break
    check("o'lchov bazasi bor: katalogi bo'sh ijarachi topildi",
          begona is not None, "bo'sh to'plam yo'li SINALMADI")
    if begona is not None:
        _, j_bosh = R.review_queue(begona, 500, katalog=True)
        check("katalogi BO'SH ijarachida filtr NOL beradi", j_bosh == 0,
              f"{j_bosh} ta chiqdi — bo'sh to'plam 'filtrsiz' ga aylandi")


def test_indeks_taqiqi():
    """H. Sinov fayllarida INDEKS bo'yicha tanlash bo'lmasin.

    QOIDA: `items[0]` emas, nom yoki id bo'yicha `next(...)`.

    NEGA: tartib o'zgarsa indeks JIMGINA boshqa narsani o'lchaydi.
    §16.44 da aynan shunday bo'ldi — `review_items()` ishonch bo'yicha
    O'SISH tartibida qaytaradi, birinchi element esa men o'ylagan
    talab emas edi. Sinov noto'g'ri qatorni belgilab, "rad etilgan
    talab promptda qoldi" degan YOLG'ON xato berdi.

    Tartib o'zgarsa sinov YIQILSIN, jimgina boshqa narsani o'lchamasin.
    """
    section("H. Sinov uslubi — indeks bo'yicha tanlash taqiqi")

    NL = chr(10)
    NAQSH = r"(review_items|list_for|review_queue)\([^)]*\)\[\d+\]"

    xom = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    # IKKI XIL QATOR CHIQARILADI:
    #
    # 1. IZOHLAR — skaner NASRNI emas, KODNI tekshiradi. Birinchi
    #    urinishda u o'z izohidagi misolni buzilish deb topdi.
    #
    # 2. `skaner-namuna` belgisi bor qatorlar — bu skanerning O'Z
    #    sinov namunalari, ya'ni ATAYLAB buzuq misollar. Ularsiz
    #    "skaner ishlayaptimi" degan savolga javob bo'lmaydi.
    #    Belgi ANIQ va grep bilan topiladi — yashirin istisno emas.
    manba = NL.join(q for q in xom.split(NL)
                    if not q.lstrip().startswith("#")
                    and "skaner-namuna" not in q)

    yomon = re.findall(r"\b(items|rows|lst\d*|natijalar)\[(\d+)\]\[", manba)
    check("DB ro'yxatidan indeks bo'yicha tanlash yo'q", not yomon,
          f"topildi: {yomon[:5]}")

    yomon2 = re.findall(NAQSH, manba)
    check("funksiya natijasidan indeks bo'yicha tanlash yo'q", not yomon2,
          f"topildi: {yomon2[:5]}")

    # SKANERNING O'ZINI SINAYMIZ — u haqiqiy buzilishni TOPADIMI.
    # Aks holda "0 ta buzilish" degani "skaner ishlamayapti" bo'lishi
    # mumkin va biz buni bilmasdik. Bu bo'lim shu sinf uchun yozilgan.
    yomon_misol = 'x = R.review_items(t, c)[0]["name"]'   # skaner-namuna
    yaxshi_misol = ('x = next(i for i in R.review_items(t, c) '
                    'if i["id"] == kutilgan)')
    check("skaner haqiqiy buzilishni TOPADI",
          bool(re.search(NAQSH, yomon_misol)), yomon_misol)
    check("skaner to'g'ri uslubni tutmaydi",
          not re.search(NAQSH, yaxshi_misol), yaxshi_misol)


# =====================================================================
def tozala():
    """FAQAT sinov YARATGAN qatorlarni o'chiradi.

    O'LCHANGAN NUQSON (2026-08-30): ilgari butun (kompaniya, tender)
    juftligi o'chirilardi — `DELETE ... WHERE company_id=.. AND
    tender_id=..`. Sinov kompaniyani `company_account ORDER BY id
    LIMIT 2` bilan oladi va u REAL ishlab turgan kompaniyaga
    (id=2) tushadi, tender ham real. Ya'ni sinov o'z ma'lumotini
    emas, MIJOZNIKINI o'chirardi: 8785 -> 8736 (44 qator).

    Nuqson JIMGINA edi — sinov yashil qolardi, chunki u o'chirilgan
    narsani tekshirmasdi. Endi sinovdan OLDIN mavjud bo'lgan id lar
    eslab qolinadi va ularga TEGILMAYDI.
    """
    n = ochirildi = tegilmadi = 0
    for cid, tid in set(_yozilgan):
        oldin = _oldingi_idlar.get((cid, tid), set())
        hozir = {r["id"] for r in db.query(
            "SELECT id FROM tender_requirement "
            "WHERE company_id=%(c)s AND tender_id=%(t)s",
            {"c": cid, "t": tid})}
        yangi = hozir - oldin
        tegilmadi += len(hozir & oldin)
        if yangi:
            db.execute_returning(
                "DELETE FROM tender_requirement WHERE id = ANY(%(ids)s) "
                "RETURNING id", {"ids": list(yangi)})
            ochirildi += len(yangi)
        # Yurish jurnali: juftlikda oldin HECH NARSA bo'lmagan
        # bo'lsagina o'chiramiz — aks holda real yurish tarixi
        # yo'qolardi.
        if not oldin:
            db.execute_returning(
                "DELETE FROM tender_requirement_run WHERE company_id=%(c)s "
                "AND tender_id=%(t)s RETURNING company_id", {"c": cid, "t": tid})
        n += 1
    # FIKSTURA TENDERI HAM O'CHIRILADI.
    #
    # U `status='open'` va muddati 30 kun keyin — ya'ni tozalanmasa
    # tender ro'yxatida va broker navbatida KO'RINARDI. Sinov o'z
    # ma'lumotini o'zi qursa, o'zi YIG'ISHTIRISHI ham shart.
    #
    # `tender_requirement` dan keyin o'chiriladi: tartib muhim,
    # aks holda tashqi kalit to'sardi.
    zz = db.execute_returning(
        "DELETE FROM tender WHERE id = %(id)s RETURNING id",
        {"id": ZZ_TENDER_ID})
    # TOZALANGANI TASDIQLANADI — "o'chirdim" yetarli emas.
    #
    # `DELETE` yiqilishi mumkin (tashqi kalit, huquq, ulanish) va
    # `finally` ichida bo'lgani uchun bu JIMGINA o'tib ketardi:
    # sinov "PASS" deb tugab, korpusda ochiq ZZTEST tenderi
    # qolardi. Shuning uchun YO'QLIGI alohida so'raladi.
    #
    # Bu 2-sinf ("xato chiqmadi" != "ish bajarildi") ning tozalash
    # bosqichidagi ko'rinishi.
    qoldi = db.scalar("SELECT count(*) FROM tender WHERE id = %(id)s",
                      {"id": ZZ_TENDER_ID})
    if qoldi:
        print(f"  [!] FIKSTURA TENDERI QOLDI ({ZZ_TENDER_ID}) — "
              f"u ochiq holatda va tender ro'yxatida KO'RINADI. "
              f"Qo'lda o'chiring: DELETE FROM tender WHERE id = "
              f"{ZZ_TENDER_ID};")
    elif zz:
        print(f"Fikstura tenderi o'chirildi va yo'qligi tasdiqlandi: "
              f"{ZZ_TENDER_ID}")

    qoldiq = db.scalar("SELECT count(*) FROM tender_requirement")
    print(f"\nTozalandi: {n} ta juftlik, {ochirildi} ta SINOV qatori "
          f"o'chirildi, {tegilmadi} ta mavjud qator TEGILMADI. "
          f"Jadvalda qolgan: {qoldiq}")


def main() -> None:
    print("=" * 62)
    print("J3 SINOVI — modelga chiqmaydi, PUL SARFLAMAYDI")
    print("=" * 62)
    db.init_pool()
    try:
        if not db.scalar("SELECT to_regclass('public.tender_requirement')"):
            check("schema_patch_requirement.sql qo'llangan", False,
                  "psql -d xtxarid -f schema_patch_requirement.sql")
        else:
            test_sinovni_sinash()
            test_sxema()
            test_statik()
            test_amaliy()
            test_hujjatdan()
            test_naqsh()
            test_isteemolchilar()
            test_review()
            test_kirish_yetib_boradimi()
            test_inson_mehnati_olchovi()
            test_pilot()
            test_vaqt_olchovi()
            test_eskirish()
            test_yorliqlash()
            test_qayta_ajratish()
            test_navbat_filtri()
            test_indeks_taqiqi()
    finally:
        try:
            tozala()
        finally:
            db.close_pool()

    print("\n" + "=" * 62)
    print(f"NATIJA: {PASS}/{PASS + FAIL} o'tdi")
    print("=" * 62)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
