#!/usr/bin/env python3
"""
BILDIRISHNOMA SINOVLARI (TZ P0-10) — email va Telegram
======================================================
TARMOQQA HECH NARSA CHIQMAYDI:
  * `smtplib.SMTP` soxta transport bilan almashtiriladi (FakeSMTP)
  * `api.telegram.call` soxta funksiya bilan almashtiriladi (FakeTelegram)
Ikkalasi ham xabarni faqat XOTIRADA to'playdi. Haqiqiy email ham, haqiqiy
Telegram xabari ham YUBORILMAYDI.

Nimalar tekshiriladi:
  1. Chegaradan PAST ballli tender tanlanmaydi
  2. Bir tender haqida IKKI MARTA xabar ketmaydi (`notify_sent`)
  3. Xabarда TENDER KARTOCHKASIGA HAVOLA bor (TZ qabul mezoni) — matn+HTML+TG
  4. `--dry-run` hech narsa yubormaydi va bazaga yozmaydi
  5. SMTP/Telegram sozlanmaganda ANIQ xato (jimgina o'tmaydi)
  6. HTML va matn versiyalari ikkalasi ham to'g'ri (multipart/alternative)
  7. Soatlik tsikl oynasi: oxirgi ETL tsiklidan OLDIN ko'rilgan tender tushmaydi
  8. TELEGRAM: HTML escape, 4096 belgilik chegara BLOK CHEGARASIDAN bo'linadi
  9. TELEGRAM: kanallar mustaqil — o'z jurnali (`kind`) va biri yiqilsa
     ikkinchisi baribir yuboriladi

Ishga tushirish:
    .venv/Scripts/python.exe _tests/notify_test.py

SINOVDAN KEYIN barcha sinov yozuvlari bazadan tozalanadi (notify_sent qatorlari
o'chiriladi, notify_settings esa sinovdan OLDINGI holatiga qaytariladi).
"""
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

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

load_dotenv(os.path.join(ROOT, ".env"))

from api import db, notify, telegram  # noqa: E402



# ---------------------------------------------------------------------------
# Soxta SMTP transporti — tarmoqqa CHIQMAYDI
# ---------------------------------------------------------------------------
class FakeSMTP:
    """smtplib.SMTP o'rnini bosadi: xabarni xotirada saqlaydi."""
    sent = []          # [(host, port, EmailMessage), ...]
    started_tls = []
    logins = []

    def __init__(self, host, port=0, timeout=None, **kw):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self, *a, **kw):
        return (250, b"ok")

    def starttls(self, *a, **kw):
        FakeSMTP.started_tls.append((self.host, self.port))
        return (220, b"ready")

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, msg))

    def quit(self):
        pass

    @classmethod
    def reset(cls):
        cls.sent, cls.started_tls, cls.logins = [], [], []


class ExplodingSMTP(FakeSMTP):
    """Ulanishga URINISH BO'LMASLIGI kerak bo'lgan joylarda ishlatiladi."""
    def __init__(self, *a, **kw):
        raise AssertionError("SMTP ga ulanmaslik kerak edi!")


# ---------------------------------------------------------------------------
# Soxta Telegram transporti — api.telegram.call O'RNINI bosadi
# ---------------------------------------------------------------------------
# Nima uchun aynan `call`: undan pastda faqat `requests` bor, ya'ni bu eng
# past nuqta — yuqoridagi HAMMA mantiq (bo'lish, escape, xato o'rash) haqiqiy
# kod bo'lib qoladi va sinovда tekshiriladi.
class FakeTelegram:
    sent = []          # [(chat_id, text), ...]
    fail = None        # o'rnatilsa har chaqiruv shu matn bilan yiqiladi
    # `getUpdates` qaytaradigan xabar matni. Ulash tokenini shu yerga
    # qo'yamiz — foydalanuvchi havolani bosgani shunday ko'rinadi.
    update_text = None

    @classmethod
    def call(cls, method, params=None):
        params = params or {}
        if cls.fail:
            raise telegram.TelegramError(cls.fail)
        if method == "sendMessage":
            cls.sent.append((str(params.get("chat_id")), params.get("text") or ""))
            return {"message_id": len(cls.sent)}
        if method == "getMe":
            return {"id": 1, "username": "sinov_bot", "first_name": "Sinov"}
        if method == "getUpdates":
            # AYNAN sinov chati qaytadi: `run()` yuborishdan oldin
            # `consume_links()` ni chaqiradi, va u haqiqiy chatlarni
            # bazaga yozib qo'ymasligi kerak.
            msg = {"chat": {"id": TEST_CHAT, "type": "supergroup",
                            "title": "Sinov guruhi"}}
            if cls.update_text:
                msg["text"] = cls.update_text
            return [{"message": msg}]
        raise AssertionError(f"kutilmagan Telegram metodi: {method}")

    @classmethod
    def reset(cls, fail=None):
        cls.sent, cls.fail, cls.update_text = [], fail, None


class _TgPatch:
    """`telegram.call` ni soxta bilan almashtiruvchi context manager.

    `require_token` ham almashtiriladi — sinov .env dagi haqiqiy tokenga
    BOG'LIQ BO'LMASIN (token bo'lsa ham, bo'lmasa ham bir xil o'tsin).

    OBUNACHILARNI HAM IZOLYATSIYA QILADI. Bu SHART: bazada haqiqiy
    obunachilar bor (botga /start bosgan odamlar). Ularsiz sinov
    `notify_sent` ga o'sha odamlar nomidan qator yozib qo'yardi va keyin
    ularga haqiqiy tenderlar HECH QACHON ketmasdi. Shuning uchun sinov
    davomida hammasi o'chiriladi va faqat TEST_CHAT yoqiladi.
    """

    def __init__(self, fail=None, token="SINOV:token", with_subscriber=True):
        self.fail, self.token = fail, token
        self.with_subscriber = with_subscriber

    def __enter__(self):
        FakeTelegram.reset(self.fail)
        self._call, self._req = telegram.call, telegram.require_token
        self._env = os.environ.get("TELEGRAM_BOT_TOKEN")
        telegram.call = FakeTelegram.call
        telegram.require_token = lambda: self.token
        if self.token:
            os.environ["TELEGRAM_BOT_TOKEN"] = self.token
        else:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)

        # Haqiqiy obunachilarni vaqtincha o'chiramiz
        self._subs = db.query(
            "SELECT chat_id, enabled FROM notify_telegram_subscriber")
        db.execute_returning(
            "UPDATE notify_telegram_subscriber SET enabled = false "
            "RETURNING chat_id")
        if self.with_subscriber:
            db.execute_returning(
                # PK (company_id, chat_id) — J1 dan keyin. `company_id`
                # ko'rsatilmaydi: ustunda DEFAULT bor, lekin ON CONFLICT
                # nishoni indeks bilan AYNAN mos kelishi shart.
                "INSERT INTO notify_telegram_subscriber "
                "(chat_id, company_id, title, chat_type) "
                "VALUES (%(c)s, %(cid)s, 'Sinov obunachisi', 'supergroup') "
                "ON CONFLICT (company_id, chat_id) DO UPDATE SET enabled = true "
                "RETURNING chat_id",
                {"c": TEST_CHAT, "cid": _test_company_id()})
        return FakeTelegram

    def __exit__(self, *exc):
        telegram.call, telegram.require_token = self._call, self._req
        if self._env is None:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        else:
            os.environ["TELEGRAM_BOT_TOKEN"] = self._env
        # Sinov obunachisi, uning tokenlari va jurnali tozalanadi,
        # haqiqiy obunachilar esa tiklanadi
        db.execute_returning(
            "DELETE FROM notify_telegram_subscriber WHERE chat_id = %(c)s "
            "RETURNING chat_id", {"c": TEST_CHAT})
        db.execute_returning(
            "DELETE FROM notify_telegram_link "
            "WHERE chat_id = %(c)s OR used_at IS NULL RETURNING token",
            {"c": TEST_CHAT})
        for r in self._subs:
            db.execute_returning(
                "UPDATE notify_telegram_subscriber SET enabled = %(e)s "
                "WHERE chat_id = %(c)s RETURNING chat_id",
                {"c": r["chat_id"], "e": r["enabled"]})
        return False


# ---------------------------------------------------------------------------
# Kichik sinov harnessi (loyihada pytest yo'q)
# ---------------------------------------------------------------------------
CASES = []
FAILED = []


def case(fn):
    CASES.append(fn)
    return fn


def eq(a, b, what=""):
    if a != b:
        raise AssertionError(f"{what}: kutilgan {b!r}, olingan {a!r}")


def ok(cond, what=""):
    if not cond:
        raise AssertionError(what or "shart bajarilmadi")


# ---------------------------------------------------------------------------
# Sinov ma'lumotlari
# ---------------------------------------------------------------------------
TEST_EMAIL = "sinov@example.invalid"
TEST_BASE = "http://localhost:5173"

TEST_CHAT = "-100123456789"


