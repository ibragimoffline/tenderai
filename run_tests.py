#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOVLARNI YURGIZUVCHI — NOINTERAKTIV, CI UCHUN.

NEGA BU FAYL BOR
----------------
Sinovlar shu paytgacha qo'lda, bittalab yurgizilardi. Bu ikki
muammoni berdi:

  1. KODLASH. Chiqish quvurga yo'naltirilganda (CI da HAR DOIM
     shunday) Windows'da Python `locale.getpreferredencoding()` ni
     oladi — bu mashinada `cp1251`. O'zbek kirill va to'liq
     kenglikdagi belgilar u yerda yo'q va chop etish butun
     to'plamni `UnicodeEncodeError` bilan o'ldiradi.
     `_tests/import_test.py` AYNAN shu sababdan 143 ta tekshiruvni
     BAJARMASDAN yiqilardi va uni hech kim payqamadi, chunki
     terminalda yurgizilganda muammo KO'RINMAYDI.

  2. CHIQISH KODI. Bittalab yurgizishda "hammasi o'tdimi" degan
     savolga javob odamning e'tiboriga bog'liq edi.

Bu yurgizuvchi ikkalasini ham hal qiladi: har bola jarayonga
`PYTHONIOENCODING=utf-8` beriladi, chiqish UTF-8 deb o'qiladi, va
yakuniy chiqish kodi HAR QANDAY yiqilishda nolga teng bo'lmaydi.

ISHGA TUSHIRISH
---------------
    python run_tests.py                 # BAZALI, tarmoqsiz (standart)
    python run_tests.py --online        # tarmoq/uchidan-uchiga ham
    python run_tests.py --bazasiz       # bazasiz muhit uchun (CI)
    python run_tests.py --only import   # nomida "import" bori
    python run_tests.py --list          # ro'yxat, yurgizmaydi

CHIQISH KODI: 0 — hammasi o'tdi; 1 — kamida bittasi yiqildi.
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import subprocess
import sys
import time
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(HERE, "_tests")

sys.path.insert(0, TESTS)
import konsol  # noqa: E402

#: Bitta to'plamning yuqori vaqt chegarasi. Osilgan sinov butun
#: CI ni to'sib qo'ymasin.
TIMEOUT = int(os.environ.get("TEST_TIMEOUT", "900"))

#: ILOVA ROLI — sinov MANA SHU rol bilan yurishi kerak.
#:
#: `postgres` (superuser) HAMMA grant tekshiruvini chetlab o'tadi,
#: ya'ni ERP chegarasi va IDOR himoyalari sinalmay qoladi.
#:
#: MANBA BITTA: `_tests/rejim.py`. Ilgari bu yerda AYNI qiymat
#: ikkinchi marta e'lon qilingan edi va izohda "`nom_butunlik_test`
#: ikkalasini solishtiradi" deb YOZILGAN edi -- bunday tekshiruv
#: YO'Q edi (5-sinf: izoh himoya deb hisoblangan). Ikki manba
#: o'rniga import: endi ajralib ketishning IMKONI yo'q.
sys.path.insert(0, TESTS)
from rejim import ILOVA_ROL                              # noqa: E402


def toplamlar(filtr: str = "") -> List[str]:
    hammasi = sorted(glob.glob(os.path.join(TESTS, "*_test.py")))
    if filtr:
        hammasi = [p for p in hammasi if filtr.lower() in os.path.basename(p).lower()]
    return hammasi


#: Rejim -> bola jarayonga uzatiladigan bayroqlar.
#:
#: STANDART `tarmoq_yoq`: baza tekshiruvlari YURADI. Ilgari standart
#: `--offline` edi va u BAZANI ham o'chirardi — ya'ni haqiqiy
#: ma'lumot nuqsonlarini ushlaydigan tekshiruvlar UMUMAN
#: bajarilmasdi. Sabab va o'lchov: `_tests/rejim.py`.
REJIM = {
    "toliq": [],                             # hammasi (baza + tarmoq)
    "tarmoq_yoq": ["--tarmoqsiz"],           # STANDART
    "baza_yoq": ["--bazasiz"],
    "hech_narsa": ["--bazasiz", "--tarmoqsiz"],
}


