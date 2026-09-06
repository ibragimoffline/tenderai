# -*- coding: utf-8 -*-
"""J3 — TENDER TALABLARI (`tender_requirement`).

NIMA UCHUN KERAK
════════════════
Hozir "tenderda nima talab qilinadi" degan savol uch joyda uch xil
javob oladi: `tender_good` (reyestr pozitsiyalari), `ai_gonogo` ning
erkin matnli tahlili, va chatning `search_documents` natijasi. Ularni
JOIN qilib bo'lmaydi, filtrlab bo'lmaydi ("GOST talab qiladigan
tenderlarni ko'rsat") va har biriga ishonch darajasi berib bo'lmaydi.

`tender_requirement` shu uchtasini bitta TUZILGAN jadvalga yig'adi.

IKKI MANBA
══════════
    source='api'       reyestr pozitsiyalari — MODELSIZ, BEPUL, aniq
    source='document'  hujjat matnidan model ajratgani — J3 ning
                       qimmat qismi (Opus 5 + Batch API, qaror 3.4)

BU MODUL HOZIR FAQAT `api` MANBASINI QO'LLAB-QUVVATLAYDI. Sabab: u
pul sarflamaydi, darhol foyda beradi va hujjat ajratishga POYDEVOR
bo'ladi — jadval, `ON CONFLICT` mantiqi, yurish jurnali va sinovlar
o'sha-o'sha qoladi, faqat manba qo'shiladi.

IQTIBOS — `doc_chunk` GA FK YO'Q
════════════════════════════════
`etl_embed.py --chunks` bo'laklarni DELETE + INSERT bilan qayta
yozadi. FK bo'lganda har qayta bo'laklashda talablar CASCADE bilan
o'chib ketardi. Shuning uchun ko'rsatkich `file_ref` + `char_start`
(§16.32 bilan bir xil saboq: matn o'rni barqaror, bo'lak id si emas).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from api import db, xatolar

# =====================================================================
# SQL — modul bilan birga
#
# Loyiha konvensiyasi SQL ni `api/queries.py` da saqlaydi, lekin
# `api/ai_chat.py` da bo'lgani kabi bu yerdagi so'rovlar FAQAT shu
# quyi tizimga tegishli va modul bilan birga ko'chib yursin.
# =====================================================================

#: Reyestr pozitsiyalari — `source='api'` talablarining manbai.
SQL_GOODS = """
SELECT g.lot_id, g.good_code, g.name, g.unit, g.amount,
       g.category_uid, c.code AS category_code, c.title_ru AS category_title
FROM tender_good g
LEFT JOIN dim_category c ON c.category_uid = g.category_uid
WHERE g.tender_id = %(tender_id)s
ORDER BY g.lot_id NULLS FIRST, g.good_code
"""

#: Talab yozish. `ON CONFLICT` maqsadi `tender_requirement_uq` bilan
#: AYNAN mos kelishi SHART — J1 da bu beshta joyda jimgina buzilgan edi.
SQL_UPSERT = """
INSERT INTO tender_requirement
    (company_id, tender_id, lot_id, source, method, position_no, name, attrs,
     qty, unit, delivery_days, is_mandatory, confidence, raw_snippet,
     file_ref, char_start, char_end, model, review_status, mashina_holat)
VALUES
    (%(company_id)s, %(tender_id)s, %(lot_id)s, %(source)s, %(method)s,
     %(position_no)s, %(name)s, %(attrs)s::jsonb, %(qty)s, %(unit)s,
     %(delivery_days)s, %(is_mandatory)s, %(confidence)s, %(raw_snippet)s,
     %(file_ref)s, %(char_start)s, %(char_end)s, %(model)s,
     %(review_status)s, %(mashina_holat)s)
