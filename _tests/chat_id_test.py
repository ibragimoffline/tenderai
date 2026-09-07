#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: XABARDAGI TENDER RAQAMINI HAL QILISH
============================================

O'LCHANGAN MUAMMO (2026-09-04, `chat_tool_call` jurnalidan).
Haqiqiy foydalanuvchining raqamli 7 xabari:

    2 ta  to'g'ri tool
    2 ta  `get_tender` UMUMAN chaqirilmagan
    2 ta  ortiqcha `search_tenders` raundi
    1 ta  hal qilinmagan (e-do'kon havolasi)

REJADAGI NAQSH RAD ETILDI. `ai_chat_takomil.md` §1.2
`\\b[tT]?(\\d{6,8})\\b` ni taklif qilgan edi. Jurnal ko'rsatdi:

  * `t` prefiksi HECH QACHON uchramaydi — foydalanuvchi `#` yozadi;
  * raqamlarning aksariyati 11 xonali;
  * korpusda `tender.id` ning 74,8% i 11 xonali.

Ya'ni naqsh 7 raqamdan faqat 2 tasini ko'rardi.

IKKI BOSQICH QOIDASI SINALADI:
    naqsh KENG (5–12 xona)  ->  soxta nomzod ko'p bo'ladi
    baza TOR                ->  topilmagan yalang'och raqam JIM tashlanadi

Va IKKI XIL "YO'Q" ajratiladi:
    bazada yo'q    -> "TOPILMADI"
    qamrovda yo'q  -> "bu manba kuzatilmaydi" (e-do'kon havolasi)

BU SINOV PULLIK CHAQIRUVSIZ. Naqsh qismi bazasiz ham yuradi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\chat_id_test.py
    .venv\\Scripts\\python.exe _tests\\chat_id_test.py --bazasiz
