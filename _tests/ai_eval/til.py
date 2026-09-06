# -*- coding: utf-8 -*-
"""
O'ZBEK LOTIN -> KIRILL TRANSLITERATSIYASI (baholash to'plami uchun)
====================================================================

NEGA `api/translit.py` ISHLATILMAYDI. U qidiruv uchun mo'ljallangan
va natijani YIG'ADI (`fold_cyr`): `ҳ қ ў ғ й` harflari yo'qoladi.

    api/translit.variants("Ehtiyot qismlar ... necha oy?")
      -> "ехтиет кисмлар ... неча ои?"

Bu YIG'ILGAN shakl -- indeks bilan solishtirish uchun to'g'ri, lekin
FOYDALANUVCHI bunday YOZMAYDI. Kirill klaviaturasidagi o'zbek
"Эҳтиёт қисмлар ... неча ой?" deb yozadi.

Baholash to'plami REAL KIRISHNI taqlid qilishi kerak, aks holda
"kirill so'rovlar ishlaydi" degan xulosa YIG'ISH yo'lini sinagan
bo'lardi, foydalanuvchi yo'lini emas.

BU MODUL TARJIMA QILMAYDI, YOZUVNI o'giradi. Ma'no o'zgarmaydi,
ya'ni ground truth ham o'zgarmaydi.
"""
from __future__ import annotations

import re

#: Ko'p harfli birikmalar BIRINCHI (uzunroq oldin).
#:
#: `oʻ`/`o'` -> `ў` va `gʻ`/`g'` -> `ғ`: apostrof uch xil belgida
#: uchraydi (ʻ U+02BB, ' U+2018, ' ASCII) va uchalasi ham qamrab
#: olinadi -- aks holda "o'rtacha" so'zi "оʻртача" bo'lib qolardi.
_KOP = [
    ("o'", "ў"), ("oʻ", "ў"), ("o‘", "ў"), ("o’", "ў"),
    ("g'", "ғ"), ("gʻ", "ғ"), ("g‘", "ғ"), ("g’", "ғ"),
    ("sh", "ш"), ("ch", "ч"), ("ng", "нг"),
    ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"),
    ("ts", "ц"),
]

_BIR = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "ҳ", "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с",
    "t": "т", "u": "у", "v": "в", "x": "х", "y": "й", "z": "з",
    "'": "ъ", "ʼ": "ъ", "ʻ": "ъ",
}


def _bosh_harf(cyr: str, asl_bosh: bool) -> str:
    return cyr.upper() if asl_bosh else cyr


def lotin_kirill(matn: str) -> str:
    """O'zbek lotin yozuvini kirillga o'giradi.

    SO'Z BOSHIDAGI `e` -> `э`. O'zbek imlosida so'z boshida `э`
    yoziladi ("Эҳтиёт", "Электр"), so'z ichida esa `е`. Buni
    hisobga olmaslik "еҳтиёт" beradi -- kirill o'quvchi uchun
    darhol ko'zga tashlanadigan xato.
    """
    out = []
    i = 0
    n = len(matn)
    while i < n:
        ch = matn[i]
        if not (ch.isascii() and ch.isalpha()) and ch not in "'ʼʻ‘’":
            out.append(ch)
            i += 1
            continue

        # SO'Z BOSHIMI: oldingi belgi harf emas.
        soz_boshi = (i == 0) or not (matn[i - 1].isalpha()
                                     or matn[i - 1] in "'ʼʻ‘’")
        bosh = ch.isupper()

        # 1) Ko'p harfli birikma.
        topildi = None
        for lat, cyr in _KOP:
            if matn[i:i + len(lat)].lower() == lat:
                topildi = (lat, cyr)
                break
        if topildi:
            lat, cyr = topildi
            out.append(_bosh_harf(cyr, bosh))
            i += len(lat)
            continue

        # 2) Bitta harf.
        past = ch.lower()
        if past == "e" and soz_boshi:
            out.append(_bosh_harf("э", bosh))
        elif past in _BIR:
            out.append(_bosh_harf(_BIR[past], bosh))
        else:
            out.append(ch)
        i += 1
    return "".join(out)


#: Yozuvni aniqlash — `rag_eval.til_aniqla` bilan bir xil qoida,
#: lekin bu yerda RUS ham ajratiladi (o'zbek kirilliga xos
#: harflar YO'Q bo'lsa va rus so'zlari bo'lsa).
_UZ_CYR = set("ҳқўғҲҚЎҒ")


def yozuv(matn: str) -> str:
    """`uz_lat` | `uz_cyr` | `ru` | `?`

    RUS va O'ZBEK KIRILLI ajratilishi CHEKLANGAN: agar matnda
    `ҳ қ ў ғ` bo'lmasa, alifbo ularni ajratmaydi. Shu holda `ru`
    qaytadi va bu TAXMIN -- to'plamda til MAYDONDA yoziladi,
    aniqlanmaydi.
    """
    kir = sum(1 for c in matn if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in matn if c.isascii() and c.isalpha())
    if kir == 0:
        return "uz_lat" if lat else "?"
    if any(c in _UZ_CYR for c in matn):
        return "uz_cyr"
    return "ru" if kir > lat else "uz_lat"


def _oz_sinov() -> int:
    """Transliteratorning O'ZI sinaladi.

    Aks holda u noto'g'ri o'girsa ham "kirill so'rovlar sinaldi"
    degan yashil natija chiqardi.
    """
    holatlar = [
        ("Ehtiyot qismlar uchun kafolat muddati necha oy?",
         "Эҳтиёт қисмлар учун кафолат муддати неча ой?"),
        ("O'zbekiston", "Ўзбекистон"),
        ("g'isht", "ғишт"),
        ("shartnoma", "шартнома"),
        ("chegara", "чегара"),
        ("yozuv", "ёзув"),
        ("yuk", "юк"),
        ("yangi", "янги"),
        ("elektr", "электр"),
        ("necha", "неча"),
        ("qancha", "қанча"),
        ("hujjat", "ҳужжат"),
        ("50 foiz", "50 фоиз"),
    ]
    xato = 0
    for lat, kutilgan in holatlar:
        olingan = lotin_kirill(lat)
        if olingan != kutilgan:
            print(f"  XATO: {lat!r} -> {olingan!r}, kutilgan {kutilgan!r}")
            xato += 1
    # Yozuv aniqlash.
    if yozuv("Эҳтиёт қисмлар") != "uz_cyr":
        print("  XATO: uz_cyr aniqlanmadi")
        xato += 1
    if yozuv("Какой срок гарантии") != "ru":
        print("  XATO: ru aniqlanmadi")
        xato += 1
    if yozuv("Ehtiyot qismlar") != "uz_lat":
        print("  XATO: uz_lat aniqlanmadi")
        xato += 1
    return xato


if __name__ == "__main__":
    import sys
    n = _oz_sinov()
    print(f"transliterator: {'OK' if not n else str(n) + ' XATO'}")
    sys.exit(1 if n else 0)
