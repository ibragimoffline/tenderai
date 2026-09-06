"""
BIRIKTIRILGAN HUJJAT MATNINI AI TAHLILIGA BERISH (TZ P0-2 -> P0-3/P0-5)
======================================================================
Ilgari AI faqat KARTOCHKA ma'lumotini ko'rardi (nom, lot, pozitsiya, summa),
biriktirilgan hujjatlar haqida esa `ai.build_input()` shunchaki
"Biriktirilgan hujjatlar: 5 ta" deb yozib qo'yardi. Texnik topshiriq,
spetsifikatsiya va malaka talablari — hammasi PDF/DOCX ichida qolardi.
Bu modul o'sha matnni tahlilga olib kiradi.

UCHTA QARSHILIK VA ULARNING YECHIMI
-----------------------------------
1. HAJM. Bitta tenderда 400 000 belgigacha matn bor (o'lchangan: 104 ta
   tenderда jami 13,5 mln belgi). Uni butunlay promptga solib bo'lmaydi —
   narx ham, kechikish ham portlaydi. Shuning uchun QAT'IY BYUDJET
   (`AI_DOC_CHARS`, standart 45 000 belgi).

2. FAYL NOMI YORDAM BERMAYDI. O'lchov: nomlarning aksariyati ma'nosiz
   raqam ("202607202430310616.pdf"). Shuning uchun hujjat MAZMUNI bo'yicha
   saralanadi, nomi bo'yicha emas.

3. BOSHIDAN KESISH NOTO'G'RI. PDF ning birinchi sahifalari — muqova,
   rekvizitlar, mundarija. Talablar o'rtada bo'ladi. Shuning uchun matn
   TALAB O'ZAKLARI atrofidan oyna qilib olinadi (compliance.py dagi
   yondashuv), bosh qismidan emas.

HALOLLIK — TZ TALABI
--------------------
"O'qib bo'lmaydigan fayl -> qo'lda tekshirish talab etiladi" va "qora quti
bo'lmasin". Shuning uchun bu modul FAQAT matn emas, HISOBOT ham qaytaradi:
qaysi fayl ishlatildi, qanchasi kesildi, qaysilari umuman o'qilmadi.
Hisobot promptga ham kiradi (model to'liq ma'lumotga ega deb o'ylamasin),
API javobiga ham (foydalanuvchi tahlil qanchalik to'liq ekanini bilsin).
"""
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from api import compliance

#: Promptga ketadigan hujjat matnining umumiy chegarasi (belgi).
#: Kirill matn ~2-3 belgi/token, ya'ni 45k belgi ~ 15-20k token.
DOC_BUDGET = int(os.environ.get("AI_DOC_CHARS", "45000"))

#: Bitta hujjatga ajratiladigan eng kam ulush — bitta yirik fayl butun
#: byudjetni yeb qo'ymasin, qolganlari umuman ko'rinmay qolmasin.
MIN_PER_DOC = 1500

#: Talab o'zagi atrofidan olinadigan oyna (belgi, har tomonga).
WINDOW_PAD = 700

#: Nechta hujjatdan ko'pi bilan matn olinadi.
MAX_DOCS = 8

#: TALAB O'ZAKLARI — matnning qaysi joyi qimmatli ekanini belgilaydi.
#: `compliance.canon()` orqali o'tadi, ya'ni rus kirill, o'zbek lotin va
#: o'zbek kirill yozuvlari bir nuqtaga tushadi ("сертификат" <-> "sertifikat").
#: Alifbo bilan bog'lanmaydigan atamalar ALOHIDA yoziladi.
ANCHOR_STEMS: Tuple[str, ...] = (
    # talab / shart
    "требовани", "talab", "услови", "shart",
    # texnik topshiriq / spetsifikatsiya
    "техническ задани", "texnik topshiriq", "спецификац", "spetsifikatsiya",
    "характеристик", "xususiyat", "параметр",
    # hajm va muddat
    "объем работ", "hajm", "срок поставк", "yetkazish muddat",
    "график", "этап",
    # malaka va hujjat
    "квалификац", "malaka", "лиценз", "litsenziya",
    "сертификат", "sertifikat", "опыт работ", "tajriba",
    # moliyaviy shartlar
    "гаранти", "kafolat", "аванс", "предоплат", "оплат", "to'lov",
    "штраф", "penya", "неустойк",
    # standart
    "гост", "стандарт", "standart", "регламент",
)