"""
from __future__ import annotations

import argparse
import io
import statistics
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
# 1. NAQSH — bazasiz
# =====================================================================
#: (matn, kutilgan raqamlar, izoh)
#:
#: MUSBATLAR JURNALDAN OLINGAN — o'ylab topilgan emas.
NAQSH_HOLATLARI = [
    # --- jurnaldagi haqiqiy xabarlar ---
    ("#20000508544 tenderda qatnashish va uni yutish ehtimolligi yuqorimi?",
     [20000508544], "11 xonali, `#` prefiksi"),
    ("#8440527 tenderi", [8440527], "7 xonali, `#` prefiksi"),
    ("#20000509114 tenderi bo'yicha 14 yillik tajriba so'ralgan",
     [20000509114], "raqam + boshqa sonlar (14) aralash"),
    ("18.08. Tezkor boshqaruv markazlari uchun qo'shimcha uskunalar "
     "#20000509580", [20000509580], "sana bilan boshlangan xabar"),
    ("https://xarid.uzex.uz/shop/lot-details/5613572  lot bo'yicha ma'lumot",
     [5613572], "havoladan ajratiladi"),

    # --- SALBIYLAR: 5-12 diapazoni keng, ular tutilmasin ---
    ("ISO90011 sertifikati kerakmi?", [], "harfga yopishgan raqam"),
    ("1.234567 koeffitsiyent", [], "o'nlik kasr"),
    ("18.08.2026 da tugaydi", [], "sana — bo'laklari qisqa"),
    ("Narxi 1234 so'm", [], "4 xona — diapazondan past"),
    ("9989012345678 raqamiga yozing", [], "13 xona — diapazondan yuqori"),

    # --- CHEGARA: tutiladi, lekin bazada tekshiriladi ---
    ("summa 15000000 so'm", [15000000], "8 xona — naqsh tutadi, baza hal qiladi"),
    ("998901234567 ga qo'ng'iroq qiling", [998901234567],
     "12 xonali telefon — naqsh tutadi, baza hal qiladi"),
    ("sana 20260904 da tugaydi", [20260904],
     "8 xonali sana — naqsh tutadi, baza hal qiladi"),

    # --- KO'P RAQAM ---
    ("#8440527 va #20000509580 ni solishtir", [8440527, 20000509580],
     "bitta xabarda ikkita"),
    ("narxi 8440527.", [8440527], "jumla nuqtasi xalaqit bermaydi"),

    # --- `t` PREFIKSI: foydalanuvchidan emas, MODELDAN ---
    # Jurnalda `t8440527` HECH QACHON uchramagan. Lekin model uni
    # o'z javobidan yoki hujjat matnidan olib tool ga uzatishi
    # mumkin -- va ilgari `int()` shu yerda yiqilardi.
    ("t8440527", [8440527], "`t` prefiksi (model uzatishi mumkin)"),
    ("net12345 porti ochiq", [], "`t` harfi so'z ichida — prefiks EMAS"),
]


def test_naqsh():
    bolim("1. Naqsh — nomzodlarni ajratish (bazasiz)")
    from api import tender_ref as T

    for matn, kutilgan, izoh in NAQSH_HOLATLARI:
        olindi = sorted(c["raqam"] for c in T.nomzodlar(matn))
        check(f"{izoh}", olindi == sorted(kutilgan),
              f"{matn[:44]!r} -> {olindi}, kutilgan {sorted(kutilgan)}")

    # `#` — ANIQ ID DA'VOSI. Farq muhim: topilmagan yalang'och raqam
    # jim tashlanadi, `#` li esa "topilmadi" deb aytiladi.
    check("`#` belgisi `aniq` bayrog'ini qo'yadi",
          T.nomzodlar("#8440527")[0]["aniq"] is True)
    check("yalang'och raqam `aniq` EMAS",
          T.nomzodlar("summa 15000000 so'm")[0]["aniq"] is False)
    check("havoladagi raqam `aniq`",
          T.nomzodlar("https://etender.uzex.uz/tender/20000509114"
                      )[0]["aniq"] is True)

    # REJADAGI NAQSH NEGA RAD ETILGANI — SINOVDA QOLADI.
    # Bu qator kelajakda kimdir "6-8 yetarli edi" deb qaytarmasin.
    import re
    reja = re.compile(r"\b[tT]?(\d{6,8})\b")
    jurnal = [m for m, k, _ in NAQSH_HOLATLARI if k][:5]
    topgan = sum(1 for m in jurnal if reja.findall(m))
    check("rejadagi `\\d{6,8}` naqshi YETARLI EMAS EDI",
          topgan < len(jurnal),
          f"5 ta haqiqiy xabardan {topgan} tasini ko'rardi")

    # CHEGARA: ko'p raqam prompt blokini shishirmasin.
    kop = " ".join(str(1000000 + i) for i in range(20))
    check("nomzodlar soni cheklangan (MAX_RAQAM)",
          len(T.nomzodlar(kop)) <= T.MAX_RAQAM, str(len(T.nomzodlar(kop))))


def test_qamrov_manbasi():
    bolim("2. Qamrov — kuzatiladigan va kuzatilmaydigan manba")
    from api import tender_ref as T

    # IKKI XIL "YO'Q" — bu farq modelga yetkaziladi.
    c = T.nomzodlar("https://xarid.uzex.uz/shop/lot-details/5613572")
    check("e-do'kon havolasi QAMROVDAN TASHQARI deb belgilanadi",
          c and c[0]["manba"] is not None, str(c))
    c2 = T.nomzodlar("https://etender.uzex.uz/tender/20000509114")
    check("etender havolasi kuzatiladi (manba bo'sh)",
          c2 and c2[0]["manba"] is None, str(c2))
    c3 = T.nomzodlar("https://xt-xarid.uz/tender/8440527")
    check("xt-xarid havolasi kuzatiladi",
          c3 and c3[0]["manba"] is None, str(c3))

    check("`xarid.uzex.uz` KUZATILADI ro'yxatida YO'Q",
          "xarid.uzex.uz" not in T.KUZATILADI)
    check("kuzatiladigan hostlar `source_platform` qiymatlarini beradi",
          set(T.KUZATILADI.values()) == {"uzex", "xt-xarid"},
          str(set(T.KUZATILADI.values())))


def test_manba_matni():
    bolim("3. Manba kodi — qoidalar izohda")
    src = io.open(os.path.join(ROOT, "api", "tender_ref.py"),
                  encoding="utf-8").read()
    # `tender_lot.lot_id` GLOBAL EMAS — u qidiruvga QO'SHILMASLIGI kerak.
    check("`lot_id` qidiruvga qo'shilmagan",
          "tender_lot" not in src.split("SQL_HAL")[1].split('"""')[1],
          "lot_id tender ichidagi tartib raqami")
    check("nega qo'shilmagani izohda", "global identifikator EMAS" in src)
    check("`source_id` qidiriladi", "source_id = %(n)s" in src)
    check("ikki bosqich qoidasi izohda",
          "NAQSH KENG" in src and "BAZA TOR" in src)

    # ai_chat ga ULANGANMI.
    chat = io.open(os.path.join(ROOT, "api", "ai_chat.py"),
                   encoding="utf-8").read()
    check("`build_system` raqam blokini qabul qiladi",
          "raqam_bloki: Optional[str] = None" in chat)
    check("blok KESH CHEGARASIDAN KEYIN qo'shiladi",
          chat.index("dynamic.append(raqam_bloki)")
          > chat.index('"cache_control"'))
    check("`stream_chat` uni hisoblaydi",
          "_raqam_bloki, user_text, ctx.company_id" in chat)
    check("yiqilsa chat ishlayveradi",
          "raqam_bloki = None" in chat and "except Exception" in chat)


