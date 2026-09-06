"""
KODLASH — katalog mahsuloti <-> rasmiy tasniflagich (`good_code`)
=================================================================

NEGA BU MODUL BOR (o'lchangan, taxmin emas)
-------------------------------------------
Matn bo'yicha moslashtirish TILGA BOG'LIQ va shu sababli yiqiladi. Korpus
rus va o'zbek-kirillda, foydalanuvchi o'zbek-lotinda yozadi:

    "dori"                              -> Сосуд Дьюара, Чай зеленый     XATO
    "дори"  (transliteratsiya)          -> Урна                          XATO
    "лекарственные средства препараты"  -> 21.40, 86.23                  TO'G'RI

Ya'ni yetishmayotgani boshqa ALIFBO emas (`translit.py` buni yopmaydi),
boshqa LUG'AT. Ayni paytda `tender_good.good_code` qamrovi 100% (1880/1880
ochiq pozitsiya) va kod TILGA BOG'LIQ EMAS:

    substring "dori"       ->  6 ochiq tender
    gibrid semantik        ->  6 ochiq tender
    good_code LIKE '21%'   -> 63 ochiq tender, 124 pozitsiya

DIZAYN
------
Semantika HAR QIDIRUVDA emas, mahsulot qo'shilganda BIR MARTA ishlaydi:

    mahsulot --(taklif: 3 signal)--> nomzod kodlar --(INSON)--> tasdiqlangan
                                                                     |
    tender pozitsiyasi --(good_code)--------------------------------(join)--> moslik

Tasdiqlangandan keyin moslashtirish — indeksli `LIKE` join. Model
chaqirilmaydi, token sarflanmaydi, til farqi yo'q.

TASDIQ MAJBURIY
---------------
`catalog_product_code.tasdiqlandi IS NULL` bo'lgan qator moslashtirishda
ISHLATILMAYDI va buni struktura ta'minlaydi (`v_catalog_code_active`
ko'rinishi + `CHECK (tasdiqlandi IS NULL OR tasdiqlagan IS NOT NULL)`).

Sabab tarixiy: bu loyihada `tender_requirement` da 1514 qator
`review_status='approved'` bo'lib turibdi va ularni HECH KIM ko'rmagan —
kodning o'zi tasdiqlagan. Natijada `v_review_disagreement` "0%
kelishmovchilik" ko'rsatadi, ya'ni asbob o'zini o'lchaydi. Bu yerda o'sha
xato takrorlanmaydi.

NIMA O'LCHANMAGAN (halol qoldiriladi)
-------------------------------------
Kod-asosli moslikni `tender_category` oracle'i bilan tekshirib BO'LMAYDI:
`etl_categorize.py` kategoriyani AYNAN `good_code` dan chiqaradi
(good_code -> NACE bo'limi -> kategoriya). Ya'ni o'lchov 100% berardi va
hech narsani isbotlamasdi. Yagona haqiqiy tekshiruv — inson tasdig'i,
ya'ni `v_code_review` navbati.

Manba ma'lumoti ham mukammal emas: 21.31 (farmatsevtika) kodi ostida
"Стол психолога" uchraydi — xaridor pozitsiyani noto'g'ri kodlagan.
Inson tasdig'i aynan shuni ushlaydi.
"""
import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

from api import categories as C
from api import db, translit, xatolar

#: Taklif uchun ishlatiladigan daraja. 2 juda keng (butun NACE bo'limi),
#: 8 juda tor (823 ta sinf, ko'pi bitta tenderda uchraydi). 5 — guruh.
DEFAULT_LEVEL = 5

#: RRF birlashtirish konstantasi. Klassik qiymat; kichikroq bo'lsa
#: birinchi o'rinlar haddan tashqari ustunlik qiladi.
RRF_K = 60

#: Kategoriya oilasiga a'zolik bonusi. Qiymat ATAYLAB `1/(RRF_K+1)` ga
#: teng — ya'ni "bitta signal bo'yicha 1-o'rin" ga arziydi. Undan katta
#: bo'lsa prior hamma narsani hal qilardi (kategoriya xato qo'yilgan
#: mahsulot hech qachon to'g'ri kod topmasdi); kichik bo'lsa begona
#: oiladagi semantik shovqin o'tib ketardi.
PRIOR_BONUS = 1.0 / (RRF_K + 1)

#: Hajm koeffitsienti — faqat TENGLARNI ajratadi. 50 ta ochiq tenderli
#: kod ham 0.0005 oladi, ya'ni bitta RRF o'rnining (0.016) 3% i.
#: Hech qachon hal qiluvchi emas — bu ataylab.
VOLUME_EPS = 1e-5

#: Bitta mahsulot uchun ko'rsatiladigan taklif soni. Inson 30 soniyada
#: ko'rib chiqadigan miqdor — undan ko'pi tasdiqni "keyingi safar" ga
#: suradi va navbat o'sib ketadi.
DEFAULT_LIMIT = 8


# ---------------------------------------------------------------------------
# 1. KATEGORIYA PRIORI — bepul va tilga bog'liq emas
# ---------------------------------------------------------------------------
def divisions_for_category(category_code: Optional[str]) -> List[str]:
    """Ichki kategoriya kodi -> NACE bo'limlari (`OKED_MAP` ning teskarisi).

    'tibbiyot' -> ['21', '32', '86', '87', '88']

    NEGA KUCHLI SIGNAL: bu bog'lanish deterministik va TILGA BOG'LIQ EMAS.
    Mahsulotda kategoriya belgilangan bo'lsa, nomzodlar darhol to'g'ri
    oilaga qisqaradi — semantik model umuman kerak bo'lmasligi mumkin.

    Parent kategoriya berilsa ichkilari ham qamraladi
    ('transport' -> 'transport/avto' bo'limlari ham).
    """
    if not category_code:
        return []
    parent = C.parent_of(category_code)
    out = [d for d, c in C.OKED_MAP.items()
           if c == category_code or C.parent_of(c) == parent]
    return sorted(set(out))


def _query_text(product: Dict[str, Any]) -> str:
    """Mahsulotdan qidiruv matni.

    Nom + kalit so'zlar BIRGA beriladi: o'lchandi, bitta so'z ("dori")
    e5 uchun juda zaif signal — korpusdagi eng yaqin 6 natija bir-biridan
    0.007 ga farq qilardi.
    """
    qismlar = [(product.get("name") or "").strip()]
    qismlar += [k.strip() for k in (product.get("keywords") or []) if k and k.strip()]
    return ", ".join(q for q in qismlar if q)


def _lexical_patterns(product: Dict[str, Any]) -> List[str]:
    """Leksik qidiruv naqshlari — HAR IKKI alifboda.

    `translit.variants()` lotin<->kirill o'qishlarini beradi. Bu lug'at
    nomlari kirillda bo'lgani uchun zarur, LEKIN yetarli emas: o'lchandi,
    "дори" ham noto'g'ri kod topadi. Shuning uchun leksik — uch signaldan
    faqat BITTASI.
    """
    out: List[str] = []
    for term in [product.get("name")] + list(product.get("keywords") or []):
        if term and term.strip():
            out.extend(translit.variants(term))
    seen, res = set(), []
    for v in out:
        if v and v not in seen and len(v) >= 3:
            seen.add(v)
            res.append(v)
    return res[:12]


# ---------------------------------------------------------------------------
# 2. TAKLIF — uch signalni RRF bilan birlashtiradi
# ---------------------------------------------------------------------------
#: Semantik shox. `embedding_c` — MARKAZLASHTIRILGAN vektor
#: (schema_patch_semantik.sql). Xom `embedding` ishlatilmaydi: o'lchandi,
#: korpus markazining normasi 0.909 (anizotropiya) va ma'nosiz so'rov
#: max 0.826 kosinus oladi, ya'ni xom kosinus ranglash signali EMAS.
#:
#: HUBLIK TUZATMASI (CSLS): xom kosinus emas, `cos - hub_bias`.
#: O'lchandi — `86.90` ("Услуга по лабораторному анализу") 25 mahsulotning
#: 14 tasida 1-o'ringa chiqardi, chunki uning vektori HAR QANDAY tibbiy
#: so'rovga yaqin (183 ta kod unga kosinus>0.3 da, aniq kod 32.50 da 124).
#: `hub_bias` = kodning O'Z 10 qo'shnisiga o'rtacha yaqinligi
#: (schema_patch_goodcode_2.sql). 86.90 -> 0.570, 32.50 -> 0.466.
#:
#: DIQQAT — bu ifoda HNSW indeksidan foydalanmaydi (arifmetika bor).
#: 1146 ta kod uchun to'liq skan millisekundlar oladi. Lug'at o'n
#: minglarga o'ssa qayta ko'rib chiqish kerak.
SQL_SEM = """
SELECT ge.code,
       ROW_NUMBER() OVER (
           ORDER BY (1 - (ge.embedding_c <=> %(qvec)s::vector))
                    - COALESCE(ge.hub_bias, 0) DESC) AS rnk
FROM good_code_embedding ge
JOIN dim_good_code d ON d.code = ge.code
WHERE ge.embedding_c IS NOT NULL
  AND d.level = %(level)s
  AND d.n_tender_open > 0
ORDER BY (1 - (ge.embedding_c <=> %(qvec)s::vector))
         - COALESCE(ge.hub_bias, 0) DESC
LIMIT %(cap)s
"""

#: Leksik shox — lug'at nomlari bo'yicha trigram o'xshashligi.
#: `names` massivi chastota bo'yicha tartiblangan, shuning uchun
#: birinchi nomlar guruhning haqiqiy vakili.
SQL_LEX = """
SELECT d.code,
       ROW_NUMBER() OVER (ORDER BY max(similarity(lower(n.nom), p.naqsh)) DESC) AS rnk
FROM dim_good_code d
CROSS JOIN LATERAL unnest(d.names) AS n(nom)
CROSS JOIN unnest(%(naqshlar)s::text[]) AS p(naqsh)
WHERE d.level = %(level)s
  AND d.n_tender_open > 0
  AND lower(n.nom) %% p.naqsh
GROUP BY d.code
ORDER BY max(similarity(lower(n.nom), p.naqsh)) DESC
LIMIT %(cap)s
"""

