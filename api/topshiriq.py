"""
ERP GA TOPSHIRIQ — "olindi" qarori ishga aylanadigan joy
========================================================

Broker navbatda "Olindi" deydi. Shu paytgacha zanjir shu yerda
UZILARDI: ERP kartani qo'lda ochishi kerak edi — tenderni qidiradi,
mijozni tanlaydi, muddatni ko'chiradi. Ya'ni qaror bu tomonda, ish esa
u tomonda va ikkalasi orasida ODAM turardi.

Endi qaror `tender_topshiriq` ga yoziladi, ERP esa `v_erp_topshiriq`
dan o'qiydi (`schema_patch_topshiriq.sql`). HTTP yo'q, service kaliti
yo'q: baza bitta, har tomon o'z jadvaliga yozadi.

TAHLIL — SNAPSHOT
═════════════════
`tahlil` JSONB qaror PAYTIDA hisoblanadi va keyin o'zgarmaydi. ERP uni
qayta hisoblamaydi va hisoblay olmaydi ham: qoidalar (moslik, malaka,
cheklist, ombor mosligi) shu tomonda va ularning IKKINCHI NUSXASI
BO'LMASLIGI kerak.

Sabab loyihada takrorlanadi: faktura rekvizitlari, karta snapshoti —
hujjat chiqarilgandan keyin manba o'zgarsa, hujjat o'zgarmaydi.

YIQILGAN QISM YASHIRILMAYDI
═══════════════════════════
Har bo'lim alohida `try` ichida. Model javob bermasa yoki jadval
bo'lmasa — o'sha bo'lim `{"ok": false, "xato": "..."}` bo'lib yoziladi,
qolganlari yoziladi. ERP kartada shuni ochiq ko'rsatadi.

Muqobili yomon bo'lardi: bitta bo'lim yiqilgani uchun butun topshiriqni
bermaslik ("hech narsa yo'q") yoki uni jimgina tashlab ketish ("hammasi
joyida, lekin ombor bo'limi yo'q" — nega yo'qligi noma'lum).

O'LCHAM CHEGARASI
═════════════════
`tahlil` — hisobot emas, XULOSA. Uzun ro'yxatlar kesiladi (`_kes`) va
umumiy hajm `MAX_BAYT` bilan cheklanadi: JSONB ni cheksiz o'stirish
bazani ham, ERP ekranini ham foydasiz qiladi.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict, List, Optional

from api import db, xatolar

#: Ro'yxatlarda saqlanadigan eng ko'p element.
MAX_QATOR = 25

#: Butun `tahlil` uchun taxminiy chegara (bayt). Oshsa — og'ir
#: bo'limlar tashlanadi va sababi yoziladi.
MAX_BAYT = 60_000

#: Og'irlik tartibi: chegaradan oshganda OXIRGISI birinchi tashlanadi.
#: Eng qimmatlisi boshida — broker kartani ochganda avval nimani
#: ko'rishi kerakligiga qarab.
BOLIMLAR_TARTIBI = ("moslik", "ai", "malaka", "talablar", "cheklist",
                    "ombor", "narx", "havolalar")

USTUVORLIKLAR = ("low", "medium", "high")


def ready() -> bool:
    """Jadval va view qo'llanganmi (`schema_patch_topshiriq.sql`).

    Yo'q bo'lsa modul JIMGINA o'chadi va yo'naltirish avvalgidek
    ishlayveradi — bu loyihadagi `erp_status.ready()` naqshi."""
    return bool(db.scalar(
        "SELECT to_regclass('public.tender_topshiriq') IS NOT NULL"))


# ---------------------------------------------------------------------------
# TAHLIL SNAPSHOTI
# ---------------------------------------------------------------------------
def _kes(v: Any, n: int = MAX_QATOR) -> Any:
    """Uzun ro'yxatni kesadi va nechtasi qolganini AYTADI."""
    if isinstance(v, list) and len(v) > n:
        return v[:n] + [{"_qolgan": len(v) - n}]
    return v


