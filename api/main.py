"""
xt-xarid tender aggregator — Backend API (3-bosqich)
====================================================
O'z bazamizdan (PostgreSQL 'xtxarid') dashboardga ma'lumot beruvchi API.
Manba API'ga to'g'ridan-to'g'ri ulanmaydi (arxitektura tamoyili).

Ishga tushirish:
    cp .env.example .env          # va parolni to'ldiring
    .venv/bin/pip install -r requirements-api.txt
    .venv/bin/uvicorn api.main:app --reload --port 8000
    # Swagger (sinov uchun): http://localhost:8000/docs

Endpointlar:
    GET /tenders            — filtrlanadigan ro'yxat (X-Total-Count header bilan)
    GET /tenders/{id}       — bitta tender + lotlar + tovarlar
    GET /stats             — dashboard umumiy ko'rsatkichlari
    GET /regions           — hudud dropdown
    GET /statuses          — status dropdown
    GET /health            — sog'liq tekshiruvi
"""
import json
import logging
import io
import os
import time
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote, urlsplit

import requests
from dotenv import load_dotenv
from fastapi import (BackgroundTasks, Cookie, Depends, FastAPI, File, Header,
                     Query, Request, Response, UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (JSONResponse, RedirectResponse,
                               Response as FileResponse, StreamingResponse)
from pydantic import BaseModel, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

load_dotenv()  # .env ni import paytida yuklaymiz (pool DSN'ni ko'rishi uchun)

from api import (ai, ai_chat, ai_docs, ai_gonogo, ai_match, auth, jurnal,  # noqa: E402
                 catalog_auto, compliance, db, erp_status, erp_stock, i18n, importer,
                 kodlash, matching, notify, ommaviy_url, pricing, queries,
                 saqlash, stock, telegram, translit, xatolar, yuklama)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# So'rov modellari (aqlli moslashtirish)
# ---------------------------------------------------------------------------
class ProfileIn(BaseModel):
    # --- akkaunt (yon paneldagi foydalanuvchi bloki shulardan o'qiydi) ---
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    # --- qidiruv sozlamalari ---
    name: Optional[str] = None
    keywords: List[str] = []
    regions: List[str] = []
    currency: Optional[str] = None
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None
    # --- salohiyat (Go/No-Go uchun; hammasi ixtiyoriy) ---
    # To'ldirilmagani "yomon" degani emas, "ma'lumot yo'q" degani — AI shunda
    # tegishli mezonni `malumot_yoq` deb belgilaydi va qarorni Review ga tushiradi.
    about: Optional[str] = None
    certificates: List[str] = []
    clearances: List[str] = []
    experience_years: Optional[int] = None
    max_contract_value: Optional[float] = None
    max_contract_currency: Optional[str] = None
    employees: Optional[int] = None
    capacity_note: Optional[str] = None
    lead_time_days: Optional[int] = None
    min_margin_percent: Optional[float] = None
    constraints_note: Optional[str] = None


class SavedSearchIn(BaseModel):
    """YARATISH uchun. `name` MAJBURIY: nomsiz qidiruvni yon panelda
    ajratib bo'lmaydi."""

    name: str
    keywords: List[str] = []
    categories: List[str] = []      # SAQLANADI, lekin hali ISHLATILMAYDI
    regions: List[str] = []
    currency: Optional[str] = None
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None
    notify: bool = True             # SAQLANADI, lekin hali ISHLATILMAYDI


class SavedSearchPatchIn(BaseModel):
    """TAHRIRLASH uchun — HAR MAYDON IXTIYORIY.

    NEGA ALOHIDA MODEL (o'lchangan): interfeys shakli
    (`ProfileForm.tsx`) `categories` va `notify` ni YUBORMAYDI.
    To'liq almashtirish semantikasida ular har tahrirlashda
    JIMGINA tozalanardi — foydalanuvchi buni hech qayerda
    ko'rmasdi. `notify_settings` da aynan shu xato bo'lgan va
    `{"enabled": false}` yuborish SMTP sozlamasini o'chirib
    yuborardi.
    """

    name: Optional[str] = None
    keywords: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    currency: Optional[str] = None
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None
    notify: Optional[bool] = None


class CatalogItemIn(BaseModel):
    name: str
    category_code: Optional[str] = None
    keywords: List[str] = []
    unit: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    notify: bool = True


class CatalogMatchIn(BaseModel):
    # Katalogdagi "N ta mos" bosilganda aynan shu mahsulot tekshiriladi.
    # None = butun katalog bo'yicha umumiy ko'rinish.
    product_id: Optional[int] = None
    region: Optional[str] = None
    currency: Optional[str] = None
    # Mahsulot/xizmat filtri — foydalanuvchi katalogiga qo'shimcha toraytirish
    products: List[str] = []
    services: List[str] = []
    # MATNLI QIDIRUV. O'LCHANGAN NUQSON (2026-09-02): bu maydon YO'Q edi
    # va interfeys uni yubormasdi ham -> "Sizga mos" sahifasida qidiruv
    # maydoni bor edi, lekin natijaga TA'SIR QILMASDI. Foydalanuvchi
    # yozgan so'z JIMGINA yo'qolardi va u buni "moslik yo'q" deb
    # o'qirdi — salbiy shartdan olingan yolg'on xulosa.
    q: Optional[str] = None
    # Standart ro'yxat aniq kod mosligi. Eski matn qidiruvi faqat maxsus
    # taxminiy ko'rinish so'ralsa ishlaydi.
    include_probable: bool = False
    limit: int = 20
    offset: int = 0


#: Foizli maydonlarning yuqori chegarasi (None = faqat manfiy bo'lmasin).
#: Ustama 1000% gacha — chakana savdoda uchraydi; QQS va zaxira mantiqan 100% dan
#: oshmaydi, oshsa bu kiritish xatosi.
_PERCENT_MAX = {
    "markup_percent": 1000, "risk_reserve_percent": 100,
    "logistics_percent": 100, "vat_percent": 100,
    "risk_reserve_fixed": None, "logistics_fixed": None,
}
_MAYDON_NOMI = {
    "markup_percent": "Ustama", "risk_reserve_percent": "Risk zaxirasi",
    "logistics_percent": "Logistika", "vat_percent": "QQS",
    "risk_reserve_fixed": "Risk zaxirasi (qat'iy)",
    "logistics_fixed": "Logistika (qat'iy)",
}


class PricingSettingsIn(BaseModel):
    """Narx hisobining odatiy parametrlari (bitta faol yozuv).

    Chegaralar ATAYIN qo'yilgan: manfiy ustama yoki 500% QQS smetani jimgina
    ma'nosiz qiladi (tavsiya narxi tannarxdan past chiqadi) va buni faqat
    tender yutqazilgach sezish mumkin. Shuning uchun kirishda rad etamiz.

    Maydonlar Optional: yuborilmagani "TEGMA" degani, "standartga qaytar" emas.
    """
    markup_percent: Optional[float] = None
    risk_reserve_percent: Optional[float] = None
    risk_reserve_fixed: Optional[float] = None
    logistics_percent: Optional[float] = None
    logistics_fixed: Optional[float] = None
    vat_percent: Optional[float] = None
    currency: Optional[str] = None

    @field_validator("markup_percent", "risk_reserve_percent", "logistics_percent",
                     "vat_percent", "risk_reserve_fixed", "logistics_fixed")
    @classmethod
    def _oraliq(cls, v, info):
        # Pydantic'ning o'z `Field(ge=…)` xabari INGLIZCHA ("Input
        # should be…"), interfeys esa UCH TILLI. Ilgari bu yerda
        # o'zbekcha jumla yozilardi va u rus foydalanuvchisiga ham
        # o'zbekcha ketardi. Endi KOD ko'tariladi: uni 422
        # ishlovchisi `error.fields[].code` ga qo'yadi va interfeys
        # o'z tilida ko'rsatadi.
        if v is None:
            return v
        yuqori = _PERCENT_MAX.get(info.field_name)
        if v < 0:
            raise ValueError("FIELD_NEGATIVE")
        if yuqori is not None and v > yuqori:
            raise ValueError("FIELD_PERCENT_RANGE")
        return v


class PricingItemIn(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    qty: float = 0
    unit_cost: float = 0               # BIZNING tannarximiz
    currency: Optional[str] = None
    ref_price: Optional[float] = None  # buyurtmachi narxi — faqat mo'ljal


class PricingIn(BaseModel):
    """Smetaning kiruvchi holati. Byudjet va minimal marja ATAYLAB YO'Q —
    ularni server bazadan o'zi oladi (mijoz yuborganiga ishonmaydi)."""
    items: List[PricingItemIn] = []
    markup_percent: Optional[float] = None
    risk_reserve_percent: Optional[float] = None
    risk_reserve_fixed: Optional[float] = None
    logistics_percent: Optional[float] = None
    logistics_fixed: Optional[float] = None
    vat_percent: Optional[float] = None
    currency: Optional[str] = None
    manual_price: Optional[float] = None   # broker qo'lda kiritgan narx
    note: Optional[str] = None


class NotifySettingsIn(BaseModel):
    """Bildirishnoma sozlamalari (email + Telegram). SIRLAR YO'Q — SMTP paroli
    va Telegram bot tokeni .env dan o'qiladi (SMTP_PASSWORD,
    TELEGRAM_BOT_TOKEN), bazaga ham, bu modelga ham tushmaydi.

    Maydonlar Optional: yuborilmagani "TEGMA" degani. Ilgari standart qiymat
    qo'yilgani uchun `{"enabled": false}` yuborish SMTP hostini ham,
    qabul qiluvchi emailni ham o'chirib yuborardi.
    """
    enabled: Optional[bool] = None       # EMAIL kanali
    email: Optional[str] = None          # bo'sh -> company_profile.email
    min_score: Optional[int] = None      # moslik chegarasi (IKKALA kanal uchun)
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    from_email: Optional[str] = None
    base_url: Optional[str] = None       # kartochka havolasi shundan quriladi
    # --- Telegram kanali (emaildan MUSTAQIL yoqiladi) ---
    telegram_enabled: Optional[bool] = None
    telegram_chat_id: Optional[str] = None
    # --- Xabar tili: 'uz' | 'ru' | 'en' ---
    # Interfeys tili almashtirilganda frontend AYNAN shu maydonni yuboradi
    # (boshqa maydonlarsiz — `exclude_unset` qolganini tegmasdan qoldiradi).
    # Xabarni server yuboradi, shuning uchun tanlov bazada turishi shart.
    lang: Optional[str] = None

    @field_validator("lang")
    @classmethod
    def _til_kodi(cls, v):
        """Noma'lum til XATO BERMAYDI — o'zbekchaga keltiriladi.

        Sabab: til yumshoq afzallik. Buzuq kod tufayli sozlamani umuman
        saqlab bo'lmay qolish, xabar bir tilda kelishidan ko'ra yomonroq.
        """
        return i18n.norm_lang(v) if v is not None else v

    @field_validator("min_score")
    @classmethod
    def _ball_oraligi(cls, v):
        if v is not None and not 0 <= v <= 100:
            raise ValueError("FIELD_SCORE_RANGE")
        return v

    @field_validator("smtp_port")
    @classmethod
    def _port_oraligi(cls, v):
        if v is not None and not 1 <= v <= 65535:
            raise ValueError("FIELD_PORT_RANGE")
        return v

    @field_validator("email", "from_email")
    @classmethod
    def _email_shakli(cls, v):
        """Yuzaki, lekin yetarli tekshiruv. Buzuq manzil bazaga tushsa,
        xato faqat ETL dan keyin — jimgina — chiqadi va foydalanuvchi
        bildirishnoma kelmayotganini bilmay yuradi."""
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s.]+(\.[^@\s.]+)+", v):
            raise ValueError("EMAIL_INVALID")
        return v


class CompanyDocumentIn(BaseModel):
    """Kompaniya hujjati. Sanalar ixtiyoriy: `valid_until` bo'sh bo'lsa
    hujjat MUDDATSIZ deb qaraladi ("ma'lumot yo'q" emas)."""
    doc_type: str
    name: str
    number: Optional[str] = None
    issued_at: Optional[date] = None
    valid_until: Optional[date] = None
    file_name: Optional[str] = None
    file_ref: Optional[str] = None
    note: Optional[str] = None

    @field_validator("doc_type")
    @classmethod
    def _tur_kanonik(cls, v):
        """Cheklist hujjatni FAQAT `code` bo'yicha topadi. Noma'lum turdagi
        yozuv hech qaysi bandga tushmaydi — foydalanuvchi hujjatni kiritgan
        bo'lsa ham cheklist "yo'q" deb turaveradi. Shuning uchun rad etamiz."""
        v = (v or "").strip()
        if v not in compliance.BY_CODE:
            raise ValueError("INVALID_ENUM")
        return v

    @field_validator("name")
    @classmethod
    def _nom_bosh_emas(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("FIELD_EMPTY")
        return v

    @field_validator("valid_until")
    @classmethod
    def _muddat_berilishdan_keyin(cls, v, info):
        """Amal qilish muddati berilgan sanadan oldin bo'lsa — bu kiritish
        xatosi, va cheklist buni "muddati o'tgan" deb noto'g'ri belgilaydi."""
        iss = info.data.get("issued_at")
        if v and iss and v < iss:
            raise ValueError("DATE_ORDER_INVALID")
        return v


class MatchIn(BaseModel):
    profile: ProfileIn
    # Qattiq filtrlar (profildan ALOHIDA — profil faqat skorlaydi, filtrlamaydi)
    status: Optional[str] = "open"
    region: Optional[str] = None
    currency: Optional[str] = None
    q: Optional[str] = None
    category: Optional[str] = None
    # Mahsulot/xizmat filtri — `q` dan alohida (faqat tovar nomi bo'yicha)
    products: List[str] = []
    services: List[str] = []
    limit: int = 20
    offset: int = 0


class JoylashuvXato(RuntimeError):
    """Joylashtirish sozlamalari BIR-BIRIGA ZID."""


def joylashuv_tekshir(ommaviy: str) -> None:
    """Proksi ortidagi sozlamalar IZCHILMI — ISHGA TUSHISHDA.

    NEGA KERAK. Uchta sozlama bir-biriga bog'liq, lekin uch xil
    joyda turadi: `APP_PUBLIC_URL` (muhit fayli), `TRUST_PROXY`,
    `AUTH_COOKIE_SECURE`. Namunalar (`deploy/env/*.example`) to'g'ri,
    lekin haqiqiy fayl `/etc/tenderai/<muhit>.env` da QO'LDA
    tahrirlanadi (`docs/deploy.md` §3) — ya'ni ziddiyat qonuniy
    yo'l bilan paydo bo'ladi.

    IKKI ZIDDIYAT, IKKI XIL OG'IRLIK:

    1. `http://` + `AUTH_COOKIE_SECURE=1` -> **O'LIMGA OLIB KELADI**.
       Brauzer `Secure` cookie ni shifrlanmagan ulanish orqali
       YUBORMAYDI (`localhost` dan tashqari). Xizmat ko'tariladi,
       `/health` va `/ready` YASHIL bo'ladi, va HECH KIM KIRA
       OLMAYDI. Aynan shu sinf — "yashil, lekin o'lik" — bu
       loyihada bir necha marta chiqqan, shuning uchun bu
       TO'XTATADI, ogohlantirmaydi.

    2. `https://` + `TRUST_PROXY=0` -> **JIMGINA NOTO'G'RI**.
       Caddy ortida har so'rov `127.0.0.1` dan kelgandek ko'rinadi:
       kirish urinishlari chegarasi BUTUN DUNYO uchun bitta
       hisoblagichga aylanadi va audit IP si ma'nosiz bo'ladi.
       Xizmat ishlaydi, shuning uchun bu OGOHLANTIRISH — lekin
       jurnalda KO'RINADI.

    `dev` da ikkalasi ham tekshirilmaydi: u yerda `http://localhost`
    normal va `Secure` cookie `localhost` uchun brauzerda ishlaydi.
    """
    muhit = ommaviy_url.muhit()
    if muhit == "dev":
        return
    sxema = urlsplit(ommaviy).scheme.lower()

    if sxema == "http" and COOKIE_SECURE:
        raise JoylashuvXato(
            f"APP_PUBLIC_URL={ommaviy} (http) va AUTH_COOKIE_SECURE=1 — "
            "ZID.\n"
            "  Brauzer `Secure` cookie ni http orqali YUBORMAYDI: "
            "xizmat yashil ko'rinadi, kirish esa IMKONSIZ.\n"
            "  Tuzatish: HTTPS qo'ying (tavsiya) yoki "
            "`AUTH_COOKIE_SECURE=0` (faqat ichki tarmoqda).")

    if sxema == "https" and not TRUST_PROXY:
        logging.getLogger("api").warning(
            "APP_PUBLIC_URL https, lekin TRUST_PROXY=0 — proksi ortida "
            "har so'rov 127.0.0.1 dan kelgandek ko'rinadi: kirish "
            "chegarasi va audit IP si NOTO'G'RI bo'ladi. "
            "Tuzatish: muhit faylida TRUST_PROXY=1.")


# ---------------------------------------------------------------------------
# Lifespan — pool init/close
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # JURNAL BIRINCHI — undan keyingi har qadam yozilsin.
    fmt = jurnal.sozla()
    logging.getLogger("api").info(
        "ishga tushdi", extra={"muhit": os.environ.get("APP_ENV", "dev"),
                               "log_format": fmt,
                               "docs": API_DOCS})
    # OMMAVIY MANZIL — BAZADAN OLDIN. Bu SOF sozlama tekshiruvi:
    # noto'g'ri bo'lsa xizmat ko'tarilmasligi kerak va buni aniqlash
    # uchun bazaga ulanish shart emas. Xato USHLANMAYDI — `lifespan`
    # dan chiqqan istisno uvicorn'ni to'xtatadi, systemd qayta
    # urinadi va jurnalda SABAB turadi. Ilgari bu tekshiruv faqat
    # yuborish paytida edi: `APP_ENV=production` da manzil
    # berilmagan bo'lsa ham xizmat yashil ko'rinardi va nosozlik
    # soatlar keyin, ETL jurnalida chiqardi.
    _ommaviy = ommaviy_url.ishga_tushishda_tekshir()
    joylashuv_tekshir(_ommaviy)
    db.init_pool()
    # Embedding modelini FON IPIDA isitamiz: yuklanish ~17 s, keyingi
    # so'rovlar 19-54 ms. Isitmasak birinchi chat savoli 17 soniya
    # kutardi. Fon ipida bo'lgani uchun server darhol javob beradi.
    # `.env` da EMBED_PRELOAD=0 bilan o'chiriladi (~470 MB tejaladi).
    ai_chat.preload_embedder()
    yield
    db.close_pool()


# ---------------------------------------------------------------------------
# KIMLIK DARVOZASI (auth-2)
#
# Endpointlar BITTA joyda yopiladi — har bir funksiyaga `Depends()`
# qo'shib chiqilmaydi. Sabab:
#   - bu yerda 60 dan ortiq endpoint bor va ularning imzolari xilma-xil
#     (`Query(...)`, `File(...)`, `Header(...)`); har biriga qo'lda parametr
#     qo'shish paytida BIR NECHTASI e'tibordan chetda qolishi aniq —
#     ERP tomonida aynan shunday bo'lgan edi;
#   - darvoza YOPIQ HOLATDA boshlanadi: yangi endpoint qo'shilsa u
#     avtomatik himoyalanadi. Ro'yxatga tushmagan narsa yopiq.
#
# OCHIQ qolganlar sanoqli va sababi yozilgan.
PUBLIC_PATHS = {
    # Interfeys login OLDIDAN holatni ko'rsatadi (baza tirikmi).
    "/health",
    # TAYYORLIK — reverse-proxy va systemd shuni so'raydi, ular esa
    # token ushlab turolmaydi. Javob ATAYLAB TAFSILOTSIZ: faqat
    # `ok|ogohlantirish|xato` so'zlari. Sabablar server jurnaliga
    # yoziladi — ular u yerda kerak, tashqarida emas.
    "/ready",
    # Kirishning o'zi.
    "/auth/login",
    # Swagger — ishlab chiqishda kerak; javob bermaydi, faqat sxema.
    "/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect",
    # BO'SH shablonlar (import uchun namuna fayl). Ularni brauzerdagi
    # `<a href>` yuklab oladi va u sarlavha yubora olmaydi. Ichida
    # kompaniya ma'lumoti YO'Q — faqat ustun sarlavhalari.
    "/catalog/import/template", "/company/documents/template",
}

# Fayl yuklab olish ATAYLAB ochiq: uni brauzerdagi `<a href>` chaqiradi va
# u sarlavha (`Authorization`) yubora olmaydi. Fayllar davlat portalida
# ham ochiq — bu kompaniya siri emas, tender e'lonining ilovasi.
PUBLIC_PREFIXES = ("/documents/",)

# ERP ning SERVICE kaliti FAQAT shu endpointlarni ochadi. Kalit "hamma
# eshikning kaliti" bo'lmasligi kerak: ERP tender-ai dan uchta narsani
# oladi (cheklist qoidasi, hujjat shabloni/parseri, xabar yuborish) va
# tenderning o'zini o'qiydi. Katalog, qidiruvlar, sozlamalar — unga
# kerak emas va ochilmaydi ham.
#
# Bu yerda YO'LNING SHABLONI yoziladi (`/tenders/{tender_id}`), aniq
# manzil emas: bog'liqlik marshrutlashdan KEYIN ishlaydi, ya'ni qaysi
# marshrut tanlangani ma'lum.
SERVICE_PATHS = {
    ("GET", "/tenders/{tender_id}"),
    ("GET", "/tenders/{tender_id}/pricing"),
    # Ombor moslashuvi: ERP tenderning qaysi pozitsiyasiga qaysi mahsulot
    # mos kelishini shu yerdan oladi va REZERV TAKLIF qiladi (odam
    # tasdiqlaydi). Qoidalar bu yerda — cheklist bilan bir xil sabab.
    ("GET", "/tenders/{tender_id}/stock-check"),
    ("POST", "/tenders/{tender_id}/compliance"),
    ("GET", "/company/document-types"),
    ("POST", "/company/documents/parse"),
    ("POST", "/notify/send"),
}


# --- COOKIE va CSRF (auth-4) -------------------------------------------------
# Sessiya tokeni `localStorage` da EMAS, `HttpOnly` cookie'da: XSS bo'lsa
# ham sahifadagi JavaScript uni o'qiy olmaydi.
#
# Buning narxi CSRF (cookie'ni brauzer har so'rovga o'zi qo'shadi). Ikki
# qatlam: `SameSite=Lax` va `X-CSRF-Token` sarlavhasi — qiymati SESSIYADAGI
# bilan solishtiriladi.
#
# ERP ning SERVICE kaliti bunga ARALASHMAYDI: u cookie emas, alohida
# sarlavha va uni brauzer avtomatik qo'shmaydi — ya'ni CSRF xavfi yo'q.
SESSION_COOKIE = "tai_session"
CSRF_COOKIE = "tai_csrf"
CSRF_HEADER = "x-csrf-token"

COOKIE_SECURE = os.environ.get("AUTH_COOKIE_SECURE", "1") not in ("0", "false", "")

#: CSRF faqat o'zgartiruvchi metodlar uchun.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

#: CHIQISH — istisno. Begona sayt bizni "chiqarib yuborishi" zarar
#: keltirmaydi (eng yomoni qaytadan kirasiz), ammo CSRF tokeni eskirgan
#: foydalanuvchining CHIQA OLMAY qolishi — keltiradi: u sessiyani
#: tugatolmay, tokeni muddati tugagunicha tirik qolardi.
CSRF_EXEMPT = {"/auth/logout"}


def _set_auth_cookies(response: Response, token: str, csrf: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=auth.SESSION_DAYS * 86400, path="/")
    response.set_cookie(
        CSRF_COOKIE, csrf, httponly=False, secure=COOKIE_SECURE,
        samesite="lax", max_age=auth.SESSION_DAYS * 86400, path="/")


def _clear_auth_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", samesite="lax",
                               secure=COOKIE_SECURE)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def gate(request: Request,
         authorization: Optional[str] = Header(None),
         x_service_key: Optional[str] = Header(None),
         tai_session: Optional[str] = Cookie(None)) -> None:
    """Har bir so'rovdan oldin ishlaydi (`app = FastAPI(dependencies=[...])`).

    IKKI yo'l bilan kirish mumkin:
      1. KOMPANIYA sessiyasi — brauzerdan (`Authorization: Bearer ...`);
      2. SERVICE kaliti — ERP dan (`X-Service-Key`), odam nomidan emas.

    Kimligi `request.state` ga yoziladi: endpointga kerak bo'lsa oladi."""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return
    if request.method == "OPTIONS":        # CORS preflight — CORS o'zi javob beradi
        return

    if auth.verify_service(x_service_key):
        route = request.scope.get("route")
        template = getattr(route, "path", path)
        if (request.method, template) not in SERVICE_PATHS:
            # Kalit to'g'ri, lekin bu eshik unga ochilmagan. 403 (401 emas):
            # kimligi ma'lum, huquqi yetmaydi.
            raise xatolar.Xato("AUTH_SERVICE_KEY_FORBIDDEN")
        request.state.account = None
        request.state.service = True
        return

    # OSHKORA sarlavha USTUN, cookie — zaxira. `Authorization: Bearer`
    # brauzer uchun emas (skript, sinov); u ATAYLAB qo'yiladi, cookie esa
    # avtomatik qo'shiladi — ikkalasi uchrashganda oshkora niyat yutadi.
    bearer = _bearer(authorization)
    token, from_cookie = (bearer, False) if bearer else (tai_session, True)
    if not token:
        raise xatolar.Xato("AUTH_NOT_AUTHENTICATED")
    try:
        account = auth.verify(token)
    except auth.AuthError as e:
        raise xatolar.kodli(e, "AUTH_NOT_AUTHENTICATED")

    # CSRF FAQAT cookie uchun: Bearer da token ataylab qo'yiladi, ya'ni
    # "begona sayt bizning nomimizdan" holati yuzaga kelmaydi.
    if (from_cookie and request.method in UNSAFE_METHODS
            and path not in CSRF_EXEMPT):
        sent = request.headers.get(CSRF_HEADER)
        if not sent or not secrets.compare_digest(sent, account.get("csrf") or ""):
            # 403 (401 emas): kim ekani ma'lum, so'rovning manbai shubhali.
            raise xatolar.Xato("AUTH_CSRF_MISMATCH")

    request.state.account = account
    request.state.service = False


# --- SWAGGER ISHLAB CHIQARISHDA YOPIQ ------------------------------------
# `/docs`, `/openapi.json`, `/redoc` `PUBLIC_PATHS` da — ya'ni ular
# TOKENSIZ ochiladi va BUTUN API yuzasini (har endpoint, har maydon)
# ko'rsatadi. Ishlab chiqishda bu qulay, ishlab chiqarishda esa bu
# hujumchiga tayyor xarita.
#
# Standart YOPIQ. Ochish uchun ANIQ `API_DOCS=1` kerak — "sozlamani
# unutib qoldirish" xavfsiz tomonga tushsin.
API_DOCS = os.environ.get("API_DOCS", "0").strip().lower() in ("1", "true", "yes")

#: Qaysi muhitda ishlayapmiz: dev | staging | production.
#:
#: NEGA KERAK: ba'zi tekshiruvlar FAQAT ishlab chiqarishda qat'iy
#: bo'lishi kerak. Masalan bildirishnoma havolasi `localhost` bo'lsa
#: — bu `dev` da normal, `production` da esa BUZUQ havola yuborish
#: demak. Muhitni bilmasak ikkalasini ajratib bo'lmaydi.
#:
#: Standart `dev`: sozlanmagan muhit ISHLAB CHIQARISH deb
#: hisoblanmaydi, ya'ni qat'iy tekshiruvlar tasodifan ishlab
#: turgan mahalliy nusxani to'xtatmaydi.
APP_ENV = os.environ.get("APP_ENV", "dev").strip().lower()

app = FastAPI(
    title="xt-xarid Tender Aggregator API",
    version="0.1.0",
    description="O'zbekiston davlat xaridlari agregatori — backend API (3-bosqich).",
    lifespan=lifespan,
    dependencies=[Depends(gate)],
    docs_url="/docs" if API_DOCS else None,
    redoc_url="/redoc" if API_DOCS else None,
    openapi_url="/openapi.json" if API_DOCS else None,
)


# ---------------------------------------------------------------------------
# XAVFSIZLIK SARLAVHALARI
#
# O'LCHANGAN HOLAT (2026-08-31): javoblarda BIRORTA ham xavfsizlik
# sarlavhasi yo'q edi — `X-Content-Type-Options`, `X-Frame-Options`,
# `Referrer-Policy`, CSP, HSTS — hech biri.
#
# HAR SARLAVHA NIMANI TO'SADI:
#   nosniff        — brauzer JSON ni HTML deb "taxmin qilib" ijro
#                    etmasin. `/documents/.../download` yuqori oqim
#                    `Content-Type` ini o'tkazadi (`attachment` bilan),
#                    bu ikkinchi qatlam.
#   frame-ancestors— clickjacking. `X-Frame-Options` eski brauzerlar
#                    uchun, CSP esa zamonaviylari uchun — IKKALASI ham
#                    qo'yiladi, chunki ular har xil brauzerda ishlaydi.
#   Referrer-Policy— manzildagi id lar tashqi saytga ketmasin.
#   CSP            — bu API JSON qaytaradi, shuning uchun `default-src
#                    'none'` XAVFSIZ. Swagger yoqilganda unga JS kerak,
#                    shuning uchun o'sha yo'llarga CSP QO'YILMAYDI —
#                    aks holda sahifa buzilib, "CSP bor" degan yolg'on
#                    taassurot qolardi.
#
# HSTS ATAYLAB STANDART O'CHIQ. Uni yoqish domenni HTTPS ga QULFLAYDI
# (brauzer `max-age` davomida HTTP ga umuman bormaydi). TLS hali
# sozlanmagan muhitda bu saytni YO'Q QILADI. Shuning uchun u ANIQ
# `HSTS_MAX_AGE` bilan yoqiladi va odatda TLS terminatorida (nginx /
# Caddy) qo'yiladi — `docs/xavfsizlik.md` §3.
HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "0") or 0)