#: Kategoriya priori — A'ZOLIK, RANG EMAS.
#:
#: NEGA RANG EMAS: prior avval RRF ga uchinchi RANGLANGAN ro'yxat bo'lib
#: kirardi va o'lchandi — `86.90` ("Услуга по лабораторному анализу",
#: bor-yo'g'i 1 ta ochiq tender) 25 mahsulotning 14 tasida BIRINCHI
#: o'ringa chiqdi. Sabab: u ikkita zaif signaldan (prior + semantik)
#: ball yig'ib, bitta kuchli signalga ega kodni bosib ketardi.
#:
#: Endi prior — BITTA BONUS: to'g'ri NACE oilasidami yoki yo'q. Tartibni
#: leksik va semantik hal qiladi, prior esa begona oilani pastga suradi.
SQL_PRIOR = """
SELECT d.code
FROM dim_good_code d
WHERE d.level = %(level)s
  AND substring(d.code from 1 for 2) = ANY(%(divisions)s)
"""


def takliflar(product: Dict[str, Any],
              level: int = DEFAULT_LEVEL,
              limit: int = DEFAULT_LIMIT,
              cap: int = 40) -> List[Dict[str, Any]]:
    """Mahsulot uchun nomzod kodlar — RRF bilan birlashtirilgan.

    `product`: `name`, `keywords`, `category_code` (ixtiyoriy).

    Qaytadi: [{code, name_ru, n_tender_open, skor, signallar}] — skor
    bo'yicha kamayish tartibida.

    SKOR FOIZ EMAS. U RRF yig'indisi, ya'ni faqat TARTIBLASH uchun.
    O'lchandi: markazlangan kosinusning absolyut qiymati shovqindan
    ajralmaydi (shovqin p99 = 0.119, haqiqiy so'rov top-1 = 0.139), ya'ni
    undan "% moslik" yasash yolg'on bo'lardi. Interfeys shuning uchun
    RAQAM emas, `n_tender_open` (oqibat) ko'rsatadi.
    """
    qmatn = _query_text(product)
    if not qmatn:
        return []

    divisions = divisions_for_category(product.get("category_code"))
    naqshlar = _lexical_patterns(product)

    ranklar: Dict[str, Dict[str, int]] = {}

    def yig(nom: str, rows: Sequence[Dict[str, Any]]) -> None:
        for r in rows:
            ranklar.setdefault(r["code"], {})[nom] = int(r["rnk"])

    # --- Signal 1: leksik (trigram, ikki alifboda) ---
    if naqshlar:
        yig("leksik", db.query(SQL_LEX,
                               {"level": level, "naqshlar": naqshlar, "cap": cap}))

    # --- Signal 2: semantik (markazlangan vektor) ---
    # AI IXTIYORIY: model yo'q bo'lsa yoki lug'at hali vektorlanmagan
    # bo'lsa, leksik signal ishlayveradi. Jimgina bo'sh natija emas.
    try:
        from api import ai_chat
        qvec = ai_chat.vec_literal(ai_chat.embed_query(qmatn))
        yig("semantik", db.query(SQL_SEM,
                                 {"qvec": qvec, "level": level, "cap": cap}))
    except Exception:                                        # noqa: BLE001
        pass

    if not ranklar:
        return []

    # --- Prior: A'ZOLIK bonusi (rang emas) ---
    oila = set()
    if divisions:
        oila = {r["code"] for r in db.query(
            SQL_PRIOR, {"level": level, "divisions": divisions})}

    skorlar: Dict[str, float] = {}
    for code, sig in ranklar.items():
        s = sum(1.0 / (RRF_K + r) for r in sig.values())
        if code in oila:
            s += PRIOR_BONUS
        skorlar[code] = s

    hajm = {r["code"]: r["n_tender_open"] for r in db.query(
        "SELECT code, n_tender_open FROM dim_good_code WHERE code = ANY(%(c)s)",
        {"c": list(skorlar)})}
    for code in skorlar:
        skorlar[code] += min(hajm.get(code, 0), 50) * VOLUME_EPS

    eng = sorted(skorlar, key=lambda c: -skorlar[c])[:limit]

    rows = db.query(
        "SELECT code, name_ru, names, n_tender_open, n_position "
        "FROM dim_good_code WHERE code = ANY(%(codes)s)", {"codes": eng})
    bymap = {r["code"]: r for r in rows}

    out = []
    for code in eng:
        r = bymap.get(code)
        if not r:
            continue
        out.append({
            "code": code,
            "name_ru": r["name_ru"],
            "namunalar": (r["names"] or [])[:4],
            "n_tender_open": r["n_tender_open"],
            "n_position": r["n_position"],
            "skor": round(skorlar[code], 5),
            # SHAFFOFLIK: qaysi signal ushbu kodni ko'rsatgani ko'rinsin.
            # "qora quti bo'lmasin" — inson NEGA taklif qilinganini bilsin.
            "signallar": sorted(ranklar[code]) + (["oila"] if code in oila else []),
        })
    return out


# ---------------------------------------------------------------------------
# 3. TASDIQ / RAD — faqat inson
# ---------------------------------------------------------------------------
def taklif_yoz(company_id: int, product_id: int,
               kodlar: Sequence[Dict[str, Any]]) -> int:
    """Takliflarni TASDIQLANMAGAN holda yozadi. Qaytadi: yozilgan soni.

    Mavjud qatorga TEGMAYDI — inson allaqachon qaror qilgan bo'lsa
    (tasdiq yoki rad), taklif uni bekor qilmaydi.
    """
    n = 0
    for k in kodlar:
        # RETURNING bor — `execute_returning` yozadi va commit qiladi
        # (loyiha konvensiyasi; `query()` rollback qiladi, yozish uchun
        # yaramaydi). Qator allaqachon bo'lsa DO NOTHING hech narsa
        # qaytarmaydi, ya'ni `row is None` = "yangi yozilmadi".
        row = db.execute_returning(
            "INSERT INTO catalog_product_code "
            "  (product_id, company_id, code, manba, skor) "
            "VALUES (%(p)s, %(c)s, %(k)s, 'taklif', %(s)s) "
            "ON CONFLICT (product_id, code) DO NOTHING "
            "RETURNING product_id",
            {"p": product_id, "c": company_id, "k": k["code"],
             "s": k.get("skor")})
        n += 1 if row else 0
    return n


def tasdiqla(company_id: int, product_id: int, code: str, kim: str,
             qaror_id: Optional[int] = None, *,
             ishonch: str, actor_id: Optional[int] = None) -> bool:
    """Tasdiq yoziladi. `ishonch` MAJBURIY va standart qiymati YO'Q.

    O'LCHANGAN NUQSON (2026-09-02). Ilgari yagona shart `kim` bo'sh
    bo'lmasligi edi va u MASHINANI TO'XTATMASDI: bazada 1 048 ta
    "tasdiq" bor edi, `tasdiqlagan` ustunida atigi ikki qiymat
    ('tizim:auto' va 'kompaniya') va ular 16 ta turli sekundda
    yozilgan — ya'ni ~34 va ~290 qator/sekund. Bo'sh bo'lmagan
    satr ODAM degani emas.

    Endi MANBA yoziladi va u bazada tekshiriladi
    (`catalog_product_code_tasdiq_manba_chk`). `ishonch` ning
    standart qiymati ATAYLAB yo'q: har chaqiruvchi kim nomidan
    yozayotganini OSHKOR aytishi shart. Avtomatika ham yoza oladi,
    lekin `servis` deb belgilanadi va inson ulushiga KIRMAYDI.
    """
    if not (kim or "").strip():
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "kim"})
    # `company_id` shartda TURISHI SHART — ko'p-ijarachilik: A kompaniya
    # B ning bog'lanishini tasdiqlay olmasin. Statik SQL skaneri
    # (_tests/multitenant_test.py) shu qoidani majburlaydi.
    row = db.execute_returning(
        "UPDATE catalog_product_code "
        "SET tasdiqlandi = now(), tasdiqlagan = %(kim)s, rad_etildi = NULL, "
        "    tasdiq_ishonch = %(ish)s, tasdiq_actor_id = %(aid)s, "
        # `COALESCE` — mavjud bog'lanish YO'QOLMAYDI: qayta tasdiqlash
        # audit izini o'chirib yubormasin.
        "    qaror_id = COALESCE(%(q)s, qaror_id) "
        "WHERE product_id = %(p)s AND code = %(k)s AND company_id = %(c)s "
        "RETURNING product_id",
        {"p": product_id, "k": code, "c": company_id, "kim": kim.strip(),
         "q": qaror_id, "ish": ishonch, "aid": actor_id})
    return row is not None


def rad_et(company_id: int, product_id: int, code: str, *,
           ishonch: str, actor_id: Optional[int] = None) -> bool:
    """Taklif rad etildi. Qator O'CHIRILMAYDI — aks holda keyingi
    taklif uni qayta chiqarardi va inson bir ishni takror qilardi.

    RAD ETISH HAM QAROR. Ilgari bu yo'lda umuman hech qanday
    kimlik yozilmasdi (`tasdiqlagan` NULL ga tushardi), ya'ni
    "kim rad etdi" degan savol JAVOBSIZ edi. Endi tasdiq bilan
    AYNI qoida.
    """
    row = db.execute_returning(
        "UPDATE catalog_product_code "
        "SET rad_etildi = now(), tasdiqlandi = NULL, tasdiqlagan = NULL, "
        "    tasdiq_ishonch = %(ish)s, tasdiq_actor_id = %(aid)s "
        "WHERE product_id = %(p)s AND code = %(k)s AND company_id = %(c)s "
        "RETURNING product_id",
        {"p": product_id, "k": code, "c": company_id,
         "ish": ishonch, "aid": actor_id})
    return row is not None


