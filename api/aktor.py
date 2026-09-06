"""
AKTOR KIMLIGI, RUXSAT VA AUDIT
==============================

Tender-AI ga KOMPANIYA kiradi, odam emas — bu ataylab
(`schema_patch_auth_2.sql`; hodimlar ERP da: `erp.app_user`). Lekin
tizimda INSON qarorlari bor: yo'naltirish, talab ko'rish, kodlash.
Ular kimga tegishli ekani shu modulda hal qilinadi.

ARXITEKTURA QARORI — CHEKLANGAN INTEGRATSIYA XARITASI
-----------------------------------------------------
Batafsil: `docs/erp_kimlik.md`. Qisqasi:

  A) ERP bergan kontekst — `erp.app_user` AYNAN shu bazada, lekin
     chegara shartnomasi VIEW orqali ishlashni talab qiladi
     (`erp.v_tender_status`, `erp.v_stock_balance`). Jadvalga
     bog'lanish shartnomani buzardi.
  B) Mahalliy sub-foydalanuvchi tizimi — `erp.app_user` ni TAKRORLASH.
     Aynan `schema_patch_auth_2.sql` olib tashlagan narsa. Rad etildi.
  C) CHEKLANGAN XARITA — TANLANDI. `actor` jadvali kimlik ombori emas:
     parol yo'q, sessiya yo'q, kirish bermaydi. U faqat "shu ijarachida
     shu ERP hodimi shu rol bilan ishlaydi" deydi.

YORLIQ DALILDAN OSHMAYDI
------------------------
Tender-AI hodimni O'ZI autentifikatsiya qila olmaydi. Shuning uchun
har atribut yoniga uning QANCHALIK ishonchli ekani ham yoziladi:

    erp_sessiya          odam ISBOTLANDI (ERP `erp.v_tai_actor`)
    aktor_elon           odam E'LON QILINDI (ro'yxatdagi aktor
                         ko'rsatildi, lekin isbotlanmadi)
    kompaniya_sessiyasi  faqat KOMPANIYA ma'lum, aktor yo'q
    servis               odam yo'q (ERP service kaliti)
    kuzatuvdan_oldin     aktor kuzatuvidan oldingi qator

`erp_sessiya` va `aktor_elon` ATAYLAB ajratilgan: birinchisi
tekshirilgan, ikkinchisi aytilgan.

IJARACHI IZOLYATSIYASI
----------------------
Bu modul aktorni HAR DOIM `company_id` bilan birga qidiradi. Ammo
asosiy himoya BU YERDA EMAS — u bazada: qaror jadvallari
`(company_id, actor_id)` ni KOMPOZIT FK bilan `actor` ga bog'laydi,
ya'ni boshqa ijarachining aktorini yozish JISMONAN mumkin emas.
Bu yerdagi tekshiruv — TUSHUNARLI XATO berish uchun, himoyaning
o'zi uchun emas.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from api import db, xatolar

# ---------------------------------------------------------------------------
# Lug'atlar
# ---------------------------------------------------------------------------
#: Ishonch darajalari — `ishonch_yaroqli()` SQL funksiyasi bilan BIR XIL.
#: Ikki joyda saqlanishi noqulay, lekin ular har xil qatlamda ishlaydi
#: va `_tests/aktor_test.py` ularning MOSLIGINI tekshiradi.
ISHONCH = ("erp_sessiya", "aktor_elon", "kompaniya_sessiyasi",
           "servis", "kuzatuvdan_oldin")

#: Aktori BO'LISHI SHART bo'lgan darajalar.
ISHONCH_AKTORLI = ("erp_sessiya", "aktor_elon")

ROLLAR = ("kuzatuvchi", "koruvchi", "tasdiqlovchi", "admin")

#: RUXSAT MATRITSASI. Amal -> uni bajara oladigan rollar.
#:
#: NEGA `korish` ham bor: rol berilgan aktor faqat o'qishi mumkin
#: bo'lgan holat haqiqiy (yangi xodim, tashqi kuzatuvchi).
#:
#: NEGA `admin` alohida: sozlama o'zgarishi (aktor qo'shish, rol
#: berish) — bu qarorlarni KIM qo'ya olishini belgilaydi, ya'ni u
#: qarorning o'zidan kuchliroq amal.
RUXSAT: Dict[str, Tuple[str, ...]] = {
    "korish":     ("kuzatuvchi", "koruvchi", "tasdiqlovchi", "admin"),
    "korib_chiq": ("koruvchi", "tasdiqlovchi", "admin"),
    "tasdiq":     ("tasdiqlovchi", "admin"),
    "rad":        ("tasdiqlovchi", "admin"),
    "sozlama":    ("admin",),
}

#: `X-Actor` sarlavhasi — kompaniya sessiyasi qaysi aktor nomidan
#: ishlayotganini E'LON qiladi. Bu ISBOT emas va shuning uchun
#: `aktor_elon` darajasini beradi.
AKTOR_HEADER = "x-actor"

#: ERP sessiyasi isboti. ERP `erp.v_tai_actor` view ini chop etsa
#: shu sarlavha orqali odam ISBOTLANADI.
ERP_SESSIYA_HEADER = "x-erp-session"


class RuxsatXato(RuntimeError):
    """Huquq yetmadi. `code` HTTP holatiga aylanadi.

    XATO KODI (`kod`) — TILGA BOG'LIQ EMAS. Xabar matni SERVER
    JURNALI uchun qoladi va javobga TUSHMAYDI: ilgari
    `detail=str(e)` orqali aynan shu o'zbekcha matn mijozga
    ketardi va rus/ingliz foydalanuvchisi uni o'zbekcha ko'rardi.
    Kod `api/xatolar.py:KODLAR` da tekshiriladi — imlo xatosi
    ISHLAB CHIQISHDA chiqadi.
    """

    def __init__(self, xabar: str, code: int = 403, *, kod: str = "",
                 params: Optional[Dict[str, Any]] = None):
        if kod and kod not in xatolar.KODLAR:
            raise KeyError(f"noma'lum xato kodi: {kod!r}")
        super().__init__(xabar)
        self.code = code
        self.kod = kod
        self.params = params or {}


# ---------------------------------------------------------------------------
# Sxema tayyorligi
# ---------------------------------------------------------------------------
def ready() -> bool:
    """`actor`/`audit_jurnal` jadvallari bormi.

    Patch qo'llanmagan bo'lsa modul JIMGINA o'chadi va eski xulq
    saqlanadi — bu `erp_status.ready()` bilan bir xil naqsh. Lekin
    audit yozolmaslik JIM qolmaydi: `yoz()` buni chaqiruvchiga
    aytadi.
    """
    return bool(db.scalar(
        "SELECT to_regclass('public.actor') IS NOT NULL "
        "AND to_regclass('public.audit_jurnal') IS NOT NULL"))


def erp_kontekst_ready() -> bool:
    """ERP `erp.v_tai_actor` shartnoma-view ini chop etganmi.

    YO'Q bo'lsa — bu XATO EMAS. Shunchaki `erp_sessiya` darajasi
    mavjud emas va eng yuqori ishonch `aktor_elon` bo'lib qoladi.
    Bu ochiq aytiladi (`/aktor/holat`), yashirilmaydi.
    """
    return bool(db.scalar("SELECT to_regclass('erp.v_tai_actor') IS NOT NULL"))


# ---------------------------------------------------------------------------
# Aktor ro'yxati
# ---------------------------------------------------------------------------
AKTOR_COLS = ("id, company_id, manba, erp_user_id, login, ism, rol, "
              "active, izoh, created_at, updated_at")


def royxat(company_id: int, *, faqat_faol: bool = False) -> List[Dict[str, Any]]:
    sql = (f"SELECT {AKTOR_COLS} FROM actor WHERE company_id = %(cid)s"
           + (" AND active" if faqat_faol else "")
           + " ORDER BY active DESC, ism")
    return db.query(sql, {"cid": company_id})


def bitta(company_id: int, actor_id: int) -> Optional[Dict[str, Any]]:
    """Aktorni QAT'IY o'z ijarachisi ichidan qidiradi.

    `company_id` shartda TURISHI SHART. Busiz boshqa ijarachining
    aktori nomini o'qib bo'lardi — bu ma'lumot sizishi (kim ishlaydi,
    qaysi rolda) va u FK bilan to'silmaydi, chunki FK YOZISHNI
    to'sadi, O'QISHNI emas.
    """
    return db.query_one(
        f"SELECT {AKTOR_COLS} FROM actor "
        "WHERE company_id = %(cid)s AND id = %(id)s",
        {"cid": company_id, "id": actor_id})


def qosh(company_id: int, *, login: str, ism: str, rol: str,
         manba: str = "mahalliy", erp_user_id: Optional[int] = None,
         izoh: Optional[str] = None) -> Dict[str, Any]:
    if rol not in ROLLAR:
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "rol", "qiymat": rol})
    if manba not in ("erp", "mahalliy"):
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "manba", "qiymat": manba})
    if manba == "erp" and not erp_user_id:
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "erp_user_id"})
    if manba == "mahalliy" and erp_user_id:
        raise xatolar.Xato("FIELD_INVALID", {"maydon": "erp_user_id"})
    if not (login or "").strip() or not (ism or "").strip():
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "login, ism"})
    return db.execute_returning(
        "INSERT INTO actor (company_id, manba, erp_user_id, login, ism, rol, izoh) "
        "VALUES (%(cid)s, %(manba)s, %(euid)s, %(login)s, %(ism)s, %(rol)s, %(izoh)s) "
        f"RETURNING {AKTOR_COLS}",
        {"cid": company_id, "manba": manba, "euid": erp_user_id,
         "login": login.strip(), "ism": ism.strip(), "rol": rol, "izoh": izoh})


def yangila(company_id: int, actor_id: int, *, rol: Optional[str] = None,
            ism: Optional[str] = None, active: Optional[bool] = None,
            izoh: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Aktorni yangilaydi. `company_id` SHARTDA — IDOR himoyasi."""
    if rol is not None and rol not in ROLLAR:
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "rol", "qiymat": rol})
    return db.execute_returning(
        "UPDATE actor SET rol = COALESCE(%(rol)s, rol), "
        "                 ism = COALESCE(%(ism)s, ism), "
        "                 active = COALESCE(%(active)s, active), "
        "                 izoh = COALESCE(%(izoh)s, izoh), "
        "                 updated_at = now() "
        " WHERE company_id = %(cid)s AND id = %(id)s "
        f"RETURNING {AKTOR_COLS}",
        {"cid": company_id, "id": actor_id, "rol": rol, "ism": ism,
         "active": active, "izoh": izoh})


