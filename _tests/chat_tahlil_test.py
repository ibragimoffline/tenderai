#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: GO/NO-GO DAN KEYIN DAVOM ETISH (§2.2–2.5)
=================================================

MUAMMO: foydalanuvchi Go/No-Go hukmini ko'radi va "nega review?"
deb so'ramoqchi bo'ladi. Chat esa boshqa joyda va u tahlilni
KO'RMAGAN. Modelning yagona yo'li `run_gonogo` edi — ya'ni
foydalanuvchi ENDIGINA ko'rgan natijani 30-60 soniyada va yangi
pullik chaqiruv bilan QAYTA hisoblash.

YECHIM UCH QISMDAN:

  1. `get_analysis` tool — saqlangan tahlilni BAZADAN o'qiydi,
     model chaqirilmaydi;
  2. kontekst bloki — `manba='gonogo'` sessiyasida hukm, yiqilgan
     mezonlar va bloklovchilar tizim promptiga qo'yiladi;
  3. `chat_session.tahlil_hash` — sessiya ochilgandagi surat;
     joriysi bilan farq qilsa model OGOHLANTIRILADI.

BU SINOV PULLIK CHAQIRUVSIZ. Model xulqi (§2.5 eval, G guruhi)
alohida va u production gacha qoladi.

QO'RIQLANADIGAN CHEGARALAR:

  * "TOPILMADI" va "SALBIY NATIJA" ARALASHMAYDI;
  * `malumot_yoq` mezon "yiqilgan" ga qo'shilmaydi;
  * kesilgan ro'yxat KESILGANINI aytadi;
  * `company_id` sessiyadan — boshqa ijarachining tahlili
    o'qilmaydi (IDOR juftligi);
  * `manba` va `tahlil_hash` MIJOZDAN emas, SESSIYADAN olinadi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\chat_tahlil_test.py
    .venv\\Scripts\\python.exe _tests\\chat_tahlil_test.py --bazasiz
