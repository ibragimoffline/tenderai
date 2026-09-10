#!/usr/bin/env python3
"""
BO'LAKKA BO'LISH va VEKTORLASH ETL  (J2)
========================================
`tender_document_text` dagi matnni RAG uchun bo'laklarga bo'ladi va
(pgvector mavjud bo'lsa) vektorlaydi.

IKKI BOSQICH — ATAYLAB AJRATILGAN:

  1. BO'LAKKA BO'LISH — sof Python, hech qanday kengaytma kerak emas.
     Natija `doc_chunk` ga yoziladi (`embedding` ustuni NULL qoladi).
  2. VEKTORLASH — embedding modeli va `pgvector` talab qiladi.

Nega ajratilgan: `pgvector` hozir serverda YO'Q (reja_ai_chat.md J0.1) va
uni o'rnatish administrator huquqini talab qiladi. Bo'lakka bo'lish esa
undan mustaqil — uni hozir qilib qo'yish mumkin, vektorlash keyin ustiga
qo'shiladi. Bo'laklar `search_tsv` bilan LEKSIK qidiruvda darhol ishlaydi.

Ishga tushirish:
    python etl_embed.py --chunks              # faqat bo'lakka bo'lish
    python etl_embed.py --chunks --limit 50   # sinov
    python etl_embed.py --vectors             # vektorlash (pgvector kerak)
    python etl_embed.py --count-only          # SANAYDI, yozmaydi

QAMROV: `etl_doc_text.py` bilan bir xil tamoyil — faqat matni bor
hujjatlar (`status='ok'`). Qamrovni kengaytirish `--all` bilan.

Reja: reja_ai_chat.md §6 (RAG) · Sxema: schema_patch_ai_chat.sql
"""
import argparse
import json
import hashlib
import os
import re
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:                                    # pragma: no cover
    load_dotenv = None

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
except ImportError:                                    # pragma: no cover
    psycopg2 = None


# ---------------------------------------------------------------------------
# 1. BO'LAKKA BO'LISH — sof funksiyalar (bazasiz sinaladi)
# ---------------------------------------------------------------------------
#: Bo'lak hajmi. Tender hujjatlarida bandlar qisqa, 1000 belgi bitta talabni
#: to'liq qamrab oladi va promptga ham arzon tushadi (reja §6.3).
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1000"))

#: Ustma-ustlik: chegarada kesilgan jumla YO'QOLMASIN. Ikki qo'shni bo'lak
#: shu qadar belgini baham ko'radi.
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "150"))

#: Shundan qisqa bo'lak saqlanmaydi — qidiruvda shovqin beradi.
MIN_CHUNK = 80

#: Chegarani shu oraliqda ORQAGA surib, tabiiy joyni qidiramiz.
#: Katta bo'lsa bo'laklar juda notekis bo'lib qoladi.
_LOOKBACK = 250

#: Chegara ustuvorligi: avval xatboshi, keyin jumla oxiri, keyin bo'shliq.
#: Jadval qatorini o'rtasidan kesmaslik uchun xatboshi birinchi.
_BOUNDARIES = (
    re.compile(r"\n\s*\n"),                 # xatboshi
    re.compile(r"[.!?…]\s"),                # jumla oxiri
    re.compile(r"[;:]\s"),                  # band ichidagi bo'linish
    re.compile(r"\n"),                      # qator
    re.compile(r"\s"),                      # bo'shliq
)


def _kesish_nuqtasi(text: str, boshi: int, ideal: int) -> int:
    """`ideal` ga eng yaqin TABIIY chegarani topadi (undan ORQADA).

    Qaytadi: absolyut indeks. Tabiiy chegara topilmasa `ideal` ning o'zi —
    ya'ni so'z o'rtasidan kesish faqat ILOJI BO'LMAGANDA sodir bo'ladi.
    """
    if ideal >= len(text):
        return len(text)

    quyi = max(boshi + MIN_CHUNK, ideal - _LOOKBACK)
    oyna = text[quyi:ideal]
    if not oyna:
        return ideal

    for naqsh in _BOUNDARIES:
        oxirgi = None
        for m in naqsh.finditer(oyna):
            oxirgi = m
        if oxirgi is not None:
            return quyi + oxirgi.end()
    return ideal