# ---------------------------------------------------------------------------
# ERP moslikni O'LCHASH
# ---------------------------------------------------------------------------
def erp_moslikni_tekshir(company_id: int) -> Dict[str, Any]:
    """Xaritadagi `erp_user_id` lar ERP da HALI HAM bormi.

    `actor.erp_user_id` da FK ATAYLAB YO'Q (chegara shartnomasi
    jadvalga emas, view ga bog'lanishni talab qiladi). FK yo'qligi
    "tekshirilmaydi" degani EMAS — bu funksiya nomuvofiqlikni
    O'LCHAYDI va ko'rsatadi.

    ERP view i yo'q bo'lsa `tekshirildi=False` qaytadi — nol emas.
    "O'lchanmadi" va "nomuvofiqlik yo'q" BIR XIL KO'RINMASLIGI kerak.
    """
    aktorlar = [a for a in royxat(company_id) if a["erp_user_id"]]
    if not erp_kontekst_ready():
        return {"tekshirildi": False, "sabab": "erp.v_tai_actor yo'q",
                "erp_aktorlari": len(aktorlar), "yetim": []}
    idlar = [a["erp_user_id"] for a in aktorlar]
    if not idlar:
        return {"tekshirildi": True, "erp_aktorlari": 0, "yetim": []}
    bor = {r["erp_user_id"] for r in db.query(
        "SELECT erp_user_id FROM erp.v_tai_actor "
        "WHERE erp_user_id = ANY(%(ids)s)", {"ids": idlar})}
    yetim = [{"actor_id": a["id"], "login": a["login"],
              "erp_user_id": a["erp_user_id"]}
             for a in aktorlar if a["erp_user_id"] not in bor]
    return {"tekshirildi": True, "erp_aktorlari": len(aktorlar), "yetim": yetim}