def _test_company_id() -> int:
    """J1.6: sinov yozuvlari QAYSI kompaniyaga tegishli.
    Yagona faol hisob — `auth.sole_company_id()` bilan bir xil qoida."""
    from api import auth
    return auth.sole_company_id()


# Telegram ATAYIN O'CHIRIQ: sinovlarning ko'pchiligi email haqida va ular
# tasodifan HAQIQIY chatga xabar yubormasligi kerak. Telegram sinovlari uni
# o'zi yoqib oladi (`_TgPatch` bilan birga).
TEST_SETTINGS = {
    "enabled": True, "email": TEST_EMAIL, "min_score": 70,
    "base_url": TEST_BASE,
    "telegram_enabled": False, "telegram_chat_id": None,
    # Xabar tili — sinovlar standart tilда kutadi (til sinovi uni o'zi
    # almashtirib, oxirида shu holatga qaytaradi).
    "lang": "uz",
}

# SMTP endi PLATFORMA sozlamasi (.env), foydalanuvchi formasida emas.
# Sinov davomida uni MUHITGA qo'yamiz — haqiqiy `.env` ga bog'liq bo'lmaslik
# uchun (u to'ldirilgan ham, bo'sh ham bo'lishi mumkin).
TEST_SMTP_ENV = {
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USER": "",
    "SMTP_PASSWORD": "",
    "SMTP_FROM": "tender-ai@example.invalid",
    "SMTP_TLS": "0",
}
_ORIGINAL_SMTP_ENV = {}

# Sinov davomida yaratilgan notify_sent qatorlari — oxirida o'chiriladi
CREATED_SENT = set()
_ORIGINAL_SETTINGS = None
#: "Asl holat" ning o'zi sinov qoldig'imi.
_QOLDIQ_TOPILDI = False


def fake_tender(tid=99, name="Насос va kompyuter xaridi", cats=None, goods="",
                good_codes=None):
    """`_product_matches`/`score_tender` kutadigan minimal nomzod qatori.

    `good_codes` — rasmiy tasniflagich kodlari. Moslashtirishning
    BIRLAMCHI kaliti (`matching.product_matches`), shuning uchun
    soxta nomzodda ham bo'lishi kerak.
    """
    return {
        "id": tid, "name": name, "company_name": "Sinov buyurtmachi",
        "totalcost": 1000000, "currency": "UZS", "region_name": "Toshkent shahri",
        "area_path": "33.2137", "close_at": None, "publicated_at": None,
        "source_platform": "xt-xarid",
        "category_codes": cats or [], "goods_blob": goods,
        "good_codes": good_codes or [],
    }


# ---------------------------------------------------------------------------
# 1. Chegara — past ballli tender tanlanmaydi
# ---------------------------------------------------------------------------
@case
def test_ball_shkalasi():
    """Ball /catalog/match shkalasi bilan bir xil: kod=100, nom=60.

    SHKALA O'ZGARDI (2026-08). Ilgari `kategoriya=100` edi. O'lchandi:
    206 katalog mosligining 131 tasi AYNAN kategoriya orqali kelardi va
    ular asosan soxta edi — "Andijon GES kuch transformatorini
    ta'mirlash" tibbiy muzlatgich sotuvchiga 100 ball bilan borardi,
    4 kategoriyali maktab tenderi esa 25 mahsulotdan 23 tasiga mos
    chiqardi. Kategoriya endi moslik DALILI EMAS (u filtr bo'lib
    qoladi) — `api/matching.product_matches()`.
    """
    prod = {"id": 1, "name": "kompyuter", "category_code": "elektronika",
            "keywords": [], "notify": True, "codes": ["26.20"]}

    # KOD mosligi — rasmiy tasniflagich, inson tasdiqlagan -> 100
    by_code = notify.score_candidate(
        fake_tender(cats=["qurilish"], good_codes=["26.20.11.000-00001"]),
        [prod], None)
    eq(by_code["score"], 100, "kod mosligi")
    eq(by_code["by"], "katalog", "manba")

    # KATEGORIYA endi MOSLIK EMAS: kodi bor mahsulot uchun kategoriya
    # tengligi hech narsa bermaydi.
    kodsiz_prod = dict(prod, codes=[])
    by_cat = notify.score_candidate(
        fake_tender(name="Beton va g'isht xaridi",
                    cats=["elektronika/kompyuter"], goods="beton g'isht"),
        [kodsiz_prod], None)
    eq(by_cat["score"], 0, "kategoriya tengligi MOSLIK EMAS")

    # NOM mosligi — matn, morfologik jihatdan mo'rt -> 60
    by_name = notify.score_candidate(
        fake_tender(name="Kompyuter xaridi", cats=["qurilish"]),
        [kodsiz_prod], None)
    eq(by_name["score"], 60, "nom mosligi")

    # SO'Z CHEGARASI: "kompyuter" so'zining O'RTASIDAN topilmasin.
    ichki = notify.score_candidate(
        fake_tender(name="Superkompyuter markazi", cats=["qurilish"],
                    goods="xizmat"),
        [kodsiz_prod], None)
    eq(ichki["score"], 0, "so'z o'rtasidan moslik YO'Q")

    no_match = notify.score_candidate(
        fake_tender(name="Non va sut", cats=["oziq-ovqat"], goods="non sut"),
        [kodsiz_prod], None)
    eq(no_match["score"], 0, "moslik yo'q")


@case
def test_chegaradan_past_tanlanmaydi():
    """min_score dan PAST ballli tender ro'yxatga tushmaydi."""
    since = datetime.now(timezone.utc) - timedelta(days=3650)

    hammasi = notify.find_candidates(min_score=0, since=since, limit=0)
    ok(len(hammasi) > 0, "bazada nomzod tender bo'lishi kerak (min_score=0)")

    eng_yuqori = max(t["score"] for t in hammasi)
    past_ballar = [t for t in hammasi if t["score"] < eng_yuqori]

    # BALL XILMA-XILLIGI KORPUSDAN TALAB QILINMAYDI.
    #
    # O'LCHANGAN NUQSON (2026-09-08, darvoza): bu yerda
    #
    #     ok(len(past_ballar) > 0, "... hammasi bir xil ball")
    #
    # turardi va darvoza bazasida hamma nomzodning bali bir xil
    # bo'lgani uchun BUTUN TO'PLAM yiqilardi. Ya'ni sinov kodni emas,
    # KORPUS TARKIBINI o'lchardi -- va tuzatish uchun korpusga
    # ma'lumot qo'shish kerakdek ko'rinardi.
    #
    # Aslida kerak emas: pastki halqa ayni shu xossani ma'lumotdan
    # MUSTAQIL ravishda to'liq tekshiradi -- har chegara uchun qaytgan
    # to'plam kutilganiga TENG bo'lishi shart.
    #
    # Xilma-xillik bo'lsa quyidagi qat'iy blok ham yuradi; bo'lmasa u
    # o'tkazib yuboriladi va buni jurnal AYTADI. Chiqarib tashlash
    # esa baribir o'lchanadi: halqaga `eng_yuqori + 1` qo'shilgan va
    # unda HECH BIR tender o'tmasligi kerak.
    if past_ballar:
        natija = notify.find_candidates(min_score=eng_yuqori, since=since,
                                        limit=0)
        chiqqan = {t["id"] for t in natija}
        for t in natija:
            ok(t["score"] >= eng_yuqori,
               f"chegaradan past ball o'tib ketdi: {t['score']}")
        for t in past_ballar:
            ok(t["id"] not in chiqqan,
               f"past ballli tender ({t['score']} < {eng_yuqori}) tanlandi")
    else:
        print(f"  [i] korpusda ball xilma-xilligi yo'q (hammasi {eng_yuqori})"
              f" — qat'iy blok o'tkazildi, chegara halqasi o'lchaydi")

    # Filtr AYNAN ball bo'yicha ishlaydi (ortiqcha/kam tender yo'q).
    # `eng_yuqori + 1` — CHIQARIB TASHLASH kafolatli o'lchansin.
    for chegara in (0, 50, 70, 100, eng_yuqori + 1):
        kutilgan = {t["id"] for t in hammasi if t["score"] >= chegara}
        olingan = {t["id"] for t in
                   notify.find_candidates(min_score=chegara, since=since, limit=0)}
        eq(olingan, kutilgan, f"chegara {chegara} da tanlov noto'g'ri")


