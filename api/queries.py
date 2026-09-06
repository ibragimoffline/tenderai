"""
SQL matnlari va dinamik filtr quruvchisi — bir joyda saqlanadi.

Xavfsizlik: barcha foydalanuvchi qiymatlari psycopg2 named-param (%(x)s) orqali
uzatiladi — SQL-injection yo'q. Faqat ORDER BY ustuni oq ro'yxat (whitelist)
bilan tekshiriladi, chunki ustun nomini parametrlashtirib bo'lmaydi.
"""
from typing import Any, Dict, List, Tuple

from api import translit

# Ro'yxat va bitta tender uchun umumiy SELECT boshi (JOIN'lar bilan).
# name_uz hozircha bo'sh — shuning uchun name_ru ni ham qaytaramiz, frontend tanlaydi.
_TENDER_SELECT = """
SELECT
    t.id, t.source_id, t.type, t.name, t.status,
    s.name_uz  AS status_name_uz,
    s.name_ru  AS status_name_ru,
    s.is_terminal,
    t.totalcost, t.currency,
    t.area_path, t.area_leaf_id,
    a.name_uz  AS region_name_uz,
    a.name_ru  AS region_name_ru,
    t.buyer_org_id, t.company_name,
    t.lot_count, t.good_count, t.part_count,
    t.publicated_at, t.close_at, t.starting_date, t.ends_at,
    t.remain_time, t.source_platform, t.fetched_at, t.first_seen_at,
    -- Mahsulot nomlari qisqacha ro'yxati (jadvalда ko'rsatish uchun, takrorsiz, 6 tagacha)
    ARRAY(SELECT DISTINCT tg.name FROM tender_good tg
          WHERE tg.tender_id = t.id AND tg.name IS NOT NULL
          ORDER BY tg.name LIMIT 6) AS goods_preview,
    COALESCE(td.doc_count, 0) AS doc_count,
    -- LOTLAR xulosasi: ko'p lotli tenderda asosiy ma'no LOT nomlarida.
    -- Ro'yxatda darhol ko'rsatish uchun (qo'shimcha so'rovsiz) shu yerda yig'amiz.
    (SELECT json_agg(l ORDER BY l.lot_id) FROM (
        SELECT tl.lot_id, tl.title, tl.total_sum_lot, tl.item_count,
               MAX(ti.delivery_period) AS delivery_period,
               MAX(ti.guarantee)       AS guarantee
        FROM tender_lot tl
        LEFT JOIN tender_item ti
               ON ti.tender_id = tl.tender_id AND ti.lot_id = tl.lot_id
        WHERE tl.tender_id = t.id
        GROUP BY tl.lot_id, tl.title, tl.total_sum_lot, tl.item_count
    ) l) AS lots_json
FROM tender t
LEFT JOIN dim_status   s  ON s.status_code = t.status AND s.domain = 'tender'
LEFT JOIN dim_area     a  ON a.area_id = t.area_leaf_id
LEFT JOIN tender_detail td ON td.tender_id = t.id
"""

# ORDER BY uchun ruxsat etilgan ustunlar (oq ro'yxat)
_SORT_WHITELIST = {
    "close_at": "t.close_at",
    "publicated_at": "t.publicated_at",
    "totalcost": "t.totalcost",
    "id": "t.id",
}
DEFAULT_SORT = "close_at"  # deadline yaqinlashayotgani yuqorida

# ---------------------------------------------------------------------------
# AI QIDIRUV MATNI — 5a tahlilining qidiriladigan qismlari bitta matnga.
#
# NEGA KERAK: tovar nomi "Моноблок" bo'lsa, "kompyuter" so'rovi uni hech qachon
# topmaydi — harflar mos kelmaydi. AI esa `keywords_uz` ga "kompyuter",
# `keywords_ru` ga "моноблок, МФУ, ноутбук" yozadi. Shu matnni qidiruvga
# qo'shsak, ikkala tomondan ham topiladi.
#
# Butun JSONB ni matn sifatida qidirmaymiz — u holda maydon NOMLARI
# ("summary_uz") ham qidiruvga tushib, soxta natija berardi. Faqat QIYMATLAR.
# ---------------------------------------------------------------------------
_AI_TEXT = """concat_ws(' ',
    ax.result->>'summary_uz',
    ax.result->>'supplier_profile',
    (SELECT string_agg(x, ' ') FROM jsonb_array_elements_text(
        COALESCE(ax.result->'keywords_uz', '[]'::jsonb)) x),
    (SELECT string_agg(x, ' ') FROM jsonb_array_elements_text(
        COALESCE(ax.result->'keywords_ru', '[]'::jsonb)) x),
    (SELECT string_agg(x, ' ') FROM jsonb_array_elements_text(
        COALESCE(ax.result->'category_tags', '[]'::jsonb)) x))"""


# ---------------------------------------------------------------------------
# MATNLI QIDIRUV — alifbodan qat'i nazar (api/translit.py ga qarang)
#
# Manba nomlari aralash alifboda: "Спектрометр", "Listlarni bukish mashinasi",
# "Ўткир юрак-қон томир", "Deflazakort". Oddiy ILIKE bilan lotin so'rov deyarli
# hech narsa topmasdi (`nasos` -> 0, `насос` -> 15).
#
# Ishlash tartibi:
#   1. Ustunlar SQL da YIG'ILADI (translit.sql_fold): ь ъ o'chadi, э->е, ы й->и.
#   2. So'rov ham yig'iladi va alifbo variantlariga yoyiladi (translit.variants).
#   3. Variantlar `LIKE ANY(ARRAY[...])` bilan solishtiriladi.
#
# NEGA `LIKE ANY`, `OR` emas: variantlarni OR bilan qo'shsak, translate() har
# variant uchun QAYTA hisoblanadi (6 variant = 6 marta). `LIKE ANY` da esa
# ustun bir marta yig'iladi va massivga solishtiriladi — o'lchovda qidiruv
# ~3x tezlashdi.
#
# Ikkala tomon yig'ilgani uchun ILIKE emas, oddiy LIKE yetarli.
# ---------------------------------------------------------------------------


def _like_patterns(variants: List[str]) -> List[str]:
    """LIKE naqshlari — foydalanuvchi kiritgan joker belgilar ekranlanadi.

    Qiymatlar parametr orqali uzatiladi (injection yo'q), lekin `%` va `_`
    LIKE uchun maxsus belgi: "50%" so'rovi ekranlanmasa hamma narsaga mos keladi.
    """
    out = []
    for v in variants:
        v = v.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        out.append(f"%{v}%")
    return out


def build_column_search(col: str, q: str,
                        param: str = "pats") -> Tuple[str, Dict[str, Any]]:
    """Bitta ustun bo'yicha alifbodan qat'i nazar qidiruv sharti.

    `/products` takliflari uchun ishlatiladi — u yerda faqat tovar nomi
    qidiriladi (buyurtmachi/AI matni emas).
    """
    variants = translit.variants(q)
    if not variants:
        return "", {}
    cond = f"{translit.sql_fold(col)} LIKE ANY(%({param})s)"
    return cond, {param: _like_patterns(variants)}