def chunk_text(text: str, size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> List[Tuple[int, int, str]]:
    """Matnni bo'laklarga bo'ladi.

    Qaytadi: `[(char_start, char_end, matn), ...]` — ofsetlar XOM matnga
    nisbatan. Bu MAJBURIY: iqtibos hujjatning aniq joyiga bog'lanadi
    ("qora quti bo'lmasin" tamoyili, reja §6.3).

    Kafolatlar:
      * `text[char_start:char_end] == matn` — har doim;
      * bo'laklar TARTIBLI va butun matnni qoplaydi (ustma-ustliksiz hisobda);
      * bo'sh yoki MIN_CHUNK dan qisqa bo'lak QAYTMAYDI (oxirgisidan tashqari,
        agar u yagona bo'lsa).
    """
    if not text:
        return []
    text_len = len(text)
    if text_len <= size:
        s = text.strip()
        return [(0, text_len, text)] if s else []

    out: List[Tuple[int, int, str]] = []
    boshi = 0
    while boshi < text_len:
        ideal = boshi + size
        oxiri = _kesish_nuqtasi(text, boshi, ideal)
        if oxiri <= boshi:                     # himoya: cheksiz tsikl bo'lmasin
            oxiri = min(boshi + size, text_len)

        bolak = text[boshi:oxiri]
        if bolak.strip() and (len(bolak) >= MIN_CHUNK or not out):
            out.append((boshi, oxiri, bolak))

        if oxiri >= text_len:
            break
        # Keyingi bo'lak `overlap` belgi orqadan boshlanadi.
        keyingi = oxiri - overlap
        boshi = keyingi if keyingi > boshi else oxiri
    return out


def content_hash(text: str) -> str:
    """Bo'lak matnining barqaror SHA-256 (qayta vektorlashni oldini oladi)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def guess_lang(text: str) -> Optional[str]:
    """Bo'lak tili — TAXMINIY, faqat statistika uchun.

    Aniq aniqlash kutubxonasi qo'shilmaydi: bu qiymat qidiruvga TA'SIR
    QILMAYDI (tsvector 'simple' konfiguratsiyasi tildan mustaqil), u faqat
    "qaysi hujjat qaysi tilda" degan hisobot uchun.
    """
    if not text:
        return None
    kiril = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    lotin = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    if kiril + lotin < 20:
        return None
    if kiril > lotin * 2:
        return "ru"
    if lotin > kiril * 2:
        return "uz"
    return None


# ---------------------------------------------------------------------------
# 2. BAZA
# ---------------------------------------------------------------------------
TARGETS_SQL = """
SELECT t.tender_id, t.file_ref, t.text, t.char_count
FROM tender_document_text t
WHERE t.status = 'ok' AND t.text IS NOT NULL AND length(t.text) >= %(min_len)s
  AND (%(all)s OR NOT EXISTS (
        SELECT 1 FROM doc_chunk c
         WHERE c.tender_id = t.tender_id AND c.file_ref = t.file_ref))
ORDER BY t.tender_id DESC, t.file_ref
"""

DELETE_OLD_SQL = ("DELETE FROM doc_chunk "
                  "WHERE tender_id = %(tender_id)s AND file_ref = %(file_ref)s")

INSERT_SQL = """
INSERT INTO doc_chunk (tender_id, file_ref, chunk_no, text,
                       char_start, char_end, token_count, lang, content_hash)
VALUES %s
ON CONFLICT (tender_id, file_ref, chunk_no) DO NOTHING
"""

VECTOR_READY_SQL = ("SELECT count(*) = 1 AS ok FROM pg_extension "
                    "WHERE extname = 'vector'")

#: Vektorlanmagan bo'laklar — MUDDAT USTUVORLIGI bilan.
#:
#: OLDIN `ORDER BY id` edi, ya'ni FIFO. Bu jimgina xato: yangi bo'lak
#: eng KATTA `id` oladi va navbat OXIRIGA tushadi. Ya'ni bugun kelgan
#: tender butun eski qoldiq tugagunicha kutadi — 40 000 lik qoldiqda
#: bu bir necha kun. Soatlik jadval qo'yishning foydasi yo'qolardi:
#: quvur tez-tez yuradi, lekin YANGI hujjatga yetib bormaydi.
#:
#: Endi tartib:
#:   1. OCHIQ tender bo'laklari birinchi (yopilganiga taklif berilmaydi);
#:   2. muddati YAQIN bo'lgani oldin (shoshilinchroq);
#:   3. keyin yangi bo'lak (`id DESC`).
#:
#: NARXI O'LCHANDI: 5 ms -> 138 ms bir partiyaga (42k qoldiqda, sort
#: kerak bo'lgani uchun). Soatlik yurishda 32 partiya = 4.4 s. Yangi
#: tenderning bir soatda tayyor bo'lishi bunga arziydi.
#:
#: Uzilishga chidamlilik saqlanadi: shart `embedding IS NULL`, har
#: partiyadan keyin commit — qayta yurgizilsa QOLGANIDAN davom etadi.
PENDING_SQL = """
SELECT c.id, c.text, c.content_hash
FROM doc_chunk c
LEFT JOIN tender t ON t.id = c.tender_id
WHERE c.embedding IS NULL
  -- YAROQSIZ va BUTUNLAY YIQILGAN bo'laklar navbatga TUSHMAYDI.
  -- Ilgari shart faqat `embedding IS NULL` edi va yiqilgan bo'lak
  -- har yurishda qayta urinilardi — navbat boshida turib qolib,
  -- yangi bo'laklarni to'sardi.
  AND embed_holat_aniqla(c.embed_holat, false, c.text)
      IN ('navbatda', 'eskirgan', 'yiqildi')
ORDER BY (t.close_at IS NOT NULL AND t.close_at > now()) DESC,
         t.close_at ASC NULLS LAST,
         c.id DESC
LIMIT %(batch)s
"""

#: XESHDAN NUSXALASH — bir xil matn IKKI MARTA hisoblanmaydi.
#:
#: O'LCHANGAN (2026-08-30): 61 392 vektorsiz bo'lakdan 31 138 tasining
#: (51%) matni ALLAQACHON vektorlangan. `content_hash` ustuni bor edi
#: va `NOT NULL`, lekin vektorlash undan foydalanmasdi — ya'ni model
#: bir xil matn uchun qayta chaqirilardi.
#:
#: `embed_model` SHARTDA: boshqa model bilan hisoblangan vektorni
#: nusxalash MODELLARNI ARALASHTIRARDI va o'xshashlik masofasi
#: ma'nosiz bo'lardi.
#:
#: `DISTINCT ON` — bir xeshda bir necha manba bo'lishi mumkin, biri
#: yetarli.
NUSXALA_SQL = """
WITH manba AS (
    SELECT DISTINCT ON (content_hash)
           content_hash, embedding, embed_model, embed_dims
    FROM doc_chunk
    WHERE embedding IS NOT NULL AND embed_model = %(model)s
      AND content_hash = ANY(%(hashes)s)
    ORDER BY content_hash, id
)
UPDATE doc_chunk c
   SET embedding          = m.embedding,
       embed_model        = m.embed_model,
       embed_dims         = COALESCE(m.embed_dims, %(dims)s),
       embed_holat        = 'ok',
       embedded_at        = now(),
       embed_content_hash = c.content_hash,
       embed_manba        = 'xesh',
       embed_xato         = NULL,
       embed_xato_at      = NULL,
       embed_urinish      = 0
  FROM manba m
 WHERE c.content_hash = m.content_hash
   AND c.id = ANY(%(ids)s)
   AND c.embedding IS NULL
RETURNING c.id
"""

#: OMMAVIY XESH NUSXALASH — bitta SQL, MODEL CHAQIRILMAYDI.
#:
#: `NUSXALA_SQL` bilan AYNI mantiq, farqi: u PARTIYA ichida
#: ishlaydi (`c.id = ANY(...)`), bu esa BUTUN navbat bo'ylab.
#:
#: NEGA KERAK (o'lchangan 2026-09-01): navbatda 81 081 bo'lak bor
#: edi, shundan 42 325 tasi (52%) allaqachon vektorlangan matnning
#: NUSXASI. Ular partiya-partiya, modelning 2.3 bo'lak/s tezligiga
#: BOG'LANIB o'tardi — garchi ularga model UMUMAN kerak bo'lmasa
#: ham. 2 000 lik partiya 5.4 daqiqa olardi.
#:
#: Endi arzon ish AVVAL va BIR YO'LA bajariladi; modelga faqat
#: HAQIQATAN yangi matn qoladi.
#:
#: `embed_model` SHARTDA — boshqa model bilan hisoblangan vektorni
#: nusxalash modellarni aralashtirardi.
OMMAVIY_NUSXA_SQL = """
WITH manba AS (
    SELECT DISTINCT ON (content_hash)
           content_hash, embedding, embed_model, embed_dims
    FROM doc_chunk
    WHERE embedding IS NOT NULL AND embed_model = %(model)s
    ORDER BY content_hash, id
)
UPDATE doc_chunk c
   SET embedding          = m.embedding,
       embed_model        = m.embed_model,
       embed_dims         = COALESCE(m.embed_dims, %(dims)s),
       embed_holat        = 'ok',
       embedded_at        = now(),
       embed_content_hash = c.content_hash,
       embed_manba        = 'xesh',
       embed_xato         = NULL,
       embed_xato_at      = NULL,
       embed_urinish      = 0
  FROM manba m
 WHERE c.content_hash = m.content_hash
   AND c.embedding IS NULL
RETURNING c.id
"""


#: Bitta bo'lak YIQILGANDA. Butun partiya emas — BITTA bo'lak.
#:
#: Ilgari `embed_documents()` istisnosi butun yurishni to'xtatardi
#: va bo'lak `embedding IS NULL` bo'lib qolardi, ya'ni "navbatda"
#: dan farq qilmasdi. Endi u ALOHIDA holatda va sababi yozilgan.
YIQILDI_SQL = """
UPDATE doc_chunk
   SET embed_urinish = embed_urinish + 1,
       embed_holat   = CASE WHEN embed_urinish + 1 >= %(max)s
                            THEN 'butunlay_yiqildi' ELSE 'yiqildi' END,
       embed_xato    = %(xato)s,
       embed_xato_at = now()
 WHERE id = %(id)s
"""

#: Matni juda qisqa bo'lak — vektorlash MA'NOSIZ.
YAROQSIZ_SQL = """
UPDATE doc_chunk
   SET embed_holat = 'yaroqsiz',
       embed_xato  = %(xato)s, embed_xato_at = now()
 WHERE id = %(id)s
"""

#: Model o'zgarganda QAYTA VEKTORLASHNI belgilash. AVTOMATIK EMAS —
#: bu BOSHQARILADIGAN qaror: 95 874 vektorni qayta hisoblash soatlar
#: oladi va uni ETL o'zi boshlab yubormasligi kerak.
MODEL_OZGARDI_SQL = """
UPDATE doc_chunk
   SET embed_holat = 'eskirgan'
 WHERE embedding IS NOT NULL
   AND embed_model IS DISTINCT FROM %(model)s
RETURNING id
"""

#: Matni o'zgargan bo'laklar (vektor eskirgan).
MATN_OZGARDI_SQL = """
UPDATE doc_chunk
   SET embed_holat = 'eskirgan'
 WHERE embedding IS NOT NULL
   AND embed_content_hash IS NOT NULL
   AND embed_content_hash <> content_hash
RETURNING id
"""

SET_VECTOR_SQL = """
UPDATE doc_chunk
   SET embedding          = %(vec)s::vector,
       embed_model        = %(model)s,
       embed_dims         = %(dims)s,
       embed_holat        = 'ok',
       embedded_at        = now(),
       -- Vektor QAYSI matn uchun hisoblangani. `content_hash` bilan
       -- farq qilsa vektor eskirgani BILINADI.
       embed_content_hash = content_hash,
       embed_manba        = 'model',
       embed_xato         = NULL,
       embed_xato_at      = NULL,
       embed_urinish      = 0
 WHERE id = %(id)s
"""

#: Bitta bo'lak uchun eng ko'p urinish. Undan oshgach
#: `butunlay_yiqildi` va navbatdan CHIQADI — aks holda buzuq bo'lak
#: navbat boshida abadiy aylanardi.
MAX_URINISH = int(os.environ.get("EMBED_MAX_URINISH", "3"))

ACTIVE_MODEL_SQL = ("SELECT name, dims FROM embed_model WHERE is_active LIMIT 1")

PENDING_COUNT_SQL = "SELECT count(*) FROM doc_chunk WHERE embedding IS NULL"


def vec_literal(vec) -> str:
    """`[0.013,-0.204,...]` — `::vector` ga cast qilinadigan matn.

    `api/ai_chat.py` dagi bilan bir xil: psycopg2 Python ro'yxatini
    `vector` turiga o'zi o'girmaydi va biz `pgvector` Python paketiga
    BOG'LANMAYMIZ (bitta bog'liqlik kam).
    """
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

CHUNK_TABLE_SQL = ("SELECT count(*) = 1 AS ok FROM information_schema.tables "
                   "WHERE table_schema = 'public' AND table_name = 'doc_chunk'")


def _bir(conn, sql: str) -> bool:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return bool(row and row.get("ok"))


def fetch_targets(conn, args) -> List[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(TARGETS_SQL, {"min_len": MIN_CHUNK, "all": bool(args.all)})
        rows = [dict(r) for r in cur.fetchall()]
    return rows[:args.limit] if args.limit else rows


def save_chunks(conn, tender_id: int, file_ref: str,
                chunks: List[Tuple[int, int, str]]) -> int:
    """Bitta hujjatning bo'laklarini yozadi (idempotent: avval eskisi o'chadi)."""
    if not chunks:
        return 0
    qatorlar = []
    for i, (a, b, matn) in enumerate(chunks):
        qatorlar.append((tender_id, file_ref, i, matn, a, b,
                         # Token soni TAXMINIY: ~4 belgi = 1 token. Aniq
                         # hisob tokenizator talab qiladi va bu yerda
                         # faqat byudjet bahosi uchun kerak.
                         max(1, len(matn) // 4),
                         guess_lang(matn), content_hash(matn)))
    with conn.cursor() as cur:
        cur.execute(DELETE_OLD_SQL, {"tender_id": tender_id, "file_ref": file_ref})
        execute_values(cur, INSERT_SQL, qatorlar)
    return len(qatorlar)


# ---------------------------------------------------------------------------
# 2b. VEKTORLASH
# ---------------------------------------------------------------------------
#: Bir partiyadagi bo'lak soni. Katta partiya tezroq, lekin xotira ko'proq
#: va uzilishda ko'proq ish qaytadan bajariladi.
BATCH = int(os.environ.get("EMBED_BATCH", "32"))


#: Advisory lock kalitlari. Raqamlar IXTIYORIY, lekin BARQAROR bo'lishi
#: shart — boshqa joyda qayta ishlatilmasin.
LOCK_VECTORS = 918_273_641
LOCK_CHUNKS = 918_273_642


#: Ketma-ket o'tkazishlar shu songa yetsa — ogohlantirish.
OTKAZISH_OGOH = 3

#: Hisoblagich fayli. NEGA JADVAL EMAS: bu OPERATSION holat, sxemaga
#: aloqasi yo'q; jadval qo'shish migratsiya va `company_id` masalasini
#: keltirib chiqaradi. Fayl yo'qolsa hisob noldan boshlanadi — zarari
#: yo'q.
_OTKAZISH_FAYL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              ".etl_embed_otkazish.json")


def _otkazish_oqi() -> dict:
    try:
        with open(_OTKAZISH_FAYL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _otkazish_sana(conn, nom: str) -> int:
    """O'tkazishni sanaydi va yangi qiymatni qaytaradi."""
    h = _otkazish_oqi()
    h[nom] = int(h.get(nom, 0)) + 1
    try:
        with open(_OTKAZISH_FAYL, "w", encoding="utf-8") as f:
            json.dump(h, f)
    except OSError:
        pass            # hisoblagich yozilmasa ham ish to'xtamasin
    return h[nom]


