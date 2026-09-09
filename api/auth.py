"""
KIMLIK (auth) — KOMPANIYA hisobi, paroli va sessiyasi.

Tender-AI ga KOMPANIYA kiradi, odam emas. Bu tender agregatori: kompaniya
unga ulanadi, e'lonlarni ko'radi va o'ziga keraklisini ERP ga uzatadi.

HODIMLAR BU YERDA EMAS. Odam — ERP ning tushunchasi: kim qaysi tenderni
oldi, kim mas'ul, kim shartnoma imzoladi — hammasi o'sha yerda
(`erp.app_user`, `erp.broker`). Tender-AI da tender olish ERP dan kelgan
hodimga biriktiriladi, ya'ni ism ERP dan keladi.

TUZATISH TARIXI (auth-1 -> tuzatish): dastlab bu modul HODIM hisoblarini
yuritardi (`app_user`, rollar, `broker_id`) va ERP tokenni shu yerdan
HTTP orqali tekshirardi. Kimlik teskari tomonda turgan edi. Endi:
  - hodim hisoblari ERP da (`erp.app_user`, `schema_patch_erp_6.sql`);
  - bu yerda faqat kompaniya hisobi (`company_account`);
  - ikkala tomon o'z kimligini O'ZI tekshiradi, tarmoqqa chiqmaydi.

QARORLAR (o'zgarmadi):
  - PAROL XESHI — PBKDF2-HMAC-SHA256, `hashlib` (stdlib). `bcrypt`/`passlib`
    qo'shilmaydi: yangi bog'liqlik, C-kengaytma va Windows'da o'rnatish
    muammosi evaziga bu hajmda foyda yo'q. Algoritm va iteratsiya soni
    USTUNDA saqlanadi, shuning uchun keyin kuchliroqqa o'tish migratsiyasiz.
  - TOKEN bazada sha256 XESHI ko'rinishida. Xom token faqat brauzerda.
  - "Login yoki parol noto'g'ri" — BITTA matn: qaysi biri xato ekanini
    aytish mavjud loginlarni topishga yo'l ochadi.
  - Hisob O'CHIRILMAYDI (`active=false`).
  - PAROL ALMASHTIRISH (auth-6) — hisob O'Z parolini almashtirganda
    ESKI parolni ham kiritadi, va almashtirishdan keyin BOSHQA
    sessiyalar o'chadi. Aks holda "parolimni o'zgartirdim" degan
    harakat o'g'irlangan tokenni bekor qilmasdi.
  - PAROL TANLASHDAN HIMOYA (auth-5) — urinishlar JURNALI
    (`public.login_attempt`), hisoblagich ustuni emas. Bloklash undan
    hisoblanadi va HISOBGA emas, (login + IP) juftligiga tegadi:
    kompaniya hisobi BITTA, uni yopish butun kompaniyani tizimdan
    uzib qo'yardi. ERP ning o'z jurnali alohida (`erp.login_attempt`)
    — chegara qoidasi ikki tomonga ham teng ishlaydi.

ROL YO'Q. Kompaniya hisobi — bitta daraja: kirgan bo'lsa, tender-ai ning
hammasini ko'radi. Huquq taqsimoti odamlar orasida bo'ladi, odamlar esa
ERP da; u yerda uch rol bor (`erp.app_user.role`).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import secrets
from typing import Any, Dict, List, Optional

from api import db

#: PBKDF2-HMAC-SHA256 iteratsiyalari.
#:
#: 240 000 dan 600 000 ga ko'tarildi (OWASP Password Storage Cheat
#: Sheet, 2023+ tavsiyasi PBKDF2-SHA256 uchun 600 000).
#:
#: NARXI O'LCHANDI (shu mashinada, 2026-08-31):
#:     240 000 -> 171 ms      600 000 -> 431 ms      1 000 000 -> 923 ms
#:
#: 431 ms kirish uchun maqbul. Xizmatni rad etish xavfi yo'q: xato
#: urinishlar `guard_attempts()` bilan XESHLASHDAN OLDIN to'siladi
#: (login+IP uchun 5 ta, IP uchun 25 ta / 15 daqiqa).
#:
#: ESKI XESHLAR BUZILMAYDI: format iteratsiya sonini O'ZI saqlaydi
#: (`pbkdf2_sha256$<iters>$<salt>$<hash>`), shuning uchun eskilari
#: o'z soni bilan tekshiriladi va muvaffaqiyatli kirishda JIMGINA
#: yangisiga ko'chiriladi (`_rehash_kerakmi`).
ITERATIONS = int(os.environ.get("AUTH_PBKDF2_ITERATIONS", "600000"))
SESSION_DAYS = int(os.environ.get("AUTH_SESSION_DAYS", "14"))

# --- PAROL TANLASHDAN HIMOYA ------------------------------------------------
# Raqamlar ERP dagi bilan BIR XIL: ikki eshik bir xil qoida bilan
# qo'riqlansin, aks holda "qaysi biri qancha ruxsat beradi" degan
# javobsiz savol paydo bo'ladi.
#: Qancha vaqt ichidagi xatolar sanaladi.
ATTEMPT_WINDOW_MIN = int(os.environ.get("AUTH_ATTEMPT_WINDOW_MIN", "15"))
#: Shu oynada bitta (login + IP) uchun ruxsat etilgan xato.
MAX_PER_USER = int(os.environ.get("AUTH_MAX_ATTEMPTS", "5"))
#: Shu oynada bitta IP uchun — HAMMA loginlar bo'yicha.
MAX_PER_IP = int(os.environ.get("AUTH_MAX_ATTEMPTS_IP", "25"))
#: Jurnal shuncha kundan keyin tozalanadi.
ATTEMPT_KEEP_DAYS = int(os.environ.get("AUTH_ATTEMPT_KEEP_DAYS", "90"))

# --- PAROL TALABI (auth-6) --------------------------------------------------
# UZUNLIK talab qilinadi, "katta harf + raqam + belgi" EMAS: murakkablik
# qoidalari amalda `Parol123!` ni keltirib chiqaradi va u monitorga
# yopishtiriladi. Uzun sodda ibora ancha kuchli va yodda qoladi
# (NIST 800-63B). Qoida ERP dagi bilan BIR XIL.
PASSWORD_MIN = int(os.environ.get("AUTH_PASSWORD_MIN", "10"))
#: Yuqori chegara — PBKDF2 ni ataylab uzun matn bilan yuklamasin.
PASSWORD_MAX = 200

#: Uzunlik talabidan (10) o'tib ketadigan, lekin baribir ko'p
#: uchraydigan parollar. Ro'yxat qisqa ATAYLAB.
WEAK_PASSWORDS = {
    "1234567890", "0123456789", "qwertyuiop", "parol12345", "password1",
    "password123", "administrator", "qwerty12345", "iloveyou11",
    "1qaz2wsx3edc", "passw0rd123", "welcome123",
}


def check_password(password: str, username: str = "") -> None:
    """Yangi parol talabga mos keladimi. Mos kelmasa `AuthError(400)`.

    Xato matni NIMA QILISH kerakligini aytadi."""
    p = password or ""
    if len(p) < PASSWORD_MIN:
        raise AuthError(f"Parol kamida {PASSWORD_MIN} belgi bo'lsin.", 400,
                        kod="PASSWORD_TOO_SHORT",
                        params={"min": PASSWORD_MIN})
    if len(p) > PASSWORD_MAX:
        raise AuthError(f"Parol {PASSWORD_MAX} belgidan uzun bo'lmasin.", 400,
                        kod="PASSWORD_TOO_LONG",
                        params={"max": PASSWORD_MAX})
    if p.lower() in WEAK_PASSWORDS:
        raise AuthError("Bu parol juda ko'p ishlatiladi.", 400,
                        kod="PASSWORD_TOO_COMMON")
    u = (username or "").strip().lower()
    if u and u in p.lower():
        raise AuthError("Parol login nomini o'z ichiga olmasin.", 400,
                        kod="PASSWORD_CONTAINS_LOGIN")

# --- SERVER-SERVER kaliti (ERP uchun) ---------------------------------------
# ERP odam nomidan emas, O'Z NOMIDAN keladi: cheklist qoidasi, hujjat
# shabloni, xabar yuborish. Uning uchun kompaniya sessiyasi mos emas —
# sessiya brauzerda tug'iladi va muddati tugaydi, ERP esa fonda (masalan
# tungi eslatma skriptida) ham ishlaydi.
#
# Shuning uchun ikkinchi yo'l: `X-Service-Key` sarlavhasi. U FAQAT
# server-server chaqiruvida ishlatiladi va BRAUZERGA HECH QACHON
# tushmaydi (aks holda uni JS to'plamidan o'qib olish mumkin bo'lardi).
SERVICE_KEY = os.environ.get("ERP_SERVICE_KEY", "").strip()


def service_ready() -> bool:
    return bool(SERVICE_KEY)


def verify_service(key: Optional[str]) -> bool:
    """Doimiy vaqtli solishtirish. Kalit sozlanmagan bo'lsa HAR DOIM
    False: "sozlanmagan" degani "hammaga ochiq" degani emas."""
    if not SERVICE_KEY or not key:
        return False
    return hmac.compare_digest(SERVICE_KEY, key.strip())


class AuthError(RuntimeError):
    """Kirish/huquq xatosi -> main.py da 401/403.

    `kod` — TILGA BOG'LIQ BO'LMAGAN xato kodi
    (`api/xatolar.py:KODLAR`). `msg` esa SERVER JURNALI uchun: u
    javobga TUSHMAYDI. Ilgari `detail=str(e)` orqali aynan shu
    o'zbekcha matn mijozga ketardi va rus/ingliz tilidagi
    foydalanuvchi uni o'zbekcha ko'rardi.

    `kod` MAJBURIY EMAS deb qoldirilmadi: standart qiymat qo'ysak,
    yangi `raise` kodsiz o'tib ketardi va u tarjimasiz xato
    bo'lardi. Sinov kodsiz `raise` ni sanaydi va nol talab qiladi.
    """

    def __init__(self, msg: str, code: int = 401, *, kod: str = "",
                 params: Optional[Dict[str, Any]] = None):
        super().__init__(msg)
        self.code = code
        self.kod = kod
        self.params = params or {}


# ---------------------------------------------------------------------------
# Parol
# ---------------------------------------------------------------------------
def hash_password(password: str, *, iterations: int = ITERATIONS,
                  salt: Optional[bytes] = None) -> str:
    if not password or len(password) < 6:
        raise AuthError("Parol kamida 6 belgidan iborat bo'lishi kerak.", 400,
                        kod="PASSWORD_TOO_SHORT", params={"min": 6})
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Doimiy vaqtli solishtirish (`hmac.compare_digest`) — vaqt bo'yicha
    sizib chiqishning oldini oladi."""
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
    except (ValueError, AttributeError):
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                             bytes.fromhex(salt_hex), int(iters))
    return hmac.compare_digest(dk.hex(), hash_hex)