def yurgiz(yol: str, rejim_nomi: str) -> Tuple[str, int, float, str, str]:
    """Bitta to'plamni yurgizadi.

    -> (nom, chiqish_kodi, sekund, xulosa, TO'LIQ_CHIQISH)

    TO'LIQ CHIQISH NEGA QAYTARILADI (2026-09-03 da o'lchandi):
    `auth_test` to'plam ichida 128/132 berdi, yakka yurgizilganda esa
    UCH MARTA 132/132. Qaysi 4 tekshiruv yiqilgani ANIQLANMADI —
    yurgizuvchi bolaning chiqishini SAQLAMASDI, faqat oxirgi
    xulosa qatorini olardi. Ya'ni flaky yiqilishni keyin tahlil
    qilishning imkoni yo'q edi. Endi chiqish faylga yoziladi.
    """
    nom = os.path.basename(yol)[:-3]
    args = [sys.executable, yol] + REJIM[rejim_nomi]

    # BOLAGA UTF-8 MAJBURAN BERILADI. Bu yurgizuvchining o'zi UTF-8
    # bo'lgani yetarli emas — har bola O'Z oqimini o'zi ochadi.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")

    t0 = time.time()
    try:
        r = subprocess.run(args, cwd=HERE, env=env, capture_output=True,
                           # CHIQISH UTF-8 DEB O'QILADI. `errors` ATAYLAB
                           # "backslashreplace": bola kutilmagan bayt
                           # yuborsa ham yurgizuvchi YIQILMAYDI, lekin
                           # bayt YO'QOLMAYDI — u `\xNN` bo'lib ko'rinadi.
                           encoding="utf-8", errors="backslashreplace",
                           timeout=TIMEOUT)
        kod = r.returncode
        chiqish = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        # BESHTA qiymat — normal yo'l bilan BIR XIL. Ilgari bu tarmoq
        # TO'RTTA qaytarardi va `main()` uni beshta deb ochardi:
        # to'plam TIMEOUT bo'lganda yurgizuvchining O'ZI `ValueError`
        # bilan qulardi — ya'ni eng kerak paytda natija YO'QOLARDI.
        qisman = ""
        for oqim in (getattr(e, "stdout", None), getattr(e, "stderr", None)):
            if isinstance(oqim, bytes):
                qisman += oqim.decode("utf-8", "backslashreplace")
            elif isinstance(oqim, str):
                qisman += oqim
        return (nom, -1, time.time() - t0, f"TIMEOUT ({TIMEOUT}s)",
                qisman or f"(timeout {TIMEOUT}s — chiqish saqlanmadi)")
    dt = time.time() - t0

    # Natija qatorini topamiz. To'plamlar turli shakl ishlatadi,
    # shuning uchun bir nechta naqsh qaraladi.
    xulosa = ""
    for ln in reversed(chiqish.strip().splitlines()):
        past = ln.lower()
        if any(k in past for k in ("natija:", "hammasi o'tdi", "sinov o'tdi",
                                   "o'tdi", "yiqildi")):
            xulosa = ln.strip()
            break
    if not xulosa:
        # XULOSA TOPILMASA — bu SIGNAL, jimgina o'tkazib yuborilmaydi.
        # `import_test` aynan shunday holatda edi: chiqish bor, natija
        # qatori yo'q, chunki to'plam o'rtada o'lgan.
        oxiri = chiqish.strip().splitlines()[-1:] or ["(chiqish bo'sh)"]
        xulosa = f"XULOSA QATORI YO'Q — {oxiri[0][:80]}"
    return nom, kod, dt, xulosa, chiqish