def _otkazish_nolla(conn, nom: str) -> None:
    h = _otkazish_oqi()
    if h.pop(nom, None) is not None:
        try:
            with open(_OTKAZISH_FAYL, "w", encoding="utf-8") as f:
                json.dump(h, f)
        except OSError:
            pass


def _qulf_ol(conn, kalit: int) -> bool:
    """Sessiya darajasidagi qulf. Band bo'lsa `False` — KUTMAYDI.

    NEGA KERAK: `PENDING_SQL` `embedding IS NULL` bo'yicha tanlaydi va
    UPDATE dan OLDIN commit bo'lmaydi. Ikki yurish bir vaqtda ishlasa
    ikkalasi ham AYNI bo'laklarni oladi: model ikki marta hisoblaydi
    (CPU bekorga sarflanadi) va UPDATE lar bir-birini kutadi.
    Soatlik ETL avtomatlashtirilgach bu ehtimol real bo'ldi — qo'lda
    yurgizilgan uzoq vektorlash bilan ustma-ust tushishi mumkin.

    Qulf SESSIYA bilan bog'liq: jarayon yiqilsa PostgreSQL uni o'zi
    bo'shatadi, ya'ni "osilib qolgan qulf" muammosi yo'q.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (kalit,))
        return bool(cur.fetchone()[0])


def _qulf_qoy(conn, kalit: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (kalit,))


def vectorize(conn, args) -> None:
    """Vektorlanmagan bo'laklarni model orqali o'tkazadi.

    UZILISHGA CHIDAMLI: har partiyadan keyin commit va tanlash sharti
    `embedding IS NULL` — qayta yurgizilsa QOLGANIDAN davom etadi.
    Bu 20 000 bo'lakli yurish uchun majburiy: soatlab davom etishi mumkin.
    """
    if not _bir(conn, VECTOR_READY_SQL):
        sys.exit("XATO: `pgvector` kengaytmasi yo'q — vektorlash mumkin emas.\n"
                 "  .\\install_pgvector.ps1 (administrator) va so'ng\n"
                 "  psql -d xtxarid -c \"CREATE EXTENSION vector;\"")

    if not _qulf_ol(conn, LOCK_VECTORS):
        # JIMGINA CHIQMAYMIZ — loyihaning "xato jimgina o'tmaydi"
        # qoidasi bu yerda ham amal qiladi.
        #
        # XAVFLI SSENARIY: qo'lda uzoq vektorlash 4 soat yuradi, shu
        # davrda 4 ta rejalashtirilgan yurish hech narsa qilmasdan
        # `exit 0` bilan chiqadi. Keyin qo'lda yurish YIQILADI va buni
        # hech kim sezmaydi — jadvalda hammasi "muvaffaqiyatli".
        #
        # Shuning uchun KETMA-KET o'tkazishlar sanaladi va 3 tadan
        # oshsa OGOHLANTIRISH bo'ladi.
        n = _otkazish_sana(conn, "vectors")
        # XABAR IXCHAM: `run_etl.run_script` bola chiqishining faqat
        # OXIRGI 4 QATORINI jurnalga oladi. Uzun ogohlantirish kesilib,
        # jurnalga faqat SQL maslahati tushib qolardi — ya'ni eng
        # muhim qator YO'QOLARDI.
        if n >= OTKAZISH_OGOH:
            print(f"!! OGOHLANTIRISH: vektorlash ketma-ket {n} marta "
                  f"o'tkazildi — qulf {n} soatdan beri band. Osilib qolgan "
                  "jarayonni tekshiring (pg_locks / locktype='advisory').")
        else:
            print(f"Vektorlash allaqachon yurmoqda — o'tkazildi "
                  f"(ketma-ket {n}-marta).")
        return

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(ACTIVE_MODEL_SQL)
        model = cur.fetchone()
        cur.execute(PENDING_COUNT_SQL)
        qoldi = list(cur.fetchone().values())[0]
    if not model:
        sys.exit("XATO: `embed_model` da faol model yo'q.")
    if not qoldi:
        print("Vektorlanmagan bo'lak yo'q — hammasi tayyor.")
        return

    # Import KECH: model kutubxonasi og'ir (torch), `--chunks` uchun kerak emas.
    from api.ai_chat import embed_documents

    nishon = min(qoldi, args.limit) if args.limit else qoldi
    print(f"[1/1] {nishon:,} ta bo'lak, model: {model['name']} "
          f"({model['dims']} o'lchov), partiya: {BATCH}")

    import time
    t0 = time.time()
    bajarildi = 0
    # MANBA BO'YICHA AJRATILGAN SANOQ. Tezlik FAQAT model chaqiruvi
    # bo'yicha hisoblanadi — nusxalar uni shishirardi va "sekinlashdi"
    # degan yolg'on signal berardi.
    n_model = n_nusxa = n_yiqildi = 0
    while bajarildi < nishon:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(PENDING_SQL, {"batch": min(BATCH, nishon - bajarildi)})
            rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            break

        # --- 1-QADAM: XESHDAN NUSXALASH (arzon, model chaqirilmaydi) ---
        #
        # O'lchangan: navbatning 51% i allaqachon hisoblangan matnning
        # nusxasi. Model uchun ularni qayta hisoblash sof isrof.
        nusxalandi = []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(NUSXALA_SQL, {
                    "model": model["name"], "dims": model["dims"],
                    "hashes": [r["content_hash"] for r in rows],
                    "ids": [r["id"] for r in rows]})
                nusxalandi = [x["id"] for x in cur.fetchall()]
            conn.commit()
        except Exception as e:                              # noqa: BLE001
            # Nusxalash IXTIYORIY tezlashtirish. Yiqilsa ish
            # to'xtamaydi — model yo'li baribir ishlaydi.
            conn.rollback()
            print(f"      ! xeshdan nusxalash bajarilmadi: {str(e)[:100]}",
                  file=sys.stderr)
            nusxalandi = []

        nusxa_id = set(nusxalandi)
        qolgan_rows = [r for r in rows if r["id"] not in nusxa_id]
        n_nusxa += len(nusxa_id)

        if not qolgan_rows:
            bajarildi += len(rows)
            o_tgan = time.time() - t0
            print(f"      {bajarildi:,}/{nishon:,}  "
                  f"(butun partiya xeshdan nusxalandi)")
            continue

        # --- 2-QADAM: MODEL CHAQIRUVI ---
        #
        # PARTIYA YIQILSA BUTUN YURISH TO'XTAMAYDI. Ilgari istisno
        # yuqoriga ko'tarilar va bo'lak `embedding IS NULL` bo'lib
        # qolardi — ya'ni "navbatda" dan farq qilmasdi va sabab
        # hech qayerda saqlanmasdi.
        try:
            vecs = embed_documents([r["text"] for r in qolgan_rows])
        except Exception as e:                              # noqa: BLE001
            xato = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"      ! partiya yiqildi: {xato}", file=sys.stderr)
            with conn.cursor() as cur:
                for r in qolgan_rows:
                    cur.execute(YIQILDI_SQL, {"id": r["id"], "xato": xato,
                                              "max": MAX_URINISH})
            conn.commit()
            n_yiqildi += len(qolgan_rows)
            bajarildi += len(rows)
            continue

        if len(vecs) != len(qolgan_rows):
            sys.exit(f"XATO: model {len(vecs)} vektor qaytardi, "
                     f"{len(qolgan_rows)} kutilgandi.")
        # O'LCHAM MOS KELMASA TO'XTAYMIZ — bu SXEMA nosozligi va uni
        # bo'lak darajasida "yiqildi" deb yozish sababni yashirardi.
        if len(vecs[0]) != model["dims"]:
            sys.exit(f"XATO: model {len(vecs[0])} o'lchov qaytardi, "
                     f"`embed_model` da {model['dims']} yozilgan. "
                     "Sxema va model MOS EMAS.")

        with conn.cursor() as cur:
            for r, v in zip(qolgan_rows, vecs):
                cur.execute(SET_VECTOR_SQL, {"id": r["id"], "vec": vec_literal(v),
                                             "model": model["name"],
                                             "dims": model["dims"]})
        conn.commit()            # uzilsa ham shu partiya saqlanib qoladi
        n_model += len(qolgan_rows)

        bajarildi += len(rows)
        o_tgan = time.time() - t0
        # TEZLIK FAQAT MODEL yo'li bo'yicha — nusxalar shishirmasin.
        tezlik = n_model / max(o_tgan, 0.001)
        qolgan = (nishon - bajarildi) / max(bajarildi / max(o_tgan, 0.001), 0.001)
        print(f"      {bajarildi:,}/{nishon:,}  "
              f"(model {n_model:,} @ {tezlik:.1f}/s, xeshdan {n_nusxa:,}, "
              f"yiqildi {n_yiqildi}, ~{qolgan/60:.0f} daqiqa qoldi)")

    _otkazish_nolla(conn, "vectors")     # yurish bo'ldi — hisob tozalanadi
    _qulf_qoy(conn, LOCK_VECTORS)
    print(f"\nTayyor. {bajarildi:,} ta bo'lak: model {n_model:,}, "
          f"xeshdan {n_nusxa:,}, yiqildi {n_yiqildi} "
          f"({(time.time()-t0)/60:.1f} daqiqa).")
    if n_nusxa:
        print(f"      Xeshdan nusxalash {n_nusxa:,} ta model chaqiruvini "
              f"tejadi ({100 * n_nusxa / max(bajarildi, 1):.0f}%).")
    # ESLATMA MATNI 2026-08-25 da YANGILANDI. Eskisi "indeks bo'sh
    # jadvalga qurilgan" derdi — bu NOTO'G'RI edi: HNSW pgvector'da
    # inkremental quriladi. Va `REINDEX` ham to'g'ri maslahat emas:
    # standart `maintenance_work_mem` (64 MB) da 80k vektorli indeks
    # disk ustida birlashtiriladi va juda sekin quriladi.
    qoldi = 0
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(PENDING_COUNT_SQL)
        qoldi = list(cur.fetchone().values())[0]
    if qoldi:
        print(f"\nESLATMA: yana {qoldi:,} ta bo'lak vektorlanmagan — "
              "qayta yurgizing (qolganidan davom etadi).")
    else:
        print("\nESLATMA: hamma bo'lak vektorlangan. Endi HNSW indeksini "
              "qurish kerak:")
        print("  python _tests/ai_eval/yakunlash.py --indeks")


# ---------------------------------------------------------------------------
# 2c. TENDER DARAJASIDAGI VEKTOR
# ---------------------------------------------------------------------------
#
# NEGA KERAK: `api/ai_chat.SQL_HYBRID_TENDERS` ning semantik shoxi
# `tender_embedding` jadvalidan o'qiydi. Jadval BO'SH bo'lsa shox jimgina
# hech nima qaytarmaydi va `search_tenders` FAQAT LEKSIK bo'lib qoladi —
# tool ta'rifi esa modelga "ma'no bo'yicha ham qidiradi" deb va'da beradi.
# O'lchandi (2026-08-25): 2878 tender, `tender_embedding` da 0 qator.
#
# NIMA VEKTORLANADI: tender nomi + eng yirik pozitsiyalar nomi. Faqat nom
# yetarli emas — ko'p tender nomi "Тендер" yoki idora nomi bo'ladi,
# mazmun esa pozitsiyalarda ("nasos", "kompyuter butlovchi qismlari").
#
# UZILISHGA CHIDAMLI VA IDEMPOTENT: `content_hash` mos kelsa o'tkazib
# yuboriladi, ya'ni qayta yurgizish arzon va tender nomi/pozitsiyasi
# o'zgarsa o'sha tender qayta vektorlanadi.

#: Bitta tenderning vektorlanadigan matni.
#: Pozitsiyalar qiymat bo'yicha saralanadi — eng muhimi birinchi bo'lsin,
#: chunki matn `TENDER_TEXT_LIMIT` da kesiladi.
TENDER_TEXT_SQL = """
SELECT t.id,
       t.name,
       t.company_name,
       COALESCE((
           SELECT string_agg(x.name, ' | ' ORDER BY x.totalcost_item DESC NULLS LAST)
           FROM (SELECT g.name, g.totalcost_item
                 FROM tender_good g
                 WHERE g.tender_id = t.id AND g.name IS NOT NULL
                 ORDER BY g.totalcost_item DESC NULLS LAST
                 LIMIT 40) x
       ), '') AS goods
