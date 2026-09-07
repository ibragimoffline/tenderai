#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: API XATOLARI TILGA BOG'LIQ EMAS
=======================================

O'LCHANGAN MUAMMO (2026-09-01). Interfeys uch tilli (uz/ru/en),
server xatolari esa FAQAT o'zbekcha matn edi:

    api/main.py da 75 ta `HTTPException`
      shundan 28 tasi `detail=str(e)` — ichki modulning o'zbekcha
      matni to'g'ridan-to'g'ri javobga tushardi

Ikki xil zarar:

  1. RUS/INGLIZ tilida ishlayotgan foydalanuvchi xatoni
     O'ZBEKCHA ko'rardi — aynan noto'g'ri ketganda til yo'qolardi.
  2. `str(e)` ICHKI TAFSILOTNI oshkor qilardi: SQL patch nomlari,
     jadval nomlari, SMTP host/port, modul chegaralari.

BU SINOV QO'RIQLAYDIGAN NARSA:

  - javobda KOD bor va u ASCII (tarjima emas, SHARTNOMA);
  - HAR kodning uz/ru/en tarjimasi bor;
  - javob tanasida O'ZBEKCHA/RUSCHA JUMLA yo'q;
  - ichki tafsilot javobga TUSHMAYDI, jurnalga tushadi;
  - modullarda kodsiz `raise` qolmadi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\xato_kodlari_test.py
    .venv\\Scripts\\python.exe _tests\\xato_kodlari_test.py --offline