# ---------------------------------------------------------------------------
# 2. Takroriy xabar yo'q
# ---------------------------------------------------------------------------
@case
def test_ikki_marta_yuborilmaydi():
    """`notify_sent` da qayd etilgan tender ikkinchi marta tanlanmaydi."""
    since = datetime.now(timezone.utc) - timedelta(days=3650)
    oldin = notify.find_candidates(min_score=0, since=since, limit=0)
    ok(len(oldin) > 0, "sinov uchun nomzod kerak")

    nishon = oldin[0]
    notify.mark_sent(nishon["id"], TEST_EMAIL, nishon["score"])
    CREATED_SENT.add(nishon["id"])

    keyin = notify.find_candidates(min_score=0, since=since, limit=0)
    ok(nishon["id"] not in {t["id"] for t in keyin},
       "yuborilgan tender qayta tanlandi (takroriy xabar!)")
    eq(len(keyin), len(oldin) - 1, "faqat bitta tender chiqib ketishi kerak")

    # --force (include_sent=True) bo'lsa qaytadi
    majburiy = notify.find_candidates(min_score=0, since=since, limit=0,
                                      include_sent=True)
    ok(nishon["id"] in {t["id"] for t in majburiy}, "--force ishlamadi")

    # Takroriy INSERT xato bermaydi (ON CONFLICT DO NOTHING) va qator ko'paymaydi
    notify.mark_sent(nishon["id"], TEST_EMAIL, nishon["score"])
    n = db.scalar("SELECT count(*) FROM notify_sent WHERE tender_id=%(id)s",
                  {"id": nishon["id"]})
    eq(int(n), 1, "notify_sent da dublikat paydo bo'ldi")


# ---------------------------------------------------------------------------
# 3 + 6. Xabar matni: havola, HTML va matn versiyalari
# ---------------------------------------------------------------------------
@case
def test_xabarda_kartochka_havolasi():
    """TZ QABUL MEZONI: xabar tizimdagi tender kartochkasiga havolani
    o'z ichiga oladi — matnli va HTML versiyada ham."""
    t = {"id": 20000502564, "name": "Server infratuzilmasi xaridi",
         "company_name": "AGROBANK ATB", "totalcost": 17128200000,
         "currency": "UZS", "region_name": "Toshkent shahri",
         "close_at": datetime(2026, 7, 31, 18, 51), "score": 100,
         "by": "katalog", "reasons": ["Katalogingizga mos: kompyuter"]}

    subj, text, html = notify.render([t], TEST_BASE, 70)
    kutilgan = f"{TEST_BASE}/?tender=20000502564"

    eq(notify.card_url(TEST_BASE, t["id"]), kutilgan, "kartochka havolasi")
    ok(kutilgan in text, "MATNLI versiyada havola yo'q")
    ok(kutilgan in html, "HTML versiyada havola yo'q")
    ok(f'href="{kutilgan}"' in html, "HTML da havola <a href> ichida emas")


@case
def test_matn_va_html_tarkibi():
    """Ikkala versiyada ham: nomi, buyurtmachi, summa, muddat, ball."""
    t = {"id": 42, "name": "Planshet xaridi", "company_name": "Taminot DUK",
         "totalcost": 15938332700, "currency": "UZS",
         "region_name": "Toshkent shahri",
         "close_at": datetime(2026, 8, 4, 14, 45), "score": 85,
         "by": "profil", "reasons": ["2 ta kalit so'z mos"]}
    subj, text, html = notify.render([t], TEST_BASE, 70)

    ok("85" in subj and "1 ta" in subj, f"mavzu noto'g'ri: {subj}")

    for kesim, nom in ((text, "matn"), (html, "html")):
        ok("Planshet xaridi" in kesim, f"{nom}: tender nomi yo'q")
        ok("Taminot DUK" in kesim, f"{nom}: buyurtmachi yo'q")
        ok("15 938 332 700 UZS" in kesim, f"{nom}: summa noto'g'ri formatlandi")
        ok("04.08.2026 14:45" in kesim, f"{nom}: muddat yo'q")
        ok("85" in kesim, f"{nom}: moslik balli yo'q")
        ok("2 ta kalit so'z mos" in kesim, f"{nom}: sabab yo'q")

    ok(html.lstrip().startswith("<!DOCTYPE html>"), "HTML hujjat emas")
    ok("<div" not in text and "<a " not in text, "matn versiyasida HTML teglari bor")
    ok("&gt;" not in text and "&#x27;" not in text,
       "matn versiyasi HTML-escape qilingan")
    # Apostrof HTML da ham o'qiladigan holida qolsin (&#x27; emas)
    ok("&#x27;" not in html, "HTML da apostrof escape qilinib qolgan")


@case
def test_xabar_platforma_tilida():
    """TZ: bildirishnoma PLATFORMA TILIDA keladi.

    Bir xil tender uch tilda chizilganда: matn, mavzu, moslik sabablari,
    summa va sana formati o'zgaradi; HAVOLA va tender NOMI (ma'lumot) esa
    o'zgarmaydi. Sabablar `reason_keys` dan quriladi — ya'ni tarjima
    tayyor matnni "qidirib almashtirish" bilan emas, manbadan bo'ladi.
    """
    t = {"id": 77, "name": "Planshet xaridi", "company_name": "Taminot DUK",
         "totalcost": 15938332700, "currency": "UZS",
         "region_name": "Toshkent shahri",
         "close_at": datetime(2026, 8, 4, 14, 45), "score": 85,
         "by_key": "by.profile",
         "reason_keys": [{"key": "reason.keywords",
                          "vars": {"n": 2, "items": "nasos, quvur"}}]}

    kutilgan = {
        # til: (matndagi maydon nomi, HTML dagi maydon nomi, summa, sana, sabab)
        # HTML da buyurtmachi YORLIQSIZ chiqadi (nomning o'zi), shuning uchun
        # u yerda "Summa" yorlig'i tekshiriladi.
        "uz": ("Buyurtmachi", "Summa", "15 938 332 700 UZS", "04.08.2026 14:45",
               "2 ta kalit so‘z mos"),
        "ru": ("Заказчик", "Сумма", "15 938 332 700 UZS", "04.08.2026 14:45",
               "Совпало 2 ключевых слова"),
        "en": ("Buyer", "Amount", "15,938,332,700 UZS", "2026-08-04 14:45",
               "2 keywords matched"),
    }
    for lang, (matn_yorliq, html_yorliq, pul, sana, sabab) in kutilgan.items():
        subj, text, html = notify.render([t], TEST_BASE, 70, lang)
        head, blocks, _ = notify.render_telegram([t], TEST_BASE, 70, lang)
        yorliq = {"matn": matn_yorliq, "html": html_yorliq}
        for kesim, nom in ((text, "matn"), (html, "html"), (blocks[0], "telegram")):
            # Telegramда maydon nomi o'rnida emoji — tarjima talab qilinmaydi
            if nom in yorliq:
                ok(yorliq[nom] in kesim,
                   f"{lang}/{nom}: maydon nomi tarjima qilinmadi")
            ok(pul in kesim, f"{lang}/{nom}: summa formati noto‘g‘ri")
            ok(sana in kesim, f"{lang}/{nom}: sana formati noto‘g‘ri")
            ok(sabab in kesim, f"{lang}/{nom}: sabab tarjima qilinmadi")
            # Ma'lumot — tarjima qilinmaydi
            ok("Planshet xaridi" in kesim, f"{lang}/{nom}: tender nomi yo‘qoldi")
            ok(f"{TEST_BASE}/?tender=77" in kesim, f"{lang}/{nom}: havola yo‘qoldi")
        ok("Tender AI" in subj and "85" in subj, f"{lang}: mavzu noto‘g‘ri: {subj}")
        ok("85" in head or "70" in head, f"{lang}: TG sarlavhasida chegara yo‘q")

    # Boshqa til — boshqa MATN (jimgina o'zbekchada qolib ketmasin)
    uz_text = notify.render([t], TEST_BASE, 70, "uz")[1]
    for lang in ("ru", "en"):
        ok(notify.render([t], TEST_BASE, 70, lang)[1] != uz_text,
           f"{lang}: xabar o'zbekchada qolib ketdi")

    # Noma'lum/bo'sh til — o'zbekchaga tushadi, XATO BERMAYDI
    for yaroqsiz in ("de", "", None, "uz-Latn-UZ", "RU"):
        kutilgani = notify.render([t], TEST_BASE, 70,
                                  "ru" if yaroqsiz == "RU" else "uz")[1]
        eq(notify.render([t], TEST_BASE, 70, yaroqsiz)[1], kutilgani,
           f"{yaroqsiz!r}: til kodi noto‘g‘ri keltirildi")


