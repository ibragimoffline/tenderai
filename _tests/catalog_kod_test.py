#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: KATALOG KODLASH — PRECISION QO'RIQCHISI
===============================================

Bu to'plam qamrovni EMAS, ANIQLIKNI qo'riqlaydi. Kodlash qamrovini
oshirishning eng oson yo'li chegarani pasaytirish, va u JIMGINA
ishlaydi: raqam o'sadi, xato mos kelishlar esa faqat broker
"bu tender menga umuman mos emas" deganda bilinadi.

NIMA TEKSHIRILADI VA NEGA

  1. CHEGARALAR O'ZGARMAGAN. `MIN_EVIDENCE` va `MIN_SHARE` qattiq
     yozilgan: ular pasaysa sinov yiqiladi va o'zgarish ONGLI
     bo'lishga majbur qiladi.

  2. MA'LUM SOXTA MOSLIKLAR to'silgan:
     - `monitor` `monitoring` ichidan topilmaydi (qism-so'z);
     - dalil ikkitadan kam bo'lsa kod BERILMAYDI;
     - ikki oila teng bo'lsa kod BERILMAYDI (`noaniq`);
     - nomdan ma'noli so'z chiqmasa kod BERILMAYDI (`tokensiz`).

  3. ANIQLIK HAQIQIY INSON YORLIG'IGA qarshi o'lchanadi.
     960 ta keng kodni ODAM bergan — bu sintetik emas, haqiqiy
     yorliq. Avtomatik taklif ular bilan solishtiriladi.

  4. SABAB LUG'ATI Python va SQL da BIR XIL.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\catalog_kod_test.py
    .venv\\Scripts\\python.exe _tests\\catalog_kod_test.py --offline
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
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}" + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
def test_chegaralar():
    bolim("1. Chegaralar O'ZGARMAGAN (precision qo'riqchisi)")
    from api import catalog_auto as C
    # BU RAQAMLAR ATAYLAB QATTIQ YOZILGAN. Ular pasaysa sinov
    # yiqiladi — qamrovni chegara pasaytirib oshirish JIMGINA
    # sodir bo'lmasin.
    check("`MIN_EVIDENCE` = 2", C.MIN_EVIDENCE == 2, str(C.MIN_EVIDENCE))
    check("`MIN_SHARE` = 0.75", abs(C.MIN_SHARE - 0.75) < 1e-9, str(C.MIN_SHARE))
    check("`MAX_TOKENS` = 4", C.MAX_TOKENS == 4, str(C.MAX_TOKENS))
    check("kuchsiz band chegarasi 0.80", abs(C.KUCHSIZ_ISHONCH - 0.80) < 1e-9)
    check("kuchsiz band dalili 4", C.KUCHSIZ_DALIL == 4)