#: Swagger ishlaganda unga CSP qo'yilmaydi (CDN dan JS/CSS oladi).
_CSP_ISTISNO = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")

_XAVFSIZLIK_SARLAVHALARI = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Bu API brauzer qurilmalariga MUHTOJ EMAS — hammasi o'chiriladi.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), "
                          "payment=(), usb=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

#: JSON API uchun ENG QAT'IY siyosat: hech narsa yuklanmaydi, hech kim
#: freym ichiga olmaydi, forma yuborilmaydi.
_CSP = ("default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'; sandbox")


@app.middleware("http")
async def sorov_jurnali(request: Request, call_next):
    """Har so'rovga IDENTIFIKATOR beradi va natijasini yozadi.

    Identifikator javobga ham qo'yiladi (`X-Request-Id`) — foydalanuvchi
    xato haqida aytganda o'sha id bo'yicha jurnalni topish mumkin.
    Mijoz o'zi id yuborsa, u ISHLATILADI (proksi zanjiri uzilmasin),
    lekin UZUNLIGI cheklanadi — jurnalga cheksiz matn tushmasin.
    """
    kelgan = (request.headers.get("x-request-id") or "").strip()[:64]
    sid = kelgan or jurnal.yangi_sorov_id()
    if kelgan:
        jurnal.sorov_id.set(kelgan)
    t0 = time.time()
    javob = await call_next(request)
    javob.headers.setdefault("X-Request-Id", sid)
    # `/health` va `/ready` HAR DAQIQA so'raladi — ular jurnalni
    # to'ldirib, haqiqiy hodisalarni ko'mib tashlardi. Faqat muammo
    # bo'lganda yoziladi.
    shovqin = request.url.path in ("/health", "/ready")
    if not shovqin or javob.status_code >= 400:
        logging.getLogger("api.sorov").info(
            "%s %s -> %s", request.method, request.url.path,
            javob.status_code,
            extra={"metod": request.method, "yol": request.url.path,
                   "kod": javob.status_code,
                   "ms": int((time.time() - t0) * 1000)})
    return javob


@app.middleware("http")
async def xavfsizlik_sarlavhalari(request: Request, call_next):
    javob = await call_next(request)
    for k, v in _XAVFSIZLIK_SARLAVHALARI.items():
        javob.headers.setdefault(k, v)
    if request.url.path not in _CSP_ISTISNO:
        javob.headers.setdefault("Content-Security-Policy", _CSP)
    # HSTS FAQAT HTTPS da ma'noli va faqat ANIQ yoqilganda.
    if HSTS_MAX_AGE > 0:
        javob.headers.setdefault(
            "Strict-Transport-Security",
            f"max-age={HSTS_MAX_AGE}; includeSubDomains")
    return javob

# CORS — .env dagi CORS_ORIGINS bo'sh bo'lmasa yoqiladi (frontend ulanganда)
_cors = os.environ.get("CORS_ORIGINS", "").strip()
if _cors:
    from fastapi.middleware.cors import CORSMiddleware

    origins = ["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Faqat GET yetmaydi: profil/katalog/qidiruvlar POST-PUT-DELETE ishlatadi
        # (masalan POST /match) — preflight rad etilsa frontend "Failed to fetch"
        # xatosini ko'rsatadi.
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        # Ro'yxatning umumiy soni shu header'da qaytadi — brauzer uni
        # ochib bermasa frontend o'qiy olmaydi.
        expose_headers=["X-Total-Count"],
    )


# DB mavjud emasligini 503 ga aylantiramiz
@app.exception_handler(db.DBUnavailable)
async def _db_unavailable_handler(request, exc: db.DBUnavailable):
    """Baza yetib bo'lmadi.

    TAFSILOT MIJOZGA CHIQMAYDI. psycopg2 ning ulanish xatosi HOST,
    PORT va FOYDALANUVCHI nomini o'z ichiga oladi
    (`connection to server at "localhost" (::1), port 5432 failed:
    ... user "postgres"`). Ilgari u to'g'ridan-to'g'ri javobga
    tushardi va bu infratuzilma xaritasini oshkor qilardi.

    Tafsilot SERVER jurnaliga yoziladi — u yerda kerak, mijozda emas.
    """
    logging.getLogger("api").error("DB yetib bo'lmadi: %s", exc)
    return JSONResponse(
        status_code=503,
        content=xatolar.tana("DATABASE_UNAVAILABLE",
                             tashxis=jurnal.sorov_id.get()),
    )


# ---------------------------------------------------------------------------
# XATO KODLARI — JAVOB TILGA BOG'LIQ EMAS (20-vazifa)
#
# Uch ishlovchi, BITTA shakl (`xatolar.tana()`):
#   `Xato`                  — biznes xatosi, kodi bor
#   `HTTPException`         — FastAPI ning o'zi ko'targani (404 marshrut,
#                             405 metod); kod HOLATDAN olinadi
#   `RequestValidationError`— maydon tekshiruvi (422)
#
# TEXNIK TAFSILOT JAVOBGA TUSHMAYDI, jurnalga tushadi. Foydalanuvchi
# `diagnostic_id` ni aytsa, jurnaldan AYNAN o'sha so'rov topiladi —
# ya'ni tafsilotni olib tashlash yordamni qiyinlashtirmaydi.
# ---------------------------------------------------------------------------
@app.exception_handler(xatolar.Xato)
async def _xato_handler(request, exc: xatolar.Xato):
    xatolar.jurnalga(exc.kod, exc.status, exc.ichki, exc.params)
    javob = JSONResponse(
        status_code=exc.status,
        content=xatolar.tana(exc.kod, exc.params, jurnal.sorov_id.get()),
    )
    # 429 da `Retry-After` — standart yo'l bilan "qachon qayta urinish
    # mumkin" degan savolga javob. Matndan emas, SONDAN olinadi.
    kutish = exc.params.get("kutish_soniya")
    if exc.status == 429 and kutish:
        javob.headers["Retry-After"] = str(int(kutish))
    return javob


#: HTTP holati -> kod. FastAPI O'ZI ko'targan istisnolar uchun
#: (marshrut topilmadi, metod ruxsat etilmagan). Bu ro'yxat
#: TO'LIQ EMASLIGI ataylab: ilova kodidagi har xato `Xato` bilan
#: ko'tariladi va bu yerga TUSHMAYDI.
_HOLAT_KODI = {
    401: "AUTH_NOT_AUTHENTICATED",
    403: "AUTH_LOGIN_REQUIRED",
    404: "RECORD_NOT_FOUND",
    405: "FIELD_INVALID",
    413: "FILE_TOO_LARGE",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    503: "DATABASE_UNAVAILABLE",
}


@app.exception_handler(StarletteHTTPException)
async def _http_handler(request, exc: StarletteHTTPException):
    kod = _HOLAT_KODI.get(exc.status_code, "INTERNAL_ERROR")
    xatolar.jurnalga(kod, exc.status_code, str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content=xatolar.tana(kod, tashxis=jurnal.sorov_id.get()),
        headers=getattr(exc, "headers", None),
    )


#: Pydantic xato turi -> bizning kod. To'liq emasligi ATAYLAB:
#: ro'yxatda yo'q tur `FIELD_INVALID` beradi va bu YOLG'ON emas —
#: "qiymat noto'g'ri" har holatda rost.
_PYDANTIC_KODI = {
    "missing": "FIELD_REQUIRED",
    "string_too_short": "FIELD_EMPTY",
    "string_too_long": "FIELD_TOO_LONG",
    "literal_error": "INVALID_ENUM",
    "enum": "INVALID_ENUM",
}


@app.exception_handler(RequestValidationError)
async def _validatsiya_handler(request, exc: RequestValidationError):
    """Maydon tekshiruvi (422).

    MAYDON RO'YXATI javobda QOLADI: "nimadir noto'g'ri" deyish
    foydalanuvchiga qaysi maydonni tuzatishni AYTMAYDI. Lekin
    pydantic ning INGLIZCHA tushuntirishi olib tashlanadi — u
    tarjima qilinmaydi va interfeys uch tilli.

    Maydon nomlari — SXEMA nomlari (`min_score`, `smtp_port`), ya'ni
    tildan mustaqil. Ularni odam o'qiydigan nomga interfeys
    aylantiradi.
    """
    nomlar, maydonlar = [], []
    for x in exc.errors():
        yol = ".".join(str(p) for p in x.get("loc", ()) if p != "body")
        # Pydantic `ValueError("FIELD_NEGATIVE")` ni "Value error,
        # FIELD_NEGATIVE" deb o'raydi — kodni shundan ajratamiz.
        xom = str(x.get("msg", "")).replace("Value error, ", "").strip()
        if xom in xatolar.KODLAR:
            kod = xom
        else:
            # Pydantic'ning O'Z xatolari (maydon yo'q, tur mos emas):
            # ularning `msg` i INGLIZCHA va tarjima qilinmaydi, lekin
            # `type` i BARQAROR mashina qiymati — kodni SHUNDAN
            # olamiz. Ilgari hammasi `FIELD_INVALID` ga tushardi va
            # "maydon TO'LDIRILMAGAN" bilan "qiymat NOTO'G'RI"
            # farqi yo'qolardi.
            kod = _PYDANTIC_KODI.get(str(x.get("type", "")), "FIELD_INVALID")
        if yol:
            nomlar.append(yol)
        maydonlar.append({"field": yol, "code": kod})
    xatolar.jurnalga("VALIDATION_ERROR", 422, str(exc.errors())[:400])
    return JSONResponse(
        status_code=422,
        content=xatolar.tana("VALIDATION_ERROR",
                             {"maydonlar": ", ".join(nomlar)},
                             jurnal.sorov_id.get(), maydonlar),
    )


# ---------------------------------------------------------------------------
# Javob shakllantiruvchi yordamchilar
# ---------------------------------------------------------------------------
def _shape_tender(r: dict) -> dict:
    """Xom qatorni toza, ichma-ich (nested) JSON obyektiga aylantiradi."""
    return {
        "id": r["id"],
        # Manbadagi asl ID — rasmiy sahifa havolasini qurish uchun
        # (bizning id global: source_id + platforma ofseti)
        "source_id": r.get("source_id"),
        "type": r["type"],
        "name": r["name"],
        "status": r["status"],
        "status_name": r.get("status_name_uz") or r.get("status_name_ru"),
        "status_name_ru": r.get("status_name_ru"),
        "status_name_uz": r.get("status_name_uz"),
        "is_terminal": r.get("is_terminal"),
        "totalcost": _num(r.get("totalcost")),
        "currency": r.get("currency"),
        "region": {
            "id": r.get("area_leaf_id"),
            "name": r.get("region_name_uz") or r.get("region_name_ru"),
            "name_ru": r.get("region_name_ru"),
            "name_uz": r.get("region_name_uz"),
            "path": r.get("area_path"),
        },
        # BUYURTMACHI tashkiloti (manba platformadan) — bizning ijarachimiz
        # emas. Ustun `buyer_org_id` deb nomlangan, javob shakli o'zgarmadi.
        "company": {"id": r.get("buyer_org_id"), "name": r.get("company_name")},
        "lot_count": r.get("lot_count"),
        "good_count": r.get("good_count"),
        "goods_preview": r.get("goods_preview") or [],
        "doc_count": r.get("doc_count") or 0,
        # Lotlar xulosasi — ro'yxatда qatorni ochib ko'rish uchun
        "lots_summary": [
            {
                "lot_id": l.get("lot_id"),
                "title": l.get("title"),
                "total_sum_lot": _num(l.get("total_sum_lot")),
                "item_count": l.get("item_count"),
                "delivery_period": l.get("delivery_period"),
                "guarantee": l.get("guarantee"),
            }
            for l in (r.get("lots_json") or [])
        ],
        "part_count": r.get("part_count"),
        "publicated_at": _iso(r.get("publicated_at")),
        "close_at": _iso(r.get("close_at")),
        "starting_date": _iso(r.get("starting_date")),
        "ends_at": _iso(r.get("ends_at")),
        "remain_time": r.get("remain_time"),
        "source_platform": r.get("source_platform"),
        "fetched_at": _iso(r.get("fetched_at")),
        "first_seen_at": _iso(r.get("first_seen_at")),
    }


# Fayl yuklab olish manzili.
#   xt-xarid — to'g'ridan-to'g'ri GET (brauzer o'zi yuklab oladi, trafik bizdan o'tmaydi)
#   uzex     — manba POST talab qiladi, brauzer havolasi esa GET yuboradi,
#              shuning uchun BIZNING proksi orqali o'tadi (pastdagi endpoint).
_FILE_URL = {"xt-xarid": "https://api.xt-xarid.uz/file/{file_id}"}

# To'g'ridan-to'g'ri GET bilan yuklab olinadigan manbalar: fayl yo'li shu bazaga
# ulanadi (proksi shart emas — brauzer o'zi oladi, trafik bizdan o'tmaydi).
# Hozircha bo'sh (kelajakdagi shunday manbalar uchun mexanizm qoldirildi).
_FILE_DIRECT: dict = {}

# POST talab qiluvchi manbalar — proksi orqali o'tadi (brauzer havolasi GET
# yuboradi, manba esa POST kutadi).
_POST_DOWNLOAD = {
    "uzex": "https://apietender.uzex.uz/api/common/DownloadFile",
}
# Ba'zi manbalar oddiy skript User-Agent'ini rad etadi — brauzernikini beramiz.
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/120.0.0.0 Safari/537.36")

# Moslashtirish uchun nomzodlar chegarasi. Ballash Pythonда bo'lgani uchun
# bu SQL LIMIT — undan tashqaridagilar UMUMAN ballanmaydi. Hozirgi baza ~900
# yozuv, shuning uchun chegara undan yuqori. Cap ishga tushsa javobда
# `truncated: true` qaytadi.
MATCH_CAP = 3000

# Katalog ro'yxatida moslik sonini mahsulot x tender kesimida hisoblash
# kvadratik ish. Sinovdagi 27 mahsulotda bilinmagan, 1 797 pozitsiyali real
# katalogda esa GET /catalog bir necha daqiqaga qotib qoladi. Kichik katalogda
# avvalgi qulaylik saqlanadi; katta katalogda ro'yxat darhol qaytadi, moslik
# esa maxsus /catalog/match oqimida hisoblanadi.
CATALOG_INLINE_MATCH_LIMIT = 100

# Hujjat qaysi bo'limdan kelgani — o'qiladigan nom
_FIELD_LABELS = {
    "anno_file": "Tender asos-hujjatlari",
    "proform_file": "Shartnoma namunasi",
    "start_price_file": "Texnik topshiriq / boshlang‘ich narx",
    "load_pdf": "PDF ilova",
}


def _doc_label(field_key: Optional[str]) -> str:
    if not field_key:
        return "Boshqa hujjatlar"
    if field_key in _FIELD_LABELS:
        return _FIELD_LABELS[field_key]
    m = re.match(r"proc_custom(\d+)", field_key)
    if m:
        return f"Qo‘shimcha ma'lumot №{m.group(1)}"
    return field_key


def _shape_document(r: dict, tender_id: Optional[int] = None) -> dict:
    platform = r.get("source_platform") or "xt-xarid"
    ref = r.get("file_ref")
    if platform == "xt-xarid" and r.get("file_id"):
        url = _FILE_URL["xt-xarid"].format(file_id=r["file_id"])
    elif platform in _FILE_DIRECT and r.get("file_path"):
        # To'g'ridan-to'g'ri GET — fayl yo'li ('/storage/...') bazaga ulanadi
        url = _FILE_DIRECT[platform] + r["file_path"]
    else:
        # Proksi orqali (uzex va kelajakdagi POST-talab qiluvchi manbalar)
        url = f"/documents/{tender_id}/download?ref={quote(str(ref), safe='')}"
    return {
        "file_ref": ref,
        "file_id": str(r["file_id"]) if r.get("file_id") else None,
        "name": r.get("name"),
        "size_bytes": r.get("size_bytes"),
        "content_type": r.get("content_type"),
        "file_type": r.get("file_type"),
        "section": _doc_label(r.get("field_key")),
        "download_url": url,
    }


def _num(v):
    """Decimal -> float (JSON uchun). None o'zgarmaydi."""
    return float(v) if v is not None else None


def _iso(v):
    """datetime -> ISO string. None o'zgarmaydi."""
    return v.isoformat() if v is not None else None


# ---------------------------------------------------------------------------
# Endpointlar
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# KIMLIK (auth) — KOMPANIYA hisobi.
#
# Tender-AI ga KOMPANIYA kiradi. Hodim hisoblari BU YERDA EMAS: odam —
# ERP ning tushunchasi va u yerda o'z kimlik moduli bor
# (`erp.app_user`, ERP `api/auth.py`). Ikkala tomon mustaqil tekshiradi,
# bir-biriga token uchun murojaat qilmaydi.
#
# Auth-1 da teskarisi qilingan edi (hodimlar shu yerda, ERP HTTP orqali
# tekshirardi); tuzatish sababi `api/auth.py` boshida yozilgan.
#
# DIQQAT: tender-ai ning boshqa endpointlari hozircha OCHIQ qoladi
# (auth-2). Bu ongli chegara: interfeysga login qo'shish alohida ish va u
# ERP'ni himoyalashni kechiktirmasligi kerak.
# ---------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


class AccountIn(BaseModel):
    """Kompaniya hisobi. `password` faqat almashtirishda."""
    company_name: Optional[str] = None
    password: Optional[str] = None
    #: JORIY parol — almashtirishda MAJBURIY (auth-6).
    current_password: Optional[str] = None
    email: Optional[str] = None
    active: bool = True



# --- PROKSI ORQASIDA MANZIL (auth-5 davomi) ---------------------------------
# `X-Forwarded-For` ga ODATDA ISHONILMAYDI: uni mijozning o'zi yozib
# yuborishi mumkin, ya'ni parol tanlashdan himoyaning IP cheklovini
# bir qator matn bilan chetlab o'tish mumkin bo'lardi.
#
# Lekin ERP proksi (nginx/IIS) orqasiga qo'yilsa, `request.client` HAR
# DOIM proksining o'zini ko'rsatadi va hamma so'rov bitta manzildan
# kelayotgandek bo'ladi — IP kesimi ishlamay qoladi.
#
# Yechim — SOZLAMA, kod emas: `TRUST_PROXY=1`. Default O'CHIQ, ya'ni
# to'g'ridan-to'g'ri ishlayotgan o'rnatma xavfsiz holatda qoladi.
#
# NEGA OXIRGI manzil: sarlavha `mijoz, proksi1, proksi2` ko'rinishida
# bo'ladi va BOSHIDAGI qiymatlarni mijoz o'zi yozib yuborishi mumkin.
# Oxirgisini esa bizga eng yaqin (ishonchli) proksi qo'yadi — u
# haqiqatan ko'rgan manzil. Shuning uchun ro'yxatning oxiridan olinadi.
#
# DIQQAT: ikki yoki undan ko'p proksi bo'lsa bu joy qayta ko'rib
# chiqilishi kerak (o'shanda oxirgisi ichki proksi manzili bo'ladi).
TRUST_PROXY = (os.environ.get("TRUST_PROXY", "0").strip().lower()
               in ("1", "true", "yes", "on"))


def client_ip(request: Request) -> Optional[str]:
    """So'rov kelgan manzil. `TRUST_PROXY` o'chiq bo'lsa — faqat
    to'g'ridan-to'g'ri ulanish manzili."""
    if TRUST_PROXY:
        xff = request.headers.get("X-Forwarded-For") or ""
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else None


def _auth(fn, *a, **kw):
    """AuthError -> HTTP kodi (400/401/403/404/409/429/503).

    429 da `Retry-After` sarlavhasi ham qo'shiladi — bu standart yo'l
    bilan "qachon qayta urinish mumkin" degan savolga javob beradi va
    brauzerdan tashqari mijozlar ham tushunadi."""
    try:
        return fn(*a, **kw)
    except auth.AuthError as e:
        # `Retry-After` sarlavhasini ISHLOVCHI qo'yadi: u `params`
        # dagi `kutish_soniya` SONIDAN olinadi, matndan emas.
        # Ilgari u shu yerda edi va faqat SHU chegaradan o'tgan
        # xatolarga tegishli bo'lardi.
        raise xatolar.kodli(e, "AUTH_NOT_AUTHENTICATED")


def _token(authorization: Optional[str]) -> str:
    """`Authorization: Bearer <token>` dan tokenni ajratadi."""
    if not authorization:
        raise xatolar.Xato("AUTH_TOKEN_MISSING")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise xatolar.Xato("AUTH_TOKEN_MALFORMED")
    return parts[1].strip()


def current_account(request: Request) -> Dict[str, Any]:
    """Kirgan hisob. Kimlikni DARVOZA (`gate`) allaqachon tekshirgan —
    bu yerda faqat natijasi olinadi, ikkinchi SQL so'rov qilinmaydi."""
    return getattr(request.state, "account", None) or {}


#: ERP `X-Service-Key` bilan kelganda so'rov QAYSI kompaniya nomidan
#: bajarilishi. Bo'sh bo'lsa — yagona FAOL hisob (bittadan ko'p bo'lsa xato).
ERP_COMPANY_ID = os.environ.get("ERP_COMPANY_ID", "").strip()

def kimlik_of(request: Request, cid: Optional[int] = None):
    """So'rov ortidagi AKTOR kimligi (`api/aktor.py:Kimlik`).

    `company_id_of()` "qaysi IJARACHI" degan savolga javob beradi —
    u hal qilingan va ishonchli. Bu funksiya "qaysi ODAM" degan
    ALOHIDA savolga javob beradi va javob bilan birga uning
    QANCHALIK ISHONCHLI ekanini ham qaytaradi.

    Ikkisini bitta funksiyaga qo'shmadik: ijarachi aniqligi bilan
    aktor aniqligi bir xil emas va ularni aralashtirish aynan shu
    modul tuzatayotgan xatoning manbai edi.
    """
    from api import aktor as _aktor
    try:
        return _aktor.aniqla(request, cid if cid is not None
                             else company_id_of(request))
    except _aktor.RuxsatXato as e:
        raise xatolar.kodli(e, "ACTOR_FORBIDDEN")


def ruxsat(k, amal: str) -> None:
    """Huquqni tekshiradi; yetmasa HTTP xatosi."""
    from api import aktor as _aktor
    try:
        _aktor.ruxsat_tekshir(k, amal)
    except _aktor.RuxsatXato as e:
        raise xatolar.kodli(e, "ACTOR_FORBIDDEN")


def audit_yoz(k, request: Request, *, amal: str, entity: str,
              entity_id: int, oldin=None, keyin=None, izoh=None) -> None:
    """Audit qatorini yozadi.

    XATO YUTILMAYDI VA JIM QOLMAYDI: agar o'zgarish yozilib, izi
    yozilmasa — bu audit tizimining eng yomon holati. 500 qaytarish
    o'zgarishni qaytarmaydi (u boshqa tranzaksiyada), lekin holat
    KO'RINADI. Jimgina yutish "audit bor" degan yolg'on beradi.
    """
    from api import aktor as _aktor
    try:
        _aktor.yoz(k, amal=amal, entity=entity, entity_id=entity_id,
                   oldin=oldin, keyin=keyin, izoh=izoh,
                   ip=client_ip(request),
                   user_agent=request.headers.get("user-agent"))
    except Exception as e:                                    # noqa: BLE001
        raise xatolar.Xato("AUDIT_WRITE_FAILED", ichki=str(e))


def company_id_of(request: Request) -> int:
    """So'rov QAYSI kompaniya nomidan bajarilyapti (J1.6).

    Ikki yo'l bor va ikkalasi ham `gate()` da tekshirilgan:
      * KOMPANIYA sessiyasi — hisob `request.state.account` da;
      * SERVICE kaliti (ERP) — odam nomidan emas, shuning uchun hisob YO'Q.

    ERP holatida kompaniya `.env` dagi `ERP_COMPANY_ID` dan olinadi. U
    ko'rsatilmagan bo'lsa yagona FAOL hisob ishlatiladi; faol hisob bir
    nechta bo'lsa — ANIQ xato, chunki taxmin qilish bu yerda ma'lumotni
    boshqa ijarachiga berib yuborish demakdir.
    """
    acc = getattr(request.state, "account", None)
    if acc and acc.get("id"):
        return int(acc["id"])

    if ERP_COMPANY_ID.isdigit():
        return int(ERP_COMPANY_ID)

    # Mantiq `api/auth.py` da — bildirishnoma tsikli ham shuni ishlatadi.
    try:
        return auth.sole_company_id()
    except auth.AuthError as e:
        raise xatolar.kodli(e, "ACTOR_FORBIDDEN")


@app.post("/auth/login")
def auth_login(body: LoginIn, request: Request, response: Response,
               user_agent: Optional[str] = Header(None)):
    """KOMPANIYA hisobi bilan kirish.

    Sessiya tokeni JAVOB TANASIDA QAYTMAYDI — u `HttpOnly` cookie'ga
    qo'yiladi (auth-4). Javobda faqat hisob va CSRF tokeni.

    Urinishlar JURNALGA yoziladi va ko'p xatodan keyin 429 qaytadi
    (auth-5). Manzil `client_ip()` orqali olinadi: `X-Forwarded-For` ga
    faqat `TRUST_PROXY=1` bo'lganda ishoniladi (sababi o'sha funksiya
    ustidagi izohda)."""
    res = _auth(auth.login, body.username, body.password,
                user_agent=user_agent, ip=client_ip(request))
    _set_auth_cookies(response, res["token"], res["csrf"])
    response.headers["Cache-Control"] = "no-store"
    return {"account": res["account"], "csrf": res["csrf"],
            "expires_at": res["expires_at"]}


@app.post("/auth/logout")
def auth_logout(response: Response,
                authorization: Optional[str] = Header(None),
                tai_session: Optional[str] = Cookie(None)):
    """Chiqish. Cookie'lar HAR HOLDA tozalanadi — yaroqsiz token
    brauzerda osilib qolmasin."""
    ok = False
    try:
        ok = _auth(auth.logout, tai_session or _token(authorization))
    except xatolar.Xato:
        pass
    _clear_auth_cookies(response)
    return {"ok": ok}


@app.get("/auth/me")
def auth_me(request: Request, response: Response):
    """Kim kirgan. Javobda CSRF tokeni ham bor: sahifa yangilanganda uni
    login'siz tiklaydi.

    ERP bu endpointga TAYANMAYDI: hodimlar ERP ning o'zida
    (`erp.app_user`) va u kimlikni mustaqil tekshiradi.

    Kimlikni DARVOZA allaqachon tekshirgan (`gate`) — bu yerda faqat
    natijasi olinadi."""
    response.headers["Cache-Control"] = "no-store"
    return getattr(request.state, "account", None) or {}


@app.get("/auth/attempts")
def auth_attempts(hours: int = Query(24, ge=1, le=720),
                  limit: int = Query(100, ge=1, le=1000),
                  only_failed: bool = True):
    """Kirish urinishlari — "kim, qayerdan va qachon urindi".

    Kirgan hisob uchun ochiq: tender-ai da ROL YO'Q va hisob bitta —
    ya'ni bu ro'yxatni ko'rayotgan odam allaqachon o'sha kompaniya.
    Darvoza (`gate`) kimlikni tekshirgan."""
    return _auth(auth.attempts, hours, limit, only_failed)


@app.get("/auth/account")
def auth_account(request: Request):
    """Hisob ma'lumotlari. Rol yo'q — kompaniya hisobi bitta darajali."""
    return getattr(request.state, "account", None) or {}


@app.put("/auth/account")
def auth_update_account(body: AccountIn, request: Request):
    a = getattr(request.state, "account", None) or {}
    return _auth(auth.update_account, a["id"], body.model_dump())