FROM tender t
WHERE (%(all)s OR t.close_at IS NULL OR t.close_at > now())
ORDER BY t.id
"""

TENDER_HASH_SQL = "SELECT tender_id, content_hash FROM tender_embedding"

TENDER_UPSERT_SQL = """
INSERT INTO tender_embedding (tender_id, embedding, embed_model, content_hash)
VALUES (%(id)s, %(vec)s::vector, %(model)s, %(hash)s)
ON CONFLICT (tender_id) DO UPDATE
   SET embedding = EXCLUDED.embedding,
       embed_model = EXCLUDED.embed_model,
       content_hash = EXCLUDED.content_hash
"""

#: Model kontekstiga sig'adigan uzunlik. E5 `max_seq_length=512` token —
#: undan uzun matn baribir kesiladi, uzatish esa bekorga vaqt oladi.
TENDER_TEXT_LIMIT = 1200


def tender_matni(row: dict) -> str:
    """Tender uchun vektorlanadigan matn. SOF FUNKSIYA — sinovga qulay."""
    qismlar = [(row.get("name") or "").strip(),
               (row.get("goods") or "").strip()]
    matn = ". ".join(q for q in qismlar if q)
    return matn[:TENDER_TEXT_LIMIT]


def vectorize_tenders(conn, args) -> None:
    """Tender darajasidagi vektorlarni to'ldiradi."""
    if not _bir(conn, VECTOR_READY_SQL):
        sys.exit("XATO: `pgvector` kengaytmasi yo'q.")

    if not _qulf_ol(conn, LOCK_CHUNKS):
        n = _otkazish_sana(conn, "tenders")
        print(f"Tender vektorlash ALLAQACHON yurmoqda — "
              f"o'tkazildi (ketma-ket {n}-marta).")
        return

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(ACTIVE_MODEL_SQL)
        model = cur.fetchone()
        if not model:
            sys.exit("XATO: `embed_model` da faol model yo'q.")
        cur.execute(TENDER_HASH_SQL)
        bor = {r["tender_id"]: r["content_hash"] for r in cur.fetchall()}
        cur.execute(TENDER_TEXT_SQL, {"all": bool(args.all)})
        rows = [dict(r) for r in cur.fetchall()]

    ish = []
    for r in rows:
        matn = tender_matni(r)
        if len(matn) < 8:                 # nomsiz/pozitsiyasiz — foydasi yo'q
            continue
        h = content_hash(matn)
        if bor.get(r["id"]) == h:         # o'zgarmagan — o'tkazamiz
            continue
        ish.append((r["id"], matn, h))
    if args.limit:
        ish = ish[:args.limit]

    print(f"[tender] jami {len(rows):,} tender, yangilanadi {len(ish):,} ta "
          f"(o'zgarmagani o'tkazib yuborildi)")
    if args.count_only or not ish:
        return

    from api.ai_chat import embed_documents

    import time
    t0, bajarildi = time.time(), 0
    for i in range(0, len(ish), BATCH):
        bolak = ish[i:i + BATCH]
        vecs = embed_documents([m for _, m, _ in bolak])
        if len(vecs) != len(bolak):
            sys.exit(f"XATO: model {len(vecs)} vektor qaytardi, "
                     f"{len(bolak)} kutilgandi.")
        if len(vecs[0]) != model["dims"]:
            sys.exit(f"XATO: model {len(vecs[0])} o'lchov qaytardi, "
                     f"`embed_model` da {model['dims']} yozilgan.")
        with conn.cursor() as cur:
            for (tid, _m, h), v in zip(bolak, vecs):
                cur.execute(TENDER_UPSERT_SQL, {
                    "id": tid, "vec": vec_literal(v),
                    "model": model["name"], "hash": h})
        conn.commit()                     # uzilsa ham shu partiya qoladi
        bajarildi += len(bolak)
        tezlik = bajarildi / max(time.time() - t0, 0.001)
        print(f"      {bajarildi:,}/{len(ish):,} "
              f"({tezlik:.1f} tender/s, ~{(len(ish)-bajarildi)/max(tezlik,0.001)/60:.0f} daq)")

    _otkazish_nolla(conn, "tenders")
    _qulf_qoy(conn, LOCK_CHUNKS)
    print(f"\nTayyor. {bajarildi:,} tender vektorlandi "
          f"({(time.time()-t0)/60:.1f} daqiqa).")
    print("Endi `search_tenders` semantik shoxi ham ishlaydi.")