# ---------------------------------------------------------------------------
# ERP dan aktor TAYYORLASH (provisioning)
# ---------------------------------------------------------------------------
#
# NEGA BU BOR. `erp_moslikni_tekshir()` BIR TOMONLAMA edi: "xaritadagi
# aktor ERP da hali bormi". Teskari savol — "ERP da odam bor, xaritada
# yo'q" — hech qayerda so'ralmasdi va javobi qo'lda `POST /aktor` edi.
# Natijasi o'lchandi (2026-09-03): `erp.v_tai_actor` da UCH FAOL odam,
# `public.actor` da ijarachi 2 uchun NOL qator, va shu sababli
# `_erp_sessiyadan()` hech qachon muvaffaqiyatli tugamasdi — har qaror
# `kompaniya_sessiyasi` darajasida yozilardi va sifat darvozasi
# (`v_sifat_darvoza`, 290 ta atributlangan qaror) nolda turardi.
#
# NEGA AVTOMATIK EMAS — LOGIN PAYTIDA SINXRONLAMAYMIZ. ERP odami
# o'zini istalgan ijarachiga yoza olsa ko'p-ijarachilik buzilardi:
# `_erp_sessiyadan()` ning ikkinchi sharti aynan shuning uchun bor.
# Xaritalash — `sozlama` huquqiga ega operatorning ANIQ amali, va
# ijarachi SESSIYADAN olinadi, so'rov tanasidan emas.