@app.put("/auth/password")
def auth_set_password(body: AccountIn, request: Request,
                      authorization: Optional[str] = Header(None),
                      tai_session: Optional[str] = Cookie(None)):
    """Kompaniya O'Z parolini almashtiradi. Boshqa hisobniki emas: hisoblar
    ro'yxati serverda, `create_company.py` orqali boshqariladi.

    JORIY parol MAJBURIY (auth-6): ochiq qolgan kompyuter yoki
    o'g'irlangan sessiya bilan begona odam parolni o'zgartirib, hisobni
    butunlay egallab olmasin. Almashtirgandan keyin BOSHQA sessiyalar
    o'chadi — aks holda o'g'irlangan token ishlayveradi va butun amal
    ma'nosiz bo'lardi."""
    a = getattr(request.state, "account", None) or {}
    if not body.password:
        raise xatolar.Xato("PASSWORD_REQUIRED")
    if not body.current_password:
        raise xatolar.Xato("PASSWORD_CURRENT_REQUIRED")
    return _auth(auth.set_password, a["id"], body.password,
                 current=body.current_password,
                 # Tartib DARVOZA bilan bir xil bo'lishi SHART: u ham
                 # oshkora sarlavhani ustun qo'yadi. Aks holda ikkalasi
                 # ham kelganda "qaysi sessiya qoladi" degan savolga
                 # ikki joyda ikki xil javob chiqardi va parolni
                 # almashtirgan odam o'zi tizimdan chiqib qolardi.
                 keep_token=(_token_opt(authorization) or tai_session))


def _token_opt(authorization: Optional[str]) -> Optional[str]:
    """Sarlavhadagi token, bo'lmasa `None`. `_token()` dan farqi: bu
    yerda tokenning yo'qligi xato emas — kimlikni DARVOZA allaqachon
    tekshirgan, token esa faqat "qaysi sessiyani qoldirish" uchun."""
    try:
        return _token(authorization)
    except xatolar.Xato:
        return None


@app.get("/health")
def health():
    """TIRIKLIK (liveness) — jarayon javob beryaptimi.

    Baza ulanishini ham tekshiradi (tarixiy xulq, interfeys shunga
    tayanadi). Chuqurroq tekshiruv — `/ready`.
    """
    db.scalar("SELECT 1")
    return {"status": "ok"}


@app.get("/ready")
def ready(response: Response):
    """TAYYORLIK (readiness) — TRAFIK YUBORSA BO'LADIMI.

    `/health` dan FARQI ATAYLAB: jarayon tirik bo'lishi mumkin, lekin
    xizmatga TAYYOR bo'lmasligi mumkin — migratsiya qo'llanmagan,
    embedding modeli hali yuklanmagan. Ikkalasini bitta endpointga
    qo'shish "tirik = tayyor" degan yolg'on beradi va reverse-proxy
    tayyor bo'lmagan jarayonga trafik yuborardi.

    TAYYOR EMAS bo'lsa **503** qaytadi — proksi (Caddy) va systemd
    shu kodga qarab kutadi.

    Har tekshiruv `ok | ogohlantirish | xato` beradi. Faqat `xato`
    503 ga olib keladi: model yuklanmagani xizmatni to'xtatmaydi
    (chat sekinroq ishlaydi, qolgani ishlaydi) — bu OGOHLANTIRISH.
    """
    tekshiruv: Dict[str, Any] = {}
    xato = False

    # 1) BAZA
    try:
        db.scalar("SELECT 1")
        tekshiruv["baza"] = {"holat": "ok"}
    except Exception as e:                                    # noqa: BLE001
        xato = True
        tekshiruv["baza"] = {"holat": "xato", "sabab": str(e)[:120]}

    # 2) MIGRATSIYALAR. Manifestdagi va bazada yozilganlar mos kelmasa —
    #    kod sxemadan oldinda yoki orqada. Bu jimgina yiqilishga olib
    #    keladigan holat, shuning uchun XATO.
    try:
        kutilgan = 0
        man = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "migratsiya_manifest.tsv")
        if os.path.exists(man):
            with io.open(man, encoding="utf-8") as f:
                kutilgan = sum(1 for ln in f
                               if ln.strip() and not ln.lstrip().startswith("#"))
        bor = db.scalar("SELECT count(*) FROM schema_migration "
                        "WHERE holat IN ('ok','bootstrap')") or 0
        if not kutilgan:
            tekshiruv["migratsiya"] = {"holat": "ogohlantirish",
                                       "sabab": "manifest topilmadi"}
        elif int(bor) < kutilgan:
            xato = True
            tekshiruv["migratsiya"] = {
                "holat": "xato", "qollangan": int(bor), "kutilgan": kutilgan,
                "sabab": "migratsiya qo'llanmagan"}
        else:
            tekshiruv["migratsiya"] = {"holat": "ok", "qollangan": int(bor),
                                       "kutilgan": kutilgan}
    except Exception as e:                                    # noqa: BLE001
        xato = True
        tekshiruv["migratsiya"] = {"holat": "xato", "sabab": str(e)[:120]}

    # 3) EMBEDDING MODELI — OGOHLANTIRISH, xato emas.
    try:
        yuklandi = ai_chat.embedder_yuklandi()
        tekshiruv["embedding"] = {
            "holat": "ok" if yuklandi else "ogohlantirish",
            "yuklandi": bool(yuklandi),
            "provayder": os.environ.get("EMBED_PROVIDER", "local")}
    except Exception as e:                                    # noqa: BLE001
        tekshiruv["embedding"] = {"holat": "ogohlantirish",
                                  "sabab": str(e)[:120]}

    if xato:
        response.status_code = 503
        logging.getLogger("api").error("TAYYOR EMAS: %s", tekshiruv)
    elif any(v.get("holat") == "ogohlantirish" for v in tekshiruv.values()):
        logging.getLogger("api").warning("tayyorlik ogohlantirishi: %s",
                                         tekshiruv)
    # TAFSILOT TASHQARIGA CHIQMAYDI. `/ready` ochiq endpoint bo'lgani
    # uchun migratsiya sanog'i, xato matni va muhit nomi javobda
    # BERILMAYDI — ular server jurnalida (yuqorida).
    return {"tayyor": not xato,
            "tekshiruv": {k: v["holat"] for k, v in tekshiruv.items()}}