# ---------------------------------------------------------------------------
# 3. Kirish nuqtasi
# ---------------------------------------------------------------------------
def kod_matni(row: dict) -> str:
    """Tasniflagich kodi uchun vektorlanadigan matn. SOF FUNKSIYA.

    `names` CHASTOTA bo'yicha tartiblangan (schema_patch_goodcode.sql),
    shuning uchun birinchi nomlar guruhning haqiqiy vakili. Hammasini
    emas, dastlabki 6 tasini olamiz: uzun ro'yxat guruhning ma'nosini
    suyultiradi.
    """
    nomlar = [n for n in (row.get("names") or []) if n][:6]
    return ", ".join(nomlar)[:400]


def vectorize_codes(conn, args) -> None:
    """`dim_good_code` lug'atini vektorlaydi (kod TAKLIFI uchun).

    NEGA ALOHIDA: bu vektorlar tenderlarni emas, LUG'ATNI tavsiflaydi.
    Ular faqat mahsulot qo'shilganda — bir marta — ishlatiladi, ya'ni
    korpus bilan birga o'smaydi (1237 ta kod, 5 va 8 daraja).

    MARKAZLASH: lug'at vektorlari ham `embed_centroid` bilan
    markazlashtiriladi — tender vektorlari bilan BIR XIL markaz, chunki
    ular bir fazoda solishtiriladi.
    """
    if not _bir(conn, VECTOR_READY_SQL):
        sys.exit("XATO: `pgvector` kengaytmasi yo'q.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(ACTIVE_MODEL_SQL)
        model = cur.fetchone()
        if not model:
            sys.exit("XATO: `embed_model` da faol model yo'q.")
        cur.execute("SELECT to_regclass('dim_good_code') AS t")
        if not cur.fetchone()["t"]:
            sys.exit("XATO: `dim_good_code` yo'q. Avval qo'llang:\n"
                     "  psql -d xtxarid -f schema_patch_goodcode.sql")
        # FAOL markaz — bo'lmasa markazlangan ustun to'ldirilmaydi va
        # taklif semantik shoxsiz (leksik + prior bilan) ishlaydi.
        cur.execute("SELECT id, vec FROM embed_centroid "
                    "WHERE model = %s AND is_active LIMIT 1", (model["name"],))
        markaz = cur.fetchone()
        cur.execute("SELECT code, names FROM dim_good_code "
                    "WHERE level = ANY(%s) AND names <> '{}' ORDER BY code",
                    ([5, 8],))
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT code, content_hash FROM good_code_embedding")
        bor = {r["code"]: r["content_hash"] for r in cur.fetchall()}

    ish = []
    for r in rows:
        matn = kod_matni(r)
        if len(matn) < 3:
            continue
        h = content_hash(matn)
        if bor.get(r["code"]) == h:            # o'zgarmagan
            continue
        ish.append((r["code"], matn, h))
    if args.limit:
        ish = ish[:args.limit]

    print(f"[kod] lug'at {len(rows):,} ta, yangilanadi {len(ish):,} ta")
    if args.count_only or not ish:
        if markaz is None:
            print("  [!] Faol markaz yo'q — `SELECT recompute_centroid();`")
        return

    from api.ai_chat import embed_documents
    import time
    t0, bajarildi = time.time(), 0
    for i in range(0, len(ish), BATCH):
        bolak = ish[i:i + BATCH]
        vecs = embed_documents([m for _, m, _ in bolak])
        if len(vecs) != len(bolak):
            sys.exit(f"XATO: model {len(vecs)} vektor qaytardi, "
                     f"{len(bolak)} kutilgandi.")
        with conn.cursor() as cur:
            for (code, _m, h), v in zip(bolak, vecs):
                cur.execute("""
                    INSERT INTO good_code_embedding
                        (code, embedding, embedding_c, centroid_id,
                         embed_model, content_hash)
                    VALUES (%(code)s, %(vec)s::vector,
                            CASE WHEN %(mvec)s::vector IS NULL THEN NULL
                                 ELSE l2_normalize(%(vec)s::vector - %(mvec)s::vector) END,
                            %(mid)s, %(model)s, %(hash)s)
                    ON CONFLICT (code) DO UPDATE SET
                        embedding    = EXCLUDED.embedding,
                        embedding_c  = EXCLUDED.embedding_c,
                        centroid_id  = EXCLUDED.centroid_id,
                        embed_model  = EXCLUDED.embed_model,
                        content_hash = EXCLUDED.content_hash""",
                    {"code": code, "vec": vec_literal(v),
                     "mvec": markaz["vec"] if markaz else None,
                     "mid": markaz["id"] if markaz else None,
                     "model": model["name"], "hash": h})
        conn.commit()
        bajarildi += len(bolak)
        tezlik = bajarildi / max(time.time() - t0, 0.001)
        print(f"      {bajarildi:,}/{len(ish):,} ({tezlik:.1f} kod/s)")

    print(f"\nTayyor. {bajarildi:,} kod vektorlandi "
          f"({(time.time() - t0) / 60:.1f} daqiqa).")
    if markaz is None:
        print("  [!] Markaz yo'q edi — `embedding_c` bo'sh qoldi. "
              "`SELECT recompute_centroid();` dan keyin qayta yurgizing.")


def ommaviy_nusxa(conn, args) -> None:
    """Butun navbat bo'ylab XESHDAN nusxalash. Model chaqirilmaydi.

    Bu ish `vectorize()` ichida ham bor, lekin PARTIYA ichida —
    ya'ni arzon nusxa qimmat model navbatiga bog'lanib turadi.
    Bu yerda u BIR YO'LA, bitta SQL bilan bajariladi.
    """
    import time

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(ACTIVE_MODEL_SQL)
        model = cur.fetchone()
    if not model:
        sys.exit("XATO: `embed_model` da faol model yo'q.")
    oldin = _bir_son(conn, "SELECT count(*) FROM doc_chunk "
                           "WHERE embedding IS NULL")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(OMMAVIY_NUSXA_SQL,
                    {"model": model["name"], "dims": model["dims"]})
        n = cur.rowcount
    conn.commit()
    keyin = _bir_son(conn, "SELECT count(*) FROM doc_chunk "
                           "WHERE embedding IS NULL")
    print(f"Xeshdan nusxalandi: {n:,} ta bo'lak, {time.time() - t0:.1f} s "
          f"(model CHAQIRILMADI)")
    print(f"  navbat: {oldin:,} -> {keyin:,}")


def _bir_son(conn, sql: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql)
        return int(cur.fetchone()[0])


def qamrov_korsat(conn) -> None:
    """Vektorlash qamrovi — hech narsa yozmaydi.

    HAR BO'LAK AYNAN BITTA HOLATDA va yig'indi jamiga TENG.
    `hisobga_olinmagan` noldan farqli bo'lsa jim bo'shliq qaytgan.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM v_embedding_coverage")
        v = dict(cur.fetchone())
        cur.execute("SELECT * FROM v_embedding_pending_reason")
        sabablar = [dict(r) for r in cur.fetchall()]

    print(f"Model: {v['faol_model']} ({v['faol_olcham']} o'lchov)")
    print(f"\njami bo'lak            {v['jami']:>9,}")
    print(f"  vektorlangan           {v['vektorlangan']:>9,}")
    print(f"  navbatda               {v['navbatda']:>9,}")
    print(f"  eskirgan               {v['eskirgan']:>9,}")
    print(f"  yiqildi                {v['yiqildi']:>9,}")
    print(f"  butunlay yiqildi       {v['butunlay_yiqildi']:>9,}")
    print(f"  yaroqsiz               {v['yaroqsiz']:>9,}")
    print(f"  ataylab o'tkazildi     {v['otkazildi']:>9,}")
    print(f"  {'-' * 34}")
    print(f"  HISOBGA OLINMAGAN      {v['hisobga_olinmagan']:>9,}  "
          f"<- 0 bo'lishi SHART")
    print(f"  {'-' * 34}")
    print(f"  yaroqli (maxraj)       {v['yaroqli']:>9,}")
    print(f"  QAMROV                 {v['qamrov_foiz']:>8}%")
    print(f"\nmodel mos emas         {v['model_mos_emas']:>9,}")
    print(f"  matn o'zgargan         {v['matn_ozgargan']:>9,}")
    print(f"  manba: model / xesh    {v['modeldan']:>9,} / {v['xeshdan']:,}")

    # OPERATSION QAMROV — FAQAT OCHIQ TENDERLAR (Q-2).
    #
    # Umumiy foiz TARIXNI ham sanaydi: yopilgan tenderning bo'lagi
    # vektorlanmagani RAG uchun ahamiyatsiz — unga taklif berilmaydi.
    # Q-1 dagi bilan AYNI saboq: bitta foiz ikki savolga javob
    # bera olmaydi.
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT count(*)                                        AS jami,
                   count(*) FILTER (WHERE c.embedding IS NOT NULL) AS bor
              FROM doc_chunk c JOIN tender t ON t.id = c.tender_id
             WHERE t.status = 'open'""")
        o = cur.fetchone()
    if o and o["jami"]:
        print("\nOCHIQ tenderlar bo'yicha (OPERATSION):")
        print(f"  bo'lak                 {o['jami']:>9,}")
        print(f"  vektorlangan           {o['bor']:>9,}")
        print(f"  QAMROV                 "
              f"{100.0 * o['bor'] / o['jami']:>8.2f}%")

    if sabablar:
        print("\nNEGA VEKTORLANMAGAN:")
        for r in sabablar:
            print(f"    {r['soni']:>8,}  {r['holat']:<18} {r['sabab']}")

    # NUSXA IMKONIYATI ALOHIDA SO'ROV — u sekin (157k qator ustida
    # korrelyatsiyalangan EXISTS), shuning uchun har chaqiruvda emas.
    print("\nNusxa imkoniyati hisoblanmoqda (sekin)...")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM v_embedding_dedup")
        d = dict(cur.fetchone())
    print(f"    navbat                 {d['navbat']:>9,}")
    print(f"    takrorsiz matn         {d['takrorsiz_navbat']:>9,}")
    print(f"    XESHDAN NUSXALANADI    {d['xeshdan_nusxalanadi']:>9,}  "
          f"({100 * d['xeshdan_nusxalanadi'] / max(d['navbat'], 1):.0f}% "
          f"model chaqiruvisiz)")


