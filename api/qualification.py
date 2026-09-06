"""
MALAKA TEKSHIRUVI — kompaniya tender talabiga mos keladimi?
===========================================================

`ai_gonogo.py` DAN FARQI: u 11 mezonni PULLIK modelga nasr sifatida
beradi. Bu modul o'sha taqqoslashning DETERMINISTIK qismini bajaradi —
model chaqirmasdan, xarajatsiz, takrorlanadigan.

NEGA MUMKIN: ikkala tomon ham allaqachon STRUKTURALI.

    tender tomoni    `tender_requirement.attrs->>'tur'`
                     sertifikat 1347, moliyaviy 524, tolov 257,
                     bazis 149, kafolat 134, muddat 54
    kompaniya tomoni `company_profile`
                     certificates[], clearances[], experience_years,
                     max_contract_value, employees, lead_time_days,
                     min_margin_percent, regions[]

Yetishmagani — ULARNI BIRLASHTIRISH edi. `ai_gonogo._facts()` kompaniya
qiymatlarini faqat CHOP ETADI, talab bilan solishtirmaydi; solishtirish
Opus ga topshirilgan.


UCHTA QOIDA — buzilsa natija yolg'on bo'ladi
════════════════════════════════════════════

1. `is_mandatory` GA HECH QACHON TAYANMAYMIZ.
   Bazadagi 4 708 qatordan 4 708 tasi `False`. Bu xato emas, ataylab:
   naqsh "shart" bilan "mumkin" ni ajrata olmaydi, ajratadigan LLM
   qatlami esa bloklangan. Ya'ni `WHERE is_mandatory` shartli har
   qanday darvoza HAMMA NARSANI JIMGINA O'TKAZADI va ishlayotgandek
   ko'rinadi.

2. QAROR MUSBAT DALILDAN CHIQADI.
   "To'siq topilmadi" != "malakali". Agar hech narsa o'lchanmagan
   bo'lsa, javob `review` — hech qachon `go` emas. Har `ok` hukmi
   QAYSI talab QAYSI maydonga tegganini nomlaydi.

3. SINOV MA'LUMOTI YORLIG'I NATIJA BILAN BIRGA YURADI.
   Profil `is_sample = true` bo'lsa, natijadagi `is_sample` ham
   `true`. Undan statistik xulosa chiqarilmaydi.


ISHONCH — talab tasdiqlanmagan bo'lsa hukm PASAYTIRILADI
════════════════════════════════════════════════════════
`requirement.ishonchli()` ni ISHLATMAYMIZ va buning sababi bor: u
"inson tasdiqlagan YOKI c >= 0.85" ni qaytaradi, naqsh talablari esa
c = 0.75 va `pending`. Ya'ni bugun u FAQAT reyestr pozitsiyalarini
qaytaradi — sertifikat talablari umuman ko'rinmasdi.

Shuning uchun hamma talab o'qiladi, lekin tasdiqlanmagan talabga
asoslangan hukm `fail` dan `risk` ga TUSHIRILADI va `tasdiqlanmagan`
bayrog'i qo'yiladi. Ma'lumot jimgina tashlab yuborilmaydi ham,
haddan tashqari ishonilmaydi ham.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from api import compliance, db, requirement, xatolar

#: Hukm darajalari — `ai_gonogo.STATUSES` bilan bir xil so'zlar, chunki
#: ikkalasi bitta interfeysda ko'rsatiladi.
STATUSES = ("ok", "risk", "fail", "malumot_yoq")

#: Qaror — `ai_gonogo.DECISIONS` bilan bir xil.
DECISIONS = ("go", "review", "no_go")

#: Shundan past ishonchli talabga asoslangan hukm `risk` dan oshmaydi.
#: `requirement.ISHONCH_CHEGARA` bilan BIR XIL manba — ikki joyda
#: yozilsa jimgina ajralib ketardi.
ISHONCH_CHEGARA = requirement.ISHONCH_CHEGARA

#: `go` uchun KAMIDA shuncha mezon `ok` bo'lishi kerak. Musbat dalil
#: talabi: nol o'lchov `go` bermasin.
GO_MIN_OK = 3


SQL_TALABLAR = """
SELECT id, name, attrs->>'tur' AS tur, attrs->>'qiymat' AS qiymat,
       confidence, review_status, mashina_holat, reviewed_by,
       corrected_value, raw_snippet,
       file_ref, char_start, delivery_days