# =====================================================================
# 4. BAZA — haqiqiy korpus
# =====================================================================
def test_baza(db):
    bolim("4. Hal qilish — haqiqiy korpus")
    from api import tender_ref as T

    # JURNALDAGI XABARLAR: hammasi topilishi SHART.
    for matn, kutilgan_id in [
            ("#20000508544 tenderda qatnashish", 20000508544),
            ("#8440527 tenderi", 8440527),
            ("#20000509114 tenderi bo'yicha 14 yillik tajriba", 20000509114),
            ("18.08. uskunalar #20000509580", 20000509580)]:
        r = T.hal_qil(matn, 2)
        topildi = [x for x in r if x["holat"] == "topildi"]
        check(f"{kutilgan_id} topildi",
              len(topildi) == 1 and topildi[0]["tender_id"] == kutilgan_id,
              str(r))

    # E-DO'KON HAVOLASI: "topilmadi" EMAS, "qamrovda yo'q".
    r = T.hal_qil("https://xarid.uzex.uz/shop/lot-details/5613572", 2)
    check("e-do'kon havolasi -> `qamrovdan_tashqari`",
          len(r) == 1 and r[0]["holat"] == "qamrovdan_tashqari", str(r))

    # YALANG'OCH SOXTA RAQAMLAR JIM TASHLANADI.
    for matn, izoh in [("summa 15000000 so'm", "summa"),
                       ("998901234567 ga qo'ng'iroq qiling", "telefon"),
                       ("sana 20260904 da tugaydi", "sana")]:
        r = T.hal_qil(matn, 2)
        check(f"{izoh} — jimgina tashlandi", r == [], str(r))

    # `#` LI TOPILMAGAN RAQAM AYTILADI.
    r = T.hal_qil("#99999999999 tenderi", 2)
    check("`#` li topilmagan raqam -> `topilmadi`",
          len(r) == 1 and r[0]["holat"] == "topilmadi", str(r))

    # `source_id` ORQALI HAL QILISH (uzex: id = 20000000000 + source_id).
    row = db.query_one("SELECT id, source_id FROM tender "
                       "WHERE source_id IS NOT NULL AND source_platform='uzex' "
                       "LIMIT 1")
    if row:
        r = T.hal_qil(f"#{row['source_id']} tenderi", 2)
        t = [x for x in r if x["holat"] == "topildi"]
        check("`source_id` bilan ham topiladi",
              len(t) == 1 and t[0]["tender_id"] == row["id"],
              f"{row['source_id']} -> {r}")
        check("`mos_ustun` qaysi ustun ekanini AYTADI",
              t and t[0]["mos_ustun"] == "source_id", str(t))