def _qism(nom: str, fn) -> Dict[str, Any]:
    """Bitta bo'limni hisoblaydi. Yiqilsa — sababi bilan yoziladi."""
    try:
        return {"ok": True, "data": fn()}
    except Exception as e:                      # noqa: BLE001
        # Turi ham yoziladi: "TENDER_NOT_FOUND" bilan "ulanish uzildi"
        # ERP uchun ikki xil xabar.
        return {"ok": False, "xato": f"{type(e).__name__}: {e}"[:300]}


def _moslik(routing: Dict[str, Any]) -> Dict[str, Any]:
    """Moslik balli — QARORDAGI qiymat, qayta hisoblanmaydi.

    `tender_routing` da u allaqachon saqlangan (AI shu asosda qaror
    qilgan). Qayta hisoblash boshqa raqam berishi mumkin edi va
    "AI nimaga qarab qaror qilgan" degan savol javobsiz qolardi."""
    return {"ball": float(routing.get("ai_ball") or 0),
            "manba": routing.get("ai_manba"),
            "sabab": routing.get("ai_sabab")}


def _ai(routing: Dict[str, Any]) -> Dict[str, Any]:
    return {"qaror": routing.get("ai_qaror"),
            "qaror_eski": routing.get("ai_qaror_eski"),
            "ozgardi": bool(routing.get("ai_ozgardi"))}


def _malaka(tender_id: int, company_id: int) -> Dict[str, Any]:
    from api import qualification
    r = qualification.check(tender_id, company_id)
    return {"qaror": r.get("qaror"), "sabab": r.get("sabab"),
            "mezonlar": _kes([{"key": m.get("key"), "label": m.get("label"),
                               "status": m.get("status"),
                               "izoh": m.get("izoh")}
                              for m in (r.get("mezonlar") or [])])}


def _talablar(tender_id: int, company_id: int) -> Dict[str, Any]:
    from api import requirement
    xulosa = requirement.summary(tender_id, company_id)
    # Talablarning O'ZI ham kerak: broker kartada "nima talab
    # qilinadi" degan savolga javob ko'rishi kerak. Iqtibos
    # (`file_ref`, `char_start`) ham olinadi — dalilsiz talab
    # "kimdir shunday deb o'ylabdi" degani.
    royxat = [{"tur": r.get("kind") or r.get("tur"),
               "matn": (r.get("name") or r.get("matn") or "")[:300],
               "holat": r.get("review_status"),
               "mashina_holat": r.get("mashina_holat"),
               "file_ref": r.get("file_ref"),
               "char_start": r.get("char_start")}
              for r in requirement.list_for(tender_id, company_id)]
    return {"xulosa": xulosa, "royxat": _kes(royxat)}


def _cheklist(tender_id: int, company_id: int) -> Dict[str, Any]:
    from api import compliance
    r = compliance.check(tender_id, company_id=company_id)
    return {"xulosa": r.get("summary"),
            "yetishmayotgan": _kes(r.get("missing") or []),
            "manba": "kompaniya"}


def _ombor(tender_id: int, company_id: int) -> Dict[str, Any]:
    from api import stock
    r = stock.check_tender_stock(tender_id, company_id)
    if not r:
        return {"holat": "hisoblanmadi"}
    return {"xulosa": r.get("summary") or r.get("xulosa"),
            "yetishmovchilik": _kes(r.get("shortages")
                                    or r.get("yetishmovchilik") or [])}


def _narx(tender_id: int, company_id: int) -> Dict[str, Any]:
    """SAQLANGAN smeta. Hisoblanmagan bo'lsa — bu XATO EMAS.

    Formula `api/pricing.py` da va u QAYTA hisoblanmaydi: taklif
    paketiga natijaning NUSXASI qo'yiladi (ERP dagi bilan bir xil
    qoida)."""
    r = db.query_one("SELECT * FROM tender_pricing "
                     "WHERE tender_id = %(t)s AND company_id = %(c)s",
                     {"t": tender_id, "c": company_id})
    if not r:
        return {"holat": "hisoblanmagan"}
    natija = r.get("result") or {}
    if isinstance(natija, str):                 # jsonb matn ko'rinishida kelsa
        try:
            natija = json.loads(natija)
        except ValueError:
            natija = {}
    return {"tavsiya_narx": (r.get("manual_price")
                             or natija.get("recommended_price")
                             or natija.get("narx")),
            "qolda_qoyilgan": r.get("manual_price") is not None,
            "valyuta": r.get("currency"),
            "marja": natija.get("margin") or natija.get("marja"),
            "hisoblangan_at": r.get("updated_at")}


