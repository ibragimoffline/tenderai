# -*- coding: utf-8 -*-
"""
OMMAVIY MANZIL — YAGONA MANBA
==============================

Qabul qiluvchi BOSADIGAN har qanday havola (email matni, email HTML,
Telegram xabari, kelajakdagi tiklash/sozlama havolalari) SHU
moduldan quriladi. Boshqa joyda `f"{base}/..."` yozilmaydi.

NEGA ALOHIDA MODUL (o'lchangan 2026-09-01)
-------------------------------------------
Ilgari tanlash mantig'i `api/notify.py` ichida edi. Bu ikkita
noto'g'ri xabar berardi:

  1. "Ommaviy manzil — BILDIRISHNOMA xossasi". Aslida u ILOVANING
     xossasi: bitta joylashtirishda bitta ommaviy manzil bo'ladi va
     u parol tiklash havolasiga ham, chuqur havolaga ham bir xil
     kerak. Bildirishnoma moduliga qamalgan qiymatni ikkinchi
     chaqiruvchi TAKRORLAB yozardi — ikkita haqiqat manbai.
  2. Tekshiruv FAQAT YUBORISHDA edi. `APP_ENV=production` va manzil
     berilmagan holatda ilova MUAMMOSIZ ISHGA TUSHARDI va nosozlik
     faqat birinchi bildirishnoma navbatida — ya'ni soatlar keyin,
     ETL jurnalida — ko'rinardi. Endi `ishga_tushishda_tekshir()`
     buni ISHGA TUSHISHDA to'xtatadi.

O'LCHANGAN NOSOZLIK (2026-09-01, joylashtirish yo'li)
-----------------------------------------------------
`deploy/bin/deploy.sh` relizni `git archive` bilan yasaydi.
`frontend/.env` KUZATILMAGAN fayl, ya'ni relizga TUSHMAYDI. Shu
sababli `npm run build` `VITE_API_BASE` siz yurardi va qurilmaga
zaxira qiymat — `http://localhost:8000` — SINGIB QOLARDI:

    dist/assets/index-*.js:  localhost:8000  x1   (butun API)
    dist/assets/index-*.js:  localhost:5173  x3   (sozlama shakli)

Ya'ni ishlab chiqarish qurilmasidagi HAR SO'ROV foydalanuvchi
brauzerida `localhost:8000` ga ketardi. Bu modul serverni
qo'riqlaydi; qurilma tomoni `frontend/vite.config.ts` dagi
qo'rovul plagin va `deploy.sh` dagi qurilma tekshiruvi bilan
yopilgan.

MUHIT O'ZGARUVCHISI
-------------------
    APP_PUBLIC_URL    ASOSIY nom.
    PUBLIC_BASE_URL   ESKI nom (14-vazifada kiritilgan). Ishlaydi,
                      lekin ogohlantirish yozadi.

Ikkalasi ham berilgan va QIYMATLARI BOSHQA bo'lsa — XATO. "Qaysi
biri to'g'ri" degan savolga taxmin bilan javob berish yana ikkita
haqiqat manbai demak; buni jimgina hal qilish mumkin emas.

`localhost` GA RUXSAT — `dev` VA `staging`, `production` DA HECH QACHON
----------------------------------------------------------------------
Alohida "ruxsat bayrog'i" (`ALLOW_LOCAL=1` kabi) ATAYLAB
QO'SHILMADI: uni ishlab chiqarish muhitiga ham yozib qo'yish
mumkin bo'lardi va qo'riqchi o'z-o'zini o'chirardi. Ruxsatning
YAGONA ifodasi — MUHITNING O'ZI.

`staging` 2026-09-07 da qo'shildi va sabab O'LCHANGAN. Bu
o'rnatmada staging ga domen ATAYLAB berilmagan: nginx bloki
`127.0.0.1:8091` da tinglaydi va unga SSH tunnel orqali kiriladi.
Ya'ni staging da mahalliy manzil — nosozlik emas, ARXITEKTURA.

Ilgari `deploy/bin/oldindan-tekshir.sh` va shu modul ZID siyosat
yuritardi: joylashtirish tekshiruvi staging da mahalliy manzilni
o'tkazardi, ilova esa uni RAD ETARDI. Natijada `notify_test` va
`xavfsizlik_test` staging darvozasida yiqilardi va sabab
sozlamada emas, IKKI QATLAMNING KELISHMAGANIDA edi.

PRODUCTION UCHUN HECH NARSA YUMSHATILMADI: u yerda mahalliy
manzil ham, HTTPS bo'lmagani ham xato bo'lib qoladi. Noma'lum
muhit ham `production` kabi qattiq qaraladi (pastga qarang) —
"tanimadim" hech qachon "ruxsat" ga aylanmasin.
"""
from __future__ import annotations

import ipaddress
import logging
import os
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