@app.get("/tenders")
def list_tenders(
    response: Response,
    status: Optional[str] = Query("open", description="Status kodi. Barchasi uchun bo'sh bering (?status=)."),
    region: Optional[str] = Query(None, description="Hudud kodi (istalgan daraja — leaf/viloyat/respublika)."),
    currency: Optional[str] = Query(None, description="Valyuta: UZS yoki USD."),
    source: Optional[str] = Query(None, description="Manba platforma (masalan xt-xarid)."),
    q: Optional[str] = Query(None, description="Qidiruv: tender nomi, buyurtmachi yoki tovar nomi."),
    category: Optional[str] = Query(None, description="Kategoriya kodi (parent tanlansa ichkilar ham kiradi)."),
    product: Optional[List[str]] = Query(None, description="Mahsulot nomi — FAQAT tovar ro'yxati bo'yicha. Bir nechta berilsa: birortasi."),
    service: Optional[List[str]] = Query(None, description="Xizmat nomi. Mahsulot bilan BIRGA berilsa: birortasi (OR)."),
    sort: str = Query(queries.DEFAULT_SORT, description="Saralash: close_at | publicated_at | totalcost | id. Kamayish uchun oldiga '-'."),
    limit: int = Query(51, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Ochiq (yoki filtrlangan) tenderlar ro'yxati. Umumiy soni X-Total-Count header'da."""
    status_val = status or None  # bo'sh string -> filtr yo'q
    where, params = queries.build_tender_filters(
        status=status_val, region=region, currency=currency, source=source,
        q=q, category=category, products=(product or []) + (service or []),
    )
    order_by = queries.build_order_by(sort)

    total = db.scalar(queries.tenders_count_sql(where), params) or 0

    params_page = {**params, "limit": limit, "offset": offset}
    rows = db.query(queries.tenders_sql(where, order_by), params_page)

    response.headers["X-Total-Count"] = str(total)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_shape_tender(r) for r in rows],
    }


def build_tender_detail(tender_id: int) -> Optional[dict]:
    """Tenderning to'liq ko'rinishi: lotlar, tovarlar, pozitsiyalar, tafsilot,
    AI xulosasi va hujjatlar. Tender yo'q bo'lsa `None`.

    ENDPOINTDAN AJRATILGAN (ai-chat): shu ma'lumotni AI-Chat ning `get_tender`
    tool'i ham oladi (`api/ai_chat.py`). Mantiq bir joyda tursin — HTTP qatlami
    (404) esa endpointda qoladi."""
    row = db.query_one(queries.tender_by_id_sql(), {"id": tender_id})
    if not row:
        return None

    tender = _shape_tender(row)

    lots = db.query(queries.TENDER_LOTS_SQL, {"id": tender_id})
    goods = db.query(queries.TENDER_GOODS_SQL, {"id": tender_id})

    # Tovarlarni lot bo'yicha guruhlaymiz
    goods_by_lot: dict = {}
    for g in goods:
        goods_by_lot.setdefault(g["lot_id"], []).append({
            "good_code": g["good_code"],
            "name": g["name"],
            "unit": g["unit"],
            "amount": _num(g["amount"]),
            "price": _num(g["price"]),
            "totalcost_item": _num(g["totalcost_item"]),
            "category": (
                {"uid": str(g["category_uid"]), "code": g["category_code"],
                 "title_ru": g["category_title_ru"]}
                if g.get("category_uid") else None
            ),
        })

    # Pozitsiya tafsilotlari (get_items dan) — yetkazish/kafolat/xarakteristika
    items = db.query(queries.TENDER_ITEMS_SQL, {"id": tender_id})
    items_by_lot: dict = {}
    for it in items:
        items_by_lot.setdefault(it["lot_id"], []).append({
            "item_id": it["item_id"],
            "product_code": it["product_code"],
            "name": it["name"],
            "unit": it["unit"],
            "amount_text": it["amount_text"],
            "price_text": it["price_text"],
            "totalcost_text": it["totalcost_text"],
            "delivery_period": it["delivery_period"],
            "guarantee": it["guarantee"],
            "prod_year": it["prod_year"],
            "country_of_origin": it["country_of_origin"],
            "delivery_address": it["delivery_address"],
            "spec": it["spec"],
            "properties": it["properties"] or [],
        })

    tender["lots"] = [
        {
            "lot_id": l["lot_id"],
            "title": l.get("title"),
            "item_count": l["item_count"],
            "total_sum_lot": _num(l["total_sum_lot"]),
            "goods": goods_by_lot.get(l["lot_id"], []),
            "items": items_by_lot.get(l["lot_id"], []),
        }
        for l in lots
    ]

    # Tafsilot (get_proc dan): baholash usuli, rekvizitlar, izoh...
    det = db.query_one(queries.TENDER_DETAIL_SQL, {"id": tender_id})
    tender["detail"] = {
        "anno": det.get("anno"),
        "method_marks": det.get("method_marks"),
        "company_details": det.get("company_details"),
        "director": det.get("director"),
        "close_time": det.get("close_time"),
        "proc_lang": det.get("proc_lang"),
        "offer_period": det.get("offer_period"),
    } if det else None

    # AI TAHLILI (5a) — bo'lsa qo'shamiz, bo'lmasa null (majburiy emas)
    ai_row = db.query_one(queries.AI_ANALYSIS_SQL,
                          {"id": tender_id, "kind": ai.KIND})
    tender["ai"] = ({**ai_row["result"],
                     "model": ai_row.get("model"),
                     "generated_at": _iso(ai_row.get("created_at"))}
                    if ai_row else None)

    # HUJJATLAR — bo'limlar bo'yicha guruhlangan (texnik topshiriq, xarid hujjati...)
    docs = [_shape_document(r, tender_id) for r in
            db.query(queries.TENDER_DOCUMENTS_SQL, {"id": tender_id})]
    tender["documents"] = docs
    tender["doc_count"] = len(docs)

    groups: dict = {}
    for d in docs:
        groups.setdefault(d["section"], []).append(d)
    tender["document_sections"] = [
        {"section": k, "files": v} for k, v in groups.items()
    ]
    return tender


@app.get("/tenders/{tender_id}")
def get_tender(tender_id: int):
    """Bitta tender to'liq — lotlar va har lotda tovarlar bilan."""
    tender = build_tender_detail(tender_id)
    if tender is None:
        raise xatolar.Xato("TENDER_NOT_FOUND", {"id": tender_id})
    return tender


def _tender_bor_yoki_404(tender_id: int) -> None:
    """Yo'q tender uchun 404. Bo'sh ro'yxat "hujjat yo'q" degani, "tender yo'q"
    degani EMAS — ikkalasini bir xil javob bilan qaytarsak, mijoz noto'g'ri
    havoladan kelganini bilolmaydi. /stock-check va /compliance allaqachon
    shunday qiladi; qolganlarini ham shu qatorga keltiramiz."""
    if not db.query_one("SELECT 1 AS x FROM tender WHERE id = %(id)s",
                        {"id": tender_id}):
        raise xatolar.Xato("TENDER_NOT_FOUND", {"id": tender_id})


def _tirik_yoki_409(row: dict, tender_id: int) -> None:
    """Yopilgan tenderда AI tahlilini BOSHLAMAYDI.

    Nega 404 emas: tender bor, lekin unga endi taklif berib bo'lmaydi —
    "topilmadi" degan javob noto'g'ri bo'lardi.

    Nega model chaqirilishidan OLDIN: tahlil pul turadi. Muddati o'tgan
    tender bo'yicha xulosa esa foydasiz — foydalanuvchi u bilan hech nima
    qila olmaydi. Ro'yxat filtrlari buni allaqachon yashiradi, ammo bu
    endpointга to'g'ridan-to'g'ri havola, eski kartochka yoki ERP so'rovi
    bilan ham kelish mumkin (reja_ai_chat.md §16.2).
    """
    reason = matching.closed_reason(row)
    if reason:
        raise xatolar.Xato("AI_SKIPPED", {"id": tender_id, "sabab": reason})


@app.get("/tenders/{tender_id}/documents")
def tender_documents(tender_id: int):
    """Faqat hujjatlar ro'yxati (yuklab olish havolalari bilan)."""
    _tender_bor_yoki_404(tender_id)
    rows = db.query(queries.TENDER_DOCUMENTS_SQL, {"id": tender_id})
    return [_shape_document(r, tender_id) for r in rows]


@app.get("/tenders/{tender_id}/erp-status")
def tender_erp_status(tender_id: int):
    """Shu tender ERP da ishga olinganmi va kim tomonidan.

    ERP GA HTTP SO'ROV YO'Q — `erp.v_tender_status` view i o'qiladi
    (`api/erp_status.py` dagi izohga qarang). ERP o'rnatilmagan bo'lsa
    bo'sh ro'yxat qaytadi va interfeys blokni ko'rsatmaydi."""
    return {"ready": erp_status.ready(),
            "opportunities": erp_status.for_tender(tender_id)}


@app.get("/documents/{tender_id}/download")
def download_document(tender_id: int, ref: str):
    """Fayl yuklab olish proksisi.

    NEGA KERAK: UzEx fayl endpointi faqat POST qabul qiladi (GET -> 405),
    brauzerdagi <a href> esa GET yuboradi. Shuning uchun POST'ni biz qilamiz
    va oqimni (stream) foydalanuvchiga uzatamiz — fayl xotiraga to'liq
    yuklanmaydi (16 MB li arxivlar ham bor).
    """
    row = db.query_one(queries.DOCUMENT_BY_REF_SQL, {"id": tender_id, "ref": ref})
    if not row:
        raise xatolar.Xato("DOCUMENT_NOT_FOUND")

    platform = row.get("source_platform") or "xt-xarid"
    if platform == "xt-xarid" and row.get("file_id"):
        return RedirectResponse(_FILE_URL["xt-xarid"].format(file_id=row["file_id"]))

    upstream = _POST_DOWNLOAD.get(platform)
    if upstream:
        try:
            up = requests.post(upstream, params={"path": row["file_path"]},
                               headers={"User-Agent": _BROWSER_UA},
                               stream=True, timeout=60)
            up.raise_for_status()
        except requests.RequestException as e:
            raise xatolar.kodli(e, "SOURCE_FETCH_FAILED")
        name = row.get("name") or "document"
        return StreamingResponse(
            up.iter_content(chunk_size=65536),
            media_type=up.headers.get("Content-Type", "application/octet-stream"),
            headers={"Content-Disposition":
                     f'attachment; filename="{quote(name)}"'},
        )

    raise xatolar.Xato("PLATFORM_DOWNLOAD_UNSUPPORTED", {"platforma": platform})


@app.get("/stats")
def stats(
    status: str = Query("open", description="Qaysi status bo'yicha statistika (default open)."),
    region: Optional[str] = Query(
        None, description="Viloyat kodi (level=1). Berilsa tuman/shahar kesimi qaytadi."),
):
    """Viloyat, tanlanganda esa tuman/shahar kesimidagi statistika.

    `region` bo'sh bo'lsa respublika bo'yicha faqat level=1 hududlar
    qaytadi. Viloyat kodi berilsa barcha ko'rsatkichlar shu viloyat bilan
    cheklanadi va `by_region` tuman/shaharlarni beradi. Viloyat darajasida
    qolgan tenderlar NULL nom bilan qaytadi — frontend ularni alohida
    "tuman/shahar ko'rsatilmagan" guruhi deb ko'rsatadi.
    """
    selected = None
    if region:
        selected = db.query_one(queries.STATS_REGION_SQL, {"region": region})
        if not selected or selected.get("level") != 1:
            raise xatolar.Xato("STATS_LEVEL_INVALID")

    p = {"status": status, "region": region}
    open_count = db.scalar(queries.STATS_OPEN_COUNT_SQL, p) or 0

    by_currency = [
        {"currency": r["currency"],
         "tender_count": r["tender_count"],
         "total_value": _num(r["total_value"])}
        for r in db.query(queries.STATS_BY_CURRENCY_SQL, p)
    ]

    region_sql = (queries.STATS_BY_LOCALITY_SQL if selected
                  else queries.STATS_BY_PROVINCE_SQL)
    by_region = [{
        "area_id": r["area_id"],
        "name": r["name"],
        "tender_count": r["tender_count"],
        # Valyutalar qo'shilmaydi: 1 USD + 1 UZS ma'nosiz. Har bir hudud
        # ichida summa valyuta bo'yicha alohida qaytadi.
        "totals_by_currency": [{
            "currency": item.get("currency"),
            "total_value": _num(item.get("total_value")),
        } for item in (r.get("totals_by_currency") or [])],
    } for r in db.query(region_sql, p)]

    return {
        "status": status,
        "scope": "localities" if selected else "provinces",
        "selected_region": ({"area_id": selected["area_id"],
                             "name": selected["name"]}
                            if selected else None),
        "count": open_count,
        "by_currency": by_currency,
        "by_region": by_region,
    }


@app.get("/regions")
def regions(parent_id: Optional[str] = Query(None, description="Faqat shu ota tugun bolalari (kaskad dropdown uchun).")):
    """Hudud dropdown ma'lumotlari. parent_id berilsa faqat bolalari qaytadi."""
    if parent_id:
        where = "WHERE parent_id = %(parent_id)s"
        params = {"parent_id": parent_id}
    else:
        where, params = "", {}
    return db.query(queries.REGIONS_SQL.format(where=where), params)


@app.get("/statuses")
def statuses():
    """Status dropdown ma'lumotlari (domain='tender')."""
    return db.query(queries.STATUSES_SQL)


@app.get("/freshness")
def freshness():
    """Ma'lumot yangiligi + ETL sog'ligi (H bosqich).
    Dashboard 'oxirgi yangilanish' ko'rsatkichi va aniqlash-kechikishi uchun."""
    runs = db.query(queries.FRESHNESS_SQL)
    platforms = [{
        "source_platform": r["source_platform"],
        "status": r["status"],
        "found": r["found"], "new": r["new"],
        "finished_at": _iso(r["finished_at"]),
        "age_sec": r["age_sec"],
    } for r in runs]

    # Umumiy yangilik = eng eski (eng kam yangilangan) manba
    ages = [p["age_sec"] for p in platforms if p["age_sec"] is not None]
    overall_age = max(ages) if ages else None
    any_error = any(p["status"] == "error" for p in platforms)

    det = db.query_one(queries.DETECTION_STATS_SQL) or {}
    n = det.get("n") or 0
    detection = {
        "sample": n,
        "median_hours": round(float(det["median_hours"]), 1) if det.get("median_hours") is not None else None,
        "within_1h_pct": round(100 * det["within_1h"] / n) if n else None,
    }
    # KORPUS — semantik qidiruv qancha tenderni ko'radi.
    #
    # "TUGADI" DEB YOZILMAYDI. Korpus o'sib turadi, ya'ni yagona
    # to'g'ri holat "quvib yetdi" (`vektorsiz = 0`) yoki "N ta
    # orqada". Ko'rsatkich `tugadi` desa, odam ish bitgan deb
    # o'ylardi va navbat yana o'sganini payqamasdi.
    corpus = None
    try:
        c = db.query_one(queries.CORPUS_STATS_SQL) or {}
        vektorsiz = int(c.get("vektorsiz") or 0)
        # SOVUQ START. Bo'laklash endigina yurgan bo'lsa "oxirgi 24
        # soat" butun korpusni qamrab oladi va `new_24h` SUR'AT
        # EMAS — bir martalik to'ldirish. Aynan shu xato bugun
        # `review_speed()` da tuzatilgan edi va bu yerda QAYTDI.
        yosh = float(c.get("yosh_kun") or 0)
        corpus = {
            "chunks": int(c.get("jami") or 0),
            "unvectorized": vektorsiz,
            "tenders": int(c.get("tenderlar") or 0),
            "new_24h": int(c.get("sutkalik_yangi") or 0),
            "growth_reliable": yosh >= 2.0,
            # QUVIB YETDI — "tugadi" emas.
            "caught_up": vektorsiz == 0,
        }
        # VEKTORLASH QAMROVI — har bo'lak AYNAN BITTA holatda.
        #
        # Ilgari faqat `unvectorized` bor edi va u UCH XIL narsani
        # birlashtirar edi: "navbatda", "yiqildi", "yaroqsiz".
        # "Nega vektorlanmagan" degan savolga javob YO'Q edi.
        e = db.query_one("SELECT * FROM v_embedding_coverage") or {}
        if e:
            corpus["embedding"] = {
                "model": e.get("faol_model"),
                "dimension": e.get("faol_olcham"),
                "total": int(e.get("jami") or 0),
                "embedded": int(e.get("vektorlangan") or 0),
                "pending": int(e.get("navbatda") or 0),
                "stale": int(e.get("eskirgan") or 0),
                "failed": int(e.get("yiqildi") or 0),
                "permanently_failed": int(e.get("butunlay_yiqildi") or 0),
                "invalid": int(e.get("yaroqsiz") or 0),
                "skipped": int(e.get("otkazildi") or 0),
                "model_mismatch": int(e.get("model_mos_emas") or 0),
                "text_changed": int(e.get("matn_ozgargan") or 0),
                # MAXRAJ = yaroqli bo'laklar. `yaroqsiz` kirmaydi:
                # ularni vektorlash ma'nosiz va foizni pasaytirish
                # "ishlamayapti" degan yolg'on berardi.
                "eligible": int(e.get("yaroqli") or 0),
                "coverage_pct": (float(e["qamrov_foiz"])
                                 if e.get("qamrov_foiz") is not None else None),
                "from_model": int(e.get("modeldan") or 0),
                "from_hash": int(e.get("xeshdan") or 0),
                # NAZORAT — javobda ATAYLAB ko'rinadi.
                "unaccounted": int(e.get("hisobga_olinmagan") or 0),
                "reconciles": int(e.get("hisobga_olinmagan") or 0) == 0,
            }
    except Exception:                                       # noqa: BLE001
        corpus = None       # ko'rsatkich asosiy javobni buzmasin

    # HUJJAT QAMROVI — har metadata qatorining holati.
    #
    # NEGA KERAK: ilgari faqat `tender_document_text` statuslari
    # ko'rinardi (ok/unreadable/unsupported/too_large) va ular
    # metadata ning ATIGI 32% ini qoplardi. Qolgan 68% hech qanday
    # holatda ko'rinmasdi — "yo'qoldi" bo'lib o'qilardi, aslida esa
    # qamrovdan tashqarida yoki navbatda edi.
    #
    # `hisobga_olinmagan` HAR DOIM 0 bo'lishi shart. Noldan farqli
    # qiymat jim bo'shliq QAYTGANINI bildiradi va u javobda
    # KO'RINADI — jimgina o'tib ketmasin.
    documents = None
    try:
        d = db.query_one("SELECT * FROM v_document_processing_coverage") or {}
        if d:
            documents = {
                "metadata_rows": int(d.get("metadata_qatori") or 0),
                "total": int(d.get("jami") or 0),
                # QAMROVDAN TASHQARI — nosozlik EMAS. Alohida turadi,
                # aks holda "68% ishlamadi" degan yolg'on chiqardi.
                "not_scheduled": int(d.get("rejalashtirilmagan") or 0),
                "pending": int(d.get("navbatda") or 0),
                "downloading": int(d.get("yuklanmoqda") or 0),
                "downloaded": int(d.get("yuklab_olindi") or 0),
                "extracting": int(d.get("matn_ajratilmoqda") or 0),
                "ok": int(d.get("ok") or 0),
                "unreadable": int(d.get("unreadable") or 0),
                "unsupported": int(d.get("unsupported") or 0),
                "too_large": int(d.get("too_large") or 0),
                "download_failed": int(d.get("yuklab_olinmadi") or 0),
                "permanently_failed": int(d.get("butunlay_yiqildi") or 0),
                "gone_from_source": int(d.get("manbadan_yoqoldi") or 0),
                "metadata_missing": int(d.get("metadata_yoqolgan") or 0),
                "in_scope": int(d.get("qamrovda") or 0),
                "ok_pct_in_scope": (float(d["ok_foiz_qamrovda"])
                                    if d.get("ok_foiz_qamrovda") is not None else None),
                "settled_pct": (float(d["yakunlangan_foiz"])
                                if d.get("yakunlangan_foiz") is not None else None),
                # NAZORAT USTUNI — javobda ATAYLAB ko'rinadi.
                "unaccounted": int(d.get("hisobga_olinmagan") or 0),
                "reconciles": int(d.get("hisobga_olinmagan") or 0) == 0,
            }
    except Exception:                                       # noqa: BLE001
        documents = None

    return {
        "overall_age_sec": overall_age,
        "any_error": any_error,
        "platforms": platforms,
        "detection": detection,
        "corpus": corpus,
        "documents": documents,
    }


# ---------------------------------------------------------------------------
# AI MOSLIK TAHLILI — "bu tender menga mos keladimi?"
#
# Deterministik filtrlardan (mahsulot/xizmat/kategoriya) FARQI: ular nom
# o'xshashligiga qaraydi, AI esa MA'NOGA. Katalogda "Насос" bo'lsa, matn
# qidiruvi "Кольцо для ремонта насосов" ni ham tortadi — AI buni "mos emas,
# bu nasos emas, uning zichlagichi" deb ajratadi.
#
# XARAJAT: natija keshlanadi (ai_analysis, kind='match_v1'). Hukm tender VA
# katalogga bog'liq bo'lgani uchun kesh kaliti ikkalasini qamraydi.
# ---------------------------------------------------------------------------
@app.post("/tenders/{tender_id}/ai-match")
def ai_match_tender(
    tender_id: int,
    request: Request,
    refresh: bool = Query(False, description="Keshni chetlab o'tib qayta tahlil qilish."),
):
    """Tender foydalanuvchi katalogiga mos kelishini AI orqali baholaydi.

    Javob: {verdict, score, reason_uz, matched_items, requirements, risks,
            cached, model, generated_at}
    """
    row = db.query_one(queries.AI_TENDER_SQL, {"id": tender_id})
    if not row:
        raise xatolar.Xato("TENDER_NOT_FOUND", {"id": tender_id})
    _tirik_yoki_409(row, tender_id)

    # IJARACHI ENG BOSHIDA aniqlanadi. O'LCHANGAN NUQSON (2026-09-02):
    # `company_id` shu yerda ISHLATILARDI, lekin 12 qator KEYIN
    # aniqlanardi -> `UnboundLocalError` -> HTTP 500. Ya'ni bu
    # endpoint HECH QACHON ishlamagan.
    #
    # `company_id_of()` ishlatiladi, `current_account()["id"]` emas:
    # birinchisi SERVICE kaliti (ERP) yo'lini ham to'g'ri hal qiladi
    # va qolgan hamma endpoint bilan bir xil.
    company_id = company_id_of(request)

    products = db.query(queries.CATALOG_LIST_SQL, {"company_id": company_id})
    profile = _shape_profile(db.query_one(queries.PROFILE_GET_SQL,
                                          {"company_id": company_id}))

    # Biriktirilgan hujjatlar MATNI — tahlilning asosiy manbai. `doc_meta`
    # javobga ham tushadi: foydalanuvchi tahlil qaysi fayllarga tayanganini
    # va nimasi o'qilmaganini ko'rsin (TZ: "qora quti bo'lmasin").
    doc_text, doc_meta = ai_docs.context(tender_id)
    docs = ai_docs.prompt_block(doc_text, doc_meta)

    text = ai_match.build_input(row, products, profile, docs)
    h = ai_match.content_hash(text)

    cached = db.query_one(queries.AI_CACHED_SQL,
                          {"id": tender_id, "kind": ai_match.KIND,
                           "company_id": company_id})
    if cached and cached["content_hash"] == h and not refresh:
        return {**cached["result"], "cached": True,
                "model": cached.get("model"),
                "generated_at": _iso(cached.get("created_at")),
                "documents": doc_meta}

    try:
        out = ai_match.analyze(row, products, profile, docs=docs)
    except ai.AIUnavailable as e:
        # Kalit yo'q / chaqiruv muvaffaqiyatsiz — 503, chunki bu vaqtinchalik
        # va foydalanuvchi aybi emas. Frontend buni tushunarli ko'rsatadi.
        raise xatolar.kodli(e, "AI_UNAVAILABLE")

    saved = db.execute_returning(queries.AI_UPSERT_SQL, {
        "tender_id": tender_id, "kind": ai_match.KIND, "company_id": company_id,
        "content_hash": h,
        "result": json.dumps(out["result"], ensure_ascii=False),
        "model": out["model"],
        "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
    })
    return {**out["result"], "cached": False, "model": out["model"],
            "generated_at": _iso(saved["created_at"]) if saved else None,
            "documents": doc_meta}


def gonogo_cached(tender_id: int, company_id: int,
                  refresh: bool = False) -> Dict[str, Any]:
    """Go/No-Go natijasi, kesh bilan. Tender yo'q bo'lsa `LookupError`.

    ENDPOINTDAN AJRATILGAN (ai-chat): AI-Chat ning `run_gonogo` tool'i shu
    funksiyani chaqiradi (`api/ai_chat.py`) — kesh mantiqi ikki joyda
    bo'lmasligi uchun. `ai.AIUnavailable` yuqoriga ochiq o'tadi: uni HTTP
    qatlami 503 ga, chat qatlami esa tool xatosiga aylantiradi."""
    row = db.query_one(queries.AI_TENDER_SQL, {"id": tender_id})
    if not row:
        raise LookupError(f"Tender {tender_id} topilmadi.")
    _tirik_yoki_409(row, tender_id)
    # Tender shartlari `ai_gonogo.build_input()` uchun ichma-ich shaklda kerak
    row["detail"] = {"anno": row.get("anno"),
                     "method_marks": row.get("method_marks"),
                     "offer_period": row.get("offer_period")}

    products = db.query(queries.CATALOG_LIST_SQL, {"company_id": company_id})
    profile = _shape_profile(db.query_one(queries.PROFILE_GET_SQL,
                                          {"company_id": company_id}))

    doc_text, doc_meta = ai_docs.context(tender_id)
    docs = ai_docs.prompt_block(doc_text, doc_meta)

    # J3 — TUZILGAN TALABLAR. Bo'sh bo'lsa blok umuman qo'shilmaydi,
    # ya'ni "talablar yo'q" degan yolg'on taassurot bo'lmaydi.
    #
    # DIQQAT: bu `content_hash` ni O'ZGARTIRADI, ya'ni mavjud keshlar
    # bir marta yangilanadi. Bu ATAYLAB: eski tahlil talablarni
    # ko'rmagan, uni "hali ham to'g'ri" deb ko'rsatish xato bo'lardi.
    from api import requirement as _req
    talablar = _req.prompt_block(tender_id, company_id)

    text = ai_gonogo.build_input(row, products, profile, docs=docs,
                                 talablar=talablar)
    h = ai_gonogo.content_hash(text)

    cached = db.query_one(queries.AI_CACHED_SQL,
                          {"id": tender_id, "kind": ai_gonogo.KIND,
                           "company_id": company_id})
    if cached and cached["content_hash"] == h and not refresh:
        return {**ai_gonogo.normalize(cached["result"]), "cached": True,
                "model": cached.get("model"),
                "generated_at": _iso(cached.get("created_at")),
                "criteria_labels": ai_gonogo.CRITERIA,
                "documents": doc_meta}

    out = ai_gonogo.analyze(row, products, profile, docs=docs,
                            talablar=talablar)

    saved = db.execute_returning(queries.AI_UPSERT_SQL, {
        "tender_id": tender_id, "kind": ai_gonogo.KIND, "company_id": company_id,
        "content_hash": h,
        "result": json.dumps(out["result"], ensure_ascii=False),
        "model": out["model"],
        "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
    })
    return {**out["result"], "cached": False, "model": out["model"],
            "generated_at": _iso(saved["created_at"]) if saved else None,
            "criteria_labels": ai_gonogo.CRITERIA,
            "documents": doc_meta}


@app.post("/tenders/{tender_id}/ai-gonogo")
def ai_gonogo_tender(
    tender_id: int,
    request: Request,
    refresh: bool = Query(False, description="Keshni chetlab o'tib qayta tahlil qilish."),
):
    """GO / REVIEW / NO-GO tavsiyasi — 11 mezon bo'yicha.

    `ai-match` dan farqi: u faqat mahsulot mosligini ko'radi, bu esa
    qatnashish qarorini butun kesimda (muddat, byudjet, sertifikat, tajriba,
    resurs) baholaydi.

    Ma'lumot yetishmagan mezon `malumot_yoq` bo'lib qaytadi va qaror `review`
    ga tushadi — model bo'sh joyni taxmin bilan to'ldirmaydi.
    """
    try:
        return gonogo_cached(tender_id, current_account(request)["id"],
                             refresh=refresh)
    except LookupError as e:
        raise xatolar.kodli(e, "TENDER_NOT_FOUND")
    except ai.AIUnavailable as e:
        raise xatolar.kodli(e, "AI_UNAVAILABLE")


# ---------------------------------------------------------------------------
# HUJJAT MATNI (TZ P0-2) — ilova qilingan fayllarning MATN holati
#
# Matnni `etl_doc_text.py` oldindan ajratadi (pypdf / python-docx / openpyxl —
# sof deterministik parserlar, AI emas) va `tender_document_text` da saqlaydi.
# Bu endpoint TARMOQQA CHIQMAYDI, faqat bazadan o'qiydi.
# ---------------------------------------------------------------------------
@app.get("/tenders/{tender_id}/documents/text")
def tender_documents_text(
    tender_id: int,
    ref: Optional[str] = Query(None, description="Bitta faylning matni (file_ref)."),
    full: bool = Query(False, description="ref bilan birga — to'liq matn."),
    preview_chars: int = Query(1500, ge=0, le=50000,
                               description="Ro'yxatdagi matn parchasi uzunligi."),
):
    """`status`: ok | unreadable | unsupported | too_large | download_failed | pending.

    'ok' dan boshqasi = "qo'lda tekshirish talab etiladi" (TZ P0-2 qabul mezoni).
    """
    _tender_bor_yoki_404(tender_id)
    if ref and full:
        row = db.query_one(queries.DOCUMENT_TEXT_FULL_SQL,
                           {"id": tender_id, "ref": ref})
        if not row:
            raise xatolar.Xato("DOCUMENT_TEXT_NOT_FOUND")
        return {
            "file_ref": ref,
            "status": row["status"],
            "manual_review": row["status"] != "ok",
            "reason": (None if row["status"] == "ok"
                       else _DOC_TEXT_REASON.get(row["status"], row["status"])),
            "detail": row.get("error"),
            "char_count": row.get("char_count"),
            "page_count": row.get("page_count"),
            "extractor": row.get("extractor"),
            "extracted_at": _iso(row.get("extracted_at")),
            "text": row.get("text"),
        }

    rows = db.query(queries.TENDER_DOCUMENT_TEXT_SQL,
                    {"id": tender_id, "preview": preview_chars})
    docs, counts = [], {}
    for r in rows:
        # Matn yozuvi umuman yo'q -> ETL bu faylga hali yetib bormagan
        status = r.get("status") or "pending"
        counts[status] = counts.get(status, 0) + 1
        docs.append({
            "file_ref": r["file_ref"], "name": r.get("name"),
            "file_type": r.get("file_type"), "size_bytes": r.get("size_bytes"),
            "section": _doc_label(r.get("field_key")),
            "status": status, "manual_review": status != "ok",
            "reason": (None if status == "ok"
                       else _DOC_TEXT_REASON.get(status, status)),
            "detail": r.get("error"),
            "char_count": r.get("char_count"), "page_count": r.get("page_count"),
            "extractor": r.get("extractor"),
            "extracted_at": _iso(r.get("extracted_at")),
            "preview": r.get("preview"),
        })
    total = len(docs)
    n_ok = counts.get("ok", 0)
    return {
        "tender_id": tender_id,
        "summary": {"total": total, "ok": n_ok,
                    "manual_review": total - n_ok,
                    "pending": counts.get("pending", 0),
                    "by_status": counts,
                    "chars": sum(d["char_count"] or 0 for d in docs)},
        "documents": docs,
    }


# ---------------------------------------------------------------------------
# KATALOG IMPORTI (TZ P0-4) — Excel/CSV/Google Sheets dan mahsulot + qoldiq
# ---------------------------------------------------------------------------
MAX_IMPORT_MB = 5


def _yuklangani(file: UploadFile, max_mb: int = MAX_IMPORT_MB) -> bytes:
    """Yuklangan faylni CHEGARANI OSHIRMASDAN o'qiydi.

    ILGARIGI XATO: `data = file.file.read()` — BUTUN fayl xotiraga
    o'qilar, CHEGARA esa SHUNDAN KEYIN tekshirilardi. Ya'ni 5 GB
    yuborilsa server chegarani tekshirishga YETIB BORMASDAN xotirani
    tugatardi. Chegara bor edi, lekin u KECH ishlardi.

    Endi bo'laklab o'qiladi va chegaradan oshgan ZAHOTI to'xtaydi:
    xotiraga eng ko'pi bilan `max_mb + 1 bo'lak` tushadi.

    Starlette `UploadFile` ni diskka spool qiladi, ya'ni bu yerdagi
    himoya "xotira" uchun; TARMOQ darajasidagi chegara (nginx
    `client_max_body_size`) infratuzilma vazifasi —
    `docs/xavfsizlik.md` §5.
    """
    chegara = max_mb * 1024 * 1024
    bolaklar, jami = [], 0
    while True:
        b = file.file.read(1024 * 1024)
        if not b:
            break
        jami += len(b)
        if jami > chegara:
            raise xatolar.Xato("FILE_TOO_LARGE", {"max_mb": max_mb})
        bolaklar.append(b)
    return b"".join(bolaklar)


@app.post("/catalog/import")
def catalog_import(
    request: Request,
    file: UploadFile = File(..., description="Excel (.xlsx) yoki CSV fayl."),
    dry_run: bool = Query(True, description="TRUE — faqat tekshirish, bazaga yozilmaydi."),
):
    """Format xatolari QATOR BO'YICHA qaytadi: bitta qatordagi xato butun
    importni to'xtatmaydi. `dry_run=true` (default) bazaga umuman tegmaydi."""
    data = _yuklangani(file)
    try:
        return importer.import_catalog(data, file.filename or "",
                                       company_id_of(request), dry_run=dry_run)
    except importer.ImportFormatError as e:
        # 422 — fayl formatiga oid xato (qatorga emas, butun faylga tegishli)
        raise xatolar.kodli(e, "IMPORT_FORMAT_INVALID")


@app.get("/catalog/import/template")
def catalog_import_template(fmt: str = Query("xlsx", pattern="^(xlsx|csv)$")):
    """Namunaviy shablon fayl (sarlavhalar + misol qatorlar)."""
    if fmt == "csv":
        return FileResponse(
            content=importer.template_csv(), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="katalog_shablon.csv"'})
    return FileResponse(
        content=importer.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="katalog_shablon.xlsx"'})


@app.get("/tenders/{tender_id}/stock-check")
def tender_stock_check(tender_id: int, request: Request):
    """TZ P0-6 — mos pozitsiyalar bo'yicha ombor qoldig'i. Yetishmayotganlar
    ALOHIDA `shortages` ro'yxatida. Qoldiq eskirgan bo'lsa `preliminary: true`."""
    res = stock.check_tender_stock(tender_id, company_id_of(request))
    if res is None:
        raise xatolar.Xato("TENDER_NOT_FOUND", {"id": tender_id})
    return res


# ---------------------------------------------------------------------------
# NARX HISOBI (TZ P0-7) — tannarx + ustama + xavf zaxirasi -> tavsiya etilgan narx
#
# AI YO'Q: butun mantiq `api/pricing.py` dagi SOF FUNKSIYADA. Endpointlar
# faqat ma'lumot yig'adi, uni chaqiradi va saqlaydi.
# ---------------------------------------------------------------------------
@app.get("/pricing/settings")
def get_pricing_settings(request: Request):
    """Odatiy parametrlar (har doim mavjud — patch id=1 ni yaratib qo'ygan)."""
    return _shape_pricing_settings(db.query_one(
        queries.PRICING_SETTINGS_GET_SQL,
        {"company_id": company_id_of(request)}))


@app.put("/pricing/settings")
def put_pricing_settings(s: PricingSettingsIn, request: Request):
    """Odatiy parametrlarni saqlaydi — yangi tenderda boshlang'ich qiymat.

    QISMAN yuborish mumkin: faqat kelgan maydonlar o'zgaradi. Ilgari model
    maydonlariga standart qiymat berilgani uchun `{"markup_percent": 22}`
    yuborilsa logistika va zaxira JIMGINA nolga qaytardi.
    """
    company_id = company_id_of(request)
    cur = db.query_one(queries.PRICING_SETTINGS_GET_SQL,
                       {"company_id": company_id}) or {}
    patch = s.model_dump(exclude_unset=True)
    merged = {k: patch.get(k, cur.get(k)) for k in
              ("markup_percent", "risk_reserve_percent", "risk_reserve_fixed",
               "logistics_percent", "logistics_fixed", "vat_percent", "currency")}
    row = db.execute_returning(queries.PRICING_SETTINGS_UPSERT_SQL,
                               {**merged, "company_id": company_id})
    return _shape_pricing_settings(row)


@app.get("/tenders/{tender_id}/pricing")
def get_tender_pricing(tender_id: int, request: Request):
    """Saqlangan smeta (yo'q bo'lsa null — 404 EMAS, chunki hisoblamaganlik
    xato emas; `/profile` bilan bir xil uslub). TENDERNING O'ZI yo'q bo'lsa
    esa bu boshqa hol — 404."""
    _tender_bor_yoki_404(tender_id)
    return _shape_tender_pricing(
        db.query_one(queries.TENDER_PRICING_GET_SQL,
                     {"id": tender_id,
                      "company_id": company_id_of(request)}))


@app.post("/tenders/{tender_id}/pricing")
def post_tender_pricing(tender_id: int, body: PricingIn, request: Request):
    """Smetani qayta hisoblaydi va saqlaydi.

    Frontend ham brauzerda hisoblaydi (bir xil formula — `pricing.ts`), lekin
    bazaga YOZILADIGANI doim serverning natijasi: yagona haqiqat manbai bitta
    bo'lishi kerak. Byudjet tenderdan, minimal foyda `company_profile` dan
    olinadi (faqat o'qish — jadval o'zgarmaydi).
    """
    t = db.query_one(queries.PRICING_TENDER_SQL, {"id": tender_id})
    if not t:
        raise xatolar.Xato("TENDER_NOT_FOUND", {"id": tender_id})

    company_id = company_id_of(request)
    settings = db.query_one(queries.PRICING_SETTINGS_GET_SQL,
                            {"company_id": company_id})
    profile = db.query_one(queries.PROFILE_GET_SQL,
                           {"company_id": company_id})
    goods = db.query(queries.TENDER_GOODS_SQL, {"id": tender_id})

    inp = pricing.build_inputs(settings, t, goods, profile, saved=None,
                               override=body.model_dump(exclude={"note"}))
    # `manual_price` ATAYLAB alohida: build_inputs None ni o'tkazib yuboradi,
    # bu yerda esa None "qo'lda narxni O'CHIR" degani.
    inp["manual_price"] = body.manual_price

    result = pricing.calculate(inp)
    if not result["ok"]:
        # Noto'g'ri kiruvchidan chiqqan smetani SAQLAMAYMIZ (masalan valyuta
        # aralashgan) — foydalanuvchi avval tuzatadi.
        raise xatolar.Xato(
            "CATALOG_IMPORT_INVALID",
            {"soni": len(result["errors"])},
            ichki="; ".join(e["message"] for e in result["errors"]))

    saved = db.execute_returning(queries.TENDER_PRICING_UPSERT_SQL, {
        "tender_id": tender_id,
        "company_id": company_id,
        "inputs": json.dumps(inp, ensure_ascii=False),
        "result": json.dumps(result, ensure_ascii=False),
        "manual_price": inp.get("manual_price"),
        "currency": inp.get("currency"),
        "note": body.note,
    })
    return {**_shape_tender_pricing(saved), **result}


# ---------------------------------------------------------------------------
# HUJJATLAR TO'LIQLIGI (TZ P0-8) — kompaniya hujjatlari + tender cheklisti
#
# STATIK cheklist: hujjat BORLIGI va MUDDATI tekshiriladi, mazmunining
# huquqiy to'g'riligi EMAS (AI chaqirilmaydi). TZ da ataylab shunday
# belgilangan — noto'g'ri huquqiy kafolat hissini yaratmaslik uchun.
# ---------------------------------------------------------------------------
@app.get("/company/document-types")
def company_document_types():
    """Kanonik hujjat turlari — formadagi dropdown shundan to'ladi."""
    return [{"code": d["code"], "label": d["label"], "hint": d["hint"],
             "base": d["base"]} for d in compliance.DOC_TYPES]


@app.get("/company/documents")
def company_documents(request: Request):
    """Kompaniya hujjatlari + har birining muddat holati."""
    rows = db.query(compliance.DOCS_LIST_SQL,
                    {"company_id": company_id_of(request)})
    return [compliance.shape_document(r) for r in rows]


@app.post("/company/documents", status_code=201)
def create_company_document(d: CompanyDocumentIn, request: Request):
    row = db.execute_returning(compliance.DOC_INSERT_SQL,
                               {**d.model_dump(),
                                "company_id": company_id_of(request)})
    return compliance.shape_document(row)


@app.put("/company/documents/{doc_id}")
def update_company_document(doc_id: int, d: CompanyDocumentIn,
                            request: Request):
    # `company_id` WHERE bandida: begona hujjat id si bilan tahrirlash
    # mumkin emas — javob 404 (IDOR himoyasi).
    row = db.execute_returning(compliance.DOC_UPDATE_SQL,
                               {**d.model_dump(), "id": doc_id,
                                "company_id": company_id_of(request)})
    if not row:
        raise xatolar.Xato("DOCUMENT_NOT_FOUND")
    return compliance.shape_document(row)


@app.get("/company/documents/template")
def company_documents_template(fmt: str = Query("xlsx", pattern="^(xlsx|csv)$")):
    """HUJJATLAR SHABLONI — talab etiladigan hujjatlar ro'yxati bilan
    OLDINDAN TO'LDIRILGAN fayl.

    Broker uni yuklab oladi, raqam va sanalarni yozadi va
    `POST /company/documents/import` orqali qaytarib yuklaydi. Ro'yxat
    `compliance.DOC_TYPES` dan olinadi — cheklist tekshiradigan turlar bilan
    AYNAN bir xil."""
    if fmt == "csv":
        return FileResponse(
            content=compliance.template_csv(), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="hujjatlar_shablon.csv"'})
    return FileResponse(
        content=compliance.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="hujjatlar_shablon.xlsx"'})


@app.post("/company/documents/import")
def company_documents_import(
    request: Request,
    file: UploadFile = File(..., description="To'ldirilgan shablon (.xlsx / .csv)."),
    dry_run: bool = Query(True, description="TRUE — faqat tekshirish, bazaga yozilmaydi."),
):
    """To'ldirilgan shablonni yuklaydi. Katalog importi bilan bir xil
    shartnoma: xato BITTA QATORNI to'xtatadi, importni emas; `dry_run=true`
    (default) bazaga umuman tegmaydi."""
    data = _yuklangani(file)
    try:
        return compliance.import_documents(data, file.filename or "",
                                           company_id_of(request),
                                           dry_run=dry_run)
    except importer.ImportFormatError as e:
        raise xatolar.kodli(e, "IMPORT_FORMAT_INVALID")


@app.post("/company/documents/parse")
def company_documents_parse(
    file: UploadFile = File(..., description="To'ldirilgan shablon (.xlsx / .csv)."),
):
    """SHABLON PARSERI XIZMAT SIFATIDA — faylni o'qiydi va tekshiradi,
    BAZAGA UMUMAN TEGMAYDI.

    `POST /company/documents/import` dan farqi: natija SHU KOMPANIYA
    hujjatlariga yozilmaydi, chaqiruvchiga qaytariladi. ERP (alohida loyiha)
    mijoz korxonalarning hujjatlarini o'z bazasiga yozadi, lekin shablon va
    uning qoidalari — sarlavhalarni tanish, sana formatlari, hujjat turini
    aniqlash — SHU YERDA qoladi va ikkinchi marta yozilmaydi.

    Javobdagi `rows` — tozalangan qatorlar (sanalar ISO satr ko'rinishida),
    chaqiruvchi ularni o'zi saqlaydi."""
    data = _yuklangani(file)
    try:
        ok, report = compliance.parse_document_file(data, file.filename or "")
    except importer.ImportFormatError as e:
        raise xatolar.kodli(e, "IMPORT_FORMAT_INVALID")
    return {**report, "rows": compliance.rows_json(ok)}


@app.delete("/company/documents/{doc_id}", status_code=204)
def delete_company_document(doc_id: int, request: Request):
    row = db.execute_returning(compliance.DOC_DELETE_SQL,
                               {"id": doc_id,
                                "company_id": company_id_of(request)})
    if not row:
        raise xatolar.Xato("DOCUMENT_NOT_FOUND")
    return None


# =============================================================================
# HUJJAT FAYLI — yuklash, ko'rish, yuklab olish
# =============================================================================
# FAYL YO'LI FOYDALANUVCHIDAN QABUL QILINMAYDI. `file_ref` matn maydoni
# joyida qoladi (eski 13 qator uchun), lekin YANGI yo'l shu yerdan
# o'tadi: brauzer BINARNI yuboradi, server kalit yasaydi.
#
# CHEGARA `_yuklangani()` da — faylni xotiraga TO'LIQ o'qishdan OLDIN.
# Chegara alohida (`MAX_UPLOAD_MB=25`), `MAX_IMPORT_MB` (5) esa Excel
# shabloni uchun qoladi: ular boshqa maqsad va boshqa xavf.
# =============================================================================
def _hujjat_yoki_404(doc_id: int, cid: int) -> dict:
    row = db.query_one("SELECT * FROM company_document "
                       " WHERE id=%(i)s AND company_id=%(c)s",
                       {"i": doc_id, "c": cid})
    if not row:
        raise xatolar.Xato("DOCUMENT_NOT_FOUND")
    return dict(row)


@app.post("/company/documents/{doc_id}/fayl")
def company_document_upload(
    doc_id: int, request: Request, background: BackgroundTasks,
    file: UploadFile = File(..., description="PDF / DOCX / XLSX / TXT / CSV / ZIP"),
):
    """Hujjatga HAQIQIY fayl biriktiradi.

    ALMASHTIRISH TARIXNI O'CHIRMAYDI (§10). Eski `yuklama` qatori
    arxivlanadi, yangisi unga `almashtirdi` orqali ishora qiladi va
    eski faylning iqtiboslari ishlayveradi. Auditda kim va qachon
    almashtirgani qoladi.
    """
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    hujjat = _hujjat_yoki_404(doc_id, cid)

    data = _yuklangani(file, max_mb=saqlash.MAX_UPLOAD_MB)
    y = yuklama.qabul_qil(cid, "company_doc", file.filename or "fayl",
                          data, aktor_id=k.actor_id)

    eski_id = hujjat.get("yuklama_id")
    if eski_id:
        # ARXIV, O'CHIRISH EMAS: hujjat muvofiqlik tekshiruvida yoki
        # o'tgan qarorda ishlatilgan bo'lishi mumkin.
        db.execute_returning(
            "UPDATE yuklama SET arxiv_at=now(), arxivladi=%(a)s "
            " WHERE id=%(i)s AND arxiv_at IS NULL RETURNING id",
            {"i": eski_id, "a": k.actor_id})
        db.execute_returning(
            "UPDATE yuklama SET almashtirdi=%(e)s WHERE id=%(i)s RETURNING id",
            {"i": y["id"], "e": eski_id})

    row = db.execute_returning("""
        UPDATE company_document
           SET yuklama_id=%(y)s, file_name=%(n)s, updated_at=now()
         WHERE id=%(i)s AND company_id=%(c)s
        RETURNING *""",
        {"i": doc_id, "c": cid, "y": y["id"], "n": y["original_nom"]})

    audit_yoz(k, request, amal="hujjat_fayl_yuklandi" if not eski_id
              else "hujjat_fayl_almashtirildi",
              entity="company_document", entity_id=doc_id,
              oldin={"yuklama_id": str(eski_id) if eski_id else None},
              keyin={"yuklama_id": y["id"], "nom": y["original_nom"],
                     "sha256": y["sha256"], "size_bytes": y["size_bytes"]})

    # AJRATISH FONDA. Javob darhol qaytadi va UI "Processing" ko'rsatadi;
    # `def` funksiya FastAPI da threadpool'da yuradi, ya'ni event loop
    # bloklanmaydi.
    background.add_task(yuklama.qayta_ishla, y["id"])
    return {**compliance.shape_document(row), "fayl": _fayl_json(y)}


def _fayl_json(y: dict) -> dict:
    """Fayl haqidagi JAVOB. `kalit` va yo'l HECH QACHON kirmaydi."""
    return {
        "id": str(y["id"]),
        "nom": y["original_nom"],
        "ext": y["ext"],
        "mime": y["mime"],
        "size_bytes": int(y["size_bytes"]),
        "holat": y["holat"],
        "xato": y.get("xato"),
        "matn_belgi": y.get("matn_belgi"),
        "sahifa_soni": y.get("sahifa_soni"),
    }


def _fayl_javobi(y: dict, inline: bool):
    """Faylni oqim bilan qaytaradi.

    `StreamingResponse` ATAYLAB: fayl 25 MB gacha bo'lishi mumkin va
    uni xotiraga to'liq o'qish server xotirasini bir necha parallel
    yuklab olishda tugatardi.
    """
    f = yuklama.ochib_ber(y)
    return StreamingResponse(f, headers=yuklama.javob_sarlavhasi(y, inline))


@app.get("/company/documents/{doc_id}/download")
def company_document_download(doc_id: int, request: Request):
    """Autentifikatsiyalangan yuklab olish. Ommaviy URL YO'Q."""
    cid = company_id_of(request)
    hujjat = _hujjat_yoki_404(doc_id, cid)
    if not hujjat.get("yuklama_id"):
        raise xatolar.Xato("FILE_NOT_FOUND")
    y = yuklama.ol(str(hujjat["yuklama_id"]), cid)
    return _fayl_javobi(y, inline=False)


@app.get("/company/documents/{doc_id}/view")
def company_document_view(doc_id: int, request: Request):
    """Brauzerda ko'rish — FAQAT xavfsiz formatlar `inline`.

    PDF va TXT dan boshqasi baribir `attachment` bo'lib tushadi
    (`yuklama.javob_sarlavhasi`): `inline` berilgan HTML ayni
    originda skript yurgizardi.
    """
    cid = company_id_of(request)
    hujjat = _hujjat_yoki_404(doc_id, cid)
    if not hujjat.get("yuklama_id"):
        raise xatolar.Xato("FILE_NOT_FOUND")
    y = yuklama.ol(str(hujjat["yuklama_id"]), cid)
    return _fayl_javobi(y, inline=True)


@app.get("/company/documents/{doc_id}/fayl")
def company_document_fayl_holat(doc_id: int, request: Request):
    """Fayl holati — UI shu bilan "Processing" dan "Ready" ga o'tadi."""
    cid = company_id_of(request)
    hujjat = _hujjat_yoki_404(doc_id, cid)
    if not hujjat.get("yuklama_id"):
        return None
    return _fayl_json(yuklama.ol(str(hujjat["yuklama_id"]), cid))


@app.get("/tenders/{tender_id}/compliance")
def tender_compliance(tender_id: int, request: Request):
    """Majburiy hujjatlar ro'yxati + har biri uchun "bazada bor / yo'q" va
    muddat holati. Tenderда talab topilmasa buni OCHIQ aytadi.

    Hujjatlar manbasi — SHU kompaniyaning bazasi (`company_document`)."""
    if not db.query_one("SELECT 1 AS x FROM tender WHERE id = %(id)s",
                        {"id": tender_id}):
        raise xatolar.Xato("TENDER_NOT_FOUND")
    return compliance.check(tender_id, company_id=company_id_of(request))


class ComplianceDocsIn(BaseModel):
    """Tashqi tizim (ERP) yuboradigan hujjatlar. Maydonlari
    `company_document` bilan bir xil; `documents=None` bo'lsa shu
    kompaniyaning bazasi ishlatiladi."""
    documents: Optional[List[Dict[str, Any]]] = None


@app.post("/tenders/{tender_id}/compliance")
def tender_compliance_for(tender_id: int, body: ComplianceDocsIn):
    """CHEKLIST XIZMAT SIFATIDA — qoidalar shu yerda, hujjatlar chaqiruvchida.

    ERP alohida loyiha va mijoz korxonalarning hujjatlarini o'zi saqlaydi.
    Qoidalar esa (DOC_TYPES, tender matnidan talabni aniqlash) shu modulda,
    1400 qator — ularning IKKINCHI NUSXASI bo'lmasligi kerak. Shuning uchun
    ERP hujjatlarni YUBORADI, javobda tayyor cheklist oladi.

    Bu yerda erp sxemasi haqida hech narsa bilinmaydi: kirish — oddiy
    ro'yxat, bog'liqlik bir tomonlama."""
    if not db.query_one("SELECT 1 AS x FROM tender WHERE id = %(id)s",
                        {"id": tender_id}):
        raise xatolar.Xato("TENDER_NOT_FOUND")
    res = compliance.check(tender_id, docs=body.documents)
    res["doc_source"] = "external" if body.documents is not None else "company"
    return res


# ---------------------------------------------------------------------------
# J3 — TALABLAR va ularni TASDIQLASH
#
# NEGA TASDIQLASH KERAK: ajratilgan talab AI natijasi, ya'ni xato
# bo'lishi mumkin. Uni to'g'ridan-to'g'ri `compliance` ga ulash AI
# xatosini QAROR QATLAMIGA jimgina o'tkazadi — natijada ARVOH BLOCKER
# ("kafolat sharti bajarilmagan", holbuki shart qo'yilmagan).
# Broker bunday ogohlantirishni bir-ikki marta ko'rgach BUTUN
# cheklistga ishonishni to'xtatadi.
# ---------------------------------------------------------------------------

@app.get("/requirements/queue")
def requirements_queue(request: Request, limit: int = 100,
                       q: Optional[str] = Query(None),
                       region: Optional[str] = Query(None),
                       past: bool = Query(False),
                       manba: Optional[str] = Query(None),
                       otgan: bool = Query(False),
                       katalog: bool = Query(False)):
    """Ko'rib chiqish navbati — kutayotgan talabi bor tenderlar.

    Muddati YAQIN tenderlar birinchi: ular bo'yicha qaror tezroq
    kerak. Tenderning hamma talablari ko'rib chiqilgach u navbatdan
    CHIQIB KETADI.

    FILTR SERVERDA (2026-09-03) — navbat 484, sahifa 100. Mijoz
    tomonida filtrlash olingan sahifadan tashqarisini KO'RMASDI.
    `jami` mos kelganlarning to'liq sonini beradi.
    """
    from api import requirement
    cid = company_id_of(request)
    queue, jami = requirement.review_queue(
        cid, min(max(limit, 1), 500), q=q, region=region,
        faqat_past=past, manba=manba, otgan=otgan, katalog=katalog)
    # MANBA SONLARI — interfeys "Modeldan (0)" deb YOZADI va variantni
    # o'chiradi. Busiz filtr hech narsa qilmayotgandek ko'rinardi:
    # bugun HAMMA kutayotgan talab `naqsh` dan (LLM qatlami pullik va
    # qulflangan), ya'ni "Naqshdan" jamini o'zgartirmaydi, "Modeldan"
    # esa ro'yxatni bo'shatadi. Ikkalasi ham BUZUQ deb o'qilardi.
    #
    # `manba` ning O'ZI hisobga OLINMAYDI: savol "shu manbani
    # tanlasam nechta qoladi", "umuman nechta bor" emas.
    manbalar = requirement.review_queue_manbalar(
        cid, q=q, region=region, faqat_past=past, otgan=otgan,
        katalog=katalog)
    return {"queue": queue, "jami": jami, "korsatildi": len(queue),
            "manbalar": manbalar}


@app.get("/tenders/{tender_id}/requirements")
def tender_requirements(tender_id: int, request: Request):
    """Tender talablari — ko'rib chiqish holati bilan."""
    from api import requirement
    if not db.query_one("SELECT 1 AS x FROM tender WHERE id = %(id)s",
                        {"id": tender_id}):
        raise xatolar.Xato("TENDER_NOT_FOUND")
    cid = company_id_of(request)
    items = requirement.review_items(tender_id, cid)
    # VAQT O'LCHOVI: tender ochilgan payt shu yerda yoziladi.
    # Faqat KUTAYOTGAN talab bo'lsa — ko'rilgan tenderni qayta ochish
    # yangi o'lchov boshlamasin.
    if any(x["review_status"] == "pending_review" for x in items):
        requirement.review_ochildi(tender_id, cid)
    return {
        "tender_id": tender_id,
        # YOPIQ rejimda interfeys model javobini YASHIRADI — anchoring
        # ga qarshi. Rejim SERVERDAN keladi: mijoz uni o'zgartira
        # olmasligi kerak, aks holda o'lchov ishonchsiz bo'lardi.
        "rejim": requirement.pilot_rejim(tender_id, cid),
        "summary": requirement.summary(tender_id, cid),
        "items": items,
    }


@app.get("/requirements/doc-types")
def requirement_doc_types():
    """Yorliq lug'ati — `compliance.DOC_TYPES` + 'yoq' / 'boshqa'.

    Interfeys shu ro'yxatdan tanlaydi. Erkin matn EMAS: moslashtiruv
    ground truth i CHEKLI lug'atga tayanishi kerak, aks holda uni
    keyin normallashtirish alohida ish bo'lib qoladi.
    """
    from api import requirement
    return {"doc_types": requirement.doc_type_options()}


@app.get("/requirements/labeled")
def requirements_labeled(request: Request, limit: int = 1000):
    """Inson yorliqlagan to'plam — moslashtiruv va J6 uchun."""
    from api import requirement
    return {"items": requirement.labeled(company_id_of(request),
                                         min(max(limit, 1), 5000))}


class ReviewIn(BaseModel):
    """Bitta talabning ko'rib chiqish natijasi — INSON qarori.

    `status` FAQAT inson qarori bo'lishi mumkin. `extracted` va
    `pending_review` ATAYLAB QABUL QILINMAYDI: ular ajratish
    qatlamining holatlari, va ularni API orqali yozish "inson
    qarorini mashina bekor qildi" degan yo'lni ochardi.

    `Literal` bilan qulflangan — noto'g'ri qiymat FastAPI darajasida
    422 beradi va `requirement.review_set()` gacha yetib bormaydi.
    """
    status: Literal["approved", "rejected", "corrected", "uncertain"]
    corrected_value: Optional[str] = None
    note: Optional[str] = None
    #: `compliance.DOC_TYPES` kodi yoki 'yoq' / 'boshqa'.
    #: Berilmasa eskisi QOLADI — tasodifan o'chib ketmasin.
    doc_type: Optional[str] = None
    #: YOPIQ rejimda inson model javobini KO'RMASDAN yozgan qiymat.
    #: Bir marta yozilgach o'zgarmaydi (server tomonda `COALESCE`).
    blind_value: Optional[str] = None


# KO'RIK TUGAGACH NAVBAT YANGILANADI.
#
# Ilgari zanjir shu yerda UZILARDI: tasdiq `tender_requirement` ga
# yozilardi, `tender_routing` esa keyingi ETL yurishigacha (yoki
# brokerning "Yangilash" tugmasigacha) ESKI ballni ko'rsatib turardi.
# Ya'ni tasdiqning butun ma'nosi -- dalilni yaxshilash -- navbatga
# soatlab yetib bormasdi.
#
# QOIDA IKKI JOYDA TAKRORLANMAYDI: "kimni baholash mumkin" ta'rifi
# `api/routing.py` da (`korik_tugadi`), bu yerda faqat CHAQIRUV.
def _navbatni_yangila(tender_id: int, cid: int) -> Dict[str, Any]:
    """Ko'rik tugagach navbatni qayta hisoblaydi.

    YIQILSA KO'RIKNI BUZMAYDI. Talab allaqachon YOZILGAN va u
    asosiy ish; navbat -- ikkilamchi. Xato 500 ga aylansa
    foydalanuvchi "tasdiq o'tmadi" deb o'ylab QAYTA bosardi.

    Lekin JIMGINA ham yutilmaydi: sabab javobda qaytadi va
    interfeys uni ko'rsatadi (`api/topshiriq.py` dagi naqsh).
    """
    from api import routing
    try:
        return routing.korik_tugadi(tender_id, cid)
    except Exception as e:                              # noqa: BLE001
        _log.warning("navbatni yangilash yiqildi tender=%s: %s",
                    tender_id, e)
        return {"holat": "xato", "xato": f"{type(e).__name__}: {e}"[:200],
                "ozgardi": False, "inson_qarori_eskirdi": False,
                "ai_qaror": None, "routing_id": None}


@app.post("/requirements/{req_id}/review")
def requirement_review(req_id: int, body: ReviewIn, request: Request):
    """Talabni tasdiqlash / rad etish / tuzatish.

    `company_id` SESSIYADAN va SQL SHARTIDA — boshqa kompaniyaning
    talabini o'zgartirib bo'lmaydi (IDOR himoyasi).
    """
    from api import requirement
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    # `approved` va `rejected` — TASDIQLASH huquqi; `corrected` esa
    # ko'rib chiqish. Ular ATAYLAB har xil: qiymatni tuzatish va uni
    # rasman tasdiqlash bir xil vaznda emas.
    # `uncertain` — ko'rib chiqish huquqi yetarli: u hech narsani
    # tasdiqlamaydi, aksincha "hal qilinmadi" deb belgilaydi.
    ruxsat(k, "tasdiq" if body.status == "approved"
           else "rad" if body.status == "rejected" else "korib_chiq")
    oldin = requirement.bitta(req_id, cid)
    try:
        row = requirement.review_set(
            req_id, cid, body.status,
            corrected=body.corrected_value, note=body.note, by=cid,
            doc_type=body.doc_type, blind_value=body.blind_value,
            actor_id=k.actor_id, ishonch=k.ishonch)
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    if row:
        audit_yoz(k, request, amal=f"talab_{body.status}",
                  entity="tender_requirement", entity_id=req_id,
                  oldin=oldin,
                  keyin={"review_status": row.get("review_status"),
                         "review_action": row.get("review_action"),
                         "corrected_value": row.get("corrected_value"),
                         "doc_type": row.get("doc_type")},
                  izoh=body.note)
    if not row:
        # Yo'q, yoki BOSHQA kompaniyaniki — ikkalasida ham 404.
        # Farqni aytish "bu id mavjud" degan ma'lumot sizdirardi.
        raise xatolar.Xato("REQUIREMENT_NOT_FOUND")
    qolgan = db.scalar(
        "SELECT count(*) FROM tender_requirement "
        "WHERE company_id=%(c)s AND tender_id=%(t)s "
        "AND review_status='pending_review'",
        {"c": cid, "t": row["tender_id"]})
    yonaltirish: Optional[Dict[str, Any]] = None
    if not qolgan:
        # OXIRGI talab belgilandi — vaqtni yopamiz.
        #
        # `reviewed_by IS NOT NULL` — INSON HAQIQATAN ko'rgan qator.
        #
        # Ilgari `review_status <> 'pending'` edi va u REYESTR
        # pozitsiyalarini ham sanardi: ular avto-tasdiqlanadi
        # (`approved`, `reviewed_by IS NULL`). O'lchandi: pilot
        # tenderlarida `<> pending` = 29, `reviewed_by` = 0.
        #
        # Natijada `n_reviewed` shishar va `sekund_talabga` SHUNCHA
        # kam chiqardi — inson haqiqiydan TEZROQ ko'rinardi va
        # "har talabni inson tasdiqlaydi" modeli amalga oshadi
        # degan xato xulosa chiqardi.
        #
        # `v_review_disagreement` dagi bilan BIR XIL chalkashlik
        # (§16.67): `reviewed` va `not pending` bir narsa emas.
        korilgan = db.scalar(
            "SELECT count(*) FROM tender_requirement "
            "WHERE company_id=%(c)s AND tender_id=%(t)s "
            "AND reviewed_by IS NOT NULL",
            {"c": cid, "t": row["tender_id"]}) or 0
        requirement.review_tugadi(row["tender_id"], cid, int(korilgan))
        # KO'RIK TUGADI -> NAVBAT SHU ZAHOTI QAYTA HISOBLANADI.
        # Oraliq tasdiqlarda emas: har talabda qayta baholash
        # `qualification.check` ni ko'rik tezligiga bog'lardi va
        # oxirgi natijadan boshqa hech narsa bermasdi.
        yonaltirish = _navbatni_yangila(row["tender_id"], cid)
    return {**row, "qolgan_kutayotgan": int(qolgan or 0),
            # NAVBATGA NIMA BO'LGANI JIM QOLMAYDI. Ko'rik hali
            # tugamagan bo'lsa `None` -- "hali baholanmadi".
            "yonaltirish": yonaltirish}


# ---------------------------------------------------------------------------
# MALAKA TEKSHIRUVI — deterministik, MODEL CHAQIRILMAYDI
#
# `ai-gonogo` DAN FARQI: u 11 mezonni PULLIK modelga nasr sifatida
# beradi va bitta tender ~$0.03 turadi. Bu esa `tender_requirement`
# (turlangan) bilan `company_profile` (turlangan) ni SQL da
# solishtiradi — o'lchandi: 200 tender 0.5 s, 2 ms/tender, 0 chaqiruv.
# ---------------------------------------------------------------------------
@app.get("/tenders/{tender_id}/qualification")
def tender_qualification(tender_id: int, request: Request):
    """Kompaniya shu tenderga malakalimi. Bepul va takrorlanadigan.

    Natija `is_sample` bayrog'ini OLIB YURADI: profil sinov
    qiymatlari bilan to'ldirilgan bo'lsa, undan statistik xulosa
    chiqarilmaydi.
    """
    from api import qualification
    cid = company_id_of(request)
    try:
        return qualification.check(tender_id, cid)
    except ValueError as e:
        raise xatolar.kodli(e, "REQUIREMENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# BROKERGA YO'NALTIRISH
#
# CHEGARA: `erp.*` ga YOZILMAYDI (auth_test.py qulflaydi). Navbat shu
# tomonda turadi, ERP esa `erp.v_tender_status` orqali o'z holatini
# aytadi.
# ---------------------------------------------------------------------------
@app.get("/requirements/coverage")
def requirements_coverage(request: Request):
    """Talab qayta ishlash qamrovi — TUSHUNTIRILADIGAN.

    UCH FOIZ ATAYLAB AJRATILGAN va ular BOSHQA savolga javob
    beradi:

      `ishlanganda_topildi_foiz` — ISHLANGAN tenderlarning qanchasida
                                   talab topilgan (SIFAT)
      `ishlangan_foiz`           — YAROQLILARNING qanchasi umuman
                                   ishlangan (TARIXIY o'tkazuvchanlik;
                                   maxrajda YOPIQ tenderlar ham bor)
      `ochiq_ishlangan_foiz`     — OCHIQ tenderlarning qanchasi
                                   ishlangan (OPERATSION: ulguryapmizmi)

    Sodda `talabi bor / hamma tender` metrikasi ularni ARALASHTIRADI
    va "talab yo'q" degan yolg'on xulosaga olib boradi. O'lchandi
    (2026-08-31): sifat 100.0, o'tkazuvchanlik 32.2 — past raqam
    ajratish SIFATI emas, ISHLANMAGANI.

    UCHINCHI FOIZ NEGA QO'SHILDI (2026-09-01, Q-1). Navbatdagi
    OCHIQ tenderlar ishlandi (627 ta, 4 sekund, bepul) va
    `ishlangan_foiz` atigi 32.2 -> 34.5 ga o'zgardi. Sabab
    o'lchandi: qolgan 2 365 tenderning HAMMASI YOPIQ. Ya'ni past
    raqam OPERATSION bo'shliq emas, TARIXIY yozuvlar edi —
    `ochiq_ishlangan_foiz` esa 100.0.

    `navbatda` MAXRAJGA KIRMAYDI: ular hali savol berilmagan
    tenderlar va ularni "talabsiz" deb sanash noma'lumni
    salbiy natijaga aylantirardi.

    `hisobga_olinmagan` NOL bo'lishi SHART — nol bo'lmasa
    tasnifdan tashqarida qolgan tender bor.
    """
    cid = company_id_of(request)
    if not db.scalar("SELECT to_regclass('public.v_requirement_qamrov') IS NOT NULL"):
        return {"tayyor": False,
                "sabab": "schema_patch_req_qamrov.sql qo'llanmagan"}
    umumiy = db.query_one(
        "SELECT * FROM v_requirement_qamrov WHERE company_id = %(c)s",
        {"c": cid}) or {}
    usul = db.query(
        "SELECT usul, yaroqli, urinildi, topildi, topilmadi, matn_yoq, xato "
        "  FROM v_requirement_qamrov_usul WHERE company_id = %(c)s "
        " ORDER BY usul", {"c": cid})
    return {"tayyor": True, "umumiy": umumiy, "usul": usul,
            # NAZORAT chaqiruvchiga ochiq beriladi — u jimgina
            # o'tib ketmasin.
            "yarashadi": (umumiy.get("hisobga_olinmagan") == 0)}


@app.get("/routing/agreement")
def routing_agreement(request: Request):
    """AI <-> INSON kelishuvi — halol maxraj bilan.

    UCH NARSA ATAYLAB AJRATILGAN:

      `kelishdi` / `bekor_qilindi`  — AI ANIQ da'vo qilgan (go/no_go)
                                       va inson ANIQ javob bergan
      `ai_qaror_yoq`               — AI `review` degan, ya'ni QAROR
                                       QILMAGAN. Bu MUVAFFAQIYATSIZLIK
                                       EMAS va kelishuv maxrajiga
                                       KIRMAYDI
      `kutildi`                    — inson `kutilsin` degan; na
                                       kelishuv, na bekor qilish

    Ilgari `v_routing_agreement` `review` ni 0 FOIZ deb ko'rsatardi
    (formula tuzilishiga ko'ra u yerda hech qachon moslik chiqmasdi)
    va bu ustun holat edi: 30 qarordan 25 tasi.

    `kelishuv_foiz` maxraj nol bo'lsa **null** qaytadi — nol emas.
    "O'lchanmadi" va "hech qachon kelishmadi" bir xil emas.

    Kelishuv inson KO'RGAN AI qarori bilan hisoblanadi
    (`ai_korilgan()`): AI fikrini keyin o'zgartirgani tarixiy
    haqiqatni qayta yozmasligi kerak.
    """
    cid = company_id_of(request)
    if not db.scalar("SELECT to_regclass('public.v_routing_kelishuv') IS NOT NULL"):
        return {"tayyor": False,
                "sabab": "schema_patch_routing_kelishuv.sql qo'llanmagan"}
    umumiy = db.query_one(
        "SELECT * FROM v_routing_kelishuv WHERE company_id = %(c)s", {"c": cid})
    kesim = db.query(
        "SELECT kesim, qiymat, inson_qarori, ai_qaror_yoq, kelishdi, "
        "       bekor_qilindi "
        "  FROM v_routing_kelishuv_kesim WHERE company_id = %(c)s "
        " ORDER BY kesim, inson_qarori DESC", {"c": cid})
    return {"tayyor": True, "umumiy": umumiy or {}, "kesim": kesim}


@app.get("/routing/queue")
def routing_queue(request: Request,
                  holat: Optional[str] = Query(None),
                  q: Optional[str] = Query(None),
                  qaror: Optional[str] = Query(None),
                  region: Optional[str] = Query(None),
                  eskirgan: bool = Query(False),
                  katalog: bool = Query(False),
                  limit: int = Query(100, ge=1, le=500)):
    """Brokerga ko'rsatiladigan navbat — FAQAT ochiq tenderlar.

    FILTR SERVERDA (2026-09-03). Mijoz tomonida filtrlash faqat
    olingan sahifaga tegardi: navbat 188, sahifa 100 — ya'ni
    qidirilgan tender ikkinchi yuzlikda bo'lsa "topilmadi" bo'lib
    ko'rinardi. Bu JIMGINA noto'g'ri javob.

    `jami` — mos kelganlarning TO'LIQ soni, qaytarilganlar emas.
    Interfeys kesilganini shundan biladi.
    """
    from api import routing
    cid = company_id_of(request)
    try:
        items, jami = routing.navbat(cid, holat=holat, limit=limit,
                                     q=q, qaror=qaror, region=region,
                                     eskirgan=eskirgan, katalog=katalog)
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    return {"items": items, "jami": jami, "korsatildi": len(items),
            "moslik": routing.moslik(cid)}


@app.post("/routing/refresh")
def routing_refresh(request: Request,
                    barchasi: bool = Query(False),
                    limit: int = Query(2000, ge=1, le=2000)):
    """Navbatni qayta baholaydi. MODEL CHAQIRILMAYDI.

    MUSBAT TASDIQ: nechta baholandi VA nechtasi navbatga tushdi —
    ikkalasi ham qaytariladi. "Xato chiqmadi" yetarli emas.
    """
    from api import routing
    return routing.yonaltir_hammasi(company_id_of(request),
                                    limit=limit, barchasi=barchasi)


@app.post("/routing/{routing_id}/open")
def routing_open(routing_id: int, request: Request,
                 broker: Optional[str] = Query(None)):
    """Broker ochdi — vaqt o'lchovi shu yerdan boshlanadi."""
    from api import routing
    row = routing.ochildi(routing_id, company_id_of(request), broker)
    if not row:
        # Yo'q, boshqa kompaniyaniki, yoki ALLAQACHON YOPILGAN.
        raise xatolar.Xato("RECORD_ALREADY_CLOSED")
    return row


class RoutingDecisionIn(BaseModel):
    #: 'olindi' | 'rad' | 'kutilsin'
    qaror: str
    izoh: Optional[str] = None
    # `broker` MAYDONI OLIB TASHLANDI. U qarorni KIM qo'yganini
    # MIJOZGA yozdirardi va uni hech narsa tekshirmasdi. Endi aktor
    # SERVERDA aniqlanadi (`X-Actor` sarlavhasi yoki ERP sessiyasi)
    # va `api/aktor.py` uni ro'yxatdan tekshiradi.

    # --- ERP GA TOPSHIRIQ (`api/topshiriq.py`) --------------------------
    # `olindi` qarori ERP da ISH KARTASIGA aylanadi. Quyidagilar —
    # o'sha kartaning boshlang'ich holati. Ular MIJOZDAN keladi va
    # bu to'g'ri: bular QAROR emas, ish taqsimoti (kimga, qachon,
    # qanchalik shoshilinch). Qarorning KIMLIGI esa avvalgidek
    # serverda aniqlanadi.
    #
    # `hodim_actor_id` — SHU IJARACHINING aktori bo'lishi shart
    # (tekshiriladi); ERP hodimiga xaritalanmagan bo'lsa ERP kartani
    # "Taqsimlanmagan" ga qo'yadi va menejerga xabar beradi.
    hodim_actor_id: Optional[int] = None
    ustuvorlik: str = "medium"
    muddat: Optional[date] = None


@app.post("/routing/{routing_id}/decision")
def routing_decision(routing_id: int, body: RoutingDecisionIn,
                     request: Request):
    """Broker qarori. AI qarori TEGILMAYDI — u dalil bo'lib qoladi.

    Ikkisi ALOHIDA ustunda: aralashtirilsa "model necha foizda haq
    edi" degan savolga javob qolmasdi.
    """
    from api import routing
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "tasdiq" if body.qaror == "olindi"
           else "rad" if body.qaror == "rad" else "korib_chiq")
    try:
        row = routing.qaror(routing_id, cid, body.qaror,
                            izoh=body.izoh, actor_id=k.actor_id,
                            ishonch=k.ishonch, broker_nomi=k.ism)
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    if not row:
        raise xatolar.Xato("RECORD_NOT_FOUND")
    # --- ERP GA TOPSHIRIQ ---------------------------------------------
    # `olindi` -> ERP da karta ochiladi; `rad`/`kutilsin` -> avval
    # berilgan topshiriq BEKOR qilinadi (ERP kartasi o'chmaydi,
    # `rejected` ga o'tadi). Ikkalasi ham `erp_rollar.md` §5 qoidasi.
    #
    # XATO YUTILMAYDI, LEKIN QARORNI HAM YIQITMAYDI: qaror allaqachon
    # yozilgan va uni orqaga qaytarish yomonroq bo'lardi. Shuning
    # uchun natija javobda ochiq qaytadi (`topshiriq` maydoni).
    topshiriq_natija: Optional[Dict[str, Any]] = None
    try:
        from api import topshiriq as _topshiriq
        if not _topshiriq.ready():
            topshiriq_natija = {"holat": "migratsiya_yoq",
                                "patch": "schema_patch_topshiriq.sql"}
        elif body.qaror == "olindi":
            if body.hodim_actor_id is not None:
                from api import aktor as _aktor
                if not _aktor.bitta(cid, body.hodim_actor_id):
                    raise xatolar.Xato("RECORD_NOT_FOUND",
                                       {"maydon": "hodim_actor_id"})
            t = _topshiriq.yarat(
                routing_id, cid, int(row["tender_id"]),
                hodim_actor_id=body.hodim_actor_id,
                yonaltirgan_actor_id=k.actor_id,
                ishonch=k.ishonch, ustuvorlik=body.ustuvorlik,
                izoh=body.izoh, muddat=body.muddat)
            topshiriq_natija = {"holat": "yaratildi", "id": t["id"],
                                "hodim_actor_id": t["hodim_actor_id"]}
        else:
            b = _topshiriq.bekor(routing_id, cid)
            topshiriq_natija = {"holat": "bekor_qilindi", "id": b["id"]} if b                 else {"holat": "topshiriq_yoq"}
    except xatolar.Xato:
        raise
    except Exception as e:                      # noqa: BLE001
        topshiriq_natija = {"holat": "xato", "xato": f"{type(e).__name__}: {e}"[:300]}

    audit_yoz(k, request, amal=f"yonaltirish_{body.qaror}",
              entity="tender_routing", entity_id=routing_id,
              keyin={"inson_qaror": row.get("inson_qaror"),
                     "ai_qaror": row.get("ai_qaror"),
                     "tender_id": row.get("tender_id"),
                     "topshiriq": topshiriq_natija},
              izoh=body.izoh)
    return {**row, "topshiriq": topshiriq_natija}


@app.get("/routing/{routing_id}/topshiriq")
def routing_topshiriq(routing_id: int, request: Request):
    """Shu qaror bo'yicha ERP ga berilgan topshiriq (bo'lsa).

    Navbat ekrani "berildimi va kimga" degan savolga javob berishi
    kerak: qaror yozilgani bilan ish boshlangani bir xil emas."""
    from api import topshiriq as _topshiriq
    cid = company_id_of(request)
    if not _topshiriq.ready():
        return {"bor": False, "sabab": "schema_patch_topshiriq.sql qo'llanmagan"}
    t = _topshiriq.bitta(routing_id, cid)
    return {"bor": bool(t), "topshiriq": t}


class ReviewBulkIn(BaseModel):
    """Ommaviy INSON qarori. Tuzatish yo'q — har qiymat alohida."""
    status: Literal["approved", "rejected"]


@app.post("/tenders/{tender_id}/requirements/review-all")
def requirements_review_all(tender_id: int, body: ReviewBulkIn,
                            request: Request):
    """Tenderning BARCHA kutayotgan talablarini bir holatga o'tkazadi.

    Ommaviy TUZATISH yo'q: har qiymat alohida yoziladi.
    """
    from api import requirement
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "tasdiq" if body.status == "approved" else "rad")
    try:
        n = requirement.review_bulk(tender_id, cid, body.status, by=cid,
                                    actor_id=k.actor_id, ishonch=k.ishonch)
        # OMMAVIY AMAL BITTA audit qatori bilan yoziladi: `entity_id`
        # — TENDER, chunki qaror aynan shu darajada qabul qilingan.
        # Har talab uchun alohida qator yozish "har birini ko'rdim"
        # degan yolg'on taassurot berardi.
        audit_yoz(k, request, amal=f"talab_ommaviy_{body.status}",
                  entity="tender", entity_id=tender_id,
                  keyin={"tegdi": n, "status": body.status},
                  izoh=f"{n} ta talab bir amalda")
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    yonaltirish: Optional[Dict[str, Any]] = None
    if n:
        requirement.review_tugadi(tender_id, cid, n)
        # OMMAVIY AMAL BUTUN TENDERNI YOPADI (`pending_review`
        # qolmaydi), ya'ni bu ham KO'RIK TUGAGAN nuqta.
        yonaltirish = _navbatni_yangila(tender_id, cid)
    return {"tender_id": tender_id, "ozgardi": n, "status": body.status,
            "yonaltirish": yonaltirish}


@app.post("/requirements/pilot")
def requirements_pilot_create(request: Request):
    """Pilot to'plamini quradi: 30 tender (muddat + tasodif + summa).

    NAMUNA ARALASH: navbat muddat bo'yicha saralangan va bu ish
    jarayoni uchun to'g'ri, lekin NAMUNA uchun qiyshiq — tez
    yopiladigan tenderlar ma'lum turdagi bo'lishi mumkin.

    Birinchi 10 tasi YOPIQ rejimda: model javobi yashiriladi, inson
    avval o'zi hujjatdan o'qiydi. Bu ANCHORING ga qarshi va
    kelishmovchilik darajasini o'lchash imkonini beradi.
    """
    from api import requirement
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    # Pilot QURISH — namunani belgilaydi, ya'ni keyingi barcha
    # o'lchovlarning maxrajini belgilaydi. Shuning uchun `sozlama`.
    ruxsat(k, "sozlama")
    natija = requirement.pilot_yarat(
        cid, yaratgan=(k.login or k.ishonch))
    if not natija.get("mavjud"):
        audit_yoz(k, request, amal="pilot_yaratildi", entity="review_pilot",
                  entity_id=int(natija.get("avlod") or 0), keyin=natija)
    return natija


@app.post("/requirements/pilot/{avlod}/arxiv")
def requirements_pilot_arxiv(avlod: int, request: Request):
    """Pilot avlodini ARXIVLAYDI — qatorlar O'CHIRILMAYDI.

    Ungacha eskirgan pilotni yopishning yagona yo'li `review_pilot`
    dan qatorlarni SQL bilan o'chirish edi — ya'ni namunani va
    tarixiy dalilni yo'qotish. Endi arxivlash FAKT sifatida
    yoziladi, qatorlar joyida qoladi va yangi avlod ochiladi.
    """
    from api import requirement
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "sozlama")
    try:
        natija = requirement.pilot_arxivla(cid, avlod,
                                           kim=(k.login or k.ishonch))
    except Exception as e:                                    # noqa: BLE001
        raise xatolar.kodli(e, "NOT_FOUND")
    audit_yoz(k, request, amal="pilot_arxivlandi", entity="review_pilot",
              entity_id=avlod, keyin=natija)
    return natija


@app.get("/requirements/pilot")
def requirements_pilot_list(request: Request):
    """Pilot to'plami — holati va o'lchangan vaqti bilan."""
    from api import requirement
    cid = company_id_of(request)
    items = requirement.pilot_royxat(cid)
    return {
        "items": items,
        "tugagan": sum(1 for x in items if x["finished_at"]),
        "jami": len(items),
        "kelishmovchilik": db.query("""
            SELECT ishonch_darajasi, jami, rad_etilgan, tuzatilgan,
                   tasdiqlangan, kelishmovchilik_foiz
            FROM v_review_disagreement WHERE company_id = %(c)s""",
            {"c": cid}),
    }


@app.get("/requirements/speed")
def requirements_speed(request: Request):
    """Ko'rib chiqish tezligi — pilot natijasi.

    "Har talabni inson tasdiqlaydi" modeli ishlaydimi degan savolning
    javobi shu raqamda: mediana vaqt x navbatdagi tenderlar soni.
    """
    from api import requirement
    return requirement.review_speed(company_id_of(request))


# ---------------------------------------------------------------------------
# BILDIRISHNOMA (TZ P0-10) — "mosligi yuqori yangi tender chiqdi"
#
# IKKI KANAL: email (SMTP) va Telegram (Bot API). Xabarni `notify_new.py`
# ETL dan keyin yuboradi; bu yerdagi endpointlar faqat SOZLAMALARNI
# boshqaradi va sinov xabarini yuboradi.
# ---------------------------------------------------------------------------
@app.get("/notify/settings")
def get_notify_settings(request: Request):
    """`smtp_password_set` / `telegram_token_set` — sirlar .env da bormi
    (sirlarning O'ZI hech qachon qaytmaydi)."""
    return notify.get_settings(company_id_of(request))


@app.put("/notify/settings")
def put_notify_settings(s: NotifySettingsIn, request: Request):
    """Sozlamalarni saqlaydi. QISMAN yuborish mumkin — yuborilmagan maydon
    o'zgarmaydi (`exclude_unset`)."""
    try:
        return notify.save_settings(s.model_dump(exclude_unset=True),
                                    company_id_of(request))
    except notify.NotifyError as e:
        raise xatolar.kodli(e, "NOTIFY_CONFIG_INVALID")


@app.post("/notify/test")
def notify_test(request: Request):
    """Sinov xabari. `notify_sent` ga YOZMAYDI — haqiqiy bildirishnomalarga
    ta'sir qilmaydi."""
    try:
        return notify.send_test(company_id=company_id_of(request))
    except notify.NotifyError as e:
        # Sozlama/SMTP xatosi — foydalanuvchi tuzatishi mumkin -> 400
        raise xatolar.kodli(e, "NOTIFY_CONFIG_INVALID")


class NotifySendIn(BaseModel):
    """Tashqi tizim (ERP) yuboradigan xabar.

    QABUL QILUVCHI YO'Q: manzil qabul qilinmaydi va xabar FAQAT shu
    o'rnatmaning sozlangan manzillariga ketadi (bildirishnoma sozlamasidagi
    email va yoqilgan Telegram obunachilari). Shu tufayli endpoint ochiq
    relay bo'la olmaydi."""
    subject: str
    text: str
    html: Optional[str] = None
    channels: List[str] = ["telegram", "email"]


@app.post("/notify/send")
def notify_send(body: NotifySendIn, request: Request):
    """XABAR YUBORISH XIZMAT SIFATIDA.

    NEGA KERAK: ERP alohida loyiha, lekin transport (SMTP rekvizitlari va
    Telegram bot tokeni) SHU o'rnatmada. Sirlarni ikkinchi loyihaga
    ko'chirish o'rniga ERP tayyor matnni yuboradi va u shu yerdan ketadi —
    token bitta joyda qoladi, obunachilar ro'yxati ham.

    Kanal ishlamasa (masalan SMTP sozlanmagan) — xato butun so'rovni
    yiqitmaydi: natijada har kanal alohida hisobot beradi."""
    out: Dict[str, Any] = {"email": None, "telegram": None}
    cid = company_id_of(request)
    st = notify.get_settings(cid)

    if "email" in body.channels:
        try:
            # KOMPANIYA UZATILADI: `recipient()` busiz
            # `sole_company_id()` ga tushardi va ikkinchi faol
            # hisob bo'lsa xato berardi.
            to = notify.recipient(st, cid)
            notify.send(st, to, body.subject, body.text,
                        body.html or f"<pre>{body.text}</pre>")
            out["email"] = {"sent": True, "to": to}
        except notify.NotifyError as e:
            out["email"] = {"sent": False, "error": str(e)}

    if "telegram" in body.channels:
        chats, errors = [], []
        try:
            for sub in notify.require_subscribers(cid):
                try:
                    telegram.send_message(sub["chat_id"], body.text)
                    chats.append(sub["chat_id"])
                except Exception as e:          # noqa: BLE001
                    errors.append({"chat_id": sub["chat_id"], "error": str(e)})
            out["telegram"] = {"sent": bool(chats), "chats": chats, "errors": errors}
        except notify.NotifyError as e:
            out["telegram"] = {"sent": False, "chats": [], "error": str(e)}

    ok = any(c and c.get("sent") for c in out.values())
    return {"ok": ok, **out}


@app.post("/notify/run")
def notify_run(request: Request,
               dry_run: bool = Query(True, description="Yubormasdan ko'rish.")):
    """Bildirishnoma tsiklini qo'lda yurgizadi (standart: dry-run)."""
    try:
        res = notify.run(dry_run=dry_run, company_id=company_id_of(request))
    except notify.NotifyError as e:
        raise xatolar.kodli(e, "NOTIFY_CONFIG_INVALID")
    # Xabar tanasi (text/html) javobda kerak emas — faqat xulosa
    return {k: v for k, v in res.items() if k not in ("text", "html")}


# --- Telegram kanali --------------------------------------------------------
# Bot tokeni FAQAT .env da (TELEGRAM_BOT_TOKEN) — bu endpointlar uni HECH
# QACHON qaytarmaydi, faqat "sozlanganmi" belgisi va bot username'i.
@app.get("/notify/telegram/bot")
def telegram_bot_info():
    """Bot haqida (username) — foydalanuvchi QAYSI botga /start yozishini
    bilsin. Token yo'q/noto'g'ri bo'lsa 400 va ANIQ matn."""
    if not telegram.token_set():
        raise xatolar.Xato("TELEGRAM_TOKEN_MISSING")
    try:
        return telegram.get_me()
    except telegram.TelegramError as e:
        raise xatolar.kodli(e, "TELEGRAM_API_ERROR")


@app.get("/notify/telegram/subscribers")
def telegram_subscribers(request: Request):
    """Obunachilar ro'yxati — botga /start bosgan har bir suhbat.

    BO'SH ro'yxat XATO EMAS: shunchaki hali hech kim /start bosmagan.
    """
    return {"subscribers": notify.subscribers(company_id_of(request)),
            "ready": notify.subscribers_ready()}


@app.post("/notify/telegram/link")
def telegram_link_create(request: Request):
    """Telegramni ulash uchun BIR MARTALIK havola yaratadi.

    Foydalanuvchi shu havolani bosadi -> Telegram botni ochadi -> "Start"
    bosiladi -> bot `/start <token>` xabarini oladi. Faqat SHU token bilan
    kelgan suhbat ulanadi: tokensiz /start bosgan begona odam obunachi
    BO'LMAYDI.
    """
    try:
        return notify.create_link(company_id_of(request))
    except notify.NotifyError as e:
        raise xatolar.kodli(e, "NOTIFY_CONFIG_INVALID")


@app.get("/notify/telegram/link/{token}")
def telegram_link_status(token: str, request: Request):
    """Havola ishlatildimi. Interfeys havolani ochgach shuni qisqa oraliqda
    so'rab turadi va ulanish yakunlanishi bilan ro'yxatni yangilaydi.

    So'rov `consume_links()` ni ham chaqiradi — aks holda ulanish faqat
    keyingi bildirishnoma tsiklida qayd etilardi va foydalanuvchi
    "ishlamadi" deb o'ylardi.
    """
    try:
        notify.consume_links()
    except notify.NotifyError:
        pass          # holatni baribir qaytaramiz (quyida `found: false` bo'ladi)
    company_id = company_id_of(request)
    return {**notify.link_status(token, company_id),
            "subscribers": notify.subscribers(company_id)}


class SubscriberIn(BaseModel):
    """Obunachini yoqish/o'chirish. Bu YAGONA tahrirlanadigan maydon —
    qolgani (nom, tur) Telegramdan keladi."""
    enabled: bool


@app.put("/notify/telegram/subscribers/{chat_id}")
def telegram_subscriber_update(chat_id: str, body: SubscriberIn, request: Request):
    """Obunachiga xabar ketishini yoqadi/o'chiradi."""
    company_id = company_id_of(request)
    row = db.execute_returning(notify.SUB_SET_ENABLED_SQL,
                               {"chat_id": chat_id, "enabled": body.enabled,
                                "company_id": company_id})
    if not row:
        raise xatolar.Xato("SUBSCRIBER_NOT_FOUND")
    # KOMPANIYA UZATILADI: so'rov `company_id` bilan chegaralangan,
    # lekin QAYTARILADIGAN ro'yxat kompaniyasiz olinardi va
    # `sole_company_id()` ga tushardi.
    return {"subscribers": notify.subscribers(company_id)}


@app.delete("/notify/telegram/subscribers/{chat_id}")
def telegram_subscriber_delete(chat_id: str, request: Request):
    """Obunachini ro'yxatdan o'chiradi.

    DIQQAT: u botga QAYTA /start yozsa yana qo'shiladi. Butunlay to'xtatish
    uchun `enabled=false` qo'ying — o'chirish faqat ro'yxatni tozalaydi.
    """
    company_id = company_id_of(request)
    row = db.execute_returning(notify.SUB_DELETE_SQL,
                               {"chat_id": chat_id,
                                "company_id": company_id})
    if not row:
        raise xatolar.Xato("SUBSCRIBER_NOT_FOUND")
    # KOMPANIYA UZATILADI: so'rov `company_id` bilan chegaralangan,
    # lekin QAYTARILADIGAN ro'yxat kompaniyasiz olinardi va
    # `sole_company_id()` ga tushardi.
    return {"subscribers": notify.subscribers(company_id)}


@app.post("/notify/telegram/test")
def telegram_test(request: Request, chat_id: Optional[str] = Query(
        None, description="Faqat shu obunachiga. Bo'sh — barchasiga.")):
    """Telegram sinov xabari. `notify_sent` ga YOZMAYDI va `telegram_enabled`
    ni talab qilmaydi — yoqishdan OLDIN tekshirish uchun.

    Xabar PLATFORMA TILIDA ketadi (sozlamadagi `lang`) — haqiqiy
    bildirishnoma bilan bir xil.
    """
    try:
        return notify.send_telegram_test(chat_id=chat_id,
                                         company_id=company_id_of(request))
    except notify.NotifyError as e:
        raise xatolar.kodli(e, "NOTIFY_CONFIG_INVALID")


@app.get("/products")
def products(
    q: Optional[str] = Query(None, description="Nom bo'yicha filtr (lotin/kirill farqsiz)."),
    kind: Optional[str] = Query(None, description="'product' — faqat mahsulot, 'service' — faqat xizmat, bo'sh — hammasi."),
    status: Optional[str] = Query("open", description="Qaysi status bo'yicha sanash. Barchasi uchun bo'sh."),
    limit: int = Query(30, ge=1, le=200),
):
    """Mahsulot/xizmat filtri uchun takliflar — tenderlarда uchraydigan nomlar.

    Alohida lug'at QURILMAGAN: `tender_good.name` ikkala manbada ham to'liq
    to'ldirilgan va yaxshi takrorlanadi, shuning uchun ro'yxat to'g'ridan-to'g'ri
    ma'lumotdan chastota bo'yicha olinadi. Qidiruv alifbodan qat'i nazar
    ishlaydi (api/translit.py).

    Mahsulot/xizmat bo'linishi manbada berilmagan — u OKED bo'limi, o'lchov
    birligi va nomdan aniqlanadi (queries.SERVICE_PREDICATE).
    """
    cond, params = queries.build_column_search("g.name", q) if q else ("", {})
    rows = db.query(queries.products_sql(cond, kind=kind or ""),
                    {**params, "status": status or "", "limit": limit})
    return [{"name": r["name"], "tender_count": r["tender_count"]} for r in rows]


@app.get("/categories")
def categories():
    """Kategoriya daraxti (2 daraja) + har birida ochiq tenderlar soni.
    Parent tugunда `children` massivi; son ichkilarни ham qamrab oladi."""
    rows = db.query(queries.CATEGORIES_SQL)
    by_code = {r["code"]: {"code": r["code"], "name": r["name_uz"],
                           "count": r["cnt"], "children": []} for r in rows}
    tree = []
    for r in rows:
        node = by_code[r["code"]]
        if r["parent"] and r["parent"] in by_code:
            by_code[r["parent"]]["children"].append(node)
        else:
            tree.append(node)
    return tree


# ---------------------------------------------------------------------------
# Aqlli moslashtirish (deterministik — kelajakda AI bilan almashtiriladi)
# ---------------------------------------------------------------------------
def _shape_profile(r: Optional[dict]) -> Optional[dict]:
    if not r:
        return None
    return {
        "id": r["id"],
        "contact_name": r.get("contact_name"),
        "email": r.get("email"),
        "phone": r.get("phone"),
        "position": r.get("position"),
        "name": r["name"],
        "keywords": r["keywords"] or [],
        "regions": r["regions"] or [],
        "currency": r["currency"],
        "min_cost": _num(r["min_cost"]),
        "max_cost": _num(r["max_cost"]),
        # Salohiyat maydonlari (Go/No-Go). Eski profil qatorlarida bo'lmasligi
        # mumkin, shuning uchun .get() bilan o'qiladi.
        "about": r.get("about"),
        "certificates": r.get("certificates") or [],
        "clearances": r.get("clearances") or [],
        "experience_years": r.get("experience_years"),
        "max_contract_value": _num(r.get("max_contract_value")),
        "max_contract_currency": r.get("max_contract_currency"),
        "employees": r.get("employees"),
        "capacity_note": r.get("capacity_note"),
        "lead_time_days": r.get("lead_time_days"),
        "min_margin_percent": _num(r.get("min_margin_percent")),
        "constraints_note": r.get("constraints_note"),
        "updated_at": _iso(r["updated_at"]),
    }


# ---------------------------------------------------------------------------
# SAQLANGAN QIDIRUVLAR (A bosqich)
# ---------------------------------------------------------------------------
def _shape_search(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"],
        "keywords": r["keywords"] or [],
        "categories": r["categories"] or [],
        "regions": r["regions"] or [],
        "currency": r["currency"],
        "min_cost": _num(r["min_cost"]), "max_cost": _num(r["max_cost"]),
        "notify": r["notify"],
        "last_seen_at": _iso(r["last_seen_at"]),
        "created_at": _iso(r["created_at"]),
    }


def _search_to_profile(r: dict) -> dict:
    """Saqlangan qidiruvni matching profiliga o'giradi (skorlash uchun)."""
    return {"keywords": r["keywords"] or [], "regions": r["regions"] or [],
            "currency": r["currency"], "min_cost": _num(r["min_cost"]),
            "max_cost": _num(r["max_cost"])}


def _count_matches(candidates: list, prof: dict) -> int:
    """Qidiruvga mos ochiq tenderlar soni. Kalit so'z bo'lsa — kamida bittasi
    mos kelganlar; bo'lmasa — hudud/byudjet biror ball berganlar."""
    has_kw = bool(prof.get("keywords"))
    n = 0
    for c in candidates:
        m = matching.score_tender(c, prof)
        if (m["matched_keywords"] if has_kw else m["score"] > 0):
            n += 1
    return n


@app.get("/searches")
def list_searches(request: Request):
    """Barcha saqlangan qidiruvlar + har birida mos ochiq tenderlar soni."""
    rows = db.query(queries.SEARCHES_LIST_SQL,
                    {"company_id": company_id_of(request)})
    if not rows:
        return []
    # Nomzodlarni BIR MARTA olamiz, keyin har qidiruv bo'yicha skorlaymiz
    where, params = queries.build_tender_filters(status="open")
    cand = db.query(queries.match_candidates_sql(where, cap=MATCH_CAP), params)
    return [{**_shape_search(r),
             "match_count": _count_matches(cand, _search_to_profile(r))}
            for r in rows]


@app.post("/searches", status_code=201)
def create_search(s: SavedSearchIn, request: Request):
    row = db.execute_returning(queries.SEARCH_INSERT_SQL,
                               {**s.model_dump(),
                                "company_id": company_id_of(request)})
    return _shape_search(row)


@app.put("/searches/{search_id}")
def update_search(search_id: int, s: SavedSearchPatchIn, request: Request):
    """QISMAN yangilash: YUBORILMAGAN maydon joriy qiymatida qoladi.

    Avval joriy qator o'qiladi (`SEARCH_GET_SQL`) — u ijarachi
    bilan cheklangan, ya'ni boshqa kompaniyaning qidiruvi bu
    yerdan ham ko'rinmaydi.
    """
    cid = company_id_of(request)
    joriy = db.query_one(queries.SEARCH_GET_SQL,
                         {"id": search_id, "company_id": cid})
    if not joriy:
        raise xatolar.Xato("SEARCH_NOT_FOUND")
    berilgan = s.model_dump(exclude_unset=True)
    params = {k: berilgan.get(k, joriy[k])
              for k in ("name", "keywords", "categories", "regions",
                        "currency", "min_cost", "max_cost", "notify")}
    # Bo'sh nom yon panelda ajratib bo'lmaydigan yozuv beradi.
    if not (params["name"] or "").strip():
        raise xatolar.Xato("FIELD_REQUIRED", {"maydon": "name"})
    row = db.execute_returning(queries.SEARCH_UPDATE_SQL,
                               {**params, "id": search_id, "company_id": cid})
    if not row:
        raise xatolar.Xato("SEARCH_NOT_FOUND")
    return _shape_search(row)


@app.delete("/searches/{search_id}", status_code=204)
def delete_search(search_id: int, request: Request):
    row = db.execute_returning(queries.SEARCH_DELETE_SQL,
                               {"id": search_id,
                                "company_id": company_id_of(request)})
    if not row:
        raise xatolar.Xato("SEARCH_NOT_FOUND")
    return None


# ---------------------------------------------------------------------------
# MAHSULOT KATALOGI (REJA.md P0-4/5) — mijoz sotadigan mahsulot/xizmatlar
# ---------------------------------------------------------------------------
def _auto_classify_catalog(company_id: int, product_id: int, *,
                           force: bool = False) -> None:
    """Klassifikatsiya xatosi mahsulotning o'zini saqlashga xalaqit bermasin."""
    try:
        catalog_auto.classify_product(company_id, product_id, force=force)
    except Exception:  # noqa: BLE001 - ixtiyoriy boyitish, CRUD ishlashi shart
        _log.exception("catalog auto-classification failed: product=%s", product_id)


def _shape_product(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"],
        "category_code": r["category_code"], "keywords": r["keywords"] or [],
        "unit": r["unit"], "price": _num(r["price"]), "currency": r["currency"],
        "notify": r["notify"], "created_at": _iso(r["created_at"]),
        # --- P0-4/P0-6: ombor qoldig'i ---
        "stock_qty": _num(r.get("stock_qty")),
        "stock_unit": r.get("stock_unit"),
        "stock_updated_at": _iso(r.get("stock_updated_at")),
        # ERP ombori yoqilganda: `stock_qty` = MAVJUD (qoldiq - rezerv),
        # quyidagi ikkitasi esa tushuntirish uchun ("10 bor, 8 band").
        # ERP yo'q bo'lsa ular `None` va interfeys ularni ko'rsatmaydi.
        "stock_physical": _num(r.get("stock_physical")),
        "stock_reserved": _num(r.get("stock_reserved")),
        "cost_price": _num(r.get("cost_price")),
    }


def _pnum(v):
    """NUMERIC -> float (psycopg2 Decimal qaytaradi, JSON uni bilmaydi)."""
    return None if v is None else float(v)


def _shape_pricing_settings(r: Optional[dict]) -> Optional[dict]:
    if not r:
        return None
    return {
        "markup_percent": _pnum(r["markup_percent"]),
        "risk_reserve_percent": _pnum(r["risk_reserve_percent"]),
        "risk_reserve_fixed": _pnum(r["risk_reserve_fixed"]),
        "logistics_percent": _pnum(r["logistics_percent"]),
        "logistics_fixed": _pnum(r["logistics_fixed"]),
        "vat_percent": _pnum(r["vat_percent"]),
        "currency": r["currency"],
        "updated_at": _iso(r["updated_at"]),
    }


def _shape_tender_pricing(r: Optional[dict]) -> Optional[dict]:
    if not r:
        return None
    return {
        "tender_id": r["tender_id"],
        "inputs": r["inputs"],
        "result": r["result"],
        "manual_price": _pnum(r["manual_price"]),
        "currency": r["currency"],
        "note": r["note"],
        "updated_at": _iso(r["updated_at"]),
    }


# Nega hujjat matni o'qilmadi — foydalanuvchiga tushunarli sabab.
# TZ P0-2: 'ok' dan boshqa HAR QANDAY status "qo'lda tekshirish talab etiladi"
# toifasiga kiradi, lekin SABABI turlicha va keyingi qadam ham turlicha.
_DOC_TEXT_REASON = {
    "unreadable":      "Matn chiqmadi — skan qilingan yoki rasm ko'rinishidagi hujjat",
    "unsupported":     "Format qo'llab-quvvatlanmaydi (arxiv yoki eski binar fayl)",
    "too_large":       "Fayl juda katta — avtomatik o'qilmadi",
    "download_failed": "Manbadan yuklab olinmadi",
    "pending":         "Hali qayta ishlanmagan",
}


#: Qoidaning O'ZI `api/matching.py` da — uni `etl_doc_text.py --catalog` ham
#: ishlatadi (hujjat qamrovi). Ikki nusxa bo'lmasligi uchun bu yerda faqat
#: taxallus qoldi (reja_ai_chat.md §15.3.1).
_product_matches = matching.product_matches


def _catalog_candidates(region=None, currency=None, products=None):
    """Ochiq nomzod tenderlar (katalog moslik uchun bir marta olinadi)."""
    where, params = queries.build_tender_filters(
        status="open", region=region, currency=currency, products=products)
    return db.query(queries.match_candidates_sql(where, cap=MATCH_CAP), params)


@app.get("/catalog")
def list_catalog(request: Request):
    """Katalog mahsulotlari.

    Kichik katalogda har bir mahsulot uchun mos tenderlar soni ham qaytadi.
    Katta katalogda bu qimmat hisob ro'yxat yuklanishini to'smaydi:
    `match_count=null`, `match_count_deferred=true` qaytariladi.
    """
    prods = db.query(queries.CATALOG_LIST_SQL,
                     {"company_id": company_id_of(request)})
    if not prods:
        return []
    # QOLDIQNING EGASI — ERP (5B-1). Ro'yxatdagi `stock_qty` ERP jurnalidan
    # hisoblangan qoldiq bilan almashtiriladi; ERP o'rnatilmagan bo'lsa
    # Excel importidan qolgan surat qoladi. `api/erp_stock.py`.
    stock_source = erp_stock.apply_to_products(prods)
    deferred = len(prods) > CATALOG_INLINE_MATCH_LIMIT
    cand = [] if deferred else _catalog_candidates()
    out = []
    for p in prods:
        cnt = None if deferred else sum(
            1 for c in cand if _product_matches(c, p, allow_text=False))
        # Raqam qayerdan kelgani har qatorда ko'rinadi: interfeys "ombor
        # jurnalidan" yoki "importdan" deb ochiq aytadi.
        out.append({**_shape_product(p), "match_count": cnt,
                    "match_count_deferred": deferred,
                    "stock_source": stock_source})
    return out


@app.post("/catalog", status_code=201)
def create_product(p: CatalogItemIn, request: Request):
    cid = company_id_of(request)
    row = db.execute_returning(queries.CATALOG_INSERT_SQL,
                               {**p.model_dump(), "company_id": cid})
    # Klassifikatsiya foydalanuvchiga ko'rinmaydi. Dalil yetarli bo'lmasa
    # mahsulot saqlanadi, lekin taxminiy kod bilan ro'yxat ifloslanmaydi.
    _auto_classify_catalog(cid, row["id"])
    return _shape_product(row)


@app.put("/catalog/{product_id}")
def update_product(product_id: int, p: CatalogItemIn, request: Request):
    # `company_id` WHERE bandida ham bor: begona id ni taxmin qilib
    # tahrirlash mumkin emas — javob 404 bo'ladi (IDOR himoyasi).
    cid = company_id_of(request)
    row = db.execute_returning(queries.CATALOG_UPDATE_SQL,
                               {**p.model_dump(), "id": product_id,
                                "company_id": cid})
    if not row:
        raise xatolar.Xato("PRODUCT_NOT_FOUND")
    _auto_classify_catalog(cid, product_id, force=True)
    return _shape_product(row)


@app.delete("/catalog/{product_id}", status_code=204)
def delete_product(product_id: int, request: Request):
    row = db.execute_returning(queries.CATALOG_DELETE_SQL,
                               {"id": product_id,
                                "company_id": company_id_of(request)})
    if not row:
        raise xatolar.Xato("PRODUCT_NOT_FOUND")
    return None


@app.post("/catalog/match")
def catalog_match(body: CatalogMatchIn, request: Request):
    """Katalogga kod bo'yicha mos ochiq tenderlar, lot dalili bilan.

    Matn mosligi standartda o'chiq; u faqat `include_probable=true` bo'lsa
    alohida taxminiy signal sifatida qo'shiladi.
    """
    cid = company_id_of(request)
    if body.product_id is not None:
        # ID har doim kompaniya bilan birga tekshiriladi (IDOR himoyasi).
        p = db.query_one(queries.CATALOG_GET_SQL,
                         {"company_id": cid, "product_id": body.product_id})
        if not p:
            raise xatolar.Xato("PRODUCT_NOT_FOUND")
        # Eski keng kod bo'lsa, lotlar tarixidagi kuchli dalil asosida aniq
        # 8-belgili sinfga fon jarayonisiz, shu so'rovning o'zida toraytiramiz.
        _auto_classify_catalog(cid, body.product_id)
        p = db.query_one(queries.CATALOG_GET_SQL,
                         {"company_id": cid, "product_id": body.product_id})
        prods = [p]
    else:
        prods = db.query(queries.CATALOG_LIST_SQL, {"company_id": cid})
    if not prods:
        return {"total": 0, "limit": body.limit, "offset": body.offset,
                "items": [], "holat": kodlash.holat(cid),
                "atama_kesildi": 0,
                # SHAKL BIR XIL BO'LSIN: interfeys `hudud` kalitini
                # HAR javobda kutadi. Yo'q bo'lsa u "belgilanmagan"
                # bilan "tashqarida yo'q" ni ajrata olmasdi.
                "hudud": {"regions": [], "tashqari": 0, "jami": 0}}
    product_ids = [p["id"] for p in prods]

    # PROFIL HUDUDLARI — bir marta o'qiladi, har tender uchun emas.
    # Bo'sh bo'lsa cheklov yo'q va hech narsa belgilanmaydi
    # (`sf.regionsHint`: "Bo'sh — butun respublika").
    #
    # Import MAHALLIY — `tender_qualification` dagi bilan ayni uslub.
    from api import qualification
    profil_regions = (db.query_one(qualification.SQL_PROFIL, {"c": cid})
                      or {}).get("regions") or []

    # ------------------------------------------------------------------
    # SOLISHTIRISH SQL DA BAJARILADI, Python siklida EMAS.
    #
    # O'LCHANGAN SABAB (1797 qatorli real katalog, 782 ochiq tender):
    #     Python sikli  1797 x 782 = 1.4 mln chaqiruv  ->  ~29 DAQIQA
    # Brauzer ancha oldin uziladi va foydalanuvchi BO'SH RO'YXAT ko'radi.
    # U buni "mos tender yo'q" deb o'qiydi, aslida so'rov TUGAMAGAN —
    # ya'ni salbiy shartdan olingan xulosa. Aynan shu holat kuzatildi.
    # ------------------------------------------------------------------

    # --- 1. KOD yo'li (tasdiqlangan tasniflagich) ---
    # CHEGARA `kodlash.MOSLIK_LIMIT` DAN. Navbat filtrlari ham shuni
    # ishlatadi (`kodlash.mos_tender_idlari`) — ikki joyda ikki xil
    # raqam bo'lsa "Sizga mos" da ko'ringan tender filtrda chiqmasdi.
    kod_rows = kodlash.moslik(cid, only_open=True,
                              limit=kodlash.MOSLIK_LIMIT,
                              product_ids=product_ids)
    poz = kodlash.pozitsiya_moslik(
        cid, [r["tender_id"] for r in kod_rows], product_ids=product_ids)
    kod_ids = {r["tender_id"] for r in kod_rows}

    # --- 2. MATN yo'li — FAQAT kodsiz mahsulotlar uchun ---
    # `catalog_terms` kodi BOR mahsulotni o'zi tashlaydi — yagona qoida.
    juft, kesilgan = (queries.catalog_terms(prods)
                      if body.include_probable else ([], 0))
    terms = [t for t, _nom in juft]
    matn_poz: Dict[int, List[str]] = {}
    tsql, tpar = queries.build_catalog_text_match(terms)
    if tsql:
        for r in db.query(tsql, tpar):
            matn_poz.setdefault(r["tender_id"], []).append(r["pozitsiya"])

    ids = sorted(kod_ids | set(matn_poz))
    if not ids:
        # BO'SH NATIJANING SABABI AYTILADI. "Moslik yo'q" va "katalog
        # kodlanmagan" butunlay boshqa holatlar va keyingi qadam ham
        # boshqa.
        return {"total": 0, "limit": body.limit, "offset": body.offset,
                "items": [], "holat": kodlash.holat(cid),
                "atama_kesildi": kesilgan,
                "hudud": {"regions": profil_regions, "tashqari": 0,
                          "jami": 0}}

    # Filtrlar (hudud/valyuta/mahsulot) SHU YERDA qo'llanadi — nomzodlar
    # allaqachon id bo'yicha qisqargan, ya'ni so'rov arzon.
    where, params = queries.build_tender_filters(
        status="open", region=body.region, currency=body.currency,
        q=body.q, products=body.products + body.services)
    where = (where + " AND t.id = ANY(%(ids)s)") if where else "WHERE t.id = ANY(%(ids)s)"
    params["ids"] = ids
    cand = db.query(queries.match_candidates_sql(where, cap=MATCH_CAP), params)

    # Matn mosligini MAHSULOTGA biriktirish.
    #
    # ATAMA BO'YICHA, MAHSULOT BO'YICHA EMAS. Mahsulot bo'ylab yurish
    # ikki xato berardi:
    #   TEZLIK — 1797 mahsulot x 3 kalit so'z har pozitsiya uchun;
    #   TO'G'RILIK — birinchi MOS KELGAN mahsulot qaytardi, va u
    #       ko'pincha noto'g'ri edi: "Кабель силовой" pozitsiyasiga
    #       "GNT-10703-60" biriktirilgandi.
    # Endi AYNAN mos kelgan ATAMA topiladi va mahsulot o'shandan olinadi.
    atama_mahsulot: Dict[str, str] = dict(juft)
    # Uzun atama aniqroq: "IP камеры" "камер" dan ustun bo'lsin.
    atamalar = sorted(atama_mahsulot, key=len, reverse=True)

    def _matn_mahsulot(poz_nomi: str) -> Optional[str]:
        blob = matching._norm(poz_nomi or "")
        for t in atamalar:
            if matching._hits(t, blob):
                return atama_mahsulot[t]
        return None

    matched = []
    for c in cand:
        # BALL DALILGA QARAB. Ilgari `category` mosligi 100 berardi va
        # bu eng katta soxta-moslik manbai edi (o'lchangan: 206 dan 131
        # tasi shu yo'ldan; "Andijon GES transformatori" -> "Kondensator"
        # 100 ball). Endi:
        #   kod — rasmiy tasniflagich, inson tasdiqlagan   -> 100
        #   nom — matn mosligi, morfologik jihatdan mo'rt  ->  60
        # Nom uchun 100 BERILMAYDI: "monitor" so'zi "monitoringi" ichida
        # ham uchraydi va buni matn darajasida ajratib bo'lmaydi
        # (o'lchandi: qo'shimcha uzunligi to'g'ri va xato holatlarni
        # ajratmaydi).
        kod_bor = c["id"] in kod_ids
        p_list = poz.get(c["id"], []) if kod_bor else []
        if kod_bor:
            positions = [{"pozitsiya": x["pozitsiya"], "mahsulot": x["mahsulot"],
                          "aniq": x["aniq"] and len(x["kod"] or "") >= 8,
                          "kod": x["good_code"]}
                         for x in p_list[:6]]
            n_poz = len(p_list)
        else:
            nomlar = matn_poz.get(c["id"], [])
            positions = [{"pozitsiya": nm, "mahsulot": _matn_mahsulot(nm),
                          "aniq": False, "kod": None} for nm in nomlar[:6]]
            n_poz = len(nomlar)

        item = _shape_tender(c)
        # HUDUD BELGISI — "Sizga mos" bilan navbat BIR XIL qoidani
        # ko'rsatsin.
        #
        # O'LCHANGAN NOMUVOFIQLIK (2026-09-03). Bu bo'lim profildagi
        # hudud cheklovini UMUMAN hisobga olmasdi, malaka tekshiruvi
        # esa uni QATTIQ `fail` sifatida qo'llardi. Natijada katalogga
        # mos 28 ta ochiq tenderdan 11 tasi broker navbatida yo'q edi
        # va sababi hech qayerda ko'rinmasdi — hammasi kompaniyaning
        # O'Z profili "biz u yerda ishlamaymiz" degan viloyatlarda
        # (Jizzax, Andijon, Farg'ona, Qoraqalpog'iston, ...).
        #
        # RO'YXATDAN OLIB TASHLANMAYDI, BELGILANADI. Yashirish
        # kompaniyaga "hududni kengaytirsam nima yutaman" degan
        # savolga javob berish imkonini yo'q qilardi — va bu qaror
        # SOTUV qarori, filtr emas.
        # O'LCHAB BO'LMAGANI (`None`) "tashqarida" DEGANI EMAS —
        # cheklov qo'yilmagan yoki tenderning hududi noma'lum.
        mos = qualification.hudud_mos(c.get("area_path"), profil_regions)
        item["hudud_tashqari"] = (mos is False)
        item["catalog"] = {
            # kod — rasmiy tasniflagich, inson tasdiqlagan   -> 100
            # nom — matn mosligi, morfologik jihatdan mo'rt  ->  60
            # Nom uchun 100 BERILMAYDI: "monitor" so'zi "monitoringi"
            # ichida ham uchraydi va buni matn darajasida ajratib
            # bo'lmaydi (o'lchandi: qo'shimcha uzunligi to'g'ri va xato
            # holatlarni ajratmaydi).
            "score": (100 if any(len(x["kod"] or "") >= 8 for x in p_list)
                      else 80) if kod_bor else 60,
            "by": "kod" if kod_bor else "nom",
            # DALIL — tenderning QAYSI pozitsiyasi mos kelgani.
            # Mahsulot nomi emas: bir kodni bir necha mahsulot baham
            # ko'rishi mumkin va u holda mahsulot nomi taxmin bo'ladi.
            "positions": positions,
            "position_count": n_poz,
            # TAKRORSIZ, TARTIB SAQLANGAN. O'LCHANGAN NUQSON
            # (2026-09-02): bir mahsulot bir tenderning bir necha
            # pozitsiyasiga mos kelsa, nomi ro'yxatga BIR NECHA
            # marta tushardi (37 elementdan 3 tasida). Ikki oqibati
            # bor edi:
            #   * interfeys sababni IKKI MARTA ko'rsatardi;
            #   * React `key` dublikati ogohlantirishi chiqardi
            #     (`TenderTable` sabablarni nom bo'yicha kalitlaydi).
            # `dict.fromkeys` tartibni saqlaydi -- eng kuchli moslik
            # birinchi bo'lib qolsin.
            "products": list(dict.fromkeys(
                x["mahsulot"] for x in positions if x["mahsulot"]))[:5],
        }
        matched.append(item)

    # Kod mosligi yuqori, keyin deadline yaqin
    matched.sort(key=lambda it: (-it["catalog"]["score"], it["close_at"] or "9999"))
    total = len(matched)
    page = matched[body.offset: body.offset + body.limit]
    return {"total": total, "limit": body.limit, "offset": body.offset,
            "items": page, "holat": kodlash.holat(cid),
            # Atama chegarasi ishga tushgan bo'lsa JIMGINA kesmaymiz —
            # foydalanuvchi qamrov to'liq emasligini bilishi kerak.
            "atama_kesildi": kesilgan,
            # HUDUD XULOSASI — SAHIFADAN emas, BUTUN natijadan.
            # Sahifadagi sonni ko'rsatish "2 tasi tashqarida" derdi,
            # holbuki jami 11 ta bo'lishi mumkin. Bu bo'lim aynan
            # "nechtasini yo'qotyapman" savoliga javob beradi.
            "hudud": {"regions": profil_regions,
                      "tashqari": sum(1 for it in matched
                                      if it["hudud_tashqari"]),
                      "jami": total}}


@app.get("/catalog/new-count")
def catalog_new_count(request: Request):
    """Xabarnoma belgisi: katalogga mos VA oxirgi ko'rilgandan keyin e'lon
    qilingan ochiq tenderlar soni (ilova-ichi 'N yangi')."""
    company_id = company_id_of(request)
    prods = db.query(queries.CATALOG_LIST_SQL, {"company_id": company_id})
    if not prods:
        return {"new": 0, "total": 0}
    if len(prods) > CATALOG_INLINE_MATCH_LIMIT:
        # Birinchi sahifa ochilishida 1 797 x 528 matn solishtirishni ishga
        # tushirmaymiz. Bu badge yordamchi signal; katalogning o'zi undan
        # ustun va darhol ko'rinishi kerak.
        return {"new": 0, "total": 0, "deferred": True}
    last_seen = db.scalar(queries.CATALOG_STATE_GET_SQL,
                          {"company_id": company_id})
    cand = _catalog_candidates()
    total = new = 0
    for c in cand:
        if not any(_product_matches(c, p, allow_text=False) for p in prods):
            continue
        total += 1
        pub = c.get("publicated_at")
        if last_seen and pub and pub > last_seen:
            new += 1
    return {"new": new, "total": total}


@app.post("/catalog/seen", status_code=204)
def catalog_seen(request: Request):
    """Katalog moslarini 'ko'rildi' deb belgilaydi (yangi-belgisi tozalanadi)."""
    db.execute_returning(queries.CATALOG_SEEN_SQL,
                         {"company_id": company_id_of(request)})
    return None


# ---------------------------------------------------------------------------
# KOD-ASOSLI MOSLASHTIRISH — `api/kodlash.py`
#
# Matn bo'yicha moslashtirish TILGA BOG'LIQ va shu sababli yiqiladi:
# korpus rus/kirillda, foydalanuvchi o'zbek-lotinda yozadi. Rasmiy
# tasniflagich (`tender_good.good_code`) esa tilga bog'liq emas va
# qamrovi 100%.
#
# Oqim: taklif -> INSON tasdig'i -> moslik. Tasdiqlanmagan taklif
# hech qachon moslikka aylanmaydi (`v_catalog_code_active`).
# ---------------------------------------------------------------------------
@app.get("/catalog/{product_id}/kod-takliflar")
def kod_takliflar(product_id: int, request: Request, limit: int = 6):
    """Mahsulot uchun nomzod kodlar (tasdiqlash ekrani uchun).

    IKKI DARAJA qaytadi va bu ATAYLAB:

      `keng` (5 belgi, masalan `28.25`) — guruh. Ko'proq tender topadi,
             lekin begonasini ham olib keladi.
      `aniq` (8 belgi, masalan `28.25.13`) — sinf. Kamroq, lekin toza.

    NEGA TANLOVNI ODAMGA BERAMIZ: o'lchangan holat — "Tibbiy muzlatgich"
    uchun `28.25` guruhi "sanoat sovutish VA VENTILYATSIYA uskunalari"ni
    qamraydi, shuning uchun lokomotiv ta'miri tenderidagi "Калорифер"
    ham mos chiqadi. `28.25.13` (Чиллер, issiqlik nasosi) esa buni
    ajratadi. Qaysi kenglik to'g'ri ekanini FAQAT broker biladi —
    tizim taxmin qilmasligi kerak.

    Har taklifda `n_tender_open` bor: tasdiqlash NIMAGA olib kelishini
    inson OLDINDAN ko'radi. Ball ko'rsatilmaydi — u RRF yig'indisi,
    foiz emas.
    """
    cid = company_id_of(request)
    p = db.query_one(
        "SELECT id, name, category_code, keywords FROM catalog_product "
        "WHERE id = %(id)s AND company_id = %(c)s", {"id": product_id, "c": cid})
    if not p:
        raise xatolar.Xato("PRODUCT_NOT_FOUND")

    keng = kodlash.takliflar(dict(p), level=5, limit=limit)
    aniq = kodlash.takliflar(dict(p), level=8, limit=limit)
    kodlash.taklif_yoz(cid, product_id, keng + aniq)

    # Inson allaqachon qaror qilganlarini belgilab qaytaramiz.
    qaror = {r["code"]: r for r in db.query(
        "SELECT code, tasdiqlandi, rad_etildi FROM catalog_product_code "
        "WHERE product_id = %(p)s AND company_id = %(c)s",
        {"p": product_id, "c": cid})}
    for x in keng + aniq:
        q = qaror.get(x["code"]) or {}
        x["tasdiqlandi"] = _iso(q.get("tasdiqlandi"))
        x["rad_etildi"] = _iso(q.get("rad_etildi"))
    return {"product_id": product_id, "keng": keng, "aniq": aniq,
            # Eski maydon — birinchi versiyaga tayangan chaqiruvchilar uchun.
            "takliflar": keng}


class KodQarorIn(BaseModel):
    code: str


@app.post("/catalog/{product_id}/kod-tasdiq", status_code=204)
def kod_tasdiq(product_id: int, body: KodQarorIn, request: Request):
    """Inson kodni TASDIQLAYDI. Aktor, manba va audit yoziladi.

    O'LCHANGAN NUQSON (2026-09-02): bu yo'l `catalog_product_code`
    ga TO'G'RIDAN-TO'G'RI yozardi — aktorsiz, manbasiz, auditsiz.
    Natijada bazada 1 048 ta "inson tasdig'i" paydo bo'lgan va
    ularning hammasi mashina yozgan (16 ta sekundda). Endi bu yo'l
    `/kod/qaror` bilan AYNI qoidaga bo'ysunadi.
    """
    acc = current_account(request)
    kim = (acc.get("username") or "").strip()
    if not kim:
        # SERVICE kaliti (ERP) odam emas — tasdiq qo'ya olmaydi.
        raise xatolar.Xato("AUTH_LOGIN_REQUIRED")
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "tasdiq")
    if not kodlash.tasdiqla(cid, product_id, body.code, kim,
                            ishonch=k.ishonch, actor_id=k.actor_id):
        raise xatolar.Xato("LINK_NOT_FOUND")
    audit_yoz(k, request, amal="kod_tasdiq",
              entity="catalog_product_code", entity_id=product_id,
              keyin={"code": body.code})
    return None


@app.post("/catalog/{product_id}/kod-rad", status_code=204)
def kod_rad(product_id: int, body: KodQarorIn, request: Request):
    """Inson taklifni RAD etadi (qator qoladi — takror taklif chiqmasin).

    RAD ETISH HAM QAROR va u avval umuman kimliksiz edi: bu
    endpoint sessiyani ham tekshirmasdi, ya'ni SERVICE kaliti bilan
    ham rad etib bo'lardi va "kim rad etdi" javobsiz qolardi.
    """
    acc = current_account(request)
    kim = (acc.get("username") or "").strip()
    if not kim:
        raise xatolar.Xato("AUTH_LOGIN_REQUIRED")
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "korib_chiq")
    if not kodlash.rad_et(cid, product_id, body.code,
                          ishonch=k.ishonch, actor_id=k.actor_id):
        raise xatolar.Xato("LINK_NOT_FOUND")
    audit_yoz(k, request, amal="kod_rad",
              entity="catalog_product_code", entity_id=product_id,
              keyin={"code": body.code})
    return None


@app.get("/kod/qidir")
def kod_qidir(request: Request, soz: str = "", limit: int = 10,
              kalit: str = ""):
    """Tasniflagich kodini QIDIRISH — korpus pozitsiyalari bo'yicha.

    NEGA TESKARI YO'NALISHDA: broker `Кульман` yoki `Трубка
    рентгеновская` degan rasmiy nomlarni tanimaydi, lekin POZITSIYA
    nomlarini taniydi. Shuning uchun so'rov korpusdagi tovar nomlariga
    solishtiriladi va natija "qaysi kod ostida shunday pozitsiyalar
    bor" bo'lib qaytadi.

    KO'P-IJARACHILIK — IKKI QISM ANIQ AJRATILGAN:

      korpus qismi  (`pozitsiya`, `kod_nomi`) — UMUMIY ma'lumot.
          `tender_good` va `dim_good_code` hech qaysi ijarachiga
          tegishli emas, shuning uchun filtr QO'YILMAYDI. Qo'yilsa
          natija bo'shab qolardi.

      kompaniya qismi (`meniki`) — FAQAT shu ijarachining katalogi.
          `company_id` MAJBURIY va u `company_id_of(request)` dan
          keladi.
    """
    cid = company_id_of(request)
    natija = kodlash.qidir(soz, limit=limit)

    # Shu atama MENING katalogimda nechta mahsulotga tegishli —
    # kompaniya ma'lumoti, shuning uchun `company_id` bilan.
    meniki = 0
    if natija.get("kalit"):
        pats = []
        for bolak in natija["kalit"].split():
            for v in translit.variants(bolak):
                if v and len(v) >= 3:
                    pats.append(f"%{v}%")
        if pats:
            meniki = db.scalar(
                "SELECT count(*) FROM catalog_product p "
                "WHERE p.company_id = %(company_id)s "
                f"  AND ({translit.sql_fold('p.name')} LIKE ANY(%(pats)s) "
                "       OR EXISTS (SELECT 1 FROM unnest(p.keywords) k "
                f"                  WHERE {translit.sql_fold('k')} LIKE ANY(%(pats)s)))",
                {"company_id": cid, "pats": pats}) or 0

    natija["meniki"] = meniki

    # QIDIRUV SANOG'I. `kalit` berilsa (ekran navbatdagi atamani
    # ko'rayotgan bo'lsa) sanoq oshadi. Shu raqam "talabsiz tugmasi
    # bosilgunga qadar qidirilganmi" degan savolga javob beradi —
    # qidiruvsiz "talabsiz" avtomatik o'lchovga ishonish demak va u
    # xato bo'lishi o'lchangan (`turniket`).
    if kalit.strip():
        # QIDIRUV SO'ZI HAM SAQLANADI: "nechta marta qidirdi" va
        # "NIMANI qidirdi" boshqa-boshqa savollar. Ikkinchisisiz
        # qaror sababini keyin tiklab bo'lmaydi.
        natija["qidiruv_soni"] = kodlash.qaror_qidiruv(cid, kalit.strip(),
                                                       soz=soz)
    return natija


@app.get("/catalog/kod-navbat")
def kod_navbat(request: Request, limit: int = 40,
               takliflar: bool = False):
    """Kodlash navbati — kodsiz atamalar, DALIL bilan.

    `takliflar=false` (standart) — tez ochiladi. Taklif sifati past
    (o'lchandi: 10 atamadan 1-2 tasida ishonchli nomzod), asosiy yo'l
    `/kod/qidir`. Taklif kerak bo'lsa `takliflar=true`.

    TO'RT toifa qaytadi va ULARNING YIG'INDISI JAMIGA TENG:
      `atamalar`        — ko'rib chiqiladi
      `talabsiz`        — korpusda uchramaydi, ko'rish SHART EMAS
      `turi_aniqmas`    — kalit so'zi spetsifikatsiya yoki bo'sh
      `qaror_qilingan`  — inson allaqachon qaror qilgan

    Oxirgisi keyin qo'shildi: `talabsiz`/`otkazildi` kod BERMAYDI,
    ya'ni mahsulot kodsiz qoladi va filtrsiz atama navbatga QAYTARDI
    (o'lchandi) — navbat hech qachon tugamasdi.
    """
    return kodlash.navbat(company_id_of(request), limit=limit,
                          takliflar_bilan=takliflar)


#: NOM TAKRORLANMASIN. Yuqorida allaqachon `KodQarorIn` bor
#: (`code: str`, kod-tasdiq/kod-rad uchun). Ikkinchi marta shu nom
#: ishlatilganda ijro buzilmaydi (annotatsiya `def` paytida
#: bog'lanadi), lekin OpenAPI sxemasi ikkalasini POZITSIYA bo'yicha
#: `KodQarorIn__1` / `KodQarorIn__2` deb nomlaydi. Endpointlar tartibi
#: o'zgarsa nomlar JIMGINA almashadi va generatsiya qilingan mijoz
#: tiplari bir-birining o'rniga tushadi. Shuning uchun alohida nom.
class AtamaQarorIn(BaseModel):
    """INSON qarori — kodlash navbatidan.

    `qaror` `Literal` bilan QULFLANGAN: noto'g'ri qiymat FastAPI
    darajasida 422 beradi va `kodlash.qaror_yoz()` gacha yetib
    bormaydi. Baza CHECK i (`kod_qaror_turi`) uchinchi qavat.
    """
    kalit: str
    atama: str
    qaror: Literal["kod", "talabsiz", "dalilsiz", "otkazildi"]
    code: Optional[str] = None
    manba: Optional[Literal["taklif", "qidiruv", "qolda"]] = None
    #: Inson EKRANDA KO'RGAN dalil. ML uchun yorliqning o'zi yetarli
    #: emas — kirish ham kerak.
    dalil: Optional[Dict[str, Any]] = None
    #: Qaror paytida birinchi turgan AVTOMATIK taklif (kelishuv
    #: foizini shundan hisoblaymiz).
    taklif_code: Optional[str] = None
    taklif_skor: Optional[float] = None
    #: Inson ANIQ rad etgan kodlar — MANFIY misollar.
    rad_takliflar: Optional[List[str]] = None
    #: true = bu kod avvalgisiga QO'SHIMCHA (atama haqiqatan ko'p kodli).
    qoshimcha_kod: bool = False
    izoh: Optional[str] = None


class AtamaOchishIn(BaseModel):
    """Atama ko'rib chiqishga ochildi — VAQT hisobi shundan.

    Qaror maydonlari ATAYLAB YO'Q: ochish qaror EMAS va uni qaror
    modelida yuborish ikkisini aralashtirardi.
    """
    kalit: str
    atama: str


@app.post("/kod/qaror/ochish")
def kod_qaror_ochish(body: AtamaOchishIn, request: Request):
    """Atama ko'rib chiqishga ochildi — VAQT hisobi shu yerdan.

    Ekran atamani ochganda chaqiradi. Qo'lda vaqt yozilmasin degan
    talab shu yerda bajariladi.
    """
    return kodlash.qaror_ochish(company_id_of(request),
                                body.kalit, body.atama)


@app.post("/kod/qaror")
def kod_qaror(body: AtamaQarorIn, request: Request):
    """Qaror yoziladi. Vaqt, manba va qidiruv soni AVTOMATIK saqlanadi.

    `kim` — sessiyadan. SERVICE kaliti (ERP) odam emas, qaror qo'ya
    olmaydi: `catalog_product_code` bilan bir xil qoida.

    QAROR 'kod' bo'lsa `catalog_product_code` ga ham yoziladi —
    ya'ni moslashtirish DARHOL ishlaydi va broker natijani o'sha
    yurishda ko'radi.
    """
    acc = current_account(request)
    kim = (acc.get("username") or "").strip()
    if not kim:
        raise xatolar.Xato("AUTH_LOGIN_REQUIRED")
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    # Kod berish — TASDIQ (u katalogga yoziladi va moslashtirishga
    # darhol ta'sir qiladi). Qolganlari ko'rib chiqish.
    ruxsat(k, "tasdiq" if body.qaror == "kod" else "korib_chiq")

    try:
        row = kodlash.qaror_yoz(
            cid, body.kalit, body.atama, body.qaror, kim=kim,
            actor_id=k.actor_id, ishonch=k.ishonch,
            code=body.code, manba=body.manba, dalil=body.dalil,
            taklif_code=body.taklif_code, taklif_skor=body.taklif_skor,
            rad_takliflar=body.rad_takliflar,
            qoshimcha_kod=body.qoshimcha_kod, izoh=body.izoh)
    except ValueError as e:
        # BO'SH yoki yaroqsiz kod shu yerda to'xtaydi va broker
        # TUSHUNARLI xabar oladi (baza xabari emas).
        raise xatolar.kodli(e, "FIELD_INVALID")

    # Kod berilgan bo'lsa — shu atamaga tegishli MAHSULOTLARGA
    # biriktiramiz va biriktirmani QARORGA bog'laymiz (audit izi).
    n_mahsulot = 0
    if body.qaror == "kod" and body.code:
        n_mahsulot = kodlash.atamaga_kod_biriktir(
            cid, body.kalit, (body.code or "").strip(), kim,
            qaror_id=row.get("id"), ishonch=k.ishonch, actor_id=k.actor_id)
    audit_yoz(k, request, amal=f"kod_{body.qaror}",
              entity="kod_qaror", entity_id=int(row.get("id") or 0),
              keyin={"atama": body.atama, "qaror": body.qaror,
                     "code": body.code, "taklif_code": body.taklif_code,
                     "biriktirildi": n_mahsulot},
              izoh=body.izoh)
    return {**row, "biriktirildi": n_mahsulot}


@app.get("/kod/qaror/olchov")
def kod_qaror_olchov(request: Request):
    """Pilot o'lchovi — FAQAT haqiqiy inson harakatidan.

    `pilot` — "40 taga qancha qoldi" ekranda ko'rinsin. Qo'lda
    hisoblangan raqam xotiradan tiklanib TAXMINGA aylanadi.
    """
    cid = company_id_of(request)
    return {"olchov": kodlash.qaror_olchov(cid),
            "pilot": kodlash.pilot_holati(cid),
            "qarorlar": kodlash.qarorlar(cid)}


# ===========================================================================
# KELIB CHIQISH (provenance) — huquqiy tekshiruv uchun
#
# Har yozuv OMMAVIY manbaga qaytarib bog'lanadi. Naqsh BAZADA
# (`manba_url()` funksiyasi) — ilgari u faqat frontendda edi va
# bazadan so'ralganda mashina o'qiy oladigan javob yo'q edi.
#
# Batafsil: `docs/legal-data-map.md`.
# ===========================================================================
@app.get("/manba/qamrov")
def manba_qamrov(request: Request):
    """Kelib chiqish metama'lumoti QANCHA yozuvda yetishmaydi.

    Nol bo'lmagan ustun — kelib chiqishi yo'q yozuvlar bor. Bu
    O'LCHOV, da'vo emas: raqam o'zi gapiradi.
    """
    company_id_of(request)              # darvoza: kirmagan ko'ra olmaydi
    if not db.scalar("SELECT to_regclass('public.v_manba_qamrov') IS NOT NULL"):
        return {"tayyor": False,
                "sabab": "schema_patch_manba_url.sql qo'llanmagan"}
    return {"tayyor": True, "qamrov": db.query("SELECT * FROM v_manba_qamrov")}


@app.get("/manba/tender/{tender_id}")
def manba_tender(tender_id: int, request: Request):
    """Bitta tenderning manbaga qaytish yo'li va uning hujjatlari.

    `ommaviy_url` NULL bo'lsa — platforma naqshi NOMA'LUM va taxminiy
    havola BERILMAYDI. "Noma'lum" va "havola yo'q" bir xil emas.
    """
    company_id_of(request)
    if not db.scalar("SELECT to_regclass('public.v_tender_manba') IS NOT NULL"):
        raise xatolar.Xato("SCHEMA_PATCH_MISSING",
                           {"patch": "schema_patch_manba_url.sql"})
    t = db.query_one("SELECT * FROM v_tender_manba WHERE ichki_id = %(id)s",
                     {"id": tender_id})
    if not t:
        raise xatolar.Xato("TENDER_NOT_FOUND")
    return {"tender": t,
            "hujjatlar": db.query(
                "SELECT * FROM v_hujjat_manba WHERE tender_id = %(id)s "
                "ORDER BY file_ref", {"id": tender_id})}


# ===========================================================================
# AKTOR VA AUDIT (auth-6)
#
# Tender-AI ga KOMPANIYA kiradi, odam emas. Aktor — ERP hodimiga
# XARITA (`api/aktor.py`), kimlik ombori emas: parol yo'q, kirish
# bermaydi. Batafsil: `docs/erp_kimlik.md`.
# ===========================================================================
class AktorIn(BaseModel):
    """Yangi aktor. `manba='erp'` bo'lsa `erp_user_id` SHART."""
    login: str
    ism: str
    rol: Literal["kuzatuvchi", "koruvchi", "tasdiqlovchi", "admin"]
    manba: Literal["erp", "mahalliy"] = "mahalliy"
    erp_user_id: Optional[int] = None
    izoh: Optional[str] = None


class AktorYangilashIn(BaseModel):
    """Berilmagan maydon O'ZGARMAYDI."""
    rol: Optional[Literal["kuzatuvchi", "koruvchi", "tasdiqlovchi", "admin"]] = None
    ism: Optional[str] = None
    active: Optional[bool] = None
    izoh: Optional[str] = None


@app.get("/aktor")
def aktor_royxat(request: Request, faqat_faol: bool = False):
    """Shu IJARACHINING aktorlari.

    `company_id` SQL shartida — boshqa ijarachining xodimlari
    ro'yxati ko'rinmaydi. FK yozishni to'sadi, O'QISHNI esa faqat
    shu shart to'sadi.
    """
    from api import aktor
    cid = company_id_of(request)
    if not aktor.ready():
        return {"tayyor": False, "aktorlar": [],
                "sabab": "schema_patch_aktor.sql qo'llanmagan"}
    k = kimlik_of(request, cid)
    ruxsat(k, "korish")
    return {"tayyor": True, "aktorlar": aktor.royxat(cid, faqat_faol=faqat_faol),
            "meniki": k.dict()}


@app.post("/aktor")
def aktor_qosh(body: AktorIn, request: Request):
    """Aktor qo'shadi. FAQAT `sozlama` huquqi bilan.

    Bu amal "kim qaror qo'ya oladi" ni belgilaydi, ya'ni qarorning
    o'zidan KUCHLIROQ. Shuning uchun eng yuqori huquq talab qilinadi.
    """
    from api import aktor
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "sozlama")
    try:
        row = aktor.qosh(cid, login=body.login, ism=body.ism, rol=body.rol,
                         manba=body.manba, erp_user_id=body.erp_user_id,
                         izoh=body.izoh)
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    except Exception as e:                                    # noqa: BLE001
        # Takroriy login/erp_user_id — baza indeksi to'sadi.
        raise xatolar.kodli(e, "ACTOR_ERP_MISMATCH")
    audit_yoz(k, request, amal="aktor_qoshildi", entity="actor",
              entity_id=int(row["id"]),
              keyin={"login": row["login"], "rol": row["rol"],
                     "manba": row["manba"], "erp_user_id": row["erp_user_id"]})
    return row


@app.get("/aktor/erp")
def aktor_erp_nomzodlar(request: Request):
    """ERP odamlari va ularning xaritadagi holati. FAQAT O'QISH.

    `sozlama` talab qilinadi: bu ro'yxat "kim qaror qo'ya oladigan
    bo'lishi mumkin" degan ma'lumot, ya'ni tashkilot tarkibi.

    `token_hash` QAYTMAYDI — u `erp.v_tai_actor` da bor, lekin sir.
    """
    from api import aktor
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "sozlama")
    return aktor.erp_nomzodlar(cid)