#: ERP roli -> TenderAI roli. TenderAI roli VAKOLAT beradi, shuning
#: uchun xarita ANIQ yoziladi: noma'lum ERP roli JIMGINA eng past
#: vakolatga tushirilmaydi, u umuman xaritalanmaydi va sabab bilan
#: qaytariladi (operator qaror qilsin).
#:
#: O'lchangan ERP rollari (2026-09-03): admin, broker, menejer.
ROL_XARITASI: Dict[str, str] = {
    "admin":   "admin",
    "broker":  "tasdiqlovchi",
    "menejer": "koruvchi",
}


def erp_nomzodlar(company_id: int) -> Dict[str, Any]:
    """ERP odamlari va ularning xaritadagi holati. FAQAT O'QISH.

    `erp.v_tai_actor` SESSIYA bo'yicha qator ko'paytiradi (u
    `app_session` ga LEFT JOIN qilingan), shuning uchun `DISTINCT`
    SHART: ikki faol sessiyali odam ikki qator berardi va
    sinxronizatsiya uni ikki marta urinib ko'rardi.

    `token_hash` va `expires_at` BU YERDA O'QILMAYDI. Ular sir va
    ularning API javobiga tushishi uchun hech qanday sabab yo'q.
    """
    if not erp_kontekst_ready():
        return {"tekshirildi": False, "sabab": "erp.v_tai_actor yo'q",
                "nomzodlar": []}

    erp_odamlar = db.query(
        "SELECT DISTINCT erp_user_id, login, ism, rol, faol "
        "  FROM erp.v_tai_actor ORDER BY erp_user_id")
    mavjud = {a["erp_user_id"]: a for a in royxat(company_id)
              if a["erp_user_id"] is not None}

    nomzodlar = []
    for u in erp_odamlar:
        a = mavjud.get(u["erp_user_id"])
        tai_rol = ROL_XARITASI.get(u["rol"])
        nomzodlar.append({
            "erp_user_id": u["erp_user_id"],
            "login": u["login"], "ism": u["ism"],
            "erp_rol": u["rol"], "erp_faol": u["faol"],
            "tai_rol": tai_rol,
            "actor_id": a["id"] if a else None,
            "tai_active": a["active"] if a else None,
            "holat": ("xaritalanmagan_rol" if tai_rol is None
                      else "xaritalangan" if a else "yangi"),
        })
    return {"tekshirildi": True, "nomzodlar": nomzodlar}