# ---------------------------------------------------------------------------
# 4. MOSLASHTIRISH — tasdiqlangan kodlar bo'yicha, POZITSIYA darajasida
# ---------------------------------------------------------------------------
#: NEGA POZITSIYA DARAJASIDA: o'lchandi — bitta tenderда ham
#: "Стол ученический" (31.01), ham "Шкаф медицинский" (32.50) bo'ladi.
#: Tender darajasidagi kategoriya shuning uchun qo'pol. Tibbiy shkaf
#: sotuvchi broker o'sha tenderni KO'RISHI kerak, lekin QAYSI pozitsiya
#: unga tegishli ekanini ham bilishi kerak — TZ dagi `match_line` shu.
SQL_MOSLIK = """
WITH kodlar AS (
    -- ALIAS MAJBURIY (`v.`). Bu so'rovda ijarachi ustunining IKKI xil
    -- ma'nosi uchrashadi: `t.company_id` — BUYURTMACHI tashkiloti (manba
    -- platformadan kelgan), `v.company_id` — BIZNING ijarachimiz.
    -- Aliassiz qoldirilsa PostgreSQL o'zi tanlaydi: xato chiqmaydi,
    -- natija noto'g'ri bo'ladi. `_tests/multitenant_test.py` (A4) buni
    -- statik tekshiradi (u izoh matnini ham skanerlaydi, shuning uchun
    -- bu yerda ham aliasli shakl yozilgan).
    SELECT DISTINCT v.code, v.product_id, v.product_name
    FROM v_catalog_code_active v
    WHERE v.company_id = %(company_id)s
      AND (%(product_ids)s::bigint[] IS NULL
           OR v.product_id = ANY(%(product_ids)s::bigint[]))
)
SELECT t.id                                   AS tender_id,
       count(DISTINCT g.good_code)            AS mos_pozitsiya,
       sum(g.totalcost_item)                  AS mos_summa,
       array_agg(DISTINCT k.product_name)     AS mahsulotlar,
       array_agg(DISTINCT g.name)             AS pozitsiyalar,
       array_agg(DISTINCT k.code)             AS kodlar
FROM kodlar k
JOIN tender_good g ON g.good_code LIKE k.code || '%%'
JOIN tender t      ON t.id = g.tender_id
WHERE (%(only_open)s IS FALSE
       OR (t.status = 'open' AND (t.close_at IS NULL OR t.close_at > now())))
GROUP BY t.id
ORDER BY mos_pozitsiya DESC, mos_summa DESC NULLS LAST
LIMIT %(limit)s
"""