def test_ommaviy_ochirish():
    """`POST /catalog/ommaviy-ochir` shartnomasi.

    OMMAVIY O'CHIRISH — QAYTARIB BO'LMAYDIGAN AMAL. Uning har bir
    qo'rig'i shu yerda qulflanadi: qo'riq jimgina yo'qolsa, buni
    faqat ma'lumot yo'qolgandan KEYIN bilish mumkin.
    """
    import ast as _ast
    import io as _io
    bolim("6. Ommaviy o'chirish shartnomasi")

    q = _io.open(os.path.join(ROOT, "api", "queries.py"),
                 encoding="utf-8").read()
    manba = _io.open(os.path.join(ROOT, "api", "main.py"),
                     encoding="utf-8").read()

    # --- IJARACHI SHARTI SQL DA ---
    # Python da filtrlash IDOR uchun bitta unutilgan shart masofasida.
    # HAR KONSTANTA ALOHIDA AJRATILADI, tayinlashning O'ZIDAN.
    #
    # Birinchi yozuvda `q[i:i+400]` oynasi ishlatilgandi va u
    # KEYINGI konstantalarga tegib ketardi: `CATALOG_BULK_DELETE_SQL`
    # dan `company_id` olib tashlanganda ham sinov O'TIB KETDI,
    # chunki `company_id` qo'shni `CATALOG_CLEAR_SQL` da bor edi.
    # Ya'ni qo'riq emas, tasodif edi.
    def _qiymat(nom: str) -> str:
        from api import queries as _Q
        v = getattr(_Q, nom)
        return " ".join(str(v).split())

    for nom in ("CATALOG_BULK_DELETE_SQL", "CATALOG_CLEAR_SQL",
                "CATALOG_COUNT_SQL"):
        v = _qiymat(nom)
        check(f"{nom}: company_id SQL DA", "%(company_id)s" in v, v[:80])

    check("tanlanganlar: `RETURNING id` — HAQIQATDA o'chirilgani",
          "RETURNING id" in _qiymat("CATALOG_BULK_DELETE_SQL"))
    check("tozalash: `RETURNING id`",
          "RETURNING id" in _qiymat("CATALOG_CLEAR_SQL"))

    # --- ENDPOINT QO'RIQLARI ---
    fn = None
    for t in _ast.walk(_ast.parse(manba)):
        if isinstance(t, _ast.FunctionDef) and t.name == "catalog_ommaviy_ochir":
            fn = t
            break
    check("`catalog_ommaviy_ochir()` bor", fn is not None)
    if fn is None:
        return
    tana = _ast.get_source_segment(manba, fn) or ""

    check("ikki rejim BIRGA berilmaydi",
          "body.hammasi and body.ids" in tana)
    check("bitta ham berilmasa RAD ETILADI",
          "not body.hammasi and not body.ids" in tana)
    check("`hammasi` uchun `kutilgan` MAJBURIY",
          "body.kutilgan is None" in tana)

    check("chegara bor", "OMMAVIY_OCHIR_CHEK" in tana)

    # --- AUDIT: BOR VA BITTA ---
    check("audit yoziladi", "audit_yoz(" in tana)
    check("audit BITTA qator (sikl ichida emas)",
          tana.count("audit_yoz(") == 1, str(tana.count("audit_yoz(")))
    check("audit `entity_id` — KOMPANIYA",
          'entity="company"' in tana and "entity_id=cid" in tana)

    # --- QAYTARILGAN SON HAQIQIY ---
    # `len(body.ids)` qaytarilsa interfeys "hammasi o'chdi" deb
    # ko'rsatardi, holbuki eskirgan id topilmagan bo'lishi mumkin.
    check("qaytadi: HAQIQATDA o'chirilgan son",
          'natija or {}' in tana and '"ochirildi": n' in tana, tana[:0])
    # SON BAZADAN KELADI, so'rovdan emas.
    check("son `len(body.ids)` dan OLINMAYDI",
          "n = len(body.ids)" not in tana)
    # YOZUV YO'LI. `db.query()` rollback qiladi -- o'chirish bekor
    # bo'lardi, `RETURNING` esa sonni baribir qaytarib, YOLG'ON
    # muvaffaqiyat ko'rsatardi (o'lchandi 2026-09-11).
    # AST BILAN -- IZOH HISOBGA OLINMAYDI.
    #
    # Matn qidiruvi bugun UCH marta yolg'on signal berdi va uchalasida
    # ham aybdor MENING O'Z IZOHIM bo'ldi: izohda `db.query()`
    # eslatilgani uchun tekshiruv qizarardi. Izoh -- hujjat, kod emas.
    _db_chaqiruv = set()
    for _n in _ast.walk(fn):
        if (isinstance(_n, _ast.Call) and isinstance(_n.func, _ast.Attribute)
                and isinstance(_n.func.value, _ast.Name)
                and _n.func.value.id == "db"):
            _db_chaqiruv.add(_n.func.attr)
    check("yozuv `execute_returning()` orqali",
          "execute_returning" in _db_chaqiruv, str(sorted(_db_chaqiruv)))
    check("yozuv `query()` orqali O'TMAYDI",
          "query" not in _db_chaqiruv, str(sorted(_db_chaqiruv)))

    # --- XATO KODI RO'YXATDA ---
    from api import xatolar
    check("`CATALOG_COUNT_MISMATCH` kodi ro'yxatda",
          "CATALOG_COUNT_MISMATCH" in xatolar.KODLAR)
    check("u 409 (nizo), 400 emas",
          xatolar.KODLAR.get("CATALOG_COUNT_MISMATCH") == 409,
          str(xatolar.KODLAR.get("CATALOG_COUNT_MISMATCH")))