# ---------------------------------------------------------------------------
# XIZMAT vs MAHSULOT — manbada bunday bayroq YO'Q, uni o'zimiz aniqlaymiz.
#
# Uchta signal birlashtiriladi (o'lchov asosida tanlangan, 2357 tovar qatorida):
#   1) OKED bo'limi (good_code) — rasmiy klassifikator, 99% qatorda bor.
#      NACE'da 33, 35-39, 41-53, 55-66, 68-82, 84-96 — xizmat bo'limlari.
#      EHTIYOT: good_code ba'zan UUID bo'ladi (31 qator), o'shanda birinchi
#      ikki belgi bo'lim deb o'qilib "Шайба" xizmatga aylanib qolgan edi.
#      Shuning uchun `^\d{2}\.` shakli TEKSHIRILADI.
#   2) O'lchov birligi — "усл. ед", "порция", "объект", "шартли бирлик".
#   3) Nom — "услуга/работы/хизмат/ишлари/қуриш...".
#      EHTIYOT: "ремонт"/"монтаж" faqat SO'Z BOSHIDA hisobga olinadi, aks holda
#      "Кольцо для ремонта насосов" va "Панель электромонтажная" (mahsulotlar)
#      xizmat bo'lib qolardi.
#
# Natija: 193 xizmat qatori / 62 turli nom, 2156 mahsulot qatori / 710 nom.
# Bu EVRISTIKA — manbaning o'z xatolari o'tib ketishi mumkin (masalan "Отвод"
# quvur bo'lagi manbada qurilish kodi 42.21 bilan berilgan).
# ---------------------------------------------------------------------------
_SERVICE_DIVISIONS = (
    [33] + list(range(35, 40)) + list(range(41, 54)) +
    list(range(55, 67)) + list(range(68, 83)) + list(range(84, 97))
)

SERVICE_PREDICATE = (
    "("
    "  (g.good_code ~ '^\\d{2}\\.'"
    "   AND substring(g.good_code from '^(\\d{2})')::int IN ("
    + ",".join(str(d) for d in _SERVICE_DIVISIONS) + "))"
    "  OR g.unit ~* '^\\s*(усл|порц|об[ъь]ект|шартли)'"
    "  OR g.name ~* '(услуг|работ|обслуживани|строительств|^\\s*ремонт|^\\s*монтаж"
    "|xizmat|хизмат|таъмир|ишлари|қуриш|ish lari)'"
    ")"
)


def kind_predicate(kind: str) -> str:
    """`kind` -> SQL sharti. 'service' | 'product' | boshqa (=hammasi)."""
    if kind == "service":
        return SERVICE_PREDICATE
    if kind == "product":
        return f"NOT {SERVICE_PREDICATE}"
    return ""


def build_product_filter(products: List[str],
                         param: str = "prod_pats") -> Tuple[str, Dict[str, Any]]:
    """MAHSULOT filtri — FAQAT tovar nomi bo'yicha.

    Erkin matnli `q` dan ATAYIN ajratilgan. `q` tender nomi va BUYURTMACHI
    nomini ham qamraydi, bu esa mahsulot uchun soxta natija beradi: "qurilish"
    so'rovi "Курилиш дирекцияси" MCHJ e'lon qilgan 39 ta tenderni tortadi,
    ularда qurilish tovari yo'q bo'lsa ham. Xuddi shu sabab bilan
    matching.score_tender() ham company_name ni hisobga olmaydi.

    Bir nechta mahsulot berilsa — ULARDAN BIRORTASI (OR): ta'minotchi bir
    nechta narsa sotadi, hammasi bitta tenderда bo'lishi shart emas. Xizmatlar
    ham shu ro'yxatga qo'shiladi (ular ham "men taklif qilaman" ma'nosida).
    """
    pats: List[str] = []
    for p in products or []:
        pats.extend(_like_patterns(translit.variants(p)))
    if not pats:
        return "", {}
    cond = ("EXISTS (SELECT 1 FROM tender_good g "
            f"        WHERE g.tender_id = t.id "
            f"          AND {translit.sql_fold('g.name')} LIKE ANY(%({param})s))")
    return cond, {param: pats}


def build_text_search(q: str, param: str = "q_pats") -> Tuple[str, Dict[str, Any]]:
    """Erkin matnli qidiruv sharti. Bo'sh so'rovda ('', {}) qaytadi."""
    variants = translit.variants(q)
    if not variants:
        return "", {}

    pat = f"LIKE ANY(%({param})s)"
    fold = translit.sql_fold
    company = fold("COALESCE(t.company_name, '')")
    clause = (
        f"({fold('t.name')} {pat}"
        f" OR {company} {pat}"
        f" OR EXISTS (SELECT 1 FROM tender_good g"
        f"            WHERE g.tender_id = t.id AND {fold('g.name')} {pat})"
        # AI kalit so'zlari — "kompyuter" so'rovi "Моноблок" tenderini topadi
        # (AI sinonimlarni yozib qo'ygan). Tahlil qilinmaganда shart FALSE.
        f" OR EXISTS (SELECT 1 FROM ai_analysis ax"
        f"            WHERE ax.tender_id = t.id AND ax.kind = 'summary_v1'"
        f"              AND {fold(_AI_TEXT)} {pat}))"
    )
    return clause, {param: _like_patterns(variants)}