def moslik(company_id: int, only_open: bool = True,
           limit: int = 200,
           product_ids: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
    """Kompaniyaning TASDIQLANGAN kodlari bo'yicha mos tenderlar.

    Tasdiqlangan kodi yo'q bo'lsa BO'SH ro'yxat qaytadi — va chaqiruvchi
    buni "moslik yo'q" deb EMAS, "katalog hali kodlanmagan" deb
    ko'rsatishi shart (`v_catalog_kodsiz`). Ikkisi butunlay boshqa holat.
    """
    return db.query(SQL_MOSLIK, {"company_id": company_id,
                                 "only_open": only_open, "limit": limit,
                                 "product_ids": (list(product_ids)
                                                 if product_ids else None)})


#: "Sizga mos" bo'limi qancha tenderni ko'rib chiqadi.
#:
#: `POST /catalog/match` va navbat filtrlari SHU BITTA raqamni
#: ishlatadi. Ikki joyda ikki xil chegara turgan bo'lsa "Sizga
#: mos" da ko'ringan tender navbat filtrida CHIQMASLIGI mumkin
#: edi — va sabab hech qayerda ko'rinmasdi.
MOSLIK_LIMIT = 1000


def mos_tender_idlari(company_id: int, only_open: bool = True) -> set:
    """"Sizga mos" bo'limidagi tenderlarning id lari — YAGONA manba.

    NEGA ALOHIDA FUNKSIYA (2026-09-03). Bu ta'rifni endi UCH joy
    so'raydi: `POST /catalog/match` (ro'yxatning o'zi), broker
    navbati filtri va ko'rik navbati filtri. Har biri o'zicha
    hisoblasa ular ASTA-SEKIN ajralib ketardi — bu loyihada
    aynan shunday bo'lgan: hudud qoidasi ikki joyda yozilgani
    uchun "Sizga mos" va navbat boshqa-boshqa javob berardi.

    FAQAT KOD YO'LI. `/catalog/match` da matn yo'li ham bor, lekin
    u `include_probable=true` bo'lgandagina qo'shiladi va interfeys
    uni STANDART holda YUBORMAYDI. Ya'ni foydalanuvchi ko'radigan
    "Sizga mos" — aynan shu to'plam. Matn yo'lini bu yerga qo'shish
    filtrni ro'yxatdan KENGROQ qilardi.

    KATALOG KODLANMAGAN bo'lsa BO'SH to'plam qaytadi. Chaqiruvchi
    buni "moslik yo'q" deb emas, "katalog hali kodlanmagan" deb
    ko'rsatishi kerak — ikkisi butunlay boshqa holat.
    """
    from api import queries

    prods = db.query(queries.CATALOG_LIST_SQL, {"company_id": company_id})
    if not prods:
        return set()
    rows = moslik(company_id, only_open=only_open, limit=MOSLIK_LIMIT,
                  product_ids=[p["id"] for p in prods])
    return {r["tender_id"] for r in rows}


#: Bitta tenderning MOS POZITSIYALARI — dalil bilan.
#:
#: NEGA POZITSIYA QAYTADI: broker "bu tender menga mos" degan da'voni
#: TEKSHIRA olishi kerak. Mahsulot nomini ko'rsatish yetarli emas —
#: o'lchandi, bir kod (masalan `32.50`) katalogning 8 ta mahsuloti
#: bilan bog'langan bo'lishi mumkin va u holda qaysi biri
#: ko'rsatilishi TASODIFIY bo'lib qoladi: "Шкаф медицинский"
#: pozitsiyasi yonida "Bemor monitori" chiqardi.
SQL_POZITSIYALAR = """
SELECT g.tender_id, g.good_code, g.name AS pozitsiya,
       g.amount, g.unit, g.totalcost_item,
       v.code, v.product_id, v.product_name
FROM tender_good g
JOIN v_catalog_code_active v
  ON g.good_code LIKE v.code || '%%'
 AND v.company_id = %(company_id)s
 AND (%(product_ids)s::bigint[] IS NULL
      OR v.product_id = ANY(%(product_ids)s::bigint[]))
WHERE g.tender_id = ANY(%(ids)s)
  AND g.name IS NOT NULL
ORDER BY g.tender_id, g.good_code
"""


#: Atribut uchun eng kichik o'xshashlik. Bundan past bo'lsa MAHSULOT
#: BIRIKTIRILMAYDI — "Шкаф для книг" (kitob javoni) katalogdagi hech
#: bir mahsulotga o'xshamaydi va unga tasodifiy nom yopishtirish
#: foydalanuvchini chalg'itadi. O'lchangan qiymatlar:
#:     "Кресло офисное"   -> "Ofis kreslosi"  0.348   (to'g'ri)
#:     "Шкаф медицинский" -> "Tibbiy shkaf"   0.192   (to'g'ri)
#:     "Шкаф медицинский" -> "Bemor monitori" 0.030   (shovqin)
#: 0.05 shovqin (0.03) dan yuqori, eng zaif to'g'ri moslik (0.179) dan past.
ATRIBUT_CHEGARA = 0.05


@lru_cache(maxsize=32768)
def _uchliklar(s: str) -> frozenset:
    """Belgi-uchliklar to'plami. KESHLANADI — sof funksiya.

    `frozenset` qaytadi: chaqiruvchi to'plamni o'zgartirsa kesh
    zaharlanardi.
    """
    s = f"  {(s or '').lower().strip()}  "
    return frozenset(s[i:i + 3] for i in range(len(s) - 2))


@lru_cache(maxsize=65536)
def _ozgarish(katalog_nomi: str, pozitsiya: str) -> float:
    """Katalog nomi va tender pozitsiyasining o'xshashligi, 0..1.

    TRANSLITERATSIYA MAJBURIY. Katalog o'zbek-lotinda, korpus rus va
    o'zbek-kirillda — xom belgi-uchliklar HAR DOIM 0 beradi:

        xom:        "Кресло офисное" <-> "Ofis kreslosi"  = 0.000
        translit:                                          = 0.348

    Xom taqqoslash bilan atribut butunlay tasodifiy bo'lardi va aynan
    shu sababli "Шкаф медицинский" pozitsiyasi yonida "Bemor monitori"
    ko'rinardi.
    """
    nishon = translit.norm_text(pozitsiya)
    B = _uchliklar(nishon)
    if not B:
        return 0.0
    eng = 0.0
    for v in (translit.variants(katalog_nomi) or [katalog_nomi]):
        A = _uchliklar(v)
        if A:
            eng = max(eng, len(A & B) / len(A | B))
    return eng


def pozitsiya_moslik(company_id: int,
                     tender_ids: Sequence[int],
                     product_ids: Optional[Sequence[int]] = None
                     ) -> Dict[int, List[Dict[str, Any]]]:
    """Tender -> mos pozitsiyalar ro'yxati, TO'G'RI mahsulot atributi bilan.

    Bir kodni bir necha mahsulot baham ko'rsa, pozitsiyaga NOMI eng
    yaqin mahsulot biriktiriladi. Bu taxmin va shundayligicha
    belgilanadi (`aniq=False`) — interfeys shubhani yashirmasin.
    """
    if not tender_ids:
        return {}
    rows = db.query(SQL_POZITSIYALAR,
                    {"company_id": company_id, "ids": list(tender_ids),
                     "product_ids": (list(product_ids) if product_ids else None)})

    # Pozitsiya bo'yicha guruhlaymiz: bitta pozitsiyaga bir nechta
    # mahsulot da'vogar bo'lishi mumkin.
    davogarlar: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        davogarlar.setdefault((r["tender_id"], r["good_code"], r["pozitsiya"]),
                              []).append(r)

    out: Dict[int, List[Dict[str, Any]]] = {}
    for (tid, gcode, poz), lst in davogarlar.items():
        if len(lst) == 1:
            eng, aniq = lst[0], True
        else:
            # Bir kodni bir necha mahsulot baham ko'rgan -> pozitsiya
            # nomiga eng yaqinini tanlaymiz.
            # BALL BIR MARTA hisoblanadi. Ilgari `max(key=...)` har
            # da'vogar uchun hisoblardi, so'ng g'olib uchun YANA bir
            # marta — ya'ni N+1 chaqiruv. Endi juftlik saqlanadi.
            skor, eng = max(((_ozgarish(r["product_name"], poz), r)
                             for r in lst), key=lambda t: t[0])
            if skor < ATRIBUT_CHEGARA:
                # SIGNAL YO'Q -> TAXMIN QILMAYMIZ. Pozitsiya ko'rsatiladi,
                # mahsulot nomi esa NULL. Tasodifiy nom yopishtirish
                # foydalanuvchini chalg'itadi (bu aynan shikoyat
                # qilingan xatti-harakat edi).
                out.setdefault(tid, []).append({
                    "pozitsiya": poz, "good_code": gcode, "kod": eng["code"],
                    "mahsulot": None, "mahsulot_id": None,
                    "aniq": False, "davogar": len(lst),
                    "miqdor": (float(eng["amount"])
                               if eng["amount"] is not None else None),
                    "birlik": eng["unit"],
                    "summa": (float(eng["totalcost_item"])
                              if eng["totalcost_item"] is not None else None),
                })
                continue
            aniq = False
        out.setdefault(tid, []).append({
            "pozitsiya": poz,
            "good_code": gcode,
            "kod": eng["code"],
            "mahsulot": eng["product_name"],
            "mahsulot_id": eng["product_id"],
            # `aniq=False` -> bir kodni bir necha mahsulot baham ko'rgan,
            # mahsulot nomi TAXMIN. Interfeys buni ko'rsatishi kerak.
            "aniq": aniq,
            "davogar": len(lst),
            "miqdor": float(eng["amount"]) if eng["amount"] is not None else None,
            "birlik": eng["unit"],
            "summa": (float(eng["totalcost_item"])
                      if eng["totalcost_item"] is not None else None),
        })
    return out


# ---------------------------------------------------------------------------
# DALIL — "bu kod ostida HAQIQATAN nima bor?"
#
# BU MODULNING ENG MUHIM QISMI, taklif algoritmi emas.
#
# Kod nomi begona tilda bo'lishi mumkin, lekin POZITSIYALAR tanish.
# Qo'lda ko'rib chiqqanda qaror aynan shundan chiqdi:
#
#     26.40  Камера видеонаблюдения   9 ochiq
#            poz: Камера видеонаблюдения, Микрофон, Аудио спикерфон   -> HA
#     26.51  Кульман                 26 ochiq
#            poz: Дефектоскоп, Термопара, Анализатор воздуха          -> YO'Q
#
# 26.51 uch barobar ko'p tender va'da qiladi va shunga qaramay 3
# soniyada rad etiladi — chunki pozitsiyalar ko'rinib turibdi.
#
# Bu til muammosini AYLANIB O'TADI: tarjima qilmaydi, brokerga o'z
# sohasidagi tovar nomlarini ko'rsatadi.
# ---------------------------------------------------------------------------
SQL_DALIL = """
SELECT substring(g.good_code from 1 for %(uzunlik)s) AS kod,
       g.name AS pozitsiya,
       count(*)                                        AS n_pozitsiya,
       count(DISTINCT t.id) FILTER (
           WHERE t.status = 'open'
             AND (t.close_at IS NULL OR t.close_at > now()))  AS n_ochiq
FROM tender_good g
JOIN tender t ON t.id = g.tender_id
WHERE g.good_code IS NOT NULL
  AND g.name IS NOT NULL
  AND substring(g.good_code from 1 for %(uzunlik)s) = ANY(%(kodlar)s)
GROUP BY 1, 2
ORDER BY 1, 4 DESC, 3 DESC
"""


def dalil(kodlar: Sequence[str], limit: int = 6) -> Dict[str, Dict[str, Any]]:
    """Kod -> o'sha kod ostidagi HAQIQIY pozitsiyalar va ochiq tender soni.

    `kodlar` bir xil uzunlikda bo'lishi kutiladi (5 yoki 8) — aralash
    kelsa har uzunlik uchun alohida so'rov ketadi.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for uzunlik in sorted({len(k) for k in kodlar if k}):
        qism = [k for k in kodlar if len(k) == uzunlik]
        for r in db.query(SQL_DALIL, {"kodlar": qism, "uzunlik": uzunlik}):
            d = out.setdefault(r["kod"], {"pozitsiyalar": [], "n_ochiq": 0,
                                          "n_pozitsiya": 0})
            d["n_pozitsiya"] += r["n_pozitsiya"]
            d["n_ochiq"] = max(d["n_ochiq"], r["n_ochiq"] or 0)
            if len(d["pozitsiyalar"]) < limit:
                d["pozitsiyalar"].append({"nom": r["pozitsiya"],
                                          "n_ochiq": r["n_ochiq"] or 0})
    for k in kodlar:
        out.setdefault(k, {"pozitsiyalar": [], "n_ochiq": 0, "n_pozitsiya": 0})
    return out


def _ozaklar(atama_matni: str):
    """Atamadan (keng_ozak, aniq_soz) juftligini beradi. Yo'q -> (None, None)."""
    sozlar = [w for w in re.split(r"[\s,\-/]+", atama_matni or "")
              if len(w) >= _TALAB_MIN]
    if not sozlar:
        return None, None
    w = translit.norm_text(sorted(sozlar, key=len, reverse=True)[0])
    return w[:max(_TALAB_MIN, len(w) - 2)], w


def _talab_bormi(atamalar) -> Dict[str, int]:
    """Atama korpusda UMUMAN uchraydimi — ARZON tekshiruv.

    `count(DISTINCT tender)` va `tender` bilan join YO'Q: bu yerda
    faqat NOL/NOLMAS kerak. To'liq raqam keyin, ko'rsatiladigan
    atamalar uchun hisoblanadi.
    """
    juft = {}
    for a in atamalar:
        keng, _ = _ozaklar(a)
        if keng:
            juft[a] = f"%{keng}%"
    if not juft:
        return {}
    atama_list = list(juft)
    rows = db.query(
        "WITH n(pat, idx) AS (SELECT * FROM unnest(%(pats)s::text[]) "
        "                     WITH ORDINALITY) "
        "SELECT n.idx, count(g.*) AS jami "
        "FROM n LEFT JOIN tender_good g "
        f"       ON {translit.sql_fold('g.name')} LIKE n.pat "
        "GROUP BY n.idx",
        {"pats": [juft[a] for a in atama_list]})
    say = {r["idx"]: (r["jami"] or 0) for r in rows}
    return {a: say.get(i + 1, 0) for i, a in enumerate(atama_list)}


def _talab_koplab(atamalar) -> Dict[str, Dict[str, int]]:
    """Ko'p atamaning talabini BITTA so'rovda o'lchaydi.

    Atama boshiga ikki so'rov yuborish (~260 atama = 520 so'rov)
    navbatni 19 soniyaga cho'zardi. Naqshlar massiv sifatida beriladi
    va solishtirishni Postgres bajaradi.
    """
    juft = {}
    for a in atamalar:
        keng, aniq = _ozaklar(a)
        if keng:
            juft[a] = (keng, aniq)
    if not juft:
        return {}

    naqsh, tur = [], []
    for a, (keng, aniq) in juft.items():
        naqsh.append(f"%{keng}%"); tur.append("keng")
        naqsh.append(f"%{aniq}%"); tur.append("aniq")

    rows = db.query(
        # USTUN TARTIBI: `unnest(...) WITH ORDINALITY` avval QIYMATNI,
        # keyin tartib raqamini qaytaradi. `n(idx, pat)` deb yozilsa
        # ular teskari bog'lanadi va `LIKE` bigint bilan solishtiriladi.
        "WITH n(pat, idx) AS (SELECT * FROM unnest(%(pats)s::text[]) "
        "                     WITH ORDINALITY) "
        "SELECT n.idx, count(g.*) AS jami, "
        "       count(DISTINCT t.id) FILTER ("
        "           WHERE t.status='open' "
        "             AND (t.close_at IS NULL OR t.close_at > now())) AS ochiq "
        "FROM n LEFT JOIN tender_good g "
        f"       ON {translit.sql_fold('g.name')} LIKE n.pat "
        "     LEFT JOIN tender t ON t.id = g.tender_id "
        "GROUP BY n.idx",
        {"pats": naqsh})
    say = {r["idx"]: r for r in rows}

    out: Dict[str, Dict[str, int]] = {}
    i = 1
    for a in juft:
        k = say.get(i, {})
        an = say.get(i + 1, {})
        out[a] = {"jami": k.get("jami") or 0, "ochiq": k.get("ochiq") or 0,
                  "aniq_jami": an.get("jami") or 0,
                  "aniq_ochiq": an.get("ochiq") or 0}
        i += 2
    return out


#: Navbatda bir marta ko'rsatiladigan atamalar soni. Chegara bor,
#: chunki har atama uchun taklif hisoblanadi (embedding + SQL).
NAVBAT_LIMIT = 40

#: Korpusda talabni o'lchash uchun eng qisqa o'zak. Undan qisqasi
#: deyarli hamma narsaga mos keladi.
_TALAB_MIN = 5

#: Tur nomining eng katta uzunligi. Undan uzunlari SPETSIFIKATSIYA
#: ("Диаметр 66 мм; рабочее давление", "ODF kross Пластик 4 port") —
#: ular mahsulot TURI emas, tavsifi, va navbatni to'ldirib haqiqiy
#: turlarni pastga suradi. `queries.MAX_TERM_LEN` bilan bir xil sabab.
_TUR_MAX_LEN = 30


def _talab(atama_matni: str) -> Dict[str, int]:
    """Atama korpusda UMUMAN uchraydimi — qaror qiymatini oldindan o'lchash.

    Qaytadi: {"jami": pozitsiya soni, "ochiq": ochiq tender soni}

    NEGA KERAK: kod berish qarori faqat TALAB bo'lganda ma'noli.
    O'lchandi — "HDMI кабели" 42 mahsulot, korpusda 0 pozitsiya;
    "Домофоны" 61 mahsulot, korpusda 0. Ularga kod berish soxta
    moslikdan boshqa narsa qo'shmaydi.

    ANIQLIK CHEGARASI — bu O'LCHOV EMAS, YUQORI CHEGARA.
    O'zak qisqartirilgani uchun begona so'zlar ham sanaladi:

        "Контроль доступа"      -> o'zak "контр"      -> "Контргайка стальная"
        "Проектное оборудование" -> o'zak "оборудован" -> har qanday uskuna

    Ya'ni MUSBAT raqamga qat'iy ishonib bo'lmaydi. NOL esa ishonchli:
    bo'sh o'zak ham hech narsa topmagan bo'lsa, korpusda haqiqatan
    yo'q. Shuning uchun bu qiymat FAQAT ikki ishda ishlatiladi:
      1. nol/nolmas ajratish (ishonchli);
      2. taxminiy tartiblash (ishonchsiz, lekin tasodifiydan yaxshi).
    Undan "shu atama N ta tender ochadi" degan XULOSA chiqarilmaydi.
    """
    sozlar = [w for w in re.split(r"[\s,\-/]+", atama_matni or "")
              if len(w) >= _TALAB_MIN]
    if not sozlar:
        return {"jami": 0, "ochiq": 0, "aniq_jami": 0, "aniq_ochiq": 0}
    # Eng uzun so'z eng aniq — u bo'yicha o'lchaymiz.
    w = translit.norm_text(sorted(sozlar, key=len, reverse=True)[0])
    # O'ZAK bo'yicha: ko'plik/kelishik farqi o'lchovni nolga tushirmasin.
    ozak = w[:max(_TALAB_MIN, len(w) - 2)]

    sql = ("SELECT count(*) AS jami, "
           "       count(DISTINCT t.id) FILTER ("
           "           WHERE t.status='open' "
           "             AND (t.close_at IS NULL OR t.close_at > now())) AS ochiq "
           "FROM tender_good g JOIN tender t ON t.id = g.tender_id "
           f"WHERE {translit.sql_fold('g.name')} LIKE %(p)s")

    keng = db.query_one(sql, {"p": f"%{ozak}%"}) or {}
    # IKKINCHI O'LCHOV — QISQARTIRILMAGAN so'z bo'yicha. Ikki raqam
    # yonma-yon turadi va farq katta bo'lsa (500 / 87) o'zak kengligi
    # sabab ekani KO'RINADI. Bitta raqam ko'rsatilsa, u aniq deb
    # o'qilardi.
    aniq = db.query_one(sql, {"p": f"%{w}%"}) or {}
    return {"jami": keng.get("jami") or 0, "ochiq": keng.get("ochiq") or 0,
            "aniq_jami": aniq.get("jami") or 0,
            "aniq_ochiq": aniq.get("ochiq") or 0}


def navbat(company_id: int, limit: int = NAVBAT_LIMIT,
           level: int = DEFAULT_LEVEL,
           takliflar_bilan: bool = True) -> Dict[str, Any]:
    """KO'RIB CHIQISH NAVBATI — kodsiz atamalar, taklif va DALIL bilan.

    Qaytadi: {"atamalar": [...], "qolgan": N}

    QAROR QILINGAN ATAMA KO'RSATILMAYDI. `talabsiz`/`otkazildi` kod
    bermaydi, ya'ni mahsulot kodsiz qoladi — filtrsiz atama navbatga
    QAYTARDI va navbat hech qachon tugamasdi (o'lchandi). U yo'qolmaydi:
    `qaror_qilingan` toifasida sanaladi va `toifa_yigindi` ga kiradi.

    Har element:
        kalit       `atama.normal()` — qoida kaliti (shu bilan saqlanadi)
        atama       ko'rsatish uchun ASL matn
        n_mahsulot  shu kalitga tegishli mahsulot soni
        takliflar   [{code, name_ru, n_ochiq, pozitsiyalar}]

    ATAMALAR `atama.normal()` BO'YICHA GURUHLANADI. Xom matn bo'lsa
    "Коммутаторы" va "Kommutatorlar" ikki alohida qator bo'lib
    chiqardi va bir ishni ikki marta qildirardi.

    KO'P MAHSULOTLI ATAMA OLDINDA: bitta qaror qancha ko'p mahsulotni
    qoplasa, shuncha arzon. O'lchangan (1797 qatorli katalog): eng ko'p
    11 naqsh 960 mahsulotni qopladi.
    """
    from api import atama as _atama

    prods = db.query(
        "SELECT id, name, keywords FROM catalog_product "
        "WHERE company_id = %(c)s "
        "  AND NOT EXISTS (SELECT 1 FROM v_catalog_code_active v "
        "                   WHERE v.product_id = catalog_product.id "
        "                     AND v.company_id = catalog_product.company_id)",
        {"c": company_id})

    # kalit -> {asl matn, mahsulot soni}
    guruh: Dict[str, Dict[str, Any]] = {}
    #: Turi aniqlanmagan mahsulotlar — JIMGINA TASHLANMAYDI.
    aniqmas: List[Dict[str, Any]] = []
    for p in prods:
        kws = list(p["keywords"] or [])
        # TUR — ko'rsatkich sifatida ikkinchi kalit so'z (katalog
        # importlarida odatda mahsulot turi), bo'lmasa birinchisi,
        # u ham bo'lmasa nomi.
        xom = ((kws[1] if len(kws) >= 2 else (kws[0] if kws else p["name"]))
               or "").strip()
        # SPETSIFIKATSIYA TUR EMAS. "Диаметр 66 мм; рабочее давление",
        # "ODF kross Пластик 4 port" — bular mahsulot tavsifi va ular
        # navbatni to'ldirib, haqiqiy turlarni pastga suradi.
        #
        # LEKIN ULAR JIMGINA YO'QOLMAYDI. Avval shunday edi va o'lchandi:
        # 837 kodsiz mahsulotdan 185 tasi na navbatda, na "talabsiz" da
        # ko'rinardi — ya'ni ular haqida hech kim bilmasdi. Endi alohida
        # toifa (`turi_aniqmas`).
        if not xom or len(xom) > _TUR_MAX_LEN:
            aniqmas.append(p)
            continue
        kalit = _atama.normal(xom)
        if not kalit:
            aniqmas.append(p)
            continue
        g = guruh.setdefault(kalit, {"atama": xom, "n_mahsulot": 0})
        g["n_mahsulot"] += 1

    # --- ALLAQACHON QAROR QILINGAN ATAMALAR NAVBATDAN CHIQADI ---
    #
    # O'lchandi (2026-08-30): `talabsiz` yoki `otkazildi` qarori KOD
    # bermaydi, ya'ni mahsulotlar kodsiz qoladi va atama keyingi
    # yuklashda navbatga QAYTARDI — o'sha joyda, o'sha tartibda.
    # Navbat hech qachon tugamasdi va har takror bosish `kod_qaror` ga
    # YANGI qator qo'yardi: bir atamani uch marta "o'tkazish" ->
    # `qaror_soni = 3`. Ya'ni "40 qaror" maqsadiga bir tugmani qayta
    # bosib ham yetish mumkin edi va hech qanday xato chiqmasdi.
    #
    # Endi qaror qilingan atama ko'rsatilmaydi. LEKIN U YO'QOLMAYDI:
    # o'z toifasida sanaladi va `toifa_yigindi` ga kiradi — qoldiqsiz
    # toifalash qoidasi shu yerda ham amal qiladi.
    qaror_kalit = {r["kalit"] for r in db.query(
        "SELECT DISTINCT kalit FROM kod_qaror "
        "WHERE company_id = %(c)s AND qaror IS NOT NULL", {"c": company_id})}
    qaror_qilingan = [(k, g) for k, g in guruh.items() if k in qaror_kalit]
    guruh = {k: g for k, g in guruh.items() if k not in qaror_kalit}

    # --- KORPUSDAGI TALAB o'lchanadi ---
    #
    # NAVBAT MAHSULOT SONI BO'YICHA EMAS. O'lchandi: "Турникеты" 39 ta
    # mahsulot, korpusda esa 3 ta pozitsiya (1 ochiq); "HDMI кабели"
    # 42 mahsulot, korpusda 0; "Домофоны" 61 mahsulot, korpusda 0.
    #
    # Bunday atamaga kod berish NOTO'G'RI bo'lardi — talab yo'q,
    # ya'ni har qanday kod faqat soxta moslik qo'shadi. Kodsiz qolishi
    # TO'G'RI natija.
    #
    # Shuning uchun tartib "bitta qaror qancha OCHIQ TENDER ochadi"
    # bo'yicha. Talabsiz atamalar oxirida turadi va ular uchun taklif
    # UMUMAN hisoblanmaydi (embedding chaqiruvi tejaladi).
    # IKKI BOSQICH — tartib endi MAHSULOT SONI bo'yicha bo'lgani uchun
    # talab raqami saralashga kerak emas, faqat:
    #   1) NOL/NOLMAS ajratish — hamma atama uchun, ARZON so'rov
    #      (`count(DISTINCT)` va `tender` join'siz);
    #   2) to'liq raqam — FAQAT ko'rsatiladigan atamalar uchun (<=40).
    # Ilgari ikkalasi ham hamma atama uchun hisoblanardi: 19 soniya.
    bor = _talab_bormi([g["atama"] for g in guruh.values()])
    for _k, g in guruh.items():
        g["korpus"] = {"jami": bor.get(g["atama"], 0), "ochiq": 0,
                       "aniq_jami": 0, "aniq_ochiq": 0}

    # TARTIB MAHSULOT SONI BO'YICHA — u ANIQ raqam.
    #
    # Ilgari tartib `talab x qamrov` edi va u `_talab()` ning
    # YUQORI CHEGARASIGA tayanardi. Oqibati e'tibordan chetda qolgandi:
    # "yuqori 10 ta" aslida "yuqori chegarasi eng katta 10 ta" edi.
    # "Контроль доступа" ning 500 foydasi "контр" -> "Контргайка" ni
    # ham sanagan bo'lishi mumkin; haqiqiy foydasi 50 bo'lsa, u navbat
    # boshida turmasligi kerak edi.
    #
    # Mahsulot soni — taxmin emas, sanoq. Talab raqamlari esa yonma-yon
    # KO'RSATILADI (keng / aniq), ya'ni broker o'zi baho beradi.
    tartib = sorted(guruh.items(),
                    key=lambda kv: (-kv[1]["n_mahsulot"],
                                    -kv[1]["korpus"]["aniq_ochiq"]))
    # NOL ISHONCHLI: keng o'zak ham hech narsa topmagan bo'lsa,
    # korpusda haqiqatan yo'q. Ajratish AYNAN shu shart bo'yicha —
    # musbat raqam bo'yicha emas.
    koriladigan = [(k, g) for k, g in tartib if g["korpus"]["jami"] > 0]
    tanlangan = koriladigan[:limit]
    # Chegaradan tashqarida qolganlar — ular ham TOIFADA, faqat shu
    # sahifada ko'rsatilmaydi. Yig'indi tekshiruvida sanaladi.
    qolgan_koriladigan = koriladigan[limit:]
    talabsiz = [(k, g) for k, g in tartib if g["korpus"]["jami"] == 0]

    # TO'LIQ TALAB — faqat ko'rsatiladigan atamalar uchun (<=40).
    toliq = _talab_koplab([g["atama"] for _k, g in tanlangan])
    for _k, g in tanlangan:
        g["korpus"] = toliq.get(g["atama"], g["korpus"])

    # Takliflar va DALIL — FAQAT talabi bor atamalar uchun
    natija: List[Dict[str, Any]] = []
    barcha_kod: List[str] = []
    # TAKLIF IXTIYORIY. O'lchandi: 10 atama uchun 53 s (har atamada
    # embedding chaqiruvi). Va o'lchov shuni ham ko'rsatdiki, taklif
    # sifati past — 10 tadan 1-2 tasida ishonchli nomzod bor. Asosiy
    # yo'l endi QIDIRUV (`qidir()`), taklif esa qo'shimcha.
    # Shuning uchun navbat standart holda taklifsiz ham ochilishi
    # mumkin va u bir necha soniya emas, millisekund oladi.
    for _kalit, g in tanlangan:
        t = (takliflar({"name": g["atama"], "keywords": []},
                       level=level, limit=3) if takliflar_bilan else [])
        g["_t"] = t
        barcha_kod.extend(x["code"] for x in t)
    dalillar = dalil(sorted(set(barcha_kod))) if barcha_kod else {}

    for kalit, g in tanlangan:
        natija.append({
            "kalit": kalit,
            "atama": g["atama"],
            "n_mahsulot": g["n_mahsulot"],
            # IKKI RAQAM YONMA-YON. `keng` qisqartirilgan o'zak bo'yicha
            # (yuqori chegara), `aniq` to'liq so'z bo'yicha. Farq katta
            # bo'lsa o'zak kengligi sabab ekani ko'rinadi va broker
            # ehtiyot bo'ladi. Bitta raqam ko'rsatilsa u ANIQ deb
            # o'qilardi — bu esa yolg'on bo'lardi.
            "korpus_ochiq": g["korpus"]["ochiq"],
            "korpus_jami": g["korpus"]["jami"],
            "korpus_ochiq_aniq": g["korpus"]["aniq_ochiq"],
            "korpus_jami_aniq": g["korpus"]["aniq_jami"],
            "takliflar": [{
                "code": x["code"],
                "name_ru": x["name_ru"],
                # SKOR ham beriladi: qaror paytida u `kod_qaror.
                # taklif_skor` ga yozib olinadi va "mashina qanchalik
                # ishonchli edi" degan savolga javob beradi. Busiz
                # kelishuv foizi bor-yo'g'i "to'g'ri/noto'g'ri"
                # bo'lardi, ishonch darajasi bo'yicha kesib
                # bo'lmasdi.
                "skor": x.get("skor"),
                "n_tender_open": x["n_tender_open"],
                # DALIL — qarorning asosi. Kod nomi begona bo'lishi
                # mumkin, pozitsiyalar esa tanish.
                "pozitsiyalar": dalillar.get(x["code"], {}).get("pozitsiyalar", []),
            } for x in g["_t"]],
        })
    return {
        "atamalar": natija,
        "qolgan": len(qolgan_koriladigan),
        # TALABSIZ atamalar JIMGINA yo'qolmaydi — ular "hali ko'rilmagan"
        # emas, "ko'rish SHART EMAS". Interfeys buni ayirishi kerak.
        "talabsiz": [{"kalit": k, "atama": g["atama"],
                      "n_mahsulot": g["n_mahsulot"]}
                     for k, g in talabsiz[:20]],
        "talabsiz_jami": len(talabsiz),
        # TURI ANIQLANMAGAN — kalit so'zi spetsifikatsiya yoki bo'sh.
        # Ular kodlanmaydi, lekin YO'QOLMAYDI ham: interfeys ularni
        # ko'rsatib, katalogni tuzatishni taklif qiladi.
        "turi_aniqmas": [{"id": x["id"], "name": x["name"]}
                         for x in aniqmas[:20]],
        "turi_aniqmas_jami": len(aniqmas),
        # QAROR QILINGAN — inson allaqachon ko'rgan. Ular navbatda
        # ko'rsatilmaydi (aks holda navbat tugamasdi), lekin YO'QOLMAYDI:
        # yig'indiga kiradi va bu yerda sanaladi. Kodi bo'lmagani uchun
        # mahsulotlari hali kodsiz — bu HOLAT, xato emas ('talabsiz' va
        # 'otkazildi' ataylab kod bermaydi).
        "qaror_qilingan": [{"kalit": k, "atama": g["atama"],
                            "n_mahsulot": g["n_mahsulot"]}
                           for k, g in qaror_qilingan[:20]],
        "qaror_qilingan_jami": len(qaror_qilingan),
        # QOLDIQSIZ TOIFALASH — yig'indi JAMIGA teng.
        #
        # Bu umumiy qoida, alohida holat emas: har toifalashda QOLDIQ
        # toifa bo'lishi va yig'indi tekshirilishi shart. Aks holda
        # element jimgina yo'qoladi va hech qanday xato chiqmaydi —
        # aynan shu sodir bo'ldi: 837 kodsiz mahsulotdan 185 tasi na
        # navbatda, na "talabsiz" da ko'rinmasdi (turi 30 belgidan
        # uzun edi). Bu loyihada shu sinf o'ninchi marta uchradi.
        "jami_mahsulot": len(prods),
        "toifa_yigindi": (
            sum(g["n_mahsulot"] for _k, g in tanlangan)
            + sum(g["n_mahsulot"] for _k, g in qolgan_koriladigan)
            + sum(g["n_mahsulot"] for _k, g in talabsiz)
            + sum(g["n_mahsulot"] for _k, g in qaror_qilingan)
            + len(aniqmas)),
    }


# ---------------------------------------------------------------------------
# QIDIRUV — KORPUS POZITSIYALARI bo'yicha, lug'at nomlari bo'yicha EMAS
#
# NEGA TESKARI YO'NALISHDA: broker `Кульман` yoki `Трубка рентгеновская`
# degan RASMIY nomlarni tanimaydi — 26.51 misoli aynan shuni ko'rsatdi.
# Ya'ni kod nomlari bo'yicha qidiruv o'sha til devoriga uriladi.
#
# Lekin u POZITSIYA nomlarini taniydi. Shuning uchun:
#
#     broker yozadi "kabel"
#         -> atama.normal -> "kabel" -> translit variantlari
#         -> korpusda mos POZITSIYALAR
#         -> ular qaysi KOD ostida turibdi
#         -> 27.32 (38 poz: Кабель силовой, Монтажный провод...)  12 ochiq
#
# Natija — dalil ko'rinishining o'zi. Broker kod nomini o'qimaydi,
# pozitsiyalarni ko'radi va tanlaydi.
#
# BU AVTOMATIK TAKLIFDAN FARQ QILADI: tanlashni modelga emas, insonga
# qoldiradi, lekin unga TANISH material ko'rsatadi. Uch avtomatik usul
# (semantik, prefiks-leksik, korpus-pozitsiya ranglash) o'lchovda
# yiqilgan edi — bu ularning o'rniga emas, ULARDAN KEYIN turadi.
# ---------------------------------------------------------------------------
SQL_QIDIR_POZITSIYA = """
SELECT substring(g.good_code from 1 for %(uzunlik)s) AS kod,
       count(*)                                       AS n_poz,
       count(DISTINCT t.id) FILTER (
           WHERE t.status = 'open'
             AND (t.close_at IS NULL OR t.close_at > now()))  AS n_ochiq,
       (array_agg(DISTINCT g.name))[1:5]              AS namunalar
FROM tender_good g
JOIN tender t ON t.id = g.tender_id
WHERE g.good_code IS NOT NULL
  AND g.name IS NOT NULL
  AND length(g.good_code) >= %(uzunlik)s
  AND {fold} LIKE ANY(%(pats)s)
GROUP BY 1
ORDER BY n_ochiq DESC, n_poz DESC
LIMIT %(limit)s
"""

#: Kod NOMI bo'yicha qidiruv — IKKINCHI darajada. Ba'zan broker aniq
#: kodni yoki uning rasmiy nomini biladi.
SQL_QIDIR_KOD = """
SELECT d.code AS kod, d.name_ru, d.n_tender_open AS n_ochiq, d.n_position AS n_poz
FROM dim_good_code d
WHERE d.level = %(level)s
  AND (d.code LIKE %(xom)s || '%%'
       OR EXISTS (SELECT 1 FROM unnest(d.names) nm WHERE {fold} LIKE ANY(%(pats)s)))
ORDER BY d.n_tender_open DESC, d.n_position DESC
LIMIT %(limit)s
"""


def qidir(soz: str, level: int = DEFAULT_LEVEL,
          limit: int = 10) -> Dict[str, Any]:
    """Broker so'rovi -> nomzod kodlar, DALIL bilan.

    Qaytadi: {"pozitsiya": [...], "kod_nomi": [...], "kalit": ...}

    `pozitsiya` — ASOSIY natija: korpusda so'rovga mos tovar nomlari
    topiladi va ular qaysi kod ostida ekani ko'rsatiladi.
    `kod_nomi` — ikkinchi darajali: rasmiy kod nomi bo'yicha.

    KIRISH `atama.normal()` DAN O'TADI. Aks holda qidiruv YANGI til
    devorini yaratardi: broker "kommutator" yozib, korpusdagi
    "Коммутаторы" ni topa olmasdi.
    """
    from api import atama as _atama

    xom = (soz or "").strip()
    kalit = _atama.normal(xom)
    if not kalit:
        return {"kalit": "", "pozitsiya": [], "kod_nomi": []}

    # Kanonik shakl LOTINDA. Korpus esa kirillda — variantlar kerak.
    # `normal()` o'zaklashtirgani uchun "kommutator" -> "коммутатор"
    # va u "Коммутаторы" ichida ham topiladi.
    pats: List[str] = []
    for boʻlak in kalit.split():
        for v in translit.variants(boʻlak):
            if v and len(v) >= 3:
                p = f"%{v}%"
                if p not in pats:
                    pats.append(p)
    if not pats:
        return {"kalit": kalit, "pozitsiya": [], "kod_nomi": []}

    fold = translit.sql_fold("g.name")
    poz = db.query(SQL_QIDIR_POZITSIYA.format(fold=fold),
                   {"pats": pats, "uzunlik": level, "limit": limit})

    nomlar = db.query(
        SQL_QIDIR_KOD.format(fold=translit.sql_fold("nm")),
        {"pats": pats, "level": level, "xom": xom, "limit": limit})

    # Kod nomlari ro'yxatidan pozitsiya natijasida BOR kodlarni
    # olib tashlaymiz — takror ko'rsatish navbatni cho'zadi.
    bor = {r["kod"] for r in poz}
    return {
        "kalit": kalit,
        "pozitsiya": [{
            "code": r["kod"], "n_poz": r["n_poz"], "n_ochiq": r["n_ochiq"],
            "namunalar": [x for x in (r["namunalar"] or []) if x][:5],
        } for r in poz],
        "kod_nomi": [{
            "code": r["kod"], "name_ru": r["name_ru"],
            "n_ochiq": r["n_ochiq"], "n_poz": r["n_poz"],
        } for r in nomlar if r["kod"] not in bor],
    }


# ---------------------------------------------------------------------------
# QAROR O'LCHOVI — uch raqam AVTOMATIK yoziladi
#
# Vaqt, manba va qidiruv soni QO'LDA yozilmaydi: qo'lda yozilsa ular
# xotiradan tiklanadi va TAXMINGA aylanadi. Ekran ularni o'zi qayd
# etadi.
#
# Eng muhimi `qidiruv_soni`: `talabsiz` bosilganda undan OLDIN qidiruv
# qilinganmi. Qidiruvsiz "talabsiz" — avtomatik o'lchovga ishonish, va
# u xato bo'lishi O'LCHANGAN (`turniket` avtomatik o'lchovda talabsiz
# edi, qidiruv 26.30 "Турникет" ni topdi).
# ---------------------------------------------------------------------------
def qaror_ochish(company_id: int, kalit: str, atama: str) -> Dict[str, Any]:
    """Atama ko'rib chiqishga OCHILDI — vaqt hisobi shu yerdan boshlanadi.

    Ochiq qator allaqachon bo'lsa YANGI YARATILMAYDI (qisman unikal
    indeks buni majburlaydi), aks holda `qidiruv_soni` bo'linib
    ketardi.
    """
    # `ochilgan_at` ANIQ yoziladi. Ustunning DEFAULT i ataylab olib
    # tashlangan (schema_patch_kod_qaror_2.sql): NULL endi "o'lchanmadi"
    # degani va uni faqat SHU funksiya to'ldiradi. Aks holda har qanday
    # INSERT jimgina `now()` qo'yib, o'tgan vaqtni 0 qilardi.
    row = db.execute_returning(
        "INSERT INTO kod_qaror (company_id, kalit, atama, ochilgan_at) "
        "VALUES (%(c)s, %(k)s, %(a)s, now()) "
        "ON CONFLICT (company_id, kalit) WHERE qaror IS NULL "
        "  DO UPDATE SET atama = EXCLUDED.atama "
        "RETURNING id, ochilgan_at, qidiruv_soni",
        {"c": company_id, "k": kalit, "a": atama})
    return row or {}


def qaror_qidiruv(company_id: int, kalit: str,
                  soz: Optional[str] = None) -> int:
    """Qidiruv qilindi — sanoqni oshiradi. Qaytadi: yangi son.

    `soz` ham saqlanadi: `qidiruv_soni` "nechta marta qidirdi" deydi,
    `qidiruv_sozi` esa "NIMANI qidirdi". Ikkinchisisiz qaror sababini
    keyin tiklab bo'lmaydi — "turniket" deb qidirib 26.30 ni topgan
    inson bilan hech nima qidirmagan inson bir xil ko'rinardi.
    """
    row = db.execute_returning(
        "UPDATE kod_qaror SET qidiruv_soni = qidiruv_soni + 1, "
        "       qidiruv_sozi = COALESCE(NULLIF(btrim(%(s)s), ''), qidiruv_sozi) "
        "WHERE company_id = %(c)s AND kalit = %(k)s AND qaror IS NULL "
        "RETURNING qidiruv_soni",
        {"c": company_id, "k": kalit, "s": soz})
    return (row or {}).get("qidiruv_soni") or 0


#: Ruxsat etilgan qaror turlari. Baza CHECK i bilan AYNAN mos
#: bo'lishi shart (`kod_qaror_turi`) — ikki joyda ikki lug'at
#: bo'lsa biri jimgina eskiradi.
QARORLAR = ("kod", "talabsiz", "dalilsiz", "otkazildi")

#: `dalil` JSON ning yuqori chegarasi (bayt). Chegara bor, chunki
#: mijoz istalgan hajmni yuborishi mumkin va `kod_qaror` har qaror
#: uchun bitta qator — cheksiz JSON jadvalni shishirardi.
DALIL_MAX = 64 * 1024


def qaror_yoz(company_id: int, kalit: str, atama: str, qaror: str,
              kim: str, code: Optional[str] = None,
              manba: Optional[str] = None,
              dalil: Optional[Dict[str, Any]] = None,
              taklif_code: Optional[str] = None,
              taklif_skor: Optional[float] = None,
              rad_takliflar: Optional[Sequence[str]] = None,
              qoshimcha_kod: bool = False,
              izoh: Optional[str] = None, *,
              actor_id: Optional[int] = None,
              ishonch: Optional[str] = None) -> Dict[str, Any]:
    """INSON qarorini yozadi. `qaror`: kod | talabsiz | dalilsiz | otkazildi.

    Ochiq qator bo'lsa u YAKUNLANADI (vaqt va qidiruv soni saqlanadi).
    Bo'lmasa — YANGI yakunlangan qator (bir atamaga IKKINCHI kod
    berilgan holat; `UNIQUE(kalit)` ataylab yo'q).

    ZAXIRA YO'LDA `ochilgan_at` NULL QOLADI — ya'ni "O'LCHANMADI".
    Ilgari ustunda `DEFAULT now()` bor edi va bu qator
    `ochilgan_at = qaror_at` bo'lib "0 soniya ketdi" deb o'qilardi.
    O'lchandi: uchta sinov qarordan keyin `ortacha_sek = 0` chiqdi,
    holbuki hech qaysi qarorning vaqti o'lchanmagan edi. Nol —
    o'lchov, NULL — o'lchov yo'qligi; ikkisi aralashmasin.

    DALIL NEGA SAQLANADI: qarorning o'zi ML uchun YETARLI EMAS.
    "Кабель -> 27.32" degan yorliq, inson NIMA KO'RIB shunday
    deganini bilmasdan, o'rgatish uchun yaroqsiz. `dalil` ekranda
    ko'rsatilgan takliflar, qidiruv natijasi va korpus raqamlarini
    saqlaydi.
    """
    if not (kim or "").strip():
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "kim"})
    # `kim` — KOMPANIYA login'i (sessiyadan). U "qaysi odam" degan
    # savolga javob bermaydi, shuning uchun aktor va uning ishonch
    # darajasi ALOHIDA yoziladi.
    if ishonch not in ("erp_sessiya", "aktor_elon", "kompaniya_sessiyasi"):
        raise xatolar.Xato("TRUST_LEVEL_INVALID", {"ishonch": ishonch})
    if ishonch in ("erp_sessiya", "aktor_elon") and not actor_id:
        raise xatolar.Xato("ACTOR_REQUIRED_FOR_TRUST", {"ishonch": ishonch})
    if qaror not in QARORLAR:
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "qaror", "qiymat": qaror})

    # BO'SH KODNI TASODIFAN TASDIQLASH — ANIQ XATO BERADI.
    # Baza ham to'sadi (`kod_qaror_kod_mos` + `kod_qaror_code_bosh_emas`
    # + FK), lekin u yerdan kelgan xabar brokerga tushunarsiz bo'lardi.
    code = (code or "").strip() or None
    if qaror == "kod" and not code:
        raise xatolar.Xato("CODE_REQUIRED")
    if qaror != "kod" and code:
        raise xatolar.Xato("CODE_NOT_ALLOWED", {"qaror": qaror})
    if qoshimcha_kod and qaror != "kod":
        raise xatolar.Xato("CODE_NOT_ALLOWED", {"qaror": qaror})

    taklif_code = (taklif_code or "").strip() or None
    if taklif_skor is not None and taklif_code is None:
        taklif_skor = None

    rad = [str(x).strip() for x in (rad_takliflar or []) if str(x).strip()]
    # Tanlangan kod "rad etilgan" ro'yxatida turmasin — o'qib
    # bo'lmaydigan qator bo'lardi.
    rad = sorted({x for x in rad if x != code}) or None

    d_json = None
    if dalil is not None:
        matn = json.dumps(dalil, ensure_ascii=False)
        if len(matn.encode("utf-8")) > DALIL_MAX:
            # KESMAYMIZ va JIMGINA TASHLAMAYMIZ: yarim dalil to'liq
            # dalildek ko'rinardi. Aniq xato — mijoz kichraytirsin.
            raise xatolar.Xato("EVIDENCE_TOO_LARGE",
                               {"belgi": len(matn), "chegara": DALIL_MAX})
        d_json = matn

    umumiy = {"c": company_id, "k": kalit, "a": atama, "q": qaror,
              "kod": code, "m": manba, "kim": kim.strip(),
              "d": d_json, "tc": taklif_code, "ts": taklif_skor,
              "rad": rad, "qk": bool(qoshimcha_kod),
              "izoh": (izoh or "").strip()[:1000] or None,
              "actor_id": actor_id, "ishonch": ishonch}

    row = db.execute_returning(
        "UPDATE kod_qaror SET qaror=%(q)s, code=%(kod)s, manba=%(m)s, "
        "       kim=%(kim)s, qaror_at=now(), dalil=%(d)s::jsonb, "
        "       taklif_code=%(tc)s, taklif_skor=%(ts)s, "
        "       rad_takliflar=%(rad)s, qoshimcha_kod=%(qk)s, izoh=%(izoh)s, "
        "       actor_id=%(actor_id)s, ishonch=%(ishonch)s "
        "WHERE company_id=%(c)s AND kalit=%(k)s AND qaror IS NULL "
        "RETURNING id, ochilgan_at, qaror_at, qidiruv_soni, qidiruv_sozi",
        umumiy)
    if row:
        return row
    return db.execute_returning(
        "INSERT INTO kod_qaror (company_id, kalit, atama, qaror, code, "
        "                       manba, kim, qaror_at, dalil, taklif_code, "
        "                       taklif_skor, rad_takliflar, qoshimcha_kod, izoh, "
        "                       actor_id, ishonch) "
        "VALUES (%(c)s, %(k)s, %(a)s, %(q)s, %(kod)s, %(m)s, %(kim)s, now(), "
        "        %(d)s::jsonb, %(tc)s, %(ts)s, %(rad)s, %(qk)s, %(izoh)s, "
        "        %(actor_id)s, %(ishonch)s) "
        "RETURNING id, ochilgan_at, qaror_at, qidiruv_soni, qidiruv_sozi",
        umumiy) or {}