def _anchor_variants() -> List[str]:
    """O'zaklarning barcha alifbo yozuvlari — kanonik shaklda (bir marta)."""
    out: List[str] = []
    seen = set()
    for stem in ANCHOR_STEMS:
        for v in (compliance.canon(stem),) + compliance._stem_variants(stem):
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    return out


_VARIANTS: Optional[List[str]] = None


def anchors() -> List[str]:
    global _VARIANTS
    if _VARIANTS is None:
        _VARIANTS = _anchor_variants()
    return _VARIANTS


# ---------------------------------------------------------------------------
# Matndan qimmatli bo'laklarni ajratish
# ---------------------------------------------------------------------------
_WS = re.compile(r"[ \t ]+")
_NL = re.compile(r"\n{3,}")


def _tidy(s: str) -> str:
    """PDF/DOCX dan chiqqan matnda ortiqcha bo'shliq juda ko'p — byudjetni
    behuda yeydi. Ma'noni buzmasdan siqamiz."""
    return _NL.sub("\n\n", _WS.sub(" ", s)).strip()


def hit_positions(raw: str) -> List[int]:
    """Talab o'zaklari XOM matnning qaysi pozitsiyalarida uchraydi."""
    blob, idx = compliance._canon_indexed(raw)
    if not idx:
        return []
    out: List[int] = []
    for needle in anchors():
        start = 0
        while True:
            i = blob.find(needle, start)
            if i < 0:
                break
            out.append(idx[i])
            start = i + len(needle)
    return sorted(set(out))


def excerpts(raw: str, budget: int) -> Tuple[str, int]:
    """Talab o'zaklari atrofidagi oynalarni birlashtirib qaytaradi.

    Natija: (matn, ishlatilgan belgi). Oynalar KESISHSA birlashtiriladi —
    aks holda bir joy ikki marta ketardi. Byudjet tugasa to'xtaydi.

    O'zak umuman topilmasa — matnning BOSHIDAN oladi: bu hujjat baribir
    qimmatli bo'lishi mumkin (masalan sof jadval), lekin bunday holatda
    tanlash uchun ishonchli belgi yo'q.
    """
    if budget <= 0 or not raw:
        return "", 0
    hits = hit_positions(raw)
    if not hits:
        piece = _tidy(raw[:budget])
        return piece, len(piece)

    # Oyna chegaralari, kesishganlari birlashtirilgan holda
    spans: List[List[int]] = []
    for h in hits:
        lo, hi = max(0, h - WINDOW_PAD), min(len(raw), h + WINDOW_PAD)
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])

    parts: List[str] = []
    used = 0
    for lo, hi in spans:
        if used >= budget:
            break
        piece = _tidy(raw[lo:min(hi, lo + (budget - used))])
        if not piece:
            continue
        parts.append(("…" if lo > 0 else "") + piece + ("…" if hi < len(raw) else ""))
        used += len(piece)
    return "\n---\n".join(parts), used


