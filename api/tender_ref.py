"""
XABARDAGI TENDER RAQAMINI HAL QILISH — MODEL CHAQIRILMAYDI
===========================================================

Foydalanuvchi "#20000509580 tender bo'yicha narxini hisoblab ber"
deb yozadi. Shu paytgacha raqamni MODEL hal qilardi va u ko'pincha
`search_tenders("20000509580")` ni tanlardi — ya'ni ID ni matn deb
qidirardi.

O'LCHANDI (2026-09-04, `chat_message` jurnalidan). Haqiqiy
foydalanuvchining 7 ta raqamli xabari:

    2 ta  to'g'ri tool
    2 ta  `get_tender` UMUMAN chaqirilmagan — javob qidiruvdan tuzilgan
    2 ta  ortiqcha `search_tenders` raundi, keyin to'g'ri ID bilan davom
    1 ta  hal qilinmagan (e-do'kon havolasi)

Shuning uchun raqam MODEL CHAQIRILISHIDAN OLDIN, kod bilan hal
qilinadi va natija tizim blokiga qo'yiladi.

NAQSH KENG, BAZA TOR — IKKI BOSQICH
════════════════════════════════════
Reja `\\d{6,8}` ni taklif qilgan edi. Jurnal uni rad etdi: haqiqiy
raqamlarning aksariyati 11 xonali (`20000509580`) va `#` bilan
yoziladi. Korpusda `tender.id` ning 74,8% i 11 xonali — ya'ni
6–8 naqshi uchdan ikki qismini KO'RMASDI.

Diapazon 5–12 xonaga kengaytirildi. Bu soxta tanish ehtimolini
oshiradi (summa `15000000`, sana `20260904`, telefon
`998901234567`), shuning uchun ikkinchi bosqich TOR: raqam BAZADA
tekshiriladi.

TOPILMAGAN RAQAM HAQIDA IKKI XIL XULQ
══════════════════════════════════════
    yalang'och raqam   ->  JIMGINA tashlanadi
    `#`/`№` yoki havola ->  "topilmadi" deb AYTILADI

Sabab: `15000000` ID bo'lmasligi mumkin va u haqida "topilmadi"
deyish modelni yo'q narsani qidirishga majburlardi. `#8440527` esa
ANIQ ID da'vosi — u topilmasa, foydalanuvchi buni bilishi kerak.

"BAZADA YO'Q" ва "QAMROVDA YO'Q" — BOSHQA-BOSHQA
═════════════════════════════════════════════════
`https://xarid.uzex.uz/shop/lot-details/5613572` — bu UzEx
E-DO'KONI, e'lon platformasi emas. Tizim faqat `etender.uzex.uz`
va `xt-xarid.uz` ni kuzatadi. Javob "topilmadi" emas: "bu manba
kuzatilmaydi". Farqni aytmasak model yo'q narsani qidirib yurardi —
o'lchandi, aynan shunday bo'lgan (`search_tenders` chaqirilgan).

NEGA ALOHIDA MODUL: `ai_chat.py` dan tashqarida turadi, chunki bu
sof deterministik ish va u PULLIK QATLAMSIZ sinaladi
(`_tests/chat_id_test.py`). `get_tender` tool ham shu funksiyani
ishlatadi — qoida IKKI JOYDA yozilmaydi.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from api import db

#: Bitta xabardan nechta raqam olinadi. Prompt blokini cheklaydi:
#: 40 ta raqam yopishtirilgan xabar kontekstni to'ldirardi.
MAX_RAQAM = 5

#: Eng qisqa va eng uzun ID. Pastki chegara 5 — korpusda 5 xonali
#: 6 ta tender bor. Yuqorisi 12 — 11 xonali ID dan bittagina
#: ko'p, ya'ni telefon raqami (12 xona) hali ham kiradi va uni
#: BAZA tekshiruvi tashlaydi.
MIN_XONA, MAX_XONA = 5, 12

#: KUZATILADIGAN PLATFORMALAR — `tender.source_platform` bilan AYNI.
#: `xarid.uzex.uz` ATAYLAB YO'Q: u e-do'kon, e'lon platformasi emas.
KUZATILADI = {
    "etender.uzex.uz": "uzex",
    "apietender.uzex.uz": "uzex",
    "xt-xarid.uz": "xt-xarid",
    "api.xt-xarid.uz": "xt-xarid",
    "www.xt-xarid.uz": "xt-xarid",
}

#: Nomi ma'lum, lekin KUZATILMAYDIGAN manbalar. Bularni "noma'lum
#: havola" dan ajratamiz: foydalanuvchiga NEGA yo'qligini aytish
#: mumkin bo'ladi.
KUZATILMAYDI = {
    "xarid.uzex.uz": "UzEx e-do'koni",
}

_URL = re.compile(r"https?://([^\s/]+)([^\s]*)", re.IGNORECASE)

#: Xabardagi raqam nomzodi.
#:
#: Oldi/keti tekshiruvi soxta tanishni kesadi:
#:   `ISO900112`  -> harf yopishgan, olinmaydi
#:   `1.234567`   -> o'nlik kasr, olinmaydi
#:   `18.08.`     -> 2 xonali, diapazonga kirmaydi
#:   `narxi 8440527.` -> jumla nuqtasi XALAQIT BERMAYDI
#: `[tT]` PREFIKSI — FOYDALANUVCHIDAN EMAS, MODELDAN.
#: Jurnalda `t8440527` shakli HECH QACHON uchramagan (foydalanuvchi
#: `#` yozadi). Lekin model uni o'z javobidan yoki hujjat matnidan
#: olib tool ga uzatishi mumkin, shuning uchun qabul qilinadi.
#: `(?=\d)` shart: `net12345` dagi `t` prefiks bo'lib qolmasin —
#: uning oldidagi harf lookbehind bilan allaqachon rad etiladi.
_RAQAM = re.compile(
    r"(?<![0-9A-Za-z.,])"
    r"(?P<belgi>[#№]|[tT](?=\d))?"
    r"(?P<raqam>\d{%d,%d})"
    r"(?![0-9A-Za-z])(?![.,]\d)" % (MIN_XONA, MAX_XONA)
)

#: Raqam IKKI ustunda qidiriladi.
#:
#: `tender_lot.lot_id` ATAYLAB YO'Q. U global identifikator EMAS —
#: tender ichidagi tartib raqami (1, 2, 3). O'lchandi: `lot_id`
#: qiymatlari kichik butun sonlar. Uni qidirishga qo'shish har
#: qanday raqamni "lot" deb ko'rsatib, soxta musbat berardi.
#:
#: `source_id` esa haqiqiy muqobil: uzex da `id = 20000000000 +
#: source_id`, ya'ni foydalanuvchi `508540` deb ham yozishi mumkin.
SQL_HAL = """
SELECT id, name, source_platform, source_id,
       (id = %(n)s) AS aynan_id
