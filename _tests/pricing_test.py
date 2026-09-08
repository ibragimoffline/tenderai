"""
NARX HISOBI sinovlari — `api/pricing.py` (REJA.md P0-7)
=======================================================
Baza KERAK EMAS, server KERAK EMAS: hisob sof funksiya, shuning uchun to'g'ridan
to'g'ri chaqiriladi.

Ishga tushirish:
    .venv/Scripts/python.exe _tests/pricing_test.py
yoki (pytest o'rnatilgan bo'lsa):
    .venv/Scripts/python.exe -m pytest _tests/pricing_test.py -q

ENG MUHIM SINOV — `test_javascript_bilan_bir_xil`: formula ikki joyda yozilgan
(`api/pricing.py` va `frontend/src/pricing.ts`), chunki brauzerda serverga
so'rovsiz qayta hisoblash kerak. Bu sinov Node orqali JS ijrosini ishga
tushirib, natijani Python natijasi bilan AYNAN solishtiradi. Ikki manba
bir-biridan chetga chiqsa — shu yerda ushlanadi.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

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

from api import pricing  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_FILE = os.path.join(ROOT, "frontend", "src", "pricing.ts")


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------
def _totals(inp):
    r = pricing.calculate(inp)
    assert r["ok"], f"hisob bajarilmadi: {r['errors']}"
    return r["totals"]


def _codes(msgs):
    return [m["code"] for m in msgs]


def _step(res, key):
    for s in res["steps"]:
        if s["key"] == key:
            return s
    raise AssertionError(f"'{key}' bosqichi topilmadi")


# ---------------------------------------------------------------------------
# 1. Biznes-jarayon hujjatidagi namunaviy raqamlar (7-8 bosqich)
#    Tannarx 650 + Logistika 20 + Zaxira 30 = 700; byudjet 1000.
# ---------------------------------------------------------------------------
DOC_CASE = {
    "currency": "USD",
    "items": [{"name": "Uskuna", "unit": "dona", "qty": 1, "unit_cost": 650}],
    "logistics_percent": 0, "logistics_fixed": 20,
    "risk_reserve_percent": 0, "risk_reserve_fixed": 30,
    # Namunada ustama va QQS alohida ko'rsatilmagan — taklif aynan xarajatga
    # teng (700). Shuning uchun ikkalasi ham 0.
    "markup_percent": 0, "vat_percent": 0,
    "budget": 1000, "budget_currency": "USD",
}


def test_hujjat_namunasi_700():
    t = _totals(DOC_CASE)
    assert t["cost_base"] == 650
    assert t["logistics"] == 20
    assert t["risk_reserve"] == 30
    assert t["total_cost"] == 700, "650 + 20 + 30 = 700"
    assert t["recommended_price"] == 700
    assert t["final_price"] == 700
    # Hujjatdagi "kutilayotgan foyda 300" — bu BYUDJET ZAXIRASI (1000 − 700),
    # ya'ni raqobat maydoni. Bizning haqiqiy foydamiz esa 0, chunki narx
    # aynan tannarx darajasida (ustama 0%).
    assert t["budget_left"] == 300, "1000 − 700 = 300"
    assert t["budget_ratio_percent"] == 70
    assert t["profit"] == 0
    res = pricing.calculate(DOC_CASE)
    assert "zero_profit" in _codes(res["warnings"]), \
        "ustamasiz narx ogohlantirishsiz qolmasin"


def test_hujjat_namunasi_bosqichlar_korinadi():
    """TZ mezoni: 'hisoblash formulasi KO'RINADI'."""
    res = pricing.calculate(DOC_CASE)
    keys = [s["key"] for s in res["steps"]]
    for k in ("cost_base", "logistics", "risk_reserve", "total_cost", "markup",
              "price_ex_vat", "vat", "recommended_price", "final_price",
              "profit", "profit_percent", "budget_left"):
        assert k in keys, f"'{k}' bosqichi ko'rsatilmagan"
    s = _step(res, "total_cost")
    assert s["rule"] == "tannarx + logistika + xavf zaxirasi"
    assert s["formula"] == "650 + 20 + 30", "formulada RAQAMLAR ko'rinishi kerak"
    assert _step(res, "cost_base")["formula"] == "1 × 650"