@case
def test_til_sozlamada_saqlanadi():
    """Til BAZADA turadi (brauzerда emas) — xabarni server yuboradi.

    Patch qo'llanmagan bazada esa saqlanmaydi, lekin sozlama saqlash
    YIQILMAYDI: til yumshoq afzallik, uni deb butun forma ishlamay
    qolmasligi kerak.
    """
    st = notify.save_settings(dict(TEST_SETTINGS, lang="ru"))
    if not notify.lang_column_ready():
        eq(st["lang"], "uz", "patchsiz bazada standart til kutilgandi")
        eq(st["lang_ready"], False, "lang_ready noto‘g‘ri")
        return

    eq(st["lang"], "ru", "til saqlanmadi")
    eq(notify.get_settings()["lang"], "ru", "til bazadan qaytmadi")
    # Yaroqsiz kod XATO bermaydi — standart tilga keltiriladi
    eq(notify.save_settings({"lang": "klingon"})["lang"], "uz",
       "yaroqsiz til kodi standart tilga keltirilmadi")
    # Faqat `lang` yuborilsa qolgan maydonlar TEGILMAYDI
    eq(notify.save_settings({"lang": "en"})["min_score"],
       TEST_SETTINGS["min_score"], "til saqlash boshqa maydonni o‘zgartirdi")

    # To'liq tsikl xabarni AYNAN SHU tilda quradi
    notify.save_settings({"lang": "en"})
    res = notify.run(min_score=0, limit=2, dry_run=True, since_hours=87600)
    eq(res["lang"], "en", "tsikl sozlamadagi tilni olmadi")
    if res.get("text"):
        ok("Match threshold" in res["text"],
           f"xabar ingliz tilida emas: {res['text'][:80]}")
    notify.save_settings(TEST_SETTINGS)


@case
def test_multipart_alternative():
    """Yuborilgan xabar HAM matn, HAM HTML qismga ega bo'lishi kerak."""
    FakeSMTP.reset()
    st = notify.get_settings()
    subj, text, html = notify.render(
        [{"id": 7, "name": "Sinov", "company_name": "X", "totalcost": None,
          "currency": None, "region_name": None, "close_at": None,
          "score": 90, "by": "katalog", "reasons": []}], TEST_BASE, 70)

    orig = smtplib.SMTP
    smtplib.SMTP = FakeSMTP
    try:
        notify.send(st, TEST_EMAIL, subj, text, html)
    finally:
        smtplib.SMTP = orig

    eq(len(FakeSMTP.sent), 1, "aynan bitta xabar yuborilishi kerak")
    _, _, msg = FakeSMTP.sent[0]
    eq(msg["To"], TEST_EMAIL, "qabul qiluvchi")
    eq(msg.get_content_type(), "multipart/alternative", "xabar turi")

    plain = msg.get_body(preferencelist=("plain",))
    rich = msg.get_body(preferencelist=("html",))
    ok(plain is not None, "matn qismi yo'q")
    ok(rich is not None, "HTML qismi yo'q")
    ok(f"{TEST_BASE}/?tender=7" in plain.get_content(), "matn qismida havola yo'q")
    ok(f"{TEST_BASE}/?tender=7" in rich.get_content(), "HTML qismida havola yo'q")


# ---------------------------------------------------------------------------
# 4. --dry-run
# ---------------------------------------------------------------------------
@case
def test_dry_run_hech_narsa_qilmaydi():
    """--dry-run: SMTP ga ulanmaydi va `notify_sent` ga yozmaydi."""
    oldin = int(db.scalar("SELECT count(*) FROM notify_sent"))

    orig = smtplib.SMTP
    smtplib.SMTP = ExplodingSMTP     # ulanishga urinilsa — sinov yiqiladi
    try:
        res = notify.run(min_score=0, limit=5, dry_run=True, since_hours=87600)
    finally:
        smtplib.SMTP = orig

    ok(res["found"] > 0, "dry-run uchun nomzod topilishi kerak edi")
    eq(res["sent"], 0, "dry-run da yuborilgan bo'lmasligi kerak")
    ok(res["dry_run"] is True, "dry_run bayrog'i")
    ok("dry-run" in (res["message"] or ""), "dry-run xabari yo'q")
    ok(res.get("text") and res.get("html"), "dry-run xabar matnini ko'rsatishi kerak")

    keyin = int(db.scalar("SELECT count(*) FROM notify_sent"))
    eq(keyin, oldin, "dry-run BAZAGA YOZDI (yozmasligi kerak edi)")


# ---------------------------------------------------------------------------
# 5. SMTP sozlanmaganda aniq xato
# ---------------------------------------------------------------------------
@case
def test_smtp_sozlanmagan_aniq_xato():
    """SMTP endi PLATFORMA sozlamasi (.env). Host/parol/jo'natuvchi yo'q bo'lsa
    -> NotifyError, jimgina emas. Xato matni OPERATORGA qaratilgan: bu server
    sozlamasi, foydalanuvchi uni tuzata olmaydi."""
    orig = smtplib.SMTP
    smtplib.SMTP = ExplodingSMTP
    saqlangan = {k: os.environ.get(k) for k in TEST_SMTP_ENV}

    def env(**kw):
        for k in TEST_SMTP_ENV:
            os.environ.pop(k, None)
        for k, v in kw.items():
            os.environ[k] = v

    try:
        st = notify.get_settings()

        # (a) host yo'q
        env(SMTP_FROM="a@example.invalid")
        try:
            notify.send(st, TEST_EMAIL, "s", "t", "<b>h</b>")
            raise AssertionError("host yo'q edi — xato kutilgandi")
        except notify.NotifyError as e:
            ok("SMTP_HOST" in str(e), f"xato .env ni ko'rsatmadi: {e}")

        # (b) SMTP_USER bor, lekin SMTP_PASSWORD yo'q
        env(SMTP_HOST="smtp.example.com", SMTP_USER="u@example.invalid",
            SMTP_FROM="a@example.invalid")
        try:
            notify.send(st, TEST_EMAIL, "s", "t", "<b>h</b>")
            raise AssertionError("parol yo'q edi — xato kutilgandi")
        except notify.NotifyError as e:
            ok("SMTP_PASSWORD" in str(e), f"xato .env ni ko'rsatmadi: {e}")

        # (c) jo'natuvchi manzil yo'q
        env(SMTP_HOST="smtp.example.com")
        try:
            notify.send(st, TEST_EMAIL, "s", "t", "<b>h</b>")
            raise AssertionError("jo'natuvchi yo'q edi — xato kutilgandi")
        except notify.NotifyError as e:
            ok("SMTP_FROM" in str(e), f"xato matni tushunarsiz: {e}")

        # (d) hammasi bor -> `smtp_ready()` true
        env(**TEST_SMTP_ENV)
        ok(notify.smtp_ready(), "to'liq sozlamada smtp_ready false qaytdi")
    finally:
        smtplib.SMTP = orig
        for k, v in saqlangan.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@case
def test_qabul_qiluvchi_yoq_aniq_xato():
    """Email ham sozlamada, ham profilda yo'q -> NotifyError."""
    st = dict(notify.get_settings(), email=None)
    # J1.6: profil KOMPANIYAGA bog'landi — SQL endi `company_id` talab qiladi.
    from api import auth
    profil_email = db.scalar(notify.PROFILE_EMAIL_SQL,
                             {"company_id": auth.sole_company_id()})
    if profil_email:
        # Profilda email bor — zaxira manba ISHLASHI kerak
        eq(notify.recipient(st), profil_email, "profil emaili ishlatilmadi")
        return
    try:
        notify.recipient(st)
        raise AssertionError("email yo'q edi — xato kutilgandi")
    except notify.NotifyError as e:
        ok("email" in str(e).lower(), f"xato matni tushunarsiz: {e}")


# ---------------------------------------------------------------------------
# 7. To'liq tsikl (soxta SMTP bilan) + kuzatuv oynasi
# ---------------------------------------------------------------------------
@case
def test_toliq_tsikl_va_jurnal():
    """run(): xabar yuboriladi, `notify_sent` ga yoziladi, ikkinchi yurishda
    esa QAYTA YUBORILMAYDI (soatlik tsikl takror xabar bermasin)."""
    FakeSMTP.reset()
    orig = smtplib.SMTP
    smtplib.SMTP = FakeSMTP
    try:
        res = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600)
        ok(res["found"] > 0, "nomzod topilmadi")
        eq(res["sent"], res["found"], "hamma tender jurnalga yozilishi kerak")
        eq(len(FakeSMTP.sent), 1, "bitta jamlangan xabar ketishi kerak")
        eq(res["to"], TEST_EMAIL, "qabul qiluvchi")
        for t in res["tenders"]:
            CREATED_SENT.add(t["id"])

        _, _, msg = FakeSMTP.sent[0]
        tana = msg.get_body(preferencelist=("plain",)).get_content()
        for t in res["tenders"]:
            ok(f"/?tender={t['id']}" in tana, f"{t['id']} havolasi yo'q")

        # IKKINCHI YURISH — o'sha tenderlar qayta ketmasligi kerak
        FakeSMTP.reset()
        res2 = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600)
        yuborilgan = {t["id"] for t in res["tenders"]}
        qayta = {t["id"] for t in res2["tenders"]} & yuborilgan
        eq(qayta, set(), "o'sha tenderlar haqida IKKINCHI marta xabar ketdi")
        for t in res2["tenders"]:
            CREATED_SENT.add(t["id"])
    finally:
        smtplib.SMTP = orig