def erp_sinxron(company_id: int, *, quruq: bool = False) -> Dict[str, Any]:
    """ERP odamlarini `public.actor` ga IDEMPOTENT xaritalaydi.

    QOIDALAR — har biri ataylab:

      * `company_id` CHAQIRUVCHIDAN keladi va u SESSIYADAN olinadi.
        So'rov tanasida kompaniya YO'Q, shuning uchun kompaniyalararo
        xaritalash imkonsiz.

      * ERP da `faol=false` bo'lgan odam YANGI aktor sifatida
        YARATILMAYDI, va allaqachon xaritalangan bo'lsa
        `active=false` ga o'tkaziladi. Yo'nalish BIR TOMONLAMA:
        NOFAOLLASHTIRISH avtomatik (xavfsizlik tomonga yopiladi),
        FAOLLASHTIRISH esa hech qachon avtomatik emas — u vakolat
        berish demak va `PATCH /aktor/{id}` orqali aniq qilinadi.

      * Noma'lum ERP roli (`ROL_XARITASI` da yo'q) — o'tkazib
        yuboriladi va sababi qaytariladi. Eng past vakolatga
        JIMGINA tushirilmaydi: "bilmayman" ni "kuzatuvchi" ga
        aylantirish qaror qabul qilish bo'lardi.

      * ROL mavjud aktorda O'ZGARTIRILMAYDI. Rol — TenderAI
        vakolati; ERP da rol o'zgargani bu yerda avtomatik
        vakolat bermaydi. Nomuvofiqlik `rol_farqi` da qaytariladi.

      * Takror xaritalash bazada to'silgan
        (`actor_erp_bir_marta`: UNIQUE (company_id, erp_user_id)).
        Kod ham tekshiradi, lekin oxirgi so'z bazaniki.

    `quruq=True` — hech narsa yozilmaydi, faqat reja qaytadi.

    Qaytadi: har bir ERP odami uchun `amal` va `sabab`.
    """
    holat = erp_nomzodlar(company_id)
    if not holat["tekshirildi"]:
        return {"bajarildi": False, "sabab": holat["sabab"],
                "quruq": quruq, "natija": []}

    mavjud = {a["erp_user_id"]: a for a in royxat(company_id)
              if a["erp_user_id"] is not None}
    natija: List[Dict[str, Any]] = []

    for n in holat["nomzodlar"]:
        euid, tai_rol = n["erp_user_id"], n["tai_rol"]
        a = mavjud.get(euid)

        if tai_rol is None:
            natija.append({**_qisqa(n), "amal": "otkazildi",
                           "sabab": f"ERP roli xaritalanmagan: {n['erp_rol']!r}"})
            continue

        if a is None:
            if not n["erp_faol"]:
                natija.append({**_qisqa(n), "amal": "otkazildi",
                               "sabab": "ERP da nofaol — aktor yaratilmaydi"})
                continue
            if quruq:
                natija.append({**_qisqa(n), "amal": "yaratiladi",
                               "sabab": f"rol={tai_rol}"})
                continue
            row = qosh(company_id, login=n["login"], ism=n["ism"],
                       rol=tai_rol, manba="erp", erp_user_id=euid,
                       izoh="ERP sinxronizatsiyasi")
            natija.append({**_qisqa(n), "actor_id": int(row["id"]),
                           "amal": "yaratildi", "sabab": f"rol={tai_rol}"})
            continue

        # Allaqachon xaritalangan — faqat NOFAOLLASHTIRISH avtomatik.
        rol_farqi = (a["rol"] != tai_rol)
        if not n["erp_faol"] and a["active"]:
            if quruq:
                natija.append({**_qisqa(n), "actor_id": a["id"],
                               "amal": "nofaollashtiriladi",
                               "sabab": "ERP da nofaol"})
            else:
                yangila(company_id, a["id"], active=False)
                natija.append({**_qisqa(n), "actor_id": a["id"],
                               "amal": "nofaollashtirildi",
                               "sabab": "ERP da nofaol"})
        elif n["erp_faol"] and not a["active"]:
            # FAOLLASHTIRISH AVTOMATIK EMAS — bu vakolat qaytarish.
            natija.append({**_qisqa(n), "actor_id": a["id"],
                           "amal": "otkazildi",
                           "sabab": "TenderAI da nofaol — faollashtirish "
                                    "ANIQ qaror (PATCH /aktor/{id})"})
        else:
            natija.append({**_qisqa(n), "actor_id": a["id"],
                           "amal": "ozgarmadi",
                           "sabab": (f"rol farqi: TenderAI={a['rol']} "
                                     f"ERP={n['erp_rol']}->{tai_rol}")
                                    if rol_farqi else None})

    xulosa: Dict[str, int] = {}
    for r in natija:
        xulosa[r["amal"]] = xulosa.get(r["amal"], 0) + 1
    return {"bajarildi": True, "quruq": quruq,
            "xulosa": xulosa, "natija": natija}


def _qisqa(n: Dict[str, Any]) -> Dict[str, Any]:
    """Javobga tushadigan maydonlar — SIR EMASLARI."""
    return {"erp_user_id": n["erp_user_id"], "login": n["login"],
            "ism": n["ism"], "erp_rol": n["erp_rol"],
            "erp_faol": n["erp_faol"], "tai_rol": n["tai_rol"]}