# ---------------------------------------------------------------------------
# 2. Broker qo'lda narx kiritadi (+50) -> smeta qayta hisoblanadi
# ---------------------------------------------------------------------------
def test_broker_qolda_750_foyda_50():
    t = _totals({**DOC_CASE, "manual_price": 750})
    assert t["manual_used"] is True
    assert t["final_price"] == 750
    assert t["total_cost"] == 700, "xarajat o'zgarmaydi"
    assert t["profit"] == 50, "750 − 700 = 50"
    assert t["budget_left"] == 250
    # Foyda ulushi narxga nisbatan: 50 / 750 = 6.666… -> 6.67
    assert t["profit_percent"] == 6.67


def test_qolda_narx_pastga_zarar():
    t = _totals({**DOC_CASE, "manual_price": 600})
    assert t["profit"] == -100
    res = pricing.calculate({**DOC_CASE, "manual_price": 600})
    assert "loss" in _codes(res["warnings"])


def test_qolda_narx_ochirilsa_tavsiyaga_qaytadi():
    t = _totals({**DOC_CASE, "manual_price": None})
    assert t["manual_used"] is False
    assert t["final_price"] == t["recommended_price"] == 700


# ---------------------------------------------------------------------------
# 3. Foiz hisoblari — to'liq zanjir
# ---------------------------------------------------------------------------
def test_foizli_zanjir():
    t = _totals({
        "currency": "UZS",
        "items": [{"name": "Stol", "qty": 10, "unit_cost": 100}],
        "logistics_percent": 10, "logistics_fixed": 0,
        "risk_reserve_percent": 5, "risk_reserve_fixed": 0,
        "markup_percent": 20, "vat_percent": 12,
    })
    assert t["cost_base"] == 1000                 # 10 × 100
    assert t["logistics"] == 100                  # 1000 × 10%
    assert t["risk_reserve"] == 55                # (1000 + 100) × 5%
    assert t["total_cost"] == 1155
    assert t["markup"] == 231                     # 1155 × 20%
    assert t["price_ex_vat"] == 1386
    assert t["vat"] == 166.32                     # 1386 × 12%
    assert t["recommended_price"] == 1552.32
    # QQS foydaga kirmaydi: 1552.32 / 1.12 = 1386 -> foyda 1386 − 1155 = 231
    assert t["final_ex_vat"] == 1386
    assert t["profit"] == 231
    assert t["profit_percent"] == 16.67           # 231 / 1386


def test_qqs_default_12():
    """QQS ko'rsatilmasa 12% (O'zbekiston) — lekin bu DEFAULT, qat'iy emas."""
    assert pricing.DEFAULTS["vat_percent"] == 12
    t = _totals({"items": [{"qty": 1, "unit_cost": 100}],
                 "markup_percent": 0, "risk_reserve_percent": 0})
    assert t["vat"] == 12
    assert t["recommended_price"] == 112


def test_koproq_pozitsiya_formulasi_qisqaradi():
    res = pricing.calculate({
        "items": [{"qty": 1, "unit_cost": 10} for _ in range(6)],
        "markup_percent": 0, "risk_reserve_percent": 0, "vat_percent": 0,
    })
    assert res["totals"]["cost_base"] == 60
    assert _step(res, "cost_base")["formula"].endswith("…(yana 2 ta)")


# ---------------------------------------------------------------------------
# 4. Yaxlitlash — noldan uzoqlashtirib, 2 kasr, HAR BOSQICHDA
# ---------------------------------------------------------------------------
def test_yaxlitlash_qoidasi():
    assert pricing.round2(0.125) == 0.13, "half-up: yuqoriga"
    assert pricing.round2(-0.125) == -0.13, "manfiy ham noldan uzoqlashadi"
    assert pricing.round2(1.005) == 1.01, "ikkilik kasr xatosi tuzatiladi"
    assert pricing.round2(2.675) == 2.68
    assert pricing.round2(0.124) == 0.12
    assert pricing.round2(0) == 0
    assert pricing.round2(-0.0) == 0


