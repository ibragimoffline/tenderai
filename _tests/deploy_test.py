#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: JOYLASHTIRISH ARTEFAKTLARI
==================================

Joylashtirish fayllari kod bilan birga eskiradi va buni HECH NARSA
ko'rsatmaydi — ular faqat serverda ishlaydi. Bu to'plam ularni
repozitoriyada tekshiradi.

HAR TEKSHIRUV AYNAN BITTA TALABGA bog'langan (foydalanuvchi
mezonlari):

  1. Sir repozitoriyaga TUSHMASIN
  2. Ommaviy havolada `localhost` BO'LMASIN
  3. Serverni qayta yuklash hamma xizmatni TIKLASIN
  4. ETL kirgan seanssiz DAVOM ETSIN
  5. Zaxira BOR va tiklash SINALGAN
  6. Ishlab chiqarishga staging'siz joylashtirib BO'LMASIN

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\deploy_test.py
    .venv\\Scripts\\python.exe _tests\\deploy_test.py --offline
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

_natija = []
D = os.path.join(ROOT, "deploy")


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


def oqi(*p):
    return io.open(os.path.join(D, *p), encoding="utf-8").read()


def _oqi_ildiz(yol):
    return io.open(os.path.join(ROOT, yol), encoding="utf-8").read()


# =====================================================================
def test_tuzilma():
    bolim("1. Fayllar joyida")
    kerak = [
        ("systemd", "tenderai-api@.service"),
        ("systemd", "tenderai-etl@.service"),
        ("systemd", "tenderai-etl@.timer"),
        ("systemd", "tenderai-backup@.service"),
        ("systemd", "tenderai-backup@.timer"),
        ("systemd", "tenderai-restore-test@.service"),
        ("systemd", "tenderai-restore-test@.timer"),
        ("caddy", "Caddyfile"),
        ("bin", "deploy.sh"), ("bin", "rollback.sh"), ("bin", "backup.sh"),
        ("bin", "restore-test.sh"), ("bin", "health-check.sh"),
        ("bin", "bootstrap.sh"), ("bin", "oldindan-tekshir.sh"),
        ("env", "staging.env.example"), ("env", "production.env.example"),
    ]
    for p in kerak:
        check("/".join(p), os.path.exists(os.path.join(D, *p)))

    # --- QATOR OXIRI: `\r` skriptni Linux'da O'LDIRADI --------------------
    # O'LCHANGAN XAVF (2026-09-03). `core.autocrlf=true` Windows'da
    # checkout paytida LF ni CRLF ga o'giradi. Repozitoriyadagi nusxa
    # LF bo'lib qoladi, ya'ni SERVER zarar ko'rmaydi — lekin MASHQ
    # ko'radi: 16- va 17-bo'limlar shu skriptlarni HAQIQATAN
    # yurgizadi va CRLF bilan `bash` birinchi qatordayoq yiqiladi
    # ("/usr/bin/env bash^M: bad interpreter").
    #
    # O'LCHANDI: `run_etl.sh` ishchi nusxada ALLAQACHON CRLF edi va
    # buni hech narsa ko'rsatmasdi. `.gitattributes` shuning uchun
    # qo'shildi.
    ga = os.path.join(ROOT, ".gitattributes")
    check("`.gitattributes` mavjud", os.path.isfile(ga))
    if os.path.isfile(ga):
        g = io.open(ga, encoding="utf-8").read()
        for naqsh in ("*.sh text eol=lf", "*.service text eol=lf",
                      "Caddyfile text eol=lf"):
            check(f"`.gitattributes`: {naqsh}", naqsh in g)

    # NAQSH EMAS, NATIJA tekshiriladi: ishchi nusxada `\r` bormi.
    # Windows'da bu HAQIQIY tekshiruv (checkout o'girib qo'yishi
    # mumkin), Linux'da esa har doim toza — ya'ni u yerda bu
    # tekshiruv hech narsa isbotlamaydi va shuni bilib turamiz.
    crlf = []
    for dirpath, _dn, fnames in os.walk(D):
        for fn in fnames:
            if not fn.endswith((".sh", ".service", ".timer")) \
                    and fn != "Caddyfile":
                continue
            p = os.path.join(dirpath, fn)
            if b"\r" in io.open(p, "rb").read():
                crlf.append(os.path.relpath(p, ROOT))
    check("joylashtirish fayllarida `\\r` YO'Q", not crlf, str(crlf[:3]))


def test_sirlar():
    bolim("2. SIR REPOZITORIYAGA TUSHMASIN")
    # `deploy/env/*.env` chetlatilganmi (namunalar esa kuzatiladi).
    gi = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    check("`deploy/env/*.env` chetlatilgan", "deploy/env/*.env" in gi)
    check("`*.env.example` istisno qilingan", "!deploy/env/*.env.example" in gi)

    r = subprocess.run(["git", "ls-files", "deploy/"], capture_output=True,
                       text=True, cwd=ROOT, encoding="utf-8", errors="replace")
    kuzatilgan = [f for f in r.stdout.split() if f]
    yomon = [f for f in kuzatilgan
             if f.endswith(".env") and not f.endswith(".env.example")]
    check("kuzatilgan `.env` fayli YO'Q", not yomon, str(yomon))

    # HAQIQIY qiymat naqshlari. Namunada `REPLACE` va bo'sh qiymatlar
    # bo'lishi KUTILGAN — ular sir emas.
    pats = {
        "anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
        "telegram": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),
        "aws": re.compile(r"AKIA[0-9A-Z]{16}"),
        "shaxsiy_kalit": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
        "dsn_parol": re.compile(r"password=(?!REPLACE)(?!$)\S{6,}"),
        "bcrypt": re.compile(r"\$2[aby]\$\d\d\$(?!REPLACE)[./A-Za-z0-9]{50,}"),
    }
    topildi = []
    for dirpath, _dn, fnames in os.walk(D):
        for fn in fnames:
            p = os.path.join(dirpath, fn)
            t = io.open(p, encoding="utf-8", errors="ignore").read()
            for nom, rx in pats.items():
                if rx.search(t):
                    topildi.append(f"{os.path.relpath(p, ROOT)} [{nom}]")
    check("`deploy/` da haqiqiy sir naqshi YO'Q", not topildi, str(topildi[:3]))

    # Sirlar FAYLDAN o'qilsin, birlik faylida YOZILMASIN.
    api = oqi("systemd", "tenderai-api@.service")
    check("sirlar `EnvironmentFile` dan", "EnvironmentFile=/etc/tenderai/" in api)
    check("birlik faylida parol/kalit YOZILMAGAN",
          not re.search(r"Environment=.*(PASSWORD|API_KEY|TOKEN|DSN)=", api))


def test_localhost():
    bolim("3. OMMAVIY HAVOLADA `localhost` BO'LMASIN")
    # ASOSIY nom 19-vazifada `APP_PUBLIC_URL` ga o'tdi va tanlash
    # mantig'i `api/ommaviy_url.py` ga ko'chdi (yagona manba).
    # BATAFSIL tekshiruv `_tests/ommaviy_url_test.py` da; bu yerda
    # joylashtirish ARTEFAKTLARI tekshiriladi.
    for muhit in ("production", "staging"):
        s = oqi("env", f"{muhit}.env.example")
        m = re.search(r"^APP_PUBLIC_URL=(.*)$", s, re.M)
        check(f"`APP_PUBLIC_URL` {muhit} namunasida bor", bool(m))
        if m:
            u = m.group(1).strip()
            check(f"{muhit} `APP_PUBLIC_URL` mahalliy EMAS",
                  "localhost" not in u and "127.0.0.1" not in u, u)
            check(f"{muhit} `APP_PUBLIC_URL` HTTPS", u.startswith("https://"), u)

    # KOD DARAJASIDA: `dev` dan boshqa muhitda mahalliy havola
    # yuborilmasin — va bu ISHGA TUSHISHDA tekshirilsin, yuborishda
    # emas: aks holda noto'g'ri sozlama soatlab ko'rinmasdi.
    src = io.open(os.path.join(ROOT, "api", "ommaviy_url.py"),
                  encoding="utf-8").read()
    check("`bazani_tekshir()` mavjud", "def bazani_tekshir" in src)
    check("`ishga_tushishda_tekshir()` mavjud",
          "def ishga_tushishda_tekshir" in src)
    nsrc = io.open(os.path.join(ROOT, "api", "notify.py"),
                   encoding="utf-8").read()
    check("`card_url()` yagona quruvchidan o'tadi",
          re.search(r"def card_url.*?ommaviy_url\.havola\(", nsrc, re.S)
          is not None)
    msrc = io.open(os.path.join(ROOT, "api", "main.py"),
                   encoding="utf-8").read()
    check("qo'rovul `lifespan` ga ulangan",
          "ommaviy_url.ishga_tushishda_tekshir()" in msrc)

    # QURILMA: mahalliy manzil frontend qurilmasiga ham singib
    # qolardi (o'lchangan: `localhost:8000` x1, `localhost:5173` x3).
    d = oqi("bin", "deploy.sh")
    check("joylashtirish qurilma NATIJASINI tekshiradi",
          "frontend/dist/assets" in d and "MAHALLIY manzil bor" in d)


def test_qayta_yuklash():
    bolim("4. SERVERNI QAYTA YUKLASH HAMMA XIZMATNI TIKLASIN")
    api = oqi("systemd", "tenderai-api@.service")
    check("API `Restart=always`", "Restart=always" in api)
    check("API `WantedBy=multi-user.target`", "WantedBy=multi-user.target" in api)
    # Cheksiz qayta urinish jurnalni to'ldirib sababni ko'mib tashlardi.
    check("qayta urinish CHEKLANGAN (`StartLimitBurst`)",
          "StartLimitBurst=" in api)
    check("to'xtatishda so'rov tugatiladi (`SIGINT` + timeout)",
          "KillSignal=SIGINT" in api and "TimeoutStopSec=" in api)

    for nom in ("etl", "backup", "restore-test"):
        t = oqi("systemd", f"tenderai-{nom}@.timer")
        check(f"`{nom}` timer `WantedBy=timers.target`",
              "WantedBy=timers.target" in t)


