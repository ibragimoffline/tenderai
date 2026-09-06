# -*- coding: utf-8 -*-
"""SINOV: PULLIK CHAQIRUV QULFI.

QAT'IY SHART (loyiha egasi, 2026-08-25): loyiha ishlab chiqarish
holatiga chiqmaguncha HECH QANDAY pullik amal bajarilmaydi.

NEGA BU SINOV BOR: qoidani odam eslab qolishiga tayanish yetarli
emas. Bu loyihada pullik chaqiruv OLTI joyda:

    api/ai.py              -> analyze()
    api/ai_gonogo.py       -> analyze()          (ai.get_client orqali)
    api/ai_match.py        -> analyze()          (ai.get_client orqali)
    api/requirement_ai.py  -> extract(dry_run=False)
    api/ai_chat.py         -> stream_chat()      (O'Z asinxron mijozi)
    api/ai_chat.py         -> _load_embedder()   (EMBED_PROVIDER=voyage)

OXIRGI IKKITASI `ai.get_client()` dan O'TMAYDI, ya'ni bitta joyga
qo'yilgan qulf ularni QAMRAMAYDI. Oltinchisi eng xavflisi: vektorlash
soatiga 1000 bo'lak, ya'ni `.env` da bitta so'z o'zgarsa quvur
MINGLAB pullik so'rov yuborardi.

Ro'yxat birinchi urinishda BESHTA edi va oltinchisi o'tkazib
yuborilgan edi — shuning uchun har yangi pullik chaqiruv bu ro'yxatga
QO'SHILISHI shart.

Sinovning o'zi PUL SARFLAMAYDI — u qulf ISHLAYOTGANINI tekshiradi,
ya'ni chaqiruvlar bloklanishini.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# KONSOL KODLASHI — Windows kod sahifasidan MUSTAQIL UTF-8.
#
# Chiqish QUVUR yoki FAYLGA yo'naltirilganda (ya'ni CI da) Python
# `locale.getpreferredencoding()` ni oladi — bu mashinada `cp1251`.
# O'zbek kirill (`ҳ`, `қ`, `ў`) va to'liq kenglikdagi belgilar
# (`）`) u yerda YO'Q va chop etish `UnicodeEncodeError` bilan
# BUTUN TO'PLAMNI o'ldiradi. `import_test` aynan shu sababdan
# 143 ta tekshiruvni bajarmasdan yiqilardi. Tafsilot: _tests/konsol.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import konsol  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv                              # noqa: E402
load_dotenv(os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), ".env"))

from api import ai, db                                      # noqa: E402

PASS = FAIL = 0


def check(nom: str, shart: bool, izoh: str = "") -> None:
    global PASS, FAIL
    if shart:
        PASS += 1
        print(f"  OK   {nom}")
    else:
        FAIL += 1
        print(f"  XATO {nom}" + (f"\n       {izoh}" if izoh else ""))


def section(t: str) -> None:
    print(f"\n=== {t} ===")


def bloklandimi(fn, nom: str) -> None:
    """Chaqiruv `AIUnavailable` bilan to'xtaydimi va SABABI aniqmi."""
    try:
        fn()
        check(f"{nom} BLOKLANADI", False, "chaqiruv o'tib ketdi!")
    except ai.AIUnavailable as e:
        check(f"{nom} BLOKLANADI", "BLOKLANGAN" in str(e), str(e)[:90])
    except Exception as e:                                  # noqa: BLE001
        # Boshqa xato ham bloklaydi, lekin SABABI noaniq bo'ladi —
        # foydalanuvchi "nima uchun ishlamadi" deb hayron qoladi.
        check(f"{nom} BLOKLANADI", "BLOKLANGAN" in str(e),
              f"noaniq xato: {type(e).__name__}: {str(e)[:70]}")