# ---------------------------------------------------------------------------
# DB qatlami
# ---------------------------------------------------------------------------
#: Hujjat matni + nomi. Nom `tender_document` da, matn `tender_document_text` da.
#: `field_key` — manbadagi bo'lim kaliti ("tech_task", "contract_project" …);
#: fayl nomi ma'nosiz raqam bo'lganda o'sha yagona ma'no manbai.
#: DISTINCT ON SHART: `tender_document` da bitta fayl bir necha qator bo'lib
#: turishi mumkin (har `field_key` uchun alohida). Oddiy JOIN da har hujjat
#: IKKI MARTA chiqib, byudjetning yarmini nusxaga sarflardi — o'lchangan
#: holat: 14 ta faylli tender 30 ta bo'lib ko'rinardi.
DOCS_SQL = """
SELECT DISTINCT ON (x.file_ref)
       x.file_ref, x.status, x.char_count, x.page_count, x.error,
       d.name, d.field_key AS section, d.file_type
FROM tender_document_text x
LEFT JOIN tender_document d ON d.file_ref = x.file_ref
WHERE x.tender_id = %(tender_id)s
ORDER BY x.file_ref, x.char_count DESC NULLS LAST
"""

TEXT_SQL = "SELECT text FROM tender_document_text WHERE tender_id=%(t)s AND file_ref=%(f)s"


def _label(row: Dict[str, Any]) -> str:
    """Hujjatning o'qiladigan nomi. Fayl nomi ma'nosiz raqam bo'lsa
    (o'lchov: aksariyati shunday) bo'lim nomi ko'proq ma'no beradi."""
    name = (row.get("name") or "").strip()
    section = (row.get("section") or "").strip()
    if name and not re.fullmatch(r"\d{8,}\.\w+", name):
        return f"{name}" + (f" ({section})" if section else "")
    return section or name or (row.get("file_ref") or "hujjat")