def test_yaxlitlash_har_bosqichda():
    """Ko'rinib turgan raqamlar qo'lda qo'shilganda jamiga TO'G'RI kelishi kerak."""
    res = pricing.calculate({
        "items": [{"qty": 3, "unit_cost": 33.333}],   # 99.999 -> 100.00
        "logistics_percent": 3.333, "risk_reserve_percent": 1.777,
        "markup_percent": 7.77, "vat_percent": 12,
    })
    t = res["totals"]
    assert t["cost_base"] == 100.0
    assert t["logistics"] == 3.33                     # 100 × 3.333%
    assert t["risk_reserve"] == 1.84                  # 103.33 × 1.777% = 1.8362
    assert t["total_cost"] == 105.17
    assert t["cost_base"] + t["logistics"] + t["risk_reserve"] == t["total_cost"]
    assert t["price_ex_vat"] == t["total_cost"] + t["markup"]
    assert t["recommended_price"] == t["price_ex_vat"] + t["vat"]


# ---------------------------------------------------------------------------
# 5. Valyuta aralashuvi — kurs konvertatsiyasi yo'q, JIMGINA QO'SHILMAYDI
# ---------------------------------------------------------------------------
def test_valyuta_aralashuvi_xato():
    res = pricing.calculate({
        "currency": "USD",
        "items": [{"name": "A", "qty": 1, "unit_cost": 100, "currency": "USD"},
                  {"name": "B", "qty": 1, "unit_cost": 500000, "currency": "UZS"}],
    })
    assert res["ok"] is False
    assert "currency_mix" in _codes(res["errors"])
    assert res["steps"] == [], "xato bo'lsa hisob umuman bajarilmaydi"
    assert res["totals"]["cost_base"] == 0, "500100 kabi soxta summa CHIQMASIN"


def test_pozitsiya_valyutasi_smetadan_farqli():
    res = pricing.calculate({
        "currency": "UZS",
        "items": [{"qty": 1, "unit_cost": 100, "currency": "USD"}],
    })
    assert res["ok"] is False
    assert "currency_mix" in _codes(res["errors"])


def test_valyuta_korsatilmasa_qoshiladi():
    """Pozitsiyada valyuta yo'q -> smeta valyutasi deb qaraladi (aralashuv emas)."""
    res = pricing.calculate({
        "currency": "USD",
        "items": [{"qty": 1, "unit_cost": 100}, {"qty": 2, "unit_cost": 50}],
        "markup_percent": 0, "risk_reserve_percent": 0, "vat_percent": 0,
    })
    assert res["ok"] is True
    assert res["totals"]["cost_base"] == 200


def test_byudjet_valyutasi_farqli_taqqoslanmaydi():
    res = pricing.calculate({**DOC_CASE, "budget": 12000000, "budget_currency": "UZS"})
    assert res["ok"] is True
    assert "budget_currency" in _codes(res["warnings"])
    assert res["totals"]["budget_left"] is None, "700 va 12 mln taqqoslanmasin"
    assert all(s["key"] not in ("budget_left", "budget_ratio") for s in res["steps"])


# ---------------------------------------------------------------------------
# 6. Nol / manfiy / bo'sh qiymatlar
# ---------------------------------------------------------------------------
def test_bosh_kiruvchi():
    res = pricing.calculate({})
    assert res["ok"] is True
    assert "no_items" in _codes(res["warnings"])
    assert res["totals"]["cost_base"] == 0
    assert res["totals"]["recommended_price"] == 0
    assert res["totals"]["profit"] == 0
    assert res["totals"]["profit_percent"] == 0, "0 ga bo'linish yiqitmasin"


def test_none_va_bosh_matn():
    res = pricing.calculate({
        "items": [{"qty": None, "unit_cost": ""}],
        "markup_percent": None, "vat_percent": "",
        "manual_price": "", "budget": None,
    })
    assert res["ok"] is True
    assert res["totals"]["cost_base"] == 0
    assert res["totals"]["manual_used"] is False
    assert res["totals"]["budget"] is None


def test_matn_korinishidagi_son():
    """Inputdan matn keladi: '15' va '15,5' ham qabul qilinadi."""
    t = _totals({"items": [{"qty": "2", "unit_cost": "10,5"}],
                 "markup_percent": "0", "risk_reserve_percent": "0",
                 "vat_percent": "0"})
    assert t["cost_base"] == 21


