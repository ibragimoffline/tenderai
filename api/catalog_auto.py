"""Katalog mahsulotini foydalanuvchiga ko'rinmas tarzda aniq kodlash.

Bu modul alohida "kodlash navbati" talab qilmaydi. Mahsulot nomi (yoki import
qilingan katalogdagi mahsulot turi) tender lotlarining tarixiy nomlari bilan
solishtiriladi. Faqat barcha mazmunli so'zlar bir lotda uchragan va bitta
8-belgili kod mutlaq ustun bo'lgan holat avtomatik qabul qilinadi.

Noaniq holatda kod taxmin qilinmaydi. Bu recall hisobiga precisionni saqlaydi:
bo'sh natija noto'g'ri "mos" tenderdan xavfsizroq va foydalanuvchi texnik
jarayonni boshqarishga majbur bo'lmaydi.
"""
import re
from typing import Any, Dict, List, Optional, Set

from api import atama, db, kodlash, translit

SYSTEM_ACTOR = "tizim:auto"
MIN_EVIDENCE = 2
MIN_SHARE = 0.75
MAX_TOKENS = 4

#: KUCHSIZ DALIL BANDI — avtomatik QO'LLANMAYDI, navbatga boradi.
#:
#: O'LCHANGAN SABAB (2026-08-31, 1 797 mahsulot). Avtomatik takliflar
#: inson bergan keng kod bilan solishtirildi (383 ta juftlik):
#:
#:     umumiy moslik            382/383  (99.7%)
#:     0.75-0.79 + dalil<=4       3/4    (75.0%)
#:
#: Ya'ni ishonch chegaraga tegib turgan VA dalil kam bo'lgan band
#: sezilarli darajada kuchsiz. Bu bandda 34 ta taklif bor (501 dan
#: 6.8%) va ular YO'QOLMAYDI — navbatga tushadi.
#:
#: NEGA CHEGARA O'ZGARTIRILMAYDI: `MIN_SHARE` ni ko'tarish 297 ta
#: kuchli taklifni (0.80-0.89, o'rtacha dalil 18.0) ham to'sardi.
#: Bitta bandni ajratish aniqroq javob.
#:
#: HALOL CHEKLOV: 3/4 — namuna KICHIK (n=4) va u yolg'iz o'zi
#: yetarli dalil emas. Lekin mexanizm izchil (kam dalil + chegara
#: cheti) va bandni navbatga yo'naltirish narxi kichik.
KUCHSIZ_ISHONCH = 0.80
KUCHSIZ_DALIL = 4

#: KODSIZLIK SABABLARI. Ilgari `suggest_exact_code()` BESH XIL holatda
#: bir xil `None` qaytarardi va "kod yo'q" degan yagona chelak qolardi.
#: Chelak ichida esa butunlay boshqa ishlar yashiringan edi: birida
#: nom normallashmagan, boshqasida DALIL ikkiga yetmagan, uchinchisida
#: ikki kod oilasi teng kelgan. Ular BIR XIL emas va bir xil harakat
#: talab qilmaydi.
#:
#: "Noma'lum noma'lumligicha qoladi" tamoyili bu yerda ham amal
#: qiladi: sabab NOMA'LUM bo'lsa ham u ANIQ aytiladi.
SABABLAR = (
    "kod",              # ishonchli kod topildi
    "tokensiz",         # ma'noli so'z chiqmadi (normallashtirish/nom muammosi)
    "nomzodsiz",        # tarixiy lotlarda umuman mos nom yo'q
    "sozlar_mos_emas",  # nomzod bor, lekin HAMMA so'z mos kelmadi
    "dalil_kam",        # mos keldi, lekin dalil MIN_EVIDENCE dan kam
    "noaniq",           # dalil yetarli, lekin ulush MIN_SHARE dan past
                        # (bir nechta kod oilasi teng — TAXMIN QILINMAYDI)
)

_STOP = {
    "uchun", "bilan", "hamda", "yoki", "va", "the", "for", "with",
    "dlya", "and", "product", "mahsulot", "tovar", "xizmat", "usluga",
}


def _type_text(product: Dict[str, Any]) -> str:
    """Import katalogidagi tur maydonini, oddiy formada esa nomni oladi."""
    kws = [str(x).strip() for x in (product.get("keywords") or []) if str(x).strip()]
    # Amaldagi importlarda: brand, mahsulot turi, tavsif. Ikkinchi qiymat
    # model/SKU nomidan ko'ra klassifikatsiya uchun ancha barqaror.
    if len(kws) >= 2 and len(kws[1]) <= 40:
        return kws[1]
    return (product.get("name") or "").strip()


def _tokens(product: Dict[str, Any]) -> List[str]:
    normalized = atama.normal(_type_text(product))
    out: List[str] = []
    for token in re.findall(r"[^\W\d_]+", normalized, flags=re.UNICODE):
        token = token.strip().lower()
        if len(token) < 3 or token in _STOP or token in out:
            continue
        out.append(token)
    # Uzunroq so'z ko'proq ma'no tashiydi. Juda uzun tavsif SQL ni
    # haddan tashqari toraytirmasin.
    return sorted(out, key=len, reverse=True)[:MAX_TOKENS]