@case
def test_ochirilganda_yuborilmaydi():
    """enabled=false bo'lsa xabar ketmaydi (lekin sabab aniq aytiladi)."""
    notify.save_settings(dict(TEST_SETTINGS, enabled=False))
    orig = smtplib.SMTP
    smtplib.SMTP = ExplodingSMTP
    try:
        res = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600,
                         force=True)
        eq(res["sent"], 0, "o'chirilganда yuborilmasligi kerak")
        ok("o'chirilgan" in (res["message"] or ""), f"sabab aytilmadi: {res['message']}")
    finally:
        smtplib.SMTP = orig
        notify.save_settings(TEST_SETTINGS)


# ---------------------------------------------------------------------------
# 8. TELEGRAM: xabar matni
# ---------------------------------------------------------------------------
@case
def test_telegram_kartochka_havolasi():
    """TZ QABUL MEZONI Telegram uchun ham: xabarда kartochkaga havola bor."""
    t = {"id": 20000502564, "name": "Server infratuzilmasi xaridi",
         "company_name": "AGROBANK ATB", "totalcost": 17128200000,
         "currency": "UZS", "region_name": "Toshkent shahri",
         "close_at": datetime(2026, 7, 31, 18, 51), "score": 100,
         "by": "katalog", "reasons": ["Katalogingizga mos: kompyuter"]}

    head, blocks, foot = notify.render_telegram([t], TEST_BASE, 70)
    blok = blocks[0]
    kutilgan = f"{TEST_BASE}/?tender=20000502564"

    ok(f'href="{kutilgan}"' in blok, "Telegram blokida <a href> havola yo'q")
    ok("Server infratuzilmasi xaridi" in blok, "tender nomi yo'q")
    ok("AGROBANK ATB" in blok, "buyurtmachi yo'q")
    ok("17 128 200 000 UZS" in blok, "summa noto'g'ri formatlandi")
    ok("31.07.2026 18:51" in blok, "muddat yo'q")
    ok("100 ball" in blok, "moslik balli yo'q")
    ok("Katalogingizga mos: kompyuter" in blok, "sabab yo'q")
    ok("70 ball" in head, "sarlavhada chegara yo'q")
    eq(len(blocks), 1, "bitta tender -> bitta blok")


@case
def test_telegram_html_escape():
    """`<`, `>`, `&` escape qilinadi (aks holda Telegram xabarni RAD ETADI),
    APOSTROF esa TEGILMAYDI — o'zbekcha matnда u har qadamda uchraydi."""
    t = {"id": 5, "name": "Truba <DN100> & flanets", "company_name": "O'zbekiston MTM",
         "totalcost": None, "currency": None, "region_name": None,
         "close_at": None, "score": 70, "by": "katalog",
         "reasons": ["Nomi bo'yicha mos"]}
    blok = notify.telegram_block(t, TEST_BASE)

    ok("&lt;DN100&gt;" in blok, "< > escape qilinmadi")
    ok("&amp; flanets" in blok, "& escape qilinmadi")
    ok("O'zbekiston MTM" in blok, "apostrof buzildi (&#x27; ga aylandi)")
    ok("bo'yicha" in blok, "sabab matnidagi apostrof buzildi")
    # Bizning teglarimiz JOYIDA qolishi kerak
    ok("<b>" in blok and "<a href=" in blok, "HTML teglari yo'qoldi")


@case
def test_telegram_uzun_xabar_bolinadi():
    """Telegram bitta xabarga 4096 belgi beradi. Bo'linish BLOK CHEGARASIDAN
    o'tishi kerak — tender o'rtasidan kesilsa ochilgan <b>/<a> tegi yopilmay
    qoladi va Telegram BUTUN xabarni rad etadi."""
    with _TgPatch() as tg:
        blocks = [f"<b>Blok {i}</b>\n" + ("x" * 900) for i in range(12)]
        n = telegram.send_blocks(TEST_CHAT, "<b>Sarlavha</b>", blocks, "<i>izoh</i>")

    eq(n, len(tg.sent), "qaytgan son yuborilganlar soniga teng emas")
    ok(n > 1, "uzun ro'yxat bitta xabarga sig'ib qolmasligi kerak edi")
    for _, text in tg.sent:
        ok(len(text) <= telegram.MAX_MESSAGE,
           f"xabar Telegram chegarasidan uzun: {len(text)}")
        # Teg butunligi: har bir <b> uchun </b> bo'lishi kerak
        eq(text.count("<b>"), text.count("</b>"), "yopilmagan <b> tegi")
    # Bironta blok yo'qolmasligi kerak
    hammasi = "".join(t for _, t in tg.sent)
    for i in range(12):
        ok(f"Blok {i}" in hammasi, f"Blok {i} yo'qoldi")


# ---------------------------------------------------------------------------
# 9. TELEGRAM: kanal mustaqilligi va to'liq tsikl
# ---------------------------------------------------------------------------
@case
def test_telegram_toliq_tsikl():
    """Telegram yoqilganда OBUNACHIGA xabar ketadi, `notify_sent` ga uning
    O'Z `kind` i bilan yoziladi va ikkinchi yurishда QAYTA yuborilmaydi."""
    with _TgPatch() as tg:
        notify.save_settings(dict(TEST_SETTINGS, enabled=False,
                                  telegram_enabled=True))
        orig = smtplib.SMTP
        smtplib.SMTP = ExplodingSMTP      # email o'chiq -> SMTP ga tegilmasin
        try:
            res = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600)
            t = res["telegram"]
            ok(t["found"] > 0, "Telegram uchun nomzod topilmadi")
            eq(t["sent"], t["found"], "hamma tender jurnalga yozilishi kerak")
            eq(t["errors"], [], f"Telegram xatosi: {t['errors']}")
            eq(t["chats"], [TEST_CHAT], "boshqa obunachiga ketdi")
            ok(len(tg.sent) >= 1, "Telegramga xabar ketmadi")
            for cid, _ in tg.sent:
                eq(cid, TEST_CHAT, "boshqa chatga ketdi")

            # Jurnal AYNAN shu OBUNACHI kaliti bilan yozilgan
            yuborilgan = {x["id"] for x in t["tenders"]}
            jurnal = notify.sent_ids(notify.tg_kind(TEST_CHAT))
            CREATED_SENT.update(jurnal)
            ok(yuborilgan <= jurnal,
               f"yuborilgan tenderlar '{notify.tg_kind(TEST_CHAT)}' jurnaliga tushmadi")

            # IKKINCHI YURISH — o'shalar qayta ketmaydi
            tg.reset()
            res2 = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600)
            qayta = {x["id"] for x in res2["telegram"]["tenders"]} & yuborilgan
            eq(qayta, set(), "o'sha tenderlar Telegramga IKKINCHI marta ketdi")
            CREATED_SENT.update(notify.sent_ids(notify.tg_kind(TEST_CHAT)))
        finally:
            smtplib.SMTP = orig
            notify.save_settings(TEST_SETTINGS)


@case
def test_telegram_sinov_platforma_tilida():
    """Telegram SINOV xabari ham PLATFORMA TILIDA ketadi — haqiqiy
    bildirishnoma bilan bir xil. Til almashsa — xabar ham almashadi.

    BITTA xabar: sinov "haqiqiy xabar qanday keladi" ni ko'rsatadi, ya'ni
    ulardan soni bilan ham farq qilmasligi kerak.
    """
    with _TgPatch() as tg:
        # Jurnal SINOVGACHA (oldingi sinovlar yozgan bo'lishi mumkin)
        jurnal_oldin = notify.sent_ids(notify.tg_kind(TEST_CHAT))

        kutilgan = {
            "uz": ("Sinov xabari —", "Toshkent shahri", "[SINOV]"),
            "ru": ("Проверочное сообщение", "город Ташкент", "[ПРОВЕРКА]"),
            "en": ("Test message —", "Tashkent city", "[TEST]"),
        }
        for lang, (nom, hudud, teg) in kutilgan.items():
            tg.reset()
            notify.save_settings(dict(TEST_SETTINGS, lang=lang))
            res = notify.send_telegram_test()

            eq(res["lang"], lang, "sinov boshqa tilda ketdi")
            eq(len(tg.sent), 1, f"{lang}: BITTA xabar kutilgandi, "
                                f"{len(tg.sent)} ta ketdi")
            eq(res["errors"], [], f"{lang}: xato: {res['errors']}")
            eq(res["chats"], [TEST_CHAT], "boshqa obunachiga ketdi")

            matn = tg.sent[0][1]
            ok(nom in matn, f"{lang}: namuna tender nomi tarjima qilinmadi")
            ok(hudud in matn, f"{lang}: hudud tarjima qilinmadi")
            ok(teg in matn, f"{lang}: [SINOV] belgisi tarjima qilinmadi")
            ok("🧪" in matn, f"{lang}: sinov belgisi yo‘q")
            ok(f"{TEST_BASE}/?tender=0" in matn, f"{lang}: namuna havolasi yo‘q")
            # Boshqa tillarning matni ARALASHIB ketmasin
            for boshqa, (n2, _, _) in kutilgan.items():
                if boshqa != lang:
                    ok(n2 not in matn, f"{lang}: xabarда {boshqa} matni bor")

        # SINOV JURNALGA YOZILMAYDI (haqiqiy bildirishnomaga xalaqit bermasin)
        eq(notify.sent_ids(notify.tg_kind(TEST_CHAT)), jurnal_oldin,
           "sinov xabari notify_sent ga yozildi")
        notify.save_settings(TEST_SETTINGS)