def build_tender_filters(
    status: str = None,
    region: str = None,
    currency: str = None,
    source: str = None,
    q: str = None,
    category: str = None,
    products: List[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """WHERE bo'lagini va parametrlarni quradi (bo'sh filtrlar tashlab yuboriladi)."""
    clauses: List[str] = []
    params: Dict[str, Any] = {}

    if status:
        clauses.append("t.status = %(status)s")
        params["status"] = status
        if status == "open":
            # MUDDAT HAM TEKSHIRILADI. `status` — manba bergan oxirgi qiymat.
            # Tender yopilgach manba ro'yxatidan CHIQIB KETADI, biz uni boshqa
            # ko'rmaymiz va bizdagi 'open' abadiy qotib qoladi. Natijada
            # ro'yxatda taklif berib bo'lmaydigan tenderlar chiqardi.
            clauses.append("(t.close_at IS NULL OR t.close_at > now())")
    if region:
        # Ierarxik PREFIX moslashuvi: dim_area.area_id to'liq nuqtali yo'l
        # ('33.2137' = viloyat, '33.2137.2138.2140' = leaf). Viloyat tanlansa,
        # ostidagi barcha tumanlar/leaflar ham chiqadi.
        #   region = '33.2137'  ->  '33.2137' va '33.2137.%' mos keladi
        # (%% — psycopg2 uchun literal foiz belgisi)
        clauses.append("(t.area_path = %(region)s OR t.area_path LIKE %(region)s || '.%%')")
        params["region"] = region
    if currency:
        clauses.append("t.currency = %(currency)s")
        params["currency"] = currency
    if source:
        clauses.append("t.source_platform = %(source)s")
        params["source"] = source
    if category:
        # Parent tanlansa ichkilar ham kiradi: 'qurilish' -> 'qurilish' va
        # 'qurilish/%'. Ichki tanlansa aynan o'zi.
        clauses.append(
            "EXISTS (SELECT 1 FROM tender_category tc WHERE tc.tender_id = t.id "
            "        AND (tc.code = %(category)s OR tc.code LIKE %(category)s || '/%%'))")
        params["category"] = category
    if products:
        # Mahsulot filtri `q` bilan VA (AND) bog'lanadi: "насос sotaman VA
        # Toshkentda" — ikkalasi bir vaqtda ishlashi kerak.
        clause, p_params = build_product_filter(products)
        if clause:
            clauses.append(clause)
            params.update(p_params)
    if q:
        clause, q_params = build_text_search(q)
        if clause:
            clauses.append(clause)
            params.update(q_params)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def build_order_by(sort: str) -> str:
    """`sort` yoki `-sort` (minus = kamayish) ni xavfsiz ORDER BY ga aylantiradi."""
    desc = sort.startswith("-")
    key = sort[1:] if desc else sort
    col = _SORT_WHITELIST.get(key, _SORT_WHITELIST[DEFAULT_SORT])
    direction = "DESC" if desc else "ASC"

    # SUMMA SARALASHIDA VALYUTA BIRINCHI KALIT.
    #
    # O'LCHANGAN NUQSON (2026-09-02): saralash xom ustun bo'yicha
    # edi va 1 000 USD ni 2 000 UZS dan PAST qo'yardi. Korpusda
    # to'rt valyuta bor (UZS 727, USD 67, EUR 4, CNY 1), ya'ni
    # taqqoslash MA'NOSIZ chiqardi.
    #
    # KURS O'YLAB TOPILMADI. Loyihada kurs ma'lumoti YO'Q va bu
    # ataylab -- `api/pricing.py` allaqachon shu qoidani yozgan:
    # "Tizimda kurs konvertatsiyasi yo'q". Yolg'on kurs bilan
    # "to'g'ri" tartib yasash eng yomon yechim bo'lardi: natija
    # ishonchli KO'RINARDI va tekshirib bo'lmasdi.
    #
    # Shuning uchun valyutalar ARALASHTIRILMAYDI: har valyuta o'z
    # ichida to'g'ri tartiblanadi. Foydalanuvchi bitta valyuta
    # ichida taqqoslaydi -- bu YAGONA ma'noli taqqoslash.
    #
    # Boshqa saralashlar (muddat, sana) valyutaga bog'liq EMAS va
    # ular o'zgarmaydi.
    if key == "totalcost":
        return (f"ORDER BY t.currency ASC NULLS LAST, "
                f"{col} {direction} NULLS LAST, t.id DESC")

    # Deadline saralashda NULL'lar oxirida bo'lsin (to'ldirilmagan sanalar pastda)
    return f"ORDER BY {col} {direction} NULLS LAST, t.id DESC"


def tenders_sql(where: str, order_by: str) -> str:
    return f"{_TENDER_SELECT}\n{where}\n{order_by}\nLIMIT %(limit)s OFFSET %(offset)s"


def tenders_count_sql(where: str) -> str:
    return f"SELECT count(*) AS n FROM tender t\n{where}"


def tender_by_id_sql() -> str:
    return f"{_TENDER_SELECT}\nWHERE t.id = %(id)s"


TENDER_LOTS_SQL = """
SELECT lot_id, title, item_count, total_sum_lot
FROM tender_lot
WHERE tender_id = %(id)s
ORDER BY lot_id
"""

# Pozitsiya tafsiloti — yetkazib berish sharti, kafolat, texnik xarakteristika
TENDER_ITEMS_SQL = """
SELECT lot_id, item_id, product_code, name, unit, amount_text,
       price_text, totalcost_text, delivery_period, guarantee, prod_year,
       country_of_origin, delivery_address, spec, properties
FROM tender_item
WHERE tender_id = %(id)s
ORDER BY lot_id, name
"""

# --- Tender tafsiloti (get_proc dan ajratilgan maydonlar) ---
TENDER_DETAIL_SQL = """
SELECT anno, method_marks, company_details, director,
       close_time, proc_lang, offer_period, doc_count
FROM tender_detail
WHERE tender_id = %(id)s
"""

# --- Tenderga biriktirilgan hujjatlar (texnik topshiriq, xarid hujjatlari...) ---
TENDER_DOCUMENTS_SQL = """
SELECT file_ref, file_id, file_path, name, size_bytes, content_type,
       file_type, field_key, source_platform
FROM tender_document
WHERE tender_id = %(id)s
ORDER BY field_key, name
"""

# AI tahlili (5a) — o'zbekcha xulosa + kanonik kategoriya teglari
AI_ANALYSIS_SQL = """
SELECT result, model, created_at
FROM ai_analysis
WHERE tender_id = %(id)s AND kind = %(kind)s
"""

# Bitta hujjat (yuklab olish proksisi uchun)
DOCUMENT_BY_REF_SQL = """
SELECT file_id, file_path, name, content_type, file_type, source_platform
FROM tender_document
WHERE tender_id = %(id)s AND file_ref = %(ref)s
"""

TENDER_GOODS_SQL = """
SELECT g.lot_id, g.good_code, g.name, g.unit, g.amount, g.price,
       g.totalcost_item, g.category_uid,
       c.code AS category_code, c.title_ru AS category_title_ru
FROM tender_good g
LEFT JOIN dim_category c ON c.category_uid = g.category_uid
WHERE g.tender_id = %(id)s
ORDER BY g.lot_id, g.good_code
"""

# --- /stats ---
# MUDDAT TEKSHIRUVI: `status` — manba bergan oxirgi qiymat. Tender yopilgach
# manba ro'yxatidan chiqib ketadi, biz uni boshqa ko'rmaymiz va bizdagi 'open'
# abadiy qotib qoladi. Shuning uchun 'open' so'ralganda close_at ham qaraladi.
# Boshqa statuslarda shart o'z-o'zidan rost bo'ladi.
STATS_OPEN_COUNT_SQL = """
SELECT count(*) AS n FROM tender
WHERE status = %(status)s
  AND (%(status)s <> 'open' OR close_at IS NULL OR close_at > now())
  AND (%(region)s::text IS NULL
       OR area_path = %(region)s OR area_path LIKE %(region)s || '.%%')
"""

STATS_BY_CURRENCY_SQL = """
SELECT currency, count(*) AS tender_count, COALESCE(SUM(totalcost), 0) AS total_value
FROM tender
WHERE status = %(status)s
  AND (%(status)s <> 'open' OR close_at IS NULL OR close_at > now())
  AND (%(region)s::text IS NULL
       OR area_path = %(region)s OR area_path LIKE %(region)s || '.%%')
GROUP BY currency
ORDER BY currency
"""

# Respublika kesimi FAQAT level=1 tugunlar (viloyat / Toshkent shahri /
# Qoraqalpog'iston). Tenderning `area_leaf_id` si ko'pincha level=3 tuman,
# shu sabab bevosita leaf bo'yicha GROUP BY qilish "viloyatlar" o'rniga
# tumanlarni chiqarib yuborardi. Prefix-join ierarxiyaning o'ziga tayanadi.
STATS_BY_PROVINCE_SQL = """
WITH grouped AS (
    SELECT province.area_id,
           COALESCE(province.name_uz, province.name_ru) AS name,
           t.currency,
           count(*) AS tender_count,
           COALESCE(SUM(t.totalcost), 0) AS total_value
    FROM tender t
    LEFT JOIN dim_area province
      ON province.level = 1
     AND (t.area_path = province.area_id
          OR t.area_path LIKE province.area_id || '.%%')
    WHERE t.status = %(status)s
      AND (%(status)s <> 'open' OR t.close_at IS NULL OR t.close_at > now())
    GROUP BY province.area_id, COALESCE(province.name_uz, province.name_ru),
             t.currency
)
SELECT area_id, name, SUM(tender_count)::bigint AS tender_count,
       jsonb_agg(
           jsonb_build_object('currency', currency, 'total_value', total_value)
           ORDER BY currency NULLS LAST
       ) AS totals_by_currency
FROM grouped
GROUP BY area_id, name
ORDER BY tender_count DESC
"""

# Viloyat tanlanganda level=3 — tuman/shahar kesimi. UzEx faqat viloyatni
# beradi; bunday tenderlar (va tuman kodi yo'q boshqa yozuvlar) yo'qolmaydi,
# NULL guruhda "tuman/shahar ko'rsatilmagan" sifatida qaytadi.
STATS_BY_LOCALITY_SQL = """
WITH grouped AS (
    SELECT CASE WHEN locality.level = 3
                THEN locality.area_id ELSE NULL END AS area_id,
           CASE WHEN locality.level = 3
                THEN COALESCE(locality.name_uz, locality.name_ru)
                ELSE NULL END AS name,
           t.currency,
           count(*) AS tender_count,
           COALESCE(SUM(t.totalcost), 0) AS total_value
    FROM tender t
    LEFT JOIN dim_area locality ON locality.area_id = t.area_leaf_id
    WHERE t.status = %(status)s
      AND (%(status)s <> 'open' OR t.close_at IS NULL OR t.close_at > now())
      AND (t.area_path = %(region)s OR t.area_path LIKE %(region)s || '.%%')
    GROUP BY CASE WHEN locality.level = 3 THEN locality.area_id ELSE NULL END,
             CASE WHEN locality.level = 3
                  THEN COALESCE(locality.name_uz, locality.name_ru)
                  ELSE NULL END,
             t.currency
)
SELECT area_id, name, SUM(tender_count)::bigint AS tender_count,
       jsonb_agg(
           jsonb_build_object('currency', currency, 'total_value', total_value)
           ORDER BY currency NULLS LAST
       ) AS totals_by_currency
FROM grouped
GROUP BY area_id, name
ORDER BY tender_count DESC
"""

STATS_REGION_SQL = """
SELECT area_id, COALESCE(name_uz, name_ru) AS name, level
FROM dim_area
WHERE area_id = %(region)s
"""

# --- /regions ---
REGIONS_SQL = """
SELECT area_id, COALESCE(name_uz, name_ru) AS name,
       name_ru, name_uz, level, parent_id, has_children
FROM dim_area
{where}
ORDER BY level, name
"""

# --- /match nomzodlari ---
# Tenderlarni skorlash uchun: har tenderning barcha tovar nomlarini bitta
# 'goods_blob' matnга jamlab olamiz (kalit so'z qidirish uchun). GROUP BY —
# t.id PK + agregatsiyasiz dim ustunlar.
def match_candidates_sql(where: str, cap: int) -> str:
    return f"""
SELECT
    t.id, t.source_id, t.type, t.name, t.status,
    s.name_uz AS status_name_uz, s.name_ru AS status_name_ru, s.is_terminal,
    t.totalcost, t.currency, t.area_path, t.area_leaf_id,
    a.name_uz AS region_name_uz, a.name_ru AS region_name_ru,
    COALESCE(a.name_uz, a.name_ru) AS region_name,
    t.buyer_org_id, t.company_name,
    t.lot_count, t.good_count, t.publicated_at, t.close_at,
    t.remain_time, t.source_platform,
    -- Kalit so'z qidiriladigan matn: tovar nomlari + AI sinonimlari.
    -- AI qismi tufayli profilda "kompyuter" bo'lsa, "Моноблок" tenderi ham
    -- moslik ball oladi. Tahlil qilinmagan tenderда bu qism bo'sh qoladi.
    COALESCE(string_agg(DISTINCT g.name, ' '), '') || ' ' ||
    COALESCE((SELECT {_AI_TEXT} FROM ai_analysis ax
              WHERE ax.tender_id = t.id AND ax.kind = 'summary_v1'), '')
        AS goods_blob,
    -- Katalog moslik uchun: shu tenderning kategoriya kodlari
    -- (FILTR uchun; moslik dalili EMAS — api/matching.py ga qarang)
    ARRAY(SELECT code FROM tender_category tc WHERE tc.tender_id = t.id) AS category_codes,
    -- BIRLAMCHI moslik kaliti: rasmiy tasniflagich kodlari. Tilga
    -- bog'liq emas va qamrovi to'liq (o'lchangan: 1880 ochiq
    -- pozitsiyaning 1880 tasida kod bor).
    -- `matching.product_matches()` shuni birinchi ko'radi.
    -- DIQQAT: bu matn psycopg2 ga boradi — izohda ham FOIZ BELGISI
    -- yozilmasin, u platsderjatel deb o'qiladi va so'rov yiqiladi.
    ARRAY(SELECT DISTINCT tg2.good_code FROM tender_good tg2
          WHERE tg2.tender_id = t.id AND tg2.good_code IS NOT NULL) AS good_codes,
    ARRAY(SELECT DISTINCT tg.name FROM tender_good tg
          WHERE tg.tender_id = t.id AND tg.name IS NOT NULL
          ORDER BY tg.name LIMIT 6) AS goods_preview,
    -- TOVAR LOTLARI NOMI — matn mosligining YAGONA dalili.
    --
    -- `goods_blob` dan farqi: XIZMAT lotlari va lug'atda kodi
    -- topilmagan lotlar CHIQARIB TASHLANADI. Sabab o'lchangan
    -- (`schema_patch_xizmat.sql`): `Кабель` bo'yicha 13 moslikdan
    -- 4 tasi soxta edi va TO'RTALASI HAM xizmat tavsifidan yoki
    -- tender sarlavhasidan kelgandi (precision 0.692).
    --
    -- DIQQAT: bu izohda FOIZ BELGISI yo'q va bo'lmasligi ham kerak —
    -- psycopg2 uni platsderjatel deb o'qiydi va so'rov yiqiladi
    -- (yuqoridagi `good_codes` izohida ham shu ogohlantirish bor;
    -- men aynan shu tuzoqqa tushdim).
    --
    -- Tender SARLAVHASI bu yerga QO'SHILMAYDI — u yolg'iz o'zi
    -- moslik dalili emas: "kabel liniyasini ko'chirish loyihasi"
    -- kabel SOTIB OLMAYDI.
    COALESCE((SELECT string_agg(DISTINCT tg3.name, ' ')
                FROM tender_good tg3
               WHERE tg3.tender_id = t.id
                 AND tg3.name IS NOT NULL
                 AND lot_tovarmi(tg3.good_code, tg3.name)), '') AS tovar_blob
FROM tender t
LEFT JOIN dim_status s ON s.status_code = t.status AND s.domain = 'tender'
LEFT JOIN dim_area   a ON a.area_id = t.area_leaf_id
LEFT JOIN tender_good g ON g.tender_id = t.id
{where}
GROUP BY t.id, s.name_uz, s.name_ru, s.is_terminal, a.name_uz, a.name_ru
-- TARTIB MUHIM: ballash PYTHONда, LIMIT esa SHU YERDA bo'ladi. Ya'ni cap
-- ishga tushsa, ro'yxat OXIRIDAGI tenderlar umuman ballanmaydi.
-- Shuning uchun eng HARAKATGA YAROQLILARI birinchi turishi shart:
--   1) ochiq tenderlar, 2) muddati o'tmaganlar, 3) deadline yaqinlari.
-- (Ilgari `close_at ASC` edi — bu muddati o'tganlarni oldinga chiqarib,
--  aynan ochiq tenderlarni cap tashqarisida qoldirardi.)
ORDER BY
    (t.status = 'open') DESC,
    (t.close_at >= now()) DESC NULLS LAST,
    t.close_at ASC NULLS LAST
LIMIT {int(cap)}
"""


# --- profil (CRUD, bitta faol profil) ---
# Ustunlar ikki guruh:
#   QIDIRUV sozlamalari — keywords, regions, currency, min_cost, max_cost
#   SALOHIYAT (Go/No-Go uchun) — about, certificates, clearances,
#       experience_years, max_contract_value/currency, employees, capacity_note
# Ikkinchi guruh schema_patch_gonogo.sql da qo'shilgan; hammasi ixtiyoriy.
_PROFILE_COLS = ("id, name, keywords, regions, currency, min_cost, max_cost, "
                 "about, certificates, clearances, experience_years, "
                 "max_contract_value, max_contract_currency, employees, "
                 "capacity_note, lead_time_days, min_margin_percent, "
                 "constraints_note, contact_name, email, phone, position, "
                 "updated_at")

# KOMPANIYA PROFILI — ijarachi siri (J1.6): salohiyat, minimal marja,
# aloqa ma'lumotlari. Har kompaniyada BITTA faol profil.
PROFILE_GET_SQL = f"""
SELECT {_PROFILE_COLS}
FROM company_profile
WHERE company_id = %(company_id)s
ORDER BY updated_at DESC
LIMIT 1
"""

# Bitta faol profil: bor bo'lsa yangilaymiz, yo'q bo'lsa qo'shamiz
PROFILE_UPSERT_SQL = f"""
INSERT INTO company_profile (
    id, company_id, name, keywords, regions, currency, min_cost, max_cost,
    about, certificates, clearances, experience_years,
    max_contract_value, max_contract_currency, employees, capacity_note,
    lead_time_days, min_margin_percent, constraints_note,
    contact_name, email, phone, position, updated_at)
VALUES (
    -- SHU KOMPANIYANING profili bor bo'lsa uning `id` si, yo'q bo'lsa
    -- ketma-ketlikdan YANGI id. Ilgari bu yerda `COALESCE(..., 1)` turardi
    -- va ikkinchi kompaniya profil saqlaganda birinchisining id=1 yozuvi
    -- ustidan yozilardi — J1 dan keyin bu jimgina ma'lumot yo'qotish edi.
    COALESCE((SELECT id FROM company_profile
               WHERE company_id = %(company_id)s
               ORDER BY updated_at DESC LIMIT 1),
             nextval(pg_get_serial_sequence('company_profile', 'id'))),
    %(company_id)s,
    %(name)s, %(keywords)s, %(regions)s, %(currency)s, %(min_cost)s, %(max_cost)s,
    %(about)s, %(certificates)s, %(clearances)s, %(experience_years)s,
    %(max_contract_value)s, %(max_contract_currency)s, %(employees)s,
    %(capacity_note)s, %(lead_time_days)s, %(min_margin_percent)s,
    %(constraints_note)s, %(contact_name)s, %(email)s, %(phone)s,
    %(position)s, now()
)
ON CONFLICT (id) DO UPDATE SET
    name=EXCLUDED.name, keywords=EXCLUDED.keywords, regions=EXCLUDED.regions,
    currency=EXCLUDED.currency, min_cost=EXCLUDED.min_cost, max_cost=EXCLUDED.max_cost,
    about=EXCLUDED.about, certificates=EXCLUDED.certificates,
    clearances=EXCLUDED.clearances, experience_years=EXCLUDED.experience_years,
    max_contract_value=EXCLUDED.max_contract_value,
    max_contract_currency=EXCLUDED.max_contract_currency,
    employees=EXCLUDED.employees, capacity_note=EXCLUDED.capacity_note,
    lead_time_days=EXCLUDED.lead_time_days,
    min_margin_percent=EXCLUDED.min_margin_percent,
    constraints_note=EXCLUDED.constraints_note,
    contact_name=EXCLUDED.contact_name, email=EXCLUDED.email,
    phone=EXCLUDED.phone, position=EXCLUDED.position,
    updated_at=now()
RETURNING {_PROFILE_COLS}
"""


# ---------------------------------------------------------------------------
# SAQLANGAN QIDIRUVLAR (A bosqich)
# ---------------------------------------------------------------------------
_SS_COLS = ("id, name, keywords, categories, regions, currency, "
            "min_cost, max_cost, notify, last_seen_at, created_at, updated_at")

# SAQLANGAN QIDIRUVLAR — ijarachi siri (J1.6).
SEARCHES_LIST_SQL = (f"SELECT {_SS_COLS} FROM saved_search "
                     "WHERE company_id = %(company_id)s ORDER BY created_at")

SEARCH_GET_SQL = (f"SELECT {_SS_COLS} FROM saved_search "
                  "WHERE id = %(id)s AND company_id = %(company_id)s")

# BILDIRISHNOMA uchun saqlangan qidiruvlar (T-1).
#
# `notify` bayrog'i 2026-08 dan beri jadvalda ham, API da ham bor edi,
# lekin bildirishnoma tsikli uni O'QIMASDI — u faqat
# `company_profile` dan skorlardi. Ya'ni bayroqni yoqish HECH NARSA
# qilmasdi va bu "imkoniyat bor" degan yolg'on taassurot berardi.
SEARCHES_NOTIFY_SQL = (f"SELECT {_SS_COLS} FROM saved_search "
                       "WHERE company_id = %(company_id)s AND notify "
                       "ORDER BY id")

SEARCH_INSERT_SQL = f"""
INSERT INTO saved_search (company_id, name, keywords, categories, regions,
                          currency, min_cost, max_cost, notify)
VALUES (%(company_id)s, %(name)s, %(keywords)s, %(categories)s, %(regions)s,
        %(currency)s, %(min_cost)s, %(max_cost)s, %(notify)s)
RETURNING {_SS_COLS}
"""

SEARCH_UPDATE_SQL = f"""
UPDATE saved_search SET
    name=%(name)s, keywords=%(keywords)s, categories=%(categories)s,
    regions=%(regions)s, currency=%(currency)s,
    min_cost=%(min_cost)s, max_cost=%(max_cost)s, notify=%(notify)s,
    updated_at=now()
WHERE id=%(id)s AND company_id=%(company_id)s
RETURNING {_SS_COLS}
"""

SEARCH_DELETE_SQL = ("DELETE FROM saved_search "
                     "WHERE id=%(id)s AND company_id=%(company_id)s RETURNING id")

# `last_seen_at` — KEYINGA QOLDIRILGAN. Uni to'ldiradigan SQL bu
# yerda BOR EDI, lekin CHAQIRUVCHISI YO'Q edi: "oxirgi ko'rgandan
# keyingi yangilar" belgisi na endpointda, na interfeysda. O'lik
# SQL "imkoniyat bor" degan yolg'on taassurot berardi, shuning
# uchun olib tashlandi. Ustun jadvalda qoldi (ma'lumot yo'qotmaslik
# uchun) va holati `docs/saved_search.md` da yozilgan.


# --- /categories (B bosqich) — daraxt + OCHIQ tenderlar soni ---
# Parent soni ichkilarни ham qamrab oladi (roll-up). Bir tender bir necha
# kategoriyada bo'lishi mumkin, shuning uchun sonlar yig'indisi jamiga teng emas.
CATEGORIES_SQL = """
SELECT c.code, c.parent, c.name_uz, c.sort_order,
       (SELECT count(DISTINCT tc.tender_id)
          FROM tender_category tc
          JOIN tender t ON t.id = tc.tender_id
         WHERE t.status = 'open'
           AND (t.close_at IS NULL OR t.close_at > now())
           AND (tc.code = c.code OR tc.code LIKE c.code || '/%%')) AS cnt
FROM dim_category_uz c
ORDER BY c.sort_order
"""

# --- Hujjat matni (P0-2) ---
# LEFT JOIN — matn ajratilmagan hujjat ham ro'yxatda qoladi ('pending'),
# aks holda "hali ishlanmagan" va "o'qib bo'lmadi" farqlanmay qolardi.
TENDER_DOCUMENT_TEXT_SQL = """
SELECT d.file_ref, d.name, d.file_type, d.field_key, d.size_bytes,
       t.status, t.char_count, t.page_count, t.error, t.extractor,
       t.extracted_at,
       left(t.text, %(preview)s) AS preview
FROM tender_document d
LEFT JOIN tender_document_text t
       ON t.tender_id = d.tender_id AND t.file_ref = d.file_ref
WHERE d.tender_id = %(id)s
ORDER BY d.field_key, d.name
"""

# Bitta faylning TO'LIQ matni (?ref=... &full=true)
DOCUMENT_TEXT_FULL_SQL = """
SELECT status, char_count, page_count, error, extractor, extracted_at, text
FROM tender_document_text
WHERE tender_id = %(id)s AND file_ref = %(ref)s
"""


# --- AI moslik tahlili (kind='match_v1') ---
# Tenderning AI uchun kerakli barcha ma'lumoti bitta so'rovda (etl_ai_summary.py
# dagi FETCH_SQL bilan bir xil shakl — ai.build_input() ikkalasini ham o'qiydi).
AI_TENDER_SQL = """
SELECT
    t.id, t.type, t.name, t.company_name, t.totalcost, t.currency,
    -- Go/No-Go uchun qo'shimcha: muddat, hudud yo'li va tender shartlari.
    -- `ai.build_input()` bu maydonlarni O'QIMAYDI, shuning uchun ai_match
    -- keshi buzilmaydi — faqat ai_gonogo ulardan foydalanadi.
    t.close_at, t.area_path, t.status,
    td.anno, td.method_marks, td.offer_period,
    COALESCE(a.name_uz, a.name_ru)  AS region_name,
    COALESCE(td.doc_count, 0)       AS doc_count,
    ARRAY(SELECT DISTINCT g.name FROM tender_good g
          WHERE g.tender_id = t.id AND g.name IS NOT NULL
          ORDER BY g.name LIMIT 25) AS goods,
    (SELECT json_agg(json_build_object('lot_id', l.lot_id, 'title', l.title)
                     ORDER BY l.lot_id)
       FROM tender_lot l WHERE l.tender_id = t.id) AS lots,
    (SELECT json_agg(json_build_object(
                'name', i.name, 'unit', i.unit,
                'delivery_period', i.delivery_period, 'guarantee', i.guarantee,
                'spec', i.spec, 'properties', i.properties))
       FROM tender_item i WHERE i.tender_id = t.id) AS items
FROM tender t
LEFT JOIN dim_area     a  ON a.area_id = t.area_leaf_id
LEFT JOIN tender_detail td ON td.tender_id = t.id
WHERE t.id = %(id)s
"""

# Keshdagi tahlil. `content_hash` mos kelsa AI qayta chaqirilmaydi.
AI_CACHED_SQL = """
SELECT result, model, content_hash, input_tokens, output_tokens, created_at
FROM ai_analysis
WHERE tender_id = %(id)s AND kind = %(kind)s AND company_id = %(company_id)s
"""

AI_UPSERT_SQL = """
INSERT INTO ai_analysis (tender_id, kind, company_id, content_hash, result,
                         model, input_tokens, output_tokens)
VALUES (%(tender_id)s, %(kind)s, %(company_id)s, %(content_hash)s, %(result)s,
        %(model)s, %(input_tokens)s, %(output_tokens)s)
-- KOMPANIYA tahlili (match_v2, gonogo_v2) — katalog va profilga asoslanadi.
-- `ai_analysis_private` qisman indeksi `WHERE company_id IS NOT NULL` bilan
-- yaratilgan, ON CONFLICT ham AYNAN shu predikatni takrorlashi shart.
-- UMUMIY tahlil (summary_v1) boshqa yo'ldan yuradi: etl_ai_summary.py.
ON CONFLICT (tender_id, kind, company_id) WHERE company_id IS NOT NULL DO UPDATE SET
    content_hash  = EXCLUDED.content_hash,
    result        = EXCLUDED.result,
    model         = EXCLUDED.model,
    input_tokens  = EXCLUDED.input_tokens,
    output_tokens = EXCLUDED.output_tokens,
    created_at    = now()
RETURNING result, model, content_hash, created_at
"""


# --- /products — mahsulot/xizmat bo'yicha filtr uchun takliflar ---
# ALOHIDA LUG'AT QURMAYMIZ: ma'lumotning o'zi lug'at. tender_good.name ikkala
# manbada ham 100% to'ldirilgan va yaxshi takrorlanadi (2357 qatorda 775 turli
# nom; "сальник" 20x, "водяной насос" 12x). Shuning uchun ro'yxat shu ustundan
# chastota bo'yicha olinadi. `kind` bilan mahsulot/xizmatga bo'linadi.
def products_sql(where_extra: str = "", kind: str = "") -> str:
    """Tovar/xizmat nomlari, chastota bo'yicha.

    `where_extra` — qidiruv sharti (build_column_search dan), bo'sh bo'lishi mumkin.
    `kind` — 'product' | 'service' | '' (hammasi).
    """
    cond = f"AND {where_extra}" if where_extra else ""
    kp = kind_predicate(kind)
    if kp:
        cond += f" AND {kp}"
    return f"""
SELECT g.name AS name, count(DISTINCT g.tender_id) AS tender_count
FROM tender_good g
JOIN tender t ON t.id = g.tender_id
WHERE g.name IS NOT NULL AND g.name <> ''
  AND (%(status)s = '' OR t.status = %(status)s)
  AND (%(status)s <> 'open' OR t.close_at IS NULL OR t.close_at > now())
  {cond}
GROUP BY g.name
ORDER BY count(DISTINCT g.tender_id) DESC, g.name
LIMIT %(limit)s
"""


# ---------------------------------------------------------------------------
# MAHSULOT KATALOGI (REJA.md P0-4/5)
# ---------------------------------------------------------------------------
# Ombor ustunlari (P0-4/P0-6) — `schema_patch_stock.sql` da qo'shilgan.
# INSERT/UPDATE ga tegish shart emas: qo'lda kiritishda qoldiq to'ldirilmaydi,
# `RETURNING {_CP_COLS}` esa yangi ustunlarni avtomatik qaytaradi.
_CP_COLS = ("id, name, category_code, keywords, unit, price, currency, "
            "stock_qty, stock_unit, stock_updated_at, cost_price, "
            "notify, created_at, updated_at")

# KATALOG — KOMPANIYA SIRI (J1.6). Har so'rovda `company_id` MAJBURIY:
# tannarx, qoldiq va mahsulot ro'yxati boshqa ijarachiga ko'rinmasligi kerak.
# `id` bo'yicha murojaatda ham filtr bor — begona id ni taxmin qilib
# tahrirlash/o'chirish mumkin bo'lmasin (IDOR).
# `codes` — INSON TASDIQLAGAN tasniflagich prefikslari. Moslashtirish
# uchun BIRLAMCHI kalit. Manba `v_catalog_code_active`, ya'ni
# tasdiqlanmagan taklif bu yerga TUSHMAYDI (schema_patch_goodcode.sql).
CATALOG_LIST_SQL = (
    f"SELECT {_CP_COLS}, "
    "  COALESCE(ARRAY(SELECT v.code FROM v_catalog_code_active v "
    "                  WHERE v.product_id = catalog_product.id "
    "                    AND v.company_id = catalog_product.company_id), "
    "           '{}') AS codes "
    "FROM catalog_product "
    "WHERE company_id = %(company_id)s ORDER BY created_at")

CATALOG_GET_SQL = (
    f"SELECT {_CP_COLS}, "
    "  COALESCE(ARRAY(SELECT v.code FROM v_catalog_code_active v "
    "                  WHERE v.product_id = catalog_product.id "
    "                    AND v.company_id = catalog_product.company_id), "
    "           '{}') AS codes "
    "FROM catalog_product "
    "WHERE company_id = %(company_id)s AND id = %(product_id)s")

# ---------------------------------------------------------------------------
# KATALOG MATN MOSLIGI — SQL DA, Python siklida EMAS
#
# O'LCHANGAN SABAB: real katalog 1797 qatorli. `matching.product_matches()`
# ni Python siklida yurgizish 1797 x 782 = 1.4 mln chaqiruv demak, va har
# chaqiruv `translit.variants()` + regex bajaradi:
#
#     25 nomzod x 1797 mahsulot = 82.6 s
#     to'liq so'rov             = ~29 DAQIQA
#
# Brauzer ancha oldin uziladi. Foydalanuvchi BO'SH RO'YXAT ko'radi va uni
# "mos tender yo'q" deb o'qiydi — aslida so'rov TUGAMAGAN. Bu 2-sinf
# tuzog'i: salbiy shartdan olingan xulosa.
#
# Bu yerda naqshlar BIR MARTA quriladi va TAKRORSIZ (katalogda "Hikvision"
# 699 marta uchraydi, naqsh esa bitta kerak). Solishtirishni Postgres
# bajaradi.
#
# ATRIBUT: qaysi mahsulot mos kelgani ham SHU SO'ROVDA qaytadi — naqsh
# `VALUES` jadvaliga mahsulot id si bilan birga qo'yiladi. Python tomonda
# ikkinchi sikl kerak emas.
# ---------------------------------------------------------------------------
#: Matn atamasining eng katta uzunligi. Undan uzunlari SKU nomlari
#: ("1280ZJ-S Германичная коробка Металлическая") va ular hech qachon
#: tender pozitsiyasida uchramaydi — faqat naqsh sonini shishiradi.
MAX_TERM_LEN = 25

#: Bir so'rovda ishlatiladigan eng ko'p TURLI atama. Chegara bor, chunki
#: naqsh soni SQL vaqtini chiziqli oshiradi. Kesilgan bo'lsa chaqiruvchi
#: buni foydalanuvchiga AYTISHI shart (jimgina kesish yo'q).
MAX_TERMS = 400


def build_catalog_text_match(terms: List[str],
                             cap: int = 400) -> Tuple[str, Dict[str, Any]]:
    """TURLI atamalar ro'yxatidan SQL quradi. Naqsh bo'lmasa ("", {}).

    Natija ustunlari: `tender_id`, `pozitsiya` (mos kelgan tovar nomi).

    ATAMALAR GLOBAL TAKRORSIZ BO'LISHI SHART — bu tezlikning butun
    mohiyati. O'lchangan (1797 qatorli real katalog, 782 ochiq tender):

        (mahsulot, naqsh) juftligi -> 22 100 naqsh -> 81.2 s
        GLOBAL takrorsiz atama     ->    925 naqsh ->  0.25 s

    Ikkalasi ham AYNAN bir xil 12 ta tender topadi. Farq faqat shundaki,
    birinchi variantda "Hikvision" naqshi 699 marta takrorlanadi.
    Katalog o'sganda bu farq kattalashadi.

    QAYSI MAHSULOT mos kelgani BU YERDA aniqlanmaydi — natija kichik
    (o'nlab qator), shuning uchun atribut Python tomonda arzon.
    """
    pats: List[str] = []
    korilgan = set()
    for term in terms:
        for pat in _like_patterns(translit.variants(term or "")):
            if pat in korilgan:
                continue
            korilgan.add(pat)
            pats.append(pat)
    if not pats:
        return "", {}

    # TENDER NOMI HAM QARALADI, faqat pozitsiya emas.
    # Python yo'li `cand.name + goods_blob` ni qarardi; SQL ni faqat
    # `tender_good.name` bilan yozish MOSLIKNI TORAYTIRARDI — nomida
    # "kompyuter" bor, pozitsiyasi boshqacha yozilgan tender tushib
    # qolardi. Ikki yo'l bir xil natija berishi SHART.
    sql = f"""
SELECT tender_id, pozitsiya FROM (
    SELECT g.tender_id, g.name AS pozitsiya
    FROM tender_good g
    JOIN tender t ON t.id = g.tender_id
    WHERE t.status = 'open'
      AND (t.close_at IS NULL OR t.close_at > now())
      AND g.name IS NOT NULL
      AND {translit.sql_fold('g.name')} LIKE ANY(%(pats)s)
    UNION                       -- UNION o'zi takrorni olib tashlaydi
    SELECT t.id AS tender_id, t.name AS pozitsiya
    FROM tender t
    WHERE t.status = 'open'
      AND (t.close_at IS NULL OR t.close_at > now())
      AND t.name IS NOT NULL
      AND {translit.sql_fold('t.name')} LIKE ANY(%(pats)s)
) x
ORDER BY x.tender_id, x.pozitsiya
LIMIT {int(cap)}
"""
    return sql, {"pats": pats}


def catalog_terms(products: List[Dict[str, Any]]
                  ) -> Tuple[List[Tuple[str, str]], int]:
    """Katalogdan TURLI matn atamalarini ajratadi — YAGONA MANBA.

    Qaytaradi: ([(atama, mahsulot_nomi)], kesilgan_soni). Kesilgan > 0
    bo'lsa chaqiruvchi buni foydalanuvchiga ko'rsatishi SHART.

    KODI BOR mahsulot TASHLANADI — `matching.product_matches()` bilan
    bir xil qoida: kod aniq javob beradi, matn shovqin qo'shadi.

    MAHSULOT NOMI HAM OLINADI, lekin OXIRGI navbatda. Tartib chastota
    bo'yicha: kalit so'z ko'p mahsulotda takrorlanadi ("IP камеры" 220
    marta), nom esa bitta mahsulotda — ya'ni nom tabiiy ravishda
    ro'yxat oxirida qoladi va katta katalogda `MAX_TERMS` chegarasiga
    tushadi.

    Bu ATAYLAB shunday: kichik katalogda nom YAGONA ma'noli atama
    bo'lishi mumkin (kalit so'z kiritilmagan bo'lsa), katta katalogda
    esa nom SKU artikuli ("Tapo C110", "GNT-10703-60") va faqat shovqin
    qo'shadi. Chastota tartibi ikkala holatni ham to'g'ri hal qiladi —
    alohida shart yozish shart emas.

    Nomni butunlay tashlab yuborish XATO edi va sinov uni tutdi:
    kalit so'zsiz mahsulot ("kompyuter", keywords=[]) umuman mos
    kelmay qoldi.

    NEGA YAGONA FUNKSIYA: bu qoida avval IKKI joyda ikki xil edi —
    `/catalog/match` faqat kalit so'zni olardi, `notify` esa nomni ham
    qo'shardi va indeksi 1325 atamaga shishib ketgandi (4.6 daqiqa).
    Ikki manba bo'lsa ular albatta chetga chiqadi.
    """
    say: Dict[str, int] = {}
    egasi: Dict[str, str] = {}
    for p in products:
        if p.get("codes"):
            continue
        nom = p.get("name") or ""
        # Kalit so'zlar OLDIN — teng chastotada ular ustun bo'lsin.
        for t in list(p.get("keywords") or []) + [nom]:
            t = (t or "").strip()
            if 3 <= len(t) <= MAX_TERM_LEN:
                say[t] = say.get(t, 0) + 1
                egasi.setdefault(t, nom)
    # Ko'p uchraydigan atama = katalogning asosiy yo'nalishi, shuning
    # uchun chegaraga tushsa birinchi u qoladi. Uzunroq atama aniqroq,
    # shuning uchun teng chastotada u oldinda.
    tartib = sorted(say, key=lambda t: (-say[t], -len(t), t))
    kesilgan = max(0, len(tartib) - MAX_TERMS)
    return [(t, egasi[t]) for t in tartib[:MAX_TERMS]], kesilgan


CATALOG_INSERT_SQL = f"""
INSERT INTO catalog_product (company_id, name, category_code, keywords, unit,
                             price, currency, notify)
VALUES (%(company_id)s, %(name)s, %(category_code)s, %(keywords)s, %(unit)s,
        %(price)s, %(currency)s, %(notify)s)
RETURNING {_CP_COLS}
"""

CATALOG_UPDATE_SQL = f"""
UPDATE catalog_product SET
    name=%(name)s, category_code=%(category_code)s, keywords=%(keywords)s,
    unit=%(unit)s, price=%(price)s, currency=%(currency)s, notify=%(notify)s,
    updated_at=now()
WHERE id=%(id)s AND company_id=%(company_id)s
RETURNING {_CP_COLS}
"""

CATALOG_DELETE_SQL = ("DELETE FROM catalog_product "
                      "WHERE id=%(id)s AND company_id=%(company_id)s RETURNING id")

# `catalog_state` endi HAR KOMPANIYAGA bitta qator (singleton sindirilgan).
# Yozuv bo'lmasligi mumkin — SEEN uni o'zi yaratadi (uq_catalog_state_company).
CATALOG_STATE_GET_SQL = ("SELECT last_seen_at FROM catalog_state "
                         "WHERE company_id = %(company_id)s")
CATALOG_SEEN_SQL = """
INSERT INTO catalog_state (company_id, last_seen_at)
VALUES (%(company_id)s, now())
ON CONFLICT (company_id) DO UPDATE SET last_seen_at = now()
RETURNING last_seen_at
"""

# --- /freshness (H bosqich) — ma'lumot yangiligi + ETL sog'ligi ---
# Har platforma uchun ENG SO'NGGI yurish.
FRESHNESS_SQL = """
SELECT DISTINCT ON (source_platform)
       source_platform, status, found, new, started_at, finished_at,
       EXTRACT(EPOCH FROM (now() - finished_at))::bigint AS age_sec
FROM etl_run
ORDER BY source_platform, started_at DESC
"""

# Aniqlash-kechikishi statistikasi (e'londan biz topgunga qadar), ochiq tenderlar
# ---------------------------------------------------------------------------
# KORPUS HOLATI — semantik qidiruv qancha tenderni KO'RADI
#
# "TUGADI" HOLATI YO'Q. Korpus doim o'sib turadi: har soat yangi tender
# keladi, hujjati chiqariladi, bo'laklarga bo'linadi. Ya'ni to'g'ri
# xulosa "quvib yetdi", "tamom" emas — va ko'rsatkich shuni aytishi
# kerak, aks holda "0 qoldi" ni ko'rgan odam ish tugagan deb o'ylardi.
#
# `sutkalik_yangi` shuning uchun bor: navbat qisqarayotganini emas,
# QUVIB YETAYOTGANINI ko'rsatadi.
# ---------------------------------------------------------------------------
#: TODO(§16.67): `detection` statistikasida minimal namuna
#: sharti yo'q. Bugun n = 815, ya'ni xavf yo'q; yangi bazada
#: BITTA kuzatuvdan mediana chiqarardi. `MOSLIK_MIN` bilan bir
#: xil chora kerak.
CORPUS_STATS_SQL = """
SELECT count(*)                                        AS jami,
       count(*) FILTER (WHERE embedding IS NULL)       AS vektorsiz,
       count(*) FILTER (WHERE created_at > now() - interval '24 hours')
                                                       AS sutkalik_yangi,
       count(DISTINCT tender_id)                       AS tenderlar,
       -- SOVUQ START yorlig'i. Bo'laklash endigina yurgan bo'lsa
       -- "oxirgi 24 soat" BUTUN korpusni qamrab oladi (o'lchandi:
       -- 118 426 dan 118 426) va `sutkalik_yangi` sur'at emas, bir
       -- martalik to'ldirish bo'ladi.
       EXTRACT(EPOCH FROM (now() - min(created_at))) / 86400.0
                                                       AS yosh_kun
FROM doc_chunk
"""


DETECTION_STATS_SQL = """
SELECT
    count(*) FILTER (WHERE publicated_at IS NOT NULL) AS n,
    percentile_cont(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (first_seen_at - publicated_at))/3600) AS median_hours,
    count(*) FILTER (
        WHERE publicated_at IS NOT NULL
          AND first_seen_at - publicated_at <= interval '1 hour') AS within_1h
FROM tender
WHERE status = 'open' AND first_seen_at >= publicated_at
"""

# --- /statuses ---
STATUSES_SQL = """
SELECT status_code, COALESCE(name_uz, name_ru) AS name,
       name_ru, name_uz, is_terminal, status_id
FROM dim_status
WHERE domain = 'tender'
ORDER BY status_id NULLS LAST, status_code
"""


# ---------------------------------------------------------------------------
# NARX HISOBI (P0-7) — schema_patch_pricing.sql
# ---------------------------------------------------------------------------
_PS_COLS = ("id, markup_percent, risk_reserve_percent, risk_reserve_fixed, "
            "logistics_percent, logistics_fixed, vat_percent, currency, updated_at")

# NARX SOZLAMALARI — har KOMPANIYAGA bitta yozuv (J1.6).
# Ilgari `WHERE id = 1` edi: singleton `schema_patch_multitenant.sql` da
# sindirilgan, endi kalit — `company_id` (uq_pricing_settings_company).
# DIQQAT: yangi kompaniyada yozuv BO'LMASLIGI mumkin — chaqiruvchi `None`
# holatini qayta ishlashi kerak (`pricing.build_inputs` buni biladi:
# bo'sh sozlama -> DEFAULTS).
PRICING_SETTINGS_GET_SQL = (f"SELECT {_PS_COLS} FROM pricing_settings "
                            "WHERE company_id = %(company_id)s")

PRICING_SETTINGS_UPSERT_SQL = f"""
INSERT INTO pricing_settings (
    company_id, markup_percent, risk_reserve_percent, risk_reserve_fixed,
    logistics_percent, logistics_fixed, vat_percent, currency, updated_at)
VALUES (%(company_id)s, %(markup_percent)s, %(risk_reserve_percent)s,
        %(risk_reserve_fixed)s, %(logistics_percent)s, %(logistics_fixed)s,
        %(vat_percent)s, %(currency)s, now())
-- `id` ketma-ketlikdan keladi (patch DEFAULT qo'ygan); kalit — company_id.
ON CONFLICT (company_id) DO UPDATE SET
    markup_percent=EXCLUDED.markup_percent,
    risk_reserve_percent=EXCLUDED.risk_reserve_percent,
    risk_reserve_fixed=EXCLUDED.risk_reserve_fixed,
    logistics_percent=EXCLUDED.logistics_percent,
    logistics_fixed=EXCLUDED.logistics_fixed,
    vat_percent=EXCLUDED.vat_percent,
    currency=EXCLUDED.currency,
    updated_at=now()
RETURNING {_PS_COLS}
"""

_TP_COLS = ("tender_id, inputs, result, manual_price, currency, note, "
            "created_at, updated_at")

# TENDER SMETASI — ijarachi siri (tannarx!). PK (tender_id, company_id):
# ikki kompaniya AYNI tenderga alohida smeta saqlaydi.
TENDER_PRICING_GET_SQL = (f"SELECT {_TP_COLS} FROM tender_pricing "
                          "WHERE tender_id = %(id)s AND company_id = %(company_id)s")

TENDER_PRICING_UPSERT_SQL = f"""
INSERT INTO tender_pricing (tender_id, company_id, inputs, result,
                            manual_price, currency, note)
VALUES (%(tender_id)s, %(company_id)s, %(inputs)s, %(result)s,
        %(manual_price)s, %(currency)s, %(note)s)
-- PK kengaygan: `ON CONFLICT (tender_id)` endi hech qanday unique
-- cheklovga mos kelmaydi va so'rov YIQILADI.
ON CONFLICT (tender_id, company_id) DO UPDATE SET
    inputs=EXCLUDED.inputs, result=EXCLUDED.result,
    manual_price=EXCLUDED.manual_price, currency=EXCLUDED.currency,
    note=EXCLUDED.note, updated_at=now()
RETURNING {_TP_COLS}
"""

# Smeta uchun tenderdan faqat byudjet va valyuta kerak — to'liq tender
# so'rovi (lot/tovar/hujjat bilan) bu yerda ortiqcha yuk bo'lardi.
PRICING_TENDER_SQL = "SELECT id, totalcost, currency FROM tender WHERE id = %(id)s"