def atamaga_kod_biriktir(company_id: int, kalit: str, code: str,
                         kim: str, qaror_id: Optional[int] = None, *,
                         ishonch: str, actor_id: Optional[int] = None) -> int:
    """Kalitga tegishli MAHSULOTLARGA kodni biriktiradi. Qaytadi: soni.

    `qaror_id` — AUDIT IZI: bu biriktirma QAYSI inson qaroridan
    kelgani. Ilgari `catalog_product_code` da faqat `tasdiqlagan`
    (ism) bor edi va "bu kod qayerdan keldi" degan savolga javob
    yo'q edi — mavjud 960 qator aynan shu holatda
    (`tasdiqlagan='kompaniya'`, ya'ni na foydalanuvchi, na skript).

    Qaror darhol kuchga kirsin — broker natijani o'sha yurishda
    ko'rsin, keyingi ETL ni kutmasin.

    Mahsulot kaliti `navbat()` dagi bilan AYNAN bir xil hisoblanadi
    (`keywords[1]` yoki `keywords[0]` yoki nom). Ikki joyda ikki xil
    hisoblansa, qaror boshqa mahsulotlarga tushardi.
    """
    from api import atama as _atama

    prods = db.query(
        "SELECT id, name, keywords FROM catalog_product "
        "WHERE company_id = %(c)s", {"c": company_id})
    n = 0
    for p in prods:
        kws = list(p["keywords"] or [])
        xom = ((kws[1] if len(kws) >= 2 else (kws[0] if kws else p["name"]))
               or "").strip()
        if not xom or len(xom) > _TUR_MAX_LEN:
            continue
        if _atama.normal(xom) != kalit:
            continue
        taklif_yoz(company_id, p["id"], [{"code": code, "skor": None}])
        if tasdiqla(company_id, p["id"], code, kim=kim, qaror_id=qaror_id,
                    ishonch=ishonch, actor_id=actor_id):
            n += 1
    return n


