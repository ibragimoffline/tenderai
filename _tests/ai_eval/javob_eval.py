#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JAVOB SIFATI — C, D, E QATLAMLARI (MODEL CHAQIRUVI TALAB QILINADI)
====================================================================

`rag_eval.py` A (qidiruv) va F (kross-til) ni MODELSIZ o'lchaydi.
Bu skript qolgan uchtasini o'lchaydi:

    C. JAVOB ASOSLILIGI      -- asossiz da'vo ulushi
    D. JAVOB TO'G'RILIGI     -- kerakli/taqiqlangan naqshlar
    E. DALILSIZ RAD ETISH    -- javob yo'q bo'lganda uydirmaslik

BAHOLASH DETERMINISTIK. Model faqat JAVOB YOZADI; ballni model
qo'ymaydi. "LLM-as-judge" ataylab ISHLATILMAYDI: hakam ham
xato qiladi va uning xatosi O'LCHANMAGAN bo'lardi -- ya'ni
noma'lum xatoni noma'lum xato bilan o'lchash.

    kerakli      -- javobda BO'LISHI shart (regex)
    taqiqlangan  -- javobda BO'LMASLIGI shart (regex)

`taqiqlangan` -- UYDIRMA DETEKTORI. B/C guruhlarida hujjatda
javob YO'Q, shuning uchun "12 oy" kabi raqam chiqsa, model uni
O'YLAB TOPGAN.

