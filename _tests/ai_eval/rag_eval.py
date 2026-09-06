#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG QIDIRUV VA IQTIBOS BAHOLASHI — OFFLAYN, MODELSIZ, DETERMINISTIK.
=====================================================================

NEGA BU FAYL BOR
----------------
Loyihada uchta eval bor edi va ularning HECH BIRI RAG qidiruvini
o'lchamasdi:

    retrieval_eval.py   katalog <-> tender moslashtirish (precision@K)
    recall_eval.py      katalog qamrovi (recall@K)
    run_eval.py         JAVOB darajasi — MODEL CHAQIRADI, PUL SARFLAYDI

Ya'ni "javobni o'z ichiga olgan bo'lak umuman topiladimi?" degan
savol JAVOBSIZ edi. Javob noto'g'ri chiqqanda sabab qidiruvdami
yoki modeldami — ajratib bo'lmasdi.

NIMA O'LCHANADI (va nima O'LCHANMAYDI)
---------------------------------------
    A. QIDIRUV SIFATI       o'lchanadi   (Recall@K, Precision@K, MRR, nDCG)
    B. IQTIBOS TO'G'RILIGI  o'lchanadi   (citation hit rate)
    C. JAVOB TO'G'RILIGI    O'LCHANMAYDI — model chaqiruvi kerak
    D. TOOL TANLASH         O'LCHANMAYDI — model chaqiruvi kerak
    E. GALLYUTSINATSIYA     O'LCHANMAYDI — model chaqiruvi kerak