ON CONFLICT (company_id, tender_id, source, method, position_no, name)
DO UPDATE SET
    lot_id        = EXCLUDED.lot_id,
    attrs         = EXCLUDED.attrs,
    qty           = EXCLUDED.qty,
    unit          = EXCLUDED.unit,
    delivery_days = EXCLUDED.delivery_days,
    is_mandatory  = EXCLUDED.is_mandatory,
    confidence    = EXCLUDED.confidence,
    raw_snippet   = EXCLUDED.raw_snippet,
    file_ref      = EXCLUDED.file_ref,
    char_start    = EXCLUDED.char_start,
    char_end      = EXCLUDED.char_end,
    model         = EXCLUDED.model,
    -- INSON QARORI — IKKI TOMONLAMA HIMOYA.
    --
    -- 1-TUYNUK (tuzatildi): qayta ajratish `pending` ni qaytarib
    --    yozsa, tasdiqlangan talab yana navbatga tushardi va BUTUN
    --    KO'RIB CHIQISH ISHI bekor bo'lardi.
    --
    -- 2-TUYNUK (undan XAVFLIROQ): faqat holatni saqlash yetarli emas.
    --    Ssenariy:
    --       1. model ajratdi:     kafolat = "12 oy"
    --       2. inson tasdiqladi:  approved
    --       3. buyurtmachi hujjatni yangiladi: kafolat = "24 oy"
    --       4. qayta ajratish:    qiymat = "24 oy", holat = approved
    --    Natijada `approved` yorlig'i INSON KO'RMAGAN qiymatga
    --    o'tadi — va bu navbatda KO'RINMAYDI.
    --
    -- Shuning uchun qiymat o'zgarsa tasdiq BEKOR bo'ladi va talab
    -- navbatga qaytadi. `corrected_value` saqlanadi (inson tuzatgani
    -- yo'qolmaydi), lekin asl qiymat o'zgargani qayta ko'rib
    -- chiqishga sabab bo'ladi.
    review_status = CASE
        WHEN tender_requirement.review_status IN ('extracted', 'pending_review')
            THEN EXCLUDED.review_status
        WHEN tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN 'pending_review'
        ELSE tender_requirement.review_status END,
    -- INSON IZLARI TOZALANADI. Bu YANGI va MAJBURIY: qiymat o'zgargani
    -- uchun holat `pending_review` ga qaytsa, `reviewed_by` va
    -- `reviewed_at` joyida qolsa `tender_requirement_mashina_toza_chk`
    -- cheklovi UPSERT ni RAD ETADI.
    --
    -- Bu ATAYLAB shunday: aks holda "navbatda turibdi, lekin inson
    -- ko'rgan" degan yarim holat qolardi va navbat bilan hisoblagich
    -- BIR XIL bazadan IKKI xil javob berardi. Aynan shu chalkashlik
    -- 1 487 ta soxta "approved" ni tug'dirgan edi.
    --
    -- Inson mehnati YO'QOLMAYDI: `corrected_value`, `previous_value`
    -- va `review_note` saqlanadi, ya'ni "u nima degandi" bilinadi.
    reviewed_by = CASE
        WHEN tender_requirement.review_status
             NOT IN ('extracted', 'pending_review')
         AND tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN NULL
        ELSE tender_requirement.reviewed_by END,
    reviewed_at = CASE
        WHEN tender_requirement.review_status
             NOT IN ('extracted', 'pending_review')
         AND tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN NULL
        ELSE tender_requirement.reviewed_at END,
    review_action = CASE
        WHEN tender_requirement.review_status
             NOT IN ('extracted', 'pending_review')
         AND tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN NULL
        ELSE tender_requirement.review_action END,
    -- AKTOR IZI HAM TOZALANADI. Busiz qiymat o'zgarib holat navbatga
    -- qaytganda "falonchi tasdiqlagan" yorlig'i QOLARDI va u endi
    -- BOSHQA qiymatga tegishli bo'lardi — ya'ni yolg'on atribut.
    reviewed_actor_id = CASE
        WHEN tender_requirement.review_status
             NOT IN ('extracted', 'pending_review')
         AND tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN NULL
        ELSE tender_requirement.reviewed_actor_id END,
    reviewed_ishonch = CASE
        WHEN tender_requirement.review_status
             NOT IN ('extracted', 'pending_review')
         AND tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN NULL
        ELSE tender_requirement.reviewed_ishonch END,
    -- JURNALGA YOZAMIZ. Aks holda broker "men buni tasdiqlagandim-ku"
    -- deb hayron bo'ladi va tizimga ishonchi tushadi.
    review_note = CASE
        WHEN tender_requirement.review_status
             NOT IN ('extracted', 'pending_review')
         AND tender_requirement.attrs->>'qiymat'
             IS DISTINCT FROM EXCLUDED.attrs->>'qiymat'
            THEN 'qiymat_ozgardi: '
                 || COALESCE(tender_requirement.attrs->>'qiymat', '-')
                 || ' -> ' || COALESCE(EXCLUDED.attrs->>'qiymat', '-')
                 || ' (tasdiq bekor qilindi, qayta ko''rish kerak)'
        ELSE tender_requirement.review_note END,
    -- Mashina o'qi ajratishdan keladi va INSON qaroriga bog'liq emas.
    mashina_holat = EXCLUDED.mashina_holat,
    extracted_at  = now()
RETURNING id
"""

#: Yurish jurnali. "Topilmadi" va "hali ajratilmagan" ni AJRATADI —
#: aks holda har yurishda o'sha tender qayta modelga yuboriladi (PUL).
SQL_RUN_UPSERT = """
INSERT INTO tender_requirement_run
    (company_id, tender_id, method, status, n_requirements, min_confidence,
     content_hash, model, input_tokens, output_tokens, cost_usd, error)
VALUES
    (%(company_id)s, %(tender_id)s, %(method)s, %(status)s, %(n)s,
     %(min_conf)s, %(content_hash)s, %(model)s, %(in_tok)s, %(out_tok)s,
     %(cost)s, %(error)s)
ON CONFLICT (company_id, tender_id, method)
DO UPDATE SET
    status         = EXCLUDED.status,
    n_requirements = EXCLUDED.n_requirements,
    min_confidence = EXCLUDED.min_confidence,
    content_hash   = EXCLUDED.content_hash,
    model          = EXCLUDED.model,
    input_tokens   = EXCLUDED.input_tokens,
    output_tokens  = EXCLUDED.output_tokens,
    cost_usd       = EXCLUDED.cost_usd,
    error          = EXCLUDED.error,
    extracted_at   = now()
RETURNING company_id
"""

SQL_LIST = """
SELECT id, lot_id, source, method, position_no, name, attrs, qty, unit,
       delivery_days, is_mandatory, confidence, raw_snippet,
       file_ref, char_start, char_end, model, extracted_at
FROM tender_requirement
WHERE company_id = %(company_id)s AND tender_id = %(tender_id)s
ORDER BY is_mandatory DESC, source, position_no NULLS LAST, name
"""

SQL_RUN_GET = """
SELECT method, status, n_requirements, min_confidence, content_hash, model,
       cost_usd, error, extracted_at
FROM tender_requirement_run
WHERE company_id = %(company_id)s AND tender_id = %(tender_id)s
  AND method = %(method)s
"""

#: Ajratilmagan tenderlar — QAMROV bu yerda hal qilinadi.
#:
#: DIQQAT: qaror 3.3 "ochiq + katalogga mos" degan edi, lekin §16.33 da
#: katalog filtri amalda TUGAGANI o'lchandi (ochiq doirada atigi 3 ta
#: hujjat qoldirardi). Shuning uchun standart qamrov — BARCHA OCHIQ
#: tenderlar, `--catalog` esa ixtiyoriy tor variant.
SQL_PENDING = """
SELECT t.id, t.name, t.close_at
FROM tender t
WHERE (t.close_at IS NULL OR t.close_at > now())
  AND (
    -- Hech qachon yurgizilmagan
    NOT EXISTS (
        SELECT 1 FROM tender_requirement_run r
        WHERE r.tender_id = t.id AND r.company_id = %(company_id)s
          AND r.method = %(method)s)
    -- YOKI o'shanda MATN YO'Q edi, endi BOR.
    --
    -- O'LCHANGAN XATO: `pending` faqat "yurgizilganmi" ga qarardi,
    -- "kirish o'zgardimi" ga emas. Hujjat matni keyinroq chiqarilgan
    -- 236 ta tender `no_text` bo'lib qotib qolgan edi va qayta
    -- ko'rilmasdi — ya'ni talablari MANGU yo'q bo'lardi.
    OR EXISTS (
        SELECT 1 FROM tender_requirement_run r
        WHERE r.tender_id = t.id AND r.company_id = %(company_id)s
          AND r.method = %(method)s AND r.status = 'no_text'
          AND EXISTS (SELECT 1 FROM doc_chunk c WHERE c.tender_id = t.id))
  )
ORDER BY t.close_at NULLS LAST
LIMIT %(limit)s
"""


# =====================================================================
# Yordamchilar
# =====================================================================

def content_hash(text: str) -> str:
    """Barqaror SHA-256 — `api/ai_chat.content_hash()` bilan bir xil."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _goods_hash(goods: List[dict]) -> str:
    """Pozitsiyalar to'plamining hashi — o'zgarmasa qayta yozilmaydi."""
    xom = "|".join(
        f"{g.get('lot_id')}:{g.get('good_code')}:{g.get('name')}:"
        f"{g.get('amount')}:{g.get('unit')}"
        for g in goods)
    return content_hash(xom)


# =====================================================================
# 1. API MANBASI — modelsiz, bepul
# =====================================================================

def from_api(tender_id: int, company_id: int) -> Dict[str, Any]:
    """Reyestr pozitsiyalarini talabga aylantiradi.

    MODEL CHAQIRILMAYDI. Ma'lumot allaqachon tuzilgan — bizning ishimiz
    uni bitta jadvalga keltirish, shunda hujjatdan ajratilgan talablar
    bilan YONMA-YON turadi.

    `confidence = 1.00`: bu taxmin emas, reyestrdagi rasmiy yozuv.
    """
    goods = db.query(SQL_GOODS, {"tender_id": tender_id})
    if not goods:
        _run_yoz(company_id, tender_id, "reyestr", "ok", 0, None, None,
                 model=None, error="reyestrda pozitsiya yo'q")
        return {"tender_id": tender_id, "n": 0, "status": "ok"}

    yozildi = 0
    for i, g in enumerate(goods, 1):
        attrs: Dict[str, Any] = {"manba": "reyestr"}
        if g.get("category_uid"):
            attrs["kategoriya_uid"] = g["category_uid"]
        if g.get("category_code"):
            attrs["kategoriya_kod"] = g["category_code"]
        if g.get("category_title"):
            attrs["kategoriya"] = g["category_title"]
        if g.get("good_code"):
            attrs["good_code"] = g["good_code"]

        db.execute_returning(SQL_UPSERT, {
            "company_id": company_id,
            "tender_id": tender_id,
            "lot_id": g.get("lot_id"),
            "source": "api",
            "method": "reyestr",
            # REYESTR — manba platformasining RASMIY yozuvi, model
            # taxmini emas. Shuning uchun u navbatga TUSHMAYDI.
            #
            # LEKIN "approved" DEB YOZILMAYDI. Ilgari aynan shunday
            # edi va 1 487 qator "inson tasdiqlagan" bo'lib ko'rindi
            # (o'lchangan 2026-08-30, `reviewed_by` = 0). Ikki boshqa
            # gap bitta ustunga yuklangan edi:
            #     "bu ma'lumotga ishonsa bo'ladi"  -> mashina_holat
            #     "buni inson tasdiqladi"          -> review_status
            #
            # Endi ular AJRATILGAN. `review_status='extracted'` —
            # halol: mashina chiqardi, inson ko'rmadi, navbatda ham
            # emas. Ishonchlilik `mashina_holat='manba'` va
            # `confidence=1.00` dan o'qiladi.
            "review_status": "extracted",
            "mashina_holat": "manba",
            "position_no": i,
            "name": (g.get("name") or "").strip()[:2000] or f"pozitsiya {i}",
            "attrs": json.dumps(attrs, ensure_ascii=False),
            "qty": g.get("amount"),
            "unit": g.get("unit"),
            "delivery_days": None,      # reyestrda yo'q; hujjatdan keladi
            # Reyestr pozitsiyasi TALAB, lekin "majburiy shart" emas —
            # `is_mandatory` GOST/sertifikat kabi shartlar uchun.
            "is_mandatory": False,
            "confidence": 1.00,
            "raw_snippet": None,
            "file_ref": None,
            "char_start": None,
            "char_end": None,
            "model": None,
        })
        yozildi += 1

    _run_yoz(company_id, tender_id, "reyestr", "ok", yozildi, 1.00,
             _goods_hash(goods), model=None, error=None)
    return {"tender_id": tender_id, "n": yozildi, "status": "ok"}


# =====================================================================
# 2. Yurish jurnali
# =====================================================================

def _run_yoz(company_id: int, tender_id: int, method: str, status: str,
             n: int, min_conf: Optional[float], content_hash_: Optional[str],
             model: Optional[str] = None, error: Optional[str] = None,
             in_tok: Optional[int] = None, out_tok: Optional[int] = None,
             cost: Optional[float] = None) -> None:
    db.execute_returning(SQL_RUN_UPSERT, {
        "company_id": company_id, "tender_id": tender_id, "method": method,
        "status": status, "n": n, "min_conf": min_conf,
        "content_hash": content_hash_, "model": model,
        "in_tok": in_tok, "out_tok": out_tok, "cost": cost,
        "error": error,
    })


# =====================================================================
# 3. O'qish — iste'molchilar uchun (`ai_gonogo`, `compare_tenders`, UI)
# =====================================================================

def list_for(tender_id: int, company_id: int) -> List[dict]:
    """Tender talablari. `company_id` SESSIYADAN — model argumentidan EMAS."""
    return db.query(SQL_LIST, {"tender_id": tender_id,
                              "company_id": company_id})


def run_info(tender_id: int, company_id: int,
             method: str = "reyestr") -> Optional[dict]:
    """Ajratish yurishi haqida: bo'lganmi, nima bo'lgan, qancha turgan.

    `method` MAJBURIY ma'noda: naqsh yurishi va LLM yurishi BOSHQA-BOSHQA
    yozuv. Birini so'rab ikkinchisining holatini olish xato bo'lardi.
    """
    return db.query_one(SQL_RUN_GET, {"tender_id": tender_id,
                                      "company_id": company_id,
                                      "method": method})


def pending(company_id: int, limit: int = 100,
            method: str = "reyestr") -> List[dict]:
    """Shu USUL bilan hali ajratilmagan ochiq tenderlar."""
    return db.query(SQL_PENDING, {"company_id": company_id, "limit": limit,
                                  "method": method})


#: Prompt blokiga tushadigan eng ko'p talab. Ko'proq bo'lsa token
#: bekorga sarflanadi — modelga eng ishonchlilari kerak.
PROMPT_LIMIT = 40


def prompt_block(tender_id: int, company_id: int,
                 limit: int = PROMPT_LIMIT) -> str:
    """Talablarni MODEL O'QIYDIGAN matn blokiga aylantiradi.

    NEGA XOM HUJJAT MATNIDAN AFZAL: bu yerda talab allaqachon
    ajratilgan, ISHONCH darajasi bilan va IQTIBOS ko'rsatkichi bilan.
    Model uni qayta ajratishi shart emas — faqat baholaydi.

    ISHONCH KO'RSATILADI. Modelga "bu aniq ma'lumot" degan taassurot
    bermaymiz: naqsh bilan olingan talab kontekstni bilmaydi
    (`0.75`), bo'sh shablon esa umuman qiymatsiz (`0.40`). §16.29
    saboqi: past ishonchni YASHIRISH — eng qimmat xato turi.

    Bo'sh satr qaytsa — chaqiruvchi blokni QO'SHMAYDI, ya'ni
    "talablar yo'q" degan yolg'on taassurot bo'lmaydi.
    """
    rows = db.query("""
        SELECT
               -- KESILGANINI BILISH UCHUN. Oyna funksiyasi `LIMIT`
               -- dan OLDIN hisoblanadi, ya'ni bu FILTRDAN o'tgan
               -- HAMMASINING soni. Alohida `COUNT` so'rovi kerak
               -- emas va ikki so'rov orasida ma'lumot o'zgarib
               -- ketish ehtimoli ham yo'q.
               count(*) OVER () AS _jami,
               name, method, attrs->>'qiymat' AS qiymat,
               attrs->>'tur' AS tur, is_mandatory, confidence,
               file_ref, char_start, review_status, corrected_value,
               -- MODELGA AYTILADIGAN GAP DALILGA TAYANSIN.
               -- Ilgari faqat holatga qaralardi va "INSON TASDIQLAGAN"
               -- degan yorliq reyestr pozitsiyalariga ham tushardi.
               -- Endi holat CHECK bilan kafolatlangan, lekin dalilni
               -- ham olib kelamiz: model uchun yozilgan matn eng
               -- kuchli da'vo va u ikki qavat tekshirilsin.
               reviewed_by, mashina_holat
        FROM tender_requirement
        WHERE company_id = %(c)s AND tender_id = %(t)s
          AND source = 'document'
          -- RAD ETILGAN talab CHIQARILADI: inson uni "hujjatda yo'q"
          -- deb belgilagan, ya'ni u ARVOH. Modelga ko'rsatish —
          -- tasdiqlash ishini bekor qilish demak.
          AND review_status <> 'rejected'
        ORDER BY is_mandatory DESC, confidence DESC, name
        LIMIT %(l)s""",
        {"c": company_id, "t": tender_id, "l": limit})
    if not rows:
        return ""

    qatorlar = ["=== HUJJATDAN AJRATILGAN TALABLAR ==="]
    past = 0
    tasdiqlangan = 0
    for r in rows:
        conf = float(r["confidence"])
        holat = r["review_status"]
        # INSON TASDIQLAGAN talab — eng ishonchli ma'lumot. Uni
        # model ishonchi bilan bir xil ko'rsatish XATO bo'lardi.
        if holat in ("approved", "corrected") and r.get("reviewed_by"):
            tasdiqlangan += 1
            manba = "INSON TASDIQLAGAN"
        else:
            manba = f"ishonch {conf:.2f}, " + (
                "naqsh" if r["method"] == "naqsh" else "model")
            if conf < 0.60:
                past += 1
        qiymat = r["corrected_value"] or r["qiymat"] or "-"
        belgi = "!" if r["is_mandatory"] else " "
        qatorlar.append(f"{belgi} {r['name']}: {qiymat}  [{manba}]")

    izoh = [
        "",
        "'!' = majburiy shart. `ishonch` — 1.00 ga yaqin bo'lsa aniq,",
        "0.60 dan past bo'lsa TEKSHIRILISHI kerak.",
    ]
    if tasdiqlangan:
        izoh.append(f"{tasdiqlangan} ta talabni INSON tasdiqlagan — ular "
                    "ishonchli.")
    if past:
        izoh.append(f"DIQQAT: {past} ta talabning ishonchi past — ular "
                    "hujjatda TO'LDIRILMAGAN yoki chalkash yozilgan. "
                    "Ularni ANIQ ma'lumot sifatida ishlatma.")
    # KESILGANI ALOHIDA AYTILADI.
    #
    # Quyidagi umumiy ogohlantirish ("hujjatning barchasi emas")
    # BOSHQA narsa haqida: u hujjatda AJRATILMAGAN shartlar
    # bo'lishi mumkinligini aytadi. Bu yerdagi kesim esa
    # AJRATILGAN talablarning bir qismi ko'rsatilmaganini bildiradi
    # — va uni aytmaslik yomonroq: model 40 ta talabni TO'LIQ
    # ro'yxat deb o'qib, "boshqa majburiy shart yo'q" degan
    # xulosaga kelardi.
    #
    # O'lchandi (2026-09-04): 4 ta tenderda 40 dan ko'p talab bor
    # (eng kattasi 44). Bu blok PULLIK Go/No-Go promptiga kiradi.
    jami = int(rows[0].get("_jami") or len(rows))
    kesildi = max(0, jami - len(rows))
    if kesildi:
        izoh.append(
            f"DIQQAT: bu tenderda {jami} ta ajratilgan talab bor, "
            f"yuqorida FAQAT {len(rows)} tasi (majburiy va ishonchi "
            f"yuqori bo'lganlari). Qolgan {kesildi} tasi bu yerda YO'Q "
            f"— 'boshqa shart yo'q' deb XULOSA CHIQARMA.")
    izoh.append("Bu ro'yxat hujjatning BARCHASI emas — quyidagi xom "
                "matnda qo'shimcha shartlar bo'lishi mumkin.")
    return "\n".join(qatorlar + izoh)


def qisqa(tender_id: int, company_id: int) -> Dict[str, Any]:
    """Bir qatorlik ko'rinish — `compare_tenders` jadvali uchun.

    HAR TUR uchun ISHONCHI ENG YUQORI qiymat olinadi.
    `max()` ISHLATMAYMIZ: u alifbo bo'yicha tasodifiy qiymatni
    tanlaydi. Sinovda `tolov` uchun jarima stavkasini olib qo'ydi
    ("0,5% har kun uchun") — taqqoslash jadvalida bu CHALG'ITADI.
    """
    hisob = db.query_one("""
        SELECT count(*) FILTER (WHERE source = 'document') AS hujjatdan,
               count(*) FILTER (WHERE is_mandatory) AS majburiy,
               count(*) FILTER (WHERE confidence < 0.60) AS past,
               count(*) FILTER (WHERE review_status = 'pending_review')
                   AS kutayotgan,
               -- MASHINA chiqargani (reyestr) ALOHIDA sanaladi.
               -- Ilgari u "tasdiqlangan" ga qo'shilardi va interfeys
               -- "1487 tasdiqlangan" deb ko'rsatardi — hech kim
               -- ko'rmagan bo'lsa ham.
               count(*) FILTER (WHERE review_status = 'extracted')
                   AS mashina_chiqargan,
               count(*) FILTER (WHERE review_status IN ('approved','corrected'))
                   AS tasdiqlangan
        FROM tender_requirement
        WHERE company_id = %(c)s AND tender_id = %(t)s
          AND review_status <> 'rejected'""",
        {"c": company_id, "t": tender_id}) or {}

    # DISTINCT ON — har tur uchun eng ishonchli bitta qiymat.
    eng = {r["tur"]: r["qiymat"] for r in db.query("""
        SELECT DISTINCT ON (attrs->>'tur')
               attrs->>'tur' AS tur,
               -- Inson tuzatgan qiymat ustun turadi.
               COALESCE(corrected_value, attrs->>'qiymat') AS qiymat
        FROM tender_requirement
        WHERE company_id = %(c)s AND tender_id = %(t)s
          AND attrs->>'tur' IN ('kafolat', 'tolov', 'muddat', 'bazis')
          AND review_status <> 'rejected'
        -- TASDIQLANGAN talab ishonch darajasidan QAT'IY NAZAR birinchi.
        ORDER BY attrs->>'tur',
                 (review_status IN ('approved', 'corrected')) DESC,
                 confidence DESC, char_start NULLS LAST""",
        {"c": company_id, "t": tender_id})}

    return {
        "hujjatdan_talab": int(hisob.get("hujjatdan") or 0),
        "majburiy": int(hisob.get("majburiy") or 0),
        "past_ishonchli": int(hisob.get("past") or 0),
        "kutayotgan": int(hisob.get("kutayotgan") or 0),
        # MASHINA chiqargani ALOHIDA. Ilgari u "tasdiqlangan" ga
        # qo'shilardi va interfeys inson ko'rmagan talablarni
        # tasdiqlangan deb ko'rsatardi.
        "mashina_chiqargan": int(hisob.get("mashina_chiqargan") or 0),
        "tasdiqlangan": int(hisob.get("tasdiqlangan") or 0),
        "kafolat": eng.get("kafolat"),
        "tolov": eng.get("tolov"),
        "yetkazish": eng.get("muddat"),
        "bazis": eng.get("bazis"),          # INCOTERMS
    }


# =====================================================================
# KO'RIB CHIQISH (review)
#
# NEGA KERAK: `compliance.check()` ga tekshirilmagan talabni ulash AI
# xatosini QAROR QATLAMIGA o'tkazadi. Misol (t7886728): model
# "kafolat muddati ko'rsatilmagan (shablon bo'sh)" deb TO'G'RI yozdi,
# lekin cheklist buni ko'r-ko'rona o'qisa — ARVOH BLOCKER chiqadi
# ("kafolat sharti bajarilmagan"), holbuki shart qo'yilmagan.
# Noto'g'ri blocker — yo'q blockerdan yomonroq.
# =====================================================================

#: `compliance` va boshqa QAROR qatlamlari uchun kirish sharti.
#: Tasdiqlanmagan talab shu chegaradan past bo'lsa — cheklistda emas,
#: "tekshirish kerak" bo'limida ko'rinadi.
ISHONCH_CHEGARA = 0.85


# =====================================================================
# HOLAT LUG'ATI — IKKI O'Q, BIR-BIRIGA ARALASHMAYDI
# =====================================================================
#
# O'LCHANGAN SABAB (2026-08-30): bitta `review_status` ustuni ikki
# boshqa savolga javob berardi va ular bir-biriga aylanib ketgan edi:
#
#     "bu ma'lumotga ishonsa bo'ladimi?"   -> MASHINA savoli
#     "buni inson tasdiqladimi?"           -> INSON savoli
#
# Reyestr pozitsiyalari birinchisiga "ha" bergani uchun ikkinchisiga
# ham "ha" deb yozilgan edi: 1 487 qator `approved`, `reviewed_by`
# esa 0. Endi ular AJRATILGAN va baza ularni CHECK bilan ajratib
# turadi (`schema_patch_requirement_8.sql`).

#: MASHINA qo'yadigan holatlar. Ko'rib chiqish API si bularni
#: QO'YA OLMAYDI — faqat ajratish qatlami yozadi.
MASHINA_HOLATLARI = frozenset({
    "extracted",        # mashina chiqardi, navbatda EMAS (reyestr)
    "pending_review",   # navbatda, INSONNI kutmoqda
})

#: INSON qo'yadigan holatlar. Har biri `reviewed_by` + `reviewed_at`
#: + `review_action` ni TALAB qiladi (baza cheklovi).
#: `uncertain` — KO'RUVCHI ISHONCHI KOMIL EMAS.
#:
#: Ilgari faqat uchta yo'l bor edi va shubhadagi ko'ruvchi
#: MAJBURAN ulardan birini tanlardi. Amalda shubha "approved"
#: bo'lib yozilardi, chunki u eng kam qarshilikli tugma. Bu
#: o'lchovni JIMGINA buzardi: aniqlik yuqori ko'rinardi.
#:
#: `uncertain` HAM inson qarori — aktor, vaqt va amal shu
#: darajada majburiy. U "ko'rilmagan" DEGANI EMAS.
INSON_QARORLARI = frozenset({"approved", "rejected", "corrected",
                             "uncertain"})

#: Holat -> inson amali. Baza `tender_requirement_amal_chk` bilan
#: shu moslikni majburlaydi, bu yerda esa yagona manba.
AMAL = {"approved": "approve", "rejected": "reject",
        "corrected": "correct", "uncertain": "uncertain"}

#: `mashina_holat` lug'ati.
#:   manba       — platformaning RASMIY reyestr yozuvi (xulosa emas)
#:   ajratilgan  — matndan naqsh yoki model chiqargan
MASHINA_MANBA = "manba"
MASHINA_AJRATILGAN = "ajratilgan"


#: Ko'rib chiqish navbatining ustunlari va manbai.
#:
#: `tender t` JOIN QILINADI — `queries.build_text_search()` aynan shu
#: taxallusni kutadi va qidiruv qoidasi SHU YERDA QAYTA YOZILMAYDI.
#: Takrorlash "bosh ro'yxatda topiladi, navbatda topilmaydi"
#: holatini yasardi: `translit.variants()` lotin/kirill/o'zbek
#: shakllarini kengaytiradi va uni qo'lda takrorlash mumkin emas.
SQL_REVIEW_QUEUE_FROM = """
FROM v_requirement_review v
JOIN tender t ON t.id = v.tender_id
"""

#: Tartib VIEW ichida ham bor, lekin JOIN dan keyin unga
#: ISHONIB BO'LMAYDI (planner uni saqlashi shart emas). Shuning
#: uchun ANIQ yoziladi — view'dagi bilan AYNI: muddati yaqin
#: birinchi, keyin eng past ishonch.
SQL_REVIEW_QUEUE_TARTIB = """
ORDER BY v.close_at NULLS LAST, v.eng_past_ishonch NULLS LAST
"""

#: TANLANMA QIYSHIQLIGI — ATAYLAB YUMSHATILGAN.
#:
#: Past ishonchni tepaga chiqarish ISH JARAYONI uchun to'g'ri: qiyin
#: holatlar avval ko'riladi. Lekin J6 oltin to'plami shu navbatdan
#: yig'ilsa, u FAQAT eng qiyin holatlardan iborat bo'ladi va o'rtacha
#: aniqlikni haqiqiydan PAST ko'rsatadi. "Sifat pasaydi" degan
#: yolg'on xulosa aynan shundan chiqadi.
#:
#: Arzon tuzatish: har 5-chi YUQORI ishonchli talab ham tepaga
#: chiqariladi (~20%). Ko'rib chiqish yuki deyarli o'zgarmaydi,
#: oltin to'plam esa vakillik qiladi.
#:
#: `id % 5` — TASODIFIY EMAS, ATAYLAB: takrorlanadigan tanlanma
#: kerak. `random()` bilan har so'rov boshqa natija berardi va
#: sahifani yangilash tartibni o'zgartirib yuborardi.
SQL_REVIEW_ITEMS = """
SELECT id, name, method, source, attrs, confidence, is_mandatory,
       raw_snippet, file_ref, char_start, char_end,
       review_status, corrected_value, review_note, reviewed_at, doc_type,
       blind_value
FROM tender_requirement
WHERE company_id = %(company_id)s AND tender_id = %(tender_id)s
ORDER BY (review_status = 'pending_review') DESC,
         CASE WHEN confidence >= 0.90 AND (id %% 5) = 0 THEN 0 ELSE 1 END,
         is_mandatory DESC, confidence, name
"""

#: `company_id` SHARTDA — IDOR himoyasi. Boshqa kompaniyaning
#: talabini tasdiqlab bo'lmaydi.
SQL_REVIEW_SET = """
UPDATE tender_requirement
   SET review_status   = %(status)s,
       corrected_value = %(corrected)s,
       review_note     = %(note)s,
       -- `doc_type` BERILMASA ESKISI QOLADI (COALESCE): tasdiqlashni
       -- yorliqsiz ham qilish mumkin, lekin qo'yilgan yorliq
       -- TASODIFAN o'chib ketmasin.
       doc_type        = COALESCE(%(doc_type)s, doc_type),
       -- Yopiq rejimdagi MUSTAQIL javob. Bir marta yozilgach
       -- O'ZGARMAYDI: keyin model javobi ochiladi va inson fikrini
       -- o'zgartirsa ham, ASL mustaqil javob qolishi kerak — aks
       -- holda kelishmovchilik darajasi yolg'on chiqadi.
       blind_value     = COALESCE(blind_value, %(blind)s),
       -- TUZATISHDAN OLDINGI qiymat. Ilgari faqat "nimaga" saqlanardi,
       -- "nimadan" esa yo'q edi va uni keyin `attrs` dan qayta
       -- hisoblashga to'g'ri kelardi.
       previous_value  = CASE
           WHEN %(status)s = 'corrected'
               THEN COALESCE(previous_value, corrected_value,
                             attrs->>'qiymat', '(bo''sh)')
           ELSE previous_value END,
       reviewed_by     = %(by)s,
       -- AKTOR: qaysi ODAM. `reviewed_by` KOMPANIYA ni ko'rsatadi va
       -- u yetarli emas edi — shu ikkisi ALOHIDA saqlanadi.
       reviewed_actor_id = %(actor_id)s,
       reviewed_ishonch  = %(ishonch)s,
       reviewed_at     = now(),
       -- INSON AYNAN NIMA QILDI. `review_status` dan kelib chiqadi,
       -- lekin ALOHIDA yoziladi va CHECK ikkalasining mosligini
       -- majburlaydi — ya'ni holatni yozib amalni unutib bo'lmaydi.
       -- `AMAL` lug'atidan PARAMETR bilan keladi. Ilgari bu yerda
       -- `CASE` bor edi, ya'ni moslik IKKI joyda yozilgan edi
       -- (Python va SQL) va yangi holat qo'shilganda ulardan biri
       -- unutilishi mumkin edi.
       review_action   = %(amal)s
 WHERE id = %(id)s AND company_id = %(company_id)s
RETURNING id, tender_id, review_status, review_action, doc_type,
          reviewed_by, reviewed_actor_id, reviewed_ishonch,
          reviewed_at, previous_value, corrected_value
"""


#: Talab manbai bo'yicha filtr. Ustunlar `v_requirement_review` da
#: allaqachon sanab qo'yilgan — yangi so'rov kerak emas.
MANBA_FILTRLARI = {"naqsh": "v.naqshdan > 0", "llm": "v.modeldan > 0"}


def _review_queue_where(company_id: int, q: Optional[str],
                        region: Optional[str], faqat_past: bool,
                        manba: Optional[str], otgan: bool,
                        katalog_ids: Optional[List[int]]
                        ) -> Tuple[str, Dict[str, Any]]:
    """Ko'rib chiqish navbatining filtri."""
    from api import queries

    clauses = ["v.company_id = %(company_id)s"]
    params: Dict[str, Any] = {"company_id": company_id}

    if not otgan:
        # MUDDATI O'TGAN TENDER STANDART HOLDA CHIQARILADI.
        #
        # O'LCHANGAN NUQSON (2026-09-03). `v_requirement_review` da
        # muddat sharti YO'Q, tartib esa `close_at` bo'yicha O'SISH —
        # ya'ni eng erta yopilganlar ENG TEPADA turadi. Natijada
        # ko'rik navbatining BUTUN BIRINCHI SAHIFASI allaqachon
        # yopilgan tenderlardan iborat edi:
        #
        #     jami 989 · ochiq 455 · MUDDATI O'TGAN 534
        #     birinchi 10 qatorning 10 tasi ham o'tgan
        #
        # Ya'ni ko'ruvchining ko'rinadigan butun ish yuki O'LIK
        # tenderlar edi va buni hech narsa ko'rsatmasdi. Broker
        # navbatida bu nuqson yo'q — `v_routing_queue` muddatni
        # tekshiradi; ikki navbat bir xil qoidada bo'lsin.
        #
        # YASHIRILMAYDI, CHIQARILADI: `otgan=True` bilan ular
        # baribir ko'rinadi. Ko'rik natijasi J6 oltin to'plamiga
        # ham ketadi va yopilgan tenderning yorlig'i ham qimmatli —
        # lekin u KUNDALIK ish yukini ko'mib tashlamasin.
        clauses.append("(v.close_at IS NULL OR v.close_at > now())")
    if faqat_past:
        # PAST ISHONCH — ko'rikning eng qimmat qismi. `> 0` yetadi:
        # chegara `v_requirement_review` da (`confidence < 0.60`) va
        # uni bu yerda TAKRORLASH ikkinchi haqiqat yasardi.
        clauses.append("v.past_ishonchli > 0")
    if katalog_ids is not None:
        # "SIZGA MOS" — ta'rif `kodlash.mos_tender_idlari()` da.
        # Bo'sh ro'yxat "filtr yo'q" emas, "moslik yo'q" degani.
        clauses.append("v.tender_id = ANY(%(katalog_ids)s::bigint[])")
        params["katalog_ids"] = katalog_ids
    if manba:
        if manba not in MANBA_FILTRLARI:
            raise xatolar.Xato("INVALID_ENUM",
                               {"maydon": "manba", "qiymat": manba})
        clauses.append(MANBA_FILTRLARI[manba])
    if region:
        clauses.append("(t.area_path = %(region)s"
                       " OR t.area_path LIKE %(region)s || '.%%')")
        params["region"] = region
    if q:
        clause, q_params = queries.build_text_search(q)
        if clause:
            clauses.append(clause)
            params.update(q_params)
    return "WHERE " + " AND ".join(clauses), params


def review_queue(company_id: int, limit: int = 100,
                 q: Optional[str] = None, region: Optional[str] = None,
                 faqat_past: bool = False, manba: Optional[str] = None,
                 otgan: bool = False,
                 katalog: bool = False) -> Tuple[List[dict], int]:
    """Ko'rib chiqish navbati. Muddati yaqin tenderlar birinchi.

    QATORLAR **va** MOS KELGANLARNING JAMI SONI qaytariladi.

    NEGA JAMI ALOHIDA (2026-09-03): `limit` 100, navbat esa 484.
    Faqat qatorlarni bersak interfeys "100 ta" derdi va filtr
    natijasi JIMGINA kesilardi — qidirilgan tender ro'yxatda
    bo'lmasa foydalanuvchi buni "yo'q" deb o'qirdi.
    """
    # KATALOG FILTRI — id lar YAGONA manbadan.
    #
    # `only_open` NAVBAT QAMROVIGA ERGASHADI: `otgan=True` bo'lsa
    # navbat yopilgan tenderlarni ham ko'rsatadi va katalog to'plami
    # ham shunday bo'lishi kerak. Aks holda ikki filtr birga
    # qo'yilganda natija HAR DOIM bo'sh chiqardi — va sabab
    # ko'rinmasdi.
    katalog_ids = None
    if katalog:
        from api import kodlash
        katalog_ids = sorted(
            kodlash.mos_tender_idlari(company_id, only_open=not otgan))
    where, params = _review_queue_where(company_id, q, region,
                                        faqat_past, manba, otgan,
                                        katalog_ids)
    jami = db.scalar(f"SELECT count(*) {SQL_REVIEW_QUEUE_FROM} {where}",
                     params) or 0
    qatorlar = db.query(
        f"SELECT v.tender_id, v.tender_name, v.close_at, v.kutayotgan,"
        f"       v.modeldan, v.naqshdan, v.eng_past_ishonch,"
        f"       v.past_ishonchli, v.ajratilgan"
        f" {SQL_REVIEW_QUEUE_FROM} {where} {SQL_REVIEW_QUEUE_TARTIB}"
        f" LIMIT %(limit)s", {**params, "limit": limit})
    return qatorlar, int(jami)


def review_queue_manbalar(company_id: int, q: Optional[str] = None,
                          region: Optional[str] = None,
                          faqat_past: bool = False, otgan: bool = False,
                          katalog: bool = False) -> Dict[str, int]:
    """Har manba QANCHA natija berishini oldindan aytadi.

    O'LCHANGAN NUQSON (2026-09-03). "Manba" filtri qo'shilganda
    ko'rinishdagi `naqshdan` / `modeldan` ustunlariga qaraldi, lekin
    ular HAQIQATAN farq qiladimi degan savol berilmadi. Javob:
    YO'Q.

        naqsh   document  pending_review  8455
        reyestr api       extracted       2654   <- ko'rikka kirmaydi
        naqshdan>0: 989 tender · modeldan>0: 0 tender

    Ko'rik navbatiga faqat `pending_review` qatorlari kiradi, ular
    esa faqat `naqsh` va `llm` dan chiqadi — reyestr qatorlari
    `extracted` bilan yoziladi. LLM qatlami pullik va qulflangan
    (`api/ai.paid_guard`), ya'ni hech qachon yurmagan. Natijada
    "Naqshdan" hech narsani o'zgartirmasdi, "Modeldan" esa ro'yxatni
    bo'shatardi — foydalanuvchi ikkalasini ham BUZUQ deb o'qidi.

    FILTR OLIB TASHLANMADI, ROST GAPIRADIGAN QILINDI. LLM ajratish
    yurgan kunda u o'z-o'zidan foydali bo'ladi; bugun esa "Modeldan
    (0)" yozuvi sababni AYTADI. Hech narsa o'zgartira olmaydigan
    boshqaruv elementi — boshqaruv yo'qligidan YOMONROQ: u
    interfeys buzuq degan xulosani o'rgatadi.

    SONLAR BOSHQA FILTRLARNI HISOBGA OLADI: savol "shu manbani
    tanlasam nechta qoladi", "umuman nechta bor" emas.
    """
    katalog_ids = None
    if katalog:
        from api import kodlash
        katalog_ids = sorted(
            kodlash.mos_tender_idlari(company_id, only_open=not otgan))
    # `manba=None` — shartning O'ZI chiqarib tashlanadi, aks holda
    # har variant o'zini o'zi sanardi.
    where, params = _review_queue_where(company_id, q, region, faqat_past,
                                        None, otgan, katalog_ids)
    r = db.query_one(
        f"SELECT count(*) FILTER (WHERE {MANBA_FILTRLARI['naqsh']}) AS naqsh,"
        f"       count(*) FILTER (WHERE {MANBA_FILTRLARI['llm']})   AS llm"
        f" {SQL_REVIEW_QUEUE_FROM} {where}", params) or {}
    return {"naqsh": int(r.get("naqsh") or 0), "llm": int(r.get("llm") or 0)}


def review_items(tender_id: int, company_id: int) -> List[dict]:
    """Bitta tenderning barcha talablari — kutayotganlari birinchi."""
    return db.query(SQL_REVIEW_ITEMS, {"tender_id": tender_id,
                                       "company_id": company_id})


def bitta(req_id: int, company_id: int) -> Optional[dict]:
    """Bitta talabning HOZIRGI holati — audit uchun "oldin" surati.

    `company_id` SHARTDA: boshqa ijarachining qatorini o'qib
    bo'lmaydi (IDOR himoyasi o'qishda ham kerak).

    NEGA ALOHIDA FUNKSIYA: audit "oldingi holat" ni talab qiladi va
    uni o'zgarishdan KEYIN olish mumkin emas. Ilgari bu yerda
    `hasattr()` qorovuli bor edi va u funksiya yo'qligi uchun
    "oldin" ni HAR DOIM bo'sh qoldirardi — ya'ni audit yarim
    yozilardi va buni hech narsa ko'rsatmasdi.
    """
    return db.query_one(
        "SELECT id, review_status, review_action, mashina_holat, "
        "       corrected_value, previous_value, review_note, doc_type, "
        "       reviewed_by, reviewed_actor_id, reviewed_ishonch, "
        "       attrs->>'qiymat' AS qiymat "
        "  FROM tender_requirement "
        " WHERE id = %(id)s AND company_id = %(c)s",
        {"id": req_id, "c": company_id})


def review_set(req_id: int, company_id: int, status: str,
               corrected: Optional[str] = None,
               note: Optional[str] = None,
               by: Optional[int] = None,
               doc_type: Optional[str] = None,
               blind_value: Optional[str] = None, *,
               actor_id: Optional[int] = None,
               ishonch: Optional[str] = None) -> Optional[dict]:
    """INSON qarorini yozadi. FAQAT inson qarori.

    BU FUNKSIYA MASHINA HOLATINI QO'YA OLMAYDI. `extracted` va
    `pending_review` ro'yxatda ATAYLAB YO'Q: ular ajratish qatlamining
    ishi. Aks holda API orqali "bu talab endi ko'rilmagan" deb
    yozish mumkin bo'lardi va inson qarori jimgina yo'qolardi.

    `by` (kim) MAJBURIY. Ilgari u `Optional` edi va `None` bilan
    chaqirilsa baza `approved, reviewed_by IS NULL` qatorini QABUL
    QILARDI — aynan shu 1 487 ta soxta tasdiqni tug'dirgan sinf.
    Endi ikki qavat himoya bor: bu tekshiruv va
    `tender_requirement_inson_qarori_chk` cheklovi.

    `corrected` FAQAT `status='corrected'` uchun. Sxema buni CHECK
    bilan ham himoya qiladi — bu yerda ANIQ xato beramiz.
    """
    if status not in INSON_QARORLARI:
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "status", "qiymat": status})
    if by is None or int(by) <= 0:
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "by"})
    # ISHONCH DARAJASI MAJBURIY. `by` (kompaniya) kim ekanini
    # aytadi, `ishonch` esa BU MA'LUMOT QANCHALIK ISHONCHLI ekanini.
    # Ikkinchisisiz atribut o'z sifatini yashirardi.
    if not ishonch:
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "ishonch"})
    if ishonch not in ("erp_sessiya", "aktor_elon", "kompaniya_sessiyasi"):
        raise xatolar.Xato("TRUST_LEVEL_INVALID", {"ishonch": ishonch})
    if ishonch in ("erp_sessiya", "aktor_elon") and not actor_id:
        raise xatolar.Xato("ACTOR_REQUIRED_FOR_TRUST", {"ishonch": ishonch})
    if status == "corrected" and not (corrected or "").strip():
        raise xatolar.Xato("CORRECTED_VALUE_REQUIRED")
    if status != "corrected":
        corrected = None
    if doc_type is not None and doc_type not in doc_type_vocab():
        raise xatolar.Xato("INVALID_ENUM",
                           {"maydon": "doc_type", "qiymat": doc_type})
    return db.execute_returning(SQL_REVIEW_SET, {
        "id": req_id, "company_id": company_id, "status": status,
        "corrected": (corrected or "").strip()[:2000] or None,
        "note": (note or "").strip()[:2000] or None, "by": by,
        "actor_id": actor_id, "ishonch": ishonch, "amal": AMAL[status],
        "doc_type": doc_type,
        "blind": (blind_value or "").strip()[:2000] or None})