def _rehash_kerakmi(stored: str) -> bool:
    """Saqlangan xesh HOZIRGI kuchdan pastmi.

    Iteratsiya soni oshirilganda eski hisoblar ESKI kuchda qolib
    ketardi va buni hech narsa ko'rsatmasdi. Endi ular kirish paytida
    (parol qo'lda bo'lganda — yagona imkoniyat) ko'chiriladi.
    """
    try:
        algo, iters, _s, _h = stored.split("$")
    except (ValueError, AttributeError):
        return False
    return algo == "pbkdf2_sha256" and int(iters) < ITERATIONS


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
_ACC_COLS = ("id, username, company_name, email, active, last_login_at, "
             "created_at")

ACC_BY_NAME_SQL = (f"SELECT {_ACC_COLS}, password_hash FROM company_account "
                   "WHERE username = %(username)s")
ACC_BY_ID_SQL = f"SELECT {_ACC_COLS} FROM company_account WHERE id = %(id)s"
#: Parol almashtirishda ESKI xesh kerak. Bu so'rov `shape()` ga
#: BERILMAYDI — xesh javobga chiqmasligi kerak.
ACC_HASH_BY_ID_SQL = (f"SELECT {_ACC_COLS}, password_hash FROM company_account "
                      "WHERE id = %(id)s")