def qayta_belgila(conn, args) -> None:
    """Eskirgan vektorlarni 'eskirgan' deb belgilaydi.

    VEKTORNI O'CHIRMAYDI. Eski vektor joyida qoladi va qidiruv
    ishlashda davom etadi — qayta hisoblash tugagunча "hech narsa
    topilmaydi" holati bo'lmasin.
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(ACTIVE_MODEL_SQL)
        model = cur.fetchone()
    if not model:
        sys.exit("XATO: `embed_model` da faol model yo'q.")

    jami = 0
    if args.model_ozgardi:
        with conn.cursor() as cur:
            cur.execute(MODEL_OZGARDI_SQL, {"model": model["name"]})
            n = cur.rowcount
        conn.commit()
        jami += n
        print(f"Model '{model['name']}' dan boshqa bilan hisoblangan "
              f"{n:,} ta vektor 'eskirgan' deb belgilandi.")
    if args.matn_ozgardi:
        with conn.cursor() as cur:
            cur.execute(MATN_OZGARDI_SQL)
            n = cur.rowcount
        conn.commit()
        jami += n
        print(f"Matni o'zgargan {n:,} ta bo'lak 'eskirgan' deb belgilandi.")

    if jami:
        print(f"\nJami {jami:,} ta bo'lak navbatga qaytdi. Qayta hisoblash:")
        print("  python etl_embed.py --vectors")
        print("\nESLATMA: eski vektorlar O'CHIRILMADI — qidiruv "
              "hisoblash tugagunga qadar ham ishlaydi.")
    else:
        print("Eskirgan vektor topilmadi — hammasi faol model bilan.")


def main() -> None:
    if load_dotenv:
        load_dotenv()

    ap = argparse.ArgumentParser(description="Hujjat matnini bo'laklarga bo'lish (J2)")
    ap.add_argument("--chunks", action="store_true",
                    help="Bo'lakka bo'lish (pgvector KERAK EMAS)")
    ap.add_argument("--vectors", action="store_true",
                    help="Vektorlash (pgvector va embedding modeli kerak)")
    ap.add_argument("--tenders", action="store_true",
                    help="TENDER darajasidagi vektorlar "
                         "(nom + pozitsiyalar) — search_tenders uchun")
    ap.add_argument("--codes", action="store_true",
                    help="TASNIFLAGICH lug'ati vektorlari (dim_good_code) — "
                         "katalog mahsulotiga kod taklif qilish uchun")
    ap.add_argument("--count-only", action="store_true",
                    help="Faqat SANAYDI — bazaga yozmaydi")
    ap.add_argument("--all", action="store_true",
                    help="Allaqachon bo'lingan hujjatlarni ham qayta bo'ladi")
    ap.add_argument("--limit", type=int, help="Nechta hujjat (sinov uchun)")
    ap.add_argument("--xeshdan", action="store_true",
                    help="Butun navbat bo'ylab XESHDAN nusxalash "
                         "(model chaqirilmaydi, sekundlar)")
    ap.add_argument("--qamrov", action="store_true",
                    help="Vektorlash QAMROVINI ko'rsatadi va chiqadi "
                         "(bazaga yozmaydi)")
    ap.add_argument("--model-ozgardi", action="store_true",
                    help="Faol modeldan BOSHQA model bilan hisoblangan "
                         "vektorlarni 'eskirgan' deb belgilaydi. "
                         "AVTOMATIK EMAS — bu boshqariladigan qaror: "
                         "95 874 vektorni qayta hisoblash soatlar oladi")
    ap.add_argument("--matn-ozgardi", action="store_true",
                    help="Matni o'zgargan bo'laklarni 'eskirgan' deb "
                         "belgilaydi (`embed_content_hash` <> `content_hash`)")
    ap.add_argument("--dsn", default=os.environ.get("XT_DB_DSN"))
    args = ap.parse_args()

    if not (args.chunks or args.vectors or args.tenders or args.codes
            or args.count_only or args.qamrov or args.model_ozgardi
            or args.matn_ozgardi or args.xeshdan):
        ap.error("--chunks, --vectors, --tenders, --codes, --xeshdan, "
                 "--qamrov yoki --count-only ni tanlang.")
    if psycopg2 is None:
        sys.exit("XATO: pip install psycopg2-binary")
    if not args.dsn:
        sys.exit("XATO: XT_DB_DSN o'rnatilmagan.")

    conn = psycopg2.connect(args.dsn)
    try:
        # --- QAMROV: hech narsa yozmaydi, faqat ko'rsatadi ---
        if args.qamrov:
            qamrov_korsat(conn)
            return

        # ARZON ISH BIRINCHI: xeshdan nusxalash modelsiz va tez.
        if args.xeshdan:
            ommaviy_nusxa(conn, args)
            return

        # --- BOSHQARILADIGAN QAYTA VEKTORLASH ---
        #
        # ATAYLAB ALOHIDA BUYRUQ. Model o'zgarganda ETL O'ZI qayta
        # hisoblashni boshlab yuborsa, soatlik yurish to'satdan
        # soatlarga cho'zilardi va buni hech kim so'ramagan bo'lardi.
        if args.model_ozgardi or args.matn_ozgardi:
            qayta_belgila(conn, args)
            return

        # TENDER darajasi `doc_chunk` ga bog'liq emas — hujjat matni
        # umuman bo'lmagan tenderlar ham nomi/pozitsiyasi bo'yicha
        # qidirilishi kerak. Shuning uchun `doc_chunk` tekshiruvidan
        # OLDIN va alohida.
        if args.tenders:
            vectorize_tenders(conn, args)
            return

        # LUG'AT ham `doc_chunk` ga bog'liq emas — hujjat matni umuman
        # bo'lmasa ham kod taklifi ishlashi kerak.
        if args.codes:
            vectorize_codes(conn, args)
            return

        if not _bir(conn, CHUNK_TABLE_SQL):
            sys.exit("XATO: `doc_chunk` jadvali yo'q. Avval qo'llang:\n"
                     "  psql -d xtxarid -f schema_patch_ai_chat.sql\n"
                     "(u `pgvector` kengaytmasini talab qiladi — reja J0.1)")

        rows = fetch_targets(conn, args)
        jami_belgi = sum(r["char_count"] or len(r["text"] or "") for r in rows)

        if args.count_only:
            taxminiy = sum(len(chunk_text(r["text"] or "")) for r in rows)
            print(f"Qamrov: {'hammasi' if args.all else 'faqat yangi'}")
            print(f"  hujjat        : {len(rows)}")
            print(f"  belgi         : {jami_belgi:,}")
            print(f"  taxminiy bo'lak: {taxminiy}")
            print(f"  vektor hajmi  : ~{taxminiy * 1024 * 4 / 1048576:.1f} MB "
                  "(1024 o'lchov, float4)")
            print(f"  pgvector      : {'BOR' if _bir(conn, VECTOR_READY_SQL) else 'YO`Q'}")
            print("\n  (--count-only — bazaga yozilmadi)")
            return

        if args.vectors:
            vectorize(conn, args)
            return

        if not rows:
            print("Bo'lakka bo'linadigan hujjat yo'q "
                  "(hammasi bo'lingan bo'lishi mumkin — --all bilan qayta yurgizing).")
            return

        print(f"[1/1] {len(rows)} ta hujjat, {jami_belgi:,} belgi...")
        jami = 0
        for i, r in enumerate(rows, 1):
            chunks = chunk_text(r["text"] or "")
            n = save_chunks(conn, r["tender_id"], r["file_ref"], chunks)
            conn.commit()           # har hujjatdan keyin — uzilsa ish yo'qolmaydi
            jami += n
            if i % 25 == 0 or i == len(rows):
                print(f"      {i}/{len(rows)} — {jami} bo'lak")
        print(f"\nTayyor. {jami} ta bo'lak yozildi "
              f"(o'rtacha {jami / max(1, len(rows)):.1f} ta hujjatga).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
