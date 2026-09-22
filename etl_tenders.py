#!/usr/bin/env python3
"""
xt-xarid.uz  |  ochiq reyestrlar ETL yig'uvchi skript
=====================================================
Vazifa: JSON-RPC endpointdan barcha (yoki filtrlangan) protseduralarni
sahifalab yig'ib, PostgreSQL bazasiga (xt_xarid_schema.sql sxemasi) yuklaydi.

MUHIM: platformada BIR EMAS, IKKI ochiq reyestr bor va ular bir xil
tuzilishga ega (`transform` ikkalasiga ham mos):
    ref_tender_public     — "Tender" protseduralari      (type='tender')
    ref_selection_public  — "Eng yaxshi taklifni tanlash" (type='selection')
Faqat birinchisini yig'ish ochiq lotlarning katta qismini yo'qotadi, shuning
uchun reyestr `--ref` bayrog'i bilan tanlanadi va run_etl.py ikkalasini ham
chaqiradi. ID fazolari kesishmaydi (tekshirilgan), shuning uchun ular bitta
`tender` jadvalida xavfsiz yashaydi.

Tadbirkorga mo'ljallangan: standart holatda faqat OCHIQ protseduralar ('open')
yig'iladi, chunki tadbirkorga ariza berish mumkin bo'lganlari kerak.
Butun bazani olish uchun --all-statuses bayrog'ini bering.

ISHGA TUSHIRISH (o'z muhitingizda — sandbox tarmog'i bu domenga chiqa olmaydi):
    pip install requests psycopg2-binary
    export XT_DB_DSN="dbname=xtxarid user=postgres password=... host=localhost"
    python3 etl_tenders.py                          # ochiq tenderlar
    python3 etl_tenders.py --ref ref_selection_public   # ochiq "tanlov"lar
    python3 etl_tenders.py --all-statuses           # barcha statuslar
    python3 etl_tenders.py --dry-run                # DBga yozmasdan, sanaydi

ESLATMA (odob-axloq):
    Bu rasmiy hujjatlashtirilmagan ichki API. Serverga bosim qilmaslik uchun
    so'rovlar orasida REQUEST_DELAY (s) kechikish qo'yilgan. Ommaviy chop
    etishdan oldin UzEx/mas'ul tashkilotdan rasmiy ruxsat so'rash tavsiya etiladi.
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

import etl_ishonch as ish

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    psycopg2 = None  # --dry-run uchun DB shart emas

# ---------------------------------------------------------------------------
# Konfiguratsiya
# ---------------------------------------------------------------------------
API_URL        = "https://api.xt-xarid.uz/rpc"
DEFAULT_REF    = "ref_tender_public"
# Ma'lum ochiq reyestrlar — --ref uchun yordam matni va sinovlar shundan oladi
KNOWN_REFS     = ("ref_tender_public", "ref_selection_public")
PAGE_LIMIT     = 51          # aniqlangan standart limit
REQUEST_DELAY  = 1.0         # so'rovlar orasi (sekund) — rate-limit hurmati
MAX_RETRIES    = 4           # bitta sahifa uchun qayta urinishlar
RETRY_BACKOFF  = 2.0         # eksponensial kutish koeffitsienti
#: (ulanish, o'qish). Ilgari BITTA `TIMEOUT = 30` edi va `requests` uni
#: IKKALASIGA ham qo'llardi: tushgan host uchun ham 30 sekund kutardik.
TIMEOUT        = (8.0, 30.0)
#: Qayta urinish SIYOSATI — `etl_ishonch` dagi yagona mexanizm.
#: Ilgari `rpc_call` HAR QANDAY istisnoni qayta urinardi, shu jumladan
#: 404 va 400 ni. Ular hech qachon tuzalmaydi, ya'ni 4 urinish x
#: eksponensial kutish = 30 sekund BEHUDA sarf, va oxirida baribir xato.
SIYOSAT = ish.Siyosat(urinishlar=MAX_RETRIES, asos=1.0, koeff=RETRY_BACKOFF,
                      max_kutish=45.0, jitter=0.25)
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    # Foydalanuvchi agentini halol ko'rsatamiz
    "User-Agent": "xt-xarid-tender-aggregator/0.1 (research; contact: you@example.com)",
}
# O'zbekiston vaqti. ATAYIN qattiq yozilgan: manba sanalari mahalliy vaqtda
# beriladi, baza ham Asia/Tashkent da yuradi, mamlakatda esa yozgi vaqt yo'q
# (doim UTC+5). ETL boshqa mintaqadagi mashinada yurganda ham muddat siljimasin.
TZ = timezone(timedelta(hours=5))


# ---------------------------------------------------------------------------
# RPC qatlami
# ---------------------------------------------------------------------------
#: Metrika hisoblagichi — `main()` da o'rnatiladi.
_HISOB: Optional[Any] = None


def rpc_call(session: requests.Session, params: Dict[str, Any], req_id: int = 1) -> Any:
    """Bitta JSON-RPC 'ref' chaqiruvi, TASNIFLANGAN qayta urinish bilan.

    UCH XATO TUZATILDI (2026-08-30):

      1. `except Exception` HAMMASINI qayta urinardi. 404/400 hech qachon
         tuzalmaydi — endi ular DARHOL ko'tariladi.
      2. Oxirgi urinishdan KEYIN ham `time.sleep(wait)` bajarilardi:
         4-urinish yiqilgach 16 sekund BEHUDA kutib, keyin xato berardi.
      3. Jitter yo'q edi. Ikki reyestr (tender + selection) bir xil
         xatoga uchraganda AYNAN bir vaqtda qayta urinib, manbaga
         to'lqin bo'lib urilardi.
    """
    payload = {"jsonrpc": "2.0", "id": req_id, "method": "ref", "params": params}

    def _ish():
        data = ish.javob_json(
            session.post(API_URL, json=payload, headers=HEADERS, timeout=TIMEOUT))
        if isinstance(data, dict) and data.get("error"):
            # RPC darajasidagi xato — HTTP 200 bilan keladi. Bu MAZMUNIY
            # xato (noto'g'ri ref nomi, ruxsat yo'q), tarmoq emas:
            # qayta urinish uni tuzatmaydi.
            raise ish.ManbaXato(f"RPC error: {str(data['error'])[:160]}",
                                qayta_urinsa=False)
        return data.get("result") if isinstance(data, dict) else data

    return ish.qayta_urin(
        _ish, siyosat=SIYOSAT, nom=f"rpc[{params.get('ref')}] sahifa {req_id}",
        ogohlantir=lambda m: print(f"  ! {m}", file=sys.stderr),
        hisob=(lambda: _HISOB.oldinga(retried=1)) if _HISOB else None)


def fetch_all_tenders(statuses: Optional[List[str]],
                      ref: str = DEFAULT_REF) -> List[Dict[str, Any]]:
    """
    Berilgan reyestrni (ref_tender_public / ref_selection_public) limit+offset
    bilan sahifalab, to'liq yig'adi. Bo'sh sahifa (result==[]) kelguncha davom.

    NATIJA `id` BO'YICHA TAKRORSIZ. Sabab: manba OFFSET bilan sahifalaydi va
    ro'yxatni YANGISI BIRINCHI tartibida beradi. Sahifalar orasida yangi
    protsedura e'lon qilinsa, butun ro'yxat bir pozitsiya pastga suriladi va
    chegaradagi yozuv KEYINGI sahifada YANA keladi. O'sha takror butun ETLni
    yiqitardi:

        psycopg2.errors.CardinalityViolation: ON CONFLICT DO UPDATE
        ne mozhet podeystvovat na stroku dvazhdy

    Yuklash bitta tranzaksiyada bo'lgani uchun bu FAQAT bitta yozuvni emas,
    BUTUN yurishni bekor qilardi — shuning uchun ba'zi soatlarda xt-xarid'dan
    umuman yangi ma'lumot tushmasdi (etl_cron.log: "!! XATO:" bo'sh matn bilan).

    Takrorni shu yerda, manbaga eng yaqin joyda olib tashlaymiz: shunda
    lot/tovar qatorlari ham ikkilanmaydi.
    """
    # Keep-alive + ulanish pooli. Sahifalash 12+ so'rov qiladi, har
    # biriga yangi TLS qo'l berish keraksiz.
    session = ish.sessiya_yarat(pool=2, sarlavhalar=HEADERS)
    filters: Dict[str, Any] = {}
    if statuses:
        filters["status"] = statuses  # qiymatlar massiv ko'rinishida

    all_records: List[Dict[str, Any]] = []
    offset = 0
    page = 0
    while True:
        page += 1
        params = {
            "ref": ref, "op": "read",
            "limit": PAGE_LIMIT, "offset": offset,
            "filters": filters,
            # fields bermaymiz → API barcha maydonlarni qaytaradi
        }
        result = rpc_call(session, params, req_id=page)

        # Javob shakli {"result": [...]} yoki to'g'ridan-to'g'ri [...] bo'lishi mumkin
        if isinstance(result, dict) and "result" in result:
            batch = result["result"]
        elif isinstance(result, list):
            batch = result
        else:
            batch = result.get("items") if isinstance(result, dict) else []
            batch = batch or []

        got = len(batch)
        all_records.extend(batch)
        print(f"  sahifa {page}: offset={offset}, olindi={got}, "
              f"jami={len(all_records)}")

        if got < PAGE_LIMIT:      # oxirgi (to'liq bo'lmagan yoki bo'sh) sahifa
            break
        offset += PAGE_LIMIT
        time.sleep(REQUEST_DELAY)

    # `id` bo'yicha takrorsizlantirish — OXIRGISI saqlanadi (u yangiroq
    # sahifadan, ya'ni holati eng so'nggi).
    unique: Dict[Any, Dict[str, Any]] = {}
    for r in all_records:
        unique[r.get("id")] = r
    dropped = len(all_records) - len(unique)
    if dropped:
        print(f"  ! sahifalash takrori: {dropped} ta yozuv bir necha sahifada "
              f"kelgan (id bo'yicha birlashtirildi)")
    return list(unique.values())


# ---------------------------------------------------------------------------
# MUDDAT — manba FAQAT SANA beradi, biz esa SOATgacha aniqlik talab qilamiz
#
# `close_at` manbada '2026-08-28' ko'rinishida keladi. Postgres uni o'sha
# kunning 00:00 iga aylantiradi, ya'ni saqlangan muddat haqiqiysidan 24 soatgacha
# OLDIN bo'ladi. Oqibati o'lchandi (2026-08-12): bugun tugaydigan 18 ta ochiq
# xt-xarid tenderi ro'yxatdan YARIM TUNDA yo'qolgan edi — API `close_at > now()`
# sharti bilan filtrlaydi, ularga esa hali soatlar bor edi. Qolganlarida ham
# "N soat qoldi" hisoblagichi bir kunga kam ko'rsatardi.
#
# Aniq vaqt manbada BOR: `remain_time` — so'rov paytida muddatgacha QOLGAN
# SEKUNDLAR. Tekshirildi (ochiq yozuvlar): fetch vaqti + remain_time har safar
# manba bergan `close_at` SANASINING ichiga tushdi, ya'ni ikkalasi bir xil
# muddatni ko'rsatadi. Shuning uchun vaqtni remain_time dan tiklaymiz, sanani
# esa SANITY tekshiruvi sifatida ishlatamiz (mos kelmasa — ishonmaymiz).
#
# remain_time bo'lmasa/mos kelmasa: 00:00 emas, KUN OXIRI. Sanada berilgan
# muddat o'sha kun davomida amal qiladi — bu eng kam zarar keltiradigan taxmin.
# ---------------------------------------------------------------------------
def precise_close_at(raw: Any, remain_time: Any, fetched_at: datetime) -> Any:
    """Sana ko'rinishidagi muddatni aniq vaqtga aylantiradi.

    Manba vaqt bilan bersa (yoki sana umuman yo'q bo'lsa) — tegmaydi.
    """
    if not raw:
        return raw
    s = str(raw)
    if len(s) > 10:          # allaqachon sana+vaqt
        return raw
    try:
        day = date.fromisoformat(s[:10])
    except ValueError:       # kutilmagan format — o'zgartirmasdan o'tkazamiz
        return raw

    try:
        remain = int(remain_time)
    except (TypeError, ValueError):
        remain = None

    if remain and remain > 0:
        exact = fetched_at + timedelta(seconds=remain)
        if exact.astimezone(TZ).date() == day:
            return exact.isoformat()

    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=TZ).isoformat()


# ---------------------------------------------------------------------------
# Transform — RPC yozuvini jadval qatorlariga ajratadi (namunada tasdiqlangan)
# ---------------------------------------------------------------------------
def transform(rec: Dict[str, Any],
              fetched_at: Optional[datetime] = None
              ) -> Tuple[dict, List[dict], List[dict], Dict[str, dict]]:
    meta = rec.get("meta") or {}
    area = rec.get("area") or ""
    if fetched_at is None:
        fetched_at = datetime.now(TZ)
    # MUHIM: dim_area.area_id TO'LIQ nuqtali yo'lni saqlaydi ('33.2137.2138.2140'),
    # oxirgi segment ('2140') EMAS. Shuning uchun FK (area_leaf_id → dim_area.area_id)
    # mos kelishi uchun bu yerga ham to'liq yo'lni beramiz (leaf tugun IDsi = yo'l).
    area_leaf = area or None

    tender_row = {
        # Ko'p-platforma sxemasi: xt-xarid ofsetsi 0, ya'ni global id = manba id.
        "id": rec["id"], "source_id": rec["id"], "source_platform": "xt-xarid",
        "type": rec.get("type"), "name": rec.get("name"),
        "status": rec.get("status"), "totalcost": rec.get("totalcost"),
        "currency": rec.get("currency"), "lang": rec.get("lang"),
        "is_new_multilot": rec.get("is_new_multilot"),
        "lot_count": rec.get("lot_count"), "good_count": rec.get("good_count"),
        "part_count": rec.get("part_count"),
        "participants_of_joint_purchase": rec.get("participants_of_joint_purchase"),
        "green": rec.get("green"),
        "area_path": area or None, "area_leaf_id": area_leaf,
        "buyer_org_id": rec.get("company_id"),   # manba kaliti o'zgarmagan
        "company_name": (rec.get("company_name") or "").strip() or None,
        "contract_num": rec.get("contract_num"),
        "contract_number": rec.get("contract_number"),
        "contract_id": rec.get("contract_id"),
        "created_at": rec.get("created_at"), "inserted_at": rec.get("inserted_at"),
        "publicated_at": rec.get("publicated_at"), "starting_date": rec.get("starting_date"),
        "agree_at": rec.get("agree_at"),
        # Sana -> aniq vaqt (yuqoridagi izohga qarang)
        "close_at": precise_close_at(rec.get("close_at"),
                                     rec.get("remain_time"), fetched_at),
        "ends_at": rec.get("ends_at"),
        "close_docs_objections_at": rec.get("close_docs_objections_at"),
        "docs_objections_remain_time": rec.get("docs_objections_remain_time"),
        "remain_time": rec.get("remain_time"),
        "raw_json": json.dumps(rec, ensure_ascii=False),
    }

    lot_rows = [
        {"tender_id": rec["id"], "lot_id": l["lot_id"],
         "item_count": l.get("item_count"), "total_sum_lot": l.get("total_sum_lot")}
        for l in meta.get("lots", [])
    ]

    good_rows: List[dict] = []
    categories: Dict[str, dict] = {}
    for g in meta.get("good_maps", []):
        cat = g.get("category")
        cat_uid = None
        if cat:
            cat_uid = cat.get("uid")
            categories[cat_uid] = {
                "category_uid": cat_uid, "code": cat.get("code"),
                "title_ru": cat.get("title"), "title_uz": None,
            }
        good_rows.append({
            "tender_id": rec["id"], "lot_id": g.get("lot_id"),
            "good_code": g.get("id"), "name": g.get("name"), "unit": g.get("unit"),
            "amount": g.get("amount"), "price": g.get("price"),
            "totalcost_item": g.get("totalcost_item"), "category_uid": cat_uid,
        })

    return tender_row, lot_rows, good_rows, categories


# ---------------------------------------------------------------------------
# Load — PostgreSQL ga UPSERT (idempotent: qayta ishga tushirsa dublikat bo'lmaydi)
# ---------------------------------------------------------------------------
TENDER_COLS = [
    "id","source_id","source_platform",
    "type","name","status","totalcost","currency","lang","is_new_multilot",
    "lot_count","good_count","part_count","participants_of_joint_purchase","green",
    "area_path","area_leaf_id","buyer_org_id","company_name","contract_num",
    "contract_number","contract_id","created_at","inserted_at","publicated_at",
    "starting_date","agree_at","close_at","ends_at","close_docs_objections_at",
    "docs_objections_remain_time","remain_time","raw_json",
]

def dedupe_by_key(rows: List[dict], key_cols: Tuple[str, ...], label: str) -> List[dict]:
    """PK bo'yicha takrorlarni olib tashlaydi (OXIRGISINI saqlaydi).

    Manba API bir tenderning bir lotida bir xil good_code'ni bir necha marta
    qaytarishi mumkin — bu PK'ni buzadi. Jimgina yo'qotmaymiz: nechta tashlangani
    log qilinadi, to'liq yozuv esa tender.raw_json da saqlanib qoladi.
    """
    seen: Dict[tuple, dict] = {}
    for r in rows:
        seen[tuple(r[c] for c in key_cols)] = r  # keyingisi avvalgisini bosadi
    dropped = len(rows) - len(seen)
    if dropped:
        print(f"  ! {label}: {dropped} ta takror qator dedup qilindi "
              f"(PK={'+'.join(key_cols)}; raw_json da saqlanib qoldi)")
    return list(seen.values())


def area_tozala(cur, tenders) -> int:
    """`area_leaf_id` ni `dim_area` ga solishtiradi; NOMA'LUMINI NULL qiladi.

    --- O'LCHANGAN NOSOZLIK (ishlab chiqarish, 2026-09-22) -------------
        DETAIL: Key (area_leaf_id)=(33.34.35.89.90.91) is not present
                in table "dim_area".

    Manba KO'P HUDUDLI tenderni yubordi: `33.34.35.89.90.91` --
    ierarxik yo'l emas, olti alohida viloyat kodi. `dim_area` esa
    ierarxiyani saqlaydi (`33.2137.2138.2140`) va bunday BIRIKMA u
    yerda hech qachon bo'lmaydi.

    OQIBATI NOMUTANOSIB: `load_to_db` BITTA tranzaksiya, shuning uchun
    bitta yaroqsiz qiymat BUTUN paketni qaytaradi. O'lchandi: 168
    yozuvdan hammasi yozilmay qoldi, va soatlik ETL shu sababli
    `baza_xato` bilan to'xtab turgandi.

    --- NEGA NULL, NEGA SOXTA QATOR EMAS ------------------------------
    `dim_area` ga `33.34.35.89.90.91` qatorini qo'shish oson bo'lardi,
    lekin bu YOLG'ON bo'lardi: bunday hudud YO'Q. Bizda esa "noma'lum
    noma'lumligicha qoladi" qoidasi bor.

    XOM QIYMAT YO'QOLMAYDI: `area_path` da (FK siz) va `raw_json` da
    o'sha holicha turadi -- ya'ni ko'p hududli model qo'shilganda
    ma'lumot qayta tiklanadi.

    HALOL CHEKLOV: `area_leaf_id` NULL bo'lgan tender HUDUD bo'yicha
    filtrlanmaydi. Bu yo'qotish, lekin butun paketni yo'qotishdan
    kichik. To'liq yechim -- `tender_area` bog'lovchi jadval.
    """
    qiymatlar = {t.get("area_leaf_id") for t in tenders if t.get("area_leaf_id")}
    if not qiymatlar:
        return 0
    cur.execute("SELECT area_id FROM dim_area WHERE area_id = ANY(%s)",
                (list(qiymatlar),))
    malum = {r[0] for r in cur.fetchall()}
    noma = qiymatlar - malum
    if not noma:
        return 0
    n = 0
    for t in tenders:
        if t.get("area_leaf_id") in noma:
            t["area_leaf_id"] = None
            n += 1
    print(f"  ! area_leaf_id: {len(noma)} ta noma'lum qiymat, {n} ta tender "
          f"NULL ga tushdi (area_path saqlandi): "
          f"{', '.join(sorted(noma)[:3])}", file=sys.stderr)
    return n


def load_to_db(dsn: str, tenders, lots, goods, categories) -> None:
    # Yuklashdan oldin PK bo'yicha dedup — manba ma'lumotidagi takrorlar.
    # `tender` ham tekshiriladi: bitta INSERT ichida takror `id` bo'lsa Postgres
    # butun tranzaksiyani CardinalityViolation bilan bekor qiladi (asosiy sabab
    # fetch_all_tenders da olib tashlangan, bu — kafolat).
    tenders = dedupe_by_key(tenders, ("id",), "tender")
    lots  = dedupe_by_key(lots,  ("tender_id", "lot_id"), "tender_lot")
    goods = dedupe_by_key(goods, ("tender_id", "lot_id", "good_code"), "tender_good")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # 1) categories (FK bog'liqligi uchun avval)
            if categories:
                execute_values(cur,
                    """INSERT INTO dim_category (category_uid, code, title_ru, title_uz)
                       VALUES %s
                       ON CONFLICT (category_uid) DO UPDATE
                       SET code=EXCLUDED.code, title_ru=EXCLUDED.title_ru""",
                    [(c["category_uid"], c["code"], c["title_ru"], c["title_uz"])
                     for c in categories.values()])

            # 2) tenders -- AVVAL hududni tozalaymiz. FK buzilishi
            #    butun tranzaksiyani qaytaradi, ya'ni bitta yaroqsiz
            #    qiymat 168 ta yaxshi yozuvni ham yo'qotardi.
            area_tozala(cur, tenders)
            execute_values(cur,
                f"""INSERT INTO tender ({",".join(TENDER_COLS)})
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                    {",".join(f"{c}=EXCLUDED.{c}" for c in TENDER_COLS if c != "id")},
                    fetched_at = now()""",
                [tuple(t[c] for c in TENDER_COLS) for t in tenders])

            # 3) lots (avval eski lotlarni tozalab, qayta yozamiz — struktura o'zgarishi mumkin)
            tid_list = tuple({t["id"] for t in tenders}) or (None,)
            cur.execute("DELETE FROM tender_lot WHERE tender_id IN %s", (tid_list,))
            if lots:
                execute_values(cur,
                    """INSERT INTO tender_lot (tender_id, lot_id, item_count, total_sum_lot)
                       VALUES %s""",
                    [(l["tender_id"], l["lot_id"], l["item_count"], l["total_sum_lot"])
                     for l in lots])

            # 4) goods
            cur.execute("DELETE FROM tender_good WHERE tender_id IN %s", (tid_list,))
            if goods:
                execute_values(cur,
                    """INSERT INTO tender_good
                       (tender_id, lot_id, good_code, name, unit, amount, price,
                        totalcost_item, category_uid)
                       VALUES %s""",
                    [(g["tender_id"], g["lot_id"], g["good_code"], g["name"], g["unit"],
                      g["amount"], g["price"], g["totalcost_item"], g["category_uid"])
                     for g in goods])

        conn.commit()
        print("  ✓ DBga muvaffaqiyatli yuklandi (commit).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
#: Kelishilgan chiqish kodlari — `run_etl.py` shularga qarab
#: `etl_run.status` ni ok / partial / error qilib qo'yadi.
CHIQISH_TUGADI = 0
CHIQISH_QISMAN = 7
CHIQISH_BAND   = 8
CHIQISH_XATO   = 1


def main() -> None:
    ish.chiqishni_sozla()
    ap = argparse.ArgumentParser(description="xt-xarid.uz protseduralarini yig'uvchi ETL")
    ap.add_argument("--ref", default=DEFAULT_REF,
                    help=f"Manba reyestri (ma'lumlari: {', '.join(KNOWN_REFS)}; "
                         f"standart: {DEFAULT_REF})")
    ap.add_argument("--all-statuses", action="store_true",
                    help="Barcha statuslar (standart: faqat 'open')")
    ap.add_argument("--dry-run", action="store_true",
                    help="DBga yozmasdan, faqat yig'ib sanaydi")
    ap.add_argument("--limit", type=int,
                    help="Faqat birinchi N yozuvni qayta ishlash (sinov uchun)")
    ap.add_argument("--dsn", default=os.environ.get("XT_DB_DSN"),
                    help="PostgreSQL DSN (yoki XT_DB_DSN muhit o'zgaruvchisi)")
    args = ap.parse_args()

    global _HISOB
    yozuvchi = ish.BazaYozuvchi(args.dsn)
    yurish = ish.Yurish(yozuvchi)
    _HISOB = yurish

    # USTMA-UST YURISHDAN HIMOYA — vazifa chegarasidan o'tadigan qulf.
    # Task Scheduler ning `IgnoreNew` i faqat BITTA vazifa ichida
    # ishlaydi. O'lchangan (etl_cron.log, 2026-08-30): ETL 01:00:02 da,
    # RAG 01:02:14 da boshlangan va ikkalasi ham shu manbaga urilgan.
    qulf = ish.Qulf("etl:xt-xarid", args.dsn) if not args.dry_run else None
    if qulf is not None and not qulf.ol():
        print("[BAND] xt-xarid allaqachon yig'ilmoqda — o'tkazib yuborildi "
              "(manbaga ikki barobar so'rov yubormaymiz).")
        yurish.sabab_yoz("band")
        yozuvchi.yop()
        sys.exit(CHIQISH_BAND)

    statuses = None if args.all_statuses else ["open"]
    label = "BARCHA statuslar" if args.all_statuses else "faqat 'open' (ochiq)"
    print(f"[1/3] Yig'ish boshlandi — {args.ref}, {label}")

    # `remain_time` shu paytga nisbatan o'lchanadi — muddatni tiklashda kerak.
    fetched_at = datetime.now(TZ)
    try:
        records = fetch_all_tenders(statuses, args.ref)
    except ish.ManbaXato as e:
        print(f"[XATO] {args.ref} ro'yxati olinmadi: {e}", file=sys.stderr)
        yurish.sabab_yoz("manba_xato")
        if qulf is not None:
            qulf.qoyver()
        yozuvchi.yop()
        sys.exit(CHIQISH_XATO)
    yurish.puls(majburan=True)
    if args.limit:
        records = records[:args.limit]
        print(f"  ! --limit {args.limit}: faqat birinchi {len(records)} yozuv olinadi")
    print(f"[1/3] Jami {len(records)} ta yozuv yig'ildi ({args.ref}).\n")

    print("[2/3] Transform...")
    all_t, all_l, all_g, all_c = [], [], [], {}
    buzuq = 0
    for rec in records:
        # BITTA BUZUQ YOZUV BUTUN PAKETNI YIQITMAYDI. Ilgari `transform`
        # dagi har qanday istisno butun skriptni to'xtatardi va o'sha
        # soatda xt-xarid'dan UMUMAN ma'lumot tushmasdi.
        try:
            t, l, g, c = transform(rec, fetched_at)
        except Exception as e:                              # noqa: BLE001
            buzuq += 1
            print(f"  ! #{rec.get('id')} BUZUQ YOZUV tashlandi: "
                  f"{type(e).__name__}: {str(e)[:90]}", file=sys.stderr)
            continue
        all_t.append(t); all_l.extend(l); all_g.extend(g); all_c.update(c)
    if buzuq:
        yurish.oldinga(processed=buzuq, failed=buzuq)
    print(f"[2/3] {len(all_t)} protsedura, {len(all_l)} lot, {len(all_g)} tovar, "
          f"{len(all_c)} kategoriya.\n")

    if args.dry_run:
        print("[3/3] --dry-run: DBga yozilmadi. Namuna (birinchi yozuv):")
        if all_t:
            preview = {k: all_t[0][k] for k in
                       ["id","type","name","status","currency","totalcost",
                        "area_leaf_id","company_name"]}
            print("   ", json.dumps(preview, ensure_ascii=False, indent=2))
        yozuvchi.yop()
        return

    if not args.dsn:
        sys.exit("XATO: DSN berilmagan. --dsn yoki XT_DB_DSN o'rnating (yoki --dry-run).")
    if psycopg2 is None:
        sys.exit("XATO: psycopg2 o'rnatilmagan. `pip install psycopg2-binary`.")

    print("[3/3] DBga yuklash...")
    try:
        load_to_db(args.dsn, all_t, all_l, all_g, all_c)
    except Exception as e:                                  # noqa: BLE001
        # Yuklash BITTA tranzaksiya: yiqilsa hech narsa yozilmagan.
        # Bu ATAYLAB — yarim yozilgan reyestr "hammasi shu" bo'lib
        # ko'rinardi va `expire_stale_tenders` yaxshi tenderlarni
        # "muddati tugadi" deb belgilab qo'yardi.
        yurish.oldinga(processed=len(all_t), failed=len(all_t))
        yurish.sabab_yoz("baza_xato")
        print(f"[XATO] yuklash bekor qilindi (rollback): {str(e)[:200]}",
              file=sys.stderr)
        if qulf is not None:
            qulf.qoyver()
        yozuvchi.yop()
        sys.exit(CHIQISH_XATO)

    yurish.oldinga(processed=len(all_t), succeeded=len(all_t))
    yurish.sabab_yoz("tugadi" if not buzuq else "qisman")
    print(f"\nTayyor. Metrika: {yurish.xulosa()}")
    if qulf is not None:
        qulf.qoyver()
    yozuvchi.yop()
    # Buzuq yozuv bo'lsa yurish "to'liq tugadi" deb ko'rsatilmaydi:
    # jimgina o'tkazib yuborish shu loyihada takroriy nuqson.
    sys.exit(CHIQISH_QISMAN if buzuq else CHIQISH_TUGADI)


if __name__ == "__main__":
    main()