ACCOUNTS_SQL = (f"SELECT {_ACC_COLS} FROM company_account "
                "ORDER BY active DESC, username")

ACC_INSERT_SQL = f"""
INSERT INTO company_account (username, company_name, password_hash, email)
VALUES (%(username)s, %(company_name)s, %(password_hash)s, %(email)s)
RETURNING {_ACC_COLS}
"""

ACC_UPDATE_SQL = f"""
UPDATE company_account SET
    company_name=%(company_name)s, email=%(email)s, active=%(active)s,
    updated_at=now()
WHERE id = %(id)s
RETURNING {_ACC_COLS}
"""

PASSWORD_UPDATE_SQL = ("UPDATE company_account SET password_hash=%(h)s, "
                       "updated_at=now() WHERE id=%(id)s RETURNING id")

SESSION_INSERT_SQL = """
INSERT INTO company_session
    (account_id, token_hash, expires_at, user_agent, csrf_token)
VALUES (%(account_id)s, %(token_hash)s, %(expires_at)s, %(user_agent)s,
        %(csrf_token)s)
RETURNING id
"""

# Ustunlar ATAYLAB to'liq yozilgan: `_ACC_COLS` ni almashtirish bilan
# yasashga urinish bir marta ustun nomini buzgan edi ("broker_u.id").
SESSION_GET_SQL = """
SELECT s.id AS session_id, s.expires_at, s.csrf_token,
       a.id, a.username, a.company_name, a.email, a.active,
       a.last_login_at, a.created_at
FROM company_session s JOIN company_account a ON a.id = s.account_id
WHERE s.token_hash = %(token_hash)s
"""

