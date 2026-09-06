#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: OMMAVIY MANZIL — YAGONA MANBA
=====================================

O'LCHANGAN MUAMMO (2026-09-01). Ommaviy havolada `localhost` uch
xil yo'l bilan paydo bo'lardi va UCHALASI ham jimgina o'tardi:

  1. SERVER SOZLAMASI. `APP_ENV=production` va manzil berilmagan
     bo'lsa, xizmat MUAMMOSIZ ko'tarilardi. `/health` va `/ready`
     yashil edi. Nosozlik birinchi bildirishnoma navbatida —
     soatlar keyin, ETL jurnalida — chiqardi.

  2. FRONTEND QURILMASI. `deploy.sh` relizni `git archive` bilan
     yasaydi; `frontend/.env` KUZATILMAGAN fayl va relizga
     tushmaydi. Qurilma `VITE_API_BASE` siz yurardi va zaxira
     qiymat SINGIB QOLARDI (o'lchangan, qurilmadagi hisob):

         localhost:8000   x1    butun API
         localhost:5173   x3    bildirishnoma sozlamasi shakli

     Ya'ni ishlab chiqarish sahifasidagi HAR so'rov foydalanuvchi
     brauzerida `localhost:8000` ga ketardi.

  3. QO'ROVULNING O'ZI. `mahalliymi()` `"localhost" in url` edi —
     matn ichidan qidirish. U `https://10.0.0.5/app` ni OMMAVIY
     deb o'tkazardi (xususiy tarmoq — qabul qiluvchida ochilmaydi)
     va `https://mylocalhost.uz` ni mahalliy deb RAD ETARDI.

BU SINOV QO'RIQLAYDIGAN NARSA:

  - manba BITTA (`api/ommaviy_url.py`); ikkinchi nusxa yo'q;
  - `dev` / `staging` / `production` xulqi BOSHQA va aniq;
  - yaroqsiz sozlama ISHGA TUSHISHDA yiqiladi, yuborishda emas;
  - uchala kanal (email matni, email HTML, Telegram) AYNI havola;
  - frontend manbasida qotirilgan mahalliy manzil yo'q.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\ommaviy_url_test.py
    .venv\\Scripts\\python.exe _tests\\ommaviy_url_test.py --offline
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

_natija = []


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


def oqi(*yol):
    p = os.path.join(ROOT, *yol)
    return io.open(p, encoding="utf-8").read()


class Muhit:
    """Muhit o'zgaruvchilarini VAQTINCHA o'rnatadi va TIKLAYDI.

    Sinov jarayoni bitta — bir tekshiruv qoldirgan qiymat keyingisini
    jimgina yashil qilib qo'yishi mumkin edi.
    """

    KALIT = ("APP_ENV", "APP_PUBLIC_URL", "PUBLIC_BASE_URL")

    def __init__(self, **kw):
        self.yangi = kw

    def __enter__(self):
        self.eski = {k: os.environ.get(k) for k in self.KALIT}
        for k in self.KALIT:
            os.environ.pop(k, None)
        for k, v in self.yangi.items():
            if v is not None:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.eski.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def yiqiladimi(fn, tur):
    """`fn()` AYNAN `tur` istisnosi bilan yiqiladimi.

    Boshqa istisno "o'tdi" deb hisoblanmaydi: `TypeError` bilan
    yiqilgan qo'rovul ham qo'riqlamaydi, u shunchaki buzuq.
    """
    try:
        fn()
    except tur:
        return True, ""
    except Exception as e:                                    # noqa: BLE001
        return False, f"BOSHQA istisno: {type(e).__name__}: {e}"
    return False, "yiqilmadi"


#: Muhitdan O'QISH naqshi — `os.environ[...]`, `os.environ.get(...)`,
#: `getenv(...)`, ichida o'zgaruvchi nomi yoki modul doimiysi bilan.
#: Nomning shunchaki matnda uchrashi (tashxis xabari, istisno matni)
#: BU NAQSHGA TUSHMAYDI — bu ataylab, izohga qarang.
ENV_OQISH_RE = re.compile(
    r"(?:os\.)?(?:environ\s*\.\s*get\s*\(|environ\s*\[|getenv\s*\()"
    r"\s*[^)\]\n]*?(?:APP_PUBLIC_URL|PUBLIC_BASE_URL|ENV_ASOSIY|ENV_ESKI)"
)


def _env_oquvchilar():
    """Muhit o'zgaruvchisini HAQIQATAN o'qiydigan fayllar ro'yxati."""
    topildi = []
    for katalog, _d, fayllar in os.walk(ROOT):
        if any(x in katalog for x in (".venv", "node_modules", ".git",
                                      "__pycache__", "_tests")):
            continue
        for f in fayllar:
            if not f.endswith(".py"):
                continue
            yol = os.path.join(katalog, f)
            src = io.open(yol, encoding="utf-8", errors="replace").read()
            kod = "\n".join(ln for ln in src.split("\n")
                            if not ln.lstrip().startswith("#"))
            if ENV_OQISH_RE.search(kod):
                topildi.append(os.path.relpath(yol, ROOT).replace("\\", "/"))
    return sorted(topildi)


# =====================================================================
def test_yagona_manba():
    bolim("1. YAGONA MANBA — ikkinchi nusxa yo'q")
    from api import ommaviy_url, notify

    check("`api/ommaviy_url.py` moduli bor",
          os.path.exists(os.path.join(ROOT, "api", "ommaviy_url.py")))
    check("asosiy o'zgaruvchi nomi `APP_PUBLIC_URL`",
          ommaviy_url.ENV_ASOSIY == "APP_PUBLIC_URL", ommaviy_url.ENV_ASOSIY)
    check("eski nom `PUBLIC_BASE_URL` saqlangan",
          ommaviy_url.ENV_ESKI == "PUBLIC_BASE_URL", ommaviy_url.ENV_ESKI)

    # Muhitni O'QIYDIGAN yagona fayl — `ommaviy_url.py`. Ikkinchi
    # o'quvchi paydo bo'lsa, u boshqa tartib/zaxira bilan o'qib
    # ikkinchi haqiqat manbai bo'lardi.
    # Izoh qatorlari HISOBGA OLINMAYDI: ular boshqa faylga ishora
    # qilishi mumkin va bu takrorlanish emas. Faqat KOD qidiriladi.
    #
    # NIMA QIDIRILADI — O'QISH, NOM EMAS.
    # ────────────────────────────────────
    # Ilgari bu yerda o'zgaruvchi NOMI qidirilardi (`APP_PUBLIC_URL`
    # matni kodning istalgan joyida). Bu ANIQ invariant emas, uning
    # o'rniga qo'yilgan TAXMIN edi va yolg'on ogohlantirish berdi:
    # `api/topshiriq.py` muhitni umuman o'qimaydi — u to'g'ri yo'l
    # bilan `ommaviy_url.sozlangan()` ni chaqiradi — lekin
    # tashxis MATNIDA o'zgaruvchi nomini tilga oladi
    # ("APP_PUBLIC_URL mahalliy yoki sozlanmagan"). Nom tilga
    # olinishi ikkinchi o'quvchi EMAS.
    #
    # Endi aynan muhitdan O'QISH qidiriladi: `os.environ[...]`,
    # `os.environ.get(...)`, `getenv(...)` — nom yoki modul
    # doimiysi (`ENV_ASOSIY`/`ENV_ESKI`) bilan. Invariant
    # KUCHSIZLANMAYDI, aksincha aniqlashadi: haqiqiy ikkinchi
    # o'quvchi endi ham ushlanadi (pastdagi salbiy sinovga qarang),
    # tashxis matni esa endi yolg'on ogohlantirmaydi.
    oquvchi = _env_oquvchilar()
    check("muhitdan O'QIYDIGAN fayl AYNAN bitta",
          oquvchi == ["api/ommaviy_url.py"], str(oquvchi))

    # SKANERNI SINAYMIZ. Qo'riqchi jimgina "o'tib" ketishi eng oson
    # nuqson: yuqoridagi tekshiruv har doim `[]` qaytarsa ham "o'tdi"
    # bo'lib ko'rinardi. Shuning uchun skaner HAQIQIY ikkinchi
    # o'quvchini topishi alohida tasdiqlanadi.
    soxta = [
        'x = os.environ.get("APP_PUBLIC_URL")',
        'x = os.environ["PUBLIC_BASE_URL"]',
        'x = os.getenv("APP_PUBLIC_URL", "")',
        'x = getenv(ENV_ASOSIY)',
        'x = os.environ.get(ENV_ESKI) or ""',
    ]
    for s in soxta:
        check(f"skaner ikkinchi o'quvchini TOPADI: {s[4:40]}",
              ENV_OQISH_RE.search(s) is not None)
    # Va TESKARISI: shunchaki nom tilga olinishi o'quvchi emas.
    for s in ('out["sabab"] = "APP_PUBLIC_URL sozlanmagan"',
              'raise ValueError("PUBLIC_BASE_URL yaroqsiz")'):
        check(f"nomni TILGA OLISH o'quvchi emas: {s[:38]}",
              ENV_OQISH_RE.search(s) is None)

    nsrc = oqi("api", "notify.py")
    check("`notify.py` manzilni o'zi TANLAMAYDI (uzatadi)",
          "bazaviy_url = ommaviy_url.bazaviy_url" in nsrc)
    check("`card_url()` `ommaviy_url.havola()` dan o'tadi",
          re.search(r"def card_url.*?ommaviy_url\.havola\(", nsrc, re.S)
          is not None)
    # Havolani `ommaviy_url` dan TASHQARIDA qurish taqiqlanadi.
    check("`notify.py` da `f\"{base}...\"` naqshi yo'q",
          not re.search(r'f"\{base[^}]*\}/', nsrc))


def test_tuzilma():
    bolim("2. TUZILMA tekshiruvi — muhitdan qat'i nazar")
    from api import ommaviy_url as ou

    yaroqli = ["https://tender.uz", "http://tender.uz:8080",
               "https://tender.example.uz/app"]
    for u in yaroqli:
        check(f"yaroqli: {u}", ou.nosozliklar(u) == [], str(ou.nosozliklar(u)))

    yaroqsiz = {
        "": "bo'sh",
        "tender.example.uz": "sxemasiz",
        "ftp://tender.uz": "sxema noto'g'ri",
        "https://": "host yo'q",
        "https://tender.uz/?a=1": "so'rov qismi",
        "https://tender.uz/#x": "langar",
        "https://tender uz": "bo'shliq",
    }
    for u, sabab in yaroqsiz.items():
        check(f"yaroqsiz ({sabab}): {u!r}", ou.nosozliklar(u) != [])


def test_mahalliylik():
    bolim("3. MAHALLIYLIK — host bo'yicha, matn ichidan emas")
    from api import ommaviy_url as ou

    # Ilgari `"localhost" in url` edi. Ikki tomonlama xato berardi.
    check("SOXTA MUSBAT tuzatildi: `https://mylocalhost.uz` OMMAVIY",
          not ou.mahalliymi("https://mylocalhost.uz"))
    check("SOXTA MUSBAT tuzatildi: `https://tender.uz/x?ip=127.0.0.1` OMMAVIY",
          not ou.mahalliymi("https://tender.uz/x?ip=127.0.0.1"))
    check("SOXTA MANFIY tuzatildi: `https://10.0.0.5/app` MAHALLIY",
          ou.mahalliymi("https://10.0.0.5/app"))
    check("SOXTA MANFIY tuzatildi: `https://192.168.1.7` MAHALLIY",
          ou.mahalliymi("https://192.168.1.7"))
    check("SOXTA MANFIY tuzatildi: `https://172.16.0.9` MAHALLIY",
          ou.mahalliymi("https://172.16.0.9"))
    check("SOXTA MANFIY tuzatildi: `https://srv.internal` MAHALLIY",
          ou.mahalliymi("https://srv.internal"))

    for u in ("http://localhost:5173", "http://127.0.0.1:8000",
              "http://0.0.0.0:8000", "http://[::1]:8000",
              "http://host.docker.internal:8000"):
        check(f"mahalliy: {u}", ou.mahalliymi(u))
    for u in ("https://tender.example.uz", "https://xt-xarid.uz/procedure/1"):
        check(f"ommaviy: {u}", not ou.mahalliymi(u))


def test_dev():
    bolim("4. `dev` xulqi — mahalliy manzilga RUXSAT")
    from api import ommaviy_url as ou, notify

    with Muhit(APP_ENV="dev"):
        check("sozlanmagan `dev` ISHGA TUSHADI",
              ou.ishga_tushishda_tekshir() == ou.DEV_ZAXIRA)
        check("zaxira mahalliy manzil", ou.bazaviy_url(None) == ou.DEV_ZAXIRA)
        u = notify.card_url("http://localhost:5173", 42)
        check("`dev` da mahalliy havola RUXSAT", "localhost" in u, u)

    with Muhit(APP_ENV="dev", APP_PUBLIC_URL="https://dev.example.uz"):
        check("`dev` da ham muhit qiymati ustun",
              ou.ishga_tushishda_tekshir() == "https://dev.example.uz")


def test_staging_production():
    bolim("5. `staging` / `production` — mahalliy manzil RAD ETILADI")
    from api import ommaviy_url as ou, notify

    for m in ("staging", "production"):
        with Muhit(APP_ENV=m):
            ok, d = yiqiladimi(ou.ishga_tushishda_tekshir, ou.OmmaviyUrlXato)
            check(f"{m}: manzil BERILMASA ishga tushmaydi", ok, d)

        with Muhit(APP_ENV=m, APP_PUBLIC_URL="http://localhost:5173"):
            ok, d = yiqiladimi(ou.ishga_tushishda_tekshir, ou.OmmaviyUrlXato)
            check(f"{m}: MAHALLIY manzil ishga tushirmaydi", ok, d)

        with Muhit(APP_ENV=m, APP_PUBLIC_URL="https://10.0.0.5"):
            ok, d = yiqiladimi(ou.ishga_tushishda_tekshir, ou.OmmaviyUrlXato)
            check(f"{m}: XUSUSIY tarmoq manzili ham rad etiladi", ok, d)

        with Muhit(APP_ENV=m, APP_PUBLIC_URL="tender.example.uz"):
            ok, d = yiqiladimi(ou.ishga_tushishda_tekshir, ou.OmmaviyUrlXato)
            check(f"{m}: SXEMASIZ qiymat rad etiladi", ok, d)

        with Muhit(APP_ENV=m, APP_PUBLIC_URL="https://tender.example.uz/"):
            check(f"{m}: yaroqli manzil O'TADI va oxirgi `/` olib tashlanadi",
                  ou.ishga_tushishda_tekshir() == "https://tender.example.uz")

    # Bazadagi ijarachi qiymati mahalliy bo'lsa MUHIT yutadi.
    with Muhit(APP_ENV="production",
               APP_PUBLIC_URL="https://tender.example.uz"):
        u = notify.card_url("http://localhost:5173", 42)
        check("production: bazadagi mahalliy qiymat MUHIT bilan almashadi",
              u == "https://tender.example.uz/?tender=42", u)

    # Muhit ham berilmagan bo'lsa — YUBORISH TO'XTAYDI (jimgina emas).
    with Muhit(APP_ENV="production"):
        ok, d = yiqiladimi(lambda: notify.card_url("http://localhost:5173", 42),
                           notify.NotifyError)
        check("production: mahalliy havola YUBORISHDA ham to'xtatiladi", ok, d)


def test_eski_nom():
    bolim("6. ESKI NOM va ZIDDIYAT")
    from api import ommaviy_url as ou

    with Muhit(APP_ENV="production", PUBLIC_BASE_URL="https://eski.example.uz"):
        check("eski nom YOLG'IZ ishlaydi (moslik)",
              ou.ishga_tushishda_tekshir() == "https://eski.example.uz")
        check("manba nomi eski deb qaytadi",
              ou.sozlangan()[1] == "PUBLIC_BASE_URL")

    with Muhit(APP_ENV="production",
               APP_PUBLIC_URL="https://a.example.uz",
               PUBLIC_BASE_URL="https://a.example.uz"):
        check("ikkalasi BIR XIL bo'lsa muammo yo'q",
              ou.ishga_tushishda_tekshir() == "https://a.example.uz")

    with Muhit(APP_ENV="production",
               APP_PUBLIC_URL="https://a.example.uz",
               PUBLIC_BASE_URL="https://b.example.uz"):
        # Taxmin qilib bo'lmaydi: ikkita haqiqat manbai.
        ok, d = yiqiladimi(ou.ishga_tushishda_tekshir, ou.OmmaviyUrlXato)
        check("ikkalasi BOSHQA bo'lsa ishga tushmaydi", ok, d)

    with Muhit(APP_ENV="dev",
               APP_PUBLIC_URL="https://a.example.uz",
               PUBLIC_BASE_URL="https://b.example.uz"):
        ok, d = yiqiladimi(ou.ishga_tushishda_tekshir, ou.OmmaviyUrlXato)
        check("ziddiyat `dev` da ham yashirilmaydi", ok, d)


def test_uch_kanal():
    bolim("7. UCHALA KANAL — AYNI havola")
    from api import notify

    # Bazasiz: `_sample()` soxta tender beradi, `render*` esa faqat
    # matn quradi. Ya'ni bu HAQIQIY chiqish tekshiriladi, manba
    # matni emas.
    st = {"min_score": 70, "lang": "uz"}
    tenders = notify._sample(st)
    with Muhit(APP_ENV="production",
               APP_PUBLIC_URL="https://tender.example.uz"):
        kutilgan = "https://tender.example.uz/?tender=0"
        _subj, matn, html = notify.render(tenders, "http://localhost:5173",
                                          70, "uz")
        _h, bloklar, _f = notify.render_telegram(
            tenders, "http://localhost:5173", 70, "uz")
        tg = "\n".join(bloklar)

        check("email MATNIDA to'g'ri havola", kutilgan in matn)
        check("email HTML ida to'g'ri havola", kutilgan in html)
        check("Telegram blokida to'g'ri havola", kutilgan in tg)
        for nom, s in (("email matni", matn), ("email HTML", html),
                       ("Telegram", tg)):
            check(f"{nom} da `localhost` YO'Q", "localhost" not in s)


def test_sozlama_yozish():
    bolim("8. SOZLAMA YOZISH — aniq berilgan mahalliy qiymat RAD ETILADI")
    from api import notify

    # Bu chegara bazasiz tekshiriladi: yordamchi funksiya sof.
    with Muhit(APP_ENV="production",
               APP_PUBLIC_URL="https://tender.example.uz"):
        ok, d = yiqiladimi(
            lambda: notify._base_url_saqlash(
                {"base_url": "http://localhost:5173"}, None),
            notify.NotifyError)
        check("ANIQ berilgan mahalliy qiymat rad etiladi", ok, d)
        # ANIQ BERILMAGAN eski qiymat jimgina tuzatiladi: aks holda
        # eski ijarachi yozuvi tufayli HECH QANDAY sozlamani saqlab
        # bo'lmay qolardi.
        check("berilmagan eski mahalliy qiymat MUHIT bilan tuzatiladi",
              notify._base_url_saqlash({"enabled": True},
                                       "http://localhost:5173")
              == "https://tender.example.uz")
        check("ANIQ berilgan ommaviy qiymat saqlanadi",
              notify._base_url_saqlash(
                  {"base_url": "https://mijoz.example.uz/"}, None)
              == "https://mijoz.example.uz")

    with Muhit(APP_ENV="dev"):
        check("`dev` da mahalliy qiymat yozishga RUXSAT",
              notify._base_url_saqlash(
                  {"base_url": "http://localhost:5173"}, None)
              == "http://localhost:5173")


def test_ishga_tushish_ulangan():
    bolim("9. QO'ROVUL ISHGA TUSHISH YO'LIGA ULANGAN")
    msrc = oqi("api", "main.py")
    check("`lifespan` da qo'rovul chaqiriladi",
          re.search(r"async def lifespan.*?ommaviy_url\."
                    r"ishga_tushishda_tekshir\(\)", msrc, re.S) is not None)
    # BAZADAN OLDIN: sozlama xatosini aniqlash uchun baza kerak emas
    # va baza yo'qligi sozlama xatosini YASHIRMASLIGI kerak.
    i_url = msrc.index("ommaviy_url.ishga_tushishda_tekshir()")
    i_db = msrc.index("db.init_pool()")
    check("qo'rovul `db.init_pool()` DAN OLDIN", i_url < i_db)
    check("xato USHLANMAYDI (xizmat ko'tarilmasin)",
          "try:\n        ommaviy_url.ishga_tushishda_tekshir()" not in msrc)

    nsrc = oqi("notify_new.py")
    check("ETL yuborish skriptida ham qo'rovul bor",
          "ommaviy_url.ishga_tushishda_tekshir()" in nsrc)
    check("ETL da qo'rovul `db.init_pool()` DAN OLDIN",
          nsrc.index("ommaviy_url.ishga_tushishda_tekshir()")
          < nsrc.index("db.init_pool()"))


def test_frontend_manba():
    bolim("10. FRONTEND MANBASI — qotirilgan mahalliy manzil yo'q")
    for yol in (("frontend", "src", "api.ts"),
                ("frontend", "src", "components", "NotifySettings.tsx")):
        src = oqi(*yol)
        nom = "/".join(yol[1:])
        # Izohlarda `localhost` NEGA olib tashlangani yozilgan — u
        # qurilmaga tushmaydi. KOD qatorlarini tekshiramiz.
        kod = [ln for ln in src.split("\n")
               if not ln.lstrip().startswith(("//", "*", "/*", "{/*"))]
        yomon = [ln.strip() for ln in kod
                 if re.search(r"localhost|127\.0\.0\.1", ln)]
        check(f"`{nom}` KODIDA mahalliy manzil yo'q", not yomon,
              "; ".join(yomon)[:120])

    api_ts = oqi("frontend", "src", "api.ts")
    check("`VITE_API_BASE` zaxirasi `/api` (same-origin)",
          "import.meta.env.VITE_API_BASE || '/api'" in api_ts)

    ns = oqi("frontend", "src", "components", "NotifySettings.tsx")
    check("bo'sh shakl `base_url` ni QOTIRMAYDI",
          "base_url: ''," in ns)


def test_qurilma_qorovuli():
    bolim("11. QURILMA QO'ROVULI va JOYLASHTIRISH TEKSHIRUVI")
    v = oqi("frontend", "vite.config.ts")
    check("`vite.config.ts` da qo'rovul plagin bor",
          "ommaviyUrlQorovuli" in v)
    check("qo'rovul FAQAT qurilmada ishlaydi", "apply: 'build'" in v)
    check("qat'iylik `APP_ENV` ga bog'langan (`mode` ga emas)",
          "process.env.APP_ENV" in v)
    check("staging va production QAT'IY",
          "muhit === 'staging' || muhit === 'production'" in v)
    check("qat'iy muhitda qurilma TO'XTAYDI", "throw new Error(" in v)

    d = oqi("deploy", "bin", "deploy.sh")
    check("`deploy.sh` `APP_ENV` ni beradi", 'export APP_ENV="$MUHIT"' in d)
    check("`deploy.sh` `.env.production` ni YOZADI",
          "frontend/.env.production" in d)
    check("muhit fayli QURILMADAN OLDIN o'qiladi",
          d.index('. "$ENVFILE"') < d.index("npm run build"))
    check("qurilma NATIJASI tekshiriladi (localhost qidiriladi)",
          re.search(r"grep -rqE 'localhost[^']*'\s+\"\$\{YANGI\}"
                    r"/frontend/dist/assets\"", d) is not None)
    check("mahalliy manzil topilsa joylashtirish TO'XTAYDI",
          re.search(r"xato \"qurilmada MAHALLIY manzil bor", d) is not None)


def test_muhit_namunalari():
    bolim("12. MUHIT NAMUNALARI")
    for muhit in ("staging", "production"):
        s = oqi("deploy", "env", f"{muhit}.env.example")
        m = re.search(r"^APP_PUBLIC_URL=(.+)$", s, re.M)
        check(f"{muhit}: `APP_PUBLIC_URL` bor", bool(m))
        if m:
            u = m.group(1).strip()
            from api import ommaviy_url as ou
            check(f"{muhit}: namuna manzili MAHALLIY emas",
                  not ou.mahalliymi(u), u)
            check(f"{muhit}: namuna manzili HTTPS", u.startswith("https://"), u)
            check(f"{muhit}: namuna manzili tuzilma bo'yicha yaroqli",
                  ou.nosozliklar(u) == [], str(ou.nosozliklar(u)))
        check(f"{muhit}: eski nom IZOHGA olingan (faol emas)",
              re.search(r"^PUBLIC_BASE_URL=", s, re.M) is None)
        check(f"{muhit}: `VITE_API_BASE=/api`",
              re.search(r"^VITE_API_BASE=/api$", s, re.M) is not None)

    dev = oqi(".env.example")
    check("`.env.example` da `APP_ENV=dev`",
          re.search(r"^APP_ENV=dev$", dev, re.M) is not None)
    check("`.env.example` da `APP_PUBLIC_URL` bor (bo'sh — `dev` uchun)",
          re.search(r"^APP_PUBLIC_URL=$", dev, re.M) is not None)

    # Sir tekshiruvi: `VITE_` prefiksi qurilmaga tushadi, ya'ni u
    # OMMAVIY. Namunada sirga o'xshash qiymat bo'lmasin.
    for muhit in ("staging", "production"):
        s = oqi("deploy", "env", f"{muhit}.env.example")
        vite = re.findall(r"^(VITE_\w+)=(.*)$", s, re.M)
        sirli = [k for k, v in vite
                 if re.search(r"password|secret|token|key", k, re.I)]
        check(f"{muhit}: `VITE_` o'zgaruvchilarida sir YO'Q", not sirli,
              str(sirli))


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Ommaviy manzil sinovi")
    rejim.bayroqlar(ap)
    rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: OMMAVIY MANZIL — YAGONA MANBA")
    print("=" * 70)

    test_yagona_manba()
    test_tuzilma()
    test_mahalliylik()
    test_dev()
    test_staging_production()
    test_eski_nom()
    test_uch_kanal()
    test_sozlama_yozish()
    test_ishga_tushish_ulangan()
    test_frontend_manba()
    test_qurilma_qorovuli()
    test_muhit_namunalari()

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