#: Yorliq lug'ati — `compliance.DOC_TYPES` + ikki maxsus qiymat.
#:
#: 'yoq' va 'boshqa' NULL DAN FARQ QILADI:
#:   NULL     — hali so'ralmagan
#:   'yoq'    — inson qaradi va "hujjat turiga tegishli emas" dedi
#:   'boshqa' — hujjat kerak, lekin lug'atda mos turi yo'q
#:
#: Bu farq §16.44 dagi "topilmadi va ajratilmagan" bilan bir sinf:
#: bo'sh qiymatning IKKI MA'NOSI bo'lsa, xulosa ham ikki xil chiqadi.
MAXSUS_TURLAR = ["yoq", "boshqa"]


def doc_type_vocab() -> List[str]:
    """Ruxsat etilgan `doc_type` qiymatlari."""
    from api import compliance
    return [d["code"] for d in compliance.DOC_TYPES] + MAXSUS_TURLAR


def doc_type_options() -> List[dict]:
    """Interfeys uchun ro'yxat: kod + o'qiladigan nom."""
    from api import compliance
    return ([{"code": d["code"], "label": d["label"], "base": d.get("base", False)}
             for d in compliance.DOC_TYPES]
            + [{"code": "boshqa", "label": "Boshqa (lug'atda yo'q)", "base": False},
               {"code": "yoq", "label": "Hujjat turiga tegishli emas",
                "base": False}])