@case
def test_tokensiz_start_obunachi_qilmaydi():
    """XAVFSIZLIK MEZONI: botga shunchaki /start bosgan odam OBUNACHI
    BO'LMAYDI. Aks holda botni topgan begona ham, bot tasodifan qo'shilgan
    guruh ham kompaniyaning mos tenderlarini olardi."""
    with _TgPatch(with_subscriber=False) as tg:
        tg.update_text = "/start"           # tokenSIZ
        res = notify.consume_links()
        eq(res["added"], 0, "tokensiz /start obunachi qilib qo'ydi")
        eq(notify.enabled_subscribers(), [], "tokensiz chat obunachi bo'lib qoldi")

        # Yaroqsiz token ham o'tmasligi kerak
        tg.update_text = "/start " + ("x" * 24)
        eq(notify.consume_links()["added"], 0, "yaroqsiz token qabul qilindi")
        eq(notify.enabled_subscribers(), [], "yaroqsiz token bilan ulanib qolindi")


@case
def test_ulash_havolasi_obunachi_qiladi():
    """TZ MOHIYATI: platforma bir martalik havola beradi, foydalanuvchi uni
    bosadi va bot tokenni oladi -> AYNAN o'sha suhbat ulanadi.

    Token BIR MARTA ishlaydi va ulangan suhbat SHU yurishда xabar oladi."""
    with _TgPatch(with_subscriber=False) as tg:
        notify.save_settings(dict(TEST_SETTINGS, enabled=False,
                                  telegram_enabled=True))
        orig = smtplib.SMTP
        smtplib.SMTP = ExplodingSMTP
        try:
            link = notify.create_link()
            ok(link["url"].startswith("https://t.me/sinov_bot?start="),
               f"havola noto'g'ri: {link['url']}")
            ok(link["token"] in link["url"], "havolada token yo'q")
            eq(notify.link_status(link["token"])["connected"], False,
               "hali bosilmagan havola ulangan deb ko'rsatildi")

            # Foydalanuvchi havolani bosdi -> Telegram "/start <token>" yubordi
            tg.update_text = f"/start {link['token']}"

            res = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600)
            subs = {s["chat_id"] for s in notify.enabled_subscribers()}
            eq(subs, {TEST_CHAT}, "havola bosilgan suhbat ulanmadi")
            eq(notify.link_status(link["token"])["connected"], True,
               "havola ishlatilgan deb belgilanmadi")
            ok(res["telegram"]["sent"] > 0,
               "yangi ulanmaga SHU yurishда xabar ketishi kerak edi")
            ok(len(tg.sent) >= 1, "Telegramga xabar ketmadi")
            CREATED_SENT.update(notify.sent_ids(notify.tg_kind(TEST_CHAT)))

            # TOKEN BIR MARTALIK: o'sha matn qayta kelsa yangi ulanma yo'q
            eq(notify.consume_links()["added"], 0, "token ikkinchi marta ishladi")
        finally:
            smtplib.SMTP = orig
            notify.save_settings(TEST_SETTINGS)


@case
def test_muddati_otgan_havola_ishlamaydi():
    """Muddati o'tgan token bilan ulanib bo'lmaydi — havola boshqa qo'lga
    tushsa ham cheksiz ochiq qolmasligi kerak."""
    with _TgPatch(with_subscriber=False) as tg:
        link = notify.create_link()
        db.execute_returning(
            "UPDATE notify_telegram_link SET expires_at = now() - INTERVAL '1 minute' "
            "WHERE token = %(t)s RETURNING token", {"t": link["token"]})
        tg.update_text = f"/start {link['token']}"
        eq(notify.consume_links()["added"], 0, "muddati o'tgan token ishladi")
        eq(notify.enabled_subscribers(), [], "muddati o'tgan token bilan ulanildi")


@case
def test_ochirilgan_obunachi_xabar_olmaydi():
    """`enabled=false` obunachiga xabar KETMAYDI va /start qayta bosilsa ham
    O'ZI QAYTA YOQILMAYDI (egasi ataylab o'chirgan)."""
    with _TgPatch() as tg:
        notify.save_settings(dict(TEST_SETTINGS, enabled=False,
                                  telegram_enabled=True))
        db.execute_returning(
            "UPDATE notify_telegram_subscriber SET enabled=false "
            "WHERE chat_id=%(c)s RETURNING chat_id", {"c": TEST_CHAT})
        orig = smtplib.SMTP
        smtplib.SMTP = ExplodingSMTP
        try:
            res = notify.run(min_score=0, limit=3, dry_run=False, since_hours=87600)
        finally:
            smtplib.SMTP = orig
            notify.save_settings(TEST_SETTINGS)

        eq(len(tg.sent), 0, "o'chirilgan obunachiga xabar ketdi")
        eq(res["telegram"]["sent"], 0, "o'chirilgan obunachi 'yuborildi' deb hisoblandi")
        # sync (/start) uni QAYTA YOQMASLIGI kerak
        row = db.query_one("SELECT enabled FROM notify_telegram_subscriber "
                           "WHERE chat_id=%(c)s", {"c": TEST_CHAT})
        eq(row["enabled"], False, "o'chirilgan obunachi /start dan keyin qayta yoqildi")


@case
def test_kanallar_mustaqil():
    """Bir kanal yiqilsa IKKINCHISI baribir yuboriladi va xato JIMGINA
    yutilmaydi (natijada `error` maydonida qaytadi)."""
    with _TgPatch(fail="Chat topilmadi (sinov)"):
        notify.save_settings(dict(TEST_SETTINGS, enabled=True,
                                  telegram_enabled=True))
        FakeSMTP.reset()
        orig = smtplib.SMTP
        smtplib.SMTP = FakeSMTP
        try:
            res = notify.run(min_score=0, limit=3, dry_run=False,
                             since_hours=87600, force=True)
            # Telegram yiqildi...
            ok(res["telegram"]["error"], "Telegram xatosi qayd etilmadi")
            eq(res["telegram"]["sent"], 0, "yiqilgan kanal 'yuborildi' demasligi kerak")
            # ...email esa baribir ketdi
            eq(len(FakeSMTP.sent), 1, "Telegram xatosi emailni to'xtatib qo'ydi")
            eq(res["sent"], res["found"], "email yuborilmadi")
            ok("XATO" in (res["message"] or ""), "xato xulosaда ko'rinmadi")
            for t in res["tenders"]:
                CREATED_SENT.add(t["id"])
        finally:
            smtplib.SMTP = orig
            notify.save_settings(TEST_SETTINGS)


@case
def test_telegram_sozlanmagan_aniq_xato():
    """Obunachi yo'q / token yo'q -> ANIQ xato, jimgina o'tmaydi.

    20-vazifadan keyin "nima qilish kerak" degan MASLAHAT tarjimada
    (`err.TELEGRAM_NOT_LINKED`), xato matnida emas — interfeys uch
    tilli va o'zbekcha jumla rus foydalanuvchisiga yordam bermasdi.
    Shu sababli tekshiruv KOD bo'yicha: u sababni bir xil ANIQ
    ko'rsatadi va tarjimaga bog'lanadi.
    """
    # (a) obunachi yo'q — sinov xabari aniq sabab aytadi
    with _TgPatch(with_subscriber=False):
        try:
            notify.send_telegram_test()
            raise AssertionError("obunachi yo'q edi — xato kutilgandi")
        except notify.NotifyError as e:
            ok(e.kod == "TELEGRAM_NOT_LINKED",
               f"xato sababni kod bilan aytmadi: kod={e.kod!r} ({e})")

    # (b) token yo'q — `require_token` HAQIQIY holida qoladi
    eski = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    try:
        try:
            telegram.require_token()
            raise AssertionError("token yo'q edi — xato kutilgandi")
        except telegram.TelegramError as e:
            ok("TELEGRAM_BOT_TOKEN" in str(e), f"xato .env ni ko'rsatmadi: {e}")
        # Yoqishga urinish ham to'xtatiladi
        try:
            notify.save_settings(dict(TEST_SETTINGS, telegram_enabled=True))
            raise AssertionError("tokensiz yoqib bo'lmasligi kerak edi")
        except notify.NotifyError as e:
            ok("TELEGRAM_BOT_TOKEN" in str(e), f"xato matni tushunarsiz: {e}")
    finally:
        if eski is not None:
            os.environ["TELEGRAM_BOT_TOKEN"] = eski
        notify.save_settings(TEST_SETTINGS)


