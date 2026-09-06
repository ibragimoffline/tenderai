#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISHLAB CHIQARISH DARVOZASI — YAGONA, TAKRORLANADIGAN, IKKILIK QAROR.

    python production_gate.py            # to'liq tekshiruv
    python production_gate.py --ref main # kutilgan branch/ref
    python production_gate.py --json     # mashina o'qishi uchun

CHIQISH KODI:
    0  — MAJBURIY darvozalarning HAMMASI o'tdi   -> GO
    1  — kamida bittasi o'tmadi                  -> NO-GO

NEGA FOIZ YO'Q
──────────────
Relis qarori IKKILIK. "87% tayyor" degan raqam har doim "deyarli
tayyor" deb o'qiladi, holbuki qolgan 13% ichida ijarachi izolyatsiyasi
ham, zaxira ham bo'lishi mumkin. Og'irlik koeffitsientini kim
tanlaydi degan savolga esa obyektiv javob yo'q. Shuning uchun bu
skript FOIZ CHIQARMAYDI; qatorlar soni faqat MA'LUMOT uchun beriladi
va u qarorga TA'SIR QILMAYDI.

NEGA "BLOKLANGAN" ALOHIDA
────────────────────────
Darvoza uch holat qaytaradi: `PASS`, `FAIL`, `BLOKLANGAN`.
`BLOKLANGAN` — "tekshirib bo'lmadi" (host yo'q, manba uzilgan).
U PASS EMAS va relisni to'sadi, lekin `FAIL` dan FARQ QILADI:
`FAIL` — biz buzganmiz, `BLOKLANGAN` — biz o'lchay olmadik.
Ikkisini bir belgiga qo'shish "o'lchanmagan" ni "yaxshi" ga
aylantirardi — bu loyihada eng qimmatga tushgan xato sinfi.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "_tests"))

try:
    import konsol                                            # noqa: E402
    konsol.sozla()
except Exception:                                            # noqa: BLE001
    pass

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except Exception:                                            # noqa: BLE001
    pass

PASS, FAIL, BLOK = "PASS", "FAIL", "BLOKLANGAN"

#: Sinov natijasi shu vaqtdan eski bo'lsa — ISHONCHSIZ.
#: Kod o'zgargan bo'lishi mumkin, natija esa eskisiniki.
SINOV_YANGILIK_SOAT = 6.0

#: `tsc` kamida shuncha LOYIHA faylini ko'rishi kerak.
#:
#: Qattiq son mo'rt (9-sinf), lekin bu yerda u chegara emas —
#: NOL QAMROV signali. Frontendda 75 ta `.ts/.tsx` bor; 20 dan
#: kam ko'rilsa buyruq bo'sh konfiguratsiyaga urilgan.
TSC_ENG_KAM_FAYL = 20

#: ETL foydali yurish ulushi. Pastroq — ma'lumot eskirishi mumkin.
ETL_MIN_FOIZ = 95.0

#: Vektor qamrovi — RAG va semantik qidiruv shunga tayanadi.
EMBED_MIN_FOIZ = 95.0