def test_manfiy_qiymatlar_xato():
    res = pricing.calculate({"items": [{"name": "A", "qty": -1, "unit_cost": 10},
                                       {"name": "B", "qty": 1, "unit_cost": -5}]})
    assert res["ok"] is False
    assert "qty_negative" in _codes(res["errors"])
    assert "cost_negative" in _codes(res["errors"])

    res2 = pricing.calculate({"items": [], "markup_percent": -3,
                              "logistics_fixed": -1})
    assert res2["ok"] is False
    assert "markup_percent_negative" in _codes(res2["errors"])
    assert "logistics_fixed_negative" in _codes(res2["errors"])

    res3 = pricing.calculate({"vat_percent": 120})
    assert res3["ok"] is False
    assert "vat_range" in _codes(res3["errors"])

    res4 = pricing.calculate({"manual_price": -10})
    assert res4["ok"] is False
    assert "manual_negative" in _codes(res4["errors"])


def test_nol_byudjet():
    res = pricing.calculate({**DOC_CASE, "budget": 0})
    assert res["ok"] is True
    assert res["totals"]["budget_ratio_percent"] == 0, "0 ga bo'linish yiqitmasin"
    assert "over_budget" in _codes(res["warnings"])


# ---------------------------------------------------------------------------
# 7. min_margin_percent — company_profile dan (faqat o'qish)
# ---------------------------------------------------------------------------
def test_minimal_marja_ogohlantirishi():
    inp = {
        "items": [{"qty": 1, "unit_cost": 1000}],
        "logistics_percent": 0, "risk_reserve_percent": 0,
        "markup_percent": 15, "vat_percent": 0,
        "min_margin_percent": 20,
    }
    res = pricing.calculate(inp)
    # 1000 -> ustama 150 -> narx 1150 -> foyda 150 -> ulush 150/1150 = 13.04%
    assert res["totals"]["profit_percent"] == 13.04
    assert "below_min_margin" in _codes(res["warnings"])

    ok = pricing.calculate({**inp, "min_margin_percent": 10})
    assert "below_min_margin" not in _codes(ok["warnings"])


def test_minimal_marja_korsatilmasa_ogohlantirish_yoq():
    res = pricing.calculate({"items": [{"qty": 1, "unit_cost": 100}],
                             "min_margin_percent": None})
    assert "below_min_margin" not in _codes(res["warnings"])


def test_byudjetdan_oshib_ketish():
    res = pricing.calculate({**DOC_CASE, "manual_price": 1200})
    assert "over_budget" in _codes(res["warnings"])
    assert res["totals"]["budget_left"] == -200


# ---------------------------------------------------------------------------
# 8. Kiruvchini tayyorlash yordamchilari
# ---------------------------------------------------------------------------
def test_parse_amount_text():
    assert pricing.parse_amount_text("2.00 dona") == 2.0
    assert pricing.parse_amount_text(" 1 500,5 kg") == 1500.5
    assert pricing.parse_amount_text("dona") is None
    assert pricing.parse_amount_text(None) is None
    assert pricing.parse_amount_text(7) == 7.0


def test_positions_from_goods():
    pos = pricing.positions_from_goods([
        {"name": "Stol", "unit": "dona", "amount": 5, "price": 1200},
        {"good_code": "X1", "amount_text": "3.00 dona"},
    ])
    assert pos[0]["name"] == "Stol" and pos[0]["qty"] == 5
    # Buyurtmachi narxi TANNARX o'rniga QO'YILMAYDI — u faqat mo'ljal
    assert pos[0]["unit_cost"] == 0 and pos[0]["ref_price"] == 1200
    assert pos[1]["name"] == "X1" and pos[1]["qty"] == 3.0