@case
def test_telegram_ochirilganda_yuborilmaydi():
    """telegram_enabled=false -> Bot API ga UMUMAN tegilmaydi."""
    with _TgPatch() as tg:
        notify.save_settings(dict(TEST_SETTINGS, enabled=False,
                                  telegram_enabled=False))
        orig = smtplib.SMTP
        smtplib.SMTP = ExplodingSMTP
        try:
            res = notify.run(min_score=0, limit=3, dry_run=False,
                             since_hours=87600, force=True)
        finally:
            smtplib.SMTP = orig
        eq(len(tg.sent), 0, "o'chirilganда Telegramga xabar ketdi")
        eq(res["telegram"]["sent"], 0, "o'chirilganда 'yuborildi' deyildi")
        ok("o'chirilgan" in (res["telegram"]["message"] or ""),
           f"sabab aytilmadi: {res['telegram']['message']}")


@case
def test_telegram_dry_run():
    """--dry-run: Telegramga ham HECH NARSA ketmaydi."""
    with _TgPatch() as tg:
        notify.save_settings(dict(TEST_SETTINGS, telegram_enabled=True))
        oldin = int(db.scalar("SELECT count(*) FROM notify_sent"))
        orig = smtplib.SMTP
        smtplib.SMTP = ExplodingSMTP
        try:
            res = notify.run(min_score=0, limit=5, dry_run=True, since_hours=87600)
        finally:
            smtplib.SMTP = orig
            notify.save_settings(TEST_SETTINGS)
        eq(len(tg.sent), 0, "dry-run da Telegramga xabar ketdi")
        eq(res["telegram"]["sent"], 0, "dry-run da 'yuborildi' deyildi")
        eq(int(db.scalar("SELECT count(*) FROM notify_sent")), oldin,
           "dry-run BAZAGA YOZDI")


@case
def test_telegram_chat_aniqlash():
    """`discover_chats()` getUpdates javobidan chat ro'yxatini quradi."""
    with _TgPatch():
        chats = telegram.discover_chats()
    eq(len(chats), 1, "bitta suhbat kutilgandi")
    eq(chats[0]["chat_id"], TEST_CHAT, "chat ID")
    eq(chats[0]["title"], "Sinov guruhi", "suhbat nomi")
    eq(chats[0]["type"], "supergroup", "suhbat turi")


@case
def test_qayta_ulash_dublikat_qilmaydi():
    """Bir chat YANGI havola bilan qayta ulansa — dublikat paydo bo'lmaydi,
    ma'lumoti yangilanadi va O'CHIRILGAN ulanma QAYTA YOQILADI.

    (Qayta ulash — foydalanuvchining aniq harakati, shuning uchun tokensiz
    /start dan farqli o'laroq `enabled` ni tiklaydi.)"""
    with _TgPatch(with_subscriber=False) as tg:
        birinchi = notify.create_link()
        tg.update_text = f"/start {birinchi['token']}"
        eq(notify.consume_links()["added"], 1, "birinchi ulanish bo'lmadi")

        # Egasi ulanmani o'chirdi
        db.execute_returning(
            "UPDATE notify_telegram_subscriber SET enabled=false "
            "WHERE chat_id=%(c)s RETURNING chat_id", {"c": TEST_CHAT})

        # YANGI havola bilan qayta ulanadi
        ikkinchi = notify.create_link()
        tg.update_text = f"/start {ikkinchi['token']}"
        notify.consume_links()

        n = int(db.scalar("SELECT count(*) FROM notify_telegram_subscriber "
                          "WHERE chat_id=%(c)s", {"c": TEST_CHAT}))
        eq(n, 1, "obunachilar jadvalида dublikat paydo bo'ldi")
        row = db.query_one(
            "SELECT title, chat_type, enabled, source FROM notify_telegram_subscriber "
            "WHERE chat_id=%(c)s", {"c": TEST_CHAT})
        eq(row["title"], "Sinov guruhi", "nom yangilanmadi")
        eq(row["chat_type"], "supergroup", "tur yangilanmadi")
        eq(row["enabled"], True, "qayta ulanganда ulanma tiklanmadi")
        eq(row["source"], "link", "manba 'link' deb belgilanmadi")


@case
def test_kuzatuv_oynasi():
    """Oxirgi ETL tsiklidan OLDIN ko'rilgan tenderlar tanlanmaydi
    (TZ: bildirishnoma soatlik kuzatish tsikli davomida keladi)."""
    since = notify.last_cycle_since()
    ok(isinstance(since, datetime), "last_cycle_since datetime qaytarishi kerak")

    kelajak = datetime.now(timezone.utc) + timedelta(days=1)
    eq(len(notify.find_candidates(min_score=0, since=kelajak, limit=0)), 0,
       "kelajakdagi oynada tender bo'lmasligi kerak")


# ---------------------------------------------------------------------------
# Tayyorlash / tozalash
# ---------------------------------------------------------------------------
def setup():
    global _ORIGINAL_SETTINGS
    db.init_pool()
    # SMTP — PLATFORMA sozlamasi (.env). Sinov haqiqiy `.env` ga bog'liq
    # bo'lmasligi kerak, shuning uchun muhitni o'zimiz qo'yamiz.
    for k, v in TEST_SMTP_ENV.items():
        _ORIGINAL_SMTP_ENV[k] = os.environ.get(k)
        os.environ[k] = v
    # SQL bazada HAQIQATDA bor ustunlardan quriladi (Telegram/til patchlari
    # qo'llanmagan bo'lishi mumkin) — shuning uchun konstanta emas, funksiya.
    from api import auth
    row = db.query_one(notify.settings_get_sql(),
                       {"company_id": auth.sole_company_id()})
    _ORIGINAL_SETTINGS = dict(row) if row else None

    # QOLDIQNI TANIYMIZ.
    #
    # Agar "asl holat" ning O'ZI sinov fiksturasi bo'lsa — bu oldingi
    # yurish o'ldirilib qolgan qoldiq. Uni "asl" deb qaytarish
    # QOLDIQNI ABADIYLASHTIRADI: har yurish uni suratga oladi va
    # sodiqlik bilan tiklaydi.
    #
    # HAQIQATAN SODIR BO'LDI: `notify_settings.email` da
    # `sinov@example.invalid` va `enabled = true` turgan edi, jurnal
    # tarixida esa doim `enabled=false`.
    global _QOLDIQ_TOPILDI
    # BELGI FAQAT `TEST_EMAIL`.
    #
    # `TEST_BASE = "http://localhost:5173"` HAM ishlatilgan edi va u
    # SOXTA topilma berdi: bu haqiqiy Vite manzili, ya'ni ishlab
    # chiqarish uchun ham to'g'ri qiymat.
    #
    # QOIDA: belgi QONUNIY QIYMAT BO'LA OLMAYDIGAN narsa bo'lsin.
    # `sinov@example.invalid` — RFC 2606 bo'yicha ataylab mavjud
    # emas, ya'ni haqiqiy sozlamada UCHRAY OLMAYDI.
    _QOLDIQ_TOPILDI = bool(
        _ORIGINAL_SETTINGS
        and _ORIGINAL_SETTINGS.get("email") == TEST_EMAIL)
    if _QOLDIQ_TOPILDI:
        print("[!] QOLDIQ TOPILDI: `notify_settings` da sinov qiymatlari "
              "turibdi — oldingi yurish o'ldirilgan.")
        print("    Tiklashda ASL holat emas, XAVFSIZ holat qo'yiladi "
              "(enabled=false, email bo'sh).")
    notify.save_settings(TEST_SETTINGS)


def teardown():
    """SINOV YOZUVLARINI TOZALAYDI: notify_sent qatorlari o'chiriladi,
    notify_settings sinovdan oldingi holatiga qaytariladi."""
    for tid in CREATED_SENT:
        db.execute_returning(
            "DELETE FROM notify_sent WHERE tender_id=%(id)s RETURNING tender_id",
            {"id": tid})
    # Ehtiyot chorasi: sinov emaili / sinov Telegram chati bilan ketgan qatorlar
    for manzil in (TEST_EMAIL, f"tg:{TEST_CHAT}"):
        db.execute_returning(
            "DELETE FROM notify_sent WHERE email=%(e)s RETURNING tender_id",
            {"e": manzil})

    for k, v in _ORIGINAL_SMTP_ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    if _QOLDIQ_TOPILDI:
        # ASL HOLAT EMAS — u qoldiq edi. Xavfsiz holatga qo'yamiz:
        # o'chirilgan va manzilsiz. Bu ishlab chiqarish uchun ham
        # to'g'ri: yetkazib bo'lmaydigan manzil bilan yoqilgan
        # bildirishnoma har tsiklda xato beradi.
        notify.save_settings({"enabled": False, "email": None})
        print("[i] sinov qoldig'i o'rniga XAVFSIZ holat qo'yildi.")
    elif _ORIGINAL_SETTINGS:
        notify.save_settings(_ORIGINAL_SETTINGS)
    else:
        db.execute_returning(
            "DELETE FROM notify_settings WHERE id=1 RETURNING id")

    # MUSBAT TASDIQ: oxirgi holat SINOV QIYMATI EMASLIGI.
    #
    # "Xato chiqmadi" yetarli emas — tiklash ishlaganini ISBOTLAYMIZ.
    oxirgi = db.query_one("SELECT enabled, email, base_url "
                          "FROM notify_settings WHERE id=1")
    if oxirgi:
        # FAQAT emaildan tekshiramiz — `base_url` qonuniy qiymat
        # bo'lishi mumkin va uni tekshirish soxta xato berardi.
        ok(oxirgi["email"] != TEST_EMAIL,
           f"sinov emaili bazada QOLMADI (email={oxirgi['email']})")
    qoldi = int(db.scalar("SELECT count(*) FROM notify_sent WHERE email=%(e)s",
                          {"e": TEST_EMAIL}) or 0)
    print(f"\nTozalandi: {len(CREATED_SENT)} ta notify_sent yozuvi o'chirildi "
          f"(qoldiq: {qoldi}), sozlamalar tiklandi.")


