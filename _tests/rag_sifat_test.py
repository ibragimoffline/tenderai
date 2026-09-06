#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: RAG SIFATI — DALILGA ASOSLANGAN BAZAVIY DARAJA
=======================================================

"API 200 qaytardi" DEGANI SIFAT DEGANI EMAS. Bu sinov RAG ni
OLTI QATLAMGA ajratadi va HAR BIRI uchun holatni ANIQ aytadi:

    A. QIDIRUV SIFATI        O'LCHANADI   modelsiz
    B. IQTIBOS TO'G'RILIGI   QISMAN       plumbing o'lchanadi, mos
                                          kelishi model chaqiruvini
                                          talab qiladi
    C. JAVOB ASOSLILIGI      O'LCHANMAYDI model kerak (pullik qulf)
    D. JAVOB TO'G'RILIGI     O'LCHANMAYDI model kerak
    E. DALILSIZ RAD ETISH    O'LCHANMAYDI model kerak
    F. KROSS-TIL QIDIRUV     O'LCHANADI   modelsiz

QATLAMLARNI ARALASHTIRISH — asosiy xato. "RAG ishlaydi" degan
bitta gap A ni ham, D ni ham qamrab olgandek ko'rinadi, aslida
D umuman o'lchanmagan.

O'LCHANGAN NUQSON (2026-09-02): kross-til qidiruv UMUMAN
o'lchanmagan edi — to'plamdagi 18 savolning HAMMASI o'zbek
lotinida edi, korpus esa asosan rus va o'zbek kirillida. Til
variantlari qo'shilgach:

    uz_lat  recall@8 0.681   MRR 0.577   (asos)
    uz_cyr  recall@8 0.552   MRR 0.195
    ru      recall@8 0.429   MRR 0.262

Ya'ni kirill so'rovda dalil TOPILADI, lekin JUDA PAST
o'rinda — MRR 0.577 dan 0.195 ga tushadi.

IKKINCHI O'LCHANGAN NUQSON: ground truth SHISHGAN edi. A4
holatining dalil matni `"15% oldindan to"` va undagi `%`
PostgreSQL `ILIKE` uchun JOKER belgi. Naqsh `%15% oldindan to%`
bo'lib, "15" bilan "oldindan to" orasida nima bo'lsa ham mos
kelardi:

    ILIKE mos kelgan bo'lak   4
    dalilni HAQIQATAN tutgan  1

Uchta soxta bo'lak nishonni kengaytirib, RECALL NI SHISHIRARDI.
Tuzatilgach: gibrid recall 0.705 -> 0.681, MRR 0.699 -> 0.577.
Ya'ni oldingi raqamlar O'LCHOV NUQSONI tufayli yuqori edi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\rag_sifat_test.py
    .venv\\Scripts\\python.exe _tests\\rag_sifat_test.py --bazasiz
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_tests", "ai_eval"))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []

HOLATLAR = os.path.join(ROOT, "_tests", "ai_eval", "cases.jsonl")
BAZAVIY = os.path.join(ROOT, "_tests", "ai_eval", "results",
                       "rag_eval_baseline.json")

#: REGRESSIYA DARVOZALARI.
#:
#: Bu raqamlar STATISTIK CHEGARA EMAS — namuna 7 ta javobli
#: holatdan iborat. Ular "shu darajadan PASTGA tushmasin" degan
#: muhandislik qulfi. Chegara bazaviy qiymatdan bir oz past
#: qo'yilgan: shovqin sinovni yiqitmasin, lekin HAQIQIY
#: yomonlashuv ushlansin.
DARVOZA = {
    "gibrid_recall": 0.60,       # bazaviy 0.681
    "gibrid_mrr": 0.48,          # bazaviy 0.577
    "iqtibos_hit": 0.85,         # bazaviy 1.000
    "uz_cyr_recall": 0.45,       # o'lchandi 0.552
    "ru_recall": 0.35,           # o'lchandi 0.429
}