def test_etl_seanssiz():
    bolim("5. ETL KIRGAN SEANSSIZ DAVOM ETSIN")
    svc = oqi("systemd", "tenderai-etl@.service")
    tmr = oqi("systemd", "tenderai-etl@.timer")
    # systemd xizmati SEANSGA bog'liq emas — Windows Task Scheduler'da
    # `LogonType=Interactive` aynan shu sababdan yurishlarni o'ldirgan.
    check("`User=tenderai` (tizim foydalanuvchisi)", "User=tenderai" in svc)
    check("`Type=oneshot`", "Type=oneshot" in svc)
    # Mashina o'chgan bo'lsa — yoqilganda O'TKAZIB YUBORILGANI bajariladi.
    check("`Persistent=true` (o'tkazib yuborilgan yurish bajariladi)",
          "Persistent=true" in tmr)
    check("soatlik jadval", "OnCalendar=" in tmr)
    # Ikki muhit BIR VAQTDA manbaga urilmasin.
    check("tasodifiy kechikish bor", "RandomizedDelaySec=" in tmr)
    # ETL o'zi TOZA to'xtasin; systemd timeout — faqat oxirgi to'siq.
    check("vaqt byudjeti ILOVAGA beriladi (`--max-seconds`)",
          "--max-seconds" in svc)
    check("ETL da `Restart=no` (timer qayta uradi)", "Restart=no" in svc)


def test_zaxira():
    bolim("6. ZAXIRA BOR VA TIKLASH SINALGAN")
    b = oqi("bin", "backup.sh")
    check("`pg_dump` maxsus formatda", "--format=custom" in b)
    # Buzuq dump faqat tiklash paytida bilinardi — eng yomon paytda.
    check("dump OCHILISHI darhol tekshiriladi", "pg_restore --list" in b)
    check("buzuq dump O'CHIRILADI", "rm -f" in b and "OCHILMADI" in b)
    check("sha256 yoziladi", "sha256sum" in b)
    check("eski zaxiralar tozalanadi", "-mtime" in b)

    r = oqi("bin", "restore-test.sh")
    check("tiklash mashqi VAQTINCHALIK bazaga", "SINOV_BAZA=" in r)
    # Bu tekshiruv bo'lmasa mashq ishlab chiqarishni yo'q qilardi.
    check("ishlab chiqarish bazasi bilan ADASHMASLIK tekshiruvi",
          "BIR XIL" in r and "ASOSIY_BAZA" in r)
    check("sha256 tekshiriladi", "sha256sum -c" in r)
    check("tiklash VAQTI o'lchanadi (RTO)", "RTO" in r)
    check("jadval/qator soni tekshiriladi", "N_JADVAL" in r and "N_TENDER" in r)
    check("pgvector tiklanganmi tekshiriladi", "pg_extension" in r)
    check("vaqtinchalik baza TASHLANADI", "DROP DATABASE" in r)

    t = oqi("systemd", "tenderai-restore-test@.timer")
    check("tiklash mashqi JADVALDA (haftalik)", "OnCalendar=Sun" in t)


def test_staging_birinchi():
    bolim("7. ISHLAB CHIQARISHGA STAGING'SIZ JOYLASHTIRIB BO'LMASIN")
    d = oqi("bin", "deploy.sh")
    check("production uchun staging tasdig'i TALAB qilinadi",
          ".verified" in d and "staging tasdigi yoq" in d)
    check("AYNAN SHU ref tekshirilgani solishtiriladi",
          "BOSHQA ref tekshirilgan" in d)
    check("tasdiq staging MUVAFFAQIYATLI tugagach yoziladi",
          re.search(r'if \[ "\$MUHIT" = "staging" \].*?\.verified', d, re.S) is not None)

    check("`current` simvolik havola (atomar almashtirish)", "ln -sfn" in d)
    check("sog'liq tekshiruvi o'tmasa AVTOMATIK qaytariladi",
          "orqaga qaytarilmoqda" in d)
    check("migratsiya EGASI roli bilan", "XT_DB_DSN_OWNER" in d)
    check("frontend QURILADI (dev-server emas)",
          "npm run build" in d and "npm run dev" not in d)

    r = oqi("bin", "rollback.sh")
    check("qaytarish atomar (`ln -sfn`)", "ln -sfn" in r)
    # Avtomatik `down` skript ma'lumot yo'qotishning eng qisqa yo'li.
    check("baza migratsiyasi QAYTARILMAYDI va sababi yozilgan",
          "QAYTARILMAYDI" in r and "ATAYLAB" in r)
    check("qaytargandan keyin sog'liq tekshiriladi", "health-check.sh" in r)


def test_proksi():
    bolim("8. Teskari proksi va HTTPS")
    c = oqi("caddy", "Caddyfile")
    check("staging va production sayti bor",
          c.count("import umumiy") >= 2)
    check("HSTS TLS TERMINATORIDA", "Strict-Transport-Security" in c)
    check("proksi `/ready` ni so'raydi", "health_uri /ready" in c)
    check("frontend STATIK `dist` dan", "frontend/dist" in c)
    check("dev-server ISHLATILMAYDI", ":5173" not in c)
    check("API faqat 127.0.0.1 ga proksi", "reverse_proxy 127.0.0.1:" in c)
    check("staging YOPIQ (basic_auth)", "basic_auth" in c)

    # TANA CHEGARASI IKKALA MUHITDA VA ILOVA CHEGARASI BILAN MOS.
    #
    # NEGA SINOV KERAK: `MAX_UPLOAD_MB` va Caddy `max_size` — ikki
    # AYRIM joyda va Caddy ilova muhitini o'qimaydi. Ular ajralib
    # ketsa nuqson JIM bo'ladi:
    #   proksi kichik  -> foydalanuvchi ilovaning tushunarli xatosi
    #                     o'rniga proksining yalang'och 413 sahifasini
    #                     ko'radi;
    #   proksi katta   -> 500 MB li so'rov ilovagacha yetib boradi.
    import re as _re
    olcham = _re.findall(r"max_size\s+(\d+)MB", c)
    check("proksi tana chegarasi IKKALA muhitda bor",
          len(olcham) >= 2, str(olcham))
    if olcham:
        from api import saqlash as _s
        # Proksi ILOVADAN KATTA bo'lishi shart: multipart o'ramasi
        # (chegara satrlari, sarlavhalar) bir necha KB qo'shadi.
        check("proksi chegarasi ilova chegarasidan KATTA",
              all(int(x) > _s.MAX_UPLOAD_MB for x in olcham),
              f"caddy={olcham} ilova={_s.MAX_UPLOAD_MB}MB")
        # Lekin CHEKSIZ ham emas: 2 barobardan oshsa proksi amalda
        # himoya qilmay qo'yadi.
        check("proksi chegarasi ilova chegarasiga YAQIN",
              all(int(x) <= _s.MAX_UPLOAD_MB * 2 for x in olcham),
              f"caddy={olcham} ilova={_s.MAX_UPLOAD_MB}MB")

    api = oqi("systemd", "tenderai-api@.service")
    check("uvicorn faqat 127.0.0.1 ga bog'lanadi",
          "--host 127.0.0.1" in api and "0.0.0.0" not in api)
    check("proksi sarlavhalari yoqilgan", "--proxy-headers" in api)


def test_zaxira_tashqi():
    bolim("8b. Zaxira — tashqi nusxa va fayl arxivi")
    b = oqi("bin", "backup.sh")
    # ISHLAB CHIQARISHDA TASHQI NUSXA MAJBURIY.
    #
    # NEGA SINOV: ilgari sozlanmagani faqat OGOHLANTIRISH edi va
    # skript 0 bilan tugardi — `systemd` timer uni "muvaffaqiyatli"
    # deb yozardi. Bitta diskdagi zaxira YASHIL ko'rinardi.
    check("production da `BACKUP_REMOTE_CMD` MAJBURIY",
          'elif [ "$MUHIT" = "production" ]' in b and "exit 1" in b)
    check("staging da OGOHLANTIRISH bo'lib qoladi",
          "staging uchun ruxsat" in b)
    # FAYL ARXIVI — `pg_dump` yuklangan hujjatlarni OLMAYDI.
    check("yuklangan fayllar ARXIVLANADI", "FAYL_ARXIV" in b and "tar -czf" in b)
    check("fayl arxivi ham UZOQQA ketadi",
          "FAYL_ARXIV:+" in b)
    check("bo'sh arxiv JIM O'TMAYDI (baza soni bilan solishtiriladi)",
          "FROM yuklama WHERE arxiv_at IS NULL" in b)
    check("`UPLOAD_ROOT` reliz ichida bo'lsa OGOHLANTIRADI",
          "RELIZ ICHIDA" in b)
    r = oqi("bin", "restore-test.sh")
    check("tiklash mashqi fayl arxivini ham tekshiradi",
          "FAYL_ARXIV" in r and "fayl arxivi BO'SH" in r)