SESSION_TOUCH_SQL = ("UPDATE company_session SET last_seen_at = now() "
                     "WHERE id = %(id)s RETURNING id")
SESSION_DELETE_SQL = ("DELETE FROM company_session WHERE token_hash = %(token_hash)s "
                      "RETURNING id")
SESSION_CLEAN_SQL = ("DELETE FROM company_session WHERE expires_at < now() "
                     "RETURNING id")

# Parol almashgach BOSHQA sessiyalar o'chadi (auth-6). `keep` — hozirgi
# sessiya: parolni almashtirgan odam tizimdan chiqib qolmasin.
_OTHER_SESSIONS = ("FROM company_session WHERE account_id = %(account_id)s "
                   "AND (%(keep)s::text IS NULL OR token_hash <> %(keep)s)")
SESSION_OTHERS_COUNT_SQL = f"SELECT count(*) AS n {_OTHER_SESSIONS}"
SESSION_KILL_OTHERS_SQL = f"DELETE {_OTHER_SESSIONS} RETURNING id"
LOGIN_STAMP_SQL = ("UPDATE company_account SET last_login_at = now() "
                   "WHERE id = %(id)s RETURNING id")


# --- Kirish urinishlari (auth-5) -------------------------------------------
#: Jadval bormi. Patch qo'llanmagan bo'lsa himoya JIM o'chadi — eski baza
#: bilan ilova ko'tarilishdan to'xtamasligi kerak.
ATTEMPT_SCHEMA_SQL = ("SELECT 1 AS x FROM information_schema.tables "
                      "WHERE table_schema = 'public' "
                      "AND table_name = 'login_attempt'")

ATTEMPT_INSERT_SQL = """
INSERT INTO public.login_attempt (username, ip, ok, user_agent)
VALUES (%(username)s, %(ip)s, %(ok)s, %(user_agent)s)
RETURNING id
"""

# OXIRGI MUVAFFAQIYATLI KIRISHDAN KEYINGI xatolar sanaladi: to'g'ri parol
# zanjirni UZADI.
ATTEMPT_COUNT_SQL = """
SELECT count(*) AS n, max(created_at) AS last_at
FROM public.login_attempt a
WHERE a.ok = false
  AND a.created_at > now() - (%(mins)s || ' minutes')::interval
  AND a.created_at > COALESCE((
        SELECT max(s.created_at) FROM public.login_attempt s
        WHERE s.ok = true AND s.username = %(username)s
          AND (%(ip)s::inet IS NULL OR s.ip = %(ip)s::inet)
      ), '-infinity'::timestamptz)
  AND a.username = %(username)s
  AND (%(ip)s::inet IS NULL OR a.ip = %(ip)s::inet)
"""

ATTEMPT_IP_COUNT_SQL = """
SELECT count(*) AS n, max(created_at) AS last_at
FROM public.login_attempt
WHERE ok = false AND ip = %(ip)s::inet
  AND created_at > now() - (%(mins)s || ' minutes')::interval
"""

ATTEMPT_CLEAN_SQL = ("DELETE FROM public.login_attempt "
                     "WHERE created_at < now() - (%(days)s || ' days')::interval "
                     "RETURNING id")

