#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: RAG BAHOLASH BAZAVIY O'LCHOVI — REGRESSIYA QO'RIQCHISI
==============================================================

`_tests/ai_eval/rag_eval.py` bazaviy o'lchovni beradi. Bu sinov uch
narsani qo'riqlaydi:

  1. GROUND TRUTH HAQIQIY. Har dalil satri KORPUSDA borligini
     tekshiradi. Dalil yo'qolsa (hujjat qayta ishlangan, bo'lak
     chegarasi siljigan) yorliq JIMGINA yolg'onga aylanardi.

  2. SIZIB CHIQISH YO'Q. Qidiruvga faqat savol beriladi.

  3. METRIKA PASAYMAGAN. Bazaviy fayl bilan taqqoslanadi. Pasayish
     TO'XTATADI — aks holda sifat sekin-asta yo'qolib, buni hech
     narsa ko'rsatmasdi.

NEGA CHEGARA BOR (`TOLERANS`): korpus o'sib boradi va yangi bo'laklar
tartibni biroz siljitishi mumkin. Katta pasayish esa REGRESSIYA.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\rag_eval_test.py
    .venv\\Scripts\\python.exe _tests\\rag_eval_test.py --offline
"""
import argparse
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

try:
    import psycopg2
except ImportError:                                           # pragma: no cover
    psycopg2 = None

EVAL = os.path.join(ROOT, "_tests", "ai_eval", "rag_eval.py")
CASES = os.path.join(ROOT, "_tests", "ai_eval", "cases.jsonl")
BASELINE = os.path.join(ROOT, "_tests", "ai_eval", "results",
                        "rag_eval_baseline.json")

#: Metrika shuncha pasaysa — REGRESSIYA. Korpus o'sishi tartibni
#: biroz siljitadi, shuning uchun nol emas; lekin katta pasayish
#: to'xtatadi.
TOLERANS = 0.10

_results = []


def check(name, ok, detail=""):
    _results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def section(t):
    print(f"\n--- {t} ---")


def cases():
    return [json.loads(l) for l in io.open(CASES, encoding="utf-8")
            if l.strip() and '"id"' in l]


# =====================================================================
def test_toplam_shakli():
    section("To'plam shakli — har holat to'liq")
    cs = cases()
    check("holatlar bor", len(cs) >= 10, f"{len(cs)} ta")
    kerak = ("id", "guruh", "tender_id", "savol", "haqiqat", "kutilgan")
    for c in cs:
        yoq = [k for k in kerak if k not in c]
        check(f"{c.get('id', '?')}: barcha maydonlar bor", not yoq, str(yoq))
    turlar = {c["kutilgan"]["tur"] for c in cs}
    check("javobsiz holatlar BOR",
          {"topilmadi"} & turlar == {"topilmadi"},
          "gallyutsinatsiyani faqat ular o'lchaydi")
    check("id lar TAKRORSIZ", len({c["id"] for c in cs}) == len(cs))


def test_tool_yoli_guruhlari():
    section("F va G — modelning YO'LI o'lchanadi (2026-09-04)")
    # F va G javob MATNINI emas, qaysi tool chaqirilganini o'lchaydi.
    # Ular PULLIK yurgizilmaydi; bu yerda SHAKL va BAHOLOVCHI
    # sinaladi, aks holda holat yozilib, yurgizilganda yiqilardi.
    cs = {c["id"]: c for c in cases()}
    f = [c for c in cs.values() if c.get("guruh") == "F"]
    g = [c for c in cs.values() if c.get("guruh") == "G"]
    check("F guruhi yozilgan (>= 6)", len(f) >= 6, f"{len(f)} ta")
    check("G guruhi yozilgan (>= 5)", len(g) >= 5, f"{len(g)} ta")

    for c in f + g:
        k = c["kutilgan"]
        check(f"{c['id']}: turi `tool_yoli`", k["tur"] == "tool_yoli",
              k["tur"])
        check(f"{c['id']}: tool sharti BOR",
              bool(k.get("tool_kerakli") or k.get("tool_taqiqlangan")),
              "shartsiz holat hech narsani o'lchamaydi")

    # SALBIY HOLAT MAJBURIY. Taqiq faqat "chaqirma" dan iborat
    # bo'lsa, model HECH QACHON chaqirmay ham o'tib ketardi va
    # taqiqning chegarasi o'lchanmasdi.
    check("G da `run_gonogo` TALAB qilinadigan holat bor",
          any("run_gonogo" in (c["kutilgan"].get("tool_kerakli") or [])
              for c in g),
          "aks holda taqiq cheksiz bo'lardi")
    check("F da `get_tender` TAQIQLANGAN holat bor",
          any("get_tender" in (c["kutilgan"].get("tool_taqiqlangan") or [])
              for c in f),
          "raqam ID emas bo'lgan holat")

    # BAHOLOVCHI — soxta yurish bilan, PULLIK CHAQIRUVSIZ.
    #
    # `EVAL` (`rag_eval.py`) BOSHQA skript: u qidiruv sifatini
    # o'lchaydi. Tool yo'lini `run_eval.py` baholaydi.
    import importlib.util
    yol = os.path.join(ROOT, "_tests", "ai_eval", "run_eval.py")
    spec = importlib.util.spec_from_file_location("run_eval_baho", yol)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def yurish(javob, tools):
        return {"javob": javob, "tools": tools, "citations": [],
                "xato": None}

    c = cs["F1"]
    check("baholovchi: to'g'ri yo'l O'TADI",
          m.baho(c, yurish("Narx hisoblandi.", ["calc_price:done"]))["otdi"])
    b = m.baho(c, yurish("Narx.", ["search_tenders:start", "calc_price:done"]))
    check("baholovchi: ORTIQCHA tool tutiladi",
          not b["otdi"] and b["tool_ortiqcha"] == ["search_tenders"],
          str(b["tool_ortiqcha"]))
    b = m.baho(c, yurish("Narx.", ["get_tender:done"]))
    check("baholovchi: YETISHMAGAN tool tutiladi",
          not b["otdi"] and b["tool_yetishmadi"] == ["calc_price"],
          str(b["tool_yetishmadi"]))
    # MATN SHARTI HAM AMAL QILADI — yo'l to'g'ri bo'lib javob
    # noto'g'ri bo'lishi mumkin.
    check("baholovchi: yo'l to'g'ri, MATN noto'g'ri -> YIQILADI",
          not m.baho(cs["G1"], yurish("Bilmadim.", []))["otdi"])
    check("baholovchi: taqiqlangan MATN tutiladi",
          not m.baho(cs["G3"],
                     yurish("Sertifikati yo'q, malumot yetarli emas.",
                            []))["otdi"])


def test_sizib_chiqish():
    section("Sizib chiqish — ground truth qidiruvga bormaydi")
    r = subprocess.run([sys.executable, EVAL, "--sizish-tekshir"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="backslashreplace", cwd=ROOT, timeout=300)
    check("sizish tekshiruvi O'TDI", r.returncode == 0,
          (r.stdout or "")[-200:])


def test_ground_truth(conn):
    section("Ground truth KORPUSDA tasdiqlanadi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    dalilli = [c for c in cases() if c["kutilgan"].get("manba_matn")]
    check("dalilli holatlar bor", len(dalilli) >= 5, f"{len(dalilli)} ta")
    for c in dalilli:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM doc_chunk "
                        "WHERE tender_id=%s AND text ILIKE %s",
                        (c["tender_id"], "%" + c["kutilgan"]["manba_matn"] + "%"))
            n = cur.fetchone()[0]
        # DALIL YO'QOLSA YORLIQ YOLG'ONGA AYLANADI. Jimgina
        # o'tkazib yuborilmaydi.
        # Tafsilot FAQAT yiqilganda ma'noli — `check()` uni ikkala
        # holatda ham chop etadi, shuning uchun shartli beriladi.
        check(f"{c['id']}: dalil korpusda BOR ({n} bo'lak)", n > 0,
              "" if n else (f"{c['kutilgan']['manba_matn'][:40]!r} KORPUSDA "
                            f"YO'Q — yorliq endi YOLG'ON"))

    # Javobsiz holatlarda dalil BO'LMASLIGI shart — aks holda ular
    # "javobsiz" emas edi.
    javobsiz = [c for c in cases() if c["kutilgan"]["tur"] == "topilmadi"]
    for c in javobsiz:
        check(f"{c['id']}: javobsiz holatda dalil YO'Q",
              not c["kutilgan"].get("manba_matn"))


def test_bazaviy_fayl():
    section("Bazaviy o'lchov fayli")
    check("bazaviy JSON mavjud", os.path.exists(BASELINE), BASELINE)
    if not os.path.exists(BASELINE):
        return None
    b = json.loads(io.open(BASELINE, encoding="utf-8").read())
    for k in ("k", "usullar", "iqtibos", "cheklovlar", "sana"):
        check(f"bazaviy faylda '{k}' bor", k in b)
    check("uchala usul ham o'lchangan",
          set(b["usullar"]) == {"leksik", "semantik", "gibrid"},
          str(sorted(b["usullar"])))
    for u, d in b["usullar"].items():
        for m in ("recall_at_k", "precision_at_k", "mrr", "ndcg_at_k"):
            check(f"{u}: '{m}' hisoblangan", d.get(m) is not None, str(d.get(m)))
    # T-2 TUZATISHI (2026-09-02): METRIKA QAMROVI PER-TENDER.
    #
    # Men "korpus 57% o'sdi, sifat o'zgarmadi" deb yozgan edim va
    # bu XULOSA CHIQARIB BO'LMAYDIGAN da'vo edi. `rag_eval.py`
    # dagi HAR qidiruv `WHERE c.tender_id = %(tender_id)s` bilan
    # cheklangan: boshqa tenderning bo'lagi nomzodlar to'plamiga
    # UMUMAN kira olmaydi. Ya'ni korpusning boshqa joyida qancha
    # o'sish bo'lsa ham, bu metrikalarga TA'SIR QILA OLMAYDI.
    #
    # O'LCHANDI: 19 holatning 8 tenderida 2 073 bo'lak bor va
    # ularning HAMMASI bazaviy o'lchovdan oldin vektorlangan
    # (fon vazifasi ularga TEGMAGAN). Ya'ni bir xil raqamlar
    # DETERMINIZMNI tasdiqlaydi, korpus o'sishiga chidamlilikni
    # EMAS.
    #
    # Bu qo'riqcha shuning uchun turadi: qamrov o'zgarsa (masalan
    # qidiruv korpus bo'ylab qilinadigan bo'lsa) sinov yiqiladi va
    # yuqoridagi xulosa qayta yozilishi kerak bo'ladi.
    kod = io.open(os.path.join(ROOT, "_tests", "ai_eval", "rag_eval.py"),
                  encoding="utf-8").read()
    check("qidiruv PER-TENDER cheklangan (korpus bo'ylab EMAS)",
          "c.tender_id = %(tender_id)s" in kod)
    check("holat tenderi HAR qidiruvga uzatiladi",
          'qidir(conn, usul, cs["tender_id"], cs["savol"], k)' in kod)

    # T-2: QAYSI QATLAM O'LCHANMAGANI ANIQ YOZILGAN bo'lsin.
    #
    # Reyestrda T-2 "RAG qatlamlari O'LCHANMAGAN" deb yozilgan edi
    # va bu ANIQ EMAS: qidiruv va iqtibos O'LCHANADI (modelsiz),
    # faqat javob/tool/gallyutsinatsiya o'lchanmaydi. Bu farq
    # yo'qolsa, "hech narsa o'lchanmagan" degan yolg'on xulosa
    # qaytardi.
    matn = " ".join(b["cheklovlar"])
    check("javob/tool/gallyutsinatsiya O'LCHANMAGANI yozilgan",
          "O'LCHANMADI" in matn and "model chaqiruvi" in matn,
          matn[:120])
    # NAMUNA HAJMI OSHKOR: 7 javobli holatdagi 0.705 recall ni
    # statistik da'vo deb o'qib bo'lmaydi.
    check("namuna hajmi oshkor qilingan",
          isinstance(b.get("javobli_holat"), int) and b["javobli_holat"] > 0,
          str(b.get("javobli_holat")))
    check("namuna KICHIK ekani yozilgan", "NAMUNA KICHIK" in matn)
    # O'LCHANGAN qatlamlar HAM aniq: "hammasi o'lchanmagan" degan
    # teskari yolg'on ham chiqmasin.
    check("qidiruv metrikalari HAQIQATAN bor",
          all(m in b["usullar"]["gibrid"]
              for m in ("recall_at_k", "precision_at_k", "mrr", "ndcg_at_k")),
          str(sorted(b["usullar"]["gibrid"].keys()))[:100])
    check("iqtibos o'lchovi bor", "citation_hit_rate" in b.get("iqtibos", {}))

    check("CHEKLOVLAR ro'yxati BO'SH EMAS", len(b["cheklovlar"]) >= 3,
          "past metrika va cheklovlar YASHIRILMAYDI")
    # O'LCHANMAGAN QATLAMLAR ANIQ AYTILGAN.
    matn = " ".join(b["cheklovlar"])
    check("o'lchanmagan qatlamlar (javob/tool/gallyutsinatsiya) AYTILGAN",
          "O'LCHANMADI" in matn or "o'lchanmadi" in matn.lower())
    return b


def test_regressiya(b):
    section(f"Regressiya — metrika {TOLERANS:.0%} dan ko'p pasaymadi")
    if b is None:
        check("bazaviy fayl kerak", False, "o'tkazib yuborildi")
        return
    r = subprocess.run(
        [sys.executable, EVAL, "--json",
         os.path.join(ROOT, "_tests", "ai_eval", "results", "_joriy.json")],
        capture_output=True, text=True, encoding="utf-8",
        errors="backslashreplace", cwd=ROOT, timeout=900)
    if r.returncode != 0:
        check("baholash yurdi", False, (r.stderr or "")[-300:])
        return
    joriy_yol = os.path.join(ROOT, "_tests", "ai_eval", "results", "_joriy.json")
    j = json.loads(io.open(joriy_yol, encoding="utf-8").read())
    check("baholash yurdi", True)

    for u in ("leksik", "semantik", "gibrid"):
        for m in ("recall_at_k", "mrr", "ndcg_at_k"):
            eski, yangi = b["usullar"][u].get(m), j["usullar"][u].get(m)
            if eski is None or yangi is None:
                continue
            check(f"{u}.{m}: pasaymadi ({eski:.3f} -> {yangi:.3f})",
                  yangi >= eski - TOLERANS,
                  f"pasayish {eski - yangi:.3f} > tolerans {TOLERANS}")

    e_iq = (b["iqtibos"] or {}).get("citation_hit_rate")
    y_iq = (j["iqtibos"] or {}).get("citation_hit_rate")
    if e_iq is not None and y_iq is not None:
        check(f"citation hit rate pasaymadi ({e_iq:.3f} -> {y_iq:.3f})",
              y_iq >= e_iq - TOLERANS)

    # GIBRID ENG YAXSHI BO'LIB QOLSIN — bu arxitektura qarori va
    # u o'lchov bilan himoyalanadi.
    g = j["usullar"]["gibrid"]
    check("gibrid MRR leksik va semantikadan past emas",
          g["mrr"] >= max(j["usullar"]["leksik"]["mrr"],
                          j["usullar"]["semantik"]["mrr"]) - 1e-9,
          f"gibrid={g['mrr']:.3f} leksik={j['usullar']['leksik']['mrr']:.3f} "
          f"semantik={j['usullar']['semantik']['mrr']:.3f}")
    # IKKALA faylni ham tozalaymiz. `rag_eval.py` JSON yonida `.txt`
    # ham yozadi va faqat JSON o'chirilsa `.txt` ishchi daraxtda
    # qolib ketardi — kuzatilmagan artefakt.
    for yol in (joriy_yol, os.path.splitext(joriy_yol)[0] + ".txt"):
        try:
            os.remove(yol)
        except OSError:
            pass


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="RAG baholash regressiyasi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: RAG BAHOLASH BAZAVIY O'LCHOVI")
    print("=" * 70)

    test_toplam_shakli()

    test_tool_yoli_guruhlari()
    b = test_bazaviy_fayl()

    conn = None
    if psycopg2 and os.environ.get("XT_DB_DSN"):
        try:
            conn = psycopg2.connect(os.environ["XT_DB_DSN"], connect_timeout=8)
            conn.autocommit = True
        except Exception as e:                                # noqa: BLE001
            print(f"  [i] baza yetib bo'lmadi: {str(e)[:80]}")

    test_ground_truth(conn)

    if args.bazasiz:
        print("\n[i] --offline: sizish va regressiya tekshiruvi "
              "o'tkazib yuborildi (baholash ~30 s oladi).")
    else:
        test_sizib_chiqish()
        test_regressiya(b)

    if conn:
        conn.close()

    otdi = sum(1 for _n, ok, _d in _results if ok)
    jami = len(_results)
    print("\n" + "=" * 70)
    for n, ok, d in _results:
        if not ok:
            print(f"  YIQILDI: {n}" + (f" -- {d}" if d else ""))
    print(f"NATIJA: {otdi}/{jami} o'tdi")
    print("=" * 70)
    sys.exit(0 if otdi == jami else 1)


if __name__ == "__main__":
    main()