def test_e2e_darvozasi():
    bolim("8c. Staging E2E darvozasi — MAJBURIY")
    d = oqi("bin", "deploy.sh")
    # `.verified` NI QIDIRISH YETARLI EMAS: u sarlavha IZOHIDA ham,
    # `TASDIQ=` ta'rifida ham bor va ikkalasi ham fayl BOSHIDA.
    # Ilgari shu shart aynan shuning uchun yiqilgan edi -- skaner
    # NASRni o'qidi, KODni emas. Solishtiriladigan narsa YOZUV AMALI.
    yozuv = '> "${ILDIZ}/.verified"'
    check("`.verified` yozuvi topildi", yozuv in d)
    check("E2E `.verified` YOZUVIDAN OLDIN yuradi",
          "e2e-fayl.sh" in d and yozuv in d
          and d.index("e2e-fayl.sh") < d.index(yozuv))
    # SOZLANMAGANI 'O'TDI' EMAS. `:?` bilan bo'sh o'zgaruvchi
    # skriptni TO'XTATADI.
    for o in ("E2E_URL", "E2E_LOGIN", "E2E_PAROL",
              "E2E_BEGONA_LOGIN", "E2E_BEGONA_PAROL"):
        check(f"`{o}` sozlanmagani XATO (`:?`)", f"{o}:?" in d)
    # `--begona` va `--ai` DOIM beriladi: ularsiz ijarachi
    # chegarasi va iqtibos zanjiri O'LCHANMAYDI.
    check("`--begona` DOIM beriladi", "--begona" in d)
    check("`--ai` DOIM beriladi (iqtibos zanjiri)", "--ai" in d)
    check("E2E yiqilsa ORQAGA QAYTARILADI",
          "E2E YIQILDI" in d and d.count("ln -sfn \"$ESKI\"") >= 2)
    # Skriptning O'ZI ham ikki shartni majburiy qiladi.
    e = oqi("bin", "e2e-fayl.sh")
    check("skript `--begona` siz YIQILADI",
          "ijarachi chegarasi O'LCHANMADI" in e)
    check("skript `--ai` siz YIQILADI",
          "IQTIBOS O'LCHANMADI" in e)
    check("skript javob va iqtibosni AJRATADI",
          "citation" in e and "token" in e and "ajratilgan" in e)
    check("skript BRAUZER sinovi EMASligini aytadi",
          "BRAUZER sinovi EMAS" in e)


def test_sogliq():
    bolim("9. Sog'liq / tayyorlik / ETL yangiligi")
    src = io.open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
    check("`/health` (tiriklik) bor", '@app.get("/health")' in src)
    check("`/ready` (tayyorlik) bor", '@app.get("/ready")' in src)
    check("`/ready` OCHIQ (proksi token ushlamaydi)",
          '"/ready",' in src[src.index("PUBLIC_PATHS = {"):
                             src.index("PUBLIC_PATHS = {") + 900])
    # Tayyor emas bo'lsa 503 — proksi shu kodga qarab kutadi.
    check("tayyor bo'lmasa 503", "status_code = 503" in src)
    # Ochiq endpoint tafsilot SIZDIRMASLIGI kerak.
    blok = src[src.index('@app.get("/ready")'):]
    blok = blok[:blok.index("\n\n\n")]
    check("`/ready` javobida tafsilot YO'Q",
          'v["holat"]' in blok and '"muhit": APP_ENV' not in blok)
    check("`/freshness` (ETL yangiligi) bor", '@app.get("/freshness")' in src)

    h = oqi("bin", "health-check.sh")
    for nom, naqsh in (("tiriklik", "/health"), ("tayyorlik", "/ready"),
                       ("ETL yangiligi", "/freshness"), ("baza", "psql")):
        check(f"sog'liq skripti `{nom}` ni tekshiradi", naqsh in h)
    # ETL hali yurmagan bo'lishi NORMAL — joylashtirish to'xtamasin.
    check("ETL tekshiruvi joylashtirishni TO'XTATMAYDI", "OGOH" in h)


def test_jurnal():
    bolim("10. Tuzilmali jurnal")
    p = os.path.join(ROOT, "api", "jurnal.py")
    check("`api/jurnal.py` mavjud", os.path.exists(p))
    if not os.path.exists(p):
        return
    from api import jurnal
    check("JSON formatlovchi bor", hasattr(jurnal, "JsonFormatter"))
    check("so'rov identifikatori bor", hasattr(jurnal, "yangi_sorov_id"))

    # SIR NIQOBLANADI — nomi bo'yicha, mazmuni bo'yicha emas.
    n = jurnal.niqobla({"password": "sir", "api_key": "sir",
                        "ichki": {"token": "sir"}, "yol": "/tenders"})
    check("`password` niqoblandi", n["password"] == jurnal.NIQOB)
    check("`api_key` niqoblandi", n["api_key"] == jurnal.NIQOB)
    check("ichki `token` ham niqoblandi", n["ichki"]["token"] == jurnal.NIQOB)
    check("oddiy maydon TEGILMAYDI", n["yol"] == "/tenders")

    api_src = io.open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
    check("jurnal ishga tushishda sozlanadi", "jurnal.sozla()" in api_src)
    check("so'rov identifikatori javobga qo'yiladi", "X-Request-Id" in api_src)
    # `/health` har daqiqa so'raladi — jurnalni to'ldirmasin.
    check("sog'liq so'rovlari jurnalni to'ldirmaydi", "shovqin" in api_src)

    svc = oqi("systemd", "tenderai-api@.service")
    check("jurnal `journald` ga", "StandardOutput=journal" in svc)
    check("uvicorn kirish jurnali O'CHIQ (ikki marta yozilmasin)",
          "--no-access-log" in svc)
    stg = oqi("env", "staging.env.example")
    check("`LOG_FORMAT=json` joylashtirishda", "LOG_FORMAT=json" in stg)


# =====================================================================
def test_url_qorovuli():
    bolim("11. `localhost` qo'rovuli — HAQIQIY xulq")
    import importlib
    eski_env = os.environ.get("APP_ENV")
    eski_url = os.environ.get("PUBLIC_BASE_URL")
    try:
        from api import notify

        os.environ["APP_ENV"] = "production"
        os.environ.pop("PUBLIC_BASE_URL", None)
        importlib.reload(notify)
        try:
            notify.card_url("http://localhost:5173", 42)
            check("production da mahalliy havola TO'XTATILADI", False,
                  "o'tib ketdi")
        except notify.NotifyError:
            check("production da mahalliy havola TO'XTATILADI", True)

        os.environ["PUBLIC_BASE_URL"] = "https://tender.example.uz"
        importlib.reload(notify)
        u = notify.card_url("http://localhost:5173", 42)
        check("bazadagi mahalliy qiymat MUHIT bilan almashtiriladi",
              u.startswith("https://tender.example.uz"), u)

        os.environ["APP_ENV"] = "dev"
        os.environ.pop("PUBLIC_BASE_URL", None)
        importlib.reload(notify)
        u = notify.card_url("http://localhost:5173", 42)
        check("`dev` da mahalliy havola RUXSAT (ishlab chiqish)",
              "localhost" in u, u)
    finally:
        if eski_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = eski_env
        if eski_url is None:
            os.environ.pop("PUBLIC_BASE_URL", None)
        else:
            os.environ["PUBLIC_BASE_URL"] = eski_url
        from api import notify as n2
        importlib.reload(n2)


def test_ogohlantirish():
    """NOSOZLIK OGOHLANTIRISHI — ikki qatlam (O-3)."""
    bolim("15. OGOHLANTIRISH — systemd qayta ko'taradi, XABAR BERMASDI")

    check("`ogohlantir.sh` mavjud",
          os.path.exists(os.path.join(D, "bin", "ogohlantir.sh")))
    check("`tenderai-ogohlantirish@.service` mavjud",
          os.path.exists(os.path.join(D, "systemd",
                                      "tenderai-ogohlantirish@.service")))
    src = oqi("bin", "ogohlantir.sh")

    # 1-QATLAM: KRASH. Har xizmat birligida `OnFailure=` bo'lsin —
    # bittasi unutilsa, o'sha xizmat jimgina yiqilardi.
    import glob as _g
    birliklar = [os.path.basename(x) for x in
                 _g.glob(os.path.join(D, "systemd", "tenderai-*.service"))]
    for b in birliklar:
        if "ogohlantirish" in b:
            continue
        u = oqi("systemd", b)
        check(f"`{b}` da `OnFailure=` bor",
              "OnFailure=tenderai-ogohlantirish@" in u,
              "unutilsa o'sha xizmat JIMGINA yiqilardi")

    # 2-QATLAM: SOG'LOM EMAS. `OnFailure` faqat KRASH ni ushlaydi;
    # ko'tarilgan-u sog'lom bo'lmagan xizmat (migratsiya
    # qo'llanmagan, baza yo'q) uchun `systemd` da hammasi joyida.
    check("sog'liq taymeri bor",
          os.path.exists(os.path.join(D, "systemd", "tenderai-health@.timer")))
    t = oqi("systemd", "tenderai-health@.timer")
    check("sog'liq taymeri MUNTAZAM yuradi", "OnUnitActiveSec=" in t)
    hs = oqi("systemd", "tenderai-health@.service")
    check("sog'liq tekshiruvi ham OGOHLANTIRADI",
          "OnFailure=tenderai-ogohlantirish@" in hs)

    # OPERATOR KANALI MIJOZ KANALIDAN ALOHIDA.
    check("operator chati ALOHIDA sozlama", "ALERT_TELEGRAM_CHAT" in src,
          "mijoz obunachilariga texnik xabar ketmasin")
    check("email kanali ham bor", "ALERT_EMAIL" in src)

    # JIM QOLMASIN: hech qayerga ketmagani JURNALGA yozilsin.
    check("hech qayerga ketmagani JURNALGA yoziladi",
          "HECH QAYERGA YUBORILMADI" in src)

    # OGOHLANTIRISH ASL NOSOZLIKNI YASHIRMASIN.
    check("`ogohlantir.sh` har doim 0 qaytaradi",
          src.rstrip().endswith("exit 0"),
          "yiqilsa asl nosozlik yashirinardi")
    u = oqi("systemd", "tenderai-ogohlantirish@.service")
    check("ogohlantirish QAYTA URINMAYDI", "Restart=no" in u,
          "takrorlanishi asl nosozlikdan ko'proq shovqin qilardi")

    for muhit in ("production", "staging"):
        e = oqi("env", f"{muhit}.env.example")
        check(f"{muhit}: `ALERT_TELEGRAM_CHAT` namunada", "ALERT_TELEGRAM_CHAT" in e)
        check(f"{muhit}: `ALERT_EMAIL` namunada", "ALERT_EMAIL" in e)

    # MASHQ QILISH MUMKIN.
    check("`ogohlantir.sh` muhit yo'li ALMASHTIRILADI",
          "TENDERAI_ENVFILE" in src)
    check("`health-check.sh` ham mashq qilinadi",
          "TENDERAI_ENVFILE" in oqi("bin", "health-check.sh"))