log = logging.getLogger("api.ommaviy_url")

#: Asosiy va eski nom. Tartib MUHIM: birinchisi asosiy.
ENV_ASOSIY = "APP_PUBLIC_URL"
ENV_ESKI = "PUBLIC_BASE_URL"

#: Ommaviy manzilda BO'LMAYDIGAN host nomlari.
#: Nuqta bilan boshlanganlari — QO'SHIMCHA (suffiks) sifatida
#: tekshiriladi, qolganlari TO'LIQ moslik.
_MAHALLIY_NOM = ("localhost", "host.docker.internal",
                 ".localhost", ".local", ".internal", ".localdomain")

#: Ruxsat etilgan sxemalar. `ftp://`, `file://` va sxemasiz qiymat
#: brauzerda ochilmaydi — ular xato, ogohlantirish emas.
SXEMALAR = ("http", "https")

#: `dev` da mahalliy manzilga ruxsat; zaxira qiymat shu.
DEV_ZAXIRA = "http://localhost:5173"


class OmmaviyUrlXato(RuntimeError):
    """Ommaviy manzil sozlamasi YAROQSIZ. Jimgina o'tkazilmaydi."""


# ---------------------------------------------------------------------------
# Muhit
# ---------------------------------------------------------------------------
def muhit() -> str:
    """`dev` | `staging` | `production`.

    HAR CHAQIRUVDA o'qiladi, modul konstantasi EMAS: konstanta bo'lsa
    sinov muhitni o'zgartirib bo'lmay qolardi va `dev/staging/prod`
    xulqini o'lchash uchun modulni qayta yuklash kerak bo'lardi —
    ya'ni sinov haqiqiy kodni emas, qayta yuklash tartibini
    tekshirardi.
    """
    return os.environ.get("APP_ENV", "dev").strip().lower()


def dev_mi() -> bool:
    return muhit() == "dev"


#: Mahalliy (loopback/xususiy) manzilga ruxsat berilgan muhitlar.
#:
#: `production` bu yerda YO'Q va hech qachon bo'lmaydi.
#: Ro'yxat ATAYLAB YOPIQ: noma'lum yoki xato yozilgan `APP_ENV`
#: (masalan "prod", "Production ", bo'sh) ro'yxatga TUSHMAYDI va
#: qattiq qaraladi. "Tanimadim" -> "ruxsat" aylanishi bu qatlamda
#: eng qimmat xato bo'lardi.
MAHALLIY_RUXSAT_MUHITLARI = ("dev", "staging")


def mahalliyga_ruxsat() -> bool:
    """Shu muhitda mahalliy ommaviy manzil MAQBULMI.

    YAGONA MANBA. `oldindan-tekshir.sh` ham ayni semantikani
    ishlatadi (`MUHIT = production` -> to'siq, aks holda
    ogohlantirish) va `_tests/ommaviy_url_test.py` ikkalasini
    bir xil jadval bilan tekshiradi.
    """
    return muhit() in MAHALLIY_RUXSAT_MUHITLARI


def sozlangan() -> Tuple[str, str]:
    """Muhitdagi ommaviy manzil va U QAYSI o'zgaruvchidan kelgani.

    Qaytadi: `(qiymat, manba)`. Sozlanmagan bo'lsa `("", "")`.

    Ikkala nom ham berilgan va BOSHQA bo'lsa — `OmmaviyUrlXato`.
    """
    yangi = (os.environ.get(ENV_ASOSIY) or "").strip().rstrip("/")
    eski = (os.environ.get(ENV_ESKI) or "").strip().rstrip("/")
    if yangi and eski and yangi != eski:
        raise OmmaviyUrlXato(
            f"{ENV_ASOSIY} va {ENV_ESKI} IKKALASI ham berilgan, lekin "
            f"qiymatlari boshqa:\n"
            f"  {ENV_ASOSIY}={yangi}\n"
            f"  {ENV_ESKI}={eski}\n"
            f"  Qaysi biri to'g'ri ekanini taxmin qilib bo'lmaydi. "
            f"Eskisini ({ENV_ESKI}) o'chiring.")
    if yangi:
        return yangi, ENV_ASOSIY
    if eski:
        log.warning("%s ESKI nom - %s ga o'ting (%s hali ishlaydi)",
                    ENV_ESKI, ENV_ASOSIY, ENV_ESKI)
        return eski, ENV_ESKI
    return "", ""


# ---------------------------------------------------------------------------
# Mahalliylik
# ---------------------------------------------------------------------------
def _host(url: Optional[str]) -> str:
    """URL ning host qismi (portsiz, kichik harflarda)."""
    u = (url or "").strip()
    if "://" not in u:
        # Sxemasiz qiymat `urlsplit` da PATH bo'lib ketadi va host
        # bo'sh chiqadi. Bu holat `nosozliklar()` da alohida xato
        # sifatida ushlanadi; bu yerda faqat host qaytariladi.
        return ""
    try:
        h = urlsplit(u).hostname or ""
    except ValueError:
        return ""
    return h.lower().strip("[]")


