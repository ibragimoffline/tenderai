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
    check("AYNAN SHU KOMMIT tekshirilgani solishtiriladi",
          "BOSHQA KOMMIT tekshirilgan" in d,
          "shox nomi bo'yicha solishtirish `main` uchun MA'NOSIZ")
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
    # `--proksi` -- 413 QAYSI QATLAMDAN kelganini ajratadi.
    # Busiz "413 keldi" degan xulosa Caddy chegarasi ISHLAYOTGANINI
    # isbotlamasdi: uni ilova ham qaytaradi.
    check("`--proksi` DOIM beriladi (Caddy chegarasi isboti)",
          "--proksi" in d)
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
    check("skript 413 ni QATLAM bo'yicha ajratadi",
          "FILE_TOO_LARGE" in e and "to'xtatgan qatlam" in e)
    check("skript proksi JUDA KICHIK emasligini ham tekshiradi",
          "proksidan O'TADI" in e)
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
    # `APP_PUBLIC_URL` HAM SAQLANADI VA TOZALANADI.
    #
    # O'LCHANGAN NUQSON (2026-09-08): darvoza jarayoniga
    # `APP_PUBLIC_URL` uzatila boshlagach bu sinov yiqildi —
    #
    #     APP_PUBLIC_URL va PUBLIC_BASE_URL IKKALASI ham berilgan,
    #     lekin qiymatlari boshqa
    #
    # Sinov ESKI nomni (`PUBLIC_BASE_URL`) ataylab qo'yadi, YANGI nom
    # esa MUHITDAN kelib qolardi. Ya'ni sinov o'zi boshqarmagan
    # o'zgaruvchidan yiqilardi.
    #
    # MAHSULOT XULQI TO'G'RI VA O'ZGARMAYDI: ikki nom har xil qiymat
    # bilan berilsa `ommaviy_url` ATAYLAB to'xtaydi — "qaysi biri
    # to'g'ri" degan savolga taxmin bilan javob berish ikkita haqiqat
    # manbai demak. Tuzatish faqat SINOV IZOLYATSIYASIDA: sinov URL
    # sozlamasining IKKALA nomini ham o'zi egallaydi.
    eski_yangi_url = os.environ.get("APP_PUBLIC_URL")
    try:
        from api import notify

        os.environ["APP_ENV"] = "production"
        os.environ.pop("PUBLIC_BASE_URL", None)
        os.environ.pop("APP_PUBLIC_URL", None)
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

        if eski_yangi_url is None:
            os.environ.pop("APP_PUBLIC_URL", None)
        else:
            os.environ["APP_PUBLIC_URL"] = eski_yangi_url

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



