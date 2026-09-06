"""
DB qatlami — PostgreSQL connection pool va query yordamchilari.

Dizayn:
  - .env dan XT_DB_DSN o'qiladi (ETL bilan bir xil o'zgaruvchi).
  - psycopg2 ThreadedConnectionPool ishlatamiz: FastAPI sync-endpointlarni
    threadpool'da ishlatadi, shuning uchun thread-safe pool kerak.
  - RealDictCursor — natijalar dict ko'rinishida (JSON'ga oson).
  - Pool lifespan'da (main.py) init/close qilinadi.
"""
import os
import re
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import PoolError, ThreadedConnectionPool

_pool: Optional[ThreadedConnectionPool] = None


class DBUnavailable(RuntimeError):
    """Baza mavjud emas yoki so'rov muvaffaqiyatsiz — API buni 503 ga aylantiradi."""


def init_pool() -> None:
    """Pool'ni yaratadi. main.py lifespan startup'da chaqiriladi."""
    global _pool
    if _pool is not None:
        return
    dsn = os.environ.get("XT_DB_DSN")
    if not dsn:
        raise RuntimeError(
            "XT_DB_DSN o'rnatilmagan. .env faylini yarating (.env.example dan nusxa)."
        )
    mn = int(os.environ.get("DB_POOL_MIN", "1"))
    mx = int(os.environ.get("DB_POOL_MAX", "8"))
    try:
        _pool = ThreadedConnectionPool(mn, mx, dsn=dsn, cursor_factory=RealDictCursor)
    except psycopg2.Error as e:
        raise DBUnavailable(f"Pool yaratib bo'lmadi: {e}") from e


def close_pool() -> None:
    """Pool'ni yopadi. lifespan shutdown'da chaqiriladi."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


#: Hovuz bo'sh bo'lganda QANCHA KUTILADI (sekund).
#:
#: O'LCHANGAN NUQSON (2026-09-02). `ThreadedConnectionPool.getconn()`
#: hovuz to'lgan bo'lsa DARHOL `PoolError` beradi. U `psycopg2.Error`
#: avlodi, ya'ni `DBUnavailable` ga o'raladi va mijozga **503**
#: ketadi. Foydalanuvchi buni "server ishlamayapti" deb o'qiydi,
#: aslida server ISHLAYAPTI -- shunchaki band edi.
#:
#: O'LCHANDI: 12 parallel so'rov, hovuz 8 ta -> 4 tasi darhol 503.
#: Aynan shu "Sizga mos" sahifasida ko'ringan: sahifa bir necha
#: so'rovni birga yuboradi va ular bir-birini yiqitardi.
#:
#: FastAPI sync-endpointlarni ~40 ta ipda yuritadi, DB hovuzi esa
#: 8 ta. Ya'ni 32 ta ip hech qachon ulanish OLA OLMASDI.
#:
#: KUTISH -- YASHIRISH EMAS. Chegara tugagach xato BARIBIR
#: chiqariladi: haqiqiy ortiqcha yuklama ko'rinib turishi kerak.
_KUTISH_SEK = float(os.environ.get("DB_POOL_WAIT_SEC", "10"))
#: Qayta urinishlar orasidagi tanaffus.
_TANAFFUS_SEK = 0.05

#: Ulangandan keyin qaysi ROLGA tushiladi (bo'sh — tushilmaydi).
#:
#: Ishlab chiqarishda ilova `tai_app` bilan ULANISHI kerak. Lekin
#: sinov muhitida `postgres` ishlatiladi va superuser huquq
#: tekshiruvlarini chetlab o'tadi — grant asosidagi himoyalar
#: sinalmay qoladi. `DB_SET_ROLE=tai_app` shu bo'shliqni yopadi.
_SET_ROLE = (os.environ.get("DB_SET_ROLE") or "").strip()

def rol_ornat(nom: str) -> None:
    """`DB_SET_ROLE` ni ISH PAYTIDA o'rnatadi.

    FAQAT SINOV QATLAMI UCHUN. `_SET_ROLE` modul yuklanganda
    o'qiladi, ya'ni `os.environ` ni keyin o'zgartirish HECH
    NARSAGA ta'sir qilmasdi -- sinov rejimni to'g'riladim deb
    o'ylab, aslida superuser bilan yuraverardi (3-sinf: o'lchov
    qo'shildi-yu, hech qachon o'lchamadi).

    Nom `_quote_ident` bilan tekshiriladi va HOVUZ QAYTA OCHILADI:
    ochiq ulanishlar eski rol bilan qolib ketmasin.

    Ilova va ETL bu funksiyani CHAQIRMAYDI: ular uchun rol DSN
    yoki `.env` bilan beriladi.
    """
    global _SET_ROLE
    _quote_ident(nom)                 # yaroqsiz nom SHU YERDA yiqiladi
    _SET_ROLE = nom
    os.environ["DB_SET_ROLE"] = nom   # bola jarayonlar ham ko'rsin
    if _pool is not None:
        close_pool()
        init_pool()


def _quote_ident(nom: str) -> str:
    """Rol nomini SQL identifikatori sifatida qo'shtirnoqlaydi.

    `SET ROLE` parametr QABUL QILMAYDI (u utility buyrug'i), ya'ni
    nom matnga qo'shiladi. Shuning uchun u YOPIQ ro'yxat bilan
    cheklanadi: faqat harf, raqam va pastki chiziq.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nom):
        raise DBUnavailable(f"`DB_SET_ROLE` nomi yaroqsiz: {nom!r}")
    return '"' + nom + '"'