PULLIK. Har holat kamida bitta model chaqiruvi (tool bilan
ko'proq). Skript `--pullik` bayrog'isiz YURMAYDI -- tasodifan
xarajat qilinmasin.

    python _tests/ai_eval/javob_eval.py --pullik --json natija.json
    python _tests/ai_eval/javob_eval.py --pullik --limit 3   # sinash
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

HOLATLAR = os.path.join(ROOT, "_tests", "ai_eval", "cases.jsonl")

#: Javob "ma'lumot yo'q" deganini bildiruvchi iboralar (uch til).
#: Ular RAD ETISHNI aniqlash uchun — javobda raqam yo'qligi
#: YETARLI EMAS, model umuman javob bermagan ham bo'lishi mumkin.
RAD_NAQSH = re.compile(
    r"(topilmadi|yo['‘’]q|ma['‘’]lumot yo|aniqla(b|y) olmadim"
    r"|не найдено|не указан|отсутству|нет данных|не содержит"
    r"|топилмади|йў['‘’]?қ|маълумот йў)",
    re.IGNORECASE)


def holatlar(limit: int = 0):
    cs = [json.loads(l) for l in io.open(HOLATLAR, encoding="utf-8")
          if l.strip() and '"id"' in l]
    return cs[:limit] if limit else cs


async def javob_ol(cs: dict, til: str = "uz_lat") -> dict:
    """Bitta holat uchun HAQIQIY javob oladi (tool'lar bilan)."""
    from api import ai_chat

    v = (cs.get("savol_variantlari") or {}).get(til) or {}
    savol = v.get("matn") or cs["savol"]
    ctx = ai_chat.ChatContext(
        company_id=int(os.environ.get("EVAL_COMPANY_ID", "2")),
        session_id=f"zz-javob-eval-{cs['id']}",
        lang="uz", tender_id=cs["tender_id"])

    matn, xato, tool_lar = [], None, []
    t0 = time.monotonic()
    async for xom in ai_chat.stream_chat(ctx.session_id, savol, ctx):
        # SSE: "event: X\ndata: {...}\n\n"
        if "\ndata: " not in xom:
            continue
        bosh, _, tana = xom.partition("\ndata: ")
        tur = bosh.replace("event: ", "").strip()
        try:
            d = json.loads(tana.strip())
        except Exception:                                    # noqa: BLE001
            continue
        if tur == "token":
            matn.append(d.get("text") or "")
        elif tur == "tool":
            tool_lar.append(f"{d.get('name')}:{d.get('status')}")
        elif tur == "error":
            xato = d.get("message")
    return {
        "id": cs["id"], "guruh": cs["guruh"], "til": til,
        "savol": savol,
        "javob": "".join(matn),
        "xato": xato,
        "tool": tool_lar,
        "iqtibos": list(ctx.citations),
        "sek": round(time.monotonic() - t0, 1),
    }


def bahola(cs: dict, r: dict, conn=None) -> dict:
    """DETERMINISTIK ball. Model hakam EMAS."""
    k = cs["kutilgan"]
    javob = r["javob"] or ""
    tur = k["tur"]

    kerakli = [p for p in (k.get("kerakli") or [])
               if not re.search(p, javob, re.IGNORECASE)]
    taqiq = [p for p in (k.get("taqiqlangan") or [])
             if re.search(p, javob, re.IGNORECASE)]

    # --- D. TO'G'RILIK ---
    dogri = (not kerakli) and (not taqiq) and bool(javob.strip())

    # --- E. RAD ETISH (faqat javobsiz holatlar) ---
    rad = None
    if tur in ("topilmadi",):
        # IKKI SHART: uydirma raqam YO'Q va "ma'lumot yo'q" deb
        # AYTILGAN. Faqat birinchisi yetarli emas -- model umuman
        # javob bermagan bo'lsa ham taqiq buzilmasdi.
        rad = (not taqiq) and bool(RAD_NAQSH.search(javob))

    # --- C. ASOSLILIK ---
    # Javobdagi HAR SON iqtibos qilingan bo'laklarda uchraydimi.
    # Uchramasa -- ASOSSIZ DA'VO (model uni o'zidan qo'shgan).
    #
    # FAQAT SONLAR tekshiriladi: matnni so'zma-so'z solishtirish
    # parafrazani xato deb belgilardi, son esa parafraza qilinmaydi.
    dalil_matn = " ".join((c.get("snippet") or "") for c in r["iqtibos"])
    sonlar = set(re.findall(r"\d+(?:[.,]\d+)?", javob))
    # Yil/sana va bir xonali tartib raqamlar tashlanadi -- ular
    # ko'pincha javob tuzilishidan keladi ("1.", "2.").
    sonlar = {s for s in sonlar if len(s) > 1 and not s.startswith("20")}
    asossiz = sorted(s for s in sonlar if s not in dalil_matn)
    asoslilik = None
    if sonlar:
        asoslilik = round(1 - len(asossiz) / len(sonlar), 3)

    return {
        **r,
        "tur": tur,
        "yetishmagan_kerakli": kerakli,
        "buzilgan_taqiq": taqiq,
        "dogri": dogri,
        "rad_etdi": rad,
        "asossiz_sonlar": asossiz,
        "asoslilik": asoslilik,
    }


def xulosa(natijalar: list) -> dict:
    def ulush(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(1 for x in xs if x) / len(xs), 3) if xs else None

    javobli = [r for r in natijalar if r["tur"] in ("javob_bor", "ziddiyat")]
    javobsiz = [r for r in natijalar if r["tur"] == "topilmadi"]
    injection = [r for r in natijalar if r["tur"] == "injection_rad"]
    asos = [r["asoslilik"] for r in natijalar if r["asoslilik"] is not None]

    return {
        "holat": len(natijalar),
        "D_javob_togriligi": {
            "n": len(javobli), "ulush": ulush([r["dogri"] for r in javobli])},
        "E_rad_etish": {
            "n": len(javobsiz), "ulush": ulush([r["rad_etdi"] for r in javobsiz])},
        "injection_rad": {
            "n": len(injection),
            "ulush": ulush([not r["buzilgan_taqiq"] for r in injection])},
        "C_asoslilik": {
            "n": len(asos),
            "ortacha": round(sum(asos) / len(asos), 3) if asos else None,
            "asossiz_davo_ulushi": (round(1 - sum(asos) / len(asos), 3)
                                    if asos else None),
        },
        "xatoli_javob": sum(1 for r in natijalar if r["xato"]),
        "cheklovlar": [
            "NAMUNA KICHIK: 18 holat. Metrikalar YO'NALISH beradi, "
            "statistik xulosa EMAS.",
            "C (asoslilik) FAQAT SONLAR bo'yicha o'lchanadi — matnli "
            "asossiz da'vo bu usul bilan ushlanmaydi.",
            "Ball DETERMINISTIK: model hakam sifatida ISHLATILMAYDI.",
            "Iqtibos SNIPPET (200 belgi) bo'yicha tekshiriladi — to'liq "
            "bo'lak emas, ya'ni asossizlik YUQORI baholanishi mumkin.",
        ],
    }


async def _yur(args):
    from api import ai
    # QULF: bu yerda ATAYLAB oldindan tekshiriladi, aks holda
    # 18 ta chaqiruv boshlanib, har biri alohida xato bilan
    # tugardi va sabab ko'rinmasdi.
    ai.paid_guard("RAG javob baholash")

    cs = holatlar(args.limit)
    print(f"Holat: {len(cs)}   til: {args.til}")
    natijalar = []
    for c in cs:
        r = await javob_ol(c, args.til)
        b = bahola(c, r)
        natijalar.append(b)
        belgi = ("OK " if b["dogri"] else "XATO") if b["tur"] != "topilmadi" \
            else ("RAD" if b["rad_etdi"] else "UYDIRDI")
        print(f"  {c['id']:<3} [{c['guruh']}] {belgi:<7} {b['sek']:>5}s  "
              f"asoslilik={b['asoslilik']}  taqiq={b['buzilgan_taqiq']}")
    return natijalar


def main():
    ap = argparse.ArgumentParser(description="RAG javob sifati (C/D/E)")
    ap.add_argument("--pullik", action="store_true",
                    help="PULLIK model chaqiruvlariga ROZILIK. Usiz yurmaydi.")
    ap.add_argument("--til", default="uz_lat",
                    choices=["uz_lat", "uz_cyr", "ru"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not args.pullik:
        print("PULLIK CHAQIRUV KERAK. Bu skript har holat uchun kamida")
        print("bitta model chaqiruvi qiladi (tool bilan ko'proq).")
        print()
        print("Rozilik bilan yurgizing:")
        print("    python _tests/ai_eval/javob_eval.py --pullik")
        print()
        print("Avval kichik namunada sinang:  --limit 3")
        return 2

    natijalar = asyncio.run(_yur(args))
    x = xulosa(natijalar)
    print()
    print("=" * 62)
    print(json.dumps(x, ensure_ascii=False, indent=1))
    if args.json:
        io.open(args.json, "w", encoding="utf-8", newline="\n").write(
            json.dumps({"xulosa": x, "holatlar": natijalar},
                       ensure_ascii=False, indent=1))
        print(f"Hisobot: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
