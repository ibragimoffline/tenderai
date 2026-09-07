#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESKI `file_ref` QATORLARINI HAQIQIY SAQLASHGA KO'CHIRADI
=========================================================

MUAMMO. `company_document.file_ref` matn maydoni edi va unga MAHALLIY
yo'l yozilardi:

    file:///D:/MVP%20projects/tender-ai/.runtime/company_documents/2/...

O'lchandi (2026-09-06): 13 qatorning 13 tasi ham shunday. Bu yo'l
serverda MAVJUD EMAS va brauzer `http://` sahifadan `file://` ga
o'tishni bloklaydi — havola bosilardi va HECH NARSA bo'lmasdi.

BU SKRIPT NIMA QILADI

    file_ref (file://)  ->  yo'lni ochish
                        ->  fayl BORLIGINI tekshirish
                        ->  `yuklama.qabul_qil()` bilan yuklash
                        ->  `company_document.yuklama_id` yozish
                        ->  sha256 ni QAYTA o'qib solishtirish
                        ->  matn ajratish (`qayta_ishla`)

`file_ref` O'CHIRILMAYDI. U tarixiy dalil: qator qayerdan kelganini
va qaysi mashinada yotganini ko'rsatadi.

BU SKRIPT NIMA QILMAYDI

  * FAYL TOPILMASA HECH NARSA YOZMAYDI. "Ko'chirildi" deb belgilash
    — soxta migratsiya bo'lardi va u eng yomon shakl: hisobotda
    yashil, amalda bo'sh.
  * `file://` DAN BOSHQA sxemani QABUL QILMAYDI. `http(s)://` havola
    haqiqiy tashqi manba bo'lishi mumkin va uni yuklab olish
    BOSHQA qaror (tarmoqqa chiqish, ishonch, hajm).

"KO'CHMAGAN" HOLAT ALOHIDA USTUN TALAB QILMAYDI. U mavjud
ustunlardan CHIQADI va shuning uchun hech qachon HAQIQATDAN
AJRALMAYDI:

    yuklama_id IS NULL AND file_ref IS NOT NULL   -> ko'chmagan
    yuklama_id IS NOT NULL                        -> ko'chgan

Yangi ustun qo'shilsa u qo'lda yangilanishi kerak bo'lardi va bir
kun haqiqatdan ajralib qolardi.

ISHGA TUSHIRISH

    python legacy_fayl_kochir.py                 # FAQAT KO'RSATADI
    python legacy_fayl_kochir.py --kochir        # haqiqatan ko'chiradi
    python legacy_fayl_kochir.py --kochir --company 2

Skript FAYLLAR TURGAN mashinada yurgiziladi (odatda ishlab
chiqaruvchining mashinasi), keyin baza va `UPLOAD_ROOT` serverga
ko'chiriladi.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv                                # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from api import db, saqlash, xatolar, yuklama                 # noqa: E402

SQL_NOMZODLAR = """
SELECT id, company_id, name, doc_type, file_name, file_ref
  FROM company_document
 WHERE yuklama_id IS NULL
   AND file_ref IS NOT NULL AND file_ref <> ''
   AND (%(company)s::int IS NULL OR company_id = %(company)s)
 ORDER BY id
"""


def yolni_ol(file_ref: str) -> Optional[str]:
    """`file://` URL dan MAHALLIY yo'lni chiqaradi.

    Boshqa sxema — `None`. Bu ATAYLAB qat'iy: `http(s)://` havolani
    yuklab olish tarmoqqa chiqish va ishonch qarorini talab qiladi,
    u bu skriptning ishi emas.

    Windows yo'li `file:///D:/...` shaklida keladi va `urlparse`
    uni `/D:/...` deb beradi — boshdagi `/` olib tashlanadi.
    """
    try:
        u = urlparse(file_ref)
    except ValueError:
        return None
    if u.scheme != "file":
        return None
    yol = unquote(u.path)
    # `/D:/...` -> `D:/...`; POSIX da `/srv/...` o'zgarmaydi.
    if len(yol) > 2 and yol[0] == "/" and yol[2] == ":":
        yol = yol[1:]
    return yol or None


def bitta(qator: Dict, kochir: bool) -> Dict:
    """Bitta qatorni ko'rib chiqadi (va `kochir` bo'lsa ko'chiradi)."""
    out = {"id": qator["id"], "company_id": qator["company_id"],
           "name": qator["name"], "holat": "", "izoh": ""}

    yol = yolni_ol(qator["file_ref"] or "")
    if not yol:
        out["holat"] = "sxema_qollab_quvvatlanmaydi"
        out["izoh"] = (qator["file_ref"] or "")[:80]
        return out
    if not os.path.isfile(yol):
        # ENG MUHIM SHOX. Bu yerda HECH NARSA yozilmaydi.
        out["holat"] = "fayl_topilmadi"
        out["izoh"] = yol
        return out

    hajm = os.path.getsize(yol)
    if hajm == 0:
        out["holat"] = "fayl_bosh"
        out["izoh"] = yol
        return out
    if hajm > saqlash.MAX_UPLOAD_MB * 1024 * 1024:
        out["holat"] = "juda_katta"
        out["izoh"] = f"{hajm / 1024 / 1024:.1f} MB > {saqlash.MAX_UPLOAD_MB} MB"
        return out

    nom = qator["file_name"] or os.path.basename(yol)
    out["izoh"] = f"{os.path.basename(yol)} ({hajm / 1024:.0f} KB)"

    if not kochir:
        # KURAK URINISH: kengaytma/mazmun tekshiruvi HOZIRDAN
        # yurgiziladi, ya'ni `--kochir` da kutilmagan rad bo'lmaydi.
        try:
            with io.open(yol, "rb") as f:
                bosh = f.read(8192)
            yuklama._ext_aniqla(nom, bosh)
            out["holat"] = "tayyor"
        except xatolar.Xato as e:
            out["holat"] = f"rad:{e.kod}"
        return out

    with io.open(yol, "rb") as f:
        data = f.read()
    try:
        y = yuklama.qabul_qil(qator["company_id"], "company_doc", nom, data)
    except xatolar.Xato as e:
        out["holat"] = f"rad:{e.kod}"
        return out

    # SHA256 QAYTA O'QIB SOLISHTIRILADI. `qabul_qil` uni o'zi
    # hisoblaydi, lekin bu yerda MANBA fayldan mustaqil hisoblanadi:
    # ikkalasi bir manbadan kelsa tekshiruv hech narsani o'lchamasdi.
    kutilgan = saqlash.sha256(data)
    if y["sha256"] != kutilgan:
        out["holat"] = "sha256_mos_emas"
        return out
    # Saqlangan faylni O'QIB ham tekshiramiz — disk yozuvi butunmi.
    with saqlash.saqlagich().open(y["kalit"]) as f:
        if saqlash.sha256(f.read()) != kutilgan:
            out["holat"] = "saqlangan_fayl_buzuq"
            return out

    db.execute_returning("""
        UPDATE company_document
           SET yuklama_id = %(y)s, file_name = %(n)s, updated_at = now()
         WHERE id = %(i)s AND company_id = %(c)s
        RETURNING id""",
        {"i": qator["id"], "c": qator["company_id"],
         "y": y["id"], "n": y["original_nom"]})

    # MATN AJRATISH — yiqilsa KO'CHIRISH bekor qilinmaydi: fayl
    # saqlandi va yuklab olinadi. Holat `oqilmadi` bo'lib qoladi va
    # buni foydalanuvchi KO'RADI.
    try:
        h = yuklama.qayta_ishla(y["id"])
        out["holat"] = f"kochirildi:{h['holat']}"
    except Exception as e:                                    # noqa: BLE001
        out["holat"] = "kochirildi:ajratilmadi"
        out["izoh"] += f" — {type(e).__name__}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Eski `file_ref` qatorlarini haqiqiy saqlashga ko'chiradi")
    ap.add_argument("--kochir", action="store_true",
                    help="HAQIQATAN ko'chiradi (busiz faqat ko'rsatadi)")
    ap.add_argument("--company", type=int, default=None,
                    help="Faqat shu kompaniya")
    args = ap.parse_args()

    db.init_pool()
    qatorlar = db.query(SQL_NOMZODLAR, {"company": args.company})
    if not qatorlar:
        print("Ko'chiriladigan qator yo'q.")
        return 0

    print(f"{'REJIM: HAQIQIY KO`CHIRISH' if args.kochir else 'REJIM: FAQAT KO`RSATISH'}"
          f"  ·  {len(qatorlar)} ta nomzod\n")
    print(f"  {'id':>5}  {'kompaniya':>9}  {'holat':<28}  izoh")
    print("  " + "-" * 92)

    natijalar: List[Dict] = []
    for q in qatorlar:
        r = bitta(dict(q), args.kochir)
        natijalar.append(r)
        print(f"  {r['id']:>5}  {r['company_id']:>9}  {r['holat']:<28}  "
              f"{r['izoh'][:44]}")

    print()
    sanoq: Dict[str, int] = {}
    for r in natijalar:
        kalit = r["holat"].split(":")[0]
        sanoq[kalit] = sanoq.get(kalit, 0) + 1
    for k, v in sorted(sanoq.items()):
        print(f"  {k:<28} {v}")

    yoq = sum(v for k, v in sanoq.items()
              if k in ("fayl_topilmadi", "fayl_bosh"))
    if yoq:
        print(f"\n  DIQQAT: {yoq} ta faylning MANBASI TOPILMADI. Ular")
        print("  ko'chirilmadi va SOXTA 'ko'chirildi' deb belgilanmadi.")
        print("  Ular quyidagi so'rov bilan topiladi:")
        print("    SELECT id, file_ref FROM company_document")
        print("     WHERE yuklama_id IS NULL AND file_ref IS NOT NULL;")

    if not args.kochir:
        print("\n  Bu FAQAT KO'RSATISH edi. Ko'chirish uchun: --kochir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