def _mashq_repo(yol, teg):
    """Mashq uchun bitta kommitli bare repo yasaydi va teg qo'yadi.

    `deploy.sh` `$REF` ni `rev-parse` bilan kommitga hal qiladi —
    ya'ni mashqda ham HAQIQIY git obyekti kerak. Soxta yo'l bersak
    skript birinchi qadamda to'xtaydi va mashq keyingi qadamlarni
    umuman sinamaydi.
    """
    ish = yol + ".ish"
    os.makedirs(ish, exist_ok=True)
    io.open(os.path.join(ish, "README"), "w", encoding="utf-8").write("mashq\n")
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": "mashq", "GIT_AUTHOR_EMAIL": "m@example.invalid",
              "GIT_COMMITTER_NAME": "mashq", "GIT_COMMITTER_EMAIL": "m@example.invalid"})
    for buyruq in (["git", "init", "-q", "-b", "main"],
                   ["git", "add", "README"],
                   ["git", "commit", "-q", "-m", "mashq"],
                   ["git", "tag", teg]):
        subprocess.run(buyruq, cwd=ish, env=e, capture_output=True)
    subprocess.run(["git", "clone", "-q", "--bare", ish, yol],
                   env=e, capture_output=True)


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
        # HAQIQIY BARE REPO — `deploy.sh` endi `$REF` ni KOMMITGA
        # hal qiladi (`.verified` o'zgarmas SHA saqlashi uchun) va
        # buni har qanday tekshiruvdan OLDIN qiladi. Repo bo'lmasa
        # mashq shu qadamda to'xtardi va tasdiq darvozasiga
        # YETIB BORMASDI — ya'ni mashq o'zi ko'rmoqchi bo'lgan
        # narsani ko'rmay qolardi.
        prepo = os.path.join(baza, "mashq-repo.git")
        _mashq_repo(prepo, "v1.2.3")

        pmuhit = {"TENDERAI_ILDIZ": _posix_yol(bash, pildiz),
                  "TENDERAI_STAGING_ILDIZ": _posix_yol(bash, ildiz),
                  "TENDERAI_ENVFILE": _posix_yol(bash, penv),
                  "TENDERAI_REPO": _posix_yol(bash, prepo),
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
        # ESKI FORMAT (shox/teg nomi) — endi RAD ETILADI. Sabab:
        # "v1.2.2" qaysi KOMMIT tekshirilganini aytmaydi, ya'ni
        # tenglik tekshiruvi himoya bermaydi.
        io.open(tasdiq, "w", encoding="utf-8").write("v1.2.2")
        kod, chiq = yurgiz("deploy.sh", "production", "v1.2.3",
                           qoshimcha=pmuhit)
        check("joylashtirish: ESKI FORMATDAGI tasdiq -> RAD", kod == 1,
              f"kod={kod}")
        check("joylashtirish: SABABI aytiladi (kommit emas)",
              "ESKI FORMATDA" in chiq, chiq[-400:])

        # 40 belgili, LEKIN BOSHQA kommit — asosiy holat.
        io.open(tasdiq, "w", encoding="utf-8").write("b" * 40)
        kod, chiq = yurgiz("deploy.sh", "production", "v1.2.3",
                           qoshimcha=pmuhit)
        check("joylashtirish: BOSHQA KOMMIT -> RAD", kod == 1, f"kod={kod}")
        check("joylashtirish: IKKALA kommit ham ko'rsatiladi",
              "b" * 40 in chiq, chiq[-400:])

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
        # SHA hal qilish endi katalog yaratilishidan OLDIN yuradi,
        # ya'ni yo'q repo bilan yarim reliz UMUMAN yaratilmaydi.
        # Ikkala yo'l ham to'g'ri; muhimi — SABAB aytilsin va katalog
        # qolmasin (yuqorida tekshirildi).
        check("joylashtirish: yiqilish SABABI aytiladi",
              ("yarim reliz olib tashlanmoqda" in chiq
               or "ko'zguda topilmadi" in chiq), chiq[-400:])
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



def test_ozgarmas_tasdiq():
    bolim("18. `.verified` O'ZGARMAS KOMMIT SAQLAYDI")

    # NEGA. `main` HARAKATLANUVCHI. Staging uni bir kommitda
    # tekshiradi, ertaga `main` boshqasini ko'rsatadi, `.verified`
    # da esa hamon "main" yozilgan bo'ladi.
    #
    # O'LCHANGAN HOLAT (2026-09-07): `.verified` = "main", staging
    # 5-sentabr kodida, `main` esa 129 fayl oldinda edi.
    # `deploy.sh production main` shu holatda O'TARDI — ya'ni
    # darvoza bor, himoya yo'q.
    d = oqi("bin", "deploy.sh")

    check("SHA `rev-parse` bilan hal qilinadi", "rev-parse --verify" in d)
    check("tasdiqqa REF emas, SHA yoziladi",
          'printf \'%s\' "$SHA" > "${ILDIZ}/.verified"' in d,
          "`$REF` yozilsa shox nomi saqlanadi va tenglik ma'nosiz")
    check("REF endi tasdiqqa YOZILMAYDI",
          'printf \'%s\' "$REF" > "${ILDIZ}/.verified"' not in d)
    check("production tenglikni SHA da tekshiradi",
          '"$TASDIQLANGAN" != "$SHA"' in d)
    check("eski format (shox nomi) RAD ETILADI", "ESKI FORMATDA" in d)

    # SHA hal qilish QIMMAT qadamlardan oldin bo'lsin — noto'g'ri ref
    # `venv` va `npm ci` dan KEYIN emas, DARHOL aytilsin.
    if "rev-parse --verify" in d and "python3 -m venv" in d:
        check("SHA hal qilish `venv` dan OLDIN",
              d.index("rev-parse --verify") < d.index("python3 -m venv"))
    if "rev-parse --verify" in d and "git archive" in d:
        check("SHA hal qilish `git archive` dan OLDIN",
              d.index("rev-parse --verify") < d.index("git archive"))

    # 40 belgi qo'riqchisi IKKALA tomonda ham bo'lsin: yozishda ham,
    # o'qishda ham. Bittasi yetmaydi — eski `.verified` fayli
    # o'rnatmada allaqachon turibdi.
    check("40 belgi qo'riqchisi ikki joyda",
          d.count("????????????????????????????????????????") >= 2,
          "biri SHA ni hal qilishda, biri tasdiqni o'qishda")


def test_darvoza_dsn():
    bolim("19. RELIZ DARVOZASI: DSN MAJBURIY (yolg'on 'statik' da'vosi yo'q)")

    # O'LCHANGAN YOLG'ON (2026-09-07): darvoza "DSN bo'lmasa STATIK
    # butunlik baribir tekshiriladi" deb yozardi va `migratsiya.py
    # --tekshir` ni DSN siz chaqirardi. `migratsiya.py` da statik
    # rejim UMUMAN yo'q — u har holatda `Jurnal(dsn)` quradi.
    # Ya'ni "tekshirildi" degan xabar hech qachon rost bo'lmagan.
    g = oqi("bin", "relis-darvoza.sh")

    check("DSN siz `migratsiya.py` CHAQIRILMAYDI",
          'migratsiya.py --tekshir || xato' not in g,
          "eski `else` shoxi DSN siz chaqirardi va u hech qachon "
          "ishlamagan")
    check("'statik butunlik tekshiriladi' da'vosi olib tashlangan",
          "STATIK butunlik (manifest, checksum, fayllar) baribir" not in g)
    check("DSN yo'q bo'lsa darvoza YIQILADI",
          "migratsiya butunligi TEKSHIRILMADI" in g)

    # `migratsiya.py` da haqiqatan statik rejim YO'Qligini tasdiqlaymiz.
    # Bo'lsa — bu tekshiruv eskirgan va qayta ko'rilishi kerak.
    m = io.open(os.path.join(ROOT, "migratsiya.py"), encoding="utf-8").read()
    check("`migratsiya.py` DSN siz ishlamaydi (da'vo shundan yolg'on edi)",
          "XT_DB_DSN o'rnatilmagan" in m)

    # YURGIZIB tekshiramiz: DSN siz darvoza to'xtasin va SABABINI
    # aytsin. Matnni o'qish yetmaydi — `set -u` yoki tartib xatosi
    # boshqa joyda yiqitishi mumkin edi.
    bash = _mashq_bash()
    if not bash:
        check("bash yo'q — yurgizib tekshirilmadi", True)
        return
    with tempfile.TemporaryDirectory() as tmp:
        # To'plamlar yurmasin: `run_tests.py` o'rniga bo'sh ildiz
        # beramiz — darvoza 1-bo'limda yiqiladi va 3-bo'limga
        # yetmaydi. Shuning uchun AYNAN 3-bo'limni tekshirish uchun
        # skriptni matndan emas, o'z ildizida yurgizamiz va faqat
        # DSN o'zgaruvchilarini olib tashlaymiz.
        # MASHQ O'Z ILDIZIDA YURADI — HAQIQIY REPOZITORIYADA EMAS.
        #
        # O'LCHANGAN NUQSON (2026-09-08): ilgari bu yerda `ROOT`
        # berilardi va darvoza HAQIQIY `run_tests.py` ni chaqirardi.
        # `TENDERAI_PY` buzuq bo'lgan paytda u tez yiqilardi va nuqson
        # ko'rinmasdi. Interpretator tuzatilgach esa darvoza 44 ta
        # to'plamni ICHMA-ICH yurgizib yubordi: yurish 260s dan 1162s
        # ga chiqdi va `deploy_test` ning o'zi "o'lchanmadi" bo'lib
        # qoldi.
        #
        # Bu sinovning savoli — 3-BO'LIM: DSN yo'q bo'lsa darvoza
        # to'xtaydimi. Backend to'plamlari bunga aloqasiz. Shuning
        # uchun mashq ildizida `run_tests.py` ning O'RNIGA to'g'ri
        # xulosa qatorini beradigan qisqa dublyor turadi: darvoza
        # 1-bo'limdan o'tadi va 3-bo'limga YETADI.
        mashq_ildiz = os.path.join(tmp, "ildiz")
        os.makedirs(os.path.join(mashq_ildiz, "frontend"), exist_ok=True)
        N2 = chr(10)
        io.open(os.path.join(mashq_ildiz, "run_tests.py"), "w",
                encoding="utf-8", newline=N2).write(
            "print(\"JAMI: 44/44 to'plam yurdi, 44 o'tdi, 0 yiqildi\")" + N2)
        io.open(os.path.join(mashq_ildiz, "migratsiya.py"), "w",
                encoding="utf-8", newline=N2).write("raise SystemExit(0)" + N2)
        io.open(os.path.join(mashq_ildiz, "frontend", "package.json"), "w",
                encoding="utf-8", newline=N2).write("{}" + N2)

        e = dict(os.environ)
        e.pop("XT_DB_DSN", None)
        e.pop("XT_DB_DSN_OWNER", None)
        e["TENDERAI_DARVOZA_FRONTEND"] = "0"       # frontend qurilmasin
        r = subprocess.run([bash, os.path.join(D, "bin", "relis-darvoza.sh"),
                            _posix_yol(bash, mashq_ildiz)],
                           capture_output=True, text=True, env=e, cwd=tmp)
        # 1-bo'lim to'xtatgani ham, 3-bo'lim to'xtatgani ham MAYLI —
        # muhimi: darvoza "o'tdi" DEMAYDI.
        check("DSN siz darvoza O'TMAYDI", r.returncode != 0,
              f"chiqish kodi {r.returncode}")
        check("chiqishda 'statik o'tdi' degan yolg'on yo'q",
              "(statik)" not in (r.stdout + r.stderr))



def test_mahalliy_url_muhitga_qarab():
    bolim("20. MAHALLIY `APP_PUBLIC_URL`: staging RUXSAT, production TO'SIQ")

    # QAROR (2026-09-07, B varianti). Bu o'rnatmada staging ga domen
    # ATAYLAB berilmagan — nginx bloki `127.0.0.1:8091` da turadi va
    # unga SSH tunnel orqali kiriladi.
    #
    # Ilgari tekshiruv muhitni ajratmasdi va staging ni HAR SAFAR
    # to'sardi. Hech qachon o'tmaydigan darvozaning oqibati bitta:
    # undan chetlab o'tishni o'rganishadi.
    #
    # PRODUCTION UCHUN HECH NARSA YUMSHATILMADI va bu sinovning
    # ASOSIY vazifasi — aynan shuni qulflash.
    bash = _mashq_bash()
    if not bash:
        check("bash yo'q — yurgizib tekshirilmadi", True)
        return

    baza = tempfile.mkdtemp(prefix="tenderai_url_")
    try:
        qutі = os.path.join(baza, "shim")
        os.makedirs(qutі, exist_ok=True)
        N = chr(10)
        y = os.path.join(qutі, "psql")
        io.open(y, "w", encoding="utf-8", newline=N).write(
            "#!/bin/sh" + N + "echo 1" + N + "exit 0" + N)
        os.chmod(y, 0o755)
        shim_p = _posix_yol(bash, qutі)

        def yurgiz(muhit, envfile, caddyfile):
            e = dict(os.environ)
            e["TENDERAI_ENVFILE"] = _posix_yol(bash, envfile)
            e["TENDERAI_CADDYFILE"] = _posix_yol(bash, caddyfile)
            r = subprocess.run(
                [bash, "-c", 'PATH="$1:$PATH"; shift; exec "$@"', "_",
                 shim_p, "deploy/bin/oldindan-tekshir.sh", muhit],
                cwd=ROOT, env=e, capture_output=True, text=True, timeout=180)
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        def mahalliy(env):
            return (env.replace("APP_PUBLIC_URL=https://tender.mycompany.uz",
                                "APP_PUBLIC_URL=http://localhost:8091")
                       .replace("APP_ENV=production", "APP_ENV=staging"))

        # --- A) STAGING + mahalliy URL -> TO'SIQ EMAS ----------------
        ey, cy = _oldindan_qur(os.path.join(baza, "st"),
                               posix=lambda x: _posix_yol(bash, x),
                               ozgartir=mahalliy)
        kod, chiq = yurgiz("staging", ey, cy)
        check("staging: mahalliy URL TO'SIQ EMAS",
              "APP_PUBLIC_URL MAHALLIY manzil" not in chiq,
              chiq[-600:])
        check("staging: mahalliy URL JIM ham qolmaydi (ogohlantirish)",
              "APP_PUBLIC_URL mahalliy" in chiq,
              "to'smaslik va ko'rsatmaslik BOSHQA narsa")

        # --- B) PRODUCTION + mahalliy URL -> QAT'IY TO'SIQ -----------
        ey2, cy2 = _oldindan_qur(
            os.path.join(baza, "pr"),
            posix=lambda x: _posix_yol(bash, x),
            ozgartir=lambda env: env.replace(
                "APP_PUBLIC_URL=https://tender.mycompany.uz",
                "APP_PUBLIC_URL=http://localhost:8091"))
        kod2, chiq2 = yurgiz("production", ey2, cy2)
        check("production: mahalliy URL TO'SIQ", kod2 == 1, f"kod={kod2}")
        check("production: sabab AYTILADI",
              "production da MUMKIN EMAS" in chiq2, chiq2[-600:])

        # --- C) PRODUCTION + haqiqiy HTTPS -> shu sababdan to'siq yo'q
        ey3, cy3 = _oldindan_qur(os.path.join(baza, "ok"),
                                 posix=lambda x: _posix_yol(bash, x))
        _kod3, chiq3 = yurgiz("production", ey3, cy3)
        check("production: HTTPS domen bilan URL to'sig'i yo'q",
              "APP_PUBLIC_URL MAHALLIY" not in chiq3
              and "MUMKIN EMAS" not in chiq3, chiq3[-600:])
    finally:
        shutil.rmtree(baza, ignore_errors=True)



def test_bajarish_bayrogi():
    bolim("21. `deploy/bin/*.sh` — BAJARISH BAYROG'I (git rejimi)")

    # BU NUQSON LOYIHADA IKKI MARTA BO'LGAN.
    #
    # Birinchi marta (#2): butun qatlam 100644 edi va joylashtirish
    # umuman yurmasdi. Tuzatildi — LEKIN SINOV YOZILMADI.
    #
    # Ikkinchi marta (2026-09-07): uchta YANGI skript yana 100644
    # bo'lib qo'shildi — `oldindan-tekshir.sh`, `relis-darvoza.sh`,
    # `e2e-fayl.sh`.
    #
    # NEGA HECH KIM SEZMADI: `tender-deploy-ai` o'ramasi arxivni
    # ochgach `chmod +x deploy/bin/*.sh` qiladi, ya'ni `deploy.sh`
    # va u YONIDAN chaqiradigan `oldindan-tekshir.sh` ishlayverardi.
    # Ammo `relis-darvoza.sh`, `health-check.sh` va `e2e-fayl.sh`
    # RELIZ ICHIDAN (`${YANGI}/deploy/bin/...`) chaqiriladi, u esa
    # `git archive` bilan ochiladi va CHMOD QILINMAYDI.
    #
    # Ya'ni reliz darvozasi ham, E2E darvozasi ham keyingi
    # joylashtiruvda `126 Permission denied` bilan o'lardi —
    # ikkalasi ham "darvoza" bo'lgani uchun bu eng yomon joy.
    #
    # DISKDAGI rejim EMAS, GIT dagi rejim tekshiriladi: reliz
    # `git archive` dan chiqadi va u faqat git bilgan bayroqni
    # olib chiqadi.
    # GIT YO'Q BO'LSA — FAYL TIZIMIDAN O'LCHANADI, O'TKAZIB
    # YUBORILMAYDI.
    #
    # O'LCHANGAN (2026-09-08): darvoza `git archive` dan chiqqan
    # daraxtda yuradi va u yerda `.git` YO'Q:
    #
    #     fatal: not a git repository
    #
    # Ilgari bu `check(..., False)` bilan YIQILARDI — ya'ni sinov
    # o'zi o'lchay olmagan joyda mahsulotni ayblardi.
    #
    # SKIP HAM QILINMAYDI. `git archive` bajarish bayrog'ini
    # SAQLAYDI, ya'ni relizda diskdagi rejim git dagi rejimning
    # aynan natijasi. Demak toza daraxtda `os.access(X_OK)` AYNI
    # invariantni o'lchaydi — boshqa manbadan, lekin o'sha savolga.
    r = subprocess.run(["git", "ls-files", "-s", "deploy/"],
                       capture_output=True, text=True, cwd=ROOT,
                       encoding="utf-8", errors="replace")
    git_bor = r.returncode == 0
    if not git_bor:
        check("git yo'q — bajarish bayrog'i FAYL TIZIMIDAN o'lchanadi", True,
              r.stderr.strip()[:80])
        yomon_fs, topildi_fs = [], 0
        for dirpath, _dn, fnames in os.walk(D):
            for fn in sorted(fnames):
                if not fn.endswith(".sh"):
                    continue
                topildi_fs += 1
                yol = os.path.join(dirpath, fn)
                if not os.access(yol, os.X_OK):
                    yomon_fs.append(os.path.relpath(yol, ROOT))
        check("skriptlar topildi", topildi_fs >= 8, f"{topildi_fs} ta")
        check("HAMMA `deploy/bin/*.sh` BAJARILADIGAN", not yomon_fs,
              str(yomon_fs))
        return

    yomon = []
    topildi = 0
    for qator in r.stdout.splitlines():
        if not qator.strip():
            continue
        rejim, _qolgani = qator.split(" ", 1)
        yol = qator.split("\t", 1)[-1]
        if not yol.endswith(".sh"):
            continue
        topildi += 1
        if rejim != "100755":
            yomon.append(f"{yol} [{rejim}]")

    check("skriptlar topildi", topildi >= 8, f"{topildi} ta")
    check("HAMMA `deploy/bin/*.sh` git da 100755", not yomon, str(yomon))

    # RELIZ ICHIDAN chaqiriladiganlar ALOHIDA: aynan ular
    # o'ramaning `chmod` idan foyda ko'rmaydi.
    d = oqi("bin", "deploy.sh")
    relizdan = re.findall(r'\$\{YANGI\}/deploy/bin/([A-Za-z0-9._-]+\.sh)', d)
    check("reliz ichidan chaqiriladiganlar aniqlandi",
          len(set(relizdan)) >= 2, str(sorted(set(relizdan))))
    for nom in sorted(set(relizdan)):
        yol = "deploy/bin/" + nom
        rejim = next((q.split(" ", 1)[0] for q in r.stdout.splitlines()
                      if q.endswith("\t" + yol)), None)
        check(f"`{nom}` bajariladigan (relizdan chaqiriladi)",
              rejim == "100755",
              f"rejim={rejim} — `git archive` dan keyin 126 beradi")



def test_darvoza_xulosani_oqiydi():
    bolim("22. DARVOZA `run_tests.py` XULOSASINI HAQIQATAN O'QIYDIMI")

    # O'LCHANGAN NUQSON (2026-09-07, staging joylashtiruvi).
    #
    # `run_tests.py` xulosani "JAMI: 44/44 to'plam yurdi, ..." deb
    # chop etadi. Darvozaning naqshi esa `^JAMI: [0-9]+ to.plam` edi —
    # raqamdan keyin darhol bo'shliq kutardi va "44/44" ga MOS
    # KELMASDI.
    #
    # Natijada 44 to'plam HAQIQATAN yurdi, 35 tasi yiqildi, darvoza
    # esa "to'plam UMUMAN BAJARILMADI" dedi. Darvozaning BUTUN
    # maqsadi — "yurmadi" ni "yiqildi" dan ajratish — aynan shu
    # joyda buzilgan edi.
    #
    # Darvoza to'sdi, ya'ni zarar bo'lmadi. Lekin YOLG'ON SABAB
    # yolg'on yashilcha qimmat: operator yurgizuvchining o'zida
    # nosozlik bor deb qidiradi.
    #
    # BU SINOV IKKI FAYLNI BOG'LAYDI. Format `run_tests.py` da,
    # naqsh `relis-darvoza.sh` da — ular ALOHIDA o'zgaradi va
    # aynan shuning uchun ajralib ketgan edi.
    bash = _mashq_bash()
    if not bash:
        check("bash yo'q — yurgizib tekshirilmadi", True)
        return

    g = oqi("bin", "relis-darvoza.sh")
    m = re.search(r'XULOSA="\$\(grep -E "([^"]+)"', g)
    check("darvozadan naqsh topildi", m is not None,
          "grep chaqirig'i o'zgargan bo'lsa sinov ham yangilansin")
    if not m:
        return
    naqsh = m.group(1)

    # FORMAT `run_tests.py` NING O'ZIDAN olinadi — qo'lda ko'chirilsa
    # ikkinchi manba paydo bo'lardi va u ham ajralib ketardi.
    rt = io.open(os.path.join(ROOT, "run_tests.py"), encoding="utf-8").read()
    check("`run_tests.py` xulosani `JAMI:` bilan chop etadi",
          'f"JAMI: {len(natijalar)}/{len(hamma_yol)} to\'plam yurdi, "' in rt,
          "format o'zgargan — naqsh va bu sinov qayta ko'rilsin")

    def urin(qator):
        r = subprocess.run(
            [bash, "-c",
             'printf "%s\\n" "$1" | grep -E "$2" | tail -1', "_", qator, naqsh],
            capture_output=True, text=True)
        return r.stdout.strip()

    # A) HAQIQIY format (yiqilgan bilan)
    haqiqiy = "JAMI: 44/44 to'plam yurdi, 9 o'tdi, 35 yiqildi \u00b7 103s"
    topildi = urin(haqiqiy)
    check("YANGI format naqshga tushadi", topildi != "", haqiqiy)

    if topildi:
        def sed(ifoda):
            r = subprocess.run(
                [bash, "-c", 'printf "%s" "$1" | sed -E "$2"', "_",
                 topildi, ifoda], capture_output=True, text=True)
            return r.stdout.strip()
        jami = sed("s@^JAMI: ([0-9]+).*@\\1@")
        yiq = sed("s@.*o.tdi, ([0-9]+) yiqildi.*@\\1@")
        check("YURGAN to'plam soni to'g'ri o'qiladi", jami == "44", jami)
        check("YIQILGAN soni to'g'ri o'qiladi", yiq == "35", yiq)

    # B) ESKI format ham ishlashda davom etsin (orqaga moslik)
    check("ESKI format ham naqshga tushadi",
          urin("JAMI: 44 to'plam, 0 yiqildi") != "")

    # C) O'qib bo'lmagan xulosa "o'tdi" ga aylanmasin.
    check("o'qib bo'lmagan xulosa uchun XATO bor",
          "xulosa qatorini O'QIB BO'LMADI" in g,
          "format yana o'zgarsa darvoza JIM qolmasin")



def test_cookie_secure_siyosati():
    bolim("23. `AUTH_COOKIE_SECURE` + `http` — MUHITGA QARAB")

    # O'LCHANGAN (2026-09-07, staging darvozasi): `xavfsizlik_test` va
    # `aktor_test` `joylashuv_tekshir()` da o'lardi, chunki staging
    # `http://127.0.0.1:8091` da (SSH tunnel) va `AUTH_COOKIE_SECURE=1`.
    #
    # Ammo BRAUZER `Secure` cookie ni `localhost`/`127.0.0.1` uchun
    # http bo'lsa ham YUBORADI — bu ishonchli kontekst. Ya'ni o'sha
    # juftlik xususiy staging da ISHLAYDI va uni to'xtatish SOXTA
    # to'siq edi.
    #
    # BU SINOVNING ASOSIY VAZIFASI — production ni qulflash.
    # Yumshatish FAQAT mahalliy manzilga va faqat dev/staging da
    # tegdi; ommaviy domenli staging ham TO'SILADI.
    import importlib
    holatlar = [
        ("production", "http://tender.uz",       True,  "to'siq"),
        ("production", "https://tender.uz",      False, "o'tadi"),
        ("staging",    "http://localhost:8091",  False, "o'tadi (mahalliy)"),
        ("staging",    "http://tender.uz",       True,  "to'siq (ommaviy)"),
        ("dev",        "http://localhost:5173",  False, "o'tadi"),
        ("",           "http://localhost:8091",  True,  "to'siq (noma'lum)"),
    ]
    for env, url, kutilgan_tosiq, izoh in holatlar:
        eski_env = {k: os.environ.get(k) for k in
                    ("APP_ENV", "APP_PUBLIC_URL",
                     "AUTH_COOKIE_SECURE", "TRUST_PROXY")}
        os.environ.update({"APP_ENV": env, "APP_PUBLIC_URL": url,
                           "AUTH_COOKIE_SECURE": "1", "TRUST_PROXY": "1"})
        try:
            # MODULLAR QAYTA YUKLANADI: `COOKIE_SECURE` modul
            # darajasida o'qiladi, ya'ni muhitni o'zgartirish
            # yetarli emas.
            for m in [k for k in list(sys.modules) if k.startswith("api.")]:
                del sys.modules[m]
            from api import main as M
            try:
                M.joylashuv_tekshir(url)
                tosildi = False
            except M.JoylashuvXato:
                tosildi = True
            check(f"APP_ENV={env or '<bosh>'} + {url} -> {izoh}",
                  tosildi == kutilgan_tosiq,
                  f"to'sildi={tosildi}, kutilgan={kutilgan_tosiq}")
        finally:
            for k, v in eski_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            for m in [k for k in list(sys.modules) if k.startswith("api.")]:
                del sys.modules[m]



def test_darvoza_stdout_kelishuvi():
    bolim("24. `darvoza-baza.sh` — STDOUT MASHINA KANALI")

    # O'LCHANGAN NUQSON (2026-09-07): `log()` stdout ga yozardi va
    #
    #     GATE="$(tender-darvoza yarat)"
    #
    # baza nomi o'rniga BUTUN JURNALNI ushlab olardi. Keyingi
    # `sinov "$GATE"` ko'p qatorli qiymat bilan chaqirilardi.
    #
    # KELISHUV: `yarat` muvaffaqiyatli tugasa stdout da AYNAN BITTA
    # qator — baza nomi. Qolgan hamma narsa stderr ga.
    y = os.path.join(D, "bin", "darvoza-baza.sh")
    check("`darvoza-baza.sh` mavjud", os.path.isfile(y))
    if not os.path.isfile(y):
        return
    src = io.open(y, encoding="utf-8").read()

    check("`log()` STDERR ga yozadi",
          ">&2; }" in src.split("log() {")[1][:80],
          "jurnal stdout ga tushsa `$(...)` uni nom deb oladi")
    check("migratsiya chiqishi ham STDERR ga",
          "--qolla --dsn \"$NISHON_OWNER\" >&2" in src)
    check("`yarat` stdout ga FAQAT nom yozadi",
          src.count("printf '%s\\n' \"$YANGI\"") == 1)

    bash = _mashq_bash()
    if not bash:
        check("bash yo'q — yurgizib tekshirilmadi", True)
        return

    def yurgiz(*arg):
        e = dict(os.environ)
        e["APP_ENV"] = "staging"
        e["XT_DB_DSN_TEST_ADMIN"] = "dbname=x user=x host=127.0.0.1 port=1"
        r = subprocess.run([bash, y, *arg], capture_output=True, text=True,
                           env=e, timeout=60)
        return r.returncode, r.stdout, r.stderr

    # A) YIQILGAN `yarat` — stdout da YAROQLI NOM BO'LMASIN.
    # Bu eng xavfli holat: chaqiruvchi `set -e` siz yozilgan bo'lsa
    # yiqilgan yurishning chiqishini nom deb ishlatib yuborardi.
    kod, chiq, _ = yurgiz("yarat")
    check("yiqilgan `yarat`: chiqish kodi nolga TENG EMAS", kod != 0, f"kod={kod}")
    check("yiqilgan `yarat`: stdout da darvoza nomi YO'Q",
          "tenderai_gate_" not in chiq, repr(chiq[:200]))

    # B) KO'P QATORLI va BO'SHLIQLI qiymat — RAD.
    # Glob dagi `*` yangi qatorni ham oladi, ya'ni bu qo'riqcha
    # naqshning O'ZIDAN kelib chiqmaydi va alohida kerak.
    for nom, izoh in ((chr(10).join(["tenderai_gate_1", "DROP"]), "ko'p qatorli"),
                      ("tenderai_gate_1 x", "bo'shliqli"),
                      ("TENDERAI_GATE_1", "katta harfli")):
        for amal in ("sinov", "tozala"):
            kod, chiq, xato = yurgiz(amal, nom)
            check(f"`{amal}` {izoh} qiymatni RAD etadi",
                  kod == 2 and "begona belgi" in xato,
                  f"kod={kod} {xato[:120]}")



def test_darvoza_toliq_daraxt():
    bolim("25. DARVOZA: TO'LIQ DARAXT va YIQILGANDA TOZALASH")

    # O'LCHANGAN (2026-09-07): o'rama arxivi `deploy` bilan cheklangan,
    # darvoza esa ildizdagi `migratsiya.py` va `run_tests.py` ga
    # muhtoj. Nusxa OLINGANDAN KEYIN migratsiya
    # "can't open file .../migratsiya.py" bilan yiqildi va darvoza
    # bazasi QOLIB KETDI.
    #
    # Ikki xulosa, ikki tuzatish:
    #   1. Zarur fayllar BAZA YARATILISHIDAN OLDIN tekshiriladi.
    #   2. Yaratilgandan keyin HAR QANDAY yiqilishda baza tashlanadi.
    src = oqi("bin", "darvoza-baza.sh")

    check("zarur fayllar ro'yxati bor",
          "migratsiya.py" in src and "run_tests.py" in src
          and "migratsiya_manifest.tsv" in src)
    check("to'liq daraxt AYNI SHA dan ochiladi",
          '"$RELEASE_SHA"' in src and "archive" in src,
          "`main` qayta o'qilsa 'bir snapshot' invarianti buzilardi")
    check("`main` QAYTA O'QILMAYDI",
          'archive "$RELEASE_SHA"' in src and 'archive main' not in src)

    # Tuzoq: yaratildi + muvaffaqiyatsiz -> tashlanadi.
    check("tozalash TUZOG'I bor", "trap tozalash_tuzogi EXIT" in src)
    check("bayroqlar ajratilgan",
          "DARVOZA_YARATILDI=1" in src and "MUVAFFAQIYAT=1" in src)
    check("MUVAFFAQIYAT faqat 0071 tasdiqlangach qo'yiladi",
          src.index("0071_topshiriq TASDIQLANDI") < src.index("MUVAFFAQIYAT=1"))
    check("asl chiqish kodi SAQLANADI", 'exit "$kod"' in src,
          "tuzoq kodni yutib yuborsa yiqilish `0` bo'lib ko'rinardi")
    check("`yarat` muvaffaqiyatli bo'lsa baza QOLADI",
          '"$MUVAFFAQIYAT" != "1"' in src,
          "`sinov \"$GATE\"` keyin unga muhtoj")

    # 0071 uchun SXEMA sharti ham bor — jurnalning o'zi yetarli emas.
    check("0071: jurnal VA sxema tekshiriladi",
          "to_regclass('public.tender_topshiriq')" in src,
          "jurnalda yozuv bo'lib, jadval bo'lmasligi mumkin")

    # YURGIZIB: fayllar yo'q va RELEASE_SHA ham yo'q -> baza
    # yaratilmasdan, TUSHUNARLI xato bilan to'xtasin.
    bash = _mashq_bash()
    if not bash:
        check("bash yo'q — yurgizib tekshirilmadi", True)
        return
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "deploy", "bin"))
        shutil.copy(os.path.join(D, "bin", "darvoza-baza.sh"),
                    os.path.join(tmp, "deploy", "bin", "darvoza-baza.sh"))
        e = dict(os.environ)
        e["APP_ENV"] = "staging"
        e["XT_DB_DSN_TEST_ADMIN"] = "dbname=x user=x host=127.0.0.1 port=1"
        e["XT_DB_DSN_OWNER"] = "dbname=x user=x host=127.0.0.1 port=1"
        e.pop("RELEASE_SHA", None)
        r = subprocess.run([bash, os.path.join(tmp, "deploy", "bin",
                                               "darvoza-baza.sh"), "yarat"],
                           capture_output=True, text=True, env=e, timeout=60)
        check("fayl yo'q: baza YARATILMASDAN to'xtaydi", r.returncode != 0,
              f"kod={r.returncode}")
        check("fayl yo'q: NIMA yetishmayotgani aytiladi",
              "yetishmaydi: migratsiya.py" in r.stderr, r.stderr[:200])
        check("fayl yo'q: stdout da darvoza nomi YO'Q",
              "tenderai_gate_" not in r.stdout, repr(r.stdout[:120]))