"""
from __future__ import annotations

import argparse
import io
import os
import re
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


def oqi(*yol):
    return io.open(os.path.join(ROOT, *yol), encoding="utf-8").read()


def lugat(fayl):
    """`frontend/src/locales/<fayl>` dagi `err.*` kalitlari.

    TS ni PARSE QILMAYMIZ — kalit/qiymat juftini naqsh bilan
    olamiz. Qiymat bir tirnoq yoki qo'sh tirnoqda bo'lishi mumkin
    (apostrofli o'zbekcha matnlar qo'sh tirnoqda).
    """
    s = oqi("frontend", "src", "locales", fayl)
    out = {}
    for m in re.finditer(r"^\s*'err\.([A-Z_0-9]+)':\s*(['\"])(.*?)\2,\s*$",
                         s, re.M):
        out[m.group(1)] = m.group(3)
    return out


# =====================================================================
def test_royxat():
    bolim("1. KOD RO'YXATI — muzlatilgan shartnoma")
    from api import xatolar

    kodlar = xatolar.KODLAR
    check("kodlar bor", len(kodlar) > 50, f"{len(kodlar)} ta")

    yomon = [k for k in kodlar if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k)]
    check("har kod ASCII va KATTA HARF", not yomon, str(yomon[:5]))

    # Kod SHARTNOMA: u tarjima emas, ya'ni matn qismi bo'lmasin.
    lotin_bolmagan = [k for k in kodlar if not k.isascii()]
    check("kodda lotin bo'lmagan belgi yo'q", not lotin_bolmagan,
          str(lotin_bolmagan))

    yaroqsiz = {k: v for k, v in kodlar.items() if not (400 <= v <= 599)}
    check("har kodning HTTP holati 4xx/5xx", not yaroqsiz, str(yaroqsiz))

    # Noma'lum kod JIMGINA o'tmasin — aks holda tarjimasiz xato
    # foydalanuvchiga yetib borardi.
    try:
        xatolar.Xato("YOQ_BUNDAY_KOD")
        check("noma'lum kod RAD ETILADI", False, "o'tib ketdi")
    except KeyError:
        check("noma'lum kod RAD ETILADI", True)

    # Kodli xato chegarada UMUMIY kodga almashtirilmasin.
    x = xatolar.Xato("TELEGRAM_TOKEN_MISSING")
    check("`kodli()` mavjud kodni O'ZGARTIRMAYDI",
          xatolar.kodli(x, "FIELD_INVALID").kod == "TELEGRAM_TOKEN_MISSING")
    y = xatolar.kodli(ValueError("xom matn"), "FIELD_INVALID")
    check("`kodli()` kodsiz xatoga kod beradi", y.kod == "FIELD_INVALID")
    check("`kodli()` ichki matnni SAQLAYDI", y.ichki == "xom matn")

    # `Xato` mavjud qo'riqchilar ushlaydigan turlardan meros oladi.
    check("`Xato` — `ValueError`", isinstance(x, ValueError))
    check("`Xato` — `LookupError`", isinstance(x, LookupError))


def test_tarjima():
    bolim("2. TARJIMA TO'LIQLIGI — uz / ru / en")
    from api import xatolar

    kodlar = set(xatolar.KODLAR)
    lug = {t: lugat(f"{t}.ts") for t in ("uz", "ru", "en")}

    for til, d in lug.items():
        yoq = sorted(kodlar - set(d))
        check(f"`{til}.ts` da HAR kod bor", not yoq,
              f"yetishmaydi: {yoq[:6]}")
        ortiq = sorted(set(d) - kodlar)
        check(f"`{til}.ts` da ORTIQCHA kod yo'q", not ortiq,
              f"ortiqcha: {ortiq[:6]}")
        bosh = [k for k, v in d.items() if not v.strip()]
        check(f"`{til}.ts` da bo'sh tarjima yo'q", not bosh, str(bosh[:5]))

    # O'RNIGA QO'YISH BELGILARI uchala tilda BIR XIL bo'lsin: bitta
    # tilda `{id}` bor, ikkinchisida yo'q bo'lsa, o'sha tilda ma'lumot
    # JIMGINA yo'qoladi.
    farq = []
    for k in sorted(kodlar):
        nabor = {t: set(re.findall(r"\{(\w+)\}", lug[t].get(k, "")))
                 for t in lug}
        if len({frozenset(v) for v in nabor.values()}) != 1:
            farq.append((k, nabor))
    check("o'rniga qo'yish belgilari uchala tilda BIR XIL", not farq,
          "; ".join(f"{k}: {v}" for k, v in farq[:3]))

    # Tarjimada KOD nomi qolib ketmasin (nusxa-joylashtirish izi).
    xom = [k for k in kodlar if lug["ru"].get(k, "") == k
           or lug["en"].get(k, "") == k]
    check("tarjima o'rnida KOD qolmagan", not xom, str(xom[:5]))


def test_manba():
    bolim("3. MANBA — kodsiz `raise` qolmadi")
    src_main = oqi("api", "main.py")

    # `HTTPException` faqat FastAPI ning O'ZI ko'targanini ushlash
    # uchun qoldi (ishlovchi). Ilova kodida u ISHLATILMAYDI.
    kotarish = re.findall(r"raise HTTPException\(", src_main)
    check("`api/main.py` da `raise HTTPException` YO'Q", not kotarish,
          f"{len(kotarish)} ta qoldi")
    check("`Xato` ishlovchisi ro'yxatdan o'tgan",
          "@app.exception_handler(xatolar.Xato)" in src_main)
    check("`HTTPException` ishlovchisi ham bor",
          "@app.exception_handler(StarletteHTTPException)" in src_main)
    check("422 (maydon tekshiruvi) ishlovchisi bor",
          "@app.exception_handler(RequestValidationError)" in src_main)

    # Har modulning o'z istisnosi KOD bilan ko'tarilsin.
    kutilgan = {
        ("api/auth.py", r"raise AuthError\("),
        ("api/notify.py", r"raise NotifyError\("),
        ("api/telegram.py", r"raise TelegramError\("),
        ("api/importer.py", r"raise ImportFormatError\("),
        ("api/aktor.py", r"raise RuxsatXato\("),
        ("api/ai.py", r"raise AIUnavailable\("),
        ("api/ai_chat.py", r"raise AIUnavailable\("),
        ("api/ai_match.py", r"raise ai\.AIUnavailable\("),
        ("api/ai_gonogo.py", r"raise ai\.AIUnavailable\("),
        ("api/requirement_ai.py", r"raise ai\.AIUnavailable\("),
    }
    for yol, naqsh in sorted(kutilgan):
        satrlar = oqi(*yol.split("/")).split("\n")
        kodsiz, jami = [], 0
        i = 0
        while i < len(satrlar):
            if re.search(naqsh, satrlar[i]):
                blok, j = satrlar[i], i
                while blok.count("(") > blok.count(")") and j + 1 < len(satrlar):
                    j += 1
                    blok += " " + satrlar[j].strip()
                jami += 1
                if "kod=" not in blok:
                    kodsiz.append(i + 1)
                i = j + 1
            else:
                i += 1
        check(f"`{yol}`: {jami} ta `raise`, hammasi KODLI", not kodsiz,
              f"kodsiz qatorlar: {kodsiz}")

    # Chegaradagi `except ValueError` kodni yutmasin.
    xom = re.findall(r"except ValueError as e:\s*\n\s*raise (?!xatolar\.)",
                     src_main)
    check("chegarada kod yutadigan `except ValueError` yo'q", not xom,
          f"{len(xom)} ta")



def test_hamma_kod_royxatda():
    """HAR BIR ko'tarilgan kod `KODLAR` da bo'lsin — AVTOMATIK topib.

    O'LCHANGAN NUQSON (2026-09-07, birinchi haqiqiy staging darvozasi):

        api/topshiriq.py:288
        raise xatolar.Xato("MIGRATION_MISSING", ...)

    `MIGRATION_MISSING` `KODLAR` da YO'Q edi. `xatolar.Xato` ro'yxatda
    bo'lmagan kodni RAD ETADI, ya'ni `schema_patch_topshiriq.sql`
    qo'llanmagan o'rnatmada bu yo'l aniq 503 o'rniga `KeyError` bilan
    yiqilardi — `topshiriq_test` aynan shunda o'lgan.

    NEGA MAVJUD SINOVLAR USHLAMADI. `test_royxat` ro'yxatning O'ZINI
    tekshiradi (tarjima, HTTP holati), `test_manba` esa faqat
    `api/main.py` dagi `raise HTTPException` larni qaraydi. Kod
    BOSHQA modulda va TO'G'RI shaklda (`xatolar.Xato(...)`)
    ko'tarilganda ikkalasi ham jim qolardi.

    Shuning uchun bu yerda ro'yxat qo'lda yozilmaydi — MANBADAN
    TOPILADI. Yangi modul qo'shilsa u ham avtomatik qamrab olinadi.
    """
    bolim("7. Har bir ko'tarilgan kod ro'yxatda")
    from api import xatolar


    # Ikki shakl ham ishlatiladi:
    #   xatolar.Xato("KOD", ...)          -> pozitsion
    #   AIUnavailable(..., kod="KOD")     -> nomlangan
    RX = [re.compile(r'Xato\(\s*"([A-Z][A-Z0-9_]+)"'),
          re.compile(r'\bkod\s*=\s*"([A-Z][A-Z0-9_]+)"')]

    api_dir = os.path.join(ROOT, "api")
    topilgan = {}
    for fn in sorted(os.listdir(api_dir)):
        if not fn.endswith(".py"):
            continue
        yol = os.path.join(api_dir, fn)
        src = io.open(yol, encoding="utf-8").read()
        # IZOHLAR HISOBGA OLINMASIN: bu faylning o'z izohida ham
        # "MIGRATION_MISSING" yozilgan va u kod EMAS. Aks holda
        # sinov o'zi yasagan yolg'on bilan yiqilardi.
        src = re.sub(r"#[^\n]*", "", src)
        for rx in RX:
            for kod in rx.findall(src):
                topilgan.setdefault(kod, set()).add(fn)

    check(f"{len(topilgan)} ta kod manbadan topildi", len(topilgan) >= 40,
          "juda kam topildi — naqsh eskirgan bo'lishi mumkin")

    yoq = sorted(k for k in topilgan if k not in xatolar.KODLAR)
    check("ko'tarilgan hamma kod `KODLAR` da bor", not yoq,
          "; ".join(f"{k} <- {sorted(topilgan[k])}" for k in yoq))



def test_javob_shakli():
    bolim("4. JAVOB SHAKLI")
    from api import xatolar

    t = xatolar.tana("TENDER_NOT_FOUND", {"id": 42}, "abc12345")
    check("`error.code` bor", t["error"]["code"] == "TENDER_NOT_FOUND")
    check("`error.params` bor", t["error"]["params"] == {"id": 42})
    check("`error.diagnostic_id` bor",
          t["error"]["diagnostic_id"] == "abc12345")
    # ESKI O'QUVCHILAR uchun: `detail` ham TILGA BOG'LIQ EMAS.
    check("`detail` — KOD (o'zbekcha jumla emas)",
          t["detail"] == "TENDER_NOT_FOUND")

    x = xatolar.Xato("SMTP_SEND_FAILED", ichki="SMTP xatosi (mail.uz:587)")
    tana = xatolar.tana(x.kod, x.params)
    check("ICHKI tafsilot javobga TUSHMAYDI",
          "mail.uz" not in str(tana) and "587" not in str(tana), str(tana))
    check("ichki tafsilot xatoning O'ZIDA qoladi (jurnal uchun)",
          "mail.uz" in x.ichki)

    m = xatolar.tana("VALIDATION_ERROR", {"maydonlar": "smtp_port"}, "",
                     [{"field": "smtp_port", "code": "FIELD_PORT_RANGE"}])
    check("422 da `fields` bo'ladi",
          m["error"]["fields"][0]["code"] == "FIELD_PORT_RANGE")
    check("422 dan tashqarida `fields` YO'Q", "fields" not in t["error"])


def test_frontend():
    bolim("5. FRONTEND — kodni O'Z tilida ko'rsatadi")
    # Sof yadro (JSX'siz) —  uni yuklay oladi va
    # `src/xato.test.ts` uni HAQIQATAN chaqiradi.
    i18n = oqi("frontend", "src", "i18n-core.ts")
    check("`xatoMatni()` mavjud", "export function xatoMatni" in i18n)
    check("til `localStorage` dan (React'dan tashqarida)",
          "readLang()" in i18n[i18n.index("export function xatoMatni"):])
    # Tarjima topilmasa KOD ko'rinsin — bo'sh matn EMAS.
    blok = i18n[i18n.index("export function xatoMatni"):]
    blok = blok[:blok.index("\n}")]
    check("tarjima yo'q bo'lsa KOD qaytadi", "? code :" in blok
          or "return s === key ? code" in blok, blok[-90:])

    api_ts = oqi("frontend", "src", "api.ts")
    check("`ApiError` da `code` maydoni bor", "code?: string" in api_ts)
    check("`ApiError` da `diagnosticId` bor", "diagnosticId" in api_ts)
    check("javobdagi `error.code` o'qiladi", "xato.code" in api_ts)
    check("xabar `xatoMatni()` bilan yig'iladi",
          "xatoMatni(kod!" in api_ts or "xatoMatni(kod" in api_ts)
    check("`Retry-After` MATNDAN emas, sarlavhadan",
          "res.headers.get('Retry-After')" in api_ts)


# =====================================================================
def test_ishlayotgan_api():
    """HAQIQIY javoblar — manba matni emas, CHIQISH tekshiriladi."""
    bolim("6. HAQIQIY JAVOBLAR (TestClient)")
    from fastapi.testclient import TestClient

    from api.main import app

    # Kirill yoki o'zbek lotinidagi belgilar javob tanasida
    # BO'LMASLIGI kerak: matn — interfeysning ishi.
    KIRILL = re.compile(r"[\u0400-\u04FF]")
    OZBEK = re.compile(r"[‘’ʻ]|topilmadi|noto'g'ri|kiriting|bo'lsin",
                       re.I)

    with TestClient(app) as c:
        # (a) KIMLIKSIZ so'rov — darvoza
        r = c.get("/tenders")
        check("tokensiz -> 401", r.status_code == 401, str(r.status_code))
        b = r.json()
        check("javobda `error.code` bor",
              isinstance(b.get("error"), dict) and b["error"].get("code"),
              str(b)[:120])
        kod = b["error"]["code"]
        check("kod ASCII", kod.isascii() and kod.isupper(), kod)
        check("javobda KIRILL matn yo'q", not KIRILL.search(str(b)), str(b)[:120])
        check("javobda o'zbekcha jumla yo'q", not OZBEK.search(str(b)),
              str(b)[:120])
        check("`detail` ham kod", b.get("detail") == kod, str(b.get("detail")))
        check("tashxis identifikatori bor",
              bool(b["error"].get("diagnostic_id")), str(b["error"]))
        check("tashxis `X-Request-Id` bilan BIR XIL",
              b["error"]["diagnostic_id"] == r.headers.get("X-Request-Id"),
              f"{b['error'].get('diagnostic_id')} vs "
              f"{r.headers.get('X-Request-Id')}")

        # (b) TIL SARLAVHASI javobni O'ZGARTIRMAYDI — shartnoma
        #     tildan MUSTAQIL.
        kodlar = set()
        for til in ("uz", "ru,en;q=0.9", "en-US"):
            rr = c.get("/tenders", headers={"Accept-Language": til})
            kodlar.add(rr.json()["error"]["code"])
        check("`Accept-Language` kodni O'ZGARTIRMAYDI", len(kodlar) == 1,
              str(kodlar))

        # (c) MAVJUD BO'LMAGAN MARSHRUT — FastAPI ning o'z 404 i ham
        #     kodli bo'lsin (aks holda ikki xil javob shakli bo'lardi).
        r404 = c.get("/bunday-yol-yoq")
        check("noma'lum marshrut -> 404", r404.status_code == 404)
        b404 = r404.json()
        check("FastAPI ning 404 i ham KODLI",
              isinstance(b404.get("error"), dict)
              and b404["error"].get("code"), str(b404)[:120])
        check("404 javobida inglizcha `Not Found` matni yo'q",
              "Not Found" not in str(b404), str(b404)[:120])

        # (d) MAYDON TEKSHIRUVI (422) — maydon nomi qoladi, pydantic
        #     ning INGLIZCHA tushuntirishi olib tashlanadi.
        r422 = c.post("/auth/login", json={"username": "x"})
        check("to'liqmas tana -> 422", r422.status_code == 422,
              str(r422.status_code))
        b422 = r422.json()
        check("422 kodi `VALIDATION_ERROR`",
              b422["error"]["code"] == "VALIDATION_ERROR", str(b422)[:120])
        check("422 da maydon nomlari bor",
              "password" in str(b422["error"]), str(b422["error"])[:150])
        check("422 da pydantic ning inglizcha matni YO'Q",
              "Field required" not in str(b422)
              and "Input should be" not in str(b422), str(b422)[:150])
        check("422 da har maydonning KODI bor",
              all(f.get("code") for f in b422["error"].get("fields", [{}])),
              str(b422["error"].get("fields"))[:150])
        # MAYDON YO'Q va QIYMAT NOTO'G'RI — BOSHQA kod. Ikkalasi
        # `FIELD_INVALID` bo'lsa foydalanuvchi "to'ldirmadimmi yoki
        # xato yozdimmi" degan savolga javob olmasdi.
        check("to'ldirilmagan maydon -> FIELD_REQUIRED",
              b422["error"]["fields"][0]["code"] == "FIELD_REQUIRED",
              str(b422["error"]["fields"]))
    # O'Z validatorlarimiz ham KOD ko'taradi. Ular kimlik
    # darvozasi ORTIDAGI endpointlarda ishlaydi, ya'ni TestClient
    # bilan tokensiz yetib bo'lmaydi — shuning uchun model TO'G'RIDAN
    # chaqiriladi. Ishlovchining `msg` -> kod ajratishi yuqoridagi
    # 422 tekshiruvida allaqachon isbotlangan.
    from pydantic import ValidationError

    from api.main import NotifySettingsIn
    for maydon, qiymat, kutilgan in (
            ("smtp_port", 99999, "FIELD_PORT_RANGE"),
            ("min_score", 500, "FIELD_SCORE_RANGE"),
            ("email", "bu-email-emas", "EMAIL_INVALID")):
        try:
            NotifySettingsIn(**{maydon: qiymat})
            check(f"`{maydon}` yaroqsiz qiymati rad etiladi", False,
                  "qabul qilindi")
        except ValidationError as e:
            xom = str(e.errors()[0]["msg"]).replace("Value error, ", "")
            check(f"`{maydon}` -> {kutilgan}", xom == kutilgan, xom)


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Xato kodlari sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: API XATOLARI TILGA BOG'LIQ EMAS")
    print("=" * 70)

    test_royxat()
    test_tarjima()
    test_manba()
    test_javob_shakli()
    test_hamma_kod_royxatda()
    test_frontend()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] TestClient tekshiruvlari o'tkazib yuborildi (bazasiz).")
    else:
        try:
            test_ishlayotgan_api()
        except Exception as e:                                # noqa: BLE001
            check("TestClient tekshiruvi", False, f"{type(e).__name__}: {e}")

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