@app.post("/aktor/erp/sinxron")
def aktor_erp_sinxron(request: Request, quruq: bool = False):
    """ERP odamlarini aktor xaritasiga IDEMPOTENT qo'shadi.

    Ijarachi SESSIYADAN olinadi (`company_id_of`), so'rov tanasidan
    EMAS — kompaniyalararo xaritalash shu bilan imkonsiz.

    `?quruq=true` — reja ko'rsatiladi, hech narsa yozilmaydi.
    """
    from api import aktor
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "sozlama")
    natija = aktor.erp_sinxron(cid, quruq=quruq)
    # AUDIT HAR AKTOR UCHUN ALOHIDA. Yig'ma qator `entity_id` ni hech
    # narsaga ishora qilmaydigan qilib qo'yardi; bu yerda esa har
    # yozuv AYNAN qaysi aktorga tegishli ekani ko'rinadi.
    # QURUQ yurish audit yozmaydi: hech narsa o'zgarmagan.
    if not quruq and natija.get("bajarildi"):
        for r in natija.get("natija", []):
            if r.get("amal") not in ("yaratildi", "nofaollashtirildi"):
                continue
            audit_yoz(k, request,
                      amal=f"aktor_sinxron_{r['amal']}", entity="actor",
                      entity_id=int(r["actor_id"]),
                      keyin={"login": r["login"], "rol": r["tai_rol"],
                             "erp_user_id": r["erp_user_id"],
                             "erp_faol": r["erp_faol"]},
                      izoh=r.get("sabab"))
    return natija