def test_ommaviy_ochirish_xulqi():
    """Qo'riqlar MATNDA emas, ISHDA sinaladi.

    Birinchi yozuvda bu tekshiruvlar manba matnidan satr qidirardi.
    Mutatsiya `if int(body.kutilgan) != int(hozir):` ni `if False:`
    ga almashtirganda sinov O'TIB KETDI -- satrlar joyida turardi.
    Ya'ni qo'riqchi emas, ko'chirma edi.

    Endi endpoint ROSTDAN chaqiriladi, `db` qo'g'irchoq bilan
    almashtiriladi va NIMA BAJARILGANI o'lchanadi.
    """
    bolim("7. Ommaviy o'chirish XULQI")
    from api import main as M, xatolar

    class SoxtaDB:
        """Qo'g'irchoq HAQIQATNI aks ettiradi.

        `query()` YOZUVNI RAD ETADI. Sabab -- o'lchangan nuqson
        (2026-09-11): ommaviy o'chirish `db.query()` orqali
        yozilgandi, u esa `rollback()` qiladi. `RETURNING` qatorlarni
        baribir qaytargani uchun son to'g'ri chiqdi va ekran
        "1796 ta o'chirildi" dedi -- bazada esa hech narsa
        o'zgarmadi.

        Birinchi yozuvda bu qo'g'irchoq `query()` da yozuvni QABUL
        QILARDI, ya'ni sinov nuqsonni KODLAB QO'YGANDI: haqiqiy
        xulq bilan sinov xulqi bir-biriga mos kelmasdi va sinov
        yashil turardi.
        """

        def __init__(self, soni):
            self.soni = soni
            self.ochirildi = []      # (sql, params) -- BAJARILGAN ishlar

        def query_one(self, sql, params=None):
            return {"n": self.soni}

        def query(self, sql, params=None):
            q = " ".join(str(sql).split()).upper()
            if any(x in q for x in ("DELETE FROM", "UPDATE ", "INSERT INTO")):
                raise AssertionError(
                    "YOZUV `query()` orqali o'tdi -- u rollback qiladi")
            return []

        def execute_returning(self, sql, params=None):
            self.ochirildi.append((" ".join(str(sql).split()), params))
            if "id = ANY" in str(sql):
                return {"n": len((params or {}).get("ids", []))}
            return {"n": self.soni}

    asl = (M.db, M.company_id_of, M.kimlik_of, M.audit_yoz)
    auditlar = []
    try:
        M.company_id_of = lambda *a, **k: 7
        M.kimlik_of = lambda *a, **k: object()
        M.audit_yoz = lambda *a, **k: auditlar.append(k)

        # --- SON MOS KELMASA: HECH NARSA O'CHMAYDI ---
        # Ekranda 12 ta, serverda 1796 ta (oradan import tugagan).
        soxta = SoxtaDB(1796); M.db = soxta
        xato = None
        try:
            M.catalog_ommaviy_ochir(
                M.CatalogOmmaviyOchirIn(hammasi=True, kutilgan=12), None)
        except Exception as e:                               # noqa: BLE001
            xato = e
        check("son mos kelmasa XATO qaytadi",
              getattr(xato, "kod", None) == "CATALOG_COUNT_MISMATCH",
              f"{type(xato).__name__}: {xato}")
        # ENG QIMMAT DA'VO: o'chirish BAJARILMADI.
        check("son mos kelmasa HECH NARSA o'chmaydi",
              not soxta.ochirildi, str(soxta.ochirildi[:1]))
        check("bajarilmagan amal auditga yozilmaydi", not auditlar,
              str(auditlar[:1]))

        # --- SON MOS KELSA: O'CHADI ---
        soxta = SoxtaDB(3); M.db = soxta
        r = M.catalog_ommaviy_ochir(
            M.CatalogOmmaviyOchirIn(hammasi=True, kutilgan=3), None)
        check("son mos kelsa o'chadi", r["ochirildi"] == 3, str(r))
        check("tozalash SQL i ishlatiladi",
              any("DELETE FROM catalog_product" in sql and "id = ANY" not in sql
                  for sql, _p in soxta.ochirildi), str(soxta.ochirildi))
        check("audit BITTA marta yoziladi", len(auditlar) == 1, str(len(auditlar)))

        # --- TANLANGANLAR: AYNAN O'SHA id lar ---
        soxta = SoxtaDB(9); M.db = soxta
        auditlar.clear()
        r = M.catalog_ommaviy_ochir(
            M.CatalogOmmaviyOchirIn(ids=[4, 8]), None)
        check("tanlanganlar: aynan berilgan id lar",
              soxta.ochirildi and soxta.ochirildi[0][1].get("ids") == [4, 8],
              str(soxta.ochirildi[:1]))
        check("tanlanganlar: ijarachi params da",
              soxta.ochirildi[0][1].get("company_id") == 7,
              str(soxta.ochirildi[0][1]))
        check("tanlanganlar: o'chirilgan son qaytadi", r["ochirildi"] == 2, str(r))

        # --- IKKI REJIM BIRGA: RAD ---
        soxta = SoxtaDB(5); M.db = soxta
        xato = None
        try:
            M.catalog_ommaviy_ochir(
                M.CatalogOmmaviyOchirIn(ids=[1], hammasi=True, kutilgan=5), None)
        except Exception as e:                               # noqa: BLE001
            xato = e
        check("ikki rejim birga -> XATO", isinstance(xato, xatolar.Xato),
              f"{type(xato).__name__}")
        check("ikki rejim birga -> hech narsa o'chmaydi",
              not soxta.ochirildi, str(soxta.ochirildi[:1]))

        # --- BO'SH SO'ROV: RAD ---
        soxta = SoxtaDB(5); M.db = soxta
        xato = None
        try:
            M.catalog_ommaviy_ochir(M.CatalogOmmaviyOchirIn(), None)
        except Exception as e:                               # noqa: BLE001
            xato = e
        check("bo'sh so'rov -> XATO", isinstance(xato, xatolar.Xato))
        check("bo'sh so'rov -> hech narsa o'chmaydi", not soxta.ochirildi)

        # --- CHEGARA ---
        soxta = SoxtaDB(99999); M.db = soxta
        xato = None
        try:
            M.catalog_ommaviy_ochir(
                M.CatalogOmmaviyOchirIn(
                    ids=list(range(M.OMMAVIY_OCHIR_CHEK + 1))), None)
        except Exception as e:                               # noqa: BLE001
            xato = e
        check("chegaradan ko'p -> XATO", isinstance(xato, xatolar.Xato))
        check("chegaradan ko'p -> hech narsa o'chmaydi", not soxta.ochirildi)
    finally:
        M.db, M.company_id_of, M.kimlik_of, M.audit_yoz = asl