def qaror_olchov(company_id: int) -> Dict[str, Any]:
    """Pilot o'lchovi — FAQAT haqiqiy inson harakatidan hisoblanadi.

    `v_kod_qaror_olchov` da har raqam `qaror IS NOT NULL` sharti
    ostida: ochilgan-u qaror qilinmagan qator hech qayerda
    sanalmaydi. Aynan shu chalkashlik 2026-08-30 da "40 qaror"
    degan soxta raqam bergan edi (aslida 40 ta RENDER).
    """
    return db.query_one(
        "SELECT * FROM v_kod_qaror_olchov WHERE company_id = %(c)s",
        {"c": company_id}) or {}


def pilot_holati(company_id: int) -> Dict[str, Any]:
    """40 ta ATAMA qaroriga qancha qolgani.

    MAQSAD ATAMA BO'YICHA, qator bo'yicha EMAS: bir atamaga ikkinchi
    kod berish ikki qator yaratadi va qator bo'yicha sanash maqsadni
    SOXTA yaqinlashtirardi.
    """
    return db.query_one(
        "SELECT * FROM v_kod_pilot WHERE company_id = %(c)s",
        {"c": company_id}) or {}


def qaror_tafsil(company_id: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Har qaror dalili bilan — ML to'plamining XOM manbai.

    Hech qanday qoida qo'llanmaydi va qo'llanmasligi kerak: birinchi
    40 qarorning maqsadi O'LCHASH, qoida chiqarish EMAS.
    """
    return db.query(
        "SELECT * FROM v_kod_qaror_tafsil WHERE company_id = %(c)s "
        "ORDER BY qaror_at DESC LIMIT %(l)s",
        {"c": company_id, "l": limit})


def qarorlar(company_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """Qabul qilingan qarorlar — ekranda qaysi atama bajarilganini
    ko'rsatish uchun."""
    return db.query(
        "SELECT kalit, atama, qaror, code, manba, qidiruv_soni, qidiruv_sozi, "
        "       taklif_code, qoshimcha_kod, rad_takliflar, "
        "       (dalil IS NOT NULL) AS dalil_bor, qaror_at "
        "FROM kod_qaror WHERE company_id = %(c)s AND qaror IS NOT NULL "
        "ORDER BY qaror_at DESC LIMIT %(l)s",
        {"c": company_id, "l": limit})


def kodsiz_mahsulotlar(company_id: int) -> List[Dict[str, Any]]:
    """Tasdiqlangan kodi YO'Q mahsulotlar — moslashtirishda ko'rinmaydi."""
    return db.query(
        "SELECT product_id, name, kutayotgan_taklif FROM v_catalog_kodsiz "
        "WHERE company_id = %(c)s ORDER BY name", {"c": company_id})


def holat(company_id: int) -> Dict[str, Any]:
    """Kodlash holati — interfeys va sinov uchun bitta manba."""
    row = db.query_one(
        "SELECT (SELECT count(*) FROM catalog_product WHERE company_id=%(c)s) AS mahsulot,"
        "       (SELECT count(DISTINCT product_id) FROM v_catalog_code_active"
        "         WHERE company_id=%(c)s) AS kodlangan,"
        "       (SELECT count(*) FROM v_code_review WHERE company_id=%(c)s) AS kutayotgan",
        {"c": company_id}) or {}
    mahsulot = row.get("mahsulot") or 0
    kodlangan = row.get("kodlangan") or 0
    return {
        "mahsulot": mahsulot,
        "kodlangan": kodlangan,
        "kodsiz": mahsulot - kodlangan,
        "kutayotgan_taklif": row.get("kutayotgan") or 0,
        # Qamrov FOIZI — bu HALOL foiz, chunki maxraj aniq (jami mahsulot).
        "qamrov_pct": round(kodlangan / mahsulot * 100, 1) if mahsulot else None,
    }