# =====================================================================
# KO'RIB CHIQISH VAQTI — pilotning yagona noma'lum raqami
#
# "Har talabni inson tasdiqlaydi" modeli ISHLAYDIMI degan savol shu
# raqamga bog'liq:
#     ~2 daqiqa -> 611 tender = ~20 soat  -> to'liq ko'rib chiqish real
#     ~10 daqiqa -> ~100 soat             -> namuna asosida tekshirish
# =====================================================================

# =====================================================================
# PILOT — namuna tanlash va YOPIQ rejim
# =====================================================================

#: Yopiq rejimda ko'riladigan tender soni. Qolgani oddiy oqimda —
#: TEZLIK o'sha yerdan o'lchanadi, chunki u HAQIQIY ish sharoiti.
BLIND_N = 10

#: Har guruhdan nechta. Muddat bo'yicha saralash NAMUNA uchun qiyshiq:
#: tez yopiladigan tenderlar ma'lum turdagi bo'lishi mumkin
#: (shoshilinch xaridlar, kichik summalar, bir xil buyurtmachilar).
GURUH_N = 10


def pilot_yarat(company_id: int, blind_n: int = BLIND_N,
                guruh_n: int = GURUH_N,
                yaratgan: str = "nomalum") -> Dict[str, Any]:
    """Pilot to'plamini quradi: muddat + tasodif + summa.

    TO'PLAM BIR MARTA MUZLAYDI. Agar kompaniyada pilot allaqachon
    bo'lsa, funksiya HECH NARSA QO'SHMAYDI va mavjudini qaytaradi.

    Nega shunday: `ON CONFLICT DO NOTHING` o'zi YETARLI EMAS edi.
    Navbat vaqt bilan o'zgaradi — muddatlar o'tadi, ETL yangi
    tenderlar qo'shadi, `random()` boshqa qatorlar ustida ishlaydi.
    Shuning uchun ertasi kuni qayta chaqirilsa TANLOV BOSHQA chiqadi
    va 30 ta to'plamga yana 20 ta qo'shilardi (amalda shunday bo'ldi:
    30 -> 50). Bu namunani BUZADI: "30 tenderda mediana" degan
    maxraj yo'qoladi va yopiq rejim ulushi suziladi.

    YOPIQ REJIM birinchi `blind_n` tenderga beriladi — ANCHORING ga
    qarshi. Ular har uch guruhdan ARALASH olinadi, aks holda
    kelishmovchilik darajasi bitta guruhning xususiyatini
    ko'rsatardi.
    """
    # AVLOD TEKSHIRUVI — "qator bormi" EMAS, "FAOL avlod bormi".
    #
    # O'LCHANGAN NUQSON (2026-09-03): shart `count(*) > 0` edi, ya'ni
    # BITTA qator ham yangi pilotni ABADIY to'sardi. Jadvalda holat
    # ustuni umuman yo'q edi, shuning uchun tugagan yoki eskirgan
    # pilotni belgilash JOYI ham yo'q edi — yagona yo'l tarixiy
    # dalilni SQL bilan o'chirish bo'lardi, bu esa namunani va
    # "30 tenderda mediana" maxrajini yo'q qilardi.
    #
    # Endi holat `v_pilot_avlod` da DALILDAN hisoblanadi va yangi
    # avlod `faol` avlod BO'LMAGANDA ochiladi. Eski avlod JOYIDA
    # QOLADI — u boshqa `avlod` raqami ostida saqlanadi.
    faol = db.query_one("""
        SELECT avlod, tenderlar, hali_ochiq, qarorli_tender
          FROM v_pilot_avlod
         WHERE company_id = %(c)s AND holat = 'faol'
         ORDER BY avlod DESC LIMIT 1""", {"c": company_id})
    if faol:
        return {"qoshildi": 0, "jami": int(faol["tenderlar"]), "mavjud": True,
                "avlod": int(faol["avlod"]), "holat": "faol",
                "hali_ochiq": int(faol["hali_ochiq"]),
                "qarorli_tender": int(faol["qarorli_tender"]),
                "blind": int(db.scalar("""SELECT count(*) FROM review_pilot
                    WHERE company_id = %(c)s AND avlod = %(a)s
                      AND rejim = 'blind'""",
                    {"c": company_id, "a": faol["avlod"]}) or 0)}

    yangi_avlod = int(db.scalar("""
        SELECT COALESCE(max(avlod), 0) + 1 FROM review_pilot_avlod
         WHERE company_id = %(c)s""", {"c": company_id}) or 1)

    tanlangan: List[dict] = []
    korilgan: set = set()

    def qosh(rows, guruh):
        for r in rows:
            if r["id"] in korilgan:
                continue
            korilgan.add(r["id"])
            tanlangan.append({"id": r["id"], "guruh": guruh})

    # 1. MUDDATI YAQIN — ish jarayonining haqiqiy ustuvorligi
    qosh(db.query("""
        SELECT v.tender_id AS id FROM v_requirement_review v
        JOIN tender t ON t.id = v.tender_id
        WHERE v.company_id = %(c)s AND t.close_at > now()
        ORDER BY t.close_at LIMIT %(n)s""",
        {"c": company_id, "n": guruh_n}), "muddat")

    # 2. TASODIFIY — qiyshiqlikni yumshatadi.
    #    `setseed` bilan TAKRORLANADIGAN: bir xil chaqiruv bir xil
    #    natija bersin, aks holda pilotni qayta qurish boshqa to'plam
    #    berardi va taqqoslash buzilardi.
    db.query("SELECT setseed(0.42)")
    qosh(db.query("""
        SELECT v.tender_id AS id FROM v_requirement_review v
        WHERE v.company_id = %(c)s
        ORDER BY random() LIMIT %(n)s""",
        {"c": company_id, "n": guruh_n}), "tasodif")

    # 3. KATTA SUMMALI — boshqa turdagi hujjatlar bo'ladi
    qosh(db.query("""
        SELECT v.tender_id AS id FROM v_requirement_review v
        JOIN tender t ON t.id = v.tender_id
        WHERE v.company_id = %(c)s AND t.totalcost IS NOT NULL
        ORDER BY t.totalcost DESC LIMIT %(n)s""",
        {"c": company_id, "n": guruh_n}), "summa")

    # YOPIQ rejim har uch guruhdan aralash olinsin: ro'yxatni
    # guruhlar bo'ylab NAVBATMA-NAVBAT tekislaymiz.
    guruhlar: Dict[str, List[dict]] = {}
    for x in tanlangan:
        guruhlar.setdefault(x["guruh"], []).append(x)
    aralash: List[dict] = []
    i = 0
    while any(guruhlar.values()):
        for g in ("muddat", "tasodif", "summa"):
            if guruhlar.get(g):
                aralash.append(guruhlar[g].pop(0))
        i += 1

    # AVLOD REYESTRI AVVAL yoziladi: `review_pilot` qatorlari unga
    # tayanadi va reyestrsiz avlod `v_pilot_avlod` da UMUMAN
    # ko'rinmasdi — pilot "yo'q" bo'lib qolardi.
    db.execute_returning("""
        INSERT INTO review_pilot_avlod (company_id, avlod, yaratgan)
        VALUES (%(c)s, %(a)s, %(k)s)
        ON CONFLICT (company_id, avlod) DO NOTHING
        RETURNING avlod""",
        {"c": company_id, "a": yangi_avlod, "k": yaratgan})

    yozildi = 0
    for tartib, x in enumerate(aralash, 1):
        r = db.execute_returning("""
            INSERT INTO review_pilot
                (company_id, avlod, tender_id, guruh, rejim, tartib)
            VALUES (%(c)s, %(a)s, %(t)s, %(g)s, %(r)s, %(n)s)
            ON CONFLICT (company_id, avlod, tender_id) DO NOTHING
            RETURNING tender_id""",
            {"c": company_id, "a": yangi_avlod, "t": x["id"],
             "g": x["guruh"],
             "r": "blind" if tartib <= blind_n else "anchored",
             "n": tartib})
        if r:
            yozildi += 1

    return {"qoshildi": yozildi, "jami": len(aralash), "mavjud": False,
            "avlod": yangi_avlod, "holat": "faol",
            "blind": min(blind_n, len(aralash))}