def test_build_inputs_ustunlik_tartibi():
    settings = {"markup_percent": 15, "vat_percent": 12, "currency": "UZS"}
    tender = {"totalcost": 5000, "currency": "USD"}
    profile = {"min_margin_percent": 8}
    saved = {"inputs": {"markup_percent": 25,
                        "items": [{"name": "A", "qty": 1, "unit_cost": 10}]}}
    inp = pricing.build_inputs(settings, tender, [], profile, saved,
                               {"markup_percent": 30})
    assert inp["markup_percent"] == 30, "so'rov saqlangandan ustun"
    assert inp["vat_percent"] == 12, "sozlamadan"
    assert inp["currency"] == "USD", "tender valyutasi ustun"
    assert inp["budget"] == 5000
    assert inp["min_margin_percent"] == 8
    assert inp["items"][0]["name"] == "A", "saqlangan pozitsiyalar tiklanadi"


# ---------------------------------------------------------------------------
# 9. PYTHON <-> JAVASCRIPT PARITETI  (eng muhim sinov)
# ---------------------------------------------------------------------------
#: Yonma-yon solishtiriladigan holatlar — oddiy, foizli, qo'lda narxli,
#: yaxlitlash chegarasidagi, UZS miqyosidagi, xatoli va bo'sh.
PARITY_CASES = [
    DOC_CASE,
    {**DOC_CASE, "manual_price": 750},
    {**DOC_CASE, "manual_price": 600},
    {"currency": "UZS",
     "items": [{"name": "Stol", "qty": 10, "unit_cost": 100}],
     "logistics_percent": 10, "risk_reserve_percent": 5,
     "markup_percent": 20, "vat_percent": 12, "budget": 2000,
     "budget_currency": "UZS", "min_margin_percent": 20},
    {"currency": "UZS",
     "items": [{"name": "Kompyuter", "qty": 37, "unit_cost": 12345678.99},
               {"name": "Monitor", "qty": 74, "unit_cost": 2500000.5}],
     "logistics_percent": 3.7, "logistics_fixed": 1500000,
     "risk_reserve_percent": 2.5, "markup_percent": 17.5, "vat_percent": 12,
     "budget": 999999999.99, "budget_currency": "UZS",
     "min_margin_percent": 12.5},
    {"items": [{"qty": 3, "unit_cost": 33.333}],
     "logistics_percent": 3.333, "risk_reserve_percent": 1.777,
     "markup_percent": 7.77, "vat_percent": 12},
    {"items": [{"qty": 1, "unit_cost": 1.005}, {"qty": 1, "unit_cost": 2.675}],
     "logistics_percent": 0.125, "risk_reserve_percent": 0.125,
     "markup_percent": 0.125, "vat_percent": 0.125},
    {"items": [{"qty": i, "unit_cost": i * 1.1} for i in range(1, 8)],
     "markup_percent": 12.34, "vat_percent": 12},
    {"currency": "USD",
     "items": [{"qty": 1, "unit_cost": 100, "currency": "USD"},
               {"qty": 1, "unit_cost": 500000, "currency": "UZS"}]},
    {"items": [{"name": "A", "qty": -1, "unit_cost": 10}], "vat_percent": 120},
    {**DOC_CASE, "budget": 12000000, "budget_currency": "UZS"},
    {**DOC_CASE, "budget": 0},
    {"items": [], "markup_percent": None, "vat_percent": ""},
    {},
    {"items": [{"qty": "2", "unit_cost": "10,5"}], "markup_percent": "0",
     "risk_reserve_percent": "0", "vat_percent": "0"},
    {"items": [{"qty": 1, "unit_cost": 1000}], "logistics_percent": 0,
     "risk_reserve_percent": 0, "markup_percent": 15, "vat_percent": 0,
     "min_margin_percent": 20},
]

