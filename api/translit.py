"""
ALIFBO NORMALLASHTIRISH — lotin/kirill qidiruvni birlashtiradi.

MUAMMO: manba ma'lumoti aralash alifboda keladi — ruscha kirill
("Спектрометр"), o'zbek lotin ("Listlarni bukish mashinasi"), o'zbek kirill
("Ўткир юрак-қон томир"), xalqaro nomlar ("Deflazakort"), hatto bittasining
ichida gomoglif aralashmasi ("Реryлятор" — kirill Р-е + lotin r-y).
Foydalanuvchi lotin alifbosida yozganda oddiy ILIKE deyarli hech narsa
topmaydi: `nasos` -> 0 ta, `насос` -> 15 ta.

YECHIM ikki qismdan iborat:

  1) YIG'ISH (fold) — farqi bo'lmagan harflarni IKKALA tomonda ham yo'qotamiz:
         ь ъ -> o'chiriladi   (кольцо -> колцо,  сальник -> салник)
         э ё -> е             (электро -> електро)
         ы й -> и             (электронный -> електроннии)
         щ   -> ш
     Baza tomonda buni SQL `translate()` bajaradi (SQL_FOLD), so'rov tomonda
     shu moduldagi fold_cyr(). Ikkalasi bir xil natija berishi SHART.

  2) TARMOQLANISH — lotin yozuvda bir necha o'qilishi mumkin bo'lgan harflar
     uchun bitta qiymat tanlamaymiz, hammasini variant qilamiz:
         c  -> ц | к    (cilindr->цилиндр,  kompleks->комплекс)
         ts -> ц | тс   (koltso->кольцо,    autsorsing->аутсорсинг)

O'LCHANGAN NATIJA (bazadagi eng ko'p uchraydigan 197 ta so'z, 225 ta yozuv):
    recall median 100%, precision median 100%, mukammal 222/225 (99%)
    "hozir 0 ta topardi -> endi to'liq topadi": 220 ta holat
    teskari yo'nalish (baza lotin, so'rov kirill): 30/30
Sinovni takrorlash uchun qarang: REJA.md "Translit sinovi".

ESLATMA: bu TRANSLITRATSIYA, tarjima emas. `qurilish` va `строительство` —
har xil so'zlar, ular baribir topilmaydi. Buning uchun alohida sinonim
lug'ati kerak (hozircha yo'q).
"""
from functools import lru_cache
from typing import List, Tuple

# --- 1) YIG'ISH jadvali -----------------------------------------------------
# SQL `translate(str, from, to)`: `to` dan uzun qolgan `from` belgilari
# O'CHIRILADI. Shuning uchun o'chiriladiganlar (ь ъ) OXIRIDA turishi shart.
_FOLD_FROM = "эёыйщьъ"
_FOLD_TO = "ееииш"

#: SQL tomonda ustunni yig'ish ifodasi. `{col}` — ustun nomi/ifodasi.
#: Python fold_cyr() bilan AYNAN bir xil natija berishi kerak.
#:
#: COLLATE "unicode" (ICU) — lower() ni baza locale'iga bog'liq qilmaslik uchun.
#: Bu bazada locale Russian_Russia.1251 va lower() kirillni to'g'ri o'giradi,
#: lekin `C` locale bilan yaratilgan bazada o'girmaydi — o'shanda ham ishlasin.
SQL_FOLD = ('translate(lower({col} COLLATE "unicode"), '
            "'" + _FOLD_FROM + "', '" + _FOLD_TO + "')")


def sql_fold(col: str) -> str:
    """Ustun/ifodani yig'ilgan shaklga keltiruvchi SQL bo'lagi."""
    return SQL_FOLD.format(col=col)