def pilot_arxivla(company_id: int, avlod: int, kim: str) -> dict:
    """Avlodni ARXIVLAYDI — qatorlar O'CHIRILMAYDI.

    NEGA KERAK: `eskirdi` va `tugallandi` dalildan HOSIL bo'ladi,
    lekin ba'zan operator hali ochiq pilotni ATAYLAB yopmoqchi
    bo'ladi (namuna noto'g'ri tanlangan, ustuvorlik o'zgardi).
    Ungacha yagona yo'l qatorlarni o'chirish edi — ya'ni tarixiy
    dalilni yo'qotish.

    `kim` MAJBURIY: atributsiz arxivlash keyinchalik tiklab
    bo'lmaydigan bo'shliq qoldirardi (baza CHECK i ham talab qiladi).
    """
    if not (kim or "").strip():
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "kim"})
    r = db.execute_returning("""
        UPDATE review_pilot_avlod
           SET arxivlandi_at = now(), arxivlagan = %(k)s
         WHERE company_id = %(c)s AND avlod = %(a)s
           AND arxivlandi_at IS NULL
        RETURNING avlod, arxivlandi_at""",
        {"c": company_id, "a": avlod, "k": kim.strip()})
    if not r:
        raise xatolar.Xato("NOT_FOUND",
                           {"nima": f"pilot avlodi {avlod} (yoki allaqachon arxivlangan)"})
    return {"avlod": int(r["avlod"]), "holat": "arxivlandi"}


