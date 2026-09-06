"""
SAQLANGAN TAHLILNI O'QISH — MODEL CHAQIRILMAYDI
================================================

`ai_analysis` da tenderning uchta tahlili turadi:

    summary_v1   qisqacha xulosa      (`api/ai.py`)
    match_v2     katalog mosligi      (`api/ai_match.py`)
    gonogo_v2    qatnashish qarori    (`api/ai_gonogo.py`)

Ular ALLAQACHON hisoblangan va pul to'langan. Bu modul ularni
O'QIYDI, xolos.

NEGA ALOHIDA MODUL BOR
══════════════════════
Chat foydalanuvchisi Go/No-Go panelini ko'rgandan keyin "nega
review?" deb so'raydi. Shu paytgacha modelning yagona yo'li
`run_gonogo` edi -- ya'ni 30-60 soniya va yangi pullik chaqiruv,
FOYDALANUVCHI ENDIGINA KO'RGAN natijani qayta hisoblash uchun.

O'lchandi (2026-09-04): `run_gonogo` jami 1 marta chaqirilgan,
ya'ni bugun zarar kichik. Lekin §2.4 kirish tugmasi qo'shilgach
aynan shu yo'l ustuvor bo'ladi -- himoya UNDAN OLDIN kerak.

ESKIRISHNI ANIQLASH
═══════════════════
`chat_session.tahlil_hash` sessiya OCHILGANDA yoziladi. Har
xabarda joriy `content_hash` bilan solishtiriladi va farq bo'lsa
model OGOHLANTIRILADI.

Bu `tender_routing.ai_ozgardi` bilan BIR TAMOYIL: inson eski
ma'lumotga tayanib qaror qilmasin. Farqi shundaki, u yerda
broker qarori eskiradi, bu yerda esa SUHBAT o'rtasida asos
o'zgaradi.

CHEKLOV OCHIQ AYTILADI: hash faqat "tahlil QAYTA HISOBLANDIMI"
ni bildiradi. "Tahlil eskirdimi" (tender o'zgardi-yu tahlil
yangilanmadi) BOSHQA savol va u bu yerda o'lchanmaydi -- uni
`gonogo_cached` ning o'zi qayta hisoblaganda hal qiladi.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from api import db, queries

#: Chatga ochiq turlar. Kalitlar modullardan olinadi -- versiya
#: oshsa (`gonogo_v2` -> `v3`) bu yerda qo'lda yangilash SHART
#: EMAS va ikki joyda ikki xil qiymat bo'lib qolmaydi.
def _turlar() -> Dict[str, str]:
    from api import ai, ai_gonogo, ai_match
    return {"summary": ai.KIND, "match": ai_match.KIND,
            "gonogo": ai_gonogo.KIND}


TURLAR = ("summary", "match", "gonogo")

#: Xulosa blokidagi eng ko'p element. Blok HISOBOT EMAS, ko'rsatma:
#: uzun ro'yxat kontekstni to'ldiradi va modelni chalg'itadi.
MAX_QATOR = 4


def oqi(tender_id: int, company_id: int, tur: str) -> Optional[Dict[str, Any]]:
    """Saqlangan tahlilni qaytaradi yoki `None`.

    `None` -- "hali hisoblanmagan". Bu XATO EMAS va chaqiruvchi
    uni "tahlil yomon" deb talqin qilmasligi kerak.
    """
    turlar = _turlar()
    if tur not in turlar:
        from api import xatolar
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "kind", "qiymat": tur})
    row = db.query_one(queries.AI_CACHED_SQL,
                       {"id": tender_id, "kind": turlar[tur],
                        "company_id": company_id})
    if not row:
        return None
    return {
        "tur": tur, "kind": turlar[tur],
        "natija": row["result"],
        "content_hash": row["content_hash"],
        "model": row.get("model"),
        # Model "bu qachongi tahlil" degan savolga javob bera olsin.
        "yaratilgan": (row["created_at"].isoformat()
                       if row.get("created_at") else None),
        # QAYTA HISOBLANMADI -- model buni bilishi kerak, aks holda
        # "yangi tahlil qildim" deb yozardi.
        "qayta_hisoblanmadi": True,
    }


def joriy_hash(tender_id: int, company_id: int,
               tur: str = "gonogo") -> Optional[str]:
    """Saqlangan tahlilning hozirgi `content_hash` i.

    Sessiya ochilganda yoziladi va keyin solishtiriladi. Tahlil
    umuman yo'q bo'lsa `None` -- shunda solishtirish ham qilinmaydi
    ("yo'q" bilan "o'zgardi" ARALASHMASIN).
    """
    r = oqi(tender_id, company_id, tur)
    return r["content_hash"] if r else None


# ---------------------------------------------------------------------------
# PROMPT BLOKI
# ---------------------------------------------------------------------------
def _kes(xs: Optional[List[Any]], n: int = MAX_QATOR) -> List[Any]:
    return list(xs or [])[:n]


def gonogo_bloki(natija: Dict[str, Any]) -> str:
    """Go/No-Go tahlilining QISQACHA sharhi (~300 token).

    TO'LIQ MATN BLOKKA QO'YILMAYDI: u 11 mezon, izohlar va
    keyingi qadamlar bilan birga kontekstni to'ldirardi. Model
    tafsilotni `get_analysis` bilan oladi.
    """
    from api import ai_gonogo
    yorliq = {c["key"]: c["label"] for c in ai_gonogo.CRITERIA}

    qatorlar = [
        "KONTEKST: foydalanuvchi hozirgina SHU tenderning Go/No-Go "
        "tahlilini ko'rdi.",
        f"  hukm: {natija.get('decision')} · ishonch: "
        f"{natija.get('confidence')}",
    ]

    # YIQILGAN MEZONLAR -- "nega review?" savolining javobi shu yerda.
    yomon = [c for c in (natija.get("criteria") or [])
             if c.get("status") in ("fail", "risk")]
    if yomon:
        qatorlar.append("  e'tibor talab qiladigan mezonlar:")
        for c in _kes(yomon):
            qatorlar.append(
                f"    [{c.get('status')}] {yorliq.get(c.get('key'), c.get('key'))}"
                f" — {(c.get('note_uz') or '')[:140]}")
        if len(yomon) > MAX_QATOR:
            qatorlar.append(f"    (+{len(yomon) - MAX_QATOR} ta yana)")

    # O'LCHANMAGAN MEZON ALOHIDA. `malumot_yoq` ni "yiqildi" ga
    # qo'shish o'lchanmaganni yomonga aylantirish bo'lardi -- bu
    # loyihada eng qimmat xato sinfi.
    olchanmadi = [c for c in (natija.get("criteria") or [])
                  if c.get("status") == "malumot_yoq"]
    if olchanmadi:
        nomlar = ", ".join(yorliq.get(c.get("key"), c.get("key"))
                           for c in _kes(olchanmadi))
        # KESILGANI AYTILADI. "(7 ta): A, B, C, D" jumlasi to'rttani
        # sanab yettita deydi va model qolgan uchtasini o'ylab
        # topishga urinardi.
        qolgan = len(olchanmadi) - MAX_QATOR
        qatorlar.append(
            f"  O'LCHANMAGAN mezonlar — {len(olchanmadi)} ta: {nomlar}"
            + (f" va yana {qolgan} ta" if qolgan > 0 else "")
            + ". Bular 'yomon' EMAS — ma'lumot yetmagan.")

    bloklar = _kes(natija.get("blockers"))
    if bloklar:
        qatorlar.append("  bloklovchilar:")
        qatorlar.extend(f"    - {str(b)[:140]}" for b in bloklar)

    qatorlar.append(
        "'Bu tahlil', 'nega review', '3-mezon' — SHU tahlil haqida. "
        "Tafsilot kerak bo'lsa `get_analysis` ni chaqir. "
        "`run_gonogo` NI CHAQIRMA — u qayta hisoblaydi va qimmat; "
        "faqat foydalanuvchi ANIQ 'qayta hisobla' desa.")
    return "\n".join(qatorlar)


def kontekst_bloki(tender_id: int, company_id: int,
                   manba: Optional[str],
                   sessiya_hash: Optional[str]) -> Optional[str]:
    """Sessiya manbasiga qarab tizim bloki. Bo'lmasa `None`.

    IKKI QISM: tahlil sharhi va ESKIRISH ogohlantirishi. Ikkinchisi
    manbadan MUSTAQIL -- sessiya qanday ochilgan bo'lmasin, asos
    o'zgargani aytiladi.
    """
    qismlar: List[str] = []

    if manba in ("gonogo", "match"):
        tur = "gonogo" if manba == "gonogo" else "match"
        r = oqi(tender_id, company_id, tur)
        if r and manba == "gonogo":
            qismlar.append(gonogo_bloki(r["natija"]))
        elif r:
            # `match` uchun sharh hozircha YO'Q. Buni jimgina
            # o'tkazib yubormaymiz: model tahlil BORLIGINI bilsin
            # va uni `get_analysis` bilan olsin.
            qismlar.append(
                "KONTEKST: foydalanuvchi SHU tenderning katalog moslik "
                "tahlilini ko'rdi. Tafsilot uchun `get_analysis` "
                "(kind='match') ni chaqir; qayta hisoblama.")
        elif manba == "gonogo":
            # TAHLIL YO'Q -- va bu ham AYTILADI. Aks holda model
            # "foydalanuvchi tahlilni ko'rgan" deb taxmin qilardi.
            qismlar.append(
                "KONTEKST: foydalanuvchi Go/No-Go panelidan keldi, "
                "lekin saqlangan tahlil TOPILMADI. Uning nimani "
                "ko'rganini bilmaysan — so'ra.")

    # ESKIRISH -- `tender_routing.ai_ozgardi` bilan bir tamoyil.
    if sessiya_hash:
        joriy = joriy_hash(tender_id, company_id, "gonogo")
        if joriy and joriy != sessiya_hash:
            qismlar.append(
                "DIQQAT: tahlil sessiya ochilganidan BERI QAYTA "
                "HISOBLANGAN (tender yangilandi yoki katalog o'zgardi). "
                "Foydalanuvchiga shuni ayt va eski xulosalarga tayanma — "
                "kerak bo'lsa `get_analysis` bilan yangisini o'qi.")

    return "\n\n".join(qismlar) if qismlar else None