ATTEMPT_LIST_SQL = """
SELECT a.id, a.username, host(a.ip) AS ip, a.ok, a.user_agent, a.created_at,
       (c.id IS NOT NULL) AS known_user
FROM public.login_attempt a
LEFT JOIN company_account c ON c.username = a.username
WHERE (%(only_failed)s = false OR a.ok = false)
  AND a.created_at > now() - (%(hours)s || ' hours')::interval
ORDER BY a.created_at DESC
LIMIT %(limit)s
"""


def _attempts_ready() -> bool:
    """Jurnal jadvali bormi (schema_patch_auth_4.sql qo'llanganmi)."""
    return bool(db.query_one(ATTEMPT_SCHEMA_SQL))


def _clean_ip(ip: Optional[str]) -> Optional[str]:
    """Manzilni tozalash. Yaroqsiz qiymat `None` ga aylanadi — jurnal
    yozuvi shu sabab BUTUNLAY yo'qolmasligi kerak."""
    ip = (ip or "").strip()
    if not ip or ip in ("unknown", "testclient"):
        return None
    return ip[:45] or None


def record_attempt(username: str, ip: Optional[str], ok: bool, *,
                   user_agent: Optional[str] = None) -> None:
    """Urinishni jurnalga yozish. PAROL YOZILMAYDI."""
    if not _attempts_ready():
        return
    try:
        db.execute_returning(ATTEMPT_INSERT_SQL, {
            "username": (username or "")[:150], "ip": _clean_ip(ip),
            "ok": ok, "user_agent": (user_agent or "")[:300] or None})
    except Exception:
        # Jurnal yozilmasa ham kirish ishlashi kerak.
        pass


def guard_attempts(username: str, ip: Optional[str]) -> None:
    """Bloklangan bo'lsa `AuthError(429)` — parol TEKSHIRILMASDAN OLDIN.

    Ikki kesim: (login + IP) va IP (hamma loginlar bo'yicha, login
    nomini aylantirib chiqishga qarshi).

    IP NOMA'LUM bo'lsa cheklov faqat login bo'yicha qoladi: to'siq
    VAQTINCHA, hisob esa tegilmagan holda qoladi."""
    if not _attempts_ready():
        return
    uname = (username or "").strip().lower()
    addr = _clean_ip(ip)

    r = db.query_one(ATTEMPT_COUNT_SQL, {
        "username": uname, "ip": addr, "mins": ATTEMPT_WINDOW_MIN}) or {}
    if (r.get("n") or 0) >= MAX_PER_USER:
        raise _blocked(r["last_at"])

    if addr:
        r2 = db.query_one(ATTEMPT_IP_COUNT_SQL,
                          {"ip": addr, "mins": ATTEMPT_WINDOW_MIN}) or {}
        if (r2.get("n") or 0) >= MAX_PER_IP:
            raise _blocked(r2["last_at"])


def _blocked(last_at) -> "AuthError":
    """429 va necha soniyadan keyin urinish mumkinligi.

    Qolgan vaqt AYTILADI: odam "buzildimi?" deb o'ylab qolmasin.
    Hujumchiga bu foyda bermaydi — u baribir kutishi kerak."""
    wait = ATTEMPT_WINDOW_MIN * 60
    if last_at is not None:
        now = _dt.datetime.now(_dt.timezone.utc)
        wait = max(1, int(ATTEMPT_WINDOW_MIN * 60 - (now - last_at).total_seconds()))
    mins = max(1, round(wait / 60))
    e = AuthError(f"Juda ko'p urinish ({mins} daqiqa).", 429,
                  kod="AUTH_RATE_LIMITED",
                  params={"daqiqa": mins, "kutish_soniya": wait})
    e.retry_after = wait
    return e


def attempts(hours: int = 24, limit: int = 100,
             only_failed: bool = True) -> List[Dict[str, Any]]:
    """"Kim, qayerdan va qachon kirishga urindi".

    `known_user` — bunday login BOR yoki YO'Q. Yo'q loginlar bilan
    urinish hujumning eng ko'p uchraydigan izi."""
    if not _attempts_ready():
        raise AuthError("Urinishlar jurnali yo'q: schema_patch_auth_4.sql "
                        "bazaga qo'llanmagan.", 503,
                        kod="SCHEMA_PATCH_MISSING",
                        params={"patch": "schema_patch_auth_4.sql"})
    return [{**r, "created_at": (r["created_at"].isoformat()
                                 if r["created_at"] else None)}
            for r in db.query(ATTEMPT_LIST_SQL, {
                "hours": max(1, hours), "limit": max(1, min(limit, 1000)),
                "only_failed": bool(only_failed)})]