def pilot_royxat(company_id: int) -> List[dict]:
    """Pilot to'plami — holati bilan."""
    return db.query("""
        SELECT p.tender_id, p.guruh, p.rejim, p.tartib,
               t.name AS tender_name, t.close_at, t.totalcost,
               COALESCE(v.kutayotgan, 0) AS kutayotgan,
               o.opened_at, o.finished_at,
               EXTRACT(EPOCH FROM (o.finished_at - o.opened_at)) AS sekund
        FROM review_pilot p
        JOIN tender t ON t.id = p.tender_id
        LEFT JOIN v_requirement_review v
               ON v.tender_id = p.tender_id AND v.company_id = p.company_id
        LEFT JOIN requirement_review_open o
               ON o.tender_id = p.tender_id AND o.company_id = p.company_id
        WHERE p.company_id = %(c)s
          -- OXIRGI ARXIVLANMAGAN AVLOD. Busiz ro'yxat barcha
          -- avlodlarni ARALASHTIRIB berardi va ko'ruvchi qaysi
          -- to'plam ustida ishlayotganini bilmasdi.
          AND p.avlod = COALESCE((
                SELECT max(avlod) FROM review_pilot_avlod a
                 WHERE a.company_id = p.company_id
                   AND a.arxivlandi_at IS NULL), p.avlod)
        ORDER BY p.tartib""", {"c": company_id})