def test_tashxis_asbobi_yozmaydi():
    """`kod_tashxis.py` FAQAT o'qiydi.

    Asbob ishlab chiqarishda yurgiziladi. Agar u yo'l-yo'lakay
    `taklif_yoz()` chaqirsa, "o'lchash" ma'lumotni O'ZGARTIRARDI va
    keyingi o'lchov allaqachon buzilgan holatni ko'rsatardi.
    """
    import ast as _ast
    import io as _io
    bolim("8. Tashxis asbobi — faqat o'qiydi")

    yol = os.path.join(ROOT, "kod_tashxis.py")
    check("asbob mavjud", os.path.exists(yol))
    if not os.path.exists(yol):
        return
    daraxt = _ast.parse(_io.open(yol, encoding="utf-8").read())

    # IZOHLAR VA DOCSTRING HISOBGA OLINMAYDI -- faqat HAQIQIY
    # chaqiruvlar. Matn qidiruvi bugun ikki marta yolg'on signal
    # bergan edi.
    chaqiruvlar = set()
    for t in _ast.walk(daraxt):
        if isinstance(t, _ast.Call):
            f = t.func
            if isinstance(f, _ast.Attribute):
                chaqiruvlar.add(f.attr)
            elif isinstance(f, _ast.Name):
                chaqiruvlar.add(f.id)

    for yomon in ("taklif_yoz", "tasdiqla", "rad_et", "execute_returning",
                  "scalar_write"):
        check(f"`{yomon}()` chaqirilmaydi", yomon not in chaqiruvlar,
              str(sorted(chaqiruvlar)[:8]))

    # SQL matnlarida ham yozuv bo'lmasin.
    xom = []
    for t in _ast.walk(daraxt):
        if isinstance(t, _ast.Constant) and isinstance(t.value, str):
            v = " ".join(t.value.split()).upper()
            if v.startswith(("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ")):
                xom.append(v[:50])
    check("yozuvchi SQL yo'q", not xom, str(xom[:2]))

    # `tashxis` chiqishi ishlatilsin -- aks holda asbob signal
    # holatini ko'rsatmasdi va foydasi qolmasdi.
    manba = _io.open(yol, encoding="utf-8").read()
    check("`tashxis=` uzatiladi", "tashxis=tx" in manba)
    check("har ikki daraja o'lchanadi", "(8, \"aniq\")" in manba
          and "(5, \"keng\")" in manba)


def test_lugat():
    bolim("2. Sabab lug'ati — Python va SQL BIR XIL")
    from api import catalog_auto as C
    sql = io.open(os.path.join(ROOT, "schema_patch_kod_tahlil.sql"),
                  encoding="utf-8").read()
    blok = sql[sql.index("catalog_kod_tahlil_sabab_chk"):]
    blok = blok[:blok.index("END IF")]
    sqlda = set(re.findall(r"'([a-z_]+)'", blok)) - {"catalog_kod_tahlil_sabab_chk"}
    check("sabablar MOS", sqlda == set(C.SABABLAR),
          f"sql={sorted(sqlda)} py={sorted(C.SABABLAR)}")
    check("`kod` lug'atda bor", "kod" in C.SABABLAR)
    # "Kod yo'q" YAGONA chelak bo'lmasligi kerak — bu tuzatishning
    # asosiy maqsadi edi.
    check("kodsizlik sabablari BIR NECHTA", len(C.SABABLAR) >= 5,
          str(len(C.SABABLAR)))


def test_tokenlar():
    bolim("3. Tokenlash")
    from api import catalog_auto as C
    check("stop so'zlar tushiriladi",
          C._tokens({"name": "mahsulot uchun va bilan"}) == [],
          str(C._tokens({"name": "mahsulot uchun va bilan"})))
    check("qisqa so'z (<3) tushiriladi",
          "ab" not in C._tokens({"name": "ab kabel"}))
    t = C._tokens({"name": "kabel elektr quvvat"})
    check("uzun so'z BIRINCHI (ko'proq ma'no tashiydi)",
          t == sorted(t, key=len, reverse=True), str(t))
    check("token soni MAX_TOKENS dan oshmaydi",
          len(C._tokens({"name": "bir ikki uch tort besh olti yetti"})) <= C.MAX_TOKENS)
    # Model/SKU nomlari — ma'noli so'z bermaydi va bu KUTILGAN.
    for nom in ("LC-LC", "SC-LC", "DS-K1T341"):
        toks = C._tokens({"name": nom})
        check(f"model nomi `{nom}` -> ma'noli token kam",
              len(toks) <= 1, str(toks))


def test_manba_qism_soz():
    bolim("4. MA'LUM SOXTA MOSLIK: qism-so'z")
    src = io.open(os.path.join(ROOT, "api", "catalog_auto.py"),
                  encoding="utf-8").read()
    # `monitor` `monitoring` ichidan topilmasligi kerak. Kod buni
    # kanonik SO'Z tekshiruvi bilan hal qiladi.
    check("kanonik so'z bo'yicha yakuniy tekshiruv bor",
          "atama.normal(row[\"name\"]" in src or "set(atama.normal(" in src)
    from api import catalog_auto as C

    # PREFIKS TOLERANSI -- MATN EMAS, XULQ.
    #
    # Ilgari bu yerda `"len(word) - len(base) <= 2" in src` turardi.
    # U IKKI TOMONLAMA zaif edi: o'zgaruvchi nomi o'zgarsa YOLG'ON
    # qizarardi (2026-09-12 da aynan shunday bo'ldi), mantiq o'lik
    # kodga aylansa esa YOLG'ON yashil berardi. Endi predikatning
    # o'zi chaqiriladi.
    check("`monitor` `monitoring` ichidan TOPILMAYDI",
          not C._soz_bor("monitor", {"monitoring"}))
    check("`ofis` `ofisno` ichidan topiladi (2 harf dum)",
          C._soz_bor("ofis", {"ofisno"}))
    check("3 harf dum QABUL QILINMAYDI",
          not C._soz_bor("ofis", {"ofisnoe"}))
    check("qisqa so'zda prefiks umuman ishlamaydi (<4 harf)",
          not C._soz_bor("kab", {"kabel"}))
    check("sabab `sozlar_mos_emas` mavjud", "sozlar_mos_emas" in src)