def test_tashqi_nusxa():
    """Zaxiraning TASHQI nusxasi (O-2)."""
    bolim("14. TASHQI NUSXA — bitta disk yetarli emas")
    src = oqi("bin", "backup.sh")

    check("`BACKUP_REMOTE_CMD` qo'llab-quvvatlanadi",
          "BACKUP_REMOTE_CMD" in src)
    check("`{fayl}` o'rniga qo'yiladi", "{fayl}" in src)
    # `.sha256` HAM ketishi kerak: butunlikni UZOQDA ham tekshirish
    # imkoni bo'lmasa, tashqi nusxa "bor" bo'ladi-yu "ishonchli"
    # bo'lmaydi.
    check("`.sha256` ham yuboriladi", '"${FAYL}.sha256"' in src)

    # SOZLANMAGANI JIM QOLMASIN.
    check("sozlanmaganda OGOHLANTIRISH yoziladi",
          "BACKUP_REMOTE_CMD sozlanmagan" in src)
    # YIQILSA TO'XTASIN — "zaxira bor" yolg'on xulosa bo'lmasin.
    blok = src[src.index("if [ -n \"${BACKUP_REMOTE_CMD"):]
    blok = blok[:blok.index("# --- ESKILARINI")]
    check("nusxa yiqilsa skript TO'XTAYDI", "exit 1" in blok, blok[-120:])

    # TARTIB: tashqi nusxa TOZALASHDAN OLDIN. Aks holda mahalliy
    # fayl o'chirilib, uzoqqa hech narsa ketmagan bo'lishi mumkin.
    check("tashqi nusxa TOZALASHDAN OLDIN",
          src.index("BACKUP_REMOTE_CMD") < src.index("ESKILARINI TOZALASH"))

    for muhit in ("production", "staging"):
        e = oqi("env", f"{muhit}.env.example")
        check(f"{muhit}: `BACKUP_REMOTE_CMD` namunada bor",
              "BACKUP_REMOTE_CMD" in e)
        # Namunada QIYMAT BO'LMASIN: noto'g'ri manzilga jimgina
        # yuborishdan ko'ra sozlanmagani yaxshi.
        import re as _re
        m = _re.search(r"^BACKUP_REMOTE_CMD=(.*)$", e, _re.M)
        check(f"{muhit}: namunada qiymat BO'SH", bool(m) and not m.group(1).strip(),
              m.group(1) if m else "topilmadi")

    # HALOL CHEKLOV: tashqi nusxaning TIKLANISHI sinalmagan.
    rt = oqi("bin", "restore-test.sh")
    check("tiklash mashqi MAHALLIY fayldan (cheklov yozilgan)",
          "BACKUP_REMOTE_CMD" not in rt,
          "uzoqdagi nusxa tiklanishi hali SINALMAGAN")
    # BO'SHLIQ NORMALLASHTIRILADI: hujjatda ibora qatorlarga
    # bo'linib ketgan edi va tekshiruv soxta yiqilardi.
    d = " ".join(_oqi_ildiz("docs/deploy.md").split()).lower()
    check("cheklov hujjatda yozilgan",
          "tiklanishi hali sinalmagan" in d,
          "uzoqdagi nusxa tiklanishi sinalmagani YOZILISHI shart")


def test_muhit_fayli_shellda():
    """Muhit fayli SHELL bilan o'qilganda BUZILMASIN (B-1)."""
    bolim("13. MUHIT FAYLI — ikki parser, bitta fayl")

    # O'LCHANGAN NUQSON (2026-09-01). `XT_DB_DSN` TIRNOQSIZ edi va
    # bitta fayl IKKI XIL o'qilardi:
    #
    #   systemd `EnvironmentFile=`   butun qatorni oladi  -> TO'G'RI
    #   shell `. envfile`            birinchi bo'shliqda  -> BUZILADI
    #                                kesadi
    #
    # Ya'ni API xizmati to'g'ri DSN olardi, `backup.sh` /
    # `restore-test.sh` / `deploy.sh` esa `dbname=...` ni — user,
    # parol va host YO'QOLGAN holda. Qolgani shellda O'ZGARUVCHI
    # TAYINLASH bo'lib ketardi, ya'ni XATO HAM BERMASDI.
    #
    # Bu skriptlar hech qachon yurgizilmagani uchun payqalmagan.
    # SHELL XULQI `shlex` BILAN TAQLID QILINADI, `bash` CHAQIRILMAYDI.
    #
    # SABAB O'LCHANDI: Windows'da `subprocess` ["bash", ...] ni WSL
    # bash iga yuboradi (`C:\Windows\System32\bash.exe`), Git Bash
    # ga emas — va u yiqiladi. Ya'ni sinov MUHITGA bog'liq bo'lib
    # qolardi va CI da jimgina o'tib ketishi mumkin edi.
    #
    # `shlex` POSIX so'z ajratish qoidasini AYNAN bajaradi: agar
    # `VAR=qiymat` o'ng tomoni bir nechta so'zga bo'linsa, shell
    # faqat BIRINCHISINI tayinlaydi — qolgani yo'qoladi.
    import shlex

    def shellda(matn):
        """Muhit faylini SHELL qanday o'qisa, shunday o'qiydi."""
        out = {}
        for qator in matn.split(chr(10)):
            q = qator.strip()
            if not q or q.startswith("#") or "=" not in q:
                continue
            nom, _, xom = q.partition("=")
            if not nom.replace("_", "").isalnum():
                continue
            try:
                bolaklar = shlex.split(xom, posix=True)
            except ValueError:
                bolaklar = [xom]
            # Shell BIRINCHI so'zni tayinlaydi; qolgani boshqa
            # tayinlash yoki buyruq bo'lib ketadi.
            out[nom] = bolaklar[0] if bolaklar else ""
        return out

    for muhit in ("production", "staging"):
        d = shellda(oqi("env", f"{muhit}.env.example"))
        dsn = d.get("XT_DB_DSN", "")
        egasi = d.get("XT_DB_DSN_OWNER", "")
        url = d.get("APP_PUBLIC_URL", "")
        # DSN da user/parol/host BO'LISHI shart — kesilgan bo'lsa
        # faqat `dbname=...` qoladi.
        for qism in ("user=", "password=", "host="):
            check(f"{muhit}: shellda `{qism}` YO'QOLMADI", qism in dsn,
                  f"olingan: {dsn[:60]!r}")
        check(f"{muhit}: `XT_DB_DSN_OWNER` bor va to'liq",
              "user=" in egasi and "host=" in egasi,
              f"olingan: {egasi[:60]!r}")
        check(f"{muhit}: `APP_PUBLIC_URL` o'qildi", url.startswith("https://"),
              f"olingan: {url[:40]!r}")

    # TAQLIDNING O'ZI SINALADI. Aks holda `shellda()` har doim
    # to'liq qiymat qaytarsa ham sinov yashil bo'lardi.
    soxta = shellda('A=dbname=x user=y host=z' + chr(10)
                    + 'B="dbname=x user=y host=z"')
    check("taqlid TIRNOQSIZ qiymatni KESADI", soxta["A"] == "dbname=x",
          soxta["A"])
    check("taqlid TIRNOQLI qiymatni BUTUN qoldiradi",
          soxta["B"] == "dbname=x user=y host=z", soxta["B"])

    # `deploy.sh` va `restore-test.sh` AYNAN shu faylni SOURCE
    # qiladi — ya'ni yuqoridagi buzilish ularga TO'G'RIDAN-TO'G'RI
    # tegishli.
    for skript in ("deploy.sh", "restore-test.sh", "backup.sh"):
        src = oqi("bin", skript)
        check(f"`{skript}` muhit faylini source qiladi",
              '. "$ENVFILE"' in src)

    # MASHQ QILISH MUMKINMI: yo'l qotirilgan bo'lsa skriptni
    # serverdan tashqarida umuman yurgizib bo'lmaydi — aynan
    # shuning uchun ular hech qachon bajarilmagan edi.
    for skript in ("backup.sh", "restore-test.sh"):
        src = oqi("bin", skript)
        check(f"`{skript}` muhit yo'li ALMASHTIRILADI (mashq uchun)",
              "TENDERAI_ENVFILE" in src)


def test_hujjat():
    bolim("12. Joylashtirish hujjati")
    p = os.path.join(ROOT, "docs", "deploy.md")
    check("`docs/deploy.md` mavjud", os.path.exists(p))
    if not os.path.exists(p):
        return
    d = io.open(p, encoding="utf-8").read()
    for nom, naqsh in (
            ("staging birinchi", "staging"),
            ("orqaga qaytarish", "rollback"),
            ("zaxira va tiklash", "restore-test"),
            ("sirlar", "/etc/tenderai/"),
            ("baza roli", "tai_app"),
            ("HTTPS", "Caddy"),
            ("tiklash mashqi natijasi", "RTO")):
        check(f"hujjatda `{nom}` bor", naqsh in d)



# =============================================================================
# 16. MASHQ — SKRIPTLAR O'QILMAYDI, YURGIZILADI (B-1)
# =============================================================================
# 1-15 bo'limlar HAMMASI `"satr" in fayl_matni` shaklida edi. Ular
# satr borligini isbotlaydi, SKRIPT ISHLASHINI EMAS. B-1 mashqi
# aynan shu farqda beshta HAQIQIY nuqson topdi:
#
#   1. `health-check.sh` tiriklik sikli 210 s gacha cho'zilardi,
#      birlikdagi `TimeoutStartSec` esa 120 s — xizmat yiqilganda
#      tekshiruv O'LDIRILARDI va sabab NOMA'LUM qolardi;
#   2. `psql` cheksiz kutishi mumkin edi (byudjetsiz);
#   3. uzilishda javob kodi `000000` bo'lib chiqardi;
#   4. `--royxat` da `*` belgisi ota-katalog simvolik havola bo'lsa
#      YO'QOLARDI — operator qaysi reliz tirikligini bilmasdi;
#   5. `rollback.sh` `current` ni almashtirib, xizmatni qayta
#      ishga tushirib, ANDIN sog'liqni tekshirardi — ya'ni yarim
#      relizga qaytarish UZILISHNI O'ZI KELTIRIB CHIQARARDI.
#
# Hech biri grep bilan ko'rinmasdi.
# =============================================================================