def mahalliymi(url: Optional[str]) -> bool:
    """URL tashqi dunyodan OCHILMAYDIGAN manzilga ishora qiladimi.

    HOST bo'yicha tekshiriladi, matn ichidan qidirilmaydi. Ilgari
    `"localhost" in url` edi va u ikki tomonlama xato berardi:

      soxta MUSBAT:  `https://mylocalhost.uz`      -> mahalliy deb
      soxta MANFIY:  `https://10.0.0.5/app`        -> ommaviy deb

    Ikkinchisi xavfliroq: xususiy tarmoq manzili qabul qiluvchida
    ochilmaydi, lekin qo'riqchi uni o'tkazib yuborardi.
    """
    h = _host(url)
    if not h:
        return False
    for nom in _MAHALLIY_NOM:
        if (h.endswith(nom) if nom.startswith(".") else h == nom):
            return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_unspecified
                or ip.is_link_local)


# ---------------------------------------------------------------------------
# Tuzilma va siyosat tekshiruvi
# ---------------------------------------------------------------------------
def nosozliklar(base: Optional[str]) -> List[str]:
    """BAZAVIY manzilning TUZILMA xatolari ro'yxati (muhitdan qat'i nazar).

    Bo'sh ro'yxat — tuzilma joyida. Muhit qoidasi (mahalliylik) bu
    yerda EMAS: u `bazani_tekshir()` da, chunki u muhitga bog'liq.
    """
    u = (base or "").strip()
    xato: List[str] = []
    if not u:
        return ["qiymat bo'sh"]
    if any(c.isspace() for c in u):
        xato.append("ichida bo'shliq bor")
    if "://" not in u:
        xato.append("sxema yo'q (`https://` kerak)")
        return xato
    try:
        p = urlsplit(u)
    except ValueError as e:
        return [f"o'qib bo'lmadi: {e}"]
    if p.scheme.lower() not in SXEMALAR:
        xato.append(f"sxema `{p.scheme}` - faqat {'/'.join(SXEMALAR)}")
    if not p.hostname:
        xato.append("host yo'q")
    if p.query:
        # Havola `base + '/?tender=<id>'` deb quriladi. Bazada allaqachon
        # `?` bo'lsa ikkinchi `?` chiqadi va havola BUZILADI.
        xato.append("so'rov qismi (`?...`) bo'lmasin")
    if p.fragment:
        xato.append("langar (`#...`) bo'lmasin")
    return xato


def bazani_tekshir(base: Optional[str]) -> None:
    """Bazaviy manzil havola qurishga YAROQLIMI. Yaroqsiz bo'lsa TO'XTATADI.

    ATAYLAB XATO KO'TARADI, jimgina almashtirmaydi: to'g'ri manzil
    NOMA'LUM, taxmin qilib qo'yish esa yana bir buzuq havola berardi.
    """
    nos = nosozliklar(base)
    if nos:
        raise OmmaviyUrlXato(
            f"Ommaviy manzil YAROQSIZ: {base!r}\n"
            + "".join(f"  - {n}\n" for n in nos)
            + f"  Tuzatish: `{ENV_ASOSIY}=https://<domen>`.")
    # PRODUCTION DA HTTPS SHART. Ilgari `nosozliklar()` faqat sxema
    # BORLIGINI tekshirardi, ya'ni `http://zynq.uz` production da
    # o'tib ketardi — cookie `Secure` bilan yuboriladi va bunday
    # havolada SESSIYA UMUMAN o'rnatilmaydi, xato esa faqat
    # brauzerda ko'rinadi.
    #
    # `dev`/`staging` da `http://` qoladi: u yerda TLS tugatgich
    # bo'lmasligi mumkin va bu ARXITEKTURA, nosozlik emas.
    if muhit() == "production" and not (base or "").lower().startswith("https://"):
        raise OmmaviyUrlXato(
            f"Ommaviy manzil HTTPS EMAS: {base}\n"
            f"  APP_ENV=production da `https://` SHART: `Secure` cookie "
            f"shifrlanmagan ulanishda yuborilmaydi.\n"
            f"  Tuzatish: `{ENV_ASOSIY}=https://<domen>`.")
    if not mahalliyga_ruxsat() and mahalliymi(base):
        raise OmmaviyUrlXato(
            f"Ommaviy manzil MAHALLIY: {base}\n"
            f"  APP_ENV={muhit()} da bu qabul qiluvchida OCHILMAYDIGAN "
            f"havola demak.\n"
            f"  Tuzatish: `{ENV_ASOSIY}=https://<domen>` muhitda bering "
            f"yoki bildirishnoma sozlamasidagi `base_url` ni to'g'rilang.")