def test_blok(db):
    bolim("5. Prompt bloki — model uchun ko'rsatma")
    from api import tender_ref as T

    b = T.blok(T.hal_qil(
        "#20000509580 va https://xarid.uzex.uz/shop/lot-details/5613572 "
        "va #99999999999", 2))
    check("blok yaratildi", bool(b))
    check("topilgan tender_id yozilgan", "tender_id=20000509580" in (b or ""))
    check("qamrov farqi aytilgan", "QAMROVDA YO'Q" in (b or ""))
    check("topilmagan alohida aytilgan", "TOPILMADI" in (b or ""))
    check("qayta qidirmaslik ko'rsatmasi bor",
          "search_tenders" in (b or "") and "qidirma" in (b or ""))
    check("raqamsiz xabarda blok YO'Q",
          T.blok(T.hal_qil("Kafolat muddati qancha?", 2)) is None)


def test_identifikator(db):
    bolim("6. Tool identifikatori — model matn uzatsa ham ishlaydi")
    from api import ai_chat as A

    # `get_tender` SXEMASI matnni ham qabul qilishi kerak.
    tool = next(t for t in A.TOOLS if t["name"] == "get_tender")
    tur = tool["input_schema"]["properties"]["tender_id"]["type"]
    check("`get_tender` sxemasi matnni ham qabul qiladi",
          isinstance(tur, list) and "string" in tur and "integer" in tur,
          str(tur))
    check("ta'rif prefiks tozalashni MODELDAN kutmaydi",
          "siz tozalamang" in tool["description"])

    for xom, kutilgan, izoh in [
            (20000508544, 20000508544, "sof int"),
            ("20000508544", 20000508544, "matn"),
            ("#20000508544", 20000508544, "`#` prefiksi"),
            ("t8440527", 8440527, "`t` prefiksi"),
            ("508540", 20000508540, "`source_id` -> `id`"),
            ("https://etender.uzex.uz/tender/20000509114", 20000509114,
             "havola"),
            ("salom", None, "matn — ID emas"),
            (None, None, "bo'sh"),
            ("", None, "bo'sh satr")]:
        check(f"identifikator: {izoh}",
              A._tender_id_ol(xom, 2) == kutilgan,
              f"{xom!r} -> {A._tender_id_ol(xom, 2)}, kutilgan {kutilgan}")

    # HAMMA TOOL BITTA HAL QILGICHDAN O'TADI -- ikki xil xulq
    # bo'lmasin (model `get_tender` da `#` ishlatib, `calc_price`
    # da yiqilmasin).
    src = io.open(os.path.join(ROOT, "api", "ai_chat.py"),
                  encoding="utf-8").read()
    check("hech qayerda xom `int(args['tender_id'])` qolmagan",
          'int(args["tender_id"])' not in src)
    check("hal qilgich barcha tool'larda ishlatiladi",
          src.count("_tender_id_ol(args.get(") >= 5,
          str(src.count("_tender_id_ol(args.get(")))