def test_tasdiq_ishonch_majburiy():
    bolim("4c. TASDIQ QATORI DALILSIZ YOZILMAYDI")
    # O'LCHANGAN NOSOZLIK (2026-09-12, ishlab chiqarish):
    #
    #     CheckViolation: catalog_product_code_tasdiq_manba_chk
    #     Failing row: (3251, 1, 27.33.13, taklif, 0.999, tizim:auto, ...)
    #
    # `schema_patch_inson_dalil.sql` tasdiqlangan qatordan
    # `tasdiq_ishonch` ni TALAB qiladi, avtomatik yo'l esa o'sha
    # patchdan keyin yangilanmagandi -- `--qolla` BUTUNLAY o'lik edi
    # va buni hech narsa ushlamasdi (qamrov 0 bo'lgani uchun
    # ko'rinmasdi ham).
    #
    # Bu tekshiruv SATR QIDIRMAYDI: `catalog_product_code` ni
    # yangilaydigan har bir SQL topiladi va `tasdiqlandi` qo'yadigan
    # har biri `tasdiq_ishonch` ham qo'yishi TALAB qilinadi.
    import re
    nosoz = []
    for fayl in ("catalog_auto.py", "kodlash.py", "main.py"):
        yol = os.path.join(ROOT, "api", fayl)
        if not os.path.exists(yol):
            continue
        src = io.open(yol, encoding="utf-8").read()
        # Qo'shni satrlardagi SQL bo'laklari bitta matnga yig'iladi:
        # Python da uzun SQL qo'shni literal sifatida yoziladi.
        tekis = re.sub(r'"\s*\n\s*"', "", src)
        for m in re.finditer(r"UPDATE catalog_product_code(.{0,400}?)WHERE",
                             tekis, flags=re.S):
            blok = m.group(1)
            if re.search(r"tasdiqlandi\s*=\s*now\(\)", blok) \
                    and "tasdiq_ishonch" not in blok:
                nosoz.append(f"{fayl}: {blok.strip()[:70]}")
    check("tasdiqlandi qo'yadigan HAR BIR UPDATE tasdiq_ishonch ham qo'yadi",
          not nosoz, "; ".join(nosoz[:2]))

    # `servis` -- odam yo'q. Aktor izchilligi cheklovi unga
    # `tasdiq_actor_id IS NULL` ni talab qiladi.
    src = io.open(os.path.join(ROOT, "api", "catalog_auto.py"),
                  encoding="utf-8").read()
    check("avtomatik yo'l `servis` dalilini ishlatadi",
          "tasdiq_ishonch='servis'" in src.replace(" = ", "="))


def test_standart_qoida():
    bolim("4b. STANDART MOSLIK QOIDASI -- o'lchov bilan tanlangan")
    from api import atama
    from api import catalog_auto as C

    # 2026-09-12 O'LCHOVI (ishlab chiqarish, 1840 mahsulot):
    #     hozirgi        3 kod   0.2%      4 ochiq tender
    #     teskari      187 kod  10.2%   2154 ochiq tender
    #     qisqa_tomon  188 kod  10.2%   2156 ochiq tender  -> RAD (namunada
    #                                      ratsiya `Клавиатура` deb kodlandi)
    #     kamida2       23 kod   1.2%    290 ochiq tender
    check("standart qoida -- `teskari`", C.STANDART_QOIDA == "teskari")
    check("standart QOIDALAR ichida bor", C.STANDART_QOIDA in C.QOIDALAR)

    # O'LCHOVDA KO'RILGAN ANIQ HOLAT. Mahsulot nomi brend va modelni
    # olib yuradi, lot nomi esa bitta so'z. Eski qoida shuni rad etardi
    # va 1294 mahsulot (70.3%) aynan shu yerda yiqilardi.
    tok = C._tokens({"name": "PoE kommutator (switch) Swich KANIHAD 1006GB"})
    lot = set(atama.normal("Коммутатор").split())
    check("ESKI qoida `Коммутатор` ni RAD etardi",
          not C.QOIDALAR["hozirgi"](tok, lot), str(tok))
    check("YANGI qoida `Коммутатор` ni QABUL qiladi",
          C.QOIDALAR["teskari"](tok, lot), str(tok))

    # MA'LUM ZAIFLIK -- YASHIRILMAYDI. Qisqa lot nomi uzun mahsulot
    # nomi ichiga kirib ketadi, bosh so'z esa boshqa. Bu sinov xatoni
    # TO'G'RI deb tasdiqlamaydi; u zaiflik MAVJUDLIGINI qayd etadi,
    # toki keyingi o'quvchi uni kutilmagan hodisa deb o'ylamasin.
    tok2 = C._tokens({"name": "Server (telekommunikatsiya) shkafi 32U"})
    lot2 = set(atama.normal("Сервер").split())
    check("MA'LUM ZAIFLIK: server SHKAFI `Сервер` ga tushadi",
          C.QOIDALAR["teskari"](tok2, lot2), str(tok2))


def test_qolla_qorovuli():
    bolim("5. Kuchsiz dalil bandi avtomatik QO'LLANMAYDI")
    src = io.open(os.path.join(ROOT, "api", "catalog_auto.py"),
                  encoding="utf-8").read()
    # IKKALA yo'l ham (CRUD va ommaviy) shu yagona bayroqni o'qishi
    # kerak — aks holda bitta yo'l qattiq, ikkinchisi yumshoq bo'lardi.
    check("`classify_product` bandni hurmat qiladi",
          'natija.get("kuchsiz_dalil")' in src)
    check("bandda `review` holati qaytadi", '"status": "review"' in src)
    cli = io.open(os.path.join(ROOT, "catalog_kodla.py"), encoding="utf-8").read()
    check("ommaviy qo'llash bandni chetlab o'tmaydi",
          "NOT t.kuchsiz_dalil" in cli)
    check("ommaviy qo'llash `classify_product` ni chaqiradi "
          "(mantiq takrorlanmaydi)", "classify_product(" in cli)
    check("standart QURUQ emas, TAHLIL", "--tahlil" in cli and "--qolla" in cli)