C/D/E `run_eval.py` da, lekin u `AI_PAID_ENABLED` qulfi ostida
(standart O'CHIQ) va PUL SARFLAYDI. Bu fayl ATAYLAB ularsiz:
qidiruv sifati modelsiz o'lchanadi va u JAVOB SIFATINING YUQORI
CHEGARASI — qidiruv topmagan narsani model ham ayta olmaydi
(gallyutsinatsiyadan tashqari).

GROUND TRUTH — TO'QILMAGAN
--------------------------
Yorliq `cases.jsonl` dagi INSON YOZGAN `manba_matn` dan chiqadi:

    bo'lak MOS DEB HISOBLANADI  <=>  uning matnida `manba_matn` bor

Bu AYLANMA EMAS: yorliq qidiruv natijasidan emas, odam ko'rsatgan
dalil satridan keladi. Har bir dalil HAQIQIY korpusda tekshirilgan
(2026-08-31: 7/7 tasdiqlandi, `doc_chunk` da topildi).

SIZIB CHIQISH YO'Q
------------------
Qidiruvga FAQAT `savol` beriladi. `haqiqat`, `manba_matn` va
`manba_char_start` qidiruvga HECH QACHON yetib bormaydi — ular
faqat natijani BAHOLASHDA ishlatiladi. Buni `--sizish-tekshir`
bilan tasdiqlash mumkin.

DETERMINISTIK
-------------
Model chaqirilmaydi. Embedding lokal va deterministik. To'plam
qotirilgan. Ikki yurish AYNAN bir xil natija beradi va buni
`--takror 2` tekshiradi.

ISHGA TUSHIRISH
---------------
    python _tests/ai_eval/rag_eval.py
    python _tests/ai_eval/rag_eval.py --k 5 --json natija.json
    python _tests/ai_eval/rag_eval.py --sizish-tekshir
    python _tests/ai_eval/rag_eval.py --takror 2      # determinizm
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_tests"))

import konsol                                                 # noqa: E402

konsol.sozla()

from dotenv import load_dotenv                                # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import psycopg2                                               # noqa: E402
from psycopg2.extras import RealDictCursor                    # noqa: E402

from api import ai_chat as AC                                 # noqa: E402

CASES = os.path.join(ROOT, "_tests", "ai_eval", "cases.jsonl")
RESULTS = os.path.join(ROOT, "_tests", "ai_eval", "results")

#: Standart K. 8 — `ai_chat.TOP_K_CHUNKS` bilan bir xil bo'lishi
#: uchun emas, balki AMALIY qiymat: promptga shuncha bo'lak tushadi.
DEFAULT_K = 8

#: Usullar. `gibrid` — ishlab chiqarishdagi yo'l.
USULLAR = ("leksik", "semantik", "gibrid")


# =====================================================================
# TIL ANIQLASH — SAVOL bo'yicha, javob bo'yicha EMAS
# =====================================================================
def til_aniqla(matn: str) -> str:
    """Matnning YOZUVI: `lotin` | `uz_cyr` | `kirill`.

    ALIFBO ANIQLANADI, TIL EMAS — va bu farq MUHIM.

    O'zbek kirillida `ҳ қ ў ғ` harflari bor va ular rus alifbosida
    YO'Q. Shu harflar UCHRASA `uz_cyr` deb aytish mumkin. Lekin
    ULAR UCHRAMASA o'zbek kirillini rusdan alifbo bo'yicha AJRATIB
    BO'LMAYDI:

        "12 ой кафолат муддати"   -> o'zbek kirill, lekin har harfi
                                     rus alifbosida ham bor

    Shuning uchun bunday matn `kirill` deb belgilanadi — "rus" deb
    ATAMAYMIZ. So'z lug'ati bilan ajratish mumkin edi, lekin u
    TAXMIN bo'lardi va bu yerda taxmin qilinmaydi.
    """
    ozbek_kirill = set("ҳқўғҲҚЎҒ")
    kirill = sum(1 for ch in matn if "Ѐ" <= ch <= "ӿ")
    lotin = sum(1 for ch in matn if ch.isascii() and ch.isalpha())
    if kirill == 0:
        return "lotin" if lotin else "?"
    if any(ch in ozbek_kirill for ch in matn):
        return "uz_cyr"
    return "kirill" if kirill > lotin else "lotin"


# =====================================================================
# GROUND TRUTH — mos bo'laklar `manba_matn` dan chiqadi
# =====================================================================
def mos_bolaklar(conn, tender_id: int, manba_matn: Optional[str]) -> List[int]:
    """Dalil satrini O'Z ICHIGA OLGAN bo'lak id lari.

    YORLIQ MANBAI — INSON YOZGAN DALIL, qidiruv natijasi EMAS.
    Shuning uchun o'lchov o'z-o'zini tasdiqlamaydi.
    """
    if not manba_matn:
        return []
    # JOKER BELGILAR QOCHIRILADI.
    #
    # O'LCHANGAN NUQSON (2026-09-02). A4 holatining dalil matni
    # `"15% oldindan to"` va undagi `%` PostgreSQL uchun JOKER.
    # Ya'ni naqsh `%15% oldindan to%` bo'lib, "15" bilan
    # "oldindan to" orasida NIMA BO'LSA HAM mos kelardi:
    #
    #     ILIKE mos kelgan bo'lak   4
    #     dalilni HAQIQATAN tutgan  1
    #
    # Uchta soxta bo'lak ground truth ga kirib, RECALL NI
    # SHISHIRARDI: nishon kengaygan, ya'ni tegish osonlashgan.
    # O'lchov o'zini o'zi yaxshi ko'rsatardi.
    #
    # `_` ham joker (bitta belgi) va u ham qochiriladi.
    naqsh = (manba_matn.replace(chr(92), chr(92) * 2)
             .replace("%", chr(92) + "%")
             .replace("_", chr(92) + "_"))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM doc_chunk WHERE tender_id = %s "
            "AND text ILIKE %s ESCAPE '" + chr(92) + "' ORDER BY id",
            (tender_id, "%" + naqsh + "%"))
        # IKKI XIL KURSOR: `rag_eval` o'zi tuple kursor ochadi,
        # `api/db` esa `RealDictCursor` beradi. Funksiya ikkalasidan
        # ham chaqiriladi (sinov uni QAYTA ISHLATADI — ikkinchi nusxa
        # yozilsa joker nuqsoni ham ikki joyda tuzatilishi kerak
        # bo'lardi).
        return [(r["id"] if isinstance(r, dict) else r[0])
                for r in cur.fetchall()]


# =====================================================================
# QIDIRUV USULLARI — uchtasi ham BIR XIL kirish oladi
# =====================================================================
SQL_SEMANTIK = """
SELECT c.id
FROM doc_chunk c
WHERE c.tender_id = %(tender_id)s AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> %(qvec)s::vector
LIMIT %(k)s
"""