@app.patch("/aktor/{actor_id}")
def aktor_yangila(actor_id: int, body: AktorYangilashIn, request: Request):
    """Aktor rolini/holatini o'zgartiradi. FAQAT `sozlama`."""
    from api import aktor
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "sozlama")
    oldin = aktor.bitta(cid, actor_id)
    if not oldin:
        # Boshqa ijarachiniki ham shu yerga tushadi — javob BIR XIL.
        raise xatolar.Xato("ACTOR_NOT_FOUND")
    try:
        row = aktor.yangila(cid, actor_id, rol=body.rol, ism=body.ism,
                            active=body.active, izoh=body.izoh)
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    audit_yoz(k, request, amal="aktor_yangilandi", entity="actor",
              entity_id=actor_id,
              oldin={"rol": oldin["rol"], "ism": oldin["ism"],
                     "active": oldin["active"]},
              keyin={"rol": row["rol"], "ism": row["ism"],
                     "active": row["active"]})
    return row


@app.get("/validatsiya/holat")
def validatsiya_holat(request: Request):
    """INSON TASDIG'I holati — qatlam bo'yicha, DALIL darajasi bilan.

    UCH DARAJA ATAYLAB AJRATILGAN va ular qo'shilmaydi:

        aktorli  — qaysi ODAM qilgani ma'lum   (darvoza SHUNI sanaydi)
        anonim   — odam, lekin shaxsan noma'lum (kompaniya sessiyasi)
        mashina  — INSON EMAS

    Ilgari uchalasi bitta raqamga qo'shilardi va natijada mashina
    yozgan 1 048 ta qator "inson tasdig'i 73.4%" bo'lib ko'rinardi.

    `ulush_foiz` chegaradan O'TMAGUNCHA `null` qaytadi: kichik
    namunadan foiz chiqarish yolg'on aniqlik bo'lardi.

    `tosiq` — pilot nima uchun yurmayotgani. `null` bo'lsa shu
    qatlamda aktorli qaror yozish mumkin.
    """
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    ruxsat(k, "korish")
    darvoza = db.query(
        "SELECT qatlam, eng_kam, aktorli, qolgan, anonim, mashina, "
        "       navbatda, holat, ulush_foiz "
        "  FROM v_sifat_darvoza WHERE company_id = %(c)s ORDER BY qatlam",
        {"c": cid})
    tayyorlik = db.query(
        "SELECT qatlam, aktor_jami, aktor_faol, aktor_koruvchi, tosiq "
        "  FROM v_pilot_tayyorlik WHERE company_id = %(c)s ORDER BY qatlam",
        {"c": cid})
    t_map = {r["qatlam"]: r for r in tayyorlik}
    return {
        "qatlamlar": [{**d, **{kk: vv for kk, vv in
                               (t_map.get(d["qatlam"]) or {}).items()
                               if kk != "qatlam"}}
                      for d in darvoza],
        # HOLAT ATAMALARI — hisobotda aralashmasin.
        "izoh": {
            "INSON_TASDIQLADI": "yetarli sondagi AKTORLI qaror bor",
            "YETARLI_EMAS": "aktorli qaror bor, lekin chegaradan kam",
            "TASDIQLANMAGAN": "aktorli qaror YO'Q",
        },
    }