# =====================================================================
def test_avtomatik_yol_tugadi(db):
    """Avtomatik kodlash CHEGARANI CHETLAB O'TMAYDI (Q-3)."""
    bolim("6. Avtomatik yo'l — chegara PASAYTIRILMAGAN")

    # O'LCHANGAN (2026-09-01). Reyestrda Q-3 "749 mahsulot kodsiz
    # (41.7%)" deb yozilgan edi. Qayta tahlil YURGIZILDI (585 s,
    # 1 797 mahsulot) va natija AYNAN o'sha chiqdi — ya'ni yangi
    # dalil to'planmagan va chegarani pasaytirmasdan qo'shimcha
    # kod berib bo'lmaydi.
    #
    # Qo'llash quruq yurgizilganda: 0 ta nomzod. Avtomatik yo'l
    # TUGAGAN.
    #
    # BU NUQSON EMAS — bu ATAYLAB tanlangan aniqlik/qamrov
    # nuqtasi. Lekin u HECH QAYERDA tekshirilmasdi: kimdir
    # `KUCHSIZ_ISHONCH` ni pasaytirsa yoki `NOT t.kuchsiz_dalil`
    # shartini olib tashlasa, qamrov "o'sardi" va precision
    # JIMGINA yeyilardi.
    from api import catalog_auto as CA
    check("`MIN_EVIDENCE` = 2", CA.MIN_EVIDENCE == 2, str(CA.MIN_EVIDENCE))
    check("`MIN_SHARE` = 0.75", abs(CA.MIN_SHARE - 0.75) < 1e-9,
          str(CA.MIN_SHARE))
    check("`KUCHSIZ_ISHONCH` = 0.80", abs(CA.KUCHSIZ_ISHONCH - 0.80) < 1e-9,
          str(CA.KUCHSIZ_ISHONCH))
    check("`KUCHSIZ_DALIL` = 4", CA.KUCHSIZ_DALIL == 4, str(CA.KUCHSIZ_DALIL))

    if db is None:
        check("bazali tekshiruv", False, "o'tkazib yuborildi")
        return

    # HISOB IDENTITETI: taklif = avtomatik + navbatga.
    # Bu "kuchsiz dalil YO'QOLMADI" degani — u ham qo'llanmagan,
    # ham unutilmagan.
    r = db.query_one("SELECT * FROM v_catalog_kod_sifat WHERE company_id=2")
    if not r:
        check("sifat ko'rinishi bor", False, "company_id=2 topilmadi")
        return
    check("taklif = avtomatik + navbatga",
          r["taklif"] == r["avtomatik"] + r["navbatga"],
          f"{r['taklif']} vs {r['avtomatik']}+{r['navbatga']}")
    print(f"      taklif={r['taklif']} avtomatik={r['avtomatik']} "
          f"navbatga={r['navbatga']} o'rtacha_ishonch={r['ortacha_ishonch']}")

    # ENG MUHIM QO'RIQCHI: KUCHSIZ DALILLI mahsulotda AVTOMATIK
    # aniq kod BO'LMASLIGI kerak. Bo'lsa — band chetlab o'tilgan.
    buzuq = db.scalar("""
        SELECT count(*) FROM catalog_kod_tahlil t
          JOIN catalog_product_code c
            ON c.product_id=t.product_id AND c.company_id=t.company_id
         WHERE t.company_id=2 AND t.kuchsiz_dalil
           AND length(c.code) >= 8
           AND c.manba = 'taklif' AND c.tasdiqlandi IS NULL""")
    check("kuchsiz dalilga AVTOMATIK aniq kod berilmagan", buzuq == 0,
          f"{buzuq} ta — band chetlab o'tilgan")

    # NAVBAT BO'SH QOLMASIN: kuchsiz dalil qayergadir borishi kerak.
    navbat = db.scalar("SELECT count(*) FROM v_catalog_kod_navbat "
                       "WHERE company_id=2")
    check("ko'rib chiqish navbati BO'SH emas", (navbat or 0) > 0,
          f"{navbat} ta — kuchsiz dalil YO'QOLGAN bo'lardi")

    # SABABLAR JAMI mahsulot soniga TENG: hech bir mahsulot
    # tasnifdan tashqarida qolmasin.
    jami = db.scalar("SELECT count(*) FROM catalog_kod_tahlil WHERE company_id=2")
    sabablar = db.scalar("SELECT sum(soni) FROM v_catalog_kod_sabab "
                         "WHERE company_id=2")
    check("sabablar yig'indisi = tahlil qilingan mahsulot soni",
          int(sabablar or 0) == int(jami or 0), f"{sabablar} vs {jami}")