def pilot_rejim(tender_id: int, company_id: int) -> str:
    """Bu tender qaysi rejimda ko'riladi. Pilotda bo'lmasa 'anchored'."""
    r = db.scalar("""SELECT rejim FROM review_pilot
        WHERE company_id = %(c)s AND tender_id = %(t)s
        -- Bir tender ikki avlodda bo'lishi mumkin; ENG YANGISI amal
        -- qiladi, aks holda `blind`/`anchored` rejimi eski
        -- avloddan kelib qolardi.
        ORDER BY avlod DESC LIMIT 1""",
        {"c": company_id, "t": tender_id})
    return r or "anchored"


def review_ochildi(tender_id: int, company_id: int) -> None:
    """Tender ko'rib chiqish uchun ochilganini yozadi.

    `ON CONFLICT DO NOTHING` — QAYTA ochilsa vaqt YANGILANMAYDI. Aks
    holda sahifani yangilash o'lchovni nolga qaytarardi va natija
    haqiqiydan PAST chiqardi.

    Yozilmasa ko'rib chiqish TO'XTAMAYDI — o'lchov ikkinchi darajali.
    """
    try:
        db.execute_returning("""
            INSERT INTO requirement_review_open
                (company_id, tender_id, rejim)
            VALUES (%(c)s, %(t)s, %(r)s)
            ON CONFLICT (company_id, tender_id) DO NOTHING
            RETURNING tender_id""",
            {"c": company_id, "t": tender_id,
             "r": pilot_rejim(tender_id, company_id)})
    except Exception:                                    # noqa: BLE001
        pass


def review_tugadi(tender_id: int, company_id: int, n: int) -> None:
    """Oxirgi kutayotgan talab belgilangach vaqtni yopadi."""
    try:
        db.execute_returning("""
            UPDATE requirement_review_open
               SET finished_at = now(), n_reviewed = %(n)s
             WHERE company_id = %(c)s AND tender_id = %(t)s
               AND finished_at IS NULL
            RETURNING tender_id""",
            {"c": company_id, "t": tender_id, "n": n})
    except Exception:                                    # noqa: BLE001
        pass


def review_speed(company_id: int) -> dict:
    """Pilot natijasi: bir tenderni ko'rib chiqish vaqti.

    MEDIANA ham beriladi: bitta juda uzun tender o'rtachani buzadi,
    lekin medianaga ta'sir qilmaydi. Reja tuzishda mediana ishonchli.
    """
    r = db.query_one("""
        SELECT count(*) AS tenderlar,
               sum(n_reviewed) AS talablar,
               round(avg(sekund)) AS ortacha_sekund,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY sekund)::numeric)
                   AS mediana_sekund,
               round(min(sekund)) AS eng_tez,
               round(max(sekund)) AS eng_sekin,
               round(avg(sekund_talabga)) AS sekund_talabga
        FROM v_review_speed WHERE company_id = %(c)s""",
        {"c": company_id}) or {}
    n_tender = int(r.get("tenderlar") or 0)
    med = float(r.get("mediana_sekund") or 0)
    qolgan = db.scalar("""SELECT count(*) FROM v_requirement_review
                          WHERE company_id = %(c)s""", {"c": company_id}) or 0

    # NAVBAT O'SISH SUR'ATI — bashorat optimistik bo'lmasin.
    #
    # "qolgan 599 ta = 23.8 soat" degan hisob navbat MUZLAB turganini
    # taxmin qiladi. Aslida ETL soatiga ishlaydi va navbat to'lib
    # boradi. Agar o'sish sur'ati ko'rib chiqish sur'atidan yuqori
    # bo'lsa — "har talabni inson tasdiqlaydi" modeli UMUMAN
    # ishlamaydi, va buni raqam bilan ko'rish kerak.
    osish = db.scalar("""
        SELECT count(DISTINCT tender_id) FROM tender_requirement
        WHERE company_id = %(c)s AND review_status = 'pending_review'
          AND extracted_at > now() - interval '24 hours'""",
        {"c": company_id}) or 0

    # SOVUQ START. Birinchi kunlarda "oxirgi 24 soat" butun navbatni
    # qamrab oladi (o'lchandi: 604 dan 604), chunki quvur endigina
    # ishga tushgan. Bu SUR'AT EMAS — bir martalik to'ldirish.
    # Yorliqsiz qoldirilsa raqam "kuniga 604 ta kelyapti" deb
    # o'qilardi va xulosa teskari chiqardi.
    eng_eski = db.scalar("""
        SELECT EXTRACT(EPOCH FROM (now() - min(extracted_at))) / 86400.0
        FROM tender_requirement WHERE company_id = %(c)s""",
        {"c": company_id}) or 0.0
    osish_ishonchli = float(eng_eski) >= 2.0

    # Ko'rib chiqish sur'ati: mediana bo'yicha 8 soatlik ish kunida
    # nechta tender ko'rish mumkin.
    kunlik_quvvat = (round(8 * 3600 / med) if med else None)

    return {
        "olchangan_tender": n_tender,
        "olchangan_talab": int(r.get("talablar") or 0),
        "ortacha_sekund": float(r.get("ortacha_sekund") or 0),
        "mediana_sekund": med,
        "eng_tez": float(r.get("eng_tez") or 0),
        "eng_sekin": float(r.get("eng_sekin") or 0),
        "sekund_talabga": float(r.get("sekund_talabga") or 0),
        "navbatda_qolgan": int(qolgan),
        # MEDIANA bo'yicha bashorat — o'rtacha emas.
        "qolgan_soat": (round(med * qolgan / 3600, 1) if med else None),
        "sutkalik_osish": int(osish),
        # Quvur yangi bo'lsa yuqoridagi raqam SUR'AT EMAS.
        "osish_ishonchli": osish_ishonchli,
        "osish_izohi": (None if osish_ishonchli else
                        "Quvur endigina ishga tushgan "
                        f"({eng_eski:.1f} kun) — bu bir martalik "
                        "to'ldirish, sur'at emas."),
        "kunlik_quvvat": kunlik_quvvat,
        # ENG MUHIM XULOSA: navbat qisqaradimi yoki o'sadimi.
        # Sovuq startda XULOSA CHIQARILMAYDI.
        "quvvat_yetadimi": (None if (kunlik_quvvat is None
                                     or not osish_ishonchli)
                            else kunlik_quvvat > osish),
        "izoh": ("Hali o'lchov yo'q — kamida 10 ta tender ko'rib chiqilsin"
                 if n_tender < 10 else None),
    }