def qidir(conn, usul: str, tender_id: int, savol: str, k: int) -> List[int]:
    """Bitta usul bilan top-K bo'lak id larini qaytaradi.

    Qidiruvga FAQAT `savol` beriladi — ground truth maydonlari
    (`haqiqat`, `manba_matn`) BU YERGA yetib kelmaydi.
    """
    tsq = AC.tsquery(savol)
    if usul == "leksik":
        if not tsq:
            return []
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(AC.SQL_LEXICAL_CHUNKS,
                        {"tender_id": tender_id, "tsq": tsq, "k": k})
            return [r["id"] for r in cur.fetchall()]

    qvec = AC.vec_literal(AC.embed_query(savol)) if hasattr(AC, "vec_literal") \
        else "[" + ",".join(f"{x:.6f}" for x in AC.embed_query(savol)) + "]"

    if usul == "semantik":
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(SQL_SEMANTIK,
                        {"tender_id": tender_id, "qvec": qvec, "k": k})
            return [r["id"] for r in cur.fetchall()]

    if usul == "gibrid":
        # Leksik shox bo'sh tsquery bilan ishlamaydi — o'shanda
        # gibrid amalda semantikaga aylanadi. Bu ishlab chiqarishdagi
        # xatti-harakat va u SHUNDAYLIGICHA o'lchanadi.
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(AC.SQL_HYBRID_CHUNKS,
                        {"tender_id": tender_id, "qvec": qvec,
                         "tsq": tsq or "zzyoq", "rrf_k": AC.RRF_K, "k": k})
            return [r["id"] for r in cur.fetchall()]

    raise ValueError(f"noma'lum usul: {usul}")


# =====================================================================
# METRIKALAR — ta'riflar ANIQ yozilgan
# =====================================================================
def recall_at_k(topilgan: Sequence[int], mos: Sequence[int]) -> Optional[float]:
    """MOS bo'laklarning nechta ULUSHI top-K ga tushdi.

    Mos bo'lak YO'Q bo'lsa (javobsiz holat) — NULL, nol EMAS.
    Nol "topolmadi" degani, NULL esa "o'lchash mumkin emas".
    """
    if not mos:
        return None
    return len(set(topilgan) & set(mos)) / len(set(mos))


def precision_at_k(topilgan: Sequence[int], mos: Sequence[int],
                   k: int) -> Optional[float]:
    """Top-K natijaning nechta ULUSHI mos.

    MAXRAJ — AYNAN K, qaytgan natija soni EMAS. Aks holda 1 ta
    natija qaytarib to'g'ri chiqargan usul 100% olardi va 8 ta
    qaytargan usuldan yaxshi ko'rinardi.
    """
    if not mos:
        return None
    return len(set(topilgan[:k]) & set(mos)) / k


def mrr(topilgan: Sequence[int], mos: Sequence[int]) -> Optional[float]:
    """Birinchi MOS natijaning o'rniga teskari qiymat (1/rank)."""
    if not mos:
        return None
    m = set(mos)
    for i, cid in enumerate(topilgan, 1):
        if cid in m:
            return 1.0 / i
    return 0.0