# =====================================================================
def test_baza(db):
    bolim("6. Tahlil bazada — sabab taqsimoti")
    from api import auth
    cid = auth.sole_company_id()
    rows = db.query("SELECT sabab, soni FROM v_catalog_kod_sabab "
                    "WHERE company_id=%(c)s ORDER BY soni DESC", {"c": cid})
    if not rows:
        check("tahlil yurgizilgan", False, "catalog_kodla.py --tahlil")
        return
    jami = sum(r["soni"] for r in rows)
    mahsulot = db.scalar("SELECT count(*) FROM catalog_product "
                         "WHERE company_id=%(c)s", {"c": cid})
    # SABABLAR JAMIGA TENG BO'LISHI SHART. Teng bo'lmasa — tahlildan
    # tashqarida qolgan mahsulot bor va u KO'RINMAY qolardi.
    check("sabablar jami mahsulot soniga TENG", jami == mahsulot,
          f"{jami} vs {mahsulot}")
    for r in rows:
        print(f"        {r['sabab']:<18}{r['soni']:>6}")

    bolim("7. ANIQLIK — haqiqiy inson yorlig'iga qarshi")
    # 960 ta keng kodni ODAM bergan. Bu sintetik yorliq EMAS.
    #
    # `v_catalog_code_active` EMAS, `catalog_product_code` o'qiladi:
    # aniq kod qo'llangach keng kod FAOLSIZLANTIRILADI va faol
    # ko'rinishdan chiqadi. Yorliq esa YO'QOLMAYDI — qator qoladi
    # (`tasdiqlandi=NULL`). Faol ko'rinishga tayanish yorliqni
    # o'z harakatimiz bilan yo'q qilardi va sinov jimgina
    # ma'nosiz bo'lib qolardi (bu HAQIQATAN sodir bo'ldi:
    # 383 juftlik 4 taga tushdi).
    r = db.query_one("""
        SELECT count(*) AS jami,
               count(*) FILTER (WHERE left(t.taklif_code,2)=left(v.code,2)) AS div_mos,
               count(*) FILTER (WHERE left(t.taklif_code,5)=v.code) AS toliq_mos
          FROM catalog_kod_tahlil t
          JOIN catalog_product_code v
            ON v.product_id=t.product_id AND v.company_id=t.company_id
           AND length(v.code)=5 AND v.tasdiqlagan <> 'tizim:auto'
         WHERE t.company_id=%(c)s AND t.sabab='kod'
    """, {"c": cid}) or {}
    jami = r.get("jami") or 0
    if jami < 20:
        check("solishtirish uchun yetarli juftlik", False, f"{jami} ta")
        return
    div = 100.0 * (r["div_mos"] or 0) / jami
    tol = 100.0 * (r["toliq_mos"] or 0) / jami
    # CHEGARA o'lchangan qiymatdan PAST qo'yilgan: oddiy siljish
    # sinovni yiqitmasin, HAQIQIY regressiya esa yiqitsin.
    # O'lchangan (2026-08-31): division 100.0%, to'liq 99.7%.
    check(f"division mosligi >= 98% ({div:.1f}%)", div >= 98.0,
          f"{r['div_mos']}/{jami}")
    check(f"to'liq 5-belgi mosligi >= 95% ({tol:.1f}%)", tol >= 95.0,
          f"{r['toliq_mos']}/{jami}")

    bolim("8. Kuchsiz band ajratilgan")
    s = db.query_one("SELECT * FROM v_catalog_kod_sifat WHERE company_id=%(c)s",
                     {"c": cid}) or {}
    check("taklif = avtomatik + navbatga",
          (s.get("taklif") or 0) == (s.get("avtomatik") or 0) + (s.get("navbatga") or 0),
          f"{s.get('taklif')} = {s.get('avtomatik')} + {s.get('navbatga')}")
    check("kuchsiz band BO'SH EMAS (ajratish ishlayapti)",
          (s.get("navbatga") or 0) > 0, str(s.get("navbatga")))
    # Kuchsiz band KICHIK bo'lishi kerak — u katta bo'lsa chegara
    # noto'g'ri joyda demakdir.
    ulush = 100.0 * (s.get("navbatga") or 0) / max(s.get("taklif") or 1, 1)
    check(f"kuchsiz band kichik (<20%, hozir {ulush:.1f}%)", ulush < 20.0)

    bolim("9. Baza cheklovlari")
    def rad(sql, p):
        try:
            db.execute_returning(sql, p)
            return False
        except Exception:                                     # noqa: BLE001
            return True
    pid = db.scalar("SELECT id FROM catalog_product WHERE company_id=%(c)s "
                    "ORDER BY id DESC LIMIT 1", {"c": cid})
    check("`kod` sababi DALILSIZ yozilmaydi",
          rad("INSERT INTO catalog_kod_tahlil(company_id,product_id,sabab,"
              "taklif_code,ishonch,dalil,jami) VALUES(%(c)s,%(p)s,'kod',"
              "NULL,NULL,0,0)", {"c": cid, "p": pid}))
    check("noma'lum sabab rad etiladi",
          rad("INSERT INTO catalog_kod_tahlil(company_id,product_id,sabab) "
              "VALUES(%(c)s,%(p)s,'bilmadim')", {"c": cid, "p": pid}))
    check("ishonch 1 dan katta bo'la olmaydi",
          rad("INSERT INTO catalog_kod_tahlil(company_id,product_id,sabab,"
              "ishonch) VALUES(%(c)s,%(p)s,'noaniq',1.5)",
              {"c": cid, "p": pid}))

    bolim("10. Qamrov ANIQ va KENG kodni ajratadi")
    q = db.query_one("SELECT * FROM v_catalog_kod_qamrov WHERE company_id=%(c)s",
                     {"c": cid}) or {}
    check("qamrov ko'rinishi qaytdi", bool(q))
    # ANIQ va KENG qo'shilsa 26.40 chelagidagi 612 mahsulot "aniq
    # kodlangan" bo'lib ko'rinardi.
    check("`aniq_kod` va `keng_kod` ALOHIDA",
          "aniq_kod" in q and "keng_kod" in q)
    jami = (q.get("aniq_kod") or 0) + (q.get("keng_kod") or 0) + (q.get("kodsiz") or 0)
    check("aniq + keng + kodsiz = mahsulot", jami == (q.get("mahsulot") or 0),
          f"{jami} vs {q.get('mahsulot')}")
    print(f"        aniq={q.get('aniq_kod')}  keng={q.get('keng_kod')}  "
          f"kodsiz={q.get('kodsiz')}")