def schema_ready() -> bool:
    """Patch qo'llanmagan bo'lsa ilova YIQILMAYDI — interfeys buni ochiq
    aytadi (notify_lang.md uslubi)."""
    return bool(db.query_one(
        "SELECT 1 AS x FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='company_account'"))


def _need_schema() -> None:
    if not schema_ready():
        raise AuthError("Auth jadvallari yo'q: schema_patch_auth_2.sql "
                        "bazaga qo'llanmagan.", 503,
                        kod="SCHEMA_PATCH_MISSING",
                        params={"patch": "schema_patch_auth_2.sql"})


# ---------------------------------------------------------------------------
# Shakllantirish
# ---------------------------------------------------------------------------
def shape(r: Dict[str, Any]) -> Dict[str, Any]:
    """Parol xeshi JAVOBGA HECH QACHON tushmaydi.

    CSRF tokeni esa QASDDAN qo'shiladi (bo'lsa): u sir emas — sahifa uni
    `HttpOnly` bo'lmagan cookie'dan ham o'qiy oladi. Javobda berilishi
    sahifa yangilanganda uni login'siz tiklash imkonini beradi."""
    out = {
        "id": r["id"], "username": r["username"],
        "company_name": r["company_name"], "email": r["email"],
        "active": r["active"],
        "last_login_at": (r["last_login_at"].isoformat()
                          if r.get("last_login_at") else None),
    }
    if r.get("csrf_token"):
        out["csrf"] = r["csrf_token"]
    return out


# ---------------------------------------------------------------------------
# Amallar
# ---------------------------------------------------------------------------
def login(username: str, password: str, *,
          user_agent: Optional[str] = None,
          ip: Optional[str] = None) -> Dict[str, Any]:
    _need_schema()
    uname = (username or "").strip().lower()

    # Bloklash PAROLNI TEKSHIRISHDAN OLDIN: to'silgan urinish qimmat
    # xeshlashni ham ishga tushirmasligi kerak, aks holda cheklovning
    # o'zi yuk keltirish vositasiga aylanardi.
    guard_attempts(uname, ip)

    row = db.query_one(ACC_BY_NAME_SQL, {"username": uname})

    # Hisob topilmasa ham parolni TEKSHIRAMIZ (soxta xesh bilan): aks holda
    # javob vaqti "bunday login bormi?" degan savolga javob berardi.
    stored = row["password_hash"] if row else hash_password("x" * 12)
    ok = verify_password(password, stored)
    if not row or not ok or not row["active"]:
        record_attempt(uname, ip, False, user_agent=user_agent)
        raise AuthError("Login yoki parol noto'g'ri.", 401,
                        kod="AUTH_INVALID_CREDENTIALS")

    # Muvaffaqiyatli urinish ham yoziladi: u xatolar zanjirini UZADI.
    record_attempt(uname, ip, True, user_agent=user_agent)

    # SHAFFOF QAYTA XESHLASH. Parol ochiq holda FAQAT shu yerda bo'ladi,
    # ya'ni kuchni oshirishning yagona imkoniyati — kirish payti.
    # Xato bo'lsa kirish TO'XTAMAYDI: eski xesh ham yaroqli, shunchaki
    # kuchsizroq. Kirishni to'xtatish foydalanuvchini "parolim to'g'ri,
    # lekin kirmayapman" holatiga tashlardi.
    if _rehash_kerakmi(row["password_hash"]):
        try:
            db.execute_returning(PASSWORD_UPDATE_SQL,
                                 {"id": row["id"], "h": hash_password(password)})
        except Exception:                                     # noqa: BLE001
            pass
    db.execute_returning(SESSION_CLEAN_SQL)      # muddati o'tganlarni tozalash
    if _attempts_ready():
        db.execute_returning(ATTEMPT_CLEAN_SQL, {"days": ATTEMPT_KEEP_DAYS})
    token = secrets.token_urlsafe(32)
    # CSRF tokeni SESSIYA tokenidan ALOHIDA va boshqa maqsadda:
    #   sessiya tokeni — "kimsan" (HttpOnly cookie, sahifa ko'rmaydi);
    #   CSRF tokeni   — "so'rovni bizning sahifamiz yubordimi" (ochiq).
    csrf = secrets.token_urlsafe(24)
    expires = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=SESSION_DAYS)
    db.execute_returning(SESSION_INSERT_SQL, {
        "account_id": row["id"], "token_hash": _token_hash(token),
        "expires_at": expires,
        "user_agent": (user_agent or "")[:300] or None,
        "csrf_token": csrf})
    db.execute_returning(LOGIN_STAMP_SQL, {"id": row["id"]})
    return {"token": token, "csrf": csrf, "expires_at": expires.isoformat(),
            "account": {**shape(row), "csrf": csrf}}


