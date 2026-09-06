# -*- coding: utf-8 -*-
"""SINOV: MALAKA TEKSHIRUVI va BROKERGA YO'NALTIRISH.

Modelga CHIQMAYDI, PUL SARFLAMAYDI — ikkala modul ham deterministik.

Nima tekshiriladi:
  A. QARORNING MANBASI   — `go` musbat dalildan chiqadimi
  B. `is_mandatory`      — DARVOZA sifatida ishlatilmaydimi
  C. SINOV YORLIG'I      — natija bilan birga yuradimi
  D. NORMALLASHTIRISH    — uch alifbo (Литсензия / лицензия / litsenziya)
  E. YO'NALTIRISH        — inson qarori qayta yozilmaydimi
  F. IZOLYATSIYA         — har so'rovda `company_id` bormi
  G. O'LCHOVSIZLIK       — xulosaga aylanmaydimi
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

from dotenv import load_dotenv                              # noqa: E402
load_dotenv(os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), ".env"))

from api import compliance, db, qualification as Q, routing as R  # noqa: E402

PASS = FAIL = 0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: `is_mandatory` DARVOZA sifatida ishlatilganini topadigan naqsh.
#:
#: KENGAYTIRILDI — birinchi shakli (`is_mandatory\s*(=|==|IS|AND|WHERE)`)
#: ikkita haqiqiy buzilishni O'TKAZIB YUBORARDI:
#:
#:     if r['is_mandatory'] == True:          indeks ustunni ajratardi
#:     [x for x in t if x['is_mandatory']]    YALANG'OCH rostlik
#:
#: Ikkinchisi eng ehtimoli. Endi naqsh nomdan KEYINGI qavsni ham,
#: `if`/`filter` ichidagi yalang'och ishlatishni ham tutadi.
MANDATORY_NAQSH = (
    r"(?:"
    r"is_mandatory[\"'\]\s]*\s*(?:=|==|!=|IS\b|AND\b|OR\b)"   # taqqoslash
    r"|WHERE[^\n]*is_mandatory"                                  # SQL sharti
    r"|\bif\b[^\n]*is_mandatory"                                # if sharti
    r"|\bfilter\b[^\n]*is_mandatory"                            # filter()
    r"|\bnot\s+[\w\[\]\"'.]*is_mandatory"                      # not x[...]
    r")"
)
_yozilgan = []          # routing id lari — oxirida tozalanadi

#: SINOV QARORLARINING BELGISI.
#:
#: `tozala()` faqat shu yurishda yozilgan id larni o'chiradi. Yurish
#: O'LDIRILSA (Ctrl+C, seans uzilishi) qoldiq qoladi va uni haqiqiy
#: ma'lumotdan ajratadigan hech narsa bo'lmaydi. Amalda shunday
#: bo'ldi: bitta yozuv qolib, `v_routing_agreement` "moslik 100%"
#: ko'rsatdi.
#:
#: Endi har sinov qarori shu nom bilan yoziladi va tozalash BOSHDA
#: ham yuradi.
_BROKER = "ZZTEST-sinov"


def check(nom: str, shart: bool, izoh: str = "") -> None:
    global PASS, FAIL
    if shart:
        PASS += 1
        print(f"  OK   {nom}")
    else:
        FAIL += 1
        print(f"  XATO {nom}" + (f"\n       {izoh}" if izoh else ""))


def section(t: str) -> None:
    print(f"\n=== {t} ===")


def _cid() -> int:
    """Navbati eng katta kompaniya.

    `ORDER BY id LIMIT 1` NOTO'G'RI bo'lardi: birinchi kompaniyaning
    navbatida talab yo'q va butun sinov bo'sh ma'lumot ustida
    yurardi — ya'ni hech narsani o'lchamasdi.
    """
    return db.scalar("""SELECT company_id FROM v_requirement_review
                        GROUP BY company_id ORDER BY count(*) DESC LIMIT 1""")


# =====================================================================
def test_qaror_manbasi():
    """A. `go` MUSBAT dalildan chiqsin, "to'siq topilmadi" dan emas.

    Bu loyihada uch marta takrorlangan sinf (§16.58): muvaffaqiyat
    signali salbiy shartdan olinadi va signalning o'zi tekshirilmaydi.
    Malaka tekshiruvida bu eng xavfli shaklda bo'lardi — profil bo'sh
    bo'lgan kompaniya HAR tenderga "malakali" chiqardi.
    """
    section("A. Qarorning manbasi")

    src = io.open(os.path.join(ROOT, "api", "qualification.py"),
                  encoding="utf-8").read()
    check("`go` uchun MINIMAL `ok` soni belgilangan",
          "GO_MIN_OK" in src and "n_ok >= GO_MIN_OK" in src,
          "`go` faqat `fail` yo'qligidan chiqmasin")

    # HECH NARSA O'LCHANMAGAN holat: barcha mezon `malumot_yoq`.
    bosh = {"decision": None, "criteria": [
        {"key": k, "label": k, "status": "malumot_yoq", "izoh": "", "dalillar": []}
        for k in [c["key"] for c in Q.CRITERIA]]}
    n_ok = sum(1 for m in bosh["criteria"] if m["status"] == "ok")
    check("nol o'lchovda `ok` soni nol", n_ok == 0)

    # Haqiqiy tenderda tekshiramiz.
    cid = _cid()
    tid = db.scalar("""SELECT tender_id FROM v_requirement_review
                       WHERE company_id = %(c)s LIMIT 1""", {"c": cid})
    r = Q.check(tid, cid)
    check("qaror ro'yxatdan", r["decision"] in Q.DECISIONS, r["decision"])
    check("o'lchangan mezon soni qaytariladi", "olchandi" in r)
    check("o'lchanmagan mezon `ok` ga qo'shilmaydi",
          r["ok"] + r["fail"] + r["risk"] == r["olchandi"],
          f"ok={r['ok']} fail={r['fail']} risk={r['risk']} "
          f"olchandi={r['olchandi']}")

    # BALL maxraji — o'lchangan mezonlar, JAMI emas.
    b = R._ball({"ok": 3, "olchandi": 3, "jami_mezon": 7})
    check("ball maxraji O'LCHANGAN mezon", b == 1.0, str(b))
    b0 = R._ball({"ok": 0, "olchandi": 0, "jami_mezon": 7})
    check("nol o'lchovda ball 0", b0 == 0.0, str(b0))

    # QAMROV sababda ko'rinsin: `3/3 o'tdi` + `ball 1.000` "mukammal"
    # deb o'qiladi, holbuki 4 mezon umuman o'lchanmagan.
    out = R.yonaltir(tid, cid, barchasi=True)
    if out:
        _yozilgan.append(out["routing_id"])
        row = db.query_one("SELECT ai_sabab FROM tender_routing "
                           "WHERE id = %(i)s", {"i": out["routing_id"]})
        olchanmadi = out["jami_mezon"] - out["olchandi"]
        if olchanmadi:
            check("sabab O'LCHANMAGAN mezonni aytadi",
                  "O'LCHANMADI" in (row["ai_sabab"] or ""),
                  row["ai_sabab"])


# =====================================================================
def test_is_mandatory_darvoza_emas():
    """B. `is_mandatory` DARVOZA sifatida ishlatilmasin.

    Bazadagi HAMMA qatorda u `False` (naqsh majburiylikni ajrata
    olmaydi, LLM qatlami bloklangan). `WHERE is_mandatory` shartli
    darvoza HAMMA NARSANI JIMGINA o'tkazardi va ishlayotgandek
    ko'rinardi.
    """
    section("B. `is_mandatory` mina")

    n_true = db.scalar("SELECT count(*) FROM tender_requirement "
                       "WHERE is_mandatory")
    n_all = db.scalar("SELECT count(*) FROM tender_requirement")
    check("bazada `is_mandatory` HALI HAM hammasi False",
          n_true == 0, f"{n_true}/{n_all} true")
    if n_true:
        print("       [i] LLM qatlami yurgan bo'lsa bu sinov yangilansin")

    for nom in ("qualification.py", "routing.py"):
        src = io.open(os.path.join(ROOT, "api", nom), encoding="utf-8").read()
        kod = "\n".join(x for x in src.split("\n")
                        if not x.lstrip().startswith("#"))
        # Docstring'dagi tushuntirish hisoblanmaydi — faqat KOD.
        kod = re.sub(r'"""[\s\S]*?"""', "", kod)
        check(f"{nom} `is_mandatory` ni FILTR qilmaydi",
              not re.search(MANDATORY_NAQSH, kod, re.I),
              "hamma qator False — bunday filtr hech narsani to'smaydi")

    # --- SKANERNI SINAYMIZ ---
    #
    # Loyihada qoida bor: salbiy sinovlar (xato KUTILGAN holatlar)
    # qulflansin — ular jimgina "o'tib" ketishi eng oson. Bu skaner
    # o'sha qoidasiz yozilgan edi va IKKI shaklni o'tkazib yuborardi:
    #
    #     if r['is_mandatory'] == True:            <- indeks aralashgan
    #     [x for x in t if x['is_mandatory']]      <- YALANG'OCH rostlik
    #
    # Ikkinchisi eng ehtimoli — darvozani odam aynan shunday yozadi.
    for yomon in (
            "WHERE is_mandatory AND tur = 'x'",              # skaner-namuna
            "if r['is_mandatory'] == True:",                 # skaner-namuna
            "AND r.is_mandatory IS TRUE",                    # skaner-namuna
            "kerak = [x for x in t if x['is_mandatory']]",   # skaner-namuna
            'if row["is_mandatory"]:',                       # skaner-namuna
            "filter(lambda r: r.is_mandatory, rows)",        # skaner-namuna
    ):
        check(f"skaner TUTADI: {yomon[:42]}",
              bool(re.search(MANDATORY_NAQSH, yomon, re.I)), yomon)

    # TO'G'RI uslub tutilmasin — aks holda skaner ishni to'sardi.
    for yaxshi in (
            "d['tasdiqlanmagan'] = not tasdiq",               # skaner-namuna
            "# `is_mandatory` ga tayanmaymiz",                # skaner-namuna
            'SELECT id, name FROM tender_requirement',        # skaner-namuna
    ):
        check(f"skaner TUTMAYDI: {yaxshi[:42]}",
              not re.search(MANDATORY_NAQSH, yaxshi, re.I), yaxshi)


# =====================================================================
def test_sinov_yorligi():
    """C. SINOV MA'LUMOTI yorlig'i natija bilan BIRGA yursin.

    Profil o'ylab topilgan qiymatlar bilan to'ldirilgan. "147 ta
    tender navbatda" degan raqam SHU qiymatlarni o'lchaydi. Yorliq
    yo'qolsa, olti oydan keyin uni haqiqiy deb o'qishardi — katalog
    sun'iy to'ldirilmagani bilan bir xil sabab (§16.6).
    """
    section("C. Sinov ma'lumoti yorlig'i")

    cid = _cid()
    tid = db.scalar("""SELECT tender_id FROM v_requirement_review
                       WHERE company_id = %(c)s LIMIT 1""", {"c": cid})
    r = Q.check(tid, cid)
    prof = db.query_one("SELECT is_sample, sample_note FROM company_profile "
                        "WHERE company_id = %(c)s", {"c": cid}) or {}
    check("natijada `is_sample` bor", "is_sample" in r)
    check("yorliq PROFILDAN keladi",
          r["is_sample"] == bool(prof.get("is_sample")),
          f"natija={r['is_sample']} profil={prof.get('is_sample')}")

    # BAZA CHEKLOVI: bayroq yoqilgan bo'lsa izoh bo'sh qolmasin.
    xato = None
    try:
        db.execute_returning(
            "UPDATE company_profile SET is_sample = true, sample_note = NULL "
            "WHERE company_id = %(c)s RETURNING company_id", {"c": cid})
    except Exception as e:                                  # noqa: BLE001
        xato = type(e).__name__
    check("izohsiz `is_sample` BAZA darajasida rad etiladi",
          xato is not None, "izoh emas, CHEKLOV himoya qilsin")

    if prof.get("is_sample"):
        out = R.yonaltir(tid, cid, barchasi=True)
        if out:
            _yozilgan.append(out["routing_id"])
            row = db.query_one("SELECT ai_sabab FROM tender_routing "
                               "WHERE id = %(i)s", {"i": out["routing_id"]})
            check("yorliq YO'NALTIRISH sababiga ham tushadi",
                  "SINOV" in (row["ai_sabab"] or "").upper(),
                  row["ai_sabab"])

    # TO'LIQLIK ko'rinishi SON qaytarsin, NULL emas.
    check("profil to'liqligi NULL emas",
          not db.query("SELECT 1 FROM v_profile_completeness "
                       "WHERE toldirilgan IS NULL"),
          "bo'sh massiv butun yig'indini NULL qilardi")


# =====================================================================
def test_normallashtirish():
    """D. UCH ALIFBO — 'Литсензия', 'лицензия', 'litsenziya'.

    Bu loyihada TO'RT marta takrorlangan xato sinfi. Shuning uchun
    `qualification` o'z lug'atini YOZMAYDI, `compliance.match_doc_type()`
    ni chaqiradi — ikkinchi nusxa jimgina ajralib ketardi.
    """
    section("D. Uch alifbo")

    for matn, kutilgan in [
        ("Литсензия", "license"),            # o'zbekcha kirill
        ("лицензия", "license"),             # ruscha
        ("litsenziya", "license"),           # lotin
        ("Muvofiqlik sertifikati", "conformity_certificate"),
        ("Kafolat xati", "guarantee_letter"),
    ]:
        check(f"'{matn}' -> {kutilgan}",
              compliance.match_doc_type(matn) == kutilgan,
              str(compliance.match_doc_type(matn)))

    src = io.open(os.path.join(ROOT, "api", "qualification.py"),
                  encoding="utf-8").read()
    check("qualification O'Z lug'atini yozmaydi",
          "match_doc_type" in src and "DOC_TYPES = [" not in src,
          "ikkinchi nusxa jimgina ajralib ketardi")


# =====================================================================
def test_yonaltirish():
    """E. INSON QARORI qayta yozilmasin."""
    section("E. Yo'naltirish")

    cid = _cid()
    tid = db.scalar("""SELECT tender_id FROM v_requirement_review
                       WHERE company_id = %(c)s LIMIT 1""", {"c": cid})
    out = R.yonaltir(tid, cid, barchasi=True)
    check("yo'naltirish yozuvi yaratildi", out and out["routing_id"],
          str(out)[:120] if out else "None")
    rid = out["routing_id"]
    _yozilgan.append(rid)

    # IDEMPOTENT: o'zgarmagan baholash `updated_at` ni surmasin, aks
    # holda navbat har soat "yangilangan" bo'lib ko'rinardi.
    oldin = db.query_one("SELECT updated_at FROM tender_routing "
                         "WHERE id = %(i)s", {"i": rid})["updated_at"]
    R.yonaltir(tid, cid, barchasi=True)
    keyin = db.query_one("SELECT updated_at FROM tender_routing "
                         "WHERE id = %(i)s", {"i": rid})["updated_at"]
    check("o'zgarmagan baho `updated_at` ni SURMAYDI", oldin == keyin,
          f"{oldin} -> {keyin}")

    # OCHILDI -> QAROR -> qayta ochilmaydi
    check("navbatdagi yozuv ochiladi", bool(R.ochildi(rid, cid, _BROKER)))
    q = R.qaror(rid, cid, "olindi", "sinov", ishonch="kompaniya_sessiyasi")
    check("broker qarori yozildi", q and q["inson_qaror"] == "olindi", str(q))
    check("holat 'yopildi'", q and q["holat"] == "yopildi")
    check("yopilgan yozuv QAYTA OCHILMAYDI",
          R.ochildi(rid, cid) is None,
          "qaror berilgan yozuv qayta ochilsa hisobot buzilardi")

    # AI QARORI inson qarorini QAYTA YOZMAYDI.
    R.yonaltir(tid, cid, barchasi=True)
    row = db.query_one("SELECT ai_qaror, inson_qaror, holat FROM tender_routing "
                       "WHERE id = %(i)s", {"i": rid})
    check("qayta baholash INSON QARORINI o'chirmaydi",
          row["inson_qaror"] == "olindi", str(row))
    check("qayta baholash holatni ORQAGA qaytarmaydi",
          row["holat"] == "yopildi", str(row))

    # NOMA'LUM qaror rad etilsin.
    xato = None
    try:
        R.qaror(rid, cid, "bilmadim", ishonch="kompaniya_sessiyasi")
    except ValueError as e:
        xato = str(e)
    check("noma'lum qaror rad etiladi", xato is not None, str(xato))

    # NAVBAT faqat OCHIQ tenderlarni bersin.
    yopiq = db.scalar("""SELECT count(*) FROM v_routing_queue q
        JOIN tender t ON t.id = q.tender_id
        WHERE t.close_at IS NOT NULL AND t.close_at <= now()""")
    check("navbatda MUDDATI O'TGAN tender yo'q", yopiq == 0, str(yopiq))


# =====================================================================
def test_qaror_eskirishi():
    """H. INSON QARORI ESKIRGANINI bilib turadimi.

    HAQIQIY XAVF: broker "olindi" deb qaror beradi. Ertasiga hujjat
    qayta ajratiladi, yangi sertifikat talabi topiladi, `ai_qaror`
    `go` dan `no_go` ga o'tadi — va broker BUNDAN XABAR TOPMAYDI.

    Bu himoya `routing.py` izohida TASVIRLANGAN edi, lekin
    YOZILMAGAN: `grep ai_ozgardi` bitta natija bergan — o'sha
    izohning o'zi. Izoh himoya emas (§16.58).
    """
    section("H. Qaror eskirishi")

    cid = _cid()
    # OCHIQ tender SHART: `v_routing_queue` yopilganini ko'rsatmaydi
    # va sinov "navbatda ko'rinmadi" deb KOD XATOSI EMAS, TASODIF
    # tufayli yiqilardi. Aynan shunday bo'ldi — tanlangan tender
    # o'sha kuni ertalab yopilgan edi (7-sinf).
    tid = db.scalar("""SELECT v.tender_id FROM v_requirement_review v
        JOIN tender t ON t.id = v.tender_id
        WHERE v.company_id = %(c)s
          AND (t.close_at IS NULL OR t.close_at > now())
          AND NOT EXISTS (
            SELECT 1 FROM tender_routing r
             WHERE r.company_id = v.company_id
               AND r.tender_id = v.tender_id) LIMIT 1""", {"c": cid})
    if not tid:
        check("sinov uchun OCHIQ tender topildi", False,
              "navbatda bo'sh joy yo'q — eskirish tekshirilmadi")
        return

    out = R.yonaltir(tid, cid, barchasi=True)
    rid = out["routing_id"]
    _yozilgan.append(rid)

    # 1. Inson qaror beradi.
    R.qaror(rid, cid, "olindi", "sinov", ishonch="kompaniya_sessiyasi")
    row = db.query_one("SELECT ai_qaror, ai_ozgardi FROM tender_routing "
                       "WHERE id = %(i)s", {"i": rid})
    check("qarordan keyin bayroq TOZA", row["ai_ozgardi"] is False,
          str(row))

    # 2. AI qarori QO'LDA o'zgartiriladi — keyingi baholash uni
    #    boshqacha ko'rgan holatni taqlid qiladi.
    boshqa = "no_go" if row["ai_qaror"] != "no_go" else "go"
    db.execute_returning(
        "UPDATE tender_routing SET ai_qaror = %(q)s WHERE id = %(i)s "
        "RETURNING id", {"q": boshqa, "i": rid})

    # 3. Qayta baholash — bayroq QO'YILISHI kerak.
    R.yonaltir(tid, cid, barchasi=True)
    row2 = db.query_one("""SELECT ai_qaror, ai_ozgardi, ai_qaror_eski,
        inson_qaror FROM tender_routing WHERE id = %(i)s""", {"i": rid})
    check("AI qarori o'zgarganda bayroq QO'YILADI",
          row2["ai_ozgardi"] is True, str(row2))
    check("ESKI qaror saqlanadi", row2["ai_qaror_eski"] == boshqa,
          f"kutilgan {boshqa}, keldi {row2['ai_qaror_eski']}")
    check("inson qarori TEGILMAYDI", row2["inson_qaror"] == "olindi")

    # 4. ESKIRGAN yozuv navbatga QAYTADI va TEPADA turadi.
    nav, _nav_jami = R.navbat(cid, limit=50)
    topildi = [i for i, x in enumerate(nav) if x["id"] == rid]
    check("eskirgan qaror navbatda ko'rinadi", bool(topildi),
          "aks holda broker uni boshqa ko'rmasdi")
    if topildi:
        check("eskirgan qaror TEPADA", topildi[0] == 0,
              f"{topildi[0]}-o'rinda — yolg'on ishonch eng shoshilinch")

    # 5. YANGI qaror bayroqni yopadi.
    R.qaror(rid, cid, "rad", "qayta ko'rildi", ishonch="kompaniya_sessiyasi")
    row3 = db.query_one("SELECT ai_ozgardi, ai_qaror_eski "
                        "FROM tender_routing WHERE id = %(i)s", {"i": rid})
    check("yangi qaror bayroqni YOPADI", row3["ai_ozgardi"] is False,
          str(row3))
    check("eski qaror ham tozalanadi", row3["ai_qaror_eski"] is None,
          "cheklov: NOT ai_ozgardi OR ai_qaror_eski IS NOT NULL")

    # 6. CHEKLOV BAZADA — bayroq eski qarorsiz yozilmasin.
    xato = None
    try:
        db.execute_returning(
            "UPDATE tender_routing SET ai_ozgardi = true, "
            "ai_qaror_eski = NULL WHERE id = %(i)s RETURNING id",
            {"i": rid})
    except Exception as e:                                  # noqa: BLE001
        xato = type(e).__name__
    check("eski qarorsiz bayroq BAZADA rad etiladi", xato is not None,
          "izoh emas, CHEKLOV himoya qilsin")


# =====================================================================
def test_izolyatsiya():
    """F. Har so'rovda `company_id` bo'lsin — IDOR himoyasi."""
    section("F. Izolyatsiya")

    cid = _cid()
    boshqa = db.scalar("SELECT id FROM company_account WHERE id <> %(c)s "
                       "ORDER BY id LIMIT 1", {"c": cid})
    rid = db.scalar("SELECT id FROM tender_routing WHERE company_id = %(c)s "
                    "LIMIT 1", {"c": cid})
    if boshqa and rid:
        check("BOSHQA kompaniya yozuvni ocholmaydi",
              R.ochildi(rid, boshqa) is None)
        check("BOSHQA kompaniya qaror bera olmaydi",
              R.qaror(rid, boshqa, "olindi", ishonch="kompaniya_sessiyasi") is None)

    for nom in ("qualification.py", "routing.py"):
        src = io.open(os.path.join(ROOT, "api", nom), encoding="utf-8").read()
        sorovlar = re.findall(r'"""\s*\n?(SELECT|UPDATE|INSERT)[\s\S]*?"""', src)
        n_sorov = len(re.findall(r"(SELECT|UPDATE|INSERT)\s", src))
        n_cid = src.count("company_id")
        check(f"{nom} da `company_id` keng ishlatiladi",
              n_cid >= n_sorov / 2,
              f"{n_cid} ta company_id, ~{n_sorov} ta so'rov")


# =====================================================================
def test_olchovsizlik():
    """G. O'LCHOVSIZLIK XULOSAGA AYLANMASIN.

    "Moslik 0%" va "hali o'lchanmagan" BOSHQA-BOSHQA narsa. Birinchisi
    modelni ayblaydi, ikkinchisi rost gapiradi.
    """
    section("G. O'lchovsizlik")

    cid = _cid()
    m = R.moslik(cid)
    check("moslik hisoboti qaytadi", isinstance(m, dict))
    check("o'lchanganmi degan bayroq bor", "olchandi" in m, str(m)[:100])

    # BITTA QARORDAN FOIZ CHIQMASIN.
    #
    # O'LCHANGAN XATO: bazada bitta sinov yozuvi qolgan edi va
    # interfeys "Moslik (1 qaror bo'yicha): no_go: 100%" ko'rsatdi.
    # Bitta kuzatuvdan foiz chiqarish statistika emas — u haqiqiy
    # o'lchov kabi ko'rinadi va shuning uchun zararli.
    check("moslik uchun MINIMAL qaror soni belgilangan",
          R.MOSLIK_MIN >= 10, str(R.MOSLIK_MIN))
    if m["inson_qarorlari"] < R.MOSLIK_MIN:
        check("yetarli qaror yo'q -> `olchandi` False",
              m["olchandi"] is False,
              f"{m['inson_qarorlari']} qaror, kerak {R.MOSLIK_MIN}")
        check("yetarli qaror yo'q -> FOIZ berilmaydi",
              m["qatorlar"] == [],
              f"{len(m['qatorlar'])} qator qaytdi")
        check("izoh sababni AYTADI", bool(m["izoh"]), str(m["izoh"])[:90])
        check("izohda qaror soni ko'rinadi",
              str(m["inson_qarorlari"]) in (m["izoh"] or ""),
              str(m["izoh"])[:90])

    # VALYUTA mos kelmasa TAXMIN QILINMASIN.
    src = io.open(os.path.join(ROOT, "api", "qualification.py"),
                  encoding="utf-8").read()
    check("valyuta farqi `malumot_yoq` beradi",
          "Valyutalar har xil" in src,
          "kurs bu modulning ishi emas — taxmin qilinmasin")

    # TAJRIBA — QOIDANI tekshiramiz, HOLATNI emas.
    #
    # Avval sinov `status == 'malumot_yoq'` deb yozilgan edi. U ESKI
    # XULQNI qulflab qo'yardi: tender tomonida ajratgich paydo
    # bo'lishi bilan sinov yiqilardi, garchi kod TO'G'RI ishlagan
    # bo'lsa ham. Qoida esa o'zgarmaydi: TALAB YO'Q bo'lsa `ok`
    # BERILMAYDI — to'siq yo'qligi malaka emas.
    tekshirildi = 0
    for tid in [x["tender_id"] for x in db.query(
            """SELECT tender_id FROM v_requirement_review
               WHERE company_id = %(c)s LIMIT 25""", {"c": cid})]:
        r = Q.check(tid, cid)
        taj = next(m for m in r["criteria"] if m["key"] == "tajriba")
        bor = any(d for d in taj["dalillar"])
        if not bor:
            tekshirildi += 1
            if taj["status"] == "ok":
                check("talabsiz tajriba `ok` BO'LMAYDI", False,
                      f"tender {tid}: {taj['izoh']}")
                break
    else:
        check("talabsiz tajriba `ok` BO'LMAYDI", True,
              f"{tekshirildi} ta tenderda tekshirildi")
    check("tajriba mezoni dalil qaytaradi",
          "dalillar" in next(m for m in Q.check(
              db.scalar("""SELECT tender_id FROM v_requirement_review
                           WHERE company_id = %(c)s LIMIT 1""", {"c": cid}),
              cid)["criteria"] if m["key"] == "tajriba"))


# =====================================================================
def test_http():
    """I. ENDPOINTLAR HTTP ORQALI ishlaydimi.

    Modul sinovi `routing.navbat()` ni to'g'ridan-to'g'ri chaqiradi —
    u `company_id_of()` ni, so'rov parametrlarini va javob shaklini
    UMUMAN sinamaydi. Ro'yxatda ko'ringan endpoint ishlayotganini
    bildirmaydi (3-sinf).
    """
    section("I. HTTP")

    try:
        from fastapi.testclient import TestClient
        from api import auth as A
        from api.main import app
    except Exception as e:                                  # noqa: BLE001
        check("TestClient mavjud", False, str(e)[:120])
        return

    USER, PAROL = "zzbroker_test", "Zz!broker#2026"
    cur = db.query_one(A.ACC_BY_NAME_SQL, {"username": USER})
    if cur:
        A.update_account(cur["id"], {"active": True})
        A.set_password(cur["id"], PAROL)
        acc_id = cur["id"]
    else:
        acc_id = A.create_account(USER, "ZZBROKER MChJ", PAROL)["id"]

    # `base_url` HTTPS bo'lishi SHART: sessiya cookie'si `Secure`
    # bayrog'i bilan qo'yiladi va `http://testserver` da brauzer
    # (va TestClient) uni QAYTA YUBORMAYDI. Natijada kirish 200
    # bo'ladi-yu, keyingi har so'rov 401 chiqadi.
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/auth/login", json={"username": USER, "password": PAROL})
        check("kirish muvaffaqiyatli", r.status_code == 200,
              f"{r.status_code}: {r.text[:120]}")
        if r.status_code != 200:
            return
        # CSRF tokeni JAVOB TANASIDA emas, `HttpOnly` BO'LMAGAN
        # cookie'da keladi (`tai_csrf`) — brauzer JS uni shu yerdan
        # o'qiydi. Javobdan olishga urinish bo'sh satr berardi va
        # har o'zgartiruvchi so'rov 403 chiqardi.
        csrf = c.cookies.get("tai_csrf") or ""
        check("CSRF tokeni cookie'dan olindi", bool(csrf),
              "`tai_csrf` — HttpOnly EMAS, ataylab")
        bosh = {"X-CSRF-Token": csrf}

        # --- NAVBAT ---
        q = c.get("/routing/queue?limit=5")
        check("GET /routing/queue 200", q.status_code == 200,
              f"{q.status_code}: {q.text[:120]}")
        if q.status_code == 200:
            j = q.json()
            for maydon in ("items", "jami", "moslik"):
                check(f"javobda `{maydon}` bor", maydon in j, str(j)[:120])
            # IZOLYATSIYA: yangi hisobning navbati BO'SH bo'lishi kerak.
            check("YANGI hisob boshqa kompaniya navbatini KO'RMAYDI",
                  j["jami"] == 0,
                  f"{j['jami']} ta yozuv ko'rindi — IDOR!")
            # O'LCHOVSIZLIK xulosaga aylanmasin.
            check("moslik `olchandi` bayrog'ini qaytaradi",
                  "olchandi" in j["moslik"], str(j["moslik"])[:120])

        # --- NOMA'LUM HOLAT rad etilsin ---
        bad = c.get("/routing/queue?holat=bilmadim")
        check("noma'lum holat 400 beradi", bad.status_code == 400,
              f"{bad.status_code}: {bad.text[:100]}")

        # --- MALAKA ---
        tid = db.scalar("SELECT id FROM tender LIMIT 1")
        m = c.get(f"/tenders/{tid}/qualification")
        check("GET /tenders/{id}/qualification 200", m.status_code == 200,
              f"{m.status_code}: {m.text[:120]}")
        if m.status_code == 200:
            mj = m.json()
            for maydon in ("decision", "criteria", "olchandi",
                           "jami_mezon", "is_sample"):
                check(f"malaka javobida `{maydon}` bor", maydon in mj,
                      str(mj)[:120])
            check("mezonlar soni to'liq",
                  len(mj["criteria"]) == mj["jami_mezon"],
                  f"{len(mj['criteria'])} != {mj['jami_mezon']}")

        yoq = c.get("/tenders/999999999999/qualification")
        check("mavjud bo'lmagan tender 404", yoq.status_code == 404,
              f"{yoq.status_code}")

        # --- BOSHQA KOMPANIYA yozuvi (IDOR) ---
        begona = db.scalar("SELECT id FROM tender_routing "
                           "WHERE company_id <> %(c)s LIMIT 1", {"c": acc_id})
        if begona:
            o = c.post(f"/routing/{begona}/open", headers=bosh)
            check("BEGONA yozuvni ocholmaydi (404)", o.status_code == 404,
                  f"{o.status_code}: {o.text[:100]}")
            d = c.post(f"/routing/{begona}/decision",
                       json={"qaror": "olindi"}, headers=bosh)
            check("BEGONA yozuvga qaror bera olmaydi (404)",
                  d.status_code == 404, f"{d.status_code}: {d.text[:100]}")

        # --- NOMA'LUM QAROR ---
        oz = db.scalar("SELECT id FROM tender_routing "
                       "WHERE company_id = %(c)s LIMIT 1", {"c": acc_id})
        if oz:
            b = c.post(f"/routing/{oz}/decision",
                       json={"qaror": "bilmadim"}, headers=bosh)
            check("noma'lum qaror 400", b.status_code == 400,
                  f"{b.status_code}")

    # TestClient kontekstdan chiqqanda ilova `shutdown` ni bajaradi
    # va DB PULINI YOPADI — shuning uchun tozalash uchun uni qayta
    # ochamiz. Busiz sinov "DB pool ishga tushmagan" bilan yiqilardi.
    db.init_pool()
    db.execute_returning("DELETE FROM company_account WHERE id = %(i)s "
                         "RETURNING id", {"i": acc_id})


# =====================================================================
def test_navbat_nomzodlari():
    """I. NAVBAT NOMZODI "ko'rilmagan" EMAS, "dalili bor" bo'lsin.

    O'LCHANGAN NUQSON (2026-09-03). `yonaltir_hammasi` nomzodlarni
    `v_requirement_review` dan olardi. O'sha ko'rinishning TIRIK
    ta'rifi (`schema_patch_requirement_8.sql`) —
    `review_status = 'pending_review'`, ya'ni u "inson hali
    KO'RMAGAN talablar" ro'yxati, "brokerga nomzod" ro'yxati EMAS.

    IKKITA OQIBAT o'lchandi:

      1. `source='api'` (reyestr) qatorlari `extracted` bilan
         yoziladi — ko'rikka muhtoj emas. Faqat reyestr talabi bor
         tender navbatga HECH QACHON tushmasdi.
      2. Talablar tasdiqlangach tender ko'rinishdan chiqadi va
         BOSHQA qayta baholanmaydi — ya'ni inson halqasi ishlay
         boshlagan zahoti tenderlar yo'naltirishdan JIMGINA tusha
         boshlardi.

    Ikkalasi ham `grep` bilan ko'rinmasdi: so'rov sintaktik
    to'g'ri edi, xato MA'NODA edi.
    """
    section("I. Navbat nomzodlari")

    cid = _cid()

    # STRUKTURAVIY QULF: nomzod so'rovi ko'rik holatiga QAYTMASIN.
    src = io.open(os.path.join(ROOT, "api", "routing.py"),
                  encoding="utf-8").read()
    gavda = src[src.index("def yonaltir_hammasi"):]
    check("nomzod so'rovi `v_requirement_review` ga TAYANMAYDI",
          "v_requirement_review" not in gavda,
          "ko'rik ro'yxati nomzod ro'yxati EMAS")
    check("nomzod so'rovi `review_status` ni FILTRLAMAYDI",
          "review_status" not in R.SQL_NOMZODLAR
          and "review_status" not in R.SQL_NOMZOD_SONI)

    nomzod = {r["tender_id"] for r in db.query(
        R.SQL_NOMZODLAR, {"c": cid, "n": 100000})}
    check("nomzod ro'yxati bo'sh emas", len(nomzod) > 0, str(len(nomzod)))

    # --- 1) FAQAT REYESTR talabi bor tender ham nomzod bo'lsin -------
    faqat_reyestr = {r["tender_id"] for r in db.query("""
        SELECT DISTINCT r.tender_id FROM tender_requirement r
        JOIN tender t ON t.id = r.tender_id
        WHERE r.company_id = %(c)s
          AND (t.close_at IS NULL OR t.close_at > now())
          AND NOT EXISTS (SELECT 1 FROM tender_requirement d
                          WHERE d.company_id = r.company_id
                            AND d.tender_id = r.tender_id
                            AND d.source <> 'api')""", {"c": cid})}
    # O'LCHAB BO'LMASA — BU HAM NATIJA. Bo'sh to'plam ustida
    # "hammasi ichida" tekshiruvi HAR DOIM o'tadi va sinov hech
    # narsa isbotlamagan bo'lardi.
    check("o'lchov bazasi bor: faqat-reyestr tenderlari topildi",
          len(faqat_reyestr) > 0, f"{len(faqat_reyestr)} ta")
    check("FAQAT REYESTR talabi bor tender ham NOMZOD",
          faqat_reyestr <= nomzod,
          f"tashqarida qolgan: {sorted(faqat_reyestr - nomzod)[:5]}")

    # --- 2) KO'RIGI TUGAGAN tender navbatdan CHIQIB KETMASIN --------
    korigi_tugagan = {r["tender_id"] for r in db.query("""
        SELECT DISTINCT r.tender_id FROM tender_requirement r
        JOIN tender t ON t.id = r.tender_id
        WHERE r.company_id = %(c)s
          AND (t.close_at IS NULL OR t.close_at > now())
          AND NOT EXISTS (SELECT 1 FROM tender_requirement p
                          WHERE p.company_id = r.company_id
                            AND p.tender_id = r.tender_id
                            AND p.review_status = 'pending_review')""",
        {"c": cid})}
    check("o'lchov bazasi bor: ko'rigi tugagan tenderlar topildi",
          len(korigi_tugagan) > 0, f"{len(korigi_tugagan)} ta")
    check("KO'RIGI TUGAGAN tender ham NOMZOD bo'lib qoladi",
          korigi_tugagan <= nomzod,
          f"tashqarida qolgan: {sorted(korigi_tugagan - nomzod)[:5]}")

    # --- 3) ESKI ta'rif YANGISINING ICHIDA bo'lsin ------------------
    # Tuzatish KENGAYTIRISH bo'lishi kerak, ALMASHTIRISH emas:
    # ilgari navbatga tushadigan biror tender endi tushmay qolsa,
    # bu tuzatish emas, yangi nuqson bo'lardi.
    eski = {r["tender_id"] for r in db.query("""
        SELECT DISTINCT v.tender_id FROM v_requirement_review v
        JOIN tender t ON t.id = v.tender_id
        WHERE v.company_id = %(c)s
          AND (t.close_at IS NULL OR t.close_at > now())""", {"c": cid})}
    check("eski nomzodlarning HAMMASI saqlanib qoldi",
          eski <= nomzod, f"yo'qolgan: {sorted(eski - nomzod)[:5]}")
    print(f"       qamrov: {len(eski)} -> {len(nomzod)} "
          f"(+{len(nomzod - eski)})")

    # --- 4) MUDDATI O'TGAN tender nomzod BO'LMASIN ------------------
    yopiq = db.scalar("""
        SELECT count(*) FROM tender t
        WHERE t.id = ANY(%(ids)s)
          AND t.close_at IS NOT NULL AND t.close_at <= now()""",
        {"ids": list(nomzod)}) or 0
    check("nomzodlar orasida MUDDATI O'TGAN tender yo'q", yopiq == 0,
          str(yopiq))

    # --- 5) CHEGARA uch joyda BIR XIL bo'lsin ----------------------
    # Ilgari uch xil edi: `yonaltir_hammasi` 500, HTTP 500/le=2000,
    # `run_etl.py` 2000. Nomzodlar 584 ga chiqqach standart 500
    # ularning 84 tasini kesardi.
    import inspect
    std = inspect.signature(R.yonaltir_hammasi).parameters["limit"].default
    msrc = io.open(os.path.join(ROOT, "api", "main.py"),
                   encoding="utf-8").read()
    # AYNAN SHU endpoint'dan qidiriladi. `main.py` da oltita
    # `limit: int = Query(...)` bor va birinchisini olish BOSHQA
    # endpoint'ni o'lchardi — sinov "yiqildi" desa ham sababi
    # noto'g'ri joyda bo'lardi.
    i = msrc.index("def routing_refresh")
    http = re.search(r"limit: int = Query\((\d+), ge=1, le=(\d+)\)",
                     msrc[i:i + 400])
    check("standart chegara nomzodlar sonidan KATTA",
          std >= len(nomzod), f"standart={std}, nomzod={len(nomzod)}")
    check("`/routing/refresh` standarti modul standartiga TENG",
          http is not None and int(http.group(1)) == std,
          f"http={http.group(1) if http else '?'} modul={std}")


def test_hudud_yagona_qoida():
    """J. HUDUD QOIDASI BITTA JOYDA yozilsin.

    O'LCHANGAN NOMUVOFIQLIK (2026-09-03). Uch bo'lim hududga uch xil
    munosabatda edi:

        Sizga mos       profildagi cheklovni UMUMAN hisobga olmasdi
        Talablar/navbat uni QATTIQ `fail` sifatida qo'llardi

    Natijada katalogga mos 28 ta ochiq tenderdan 11 tasi broker
    navbatida yo'q edi va SABABI hech qayerda ko'rinmasdi. O'sha 11
    tasining hammasi bitta mezonda — `hudud` — yiqilgan va har biri
    boshqa viloyatda (Jizzax, Andijon, Farg'ona, Qoraqalpog'iston,
    Buxoro, Toshkent viloyati, Qashqadaryo, Namangan). Kompaniya
    profilida `regions = ['33.2137']` — `dim_area` da bu level 1,
    ya'ni to'g'ri viloyat kodi ("Toshkent shahri"), xato ma'lumot
    EMAS.

    Endi qoida `qualification.hudud_mos()` da — YAGONA manba.
    """
    section("J. Hudud qoidasi")

    # --- PREFIKS TUZOG'I ---------------------------------------------
    # Oddiy `startswith` `33.21` ni `33.2137` ga ham moslashtirardi,
    # ya'ni BOSHQA viloyat "mos" bo'lib chiqardi. Nuqta TALAB
    # QILINADI. Bu tuzoq kodda tuzatilgan, lekin hech narsa uni
    # qaytib kelishdan saqlamasdi.
    check("aynan mos", Q.hudud_mos("33.2137", ["33.2137"]) is True)
    check("ichki tuman ham mos",
          Q.hudud_mos("33.2137.2138.2142", ["33.2137"]) is True)
    check("PREFIKS TUZOG'I: `33.21` `33.2137` ni QAMRAMAYDI",
          Q.hudud_mos("33.2137", ["33.21"]) is False,
          "nuqtasiz prefiks boshqa viloyatni MOS deb ko'rsatardi")
    check("boshqa viloyat mos emas",
          Q.hudud_mos("33.711", ["33.2137"]) is False)
    check("bir nechta hududdan biri mos bo'lsa yetadi",
          Q.hudud_mos("33.711", ["33.2137", "33.711"]) is True)

    # O'LCHAB BO'LMAGANI "MOS EMAS" DEGANI EMAS.
    check("cheklov yo'q -> O'LCHAB BO'LMAYDI",
          Q.hudud_mos("33.711", []) is None)
    check("tender hududi noma'lum -> O'LCHAB BO'LMAYDI",
          Q.hudud_mos(None, ["33.2137"]) is None)

    # --- IKKI ISTE'MOLCHI BIR XIL JAVOB BERSIN ------------------------
    src = io.open(os.path.join(ROOT, "api", "main.py"),
                  encoding="utf-8").read()
    i = src.index("def catalog_match")
    gavda = src[i:src.index('@app.get("/catalog/new-count")')]
    check("`/catalog/match` YAGONA qoidani chaqiradi",
          "qualification.hudud_mos(" in gavda,
          "qoidaning ikkinchi nusxasi ajralib ketardi")
    check("`/catalog/match` qoidani QAYTA YOZMAYDI",
          "startswith" not in gavda,
          "hudud solishtiruvi shu yerda takrorlanmasin")
    # AYNAN `_hudud` GAVDASI olinadi — qat'iy belgilangan uzunlikdagi
    # oyna ("birinchi 400 belgi") funksiya o'sganda jimgina noto'g'ri
    # javob berardi va sinov o'zi yolg'on gapirardi.
    qsrc = io.open(os.path.join(ROOT, "api", "qualification.py"),
                   encoding="utf-8").read()
    h0 = qsrc.index("def _hudud")
    h1 = qsrc.index("\ndef ", h0 + 1)
    check("`_hudud` ham shu qoidaga tayanadi",
          "hudud_mos(" in qsrc[h0:h1],
          "malaka tekshiruvi qoidaning O'Z nusxasini ishlatmasin")

    # --- BELGI `fail` BILAN MOS TUSHSIN -------------------------------
    # HAQIQIY ma'lumot ustida: `hudud_tashqari` rost bo'lgan tender
    # malaka tekshiruvida ham `hudud` mezonida yiqilishi SHART.
    # Ikkisi ajralsa foydalanuvchi "belgisi yo'q, lekin navbatda ham
    # yo'q" tenderni ko'rardi — ya'ni belgi YOLG'ON tinchlik berardi.
    cid = _cid()
    regions = (db.query_one(Q.SQL_PROFIL, {"c": cid}) or {}).get("regions")
    check("o'lchov bazasi bor: profilda hudud cheklovi bor",
          bool(regions), f"regions={regions}")
    if not regions:
        return
    rows = db.query("""
        SELECT t.id, t.area_path FROM tender t
        WHERE (t.close_at IS NULL OR t.close_at > now())
          AND t.area_path IS NOT NULL AND t.area_path <> ''
        ORDER BY t.id LIMIT 60""")
    nomuvofiq = []
    tashqari = 0
    for r in rows:
        belgi = Q.hudud_mos(r["area_path"], regions) is False
        tashqari += belgi
        mezon = Q.check(r["id"], cid)
        yiqildi = any(m["key"] == "hudud" and m["status"] == "fail"
                      for m in mezon["criteria"])
        if belgi != yiqildi:
            nomuvofiq.append(r["id"])
    check("o'lchov bazasi bor: hududdan tashqaridagilar topildi",
          tashqari > 0, f"{tashqari}/{len(rows)}")
    check("BELGI va malaka `fail` i BIR XIL javob beradi",
          not nomuvofiq, f"ajralganlar: {nomuvofiq[:5]}")


def test_navbat_filtri():
    """K. NAVBAT FILTRI serverda va BOSH RO'YXAT BILAN BIR XIL qoidada.

    NEGA SERVERDA: navbat 180, sahifa 100. Mijoz tomonida filtrlash
    faqat olingan sahifaga tegardi va ikkinchi yuzlikdagi tender
    "topilmadi" bo'lib ko'rinardi — salbiy shartdan olingan yolg'on
    xulosa.

    NEGA QOIDA TAKRORLANMAYDI: `translit.variants()` lotin, kirill
    va o'zbek shakllarini kengaytiradi. Navbatda o'z `LIKE` ini
    yozish "bosh ro'yxatda topiladi, navbatda topilmaydi" holatini
    yasardi — hudud qoidasi bilan aynan shunday bo'lgan (J bo'limi).
    """
    section("K. Navbat filtri")

    cid = _cid()

    # STRUKTURAVIY: qidiruv YAGONA quruvchidan.
    src = io.open(os.path.join(ROOT, "api", "routing.py"),
                  encoding="utf-8").read()
    gavda = src[src.index("def _navbat_where"):src.index("SQL_NAVBAT_FROM")]
    check("qidiruv `queries.build_text_search` dan",
          "build_text_search(" in gavda)
    check("navbat o'z `LIKE` ini YOZMAYDI", "LIKE ANY" not in gavda,
          "qidiruv qoidasi ikki joyda ajralib ketardi")

    hammasi, jami0 = R.navbat(cid, limit=500)
    check("filtrsiz navbat bo'sh emas", jami0 > 0, str(jami0))
    if not jami0:
        return

    # --- JAMI SAHIFADAN MUSTAQIL -------------------------------------
    # Kesilganini interfeys shundan biladi. `len(items)` ni `jami`
    # deb yuborish "100 ta topildi" degan yolg'on berardi.
    kichik, jami_kichik = R.navbat(cid, limit=3)
    check("`jami` SAHIFA hajmiga bog'liq EMAS", jami_kichik == jami0,
          f"limit=3 -> jami={jami_kichik}, limit=500 -> jami={jami0}")
    check("sahifa chegarani hurmat qiladi", len(kichik) <= 3, str(len(kichik)))

    # --- QIDIRUV UCH ALIFBODA BIR XIL --------------------------------
    # ASOSIY TEKSHIRUV. Bosh ro'yxat "кабель" ni "kabel" so'rovida
    # topadi; navbat ham topishi SHART.
    nom = None
    for x in hammasi:
        if x["tender_name"] and len(x["tender_name"].split()) > 1:
            nom = x["tender_name"].split()[0]
            break
    check("o'lchov bazasi bor: qidiriladigan nom topildi", bool(nom), str(nom))
    if nom:
        _, j = R.navbat(cid, limit=500, q=nom)
        check("qidiruv natija beradi", j > 0, f"q={nom!r} -> {j}")
        check("qidiruv natijani TORAYTIRADI", j <= jami0, f"{j} <= {jami0}")
        _, j_katta = R.navbat(cid, limit=500, q=nom.upper())
        check("qidiruv REGISTRGA bog'liq emas", j == j_katta,
              f"{j} vs {j_katta}")

    # --- FILTRLAR TORAYTIRADI, KENGAYTIRMAYDI ------------------------
    for nomi, kw in (("holat=yangi", {"holat": "yangi"}),
                     ("qaror=go", {"qaror": "go"}),
                     ("faqat eskirgan", {"eskirgan": True})):
        _, j = R.navbat(cid, limit=500, **kw)
        check(f"{nomi} natijani toraytiradi", j <= jami0, f"{j} <= {jami0}")

    # Ikki filtr BIRGA — VA (AND) bog'lanishi kerak, YOKI emas.
    _, j_bir = R.navbat(cid, limit=500, holat="yangi")
    _, j_ikki = R.navbat(cid, limit=500, holat="yangi", qaror="go")
    check("ikki filtr VA bilan bog'lanadi", j_ikki <= j_bir,
          f"holat+qaror={j_ikki} > holat={j_bir}")

    # --- NOTO'G'RI QIYMAT JIMGINA O'TMASIN ---------------------------
    # E'tiborsiz qoldirilsa foydalanuvchi "filtr ishlamayapti" emas,
    # "natija yo'q" deb o'qirdi.
    for maydon, qiymat in (("holat", "yo'q"), ("qaror", "bilmadim")):
        tutildi = False
        try:
            R.navbat(cid, limit=5, **{maydon: qiymat})
        except Exception:                                   # noqa: BLE001
            tutildi = True
        check(f"noto'g'ri `{maydon}` RAD ETILADI", tutildi)

    # --- IZOLYATSIYA FILTR BILAN HAM SAQLANADI -----------------------
    begona = db.scalar("SELECT id FROM company_account WHERE id <> %(c)s "
                       "ORDER BY id LIMIT 1", {"c": cid})
    if begona:
        _, j_begona = R.navbat(begona, limit=500, q=nom or "a")
        oz = {x["tender_id"] for x in R.navbat(cid, limit=500, q=nom or "a")[0]}
        boshqa = {x["tender_id"] for x in R.navbat(begona, limit=500,
                                                   q=nom or "a")[0]}
        check("qidiruv BOSHQA ijarachining navbatini ochmaydi",
              not (oz & boshqa) or j_begona == 0,
              f"kesishma: {sorted(oz & boshqa)[:3]}")


def test_katalog_filtri():
    """L. "SIZGA MOS" FILTRI ro'yxatning O'ZI bilan bir xil to'plam.

    Foydalanuvchi da'vosi oddiy: "Sizga mos" da ko'ringan tender
    navbat filtrida ham chiqsin. Bu FAQAT to'plam ta'rifi bitta
    joyda bo'lsa bajariladi.

    XAVF O'LCHANGAN VA TAKRORLANGAN: hudud qoidasi ikki joyda
    yozilgani uchun "Sizga mos" va broker navbati boshqa-boshqa
    javob berardi (J bo'limi). Katalog to'plamini navbatda qayta
    hisoblash AYNAN o'sha xatoni takrorlardi — faqat bu safar
    sekinroq ajralardi (katalog kodlari vaqt o'tib o'zgaradi).
    """
    section("L. \"Sizga mos\" filtri")

    from api import kodlash

    cid = _cid()

    # STRUKTURAVIY: navbat o'z katalog moslashuvini YOZMASIN.
    src = io.open(os.path.join(ROOT, "api", "routing.py"),
                  encoding="utf-8").read()
    gavda = src[src.index("def navbat("):src.index("def ochildi")]
    check("navbat `kodlash.mos_tender_idlari()` ni chaqiradi",
          "mos_tender_idlari(" in gavda)
    check("navbat katalog moslashuvini QAYTA YOZMAYDI",
          "v_catalog_code_active" not in gavda and "good_code" not in gavda,
          "to'plam ta'rifi ikki joyda ajralib ketardi")

    # `/catalog/match` ham AYNI chegarani ishlatsin — ikki joyda
    # ikki xil `limit` bo'lsa ro'yxatda ko'ringan tender filtrda
    # chiqmasligi mumkin edi.
    msrc = io.open(os.path.join(ROOT, "api", "main.py"),
                   encoding="utf-8").read()
    cm = msrc[msrc.index("def catalog_match"):
              msrc.index('@app.get("/catalog/new-count")')]
    check("`/catalog/match` `kodlash.MOSLIK_LIMIT` dan foydalanadi",
          "kodlash.MOSLIK_LIMIT" in cm,
          "qotirilgan raqam ikki joyda ajralib ketardi")

    kat = kodlash.mos_tender_idlari(cid)
    check("o'lchov bazasi bor: katalogga mos tender topildi",
          len(kat) > 0, f"{len(kat)} ta")
    if not kat:
        return

    hammasi, jami0 = R.navbat(cid, limit=500)
    rows, jami = R.navbat(cid, limit=500, katalog=True)

    # --- QAYTGANLARNING HAMMASI KATALOGDA -----------------------------
    tashqari = [r["tender_id"] for r in rows if r["tender_id"] not in kat]
    check("filtr FAQAT katalogdagilarni qaytaradi", not tashqari,
          f"begona: {tashqari[:5]}")

    # --- KATALOGDAGI HAR TENDER, NAVBATDA BO'LSA, CHIQADI -------------
    # ASOSIY TEKSHIRUV — foydalanuvchi so'ragan xulq AYNAN shu:
    # "Sizga mos" dagi tender ro'yxatda mavjud bo'lsa, filtr uni
    # KO'RSATISHI kerak. Teskari yo'nalish (navbatda yo'q tender)
    # bu yerda tekshirilmaydi — u boshqa masala.
    navbatda = {r["tender_id"] for r in hammasi}
    kutilgan = kat & navbatda
    olingan = {r["tender_id"] for r in rows}
    check("navbatdagi HAR katalog tenderi filtrda CHIQADI",
          kutilgan <= olingan,
          f"tushib qolgan: {sorted(kutilgan - olingan)[:5]}")
    check("son ham mos", jami == len(kutilgan),
          f"jami={jami}, kutilgan={len(kutilgan)}")
    check("filtr natijani TORAYTIRADI", jami <= jami0, f"{jami} <= {jami0}")

    # --- BOSHQA FILTR BILAN BIRGA — VA (AND) ---------------------------
    _, j_ikki = R.navbat(cid, limit=500, katalog=True, holat="yangi")
    check("katalog + holat VA bilan bog'lanadi", j_ikki <= jami,
          f"{j_ikki} > {jami}")

    # --- KATALOGI YO'Q IJARACHI: BO'SH, "FILTRSIZ" EMAS ---------------
    # ENG XAVFLI XATO SHAKLI: bo'sh ro'yxat "filtr qo'llanmadi" ga
    # aylansa, foydalanuvchi BEGONA tenderlarni "sizga mos" deb
    # o'qirdi. Bo'sh massiv bilan `= ANY` FALSE berishi SHART.
    # NOMZOD JADVAL NOMI BO'YICHA EMAS, NATIJA bo'yicha topiladi:
    # katalog jadvalining nomini bu yerda takrorlash yana bitta
    # ajralib ketadigan bog'liqlik bo'lardi (`company_product`
    # deb yozilgan edi — bunday jadval YO'Q, `catalog_product` bor).
    begona = None
    for r in db.query("SELECT id FROM company_account "
                      "WHERE id <> %(c)s ORDER BY id LIMIT 10", {"c": cid}):
        if not kodlash.mos_tender_idlari(r["id"]):
            begona = r["id"]
            break
    check("o'lchov bazasi bor: katalogi bo'sh ijarachi topildi",
          begona is not None,
          "bunday ijarachi yo'q — bo'sh to'plam yo'li SINALMADI")
    if begona is not None:
        _, j_bosh = R.navbat(begona, limit=500, katalog=True)
        check("katalogi BO'SH ijarachida filtr NOL beradi", j_bosh == 0,
              f"{j_bosh} ta chiqdi — bo'sh to'plam 'filtrsiz' ga aylandi")


def qoldiqni_supur() -> int:
    """OLDINGI yurishdan qolgan sinov yozuvlarini o'chiradi.

    BOSHDA ham, OXIRIDA ham chaqiriladi. Boshda kerak, chunki
    o'ldirilgan yurish qoldiq qoldiradi va u `v_routing_agreement`
    ni ifloslantiradi.
    """
    n = 0
    while True:
        r = db.execute_returning(
            "DELETE FROM tender_routing WHERE broker_nomi = %(b)s "
            "RETURNING id", {"b": _BROKER})
        if not r:
            break
        n += 1
    return n


def tozala():
    n = 0
    for rid in set(x for x in _yozilgan if x):
        db.execute_returning("DELETE FROM tender_routing WHERE id = %(i)s "
                             "RETURNING id", {"i": rid})
        n += 1
    # SENTINEL bo'yicha ham: `_yozilgan` ga tushmay qolgan yozuv
    # bo'lishi mumkin (masalan `yonaltir_hammasi` qayta yaratsa).
    n += qoldiqni_supur()

    # MUSBAT TASDIQ: qoldiq HAQIQATAN qolmadimi.
    qoldi = db.scalar("SELECT count(*) FROM tender_routing "
                      "WHERE broker_nomi = %(b)s", {"b": _BROKER}) or 0
    check("sinov qoldig'i qolmadi", qoldi == 0, f"{qoldi} ta yozuv")
    print(f"\nTozalandi: {n} ta yo'naltirish yozuvi. "
          f"Navbatda qolgan: {db.scalar('SELECT count(*) FROM tender_routing')}")


def main() -> None:
    print("=" * 62)
    print("MALAKA + YO'NALTIRISH — modelga chiqmaydi, PUL SARFLAMAYDI")
    print("=" * 62)
    db.init_pool()
    try:
        if not db.scalar("SELECT to_regclass('public.tender_routing')"):
            check("schema_patch_routing.sql qo'llangan", False,
                  "psql -d xtxarid -f schema_patch_routing.sql")
        else:
            # OLDINGI yurish o'ldirilgan bo'lsa qoldiq qolgan bo'ladi.
            eski = qoldiqni_supur()
            if eski:
                print(f"[i] oldingi yurishdan {eski} ta qoldiq o'chirildi")
            test_qaror_manbasi()
            test_is_mandatory_darvoza_emas()
            test_sinov_yorligi()
            test_normallashtirish()
            test_yonaltirish()
            test_qaror_eskirishi()
            test_izolyatsiya()
            test_http()
            test_olchovsizlik()
            test_navbat_nomzodlari()
            test_hudud_yagona_qoida()
            test_navbat_filtri()
            test_katalog_filtri()
    finally:
        try:
            tozala()
        finally:
            db.close_pool()

    print("\n" + "=" * 62)
    print(f"NATIJA: {PASS}/{PASS + FAIL} o'tdi")
    print("=" * 62)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