def muhit_qoldigi() -> None:
    """Oldingi yurishdan QOLGAN sinov hisoblarini KO'RSATADI.

    NEGA KERAK (o'lchangan 2026-09-03). To'plam o'ldirilsa (timeout,
    tashqi to'xtatish, Ctrl+C) sinovning `finally` bloki UMUMAN
    bajarilmaydi va sinov kompaniyasi FAOL qolib ketadi. Keyingi
    yurishda `sole_company_id()` ikki faol kompaniyani ko'rib rad
    etadi va ALOQASI YO'Q to'plam (`catalog_kod_test`, 4-o'rinda)
    yiqiladi. Sabab esa 30 ta to'plam narida — topish qiyin.

    NEGA JIMGINA TOZALAMAYMIZ: qoldiqni avtomatik o'chirish uni
    KO'RINMAS qiladi va "nega yiqildi" degan savol javobsiz qoladi.
    Bu loyihada "mexanizm qoldiqni abadiylashtiradi" sinfi bir necha
    marta chiqqan. Shuning uchun KO'RSATAMIZ va buyruqni beramiz,
    o'zimiz tegmaymiz.

    Baza yetib bo'lmasa jim o'tamiz: bu qulaylik, to'plamning sharti emas.
    """
    try:
        import psycopg2                                     # noqa: PLC0415
        dsn = os.environ.get("XT_DB_DSN")
        if not dsn:
            return
        conn = psycopg2.connect(dsn, connect_timeout=5)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username FROM company_account "
                    " WHERE active AND (username LIKE 'zz%' "
                    "                   OR username LIKE '_mt_test_%') "
                    " ORDER BY id")
                qoldiq = cur.fetchall()
        finally:
            conn.close()
    except Exception:                                       # noqa: BLE001
        return

    if not qoldiq:
        return
    print(f"  [!] OLDINGI YURISHDAN QOLDIQ: {len(qoldiq)} ta sinov hisobi FAOL.")
    for cid, login in qoldiq:
        print(f"      id={cid} {login}")
    print("      Bu `sole_company_id()` ga tayangan to'plamlarni yiqitadi.")
    idlar = ", ".join(str(c) for c, _ in qoldiq)
    print(f"      Tozalash:  UPDATE company_account SET active=false "
          f"WHERE id IN ({idlar});")
    print()