def verify(token: str) -> Dict[str, Any]:
    """Token -> kompaniya hisobi. Muddati o'tgan yoki bekor qilingan bo'lsa
    401."""
    _need_schema()
    if not token:
        raise AuthError("Token yo'q.", 401, kod="AUTH_TOKEN_MISSING")
    r = db.query_one(SESSION_GET_SQL, {"token_hash": _token_hash(token)})
    if not r:
        raise AuthError("Sessiya topilmadi.", 401,
                        kod="AUTH_SESSION_NOT_FOUND")
    if r["expires_at"] <= _dt.datetime.now(_dt.timezone.utc):
        db.execute_returning(SESSION_DELETE_SQL, {"token_hash": _token_hash(token)})
        raise AuthError("Sessiya muddati tugadi.", 401,
                        kod="AUTH_SESSION_EXPIRED")
    if not r["active"]:
        raise AuthError("Hisob faol emas.", 403,
                        kod="AUTH_ACCOUNT_INACTIVE")
    db.execute_returning(SESSION_TOUCH_SQL, {"id": r["session_id"]})
    return shape(r)


def logout(token: str) -> bool:
    _need_schema()
    return bool(db.execute_returning(SESSION_DELETE_SQL,
                                     {"token_hash": _token_hash(token)}))


# --- hisoblarni boshqarish ---------------------------------------------------
# Odatda BITTA hisob bo'ladi. Yaratish `create_company.py` orqali: kompaniya
# hisobini brauzerdan yaratadigan endpoint kerak emas va u ochiq eshik
# bo'lardi.
def accounts() -> List[Dict[str, Any]]:
    _need_schema()
    return [shape(r) for r in db.query(ACCOUNTS_SQL)]


def create_account(username: str, company_name: str, password: str, *,
                   email: Optional[str] = None) -> Dict[str, Any]:
    _need_schema()
    uname = (username or "").strip().lower()
    if not uname:
        raise AuthError("Login bo'sh.", 400, kod="AUTH_USERNAME_EMPTY")
    if db.query_one(ACC_BY_NAME_SQL, {"username": uname}):
        raise AuthError(f"'{uname}' logini band.", 409,
                        kod="AUTH_USERNAME_TAKEN", params={"login": uname})
    # Talab YARATISHDA ham amal qiladi: aks holda zaif parol tizimga
    # birinchi kundanoq kirib qolardi.
    check_password(password, uname)
    return shape(db.execute_returning(ACC_INSERT_SQL, {
        "username": uname, "company_name": (company_name or uname).strip(),
        "password_hash": hash_password(password), "email": email}))