FROM tender_requirement
WHERE tender_id = %(t)s AND company_id = %(c)s
  -- FAQAT INSON rad etgani chiqib ketadi. `extracted` (reyestr)
  -- qoladi: u rad etilgan emas, shunchaki inson ko'rmagan.
  AND review_status <> 'rejected'
ORDER BY confidence DESC, id
"""

SQL_PROFIL = """
SELECT p.*, c.toldirilgan, c.jami_maydon
FROM company_profile p
LEFT JOIN v_profile_completeness c ON c.company_id = p.company_id
WHERE p.company_id = %(c)s
"""

SQL_TENDER = """
SELECT id, name, close_at, totalcost, currency, area_path
FROM tender WHERE id = %(t)s
"""


# =====================================================================
# Yordamchilar
# =====================================================================
_FOIZ_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_KUN_RE = re.compile(r"(\d+)\s*(kun|кун|дн|day)", re.I)
_OY_RE = re.compile(r"(\d+)\s*(oy|ой|мес)", re.I)


def foiz(qiymat: Optional[str]) -> Optional[float]:
    """'3 %' -> 3.0. Topilmasa None — TAXMIN QILINMAYDI."""
    m = _FOIZ_RE.search(qiymat or "")
    return float(m.group(1).replace(",", ".")) if m else None


def kun(qiymat: Optional[str]) -> Optional[int]:
    """'24 месяца' -> 720, '30 kun' -> 30. Topilmasa None."""
    t = qiymat or ""
    m = _KUN_RE.search(t)
    if m:
        return int(m.group(1))
    m = _OY_RE.search(t)
    if m:
        return int(m.group(1)) * 30
    return None


def _hukm(r: Dict[str, Any], daraja: str) -> str:
    """Ishonchsiz talabga asoslangan `fail` -> `risk`.

    IKKI SABABDAN BIRI yetarli: INSON tasdiqlagan, YOKI mashina
    ishonchi chegaradan yuqori. Ular BOSHQA-BOSHQA asoslar va shu
    sababli alohida funksiyalar bilan o'qiladi — ilgari ikkalasi
    bitta `review_status` ustunidan chiqarilardi va reyestr
    pozitsiyalari "inson tasdiqladi" bo'lib ko'rinardi (1 487 qator,
    o'lchangan 2026-08-30).
    """
    if daraja != "fail":
        return daraja
    return "fail" if (_inson_tasdiqladi(r) or _ishonchli(r)) else "risk"


def _inson_tasdiqladi(r: Dict[str, Any]) -> bool:
    """INSON haqiqatan tasdiqladimi (yoki tuzatdimi)?

    Faqat holatga qarash YETARLI EMAS deb o'ylash mumkin, lekin endi
    yetarli: `tender_requirement_inson_qarori_chk` cheklovi
    `approved`/`corrected` ni `reviewed_by IS NOT NULL` bo'lmasdan
    yozishga YO'L QO'YMAYDI. `reviewed_by` ham tekshiriladi —
    cheklov kelajakda o'chirilsa ham bu funksiya yolg'on
    gapirmasin.
    """
    return (r.get("review_status") in ("approved", "corrected")
            and r.get("reviewed_by") is not None)


def _ishonchli(r: Dict[str, Any]) -> bool:
    """MASHINA ishonchi chegaradan yuqorimi? Bu INSON tasdig'i EMAS."""
    return float(r.get("confidence") or 0) >= ISHONCH_CHEGARA


def _qiymat(r: Dict[str, Any]) -> Optional[str]:
    """Inson tuzatgan qiymat ustun — u yakuniy haqiqat."""
    return r.get("corrected_value") or r.get("qiymat")


def _dalil(r: Dict[str, Any]) -> Dict[str, Any]:
    """Hukm QAYSI talabdan kelganini ko'rsatadi — manbaga sakrash uchun."""
    inson = _inson_tasdiqladi(r)
    ishonch = _ishonchli(r)
    return {"requirement_id": r["id"], "name": r["name"],
            "qiymat": _qiymat(r), "confidence": float(r["confidence"] or 0),
            "review_status": r["review_status"],
            "mashina_holat": r.get("mashina_holat"),
            "file_ref": r.get("file_ref"), "char_start": r.get("char_start"),
            # IKKI ALOHIDA BAYROQ — bittasi ikkinchisini bildirmaydi.
            #   inson_tasdiqladi  odam ko'rdi va roziligini berdi
            #   mashina_ishonchli mashina ishonchi chegaradan yuqori
            # Ilgari bitta `tasdiqlanmagan` bayrog'i bor edi va u
            # ikkalasini ARALASHTIRARDI: reyestr pozitsiyasi (inson
            # ko'rmagan, ishonch 1.00) "tasdiqlangan" bo'lib chiqardi.
            "inson_tasdiqladi": inson,
            "mashina_ishonchli": ishonch,
            # Eskisi MOSLIK uchun qoldirildi, lekin endi ANIQ ma'noli:
            # "na inson tasdig'i, na yetarli mashina ishonchi".
            "tasdiqlanmagan": not (inson or ishonch)}


# =====================================================================
# Mezonlar — har biri (status, izoh, dalillar) qaytaradi
# =====================================================================
def _sertifikat(talablar: List[dict], profil: dict) -> Dict[str, Any]:
    """Tender so'ragan hujjat kompaniyada bormi.

    IKKALA TOMON HAM `compliance.match_doc_type()` orqali kodga
    keltiriladi — u uch alifboni biladi ('Литсензия', 'лицензия',
    'litsenziya' -> `license`). Bu yerda qayta yozilmaydi: ikkinchi
    nusxa jimgina ajralib ketardi.
    """
    kerak: Dict[str, List[dict]] = {}
    for r in talablar:
        if r["tur"] != "sertifikat":
            continue
        kod = (compliance.match_doc_type(r["name"])
               or compliance.match_doc_type(_qiymat(r)))
        if kod:
            kerak.setdefault(kod, []).append(r)

    if not kerak:
        return {"status": "malumot_yoq",
                "izoh": "Hujjatdan aniq hujjat turi ajratilmadi.",
                "dalillar": []}

    bor = set()
    for c in (profil.get("certificates") or []):
        kod = compliance.match_doc_type(c)
        if kod:
            bor.add(kod)
    # Kompaniya HUJJATLARI ham hisobga olinadi (yuklangan fayllar).
    for d in db.query("""SELECT doc_type FROM company_document
                         WHERE company_id = %(c)s""",
                      {"c": profil["company_id"]}):
        if d["doc_type"]:
            bor.add(d["doc_type"])

    if not bor:
        return {"status": "malumot_yoq",
                "izoh": "Kompaniya sertifikatlari kiritilmagan.",
                "dalillar": [_dalil(r) for rs in kerak.values() for r in rs]}

    yetishmaydi = [k for k in kerak if k not in bor]
    topilgan = [k for k in kerak if k in bor]

    nom = {d["code"]: d["label"] for d in compliance.DOC_TYPES}
    if yetishmaydi:
        eng = [r for k in yetishmaydi for r in kerak[k]]
        st = "fail"
        for r in eng:
            st = _hukm(r, "fail")
            if st == "fail":
                break
        return {"status": st,
                "izoh": "Yetishmaydi: "
                        + ", ".join(nom.get(k, k) for k in yetishmaydi),
                "dalillar": [_dalil(r) for r in eng]}
    return {"status": "ok",
            "izoh": "Talab qilingan hujjatlar bor: "
                    + ", ".join(nom.get(k, k) for k in topilgan),
            "dalillar": [_dalil(r) for k in topilgan for r in kerak[k]]}


def _muddat(talablar: List[dict], profil: dict,
            tender: dict) -> Dict[str, Any]:
    """Yetkazish muddati kompaniya odatiy muddatidan qisqami."""
    lead = profil.get("lead_time_days")
    if lead is None:
        return {"status": "malumot_yoq",
                "izoh": "Kompaniya yetkazish muddati kiritilmagan.",
                "dalillar": []}

    eng_qisqa, manba = None, None
    for r in talablar:
        d = r.get("delivery_days") or (kun(_qiymat(r))
                                       if r["tur"] == "muddat" else None)
        if d and (eng_qisqa is None or d < eng_qisqa):
            eng_qisqa, manba = d, r
    if eng_qisqa is None:
        return {"status": "malumot_yoq",
                "izoh": "Tenderda yetkazish muddati ko'rsatilmagan.",
                "dalillar": []}

    d = [_dalil(manba)] if manba else []
    if int(lead) <= eng_qisqa:
        return {"status": "ok",
                "izoh": f"Tender {eng_qisqa} kun so'raydi, kompaniya "
                        f"{int(lead)} kunda bajaradi.",
                "dalillar": d}
    return {"status": _hukm(manba or {}, "fail"),
            "izoh": f"Tender {eng_qisqa} kun so'raydi, kompaniya "
                    f"{int(lead)} kun — YETMAYDI.",
            "dalillar": d}


def _moliya(talablar: List[dict], profil: dict,
            tender: dict) -> Dict[str, Any]:
    """Shartnoma kafolati / zakalat kompaniya quvvatiga sig'adimi.

    Kafolat odatda FOIZ bilan beriladi ('3 %'), ya'ni haqiqiy summa
    tender qiymatidan hisoblanadi.
    """
    cap = profil.get("max_contract_value")
    cost = tender.get("totalcost")
    if cap is None:
        return {"status": "malumot_yoq",
                "izoh": "Kompaniya moliyaviy salohiyati kiritilmagan.",
                "dalillar": []}
    if cost is None:
        return {"status": "malumot_yoq",
                "izoh": "Tender qiymati ko'rsatilmagan.", "dalillar": []}

    # Valyuta mos kelmasa TAXMIN QILMAYMIZ — kurs bu modulning ishi emas.
    pcur, tcur = profil.get("max_contract_currency"), tender.get("currency")
    if pcur and tcur and pcur != tcur:
        return {"status": "malumot_yoq",
                "izoh": f"Valyutalar har xil ({pcur} / {tcur}) — "
                        "taqqoslanmadi.", "dalillar": []}

    cap, cost = float(cap), float(cost)
    dalillar, eng_kafolat, manba = [], 0.0, None
    for r in talablar:
        if r["tur"] not in ("moliyaviy", "kafolat"):
            continue
        p = foiz(_qiymat(r))
        if p is None:
            continue
        summa = cost * p / 100.0
        if summa > eng_kafolat:
            eng_kafolat, manba = summa, r
        dalillar.append(_dalil(r))

    if cost > cap:
        return {"status": "fail",
                "izoh": f"Tender qiymati {cost:,.0f} kompaniya salohiyati "
                        f"{cap:,.0f} dan {cost / cap:.1f} barobar katta."
                        .replace(",", " "),
                "dalillar": dalillar}
    if manba is not None and eng_kafolat > cap:
        return {"status": _hukm(manba, "fail"),
                "izoh": f"Kafolat summasi {eng_kafolat:,.0f} salohiyatdan "
                        f"oshadi.".replace(",", " "),
                "dalillar": dalillar}
    return {"status": "ok",
            "izoh": (f"Tender qiymati {cost:,.0f}, salohiyat {cap:,.0f}"
                     .replace(",", " "))
                    + (f"; eng katta kafolat {eng_kafolat:,.0f}"
                       .replace(",", " ") if manba is not None else ""),
            "dalillar": dalillar}


def _tolov(talablar: List[dict], profil: dict,
           tender: dict) -> Dict[str, Any]:
    """Avans yo'q bo'lsa aylanma mablag' kerak bo'ladi."""
    dalillar = [_dalil(r) for r in talablar if r["tur"] == "tolov"]
    if not dalillar:
        return {"status": "malumot_yoq",
                "izoh": "To'lov sharti ajratilmadi.", "dalillar": []}
    avans = None
    manba = None
    for r in talablar:
        if r["tur"] != "tolov":
            continue
        p = foiz(_qiymat(r))
        if p is not None and (avans is None or p < avans):
            avans, manba = p, r
    if avans is None:
        return {"status": "malumot_yoq",
                "izoh": "To'lov foizi o'qilmadi.", "dalillar": dalillar}
    if avans >= 30:
        return {"status": "ok",
                "izoh": f"Oldindan to'lov {avans:g}% — aylanma mablag' "
                        "bosimi past.", "dalillar": dalillar}
    return {"status": _hukm(manba or {}, "fail") if avans == 0 else "risk",
            "izoh": f"Oldindan to'lov {avans:g}% — aylanma mablag' kerak.",
            "dalillar": dalillar}


def hudud_mos(area_path: Optional[str],
              regions: Optional[List[str]]) -> Optional[bool]:
    """Tender hududi kompaniya e'lon qilgan hududlar ichidami.

    `None` = O'LCHAB BO'LMAYDI — cheklov qo'yilmagan yoki tenderning
    hududi noma'lum. Bu "mos emas" DEGANI EMAS: interfeysda ham,
    malaka tekshiruvida ham ikkisi boshqacha ko'rsatiladi.

    NEGA ALOHIDA FUNKSIYA (2026-09-03). Shu qoida ikki joyda kerak:
    malaka tekshiruvi (`_hudud`) va katalog mosligi (`/catalog/match`
    dagi belgi). Ikki joyda YOZILSA ajralib ketardi va aynan shu
    ajralish foydalanuvchi ko'rgan nomuvofiqlikni keltirib chiqargan
    edi: "Sizga mos" hududni umuman hisobga olmasdi, navbat esa uni
    QATTIQ to'siq sifatida qo'llardi. Natijada katalogga mos 28
    tenderdan 11 tasi navbatda ko'rinmasdi va SABABI hech qayerda
    aytilmasdi.

    PREFIKS bo'yicha: `33.2137` (Toshkent shahri) `33.2137.2138.2142`
    (uning tumani) ni ham qamrab oladi. Oddiy `startswith` YETMAYDI —
    u `33.21` ni `33.2137` ga ham moslashtirardi, ya'ni boshqa
    viloyat "mos" bo'lib chiqardi. Shuning uchun nuqta TALAB
    QILINADI.
    """
    if not regions or not area_path:
        return None
    return any(area_path == r or area_path.startswith(r + ".")
               for r in regions)


def _hudud(profil: dict, tender: dict) -> Dict[str, Any]:
    regions = profil.get("regions") or []
    area = tender.get("area_path") or ""
    if not regions:
        return {"status": "malumot_yoq",
                "izoh": "Kompaniya hududlari kiritilmagan (cheklov yo'q).",
                "dalillar": []}
    if not area:
        return {"status": "malumot_yoq",
                "izoh": "Tender hududi ko'rsatilmagan.", "dalillar": []}
    hit = hudud_mos(area, regions)
    return {"status": "ok" if hit else "fail",
            "izoh": f"Tender hududi {area}, kompaniya {regions} -> "
                    + ("MOS" if hit else "MOS EMAS"),
            "dalillar": []}


def _tajriba(talablar: List[dict], profil: dict) -> Dict[str, Any]:
    """Tender talab qilgan tajriba kompaniyada bormi.

    TENDER TOMONI 2026-08-26 da qo'shildi (`atama.GURUHLAR['tajriba']`
    + `requirement_naqsh` ikki tartibda). Undan oldin bu mezon
    DOIM `malumot_yoq` edi.

    NAQSH IKKI TARTIBDA — o'lchangan, taxmin emas:

        "камида 8 йиллик тажрибага эга"   son -> atama  (128 bo'lak)
        "стаж работы не менее 3 лет"      atama -> son  (88 bo'lak)

    Faqat bittasi yozilganda talablarning ~59% i tushib qolardi.
    """
    exp = profil.get("experience_years")
    kerak, manba = None, None
    for r in talablar:
        if r["tur"] != "tajriba":
            continue
        y = None
        q = _qiymat(r) or ""
        m = re.search(r"(\d{1,3})", q)
        if m:
            y = int(m.group(1))
        if y and (kerak is None or y > kerak):
            kerak, manba = y, r

    if kerak is None:
        return {"status": "malumot_yoq",
                "izoh": ("Tenderdan tajriba talabi ajratilmadi."
                         if exp is None else
                         f"Kompaniyada {int(exp)} yil tajriba bor; "
                         "tenderda talab ko'rsatilmagan."),
                "dalillar": []}
    if exp is None:
        return {"status": "malumot_yoq",
                "izoh": f"Tender {kerak} yil tajriba so'raydi; "
                        "kompaniya tajribasi kiritilmagan.",
                "dalillar": [_dalil(manba)]}

    d = [_dalil(manba)]
    if int(exp) >= kerak:
        return {"status": "ok",
                "izoh": f"Tender {kerak} yil so'raydi, kompaniyada "
                        f"{int(exp)} yil.",
                "dalillar": d}
    return {"status": _hukm(manba, "fail"),
            "izoh": f"Tender {kerak} yil so'raydi, kompaniyada "
                    f"{int(exp)} yil — YETMAYDI.",
            "dalillar": d}


def _xavfsizlik(profil: dict) -> Dict[str, Any]:
    clr = profil.get("clearances") or []
    if not clr:
        return {"status": "malumot_yoq",
                "izoh": "Xavfsizlik ruxsatnomalari kiritilmagan.",
                "dalillar": []}
    return {"status": "malumot_yoq",
            "izoh": f"Kompaniyada {len(clr)} ruxsatnoma bor, lekin "
                    "tenderdan bunday talab ajratilmaydi.",
            "dalillar": []}


CRITERIA = [
    {"key": "sertifikat",   "label": "Sertifikat / litsenziya"},
    {"key": "muddat",       "label": "Yetkazish muddati"},
    {"key": "moliyaviy",    "label": "Moliyaviy salohiyat"},
    {"key": "tolov",        "label": "To'lov sharti"},
    {"key": "hudud",        "label": "Geografik cheklov"},
    {"key": "tajriba",      "label": "Tajriba"},
    {"key": "xavfsizlik",   "label": "Xavfsizlik ruxsatnomalari"},
]
_KEYS = [c["key"] for c in CRITERIA]


# =====================================================================
# Asosiy
# =====================================================================
def check(tender_id: int, company_id: int) -> Dict[str, Any]:
    """Bitta tender uchun malaka tekshiruvi. MODEL CHAQIRILMAYDI."""
    tender = db.query_one(SQL_TENDER, {"t": tender_id})
    if not tender:
        raise xatolar.Xato("TENDER_NOT_FOUND", {"id": tender_id})
    profil = db.query_one(SQL_PROFIL, {"c": company_id}) or {
        "company_id": company_id}
    talablar = db.query(SQL_TALABLAR, {"t": tender_id, "c": company_id})

    natija = {
        "sertifikat": _sertifikat(talablar, profil),
        "muddat":     _muddat(talablar, profil, tender),
        "moliyaviy":  _moliya(talablar, profil, tender),
        "tolov":      _tolov(talablar, profil, tender),
        "hudud":      _hudud(profil, tender),
        "tajriba":    _tajriba(talablar, profil),
        "xavfsizlik": _xavfsizlik(profil),
    }
    mezonlar = [{"key": c["key"], "label": c["label"], **natija[c["key"]]}
                for c in CRITERIA]

    n_ok = sum(1 for m in mezonlar if m["status"] == "ok")
    n_fail = sum(1 for m in mezonlar if m["status"] == "fail")
    n_risk = sum(1 for m in mezonlar if m["status"] == "risk")
    olchandi = sum(1 for m in mezonlar if m["status"] != "malumot_yoq")

    # QAROR — MUSBAT DALILDAN.
    #
    # `no_go` to'siqdan chiqadi (bu to'g'ri: bitta `fail` yetarli).
    # `go` esa TASDIQDAN chiqishi kerak: kamida GO_MIN_OK ta mezon
    # `ok` bo'lsin va xavf bo'lmasin. Aks holda hech narsa
    # o'lchanmagan tender ham `go` olardi — "to'siq topilmadi"
    # degani "malakali" degani emas.
    if n_fail:
        qaror = "no_go"
    elif n_ok >= GO_MIN_OK and not n_risk:
        qaror = "go"
    else:
        qaror = "review"

    return {
        "tender_id": tender_id,
        "company_id": company_id,
        "decision": qaror,
        "criteria": mezonlar,
        "criteria_labels": CRITERIA,
        "ok": n_ok, "fail": n_fail, "risk": n_risk,
        "olchandi": olchandi, "jami_mezon": len(_KEYS),
        "talablar_soni": len(talablar),
        # PROFIL TO'LIQLIGI — tekshiruvdan oldin ko'riladigan raqam.
        # 0 bo'lsa natija "malakali emas" emas, "BILIB BO'LMAYDI".
        "profil_toldirilgan": profil.get("toldirilgan"),
        "profil_jami": profil.get("jami_maydon"),
        # SINOV MA'LUMOTI yorlig'i natija bilan BIRGA yuradi.
        "is_sample": bool(profil.get("is_sample")),
        "sample_note": profil.get("sample_note"),
    }