def _mashq_bash():
    """Repozitoriyani KO'RADIGAN bash topiladi.

    Windows'da `subprocess` oddiy `bash` ni WSL ga yuboradi va u
    `d:\\...` ni ko'rmaydi (13-bo'limdagi bilan ayni sabab). Shuning
    uchun nomzodlar SINAB ko'riladi: repodagi faylni ko'ra olgani
    qabul qilinadi.
    """
    nomzodlar = []
    if os.name == "nt":
        nomzodlar += [r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files (x86)\Git\bin\bash.exe"]
        g = shutil.which("git")
        if g:
            nomzodlar.append(os.path.join(os.path.dirname(os.path.dirname(g)),
                                          "bin", "bash.exe"))
    nomzodlar.append(shutil.which("bash") or "bash")
    for b in nomzodlar:
        if not b or not os.path.exists(b):
            continue
        try:
            r = subprocess.run([b, "-c", 'test -f "$1" && echo BOR', "_",
                                "deploy/bin/rollback.sh"],
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=30)
            if "BOR" in r.stdout:
                return b
        except Exception:
            continue
    return None


def _posix_yol(bash, yol):
    """Windows yo'lini shu bash ko'radigan shaklga o'tkazadi."""
    if os.name != "nt":
        return yol
    r = subprocess.run([bash, "-c", 'cygpath -u "$1"', "_", yol],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() or yol


def _shimlar(qutі, jurnal):
    """`sudo`/`systemctl`/`ln` uchun mashq shimlari.

    `ln` FAQAT Windows'da almashtiriladi: MSYS `ln -s` imtiyozsiz
    yiqiladi va JIMGINA katalog NUSXASI qoldiradi — u holda atomar
    almashtirish mashqi SOXTA bo'lardi. NTFS "junction" imtiyoz
    talab qilmaydi va MSYS uni simvolik havola deb ko'radi.
    Joylashtirish skriptlarining O'ZI o'zgartirilmaydi.
    """
    os.makedirs(qutі, exist_ok=True)
    N = chr(10)
    yoz = lambda nom, matn: (
        io.open(os.path.join(qutі, nom), "w", encoding="utf-8",
                newline=N).write(matn),
        os.chmod(os.path.join(qutі, nom), 0o755))
    yoz("sudo", "#!/bin/sh" + N + 'exec "$@"' + N)
    yoz("systemctl",
        "#!/bin/sh" + N + 'echo "systemctl $*" >> "' + jurnal + '"' + N)
    # `psql` — mashqda BAZA YO'Q. `deploy.sh` endi `oldindan-tekshir.sh`
    # ni chaqiradi va u DSN larni HAQIQATAN ulanib tekshiradi (taxmin
    # emas, o'lchov). Shimsiz mashq bazaning yo'qligidan yiqilardi —
    # ya'ni 16-bo'lim o'lchayotgan narsaga aloqasi yo'q sababdan.
    yoz("psql", "#!/bin/sh" + N + "echo 1" + N + "exit 0" + N)
    if os.name == "nt":
        # `$L`/`$T` — SHELL o'zgaruvchilari (qo'sh tirnoq ichida
        # yoyiladi). PowerShell ning O'Z `$false` i esa `\$` bilan
        # QOCHIRILADI, aks holda shell uni bo'sh satrga aylantirardi
        # va junction hech qachon yaratilmasdi (JIMGINA).
        #
        # `\\$` IKKI belgi bilan yozilgan: Python `"\$"` ni HOZIR
        # `\$` deb qoldiradi, lekin buni `SyntaxWarning` bilan
        # ogohlantiradi va kelgusi versiyada TO'XTATADI. O'shanda
        # butun mashq mexanizmi (16- va 17-bo'limlar) ishlamay
        # qolardi — qobiqqa yetib boradigan matn esa AYNI.
        ps = ("powershell.exe -NoProfile -NonInteractive -Command \""
              "if (Test-Path -LiteralPath '$L') {"
              " (New-Object System.IO.DirectoryInfo('$L')).Delete(\\$false)"
              " };"
              " New-Item -ItemType Junction -Path '$L' -Target '$T'"
              " | Out-Null\" >/dev/null 2>&1")
        yoz("ln",
            "#!/bin/sh" + N
            + 'if [ "$1" = "-sfn" ]; then' + N
            + '    T=$(cygpath -w "$2"); L=$(cygpath -w "$3")' + N
            + "    " + ps + N
            + '    [ -e "$3" ] || exit 1' + N
            + "    exit 0" + N
            + "fi" + N
            + 'exec /usr/bin/ln "$@"' + N)


class _SoxtaAPI(threading.Thread):
    """/health, /ready, /freshness beradigan eng kichik xizmat."""

    def __init__(self, holat="sogolom"):
        super().__init__(daemon=True)
        self.holat = holat
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        ota = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/health":
                    kod, tana = 200, {"holat": "ok"}
                elif self.path == "/ready":
                    if ota.holat == "tayyor_emas":
                        kod, tana = 503, {"tayyor": False}
                    else:
                        kod, tana = 200, {"tayyor": True, "baza": "ok"}
                elif self.path == "/freshness":
                    kod, tana = 200, {"overall_age_sec": 1200}
                else:
                    kod, tana = 404, {}
                b = json.dumps(tana).encode()
                self.send_response(kod)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.srv = HTTPServer(("127.0.0.1", self.port), H)

    def run(self):
        self.srv.serve_forever()

    def toxta(self):
        self.srv.shutdown()


def test_mashq():
    bolim("16. MASHQ — skriptlar HAQIQATAN yurgiziladi")

    h = oqi("bin", "health-check.sh")
    birlik = oqi("systemd", "tenderai-health@.service")

    # --- BYUDJET ARIFMETIKASI (bu tekshiruv MUHITSIZ ham ishlaydi) ---------
    # Skriptning eng yomon vaqti birlikdagi `TimeoutStartSec` dan
    # KICHIK bo'lishi SHART. Aks holda xizmat yiqilganda systemd
    # tekshiruvning O'ZINI o'ldiradi va nosozlik sababi yo'qoladi.
    ts = re.search(r"TimeoutStartSec=(\d+)", birlik)
    check("birlikda `TimeoutStartSec` bor", ts is not None)
    kutish = re.search(r'KUTISH="\$\{HEALTH_WAIT_SEC:-(\d+)\}"', h)
    check("tiriklik byudjeti O'ZGARUVCHI (takror soni EMAS)",
          kutish is not None and "for _ in $(seq 1 30); do" not in h)
    check("tiriklik sikli MUDDAT bilan cheklangan",
          "MUDDAT=" in h and 'date +%s' in h)
    if ts and kutish:
        maxt = [int(x) for x in re.findall(r"--max-time (\d+)", h)]
        db = re.search(r'BAZA_KUTISH="\$\{HEALTH_DB_TIMEOUT_SEC:-(\d+)\}"', h)
        # tiriklik byudjeti + qolgan tekshiruvlar (tiriklik `--max-time`
        # allaqachon byudjet ichida, shuning uchun eng kattasi tashlanadi)
        eng_yomon = int(kutish.group(1)) + sum(sorted(maxt)[:-1] or [0])
        eng_yomon += int(db.group(1)) if db else 0
        check("ENG YOMON vaqt birlik `TimeoutStartSec` dan KICHIK",
              eng_yomon < int(ts.group(1)),
              f"{eng_yomon}s vs TimeoutStartSec={ts.group(1)}s")
    check("`psql` ham byudjetli (cheksiz kutmaydi)",
          "PGCONNECT_TIMEOUT" in h)
    check("uzilishda javob kodi BUZILMAYDI (`000000` emas)",
          "2>/dev/null || echo 000)" not in h)

    # --- MASHQ MUHITI ------------------------------------------------------
    bash = _mashq_bash()
    # MUHIT YO'Q BO'LSA JIMGINA O'TIB KETILMAYDI: mashq qilib
    # bo'lmasligi ham NATIJA — aynan shuning uchun bu skriptlar
    # oylab bajarilmagan edi.
    check("mashq muhiti bor (repozitoriyani ko'radigan `bash`)",
          bash is not None,
          "" if bash else "topilmadi — skriptlar YURGIZILMADI, faqat O'QILDI")
    if not bash:
        return

    baza = tempfile.mkdtemp(prefix="tenderai_mashq_")
    api = _SoxtaAPI()
    api.start()
    try:
        qutі = os.path.join(baza, "shim")
        jurnal_w = os.path.join(baza, "systemctl.log")
        _shimlar(qutі, _posix_yol(bash, jurnal_w))

        envfile = os.path.join(baza, "staging.env")
        io.open(envfile, "w", encoding="utf-8", newline=chr(10)).write(
            "APP_ENV=staging" + chr(10)
            + f"API_PORT={api.port}" + chr(10)
            + 'XT_DB_DSN="host=127.0.0.1 dbname=x user=y password=z"' + chr(10))

        ildiz = os.path.join(baza, "opt", "staging")
        relizlar = os.path.join(ildiz, "releases")
        toliq = []
        for nom in ("20260101-120000-v1", "20260102-120000-v2",
                    "20260103-120000-v3"):
            d = os.path.join(relizlar, nom)
            os.makedirs(os.path.join(d, "deploy", "bin"))
            os.makedirs(os.path.join(d, "api"))
            shutil.copy(os.path.join(ROOT, "deploy", "bin", "health-check.sh"),
                        os.path.join(d, "deploy", "bin"))
            shutil.copy(os.path.join(ROOT, "api", "main.py"),
                        os.path.join(d, "api"))
            toliq.append(nom)
            time.sleep(1.1)   # `ls -1dt` tartibi vaqtga tayanadi
        # YIQILGAN joylashtiruvdan qolgan YARIM reliz
        yarim = "20260904-090000-yarim"
        os.makedirs(os.path.join(relizlar, yarim))

        muhit = dict(os.environ)
        # PATH `bash` NING O'ZIDA qo'yiladi. `os.pathsep` Windows'da
        # `;` va uni bash BO'LMAYDI -- shim topilmay qolardi va
        # `ln -sfn` haqiqiy `ln` ga tushib "failed to create
        # symbolic link" berardi. Mashq shunda JIMGINA soxta
        # bo'lardi: `current` almashmasdi, sinov esa "o'zgarmadi"
        # deb YASHIL qolishi mumkin edi.
        shim_p = _posix_yol(bash, qutі)
        muhit["TENDERAI_ILDIZ"] = _posix_yol(bash, ildiz)
        muhit["TENDERAI_ENVFILE"] = _posix_yol(bash, envfile)
        muhit["HEALTH_WAIT_SEC"] = "5"     # mashq tez bo'lsin

        def yurgiz(skript, *arg, **kw):
            e = dict(muhit)
            e.update(kw.pop("qoshimcha", {}))
            r = subprocess.run(
                [bash, "-c", 'PATH="$1:$PATH"; shift; exec "$@"', "_",
                 shim_p, f"deploy/bin/{skript}", *arg],
                cwd=ROOT, env=e, capture_output=True,
                text=True, timeout=kw.get("muddat", 180))
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        def joriy():
            r = subprocess.run(
                [bash, "-c", 'basename "$(readlink -f "$1")"', "_",
                 muhit["TENDERAI_ILDIZ"] + "/current"],
                capture_output=True, text=True, timeout=30)
            return r.stdout.strip()

        def qoy(nom):
            subprocess.run([bash, "-c",
                            'PATH="$1:$PATH"; ln -sfn "$2" "$3"', "_",
                            shim_p,
                            muhit["TENDERAI_ILDIZ"] + "/releases/" + nom,
                            muhit["TENDERAI_ILDIZ"] + "/current"],
                           capture_output=True, text=True, timeout=60)

        qoy(toliq[-1])
        check("mashq maydoni tayyor (`current` simvolik havola ishlaydi)",
              joriy() == toliq[-1],
              f"kutilgan {toliq[-1]}, olingan {joriy()!r} — "
              "simvolik havola yaratilmagan bo'lsa mashqning O'ZI soxta")

        # --- health-check.sh: SOG'LOM ------------------------------------
        kod, chiq = yurgiz("health-check.sh", "staging")
        check("sog'liq: sog'lom xizmatda 0 qaytaradi", kod == 0, f"kod={kod}")
        check("sog'liq: tiriklik VA tayyorlik ALOHIDA o'lchanadi",
              "tiriklik /health" in chiq and "tayyorlik /ready" in chiq)

        # --- health-check.sh: TAYYOR EMAS (503) --------------------------
        # `deploy.sh` ning AVTOMATIK QAYTARISHI aynan shunga tayanadi.
        api.holat = "tayyor_emas"
        kod, chiq = yurgiz("health-check.sh", "staging")
        check("sog'liq: /ready 503 bo'lsa 1 qaytaradi", kod == 1, f"kod={kod}")
        check("sog'liq: tiriklik O'TDI, tayyorlik YIQILDI deb ajratadi",
              "[OK  ] tiriklik" in chiq and "[XATO] tayyorlik" in chiq)
        api.holat = "sogolom"

        # --- health-check.sh: XIZMAT YO'Q, BYUDJET ICHIDA ----------------
        api.toxta()
        t0 = time.time()
        kod, chiq = yurgiz("health-check.sh", "staging")
        ketdi = time.time() - t0
        check("sog'liq: xizmat yo'q bo'lsa 1 qaytaradi", kod == 1)
        # 5 s tiriklik + 10 s tayyorlik + biroz zaxira.
        check("sog'liq: byudjetdan OSHMAYDI (systemd o'ldirmasin)",
              ketdi < 40, f"{ketdi:.0f}s")
        check("sog'liq: uzilishda javob kodi BUZUQ emas",
              "000000" not in chiq)
        api = _SoxtaAPI()   # yangi port bilan qayta ko'tariladi
        api.start()
        io.open(envfile, "w", encoding="utf-8", newline=chr(10)).write(
            "APP_ENV=staging" + chr(10)
            + f"API_PORT={api.port}" + chr(10)
            + 'XT_DB_DSN="host=127.0.0.1 dbname=x user=y password=z"' + chr(10))

        # --- rollback.sh --royxat ----------------------------------------
        kod, chiq = yurgiz("rollback.sh", "staging", "--royxat")
        check("qaytarish: ro'yxat 0 qaytaradi", kod == 0, f"kod={kod}")
        belgili = [q for q in chiq.split(chr(10)) if q.strip().startswith("*")]
        check("qaytarish: HOZIRGI reliz `*` bilan BELGILANADI",
              len(belgili) == 1 and toliq[-1] in belgili[0],
              f"belgilangan: {belgili}")

        # --- rollback.sh: YARIM relizga -> RAD, `current` TEGILMAYDI -----
        oldin = joriy()
        kod, chiq = yurgiz("rollback.sh", "staging", yarim)
        check("qaytarish: YARIM relizga qaytarish RAD ETILADI", kod == 1,
              f"kod={kod}")
        check("qaytarish: rad etilganda `current` O'ZGARMAYDI",
              joriy() == oldin, f"{oldin} -> {joriy()}")
        check("qaytarish: nima yetishmagani AYTILADI",
              "YARIM RELIZ" in chiq and "api/main.py" in chiq)
        check("qaytarish: chiqish yo'li ko'rsatiladi", "--majburiy" in chiq)

        # --- rollback.sh: TO'LIQ relizga -> ishlaydi ---------------------
        kod, chiq = yurgiz("rollback.sh", "staging", toliq[0])
        check("qaytarish: to'liq relizga qaytarish ISHLAYDI", kod == 0,
              f"kod={kod}")
        check("qaytarish: `current` HAQIQATAN almashdi",
              joriy() == toliq[0], joriy())
        jurnal = ""
        if os.path.exists(jurnal_w):
            jurnal = io.open(jurnal_w, encoding="utf-8").read()
        check("qaytarish: xizmat QAYTA ISHGA TUSHIRILADI",
              "restart tenderai-api@staging" in jurnal, jurnal[:120])

        # --- deploy.sh: PRODUCTION DARVOZASI -----------------------------
        pildiz = os.path.join(baza, "opt", "production")
        os.makedirs(os.path.join(pildiz, "releases"))

        # PRODUCTION uchun ALOHIDA muhit fayli. Sabab: `deploy.sh`
        # endi `oldindan-tekshir.sh` ni chaqiradi va u `APP_ENV` ni
        # joylashtirilayotgan muhit bilan SOLISHTIRADI — yuqoridagi
        # `staging.env` bilan production joylashtiruvi (to'g'ri
        # ravishda) rad etilardi. Bitta fayl ikki muhitga
        # ISHLATILMASLIGI kerak, mashqda ham.
        penv = os.path.join(baza, "production.env")
        pzaxira = os.path.join(baza, "zaxira")
        os.makedirs(os.path.join(pzaxira, "production"), exist_ok=True)
        io.open(penv, "w", encoding="utf-8", newline=chr(10)).write(
            chr(10).join([
                "APP_ENV=production",
                "API_PORT=8000",
                "API_DOCS=0",
                "AUTH_COOKIE_SECURE=1",
                "TRUST_PROXY=1",
                "CORS_ORIGINS=",
                "APP_PUBLIC_URL=https://tender.mashq.uz",
                "VITE_API_BASE=/api",
                'XT_DB_DSN="dbname=t user=tai_app password=p1 host=127.0.0.1"',
                'XT_DB_DSN_OWNER="dbname=t user=postgres password=p2 host=127.0.0.1"',
                "BACKUP_DIR=" + _posix_yol(bash, pzaxira),
                "",
            ]))
        pmuhit = {"TENDERAI_ILDIZ": _posix_yol(bash, pildiz),
                  "TENDERAI_STAGING_ILDIZ": _posix_yol(bash, ildiz),
                  "TENDERAI_ENVFILE": _posix_yol(bash, penv),
                  # Caddy mashq mashinasida yo'q -> "tekshirilmadi"
                  # (to'siq EMAS). Aniq ko'rsatiladi, chunki
                  # `/etc/caddy/Caddyfile` HAQIQATAN bor bo'lsa
                  # mashq server sozlamasini o'qib qolardi.
                  "TENDERAI_CADDYFILE": "/mavjud/bolmagan/Caddyfile"}
        tasdiq = os.path.join(ildiz, ".verified")
        if os.path.exists(tasdiq):
            os.remove(tasdiq)
        kod, chiq = yurgiz("deploy.sh", "production", "v1.2.3",
                           qoshimcha=pmuhit)
        check("joylashtirish: staging TASDIG'I yo'q -> RAD", kod == 1,
              f"kod={kod}")
        io.open(tasdiq, "w", encoding="utf-8").write("v1.2.2")
        kod, chiq = yurgiz("deploy.sh", "production", "v1.2.3",
                           qoshimcha=pmuhit)
        check("joylashtirish: BOSHQA ref tekshirilgan -> RAD", kod == 1,
              f"kod={kod}")
        check("joylashtirish: qaysi ref tekshirilgani AYTILADI",
              "v1.2.2" in chiq and "v1.2.3" in chiq)

        # --- deploy.sh: YIQILSA YARIM RELIZ QOLMAYDI ---------------------
        # `git archive` mavjud bo'lmagan repoda yiqiladi — mashqda
        # AYNAN shu yuz bergan edi va bo'sh reliz katalogi qolgandi.
        io.open(tasdiq, "w", encoding="utf-8").write("v9.9.9")
        pm = dict(pmuhit)
        pm["TENDERAI_REPO"] = "/mavjud/bolmagan/repo.git"
        kod, chiq = yurgiz("deploy.sh", "production", "v9.9.9",
                           qoshimcha=pm)
        qolgan = os.listdir(os.path.join(pildiz, "releases"))
        check("joylashtirish: yiqilgach YARIM RELIZ QOLMAYDI",
              qolgan == [], str(qolgan))
        check("joylashtirish: tozalash JIMGINA emas",
              "yarim reliz olib tashlanmoqda" in chiq)
    finally:
        try:
            api.toxta()
        except Exception:
            pass
        shutil.rmtree(baza, ignore_errors=True)

# =====================================================================
def test_joylashuv_izchilligi():
    """Proksi ortidagi sozlamalar ZIDDIYATI ISHGA TUSHISHDA tutilsin.

    O'LCHANGAN XAVF (2026-09-03). Uchta sozlama bir-biriga bog'liq,
    lekin uch xil joyda: `APP_PUBLIC_URL`, `TRUST_PROXY`,
    `AUTH_COOKIE_SECURE`. `deploy/env/*.example` to'g'ri, lekin
    haqiqiy `/etc/tenderai/<muhit>.env` QO'LDA tahrirlanadi
    (`docs/deploy.md` §3) — ziddiyat qonuniy yo'l bilan paydo bo'ladi.

    ENG XAVFLISI: `http://` + `AUTH_COOKIE_SECURE=1`. Brauzer
    `Secure` cookie ni shifrlanmagan ulanish orqali YUBORMAYDI,
    ya'ni xizmat ko'tariladi, `/health` va `/ready` YASHIL bo'ladi
    va HECH KIM KIRA OLMAYDI. "Yashil, lekin o'lik" — bu loyihada
    takrorlangan sinf, shuning uchun u TO'XTATADI.
    """
    bolim("Joylashuv izchilligi — ishga tushish tekshiruvi")
    import os as _os
    from api import main as M

    eski = (M.COOKIE_SECURE, M.TRUST_PROXY, _os.environ.get("APP_ENV"))

    def holat(muhit, url, secure, proxy):
        _os.environ["APP_ENV"] = muhit
        M.COOKIE_SECURE, M.TRUST_PROXY = secure, proxy
        try:
            M.joylashuv_tekshir(url)
            return "otdi"
        except M.JoylashuvXato:
            return "toxtatdi"

    try:
        check("dev + http + secure -> O'TADI (localhost normal)",
              holat("dev", "http://localhost:5173", True, False) == "otdi")
        # ASOSIY TEKSHIRUV.
        check("prod + http + AUTH_COOKIE_SECURE=1 -> TO'XTATADI",
              holat("production", "http://tender.uz", True, True) == "toxtatdi",
              "aks holda xizmat yashil, kirish esa IMKONSIZ bo'lardi")
        check("prod + http + AUTH_COOKIE_SECURE=0 -> O'TADI (ichki tarmoq)",
              holat("production", "http://tender.uz", False, True) == "otdi")
        check("prod + https + TRUST_PROXY=1 -> O'TADI",
              holat("production", "https://tender.uz", True, True) == "otdi")
        # Bu ZIDDIYAT, lekin xizmat ISHLAYDI -> ogohlantirish, to'xtatish EMAS.
        check("prod + https + TRUST_PROXY=0 -> O'TADI (ogohlantirish bilan)",
              holat("production", "https://tender.uz", True, False) == "otdi",
              "xizmat ishlaydi; nosozlik jurnalda ko'rinadi")
    finally:
        M.COOKIE_SECURE, M.TRUST_PROXY = eski[0], eski[1]
        if eski[2] is None:
            _os.environ.pop("APP_ENV", None)
        else:
            _os.environ["APP_ENV"] = eski[2]

    # Namunalar shu sozlamalarni E'LON QILSIN — operator ularni
    # ko'rmasa, qo'lda yozilgan faylda ular UMUMAN bo'lmasdi.
    for nom in ("staging", "production"):
        yol = os.path.join(ROOT, "deploy", "env", f"{nom}.env.example")
        matn = io.open(yol, encoding="utf-8").read()
        check(f"{nom}.env.example da TRUST_PROXY=1", "TRUST_PROXY=1" in matn)
        check(f"{nom}.env.example da AUTH_COOKIE_SECURE=1",
              "AUTH_COOKIE_SECURE=1" in matn)


# =============================================================================
# 17. JOYLASHTIRISHDAN OLDINGI TEKSHIRUV — U HAM YURGIZILADI
# =============================================================================
# NEGA KERAK EDI: `bootstrap.sh` muhit faylini NAMUNADAN nusxalaydi
# va shu holda qoldiradi. `password=REPLACE`, `example.uz` va
# namunaviy bcrypt xeshi bilan turgan server BUTUNLAY NORMAL
# ko'rinadi — hech narsa uni "to'ldirilmagan" demaydi.
#
# `deploy.sh` ularni KECH ushlardi (migratsiya qadamida — `venv`,
# `npm ci` va frontend qurilmasidan keyin), `example.uz` ni esa
# UMUMAN ushlamasdi: joylashtirish muvaffaqiyatli tugardi va
# bildirishnoma havolalari mavjud bo'lmagan domenga ketaverardi.
#
# Bu bo'lim 16-bo'lim uslubida: skript O'QILMAYDI, YURGIZILADI.
# =============================================================================

def _oldindan_qur(baza, posix=None, ozgartir=None, caddy_ozgartir=None):
    r"""Mashq uchun muhit fayli va Caddyfile yasaydi (namunadan).

    `posix` — yo'lni SHU bash ko'radigan shaklga o'tkazadi. Windows
    yo'li (`C:\...`) muhit fayliga yozilsa, uni shell SOURCE
    qilganda teskari chiziqlar YO'QOLADI va `BACKUP_DIR` mavjud
    bo'lmagan yo'lga aylanadi — mashqning O'ZI soxta to'siq
    yasardi.
    """
    posix = posix or (lambda x: x)
    N = chr(10)
    env = io.open(os.path.join(D, "env", "production.env.example"),
                  encoding="utf-8").read()
    cad = io.open(os.path.join(D, "caddy", "Caddyfile"),
                  encoding="utf-8").read()
    # Namunani ISHLAYDIGAN holatga keltiramiz — keyin sinov uni
    # ataylab BUZADI va skript buni ko'rishi kerak.
    # `backup.sh` `${BACKUP_DIR}/${MUHIT}` ga yozadi — ichki
    # katalog ham yasaladi, aks holda mashq soxta to'siq berardi.
    zaxira = os.path.join(baza, "zaxira")
    for m in ("staging", "production"):
        os.makedirs(os.path.join(zaxira, m), exist_ok=True)
    almash = [
        ("APP_PUBLIC_URL=https://tender.example.uz",
         "APP_PUBLIC_URL=https://tender.mycompany.uz"),
        ('XT_DB_DSN="dbname=tenderai_production user=tai_service '
         'password=REPLACE host=127.0.0.1 port=5432"',
         'XT_DB_DSN="dbname=t user=tai_app password=p1 host=127.0.0.1 port=5432"'),
        ('XT_DB_DSN_OWNER="dbname=tenderai_production user=postgres '
         'password=REPLACE host=127.0.0.1 port=5432"',
         'XT_DB_DSN_OWNER="dbname=t user=postgres password=p2 host=127.0.0.1 port=5432"'),
        ("BACKUP_DIR=/var/backups/tenderai", "BACKUP_DIR=" + posix(zaxira)),
    ]
    for a, b in almash:
        env = env.replace(a, b)
    cad = (cad.replace("staging.example.uz", "staging.mycompany.uz")
              .replace("tender.example.uz", "tender.mycompany.uz")
              .replace("$2a$14$REPLACE_WITH_YOUR_OWN_BCRYPT_HASH",
                       "$2a$14$" + "a" * 53))
    if ozgartir:
        env = ozgartir(env)
    if caddy_ozgartir:
        cad = caddy_ozgartir(cad)
    ey = os.path.join(baza, "muhit.env")
    cy = os.path.join(baza, "Caddyfile")
    io.open(ey, "w", encoding="utf-8", newline=N).write(env)
    io.open(cy, "w", encoding="utf-8", newline=N).write(cad)
    return ey, cy


def test_oldindan_tekshiruv():
    bolim("17. JOYLASHTIRISHDAN OLDINGI TEKSHIRUV (yurgiziladi)")

    skript = os.path.join(D, "bin", "oldindan-tekshir.sh")
    check("`oldindan-tekshir.sh` mavjud", os.path.isfile(skript))
    if not os.path.isfile(skript):
        return

    # ULANISH: `deploy.sh` uni QIMMAT qadamlardan OLDIN chaqirsin.
    # Aks holda tekshiruv bor, lekin foydasi yo'q — nuqson baribir
    # `venv` va `npm ci` dan keyin chiqardi.
    d = oqi("bin", "deploy.sh")
    check("`deploy.sh` uni CHAQIRADI", "oldindan-tekshir.sh" in d)
    if "oldindan-tekshir.sh" in d:
        check("chaqiruv `python3 -m venv` dan OLDIN",
              d.index("oldindan-tekshir.sh") < d.index("python3 -m venv"))
        check("chaqiruv `git archive` dan OLDIN",
              d.index("oldindan-tekshir.sh") < d.index("git archive"))
    b = oqi("bin", "bootstrap.sh")
    check("`bootstrap.sh` operatorga uni KO'RSATADI",
          "oldindan-tekshir.sh" in b)

    bash = _mashq_bash()
    check("mashq muhiti bor (repozitoriyani ko'radigan `bash`)",
          bash is not None,
          "" if bash else "topilmadi — skript YURGIZILMADI, faqat O'QILDI")
    if not bash:
        return

    baza = tempfile.mkdtemp(prefix="tenderai_oldindan_")
    try:
        # `psql` SHIMI. Busiz mashq mahalliy bazaga tayanardi va u
        # CI da bo'lmaydi — ya'ni "toza sozlama" holati hech qachon
        # toza chiqmasdi.
        qutі = os.path.join(baza, "shim")
        os.makedirs(qutі, exist_ok=True)
        N = chr(10)

        def shim(nom, matn):
            y = os.path.join(qutі, nom)
            io.open(y, "w", encoding="utf-8", newline=N).write(matn)
            os.chmod(y, 0o755)

        shim("psql", "#!/bin/sh" + N + "echo 1" + N + "exit 0" + N)
        shim_p = _posix_yol(bash, qutі)

        def pq(yol):
            return _posix_yol(bash, yol)

        def yurgiz(muhit, envfile, caddyfile):
            e = dict(os.environ)
            e["TENDERAI_ENVFILE"] = _posix_yol(bash, envfile)
            e["TENDERAI_CADDYFILE"] = _posix_yol(bash, caddyfile)
            yol = shim_p
            r = subprocess.run(
                [bash, "-c", 'PATH="$1:$PATH"; shift; exec "$@"', "_",
                 yol, "deploy/bin/oldindan-tekshir.sh", muhit],
                cwd=ROOT, env=e, capture_output=True, text=True, timeout=180)
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        # --- A) XOM NAMUNA: hammasi to'ldirilmagan --------------------
        xom = os.path.join(baza, "xom")
        os.makedirs(xom, exist_ok=True)
        ey = os.path.join(xom, "muhit.env")
        cy = os.path.join(xom, "Caddyfile")
        shutil.copy(os.path.join(D, "env", "production.env.example"), ey)
        shutil.copy(os.path.join(D, "caddy", "Caddyfile"), cy)
        kod, chiq = yurgiz("production", ey, cy)
        check("xom namuna: JOYLASHTIRIB BO'LMAYDI", kod == 1, f"kod={kod}")
        check("xom namuna: `password=REPLACE` ko'rsatiladi",
              chiq.count("NAMUNAVIY (password=REPLACE)") == 2)
        check("xom namuna: `example.uz` domeni ko'rsatiladi",
              "APP_PUBLIC_URL hali NAMUNAVIY domen" in chiq)
        check("xom namuna: namunaviy bcrypt xeshi ko'rsatiladi",
              "NAMUNAVIY bcrypt xeshi" in chiq)
        check("xom namuna: Caddy domeni ham ko'rsatiladi",
              "Caddyfile da NAMUNAVIY domen" in chiq)

        # --- B) TO'LDIRILGAN: to'siq QOLMASIN -------------------------
        toza = os.path.join(baza, "toza")
        os.makedirs(toza, exist_ok=True)
        ey, cy = _oldindan_qur(toza, pq)
        kod, chiq = yurgiz("production", ey, cy)
        tosiq = chiq.count("[TO'SIQ]")
        check("to'ldirilgan sozlama: TO'SIQ yo'q", tosiq == 0,
              chiq if tosiq else "")
        check("to'ldirilgan sozlama: joylashtirish MUMKIN", kod == 0,
              f"kod={kod}")
        check("to'ldirilgan sozlama: baza ULANISHI tekshirildi",
              "XT_DB_DSN ulanadi" in chiq and "pgvector o'rnatilgan" in chiq)

        # HUQUQ — TO'SIQ EMAS, ogohlantirish: ochiq fayl bilan xizmat
        # bekam-ko'st ishlaydi. NTFS da `chmod 640` baribir `644`
        # bo'lib ko'rinadi, shuning uchun sinov FAQAT `644` yo'nalishini
        # tasdiqlaydi — u ikkala tizimda ham ANIQ.
        os.chmod(ey, 0o644)
        kod, chiq = yurgiz("production", ey, cy)
        check("ochiq huquq: OGOHLANTIRADI, lekin to'xtatmaydi",
              "BOSHQALAR uchun ochiq" in chiq and chiq.count("[TO'SIQ]") == 0,
              f"kod={kod}")

        # --- C) 13.1 NUQSONI: TIRNOQSIZ DSN --------------------------
        # Bitta fayl, ikki parser: systemd butun qatorni oladi, shell
        # birinchi bo'shliqda KESADI. O'sha safar faqat `XT_DB_DSN`
        # tuzatilgan edi; endi tekshiruv HAR QANDAY qiymatga tegadi.
        tir = os.path.join(baza, "tirnoqsiz")
        os.makedirs(tir, exist_ok=True)
        ey, cy = _oldindan_qur(
            tir, pq, lambda s: s.replace(
                'XT_DB_DSN="dbname=t user=tai_app password=p1 host=127.0.0.1 port=5432"',
                'XT_DB_DSN=dbname=t user=tai_app password=p1 host=127.0.0.1 port=5432'))
        kod, chiq = yurgiz("production", ey, cy)
        check("tirnoqsiz DSN: TIRNOQ tekshiruvi ushlaydi",
              "TIRNOQSIZ" in chiq and "XT_DB_DSN" in chiq)
        check("tirnoqsiz DSN: KESILGANI ham ko'rinadi",
              "tirnoq tufayli KESILGAN" in chiq)
        check("tirnoqsiz DSN: joylashtirib bo'lmaydi", kod == 1)

        # --- D) PORT: Caddy va API kelishmasa Caddy 502 beradi -------
        prt = os.path.join(baza, "port")
        os.makedirs(prt, exist_ok=True)
        ey, cy = _oldindan_qur(prt, pq,
                               lambda s: s.replace("API_PORT=8000",
                                                   "API_PORT=9999"))
        kod, chiq = yurgiz("production", ey, cy)
        check("port nomuvofiqligi ushlanadi", "PORT MOS EMAS" in chiq)

        # --- E) STAGING OCHIQ QOLMASIN -------------------------------
        stg = os.path.join(baza, "staging")
        os.makedirs(stg, exist_ok=True)
        ey, cy = _oldindan_qur(
            stg, pq,
            lambda s: (s.replace("APP_ENV=production", "APP_ENV=staging")
                        .replace("APP_PUBLIC_URL=https://tender.mycompany.uz",
                                 "APP_PUBLIC_URL=https://staging.mycompany.uz")
                        .replace("API_PORT=8000", "API_PORT=8001")),
            lambda c: re.sub(r"basic_auth \{[^}]*\}", "", c))
        kod, chiq = yurgiz("staging", ey, cy)
        check("staging `basic_auth` siz qolsa TO'XTATADI",
              "staging OCHIQ" in chiq, chiq[-400:] if "staging OCHIQ" not in chiq else "")

        # --- E2) ZAXIRA: `backup.sh` ICHKI katalogga yozadi ----------
        # Ota-katalogni tekshirish IKKI TOMONLAMA soxta natija
        # berardi: `bootstrap.sh` oraliq katalogni root nomidan
        # yaratadi (yozib bo'lmaydi -> soxta to'siq), ichki katalog
        # esa yo'q bo'lishi mumkin (soxta ok, zaxira BIRINCHI
        # yurishda yiqilardi).
        zx = os.path.join(baza, "zaxira_ota")
        os.makedirs(zx, exist_ok=True)      # ATAYLAB ichki katalogsiz
        ey, cy = _oldindan_qur(
            os.path.join(baza, "toza"), pq,
            lambda s: re.sub(r"(?m)^BACKUP_DIR=.*$",
                             "BACKUP_DIR=" + pq(zx), s))
        kod, chiq = yurgiz("production", ey, cy)
        check("zaxira: ICHKI katalog yo'qligi ushlanadi",
              "zaxira katalogi yo'q" in chiq and "production" in chiq)
        os.makedirs(os.path.join(zx, "production"), exist_ok=True)
        kod, chiq = yurgiz("production", ey, cy)
        check("zaxira: ichki katalog bo'lsa O'TADI",
              "zaxira katalogi yoziladi" in chiq and kod == 0, f"kod={kod}")

        # --- F) O'LCHAB BO'LMAGANI "O'TDI" BO'LIB SANALMASIN ---------
        # `production_gate.py` dagi `BLOKLANGAN` bilan ayni mantiq:
        # tekshira olmaslik yaxshi xabar EMAS va u JIM ham qolmaydi.
        # Caddy hali o'rnatilmagan bo'lishi mumkin (birinchi
        # joylashtirish), shuning uchun bu TO'XTATMAYDI — lekin
        # "port mos" degan YOLG'ON xulosa ham chiqmaydi.
        ey, cy = _oldindan_qur(os.path.join(baza, "toza"), pq)
        kod, chiq = yurgiz("production", ey,
                           os.path.join(baza, "bunday-fayl-yoq"))
        check("Caddyfile yo'q: JIMGINA o'tmaydi",
              "[tekshirilmadi]" in chiq and "Caddyfile yo'q" in chiq)
        check("Caddyfile yo'q: 'port mos' degan YOLG'ON xulosa yo'q",
              "port mos" not in chiq)
    finally:
        shutil.rmtree(baza, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Joylashtirish sinovi")
    rejim.bayroqlar(ap)
    rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: JOYLASHTIRISH ARTEFAKTLARI")
    print("=" * 70)

    test_tuzilma()
    test_sirlar()
    test_localhost()
    test_qayta_yuklash()
    test_etl_seanssiz()
    test_zaxira()
    test_staging_birinchi()
    test_proksi()
    test_zaxira_tashqi()
    test_e2e_darvozasi()
    test_sogliq()
    test_jurnal()
    test_url_qorovuli()
    test_muhit_fayli_shellda()
    test_tashqi_nusxa()
    test_ogohlantirish()
    test_hujjat()
    test_joylashuv_izchilligi()
    test_mashq()
    test_oldindan_tekshiruv()

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