def _token_clauses(tokens: List[str]) -> tuple:
    """Tokenlardan SQL shartlari va parametrlarini quradi.

    BITTA JOYDA: `tahlil()` va `biznes_qiymati()` ikkalasi ham shu
    yerdan oladi. Ilgari shart qurish `suggest_exact_code()` ichida
    edi; ikkinchi chaqiruvchi paydo bo'lganda uni nusxalash kerak
    bo'lardi va ikki nusxa vaqt o'tib ajralib ketardi.
    """
    params: Dict[str, Any] = {}
    clauses: List[str] = []
    folded = translit.sql_fold("g.name")
    for i, token in enumerate(tokens):
        pats: List[str] = []
        # `atama.normal()` ayrim egalik shakllarida bitta yakuniy undoshni
        # qoldiradi: "kreslosi" -> "kreslos", korpusda esa "кресло".
        # Bitta belgilik zaxira faqat uzun so'zda ishlaydi va barcha tokenlar
        # baribir AND bilan tekshiriladi.
        bases = [token] + ([token[:-1]] if len(token) >= 6 else [])
        for base in bases:
            for variant in translit.variants(base):
                if variant and len(variant) >= 3:
                    pat = f"%{variant}%"
                    if pat not in pats:
                        pats.append(pat)
        if not pats:
            continue
        key = f"p{i}"
        params[key] = pats
        clauses.append(f"{folded} LIKE ANY(%({key})s)")
    return clauses, params


def biznes_qiymati(product: Dict[str, Any]) -> Dict[str, int]:
    """Mahsulot QANCHA muhim: ochiq tender va tarixiy lot soni.

    NAVBAT USTUVORLIGI uchun. Kam uchraydigan mahsulotni kodlash
    arzon, lekin foydasi ham kam — navbat shuni hisobga olishi kerak.

    `ochiq_tender` KUCHLIROQ signal (bugungi imkoniyat), `tarixiy_lot`
    esa barqarorlik belgisi. Ikkalasi ALOHIDA qaytadi — ularni bitta
    songa qo'shish qaysi biri gapirayotganini yashirardi.
    """
    tokens = _tokens(product)
    if not tokens:
        return {"ochiq_tender": 0, "tarixiy_lot": 0}
    clauses, params = _token_clauses(tokens)
    if not clauses:
        return {"ochiq_tender": 0, "tarixiy_lot": 0}
    shart = " OR ".join(clauses)
    row = db.query_one(f"""
        SELECT count(DISTINCT g.tender_id) FILTER (
                   -- "OCHIQ" ta'rifi loyihadagi yagona manbadan
                   -- (`queries.build_tender_filters`): status 'open'
                   -- VA muddat o'tmagan. Faqat statusga qarash
                   -- yetarli emas — tender yopilgach manba
                   -- ro'yxatidan chiqib ketadi va bizdagi 'open'
                   -- abadiy qotib qoladi.
                   WHERE t.status = 'open'
                     AND (t.close_at IS NULL OR t.close_at > now())
               ) AS ochiq,
               count(*) AS lot
          FROM tender_good g
          JOIN tender t ON t.id = g.tender_id
         WHERE g.name IS NOT NULL AND ({shart})
    """, params) or {}
    return {"ochiq_tender": int(row.get("ochiq") or 0),
            "tarixiy_lot": int(row.get("lot") or 0)}