def test_0071_tasdigi():
    bolim("26. 0071 TASDIG'I — SQL XATOSI NOL EMAS")

    # O'LCHANGAN NUQSON (2026-09-07): tekshiruv shunday edi —
    #
    #     psql ... "WHERE id LIKE '0071%'" 2>/dev/null || echo 0
    #
    # Ustun `id` emas, `migratsiya_id`, ya'ni so'rov HAR SAFAR xato
    # berardi; `|| echo 0` esa xatoni yutib, natijani `0` ga
    # aylantirardi. Migratsiya HAQIQATAN qo'llangan bo'lsa ham
    # darvoza "0071 qo'llanmadi" derdi va sabab ko'rinmasdi.
    #
    # BU SINOV `psql` NI SHIMLAYDI: haqiqiy baza kerak emas, uch
    # holatni ham ISHONCHLI yasash mumkin.
    src = oqi("bin", "darvoza-baza.sh")
    check("ustun `migratsiya_id`", "migratsiya_id LIKE '0071%'" in src)
    # LITERAL MANBAGA BOG'LANADI. Men bu yerda IKKI MARTA adashdim:
    # avval ustun nomini (`id` <- `migratsiya_id`), keyin holat
    # qiymatini (`tugadi` <- `ok`) TAXMIN QILDIM. Ikkalasi ham
    # `migratsiya.py` da yozilgan turgan edi.
    #
    # Shuning uchun sinov endi qiymatni qo'lda YOZMAYDI — uni
    # `migratsiya.py` dan O'QIYDI. Kod o'zgarsa sinov ham o'zgaradi
    # yoki YIQILADI; taxminga joy qolmaydi.
    mp = io.open(os.path.join(ROOT, "migratsiya.py"), encoding="utf-8").read()
    m = re.search(r'\.tugat\(\s*sid\s*,\s*"([a-z_]+)"', mp)
    check("muvaffaqiyat literali `migratsiya.py` dan topildi", m is not None,
          "`tugat(sid, \"...\")` naqshi o'zgargan bo'lsa sinov yangilansin")
    if m:
        muvaffaqiyat = m.group(1)
        check(f"darvoza AYNI literalni kutadi ('{muvaffaqiyat}')",
              f"        {muvaffaqiyat}) log" in src,
              "darvoza va migratsiya.py ajralib ketgan")

    # O'TKAZIB YUBORILGAN — ALOHIDA VA MUHIM.
    check("`otkazildi` muvaffaqiyat deb SANALMAYDI",
          "otkazildi)" in src and "O'TKAZIB YUBORILGAN" in src,
          "skip = success — ERP 23-patchidagi nuqsonning aynan o'zi")
    # IZOHLAR CHIQARILADI: eski nuqson shu faylning IZOHIDA
    # ataylab yozilgan va uni naqsh deb sanash sinovni o'zi yasagan
    # yolg'on bilan yiqitardi.
    kod_qatorlar = [q for q in src.splitlines()
                    if not q.lstrip().startswith("#")]
    check("fail-open naqsh YO'Q",
          "2>/dev/null || echo 0" not in chr(10).join(kod_qatorlar),
          "SQL xatosi nolga aylanmasin")
    check("`ON_ERROR_STOP=1` ishlatiladi", "ON_ERROR_STOP=1" in src)

    bash = _mashq_bash()
    if not bash:
        check("bash yo'q — yurgizib tekshirilmadi", True)
        return

    baza = tempfile.mkdtemp(prefix="tenderai_0071_")
    try:
        qutі = os.path.join(baza, "shim")
        os.makedirs(qutі)
        N = chr(10)
        # SHIM: `SHIM_REJIM` ga qarab uch xil javob beradi.
        #   xato   -> chiqish kodi 1 (o'lchab bo'lmadi)
        #   yoq    -> jurnal 0
        #   jadvalsiz -> jurnal 1, sxema `f`
        #   toliq  -> jurnal 1, sxema `t`
        shim = os.path.join(qutі, "psql")
        io.open(shim, "w", encoding="utf-8", newline=N).write(
            "#!/bin/sh" + N +
            'case "$SHIM_REJIM" in' + N +
            '  xato) echo "ERROR: column does not exist" >&2; exit 1 ;;' + N +
            'esac' + N +
            'for a in "$@"; do case "$a" in' + N +
            '  *to_regclass*) if [ "$SHIM_REJIM" = "jadvalsiz" ]; then echo f;'
            ' else echo t; fi; exit 0 ;;' + N +
            '  *migratsiya_id*) case "$SHIM_REJIM" in' + N +
            '      yoq) echo "<qator yo\'q>" ;;' + N +
            '      otkazildi) echo otkazildi ;;' + N +
            '      boshlandi) echo boshlandi ;;' + N +
            '      *) echo ok ;;' + N +
            '    esac; exit 0 ;;' + N +
            'esac; done' + N + "exit 0" + N)
        os.chmod(shim, 0o755)

        def yurgiz(rejim):
            e = dict(os.environ)
            e["APP_ENV"] = "staging"
            e["XT_DB_DSN_TEST_ADMIN"] = "dbname=x user=x"
            e["SHIM_REJIM"] = rejim
            e["PATH"] = _posix_yol(bash, qutі) + os.pathsep + e["PATH"]
            r = subprocess.run(
                [bash, "-c", 'PATH="$1:$PATH"; shift; exec "$@"', "_",
                 _posix_yol(bash, qutі),
                 os.path.join(D, "bin", "darvoza-baza.sh"),
                 "tasdiq", "dbname=x"],
                capture_output=True, text=True, env=e, timeout=60)
            return r.returncode, (r.stdout or "") + (r.stderr or "")

        kod, chiq = yurgiz("toliq")
        check("1-holat: jurnal + jadval bor -> PASS", kod == 0, chiq[-200:])

        kod, chiq = yurgiz("yoq")
        check("2-holat: jurnal yo'q -> FAIL", kod != 0)
        check("2-holat: sabab — jurnaldagi HOLAT ko'rsatiladi",
              "qator yo" in chiq, chiq[-200:])

        # 5-holat: O'TKAZIB YUBORILGAN — muvaffaqiyat EMAS.
        kod, chiq = yurgiz("otkazildi")
        check("5-holat: `otkazildi` -> FAIL", kod != 0)
        check("5-holat: 'O'TKAZIB YUBORILGAN' deyiladi",
              "TKAZIB YUBORILGAN" in chiq, chiq[-200:])

        # 6-holat: tugamagan migratsiya ham muvaffaqiyat emas.
        kod, chiq = yurgiz("boshlandi")
        check("6-holat: `boshlandi` -> FAIL", kod != 0)
        check("6-holat: holat AYTILADI", "boshlandi" in chiq, chiq[-200:])

        kod, chiq = yurgiz("xato")
        check("3-holat: SQL xatosi -> FAIL", kod != 0)
        check("3-holat: 'o'lchanmagan' deyiladi va NOL DEYILMAYDI",
              "LCHANMAGAN" in chiq.upper() and "qator yo" not in chiq,
              chiq[-250:])

        kod, chiq = yurgiz("jadvalsiz")
        check("4-holat: jurnal bor, jadval yo'q -> FAIL", kod != 0)
        check("4-holat: sabab AYTILADI",
              "tender_topshiriq" in chiq, chiq[-200:])
    finally:
        shutil.rmtree(baza, ignore_errors=True)