# ---------------------------------------------------------------------------
# Aktorni SO'ROVDAN aniqlash
# ---------------------------------------------------------------------------
class Kimlik:
    """So'rov ortidagi kimlik: kim, qanchalik ishonchli, qanday rol.

    `actor_id` NULL bo'lishi MUMKIN va bu yolg'on emas — `ishonch`
    uni tushuntiradi.
    """

    __slots__ = ("company_id", "actor_id", "ishonch", "rol", "login", "ism")

    def __init__(self, company_id: int, actor_id: Optional[int], ishonch: str,
                 rol: Optional[str] = None, login: Optional[str] = None,
                 ism: Optional[str] = None):
        self.company_id = company_id
        self.actor_id = actor_id
        self.ishonch = ishonch
        self.rol = rol
        self.login = login
        self.ism = ism

    @property
    def odam(self) -> bool:
        return self.ishonch in ISHONCH_AKTORLI or \
            self.ishonch == "kompaniya_sessiyasi"

    def dict(self) -> Dict[str, Any]:
        return {"company_id": self.company_id, "actor_id": self.actor_id,
                "ishonch": self.ishonch, "rol": self.rol,
                "login": self.login, "ism": self.ism}

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"Kimlik(cid={self.company_id}, actor={self.actor_id}, "
                f"ishonch={self.ishonch!r}, rol={self.rol!r})")


def _erp_sessiyadan(company_id: int, token: str) -> Optional[Dict[str, Any]]:
    """ERP sessiya tokenidan aktorni ISBOTLAYDI.

    ERP `erp.v_tai_actor(erp_user_id, login, ism, rol, token_hash,
    expires_at)` view ini chop etishi kerak — shartnoma
    `docs/erp_kimlik.md` §4 da. View YO'Q bo'lsa bu yo'l umuman
    ishlamaydi va `None` qaytadi.

    XESH ERP TOMONIDA hisoblanadi: tender-ai xom tokenni ko'rmaydi
    va saqlamaydi. Bu yerda `digest()` bilan taqqoslash uchun
    `sha256` ishlatiladi — ERP ham shu algoritmni chop etgan.
    """
    if not erp_kontekst_ready() or not token:
        return None
    import hashlib
    xesh = hashlib.sha256(token.encode("utf-8")).hexdigest()
    r = db.query_one(
        "SELECT erp_user_id, login, ism, rol FROM erp.v_tai_actor "
        "WHERE token_hash = %(h)s AND expires_at > now()", {"h": xesh})
    if not r:
        return None
    # ERP hodimi shu IJARACHIGA xaritalanganmi. Xaritalanmagan bo'lsa —
    # ISBOT bor, lekin RUXSAT yo'q: ERP odami avtomatik ravishda har
    # ijarachiga kira olmaydi, aks holda ko'p ijarachilik buzilardi.
    a = db.query_one(
        f"SELECT {AKTOR_COLS} FROM actor "
        "WHERE company_id = %(cid)s AND erp_user_id = %(euid)s AND active",
        {"cid": company_id, "euid": r["erp_user_id"]})
    return a