# Harness `calculate(inp, t)` ni chaqiradi: bosqich MATNLARI tilga bog'liq
# va `t` funksiya PARAMETR sifatida kiradi (`pricing.ts` dagi izohga qarang).
# Python tomonda matnlar O'ZBEKCHA qotirilgan, shuning uchun bu yerda ham
# `locales/uz.ts` lug'ati ishlatiladi — aks holda paritet sinovi hisobni
# emas, tarjimani solishtirib qolardi.
#
# TypeScript: Node 22.6+ tur izohlarini o'zi olib tashlaydi (pricing.ts
# ATAYLAB faqat "o'chiriladigan" TS sintaksisidan iborat). Node eskiroq
# bo'lsa import yiqiladi va sinov buni ochiq aytadi.
# XOM SATR (`r"""`). Ichida JS regexi bor (`/\{(\w+)\}/g`) va
# Python uni O'ZINING ekran ketma-ketligi deb o'qiydi:
#
#     SyntaxWarning: "\{" is an invalid escape sequence
#
# Hozircha ogohlantirish, kelgusi Python da XATO. JS matni Python
# uchun MA'NOSIZ bo'lishi kerak — xom satr aynan shuni ta'minlaydi.
_JS_HARNESS = r"""
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'

const file = process.argv[2]
const mod = await import(pathToFileURL(file).href)
const { uz } = await import(
  pathToFileURL(join(dirname(file), 'locales', 'uz.ts')).href)

// i18n.tsx dagi `translate()` ning sinov uchun yetarli qismi: kalit
// topilmasa KALITNING O'ZI qaytadi va farq darhol ko'zga tashlanadi.
const t = (key, vars) => {
  const raw = uz[key]
  if (raw === undefined) return key
  return vars
    ? raw.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m))
    : raw
}

const cases = JSON.parse(readFileSync(0, 'utf8'))
console.log(JSON.stringify(cases.map((c) => mod.calculate(c, t))))
"""


def _node() -> str:
    """Node ijrochisi — PATH ga TAYANMAYDI.

    O'LCHANGAN (2026-09-08): natija PATH dagi birinchi `node` ga
    bog'liq edi. Darvoza hostida ikkita Node bor:

        /usr/bin/node            v22.22.1  — TS QO'LLAB-QUVVATLASHISIZ
        ~/.nvm/.../v22.23.2      v22.23.2  — TS ishlaydi

    Ikkinchisi `/home/ibragimoff` ichida (0750), ya'ni darvoza
    yuradigan `tenderai` foydalanuvchisi uni O'QIY OLMAYDI. Natijada
    ishlab chiquvchi mashinasida sinov o'tardi, darvozada esa
    `ERR_NO_TYPESCRIPT` bilan yiqilardi — "menda ishlayapti" sinfi.

    `TENDERAI_NODE` — aniq ko'rsatish yo'li. Berilmasa xulq
    o'zgarmaydi (`node`), ya'ni mavjud o'rnatmalar buzilmaydi.
    """
    return os.environ.get("TENDERAI_NODE") or "node"