@app.get("/aktor/holat")
def aktor_holat(request: Request):
    """Atribut sifati — QANCHA qaror haqiqiy odamga bog'langan.

    `nomalum` va `faqat_kompaniya` ustunlari YASHIRILMAYDI: ular
    atribut qarzining o'lchovi va uni ko'rsatmaslik "hammasi
    joyida" degan yolg'on beradi.
    """
    from api import aktor
    cid = company_id_of(request)
    if not aktor.ready():
        return {"tayyor": False, "sabab": "schema_patch_aktor.sql qo'llanmagan"}
    k = kimlik_of(request, cid)
    ruxsat(k, "korish")
    return {
        "tayyor": True,
        "meniki": k.dict(),
        "aktor_majburiy": aktor.aktor_majburiymi(cid),
        # ERP shartnoma-view i YO'Q bo'lsa eng yuqori ishonch
        # `aktor_elon` bo'lib qoladi. Bu ochiq aytiladi.
        "erp_kontekst": aktor.erp_kontekst_ready(),
        "erp_moslik": aktor.erp_moslikni_tekshir(cid),
        "atribut_sifati": aktor.atribut_sifati(cid),
        "rollar": list(aktor.ROLLAR),
        "ruxsat_matritsasi": {a: list(r) for a, r in aktor.RUXSAT.items()},
    }