def _q(sql: str, params=None):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    dsn = os.environ.get("XT_DB_DSN")
    if not dsn:
        raise RuntimeError("XT_DB_DSN yo'q")
    conn = psycopg2.connect(dsn, connect_timeout=8,
                            cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").strip()


#: O'RIN EGASI va NAQSHNI sirdan ajratadi.
#:
#: O'LCHANGAN YOLG'ON TOPILMA (2026-09-03): birinchi urinishda skaner
#: `_tests/xavfsizlik_test.py` dagi REGEX NAQSHNI
#: (`password=(?!SIZNING)\S{8,}`) va `docs/xavfsizlik.md` dagi
#: `password=<parol>` o'rin egasini SIR deb topdi.
#:
#: Bu loyihada TAKRORLANGAN sinf: skaner O'Z NASRINI o'qiydi. Qoida —
#: HAQIQIY QIYMAT skanerlanadi, naqsh va namuna emas. Haqiqiy sir
#: regex metabelgisiz, burchakli qavssiz va "REPLACE/example/SIZNING"
#: kabi ogohlantirish so'zisiz bo'ladi.
#: Regex EMAS — belgilar to'plami. Birinchi urinishda bu regex edi
#: va u KOMPILYATSIYA BO'LMADI (`unterminated character set`), lekin
#: `ast.parse` "sintaksis toza" dedi: sintaksis tekshiruvi regex
#: yaroqliligini KO'RMAYDI. Endi mantiq oddiy va o'zi ravshan.
_META = set("<>{}[]()?!*|\\")
_OGOH = ("replace", "example", "sizning", "parol", "xxx", "...",
         "your", "changeme")


def _orin_egasi(parcha: str, fayl: str) -> bool:
    r"""Bu HAQIQIY sirmi yoki NAQSH/O'RIN EGASImi.

    O'LCHANGAN YOLG'ON TOPILMA (2026-09-03): skaner
    `_tests/xavfsizlik_test.py` dagi REGEX NAQSHNI
    (`password=(?!SIZNING)\S{8,}`) va `docs/xavfsizlik.md` dagi
    `password=<parol>` o'rin egasini SIR deb topdi.

    Bu loyihada TAKRORLANGAN sinf: skaner O'Z NASRINI o'qiydi.
    Qoida — HAQIQIY QIYMAT skanerlanadi, naqsh va namuna emas.
    """
    if any(ch in _META for ch in parcha):
        return True
    past = parcha.lower()
    if any(x in past for x in _OGOH):
        return True
    # Namuna muhit fayllari — ular ATAYLAB repozitoriyda.
    return fayl.endswith(".env.example") or "/env/" in fayl


# =====================================================================
# GATE 1 — MANBA
# =====================================================================
def gate_manba(kutilgan_ref: str) -> Tuple[str, List[str]]:
    dalil: List[str] = []
    holat = PASS

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    sha = _git("rev-parse", "--short", "HEAD")
    dalil.append(f"ref: {branch} @ {sha}")
    if kutilgan_ref and branch != kutilgan_ref:
        holat = FAIL
        dalil.append(f"  KUTILGAN: {kutilgan_ref} — MOS EMAS")

    # KUZATILAYOTGAN fayllardagi o'zgarish XAVFLI: relis `git archive`
    # bilan yasaladi va u FAQAT kommit qilingan holatni oladi. Ya'ni
    # ishlab chiqarishga TEKSHIRILMAGAN kod ketardi.
    porcelain = _git("status", "--porcelain")
    ozgargan = [l for l in porcelain.splitlines() if l and not l.startswith("??")]
    kuzatilmagan = [l for l in porcelain.splitlines() if l.startswith("??")]
    dalil.append(f"kommit qilinmagan (kuzatilayotgan): {len(ozgargan)}")
    dalil.append(f"kuzatilmagan fayl: {len(kuzatilmagan)}")
    if ozgargan:
        holat = FAIL
        for l in ozgargan[:6]:
            dalil.append(f"  {l}")

    # SIR SKANERI — kuzatilayotgan fayllar ustidan.
    sir_naqsh = re.compile(
        r"(password\s*=\s*[^\s'\"]{6,}|"
        r"postgres(?:ql)?://[^\s'\"]+:[^\s'\"]+@|"
        r"sk-[A-Za-z0-9]{20,}|"
        r"AKIA[0-9A-Z]{16})")
    topilgan: List[str] = []
    for f in _git("ls-files").splitlines():
        if not f or f.endswith((".png", ".jpg", ".woff2", ".ico")):
            continue
        yol = os.path.join(HERE, f)
        try:
            matn = io.open(yol, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in sir_naqsh.finditer(matn):
            parcha = m.group(0)
            if _orin_egasi(parcha, f):
                continue
            topilgan.append(f"{f}: {parcha[:40]}")
    dalil.append(f"sir topildi: {len(topilgan)}")
    if topilgan:
        holat = FAIL
        for t in topilgan[:5]:
            dalil.append(f"  {t}")
    return holat, dalil


# =====================================================================
# GATE 2 — SINOVLAR
# =====================================================================
def _tsc_qamrovi() -> int:
    """`tsc` nechta LOYIHA faylini ko'radi.

    QAMROV RAQAMI — natijaning o'zi emas. Sinov to'plami "0 xato"
    desa, savol qoladi: 0 xato nechta fayldan? Multitenant
    skanerida bu allaqachon qilingan (`69 -> 139 funksiya`), bu
    yerda ham kerak: qamrovsiz yashil raqam ISHONCHSIZ.

    `--listFiles` kutubxona va `node_modules` fayllarini ham
    chiqaradi — ular SANALMAYDI, aks holda bo'sh konfiguratsiya
    ham yuzlab fayl ko'rsatardi va butun tekshiruv ma'nosini
    yo'qotardi.

    Yiqilsa `-1` qaytaradi: "o'lchay olmadim" ni "0 fayl" ga
    aylantirish shu faylning o'zi qo'riqlayotgan xato bo'lardi.
    """
    fe = os.path.join(HERE, "frontend")
    try:
        r = subprocess.run(
            ["npx", "tsc", "-p", "tsconfig.app.json", "--noEmit",
             "--listFiles"],
            cwd=fe, capture_output=True, text=True,
            encoding="utf-8", errors="replace", shell=True, timeout=300)
    except Exception:                                     # noqa: BLE001
        return -1
    src = os.path.join(fe, "src").replace("\\", "/").lower()
    n = 0
    for ln in (r.stdout or "").split("\n"):
        y = ln.strip().replace("\\", "/").lower()
        if y.startswith(src) and "node_modules" not in y:
            n += 1
    return n


def gate_sinov(frontend: bool) -> Tuple[str, List[str]]:
    dalil: List[str] = []
    holat = PASS
    yol = os.path.join(HERE, "_test_natija", "xulosa.json")
    if not os.path.exists(yol):
        return BLOK, ["_test_natija/xulosa.json YO'Q — "
                      "`python run_tests.py --online` yurgizing"]

    yosh_soat = (time.time() - os.path.getmtime(yol)) / 3600.0
    d = json.load(io.open(yol, encoding="utf-8"))
    dalil.append(f"rejim: {d.get('rejim')} · yosh: {yosh_soat:.1f} soat")
    dalil.append(f"to'plam: {d.get('toplam_otdi')}/{d.get('toplam_jami')} · "
                 f"tekshiruv: {d.get('tekshiruv_otdi')}/{d.get('tekshiruv_jami')}")

    if d.get("rejim") != "toliq":
        holat = FAIL
        dalil.append("  rejim `toliq` EMAS — tarmoq/baza sinovlari yurmagan")
    # QAMROV: HAMMA TO'PLAM YURDIMI.
    #
    # Filtrlangan yurish ("1/43 to'plam") xulosada "1 o'tdi, 0
    # yiqildi" bo'lib chiqadi va darvoza uni MUVAFFAQIYAT deb
    # o'qirdi. `tsc -p tsconfig.json` bilan bir sinf: yashil
    # raqam, nol qamrov.
    mavjud = d.get("toplam_mavjud")
    otkazildi = d.get("toplam_otkazildi") or []
    if mavjud is None:
        holat = FAIL
        dalil.append("  qamrov O'LCHANMAGAN — `run_tests.py` eski versiyada "
                     "yurgizilgan (`toplam_mavjud` yo'q)")
    elif otkazildi:
        holat = FAIL
        dalil.append(f"  QAMROV TO'LIQ EMAS: {d.get('toplam_jami')}/{mavjud} "
                     f"to'plam yurgan, {len(otkazildi)} tasi o'tkazilgan "
                     f"(filtr: {d.get('filtr')!r})")
    # MAXRAJ KAMAYGANI — `glob` bilan topiladigan to'plam soni
    # tushgan. `43/43` yashil qolaveradi, lekin qamrov kichraygan.
    yoqoldi = d.get("toplam_yoqoldi")
    if yoqoldi:
        holat = FAIL
        dalil.append(f"  TO'PLAM YO'QOLGAN: oldingi yurishda "
                     f"{d.get('toplam_mavjud_oldingi')} ta edi, hozir "
                     f"{mavjud} ta ({yoqoldi} ta kam). Sinov fayli "
                     f"o'chirilgan yoki nomi o'zgargan bo'lishi mumkin.")
    # ROL — tekshiruv soni SHUNGA bog'liq (`postgres` 3402,
    # `tai_app` 3280). Rol yozilmagan bo'lsa taqqoslash ham yo'q.
    rol = d.get("rol") or {}
    dalil.append(f"rol: {rol.get('nom') or 'NOMA`LUM'}"
                 + (" (SUPERUSER)" if rol.get("superuser") else ""))
    if rol.get("superuser"):
        holat = FAIL
        dalil.append("  SINOVLAR SUPERUSER BILAN YURGAN — grant asosidagi "
                     "himoyalar (ERP chegarasi) SINALMAGAN. "
                     "`DB_SET_ROLE=tai_app` bilan qayta yurgizing.")
    teks_yoq = d.get("tekshiruv_yoqoldi")
    if teks_yoq:
        holat = FAIL
        dalil.append(f"  TEKSHIRUV YO'QOLGAN: bir xil rejimda "
                     f"{d.get('tekshiruv_jami_oldingi')} dan "
                     f"{d.get('tekshiruv_jami')} ga tushdi ({teks_yoq} ta).")
    if yosh_soat > SINOV_YANGILIK_SOAT:
        holat = FAIL
        dalil.append(f"  natija {SINOV_YANGILIK_SOAT} soatdan ESKI")
    if d.get("toplam_yiqildi"):
        holat = FAIL
        dalil.append(f"  YIQILGAN: {', '.join(d.get('yiqilgan') or [])}")
    # "O'lchanmagan" to'plam — bajarilmagan bilan bir xil og'irlikda.
    olchanmadi = d.get("tekshiruv_olchanmadi") or []
    if olchanmadi:
        holat = FAIL
        dalil.append(f"  tekshiruvi O'LCHANMAGAN: {', '.join(olchanmadi)}")

    if frontend:
        # BUYRUQ `package.json` DAN — QO'LDA YOZILMAYDI.
        #
        # O'LCHANGAN NUQSON (2026-09-04, interaktiv seansda). Qo'lda
        # `npx tsc --noEmit -p tsconfig.json` yozilgan va u har safar
        # `exit 0` bergan. `frontend/tsconfig.json` da esa
        # `"files": []` va faqat `references` bor — ya'ni bu buyruq
        # HECH NARSANI tekshirmaydi. Konfiguratsiya to'g'ri, buyruq
        # to'g'ri, chiqish kodi to'g'ri; QAMROV NOL.
        #
        # Yashil raqam hisobotga chiqdi va unga tayanib qaror qabul
        # qilindi. To'g'ri buyruq (`tsc -b`) darhol haqiqiy xato
        # topdi. Shuning uchun bu yerda `npm run gate` chaqiriladi
        # va yonida QAMROV o'lchanadi.
        r = subprocess.run(["npm", "run", "gate"],
                           cwd=os.path.join(HERE, "frontend"),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", shell=True)
        ok = r.returncode == 0
        n_fayl = _tsc_qamrovi()
        dalil.append(f"frontend gate (tsc + xulq + build): "
                     f"{'PASS' if ok else 'FAIL'} · "
                     f"tsc {n_fayl} ta loyiha faylini ko'rdi")
        if not ok:
            holat = FAIL
            dalil.append("  " + (r.stdout or r.stderr or "")[-200:].strip())
        # `0 xato` va `0 fayl, 0 xato` BIR XIL KO'RINMASIN.
        if n_fayl < TSC_ENG_KAM_FAYL:
            holat = FAIL
            dalil.append(f"  tsc QAMROVI shubhali: {n_fayl} fayl "
                         f"(kutilgan >= {TSC_ENG_KAM_FAYL}). Buyruq "
                         f"bo'sh konfiguratsiyaga urilgan bo'lishi mumkin.")
    else:
        holat = FAIL if holat == PASS else holat
        dalil.append("frontend gate YURGIZILMADI (`--frontend` bering) — "
                     "tekshirilmagan narsa o'tgan deb sanalmaydi")
    return holat, dalil


# =====================================================================
# GATE 3 — BAZA
# =====================================================================
def gate_baza() -> Tuple[str, List[str]]:
    dalil: List[str] = []
    holat = PASS
    try:
        who = _q("SELECT current_user AS u, "
                 "  (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) "
                 "  AS super")[0]
    except Exception as e:                                   # noqa: BLE001
        return BLOK, [f"bazaga ulanib bo'lmadi: {str(e)[:90]}"]

    dalil.append(f"rol: {who['u']} · superuser: {who['super']}")
    if who["super"]:
        holat = FAIL
        dalil.append("  ILOVA SUPERUSER BILAN ISHLAMASLIGI KERAK")
    if who["u"] == "postgres":
        holat = FAIL
        dalil.append("  `postgres` — egalik roli, ilova roli emas")

    qolgan = _q("SELECT count(*) AS n FROM v_migratsiya_holat "
                " WHERE holat NOT IN ('ok','bootstrap')")[0]["n"]
    dalil.append(f"qo'llanmagan migratsiya: {qolgan}")
    if qolgan:
        holat = FAIL

    vec = _q("SELECT count(*) AS n FROM pg_extension WHERE extname='vector'")
    dalil.append("pgvector: " + ("bor" if vec[0]["n"] else "YO'Q"))
    if not vec[0]["n"]:
        holat = FAIL
    return holat, dalil


# =====================================================================
# GATE 4 — MA'LUMOT QUVURLARI
# =====================================================================
def gate_quvur() -> Tuple[str, List[str]]:
    dalil: List[str] = []
    holat = PASS
    try:
        etl = _q("SELECT source_platform, foydali_foiz, host_uzildi, "
                 "       manba_xato, yurmoqda, darvoza FROM v_etl_saglik")
    except Exception as e:                                   # noqa: BLE001
        return BLOK, [f"o'lchab bo'lmadi: {str(e)[:90]}"]

    for r in etl:
        dalil.append(f"ETL {r['source_platform']}: foydali {r['foydali_foiz']}% · "
                     f"host_uzildi {r['host_uzildi']} · manba_xato "
                     f"{r['manba_xato']} · darvoza {r['darvoza']}")
        if r["darvoza"] != "ochiq":
            holat = FAIL
        if (r["foydali_foiz"] or 0) < ETL_MIN_FOIZ:
            holat = FAIL
        if r["yurmoqda"]:
            dalil.append(f"  tushuntirilmagan `running`: {r['yurmoqda']}")
            holat = FAIL

    sabab = _q("SELECT coalesce(sum(n),0) AS n FROM v_document_qamrov_sabab "
               " WHERE sabab = 'sabab_nomalum'")[0]["n"]
    dalil.append(f"hujjat sababi NOMA'LUM: {sabab}")
    if sabab:
        holat = FAIL

    bosh = _q("SELECT source_platform, hujjatsiz_foiz, kutilgan "
              "  FROM v_hujjatsiz_ochiq_tender")
    for r in bosh:
        dalil.append(f"hujjatsiz ochiq tender {r['source_platform']}: "
                     f"{r['hujjatsiz_foiz']}% ({r['kutilgan']} kutilgan)")
        if (r["hujjatsiz_foiz"] or 0) > 0:
            holat = FAIL

    emb = _q("SELECT qamrov_foiz FROM v_embedding_coverage")[0]["qamrov_foiz"]
    dalil.append(f"vektor qamrovi: {emb}%")
    if (emb or 0) < EMBED_MIN_FOIZ:
        holat = FAIL
    return holat, dalil


# =====================================================================
# GATE 5 — INSON VALIDATSIYASI
# =====================================================================
def gate_inson() -> Tuple[str, List[str]]:
    dalil: List[str] = []
    holat = PASS
    try:
        tay = _q("SELECT qatlam, aktor_faol, tosiq FROM v_pilot_tayyorlik")
        dar = _q("SELECT qatlam, eng_kam, aktorli, holat FROM v_sifat_darvoza")
    except Exception as e:                                   # noqa: BLE001
        return BLOK, [f"o'lchab bo'lmadi: {str(e)[:90]}"]

    for r in tay:
        if r["tosiq"]:
            holat = FAIL
            dalil.append(f"{r['qatlam']}: TO'SIQ — {r['tosiq']}")
    for r in dar:
        dalil.append(f"{r['qatlam']}: {r['aktorli']}/{r['eng_kam']} "
                     f"({r['holat']})")
        if r["holat"] != "INSON_TASDIQLADI":
            holat = FAIL
    return holat, dalil


# =====================================================================
# GATE 6 — ERP YOPIQ HALQASI
# =====================================================================
def gate_erp() -> Tuple[str, List[str]]:
    dalil: List[str] = []
    try:
        top = _q("SELECT count(*) AS n FROM tender_topshiriq "
                 " WHERE bekor_at IS NULL")[0]["n"]
    except Exception as e:                                   # noqa: BLE001
        return BLOK, [f"o'lchab bo'lmadi: {str(e)[:90]}"]
    dalil.append(f"faol topshiriq (Tender-AI -> ERP): {top}")

    try:
        bog = _q("SELECT count(*) AS n FROM erp.opportunity "
                 " WHERE routing_id IS NOT NULL OR topshiriq_id IS NOT NULL")
        dalil.append(f"ulangan opportunity: {bog[0]['n']}")
        if not bog[0]["n"]:
            dalil.append("  halqa HECH QACHON uchidan-uchiga yurmagan")
            return FAIL, dalil
    except Exception as e:                                   # noqa: BLE001
        dalil.append(f"erp.opportunity o'qib bo'lmadi: {str(e)[:70]}")
        return BLOK, dalil

    natija = _q("SELECT count(*) AS n FROM erp.v_tender_status "
                " WHERE status IN ('submitted','won','lost','rejected')")
    dalil.append(f"yakuniy natijali opportunity: {natija[0]['n']}")
    return (PASS if natija[0]["n"] else FAIL), dalil


# =====================================================================
# GATE 7 — INFRATUZILMA
# =====================================================================
def gate_infra() -> Tuple[str, List[str]]:
    # Staging Linux hosti YO'Q (2026-09-03 da tasdiqlangan): domenlar
    # namunaviy, `deploy.sh` hostda yuriladi, ulanish ma'lumoti yo'q.
    # Shuning uchun HTTPS, monitoring, zaxira yangiligi va restore
    # mashqini bu mashinadan TEKSHIRIB BO'LMAYDI.
    return BLOK, [
        "staging Linux hosti YO'Q — HTTPS, monitoring, zaxira va "
        "restore mashqi TEKSHIRILMADI",
        "deploy/systemd va deploy/caddy artefaktlari BOR, lekin "
        "joylashtirilmagan (docs/deploy.md §13.5)",
    ]


# =====================================================================
# GATE 8 — SOZLAMA
# =====================================================================
def gate_sozlama() -> Tuple[str, List[str]]:
    dalil: List[str] = []
    holat = PASS
    # OMMAVIY MANZILNI MUHITDAN O'ZIMIZ O'QIMAYMIZ.
    #
    # `ommaviy_url_test` arxitektura invariantini qulflaydi: bu
    # qiymatni muhitdan AYNAN BITTA fayl o'qiydi (`api/ommaviy_url.py`).
    # Birinchi urinishda bu skript uni to'g'ridan-to'g'ri o'qidi va
    # sinov DARHOL yiqildi — to'g'ri qildi: ikkinchi o'quvchi ikkinchi
    # HAQIQAT MANBASI demak (eski nom, boshqa normallashtirish,
    # ziddiyat tekshiruvisiz).
    #
    # Yon foyda: endi darvoza ishlab chiqarish ISHLATADIGAN yo'lni
    # sinaydi — ziddiyat aniqlash va normallashtirish bilan birga.
    from api import ommaviy_url as OU
    muhit = OU.muhit()
    try:
        url, manba = OU.sozlangan()
        url = (url or "").strip()
    except Exception as e:                                   # noqa: BLE001
        return FAIL, [f"ommaviy manzil sozlamasi ZIDDIYATLI: {str(e)[:90]}"]
    dalil.append(f"APP_ENV={muhit} · ommaviy manzil: {url or '(sozlanmagan)'}")

    if muhit == "dev":
        return BLOK, dalil + [
            "APP_ENV=dev — bu ISHLAB CHIQARISH sozlamasi EMAS. "
            "Darvoza production muhitida yurgizilishi kerak."]

    if not url:
        holat = FAIL
        dalil.append("  APP_PUBLIC_URL majburiy")
    elif re.search(r"//(localhost|127\.0\.0\.1|.*\.local)\b", url, re.I):
        holat = FAIL
        dalil.append("  ommaviy manzil MAHALLIY — bildirishnoma "
                     "havolalari ochilmaydi")
    elif not url.lower().startswith("https://"):
        holat = FAIL
        dalil.append("  HTTPS emas")

    for nom, kutilgan in (("AUTH_COOKIE_SECURE", "1"), ("TRUST_PROXY", "1")):
        qiy = (os.environ.get(nom) or "").strip()
        dalil.append(f"{nom}={qiy or '(sozlanmagan)'}")
        if qiy != kutilgan:
            holat = FAIL
            dalil.append(f"  kutilgan {kutilgan}")

    dsn = os.environ.get("XT_DB_DSN") or ""
    if re.search(r"\buser\s*=\s*postgres\b", dsn):
        holat = FAIL
        dalil.append("  XT_DB_DSN `postgres` roli bilan — eng kam huquq buzilgan")
    return holat, dalil


# =====================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="Ishlab chiqarish darvozasi")
    ap.add_argument("--ref", default="", help="Kutilgan branch/ref")
    ap.add_argument("--frontend", action="store_true",
                    help="`npm run gate` ni ham yurgizadi (~40 s)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    darvozalar = [
        ("1. MANBA", lambda: gate_manba(args.ref)),
        ("2. SINOVLAR", lambda: gate_sinov(args.frontend)),
        ("3. BAZA", gate_baza),
        ("4. MA'LUMOT QUVURLARI", gate_quvur),
        ("5. INSON VALIDATSIYASI", gate_inson),
        ("6. ERP YOPIQ HALQASI", gate_erp),
        ("7. INFRATUZILMA", gate_infra),
        ("8. SOZLAMA", gate_sozlama),
    ]

    natija: List[Dict[str, Any]] = []
    for nom, fn in darvozalar:
        try:
            holat, dalil = fn()
        except Exception as e:                               # noqa: BLE001
            holat, dalil = BLOK, [f"tekshiruv yiqildi: {str(e)[:110]}"]
        natija.append({"darvoza": nom, "holat": holat, "dalil": dalil})

    otgan = sum(1 for r in natija if r["holat"] == PASS)
    qaror = "GO" if otgan == len(natija) else "NO-GO"

    if args.json:
        print(json.dumps({"qaror": qaror, "darvozalar": natija},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("ISHLAB CHIQARISH DARVOZASI")
        print("=" * 74)
        for r in natija:
            print(f"\n[{r['holat']:^11}] {r['darvoza']}")
            for d in r["dalil"]:
                print(f"    {d}")
        print("\n" + "=" * 74)
        # Bu qator MA'LUMOT uchun. Qaror unga TAYANMAYDI.
        print(f"(ma'lumot uchun: {otgan}/{len(natija)} darvoza o'tdi — "
              "qaror bu nisbatga tayanmaydi)")
        print(f"QAROR: {qaror}")
        print("=" * 74)

    sys.exit(0 if qaror == "GO" else 1)


if __name__ == "__main__":
    main()