# ---------------------------------------------------------------------------
# Tanlash
# ---------------------------------------------------------------------------
def bazaviy_url(db_qiymati: Optional[str] = None) -> str:
    """Ommaviy bazaviy manzil. Tartib MUHIM.

    1. Bazadagi ijarachi qiymati - LEKIN u mahalliy bo'lsa VA muhitda
       haqiqiy manzil berilgan bo'lsa, MUHIT yutadi. Sabab o'lchangan:
       ishlab chiquvchi bazasida `base_url = 'http://localhost:5173'`
       yozib qo'yilgan va u joylashtirishga KO'CHIB o'tardi.
    2. Muhit (`APP_PUBLIC_URL`, eski nomi `PUBLIC_BASE_URL`).
    3. Oxirgi zaxira - mahalliy manzil (FAQAT `dev` uchun ma'noli;
       boshqa muhitda `bazani_tekshir()` uni TO'XTATADI).

    Bu funksiya HAVOLANI BLOKLAMAYDI - u faqat TANLAYDI. Bloklash
    `bazani_tekshir()` da va u `havola()` ichida chaqiriladi.
    """
    db_q = (db_qiymati or "").strip().rstrip("/")
    muhitdagi, _manba = sozlangan()
    if db_q and not (mahalliymi(db_q) and muhitdagi):
        return db_q
    if muhitdagi:
        if db_q:
            log.warning("bazadagi base_url mahalliy (%s) - muhitdagi "
                        "%s ishlatildi", db_q, ENV_ASOSIY)
        return muhitdagi
    return DEV_ZAXIRA


def havola(yol: str, db_qiymati: Optional[str] = None) -> str:
    """OMMAVIY HAVOLANING YAGONA QURUVCHISI.

    Email matni, email HTML, Telegram, chuqur havola va kelajakdagi
    tiklash/sozlama havolalari SHU funksiyadan o'tadi. Tekshiruv
    shu yerda bo'lgani uchun YANGI KANAL qo'shilganda uni unutib
    bo'lmaydi - kanal havolani o'zi qura olmaydi.

    `yol` `/` bilan boshlanishi kerak (masalan `/?tender=42`).
    """
    if not yol.startswith("/"):
        raise OmmaviyUrlXato(f"havola yo'li `/` bilan boshlansin: {yol!r}")
    base = bazaviy_url(db_qiymati)
    bazani_tekshir(base)
    return f"{base}{yol}"


# ---------------------------------------------------------------------------
# Ishga tushish qo'riqchisi
# ---------------------------------------------------------------------------
def ishga_tushishda_tekshir() -> str:
    """Sozlamani ISHGA TUSHISHDA tekshiradi. Yaroqsiz bo'lsa TO'XTATADI.

    NEGA ISHGA TUSHISHDA (o'lchangan): ilgari tekshiruv faqat
    yuborish paytida edi. `APP_ENV=production` va manzil berilmagan
    holatda xizmat MUAMMOSIZ ko'tarilardi, `/health` va `/ready`
    yashil bo'lardi, nosozlik esa birinchi bildirishnoma navbatida
    - soatlar keyin, ETL jurnalida - chiqardi. Ya'ni noto'g'ri
    sozlama SOATLAB ko'rinmasdi.

    Qaytadi: tanlangan manzil (jurnal uchun).
    """
    m = muhit()
    qiymat, manba = sozlangan()          # ziddiyat bo'lsa shu yerda yiqiladi

    if not qiymat:
        if m == "dev":
            log.info("ommaviy manzil sozlanmagan - `dev` da zaxira: %s",
                     DEV_ZAXIRA)
            return DEV_ZAXIRA
        raise OmmaviyUrlXato(
            f"APP_ENV={m} da `{ENV_ASOSIY}` MAJBURIY.\n"
            f"  Busiz bildirishnoma havolalari `{DEV_ZAXIRA}` ga "
            f"ishora qilardi - qabul qiluvchida ochilmaydigan havola.\n"
            f"  Tuzatish: muhit faylida `{ENV_ASOSIY}=https://<domen>`.")

    bazani_tekshir(qiymat)               # tuzilma + mahalliylik

    if urlsplit(qiymat).scheme.lower() != "https" and m != "dev":
        # XATO EMAS, OGOHLANTIRISH: ichki tarmoqdagi TLS tugatgichi
        # ortida `http` qonuniy bo'lishi mumkin. Lekin qabul
        # qiluvchiga ketadigan havola shifrlanmagan bo'lishi
        # jurnalda KO'RINSIN.
        log.warning("ommaviy manzil HTTPS emas: %s (APP_ENV=%s)", qiymat, m)

    log.info("ommaviy manzil: %s (manba: %s, muhit: %s)", qiymat, manba, m)
    return qiymat