def update_account(account_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    _need_schema()
    cur = db.query_one(ACC_BY_ID_SQL, {"id": account_id})
    if not cur:
        raise AuthError("Hisob topilmadi.", 404,
                        kod="AUTH_ACCOUNT_NOT_FOUND")
    return shape(db.execute_returning(ACC_UPDATE_SQL, {
        "id": account_id,
        "company_name": (data.get("company_name")
                         or cur["company_name"]).strip(),
        "email": data.get("email"),
        "active": bool(data.get("active", cur["active"]))}))


def set_password(account_id: int, password: str, *,
                 current: Optional[str] = None,
                 keep_token: Optional[str] = None) -> Dict[str, Any]:
    """Parolni almashtirish.

    `current` — ESKI parol. Interfeysdan kelgan almashtirishda u SHART:
    ochiq qolgan kompyuter yoki o'g'irlangan sessiya bilan begona odam
    parolni o'zgartirib, hisobni butunlay egallab olmasin. CLI
    (`create_company.py`) uni bermaydi — u serverda ishlaydi va
    "parolni unutdim" holatini hal qiladi.

    `keep_token` — chaqiruvchining hozirgi tokeni. Uning sessiyasi
    qoladi, hisobning QOLGAN sessiyalari esa o'chadi: aks holda
    parolni almashtirish o'g'irlangan tokenni bekor qilmasdi."""
    _need_schema()
    row = db.query_one(ACC_HASH_BY_ID_SQL, {"id": account_id})
    if not row:
        raise AuthError("Hisob topilmadi.", 404,
                        kod="AUTH_ACCOUNT_NOT_FOUND")

    if current is not None and not verify_password(current, row["password_hash"]):
        # 400 (401 emas): kim ekani MA'LUM va sessiyasi joyida.
        raise AuthError("Joriy parol noto'g'ri.", 400,
                        kod="PASSWORD_CURRENT_WRONG")

    check_password(password, row["username"])
    # "Eskisidan farq qilsin" faqat O'ZI ALMASHTIRAYOTGANDA. Qoidaning
    # maqsadi — parolni yangilayapman deb o'sha parolni qayta yozib
    # qo'ymaslik. Admin (yoki CLI) ma'lum parolni QAYTA TIKLAYOTGAN
    # bo'lsa, bu boshqa amal va uni taqiqlash o'rnatishni buzardi.
    if current is not None and verify_password(password, row["password_hash"]):
        raise AuthError("Yangi parol eskisidan farq qilsin.", 400,
                        kod="PASSWORD_SAME_AS_OLD")

    db.execute_returning(PASSWORD_UPDATE_SQL,
                         {"id": account_id, "h": hash_password(password)})
    p = {"account_id": account_id,
         "keep": (_token_hash(keep_token) if keep_token else None)}
    # Avval SANAYMIZ: `execute_returning` bitta qator qaytaradi.
    n = db.scalar(SESSION_OTHERS_COUNT_SQL, p) or 0
    db.execute_returning(SESSION_KILL_OTHERS_SQL, p)
    return {"ok": True, "closed_sessions": int(n)}


# ---------------------------------------------------------------------------
# YAGONA KOMPANIYA — odam nomidan kelmagan so'rovlar uchun (J1.6)
#
# NEGA KERAK: ba'zi ish oqimlari sessiyasiz bajariladi —
#   * ERP `X-Service-Key` bilan keladi (odam emas, tizim);
#   * bildirishnoma tsikli ETL dan keyin yuradi (hech kim kirmagan).
# Ularga ham `company_id` kerak, lekin uni TAXMIN QILIB bo'lmaydi: xato
# tanlov — ma'lumotni boshqa ijarachiga berib yuborish demak.
#
# Shuning uchun qoida qat'iy: yagona FAOL hisob bo'lsa — o'sha; bir nechta
# bo'lsa — ANIQ xato. Bu `schema_patch_multitenant.sql` dagi ijarachi
# tanlash mantig'ining aynan o'zi.
# ---------------------------------------------------------------------------
ACTIVE_COMPANIES_SQL = ("SELECT id, username FROM company_account "
                        "WHERE active ORDER BY id")


def active_companies() -> List[Dict[str, Any]]:
    """Faol kompaniya hisoblari (`id`, `username`), id bo'yicha tartibda.

    NEGA ALOHIDA. Rejalashtirilgan ishlar (bildirishnoma tsikli) HAR
    ijarachi uchun yurishi kerak. `sole_company_id()` esa aynan
    BITTASINI talab qiladi va ikkinchi kompaniya qo'shilgan kunda
    xato beradi. Ikkala ehtiyoj ham haqiqiy, lekin ular BOSHQA
    savol: "kim?" va "kimlar?".
    """
    return db.query(ACTIVE_COMPANIES_SQL)


def sole_company_id() -> int:
    """Yagona faol kompaniya id si. Aniqlab bo'lmasa `AuthError`."""
    rows = active_companies()
    if len(rows) == 1:
        return int(rows[0]["id"])
    if not rows:
        raise AuthError("Faol kompaniya hisobi yo'q.", 503,
                        kod="COMPANY_ACCOUNT_MISSING")
    ro = ", ".join(f"{r['id']}({r['username']})" for r in rows)
    raise AuthError(
            f"Bir nechta faol kompaniya: {ro}.", 409,
            kod="COMPANY_AMBIGUOUS")