def labeled(company_id: int, limit: int = 1000) -> List[dict]:
    """Inson yorliqlagan to'plam — moslashtiruv ground truth i."""
    return db.query("""
        SELECT requirement_id, tender_id, name, amaldagi_qiymat, tur,
               method, confidence, is_mandatory, doc_type, review_status
        FROM v_requirement_labeled
        WHERE company_id = %(c)s
        ORDER BY reviewed_at DESC
        LIMIT %(l)s""", {"c": company_id, "l": limit})


def review_bulk(tender_id: int, company_id: int, status: str,
                by: Optional[int] = None, *,
                actor_id: Optional[int] = None,
                ishonch: Optional[str] = None) -> int:
    """Tenderning BARCHA navbatdagi talablarini bir holatga o'tkazadi.

    Faqat `approved`/`rejected`: ommaviy TUZATISH ma'nosiz, har
    qiymat alohida yoziladi.

    `by` MAJBURIY — bu ham INSON qarori, faqat ko'p qatorga. Ommaviy
    amal soxta tasdiq uchun eng qulay yo'l edi: bitta chaqiruv bilan
    yuzlab qatorga `approved` yozib, `reviewed_by` ni `None` qoldirish
    mumkin edi.

    FAQAT `pending_review` ga tegadi. `extracted` (reyestr) qatorlari
    ATAYLAB tashqarida: ular navbatda emas va ularni "hammasini
    tasdiqla" tugmasi bilan ko'rmasdan tasdiqlash aynan shu patch
    tuzatayotgan muammoni qaytarardi.
    """
    if status not in ("approved", "rejected"):
        raise xatolar.Xato("INVALID_ENUM",
                           {"maydon": "amal", "qiymat": "ommaviy"})
    if by is None or int(by) <= 0:
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "by"})
    # OMMAVIY AMAL — atribut uchun eng xavfli yo'l: bitta chaqiruv
    # yuzlab qatorga tegadi. Shuning uchun ishonch darajasi bu yerda
    # ham MAJBURIY.
    if ishonch not in ("erp_sessiya", "aktor_elon", "kompaniya_sessiyasi"):
        raise xatolar.Xato("TRUST_LEVEL_INVALID", {"ishonch": ishonch})
    if ishonch in ("erp_sessiya", "aktor_elon") and not actor_id:
        raise xatolar.Xato("ACTOR_REQUIRED_FOR_TRUST", {"ishonch": ishonch})
    rows = db.query("""
        UPDATE tender_requirement
           SET review_status = %(status)s,
               reviewed_by   = %(by)s,
               reviewed_actor_id = %(actor_id)s,
               reviewed_ishonch  = %(ishonch)s,
               reviewed_at   = now(),
               review_action = %(amal)s
         WHERE company_id = %(c)s AND tender_id = %(t)s
           AND review_status = 'pending_review'
        RETURNING id""",
        {"c": company_id, "t": tender_id, "status": status, "by": by,
         "amal": AMAL[status]})
    return len(rows)


# TODO(§16.51): `compliance.check()` bu funksiyani HALI
# CHAQIRMAYDI. Ulash ATAYLAB kechiktirilgan: `ISHONCH_CHEGARA`
# pilotsiz o'lchanmagan, pilot esa production gacha qoldirilgan.
# O'lchanmagan chegaraga qatlam qurish xato kiritish demak.
def ishonchli(tender_id: int, company_id: int) -> List[dict]:
    """QAROR qatlami uchun talablar — `compliance` shundan o'qisin.

    Shart: `approved`/`corrected` YOKI ishonchi `ISHONCH_CHEGARA`
    dan yuqori. Qolgani cheklistga TUSHMAYDI — arvoh blocker
    chiqmasin.

    IKKI ASOS, IKKI USTUN (2026-08-30 da tuzatildi):

        INSON asosi     review_status IN ('approved','corrected')
                        -> endi CHECK bilan kafolatlangan: bu holat
                           `reviewed_by IS NOT NULL` bo'lmasdan
                           yozilmaydi.
        MASHINA asosi   confidence >= ISHONCH_CHEGARA
                        -> reyestr pozitsiyalari shu yo'l bilan
                           kiradi (`confidence = 1.00`), inson
                           tasdig'i sifatida EMAS.

    ILGARI IZOH YOLG'ON EDI: u "inson tasdiqlagan" derdi, holbuki
    reyestr pozitsiyalari `approved` deb YOZIB QO'YILGAN edi
    (`reviewed_by IS NULL`, 1 487 qator) va birinchi shartga
    tushardi. Shu chalkashlik `v_review_disagreement` da soxta
    "0% kelishmovchilik", vaqt o'lchovida esa shishgan `n_reviewed`
    bergan (§16.67).

    Endi ular ustun darajasida ajratilgan va IZOHGA emas, CHEKLOVGA
    tayanadi. Natija AYNAN o'sha qatorlar (reyestr `confidence=1.00`
    orqali kiradi), lekin SABABI endi halol.

    Har qator `inson_tasdiqladi` bayrog'ini olib keladi — chaqiruvchi
    "nima uchun bu yerda" degan savolga javob topsin.
    """
    return db.query("""
        SELECT id, name, attrs, is_mandatory, confidence, review_status,
               mashina_holat, reviewed_by, reviewed_at,
               COALESCE(corrected_value, attrs->>'qiymat') AS qiymat,
               previous_value, file_ref, char_start,
               (review_status IN ('approved', 'corrected')) AS inson_tasdiqladi,
               (confidence >= %(ch)s)                       AS mashina_ishonchli
        FROM tender_requirement
        WHERE company_id = %(c)s AND tender_id = %(t)s
          AND review_status <> 'rejected'
          AND (review_status IN ('approved', 'corrected')
               OR confidence >= %(ch)s)
        ORDER BY is_mandatory DESC, confidence DESC""",
        {"c": company_id, "t": tender_id, "ch": ISHONCH_CHEGARA})


def summary(tender_id: int, company_id: int) -> Dict[str, Any]:
    """Qisqacha: nechta talab, nechtasi majburiy, eng past ishonch.

    `ai_gonogo` va `compare_tenders` shu ko'rinishni ishlatadi —
    to'liq ro'yxat ularga og'irlik qiladi.
    """
    r = db.query_one("""
        SELECT count(*) AS jami,
               count(*) FILTER (WHERE is_mandatory) AS majburiy,
               -- IKKI O'Q ALOHIDA SANALADI. `ai_gonogo` va
               -- `compare_tenders` shu ko'rinishni o'qiydi va ular
               -- "tasdiqlangan" ni inson roziligi deb tushunishi
               -- kerak — mashina chiqargani BOSHQA raqam.
               count(*) FILTER (WHERE review_status = 'pending_review')
                   AS navbatda,
               count(*) FILTER (WHERE review_status = 'extracted')
                   AS mashina_chiqargan,
               count(*) FILTER (WHERE reviewed_by IS NOT NULL)
                   AS inson_kordi,
               count(*) FILTER (WHERE source = 'document') AS hujjatdan,
               count(*) FILTER (WHERE method = 'naqsh') AS naqshdan,
               count(*) FILTER (WHERE method = 'llm') AS modeldan,
               count(*) FILTER (WHERE confidence < 0.60) AS past,
               min(confidence) AS eng_past
        FROM tender_requirement
        WHERE company_id = %(c)s AND tender_id = %(t)s""",
        {"c": company_id, "t": tender_id}) or {}
    # HAR USUL uchun alohida yurish yozuvi bor. Faqat `reyestr` ga
    # qarash XATO edi: 36 ta talab bo'la turib "hali ajratilmagan"
    # deb ko'rsatardi, chunki bu tender reyestr yurishiga tushmagan
    # (u ochiq emas). Endi HAMMASI qaraladi.
    yurishlar = db.query(
        "SELECT method, status FROM tender_requirement_run "
        "WHERE company_id = %(c)s AND tender_id = %(t)s",
        {"c": company_id, "t": tender_id})
    yurish = {"status": ",".join(sorted(x["status"] for x in yurishlar))}         if yurishlar else None
    return {
        "jami": int(r.get("jami") or 0),
        "majburiy": int(r.get("majburiy") or 0),
        "hujjatdan": int(r.get("hujjatdan") or 0),
        "naqshdan": int(r.get("naqshdan") or 0),
        "modeldan": int(r.get("modeldan") or 0),
        "past_ishonchli": int(r.get("past") or 0),
        "navbatda": int(r.get("navbatda") or 0),
        "mashina_chiqargan": int(r.get("mashina_chiqargan") or 0),
        "inson_kordi": int(r.get("inson_kordi") or 0),
        "eng_past_ishonch": (float(r["eng_past"])
                             if r.get("eng_past") is not None else None),
        "usullar": [x["method"] for x in yurishlar],
        "holat": (yurish or {}).get("status"),
        # IZOH SHART: "0 ta talab" ikki xil ma'no beradi — "hujjatda
        # talab yo'q" yoki "hali ajratilmagan". Modelga qaysi biri
        # ekanini aytmasak, u birinchisini taxmin qiladi.
        "izoh": ("Talablar hali AJRATILMAGAN — bu 'talab yo'q' degani "
                 "EMAS" if not yurishlar else None),
    }