def main() -> None:
    print("=" * 62)
    print("PULLIK QULF SINOVI — o'zi pul sarflamaydi")
    print("=" * 62)

    section("1. Jonli holat va STANDART qiymat")
    # JONLI QIYMAT SINOV ICHIDA ISHLATILMAYDI.
    #
    # 2026-09-02 da loyiha egasi pullik so'rovlarga ochiq ruxsat
    # berdi (`.env` da `AI_PAID_ENABLED=1`). O'shandan keyin bu sinov
    # jonli qiymat bilan ishlasa, 2-4 bo'limlar chaqiruvlar
    # BLOKLANISHINI emas, HAQIQATAN BAJARILISHINI ko'rardi — ya'ni
    # "o'zi pul sarflamaydigan" sinov chat, Go/No-Go, moslik va talab
    # ajratish uchun TO'RTTA pullik so'rov yuborardi.
    #
    # Shuning uchun jonli qiymat faqat CHOP ETILADI, so'ng jarayon
    # ichida MAJBURAN o'chiriladi. Sinovning maqsadi o'zgarmadi:
    # qulf o'chirilganda oltala yo'l ham to'xtashini isbotlash.
    jonli = os.environ.get(ai.PAID_ENV)
    print(f"     .env dagi AI_PAID_ENABLED = "
          f"{jonli if jonli is not None else '(o`rnatilmagan)'!r}")
    if ai.paid_allowed():
        print("     DIQQAT: pullik amallar YOQILGAN. Quyidagi "
              "bo'limlar qulfni\n     jarayon ichida majburan "
              "o'chiradi — sinovning O'ZI pul sarflamaydi.")
    os.environ.pop(ai.PAID_ENV, None)
    check("qiymat berilmaganda BLOKLANGAN", not ai.paid_allowed(),
          "standart qiymat ochiq qolgan — ai.paid_allowed() buzilgan")
    os.environ[ai.PAID_ENV] = "0"

    section("2. Barcha pullik yo'llar")
    bloklandimi(ai.get_client, "ai.get_client()")

    from api import ai_gonogo, ai_match
    bloklandimi(lambda: ai_gonogo.analyze(
        {"id": 1, "name": "x", "detail": {}}, [], None), "ai_gonogo.analyze")
    bloklandimi(lambda: ai_match.analyze({"id": 1, "name": "x"}, []),
                "ai_match.analyze")

    db.init_pool()
    try:
        tid = db.scalar("SELECT tender_id FROM doc_chunk LIMIT 1")
        if tid:
            from api import requirement_ai as RA
            bloklandimi(
                lambda: RA.extract(tid, 2, dry_run=False, force=True),
                "requirement_ai.extract(dry_run=False)")

            # `dry_run` BLOKLANMASLIGI kerak — u model chaqirmaydi.
            d = RA.extract(tid, 2, dry_run=True, force=True)
            check("dry_run BLOKLANMAYDI",
                  d.get("status") in ("dry_run", "no_text"), str(d)[:90])

        section("3. Chat — O'Z mijozini yaratadi")
        # Bu eng nozik yo'l: `ai.get_client()` ni ishlatmaydi.
        from api import ai_chat

        async def chat_sinov() -> str:
            ctx = ai_chat.ChatContext(company_id=2, session_id="qulf")
            sid = ai_chat.create_session(2, None, "ZZQULF", "uz")
            try:
                return "".join([x async for x in
                                ai_chat.stream_chat(sid, "salom", ctx)])
            finally:
                db.execute_returning(
                    "DELETE FROM chat_session WHERE id=%(i)s RETURNING id",
                    {"i": sid})

        natija = asyncio.run(chat_sinov())
        check("chat BLOKLANADI", "paid_disabled" in natija, natija[:120])
        check("chat ANIQ sabab beradi", "BLOKLANGAN" in natija, natija[:120])

        section("4. EMBEDDING provideri — OLTINCHI yo'l")
        # Bu yo'l `ai.get_client()` dan O'TMAYDI: `_load_embedder()`
        # o'z `voyageai.Client()` ini yaratadi.
        #
        # ENG XAVFLISI shu: vektorlash soatiga 1000 bo'lak, ya'ni
        # `.env` da bitta so'z o'zgarsa (`EMBED_PROVIDER=voyage`)
        # quvur MINGLAB pullik so'rov yuborardi va qulf sezmasdi.
        eski_prov = os.environ.get("EMBED_PROVIDER")
        eski_fn = ai_chat._embed_fn
        try:
            ai_chat._embed_fn = None            # keshni tozalaymiz
            os.environ["EMBED_PROVIDER"] = "voyage"
            bloklandimi(ai_chat._load_embedder,
                        "voyage embedding (EMBED_PROVIDER=voyage)")
        finally:
            ai_chat._embed_fn = eski_fn
            if eski_prov is None:
                os.environ.pop("EMBED_PROVIDER", None)
            else:
                os.environ["EMBED_PROVIDER"] = eski_prov

        section("5. BEPUL amallar bloklanmaydi")
        # Qulf faqat PULLIK chaqiruvni to'xtatishi kerak. Lokal
        # embedding va naqsh ajratgichi ishlashda davom etsin —
        # aks holda butun RAG quvuri to'xtab qolardi.
        v = ai_chat.embed_query("kafolat muddati")
        check("lokal embedding ishlaydi", len(v) == 384, str(len(v)))

        if tid:
            from api import requirement_naqsh as N
            r = N.extract(tid, 2)
            # `needs_review` HAM MUVAFFAQIYAT: ajratgich ishladi va
            # 18 ta talab topdi, faqat eng past ishonch 0.60 dan
            # past bo'lgani uchun inson ko'rigi so'ralyapti
            # (`requirement_naqsh.py:356`). Ilgari ruxsat etilgan
            # to'plamda u YO'Q edi va ishlagan ajratgich YIQILGAN
            # deb ko'rsatilardi.
            #
            # Bu tekshiruvning maqsadi — PULLIK qulf BEPUL yo'lni
            # to'xtatmasligini isbotlash. Uchala holat ham "qulf
            # to'xtatmadi" degani.
            check("naqsh ajratgichi ishlaydi",
                  r["status"] in ("ok", "needs_review", "no_text"), str(r))

        section("6. Qulfning O'ZI ishlaydimi")
        # "Hammasi bloklandi" degani "qulf ishlayapti" emas — u har
        # doim `False` qaytarayotgan bo'lishi ham mumkin edi.
        eski = os.environ.get(ai.PAID_ENV)
        try:
            os.environ[ai.PAID_ENV] = "1"
            check("yoqilganda RUXSAT beradi", ai.paid_allowed())
            os.environ[ai.PAID_ENV] = "0"
            check("o'chirilganda BLOKLAYDI", not ai.paid_allowed())
        finally:
            if eski is None:
                os.environ.pop(ai.PAID_ENV, None)
            else:
                os.environ[ai.PAID_ENV] = eski
    finally:
        db.close_pool()
        # Jonli qiymat QAYTARILADI — sinov `.env` ni emas, faqat
        # o'z jarayonini vaqtincha o'zgartirgan bo'lishi kerak.
        if jonli is None:
            os.environ.pop(ai.PAID_ENV, None)
        else:
            os.environ[ai.PAID_ENV] = jonli

    print("\n" + "=" * 62)
    print(f"NATIJA: {PASS}/{PASS + FAIL} o'tdi")
    print("=" * 62)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