# =====================================================================
def test_provenans(db):
    """"Kodi bor" va "ISHONCHLI kodi bor" BIR RAQAMDA turmasin.

    O'LCHANGAN MUAMMO (2026-09-03). `v_catalog_kod_qamrov` ikki foiz
    beradi va ikkalasi ham ANIQLIKNI (kod 8 belgimi yoki 5) o'lchaydi,
    ISHONCHNI emas:

        aniq_foiz        25.97   (467 ta 8 belgili kod)
        har_qanday_foiz  58.29   (1 048 ta kodli mahsulot)

    Provenans o'lchanganda manzara TESKARI:

        tasdiqlagan='tizim:auto', ishonch='servis'            467
        tasdiqlagan='kompaniya',  ishonch='kuzatuvdan_oldin'  581
        ishonch IN ('erp_sessiya','aktor_elon')                 0

    Ya'ni `aniq_kod` — eng ishonchli to'plam kabi o'qiladi, aslida u
    100% MASHINA qo'ygan. Va ikki raqam TASODIFAN teng (25.97):
    467 ta "aniq" kod aynan 467 ta mashina kodining o'zi — shuning
    uchun "aniqlik" deb o'qilgan foiz aslida "mashina" degani edi.

    Bu sinov ikki o'lchov ARALASHMASLIGINI qulflaydi.
    """
    bolim("Provenans: aniqlik va ishonch ARALASHMAYDI")
    r = db.query_one("""
        SELECT * FROM v_catalog_kod_provenans
         WHERE company_id = (SELECT min(id) FROM company_account WHERE active)""")
    if not r:
        check("v_catalog_kod_provenans qatori bor", False, "faol ijarachi yo'q")
        return

    # QOLDIQSIZ TOIFALASH — sinflar o'zaro istisno va jamiga teng.
    yigindi = (r["kodsiz"] + r["rad_etilgan"] + r["nomzod"]
               + r["provenans_nomalum"] + r["mashina_tasdigi"]
               + r["anonim_tasdiq"] + r["inson_tasdigi"])
    check("sinflar yig'indisi mahsulot soniga TENG",
          yigindi == r["mahsulot"], f"{yigindi} != {r['mahsulot']}")

    # ASOSIY INVARIANT: qamrov va inson tasdig'i ALOHIDA raqam.
    check("`inson_foiz` `qamrov_foiz` dan ALOHIDA",
          r["inson_foiz"] <= r["qamrov_foiz"],
          f"inson={r['inson_foiz']} qamrov={r['qamrov_foiz']}")
    # Mashina tasdig'i INSON tasdig'i deb sanalmaydi.
    check("mashina tasdig'i `inson_tasdigi` ga QO'SHILMAYDI",
          r["inson_tasdigi"] == db.scalar("""
              SELECT count(DISTINCT product_id) FROM catalog_product_code
               WHERE tasdiq_ishonch IN ('erp_sessiya','aktor_elon')"""),
          f"inson_tasdigi={r['inson_tasdigi']}")

    # ANIQLIK — MUSTAQIL o'lchov, ishonch sinfiga bog'liq emas.
    check("`aniq_kodli` ishonch sinfidan MUSTAQIL ustun",
          r["aniq_kodli"] is not None and r["faqat_keng"] is not None)
    check("aniq + faqat_keng = kodli mahsulotlar",
          r["aniq_kodli"] + r["faqat_keng"] == r["mahsulot"] - r["kodsiz"],
          f"{r['aniq_kodli']}+{r['faqat_keng']} vs "
          f"{r['mahsulot'] - r['kodsiz']}")

    # DALIL: `qaror_id` bo'lmasa "qaysi qoida qo'ydi" javobsiz qoladi.
    check("`dalilli` ustuni BOR (dalilsizni yashirmaydi)",
          r["dalilli"] is not None, str(r["dalilli"]))


def main():
    ap = argparse.ArgumentParser(description="Katalog kodlash sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: KATALOG KODLASH — PRECISION QO'RIQCHISI")
    print("=" * 70)

    test_chegaralar()
    test_lugat()
    test_tokenlar()
    test_manba_qism_soz()
    test_standart_qoida()
    test_tasdiq_ishonch_majburiy()
    test_qolla_qorovuli()
    test_ommaviy_ochirish()
    test_ommaviy_ochirish_xulqi()
    test_tashxis_asbobi_yozmaydi()

    if args.bazasiz or not os.environ.get("XT_DB_DSN"):
        print("\n[i] Bazali tekshiruvlar o'tkazib yuborildi.")
    else:
        from api import db
        try:
            db.init_pool()
            test_avtomatik_yol_tugadi(db)
            test_baza(db)
            test_provenans(db)
        except Exception as e:                                # noqa: BLE001
            check("bazali tekshiruv", False, str(e)[:100])

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