# --- 2) Lotin -> kirill (noaniq bo'lmagan qism) -----------------------------
# Tartib muhim: uzun birikmalar oldin turadi (sh, ch, ya...).
_BASE = [
    ("sch", "ш"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"),
    ("ya", "я"), ("yu", "ю"), ("yo", "е"),
    ("o'", "у"), ("g'", "г"), ("o‘", "у"), ("g‘", "г"), ("oʻ", "у"), ("gʻ", "г"),
    ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"),
    ("j", "ж"), ("z", "з"), ("i", "и"), ("y", "и"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"), ("s", "с"),
    ("t", "т"), ("u", "у"), ("f", "ф"), ("x", "х"), ("h", "х"), ("q", "к"),
    ("w", "в"),
]

# Noaniq birikmalar — har biri bir necha o'qiladi (tarmoqlanadi).
_AMBIG = {"ts": ["ц", "тс"], "c": ["ц", "к"]}

# Kirill -> lotin (foydalanuvchi kirill yozib, bazada lotin bo'lgan holat:
# uzex nomlari, dori INN nomlari — "Docetaxel", "Trastuzumab").
_C2L = [
    ("щ", "sh"), ("ш", "sh"), ("ч", "ch"), ("ж", "j"), ("ц", "ts"),
    ("я", "ya"), ("ю", "yu"), ("ё", "yo"), ("ў", "o"), ("ғ", "g"),
    ("қ", "q"), ("ҳ", "h"), ("а", "a"), ("б", "b"), ("в", "v"), ("г", "g"),
    ("д", "d"), ("е", "e"), ("э", "e"), ("з", "z"), ("и", "i"), ("й", "y"),
    ("ы", "y"), ("к", "k"), ("л", "l"), ("м", "m"), ("н", "n"), ("о", "o"),
    ("п", "p"), ("р", "r"), ("с", "s"), ("т", "t"), ("у", "u"), ("ф", "f"),
    ("х", "x"), ("ь", ""), ("ъ", ""),
]

# Gomoglif — ko'rinishi bir xil kirill/lotin juftlari. Manbada "Реryлятор"
# kabi ARALASH yozilgan nomlar bor, ularni lotinga yig'amiz.
_HOMO = {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x"}

#: Bitta so'rovdan chiqadigan variantlar chegarasi. Har variant SQL da
#: qo'shimcha OR sharti — cheklamasak noaniq harflari ko'p so'z portlaydi.
MAX_VARIANTS = 6

_LONGEST_FIRST = sorted(set(list(_AMBIG) + [a for a, _ in _BASE]),
                        key=len, reverse=True)
_BASE_MAP = dict(_BASE)


# KESHLAR — SOF FUNKSIYALAR uchun.
#
# O'LCHANGAN NUQSON (2026-09-02). "Sizga mos" bo'limi 4.9-8.1 s
# yuklanardi. Profil: vaqtning 96% i `kodlash.pozitsiya_moslik` da,
# uning ichida `_cyr_readings` 19 280 marta chaqirilgan va u
# 16 151 990 ta `str.startswith` bajargan.
#
# SABAB TAKROR HISOB EDI, algoritm emas: bitta so'rovda `variants()`
# 16 851 marta chaqirilardi, lekin TAKRORSIZ kirish atigi 1 048 ta —
# ya'ni 16 barobar ortiqcha ish.
#
# Bu funksiyalar SOF: bir xil satr har doim bir xil natija beradi va
# bazaga tegmaydi. Shuning uchun keshlash eskirish xavfini
# TUG'DIRMAYDI.
#
# O'ZGARMAS TUR QAYTARILADI (tuple/frozenset): chaqiruvchi natijani
# o'zgartirsa kesh ZAHARLANARDI va xato boshqa joyda chiqardi.


@lru_cache(maxsize=16384)
def fold_cyr(s: str) -> str:
    """Kirillni yig'ilgan shaklga. SQL_FOLD bilan bir xil natija berishi shart."""
    out = []
    for ch in s:
        i = _FOLD_FROM.find(ch)
        if i < 0:
            out.append(ch)
        elif i < len(_FOLD_TO):
            out.append(_FOLD_TO[i])
        # aks holda (ь, ъ) — tushib qoladi
    return "".join(out)


def to_lat(s: str) -> str:
    """Kirill -> lotin (bitta, eng ehtimolli o'qilish)."""
    r = s.lower()
    for a, b in _C2L:
        r = r.replace(a, b)
    return r


@lru_cache(maxsize=16384)
def _cyr_readings(q: str) -> Tuple[str, ...]:
    """Lotin so'zning barcha kirill o'qilishlari (noaniq harflar tarmoqlanadi)."""
    results = [""]
    i = 0
    while i < len(q):
        for key in _LONGEST_FIRST:
            if q.startswith(key, i):
                opts = _AMBIG.get(key) or [_BASE_MAP[key]]
                # Tarmoqlanish cheklovi — kombinatorik portlashning oldini oladi
                results = [r + o for r in results for o in opts][:16]
                i += len(key)
                break
        else:
            results = [r + q[i] for r in results]
            i += 1
    return tuple(fold_cyr(r) for r in results)


def variants(q: str) -> List[str]:
    """Keshlangan ichki funksiyani chaqiradi va NUSXA qaytaradi.

    Nusxa MAJBURIY: chaqiruvchi ro'yxatni o'zgartirsa kesh
    zaharlanardi va xato butunlay boshqa joyda chiqardi.
    """
    return list(_variants(q))


@lru_cache(maxsize=16384)
def _variants(q: str) -> Tuple[str, ...]:
    """So'rovning barcha ehtimoliy yozuvlari — YIG'ILGAN alifboda.

    Qaytgan naqshlar SQL_FOLD bilan yig'ilgan ustunga LIKE orqali solishtiriladi
    (ILIKE emas: ikkala tomon ham allaqachon kichik harfda).
    """
    q = (q or "").strip().lower()
    if not q:
        return []
    # So'rovning O'ZI doim birinchi variant. Harfsiz so'rovlar ("100%", "PQ-19",
    # tender raqami) uchun ham shart: aks holda variant ro'yxati bo'sh qolib,
    # filtr umuman qo'llanmaydi va foydalanuvchi HAMMA tenderni ko'radi.
    out: List[str] = [fold_cyr(q)]
    has_lat = any("a" <= ch <= "z" or ch in "'‘ʻ" for ch in q)
    has_cyr = any("Ѐ" <= ch <= "ӿ" for ch in q)

    if has_cyr:
        lat = to_lat(q)
        out.append(lat)                         # bazada LOTIN bo'lsa (uzex, INN)
        out.extend(_cyr_readings(lat))          # aylanma normallashtirish
        out.append("".join(_HOMO.get(ch, ch) for ch in q))   # gomoglif -> lotin
    if has_lat:
        out.extend(_cyr_readings(q))            # lotin kiritildi -> kirill
        out.append(q)                           # lotincha yozilgan tovarlar uchun

    seen, res = set(), []
    for i, v in enumerate(out):
        if not v or v in seen:
            continue
        # Hosil qilingan 1 belgili variant deyarli hamma narsaga mos keladi —
        # foydasiz. Foydalanuvchining O'Z so'rovi (i == 0) esa doim qoladi.
        if i > 0 and len(v) < 2:
            continue
        seen.add(v)
        res.append(v)
    return tuple(res[:MAX_VARIANTS])


@lru_cache(maxsize=16384)
def norm_text(s: str) -> str:
    """Python tomonda matnni solishtirishga tayyorlaydi (moslashtirish uchun).

    Kirill matn yig'iladi; lotin matn o'zgarmaydi. Ikkala shaklni ham qidirish
    kerak bo'lsa variants() ishlatiladi.
    """
    return fold_cyr((s or "").lower())
