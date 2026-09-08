# -*- coding: utf-8 -*-
"""UMUMIY SINOV FIKSTURASI — deterministik domen holati.

NEGA BU MODUL BOR
=================
To'plamlar domen holatini ATROFDAN olardi:

    SELECT tender_id FROM tender_item WHERE name ILIKE '%…%' LIMIT 1
    SELECT * FROM v_catalog_kod_sifat WHERE company_id = 2

`ORDER BY` yo'q, egalik yo'q — ya'ni "o'sha kuni tasodifan mavjud
bo'lgan qator". O'LCHANGAN OQIBAT (2026-09-09, izolyatsiyalangan
darvoza):

  * `import_test` — boshqa qator tanlandi (`amount_text` "8 …") va
    TO'RTTA tekshiruv birdan yiqildi, garchi tahlilchi to'g'ri
    ishlayotgan bo'lsa ham;
  * `catalog_kod`, `req_qamrov` — `company_id=2` topilmadi;
  * `korik_navbat`, `kodlash`, `inson_dalil`, `review_butunlik`,
    `routing_kelishuv` — "sinov ma'lumoti yo'q".

Bularning HECH BIRI kod nuqsoni emas edi. Sinov kodni emas, KORPUS
TARKIBINI o'lchardi.

SHARTNOMA
=========
Har bir to'plam O'ZI YARATGAN qatorlar bilan ishlaydi:

    with fikstura.Domen(db) as f:
        cid = f.kompaniya()
        tid = f.tender()
        f.yonaltirish(cid, tid, ai_qaror="no_go")
        ...
    # chiqishda HAMMASI o'chadi -- istisno bo'lsa ham

NEGA `zz` PREFIKSI: darvozaning sizish qo'riqchasi AYNAN shu naqshni
sanaydi (`sinovdan OLDIN/KEYIN faol zz* hisoblar`). Ya'ni fikstura
tozalanmay qolsa, darvoza buni O'ZI aytadi -- bu tasodif emas,
tanlov: qoldiq JIM QOLMASLIGI kerak.

NEGA `ON CONFLICT DO NOTHING` EMAS, balki aniq nomlar: ikki to'plam
bir vaqtda yursa ham to'qnashmasin. Nomlar `PREFIKS` + belgi bilan
quriladi va HECH QACHON avtomatik ID ga tayanmaydi.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: Sinov obyektlari shu bilan boshlanadi. Darvoza qo'riqchasi ko'radi.
PREFIKS = "zzfix_"

#: Sinov tenderlari — haqiqiy manba identifikatorlaridan UZOQ
#: (ular ~11 xonali, eng kattasi ~2·10^10).
TENDER_BAZA = 9_100_000_000_000

#: Kirib bo'lmaydigan parol xeshi. ATAYLAB yaroqsiz: fikstura hisobi
#: HECH QACHON haqiqiy kirish uchun ishlatilmasin.
YAROQSIZ_XESH = "pbkdf2_sha256$1$zz$zz"


class Domen:
    """Deterministik domen fiksturasi. Kontekst menejeri.

    Chiqishda HAMMA yaratilgan qator o'chadi — istisno bo'lsa ham.
    Tashqi darvoza qo'riqchasi esa jarayon O'LDIRILGAN holat uchun
    zaxira bo'lib qoladi (`SIGKILL` da `finally` ishlamaydi).
    """

    def __init__(self, db) -> None:
        self._db = db
        self._kompaniyalar: List[int] = []
        self._tenderlar: List[int] = []
        self._mahsulotlar: List[int] = []

    # -- kontekst ------------------------------------------------------
    def __enter__(self) -> "Domen":
        return self

    def __exit__(self, *_a: Any) -> None:
        self.tozala()

    # -- ichki ---------------------------------------------------------
    def _yoz(self, sql: str, args: Tuple = ()) -> Optional[Any]:
        """YOZISH uchun ulanish.

        `db.query()` YARAMAYDI: u oxirida `rollback` qiladi va yozuv
        bekor bo'ladi. Bu loyihada ilgari ham xato qilingan joy.
        """
        with self._db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                qator = cur.fetchone() if cur.description else None
            conn.commit()
        return qator

    # -- yaratuvchilar -------------------------------------------------
    def kompaniya(self, belgi: str = "a") -> int:
        """Sinov ijarachisi. `company_id` QAYTARADI, 2 ni TAXMIN QILMAYDI.

        To'plamlar `company_id=2` deb yozardi -- bu "ikkinchi
        kompaniya bor" degan taxmin edi va toza bazada yiqilardi.
        """
        nom = f"{PREFIKS}{belgi}"
        q = self._yoz(
            "INSERT INTO company_account (username, company_name, "
            "  password_hash, active) VALUES (%s, %s, %s, TRUE) "
            "ON CONFLICT (username) DO UPDATE SET active = TRUE "
            "RETURNING id",
            (nom, f"ZZ Fikstura {belgi}", YAROQSIZ_XESH))
        cid = int(q[0] if not isinstance(q, dict) else q["id"])
        if cid not in self._kompaniyalar:
            self._kompaniyalar.append(cid)
        return cid

    def tender(self, n: int = 0, status: str = "open") -> int:
        """Sinov tenderi. `tender.id` QAYTARADI."""
        tid = TENDER_BAZA + n
        self._yoz(
            "INSERT INTO tender (id, source_id, source_platform, status, "
            "  close_at, raw_json) "
            "VALUES (%s, %s, 'zzfix', %s, now() + interval '7 days', '{}') "
            "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status",
            (tid, str(tid), status))
        if tid not in self._tenderlar:
            self._tenderlar.append(tid)
        return tid

    def pozitsiya(self, tender_id: int, nom: str,
                  amount_text: str = "500.00 шт", unit: str = "шт") -> None:
        """Tender pozitsiyasi — miqdor ANIQ beriladi.

        `amount_text` ataylab parametr: "500 talab, 200 qoldiq -> 300
        yetishmaydi" kabi biznes qoidasini o'lchash uchun miqdor
        SINOVNIKI bo'lishi kerak, korpusdan kelmasligi.
        """
        self._yoz(
            "INSERT INTO tender_item (tender_id, lot_id, item_id, name, "
            "  unit, amount_text, raw_json) "
            "VALUES (%s, 1, %s, %s, %s, %s, '{}') "
            "ON CONFLICT DO NOTHING",
            (tender_id, f"{tender_id}-1", nom, unit, amount_text))

    def mahsulot(self, company_id: int, nom_belgi: str = "m",
                 stock_qty: Optional[float] = 200,
                 keywords: Optional[List[str]] = None) -> int:
        """Katalog mahsuloti. `catalog_product.id` QAYTARADI."""
        nom = f"{PREFIKS}{nom_belgi}"
        q = self._yoz(
            "INSERT INTO catalog_product (company_id, name, keywords, unit, "
            "  stock_qty, stock_unit, stock_updated_at) "
            "VALUES (%s, %s, %s, 'шт', %s, 'шт', now()) "
            "RETURNING id",
            (company_id, nom, keywords or [nom], stock_qty))
        pid = int(q[0] if not isinstance(q, dict) else q["id"])
        self._mahsulotlar.append(pid)
        return pid

    def kod_taklifi(self, company_id: int, product_id: int,
                    code: Optional[str] = None,
                    qaror: Optional[str] = None) -> Optional[str]:
        """`kod_tasdigi` QATLAMI uchun qator.

        `v_inson_halqasi` bu qatlamni `catalog_product_code` dan
        oladi. Jadval BO'SH bo'lsa `GROUP BY` hech nima qaytarmaydi va
        qatlam ko'rinishdan BUTUNLAY yo'qoladi -- `review_butunlik` va
        `inson_dalil` aynan shuni "uch qatlam emas, ikkita" deb
        ko'rsatardi.

        `code` berilmasa `dim_good_code` dan BIRINCHISI olinadi. Kod
        lug'ati bo'sh bo'lsa `None` qaytadi va CHAQIRUVCHI buni
        o'zi hal qiladi -- bu yerda soxta kod YARATILMAYDI, chunki u
        ma'lumotnoma lug'ati.

        `qaror`: `None` (kutilmoqda) | 'tasdiq' | 'rad'.
        """
        if code is None:
            q = self._yoz("SELECT code FROM dim_good_code ORDER BY code LIMIT 1")
            if not q:
                return None
            code = q[0] if not isinstance(q, dict) else q["code"]

        tasdiq = "now()" if qaror == "tasdiq" else "NULL"
        rad = "now()" if qaror == "rad" else "NULL"
        self._yoz(
            f"INSERT INTO catalog_product_code (product_id, company_id, code, "
            f"  manba, tasdiqlagan, tasdiqlandi, rad_etildi) "
            f"VALUES (%s, %s, %s, 'taklif', %s, {tasdiq}, {rad}) "
            f"ON CONFLICT (product_id, code) DO NOTHING",
            (product_id, company_id, code,
             f"{PREFIKS}operator" if qaror else None))
        return code

    def yonaltirish(self, company_id: int, tender_id: int,
                    ai_qaror: str = "no_go",
                    inson_qaror: Optional[str] = None) -> None:
        """`yonaltirish` QATLAMI uchun qator (`tender_routing`).

        `korik_navbat` "malakasi `no_go` chiqadigan tender" talab
        qiladi, `routing_kelishuv` esa "inson qarori" -- ikkalasi ham
        shu jadvaldan. Sukut `no_go`: aynan shu holat korpusda kam
        uchraydi va shuning uchun tez-tez yetishmaydi.
        """
        self._yoz(
            "INSERT INTO tender_routing (company_id, tender_id, ai_qaror, "
            "  ai_manba, ai_sabab, inson_qaror, qaror_vaqti) "
            "VALUES (%s, %s, %s, 'malaka', %s, %s, "
            "        CASE WHEN %s IS NULL THEN NULL ELSE now() END)",
            (company_id, tender_id, ai_qaror, f"{PREFIKS}sinov sababi",
             inson_qaror, inson_qaror))

    # -- tozalash ------------------------------------------------------
    def tozala(self) -> Dict[str, int]:
        """HAMMA yaratilgan qatorni o'chiradi. Xatoni YUTMAYDI.

        Tartib MUHIM: bola qatorlar avval. `tender_routing` va
        `catalog_product_code` `ON DELETE CASCADE` bilan bog'langan,
        lekin ularga TAYANMAYMIZ -- kaskad sxema o'zgarishi bilan
        jimgina yo'qolishi mumkin.
        """
        n: Dict[str, int] = {}
        with self._db.get_conn() as conn:
            with conn.cursor() as cur:
                if self._tenderlar:
                    cur.execute("DELETE FROM tender_routing "
                                "WHERE tender_id = ANY(%s)", (self._tenderlar,))
                    n["yonaltirish"] = cur.rowcount
                if self._mahsulotlar:
                    cur.execute("DELETE FROM catalog_product_code "
                                "WHERE product_id = ANY(%s)", (self._mahsulotlar,))
                    n["kod"] = cur.rowcount
                    cur.execute("DELETE FROM catalog_product "
                                "WHERE id = ANY(%s)", (self._mahsulotlar,))
                    n["mahsulot"] = cur.rowcount
                if self._tenderlar:
                    cur.execute("DELETE FROM tender WHERE id = ANY(%s)",
                                (self._tenderlar,))
                    n["tender"] = cur.rowcount
                # HISOB OXIRIDA: `tender_routing.company_id` unga
                # bog'langan va u yuqorida o'chdi.
                cur.execute("DELETE FROM company_account "
                            "WHERE username LIKE %s", (PREFIKS + "%",))
                n["kompaniya"] = cur.rowcount
            conn.commit()
        self._kompaniyalar.clear()
        self._tenderlar.clear()
        self._mahsulotlar.clear()
        return n