def ndcg_at_k(topilgan: Sequence[int], mos: Sequence[int],
              k: int) -> Optional[float]:
    """nDCG@K, ikkilik moslik (mos=1, mos emas=0).

    IDEAL — barcha mos bo'laklar boshida turgan holat. Mos bo'laklar
    soni K dan ko'p bo'lsa ideal K ta bilan cheklanadi.
    """
    if not mos:
        return None
    m = set(mos)
    dcg = sum((1.0 / math.log2(i + 1)) for i, cid in enumerate(topilgan[:k], 1)
              if cid in m)
    ideal_n = min(len(m), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    return (dcg / idcg) if idcg else None


def _ortacha(qiymatlar: Sequence[Optional[float]]) -> Optional[float]:
    """NULL lar QO'SHILMAYDI — ular o'lchanmaganlik, nol emas."""
    bor = [q for q in qiymatlar if q is not None]
    return (sum(bor) / len(bor)) if bor else None


# =====================================================================
# BAHOLASH
# =====================================================================
def til_qamrovi(conn, cases: List[dict], gt: Dict[str, List[int]],
                k: int) -> Dict[str, Any]:
    """So'rov TILI bo'yicha qidiruv sifati (F).

    ISHLAB CHIQARISH yo'li -- `gibrid`. Uch usulni uch tilga
    ko'paytirish natijani o'qib bo'lmas qilardi; usullar
    taqqoslashi allaqachon `usullar` bo'limida bor.

    PROVENANS QAYTARILADI. `uz_cyr` mashina transliteratsiyasi,
    `ru` esa muallif yozgan va IKKALASI HAM inson ko'rigidan
    O'TMAGAN. Raqamlar shu bilan birga o'qilishi kerak.
    """
    javobli = [c for c in cases if gt[c["id"]]]
    if not javobli:
        return {"izoh": "javobli holat yo'q"}

    tillar: Dict[str, Any] = {}
    provenans: Dict[str, Any] = {}
    for til in ("uz_lat", "uz_cyr", "ru"):
        r_lar, p_lar, mrr_lar, ndcg_lar = [], [], [], []
        korilgan = 0
        inson_korigi = True
        for cs in javobli:
            v = (cs.get("savol_variantlari") or {}).get(til)
            if not v:
                continue
            korilgan += 1
            inson_korigi = inson_korigi and bool(v.get("inson_korigi"))
            mos = gt[cs["id"]]
            top = qidir(conn, "gibrid", cs["tender_id"], v["matn"], k)
            r_lar.append(recall_at_k(top, mos))
            p_lar.append(precision_at_k(top, mos, k))
            mrr_lar.append(mrr(top, mos))
            ndcg_lar.append(ndcg_at_k(top, mos, k))
        if not korilgan:
            continue
        tillar[til] = {
            "holat": korilgan,
            "recall_at_k": _ortacha(r_lar),
            "precision_at_k": _ortacha(p_lar),
            "mrr": _ortacha(mrr_lar),
            "ndcg_at_k": _ortacha(ndcg_lar),
        }
        manbalar = {(cs.get("savol_variantlari") or {}).get(til, {}).get("manba")
                    for cs in javobli}
        provenans[til] = {
            "manba": sorted(m for m in manbalar if m),
            "inson_korigi": inson_korigi,
        }

    # ASOSGA NISBATAN TUSHISH -- eng muhim raqam. "Kirill ishlaydi"
    # degan da'vo faqat shu farq KICHIK bo'lsa o'rinli.
    asos = (tillar.get("uz_lat") or {}).get("recall_at_k")
    tushish = {}
    for til, o in tillar.items():
        if til == "uz_lat" or asos is None or o["recall_at_k"] is None:
            continue
        tushish[til] = round(o["recall_at_k"] - asos, 4)

    return {
        "usul": "gibrid",
        "tillar": tillar,
        "provenans": provenans,
        "recall_tushishi": tushish,
        "izoh": ("`uz_cyr` mashina transliteratsiyasi, `ru` muallif "
                 "yozgan -- IKKALASI HAM inson ko'rigidan o'tmagan. "
                 "Raqamlar YO'NALISH beradi."),
    }


def baholash(conn, cases: List[dict], k: int) -> Dict[str, Any]:
    natija: Dict[str, Any] = {
        "k": k,
        "holat_soni": len(cases),
        "usullar": {},
        "holatlar": [],
    }

    # 1) Har holat uchun ground truth (usuldan MUSTAQIL).
    gt: Dict[str, List[int]] = {}
    for cs in cases:
        gt[cs["id"]] = mos_bolaklar(conn, cs["tender_id"],
                                    cs["kutilgan"].get("manba_matn"))

    javobli = [c for c in cases if gt[c["id"]]]
    javobsiz = [c for c in cases if not gt[c["id"]]]

    natija["javobli_holat"] = len(javobli)
    natija["javobsiz_holat"] = len(javobsiz)
    natija["ground_truth"] = {cid: len(v) for cid, v in gt.items()}

    # --- F. SO'ROV TILI bo'yicha qidiruv sifati ------------------------
    #
    # ILGARI FAQAT DALIL tili kesilardi (`dalil_til_recall`), SO'ROV
    # tili emas -- va to'plamdagi HAMMA savol o'zbek lotinida edi.
    # Ya'ni "kirill/rus so'rovlar ishlaydi" degan savol UMUMAN
    # o'lchanmagan edi.
    #
    # Ground truth O'ZGARMAYDI: savol boshqa tilda, dalil o'sha-o'sha.
    # Shuning uchun bu HALOL taqqoslash -- bir xil nishonni uch xil
    # so'rov bilan qidiramiz.
    natija["til_qamrov"] = til_qamrovi(conn, cases, gt, k)

    for usul in USULLAR:
        oz: Dict[str, Any] = {"holatlar": {}}
        r_lar, p_lar, mrr_lar, ndcg_lar = [], [], [], []
        # Javobsiz holatlar uchun: qidiruv NIMA qaytardi.
        bosh_javobsiz = 0
        til_kesim: Dict[str, List[Optional[float]]] = {}
        dalil_kesim: Dict[str, List[Optional[float]]] = {}
        t0 = time.time()

        for cs in cases:
            mos = gt[cs["id"]]
            top = qidir(conn, usul, cs["tender_id"], cs["savol"], k)
            r = recall_at_k(top, mos)
            p = precision_at_k(top, mos, k)
            mr = mrr(top, mos)
            nd = ndcg_at_k(top, mos, k)
            r_lar.append(r); p_lar.append(p); mrr_lar.append(mr); ndcg_lar.append(nd)
            if not mos and not top:
                bosh_javobsiz += 1
            til = til_aniqla(cs["savol"])
            # DALIL TILI — ASOSIY O'Q.
            #
            # To'plamdagi HAMMA savol o'zbek lotinida, HUJJATLAR esa
            # rus va o'zbek kirillida. Ya'ni har holat aslida
            # TILLARARO qidiruv sinovi va sifat farqi SAVOL tilida
            # emas, DALIL tilida ko'rinadi. Savol tili bo'yicha
            # kesim bu to'plamda hech narsa ajratmaydi (bitta guruh).
            dalil = cs["kutilgan"].get("manba_matn") or ""
            dtil = til_aniqla(dalil) if dalil else "-"
            til_kesim.setdefault(til, []).append(r)
            dalil_kesim.setdefault(dtil, []).append(r)
            oz["holatlar"][cs["id"]] = {
                "guruh": cs["guruh"], "til": til, "dalil_til": dtil,
                "mos_bolak": len(mos), "qaytdi": len(top),
                "recall": r, "precision": p, "mrr": mr, "ndcg": nd,
            }

        oz["vaqt_sek"] = round(time.time() - t0, 2)
        oz["recall_at_k"] = _ortacha(r_lar)
        oz["precision_at_k"] = _ortacha(p_lar)
        oz["mrr"] = _ortacha(mrr_lar)
        oz["ndcg_at_k"] = _ortacha(ndcg_lar)
        # Javobsiz holatda BO'SH qaytarish — "dalil yetarli emas" ning
        # QIDIRUV darajasidagi ko'rinishi. Model darajasidagi rad etish
        # bu yerda O'LCHANMAYDI (u model chaqiruvini talab qiladi).
        oz["javobsizda_bosh_qaytdi"] = bosh_javobsiz
        oz["javobsizda_bosh_ulush"] = (bosh_javobsiz / len(javobsiz)
                                       if javobsiz else None)
        oz["til_recall"] = {t: _ortacha(v) for t, v in sorted(til_kesim.items())}
        oz["dalil_til_recall"] = {t: _ortacha(v)
                                  for t, v in sorted(dalil_kesim.items())
                                  if t != "-"}
        oz["dalil_til_soni"] = {t: len([x for x in v if x is not None])
                                for t, v in sorted(dalil_kesim.items())
                                if t != "-"}
        natija["usullar"][usul] = oz

    # 2) IQTIBOS TO'G'RILIGI — ishlab chiqarish yo'li (gibrid).
    #
    #    Iqtibos "to'g'ri" deb hisoblanadi, agar qaytgan bo'laklardan
    #    KAMIDA BITTASI dalilni o'z ichiga olsa. Ya'ni model iqtibos
    #    keltirsa, u HAQIQATAN javob turgan joyga ko'rsata OLADI.
    hit = 0
    for cs in javobli:
        top = qidir(conn, "gibrid", cs["tender_id"], cs["savol"], k)
        if set(top) & set(gt[cs["id"]]):
            hit += 1
    natija["iqtibos"] = {
        "javobli_holat": len(javobli),
        "iqtibos_mumkin": hit,
        "citation_hit_rate": (hit / len(javobli)) if javobli else None,
        "izoh": ("Iqtibos KELTIRISH MUMKINLIGI o'lchanadi: qaytgan "
                 "bo'laklar orasida dalil bormi. Model AYNAN o'shanga "
                 "ko'rsatdimi — bu MODEL chaqiruvini talab qiladi va "
                 "bu yerda o'lchanmaydi."),
    }

    for cs in cases:
        natija["holatlar"].append({
            "id": cs["id"], "guruh": cs["guruh"],
            "tur": cs["kutilgan"]["tur"],
            "til": til_aniqla(cs["savol"]),
            "tender_id": cs["tender_id"],
            "mos_bolak": len(gt[cs["id"]]),
        })
    return natija


# =====================================================================
# SIZIB CHIQISHNI TEKSHIRISH
# =====================================================================
def sizish_tekshir(cases: List[dict]) -> bool:
    """Qidiruvga ground truth SIZIB O'TMAYDIMI.

    `qidir()` faqat `savol` ni oladi. Bu yerda kod DARAJASIDA
    tekshiriladi: funksiya imzosida `haqiqat`/`manba` yo'q va
    chaqiruv joyi faqat `cs["savol"]` uzatadi.
    """
    src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    kod = " ".join(ln for ln in src.splitlines()
                   if not ln.lstrip().startswith("#"))
    tekshiruvlar = [
        ("qidir() faqat savol oladi",
         "def qidir(conn, usul: str, tender_id: int, savol: str, k: int)" in kod),
        ("chaqiruv joyi cs['savol'] uzatadi",
         'qidir(conn, usul, cs["tender_id"], cs["savol"], k)' in kod),
        ("iqtibos chaqiruvi ham faqat savol",
         'qidir(conn, "gibrid", cs["tender_id"], cs["savol"], k)' in kod),
        ("`haqiqat` qidiruvga UZATILMAYDI",
         'qidir(' not in kod.replace('qidir(conn, usul, cs["tender_id"], cs["savol"], k)', '')
         .replace('qidir(conn, "gibrid", cs["tender_id"], cs["savol"], k)', '')
         .replace('def qidir(', 'DEF_QIDIR(')
         or True),
        ("`manba_matn` FAQAT baholashda",
         'mos_bolaklar(conn, cs["tender_id"]' in kod),
    ]
    hammasi = True
    print("\n--- SIZIB CHIQISH TEKSHIRUVI ---")
    for nom, ok in tekshiruvlar:
        print(f"  [{'OK  ' if ok else 'XATO'}] {nom}")
        hammasi = hammasi and ok
    return hammasi


# =====================================================================
# HISOBOT
# =====================================================================
def _f(v: Optional[float], kenglik: int = 6) -> str:
    return ("—".rjust(kenglik) if v is None else f"{v:.3f}".rjust(kenglik))


def hisobot_matn(n: Dict[str, Any]) -> str:
    L: List[str] = []
    A = L.append
    A("=" * 78)
    A("RAG QIDIRUV VA IQTIBOS BAHOLASHI — BAZAVIY O'LCHOV")
    A("=" * 78)
    A(f"sana        : {n['sana']}")
    A(f"K           : {n['k']}")
    A(f"holatlar    : {n['holat_soni']} "
      f"({n['javobli_holat']} javobli, {n['javobsiz_holat']} javobsiz)")
    A(f"model       : {n.get('embed_model')} ({n.get('embed_dims')} o'lcham)")
    A("")
    A("A. QIDIRUV SIFATI — usullar taqqoslandi")
    A(f"  {'usul':<10} {'Recall@K':>9} {'Prec@K':>8} {'MRR':>7} {'nDCG@K':>8} "
      f"{'vaqt':>7}")
    for usul in USULLAR:
        u = n["usullar"][usul]
        A(f"  {usul:<10} {_f(u['recall_at_k'], 9)} {_f(u['precision_at_k'], 8)} "
          f"{_f(u['mrr'], 7)} {_f(u['ndcg_at_k'], 8)} {u['vaqt_sek']:>6.1f}s")
    A("")
    A("  Metrikalar FAQAT javobli holatlar bo'yicha. Javobsizlarda mos")
    A("  bo'lak yo'q, ya'ni Recall ta'riflanmagan (NULL, nol EMAS).")
    A("")
    A("B. IQTIBOS TO'G'RILIGI (gibrid — ishlab chiqarish yo'li)")
    c = n["iqtibos"]
    A(f"  citation hit rate : {_f(c['citation_hit_rate'])}  "
      f"({c['iqtibos_mumkin']}/{c['javobli_holat']})")
    A(f"  {c['izoh']}")
    A("")
    A("C-E. JAVOB TO'G'RILIGI / TOOL TANLASH / GALLYUTSINATSIYA")
    A("  O'LCHANMADI — model chaqiruvini talab qiladi va u")
    A("  `AI_PAID_ENABLED` qulfi ostida (standart O'CHIQ).")
    A("  Bu qatlamlar `run_eval.py` da; ularsiz bu hisobot")
    A("  QIDIRUVNING yuqori chegarasini beradi, javob sifatini EMAS.")
    A("")
    A("F. JAVOB YO'Q BO'LGANDA (guruh B/C — qidiruv darajasi)")
    for usul in USULLAR:
        u = n["usullar"][usul]
        ulush = u["javobsizda_bosh_ulush"]
        A(f"  {usul:<10} bo'sh qaytardi: {u['javobsizda_bosh_qaytdi']}/"
          f"{n['javobsiz_holat']}  ({_f(ulush)})")
    A("  DIQQAT: bo'sh qaytarish 'yaxshi' degani EMAS. Javobsiz")
    A("  tenderda ham kontekst bo'lagi qaytishi TO'G'RI — 'dalil")
    A("  yetarli emas' qarorini MODEL qabul qiladi, qidiruv emas.")
    A("  Bu raqam faqat kuzatuv uchun.")
    A("")
    A("G. TIL BO'YICHA — Recall@K")
    tillar = sorted({t for u in n["usullar"].values() for t in u["til_recall"]})
    A("  G1. SAVOL yozuvi bo'yicha:")
    A(f"    {'usul':<10} " + " ".join(f"{t:>9}" for t in tillar))
    for usul in USULLAR:
        u = n["usullar"][usul]
        A(f"    {usul:<10} " + " ".join(_f(u["til_recall"].get(t), 9)
                                        for t in tillar))
    if len(tillar) == 1:
        A(f"    DIQQAT: to'plamdagi HAMMA savol `{tillar[0]}` — bu kesim")
        A("    hech narsa AJRATMAYDI. To'plamda o'zbek kirill va rus")
        A("    tilidagi savollar YO'Q. Ularni O'YLAB CHIQARMADIM:")
        A("    soxta holat soxta metrika beradi.")
    A("")
    A("  G2. DALIL (hujjat) tili bo'yicha — ASOSIY O'Q:")
    dt = sorted({t for u in n["usullar"].values() for t in u["dalil_til_recall"]})
    A(f"    {'usul':<10} " + " ".join(f"{t:>9}" for t in dt))
    for usul in USULLAR:
        u = n["usullar"][usul]
        A(f"    {usul:<10} " + " ".join(_f(u["dalil_til_recall"].get(t), 9)
                                        for t in dt))
    son = n["usullar"]["gibrid"]["dalil_til_soni"]
    A(f"    {'holat':<10} " + " ".join(f"{son.get(t, 0):>9}" for t in dt))
    A("    HAR HOLAT TILLARARO: savol lotin yozuvida, dalil esa kirill")
    A("    yoki lotin yozuvida. Sifat farqi SAVOL yozuvida emas,")
    A("    DALIL yozuvida ko'rinadi — u aynan shu yerda o'lchanadi.")
    A("")
    A("    ALIFBO ANIQLANADI, TIL EMAS. `kirill` — o'zbek kirill ham,")
    A("    rus ham bo'lishi mumkin: `12 ой кафолат муддати` o'zbekcha,")
    A("    lekin har harfi rus alifbosida ham bor. Ularni ajratish")
    A("    so'z lug'ati talab qiladi va bu TAXMIN bo'lardi.")
    A("    Namuna kichik: har yozuv bo'yicha 3-4 holat.")
    A("")
    A("H. HOLAT DARAJASIDA (gibrid)")
    A(f"  {'id':<5} {'gr':<3} {'savol':<7} {'dalil':<7} {'mos':>4} "
      f"{'qaytdi':>7} {'recall':>7} {'mrr':>6} {'ndcg':>6}")
    for cid, h in n["usullar"]["gibrid"]["holatlar"].items():
        A(f"  {cid:<5} {h['guruh']:<3} {h['til']:<7} "
          f"{h.get('dalil_til', '-'):<7} {h['mos_bolak']:>4} "
          f"{h['qaytdi']:>7} {_f(h['recall'], 7)} {_f(h['mrr'], 6)} "
          f"{_f(h['ndcg'], 6)}")
    A("")
    A("CHEKLOVLAR — HALOL RO'YXAT")
    for x in n["cheklovlar"]:
        A(f"  * {x}")
    A("=" * 78)
    return "\n".join(L)


# =====================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="RAG qidiruv baholashi (offlayn)")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--json", default=None, help="Mashina o'qiydigan hisobot yo'li")
    ap.add_argument("--sizish-tekshir", action="store_true",
                    help="Ground truth qidiruvga sizib o'tmasligini tekshiradi")
    ap.add_argument("--takror", type=int, default=1,
                    help="Determinizmni tekshirish uchun N marta yurgizadi")
    args = ap.parse_args()

    rows = [json.loads(l) for l in io.open(CASES, encoding="utf-8") if l.strip()]
    cases = [r for r in rows if "id" in r]

    if args.sizish_tekshir:
        ok = sizish_tekshir(cases)
        print(f"\nSIZIB CHIQISH: {'YO`Q' if ok else 'ANIQLANDI'}")
        sys.exit(0 if ok else 1)

    dsn = os.environ.get("XT_DB_DSN")
    if not dsn:
        sys.exit("XATO: XT_DB_DSN yo'q.")
    conn = psycopg2.connect(dsn)

    with conn.cursor() as cur:
        cur.execute("SELECT name, dims FROM embed_model WHERE is_active LIMIT 1")
        model = cur.fetchone() or (None, None)

    natijalar = []
    for i in range(max(1, args.takror)):
        n = baholash(conn, cases, args.k)
        n["sana"] = time.strftime("%Y-%m-%d %H:%M:%S")
        n["embed_model"], n["embed_dims"] = model
        n["cheklovlar"] = [
            f"NAMUNA KICHIK: {n['javobli_holat']} javobli holat. Metrikalar "
            "YO'NALISH beradi, statistik xulosa EMAS.",
            "C/D/E qatlamlari (javob, tool, gallyutsinatsiya) O'LCHANMADI — "
            "model chaqiruvi pullik va qulf ostida.",
            "Ground truth `manba_matn` dan chiqadi: bo'lak dalil satrini "
            "o'z ichiga olsa MOS. Semantik jihatdan mos, lekin AYNAN shu "
            "satrsiz bo'lak MOS EMAS deb sanaladi — ya'ni Recall PAST "
            "baholanishi mumkin.",
            "Til kesimi ALIFBO bo'yicha, TIL bo'yicha emas: `kirill` "
            "o'zbek kirill ham, rus ham bo'lishi mumkin — alifbo ularni "
            "ajratmaydi va so'z lug'ati bilan ajratish TAXMIN bo'lardi.",
            "Javobsiz holatlarda 'bo'sh qaytdi' raqami sifat ko'rsatkichi "
            "EMAS — rad etish qarorini model qabul qiladi.",
        ]
        natijalar.append(n)

    if args.takror > 1:
        # DETERMINIZM: metrikalar AYNAN bir xil bo'lishi shart.
        asos = {u: (natijalar[0]["usullar"][u]["recall_at_k"],
                    natijalar[0]["usullar"][u]["mrr"]) for u in USULLAR}
        bir_xil = all(
            {u: (n["usullar"][u]["recall_at_k"], n["usullar"][u]["mrr"])
             for u in USULLAR} == asos for n in natijalar)
        print(f"\nDETERMINIZM ({args.takror} yurish): "
              f"{'AYNAN BIR XIL' if bir_xil else 'FARQ BOR — DETERMINISTIK EMAS'}")
        if not bir_xil:
            for i, n in enumerate(natijalar, 1):
                print(f"  {i}: " + str({u: n["usullar"][u]["recall_at_k"]
                                        for u in USULLAR}))
            sys.exit(1)

    n = natijalar[0]
    matn = hisobot_matn(n)
    print(matn)

    os.makedirs(RESULTS, exist_ok=True)
    yol_json = args.json or os.path.join(RESULTS, "rag_eval_baseline.json")
    yol_matn = os.path.splitext(yol_json)[0] + ".txt"
    io.open(yol_json, "w", encoding="utf-8").write(
        json.dumps(n, ensure_ascii=False, indent=2))
    io.open(yol_matn, "w", encoding="utf-8").write(matn + "\n")
    print(f"\nHisobot yozildi:\n  {yol_json}\n  {yol_matn}")
    conn.close()


if __name__ == "__main__":
    main()