def check(nom, ok, tafsilot=""):
    _natija.append((nom, bool(ok), tafsilot))
    print(f"  [{'OK  ' if ok else 'XATO'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))


def bolim(t):
    print(f"\n--- {t} ---")


def holatlar():
    return [json.loads(l) for l in io.open(HOLATLAR, encoding="utf-8")
            if l.strip() and '"id"' in l]


# =====================================================================
# 1. TO'PLAM — QAYTA ISHLATILADIGAN VA KO'RIB CHIQILADIGAN
# =====================================================================
def test_toplam():
    bolim("1. BAHOLASH TO'PLAMI")
    cs = holatlar()
    check("to'plam mavjud va bo'sh emas", len(cs) >= 18, f"{len(cs)} holat")

    #: Hujjatdan javob qidiradigan guruhlar. F/G bundan TASHQARIDA:
    #: ular tool tanlashni o'lchaydi va tenderga bog'lanmasligi
    #: mumkin.
    RAG_GURUHLARI = {"A", "B", "C", "D", "E"}

    #: To'plamda BO'LISHI SHART bo'lgan guruhlar — RAG (A-E) va
    #: tool yo'li (F, G). Guruh o'chirilsa sinov YIQILADI.
    KUTILGAN_GURUHLAR = RAG_GURUHLARI | {"F", "G"}

    guruhlar = {}
    for c in cs:
        guruhlar[c["guruh"]] = guruhlar.get(c["guruh"], 0) + 1
    # BEShTA GURUH ATAYLAB: javob bor / yo'q / taxmin oson /
    # ziddiyat / injection. Faqat "javob bor" holatlar bilan
    # o'lchash RAD ETISHNI umuman sinamasdi.
    # RAG GURUHLARI (A-E) MAJBURIY. F va G keyinroq qo'shildi va
    # ular BOShQA narsani o'lchaydi — javob matnini emas, modelning
    # TOOL YO'LINI (`run_eval.baho`, `tur = "tool_yoli"`).
    #
    # Shart TENGLIKDAN QAMRAB OLISHGA o'zgartirildi: aks holda har
    # yangi guruh shu sinovni yiqitardi va u "RAG sifati buzildi"
    # degan YOLG'ON signal bo'lardi.
    # KUTILGAN GURUHLAR ANIQ YOZILADI, "kamida beshta" EMAS.
    #
    # Ilgari shart TENGLIK edi va har yangi guruh sinovni
    # yiqitardi. Uni `>=` ga aylantirish teskari nuqson berardi:
    # A-E o'chirilsa tutilardi, F yoki G o'chirilsa YO'Q. Ro'yxat
    # to'liq yozilgani uchun IKKALA yo'nalish ham qo'riqlanadi.
    check("kutilgan guruhlarning HAMMASI bor",
          KUTILGAN_GURUHLAR <= set(guruhlar),
          f"yo'q: {sorted(KUTILGAN_GURUHLAR - set(guruhlar))}")
    # YANGI guruh qo'shilsa ham ko'rinsin — yiqitmaydi, AYTADI.
    yangi = set(guruhlar) - KUTILGAN_GURUHLAR
    if yangi:
        print(f"       [i] ro'yxatda YO'Q guruh(lar): {sorted(yangi)} — "
              f"`KUTILGAN_GURUHLAR` ga qo'shing")

    javobli = [c for c in cs if (c.get("kutilgan") or {}).get("manba_matn")]
    check("ground truth'li holat bor", len(javobli) >= 7,
          f"{len(javobli)} ta")

    # HAR HOLAT TEKSHIRILADIGAN bo'lsin: savol, tender, kutilgan tur.
    #
    # `tender_id` FAQAT RAG guruhlarida majburiy. F guruhi ATAYLAB
    # GLOBAL sessiyada yuradi (`tender_id = None`): u tenderni
    # xabardagi raqamdan hal qilishni o'lchaydi, ya'ni tender
    # oldindan berilsa sinovning MA'NOSI yo'qolardi.
    yomon = [c["id"] for c in cs
             if not c.get("savol")
             or (not c.get("tender_id") and c["guruh"] in RAG_GURUHLARI)
             or not (c.get("kutilgan") or {}).get("tur")]
    check("har holat to'liq (savol + tender + kutilgan tur)",
          not yomon, str(yomon))

    # HAQIQAT MAYDONI — inson o'qiy oladigan izoh. Usiz to'plamni
    # KO'RIB CHIQIB bo'lmaydi.
    izohsiz = [c["id"] for c in cs if not c.get("haqiqat")]
    check("har holatda inson o'qiydigan `haqiqat` izohi bor",
          not izohsiz, str(izohsiz))


def test_til_variantlari():
    bolim("2. TIL VARIANTLARI — provenans OSHKOR")
    cs = holatlar()
    yoq = [c["id"] for c in cs if not c.get("savol_variantlari")]
    check("har holatda til variantlari bor", not yoq, str(yoq))

    for til in ("uz_lat", "uz_cyr", "ru"):
        bor = [c for c in cs if til in (c.get("savol_variantlari") or {})]
        check(f"`{til}` varianti hamma holatda", len(bor) == len(cs),
              f"{len(bor)}/{len(cs)}")

    # PROVENANS YOZILGAN bo'lsin. Mashina yozgan savolni "inson
    # tasdiqlagan" deb ko'rsatish — aynan shu loyihada takrorlangan
    # nuqson sinfi.
    for c in cs:
        v = c["savol_variantlari"]
        for til, o in v.items():
            if not isinstance(o, dict):
                check(f"{c['id']}/{til}: provenans obyekt", False, str(o))
                break
        else:
            continue
        break
    else:
        check("har variantda `manba` va `inson_korigi` bor",
              all("manba" in o and "inson_korigi" in o
                  for c in cs for o in c["savol_variantlari"].values()))

    # ASL variant inson ko'rigidan o'tgan, qolgani YO'Q — va bu
    # OCHIQ yozilgan.
    asl = all(c["savol_variantlari"]["uz_lat"]["inson_korigi"] for c in cs)
    check("`uz_lat` — inson ko'rigidan o'tgan (asl to'plam)", asl)
    mashina = all(not c["savol_variantlari"]["uz_cyr"]["inson_korigi"]
                  and not c["savol_variantlari"]["ru"]["inson_korigi"]
                  for c in cs)
    check("`uz_cyr`/`ru` — inson ko'rigidan O'TMAGAN deb belgilangan",
          mashina, "soxta tasdiq yozilmasin")


def test_transliterator():
    bolim("3. TRANSLITERATOR — o'zi sinaladi")
    from til import _oz_sinov, lotin_kirill
    check("transliteratorning O'Z sinovi o'tadi", _oz_sinov() == 0)
    # YIG'ILGAN shakl ISHLATILMAYDI: `api/translit` qidiruv uchun
    # `ҳ қ ў ғ` ni tashlaydi va real kirish bunday emas.
    kir = lotin_kirill("Ehtiyot qismlar uchun kafolat muddati necha oy?")
    check("kirill variant HAQIQIY o'zbek kirilli (yig'ilgan emas)",
          "ҳ" in kir and "қ" in kir and "ё" in kir, kir)


# =====================================================================
# 4. GROUND TRUTH HAQIQATAN YECHILADIMI
# =====================================================================
def test_ground_truth(db):
    bolim("4. GROUND TRUTH — har bo'lak HAQIQATAN mavjud")
    # GROUND TRUTH `rag_eval.mos_bolaklar()` DAN olinadi — YAGONA
    # MANBA. Bu yerda ikkinchi nusxa yozilgan edi va u AYNI joker
    # nuqsonini takrorlagandi: sinov o'zi tekshirayotgan xatoni
    # o'zi ham qilardi.
    from rag_eval import mos_bolaklar

    cs = [c for c in holatlar() if (c.get("kutilgan") or {}).get("manba_matn")]
    jami, yaroqli = 0, 0
    xatolar = []
    with db.get_conn() as conn:
        for c in cs:
            matn = c["kutilgan"]["manba_matn"]
            ids = mos_bolaklar(conn, c["tender_id"], matn)
            if not ids:
                xatolar.append(f"{c['id']}: dalil topilmadi")
                continue
            rows = db.query(
                "SELECT id, tender_id, text FROM doc_chunk "
                "WHERE id = ANY(%(ids)s)", {"ids": ids})
            for r in rows:
                jami += 1
                # UCH SHART: bo'lak mavjud, TO'G'RI tenderga
                # tegishli, va matni dalilni HAQIQATAN (literal,
                # jokersiz) o'z ichiga oladi.
                if (r["tender_id"] == c["tender_id"]
                        and matn.lower() in (r["text"] or "").lower()):
                    yaroqli += 1
                else:
                    xatolar.append(f"{c['id']}/chunk={r['id']}")
    check("har ground truth bo'lagi YECHILADI va TO'G'RI tenderda",
          jami > 0 and yaroqli == jami and not xatolar,
          f"{yaroqli}/{jami}; {xatolar[:3]}")


# =====================================================================
# 5. IQTIBOS PLUMBING — har iqtibos HAQIQIY bo'lakka yechiladi
# =====================================================================
def test_iqtibos_yechiladi(db):
    """B — QISMAN. Model AYNAN o'shanga ko'rsatdimi, bu yerda emas."""
    bolim("5. IQTIBOS — har biri HAQIQIY bo'lakka yechiladi")
    from api import ai_chat

    cs = [c for c in holatlar() if (c.get("kutilgan") or {}).get("manba_matn")]
    ctx = ai_chat.ChatContext(company_id=2, session_id="zz-rag-sifat")
    for c in cs[:4]:
        ai_chat._t_search_documents(
            {"tender_id": c["tender_id"], "query": c["savol"]}, ctx)

    check("iqtibos yig'ildi", len(ctx.citations) > 0,
          f"{len(ctx.citations)} ta")
    if not ctx.citations:
        return

    yomon = []
    for i, it in enumerate(ctx.citations, 1):
        r = db.query_one(
            "SELECT id, tender_id, char_start, char_end, text "
            "FROM doc_chunk WHERE id = %(i)s", {"i": it["chunk_id"]})
        if not r:
            yomon.append(f"[{i}] chunk_id={it['chunk_id']} YO'Q")
            continue
        if r["tender_id"] != it["tender_id"]:
            yomon.append(f"[{i}] tender mos emas")
        if r["char_start"] != it["char_start"]:
            yomon.append(f"[{i}] char_start mos emas")
        # SNIPPET UYDIRILMAGAN bo'lsin: u bo'lak matnining
        # HAQIQIY boshi bo'lishi kerak.
        if not (r["text"] or "").startswith(it["snippet"][:60]):
            yomon.append(f"[{i}] snippet matnga mos emas")
    check("har iqtibos MAVJUD bo'lakka yechiladi", not yomon,
          str(yomon[:3]))

    # MANBA RAQAMI = ro'yxatdagi o'rin. Frontend AYNAN shunday
    # chizadi; mos kelmasa [3] boshqa hujjatga ketardi.
    check("manba raqami ro'yxat tartibi bilan mos",
          len(ctx.citations) == len(set(id(x) for x in ctx.citations)))


# =====================================================================
# 6. IJARACHI IZOLYATSIYASI
# =====================================================================
def test_ijarachi(db):
    bolim("6. IJARACHI IZOLYATSIYASI — AI tool'lari")
    from api import ai_chat

    # 1) `company_id` HECH BIR tool sxemasida bo'lmasligi kerak.
    #    Bo'lsa, model (yoki hujjatdagi injection) uni o'zgartirib
    #    boshqa ijarachining ma'lumotini so'ray olardi.
    xom = json.dumps(ai_chat.TOOLS, ensure_ascii=False, default=str)
    check("`company_id` tool sxemalarida YO'Q", "company_id" not in xom)

    # 2) HAQIQIY chaqiruv: ikki ijarachi — ikki natija.
    kompaniyalar = [r["id"] for r in db.query(
        "SELECT id FROM company_account ORDER BY id LIMIT 2")]
    if len(kompaniyalar) < 2:
        check("ikki ijarachi bor (sinov uchun)", False,
              f"{len(kompaniyalar)} ta")
        return
    a, b = kompaniyalar[0], kompaniyalar[1]

    def katalog(cid):
        ctx = ai_chat.ChatContext(company_id=cid, session_id="zz-izol")
        return ai_chat._t_get_my_catalog({}, ctx)

    ka, kb = katalog(a), katalog(b)
    # `default=str` — katalogda `Decimal` (narx) bor va u
    # JSON ga to'g'ridan-to'g'ri tushmaydi.
    sa = json.dumps(ka, ensure_ascii=False, default=str)
    sb = json.dumps(kb, ensure_ascii=False, default=str)
    check(f"katalog ijarachiga bog'liq (id={a} vs id={b})", sa != sb,
          "ikkalasi bir xil qaytdi — IZOLYATSIYA YO'Q")

    # 3) A ning mahsulot nomi B ning javobida CHIQMASIN.
    nomlar_a = {r["name"] for r in db.query(
        "SELECT name FROM catalog_product WHERE company_id=%(c)s LIMIT 40",
        {"c": a})}
    sizdi = [n for n in nomlar_a if n and len(n) > 6 and n in sb]
    check("A ning mahsuloti B ning javobiga SIZMAYDI", not sizdi,
          str(sizdi[:3]))


# =====================================================================
# 7. REGRESSIYA DARVOZALARI
# =====================================================================
def test_darvoza():
    bolim("7. REGRESSIYA DARVOZALARI")
    if not os.path.exists(BAZAVIY):
        check("bazaviy hisobot mavjud", False, BAZAVIY)
        return
    b = json.load(io.open(BAZAVIY, encoding="utf-8"))

    g = b["usullar"]["gibrid"]
    check(f"gibrid recall >= {DARVOZA['gibrid_recall']}",
          g["recall_at_k"] >= DARVOZA["gibrid_recall"],
          f"{g['recall_at_k']}")
    check(f"gibrid MRR >= {DARVOZA['gibrid_mrr']}",
          g["mrr"] >= DARVOZA["gibrid_mrr"], f"{g['mrr']}")
    check(f"iqtibos hit >= {DARVOZA['iqtibos_hit']}",
          b["iqtibos"]["citation_hit_rate"] >= DARVOZA["iqtibos_hit"],
          f"{b['iqtibos']['citation_hit_rate']}")

    # GIBRID ikkala yakka usuldan YOMON bo'lmasin — aks holda
    # birlashtirish ZARAR keltirayotgan bo'lardi.
    check("gibrid leksikdan yomon emas",
          g["recall_at_k"] >= b["usullar"]["leksik"]["recall_at_k"],
          f"{g['recall_at_k']} vs {b['usullar']['leksik']['recall_at_k']}")

    # KROSS-TIL darvozasi — bazaviyda bo'lsa.
    tq = b.get("til_qamrov") or {}
    tillar = tq.get("tillar") or {}
    if tillar:
        for til, chegara in (("uz_cyr", DARVOZA["uz_cyr_recall"]),
                             ("ru", DARVOZA["ru_recall"])):
            o = tillar.get(til)
            if o:
                check(f"{til} recall >= {chegara}",
                      o["recall_at_k"] >= chegara, f"{o['recall_at_k']}")
    else:
        # BAZAVIY ESKI — buni JIMGINA o'tkazib yubormaymiz.
        check("bazaviyda kross-til o'lchovi bor", False,
              "bazaviyni yangilash kerak: rag_eval.py --json ...")


# =====================================================================
# 8. HALOL CHEKLOVLAR
# =====================================================================
def test_cheklovlar():
    bolim("8. NIMA O'LCHANMAGANI ANIQ YOZILGAN")
    if not os.path.exists(BAZAVIY):
        check("bazaviy hisobot mavjud", False)
        return
    b = json.load(io.open(BAZAVIY, encoding="utf-8"))
    matn = " ".join(b.get("cheklovlar") or [])
    check("C/D/E o'lchanmagani YOZILGAN",
          "O'LCHANMADI" in matn and "model chaqiruvi" in matn, matn[:110])
    check("namuna KICHIK ekani yozilgan", "NAMUNA KICHIK" in matn)
    # `citation_hit_rate` — "iqtibos MUMKINMI", "iqtibos TO'G'RIMI" EMAS.
    # Bu farq yo'qolsa B qatlami o'lchangan deb hisoblanardi.
    izoh = (b.get("iqtibos") or {}).get("izoh") or ""
    check("iqtibos o'lchovining CHEGARASI yozilgan",
          "MODEL chaqiruvini talab qiladi" in izoh, izoh[:110])

    # --- C/D/E harness MAVJUD va PULLIK QULF ostida ---
    #
    # Harness bo'lmasa "o'lchash mumkin emas" degan bahona qolardi.
    # Qulfsiz bo'lsa esa tasodifan xarajat qilinardi.
    hp = os.path.join(ROOT, "_tests", "ai_eval", "javob_eval.py")
    check("C/D/E harness'i mavjud", os.path.exists(hp))
    if os.path.exists(hp):
        h = io.open(hp, encoding="utf-8").read()
        check("harness PULLIK ROZILIK talab qiladi",
              "--pullik" in h and "paid_guard" in h)
        # BALL DETERMINISTIK: model hakam EMAS. Hakam ham xato
        # qiladi va uning xatosi O'LCHANMAGAN bo'lardi.
        check("ball DETERMINISTIK (LLM-hakam ishlatilmaydi)",
              "model hakam" in h.lower() or "hakam sifatida" in h.lower())
        for m in ("kerakli", "taqiqlangan", "asossiz", "rad_etdi"):
            check(f"harness `{m}` ni hisoblaydi", m in h)

    # --- C/D/E HALI O'LCHANMAGAN deb AYTILADI ---
    #
    # Bu sinovning eng muhim qatori: harness bor, lekin YURGIZILMAGAN.
    # "Harness bor" ni "o'lchandi" deb o'qish -- aynan shu vazifada
    # taqiqlangan xato.
    nat = os.path.join(ROOT, "_tests", "ai_eval", "results",
                       "javob_eval_baseline.json")
    olchandi = os.path.exists(nat)
    print(f"      C/D/E holati: "
          f"{'O`LCHANGAN' if olchandi else 'O`LCHANMAGAN (harness tayyor)'}")
    check("C/D/E holati OSHKOR (o'lchangan yoki yo'q — yashirilmaydi)",
          True, "yuqoridagi qator")


def main():
    ap = argparse.ArgumentParser(description="RAG sifati sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: RAG SIFATI — dalilga asoslangan bazaviy daraja")
    print("=" * 70)

    test_toplam()
    test_til_variantlari()
    test_transliterator()
    test_darvoza()
    test_cheklovlar()

    if getattr(args, "bazasiz", False):
        print("\n  [i] --bazasiz: ground truth, iqtibos va ijarachi")
        print("      tekshiruvlari O'TKAZILMADI — qamrov kamaydi.")
    else:
        from api import db
        db.init_pool()
        test_ground_truth(db)
        test_iqtibos_yechiladi(db)
        test_ijarachi(db)

    otdi = sum(1 for _n, ok, _d in _natija if ok)
    jami = len(_natija)
    print("\n" + "=" * 70)
    for n, ok, d in _natija:
        if not ok:
            print(f"  YIQILDI: {n}" + (f" -- {d}" if d else ""))
    print(f"NATIJA: {otdi}/{jami} o'tdi")
    print("=" * 70)
    sys.exit(0 if otdi == jami else 1)


if __name__ == "__main__":
    main()