FROM tender
WHERE id = %(n)s OR source_id = %(n)s
ORDER BY (id = %(n)s) DESC, id
LIMIT 3
"""


def _url_nomzodlari(matn: str) -> List[Dict[str, Any]]:
    """Havolalardan raqam ajratadi va manbani baholaydi."""
    out: List[Dict[str, Any]] = []
    for host, yol in _URL.findall(matn):
        host = host.lower().split(":")[0]
        raqamlar = re.findall(r"/(\d{%d,%d})(?=[/?#]|$)"
                              % (MIN_XONA, MAX_XONA), yol)
        if not raqamlar:
            continue
        n = int(raqamlar[-1])           # oxirgisi — odatda resurs ID si
        if host in KUZATILADI:
            out.append({"raqam": n, "aniq": True, "manba": None})
        else:
            out.append({"raqam": n, "aniq": True,
                        "manba": KUZATILMAYDI.get(host, host)})
    return out


def _matn_nomzodlari(matn: str) -> List[Dict[str, Any]]:
    """Havoladan tashqari raqamlar. `#`/`№` — ANIQ ID da'vosi."""
    return [{"raqam": int(m.group("raqam")),
             "aniq": bool(m.group("belgi")),
             "manba": None}
            for m in _RAQAM.finditer(matn)]


def nomzodlar(matn: str) -> List[Dict[str, Any]]:
    """Xabardan raqam nomzodlarini ajratadi. BAZAGA BORMAYDI.

    Havoladagi raqam BIRINCHI: u kontekstni ham olib keladi
    (qaysi platforma). Takrorlar birinchi ko'rinishi bo'yicha
    saqlanadi — havoladagi `aniq=True` yalang'och takroridan
    ustun turadi.
    """
    if not matn:
        return []
    # Havoladagi raqamlar matnli qidiruvga IKKINCHI marta
    # tushmasligi uchun havolalar o'chiriladi.
    tozalangan = _URL.sub(" ", matn)
    korilgan: Dict[int, Dict[str, Any]] = {}
    for c in _url_nomzodlari(matn) + _matn_nomzodlari(tozalangan):
        korilgan.setdefault(c["raqam"], c)
        if len(korilgan) >= MAX_RAQAM:
            break
    return list(korilgan.values())