def aniqla(request: Any, company_id: int) -> Kimlik:
    """So'rovdan kimlikni chiqaradi.

    TARTIB MUHIM — kuchliroq dalil ustun:
      1. SERVICE kaliti  -> odam YO'Q (`servis`)
      2. ERP sessiyasi   -> odam ISBOTLANDI (`erp_sessiya`)
      3. `X-Actor`       -> odam E'LON QILINDI (`aktor_elon`)
      4. aks holda       -> faqat kompaniya (`kompaniya_sessiyasi`)

    3-BOSQICH NEGA ISHONCHLI EMAS: sarlavhani sessiya egasi
    o'zgartira oladi, ya'ni bu "ishonchli kimlik" emas, "e'lon
    qilingan kimlik". U shunday YOZILADI. Baribir foydali: u
    ijarachi ICHIDAGI mas'uliyatni ajratadi va uni sessiya egasi
    ataylab buzishi kerak bo'ladi — tasodifan chalkashish yo'qoladi.
    """
    if getattr(request.state, "service", False):
        return Kimlik(company_id, None, "servis")

    if not ready():
        # Patch qo'llanmagan — eski xulq. Yolg'on daraja berilmaydi.
        return Kimlik(company_id, None, "kompaniya_sessiyasi")

    sarlavhalar = getattr(request, "headers", {}) or {}

    erp_token = sarlavhalar.get(ERP_SESSIYA_HEADER)
    if erp_token:
        a = _erp_sessiyadan(company_id, erp_token)
        if a:
            return Kimlik(company_id, a["id"], "erp_sessiya", a["rol"],
                          a["login"], a["ism"])
        # Token berilgan, lekin isbotlanmadi. JIMGINA pastroq darajaga
        # TUSHIRILMAYDI — bu "isbot bor" degan noto'g'ri taassurot
        # qoldirardi. Chaqiruvchi buni ko'rishi kerak.
        raise RuxsatXato(
            "ERP sessiyasi tasdiqlanmadi yoki hodim bu kompaniyaga "
            "xaritalanmagan.", 403, kod="ACTOR_ERP_SESSION_INVALID")

    xom = (sarlavhalar.get(AKTOR_HEADER) or "").strip()
    if xom:
        if not xom.isdigit():
            raise RuxsatXato(f"`{AKTOR_HEADER}` butun son bo'lishi kerak.", 400,
                             kod="ACTOR_HEADER_INVALID")
        a = bitta(company_id, int(xom))
        if not a:
            # BOSHQA IJARACHINING aktori ham shu yerga tushadi —
            # javob BIR XIL: "topilmadi". Farqni aytish "bu id bor"
            # degan ma'lumotni sizdirardi.
            raise RuxsatXato("Bunday aktor yo'q.", 404, kod="ACTOR_NOT_FOUND")
        if not a["active"]:
            raise RuxsatXato(f"Aktor faol emas: {a['login']}", 403,
                             kod="ACTOR_INACTIVE", params={"login": a["login"]})
        return Kimlik(company_id, a["id"], "aktor_elon", a["rol"],
                      a["login"], a["ism"])

    return Kimlik(company_id, None, "kompaniya_sessiyasi")


# ---------------------------------------------------------------------------
# Ruxsat
# ---------------------------------------------------------------------------
def aktor_majburiymi(company_id: int) -> bool:
    if not ready():
        return False
    return bool(db.scalar(
        "SELECT aktor_majburiy FROM company_account WHERE id = %(cid)s",
        {"cid": company_id}))


def ruxsat_tekshir(k: Kimlik, amal: str) -> None:
    """Amalni bajarishga huquq bormi. Yo'q bo'lsa `RuxsatXato`.

    IKKI HOLAT ATAYLAB FARQLANADI:

      * `servis` — bu odam emas. INSON qarorini qo'ya olmaydi va bu
        qat'iy: ERP kaliti bilan "tasdiqlangan" talab yozilsa,
        keyinchalik uni odam tasdiqlagan deb hisoblardik. `gate()`
        allaqachon `SERVICE_PATHS` bilan cheklaydi — bu IKKINCHI
        qatlam, chunki bitta ro'yxatga qo'shilgan yangi endpoint
        buni jimgina ochib yuborardi.

      * `kompaniya_sessiyasi` — aktor ko'rsatilmagan. Ijarachi
        `aktor_majburiy = false` bo'lsa RUXSAT beriladi (hozirgi
        xulq saqlanadi) va atribut shunday YOZILADI. `true` bo'lsa
        aniq aktor talab qilinadi.
    """
    if amal not in RUXSAT:
        raise xatolar.Xato("INVALID_ENUM", {"maydon": "amal", "qiymat": amal})

    if k.ishonch == "servis":
        raise RuxsatXato(
            "Bu amal INSON qarori — service kaliti bilan bajarilmaydi.", 403,
            kod="ACTOR_SERVICE_KEY_FORBIDDEN")

    if k.ishonch == "kompaniya_sessiyasi":
        if aktor_majburiymi(k.company_id):
            raise RuxsatXato(
                f"Bu kompaniyada aktor MAJBURIY: `{AKTOR_HEADER}` sarlavhasi.", 403,
                kod="ACTOR_REQUIRED", params={"sarlavha": AKTOR_HEADER})
        # Kompaniya hisobi — ijarachining egasi. Rol tekshirilmaydi,
        # chunki rol AKTORGA beriladi, aktor esa yo'q.
        return

    if k.rol not in RUXSAT[amal]:
        raise RuxsatXato(
            f"`{k.rol}` roli `{amal}` amalini bajara olmaydi "
            f"(kerak: {', '.join(RUXSAT[amal])}).", 403,
            kod="ACTOR_FORBIDDEN", params={"rol": k.rol, "amal": amal})


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def yoz(k: Kimlik, *, amal: str, entity: str, entity_id: int,
        oldin: Optional[Dict[str, Any]] = None,
        keyin: Optional[Dict[str, Any]] = None,
        izoh: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None) -> Optional[int]:
    """Audit qatorini yozadi. -> qator id, yoki None (sxema yo'q).

    JADVAL FAQAT QO'SHILADI — `UPDATE`/`DELETE` bazada trigger bilan
    to'silgan. Ya'ni tarixni jimgina qayta yozib bo'lmaydi.

    XATO YUTILMAYDI. Audit yozilmasa chaqiruvchi buni bilishi kerak:
    "o'zgarish bo'ldi, lekin izi yo'q" holati JIM qolmasligi kerak.
    """
    if not ready():
        return None
    r = db.execute_returning(
        "INSERT INTO audit_jurnal "
        "(company_id, actor_id, ishonch, amal, entity, entity_id, "
        " oldin, keyin, izoh, ip, user_agent) "
        "VALUES (%(cid)s, %(aid)s, %(ish)s, %(amal)s, %(ent)s, %(eid)s, "
        "        %(oldin)s, %(keyin)s, %(izoh)s, %(ip)s, %(ua)s) "
        "RETURNING id",
        {"cid": k.company_id, "aid": k.actor_id, "ish": k.ishonch,
         "amal": amal, "ent": entity, "eid": entity_id,
         "oldin": json.dumps(oldin, ensure_ascii=False, default=str) if oldin is not None else None,
         "keyin": json.dumps(keyin, ensure_ascii=False, default=str) if keyin is not None else None,
         "izoh": izoh, "ip": ip, "ua": (user_agent or "")[:300] or None})
    return (r or {}).get("id")