@contextmanager
def get_conn():
    """Pool'dan connection oladi va qaytaradi (context manager).

    Hovuz to'la bo'lsa DARHOL yiqilmaydi -- `_KUTISH_SEK` gacha
    kutadi. Qisqa portlashlar shu bilan yutiladi.
    """
    if _pool is None:
        raise DBUnavailable("DB pool ishga tushmagan.")
    conn = None
    muddat = time.monotonic() + _KUTISH_SEK
    while True:
        try:
            conn = _pool.getconn()
            break
        except PoolError as e:
            # FAQAT "hovuz to'la" holati kutiladi. Boshqa
            # `PoolError` (masalan hovuz yopilgan) DARHOL chiqadi --
            # uni kutish ma'nosiz va u boshqa nosozlik.
            if "exhausted" not in str(e).lower():
                raise DBUnavailable(str(e)) from e
            if time.monotonic() >= muddat:
                # HAQIQIY ortiqcha yuklama -- YASHIRILMAYDI.
                raise DBUnavailable(
                    f"DB hovuzi {_KUTISH_SEK:.0f}s davomida bo'shamadi "
                    f"(band): {e}") from e
            time.sleep(_TANAFFUS_SEK)
    # ILOVA ROLIGA TUSHISH — ixtiyoriy, `DB_SET_ROLE` bilan.
    #
    # NEGA KERAK (o'lchandi 2026-09-04): `.env` `postgres` SUPERUSER
    # bilan ulanadi. Superuser huquq tekshiruvlarini CHETLAB o'tadi,
    # ya'ni grant asosidagi himoyalar HECH QACHON sinalmagan.
    # `auth_test` da ERP chegarasi uchun ikki shox bor — "huquq bilan
    # yopiq" va "sanoqni solishtirish" — va superuser tufayli DOIM
    # ikkinchisi, ZAIF shoxi ishlagan.
    #
    # `tai_app` roli LOGIN QILA OLMAYDI (`rolcanlogin = false`) va
    # a'zosi ham yo'q, ya'ni u bilan ULANIB bo'lmaydi. `SET ROLE`
    # esa ulanishni talab qilmaydi va superuser imtiyozini SHU
    # SESSIYA uchun tushiradi — huquq shoxi aynan shunda sinaladi.
    #
    # Ulanish hovuzga QAYTGANDA `RESET ROLE` qilinadi: rol qolib
    # ketsa keyingi chaqiruvchi buni bilmasdan cheklangan huquq
    # bilan ishlardi (11-sinf — tiklash mexanizmi qoldiqni
    # abadiylashtiradi).
    if conn is not None and _SET_ROLE:
        try:
            with conn.cursor() as cur:
                cur.execute("SET ROLE %s" % _quote_ident(_SET_ROLE))
            conn.commit()
        except psycopg2.Error as e:
            _pool.putconn(conn)
            raise DBUnavailable(
                f"`DB_SET_ROLE={_SET_ROLE}` qo'llanmadi: {e}") from e
    try:
        yield conn
    finally:
        if conn is not None:
            if _SET_ROLE:
                try:
                    with conn.cursor() as cur:
                        cur.execute("RESET ROLE")
                    conn.commit()
                except psycopg2.Error:
                    # Ulanish buzilgan — hovuzga qaytarmaymiz, aks
                    # holda keyingi chaqiruvchi noma'lum rol bilan
                    # ishlardi.
                    _pool.putconn(conn, close=True)
                    conn = None
            if conn is not None:
                _pool.putconn(conn)


def query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Ko'p qatorli SELECT — dict'lar ro'yxatini qaytaradi."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                rows = cur.fetchall()
            conn.rollback()  # faqat o'qish — tranzaksiyani ochiq qoldirmaymiz
            return [dict(r) for r in rows]
    except psycopg2.Error as e:
        raise DBUnavailable(str(e)) from e


def query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Bitta qator (yoki None)."""
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Bitta qiymat (birinchi qator, birinchi ustun)."""
    row = query_one(sql, params)
    if not row:
        return None
    return next(iter(row.values()))


def execute_returning(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """YOZISH (INSERT/UPDATE ... RETURNING) — commit qiladi. query() faqat o'qish
    uchun (u rollback qiladi), shuning uchun yozuvlar shu funksiyadan o'tishi SHART."""
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        except psycopg2.Error as e:
            conn.rollback()
            raise DBUnavailable(str(e)) from e
