"""
ERP HOLATI — "shu tender ishga olinganmi?"

Bu tender-ai ning ERP ga YAGONA murojaati va u FAQAT O'QISH.

NEGA BOR: tender panelidagi `ErpLink` bloki foydalanuvchiga "bu tender
allaqachon ishga olingan, mas'ul — Karimov" deb aytadi. Ma'lumot ERP niki
(odamlar ham, kartalar ham u yerda).

NEGA HTTP EMAS: ilgari buni BRAUZER so'rardi — `ErpLink` to'g'ridan-to'g'ri
ERP backendiga borardi. Shuning uchun ERP ning o'sha endpointi OCHIQ
qolishga majbur edi: brauzer server-server kalitini ushlab turolmaydi
(kalit JS to'plamiga tushib qolardi). Endi so'rovni SERVER qiladi va ERP
endpointi yopildi.

NEGA `erp.opportunity` EMAS, `erp.v_tender_status`: bu ATAYLAB SHARTNOMA.
Biz ERP ning jadval ustunlariga emas, u kafolatlagan view ga bog'lanamiz.
ERP ichida ustun nomi o'zgarsa yoki jadval bo'linsa — view moslashtiriladi
va bu fayl o'zgarmaydi. View ERP tomonida yaratiladi:
`tender erp/schema_patch_erp_7.sql`.

CHEGARA SIMMETRIK:
    ERP        `public.*` dan O'QIYDI (tender snapshoti), YOZMAYDI.
    Tender-AI  `erp.v_tender_status` dan O'QIYDI, YOZMAYDI.
Ikkala loyihaning sinovi ham har yurishda buni tekshiradi.

ERP O'RNATILMAGAN bo'lsa (view yo'q) — bu XATO EMAS: `ready()` False
qaytaradi, endpoint bo'sh ro'yxat beradi va interfeys blokni umuman
ko'rsatmaydi. Tender paneli ERP tufayli buzilmasligi kerak.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from api import db

log = logging.getLogger(__name__)

VIEW_SQL = """
SELECT opportunity_id, tender_id, status, status_label, priority,
       broker_name, client_name, created_at, updated_at
FROM erp.v_tender_status
WHERE tender_id = %(tender_id)s
ORDER BY opportunity_id
"""

READY_SQL = """
SELECT 1 AS x FROM information_schema.views
WHERE table_schema = 'erp' AND table_name = 'v_tender_status'
"""

#: Bir marta tekshiriladi: view paydo bo'lgach o'chib qolmaydi va har
#: so'rovda `information_schema` ga bormaymiz.
_READY: bool = False


def ready() -> bool:
    global _READY
    if _READY:
        return True
    _READY = bool(db.query_one(READY_SQL))
    return _READY


def _iso(v):
    return v.isoformat() if v is not None else None


#: Shartnoma-view IJARACHINI ko'rsatadimi.
#:
#: `erp.v_tender_status` da `tai_company_id` YO'Q (2026-09-03 da
#: o'lchandi). Ya'ni bu yerdan ijarachi bo'yicha FILTRLAB BO'LMAYDI —
#: view qaysi ijarachiga tegishli ekanini umuman aytmaydi.
_IJARACHILI: bool = False
_IJARACHILI_TEKSHIRILDI: bool = False


def ijarachili() -> bool:
    """Shartnoma-view `tai_company_id` ni chop etadimi."""
    global _IJARACHILI, _IJARACHILI_TEKSHIRILDI
    if _IJARACHILI_TEKSHIRILDI:
        return _IJARACHILI
    _IJARACHILI = bool(db.query_one(
        "SELECT 1 AS x FROM information_schema.columns "
        " WHERE table_schema = 'erp' AND table_name = 'v_tender_status' "
        "   AND column_name = 'tai_company_id'"))
    _IJARACHILI_TEKSHIRILDI = True
    return _IJARACHILI


def for_tender(tender_id: int,
               company_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Shu tender bo'yicha ERP kartalari. ERP yo'q bo'lsa — bo'sh ro'yxat.

    IJARACHI AJRATILISHI — OCHIQ CHEGARA (2026-09-03 da o'lchandi).
    `erp.v_tender_status` `tai_company_id` ni chop ETMAYDI, shuning
    uchun bu yerdan ijarachi bo'yicha filtrlab bo'lmaydi. Bitta
    tender bir necha ijarachida ishga olinishi mumkin va o'shanda
    A ijarachisi B ning kartasini (broker, mijoz, holat) KO'RARDI.
    Bu FK bilan to'silmaydi: FK yozishni to'sadi, o'qishni emas.

    Bugun zarar yo'q — faol ijarachi BITTA. Lekin "bugun bitta" —
    kafolat emas, holat. Shuning uchun qoida qat'iy:

        faol ijarachi > 1  VA  view da `tai_company_id` yo'q
        -> BO'SH RO'YXAT + jurnalga ogohlantirish

    Ya'ni jimgina sizish o'rniga BLOK ko'rinmay qoladi. "Ma'lumot
    yo'q" — halol; "boshqa kompaniyaning ma'lumoti" — emas.

    To'liq yechim ERP TOMONIDA: `v_tender_status` ga `tai_company_id`
    qo'shilsin (`docs/erp_integratsiya_2.md` shartnomasi).
    """
    if not ready():
        return []

    if not ijarachili():
        # TO'QNASHUV SHARTI ANIQ BO'LSIN, "ijarachi ko'p" EMAS.
        #
        # Birinchi urinishda shart "faol ijarachi > 1" edi va u JUDA
        # QO'POL chiqdi: `auth_test` o'z sinov hisobini yaratadi,
        # ya'ni har sinov yurishida ijarachi 2 ta bo'lardi va karta
        # bloklanardi. O'lchandi — to'plam 132 emas, 74 tekshiruvda
        # uzildi.
        #
        # HAQIQIY to'qnashuv sharti boshqa: shu TENDERNI BOSHQA
        # ijarachi ham ERP ga topshirganmi. Buni O'Z ma'lumotimizdan
        # bilamiz — `tender_topshiriq` aynan shuni yozadi. Boshqa
        # ijarachi topshirmagan bo'lsa, ERP dagi karta boshqasiniki
        # bo'lishi mumkin emas.
        begona = db.scalar(
            "SELECT count(*) FROM tender_topshiriq "
            " WHERE tender_id = %(t)s "
            "   AND bekor_at IS NULL "
            "   AND (%(c)s IS NULL OR company_id <> %(c)s)",
            {"t": tender_id, "c": company_id}) or 0
        if begona:
            log.warning(
                "tender %s: `erp.v_tender_status` da `tai_company_id` "
                "yo'q, lekin bu tenderni %s ta BOSHQA ijarachi ham "
                "topshirgan — ERP kartalari KO'RSATILMAYDI "
                "(ijarachilararo sizish xavfi).", tender_id, begona)
            return []
    return [{
        "opportunity_id": r["opportunity_id"],
        "status": r["status"],
        "status_label": r["status_label"],
        "priority": r["priority"],
        "broker_name": r["broker_name"],
        "client_name": r["client_name"],
        "created_at": _iso(r["created_at"]),
    } for r in db.query(VIEW_SQL, {"tender_id": tender_id})]