# =============================================================================
# 27. FAZA 2 — STAGING KONTEYNERI TRAFIKNI O'G'IRLAB KETMASIN
# =============================================================================
# Faza 2 ning butun ma'nosi: konteyner systemd relizining YONIDA
# ko'tariladi va yiqilsa ham foydalanuvchi hech narsa sezmaydi.
# Bu xossani bir nechta mustaqil qaror ushlab turadi va ularning
# HAR BIRI beparvo tahrirdan buziladigan:
#
#   * port 8012 -> 8011 ga aylansa, konteyner systemd relizi bilan
#     PORT UCHUN URUSHADI;
#   * `API_HOST` `0.0.0.0` bo'lib qolsa, host tarmog'ida xizmat
#     BUTUN INTERNETGA chiqadi (49.12.47.155:8012);
#   * o'ram nginx ni tahrirlay boshlasa, qadam QAYTARILADIGAN
#     bo'lmay qoladi.
#
# Uchalasi ham "ishlayapti" degan sinovdan O'TIB KETADI — yiqilish
# faqat ishlab chiqarishda ko'rinardi. Shuning uchun statik tekshiruv.


def test_faza2_staging_konteyneri():
    bolim("27. Faza 2 — staging konteyneri")
    y = _oqi_ildiz("deploy/bin/staging-docker.sh")
    o = _oqi_ildiz("deploy/bin/tender-staging-docker.namuna")
    d = _oqi_ildiz("Dockerfile.backend")

    # --- port ajratilgan ---
    check("yordamchi 8012 da (systemd 8011 dan ajratilgan)",
          "8012" in y and ":-8012}" in y)
    check("o'ram portni qotiradi", "PORT=8012" in o)
    # IZOHLAR sanalmaydi: o'ram 8011 ni TUSHUNTIRISHI mumkin, lekin
    # unga qarshi HARAKAT qilmasligi kerak.
    def _amaliy(matn):
        return [q for q in matn.splitlines()
                if q.strip() and not q.lstrip().startswith("#")]

    # 8011 ni ESLATISH mumkin (holat chiqarish, izoh), lekin unga
    # BOG'LANISH yoki uni TO'XTATISH mumkin emas — aynan shu ikkisi
    # systemd relizi bilan urushga olib kelardi.
    ozgartiruvchi = ("-p ", "--publish", "PORT=8011", "API_PORT=8011",
                     "systemctl stop", "systemctl restart", "fuser", "kill")
    urush = [q for q in _amaliy(o)
             if "8011" in q and any(t in q for t in ozgartiruvchi)]
    check("o'ram 8011 ga bog'lanmaydi va uni to'xtatmaydi", not urush,
          "; ".join(q.strip() for q in urush))
    check("o'ram 8011 ni faqat o'qiydi/eslatadi",
          all(("echo" in q or q.lstrip().startswith("PORT=8012"))
              for q in _amaliy(o) if "8011" in q))

    # --- host tarmog'ida FAQAT loopback ---
    check("host tarmog'i ishlatiladi", "--network host" in y)
    check("bog'lanish loopback ga qotirilgan", "-e API_HOST=127.0.0.1" in y)
    check("0.0.0.0 ga bog'lanmaydi", "API_HOST=0.0.0.0" not in y)
    check("Dockerfile API_HOST ni sozlanadigan qilgan",
          "${API_HOST}" in d and "API_HOST=0.0.0.0" in d)
    check("Dockerfile da qotirilgan --host 0.0.0.0 qolmagan",
          "--host 0.0.0.0" not in d)

    # --- imtiyoz ---
    for bayroq, nom in (("--cap-drop ALL", "cap-drop ALL"),
                        ("no-new-privileges:true", "no-new-privileges")):
        check(f"yordamchi: {nom}", bayroq in y)
    for yomon in ("--privileged", "docker.sock", "--user root", "chmod 777"):
        check(f"yordamchi: {yomon} yo'q", yomon not in y)
        check(f"o'ram: {yomon} yo'q", yomon not in o)

    # --- o'ram argument shartnomasi ---
    check("o'ram ixtiyoriy docker argumentini uzatmaydi",
          'docker "$@"' not in o and "docker $@" not in o)
    check("o'ram ortiqcha argumentni rad etadi", '"$#" -le 1' in o)
    check("o'ram imij tegini chaqiruvchidan olmaydi",
          "sha_ol" in o and "${SHA:0:12}" in o)
    check("o'ram root talab qiladi", '[ "$(id -u)" = 0 ]' in o)
    check("o'ram noma'lum amalni rad etadi",
          "foydalanish:" in o and "exit 2" in o)

    # --- amal ro'yxati YOPIQ: `case` dagi yorliqlar sanab chiqiladi ---
    import re as _re
    gavda = o[o.index("case \"$AMAL\" in"):]
    yorliqlar = set(_re.findall(r"^([a-z]+)\)", gavda, _re.M))
    check("amallar ro'yxati kutilganidek",
          yorliqlar == {"yangila", "tekshir", "qur", "ishga", "sogliq",
                        "toxtat", "holat"},
          f"topildi: {sorted(yorliqlar)}")

    # --- qaytarilishi: o'ram nginx va systemd ga TEGMAYDI ---
    # nginx ni O'QISH mumkin (`tekshir` upstream ni ko'rsatadi), lekin
    # YOZISH mumkin emas — aks holda qadam qaytariladigan bo'lmay qoladi
    # va nginx egaligi `tender-nginx` dan o'g'irlanadi.
    nginx_yozish = [q for q in _amaliy(o)
                    if "nginx" in q and any(t in q for t in
                        ("nginx -s", "systemctl reload nginx",
                         "systemctl restart nginx", "sed -i", "tee ",
                         "> /etc/nginx", ">>/etc/nginx", "> /etc/nginx"))]
    check("o'ram nginx ni qayta sozlamaydi", not nginx_yozish,
          "; ".join(q.strip() for q in nginx_yozish))
    check("o'ram nginx ni faqat o'qiydi",
          all("grep" in q or "echo" in q
              for q in _amaliy(o) if "/etc/nginx" in q))
    check("o'ram systemd relizini to'xtatmaydi",
          "systemctl stop" not in o and "systemctl disable" not in o)
    # `yangila` FAQAT oynani yangilaydi. `deploy.sh` ni chaqirsa,
    # u reliz yasab systemd xizmatini qayta ko'tarardi -- Faza 2 ning
    # butun ma'nosi shuni QILMASLIKDA.
    check("o'ram deploy.sh ni chaqirmaydi", "deploy.sh" not in o)
    check("yangila faqat fetch qiladi",
          "fetch --prune --tags origin" in o)
    check("o'ram migratsiya qo'llamaydi",
          "migratsiya.sh" not in o and "schema_patch" not in o)

    # --- sir tarqalmasin ---
    check("sir buyruq qatoriga tushmaydi (env-file ishlatiladi)",
          "--env-file" in y and "-e XT_DB_DSN" not in y)
    check("o'ram muhit faylini root sifatida o'qiydi",
          "ENV_FILE=/etc/tenderai/staging.env" in o)
    check("Dockerfile ga sir kirmagan",
          "XT_DB_DSN=" not in d and "ANTHROPIC_API_KEY=" not in d)

    check("o'ram eval ishlatmaydi",
          not [q for q in _amaliy(o) if "eval " in q or "eval\t" in q])

    import importlib.util as _iu
    _sp = _iu.spec_from_file_location(
        "muhit_ruxsat", os.path.join(ROOT, "deploy", "bin", "muhit-ruxsat.py"))
    _mr = _iu.module_from_spec(_sp)
    _sp.loader.exec_module(_mr)
    _mr_manbalar = set(_mr.MANBALAR)

    # --- IMIJ `api/` IMPORT QILADIGAN HAMMA NARSANI SAQLASIN ---
    # `api/yuklama.py` ildizdagi `etl_embed` va `etl_doc_text` ni
    # import qiladi. Ular imijga tushmasa:
    #
    #   * `sniff_magic`, `extract`, `chunk_text` -> `ImportError`,
    #     ya'ni FAYL YUKLASH BUTUNLAY ISHLAMAYDI;
    #   * `CHUNK_SIZE` import qilingan joyda zaxira BOR (1200/150),
    #     ya'ni ilova YIQILMASDI -- host relizidan boshqacha
    #     bo'laklardi. Jimgina paritet farqi: eng yomon turi.
    #
    # Darvoza to'plami buni USHLAMAYDI: `Dockerfile.gate` butun
    # daraxtni ko'chiradi, `Dockerfile.backend` esa tanlab ko'chiradi.
    df = _oqi_ildiz("Dockerfile.backend")
    kochirilgan = set()
    for q in df.splitlines():
        if q.startswith("COPY "):
            for b in q[len("COPY "):].split():
                if b.endswith(".py"):
                    kochirilgan.add(os.path.basename(b)[:-3])
                elif b.rstrip("/") == "api":
                    kochirilgan.add("api")

    import re as _re2

    def _ildiz_importlar(yol):
        """Shu fayl import qiladigan ILDIZ modullari."""
        try:
            matn = io.open(yol, encoding="utf-8").read()
        except Exception:                                     # noqa: BLE001
            return set()
        return {m.group(1) for m in _re2.finditer(
                    r"^\s*(?:from|import)\s+([a-z_][a-z0-9_]*)", matn, _re2.M)
                if os.path.isfile(os.path.join(ROOT, m.group(1) + ".py"))}

    # YOPILMA O'TUVCHI BO'LISHI SHART: `etl_doc_text` o'z navbatida
    # `etl_ishonch` ni import qiladi. Faqat `api/` ning BEVOSITA
    # importlarini sanash imijni to'liq deb ko'rsatardi, `docker build`
    # o'tardi va nuqson faqat birinchi fayl yuklashda chiqardi.
    kerak, korildi, navbat = set(), set(), []
    for k, _d, fayllar in os.walk(os.path.join(ROOT, "api")):
        navbat += [os.path.join(k, f) for f in fayllar if f.endswith(".py")]
    while navbat:
        yol = navbat.pop()
        if yol in korildi:
            continue
        korildi.add(yol)
        for nom in _ildiz_importlar(yol):
            if nom not in kerak:
                kerak.add(nom)
                navbat.append(os.path.join(ROOT, nom + ".py"))
    yetishmaydi = sorted(kerak - kochirilgan)
    check("imij `api/` import qiladigan ildiz modullarini saqlaydi",
          not yetishmaydi, "yetishmaydi: " + ", ".join(yetishmaydi))

    # Ruxsat ro'yxati imij tarkibi bilan mos tursin: import qilinadigan
    # modul muhitdan o'qisa, uning kaliti ham uzatilishi kerak.
    for m in kerak:
        check(f"ruxsat ro'yxati {m} ni skanerlaydi",
              m + ".py" in _mr_manbalar or m in _mr_manbalar)

    # --- MUHIT RUXSAT RO'YXATI ---
    # Butun `staging.env` ni uzatish konteynerga MIGRATSIYA roli DSN
    # sini berardi. Ro'yxat koddan hisoblanadi, chunki qo'lda yozilgani
    # surilib ketardi: kodga sozlama qo'shiladi, ro'yxat unutiladi va
    # ilova sukut qiymat bilan JIMGINA noto'g'ri ishlaydi.
    ruxsat = set(_mr.royxat(ROOT))

    check("o'ram muhit filtridan foydalanadi",
          "muhit_filtrla" in o and "muhit-ruxsat.py" in o)
    check("filtrlanmagan muhit fayli konteynerga uzatilmaydi",
          'TENDERAI_ENVFILE="$ENV_FILE"' not in o)

    # Bilvosita o'qiladigan kalitlar. Regex bilan qurilgan ro'yxat
    # bularni TUSHIRIB QOLDIRARDI va ilova ishga tushmasdi.
    for k in ("APP_PUBLIC_URL", "PUBLIC_BASE_URL", "AI_PAID_ENABLED"):
        check(f"ruxsatda bilvosita kalit: {k}", k in ruxsat)
    for k in ("XT_DB_DSN", "APP_ENV", "ANTHROPIC_API_KEY"):
        check(f"ruxsatda kerakli kalit: {k}", k in ruxsat)

    # ENG MUHIMI: konteyner sxemani o'zgartira oladigan rolni OLMAYDI.
    for k in ("XT_DB_DSN_OWNER", "XT_DB_DSN_TEST_ADMIN", "E2E_PAROL",
              "E2E_LOGIN", "BACKUP_REMOTE_CMD", "BACKUP_DIR"):
        check(f"ruxsatda YO'Q (to'g'ri): {k}", k not in ruxsat)

    check("majburiy kalitlar e'lon qilingan",
          set(_mr.MAJBURIY) == {"APP_ENV", "APP_PUBLIC_URL", "XT_DB_DSN"})

    # `docker --env-file` tirnoqni YECHMAYDI, `systemd EnvironmentFile`
    # yechadi. Ya'ni tirnoqli DSN da systemd relizi ISHLAB, konteyner
    # YIQILARDI -- va sabab ko'rinmasdi.
    check("tirnoq yechiladi", _mr._tirnoq_yech('"a=b"') == "a=b"
          and _mr._tirnoq_yech("'a=b'") == "a=b"
          and _mr._tirnoq_yech("a=b") == "a=b")

    # Filtr HAQIQATDA sirni tashlaydimi -- soxta fayl ustida.
    import tempfile as _tf
    _d = _tf.mkdtemp()
    try:
        _m = os.path.join(_d, "m.env")
        io.open(_m, "w", encoding="utf-8").write(
            "APP_ENV=staging\nAPP_PUBLIC_URL=https://x.invalid\n"
            "XT_DB_DSN=host=127.0.0.1\nXT_DB_DSN_OWNER=host=1 password=SIR\n"
            "E2E_PAROL=SIR\n")
        _c = os.path.join(_d, "c.env")
        _mr.filtr(ROOT, _m, _c)
        _matn = io.open(_c, encoding="utf-8").read()
        check("filtr sirni tashlaydi", "SIR" not in _matn, _matn.replace("\n", " | "))
        check("filtr natijasi 0600",
              oct(os.stat(_c).st_mode & 0o777) == "0o600")
    finally:
        shutil.rmtree(_d, ignore_errors=True)

    # --- DARVOZA JONLI BAZADA YURMASIN ---
    # Darvoza migratsiyadan OLDIN turadi (to'g'ri: migratsiya bazani
    # o'zgartiradi). Demak u joylashtirilayotgan kodni undan orqada
    # qolgan baza ustida sinardi -- 2026-09-08 da 31 to'plam yiqildi,
    # izolyatsiyalangan bazada esa 22 ta; 9 tasi SOXTA edi.
    #
    # Production da bundan ham yomon: `APP_ENV="$MUHIT"` bo'lgani
    # uchun 44 to'plam JONLI ISHLAB CHIQARISH bazasida yurardi va
    # sinovlar u yerga yozardi.
    d = _oqi_ildiz("deploy/bin/deploy.sh")
    d_amaliy = [q for q in d.splitlines()
                if q.strip() and not q.lstrip().startswith("#")]

    check("darvoza izolyatsiyalangan bazada yuradi",
          "darvoza-baza.sh\" yarat" in d or "darvoza-baza.sh yarat" in d)
    check("darvoza chaqiruvi DSN ni almashtiradi",
          any('XT_DB_DSN="$DARVOZA_DSN"' in q for q in d_amaliy))
    check("egasi DSN si ham almashtiriladi",
          any('XT_DB_DSN_OWNER="$DARVOZA_DSN_OWNER"' in q for q in d_amaliy))
    check("darvoza bazasi nomi qayta tekshiriladi",
          "tenderai_gate_[0-9]*)" in d)
    check("darvoza bazasi har holda tashlanadi (tozalash ichida)",
          "tozalash()" in d
          and d.index("tozalash()") < d.index("darvoza-baza.sh\" tashla")
          if 'darvoza-baza.sh" tashla' in d else False)
    check("production da darvoza qayta yuritilmaydi",
          'MUHIT" = "production"' in d
          and "production bazasida YURITILMAYDI" in d)

    # Production shoxida `relis-darvoza.sh` CHAQIRILMASLIGI shart.
    prod_bolim = d[d.index('log "reliz darvozasi: staging tasdigi'):] \
        if 'log "reliz darvozasi: staging tasdigi' in d else ""
    prod_bolim = prod_bolim.split("else", 1)[0] if prod_bolim else ""
    check("production shoxi relis-darvoza.sh ni chaqirmaydi",
          "relis-darvoza.sh" not in prod_bolim, prod_bolim[:80])

    # --- SINOVLAR VAQTINCHALIK KATALOGNI QOLDIRMASIN ---
    # Bu xostda `/tmp` — `tmpfs`, ya'ni RAM. Tozalanmagan sinov
    # katalogi diskni emas, XOTIRANI yeydi.
    #
    # O'LCHANGAN (2026-09-08): `pricing_test` tozalamasdi va darvoza
    # yurishlari davomida `/tmp` da 1724 ta katalog yig'ildi. O'sha
    # xotira ishlab chiqarish API siga kerak edi va
    # `tenderai-api@production` `oom-kill` bilan yiqildi.
    #
    # Ya'ni bu "ozodalik" masalasi emas: sinov ishlab chiqarishni
    # o'chirdi. Shuning uchun statik muvozanat tekshiruvi.
    import glob as _glob
    nomuvozanat = []
    for yol in sorted(_glob.glob(os.path.join(ROOT, "_tests", "*.py"))):
        matn = io.open(yol, encoding="utf-8").read()
        mk = matn.count("mkdtemp(")
        rm = matn.count("rmtree(") + matn.count("TemporaryDirectory(")
        if mk > rm:
            nomuvozanat.append(f"{os.path.basename(yol)} (mkdtemp={mk} tozalash={rm})")
    check("sinovlar vaqtinchalik katalogni tozalaydi", not nomuvozanat,
          "; ".join(nomuvozanat))

    # --- hujjat ---
    h = _oqi_ildiz("docs/docker.md")
    check("hujjatda qaytarish tartibi bor", "8012" in h)
    check("hujjatda ruxsat ro'yxati tushuntirilgan",
          "XT_DB_DSN_OWNER" in h)


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
    test_ozgarmas_tasdiq()
    test_darvoza_dsn()
    test_mahalliy_url_muhitga_qarab()
    test_bajarish_bayrogi()
    test_darvoza_xulosani_oqiydi()
    test_cookie_secure_siyosati()
    test_darvoza_stdout_kelishuvi()
    test_darvoza_toliq_daraxt()
    test_0071_tasdigi()
    test_faza2_staging_konteyneri()

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