def _js_results(cases):
    """JS ijrosini Node bilan ishga tushiradi. Node yo'q bo'lsa None."""
    # KATALOG `finally` DA O'CHIRILADI.
    #
    # O'LCHANGAN (2026-09-08): tozalash yo'q edi va bu funksiya har
    # chaqirilganda `/tmp` ga bitta katalog qoldirardi. Darvoza
    # yurishlari davomida 1724 ta yig'ilib qoldi.
    #
    # NEGA BU SHUNCHAKI IFLOSLIK EMAS: bu xostda `/tmp` — `tmpfs`,
    # ya'ni RAM. Qoldiqlar diskni emas, XOTIRANI yeydi va o'sha
    # xotira ishlab chiqarish API siga kerak edi. 2026-09-08 da
    # `tenderai-api@production` aynan `oom-kill` bilan yiqildi.
    #
    # Ya'ni tozalanmagan sinov katalogi ishlab chiqarishni o'chirdi.
    tmp = tempfile.mkdtemp(prefix="pricing_parity_")
    try:
        return _js_results_ichida(tmp, cases)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _js_results_ichida(tmp, cases):
    """`_js_results` ning ichki qismi — katalog tashqarida boshqariladi."""
    harness = os.path.join(tmp, "harness.mjs")
    with open(harness, "w", encoding="utf-8") as f:
        f.write(_JS_HARNESS)
    try:
        p = subprocess.run(
            # `--experimental-strip-types` ANIQ BERILADI.
            #
            # `pricing.ts` ataylab faqat "o'chiriladigan" TS
            # sintaksisidan iborat, ya'ni Node uni tur izohlarini
            # olib tashlab import qila oladi. LEKIN bu qobiliyat
            # Node versiyasiga qarab standart bo'yicha yoqilgan yoki
            # yoqilmagan bo'ladi.
            #
            # O'LCHANGAN (2026-09-08): darvoza serverida
            # `/usr/bin/node` v22.22.1 va import
            #
            #     ERR_UNKNOWN_FILE_EXTENSION
            #
            # bilan yiqilardi; ishlab chiquvchi mashinasida esa nvm
            # dagi v22.23.2 bilan O'TARDI. Ya'ni sinov natijasi
            # PATH dagi Node versiyasiga bog'liq edi — "menda
            # ishlayapti" sinfi.
            #
            # Bayroq ikkala versiyada ham qabul qilinadi (o'lchandi),
            # shuning uchun uni ANIQ berish natijani versiyadan
            # mustaqil qiladi.
            [_node(), "--experimental-strip-types", harness, JS_FILE],
            input=json.dumps(cases, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=60)
    except (FileNotFoundError, OSError):
        return None
    if p.returncode != 0:
        xato = p.stderr.decode("utf-8", "replace")
        # SABAB TANIB OLINADI — xom Node stegi o'rniga bitta gap.
        #
        # O'LCHANGAN (2026-09-08, darvoza serveri): Debian/Ubuntu
        # `nodejs` paketi TypeScript qo'llab-quvvatlashisiz quriladi
        # (`amaro` kiritilmagan) va `pricing.ts` importi
        #
        #     Error [ERR_NO_TYPESCRIPT]: Node.js is not compiled
        #     with TypeScript support
        #
        # beradi. Hech qanday BAYROQ buni tuzatmaydi — bu ijro
        # muhitining qobiliyati.
        #
        # SINOV BARIBIR YIQILADI va bu ATAYLAB: paritet tekshiruvi
        # HAQIQATAN bajarilmadi. "O'lchay olmadim" ni "o'tdi" ga
        # aylantirish bu loyihada eng qimmat xato sinfi. Lekin sabab
        # endi ANIQ aytiladi, aks holda u xom stek ichida qolardi.
        if "ERR_NO_TYPESCRIPT" in xato:
            raise AssertionError(
                "PARITET O'LCHANMADI: bu hostdagi Node TypeScript "
                "qo'llab-quvvatlashisiz qurilgan (ERR_NO_TYPESCRIPT).\n"
                "  `pricing.ts` ni Node import qila olmaydi, ya'ni "
                "Python va JS hisobi SOLISHTIRILMADI.\n"
                "  Kerak: `amaro` bilan qurilgan Node (masalan rasmiy "
                "nodejs.org paketi yoki nvm), yoki TS ni oldindan "
                "kompilyatsiya qiladigan qadam.\n"
                "  Bu 'o'tdi' EMAS — o'lchov bajarilmadi.")
        raise AssertionError("Node ijrosi yiqildi:\n" + xato)
    return json.loads(p.stdout.decode("utf-8"))


def test_javascript_bilan_bir_xil():
    """Backend va frontend formulasi AYNAN bir xil natija berishi shart.

    Aks holda foydalanuvchi brauzerda bir raqamni ko'radi, bazaga boshqasi
    yoziladi — bu eng yomon turdagi xato (jimgina farq).
    """
    js = _js_results(PARITY_CASES)
    if js is None:
        print("  ! Node topilmadi — JS pariteti TEKSHIRILMADI")
        return
    assert len(js) == len(PARITY_CASES)
    for i, case in enumerate(PARITY_CASES):
        py = json.loads(json.dumps(pricing.calculate(case), ensure_ascii=False))
        if py != js[i]:
            diff = [k for k in set(py) | set(js[i]) if py.get(k) != js[i].get(k)]
            raise AssertionError(
                f"#{i} holat farq qildi (maydonlar: {diff})\n"
                f"  Python: {json.dumps({k: py.get(k) for k in diff}, ensure_ascii=False)[:900]}\n"
                f"  JS    : {json.dumps({k: js[i].get(k) for k in diff}, ensure_ascii=False)[:900]}")


# ---------------------------------------------------------------------------
# Runner — pytestsiz ham ishlaydi
# ---------------------------------------------------------------------------
def _main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  OK   {name}")
        except Exception as e:  # noqa: BLE001
            failed.append((name, e))
            print(f"  XATO {name}: {e}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} sinov o'tdi")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