def test_tiklash_olchovi(db):
    bolim("7. Tiklanish o'lchovi — `DAVOM_SOAT` chegarasi uchun")
    from api import ai_chat as A

    check("`v_chat_tiklash` ko'rinishi bor",
          bool(db.scalar("SELECT to_regclass('public.v_chat_tiklash') "
                         "IS NOT NULL")))
    # KESIMLAR ALOHIDA: butun savol shu.
    kesimlar = {r["kesim"] for r in db.query("SELECT DISTINCT kesim "
                                             "FROM v_chat_tiklash")}
    check("global va tender kesimlari ALOHIDA",
          kesimlar <= {"global", "tender"} and kesimlar,
          str(kesimlar))
    # NOL MAXRAJDA NULL.
    bosh = db.query_one("SELECT rad_foiz, foiz_yoq_sababi "
                        "FROM v_chat_tiklash WHERE tiklandi = 0 LIMIT 1")
    if bosh:
        check("maxraj nol -> `rad_foiz` NULL (nol EMAS)",
              bosh["rad_foiz"] is None, str(bosh))
        check("foiz NEGA yo'qligi AYTILADI",
              bool(bosh["foiz_yoq_sababi"]), str(bosh))

    # MEDIANA, O'RTACHA EMAS.
    #
    # Bitta uzun holat (panel ochiq qoldirilgan, 40 daqiqadan keyin
    # "Yangi suhbat") o'rtachani buzadi. Loyiha vaqt o'lchovida
    # allaqachon medianani tanlagan (`sekund_talabga`).
    tarif = db.scalar("SELECT pg_get_viewdef("
                      "'public.v_chat_tiklash'::regclass, true)")
    check("ko'rinish MEDIANA ishlatadi", "percentile_cont" in tarif)
    check("ko'rinishda `avg(` YO'Q", "avg(" not in tarif)
    check("ustun nomi ham medianani aytadi",
          bool(db.query_one("SELECT 1 x FROM information_schema.columns "
                            "WHERE table_name='v_chat_tiklash' "
                            "  AND column_name='mediana_sek'")))

    # ENG KAM NAMUNA — `MOSLIK_MIN` bilan AYNI qoida.
    #
    # 3 tiklanish / 2 rad = 66.7% "chegara noto'g'ri" deb o'qilardi.
    # Kam namunadan foiz chiqarish "bitta qarordan 100%" xatosi.
    from api import routing as R
    check("ko'rinish chegarasi `MOSLIK_MIN` ga teng (10)",
          R.MOSLIK_MIN == 10 and ">= 10" in tarif.replace(">=10", ">= 10"),
          f"MOSLIK_MIN={R.MOSLIK_MIN}")

    # MUTLAQ QIYMAT EMAS, O'ZGARISH.
    #
    # O'LCHANGAN NUQSON (2026-09-06). Bu blok ilgari `tiklandi == 3`,
    # `rad_foiz is None` va `mediana_sek == 1500` deb MUTLAQ qiymat
    # kutardi — ya'ni "kesimda MENDAN BOSHQA hech kim yo'q" degan
    # aytilmagan shartga tayanardi. Bazada bitta HAQIQIY tiklanish
    # paydo bo'lgach (1 tiklandi / 1 rad, mediana 11 s) uchala shart
    # ham yiqildi. Kod TO'G'RI edi: 4/10 ham, `namuna kam: 4/10` ham
    # ko'rinishning to'g'ri javobi.
    #
    # Endi sinov O'ZI YOZGAN 3 qatorning HISSASINI o'lchaydi va
    # medianani ko'rinishdan MUSTAQIL ravishda qayta hisoblab
    # solishtiradi. Bu bazaviy holatga befarq va ayni paytda
    # KUCHLIROQ: ilgari mediana bitta qotirilgan songa qaralardi,
    # endi butun namunaga.
    #
    # `company_id=2` sharti QO'SHILDI: usiz tanlangan sessiya boshqa
    # kompaniyaniki bo'lib, hissa umuman ko'rinmasligi mumkin edi.
    sinov = [r["id"] for r in db.query(
        "SELECT id FROM chat_session "
        " WHERE manba IS DISTINCT FROM 'eval' AND NOT archived "
        "   AND company_id = 2 "
        "   AND tender_id IS NULL AND tiklandi_at IS NULL LIMIT 3")]
    if len(sinov) == 3:
        oldin = db.query_one("SELECT * FROM v_chat_tiklash "
                             "WHERE kesim='global' AND company_id=2") or {}
        b_tik = int(oldin.get("tiklandi") or 0)
        b_rad = int(oldin.get("rad_etildi") or 0)
        try:
            for k, i in enumerate(sinov):
                db.execute_returning(
                    "UPDATE chat_session SET tiklandi_at = now() - %(o)s::interval "
                    "WHERE id=%(i)s RETURNING id",
                    {"i": i, "o": f"{10 + k * 30} minutes"})
            for i in sinov[:2]:
                db.execute_returning(
                    "UPDATE chat_session SET tiklash_rad_at = now() "
                    "WHERE id=%(i)s RETURNING id", {"i": i})
            r = db.query_one("SELECT * FROM v_chat_tiklash "
                             "WHERE kesim='global' AND company_id=2")
            check("3 ta tiklanish HISOBGA olindi",
                  r["tiklandi"] == b_tik + 3, f"{b_tik} -> {r['tiklandi']}")
            check("2 ta rad HISOBGA olindi",
                  r["rad_etildi"] == b_rad + 2, f"{b_rad} -> {r['rad_etildi']}")
            # CHEGARA ikki tomonlama: 10 dan past bo'lsa foiz YO'Q va
            # sababi aytiladi, 10 ga yetsa foiz BERILADI. Ilgari faqat
            # birinchi tarmoq sinalardi va u ham tasodifan.
            if r["tiklandi"] < 10:
                check("kam namunada foiz BERILMAYDI",
                      r["rad_foiz"] is None, str(r))
                check("sabab AYNAN namuna sonini aytadi",
                      r["foiz_yoq_sababi"] == f"namuna kam: {r['tiklandi']}/10",
                      str(r["foiz_yoq_sababi"]))
            else:
                check("10 ga yetganda foiz BERILADI",
                      r["rad_foiz"] is not None and r["foiz_yoq_sababi"] is None,
                      str(r))
            # MEDIANA KO'RINISHDAN MUSTAQIL QAYTA HISOBLANADI.
            # Uchinchi qator RAD ETILMAGAN — u bu ro'yxatga
            # kirmaydi, ya'ni `FILTER` ishlayotgani ko'rinadi.
            xom = [float(x["sek"]) for x in db.query(
                "SELECT EXTRACT(epoch FROM tiklash_rad_at - tiklandi_at) AS sek "
                "  FROM chat_session "
                " WHERE manba IS DISTINCT FROM 'eval' AND company_id = 2 "
                "   AND tender_id IS NULL AND tiklash_rad_at IS NOT NULL")]
            kutilgan = statistics.median(xom)
            # 1 sekundlik yo'l qo'yiladi: `now()` ikki UPDATE orasida
            # siljiydi va ko'rinish `::integer` ga yaxlitlaydi.
            check("mediana faqat RAD ETILGANLARDAN hisoblanadi",
                  abs(r["mediana_sek"] - kutilgan) <= 1,
                  f"ko'rinish={r['mediana_sek']} mustaqil={kutilgan:.0f} "
                  f"namuna={len(xom)}")
        finally:
            for i in sinov:
                db.execute_returning(
                    "UPDATE chat_session SET tiklandi_at=NULL, "
                    "tiklash_rad_at=NULL WHERE id=%(i)s RETURNING id",
                    {"i": i})
            print("        (namuna sinovi tozalandi)")
    else:
        print("        [i] 3 ta bo'sh sessiya yo'q — namuna sinovi o'tkazilmadi")

    # IDOR JUFTLIGI + takroriy chaqiruv.
    #
    # `company_id = 2` SHART QILIB QO'YILDI (2026-09-06). Ilgari
    # nomzod filtrsiz `LIMIT 1` bilan tanlanardi, quyidagi shart esa
    # egasi AYNAN 2 ekaniga tayanardi (`tiklash_qayd(sid, 2, ...)`).
    # Bazada BOSHQA ijarachining sessiyasi paydo bo'lgach nomzod
    # o'shanikiga tushdi va TO'RTTA shart yiqildi -- kod TO'G'RI edi,
    # u begona yozuvni ATAYLAB rad etgan.
    #
    # Bu `requirement_test` dagi bilan AYNI sinf: aytilmagan shart +
    # tartibsiz `LIMIT 1`. `ORDER BY id` ham qo'shildi: nomzodni
    # Postgres rejasi emas, sinov tanlasin.
    sid = db.scalar("SELECT id::text FROM chat_session "
                    "WHERE manba IS DISTINCT FROM 'eval' AND NOT archived "
                    "  AND company_id = 2 "
                    "  AND tiklandi_at IS NULL ORDER BY id LIMIT 1")
    if not sid:
        print("        [i] belgisiz sessiya yo'q — tekshiruv o'tkazilmadi")
        return
    try:
        check("boshqa ijarachi yoza OLMAYDI",
              A.tiklash_qayd(sid, 10_000_007, "tiklandi") is False)
        check("o'z ijarachisi yozadi",
              A.tiklash_qayd(sid, 2, "tiklandi") is True)
        r = db.query_one("SELECT tiklandi_at, tiklash_rad_at "
                         "FROM chat_session WHERE id=%(i)s", {"i": sid})
        check("`tiklandi_at` yozildi", r["tiklandi_at"] is not None)
        birinchi = r["tiklandi_at"]
        # TAKRORIY CHAQIRUV MAXRAJNI SHISHIRMASIN.
        A.tiklash_qayd(sid, 2, "tiklandi")
        r2 = db.query_one("SELECT tiklandi_at FROM chat_session "
                          "WHERE id=%(i)s", {"i": sid})
        check("takroriy tiklanish IKKINCHI marta yozilmaydi",
              r2["tiklandi_at"] == birinchi)
        check("rad etish yoziladi", A.tiklash_qayd(sid, 2, "rad") is True)
        r3 = db.query_one("SELECT tiklash_rad_at FROM chat_session "
                          "WHERE id=%(i)s", {"i": sid})
        check("`tiklash_rad_at` yozildi", r3["tiklash_rad_at"] is not None)
    finally:
        db.execute_returning(
            "UPDATE chat_session SET tiklandi_at=NULL, tiklash_rad_at=NULL "
            "WHERE id=%(i)s RETURNING id", {"i": sid})
        print("        (sinov belgisi tozalandi)")

    # RAD ETISH TIKLANISHSIZ BO'LMAYDI (CHECK cheklovi).
    tutildi = False
    try:
        db.execute_returning(
            "UPDATE chat_session SET tiklash_rad_at=now() "
            "WHERE id=%(i)s RETURNING id", {"i": sid})
    except Exception:                                     # noqa: BLE001
        tutildi = True
    check("rad etish tiklanishsiz YOZILMAYDI (CHECK)", tutildi)