def main() -> None:
    konsol.sozla()

    ap = argparse.ArgumentParser(description="Sinovlarni yurgizuvchi (CI)")
    ap.add_argument("--online", action="store_true",
                    help="TARMOQ tekshiruvlari ham (standart: tarmoqsiz)")
    ap.add_argument("--bazasiz", action="store_true",
                    help="BAZASIZ muhit uchun (baza tekshiruvlari "
                         "o'tkaziladi). Bu bayroqsiz baza tekshiruvlari "
                         "YURADI — ular ma'lumot nuqsonlarini ushlaydi.")
    ap.add_argument("--only", default="",
                    help="Faqat nomida shu bo'lak bor to'plamlar")
    ap.add_argument("--list", action="store_true", help="Ro'yxat, yurgizmaydi")
    ap.add_argument("--natija-dir", default="",
                    help="To'plam chiqishlari va JSON xulosa shu katalogga yoziladi (standart: _test_natija/)")
    args = ap.parse_args()

    if args.online and args.bazasiz:
        rejim_nomi = "baza_yoq"
    elif args.online:
        rejim_nomi = "toliq"
    elif args.bazasiz:
        rejim_nomi = "hech_narsa"
    else:
        rejim_nomi = "tarmoq_yoq"

    # QAMROV: NECHTA TO'PLAM BOR va nechtasi YURADI.
    #
    # O'LCHANGAN NUQSON (2026-09-04, uchinchi marta). Filtrlangan
    # yurish o'zini TO'LIQ yurish kabi ko'rsatardi: xulosada
    # "12/12 to'plam o'tdi" chiqardi va o'sha 12 tasi mavjud 40
    # tadan tanlab olingani HECH QAYERDA aytilmasdi.
    #
    # Bu `tsc --noEmit -p tsconfig.json` (0 fayl ko'rdi, exit 0) va
    # `requirement_test` (o'zgartirildi, yurgizilmadi) bilan BIR
    # SINF: yashil raqam berilgan, qamrov esa aytilmagan.
    #
    # Endi ikkala son ham chiqadi va o'tkazib yuborilganlar
    # NOMMA-NOM yoziladi — "qaysi to'plamni yurgizaman" degan
    # tanlovning o'zi xato manbai.
    hamma_yol = toplamlar("")
    yollar = toplamlar(args.only)
    otkazildi = [os.path.basename(p)[:-3] for p in hamma_yol
                 if p not in yollar]
    if not yollar:
        print(f"To'plam topilmadi (filtr: {args.only!r})")
        sys.exit(1)

    if args.list:
        for p in yollar:
            print("  " + os.path.basename(p))
        return

    print("=" * 78)
    tavsif = {"toliq": "TO'LIQ (baza + tarmoq)",
              "tarmoq_yoq": "BAZALI, tarmoqsiz (standart)",
              "baza_yoq": "TARMOQLI, bazasiz",
              "hech_narsa": "FAQAT STATIK (baza ham, tarmoq ham yo'q)"}
    print(f"SINOVLAR: {len(yollar)} ta to'plam · "
          f"rejim: {tavsif[rejim_nomi]} · chegara: {TIMEOUT}s")
    print(f"stdout.encoding = {sys.stdout.encoding} · "
          f"Unicode xavfsiz: {konsol.tekshir()}")
    print("=" * 78)

    muhit_qoldigi()

    # NATIJA KATALOGI. Har to'plamning TO'LIQ chiqishi saqlanadi —
    # flaky yiqilishni KEYIN tahlil qilish uchun yagona yo'l.
    natija_dir = args.natija_dir or os.path.join(HERE, "_test_natija")
    os.makedirs(natija_dir, exist_ok=True)

    # MAXRAJ KICHRAYSA SEZILSIN.
    #
    # `toplam_mavjud` `glob` bilan topiladi, ya'ni sinov fayli
    # O'CHIRILSA yoki nomi o'zgarsa MAXRAJ ham kichrayadi va
    # `43/43` yashil qolaveradi. Qamrov o'lchovi o'zini o'lchagan
    # bo'lardi (1-sinf: asbob tekshirayotgan narsasining xatosini
    # takrorlaydi).
    #
    # QATTIQ SON EMAS (`>= 120` shakli mo'rt — kod o'sganda qamrov
    # joyida qolsa ham yashil bo'ladi). O'RNIGA: oldingi yurish
    # bilan solishtiriladi. Qiymat `xulosa.json` da allaqachon bor
    # va u YOZILISHIDAN OLDIN o'qiladi.
    oldingi = {}
    try:
        import json as _json
        with io.open(os.path.join(natija_dir, "xulosa.json"),
                     encoding="utf-8") as _f:
            oldingi = _json.load(_f) or {}
    except (OSError, ValueError):
        # Birinchi yurish yoki buzilgan fayl — solishtirish YO'Q.
        # Buni "kamaymadi" deb ko'rsatish o'lchanmaganni o'lchangan
        # deb aytish bo'lardi; `None` shundayligicha qoladi.
        pass
    oldingi_mavjud = oldingi.get("toplam_mavjud")

    # QAYSI ROL BILAN YURDIK.
    #
    # NEGA KERAK (2026-09-04): tekshiruv soni ROLGA BOG'LIQ.
    # `postgres` (superuser) bilan 3402, `tai_app` bilan 3280 —
    # farq YO'QOTISH emas, ALMASHISH: `auth_test` huquq shoxiga
    # o'tganda sanoq solishtiruvlari o'rniga bitta "surat kerak
    # emas" tekshiruvi qoladi.
    #
    # Ya'ni IKKI BAZAVIY RAQAM bor. Ularni aralashtirib
    # solishtirish qo'riqchini yolg'on qiladi: `tai_app` dan
    # `postgres` ga o'tilganda son OSHADI va "hammasi joyida"
    # deb ko'rinadi, holbuki REJIM o'zgargan.
    #
    # Shuning uchun rol YOZILADI va taqqoslash faqat BIR XIL
    # rejim ichida qilinadi.
    rol = None
    try:
        sys.path.insert(0, HERE)
        # `.env` SHU YERDA yuklanadi: `run_tests.py` faqat bola
        # jarayonlarni ochadi va o'zi bazaga bormaydi, shuning
        # uchun `XT_DB_DSN` uning muhitida yo'q edi. Buni
        # yuklamasdan rol DOIM "NOMA'LUM" chiqardi — ya'ni
        # o'lchov qo'shildi-yu, hech qachon o'lchamasdi (3-sinf).
        from dotenv import load_dotenv as _ld
        _ld(os.path.join(HERE, ".env"))
        from api import db as _db
        _db.init_pool()
        _r = _db.query_one(
            "SELECT current_user AS u, "
            "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS s")
        rol = {"nom": _r["u"], "superuser": bool(_r["s"])}

        # SUPERUSER BILAN YURISH — REJIM XATOSI, TO'PLAM XATOSI EMAS.
        #
        # O'LCHANGAN NUQSON (2026-09-06). To'liq yurishda `auth_test`
        # va `xavfsizlik_test` YIQILDI. Sabab ularda emas edi: ikkalasi
        # ham superuser aniqlagach ATAYLAB to'xtaydi, chunki superuser
        # grant tekshiruvlarini chetlab o'tadi va ERP chegarasi, IDOR
        # kabi himoyalar UMUMAN sinalmaydi. Farq katta: `auth_test`
        # superuser bilan 10 ta tekshiruv beradi, `tai_app` bilan 131 ta.
        #
        # Qo'riqchi TO'G'RI ishlagan edi, lekin narxi noto'g'ri joyga
        # tushardi: darvoza qizil bo'lardi va sabab "sinov yiqildi"
        # bo'lib ko'rinardi. `DB_SET_ROLE` esa na `.env` da, na
        # `.env.example` da bor edi — ya'ni uni HAR SAFAR eslab qolish
        # kerak edi. Bu eslab qolinmaydi.
        #
        # Endi yurgizuvchi rejimni O'ZI to'g'rilaydi va buni BAQIRIB
        # aytadi. Jim tuzatish bo'lmasin: qaysi rejimda o'lchanganini
        # bilmasdan sonlarni solishtirib bo'lmaydi.
        if rol["superuser"] and not (os.environ.get("DB_SET_ROLE") or "").strip():
            _a = _db.query_one(
                "SELECT (SELECT count(*) FROM pg_roles "
                "          WHERE rolname=%(r)s) AS bor, "
                "       pg_has_role(current_user, %(r)s, 'MEMBER') AS azo",
                {"r": ILOVA_ROL}) or {}
            if _a.get("bor") and _a.get("azo"):
                _oldin = rol["nom"]
                # `os.environ` NING O'ZI YETARLI EMAS. `api.db._SET_ROLE`
                # modul YUKLANGANDA o'qiladi va u allaqachon yuklangan,
                # ya'ni muhitni keyin o'zgartirish shu jarayonga TA'SIR
                # QILMASDI. Birinchi urinishda aynan shu bo'ldi: sarlavha
                # "rol to'g'rilandi" deb yozdi, `current_user` esa
                # `postgres` bo'lib qoldi va bazaviy raqam NOTO'G'RI rol
                # ostida saqlanardi. `rol_ornat()` ikkalasini ham qo'yadi
                # va hovuzni qayta ochadi.
                _db.rol_ornat(ILOVA_ROL)
                _r = _db.query_one(
                    "SELECT current_user AS u, "
                    "(SELECT rolsuper FROM pg_roles "
                    "  WHERE rolname=current_user) AS s")
                rol = {"nom": _r["u"], "superuser": bool(_r["s"]),
                       "avtomatik": True}
                print(f"  ROL TO'G'RILANDI: superuser `{_oldin}` aniqlandi "
                      f"-> `DB_SET_ROLE={ILOVA_ROL}` qo'yildi "
                      f"(joriy rol: `{rol['nom']}`).")
                print("  Sabab: superuser grant himoyalarini chetlab o'tadi, "
                      "ular sinalmay qolardi.")
            else:
                rol["ogohlantirish"] = (
                    f"superuser, `{ILOVA_ROL}` ga o'tib bo'lmadi")
                print(f"  DIQQAT: superuser bilan yurilyapti va `{ILOVA_ROL}` "
                      f"roliga o'tib bo'lmadi.")
                print("  Grant asosidagi himoyalar (ERP chegarasi, IDOR) "
                      "SINALMAYDI — `auth_test` va `xavfsizlik_test` "
                      "ataylab to'xtaydi.")
        _db.close_pool()
    except Exception:                                         # noqa: BLE001
        # Bazasiz muhit yoki ulanish yo'q — `None` QOLADI.
        # "Noma'lum rol" ni "postgres" deb taxmin qilish shu
        # faylning o'zi qo'riqlayotgan xato bo'lardi.
        pass

    natijalar = []
    t0 = time.time()
    for yol in yollar:
        nom, kod, dt, xulosa, chiqish = yurgiz(yol, rejim_nomi)
        natijalar.append((nom, kod, dt, xulosa))
        try:
            with io.open(os.path.join(natija_dir, f"{nom}.log"),
                         "w", encoding="utf-8", newline="") as f:
                f.write(chiqish)
        except OSError as e:                                  # noqa: BLE001
            print(f"  [!] {nom}: chiqish saqlanmadi: {e}")
        belgi = "OK  " if kod == 0 else "XATO"
        print(f"  [{belgi}] {nom:<24} {dt:6.1f}s  {xulosa}")
        sys.stdout.flush()

    yiqilgan = [n for n, k, _d, _x in natijalar if k != 0]

    # MASHINA O'QIY OLADIGAN XULOSA — relis darvozasi shundan o'qiydi.
    #
    # `tekshiruv` XULOSA QATORIDAN ajratiladi ("NATIJA: 132/140").
    # Ajratib bo'lmasa `null` qoladi va u NOLGA AYLANTIRILMAYDI:
    # "o'lchanmadi" va "nol tekshiruv" BIR XIL KO'RINMASLIGI kerak —
    # ikkinchisi to'plam o'rtada o'lganini bildiradi.
    import json
    import re

    def _tekshiruv(x: str):
        """Xulosa qatoridan (o'tdi, jami) ni ajratadi.

        SHAKLLAR TURLICHA va ular BIR JOYGA KELTIRILMAGAN — har
        to'plam o'z tarixiy formatini saqlaydi. Shuning uchun
        ajratgich SHAKLGA emas, IKKI SONGA qaraydi:

            "NATIJA: 132/132 o'tdi"
            "NATIJA: 128 ta o'tdi, 4 ta xato"
            "NATIJA: 149 ta tekshiruv o'tdi, 0 ta yiqildi"
            "HAMMASI O'TDI: 29/29"

        Ajratib bo'lmasa `None` — va u NOLGA AYLANTIRILMAYDI.
        "O'lchanmadi" va "nol tekshiruv" bir xil ko'rinsa, o'rtada
        o'lgan to'plam MUVAFFAQIYAT kabi o'qilardi.
        """
        m = re.search(r"(\d+)\s*/\s*(\d+)", x)
        if m:
            return {"otdi": int(m.group(1)), "jami": int(m.group(2))}
        # Apostrof turlicha yoziladi (', ‘, ’) — `.` bilan olamiz.
        m_ok = re.search(r"(\d+)[^\d]{0,24}?o.tdi", x, re.I)
        m_bad = re.search(r"(\d+)[^\d]{0,16}?(?:xato|yiqildi)", x, re.I)
        if m_ok and m_bad:
            o, b = int(m_ok.group(1)), int(m_bad.group(1))
            return {"otdi": o, "jami": o + b}
        return None

    xulosa_json = {
        "rejim": rejim_nomi,
        "boshlandi": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "davomiylik_sek": round(time.time() - t0, 1),
        "toplam_jami": len(natijalar),
        "toplam_otdi": len(natijalar) - len(yiqilgan),
        "toplam_yiqildi": len(yiqilgan),
        # QAMROV. `toplam_jami` FAQAT yurganlarni sanaydi — mavjud
        # to'plamlar soni ALOHIDA, aks holda filtrlangan yurish
        # to'liq yurish kabi ko'rinardi.
        "toplam_mavjud": len(hamma_yol),
        # OLDINGI YURISHDAGI MAXRAJ — kamayganini darvoza ko'rsin.
        # `None` = solishtirilmadi (birinchi yurish), `0` EMAS.
        "toplam_mavjud_oldingi": oldingi_mavjud,
        "toplam_yoqoldi": (max(0, oldingi_mavjud - len(hamma_yol))
                           if oldingi_mavjud is not None else None),
        "toplam_otkazildi": otkazildi,
        "filtr": args.only or None,
        # ROL — tekshiruv sonini SHUNGA qarab solishtiramiz.
        "rol": rol,
        "yiqilgan": yiqilgan,
        "toplamlar": [
            {"nom": n, "kod": k, "sekund": round(d, 1), "xulosa": x,
             "tekshiruv": _tekshiruv(x)}
            for n, k, d, x in natijalar],
    }
    xulosa_json["tekshiruv_jami"] = sum(
        (t["jami"] for t in (s2["tekshiruv"] for s2 in xulosa_json["toplamlar"])
         if t), 0)
    xulosa_json["tekshiruv_otdi"] = sum(
        (t["otdi"] for t in (s2["tekshiruv"] for s2 in xulosa_json["toplamlar"])
         if t), 0)
    # XULOSA QATORI O'QILMAGAN to'plamlar ALOHIDA sanaladi — ular
    # yuqoridagi yig'indiga KIRMAYDI va jimgina yo'qolmasligi kerak.
    xulosa_json["tekshiruv_olchanmadi"] = [
        s2["nom"] for s2 in xulosa_json["toplamlar"] if s2["tekshiruv"] is None]

    # TEKSHIRUV SONI KAMAYDIMI — FAQAT BIR XIL REJIM ICHIDA.
    #
    # Rol o'zgargan bo'lsa taqqoslash MA'NOSIZ: `postgres` -> 3402,
    # `tai_app` -> 3280. Farqni "yo'qolgan tekshiruv" deb o'qish
    # ham, "oshgan" deb tinchlanish ham xato bo'lardi.
    #
    # Rejim boshqa bo'lsa `None` yoziladi va SABABI aytiladi —
    # "solishtirilmadi" jimgina "kamaymadi" ga aylanmaydi.
    o_rol = (oldingi.get("rol") or {}).get("nom")
    y_rol = (rol or {}).get("nom")
    o_teks = oldingi.get("tekshiruv_jami")
    if o_rol and y_rol and o_rol == y_rol and o_teks:
        xulosa_json["tekshiruv_jami_oldingi"] = o_teks
        xulosa_json["tekshiruv_yoqoldi"] = max(
            0, int(o_teks) - int(xulosa_json["tekshiruv_jami"]))
        xulosa_json["tekshiruv_taqqos_sababi"] = None
    else:
        xulosa_json["tekshiruv_jami_oldingi"] = o_teks
        xulosa_json["tekshiruv_yoqoldi"] = None
        xulosa_json["tekshiruv_taqqos_sababi"] = (
            "oldingi yurish yo'q" if not o_teks else
            f"REJIM BOSHQA: oldin `{o_rol}`, hozir `{y_rol}` — "
            f"tekshiruv soni rolga bog'liq, taqqoslanmadi")
    try:
        with io.open(os.path.join(natija_dir, "xulosa.json"), "w",
                     encoding="utf-8", newline="") as f:
            json.dump(xulosa_json, f, ensure_ascii=False, indent=2)
    except OSError as e:                                      # noqa: BLE001
        print(f"  [!] xulosa.json saqlanmadi: {e}")

    print("=" * 78)
    print(f"JAMI: {len(natijalar)}/{len(hamma_yol)} to'plam yurdi, "
          f"{len(natijalar) - len(yiqilgan)} o'tdi, "
          f"{len(yiqilgan)} yiqildi · {time.time() - t0:.0f}s")
    # O'TKAZIB YUBORILGANLAR JIM QOLMAYDI. Filtrlangan yurish
    # natijasi to'liq yurish bilan bir xil ko'rinmasligi kerak.
    if otkazildi:
        korsat = ", ".join(otkazildi[:8])
        print(f"QAMROV TO'LIQ EMAS — filtr {args.only!r}, "
              f"{len(otkazildi)} to'plam O'TKAZILDI: {korsat}"
              + (f" (+{len(otkazildi) - 8})" if len(otkazildi) > 8 else ""))
    # MAXRAJ KAMAYGANI — sinov fayli o'chirilgan yoki nomi
    # o'zgargan bo'lishi mumkin. Bu YASHIL yurishda ham chiqadi.
    if xulosa_json["toplam_yoqoldi"]:
        print(f"DIQQAT: to'plamlar soni KAMAYDI — {oldingi_mavjud} dan "
              f"{len(hamma_yol)} ga ({xulosa_json['toplam_yoqoldi']} ta). "
              f"Fayl o'chirilgan yoki nomi o'zgargan bo'lishi mumkin.")
    print(f"TEKSHIRUV: {xulosa_json['tekshiruv_otdi']}/"
          f"{xulosa_json['tekshiruv_jami']}"
          + (f" · rol: {y_rol}" if y_rol else " · rol: NOMA'LUM")
          + (f" · o'lchanmadi: {', '.join(xulosa_json['tekshiruv_olchanmadi'])}"
             if xulosa_json["tekshiruv_olchanmadi"] else ""))
    # BIR XIL REJIMDA tekshiruv soni tushgani — sinov jimgina
    # yo'qolgan bo'lishi mumkin.
    if xulosa_json["tekshiruv_yoqoldi"]:
        print(f"DIQQAT: tekshiruv soni KAMAYDI — {o_teks} dan "
              f"{xulosa_json['tekshiruv_jami']} ga "
              f"({xulosa_json['tekshiruv_yoqoldi']} ta), rol o'zgarmagan "
              f"(`{y_rol}`). Tekshiruv o'chirilgan bo'lishi mumkin.")
    elif xulosa_json["tekshiruv_taqqos_sababi"]:
        print(f"(tekshiruv soni taqqoslanmadi: "
              f"{xulosa_json['tekshiruv_taqqos_sababi']})")
    print(f"Natijalar: {natija_dir}")
    if yiqilgan:
        print("YIQILGAN: " + ", ".join(yiqilgan))
    print("=" * 78)
    sys.exit(1 if yiqilgan else 0)


if __name__ == "__main__":
    main()