def _havolalar(tender_id: int) -> Dict[str, Any]:
    """Manba havolasi BAZADAN, ilova havolasi esa faqat OMMAVIY bo'lsa.

    `localhost` manzili ERP kartasiga yozilmaydi: u boshqa
    kompyuterda ochilmaydi va "havola buzuq" degan taassurot
    qoldirardi (`api/ommaviy_url.py` qoidasi)."""
    from api import ommaviy_url
    manba = db.query_one("SELECT * FROM v_tender_manba WHERE ichki_id = %(t)s",
                         {"t": tender_id}) or {}
    out: Dict[str, Any] = {"manba_url": manba.get("manba_url")
                           or manba.get("url")}
    base, _ = ommaviy_url.sozlangan()
    if base and not ommaviy_url.mahalliymi(base):
        out["tender_ai_url"] = f"{base.rstrip('/')}/?tender={tender_id}"
    else:
        out["tender_ai_url"] = None
        out["tender_ai_url_sababi"] = "APP_PUBLIC_URL mahalliy yoki sozlanmagan"
    return out


def tahlil_yig(tender_id: int, company_id: int,
               routing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Qaror paytidagi butun tahlil — bitta JSON.

    Har bo'lim alohida hisoblanadi va yiqilsa qolganini to'xtatmaydi.
    """
    routing = routing or {}
    t = {
        "moslik": _qism("moslik", lambda: _moslik(routing)),
        "ai": _qism("ai", lambda: _ai(routing)),
        "malaka": _qism("malaka", lambda: _malaka(tender_id, company_id)),
        "talablar": _qism("talablar", lambda: _talablar(tender_id, company_id)),
        "cheklist": _qism("cheklist", lambda: _cheklist(tender_id, company_id)),
        "ombor": _qism("ombor", lambda: _ombor(tender_id, company_id)),
        "narx": _qism("narx", lambda: _narx(tender_id, company_id)),
        "havolalar": _qism("havolalar", lambda: _havolalar(tender_id)),
        "olingan_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "versiya": 1,
    }
    return _sigdir(t)


def _sigdir(t: Dict[str, Any]) -> Dict[str, Any]:
    """Hajm chegarasi. Oshsa — OXIRIDAN boshlab bo'lim tashlanadi.

    Tashlangani JIM QOLMAYDI: o'rniga sabab yoziladi, ya'ni ERP
    kartada "ombor bo'limi hajm sababli tushib qoldi" deb ko'rsata
    oladi."""
    while len(json.dumps(t, default=str).encode("utf-8")) > MAX_BAYT:
        ogir = [b for b in reversed(BOLIMLAR_TARTIBI)
                if isinstance(t.get(b), dict) and t[b].get("ok")]
        if not ogir:
            break
        t[ogir[0]] = {"ok": False, "xato": "hajm chegarasi (MAX_BAYT)"}
    return t


# ---------------------------------------------------------------------------
# YOZISH
# ---------------------------------------------------------------------------
YARAT_SQL = """
INSERT INTO tender_topshiriq
    (company_id, routing_id, tender_id, hodim_actor_id, yonaltirgan_actor_id,
     ishonch, ustuvorlik, izoh, muddat, tahlil)
VALUES (%(c)s, %(r)s, %(t)s, %(h)s, %(y)s, %(i)s, %(u)s, %(izoh)s, %(m)s,
        %(tahlil)s::jsonb)
ON CONFLICT (routing_id) DO UPDATE
   SET hodim_actor_id = EXCLUDED.hodim_actor_id,
       yonaltirgan_actor_id = EXCLUDED.yonaltirgan_actor_id,
       ishonch    = EXCLUDED.ishonch,
       ustuvorlik = EXCLUDED.ustuvorlik,
       izoh       = EXCLUDED.izoh,
       muddat     = EXCLUDED.muddat,
       tahlil     = EXCLUDED.tahlil,
       -- Qayta "olindi" — BEKORNI ORQAGA QAYTARADI: broker fikridan
       -- qaytgan bo'lsa ERP kartasi ham tirilishi kerak.
       bekor_at   = NULL
RETURNING id, routing_id, tender_id, hodim_actor_id, ishonch, ustuvorlik,
          muddat, yaratilgan_at, bekor_at
"""

BEKOR_SQL = """
UPDATE tender_topshiriq
   SET bekor_at = now()
 WHERE routing_id = %(r)s AND company_id = %(c)s AND bekor_at IS NULL
RETURNING id, routing_id, tender_id, bekor_at
"""


def yarat(routing_id: int, company_id: int, tender_id: int, *,
          hodim_actor_id: Optional[int],
          yonaltirgan_actor_id: Optional[int],
          ishonch: str,
          ustuvorlik: str = "medium",
          izoh: Optional[str] = None,
          muddat: Optional[Any] = None,
          tahlil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Topshiriqni yozadi (va tahlil snapshotini yig'adi).

    QAYTA CHAQIRILSA — YANGILANADI (`ON CONFLICT`). Bu "tahlilni
    yangilash" tugmasi uchun: qaror bitta, tahlil esa eskirishi
    mumkin. ERP eng yangisini ko'rsatadi.
    """
    if ustuvorlik not in USTUVORLIKLAR:
        raise xatolar.Xato("INVALID_ENUM",
                           {"maydon": "ustuvorlik", "qiymat": ustuvorlik})
    if not ready():
        raise xatolar.Xato("MIGRATION_MISSING",
                           {"patch": "schema_patch_topshiriq.sql"})
    if tahlil is None:
        r = db.query_one(
            "SELECT ai_qaror, ai_qaror_eski, ai_ozgardi, ai_ball, ai_manba, "
            "ai_sabab FROM tender_routing WHERE id = %(id)s", {"id": routing_id})
        tahlil = tahlil_yig(tender_id, company_id, r or {})
    return db.execute_returning(YARAT_SQL, {
        "c": company_id, "r": routing_id, "t": tender_id,
        "h": hodim_actor_id, "y": yonaltirgan_actor_id, "i": ishonch,
        "u": ustuvorlik, "izoh": (izoh or "").strip()[:2000] or None,
        "m": muddat, "tahlil": json.dumps(tahlil, default=str)})


def bekor(routing_id: int, company_id: int) -> Optional[Dict[str, Any]]:
    """Qaror `olindi` dan qaytarilganda topshiriq BEKOR qilinadi.

    Yozuv o'chirilmaydi va ERP kartasi ham o'chmaydi: u `rejected`
    ga o'tadi va tarixda sabab qoladi. "Yo'q bo'lib qolgan karta"
    eng yomon variant bo'lardi."""
    if not ready():
        return None
    return db.execute_returning(BEKOR_SQL, {"r": routing_id, "c": company_id})


def bitta(routing_id: int, company_id: int) -> Optional[Dict[str, Any]]:
    """Qaror bo'yicha topshiriq (interfeys uchun)."""
    if not ready():
        return None
    return db.query_one(
        "SELECT * FROM v_erp_topshiriq WHERE routing_id = %(r)s "
        "AND company_id = %(c)s", {"r": routing_id, "c": company_id})


def royxat(company_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    if not ready():
        return []
    return db.query(
        "SELECT id, routing_id, tender_id, hodim_app_user_id, hodim_ism, "
        "ustuvorlik, muddat, yaratilgan_at, bekor_at "
        "FROM v_erp_topshiriq WHERE company_id = %(c)s "
        "ORDER BY yaratilgan_at DESC LIMIT %(l)s",
        {"c": company_id, "l": max(1, min(limit, 200))})