def test_interfeys_olchovi():
    bolim("8. Interfeys — o'lchov ulanganmi")
    src = io.open(os.path.join(ROOT, "frontend", "src", "components",
                               "ChatPanel.tsx"), encoding="utf-8").read()
    check("tiklanganda qayd yuboriladi",
          "api.chatTiklash(mos.id, 'tiklandi')" in src)
    check("`Yangi suhbat` rad etishni yozadi",
          "chatTiklash(tiklangan, 'rad')" in src)
    check("ikkala tugma ham bitta funksiyaga ulangan",
          src.count("onClick={yangiSuhbat}") == 2,
          str(src.count("onClick={yangiSuhbat}")))
    # QO'LDA OCHISH O'LCHOVGA KIRMASLIGI — maxrajni suyultirmasin.
    i = src.index("async function seansOch")
    check("qo'lda ochish maxrajga QO'SHILMAYDI",
          "setTiklangan(null)" in src[i:i + 1400])
    check("o'lchov xatosi ishni to'xtatmaydi",
          src.count(".catch(() => {})") >= 2)


def test_kesim_qoidasi(db):
    bolim("9. KESIM JUFTLIGI — har ro'yxatli tool javobida")
    # O'LCHANGAN NUQSON (2026-09-04). Qoida uchta tool da bor edi,
    # to'rtinchisida (`get_my_catalog`) YO'Q. Katalogda 1798 ta
    # mahsulot, javobda 200 ta, `count` esa 1798 deb turardi —
    # model "katalogimda bunday mahsulot yo'q" deb ISHONCH BILAN
    # yozardi va bu Go/No-Go ga ham o'tardi.
    #
    # Bu `paid_guard` beshinchi yo'li va `multitenant` 69/127
    # bilan bir naqsh: QOIDA BOR, QAMROVI TO'LIQ EMAS.
    from api import ai_chat as A

    # --- `kesim()` uch holatni ARALASHTIRMAYDI ---
    k = A.kesim(200, jami=1798)
    check("jami ma'lum -> aniq son", k["kesildi"] == 1598, str(k["kesildi"]))
    check("kesilganda IZOH beriladi", bool(k.get("kesildi_izoh")))
    k = A.kesim(3, chegara=10)
    check("chegaraga yetmadi -> `kesildi` = 0 (ANIQ)",
          k["kesildi"] == 0 and k["jami"] == 3, str(k))
    k = A.kesim(10, chegara=10)
    check("chegara to'ldi -> `kesildi` = None (BILMAYMIZ)",
          k["kesildi"] is None and k["jami"] is None, str(k))
    check("noma'lumlik `0` ga AYLANTIRILMAYDI",
          A.kesim(10, chegara=10)["kesildi"] != 0,
          "o'lchanmaganni o'lchangan deb ko'rsatish")
    check("noma'lumlikda ham sabab AYTILADI",
          "O'LCHANMAGAN" in A.kesim(10, chegara=10)["kesildi_izoh"])

    # --- HAR RO'YXATLI TOOL JAVOBIDA JUFTLIK BOR ---
    ctx = A.ChatContext(company_id=2, session_id="zz", lang="uz")
    ROYXATLI = {
        "get_my_catalog": ({}, "products"),
        "search_tenders": ({"query": "kompyuter", "limit": 5}, "tenders"),
    }
    for nom, (arglar, maydon) in ROYXATLI.items():
        out = A.TOOL_IMPL[nom](arglar, ctx)
        check(f"`{nom}` javobida `korsatildi` bor", "korsatildi" in out,
              str(sorted(out.keys()))[:80])
        check(f"`{nom}` javobida `kesildi` bor", "kesildi" in out)
        check(f"`{nom}`: `korsatildi` ro'yxat uzunligiga TENG",
              out["korsatildi"] == len(out.get(maydon) or []),
              f"{out['korsatildi']} vs {len(out.get(maydon) or [])}")

    # --- KATALOG TARTIBI ATAYLAB TANLANGAN va AYTILGAN ---
    r = A._t_get_my_catalog({}, ctx)
    if r["kesildi"]:
        check("kesilganda TARTIB aytiladi", bool(r.get("tartib")),
              "200 ta tasodifiy emas — model buni bilishi kerak")
        check("tartib eng yangilardan", "yangi" in (r.get("tartib") or ""))

    # --- MANBA: qoida kodda yozilgan ---
    src = io.open(os.path.join(ROOT, "api", "ai_chat.py"),
                  encoding="utf-8").read()
    check("`kesim()` yordamchisi bor", "def kesim(" in src)
    check("uch qiymat izohda ajratilgan",
          "UCH XIL qiymat" in src and "BILMAYMIZ" in src)

    # --- PULLIK PROMPT ham kesimni aytadi ---
    req = io.open(os.path.join(ROOT, "api", "requirement.py"),
                  encoding="utf-8").read()
    check("`prompt_block` kesimni aytadi",
          "ajratilgan talab bor" in req)
    check("kesim oyna funksiyasi bilan o'lchanadi",
          "count(*) OVER ()" in req)


# =====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Chat: tender raqamini hal qilish sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: XABARDAGI TENDER RAQAMINI HAL QILISH")
    print("=" * 70)

    test_naqsh()
    test_qamrov_manbasi()
    test_manba_matni()
    test_interfeys_olchovi()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Bazali tekshiruvlar o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_baza(db)
            test_blok(db)
            test_identifikator(db)
            test_tiklash_olchovi(db)
            test_kesim_qoidasi(db)
        except Exception as e:                                # noqa: BLE001
            check("bazali tekshiruv", False, str(e)[:110])

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
