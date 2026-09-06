# -*- coding: utf-8 -*-
"""
XATO KODLARI — API TILGA BOG'LIQ EMAS
======================================

O'LCHANGAN MUAMMO (2026-09-01). Interfeys uch tilli (uz/ru/en),
lekin server xatolari FAQAT o'zbekcha matn edi:

    api/main.py da 75 ta `HTTPException`
      shundan 28 tasi `detail=str(e)` — ya'ni ichki modulning
      o'zbekcha matni to'g'ridan-to'g'ri javobga tushardi

Bu ikki xil zarar berardi:

  1. RUS yoki INGLIZ tilida ishlayotgan foydalanuvchi xatoni
     O'ZBEKCHA ko'rardi. Interfeysning qolgan hammasi tarjima
     qilingan, xato esa yo'q — aynan noto'g'ri ketganda til
     yo'qolardi.
  2. `str(e)` ICHKI TAFSILOTNI oshkor qilardi: modul nomlari,
     SQL patch fayllari, jadval nomlari, chegaralar. Bu
     foydalanuvchiga ma'nosiz, hujumchiga esa xarita.

YECHIM: KOD — SHARTNOMА, MATN — KO'RINISH

Javob tanasi:

    {
      "error": {
        "code": "TENDER_NOT_FOUND",       <- BARQAROR, ASCII
        "params": {"id": 4211},           <- tarjimaga qo'yiladi
        "diagnostic_id": "a1b2c3d4"       <- jurnalga ulanish
      },
      "detail": "TENDER_NOT_FOUND"        <- eski o'quvchilar uchun
    }

`detail` ATAYLAB kod bilan to'ldirilgan, o'zbekcha matn bilan
emas: eski chaqiruvchi ham TILGA BOG'LIQ BO'LMAGAN qiymat oladi.
Odam o'qiydigan matn — interfeysning ishi (`err.<KOD>` kaliti,
`frontend/src/locales/`).

`diagnostic_id` — so'rov identifikatori (`X-Request-Id` sarlavhasi
bilan BIR XIL). Foydalanuvchi shu qiymatni aytsa, server jurnalidan
AYNAN o'sha so'rov topiladi. Ya'ni tafsilotni javobdan olib tashlash
yordamni QIYINLASHTIRMAYDI.

KOD RO'YXATI MUZLATILGAN (`KODLAR`)
------------------------------------
Kod ro'yxatda bo'lmasa `Xato` yaratilmaydi — imlo xatosi ISHLAB
CHIQISHDA chiqadi, ishlatishda emas. Har kodning STANDART HTTP
holati ham shu yerda: bitta ma'noli xato ikki endpointda ikki xil
holat qaytarmasin.

TARJIMA TO'LIQLIGI
------------------
`_tests/xato_kodlari_test.py` har kod uchun uz/ru/en tarjimasi
borligini tekshiradi. Frontend lug'atida `ru`/`en` `Record<TKey,…>`
deb e'lon qilingan, ya'ni kalit yetishmasa `tsc` ham yiqiladi —
ikki mustaqil to'siq.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger("api.xatolar")

#: KOD -> standart HTTP holati.
#:
#: TARTIB MA'NO BO'YICHA guruhlangan. Yangi kod qo'shilganda uchala
#: tilga tarjima ham qo'shilishi SHART (sinov tekshiradi).
KODLAR: Dict[str, int] = {
    # --- Kimlik va sessiya ---------------------------------------
    "AUTH_NOT_AUTHENTICATED": 401,
    "AUTH_TOKEN_MISSING": 401,
    "AUTH_TOKEN_MALFORMED": 401,
    "AUTH_SESSION_NOT_FOUND": 401,
    "AUTH_SESSION_EXPIRED": 401,
    "AUTH_INVALID_CREDENTIALS": 401,
    "AUTH_ACCOUNT_INACTIVE": 403,
    "AUTH_CSRF_MISMATCH": 403,
    "AUTH_SERVICE_KEY_FORBIDDEN": 403,
    "AUTH_LOGIN_REQUIRED": 403,
    "AUTH_ACCOUNT_NOT_FOUND": 404,
    "AUTH_USERNAME_TAKEN": 409,
    "AUTH_USERNAME_EMPTY": 400,
    "AUTH_RATE_LIMITED": 429,
    "COMPANY_ACCOUNT_MISSING": 503,
    "COMPANY_AMBIGUOUS": 409,

    # --- Parol ---------------------------------------------------
    "PASSWORD_REQUIRED": 400,
    "PASSWORD_CURRENT_REQUIRED": 400,
    "PASSWORD_CURRENT_WRONG": 400,
    "PASSWORD_TOO_SHORT": 400,
    "PASSWORD_TOO_LONG": 400,
    "PASSWORD_TOO_COMMON": 400,
    "PASSWORD_CONTAINS_LOGIN": 400,
    "PASSWORD_SAME_AS_OLD": 400,

    # --- Aktor va audit ------------------------------------------
    "ACTOR_FORBIDDEN": 403,
    "ACTOR_NOT_FOUND": 404,
    "ACTOR_REQUIRED": 403,
    "ACTOR_INACTIVE": 403,
    "ACTOR_HEADER_INVALID": 400,
    "ACTOR_ERP_SESSION_INVALID": 403,
    "ACTOR_ERP_MISMATCH": 409,
    "ACTOR_SERVICE_KEY_FORBIDDEN": 403,
    "AUDIT_WRITE_FAILED": 500,

    # --- Topilmadi -----------------------------------------------
    "TENDER_NOT_FOUND": 404,
    "DOCUMENT_NOT_FOUND": 404,
    "DOCUMENT_TEXT_NOT_FOUND": 404,
    "PRODUCT_NOT_FOUND": 404,
    "REQUIREMENT_NOT_FOUND": 404,
    "SEARCH_NOT_FOUND": 404,
    "SUBSCRIBER_NOT_FOUND": 404,
    "CHAT_SESSION_NOT_FOUND": 404,
    "LINK_NOT_FOUND": 404,
    "RECORD_NOT_FOUND": 404,
    "RECORD_ALREADY_CLOSED": 404,

    # --- So'rov mazmuni ------------------------------------------
    # `VALIDATION_ERROR` — JAVOBNING yuqori kodi (422). Quyidagi
    # maydon kodlari esa `error.fields[].code` da keladi: bitta
    # so'rovda bir necha maydon xato bo'lishi mumkin va "nimadir
    # noto'g'ri" deyish foydalanuvchiga QAYSI BIRINI tuzatishni
    # aytmaydi.
    "VALIDATION_ERROR": 422,
    "FIELD_REQUIRED": 400,
    "FIELD_INVALID": 400,
    "FIELD_EMPTY": 422,
    "FIELD_NEGATIVE": 422,
    "FIELD_TOO_LONG": 422,
    "FIELD_PERCENT_RANGE": 422,
    "FIELD_SCORE_RANGE": 422,
    "FIELD_PORT_RANGE": 422,
    "EMAIL_INVALID": 422,
    "DATE_ORDER_INVALID": 422,
    "INVALID_ENUM": 400,
    "EVIDENCE_TOO_LARGE": 400,
    "TRUST_LEVEL_INVALID": 400,
    "ACTOR_REQUIRED_FOR_TRUST": 400,
    "CODE_REQUIRED": 400,
    "CODE_NOT_ALLOWED": 400,
    "CORRECTED_VALUE_REQUIRED": 400,
    "STATS_LEVEL_INVALID": 400,

    # --- Fayl va import ------------------------------------------
    "FILE_TOO_LARGE": 413,
    "FILE_EMPTY": 422,
    "FILE_FORMAT_UNSUPPORTED": 422,
    "FILE_UNCOMPRESSED_TOO_LARGE": 413,
    "FILE_COMPRESSION_SUSPICIOUS": 400,
    "EXCEL_LIB_MISSING": 500,
    "EXCEL_UNREADABLE": 422,
    "CSV_ENCODING_UNKNOWN": 422,
    "HEADER_ROW_MISSING": 422,
    "CATALOG_IMPORT_INVALID": 400,
    "IMPORT_FORMAT_INVALID": 422,

    # --- Yuklangan fayl (schema_patch_yuklama.sql) ---------------
    #
    # `FILE_NOT_FOUND` 404: BEGONA fayl uchun ham AYNI SHU kod
    # qaytadi. 403 ("bor, lekin sizga emas") faylning MAVJUDLIGINI
    # tasdiqlardi va id ni taxmin qilib korpusni sanab chiqish
    # mumkin bo'lardi. Loyihada bu naqsh allaqachon ishlatiladi
    # (`DOC_UPDATE_SQL` da `company_id` WHERE bandida -> 404).
    "FILE_NOT_FOUND": 404,
    "FILE_TYPE_MISMATCH": 422,
    "FILE_NOT_READY": 409,
    "UPLOAD_QUOTA_EXCEEDED": 413,
    "STORAGE_BACKEND_UNKNOWN": 500,
    "STORAGE_WRITE_FAILED": 500,

    # --- Bildirishnoma -------------------------------------------
    "NOTIFY_CONFIG_INVALID": 400,
    "NOTIFY_EMAIL_REQUIRED": 400,
    "PUBLIC_URL_INVALID": 400,
    "SMTP_NOT_CONFIGURED": 400,
    "SMTP_PASSWORD_MISSING": 400,
    "SMTP_SEND_FAILED": 502,
    "TELEGRAM_TOKEN_MISSING": 400,
    "TELEGRAM_BOT_UNKNOWN": 400,
    "TELEGRAM_NOT_LINKED": 400,
    "TELEGRAM_NO_SUBSCRIBERS": 400,
    "TELEGRAM_UNREACHABLE": 502,
    "TELEGRAM_BAD_RESPONSE": 502,
    "TELEGRAM_API_ERROR": 400,

    # --- Sun'iy intellekt ----------------------------------------
    "AI_UNAVAILABLE": 503,
    "AI_PAID_DISABLED": 503,
    "AI_KEY_MISSING": 503,
    "AI_LIB_MISSING": 503,
    "AI_CALL_FAILED": 503,
    "AI_REFUSED": 503,
    "AI_EMPTY_RESPONSE": 503,
    "AI_TOKEN_LIMIT": 503,
    "AI_CHAT_DISABLED": 403,
    "AI_BUDGET_EXCEEDED": 429,
    "AI_DAILY_LIMIT": 429,
    "AI_SKIPPED": 409,
    "EMBED_UNAVAILABLE": 503,

    # --- Tashqi va tizim -----------------------------------------
    "DATABASE_UNAVAILABLE": 503,
    "SOURCE_FETCH_FAILED": 502,
    "PLATFORM_DOWNLOAD_UNSUPPORTED": 501,
    "SCHEMA_PATCH_MISSING": 503,
    "INTERNAL_ERROR": 500,
}


class Xato(ValueError, LookupError):
    """Biznes xatosi — KOD bilan, tilga bog'liq EMAS.

    NEGA IKKALA UMUMIY TURDAN MEROS (o'lchangan): loyihada mavjud
    qo'riqchilar aynan shu ikki turni ushlaydi —

        `except ValueError`    12 ta sinovda va modullarda
                               ("yaroqsiz kirish rad etiladimi")
        `except LookupError`   `ai_chat.load_session()` va uning
                               chegarasi ("sessiya topilmadimi")

    Yangi tur MUSTAQIL bo'lsa, ular JIMGINA o'tib ketardi — ya'ni
    qo'riqchilar o'chirilardi va buni hech narsa ko'rsatmasdi.
    Bu o'lchangan: `chat_test` aynan shu sababdan yiqildi.

    NARXI: `except ValueError` kodni YO'QOTISHI mumkin. Shuning
    uchun chegaradagi har `except ValueError` `kodli()` dan
    o'tadi — u kodli xatoni O'ZGARTIRMAY qaytaradi.

    `params` tarjimaga qo'yiladi (`{id}`, `{max_mb}`), ya'ni ular
    SON va ATAMA bo'lishi kerak — tayyor jumla emas. Jumlani
    tildan tilga o'zgartirish interfeysning ishi.

    `ichki` — texnik tafsilot. U FAQAT jurnalga yoziladi va
    javobga HECH QACHON tushmaydi. Ilgari `detail=str(e)` orqali
    aynan shu tafsilot mijozga ketardi.
    """

    def __init__(self, kod: str, params: Optional[Dict[str, Any]] = None,
                 ichki: Optional[str] = None, status: Optional[int] = None):
        if kod not in KODLAR:
            # ATAYLAB YIQILADI: noma'lum kodni jimgina o'tkazish
            # tarjimasiz xato demak va uni foydalanuvchi ko'rardi.
            raise KeyError(
                f"noma'lum xato kodi: {kod!r}. `api/xatolar.py:KODLAR` "
                f"ga qo'shing va uchala tilga tarjima yozing.")
        super().__init__(kod)
        self.kod = kod
        self.params = params or {}
        self.ichki = ichki
        self.status = status or KODLAR[kod]

    def __str__(self) -> str:
        q = f" {self.params}" if self.params else ""
        i = f" | {self.ichki}" if self.ichki else ""
        return f"{self.kod}{q}{i}"


def kodli(e: BaseException, kod: str,
          params: Optional[Dict[str, Any]] = None) -> "Xato":
    """Istalgan istisnoni KODLI xatoga aylantiradi.

    Xato ALLAQACHON kodli bo'lsa — O'ZGARTIRILMAYDI. Chegarada
    umumiy kod qo'yib yuborsak, modul bergan ANIQ kod (masalan
    `TELEGRAM_TOKEN_MISSING`) yo'qolib, o'rniga umumiy
    `FIELD_INVALID` chiqardi.

    `raise ... from e` YOZISH SHART EMAS: sabab shu yerda
    ulanadi, ya'ni chaqiruvchi uni unutib qololmaydi.
    """
    if isinstance(e, Xato):
        return e
    kod_ichki = getattr(e, "kod", "") or kod
    x = Xato(kod_ichki, params or getattr(e, "params", None), ichki=str(e))
    x.__cause__ = e
    return x


def tana(kod: str, params: Optional[Dict[str, Any]] = None,
         tashxis: str = "",
         maydonlar: Optional[list] = None) -> Dict[str, Any]:
    """Javob tanasi. YAGONA shakl — har ishlovchi shu yerdan oladi.

    `detail` ham kod bilan to'ldiriladi: eski o'quvchi (frontend
    `errMatn()`, `curl`, integratsiya) ham tilga bog'liq bo'lmagan
    qiymat ko'rsin.

    `maydonlar` — FAQAT 422 uchun: `[{"field": "smtp_port",
    "code": "FIELD_PORT_RANGE"}, ...]`. Maydon nomi SXEMA nomi,
    ya'ni tildan mustaqil; odam o'qiydigan nomga interfeys
    aylantiradi.
    """
    xato: Dict[str, Any] = {
        "code": kod,
        "params": params or {},
        "diagnostic_id": tashxis or None,
    }
    if maydonlar:
        xato["fields"] = maydonlar
    return {"error": xato, "detail": kod}


def jurnalga(kod: str, status: int, ichki: Optional[str] = None,
             params: Optional[Dict[str, Any]] = None) -> None:
    """Texnik tafsilot SERVER jurnaliga — javobga emas.

    5xx `error`, qolgani `warning`: mijoz xatosi (404, 400) server
    nosozligi emas va ogohlantirish darajasini bosib ketmasligi
    kerak.
    """
    yozuv = log.error if status >= 500 else log.warning
    yozuv("xato %s (%s)%s", kod, status,
          f": {ichki}" if ichki else "",
          extra={"xato_kodi": kod, "xato_status": status,
                 "xato_params": params or {}})