@app.get("/audit")
def audit_royxat(request: Request, entity: Optional[str] = None,
                 entity_id: Optional[int] = None,
                 actor_id: Optional[int] = None, limit: int = 200):
    """Audit tarixi. FAQAT shu ijarachiniki.

    Jadval APPEND-ONLY (baza trigger'i), ya'ni bu ro'yxatni
    o'zgartirish yo'li API da ham, SQL da ham yo'q.
    """
    from api import aktor
    cid = company_id_of(request)
    if not aktor.ready():
        return {"tayyor": False, "yozuvlar": []}
    k = kimlik_of(request, cid)
    ruxsat(k, "korish")
    return {"tayyor": True,
            "yozuvlar": aktor.tarix(cid, entity=entity, entity_id=entity_id,
                                    actor_id=actor_id, limit=limit)}


@app.get("/kod/qaror/tafsil")
def kod_qaror_tafsil(request: Request, limit: int = 500):
    """Har qaror DALILI bilan — ML to'plamining xom manbai.

    Hech qanday qoida qo'llanmaydi. Birinchi 40 qarorning maqsadi
    o'lchash va sxemani sinash; qoida jadvalining shakli SHUNDAN
    KEYIN ma'lum bo'ladi.
    """
    cid = company_id_of(request)
    return {"tafsil": kodlash.qaror_tafsil(cid, limit=max(1, min(limit, 2000)))}


@app.get("/catalog/kodlash-holati")
def kodlash_holati(request: Request):
    """Katalogning nechta mahsuloti kodlangan.

    `kodsiz` — moslashtirishda QATNASHMAYDIGAN mahsulotlar. Interfeys
    buni ANIQ ko'rsatishi shart: "moslik topilmadi" va "katalog hali
    kodlanmagan" butunlay boshqa holatlar.
    """
    cid = company_id_of(request)
    h = kodlash.holat(cid)
    h["kodsiz_mahsulotlar"] = kodlash.kodsiz_mahsulotlar(cid)
    return h


@app.get("/match/kod")
def match_kod(request: Request, limit: int = 200, only_open: bool = True):
    """Tasdiqlangan kodlar bo'yicha mos tenderlar (POZITSIYA darajasida).

    Har qatorda: nechta pozitsiya mos keldi, qaysi mahsulot va qaysi
    pozitsiya — ya'ni sabab ko'rinadi, "qora quti" emas.
    """
    cid = company_id_of(request)
    rows = kodlash.moslik(cid, only_open=only_open, limit=limit)
    if not rows:
        # BO'SH NATIJANING SABABI AYTILADI. Aks holda foydalanuvchi
        # "mos tender yo'q" deb o'ylaydi, aslida katalog kodlanmagan.
        return {"items": [], "holat": kodlash.holat(cid)}
    tid = [r["tender_id"] for r in rows]
    tlar = {t["id"]: t for t in db.query(
        queries.match_candidates_sql("WHERE t.id = ANY(%(ids)s)", cap=len(tid) + 1),
        {"ids": tid})}
    items = []
    for r in rows:
        t = tlar.get(r["tender_id"])
        if not t:
            continue
        items.append({**_shape_tender(t), "kod_moslik": {
            "pozitsiya": r["mos_pozitsiya"],
            "summa": float(r["mos_summa"]) if r["mos_summa"] is not None else None,
            "mahsulotlar": r["mahsulotlar"],
            "pozitsiyalar": (r["pozitsiyalar"] or [])[:6],
            "kodlar": r["kodlar"],
        }})
    return {"items": items, "holat": kodlash.holat(cid)}


@app.get("/profile")
def get_profile(request: Request):
    """Faol kompaniya profili (yo'q bo'lsa null)."""
    return _shape_profile(db.query_one(
        queries.PROFILE_GET_SQL, {"company_id": company_id_of(request)}))


@app.put("/profile")
def put_profile(p: ProfileIn, request: Request):
    """Profilni saqlaydi (bitta faol profil — bor bo'lsa yangilanadi)."""
    row = db.execute_returning(queries.PROFILE_UPSERT_SQL, {
        "company_id": company_id_of(request),
        "contact_name": p.contact_name,
        "email": p.email,
        "phone": p.phone,
        "position": p.position,
        "name": p.name,
        "keywords": p.keywords,
        "regions": p.regions,
        "currency": p.currency,
        "min_cost": p.min_cost,
        "max_cost": p.max_cost,
        "about": p.about,
        "certificates": p.certificates,
        "clearances": p.clearances,
        "experience_years": p.experience_years,
        "max_contract_value": p.max_contract_value,
        "max_contract_currency": p.max_contract_currency,
        "employees": p.employees,
        "capacity_note": p.capacity_note,
        "lead_time_days": p.lead_time_days,
        "min_margin_percent": p.min_margin_percent,
        "constraints_note": p.constraints_note,
    })
    return _shape_profile(row)


@app.post("/match")
def match(body: MatchIn):
    """Profilга qarab tenderlarни ballab tartiblaydi.

    Filtrlar (status/region/currency/q) QATTIQ — nomzodlarни cheklaydi.
    Profil esa faqat SKORLAYDI (tartiblaydi), filtrlamaydi.
    """
    where, params = queries.build_tender_filters(
        status=body.status or None, region=body.region,
        currency=body.currency, q=body.q, category=body.category,
        products=body.products + body.services,
    )
    rows = db.query(queries.match_candidates_sql(where, cap=MATCH_CAP), params)

    profile = body.profile.model_dump()
    scored = []
    for r in rows:
        m = matching.score_tender(r, profile)
        item = _shape_tender(r)
        item["match"] = m
        scored.append(item)

    # Ball bo'yicha kamayish tartibida; teng bo'lsa deadline yaqin birinchi
    scored.sort(key=lambda it: (-it["match"]["score"], it["close_at"] or "9999"))

    total = len(scored)
    page = scored[body.offset: body.offset + body.limit]
    return {
        "total": total, "limit": body.limit, "offset": body.offset,
        # Cap ishga tushgan bo'lsa buni YASHIRMAYMIZ — foydalanuvchi ba'zi
        # tenderlar umuman ballanmaganini bilishi kerak (jimgina kesish yo'q).
        "truncated": len(rows) >= MATCH_CAP,
        "candidate_cap": MATCH_CAP,
        "items": page,
    }


# ---------------------------------------------------------------------------
# AI-CHAT (J4) — RAG + tool-calling
#
# Mantiq `api/ai_chat.py` da. Bu yerda faqat HTTP qatlami: kimlik, oqim va
# xatoni HTTP kodiga aylantirish.
#
# `company_id` SESSIYADAN olinadi va `ChatContext` ga qo'yiladi — model
# uni argument sifatida BERA OLMAYDI. Bu prompt injection'ga qarshi
# yagona ARXITEKTURAVIY himoya (reja_ai_chat.md §8, 3-qatlam).
#
# PUBLIC_PATHS ga QO'SHILMAYDI — barchasi `gate()` orqali o'tadi.
# ---------------------------------------------------------------------------
class ChatIn(BaseModel):
    """Chat so'rovi.

    `company_id` ATAYLAB YO'Q — u sessiyadan olinadi. Agar bu yerda
    bo'lsa, foydalanuvchi (yoki hujjat ichidagi injection orqali model)
    boshqa kompaniyaning ma'lumotini so'rab olishi mumkin bo'lardi.
    """
    message: str
    session_id: Optional[str] = None
    tender_id: Optional[int] = None
    lang: Optional[str] = None
    #: Suhbat QAYERDAN boshlangani: `panel` | `global` | `gonogo` |
    #: `match`. `eval` bu yerdan KELMAYDI -- uni faqat
    #: `run_eval.py` o'zi yozadi (`ai_chat.create_session`).
    #:
    #: Berilmasa `None` qoladi va o'lchovda "noma'lum" deb sanaladi.
    #: Taxmin qilinmaydi: `tender_id` bor degani "tender panelidan"
    #: degani EMAS -- global suhbatda ham tender ko'rsatilishi mumkin.
    manba: Optional[str] = None

    @field_validator("message")
    @classmethod
    def _bosh_emas(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("FIELD_EMPTY")
        if len(v) > 8000:
            raise ValueError("FIELD_TOO_LONG")
        return v


def _chat_tayyor() -> None:
    """Sxema qo'llanganmi. Qo'llanmagan bo'lsa ANIQ xato — 500 emas."""
    if not ai_chat.schema_ready():
        raise xatolar.Xato("SCHEMA_PATCH_MISSING",
                           {"patch": "schema_patch_ai_chat.sql"})


@app.post("/chat")
async def chat(body: ChatIn, request: Request):
    """AI-Chat — javob SSE oqimi bilan qaytadi.

    Hodisalar: `meta` · `token` · `tool` · `citation` · `done` · `error`.
    Batafsil: `api/ai_chat.stream_chat()`.

    OQIM NEGA: tahlil 10-60 soniya davom etishi mumkin (hujjat qidiruvi,
    tool chaqiruvlari). Oddiy javobda foydalanuvchi bo'sh ekranga
    qarab turardi va nima bo'layotganini bilmasdi.
    """
    _chat_tayyor()
    company_id = company_id_of(request)

    if body.session_id:
        try:
            s = ai_chat.load_session(body.session_id, company_id)
        except LookupError as e:
            raise xatolar.kodli(e, "CHAT_SESSION_NOT_FOUND")
    else:
        # `eval` MIJOZDAN QABUL QILINMAYDI. Aks holda interfeys
        # (yoki so'rovni qo'lda yasagan kim bo'lsa) o'z sessiyasini
        # "avto-yaratilgan" deb belgilab, uni o'lchovdan yashira
        # olardi -- yoki teskarisi, eval hovuzini ifloslantirardi.
        manba = body.manba if body.manba in ("panel", "global",
                                             "gonogo", "match") else None
        # TAHLIL SURATI — SESSIYA OCHILGANDA.
        #
        # `ai_analysis.content_hash` ni yozib qo'yamiz va keyingi
        # har xabarda joriysi bilan solishtiramiz. Farq bo'lsa —
        # tahlil suhbat o'rtasida QAYTA HISOBLANGAN va model buni
        # foydalanuvchiga aytishi kerak (`tender_routing.ai_ozgardi`
        # bilan bir tamoyil).
        #
        # Tahlil YO'Q bo'lsa `None` qoladi: "yo'q" bilan "o'zgardi"
        # aralashmasin.
        t_hash = None
        if body.tender_id:
            try:
                from api import tahlil as _tahlil
                t_hash = _tahlil.joriy_hash(body.tender_id, company_id)
            except Exception as e:                      # noqa: BLE001
                _log.warning("tahlil_hash olinmadi: %s", e)
        sid = ai_chat.create_session(company_id, body.tender_id,
                                     body.message[:120],
                                     i18n.norm_lang(body.lang),
                                     manba=manba, tahlil_hash=t_hash)
        s = {"id": sid, "tender_id": body.tender_id,
             "lang": i18n.norm_lang(body.lang),
             "manba": manba, "tahlil_hash": t_hash}

    ctx = ai_chat.ChatContext(
        company_id=company_id,          # <-- SESSIYADAN, modeldan EMAS
        session_id=str(s["id"]),
        lang=s.get("lang") or i18n.DEFAULT_LANG,
        tender_id=s.get("tender_id"),
        # SESSIYADAN, MIJOZDAN EMAS. Davom etayotgan suhbatda ular
        # `load_session` dan keladi — ya'ni mijoz keyingi xabarda
        # `manba` ni o'zgartirib kontekstni almashtira olmaydi.
        manba=s.get("manba"),
        tahlil_hash=s.get("tahlil_hash"),
    )
    profile = _shape_profile(db.query_one(queries.PROFILE_GET_SQL,
                                          {"company_id": company_id}))

    return StreamingResponse(
        ai_chat.stream_chat(str(s["id"]), body.message, ctx, profile),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Proksi (nginx) oqimni BUFERLAMASIN — aks holda javob
            # oxirigacha ko'rinmaydi va oqimning ma'nosi yo'qoladi.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/chat/sessions")
def chat_sessions(request: Request,
                  limit: int = Query(50, ge=1, le=200)):
    """Suhbatlar ro'yxati (arxivlanmaganlar, oxirgi faollik bo'yicha)."""
    _chat_tayyor()
    return ai_chat.list_sessions(company_id_of(request), limit=limit)


class ChatTiklashIn(BaseModel):
    """`tiklandi` — panelga tiklandi; `rad` — "Yangi suhbat" bosildi."""
    holat: Literal["tiklandi", "rad"]


@app.post("/chat/sessions/{session_id}/tiklash")
def chat_tiklash(session_id: str, body: ChatTiklashIn, request: Request):
    """Suhbat tiklanishini QAYD ETADI — `DAVOM_SOAT` chegarasi uchun.

    `ChatPanel` ochilganda oxirgi suhbatni davom ettiradi
    (`DAVOM_SOAT = 24`). Bu raqam O'LCHANMAGAN TAXMIN: u hech
    qanday ma'lumotdan chiqmagan.

    "Yangi suhbat" tugmasi — tiklanishdan chiqish yo'li, ya'ni
    UNING BOSILISHI chegara noto'g'ri ekanining signali. Global
    suhbat uchun 24 soat ko'p bo'lishi mumkin (mavzu o'zgaradi),
    tender uchun esa oz — shuning uchun `v_chat_tiklash` ikki
    kesimni ALOHIDA sanaydi.

    `company_id` SESSIYADAN va SQL SHARTIDA — boshqa kompaniyaning
    suhbatiga belgi qo'yib bo'lmaydi (IDOR himoyasi).
    """
    _chat_tayyor()
    cid = company_id_of(request)
    ok = ai_chat.tiklash_qayd(session_id, cid, body.holat)
    if not ok:
        raise xatolar.Xato("CHAT_SESSION_NOT_FOUND")
    return {"session_id": session_id, "holat": body.holat}


@app.get("/chat/sessions/{session_id}")
def chat_history(session_id: str, request: Request):
    """Bitta suhbat tarixi + iqtiboslar.

    Xatoli javoblar ham qaytadi (`error` maydoni bilan) — "jimgina
    o'tkazib yuborilmaydi" tamoyili: foydalanuvchi nima bo'lganini ko'rsin.
    """
    _chat_tayyor()
    company_id = company_id_of(request)
    try:
        s = ai_chat.load_session(session_id, company_id)
    except LookupError as e:
        raise xatolar.kodli(e, "CHAT_SESSION_NOT_FOUND")
    return {"session": s, "messages": ai_chat.messages(session_id)}


@app.delete("/chat/sessions/{session_id}", status_code=204)
def chat_archive(session_id: str, request: Request):
    """Suhbatni arxivlaydi. O'CHIRMAYDI — jurnal (`chat_tool_call`) va
    xarajat hisobi (`ai_usage`) tekshirish uchun kerak bo'lishi mumkin."""
    _chat_tayyor()
    if not ai_chat.archive_session(session_id, company_id_of(request)):
        raise xatolar.Xato("CHAT_SESSION_NOT_FOUND")
    return None


# =============================================================================
# CHATGA FAYL BIRIKTIRISH
# =============================================================================
# FAYL SUHBATGA TEGISHLI, GLOBAL EMAS. `chat_yuklama` uch joyda
# ijarachini tekshiradi: sessiya, yuklama va bog'lanish qatorining
# o'zi — oxirgisi trigger bilan, chunki "endpoint tekshiradi" degan
# va'da bitta unutilgan `WHERE` bilan buziladi.
#
# UMR: fayl DOIMIY saqlanadi. Foydalanuvchi biriktirishni uzsa
# (`uzildi_at`) fayl keyingi savollarda ishlatilmaydi, lekin
# O'CHIRILMAYDI — aks holda o'sha faylga tayangan eski javobning
# iqtibosi buziladi va tarixiy javobni qayta ko'rib bo'lmasdi (§15).
# =============================================================================
def _sessiya_yoki_404(session_id: str, cid: int) -> dict:
    try:
        return ai_chat.load_session(session_id, cid)
    except LookupError as e:
        raise xatolar.kodli(e, "CHAT_SESSION_NOT_FOUND")


class ChatSessionIn(BaseModel):
    tender_id: Optional[int] = None
    lang: str = "uz"
    manba: Optional[str] = None


@app.post("/chat/sessions", status_code=201)
def chat_session_yarat(body: ChatSessionIn, request: Request):
    """BO'SH suhbat ochadi.

    NEGA KERAK: fayl biriktirish `session_id` ni talab qiladi, sessiya
    esa ilgari FAQAT birinchi savol yuborilganda yaratilardi. Ya'ni
    foydalanuvchi faylni savoldan OLDIN biriktira olmasdi — yoki fayl
    brauzerda kutib turishi va "Ishlanmoqda" holati birinchi savoldan
    keyin boshlanishi kerak bo'lardi. Ikkinchisi §17 ni buzadi: holat
    KO'RINISHI kerak, savol berilishidan qat'i nazar.

    Bo'sh sessiya ARZON: bitta qator. `chat_session.manba` esa
    o'lchovda ishlatiladi, shuning uchun u shu yerda ham beriladi.
    """
    _chat_tayyor()
    cid = company_id_of(request)
    try:
        sid = ai_chat.create_session(cid, body.tender_id, None,
                                     body.lang, body.manba)
    except ValueError as e:
        raise xatolar.kodli(e, "FIELD_INVALID")
    return {"session_id": sid}


@app.post("/chat/sessions/{session_id}/fayl", status_code=201)
def chat_fayl_yukla(
    session_id: str, request: Request, background: BackgroundTasks,
    file: UploadFile = File(..., description="PDF / DOCX / XLSX / TXT / CSV / ZIP"),
):
    """Faylni suhbatga yuklaydi va ajratishni FONDA boshlaydi.

    `holat` DARHOL `yuklandi` bo'lib qaytadi — `tayyor` EMAS. UI
    "Processing" ko'rsatadi va `GET .../fayl` bilan kuzatadi.
    "Ready" ni AI haqiqatan ishlata olgandagina ko'rsatish §17
    talabi, va uni baza ham qo'riqlaydi (`yuklama_tayyor_matn_chk`).
    """
    _chat_tayyor()
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    _sessiya_yoki_404(session_id, cid)

    data = _yuklangani(file, max_mb=saqlash.MAX_UPLOAD_MB)
    y = yuklama.qabul_qil(cid, "chat", file.filename or "fayl", data,
                          aktor_id=k.actor_id)
    yuklama.chatga_biriktir(session_id, y["id"], cid)

    audit_yoz(k, request, amal="chat_fayl_biriktirildi",
              entity="chat_session", entity_id=0,
              keyin={"session_id": session_id, "yuklama_id": y["id"],
                     "nom": y["original_nom"], "sha256": y["sha256"]})

    background.add_task(yuklama.qayta_ishla, y["id"])
    return _fayl_json(y)


@app.get("/chat/sessions/{session_id}/fayl")
def chat_fayl_royxat(session_id: str, request: Request):
    """Suhbatga biriktirilgan FAOL fayllar va ularning holati."""
    _chat_tayyor()
    cid = company_id_of(request)
    _sessiya_yoki_404(session_id, cid)
    return [{"id": str(r["yuklama_id"]), "nom": r["original_nom"],
             "ext": r["ext"], "mime": r["mime"],
             "size_bytes": int(r["size_bytes"]), "holat": r["holat"],
             "xato": r["xato"], "matn_belgi": r["matn_belgi"],
             "sahifa_soni": r["sahifa_soni"],
             "chunk_soni": int(r["chunk_soni"] or 0)}
            for r in yuklama.chat_fayllari(session_id, cid)]


@app.delete("/chat/sessions/{session_id}/fayl/{yuklama_id}", status_code=204)
def chat_fayl_uz(session_id: str, yuklama_id: str, request: Request):
    """Biriktirishni UZADI — faylni o'chirmaydi (§22)."""
    _chat_tayyor()
    cid = company_id_of(request)
    k = kimlik_of(request, cid)
    _sessiya_yoki_404(session_id, cid)
    yuklama.chatdan_uz(session_id, yuklama_id, cid)
    audit_yoz(k, request, amal="chat_fayl_uzildi",
              entity="chat_session", entity_id=0,
              keyin={"session_id": session_id, "yuklama_id": yuklama_id})
    return None


@app.get("/chat/fayl/{yuklama_id}/download")
def chat_fayl_download(yuklama_id: str, request: Request):
    """Biriktirilgan faylni yuklab olish — ijarachi bilan."""
    cid = company_id_of(request)
    return _fayl_javobi(yuklama.ol(yuklama_id, cid), inline=False)


@app.get("/chat/usage")
def chat_usage(request: Request):
    """Joriy oydagi AI sarfi va limit.

    Interfeys buni ko'rsatadi: chat HAR SAVOLDA pul sarflaydi va
    foydalanuvchi qancha qolganini bilishi kerak (reja §9).
    """
    _chat_tayyor()
    return ai_chat.spend(company_id_of(request))
