#!/usr/bin/env python3
"""
SINOV: AI-CHAT qatlami (J4)
===========================
MODELGA CHIQMAYDI — hech qanday Anthropic chaqiruvi yo'q, ya'ni sinov
PUL SARFLAMAYDI. Tekshiriladigan narsa modelning javobi emas, uning
ATROFIDAGI qatlam: sessiya, kvota, tool'lar, izolyatsiya va xavfsizlik
o'zgarmaslari.

Nimalar tekshiriladi:
  1. XAVFSIZLIK O'ZGARMASI — `company_id` HECH BIR tool sxemasida yo'q.
     Bu §8 ning 3-qatlami: prompt himoyasi ehtimolli, bu esa
     arxitekturaviy. Yangi tool qo'shilganda avtomatik ushlaydi.
  2. Alifbo — `tsquery()` lotin/kirill variantlarini beradi
  3. Sessiya hayoti va IKKI KOMPANIYA IZOLYATSIYASI
  4. Kvota: hisob, limit, sarf
  5. Tool'lar (modelsiz ishlaydiganlar) va `chat_tool_call` jurnali
  6. Yopiq tender himoyasi
  7. Tarix: javobsiz `tool_use` bloki tarixga TUSHMAYDI

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\chat_test.py

SINOVDAN KEYIN barcha sinov yozuvlari o'chiriladi.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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


from dotenv import load_dotenv                          # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api import ai_chat, auth, db                       # noqa: E402

_results = []
_sessions = []          # tozalash uchun


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, bool(ok)))
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" +
          (f"\n       {detail}" if detail and not ok else ""))
    return bool(ok)


def eq(name, got, want):
    return check(name, got == want, f"kutilgan={want!r} olingan={got!r}")


# =========================================================================
# 1. XAVFSIZLIK O'ZGARMASI — eng muhim sinov
# =========================================================================
def test_xavfsizlik():
    print("\n[1] company_id HECH BIR tool sxemasida bo'lmasligi kerak")
    buzuq = []
    for tool in ai_chat.TOOLS:
        sxema = json.dumps(tool.get("input_schema") or {}, ensure_ascii=False)
        if "company_id" in sxema:
            buzuq.append(tool["name"])
    check("company_id tool argumenti EMAS", not buzuq,
          f"buzuq tool'lar: {buzuq}\n"
          "       Model uni o'zgartirib boshqa kompaniyaning ma'lumotini "
          "so'rab olardi (§8, 3-qatlam).")

    nomlar = {t["name"] for t in ai_chat.TOOLS}
    eq("ta'rif <-> implementatsiya mos", nomlar, set(ai_chat.TOOL_IMPL))

    # Har tool tavsifi bo'lishi shart — modelga qachon ishlatishni
    # aytadigan yagona narsa shu.
    tavsifsiz = [t["name"] for t in ai_chat.TOOLS
                 if len((t.get("description") or "").strip()) < 30]
    check("har tool'da mazmunli tavsif bor", not tavsifsiz, f"-> {tavsifsiz}")


# =========================================================================
# 2. ALIFBO — tsquery
# =========================================================================
def test_tsquery():
    print("\n[2] tsquery — lotin/kirill variantlari")
    q = ai_chat.tsquery("nasos")
    check("lotin so'rov kirill variantini beradi", "насос" in q, f"-> {q}")
    check("variantlar OR bilan", "|" in q, f"-> {q}")

    q2 = ai_chat.tsquery("yangi nasos")
    check("bir necha so'z AND bilan", "&" in q2, f"-> {q2}")

    eq("juda qisqa so'rov -> bo'sh", ai_chat.tsquery("a"), "")
    eq("bo'sh so'rov -> bo'sh", ai_chat.tsquery(""), "")

    # `to_tsquery` sintaksisi buzilmasin — bazada haqiqatan yurgiziladi
    for s in ("nasos", "kafolat muddati", "ГОСТ 12345", "1 000 dona"):
        tsq = ai_chat.tsquery(s)
        if not tsq:
            continue
        try:
            db.scalar("SELECT to_tsquery('simple', %(q)s)::text", {"q": tsq})
            check(f"to_tsquery({s!r}) yaroqli", True)
        except db.DBUnavailable as e:
            check(f"to_tsquery({s!r}) yaroqli", False, str(e)[:90])


def test_vec_literal():
    print("\n[2b] vec_literal — pgvector matn ko'rinishi")
    v = ai_chat.vec_literal([0.5, -0.25, 1])
    eq("format", v, "[0.500000,-0.250000,1.000000]")
    # Bazada haqiqatan cast bo'lishi kerak
    try:
        n = db.scalar("SELECT vector_dims(%(v)s::vector)", {"v": v})
        eq("::vector cast ishlaydi", n, 3)
    except db.DBUnavailable as e:
        check("::vector cast ishlaydi", False, str(e)[:90])


# =========================================================================
# 3. SESSIYA va IZOLYATSIYA
# =========================================================================
def test_sessiya(cid: int):
    print("\n[3] Sessiya hayoti va izolyatsiya")
    sid = ai_chat.create_session(cid, None, "ZZTEST suhbat", "uz")
    _sessions.append(sid)
    check("yaratildi", bool(sid))

    s = ai_chat.load_session(sid, cid)
    eq("sarlavha", s["title"], "ZZTEST suhbat")
    eq("til", s["lang"], "uz")

    ai_chat.save_message(sid, "user", [{"type": "text", "text": "Salom"}])
    ai_chat.save_message(sid, "assistant", [{"type": "text", "text": "Assalom"}],
                         model="sinov", input_tokens=10, output_tokens=5)
    eq("xabarlar soni", len(ai_chat.messages(sid)), 2)
    eq("tarix (API formatida)", len(ai_chat.load_history(sid)), 2)

    check("ro'yxatda ko'rinadi",
          any(str(x["id"]) == sid for x in ai_chat.list_sessions(cid)))

    # --- IZOLYATSIYA ---
    boshqa = cid + 1000        # mavjud bo'lmagan kompaniya
    try:
        ai_chat.load_session(sid, boshqa)
        check("boshqa kompaniya KO'RA OLMAYDI", False, "sessiya ochildi!")
    except LookupError:
        check("boshqa kompaniya KO'RA OLMAYDI", True)
    check("boshqa kompaniya ro'yxatida yo'q",
          not any(str(x["id"]) == sid for x in ai_chat.list_sessions(boshqa)))

    ai_chat.archive_session(sid, cid)
    check("arxivlangach ro'yxatdan chiqadi",
          not any(str(x["id"]) == sid for x in ai_chat.list_sessions(cid)))


def test_tarix_filtri(cid: int):
    print("\n[3b] Javobsiz tool_use tarixga TUSHMAYDI")
    # Sabab: Anthropic API har `tool_use` uchun MOS `tool_result` talab
    # qiladi. Javobsiz blok tarixga tushsa keyingi so'rov 400 beradi.
    sid = ai_chat.create_session(cid, None, "ZZTEST tarix", "uz")
    _sessions.append(sid)
    ai_chat.save_message(sid, "user", [{"type": "text", "text": "savol"}])
    ai_chat.save_message(sid, "assistant", [
        {"type": "text", "text": "o'ylayapman"},
        {"type": "tool_use", "id": "toolu_x", "name": "search_tenders", "input": {}},
    ])
    ai_chat.save_message(sid, "user", [{"type": "text", "text": "yana"}])

    h = ai_chat.load_history(sid)
    bor = any(b.get("type") == "tool_use"
              for m in h for b in (m["content"] if isinstance(m["content"], list) else []))
    check("tool_use bloki tarixdan chiqarildi", not bor,
          f"tarix: {json.dumps(h, ensure_ascii=False)[:140]}")
    check("birinchi xabar 'user'", not h or h[0]["role"] == "user")


def test_api_blok(cid: int):
    print("\n[3d] SDK maydonlari API ga QAYTIB YUBORILMAYDI")
    # O'LCHANGAN NOSOZLIK (jonli evalda, 2026-08-25):
    #   400 - messages.3.content.0.text.parsed_output:
    #         Extra inputs are not permitted
    # `b.model_dump()` matn bloki uchun `parsed_output` ni ham qaytaradi.
    # U SDK ning CHIQISH maydoni, KIRISHDA taqiqlangan. Tool raundida
    # yoki tarixda qaytarib yuborilsa — chat o'sha yerda o'ladi.
    xom = {"type": "text", "text": "salom",
           "parsed_output": {"x": 1}, "citations": None}
    tozalangan = ai_chat._api_blok(xom)
    check("parsed_output olib tashlandi", "parsed_output" not in tozalangan,
          str(tozalangan))
    check("citations=None olib tashlandi", "citations" not in tozalangan,
          str(tozalangan))
    check("matn saqlanib qoldi", tozalangan.get("text") == "salom")

    tu = ai_chat._api_blok({"type": "tool_use", "id": "t1", "name": "n",
                            "input": {}, "qoshimcha": 1})
    check("tool_use: begona maydon ketdi", "qoshimcha" not in tu, str(tu))
    check("tool_use: id/name/input qoldi",
          tu.get("id") == "t1" and tu.get("name") == "n" and "input" in tu)
    check("noma'lum blok turi tashlanadi",
          ai_chat._api_blok({"type": "yangi_tur", "x": 1}) is None)
    check("dict bo'lmagan kirish", ai_chat._api_blok("matn") is None)

    # Eng muhimi: BAZADAN o'qilgan tarix ham tozalanadi.
    sid = ai_chat.create_session(cid, None, "ZZTEST blok", "uz")
    _sessions.append(sid)
    ai_chat.save_message(sid, "user", [{"type": "text", "text": "birinchi"}])
    ai_chat.save_message(sid, "assistant",
                         [{"type": "text", "text": "javob",
                           "parsed_output": {"a": 1}, "citations": None}])
    h = ai_chat.load_history(sid)
    yomon = [k for m in h for b in m["content"]
             for k in b if k not in ("type", "text", "citations")]
    check("load_history tozalangan bloklar qaytaradi", not yomon, str(yomon))


def test_xato_tarixda_yoq(cid: int):
    print("\n[3c] Xatoli javob JURNALDA qoladi, tarixga tushmaydi")
    sid = ai_chat.create_session(cid, None, "ZZTEST xato", "uz")
    _sessions.append(sid)
    ai_chat.save_message(sid, "user", [{"type": "text", "text": "savol"}])
    ai_chat.save_message(sid, "assistant", [{"type": "text", "text": ""}],
                         error="upstream yiqildi")
    check("jurnalda ko'rinadi (interfeys uchun)",
          any(m.get("error") for m in ai_chat.messages(sid)))
    check("tarixga tushmaydi (modelga qaytmaydi)",
          len(ai_chat.load_history(sid)) == 1)


# =========================================================================
# 4. KVOTA
# =========================================================================
def test_kvota(cid: int):
    print("\n[4] Kvota va xarajat")

    # KVOTANI O'ZIMIZ O'RNATAMIZ, kunlik holatga tayanmaymiz.
    #
    # SABAB (o'lchandi 2026-08-25): eval yurishi bugungi 100 ta xabarni
    # sarflagach, `check_quota` HAQLI ravishda xato berdi va sinov
    # yiqildi. Ya'ni sinov TIZIMNI emas, o'sha kungi sarfni o'lchayotgan
    # edi. Endi cheklovni ataylab qo'yamiz, ikkala tomonini ham
    # tekshiramiz va oxirida ESKI HOLATNI TIKLAYMIZ.
    eski = db.query_one("SELECT * FROM ai_quota WHERE company_id=%(c)s",
                        {"c": cid})
    try:
        db.execute_returning(
            "INSERT INTO ai_quota (company_id, daily_messages, monthly_usd) "
            "VALUES (%(c)s, 100000, 100000) "
            "ON CONFLICT (company_id) DO UPDATE SET "
            "daily_messages = 100000, monthly_usd = 100000, enabled = TRUE "
            "RETURNING company_id", {"c": cid})
        ai_chat.check_quota(cid)
        check("keng limit ichida — xato yo'q", True)

        # Endi limitni NOLGA tushiramiz — qo'riqchi ISHLASHI shart.
        db.execute_returning(
            "UPDATE ai_quota SET daily_messages = 0 WHERE company_id=%(c)s "
            "RETURNING company_id", {"c": cid})
        try:
            ai_chat.check_quota(cid)
            check("limit tugaganda BLOKLAYDI", False, "xato ko'tarilmadi")
        except Exception as e:                      # noqa: BLE001
            check("limit tugaganda BLOKLAYDI",
                  e.__class__.__name__ == "AIUnavailable", repr(e))

        db.execute_returning(
            "UPDATE ai_quota SET enabled = FALSE, daily_messages = 100000 "
            "WHERE company_id=%(c)s RETURNING company_id", {"c": cid})
        try:
            ai_chat.check_quota(cid)
            check("enabled=FALSE bo'lsa BLOKLAYDI", False, "xato ko'tarilmadi")
        except Exception as e:                      # noqa: BLE001
            check("enabled=FALSE bo'lsa BLOKLAYDI",
                  e.__class__.__name__ == "AIUnavailable", repr(e))
    finally:
        db.execute_returning("DELETE FROM ai_quota WHERE company_id=%(c)s "
                             "RETURNING company_id", {"c": cid})
        if eski:
            db.execute_returning(
                "INSERT INTO ai_quota (company_id, monthly_usd, daily_messages, "
                "enabled) VALUES (%(c)s, %(m)s, %(d)s, %(e)s) "
                "RETURNING company_id",
                {"c": cid, "m": eski["monthly_usd"],
                 "d": eski["daily_messages"], "e": eski["enabled"]})
        holat = db.query_one("SELECT * FROM ai_quota WHERE company_id=%(c)s",
                             {"c": cid})
        check("kvota holati TIKLANDI",
              (holat is None) == (eski is None), f"{eski} -> {holat}")

    sp = ai_chat.spend(cid)
    check("spend() struktura", {"company_id", "spent_usd", "limit_usd", "enabled"}
          <= set(sp), f"-> {sp}")

    class U:                       # soxta `usage` obyekti
        input_tokens = 1_000_000
        output_tokens = 1_000_000
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    narx = ai_chat.estimate_cost("claude-sonnet-5", U())
    # 1M kirish (3$) + 1M chiqish (15$) = 18$
    eq("estimate_cost (Sonnet 5, 1M+1M)", round(narx, 2), 18.0)
    check("noma'lum model ham hisoblanadi",
          ai_chat.estimate_cost("yoq-bunday-model", U()) > 0)


# =========================================================================
# 5. TOOL'LAR — modelsiz ishlaydiganlar
# =========================================================================
def test_toollar(cid: int, tid: int, yopiq: int):
    print("\n[5] Tool'lar (modelga chiqmaydi)")
    sid = ai_chat.create_session(cid, None, "ZZTEST tool", "uz")
    _sessions.append(sid)
    ctx = ai_chat.ChatContext(company_id=cid, session_id=sid)

    r = ai_chat._t_get_my_catalog({}, ctx)
    check("get_my_catalog", "products" in r, f"-> {str(r)[:80]}")

    r = ai_chat._t_get_tender({"tender_id": tid}, ctx)
    check("get_tender", r.get("id") == tid, f"-> {str(r)[:80]}")
    eq("ochiq tender: yopilgan=False", r.get("yopilgan"), False)

    r = ai_chat._t_get_tender({"tender_id": yopiq}, ctx)
    check("yopiq tender belgilanadi", r.get("yopilgan") is True)
    check("modelga ko'rsatma beriladi", "MODELGA_KO_RSATMA" in r)

    r = ai_chat._t_compare_tenders({"tender_ids": [tid, yopiq]}, ctx)
    eq("compare_tenders: yopiq chiqarildi", r.get("yopilganlar"), 1)
    eq("compare_tenders: ikkalasi ham qaytdi", r.get("count"), 2)

    r = ai_chat._t_compare_tenders({"tender_ids": []}, ctx)
    check("bo'sh ro'yxat -> aniq xato", bool(r.get("error")))

    r = ai_chat._t_check_compliance({"tender_id": tid}, ctx)
    check("check_compliance", "items" in r, f"-> {str(r)[:80]}")

    r = ai_chat._t_calc_price({"tender_id": tid}, ctx)
    check("calc_price", "totals" in r or "error" in r, f"-> {str(r)[:80]}")

    # --- run_tool: jurnalga yozadimi ---
    oldin = db.scalar("SELECT count(*) FROM chat_tool_call WHERE session_id=%(s)s",
                      {"s": sid})
    payload, ok = ai_chat.run_tool("get_my_catalog", {}, ctx)
    check("run_tool JSON qaytardi", isinstance(payload, str) and payload.startswith("{"))
    check("run_tool ok=True", ok)
    keyin = db.scalar("SELECT count(*) FROM chat_tool_call WHERE session_id=%(s)s",
                      {"s": sid})
    eq("chat_tool_call ga yozildi", keyin, oldin + 1)

    payload, ok = ai_chat.run_tool("yoq-bunday-tool", {}, ctx)
    check("noma'lum tool: ok=False", not ok)
    check("noma'lum tool: MATN qaytadi (model tushuntira olsin)",
          "error" in payload)


# =========================================================================
# 6. SSE formati
# =========================================================================
def test_interfeys():
    """AI YORDAMCHI INTERFEYSI — soxta tugma bo'lmasin, tarix ulansin.

    O'LCHANGAN NUQSON (2026-09-02, ikkitasi).

    1. TARIX ULANMAGAN EDI. Backend `GET /chat/sessions`,
       `/chat/sessions/{id}` va `DELETE` ni ANCHADAN BERI beradi,
       lekin `api.ts` da chat metodlari UMUMAN yo'q edi. Suhbat
       sahifa yangilanishi bilan yo'qolardi va `chat_session`
       jadvali to'lib borardi -- ya'ni imkoniyat bor edi, uni
       CHAQIRADIGAN narsa yo'q edi.

    2. TAYYOR NAMUNADA SOXTA BOSHQARUVLAR bor edi. Qo'shilgan
       interfeys namunasida "Deep Research", "Reason", mikrofon va
       "Upload Files" tugmalari bo'lgan; ularning hech biri
       backendda MAVJUD EMAS, "Upload" esa `setTimeout` bilan
       TAQLID qilinardi va soxta `Document.pdf` qo'shardi.

       Ishlamaydigan tugma -- eng qimmat nuqson turi: foydalanuvchi
       uni bosadi, hech narsa bo'lmaydi va BUTUN mahsulotga
       ishonmay qo'yadi.
    """
    print("\n[11] Interfeys — soxta boshqaruv yo'q, tarix ulangan")
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def oqi(*p):
        with open(os.path.join(kok, *p), encoding="utf-8") as f:
            return f.read()

    def kodgina(src: str) -> str:
        """IZOHLARNI tashlaydi.

        SHU SINOVDA YUZ BERGAN XATO: qo'riqchilar faylning O'Z
        IZOHIDAGI iborani topib yiqilgandi -- izohda "Deep Research
        OLIB TASHLANDI" deb yozilgan edi va tekshiruv uni MAVJUD
        boshqaruv deb o'qidi. Matn emas, KOD tekshirilsin.
        """
        chiq, i, n = [], 0, len(src)
        while i < n:
            if src.startswith("//", i):
                j = src.find(chr(10), i)
                i = n if j < 0 else j
            elif src.startswith("/*", i):
                j = src.find("*/", i + 2)
                i = n if j < 0 else j + 2
            else:
                chiq.append(src[i])
                i += 1
        return "".join(chiq)

    ui = kodgina(oqi("frontend", "src", "components", "ui",
                     "ai-assistant-interface.tsx"))

    # --- SOXTA BOSHQARUVLAR YO'Q ---
    for nom in ("Deep Research", "deepResearch", "Reason", "reasonEnabled",
                "Mic", "Upload Files", "handleUploadFile",
                "showUploadAnimation", "Document.pdf"):
        check(f"soxta boshqaruv YO'Q: `{nom}`", nom not in ui)
    # Namunadagi TAQLID: `setTimeout` bilan "yuklash".
    check("yuklash TAQLIDI yo'q (`setTimeout`)", "setTimeout" not in ui)

    # --- MAVZU TOKENLARI, qotirilgan rang emas ---
    # Loyihada qorong'i mavzu bor; `bg-white` unda oq ustiga oq
    # matn berardi.
    for rang in ("bg-white", "text-gray-500", "text-gray-700",
                 "border-gray-200", "bg-gray-100"):
        check(f"qotirilgan rang YO'Q: `{rang}`", rang not in ui)
    check("mavzu tokenlari ishlatiladi",
          "bg-card" in ui and "text-muted-foreground" in ui)

    # --- Vite: `use client` ma'nosiz ---
    check("`use client` yo'q (loyiha Vite'da)", '"use client"' not in ui)

    # --- HARAKATGA SEZGIRLIK hurmat qilinadi ---
    check("logotip aylanishi `prefers-reduced-motion` ni hurmat qiladi",
          "motion-safe:" in ui)

    # --- MATNLAR i18n DA ---
    check("inglizcha matn QOTIRILMAGAN",
          "Ready to assist" not in ui and "Ask me anything" not in ui)
    check("i18n ishlatiladi", "useT" in ui)

    # --- TARIX HAQIQATAN ULANGAN ---
    apits = oqi("frontend", "src", "api.ts")
    for m in ("chatSessions", "chatHistory", "chatArchive"):
        check(f"`api.{m}` mavjud", f"{m}:" in apits)
    panel = oqi("frontend", "src", "components", "ChatPanel.tsx")
    for m in ("api.chatSessions", "api.chatHistory", "api.chatArchive"):
        check(f"ChatPanel `{m}` ni CHAQIRADI", m in panel)
    check("interfeys ChatPanel ga ULANGAN",
          "AIAssistantInterface" in panel)
    # XATO YUTILMASIN: bo'sh ro'yxat va yiqilgan so'rov BOSHQA holat.
    check("tarix xatosi KO'RSATILADI", "chat.history.failed" in panel)
    # Saqlangan XATOLI javob ham ko'rinsin.
    check("saqlangan xatoli javob YASHIRILMAYDI", "m.error ?" in panel)
    # ARXIVLASH -- o'chirish emas (jurnal va xarajat saqlanadi).
    check("arxivlash ishlatiladi, o'chirish emas",
          "chatArchive" in apits and "archived" not in apits.lower()
          or "DELETE" in apits)

    # --- i18n UCH TILDA to'liq ---
    kalitlar = ["chat.welcome", "chat.welcome.hint", "chat.cat.tender",
                "chat.cat.docs", "chat.cat.decide", "chat.history",
                "chat.history.empty", "chat.history.failed"]
    for til in ("uz", "ru", "en"):
        src = oqi("frontend", "src", "locales", f"{til}.ts")
        yoq = [k for k in kalitlar if f"'{k}':" not in src]
        check(f"{til}: interfeys kalitlari to'liq", not yoq, str(yoq))

    # --- Icon nomi TUR bilan qo'riqlanadi ---
    # `| string` birlashmani BEKOR QILADI: xato nom jimgina bo'sh
    # ikonka berardi va `tsc` uni ko'rmasdi. Aynan shunday xato
    # shu ishda yuz berdi (`name="clock"` -- bunday ikonka yo'q).
    icon = oqi("frontend", "src", "components", "Icon.tsx")
    check("`Icon` nomi UNION bilan qulflangan (`| string` yo'q)",
          "name: keyof typeof PATHS" in icon
          and "keyof typeof PATHS | string" not in icon)


def test_sse():
    print("\n[6] SSE hodisa formati")
    s = ai_chat._sse("token", {"text": "salom"})
    check("event qatori", s.startswith("event: token\n"), repr(s))
    check("data qatori", "data: " in s, repr(s))
    check("bo'sh qator bilan tugaydi", s.endswith("\n\n"), repr(s))
    check("o'zbek harflari buzilmaydi",
          "ў" in ai_chat._sse("x", {"t": "ўзбек"}))


def main():
    print("=" * 62)
    print("AI-CHAT SINOVI — modelga chiqmaydi, PUL SARFLAMAYDI")
    print("=" * 62)

    test_xavfsizlik()
    test_sse()
    test_interfeys()

    db.init_pool()
    try:
        if not ai_chat.schema_ready():
            check("schema_patch_ai_chat.sql qo'llangan", False,
                  "psql -d xtxarid -f schema_patch_ai_chat.sql")
            return
        cid = auth.sole_company_id()
        print(f"     (sinov kompaniyasi: id={cid})")
        tid = int(db.scalar(
            "SELECT id FROM tender WHERE status='open' "
            "AND (close_at IS NULL OR close_at > now()) LIMIT 1"))
        yopiq = int(db.scalar("SELECT id FROM tender WHERE status='expired' LIMIT 1"))

        test_tsquery()
        test_vec_literal()
        test_sessiya(cid)
        test_tarix_filtri(cid)
        test_xato_tarixda_yoq(cid)
        test_api_blok(cid)
        test_kvota(cid)
        test_toollar(cid, tid, yopiq)
    finally:
        # --- TOZALASH: sinov sessiyalari (kaskad bilan xabar va jurnal ham) ---
        n = 0
        for sid in _sessions:
            if db.execute_returning(
                    "DELETE FROM chat_session WHERE id=%(i)s RETURNING id", {"i": sid}):
                n += 1
        qoldiq = db.scalar(
            "SELECT count(*) FROM chat_session WHERE title LIKE 'ZZTEST%%'")
        print(f"\nTozalandi: {n} ta sinov sessiyasi (qoldiq: {qoldiq})")
        db.close_pool()

    yiqilgan = [n for n, ok in _results if not ok]
    print("\n" + "=" * 62)
    print(f"NATIJA: {len(_results) - len(yiqilgan)}/{len(_results)} o'tdi")
    for n in yiqilgan:
        print(f"  FAIL: {n}")
    print("=" * 62)
    sys.exit(1 if yiqilgan else 0)


if __name__ == "__main__":
    main()