"""
from __future__ import annotations

import argparse
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
def test_manba():
    bolim("1. Manba — tool ta'rifi va qoidalar")
    from api import ai_chat, tahlil

    tools = {t["name"]: t for t in ai_chat.TOOLS}
    check("`get_analysis` tool bor", "get_analysis" in tools)
    g = tools.get("get_analysis", {})
    # ARZONLIGI TA'RIFDA AYTILADI — model tanlashi shunga bog'liq.
    check("ta'rif `run_gonogo` dan arzon ekanini aytadi",
          "QIMMAT EMAS" in g.get("description", ""))
    check("ta'rif AVVAL shuni chaqirishni aytadi",
          "AVVAL SHUNI" in g.get("description", "").upper())
    check("`topilmadi` xato EMAS deb yozilgan",
          "xato emas" in g.get("description", "").lower())
    # `run_gonogo` ENDI IKKINCHI NAVBATDA.
    rg = tools.get("run_gonogo", {})
    check("`run_gonogo` avval `get_analysis` ni talab qiladi",
          "get_analysis" in rg.get("description", ""))
    check("`run_gonogo` QAYTA HISOBLASH ekani aytilgan",
          "QAYTA HISOBLAYDI" in rg.get("description", ""))
    check("`get_analysis` dispatch ro'yxatida",
          "get_analysis" in ai_chat.TOOL_IMPL)

    # Turlar IKKI JOYDA yozilmaydi.
    src = io.open(os.path.join(ROOT, "api", "tahlil.py"),
                  encoding="utf-8").read()
    check("`kind` qiymatlari modullardan olinadi (qo'lda emas)",
          "ai_gonogo.KIND" in src and "ai_match.KIND" in src)
    check("`gonogo_v2` matni qo'lda yozilmagan", '"gonogo_v2"' not in src)
    check("turlar ro'yxati yopiq", set(tahlil.TURLAR)
          == {"summary", "match", "gonogo"}, str(tahlil.TURLAR))


def test_kontekst_manbasi():
    bolim("2. Kontekst bloki — event loop va sessiya chegarasi")
    chat = io.open(os.path.join(ROOT, "api", "ai_chat.py"),
                   encoding="utf-8").read()
    # DB SO'ROVI `build_system` ICHIDA BO'LMASIN: u sinxron va
    # asinxron oqimdan chaqiriladi.
    i = chat.index("def build_system(")
    tana = chat[i:i + 2600]
    check("`build_system` bazaga BORMAYDI",
          "tahlil.kontekst_bloki" not in tana)
    check("blok `run_in_threadpool` bilan tayyorlanadi",
          "run_in_threadpool(_tahlil_bloki" in chat)
    check("yiqilsa chat ishlayveradi",
          "tahlil_bloki = None" in chat)

    # `manba`/`tahlil_hash` MIJOZDAN EMAS.
    main = io.open(os.path.join(ROOT, "api", "main.py"),
                   encoding="utf-8").read()
    check("`ChatContext` ularni `s` (sessiya) dan oladi",
          "manba=s.get(\"manba\")" in main
          and "tahlil_hash=s.get(\"tahlil_hash\")" in main)
    check("`eval` mijozdan qabul qilinmaydi",
          '("panel", "global",' in main and '"eval"' not in
          main[main.index("manba = body.manba"):
               main.index("manba = body.manba") + 200])
    check("sessiya ochilganda `tahlil_hash` yoziladi",
          "_tahlil.joriy_hash(body.tender_id" in main)


def test_interfeys():
    bolim("3. Interfeys — kirish tugmasi va chiplar")
    gg = io.open(os.path.join(ROOT, "frontend", "src", "components",
                              "GoNoGo.tsx"), encoding="utf-8").read()
    check("Go/No-Go panelida tugma bor", "gonogo.ask" in gg)
    check("tugma ixtiyoriy (chatsiz ham ishlaydi)",
          "onAskAi &&" in gg)

    app = io.open(os.path.join(ROOT, "frontend", "src", "App.tsx"),
                  encoding="utf-8").read()
    check("`chatManba` ALOHIDA holat", "setChatManba" in app)
    check("yopilganda manba tozalanadi",
          "setChatFor(null); setChatManba(null)" in app)

    cp = io.open(os.path.join(ROOT, "frontend", "src", "components",
                              "ChatPanel.tsx"), encoding="utf-8").read()
    check("panel `manba` ni serverga uzatadi",
          "manba: manba ?? (tenderId ? 'panel' : 'global')" in cp)
    check("chiplar STATIK (LLM yaratmaydi)", "GONOGO_CHIPLAR" in cp)
    check("chiplar faqat `gonogo` da ko'rinadi",
          "manba === 'gonogo'" in cp)
    for lok in ("uz", "ru", "en"):
        t = io.open(os.path.join(ROOT, "frontend", "src", "locales",
                                 f"{lok}.ts"), encoding="utf-8").read()
        yoq = [k for k in ("gonogo.ask", "gonogo.askTitle",
                           "gonogo.chip.why", "gonogo.chip.criteria",
                           "gonogo.chip.docs", "gonogo.chip.improve")
               if f"'{k}'" not in t]
        check(f"`{lok}` tarjimalari to'liq", not yoq, str(yoq))


# =====================================================================
def _namuna(db):
    return db.query_one("SELECT tender_id, company_id FROM ai_analysis "
                        "WHERE kind = 'gonogo_v2' LIMIT 1")


def test_oqish(db):
    bolim("4. Saqlangan tahlilni o'qish — haqiqiy ma'lumot")
    from api import tahlil
    r = _namuna(db)
    if not r:
        check("`gonogo_v2` tahlili topildi", False, "sinov ma'lumoti yo'q")
        return
    t, c = r["tender_id"], r["company_id"]

    x = tahlil.oqi(t, c, "gonogo")
    check("tahlil o'qildi", bool(x))
    check("`qayta_hisoblanmadi` bayrog'i bor",
          x.get("qayta_hisoblanmadi") is True)
    check("`content_hash` qaytadi", bool(x.get("content_hash")))
    check("`yaratilgan` sanasi bor", bool(x.get("yaratilgan")))

    # "YO'Q" — XATO EMAS.
    check("hisoblanmagan tahlil -> `None`",
          tahlil.oqi(-1, c, "gonogo") is None)

    # IDOR JUFTLIGI: boshqa ijarachi O'QIY OLMAYDI.
    check("boshqa ijarachi tahlilni O'QIY OLMAYDI",
          tahlil.oqi(t, 10_000_007, "gonogo") is None)


def test_tool(db):
    bolim("5. `get_analysis` tool")
    from api import ai_chat as A
    r = _namuna(db)
    if not r:
        return
    t, c = r["tender_id"], r["company_id"]
    ctx = A.ChatContext(company_id=c, session_id="zz", lang="uz",
                        tender_id=t, manba="gonogo")

    out = A._t_get_analysis({"tender_id": t, "kind": "gonogo"}, ctx)
    check("tool tahlilni qaytardi", "natija" in out)
    check("`#` prefiksli identifikator ham ishlaydi",
          A._t_get_analysis({"tender_id": f"#{t}", "kind": "gonogo"},
                            ctx).get("natija") is not None)

    # TOPILMADI != SALBIY NATIJA.
    yoq = A._t_get_analysis({"tender_id": t, "kind": "summary"}, ctx)
    if yoq.get("topilmadi"):
        check("`topilmadi` SALBIY natija emasligi AYTILADI",
              "SALBIY natija EMAS" in yoq.get("izoh", ""), str(yoq)[:90])
    else:
        print("        [i] `summary` tahlili bor — bu yo'l o'lchanmadi")

    check("noto'g'ri `kind` xato beradi",
          "error" in A._t_get_analysis({"tender_id": t, "kind": "zz"}, ctx))

    # IDOR: kontekst boshqa ijarachiniki bo'lsa tahlil KO'RINMAYDI.
    ctx2 = A.ChatContext(company_id=10_000_007, session_id="zz", lang="uz",
                         tender_id=t, manba="gonogo")
    check("boshqa ijarachi tool orqali ham OLA OLMAYDI",
          A._t_get_analysis({"tender_id": t, "kind": "gonogo"},
                            ctx2).get("topilmadi") is True)


def test_blok(db):
    bolim("6. Kontekst bloki — uchta holat")
    from api import ai_chat as A, tahlil
    r = _namuna(db)
    if not r:
        return
    t, c = r["tender_id"], r["company_id"]

    def blok(manba, h):
        return A._tahlil_bloki(A.ChatContext(
            company_id=c, session_id="zz", lang="uz", tender_id=t,
            manba=manba, tahlil_hash=h))

    b = blok("gonogo", None)
    check("1) tahlil BOR -> sharh quriladi", bool(b) and "hukm:" in b)
    check("`run_gonogo` chaqirmaslik AYTILADI",
          "run_gonogo` NI CHAQIRMA" in (b or ""))
    check("`get_analysis` ga yo'naltiradi", "get_analysis" in (b or ""))

    # O'LCHANMAGAN MEZON "YIQILGAN" GA QO'SHILMAYDI.
    x = tahlil.oqi(t, c, "gonogo")
    olchanmadi = [m for m in (x["natija"].get("criteria") or [])
                  if m.get("status") == "malumot_yoq"]
    if olchanmadi:
        check("`malumot_yoq` ALOHIDA sanaladi",
              "O'LCHANMAGAN mezonlar" in b)
        check("u 'yomon EMAS' deb aytiladi", "'yomon' EMAS" in b)
        # KESILGANI AYTILADI.
        if len(olchanmadi) > tahlil.MAX_QATOR:
            check("kesilgan ro'yxat KESILGANINI aytadi",
                  "va yana" in b, b[b.index("O'LCHANMAGAN"):][:120])

    b2 = blok("gonogo", "BOSHQA-HASH")
    check("2) tahlil QAYTA HISOBLANGAN -> ogohlantiriladi",
          "DIQQAT" in (b2 or "") and "QAYTA" in (b2 or ""))

    check("3) `panel` manbasida sharh YO'Q", blok("panel", None) is None)
    check("tahlilsiz tender -> 'nimani ko'rganini bilmaysan'",
          "TOPILMADI" in (A._tahlil_bloki(A.ChatContext(
              company_id=c, session_id="zz", lang="uz", tender_id=-1,
              manba="gonogo")) or ""))


def test_sessiya(db):
    bolim("7. Sessiya — `tahlil_hash` yoziladi va o'qiladi")
    from api import ai_chat as A, tahlil
    r = _namuna(db)
    if not r:
        return
    t, c = r["tender_id"], r["company_id"]
    h = tahlil.joriy_hash(t, c)
    check("joriy hash olindi", bool(h))

    sid = A.create_session(c, t, "[ZZTEST] tahlil", "uz",
                           manba="gonogo", tahlil_hash=h)
    try:
        s = A.load_session(sid, c)
        check("`manba` sessiyadan qaytadi", s.get("manba") == "gonogo",
              str(s.get("manba")))
        check("`tahlil_hash` sessiyadan qaytadi",
              s.get("tahlil_hash") == h)
        check("boshqa ijarachi sessiyani OCHOLMAYDI",
              _yoq(lambda: A.load_session(sid, 10_000_007)))
        # Noto'g'ri manba BAZAGACHA bormaydi.
        check("noto'g'ri `manba` RAD ETILADI",
              _yoq(lambda: A.create_session(c, t, "x", "uz", manba="zz")))
    finally:
        db.execute_returning("DELETE FROM chat_session WHERE id=%(i)s "
                             "RETURNING id", {"i": sid})
        print("        (sinov sessiyasi o'chirildi)")


def _yoq(fn) -> bool:
    """Chaqiruv XATO berdimi (yoki bo'sh qaytardimi)."""
    try:
        return not fn()
    except Exception:                                     # noqa: BLE001
        return True


# =====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Go/No-Go dan keyin davom etish sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: GO/NO-GO DAN KEYIN DAVOM ETISH")
    print("=" * 70)

    test_manba()
    test_kontekst_manbasi()
    test_interfeys()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Bazali tekshiruvlar o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_oqish(db)
            test_tool(db)
            test_blok(db)
            test_sessiya(db)
        except Exception as e:                            # noqa: BLE001
            check("bazali tekshiruv", False, str(e)[:110])

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