# ---------------------------------------------------------------------------
# BAZASIZ: `notify_new.py` HAR IJARACHI uchun yuradimi
# ---------------------------------------------------------------------------
def test_notify_new_har_ijarachi() -> None:
    """O'LCHANGAN NUQSON (2026-09-09, staging ETL).

    `notify_new.py` kompaniyani UMUMAN so'ramasdi va `notify.run()`
    ichida `auth.sole_company_id()` ga tushardi — u esa AYNAN BITTA
    faol kompaniya bo'lishini talab qiladi:

        AuthError: Bir nechta faol kompaniya: 1(...), 8(...), ...

    Ko'p-ijarachili tizimda bu yagona-ijarachi taxmini. Production da
    u FAQAT SHU KUNGACHA ishlaydi: ikkinchi kompaniya qo'shilgan
    kunda soatlik ETL ning bildirishnoma qadami yiqiladi va HECH KIM
    xabar olmaydi.

    Bazasiz: `notify.run` va `auth.active_companies` o'rniga
    qo'g'irchoq qo'yiladi va skript NIMA CHAQIRGANI o'lchanadi.
    """
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location(
        "zz_notify_new", os.path.join(ROOT, "notify_new.py"))
    nn = _iu.module_from_spec(_sp)
    _sp.loader.exec_module(nn)

    FAOL = [{"id": 1, "username": "alfa"},
            {"id": 8, "username": "beta"},
            {"id": 9, "username": "gamma"}]
    chaqirilgan = []

    def soxta_run(**kw):
        cid = kw.get("company_id")
        chaqirilgan.append(cid)
        if cid == 8:                      # o'rtadagi ijarachi buzuq
            raise nn.notify.NotifyError("sun'iy nosozlik")
        return {"min_score": 50, "since": "x", "found": 0,
                "telegram": {"found": 0}, "message": "ok"}

    asl = (nn.auth.active_companies, nn.notify.run, nn.db.init_pool,
           nn.db.close_pool, nn.ommaviy_url.ishga_tushishda_tekshir,
           sys.argv, os.environ.get("XT_DB_DSN"))
    try:
        nn.auth.active_companies = lambda: list(FAOL)
        nn.notify.run = soxta_run
        nn.db.init_pool = lambda *a, **k: None
        nn.db.close_pool = lambda *a, **k: None
        nn.ommaviy_url.ishga_tushishda_tekshir = lambda *a, **k: None
        os.environ["XT_DB_DSN"] = "dbname=zz"

        # --- 1) STANDART: HAR faol kompaniya ---
        chaqirilgan.clear()
        sys.argv = ["notify_new.py"]
        kod = 0
        try:
            nn.main()
        except SystemExit as e:
            kod = e.code
        eq(chaqirilgan, [1, 8, 9], "har faol kompaniya uchun yuriladi")
        # BITTA IJARACHINING NOSOZLIGI QOLGANLARINI TO'XTATMASIN:
        # 8 yiqildi, lekin 9 baribir chaqirilgan.
        ok(9 in chaqirilgan, "buzuq ijarachidan KEYINGISI ham yuradi")
        # JIM O'TMASIN: chiqish kodi nolga teng bo'lmasin.
        ok(kod not in (0, None), f"nosozlik bo'lsa chiqish kodi != 0 ({kod!r})")
        ok("beta" in str(kod), f"xatoda ijarachi NOMI ko'rinadi: {kod!r}")

        # --- 2) `--company` faqat bittasini yurgizadi ---
        chaqirilgan.clear()
        sys.argv = ["notify_new.py", "--company", "9"]
        try:
            nn.main()
        except SystemExit:
            pass
        eq(chaqirilgan, [9], "`--company` faqat bittasini yurgizadi")

        # --- 3) FAOL KOMPANIYA YO'Q -> XATO ---
        chaqirilgan.clear()
        nn.auth.active_companies = lambda: []
        sys.argv = ["notify_new.py"]
        kod = 0
        try:
            nn.main()
        except SystemExit as e:
            kod = e.code
        eq(chaqirilgan, [], "kompaniya yo'q bo'lsa hech nima chaqirilmaydi")
        ok(kod not in (0, None), "kompaniya yo'q bo'lsa XATO")

        # --- 4) HAMMASI SOG'LOM -> chiqish kodi 0 ---
        chaqirilgan.clear()
        nn.auth.active_companies = lambda: [{"id": 5, "username": "yagona"}]
        sys.argv = ["notify_new.py"]
        kod = 0
        try:
            nn.main()
        except SystemExit as e:
            kod = e.code
        eq(chaqirilgan, [5], "yagona kompaniya ham yuriladi")
        ok(kod in (0, None), f"sog'lom yurishda kod 0 ({kod!r})")
    finally:
        (nn.auth.active_companies, nn.notify.run, nn.db.init_pool,
         nn.db.close_pool, nn.ommaviy_url.ishga_tushishda_tekshir,
         sys.argv, _dsn) = asl
        if _dsn is None:
            os.environ.pop("XT_DB_DSN", None)
        else:
            os.environ["XT_DB_DSN"] = _dsn


def main() -> None:
    # BAZASIZ BO'LIM AVVAL. DSN yo'q muhitda ham bu qism yurishi
    # kerak: u ijarachilar bo'yicha sikl SHARTNOMASINI o'lchaydi va
    # unga baza kerak emas.
    print("--- bazasiz: notify_new ijarachilar sikli ---")
    test_notify_new_har_ijarachi()
    print("  OK   notify_new HAR faol ijarachi uchun yuradi")
    if not os.environ.get("XT_DB_DSN"):
        sys.exit("XATO: XT_DB_DSN o'rnatilmagan (.env).")

    # OMMAVIY URL MUHITDAN KELMASIN — BU SINOVNING SHARTNOMASI.
    #
    # Bu to'plam `notify_settings.base_url` (= `TEST_BASE`) havolani
    # BELGILASHINI o'lchaydi. `api/ommaviy_url` esa MUHITDAGI
    # `APP_PUBLIC_URL` ni bazadagi MAHALLIY qiymatdan ustun qo'yadi —
    # va bu TO'G'RI xulq: ishlab chiqarishda bazada qolib ketgan
    # `localhost` havolalarni buzmasligi kerak.
    #
    # O'LCHANGAN (2026-09-08): darvoza jarayoniga `APP_PUBLIC_URL`
    # uzatila boshlagach uchta tekshiruv yiqildi, masalan
    #
    #   kutilgan 'http://localhost:5173/?tender=…'
    #   olingan  'http://localhost:8091/?tender=…'
    #
    # ya'ni sinov o'zi boshqarmagan o'zgaruvchidan yiqilardi.
    # `deploy_test:test_url_qorovuli` da ayni sinf tuzatilgan edi.
    #
    # MAHSULOT XULQI O'ZGARMAYDI: muhit ustunligi joyida qoladi,
    # sinov shunchaki muhitni O'ZI egallaydi va oxirida tiklaydi.
    _url_eski = {k: os.environ.pop(k, None)
                 for k in ("APP_PUBLIC_URL", "PUBLIC_BASE_URL")}

    setup()
    print(f"Sinovlar: {len(CASES)} ta\n" + "-" * 52)
    try:
        for fn in CASES:
            nomi = fn.__name__
            try:
                fn()
                print(f"  OK    {nomi}")
            except Exception as e:  # noqa: BLE001
                FAILED.append((nomi, e))
                print(f"  XATO  {nomi}: {e}")
    finally:
        teardown()
        for _k, _v in _url_eski.items():
            if _v is not None:
                os.environ[_k] = _v
        db.close_pool()

    print("-" * 52)
    if FAILED:
        print(f"YIQILDI: {len(FAILED)}/{len(CASES)}")
        sys.exit(1)
    print(f"HAMMASI O'TDI: {len(CASES)}/{len(CASES)}")
    print("Haqiqiy email ham, Telegram xabari ham YUBORILMADI "
          "(soxta SMTP va soxta Bot API transportlari).")


if __name__ == "__main__":
    main()