def tarix(company_id: int, *, entity: Optional[str] = None,
          entity_id: Optional[int] = None, actor_id: Optional[int] = None,
          limit: int = 200) -> List[Dict[str, Any]]:
    """Audit tarixi. `company_id` HAR DOIM shartda.

    TUZATILGAN YOZUV YASHIRILMAYDI, BELGILANADI (M-3). Jurnal
    append-only, ya'ni xato yozuv o'chirilmaydi — uning ustiga
    `amal='tuzatish'` qatori qo'shiladi (triggerning O'Z xato
    matni shu yo'lni ko'rsatadi).

    Ikkala yo'l ham noto'g'ri bo'lardi:
      * artefaktni KO'RSATISH — u haqiqiy amaldek o'qiladi;
      * uni YASHIRISH — audit jurnalidan qator yo'qolgandek
        ko'rinardi va bu auditni buzardi.

    Shuning uchun qator QOLADI va `tuzatilgan` bayrog'i bilan
    keladi; sabab `tuzatish_izohi` da.
    """
    shart = ["company_id = %(cid)s"]
    p: Dict[str, Any] = {"cid": company_id, "lim": max(1, min(limit, 1000))}
    if entity:
        shart.append("entity = %(ent)s"); p["ent"] = entity
    if entity_id is not None:
        shart.append("entity_id = %(eid)s"); p["eid"] = entity_id
    if actor_id is not None:
        shart.append("actor_id = %(aid)s"); p["aid"] = actor_id
    return db.query(
        "SELECT v.id, v.at, v.amal, v.entity, v.entity_id, v.ishonch, "
        "       v.actor_id, v.actor_login, v.actor_ism, v.actor_rol, "
        "       v.actor_manba, v.oldin, v.keyin, v.izoh, v.ip, "
        "       (t.id IS NOT NULL) AS tuzatilgan, t.izoh AS tuzatish_izohi "
        "  FROM v_audit_tolik v "
        "  LEFT JOIN audit_jurnal t "
        "    ON t.amal = 'tuzatish' AND t.entity = 'audit_jurnal' "
        "   AND t.entity_id = v.id "
        " WHERE " + " AND ".join("v." + x for x in shart) +
        " ORDER BY v.at DESC, v.id DESC LIMIT %(lim)s", p)


def atribut_sifati(company_id: int) -> List[Dict[str, Any]]:
    """Inson qarorlarining QANCHASI haqiqiy aktorga bog'langan.

    `nomalum` va `faqat_kompaniya` ustunlari YASHIRILMAYDI — ular
    atribut qarzining o'lchovi.
    """
    if not ready():
        return []
    return db.query(
        "SELECT * FROM v_atribut_sifati WHERE company_id = %(cid)s "
        "ORDER BY jadval", {"cid": company_id})