def hal_qil(matn: str, company_id: int) -> List[Dict[str, Any]]:
    """Xabardagi raqamlarni tenderga bog'laydi. MODEL CHAQIRILMAYDI.

    `company_id` HOZIRCHA ISHLATILMAYDI va bu ATAYLAB: `tender`
    korpusi ijarachiga bo'linmagan (u ommaviy e'lonlar reyestri,
    `tender_requirement` dan farqli). Parametr imzoda TURADI —
    korpus bo'linganda chaqiruvchilarni qayta yozish shart
    bo'lmasin va "bu yerda ijarachi hisobga olinmagan" degan savol
    ochiq qolmasin.

    QAYTARADI — har raqam uchun bitta yozuv:
        holat   `topildi` | `topilmadi` | `qamrovdan_tashqari`
        raqam   foydalanuvchi yozgan son
        tender_id, nom, platforma, mos_ustun  — topilganda
        manba   — qamrovdan tashqari bo'lsa, qaysi manba ekani

    Jimgina tashlanganlar RO'YXATGA UMUMAN KIRMAYDI: yalang'och
    raqam bazada yo'q bo'lsa, u ID bo'lmagan bo'lishi mumkin
    (summa, sana, telefon) va u haqida gapirish modelni chalg'itardi.
    """
    natija: List[Dict[str, Any]] = []
    for c in nomzodlar(matn):
        n = c["raqam"]
        if c["manba"]:
            # QAMROVDAN TASHQARI: bazani so'rashning ma'nosi yo'q.
            natija.append({"holat": "qamrovdan_tashqari", "raqam": n,
                           "manba": c["manba"]})
            continue
        rows = db.query(SQL_HAL, {"n": n})
        if not rows:
            if c["aniq"]:
                natija.append({"holat": "topilmadi", "raqam": n})
            continue                    # yalang'och raqam — JIM
        r = rows[0]
        natija.append({
            "holat": "topildi", "raqam": n,
            "tender_id": int(r["id"]),
            "nom": (r["name"] or "")[:80],
            "platforma": r["source_platform"],
            "mos_ustun": "id" if r["aynan_id"] else "source_id",
            # BIR NECHTA MOS KELSA AYTILADI. `source_id` platformalar
            # bo'yicha takrorlanishi mumkin va "qaysi biri" degan
            # savolni model emas, foydalanuvchi hal qilsin.
            "nomuayyan": len(rows) > 1,
        })
    return natija


def blok(natija: List[Dict[str, Any]]) -> Optional[str]:
    """Tizim blokiga qo'yiladigan matn. Bo'sh bo'lsa `None`.

    QISQA ATAYLAB: bu ko'rsatma, hisobot emas. Har qator bitta
    raqam va model uchun bitta aniq harakat.
    """
    if not natija:
        return None
    qatorlar = ["XABARDAGI TENDER RAQAMLARI (tizim aniqladi, "
                "qayta qidirish SHART EMAS):"]
    for r in natija:
        n = r["raqam"]
        if r["holat"] == "topildi":
            q = (f"  {n} -> tender_id={r['tender_id']} "
                 f"\"{r['nom']}\" ({r['platforma']}, {r['mos_ustun']})")
            if r.get("nomuayyan"):
                q += "  [bir nechta mos keldi — foydalanuvchidan so'ra]"
            qatorlar.append(q)
        elif r["holat"] == "qamrovdan_tashqari":
            qatorlar.append(
                f"  {n} -> QAMROVDA YO'Q: manba \"{r['manba']}\" "
                f"kuzatilmaydi. Tizim faqat etender.uzex.uz va "
                f"xt-xarid.uz e'lonlarini oladi. Buni foydalanuvchiga "
                f"ayt va QIDIRMA.")
        else:
            qatorlar.append(
                f"  {n} -> TOPILMADI: bazada bunday tender yo'q. "
                f"Shuni ayt, taxmin qilma.")
    qatorlar.append("Bu raqamlarni `search_tenders` bilan qidirma — "
                    "tender_id allaqachon ma'lum.")
    return "\n".join(qatorlar)