def context(tender_id: int, budget: int = DOC_BUDGET) -> Tuple[str, Dict[str, Any]]:
    """Tender hujjatlaridan AI uchun matn + halol hisobot.

    Qaytaradi: (prompt uchun matn, meta). `meta` API javobiga ham tushadi —
    foydalanuvchi tahlil qanchalik to'liq ekanini ko'rsin.
    """
    from api import db

    try:
        rows = db.query(DOCS_SQL, {"tender_id": tender_id})
    except Exception:
        # Jadval hali yo'q yoki baza javob bermadi — tahlil busiz ham ishlaydi
        return "", {"available": False, "used": [], "unreadable": [],
                    "truncated": False, "chars": 0}

    # DISTINCT ON `file_ref` bo'yicha, lekin tartib `char_count` kerak —
    # shuning uchun saralash SQL da emas, shu yerda.
    rows.sort(key=lambda r: -(r.get("char_count") or 0))

    ok_rows = [r for r in rows if r.get("status") == "ok" and (r.get("char_count") or 0) > 0]
    bad_rows = [r for r in rows if r.get("status") != "ok"]

    meta: Dict[str, Any] = {
        "available": bool(rows),
        "total_files": len(rows),
        "readable": len(ok_rows),
        "unreadable": [{"name": _label(r), "reason": r.get("status")} for r in bad_rows],
        "used": [],
        "truncated": False,
        "chars": 0,
    }
    if not ok_rows:
        return "", meta

    # Byudjetni bo'lish: har hujjatga kamida MIN_PER_DOC, qolgani hajmga
    # proporsional. Eng katta fayl butun byudjetni yeb qo'ymasin.
    picked = ok_rows[:MAX_DOCS]
    meta["skipped_for_budget"] = [_label(r) for r in ok_rows[MAX_DOCS:]]
    total_chars = sum((r.get("char_count") or 0) for r in picked) or 1
    base = min(MIN_PER_DOC, budget // max(1, len(picked)))
    rest = max(0, budget - base * len(picked))

    parts: List[str] = []
    used_total = 0
    for r in picked:
        share = base + int(rest * (r.get("char_count") or 0) / total_chars)
        row = db.query_one(TEXT_SQL, {"t": tender_id, "f": r["file_ref"]})
        raw = (row or {}).get("text") or ""
        piece, used = excerpts(raw, min(share, budget - used_total))
        if not piece:
            continue
        label = _label(r)
        parts.append(f"--- HUJJAT: {label} "
                     f"({r.get('page_count') or '?'} sahifa, "
                     f"{r.get('char_count') or 0} belgi) ---\n{piece}")
        used_total += used
        meta["used"].append({
            "name": label,
            "chars_used": used,
            "chars_total": r.get("char_count") or 0,
            "partial": used < (r.get("char_count") or 0),
        })
        if used_total >= budget:
            break

    meta["chars"] = used_total
    meta["truncated"] = any(u["partial"] for u in meta["used"]) or \
        bool(meta.get("skipped_for_budget"))
    return "\n\n".join(parts), meta


def prompt_block(text: str, meta: Dict[str, Any]) -> str:
    """Promptga qo'yiladigan bo'lim — matn + QAMROV OGOHLANTIRISHI.

    Ogohlantirish SHART: modelga "hujjatlar to'liq berildi" degan taassurot
    bersak, u o'qimagan bo'limi haqida ham ishonch bilan gapirardi.
    """
    if not text:
        if meta.get("unreadable"):
            names = ", ".join(u["name"] for u in meta["unreadable"][:5])
            return ("=== BIRIKTIRILGAN HUJJATLAR ===\n"
                    f"Matn ajratib bo'lmadi ({len(meta['unreadable'])} ta fayl: {names}). "
                    "Tahlil FAQAT kartochka ma'lumotiga asoslanadi — buni xulosada ayt.")
        return ""

    warn = [f"Quyida {len(meta['used'])} ta hujjatdan ajratilgan bo'laklar."]

    # IKKI XIL TO'LIQSIZLIK — IKKI XIL JUMLA.
    #
    # O'LCHANGAN NUQSON (2026-09-04). Ikkalasi bitta `truncated`
    # bayrog'iga yig'ilgan va bitta jumla bilan tasvirlangan edi:
    # "hujjatlar TO'LIQ emas — talab o'zaklari atrofidagi bo'laklar
    # olingan". Bu FAQAT birinchisini aytadi.
    #
    #   1. HUJJAT ICHIDA kesilgan (`partial`) — matnning bir qismi;
    #   2. HUJJATNING O'ZI tushib qolgan (`skipped_for_budget`) —
    #      `MAX_DOCS = 8` chegarasidan oshgani.
    #
    # Ikkinchisi aytilmaganda model 8 ta faylni HAMMASI deb o'qiydi.
    # O'lchandi: 96 ta tenderda 8 dan ko'p hujjat bor, eng kattasida
    # 30 ta — ya'ni 22 tasi jimgina tushib qolardi.
    #
    # Umumiy ogohlantirish tuynukni YASHIRARDI: o'qiganda "qamrov
    # haqida aytilgan" degan taassurot beradi, holbuki u boshqa
    # savolga javob beradi (12-sinf).
    if any(u["partial"] for u in meta["used"]):
        warn.append("DIQQAT: olingan hujjatlarning MATNI to'liq emas — "
                    "talab o'zaklari atrofidagi bo'laklar olingan. "
                    "Bo'lakda yo'q narsani \"yo'q\" deb xulosa qilma, "
                    "\"ko'rsatilmagan\" deb yoz.")
    tashlangan = meta.get("skipped_for_budget") or []
    if tashlangan:
        nomlar = ", ".join(str(x) for x in tashlangan[:5])
        warn.append(
            f"DIQQAT: yana {len(tashlangan)} ta hujjat hajm chegarasi "
            f"({MAX_DOCS} fayl) tufayli UMUMAN olinmadi: {nomlar}"
            + (" va boshqalar" if len(tashlangan) > 5 else "")
            + ". Ular o'qilmagan — ularda shart bo'lishi mumkin.")
    if meta.get("unreadable"):
        warn.append(f"Yana {len(meta['unreadable'])} ta fayl umuman o'qilmadi "
                    f"(matn ajratib bo'lmadi).")

    return ("=== BIRIKTIRILGAN HUJJATLAR MATNI ===\n"
            + " ".join(warn) + "\n\n" + text)