def suggest_exact_code(product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dominant 8-belgili lot kodini topadi; dalil yetmasa ``None``.

    YUPQA O'RAM: butun mantiq `tahlil()` da. Ikki joyda takrorlanmasin —
    aks holda chegara bir joyda o'zgarib, ikkinchisi eskirib qolardi.
    """
    natija = tahlil(product)
    if natija["sabab"] != "kod":
        return None
    return {k: natija[k] for k in
            ("code", "confidence", "evidence", "total", "examples", "source")}


# ---------------------------------------------------------------------
# BOSH SO'Z ZIDDIYATI (semantik signal)
#
# MUAMMO (o'lchandi 2026-09-12): `teskari` qoida lot nomining HAMMA
# so'zi mahsulot ichida bo'lishini talab qiladi. Bu QISQA lot nomlarini
# tizimli afzal ko'radi, qisqa nomlar esa eng umumiylari:
#
#     mahsulot : Server (telekommunikatsiya) shkafi 32U (polga)
#     tokenlar : telekommunikats, server, shkaf, polg
#     "Сервер"              -> qoplam 1/1 -> OVOZ BERADI  (8/8, ulush 1.0)
#     "Шкаф металлический"  -> qoplam 1/2 -> RAD ETILADI
#
# Natijada raqobatchi oila KO'RINMAY qoladi va statistik signallar
# (dalil, ulush, farq, oila) "hammasi joyida" deb ko'rsatadi. Xato
# SEMANTIK: mahsulotning bosh oti `shkaf`, kod esa `server` niki.
#
# BU YERDAGI YO'L: nomzodlarni QISMAN qoplam bilan ham hisobga olamiz
# va ularni KOD BO'LIMI bo'yicha guruhlaymiz. Har oilaga QAYSI token
# dalil bo'lganini yozamiz. Agar g'olib oilani bir token qo'llab
# tursa-yu, boshqa oilani BOSHQA token kuchli qo'llab tursa -- bu
# ziddiyat va qaror odamga boradi.
#
# QORA RO'YXAT EMAS. `server`, `shkaf`, `router` kabi so'zlar hech
# qayerda sanab chiqilmaydi -- signal mavjud nomzodlar va kod
# oilalaridan kelib chiqadi, shuning uchun yangi mahsulot turiga
# qo'lda qo'shimcha talab qilmaydi.
# ---------------------------------------------------------------------
#: Raqobatchi oila shu ulushdan kam qoplansa -- shovqin, hisobga
#: olinmaydi. 0.5 = lot nomining kamida yarmi mahsulotda uchraydi.
ZIDDIYAT_MIN_QOPLAM = 0.5

#: Raqobatchi oilada shu sondan kam lot bo'lsa -- tasodif deb qaraladi.
ZIDDIYAT_MIN_LOT = 2


def nomzod_oilalari(product: Dict[str, Any]) -> Dict[str, Any]:
    """Nomzodlarni KOD BO'LIMI bo'yicha guruhlaydi (faqat o'qish).

    Har oila uchun: nechta lot, eng yaxshi qoplam va QAYSI tokenlar
    dalil bo'lgani. `tahlil()` dan farqi -- bu yerda QISMAN qoplangan
    nomzodlar ham saqlanadi.
    """
    tokens = _tokens(product)
    natija: Dict[str, Any] = {"tokens": tokens, "oilalar": {},
                              "kodlar": {}}
    if not tokens:
        return natija
    clauses, params = _token_clauses(tokens)
    if not clauses:
        return natija
    divisions = kodlash.divisions_for_category(product.get("category_code"))
    family = ""
    if divisions:
        params["divisions"] = divisions
        family = "AND substring(g.good_code from 1 for 2) = ANY(%(divisions)s)"
    rows = db.query(f"""
        SELECT g.good_code, g.name
        FROM tender_good g
        WHERE g.good_code IS NOT NULL
          AND length(g.good_code) >= 8
          AND g.name IS NOT NULL
          AND ({' OR '.join(clauses)})
          {family}
    """, params)
    tok_set = set(tokens)
    for row in rows:
        words = _mazmunli(set(atama.normal(row["name"] or "").split()))
        if not words:
            continue
        mos = {w for w in words if _soz_bor(w, tok_set)}
        if not mos:
            continue
        qoplam = len(mos) / len(words)
        # Qaysi TOKEN shu lotni qo'llab-quvvatladi.
        dalil_tok = {t for t in tokens
                     if any(_soz_bor(w, {t}) for w in mos)}
        bolim = (row["good_code"] or "")[:2]
        o = natija["oilalar"].setdefault(
            bolim, {"lot": 0, "max_qoplam": 0.0, "tokens": set(),
                    "nom": row["name"]})
        o["lot"] += 1
        if qoplam > o["max_qoplam"]:
            o["max_qoplam"] = qoplam
            o["nom"] = row["name"]
        o["tokens"] |= dalil_tok

        # KOD darajasi ALOHIDA. G'olibning tokenlarini BO'LIM bo'yicha
        # olish XATO edi: bo'lim o'z ichiga raqibning tokenini ham
        # yutib yuboradi va ziddiyat ko'rinmay qoladi. O'lchangan
        # holat (#2850 server shkafi):
        #
        #     26.*  tokens=[server, shkaf]   <- bo'lim darajasi
        #     26.20.14 dalil lotlari: "Сервер" -> tokens=[server]
        #     31.*  tokens=[shkaf]  lot=43
        #
        # Bo'lim bilan kesishma bor -> o'tkazib yuborilardi.
        # Kod bilan kesishma YO'Q -> ziddiyat ko'rinadi.
        if qoplam >= 1.0:
            kd = (row["good_code"] or "")[:8]
            k = natija["kodlar"].setdefault(kd, {"lot": 0, "tokens": set()})
            k["lot"] += 1
            k["tokens"] |= dalil_tok
    return natija


#: Qavs ichi -- deyarli har doim IZOH yoki maqsad, bosh ot emas:
#: "Gofra truba (kabel uchun)", "Simsiz klaviatura (boshqaruv paneli)".
_QAVS_RE = re.compile(r"\([^)]*\)")
#: Kirill bo'lagi -- odatda ruscha TAKRORIY nom ("... Штекер питания").
#: Bosh ot o'zbekcha bo'lagidan olinadi, aks holda brend/model tushadi.
_KIRIL_RE = re.compile(r"[\u0400-\u04FF]")


def bosh_ot(name: str) -> str:
    """Mahsulot nomining BOSH OTINI qaytaradi (yoki bo'sh satr).

    O'zbekchada aniqlovchi oldin, BOSH OT oxirida keladi:
    "Server shkafi" -> shkaf;  "DC quvvat konnektori" -> konnektor.
    Shu sababli maqsad/izoh bo'laklari olib tashlangach OXIRGI
    ma'noli so'z olinadi.

    IKKI MAQSAD BELGISI:
        qavs ichi        "(kabel uchun)", "(boshqaruv paneli)"
        "... uchun"      "Kommutator/NVR uchun metall shit"

    O'LCHANGAN SABAB (2026-09-12): ziddiyat signalining 4 ta noto'g'ri
    belgisining HAMMASI raqib oilaning aynan shu bo'laklardagi so'zdan
    oziqlanishidan chiqqandi:

        Gofra truba (kabel uchun)   -> raqib "kabel" ustida
        DC quvvat konnektori        -> raqib "питания" ustida

    QORA RO'YXAT EMAS: bu grammatik tuzilish, so'z ro'yxati emas.
    """
    matn = _QAVS_RE.sub(" ", name or "")
    m = _KIRIL_RE.search(matn)
    if m:
        matn = matn[:m.start()]
    # "... uchun" -- undan OLDINGISI maqsad, keyingisi predmet.
    past = matn.lower()
    i = past.rfind(" uchun")
    if i >= 0:
        matn = matn[i + len(" uchun"):]
    sozlar = [w for w in re.findall(r"[^\W\d_]+",
                                    atama.normal(matn), flags=re.UNICODE)
              if len(w) >= 3 and w not in _STOP]
    return sozlar[-1] if sozlar else ""


def bosh_ot_ziddiyati(bosh: Dict[str, Any],
                      product: Dict[str, Any]) -> Dict[str, Any]:
    """G'olib oilaga BOSHQA token bilan raqobat qiladigan oila bormi?

    Qaytaradi: `{"ziddiyat": bool, "raqib": bo'lim, "raqib_nom": ...,
                 "golib_tokens": [...], "raqib_tokens": [...]}`
    """
    javob = {"ziddiyat": False, "raqib": None, "raqib_nom": None,
             "golib_tokens": [], "raqib_tokens": []}
    kod = bosh.get("code") or ""
    if not kod:
        return javob
    tahl = nomzod_oilalari(product)
    oilalar = tahl["oilalar"]
    # G'olib TOKENLARI uning o'z dalil lotlaridan (kod darajasi),
    # bo'limdan EMAS -- yuqoridagi izohga qarang.
    golib = tahl["kodlar"].get(kod[:8]) or oilalar.get(kod[:2])
    if not golib:
        return javob
    javob["golib_tokens"] = sorted(golib["tokens"])
    bosh = bosh_ot(product.get("name") or "")
    javob["bosh_ot"] = bosh
    for bolim, o in oilalar.items():
        if bolim == kod[:2]:
            continue
        if o["lot"] < ZIDDIYAT_MIN_LOT or o["max_qoplam"] < ZIDDIYAT_MIN_QOPLAM:
            continue
        # ASOSIY SHART: raqib BOSHQA token ustida turibdi. Agar
        # ikkalasi bir xil tokendan oziqlansa, bu ma'no ziddiyati
        # emas -- shunchaki bitta so'zning ikki kod oilasida uchrashi.
        if o["tokens"] & golib["tokens"]:
            continue
        # RAQIB BOSH OTGA TAYANISHI SHART. Maqsad/izoh bo'lagidagi
        # so'z ustida turgan raqib -- bu ma'no ziddiyati EMAS:
        # "Gofra truba (kabel uchun)" da mahsulot GOFRA, kabel esa
        # u nima uchun ekanligi. Bosh ot aniqlanmasa (bo'sh satr)
        # eski xulq saqlanadi -- signal YO'QOLMAYDI.
        if bosh and not any(_soz_bor(bosh, {t}) or _soz_bor(t, {bosh})
                            for t in o["tokens"]):
            continue
        javob.update({"ziddiyat": True, "raqib": bolim,
                      "raqib_nom": o["nom"],
                      "raqib_tokens": sorted(o["tokens"])})
        break
    return javob


# ---------------------------------------------------------------------
# AVTOMATIK TASDIQ SIYOSATI
#
# `tahlil()` "qaysi kod" degan savolga javob beradi. Bu yerda BOSHQA
# savol turadi: "bu javobni ODAM KO'RMASDAN faollashtirsa bo'ladimi?"
#
# Ikkisini ajratish ATAYLAB. `sabab='kod'` -- algoritm qarori;
# `qaror='auto'` -- shu qarorga INSON NAZORATISIZ ishonish. Ikkinchisi
# birinchisidan QAT'IYROQ bo'lishi shart.
#
# NEGA KERAK (2026-09-12 o'lchovi): `teskari` qoida qamrovni 0.2% dan
# 10.2% ga ko'tardi, lekin 14 talik namunada 1 ta xato chiqdi -- server
# SHKAFI `Сервер` deb kodlandi. Bunday xato inson ko'rmasdan
# faollashsa, u HAR IMPORTDA takrorlanadi.
#
# BESH SIGNAL, hammasi `tahlil()` da ALLAQACHON bor -- yangi hisob
# qo'shilmaydi:
#
#     dalil        -- top1 ni tasdiqlagan tarixiy lot soni
#     ulush        -- top1 / jami (`confidence`)
#     farq         -- top1 ulushi - top2 ulushi
#     oila         -- nomzodlar bitta NACE bo'limida turibdimi
#     kategoriya   -- mahsulot kategoriyasi kod bo'limiga ziddimi
#
# CHEGARALAR O'LCHOVSIZ TANLANMAYDI. Presetlar `kod_nima_bolardi.py
# --siyosat` bilan taqqoslanadi va shundan keyin bittasi standart
# qilinadi.
# ---------------------------------------------------------------------
SIYOSAT_PRESET: Dict[str, Dict[str, Any]] = {
    # Hozirgi amaldagi xulq: siyosat YO'Q, `sabab='kod'` bo'lsa
    # faollashadi (faqat `kuchsiz_dalil` to'sadi). Taqqoslash uchun.
    "yoq":     {"dalil": 2, "ulush": 0.75, "farq": 0.00,
                "oila": False, "kategoriya": False, "ziddiyat": False},
    "yumshoq": {"dalil": 3, "ulush": 0.85, "farq": 0.30,
                "oila": False, "kategoriya": True, "ziddiyat": True},
    "orta":    {"dalil": 4, "ulush": 0.90, "farq": 0.50,
                "oila": True,  "kategoriya": True, "ziddiyat": True},
    "qattiq":  {"dalil": 6, "ulush": 1.00, "farq": 0.75,
                "oila": True,  "kategoriya": True, "ziddiyat": True},
}

#: STANDART SIYOSAT. O'lchovdan keyin tanlanadi.
STANDART_SIYOSAT = "orta"


def siyosat_qarori(bosh: Dict[str, Any], product: Dict[str, Any],
                   siyosat: str = "",
                   ziddiyat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`tahlil()` natijasini UCH chelakka ajratadi.

        auto    -- inson ko'rmasdan faollashtirish mumkin
        navbat  -- taklif yoziladi, TASDIQLANMAYDI (inson ko'radi)
        kodsiz  -- kod umuman yo'q

    HECH NARSA YOZMAYDI -- faqat qaror qaytaradi.
    """
    p = SIYOSAT_PRESET[siyosat or STANDART_SIYOSAT]
    qaror = {"qaror": "kodsiz", "sabab": bosh.get("sabab"), "tekshiruv": {}}

    if bosh.get("sabab") != "kod":
        # `dalil_kam` va `noaniq` -- kod NOMZODI bor, faqat zaif.
        # Ular NAVBATGA tushadi: odam ko'rsa hal bo'ladi.
        if bosh.get("sabab") in ("dalil_kam", "noaniq") and bosh.get("code"):
            qaror["qaror"] = "navbat"
        return qaror

    kodlar = bosh.get("kodlar") or {}
    jami = sum(kodlar.values()) or (bosh.get("total") or 0)
    tartib = sorted(kodlar.values(), reverse=True)
    top1 = (tartib[0] / jami) if jami and tartib else 0.0
    top2 = (tartib[1] / jami) if jami and len(tartib) > 1 else 0.0

    kod = bosh.get("code") or ""
    bolimlar = {k[:2] for k in kodlar}
    kat_bolim = kodlash.divisions_for_category(product.get("category_code"))

    t = {
        "dalil": (bosh.get("evidence") or 0) >= p["dalil"],
        "ulush": (bosh.get("confidence") or 0.0) >= p["ulush"],
        "farq": (top1 - top2) >= p["farq"],
        # Nomzodlar bitta NACE bo'limida bo'lsa -- to'qnashuv yo'q.
        "oila": (not p["oila"]) or len(bolimlar) <= 1,
        # Mahsulotda kategoriya bo'lsa, kod o'sha bo'limdan chiqishi
        # kerak. HALOL ESLATMA: nomzod SQL i allaqachon shu bo'yicha
        # filtrlaydi, shuning uchun bu tekshiruv amalda deyarli hech
        # qachon qizarmaydi -- u REGRESSIYAGA qarshi turibdi.
        "kategoriya": (not p["kategoriya"]) or (not kat_bolim)
                      or (kod[:2] in kat_bolim),
    }
    # BOSH SO'Z ZIDDIYATI -- semantik qavat. Statistik signallar uni
    # KO'RMAYDI: server shkafi holati dalil 8/8, ulush 1.0 bilan
    # to'rt presetning hammasidan o'tib ketgandi.
    #
    # QIMMAT: bu qo'shimcha SQL so'rovi. Shuning uchun faqat shu
    # yergacha yetib kelganda -- ya'ni boshqa hamma tekshiruv o'tgan
    # nomzod uchun -- hisoblanadi. Chaqiruvchi tayyor natijani
    # uzatishi ham mumkin (ommaviy yo'l shundan foydalanadi).
    if p.get("ziddiyat") and all(t.values()):
        z = ziddiyat if ziddiyat is not None else bosh_ot_ziddiyati(bosh, product)
        t["ziddiyat"] = not z.get("ziddiyat")
        qaror["raqib"] = z.get("raqib")
    qaror["tekshiruv"] = t
    qaror["qaror"] = "auto" if all(t.values()) else "navbat"
    if qaror["qaror"] == "navbat":
        qaror["sabab"] = "siyosat:" + ",".join(k for k, v in t.items() if not v)
    return qaror


def _soz_bor(probe: str, vocab: Set[str]) -> bool:
    """`probe` so'zi `vocab` ichida bormi.

    Ruscha sifat oxiri kanonik shaklda 1-2 harf qoldirishi mumkin:
    `ofis` <-> `ofisno`. Uch va undan uzun davom (`monitoring`)
    ATAYLAB qabul qilinmaydi -- `monitor` `monitoring` ichidan
    topilmasligi kerak.
    """
    bases = {probe}
    if len(probe) >= 6:
        bases.add(probe[:-1])
    return any(
        base == w
        or (len(base) >= 4 and w.startswith(base) and len(w) - len(base) <= 2)
        for base in bases for w in vocab)


def _mazmunli(words: Set[str]) -> Set[str]:
    """Lot nomidan ma'no tashiydiganlarini ajratadi -- `_tokens()` bilan
    BIR XIL chegara: uch harfdan qisqa va to'xtash so'zlari tashlanadi."""
    return {w for w in words if len(w) >= 3 and w not in _STOP}


# ---------------------------------------------------------------------
# MOSLIK QOIDALARI
#
# `hozirgi` -- amaldagi xulq, STANDART. Qolganlari FAQAT o'lchov uchun
# (`kod_nima_bolardi.py`); ularni standart qilish AYRIM qaror bo'ladi
# va raqamsiz qilinmaydi.
# ---------------------------------------------------------------------
def _qoida_hozirgi(tokens: List[str], words: Set[str]) -> bool:
    """MAHSULOT nomining HAR BIR so'zi lot nomida bo'lishi shart."""
    return all(_soz_bor(t, words) for t in tokens)


def _qoida_teskari(tokens: List[str], words: Set[str]) -> bool:
    """LOT nomining har bir ma'noli so'zi mahsulot ichida bo'lishi shart."""
    lot = _mazmunli(words)
    if not lot:
        return False
    vocab = set(tokens)
    return all(_soz_bor(w, vocab) for w in lot)


def _qoida_qisqa_tomon(tokens: List[str], words: Set[str]) -> bool:
    """QISQAROQ tomon to'liq qoplanadi -- yo'nalish uzunlikka qarab."""
    lot = _mazmunli(words)
    if not lot:
        return False
    if len(lot) <= len(tokens):
        return _qoida_teskari(tokens, words)
    return _qoida_hozirgi(tokens, words)


def _qoida_kamida2(tokens: List[str], words: Set[str]) -> bool:
    """Kamida IKKI token mos kelsa yetarli (token bittagina bo'lsa -- bitta)."""
    n = sum(1 for t in tokens if _soz_bor(t, words))
    return n >= min(2, len(tokens))


#: STANDART QOIDA. 2026-09-12 da `hozirgi` dan `teskari` ga
#: o'tkazildi -- O'LCHOV bilan (ishlab chiqarish, 1840 mahsulot):
#:
#:     qoida          kod   qamrov   ochiq tender
#:     hozirgi          3     0.2%              4
#:     teskari        187    10.2%           2154
#:     qisqa_tomon    188    10.2%           2156
#:     kamida2         23     1.2%            290
#:
#: `qisqa_tomon` bir dona ko'p qamradi, lekin namunada ratsiyani
#: `Клавиатура` deb kodladi -- shu sabab RAD ETILDI.
#:
#: HALOL CHEKLOV: `teskari` namunasi 14 ta edi (13 to'g'ri, 1 xato --
#: server SHKAFI `Сервер` deb kodlandi). Bu aniqlik haqida qat'iy
#: gapirish uchun KICHIK namuna. Ma'lum zaiflik: qisqa lot nomi
#: ("Сервер") uzun mahsulot nomi ichiga kirib ketadi, bosh so'z esa
#: boshqa ("shkaf"). `MIN_SHARE` uni USHLAMAYDI -- tarixiy lotlarning
#: hammasi bir kodda bo'lsa ulush 1.0 chiqadi.
#:
#: QAROR loyiha egasiniki (2026-09-12): qamrov foydasi shu xatar
#: evaziga qabul qilindi va kodlar AVTOMATIK faollashtiriladi.
STANDART_QOIDA = "teskari"

QOIDALAR: Dict[str, Any] = {
    "hozirgi": _qoida_hozirgi,
    "teskari": _qoida_teskari,
    "qisqa_tomon": _qoida_qisqa_tomon,
    "kamida2": _qoida_kamida2,
}


def tahlil(product: Dict[str, Any],
           qoida: str = STANDART_QOIDA) -> Dict[str, Any]:
    """Kod topish urinishini SABABI bilan qaytaradi.

    HAR DOIM lug'at qaytaradi. `sabab` maydoni `SABABLAR` dan biri:
    kod topilgan bo'lsa `"kod"`, aks holda QAYSI BOSQICHDA to'xtaganini
    aytadi.

    Chegaralar (`MIN_EVIDENCE`, `MIN_SHARE`) BU YERDA O'ZGARMAYDI —
    bu funksiya faqat qaror sababini KO'RINADIGAN qiladi. Qamrovni
    chegarani pasaytirib oshirish precisionni yeydi va bu ataylab
    qilinmagan.

    Foiz modelning o'ziga bergan bahosi emas: shu mahsulot kontekstiga
    mos tarixiy lotlarning necha qismi aynan bitta kodda ekanining
    ulushi.
    """
    bosh: Dict[str, Any] = {
        "sabab": "tokensiz", "code": None, "confidence": None,
        "evidence": 0, "total": 0, "examples": [], "source": "historical_lots",
        "tokens": [], "nomzod": 0, "mos": 0, "kodlar": {},
        "kuchsiz_dalil": False,
    }
    tokens = _tokens(product)
    bosh["tokens"] = tokens
    if not tokens:
        return bosh

    clauses, params = _token_clauses(tokens)
    if not clauses:
        return bosh

    divisions = kodlash.divisions_for_category(product.get("category_code"))
    family = ""
    if divisions:
        params["divisions"] = divisions
        family = "AND substring(g.good_code from 1 for 2) = ANY(%(divisions)s)"

    bosh["sabab"] = "nomzodsiz"
    candidates = db.query(f"""
        SELECT g.good_code, g.name
        FROM tender_good g
        WHERE g.good_code IS NOT NULL
          AND length(g.good_code) >= 8
          AND g.name IS NOT NULL
          AND ({' OR '.join(clauses)})
          {family}
    """, params)
    # SQL faqat arzon nomzod olish uchun. Yakuniy tekshiruv kanonik SO'Z
    # bo'yicha: `monitor` `monitoring` ichidan topilmaydi.
    bosh["nomzod"] = len(candidates)
    counts: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}
    mos_f = QOIDALAR[qoida]
    for row in candidates:
        words = set(atama.normal(row["name"] or "").split())
        if not mos_f(tokens, words):
            continue
        code = (row["good_code"] or "")[:8]
        counts[code] = counts.get(code, 0) + 1
        bucket = examples.setdefault(code, [])
        if row["name"] not in bucket and len(bucket) < 4:
            bucket.append(row["name"])
    if candidates and not counts:
        bosh["sabab"] = "sozlar_mos_emas"
        return bosh
    if not counts:
        return bosh

    ranked = sorted(counts, key=lambda code: (-counts[code], code))
    code = ranked[0]
    total = sum(counts.values())
    evidence = counts[code]
    share = evidence / total if total else 0.0
    bosh.update({
        "code": code, "confidence": round(share, 3), "evidence": evidence,
        "total": total, "mos": total,
        "examples": examples.get(code) or [],
        # Eng kuchli uchta nomzod — "noaniq" holatida QAYSI oilalar
        # to'qnashganini odam ko'rishi kerak.
        "kodlar": {k: counts[k] for k in ranked[:3]},
    })
    # IKKI SABAB ALOHIDA: dalil kamligi (korpusda uchramagan) va
    # noaniqlik (ko'p oila teng) — butunlay boshqa ishlar.
    if evidence < MIN_EVIDENCE:
        bosh["sabab"] = "dalil_kam"
        return bosh
    if share < MIN_SHARE:
        bosh["sabab"] = "noaniq"
        return bosh
    bosh["sabab"] = "kod"
    # KUCHSIZ DALIL BANDI. Bu `sabab` ni O'ZGARTIRMAYDI — algoritm
    # qarori o'sha-o'sha. U faqat "avtomatik qo'llash mumkinmi"
    # savoliga javob beradi va IKKALA yo'l ham (CRUD va ommaviy)
    # shu yagona bayroqni o'qiydi.
    bosh["kuchsiz_dalil"] = bool(share < KUCHSIZ_ISHONCH
                                 and evidence <= KUCHSIZ_DALIL)
    return bosh


def classify_product(company_id: int, product_id: int, *, force: bool = False
                     ) -> Dict[str, Any]:
    """Mahsulotga ishonchli aniq kodni bog'laydi.

    Inson tasdiqlagan 8-belgili kod ustidan yozilmaydi. Avvalgi keng
    (5-belgili) kod esa kuchli 8-belgili dalil topilgandagina faolsizlanadi;
    qator o'chmaydi va audit tarixi saqlanadi.
    """
    product = db.query_one(
        "SELECT id, name, category_code, keywords FROM catalog_product "
        "WHERE id=%(p)s AND company_id=%(c)s",
        {"p": product_id, "c": company_id})
    if not product:
        return {"status": "not_found"}

    active = db.query(
        "SELECT code, tasdiqlagan FROM v_catalog_code_active "
        "WHERE product_id=%(p)s AND company_id=%(c)s",
        {"p": product_id, "c": company_id})
    exact = [r for r in active if len(r["code"] or "") >= 8]
    if exact and not force:
        return {"status": "ready", "code": exact[0]["code"]}
    # Qo'lda berilgan aniq kod avtomatik taxmindan ustun.
    human_exact = [r for r in exact if r.get("tasdiqlagan") != SYSTEM_ACTOR]
    if human_exact:
        return {"status": "ready", "code": human_exact[0]["code"]}

    natija = tahlil(product)
    # KUCHSIZ DALIL: kod bor, lekin avtomatik QO'LLANMAYDI — u
    # ko'rib chiqish navbatiga boradi. Ikkala yo'l (CRUD va ommaviy)
    # shu yerdan o'tadi, ya'ni qoida BITTA joyda.
    if natija["sabab"] == "kod" and natija.get("kuchsiz_dalil"):
        return {"status": "review", "code": natija["code"],
                "confidence": natija["confidence"],
                "evidence": natija["evidence"], "total": natija["total"],
                "sabab": "kuchsiz_dalil"}
    suggestion = suggest_exact_code(product)
    if not suggestion:
        # Nomi o'zgargan mahsulotda eski avtomatik kod qolib ketmasin.
        if force:
            db.execute_returning(
                "UPDATE catalog_product_code SET tasdiqlandi=NULL "
                "WHERE product_id=%(p)s AND company_id=%(c)s "
                "AND tasdiqlagan=%(actor)s RETURNING product_id",
                {"p": product_id, "c": company_id, "actor": SYSTEM_ACTOR})
        return {"status": "unresolved"}

    code = suggestion["code"]
    rejected = db.query_one(
        "SELECT 1 AS x FROM catalog_product_code "
        "WHERE product_id=%(p)s AND company_id=%(c)s AND code=%(code)s "
        "AND rad_etildi IS NOT NULL",
        {"p": product_id, "c": company_id, "code": code})
    if rejected:
        return {"status": "rejected"}

    if force:
        db.execute_returning(
            "UPDATE catalog_product_code SET tasdiqlandi=NULL "
            "WHERE product_id=%(p)s AND company_id=%(c)s "
            "AND tasdiqlagan=%(actor)s AND code<>%(code)s RETURNING product_id",
            {"p": product_id, "c": company_id, "actor": SYSTEM_ACTOR,
             "code": code})

    # SIYOSAT. `sabab='kod'` -- algoritm qarori; faollashtirish esa
    # ALOHIDA va QAT'IYROQ savol (`siyosat_qarori()` izohiga qarang).
    # O'tmagan nomzod TAKLIF bo'lib yoziladi, LEKIN faollashtirilmaydi:
    # u panelda odamni kutadi.
    qaror = siyosat_qarori(natija, product)

    # Taklif qatorini yaratamiz; faollashtirish siyosatga bog'liq.
    kodlash.taklif_yoz(company_id, product_id, [{
        "code": code, "skor": min(float(suggestion["confidence"]), 0.999),
    }])
    if qaror["qaror"] != "auto":
        db.execute_returning(
            "UPDATE catalog_product_code "
            "SET korib_chiqilsin = true, siyosat_sabab = %(s)s, "
            "    siyosat_at = now() "
            "WHERE product_id=%(p)s AND company_id=%(c)s AND code=%(code)s "
            "RETURNING product_id",
            {"p": product_id, "c": company_id, "code": code,
             "s": qaror.get("sabab")})
        return {"status": "review", "code": code,
                "sabab": qaror.get("sabab")}
    # `tasdiq_ishonch` MAJBURIY. `catalog_product_code_tasdiq_manba_chk`
    # tasdiqlangan har bir qatordan uni TALAB qiladi
    # (`schema_patch_inson_dalil.sql`). Bu yo'l o'sha patchdan keyin
    # YANGILANMAGAN edi va `--qolla` butunlay o'lik bo'lib qolgandi:
    #
    #     CheckViolation: new row for relation "catalog_product_code"
    #     violates check constraint "catalog_product_code_tasdiq_manba_chk"
    #
    # `servis` = "odam yo'q" -- aynan `tizim:auto` ning ma'nosi.
    # `catalog_product_code_aktor_izchil_chk` unga `tasdiq_actor_id
    # IS NULL` ni talab qiladi, shuning uchun u QO'YILMAYDI.
    row = db.execute_returning(
        "UPDATE catalog_product_code "
        "SET tasdiqlandi=now(), tasdiqlagan=%(actor)s, rad_etildi=NULL, "
        "    tasdiq_ishonch='servis', tasdiq_actor_id=NULL "
        "WHERE product_id=%(p)s AND company_id=%(c)s AND code=%(code)s "
        "AND rad_etildi IS NULL RETURNING product_id",
        {"p": product_id, "c": company_id, "code": code,
         "actor": SYSTEM_ACTOR})
    if not row:
        return {"status": "unresolved"}

    # Aniq kod bor ekan, keng kodlar natijani yana shishirmasin.
    db.execute_returning(
        "UPDATE catalog_product_code SET tasdiqlandi=NULL "
        "WHERE product_id=%(p)s AND company_id=%(c)s "
        "AND length(code)<8 AND tasdiqlandi IS NOT NULL RETURNING product_id",
        {"p": product_id, "c": company_id})
    return {"status": "ready", **suggestion}
