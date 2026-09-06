#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: ETL ISHONCHLILIGI (etl_ishonch.py + etl_uzex/tenders/details)
=====================================================================

NEGA BU SINOV BOR (o'lchangan sabab)
-------------------------------------
2026-08-30 da `etl_run` ning 14 kunlik tahlili: 178 xatoning **154 tasi**
ETL xatosi emas, balki jarayon o'ldirilgani uchun yopilmay qolgan
`running` qatorlari. ETL yiqilmasdi — TUGATISHGA ULGURMASDI, va
tugatolmagani uchun keyingi soatda NOLDAN boshlab yana ulgurmasdi.

Bu sinov aynan o'sha nosozlik yo'llarini KOD BILAN takrorlaydi:
tarmoq uzilishi, 5xx, 429, doimiy 4xx, buzuq JSON, buzuq yozuv,
jarayon o'ldirilishi, ustma-ust yurish, yetim qator.

DIZAYN QARORI — MANBAGA SO'ROV YUBORMAYDI
------------------------------------------
Nosozlik yo'llari SOXTA javob bilan sinaladi. Sabab uch xil:
  * 500/429/timeout ni haqiqiy manbadan CHAQIRIB BO'LMAYDI;
  * chaqirib bo'lganda ham u manbaga hurmatsizlik bo'lardi;
  * sinov TAKRORLANADIGAN bo'lishi kerak — tarmoq holatiga bog'liq
    sinov "ba'zan yiqiladi" degan foydasiz signal beradi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\etl_ishonch_test.py
    .venv\\Scripts\\python.exe _tests\\etl_ishonch_test.py --offline
"""
import argparse
import io
import json
import os
import random
import subprocess
import sys
import time

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
import rejim  # noqa: E402

konsol.sozla()


from dotenv import load_dotenv                               # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import requests                                              # noqa: E402

import etl_ishonch as ish                                    # noqa: E402

try:
    import psycopg2
except ImportError:                                          # pragma: no cover
    psycopg2 = None

_results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def db():
    dsn = os.environ.get("XT_DB_DSN")
    if not dsn:
        return None
    try:
        c = psycopg2.connect(dsn, connect_timeout=8)
        c.autocommit = True
        return c
    except Exception as e:                                   # noqa: BLE001
        print(f"  [i] baza yetib bo'lmadi: {str(e)[:90]}")
        return None


# =====================================================================
# SOXTA JAVOBLAR
# =====================================================================
class SoxtaJavob:
    """`requests.Response` ning sinov uchun yetarli qismi."""

    def __init__(self, kod=200, matn="{}", sarlavhalar=None):
        self.status_code = kod
        self.text = matn
        self.headers = sarlavhalar or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            xato = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            xato.response = self
            raise xato

    def json(self):
        return json.loads(self.text)


# =====================================================================
# 1) XATO TASNIFI — nima qayta urinishga arziydi
# =====================================================================
def test_tasnif() -> None:
    section("Xato tasnifi (qayta urinsa bo'ladimi)")

    qayta = {
        "ulanish uzildi": requests.exceptions.ConnectionError("uzildi"),
        "ULANISH timeouti": requests.exceptions.ConnectTimeout("connect"),
        "O'QISH timeouti": requests.exceptions.ReadTimeout("read"),
    }
    for nom, exc in qayta.items():
        check(f"{nom} -> QAYTA URINILADI", ish.tasnifla(exc).qayta_urinsa)

    for kod in (408, 425, 429, 500, 502, 503, 504):
        e = requests.exceptions.HTTPError()
        e.response = SoxtaJavob(kod)
        check(f"HTTP {kod} -> QAYTA URINILADI", ish.tasnifla(e).qayta_urinsa)

    # DOIMIY xatolar. Bu yerda regressiya eng qimmat: ilgari
    # `except Exception` 404 ni ham to'rt marta urinardi.
    for kod in (400, 401, 403, 404, 405, 409, 410, 422):
        e = requests.exceptions.HTTPError()
        e.response = SoxtaJavob(kod)
        check(f"HTTP {kod} -> QAYTA URINILMAYDI", not ish.tasnifla(e).qayta_urinsa)

    # MANBA JAVOBI XATO MATNIDA SAQLANADI (B-2, 2026-09-01).
    #
    # O'LCHANGAN: manba `ref_selection_public` uchun HTTP 400
    # qaytardi va butun `etl_coverage_test` yiqildi. Xato matni
    # FAQAT `HTTP 400 — doimiy` edi — SABAB haqida hech narsa yo'q.
    # Keyingi urinishda o'sha chaqiruv MUAMMOSIZ ishladi (149 ta
    # yozuv), ya'ni xato O'TKINCHI edi. Lekin buni isbotlash uchun
    # ham, sababni topish uchun ham DALIL QOLMAGANDI.
    e = requests.exceptions.HTTPError()
    e.response = SoxtaJavob(
        400, '{"error":{"code":-32602,"message":"Invalid params"}}')
    xabar = str(ish.tasnifla(e))
    check("doimiy xatoda manba javobi SAQLANADI",
          "Invalid params" in xabar, xabar)
    e2 = requests.exceptions.HTTPError()
    e2.response = SoxtaJavob(503, "<html>\n  <h1>502 Bad Gateway</h1>\n</html>")
    xabar2 = str(ish.tasnifla(e2))
    check("qayta uriniladigan xatoda ham javob saqlanadi",
          "Bad Gateway" in xabar2, xabar2)
    check("javob izi BITTA qatorda (jurnal buzilmasin)",
          "\n" not in xabar2, repr(xabar2))
    # Manba xato paytida BUTUN HTML sahifa qaytarishi kuzatilgan —
    # u jurnalni bosib ketmasin.
    e3 = requests.exceptions.HTTPError()
    e3.response = SoxtaJavob(400, "x" * 5000)
    check("javob izi QISQARTIRILADI",
          len(str(ish.tasnifla(e3))) < ish.JAVOB_IZI_MAX + 80,
          f"{len(str(ish.tasnifla(e3)))} belgi")
    # Tanasiz javob xato matnini BUZMASIN.
    e4 = requests.exceptions.HTTPError()
    e4.response = SoxtaJavob(404, "")
    check("bo'sh tanada ortiqcha ajratgich yo'q",
          "|" not in str(ish.tasnifla(e4)), str(ish.tasnifla(e4)))

    # Notanish xato DOIMIY deb qaraladi (oq ro'yxat siyosati).
    check("notanish istisno -> QAYTA URINILMAYDI",
          not ish.tasnifla(KeyError("maydon")).qayta_urinsa,
          "'balki o'zi tuzalar' degan taxmin qilinmaydi")

    # Buzuq JSON — o'tkinchi (manba xato paytida HTML sahifa qaytaradi).
    j = ish.javob_json.__wrapped__ if hasattr(ish.javob_json, "__wrapped__") else None
    try:
        ish.javob_json(SoxtaJavob(200, "<html>502 Bad Gateway</html>"))
        check("buzuq JSON -> ManbaXato", False, "istisno chiqmadi")
    except ish.ManbaXato as e:
        check("buzuq JSON -> QAYTA URINILADI", e.qayta_urinsa, str(e)[:70])

    # Retry-After hurmat qilinadi va CHEGARALANADI.
    e = requests.exceptions.HTTPError()
    e.response = SoxtaJavob(429, sarlavhalar={"Retry-After": "7"})
    check("429 Retry-After o'qildi", ish.tasnifla(e).kutish == 7.0,
          str(ish.tasnifla(e).kutish))
    e.response = SoxtaJavob(503, sarlavhalar={"Retry-After": "99999"})
    check("juda uzun Retry-After CHEGARALANDI",
          ish.tasnifla(e).kutish == 300.0,
          "soatlik jadval bitta 429 bilan to'xtab qolmasin")
    e.response = SoxtaJavob(503, sarlavhalar={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    check("sana shaklidagi Retry-After TAXMIN QILINMAYDI",
          ish.tasnifla(e).kutish is None,
          "server soati bilan farqni bilmaymiz -> siyosat bo'yicha kutamiz")


# =====================================================================
# 2) KUTISH: eksponensial + jitter + chegara
# =====================================================================
def test_kutish() -> None:
    section("Eksponensial kutish, jitter va chegara")

    s = ish.Siyosat(urinishlar=4, asos=1.0, koeff=2.0, max_kutish=60.0, jitter=0.0)
    kutishlar = [s.kutish(i) for i in (1, 2, 3, 4)]
    check("eksponensial: 1, 2, 4, 8", kutishlar == [1.0, 2.0, 4.0, 8.0], str(kutishlar))

    s2 = ish.Siyosat(asos=1.0, koeff=2.0, max_kutish=5.0, jitter=0.0)
    check("max_kutish chegarasi ishlaydi", s2.kutish(10) == 5.0, str(s2.kutish(10)))

    # JITTER: qiymatlar TARQOQ bo'lishi shart. Jittersiz ikki oqim
    # aynan bir vaqtda qayta urinib manbaga to'lqin bo'lib urilardi.
    sj = ish.Siyosat(asos=10.0, koeff=1.0, jitter=0.25)
    namuna = [sj.kutish(1) for _ in range(60)]
    check("jitter tarqatadi", len(set(namuna)) > 40, f"{len(set(namuna))} xil qiymat")
    check("jitter ±25% ichida",
          all(7.4 <= x <= 12.6 for x in namuna),
          f"min={min(namuna):.2f} max={max(namuna):.2f}")

    check("jitter=0 DETERMINISTIK (sinov uchun)",
          len({ish.Siyosat(jitter=0.0).kutish(2) for _ in range(20)}) == 1)

    # Retry-After siyosatdan USTUN.
    check("Retry-After siyosatdan ustun",
          ish.Siyosat(asos=1.0, jitter=0.0).kutish(1, tavsiya=9.0) == 9.0)


# =====================================================================
# 3) QAYTA URINISH AMALDA — timeout -> qayta urinish -> muvaffaqiyat
# =====================================================================
def test_qayta_urinish_amalda() -> None:
    section("Qayta urinish amalda")
    siyosat = ish.Siyosat(urinishlar=4, asos=0.01, koeff=2.0, jitter=0.0)

    # --- timeout -> qayta urinish -> MUVAFFAQIYAT ---
    urinish = {"n": 0}
    hisob = {"n": 0}

    def ikki_marta_yiqiladi():
        urinish["n"] += 1
        if urinish["n"] < 3:
            raise requests.exceptions.ReadTimeout("o'qish timeouti")
        return {"ok": True}

    natija = ish.qayta_urin(ikki_marta_yiqiladi, siyosat=siyosat,
                            uxla=lambda s: None,
                            hisob=lambda: hisob.__setitem__("n", hisob["n"] + 1))
    check("timeout -> qayta urinish -> MUVAFFAQIYAT", natija == {"ok": True})
    check("uchinchi urinishda o'tdi", urinish["n"] == 3, f"urinish={urinish['n']}")
    check("qayta urinishlar SANALDI", hisob["n"] == 2, f"hisob={hisob['n']}")

    # --- HTTP 500 -> qayta urinish ---
    n500 = {"n": 0}

    def bes_yuz():
        n500["n"] += 1
        if n500["n"] < 2:
            return ish.javob_json(SoxtaJavob(500, "server xatosi"))
        return ish.javob_json(SoxtaJavob(200, '{"natija": 1}'))

    check("HTTP 500 -> qayta urinildi va o'tdi",
          ish.qayta_urin(bes_yuz, siyosat=siyosat, uxla=lambda s: None)
          == {"natija": 1} and n500["n"] == 2, f"urinish={n500['n']}")

    # --- DOIMIY 4xx -> QAYTA URINILMAYDI ---
    n404 = {"n": 0}

    def tort_nol_tort():
        n404["n"] += 1
        return ish.javob_json(SoxtaJavob(404, "topilmadi"))

    try:
        ish.qayta_urin(tort_nol_tort, siyosat=siyosat, uxla=lambda s: None)
        check("404 -> istisno", False, "istisno chiqmadi")
    except ish.ManbaXato as e:
        check("404 -> DARHOL yiqildi, qayta urinilmadi",
              n404["n"] == 1 and not e.qayta_urinsa, f"urinish={n404['n']}")

    # --- urinishlar tugadi -> oxirgi xato ko'tariladi ---
    nhech = {"n": 0}

    def hech_qachon():
        nhech["n"] += 1
        raise requests.exceptions.ConnectionError("host o'lik")

    try:
        ish.qayta_urin(hech_qachon, siyosat=siyosat, uxla=lambda s: None)
        check("urinishlar tugadi -> istisno", False, "istisno chiqmadi")
    except ish.ManbaXato as e:
        check("MAKSIMAL urinishga rioya qilindi",
              nhech["n"] == siyosat.urinishlar, f"urinish={nhech['n']}")
        check("oxirgi xato matnda saqlandi", "host o'lik" in str(e), str(e)[:80])

    # --- OXIRGI urinishdan KEYIN kutilmaydi ---
    # Eski `rpc_call` da 4-urinish yiqilgach yana 16 sekund kutilardi.
    uyqular = []
    nk = {"n": 0}

    def har_doim_500():
        nk["n"] += 1
        raise requests.exceptions.ConnectionError("x")

    try:
        ish.qayta_urin(har_doim_500, siyosat=siyosat, uxla=uyqular.append)
    except ish.ManbaXato:
        pass
    check("oxirgi urinishdan KEYIN kutilmaydi",
          len(uyqular) == siyosat.urinishlar - 1,
          f"{len(uyqular)} ta kutish / {siyosat.urinishlar} urinish")

    # --- to'xtash so'rovi uzun kutishni BO'LADI ---
    t = ish.Toxtatgich()
    t.sora("sinov")
    uyqu2 = []
    try:
        ish.qayta_urin(hech_qachon, siyosat=ish.Siyosat(urinishlar=2, asos=60.0,
                                                        jitter=0.0),
                       uxla=uyqu2.append, toxtash=lambda: t.toxtaymi())
    except ish.ManbaXato:
        pass
    check("to'xtash so'ralganda 60s kutish BO'LINDI",
          sum(uyqu2) <= 0.5, f"jami kutish={sum(uyqu2)}s")


# =====================================================================
# 4) BITTA BUZUQ YOZUV BUTUN PAKETNI YIQITMAYDI
# =====================================================================
def test_buzuq_yozuv_izolyatsiyasi() -> None:
    section("Bitta buzuq yozuv qolganini to'xtatmaydi")

    # `etl_uzex.transform` ni buzuq tafsilot bilan chaqiramiz va
    # halqa mantiqini takrorlaymiz.
    import etl_uzex

    qatorlar = [
        {"id": 1, "name": "yaxshi-1"},
        {"id": 2, "name": "BUZUQ"},
        {"id": 3, "name": "yaxshi-2"},
        {"id": 4, "name": "BUZUQ-HTTP"},
        {"id": 5, "name": "yaxshi-3"},
    ]

    def soxta_get(qator):
        if qator["name"] == "BUZUQ":
            return "bu dict emas, satr"          # transform yiqiladi
        if qator["name"] == "BUZUQ-HTTP":
            raise ish.ManbaXato("HTTP 404 — doimiy", qayta_urinsa=False)
        return {"start_cost": 100, "budget_products": "[]"}

    ok = yiqildi = 0
    for q in qatorlar:
        try:
            d = soxta_get(q)
            etl_uzex.transform(q, d, 2)
        except ish.ManbaXato:
            yiqildi += 1
            continue
        except Exception:                                    # noqa: BLE001
            yiqildi += 1
            continue
        ok += 1

    check("3 ta yaxshi yozuv ISHLANDI", ok == 3, f"ok={ok}")
    check("2 ta buzuq yozuv AJRATILDI", yiqildi == 2, f"yiqildi={yiqildi}")
    check("buzuq yozuv halqani TO'XTATMADI", ok + yiqildi == len(qatorlar))


# =====================================================================
# 5) IDEMPOTENTLIK — qayta yurgizish dublikat yaratmaydi
# =====================================================================
def test_idempotentlik_strukturasi() -> None:
    section("Idempotentlik — struktura kafolatlari")

    src = io.open(os.path.join(ROOT, "etl_uzex.py"), encoding="utf-8").read()
    # Bo'shliqlar normallashtiriladi: kodda `DELETE FROM tender_lot  WHERE`
    # (ikki probel) turibdi va sinov FORMATLASHGA emas, QOIDAGA
    # bog'liq bo'lishi kerak.
    tekis = " ".join(src.split())
    check("tender UPSERT (ON CONFLICT DO UPDATE)",
          "ON CONFLICT (id) DO UPDATE" in tekis)
    check("tender_detail UPSERT", "ON CONFLICT (tender_id) DO UPDATE" in tekis)
    for jadval in ("tender_good", "tender_item", "tender_lot", "tender_document"):
        check(f"{jadval}: qayta yozishdan OLDIN DELETE",
              f"DELETE FROM {jadval} WHERE tender_id" in tekis)

    # PK ni buzadigan takror hujjat yo'li — o'lchangan nuqson sinfi.
    check("uzex: takror hujjat yo'li birlashtiriladi",
          'docs = {d["file_ref"]: d for d in rec["docs"]}' in src,
          "PK=(tender_id,file_ref); ikki maydon bir yo'lni ko'rsatishi mumkin")
    det = io.open(os.path.join(ROOT, "etl_details.py"), encoding="utf-8").read()
    check("details: takror hujjat havolasi birlashtiriladi",
          'uniq = {d["file_ref"]: d for d in docs}' in det)

    # Sahifalash takrori — `CardinalityViolation` manbai.
    check("uzex: sahifalash takrori olib tashlanadi",
          "takrorsiz[r.get(\"id\")] = r" in src)
    ten = io.open(os.path.join(ROOT, "etl_tenders.py"), encoding="utf-8").read()
    check("tenders: sahifalash takrori olib tashlanadi",
          "unique[r.get(\"id\")] = r" in ten)


def test_idempotentlik_bazada(conn) -> None:
    """HAQIQIY qayta yurgizish: bir xil yozuvni ikki marta saqlash."""
    section("Idempotentlik — bazada o'lchangan")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    import etl_uzex
    tid = etl_uzex.UZEX_OFFSET + 999_999_001
    qator = {"id": 999_999_001, "name": "[SINOV] idempotentlik",
             "start_date": "2026-08-30T00:00:00", "end_date": "2026-09-30T00:00:00",
             "cost": 1000.0, "currency_codeabc": "UZS", "seller_id": 1,
             "seller_name": "[SINOV]", "region_name": "Тошкент шаҳри"}
    tafsilot = {
        "start_cost": 1000.0,
        # ATAYLAB ikki maydon BIR XIL yo'lni ko'rsatadi — PK buzilishi
        # sinaladi (o'lchangan nuqson sinfi).
        "anno_path": "/files/sinov.pdf", "anno_name": "sinov.pdf", "anno_ext": "pdf",
        "proc_path": "/files/sinov.pdf", "proc_name": "sinov.pdf", "proc_ext": "pdf",
        "budget_products": json.dumps([
            {"Product_Code": "26.20.11", "Product_Name": "Sinov mahsuloti",
             "Amount": 2, "Price": 500, "Measure_Name": "dona"}]),
    }
    dsn = os.environ["XT_DB_DSN"]
    c2 = psycopg2.connect(dsn)
    try:
        sanoqlar = []
        for _ in range(3):                      # UCH marta — "qayta ishga tushirish"
            rec = etl_uzex.transform(qator, tafsilot, 2)
            etl_uzex.save(c2, rec)
            with c2.cursor() as cur:
                cur.execute(
                    "SELECT (SELECT count(*) FROM tender WHERE id=%s), "
                    "       (SELECT count(*) FROM tender_lot WHERE tender_id=%s), "
                    "       (SELECT count(*) FROM tender_good WHERE tender_id=%s), "
                    "       (SELECT count(*) FROM tender_item WHERE tender_id=%s), "
                    "       (SELECT count(*) FROM tender_document WHERE tender_id=%s)",
                    (tid, tid, tid, tid, tid))
                sanoqlar.append(cur.fetchone())
            c2.commit()

        check("3 marta saqlashda tender DUBLIKAT bo'lmadi",
              all(s[0] == 1 for s in sanoqlar), str([s[0] for s in sanoqlar]))
        check("lot dublikat bo'lmadi", all(s[1] == 1 for s in sanoqlar),
              str([s[1] for s in sanoqlar]))
        check("tovar dublikat bo'lmadi", len({s[2] for s in sanoqlar}) == 1,
              str([s[2] for s in sanoqlar]))
        check("pozitsiya dublikat bo'lmadi", len({s[3] for s in sanoqlar}) == 1,
              str([s[3] for s in sanoqlar]))
        check("hujjat dublikat bo'lmadi va PK buzilmadi",
              all(s[4] == 1 for s in sanoqlar),
              f"{[s[4] for s in sanoqlar]} — ikki maydon bir yo'lni ko'rsatgan")
    finally:
        with c2.cursor() as cur:
            for j in ("tender_document", "tender_item", "tender_good",
                      "tender_lot", "tender_detail"):
                cur.execute(f"DELETE FROM {j} WHERE tender_id=%s", (tid,))
            cur.execute("DELETE FROM tender WHERE id=%s", (tid,))
        c2.commit()
        c2.close()


# =====================================================================
# 6) CHECKPOINT — uzilish -> tiklash
# =====================================================================
def test_checkpoint(conn) -> None:
    section("Checkpoint: uzilgan yurish noldan boshlamaydi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    y = ish.BazaYozuvchi()
    oqim = "sinov:uzilish"
    kp = ish.Checkpoint(y, "_sinov", oqim)
    try:
        conn.cursor().execute(
            "DELETE FROM etl_checkpoint WHERE source_platform='_sinov'")

        kalit = ish.ish_kaliti([10, 20, 30, 40, 50])
        check("yangi oqim 0 dan boshlanadi", kp.boshla(5, kalit) == 0)

        # 3 ta yozuv ishlandi, keyin "o'ldirildi".
        kp.siljit(3, oxirgi_id=30, majburan=True)

        kp2 = ish.Checkpoint(y, "_sinov", oqim)
        check("UZILGAN yurish 3 dan DAVOM etadi", kp2.boshla(5, kalit) == 3,
              "noldan boshlanmasin")
        check("oxirgi muvaffaqiyatli ID saqlandi",
              kp2.yukla().oxirgi_id == 30, str(kp2.yukla().oxirgi_id))

        # RO'YXAT O'ZGARSA kursor YAROQSIZ — bu ATAYLAB qattiq.
        boshqa = ish.ish_kaliti([99, 10, 20, 30, 40, 50])
        kp3 = ish.Checkpoint(y, "_sinov", oqim)
        check("ro'yxat o'zgarsa kursor E'TIBORGA OLINMAYDI",
              kp3.boshla(6, boshqa) == 0,
              "indeks siljishi o'rtadagi yozuvni jimgina tashlab ketardi")

        # Tugagach kursor nolga qaytadi.
        kp3.siljit(6, oxirgi_id=50, majburan=True)
        kp3.tugat()
        h = ish.Checkpoint(y, "_sinov", oqim).yukla()
        check("tugagan oqim: holat='tugadi'", h.holat == "tugadi", h.holat)
        check("tugagan oqim: kursor=0", h.kursor == 0, str(h.kursor))

        # `tugadi` holatidan keyin qayta boshlansa 0 dan.
        kp4 = ish.Checkpoint(y, "_sinov", oqim)
        check("tugagan oqim qayta 0 dan boshlanadi",
              kp4.boshla(6, boshqa) == 0)
    finally:
        conn.cursor().execute(
            "DELETE FROM etl_checkpoint WHERE source_platform='_sinov'")
        y.yop()


def test_backoff_oynasi(conn) -> None:
    section("Manba backoff oynasi (429/503 dan keyin tegilmaydi)")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return
    y = ish.BazaYozuvchi()
    kp = ish.Checkpoint(y, "_sinov", "sinov:backoff")
    try:
        conn.cursor().execute(
            "DELETE FROM etl_checkpoint WHERE source_platform='_sinov'")
        kp.boshla(10, ish.ish_kaliti([1]))
        band, _ = kp.band_mi()
        check("xatosiz oqim BAND emas", not band)

        kp.xato_yoz("HTTP 503", 120.0)
        band, nega = kp.band_mi()
        check("503 dan keyin oqim BAND", band, str(nega))
        check("urinish sanaldi", kp.yukla().urinish == 1, str(kp.yukla().urinish))

        # `tugat()` kutish oynasini tozalaydi (CHECK shuni talab qiladi).
        kp.tugat()
        band2, _ = kp.band_mi()
        check("tugagach BAND emas", not band2)
    finally:
        conn.cursor().execute(
            "DELETE FROM etl_checkpoint WHERE source_platform='_sinov'")
        y.yop()


def test_checkpoint_qulflari(conn) -> None:
    """Qoidalar CHECK bilan qulflanganmi — IZOH bilan emas.

    Loyihada o'lchangan saboq: `tender_requirement` da 1 487 qator
    `review_status='approved'` bo'lib turibdi va ularni hech kim
    ko'rmagan — o'sha qoida faqat izoh bilan himoyalangan edi.
    """
    section("Baza qulflari (CHECK) — izoh yetarli emas")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    rad_etilishi_kerak = [
        ("notanish holat",
         "INSERT INTO etl_checkpoint (source_platform, oqim, holat) "
         "VALUES ('_sinov','q1','allaqachon')"),
        ("manfiy kursor",
         "INSERT INTO etl_checkpoint (source_platform, oqim, kursor) "
         "VALUES ('_sinov','q2',-1)"),
        ("urinishsiz kutish vaqti",
         "INSERT INTO etl_checkpoint (source_platform, oqim, urinish, "
         "keyingi_urinish_at) VALUES ('_sinov','q3',0, now())"),
        ("'tugadi' + ochiq kutish vaqti",
         "INSERT INTO etl_checkpoint (source_platform, oqim, holat, urinish, "
         "keyingi_urinish_at) VALUES ('_sinov','q4','tugadi',1, now())"),
        ("etl_run: notanish status",
         "INSERT INTO etl_run (source_platform, status) VALUES ('_sinov','yaxshi')"),
        ("etl_run: manfiy sanoq",
         "INSERT INTO etl_run (source_platform, status, failed) "
         "VALUES ('_sinov','ok',-5)"),
    ]
    try:
        for nom, sql in rad_etilishi_kerak:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                check(f"BAZA RAD ETDI: {nom}", False, "qabul qilindi!")
            except psycopg2.Error:
                check(f"BAZA RAD ETDI: {nom}", True)

        # 'partial' — QABUL QILINISHI shart.
        with conn.cursor() as cur:
            cur.execute("INSERT INTO etl_run (source_platform, status) "
                        "VALUES ('_sinov','partial') RETURNING id")
            rid = cur.fetchone()[0]
        check("'partial' statusi QABUL qilindi", True, f"id={rid}")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etl_run WHERE id=%s", (rid,))
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etl_checkpoint WHERE source_platform='_sinov'")
            cur.execute("DELETE FROM etl_run WHERE source_platform='_sinov'")


# =====================================================================
# 7) YETIM YURISH — heartbeat bilan HALOL yopish
# =====================================================================
def test_yetim_yurish(conn) -> None:
    section("Yetim 'running' qatori: tiklash va HALOL davomiylik")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    import run_etl
    run_etl._ENV_YUKLANDI = True
    try:
        with conn.cursor() as cur:
            # A) 3 daqiqa ishlab, keyin o'ldirilgan yurish.
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  heartbeat_at, processed, succeeded) "
                "VALUES ('_sinov','running', now() - interval '10 hours', "
                "        now() - interval '9 hours 57 minutes', 42, 40) "
                "RETURNING id")
            a = cur.fetchone()[0]
            # B) Heartbeat umuman yozilmagan (darhol o'lgan).
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at) "
                "VALUES ('_sinov','running', now() - interval '10 hours') "
                "RETURNING id")
            b = cur.fetchone()[0]
            # C) YANGI yurish — tegilmasin.
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at) "
                "VALUES ('_sinov','running', now()) RETURNING id")
            c = cur.fetchone()[0]
            # D) Bola qadamni TUGATGAN, lekin ota-jarayon o'ldirilgan.
            #    Jonli kuzatilgan holat (2026-08-30, run 441).
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  heartbeat_at, terminal_reason) "
                "VALUES ('_sinov','running', now() - interval '10 hours', "
                "        now() - interval '9 hours 55 minutes', 'tugadi') "
                "RETURNING id")
            d = cur.fetchone()[0]
            # E) UZOQ BOSHLANGAN, LEKIN TIRIK — yurak urib turibdi.
            #
            # O'LCHANGAN NUQSON (2026-09-03): shart `started_at < now() - N`
            # edi, ya'ni "qachon BOSHLANGAN". `v_etl_osilgan` va
            # `v_ops_holat` esa "qachondan beri JIM" deb hisoblaydi —
            # bitta tizimda "osilgan" ning IKKI TA'RIFI bor edi.
            # Byudjeti kattaroq (`ETL_MAX_SECONDS=2400+`) TIRIK yurish
            # shu yerda `error` deb yopilardi, ko'rinishda esa sog'lom
            # ko'rinardi: YOZUV YOLG'ON, jarayon esa yurishda davom
            # etardi. Bu qator o'sha ziddiyatni qulflaydi.
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  heartbeat_at, processed) "
                "VALUES ('_sinov','running', now() - interval '5 hours', "
                "        now() - interval '1 minute', 900) "
                "RETURNING id")
            e = cur.fetchone()[0]

        yopildi = run_etl.close_stale_runs(2.0)
        check("yetim qatorlar yopildi", yopildi >= 3, f"{yopildi} ta")

        with conn.cursor() as cur:
            cur.execute("SELECT id, status, terminal_reason, davomiylik_sek, xato "
                        "FROM v_etl_run_olchov WHERE id = ANY(%s) ORDER BY id",
                        ([a, b, c, d, e],))
            r = {x[0]: x for x in cur.fetchall()}

        # ZIDDIYATLI O'QILISH BO'LMASIN: yurish uzilgan bo'lsa
        # `terminal_reason` 'uzildi' bo'ladi, bola nima yozgan bo'lsa ham.
        check("bola 'tugadi' yozgan bo'lsa ham YURISH 'uzildi'",
              r[d][2] == "uzildi", str(r[d][2]))
        check("bolaning oxirgi holati YO'QOLMADI (xato matnida)",
              "tugadi" in (r[d][4] or ""), (r[d][4] or "")[-80:])
        check("bola tugatgan yurishning davomiyligi ham HALOL",
              r[d][3] is not None and 290 <= float(r[d][3]) <= 310,
              f"{r[d][3]}s (5 daqiqa, 10 soat emas)")

        check("uzilgan yurish 'error' deb yopildi", r[a][1] == "error", str(r[a]))
        check("tugash sababi 'uzildi'", r[a][2] == "uzildi", str(r[a][2]))
        # ENG MUHIM TEKSHIRUV. Ilgari `finished_at = now()` edi va bu
        # yurish 10 SOAT davom etgan bo'lib ko'rinardi.
        check("davomiylik HEARTBEAT gacha (10 soat EMAS, ~3 daqiqa)",
              r[a][3] is not None and 170 <= float(r[a][3]) <= 190,
              f"{r[a][3]}s — 'qachon to'xtadi', 'qachon payqadik' emas")
        check("heartbeat yo'q -> davomiylik NULL (nol EMAS)",
              r[b][3] is None,
              "o'lchanmagan narsa nolga aylantirilmaydi")
        check("YANGI yurishga tegilmadi", r[c][1] == "running", str(r[c][1]))
        # TIRIK YURISH O'LDIRILMAYDI — "osilgan" HEARTBEAT bilan
        # o'lchanadi, boshlanish vaqti bilan emas. Ta'rif
        # `v_etl_osilgan` dagi bilan AYNAN bir xil bo'lishi shart.
        check("5 soat yurgan, LEKIN TIRIK yurish yopilmadi",
              r[e][1] == "running",
              f"{r[e][1]} — yurak 1 daqiqa oldin urgan edi")
        # -------------------------------------------------------------
        # DARVOZA: HOST va MANBA ajratiladimi (0074)
        # -------------------------------------------------------------
        # O'LCHANGAN MUAMMO (2026-09-03): `v_etl_saglik` da faqat
        # `uzildi` ustuni bor edi. "Biz aybdormiz" (host o'ldirdi) va
        # "manba yiqildi" BIR `xato` ustunida yig'ilardi, holbuki SRE
        # qarori ikkisida BUTUNLAY BOSHQA. Va `terminal_reason`
        # 2026-08-30 gacha yozilmagani uchun 12 ta HAQIQIY host
        # uzilishi tasnifsiz qolardi — host ulushi PAST ko'rinardi.
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etl_run WHERE source_platform='_darvoza'")
            # a) yangi uslub: terminal_reason yozilgan
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  finished_at, heartbeat_at, terminal_reason, error) "
                "VALUES ('_darvoza','error', now()-interval '1 hour', "
                "        now()-interval '59 minutes', now()-interval '59 minutes',"
                "        'uzildi', 'yurish tugamasdan uzildi ...')")
            # b) ESKI uslub: terminal_reason YO'Q, faqat matn
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  finished_at, heartbeat_at, error) "
                "VALUES ('_darvoza','error', now()-interval '2 hours', "
                "        now()-interval '119 minutes', now()-interval '119 minutes',"
                "        'yurish tugamasdan uzildi (kompyuter uxlagan)')")
            # c) MANBA xatosi — host aybdor EMAS
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  finished_at, heartbeat_at, terminal_reason, error) "
                "VALUES ('_darvoza','error', now()-interval '3 hours', "
                "        now()-interval '179 minutes', now()-interval '179 minutes',"
                "        'manba_xato', 'HTTP 503 manba javob bermadi')")
            # d) sog'lom yurish
            cur.execute(
                "INSERT INTO etl_run (source_platform, status, started_at, "
                "  finished_at, heartbeat_at, terminal_reason) "
                "VALUES ('_darvoza','ok', now()-interval '4 hours', "
                "        now()-interval '4 hours' + interval '30 seconds', "
                "        now()-interval '4 hours' + interval '30 seconds', 'tugadi')")

            cur.execute(
                "SELECT yurish, ok, xato, host_uzildi, manba_xato, "
                "       tasniflanmagan, foydali_foiz, ort_sek_ok, darvoza "
                "  FROM v_etl_saglik WHERE source_platform='_darvoza'")
            g = cur.fetchone()

        check("darvoza: eski VA yangi uslubdagi uzilish HOST deb sanaldi",
              g[3] == 2, f"host_uzildi={g[3]}, kutilgan 2")
        check("darvoza: manba xatosi HOST ga QO'SHILMADI",
              g[4] == 1 and g[3] == 2, f"manba={g[4]} host={g[3]}")
        # QOLDIQSIZ TOIFALASH — yig'indi jamiga teng.
        check("darvoza: xato == host + manba + tasniflanmagan",
              g[2] == g[3] + g[4] + g[5],
              f"{g[2]} != {g[3]}+{g[4]}+{g[5]}")
        check("darvoza: tasniflanmagan ustuni BOR va u nolga aylantirilmaydi",
              g[5] == 0, str(g[5]))
        # `ort_sek_ok` FAQAT sog'lom yurishlarni oladi. Aks holda
        # uzilgan yurishning soatlari o'rtachani shishirardi va
        # "ETL sekin" degan YOLG'ON xulosa chiqardi.
        check("darvoza: ort_sek_ok faqat SOG'LOM yurishdan (30s)",
              g[7] is not None and 25 <= float(g[7]) <= 35,
              f"{g[7]}s — uzilganlar qo'shilsa soatlar chiqardi")
        check("darvoza: host uzilishi bo'lsa hukm 'host_uziladi'",
              g[8] == "host_uziladi", str(g[8]))
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etl_run WHERE source_platform='_sinov'")
            cur.execute("DELETE FROM etl_run WHERE source_platform='_darvoza'")


# =====================================================================
# 8) USTMA-UST YURISH — baza maslahat qulfi
# =====================================================================
def test_ustma_ust(conn) -> None:
    section("Ustma-ust yurish to'siladi (vazifa chegarasidan o'tuvchi qulf)")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    q1 = ish.Qulf("sinov:ustma-ust")
    q2 = ish.Qulf("sinov:ustma-ust")
    try:
        check("birinchi yurish qulfni OLDI", q1.ol())
        check("ikkinchi yurish qulfni OLMADI", not q2.ol(),
              "IgnoreNew faqat bitta vazifa ichida ishlaydi — bu undan kengroq")
        q1.qoyver()
        q3 = ish.Qulf("sinov:ustma-ust")
        check("qo'yib yuborilgach qulf yana OLINADI", q3.ol())
        q3.qoyver()

        # Boshqa nom — bloklamaydi (platformalar PARALLEL yurishi kerak).
        a = ish.Qulf("sinov:xt-xarid")
        b = ish.Qulf("sinov:uzex")
        check("TURLI platformalar bir-birini bloklamaydi",
              a.ol() and b.ol(),
              "guruhlar o'zaro parallel — bu qoida saqlanadi")
        a.qoyver(); b.qoyver()
    finally:
        for q in (q1, q2):
            q.qoyver()


def test_qulf_uzilganda_bosaydi(conn) -> None:
    """Jarayon o'lsa qulf QOLIB KETMAYDI.

    Fayl qulfida bu kafolat YO'Q — aynan shuning uchun baza qulfi
    tanlangan. Boshqa jarayonni o'ldirib tekshiramiz.
    """
    section("Jarayon o'ldirilsa qulf o'zi bo'shaydi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    kod = (
        "import sys, time\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "from dotenv import load_dotenv\n"
        f"load_dotenv(r'{os.path.join(ROOT, '.env')}')\n"
        "import etl_ishonch as ish\n"
        "q = ish.Qulf('sinov:oldirish')\n"
        "print('OLINDI' if q.ol() else 'OLINMADI', flush=True)\n"
        "time.sleep(60)\n"
    )
    yol = os.path.join(ROOT, "_tests", "fixtures", "_qulf_ushlagich.py")
    io.open(yol, "w", encoding="utf-8").write(kod)
    p = None
    try:
        p = subprocess.Popen([sys.executable, yol], stdout=subprocess.PIPE,
                             text=True, encoding="utf-8", cwd=ROOT)
        birinchi = p.stdout.readline().strip()
        check("bola jarayon qulfni oldi", birinchi == "OLINDI", birinchi)

        band = ish.Qulf("sinov:oldirish")
        check("biz qulfni OLA OLMAYMIZ", not band.ol())
        band.qoyver()

        p.kill()                              # taskkill /F ga teng
        p.wait(timeout=10)
        # PostgreSQL seans qulfini seans tugashi bilan bo'shatadi.
        bosh = None
        for _ in range(50):
            bosh = ish.Qulf("sinov:oldirish")
            if bosh.ol():
                break
            bosh.qoyver()
            time.sleep(0.1)
        check("jarayon O'LDIRILGACH qulf BO'SHADI", bool(bosh and bosh.olindi),
              "fayl qulfida bu kafolat yo'q")
        if bosh:
            bosh.qoyver()
    finally:
        if p and p.poll() is None:
            p.kill()
        if os.path.exists(yol):
            os.remove(yol)


# =====================================================================
# 9) UCHIDAN-UCHIGA: uzilgan yurish -> tiklash (haqiqiy skript)
# =====================================================================
def test_uzilish_va_tiklash_ete(conn) -> None:
    """HAQIQIY `etl_uzex.py` ni vaqt byudjeti bilan uzamiz va tiklaymiz.

    Bu sinovda soxta manba YO'Q: skript haqiqiy oqim bilan yuradi,
    lekin ish ro'yxati sun'iy ravishda checkpoint orqali beriladi.
    """
    section("Uchidan-uchiga: byudjet bilan uzilish -> keyingi yurish davom etadi")
    if conn is None:
        check("baza kerak", False, "o'tkazib yuborildi")
        return

    py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    with conn.cursor() as cur:
        cur.execute("INSERT INTO etl_run (source_platform, status) "
                    "VALUES ('_sinov','running') RETURNING id")
        rid = cur.fetchone()[0]
    env["ETL_RUN_ID"] = str(rid)

    try:
        # 1) `--full` bilan inkrementalni o'chiramiz (ish bo'lsin) va
        #    byudjetni juda kichik qo'yamiz -> QISMAN tugashi shart.
        r1 = subprocess.run(
            [py, "etl_uzex.py", "--type-id", "2", "--limit", "12", "--full",
             "--max-seconds", "3"],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300)
        chiqish1 = (r1.stdout or "") + (r1.stderr or "")
        check("kichik byudjet -> QISMAN chiqish kodi (7)",
              r1.returncode == 7, f"kod={r1.returncode}")
        check("to'xtash sababi 'vaqt_byudjeti'",
              "vaqt_byudjeti" in chiqish1.lower(), chiqish1[-160:].replace("\n", " "))

        with conn.cursor() as cur:
            cur.execute("SELECT kursor, jami, holat FROM etl_checkpoint "
                        "WHERE source_platform='uzex' AND oqim='type=2'")
            kp1 = cur.fetchone()
        check("checkpoint YOZILDI va kursor > 0",
              kp1 is not None and kp1[0] > 0 and kp1[2] == "ochiq", str(kp1))

        with conn.cursor() as cur:
            cur.execute("SELECT processed, succeeded, terminal_reason "
                        "FROM etl_run WHERE id=%s", (rid,))
            m1 = cur.fetchone()
        check("metrika BAZAGA yozildi (chiqishga emas)",
              m1[0] > 0 and m1[1] > 0, str(m1))
        check("terminal_reason yozildi", m1[2] == "vaqt_byudjeti", str(m1[2]))

        # 2) Yetarli byudjet bilan qayta yurgizamiz -> DAVOM etishi shart.
        r2 = subprocess.run(
            [py, "etl_uzex.py", "--type-id", "2", "--limit", "12", "--full",
             "--max-seconds", "180"],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=400)
        chiqish2 = (r2.stdout or "") + (r2.stderr or "")
        check("ikkinchi yurish TO'LIQ tugadi (kod 0)",
              r2.returncode == 0, f"kod={r2.returncode}\n{chiqish2[-300:]}")
        check("CHECKPOINT dan davom etdi (noldan boshlamadi)",
              "CHECKPOINT:" in chiqish2 and "dan davom etamiz" in chiqish2,
              chiqish2[:400].replace("\n", " ")[:200])

        with conn.cursor() as cur:
            cur.execute("SELECT holat, kursor FROM etl_checkpoint "
                        "WHERE source_platform='uzex' AND oqim='type=2'")
            kp2 = cur.fetchone()
        check("tugagach checkpoint holati 'tugadi'",
              kp2 is not None and kp2[0] == "tugadi" and kp2[1] == 0, str(kp2))

        with conn.cursor() as cur:
            cur.execute("SELECT resumed FROM etl_run WHERE id=%s", (rid,))
            check("`resumed` metrikasi yozildi", (cur.fetchone() or [0])[0] > 0)

        # 3) DUBLIKAT YO'Q: uzilib qayta yurgan tenderlar bir nusxada.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ("
                "  SELECT tender_id, lot_id, good_code FROM tender_good"
                "  WHERE tender_id IN (SELECT id FROM tender"
                "                      WHERE source_platform='uzex')"
                "  GROUP BY 1,2,3 HAVING count(*) > 1) d")
            dub = cur.fetchone()[0]
        check("qayta yurgizishdan keyin tovar DUBLIKATI yo'q", dub == 0, str(dub))
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM etl_run WHERE id=%s", (rid,))


# =====================================================================
# 10) HTTP MIJOZ AUDITI
# =====================================================================
def test_http_audit() -> None:
    section("HTTP mijoz: pool, keep-alive, ajratilgan timeoutlar")

    s = ish.sessiya_yarat(pool=4)
    adapter = s.get_adapter("https://example.invalid")
    check("ulanish pooli sozlangan",
          getattr(adapter, "_pool_maxsize", 0) == 4,
          str(getattr(adapter, "_pool_maxsize", None)))
    check("urllib3 ning O'Z retry'si O'CHIQ",
          adapter.max_retries.total == 0,
          "ikki qavat qayta urinish 4x3=12 urinish berardi")
    s.close()

    import etl_uzex, etl_tenders, etl_details
    for nom, mod in (("uzex", etl_uzex), ("tenders", etl_tenders),
                     ("details", etl_details)):
        t = mod.TIMEOUT
        check(f"{nom}: timeout AJRATILGAN (ulanish, o'qish)",
              isinstance(t, tuple) and len(t) == 2 and t[0] < t[1], str(t))

    src = io.open(os.path.join(ROOT, "etl_uzex.py"), encoding="utf-8").read()
    check("uzex: modul darajasidagi requests.post/get YO'Q",
          "requests.post(f\"{API}" not in src and "requests.get(f\"{API}" not in src,
          "har so'rovga yangi TLS qo'l berish edi (623 ta ortiqcha)")
    check("uzex: bitta seans qayta ishlatiladi", "def sessiya()" in src)


# =====================================================================
# 11) TO'XTATGICH — vaqt byudjeti va signal
# =====================================================================
def test_toxtatgich() -> None:
    section("To'xtatgich: vaqt byudjeti va to'xtash so'rovi")

    t = ish.Toxtatgich(byudjet_sek=0.15)
    check("boshida to'xtash so'ralmagan", not t.toxtaymi())
    time.sleep(0.2)
    check("byudjet tugagach to'xtash so'raladi", t.toxtaymi())
    check("sabab 'vaqt_byudjeti'", t.sabab == "vaqt_byudjeti", str(t.sabab))
    check("qolgan vaqt manfiy emas", (t.qolgan() or 0) >= 0)

    t2 = ish.Toxtatgich()
    check("byudjetsiz to'xtatgich o'zi to'xtamaydi", not t2.toxtaymi())
    t2.sora("foydalanuvchi")
    check("qo'lda so'rov qabul qilindi", t2.toxtaymi() and t2.sabab == "foydalanuvchi")
    t2.sora("boshqa")
    check("BIRINCHI sabab saqlanadi", t2.sabab == "foydalanuvchi",
          "keyingi so'rov birinchisini bosib ketmasin")


# =====================================================================
# 12) INKREMENTAL — o'zgarmagan yozuvga tegilmaydi
# =====================================================================
def test_inkremental() -> None:
    section("Inkremental: o'zgarmagan savdo qayta olinmaydi")

    import etl_uzex
    m = etl_uzex.KUZATILADIGAN
    eski = {"name": "A", "start_date": "2026-01-01", "end_date": "2026-02-01",
            "cost": 100.0, "seller_id": 5, "region_name": "Тошкент",
            "clarific_date": "2026-02-01"}

    check("bir xil qator -> O'ZGARMAGAN", not ish.ozgardimi(eski, dict(eski), m))
    check("bizda yo'q -> YANGI", ish.ozgardimi(None, eski, m))
    check("bo'sh saqlangan -> YANGI", ish.ozgardimi({}, eski, m))
    for maydon in m:
        yangi = dict(eski); yangi[maydon] = "BOSHQA"
        check(f"'{maydon}' o'zgardi -> QAYTA OLINADI",
              ish.ozgardimi(eski, yangi, m))

    # Son turi o'zgarishi MAZMUNSIZ farq — qayta olishga sabab emas.
    check("100 va 100.0 farq EMAS",
          not ish.ozgardimi({"cost": 100}, {"cost": 100.0}, ("cost",)),
          "JSON dan int/float aralash keladi")

    # Buzuq `raw_json` o'zini tuzatadi.
    check("buzuq raw_json -> bo'sh dict", ish.json_yukla("{buzuq") == {})
    check("buzuq raw_json -> yozuv QAYTA OLINADI",
          ish.ozgardimi(ish.json_yukla("{buzuq").get("list"), eski, m),
          "buzilish o'z-o'zini tuzatadi")

    # Ish kaliti barqaror va tartibga sezgir.
    check("ish kaliti BARQAROR",
          ish.ish_kaliti([1, 2, 3]) == ish.ish_kaliti([1, 2, 3]))
    check("ish kaliti TARTIBGA sezgir",
          ish.ish_kaliti([1, 2, 3]) != ish.ish_kaliti([3, 2, 1]),
          "ro'yxat qayta tartiblansa kursor yaroqsiz bo'lishi kerak")
    check("ish kaliti '12'+'3' va '1'+'23' ni AJRATADI",
          ish.ish_kaliti([12, 3]) != ish.ish_kaliti([1, 23]))


# =====================================================================
# 13) ORKESTRATOR — chiqish kodlari va status xaritasi
# =====================================================================
def test_orkestrator_kodlari() -> None:
    section("Orkestrator: chiqish kodi -> etl_run.status")

    import run_etl
    check("QISMAN kodi xatoga aylanmaydi",
          run_etl.KOD_QISMAN in run_etl._KOD_MANOSI)
    check("BAND kodi xatoga aylanmaydi",
          run_etl.KOD_BAND in run_etl._KOD_MANOSI)
    check("QISMAN -> 'partial' statusi",
          run_etl._KOD_MANOSI[run_etl.KOD_QISMAN][0] == "partial")
    check("noma'lum kod -> XATO",
          1 not in run_etl._KOD_MANOSI and 3221225786 not in run_etl._KOD_MANOSI)

    # Skriptlar KELISHILGAN kodlarni ishlatadimi.
    import etl_uzex, etl_tenders, etl_details
    for nom, mod in (("uzex", etl_uzex), ("tenders", etl_tenders),
                     ("details", etl_details)):
        check(f"{nom}: QISMAN kodi orkestrator bilan MOS",
              mod.CHIQISH_QISMAN == run_etl.KOD_QISMAN)
        check(f"{nom}: BAND kodi orkestrator bilan MOS",
              mod.CHIQISH_BAND == run_etl.KOD_BAND)


def test_orkestrator_soxta_bola() -> None:
    """Soxta bola bilan: har chiqish kodi to'g'ri o'qiladimi."""
    section("Orkestrator: soxta bola bilan chiqish kodlari")

    import run_etl
    fix = os.path.join(ROOT, "_tests", "fixtures")
    os.makedirs(fix, exist_ok=True)
    bola = os.path.join(fix, "_kod_bola.py")
    try:
        for kod, kutilgan_ok, kutilgan_belgi in (
                (0, True, "OK"), (7, True, "QISMAN"), (8, True, "BAND"),
                (1, False, "XATO")):
            io.open(bola, "w", encoding="utf-8").write(
                f"import sys\nprint('soxta bola')\nsys.exit({kod})\n")
            run_etl._UZILDI = False
            ok, _err, _dt, out, qaytgan = run_etl.run_script(
                os.path.join("_tests", "fixtures", "_kod_bola.py"), [])
            check(f"chiqish {kod}: ok={kutilgan_ok}", ok == kutilgan_ok,
                  f"ok={ok}")
            check(f"chiqish {kod}: kod qaytdi", qaytgan == kod, str(qaytgan))
            check(f"chiqish {kod}: jurnalda '{kutilgan_belgi}'",
                  any(f"[{kutilgan_belgi}]" in ln for ln in out),
                  str(out[-1]))

        # ETL_RUN_ID bolaga YETIB BORADIMI.
        io.open(bola, "w", encoding="utf-8").write(
            "import os, sys\nprint('RUN_ID=' + str(os.environ.get('ETL_RUN_ID')))\n"
            "sys.exit(0)\n")
        _ok, _e, _d, out, _k = run_etl.run_script(
            os.path.join("_tests", "fixtures", "_kod_bola.py"), [], run_id=4242)
        check("ETL_RUN_ID bolaga uzatildi",
              any("RUN_ID=4242" in ln for ln in out), str(out))
    finally:
        run_etl._UZILDI = False
        if os.path.exists(bola):
            os.remove(bola)


# =====================================================================
# 14) CHIQISH KODLASHI — chop etish ETLni o'ldirmasin
# =====================================================================
def test_chiqish_kodlashi() -> None:
    section("Kirill matn chop etish ETLni o'ldirmaydi")

    fix = os.path.join(ROOT, "_tests", "fixtures")
    os.makedirs(fix, exist_ok=True)
    yol = os.path.join(fix, "_kirill_chop.py")
    io.open(yol, "w", encoding="utf-8").write(
        "import sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import etl_ishonch as ish\n"
        "ish.chiqishni_sozla()\n"
        "print('Умумтаълим мактабларини жиҳозлаш')\n"
        "sys.exit(0)\n")
    try:
        # cp1251 konsolini TAQLID qilamiz — aynan shu holat
        # `_tests/import_test.py` ni to'liq ishlamas qilgan.
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        env["PYTHONLEGACYWINDOWSSTDIO"] = "1"
        r = subprocess.run([sys.executable, yol], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=env, cwd=ROOT, timeout=60)
        check("kirill chop etishda YIQILMADI", r.returncode == 0,
              f"kod={r.returncode}: {(r.stderr or '')[-160:]}")
        check("UnicodeEncodeError chiqmadi",
              "UnicodeEncodeError" not in (r.stderr or ""), (r.stderr or "")[-160:])
    finally:
        if os.path.exists(yol):
            os.remove(yol)


# =====================================================================
# 15) REJALASHTIRUVCHI SOZLAMALARI
# =====================================================================
def test_rejalashtiruvchi() -> None:
    section("register_task.ps1 — Windows vazifa sozlamalari")

    yol = os.path.join(ROOT, "register_task.ps1")
    src = io.open(yol, encoding="utf-8", errors="replace").read()

    # Fayl ASCII bo'lishi SHART: PowerShell 5.1 BOM'siz .ps1 ni ANSI
    # deb o'qiydi va ASCII bo'lmagan belgi qatorni buzadi (bu sinov
    # yozilayotganda AYNAN shu sodir bo'ldi — kirill matn qo'yilib
    # skript parser xatosi bergan).
    xom = io.open(yol, "rb").read()
    check("register_task.ps1 FAQAT ASCII", all(b < 128 for b in xom),
          "PowerShell 5.1 BOM'siz faylni ANSI deb o'qiydi")

    kerak = {
        "-DontStopOnIdleEnd":
            "bo'sh turish tugaganda yurish o'ldirilmasin (standart True edi)",
        "-StartWhenAvailable":
            "o'tkazib yuborilgan yurish mashina uyg'onishi bilan bajarilsin",
        "-AllowStartIfOnBatteries":
            "batareyada ham boshlansin",
        "-DontStopIfGoingOnBatteries":
            "rozetkadan uzilganda o'lmasin",
        "-MultipleInstances IgnoreNew":
            "bitta vazifa ichida ustma-ust yurish bo'lmasin",
        "-Priority 5":
            "standart 7 (past) Modern Standby'da birinchi bo'lib to'xtatiladi",
        "--max-seconds":
            "skript o'zi to'xtasin, Windows o'ldirmasin",
    }
    for bayroq, nega in kerak.items():
        check(f"sozlama bor: {bayroq}", bayroq in src, nega)

    check("ExecutionTimeLimit 2 SOAT EMAS",
          "-ExecutionTimeLimit $timeLimit" in src and "-Hours 2" not in src,
          "2 soat + 1 soatlik interval = osilgan yurish keyingi ikkitasini to'sardi")
    check("ETL chegarasi 40 daqiqa", "New-TimeSpan -Minutes 40" in src)
    check("TaskScheduler/Operational jurnali yoqiladi",
          "TaskScheduler/Operational" in src and "IsEnabled = $true" in src,
          "o'lchangan: jurnal O'CHIQ edi, vazifa nega tugagani noma'lum")
    check("Interactive rejimi uchun OGOHLANTIRISH bor",
          "OGOHLANTIRISH" in src and "0xC000013A" in src)
    check("qo'yilgan sozlamalar CHOP ETILADI",
          "Windows tasdiqladi" in src,
          "skript nima so'raganini emas, Windows nima qabul qilganini ko'rsatish")

    # ENG MUHIM INVARIANT: skript byudjeti Windows chegarasidan KICHIK.
    # Aks holda Windows jarayonni o'ldiradi va checkpoint yozilmaydi —
    # ya'ni butun tuzatish ishlamay qoladi.
    import re as _re
    m = _re.search(r"\$MaxSeconds\s*=\s*(\d+)", src)
    lim = _re.search(r"New-TimeSpan -Minutes 40", src)
    check("byudjet Windows chegarasidan KICHIK",
          bool(m) and bool(lim) and int(m.group(1)) < 40 * 60,
          f"byudjet={m.group(1) if m else '?'}s, chegara=2400s")

    import run_etl
    d = run_etl.main.__doc__ or ""
    check("run_etl standart byudjeti chegaradan kichik",
          _standart_byudjet(run_etl) < 40 * 60,
          f"{_standart_byudjet(run_etl)}s < 2400s")


def _standart_byudjet(run_etl) -> float:
    """`run_etl.py --max-seconds` ning standart qiymatini o'qiydi."""
    src = io.open(os.path.join(ROOT, "run_etl.py"), encoding="utf-8").read()
    import re as _re
    m = _re.search(r'"--max-seconds", type=float, default=([\d.]+)', src)
    return float(m.group(1)) if m else -1.0


def test_byudjet_taqsimoti() -> None:
    section("Vaqt byudjeti guruh ichida TAQSIMLANADI")

    import run_etl

    class A:
        all_statuses = False
        limit = None
        with_docs = True
        max_seconds = 1200.0

    guruhlar = run_etl.build_groups(A())
    for platform, steps in guruhlar:
        byudjetli = [(s, e) for s, e in steps if "--max-seconds" in e]
        jami = sum(float(e[e.index("--max-seconds") + 1]) for _s, e in byudjetli)
        if byudjetli:
            check(f"{platform}: byudjetlar yig'indisi guruh byudjetidan oshmadi",
                  jami <= A.max_seconds + 1,
                  f"{jami}s <= {A.max_seconds}s ({len(byudjetli)} qadam)")
    uzex = dict(guruhlar)["uzex"]
    check("uzex ikkala qadami ham byudjetli",
          all("--max-seconds" in e for _s, e in uzex), str(uzex))
    check("etl_tenders.py ga byudjet BERILMAYDI (7 sekundda tugaydi)",
          all("--max-seconds" not in e
              for s, e in dict(guruhlar)["xt-xarid"] if s == "etl_tenders.py"))


# =====================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="ETL ishonchliligi sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: ETL ISHONCHLILIGI")
    print("=" * 70)

    # --- bazasiz / tarmoqsiz qism ---
    test_tasnif()
    test_kutish()
    test_qayta_urinish_amalda()
    test_buzuq_yozuv_izolyatsiyasi()
    test_idempotentlik_strukturasi()
    test_http_audit()
    test_toxtatgich()
    test_inkremental()
    test_orkestrator_kodlari()
    test_orkestrator_soxta_bola()
    test_chiqish_kodlashi()
    test_rejalashtiruvchi()
    test_byudjet_taqsimoti()

    # --- baza kerak bo'lgan qism ---
    conn = db() if psycopg2 is not None else None
    if conn is None:
        print("\n[i] Baza yo'q — checkpoint/qulf/yetim sinovlari o'tkazib yuborildi.")
    else:
        test_checkpoint(conn)
        test_backoff_oynasi(conn)
        test_checkpoint_qulflari(conn)
        test_yetim_yurish(conn)
        test_ustma_ust(conn)
        test_qulf_uzilganda_bosaydi(conn)
        test_idempotentlik_bazada(conn)
        if args.tarmoqsiz:
            print("\n[i] --offline: uchidan-uchiga sinov o'tkazib yuborildi "
                  "(manbaga so'rov yuboradi).")
        else:
            test_uzilish_va_tiklash_ete(conn)
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
