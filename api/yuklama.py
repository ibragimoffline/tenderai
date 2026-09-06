# =============================================================================
# YUKLANGAN FAYL — qabul, tekshiruv, ajratish, bo'laklash, qidiruv
# =============================================================================
# BU MODULDA PARSER YO'Q. `etl_doc_text` allaqachon pdf/docx/xlsx/txt/
# csv/zip/ole2 ni o'qiydi, magic-bayt bilan haqiqiy formatni aniqlaydi
# va ZIP bombaga qarshi uchta chegaraga ega. Bo'laklash `etl_embed.
# chunk_text`, vektor `ai_chat.embed_documents`.
#
# NEGA MUHIM: ikkinchi parser yozilsa ikkita xavfsizlik yuzasi, ikkita
# xato ro'yxati va ikkita "qo'llab-quvvatlanadigan formatlar" ta'rifi
# paydo bo'lardi — va ular BIR KUN ajralib ketardi.
#
# BU MODUL QILADIGAN ISH: ijarachi chegarasi, holat mashinasi va
# saqlash bilan bog'lash.
# =============================================================================
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from api import db, saqlash, xatolar

log = logging.getLogger("api.yuklama")

#: Ruxsat etilgan kengaytmalar — BIZNES uchun ma'nolilari.
#:
#: `htm/html/xml/json/md` ATAYLAB YO'Q, garchi parser ularni o'qisa
#: ham: ular tender hujjati emas va `html` brauzerda ochilganda
#: skript yurgizish yuzasini kengaytiradi.
RUXSAT_EXT = {"pdf", "doc", "docx", "docm", "xls", "xlsx", "xlsm",
              "txt", "csv", "zip"}

#: `inline` KO'RSATILADIGAN formatlar — brauzer o'zi xavfsiz chizadi.
#:
#: `html`, `svg` VA BOSHQA HAMMA NARSA `attachment`: `inline` bilan
#: berilgan HTML ayni originda skript yurgizardi (saqlangan XSS).
INLINE_MIME = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
}

#: MIME xaritasi — brauzerga to'g'ri tur berish uchun.
MIME = {
    "pdf":  "application/pdf",
    "doc":  "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "docm": "application/vnd.ms-word.document.macroEnabled.12",
    "xls":  "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    "txt":  "text/plain; charset=utf-8",
    "csv":  "text/csv; charset=utf-8",
    "zip":  "application/zip",
}

#: Bitta suhbatga biriktiriladigan fayllar chegarasi (§21).
CHAT_MAX_FAYL   = int(os.environ.get("CHAT_MAX_FAYL", "5"))
CHAT_MAX_BAYT   = int(os.environ.get("CHAT_MAX_BAYT",
                                     str(60 * 1024 * 1024)))

#: Bo'lak o'lchami — `doc_chunk` bilan AYNI bo'lsin, aks holda ayni
#: savol ikki korpusda ikki xil aniqlik berardi.
try:
    from etl_embed import CHUNK_SIZE, CHUNK_OVERLAP
except Exception:                                             # noqa: BLE001
    CHUNK_SIZE, CHUNK_OVERLAP = 1200, 150


# =============================================================================
# 1. QABUL — tekshiruv va saqlash
# =============================================================================
def _ext_aniqla(nom: str, data: bytes) -> str:
    """HAQIQIY kengaytmani qaytaradi yoki xato ko'taradi.

    UCH QADAM va ular ATAYLAB shu tartibda:

      1. nomdan kengaytma (`saqlash.ext_ol` — oq ro'yxat bilan);
      2. BAYTLARDAN haqiqiy format (`sniff_magic`);
      3. ikkalasi ham ma'lum va BOSHQA bo'lsa -> rad.

    NEGA 2-QADAM YETARLI EMAS EDI: `sniff_magic` noma'lum formatda
    kirish `ext` ini QAYTARADI, ya'ni uni yolg'iz ishlatish "kengaytmaga
    ishonish" bilan bir xil bo'lardi matn fayllarida.

    NEGA 3-QADAM KERAK: `.pdf` deb nomlangan `.docx` — ataylab
    chalg'itish belgisi. Parser uni baribir to'g'ri o'qirdi, lekin
    yuklovchi NIYATI bilan mazmun mos kelmasligi yozib qo'yilishi
    kerak (§5).
    """
    from etl_doc_text import is_supported, sniff_magic

    nom_ext = saqlash.ext_ol(nom)
    if not nom_ext:
        raise xatolar.Xato("FILE_FORMAT_UNSUPPORTED", {"ext": "—"})
    if nom_ext not in RUXSAT_EXT:
        raise xatolar.Xato("FILE_FORMAT_UNSUPPORTED", {"ext": nom_ext})

    haqiqiy = sniff_magic(data, nom_ext)

    # `sniff_magic` eski Office fayllarini `ole2` deb qaytaradi —
    # `.doc` va `.xls` uchun bu KUTILGAN, ziddiyat emas.
    if haqiqiy == "ole2" and nom_ext in {"doc", "xls"}:
        return "ole2"
    # `docx`/`xlsx` ZIP oilasidan; `sniff` ularni aniq ajratadi.
    if haqiqiy == nom_ext:
        return haqiqiy
    # Nomdan kelgan kengaytma matn turi bo'lsa va baytlarda imzo
    # topilmasa — `sniff` kirishni qaytargan bo'ladi, bu holat
    # yuqoridagi tenglikka tushadi. Bu yerga faqat HAQIQIY ziddiyat
    # keladi.
    if haqiqiy in RUXSAT_EXT or is_supported(haqiqiy):
        raise xatolar.Xato("FILE_TYPE_MISMATCH",
                           {"nom": nom_ext, "haqiqiy": haqiqiy})
    raise xatolar.Xato("FILE_FORMAT_UNSUPPORTED", {"ext": haqiqiy})


def qabul_qil(company_id: int, manba_turi: str, nom: str, data: bytes,
              aktor_id: Optional[int] = None) -> Dict[str, Any]:
    """Faylni TEKSHIRADI, SAQLAYDI va `yuklama` qatorini yaratadi.

    CHEGARA BU YERDA TEKSHIRILMAYDI: u chaqiruvchida, `_yuklangani()`
    da, faylni xotiraga to'liq o'qishdan OLDIN ishlaydi. Bu yerda
    `data` allaqachon chegaradan o'tgan.

    Tartib ATAYLAB shunday: avval tekshiruv, keyin disk, keyin baza.
    Teskarisida rad etilgan fayl diskda qolardi.
    """
    if not data:
        raise xatolar.Xato("FILE_EMPTY")
    if manba_turi not in ("company_doc", "chat"):
        raise ValueError(f"noma'lum manba_turi: {manba_turi!r}")

    ext = _ext_aniqla(nom, data)
    toza_nom = saqlash.tozala_nom(nom)
    xesh = saqlash.sha256(data)

    s = saqlash.saqlagich()
    try:
        m = s.save(company_id, ext, data)   # ASL NOM saqlashga BORMAYDI
    except xatolar.Xato:
        raise
    except OSError as e:
        # Diskka yozib bo'lmadi. FOYDALANUVCHIGA yo'l KO'RSATILMAYDI —
        # `ichki` faqat jurnalga ketadi (§25).
        raise xatolar.Xato("STORAGE_WRITE_FAILED", ichki=str(e)) from e

    # QATOR YOZILMASA FAYL DISKDA QOLMASIN.
    #
    # O'LCHANGAN NUQSON (2026-09-06): fayl diskka YOZILGACH qator
    # qo'shilardi va oradagi har qanday xato YETIM FAYL qoldirardi —
    # diskda bor, bazada yo'q, hech kim biladigan joyi yo'q. Sinov
    # tozalashi aynan shunday bitta faylni topdi.
    #
    # Tartibni teskari qilib bo'lmaydi: `kalit` saqlashdan keladi.
    # Shuning uchun KOMPENSATSIYA: yozuv yiqilsa fayl ARXIVGA
    # ko'chiriladi (o'chirilmaydi — sabab noma'lum bo'lsa dalilni
    # yo'q qilish noto'g'ri).
    try:
        row = db.execute_returning("""
            INSERT INTO yuklama (id, company_id, manba_turi, original_nom,
                                 kalit, backend, mime, ext, size_bytes,
                                 sha256, holat, uploaded_by)
            VALUES (%(id)s, %(c)s, %(mt)s, %(nom)s, %(k)s, %(b)s, %(mime)s,
                    %(ext)s, %(sz)s, %(sha)s, 'yuklandi', %(by)s)
            RETURNING *""",
            {"id": str(uuid.uuid4()), "c": company_id, "mt": manba_turi,
             "nom": toza_nom, "k": m.kalit, "b": m.backend,
             "mime": MIME.get(ext, "application/octet-stream"),
             "ext": ext, "sz": m.size_bytes, "sha": xesh, "by": aktor_id})
    except Exception:                                         # noqa: BLE001
        try:
            s.archive(m.kalit)
        except Exception:                                     # noqa: BLE001
            log.warning("yetim fayl qoldi: %s", m.kalit)
        raise
    return dict(row)


# =============================================================================
# 2. QAYTA ISHLASH — matn, bo'lak, vektor
# =============================================================================
def qayta_ishla(yuklama_id: str) -> Dict[str, Any]:
    """Matnni ajratadi, bo'laklaydi va (imkon bo'lsa) vektorlaydi.

    SINXRON. Chaqiruvchi (`BackgroundTasks`) uni threadpool'da
    yurgizadi — FastAPI `def` funksiyani shunday chaqiradi. Bu
    ataylab: modul ichida DB bor va uni asinxron oqimdan to'g'ridan
    to'g'ri chaqirish event loop'ni bloklardi.

    HOLAT FAQAT HAQIQATGA QARAB QO'YILADI:
      matn yo'q            -> `oqilmadi`  (skan/chizma, OCR kerak)
      formatni bilmaymiz   -> `qollab_quvvatlanmaydi`
      matn bor             -> `tayyor`
    `tayyor` da'vosini baza ham tekshiradi (`yuklama_tayyor_matn_chk`).
    """
    from etl_doc_text import MIN_CHARS, extract, is_supported

    y = db.query_one("SELECT * FROM yuklama WHERE id=%(i)s", {"i": yuklama_id})
    if not y:
        raise xatolar.Xato("FILE_NOT_FOUND")
    if y["holat"] not in ("yuklandi", "yiqildi"):
        return dict(y)                       # allaqachon ishlangan

    db.execute_returning(
        "UPDATE yuklama SET holat='ajratilmoqda' WHERE id=%(i)s RETURNING id",
        {"i": yuklama_id})

    ext = y["ext"]
    if not is_supported(ext):
        return _xato_holat(yuklama_id, "qollab_quvvatlanmaydi",
                           f"format qo'llab-quvvatlanmaydi: {ext}")

    try:
        with saqlash.saqlagich().open(y["kalit"]) as f:
            data = f.read()
    except xatolar.Xato:
        return _xato_holat(yuklama_id, "yiqildi", "fayl saqlagichda topilmadi")

    try:
        matn, sahifa, ajratgich, xato = extract(data, ext)
    except Exception as e:                                    # noqa: BLE001
        # Parser kutilmagan holatda yiqildi. TAFSILOT JURNALGA,
        # foydalanuvchiga QISQA sabab.
        log.warning("yuklama %s: ajratish yiqildi: %s", yuklama_id, e)
        return _xato_holat(yuklama_id, "yiqildi", "matn ajratib bo'lmadi")

    if xato:
        return _xato_holat(yuklama_id, "yiqildi", xato[:300])
    if not matn or len(matn.strip()) < MIN_CHARS:
        # SOXTA "BO'SH MATN" QO'YILMAYDI. Bu eng ehtimolli holat:
        # skan qilingan PDF. `tayyor` deb belgilash AI ga "fayl
        # o'qildi, ichida hech narsa yo'q" degan YOLG'ON berardi.
        return _xato_holat(yuklama_id, "oqilmadi",
                           "matn topilmadi (skan yoki chizma — OCR kerak)")

    # IJARACHI OSHKOR O'ZGARUVCHIGA olinadi. `_bolakla(y["company_id"],
    # ...)` ham to'g'ri ishlardi, lekin `multitenant_test` skaneri
    # `Subscript` ni "kompaniya uzatildi" deb TANIMAYDI va uni
    # buzilish deb belgilaydi. Skanerni kengaytirish o'rniga kod
    # oshkor yoziladi: skaner tor bo'lgani yaxshi, chunki u
    # ijarachi chegarasini qo'riqlaydi.
    company_id = int(y["company_id"])
    bolaklar = _bolakla(company_id, yuklama_id, matn, ext, sahifa)

    row = db.execute_returning("""
        UPDATE yuklama SET holat='tayyor', matn_belgi=%(n)s,
               sahifa_soni=%(p)s, ajratgich=%(a)s, xato=NULL,
               tayyor_at=now()
         WHERE id=%(i)s RETURNING *""",
        {"i": yuklama_id, "n": len(matn), "p": sahifa, "a": ajratgich})

    _vektorla(yuklama_id, bolaklar)
    return dict(row)


def _xato_holat(yuklama_id: str, holat: str, sabab: str) -> Dict[str, Any]:
    row = db.execute_returning(
        "UPDATE yuklama SET holat=%(h)s, xato=%(x)s WHERE id=%(i)s RETURNING *",
        {"i": yuklama_id, "h": holat, "x": sabab})
    return dict(row)


def _bolakla(company_id: int, yuklama_id: str, matn: str, ext: str,
             sahifa_soni: Optional[int]) -> List[Dict[str, Any]]:
    """Matnni bo'laklaydi va bazaga yozadi.

    SAHIFA RAQAMI FAQAT PDF DA. Boshqa formatда `NULL` qoladi va UI
    bo'lak raqamini ko'rsatadi. SOXTA sahifa yasash (masalan
    "har 3000 belgi = 1 sahifa") iqtibosni ishonchli KO'RSATARDI,
    holbuki u taxmin bo'lardi (§20).
    """
    from etl_embed import chunk_text

    bolaklar = chunk_text(matn, CHUNK_SIZE, CHUNK_OVERLAP)
    if not bolaklar:
        return []

    # PDF da sahifani ofsetdan CHIQARIB BO'LMAYDI: `extract_pdf`
    # sahifalarni `\n` bilan qo'shadi va ofset->sahifa xaritasini
    # saqlamaydi. Shuning uchun sahifa faqat BITTA sahifali PDF da
    # ma'lum. Qolganida NULL — bu kamchilik, lekin YOLG'ON emas.
    yagona = sahifa_soni if (ext == "pdf" and sahifa_soni == 1) else None

    db.execute_returning(
        "DELETE FROM yuklama_chunk WHERE yuklama_id=%(i)s RETURNING 1",
        {"i": yuklama_id})

    out = []
    for n, (bosh, oxir, b_matn) in enumerate(bolaklar, 1):
        r = db.execute_returning("""
            INSERT INTO yuklama_chunk
                (yuklama_id, company_id, chunk_no, text, char_start,
                 char_end, sahifa, embed_holat)
            VALUES (%(y)s, %(c)s, %(n)s, %(t)s, %(s)s, %(e)s, %(p)s, 'navbatda')
            RETURNING id, chunk_no, text""",
            {"y": yuklama_id, "c": company_id, "n": n, "t": b_matn,
             "s": bosh, "e": oxir, "p": yagona})
        out.append(dict(r))
    return out


def _vektorla(yuklama_id: str, bolaklar: List[Dict[str, Any]]) -> None:
    """Vektorlarni hisoblaydi — MAHALLIY model bilan.

    YIQILSA HOLAT O'ZGARMAYDI. Vektor bo'lmasa ham fayl ISHLAYDI:
    leksik qidiruv (`tsvector`) mavjud va `doc_chunk` da ham aynan
    shu zaxira yo'l bor. `tayyor` ni vektorga bog'lash faylni
    embedder o'rnatilmagan mashinada ABADIY "processing" da
    qoldirardi.

    PULLIK AI AVTOMATIK YOQILMAYDI: `ai_chat.embed_documents`
    `EMBED_PROVIDER` ni o'qiydi va standart qiymat `local`.
    `voyage` tanlangan bo'lsa u `ai.paid_guard()` dan o'tadi —
    ya'ni qulf shu yerda ham kuchda (§23).
    """
    if not bolaklar:
        return
    try:
        from api.ai_chat import embed_documents
        vektorlar = embed_documents([b["text"] for b in bolaklar])
    except Exception as e:                                    # noqa: BLE001
        log.info("yuklama %s: vektorlash o'tkazib yuborildi (%s)",
                 yuklama_id, type(e).__name__)
        return

    model = os.environ.get("EMBED_MODEL_NAME") or "local"
    for b, v in zip(bolaklar, vektorlar):
        db.execute_returning("""
            UPDATE yuklama_chunk
               SET embedding = %(v)s::vector, embed_model=%(m)s,
                   embed_holat='ok'
             WHERE id=%(i)s RETURNING id""",
            {"i": b["id"], "v": "[" + ",".join(f"{x:.6f}" for x in v) + "]",
             "m": model})


# =============================================================================
# 3. O'QISH — HAR BIRI IJARACHI BILAN
# =============================================================================
def ol(yuklama_id: str, company_id: int) -> Dict[str, Any]:
    """Yuklamani oladi — `company_id` SHART va u WHERE bandida.

    BEGONA FAYL UCHUN 404, 403 EMAS. 403 faylning MAVJUDLIGINI
    tasdiqlardi va id ni taxmin qilib korpusni sanash mumkin bo'lardi.
    Loyihada bu naqsh allaqachon ishlatiladi (`DOC_UPDATE_SQL`).
    """
    row = db.query_one(
        "SELECT * FROM yuklama WHERE id=%(i)s AND company_id=%(c)s",
        {"i": _uuid(yuklama_id), "c": company_id})
    if not row:
        raise xatolar.Xato("FILE_NOT_FOUND")
    return dict(row)


def _uuid(x: str) -> str:
    """Noto'g'ri UUID — 404, `DataError` emas.

    Ilgari bunga o'xshash joyda buzuq id 500 berardi va u
    "server yiqildi" deb ko'rinardi, holbuki bu oddiy 404.
    """
    try:
        return str(uuid.UUID(str(x)))
    except (ValueError, AttributeError, TypeError):
        raise xatolar.Xato("FILE_NOT_FOUND")


def ochib_ber(y: Dict[str, Any]):
    """Fayl oqimini qaytaradi. `y` — `ol()` dan kelgan qator.

    DIQQAT: bu XOM deskriptor va uni CHAQIRUVCHI yopishi shart.
    HTTP javobi uchun `oqim()` ni ishlating.
    """
    return saqlash.saqlagich().open(y["kalit"])


def oqim(y: Dict[str, Any], bolak: int = 256 * 1024):
    """Faylni BO'LAKLAB o'qiydigan generator; oxirida DESKRIPTORNI YOPADI.

    O'LCHANGAN NUQSON (2026-09-06). Ilgari `StreamingResponse` ga
    ochiq fayl obyekti BERILARDI. Starlette uni o'qiydi, lekin
    `.close()` CHAQIRMAYDI — ya'ni har yuklab olish bitta
    deskriptorni ochiq qoldirardi.

    Linuxda bu SEKIN sizish (`ulimit -n` gacha), Windowsda esa
    DARHOL ko'rinadi: ochiq fayl ko'chirilmaydi. Sinov tozalashi
    aynan shu yerda `PermissionError` bilan yiqildi va nuqsonni
    ochdi — ilgari u `except: pass` bilan yutilgan edi.

    `finally` SHART: mijoz ulanishni yarmida uzsa generator
    `GeneratorExit` bilan to'xtaydi va usiz deskriptor baribir
    ochiq qolardi.
    """
    f = saqlash.saqlagich().open(y["kalit"])
    try:
        while True:
            b = f.read(bolak)
            if not b:
                break
            yield b
    finally:
        f.close()


def javob_sarlavhasi(y: Dict[str, Any], inline: bool) -> Dict[str, str]:
    """`Content-Type` va `Content-Disposition`.

    `inline` FAQAT PDF va TXT uchun. Boshqasi `attachment`: HTML yoki
    SVG ni `inline` berish ayni originda skript yurgizardi.

    Fayl nomi ikki marta beriladi — ASCII zaxira va RFC 5987
    (`filename*`). Kirill nomli fayl (bazadagilar aynan shunday)
    faqat `filename=` bilan buziladi.
    """
    from urllib.parse import quote
    ext = (y.get("ext") or "").lower()
    turi = INLINE_MIME.get(ext) if inline else None
    joylash = "inline" if turi else "attachment"
    nom = saqlash.tozala_nom(y.get("original_nom") or "fayl")
    ascii_nom = nom.encode("ascii", "replace").decode("ascii")
    return {
        "Content-Type": turi or y.get("mime") or "application/octet-stream",
        "Content-Disposition":
            f'{joylash}; filename="{ascii_nom}"; '
            f"filename*=UTF-8''{quote(nom)}",
        # Yuklangan fayl HECH QACHON keshga tushmasin: proksi keshi
        # uni boshqa ijarachiga berib yuborishi mumkin.
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }


# =============================================================================
# 4. CHATGA BIRIKTIRISH
# =============================================================================
def chatga_biriktir(session_id: str, yuklama_id: str, company_id: int) -> None:
    """Faylni suhbatga bog'laydi. Kvota SHU YERDA tekshiriladi (§21)."""
    n = db.scalar("""SELECT count(*) FROM chat_yuklama
         WHERE session_id=%(s)s AND uzildi_at IS NULL""",
        {"s": _uuid(session_id)})
    if n >= CHAT_MAX_FAYL:
        raise xatolar.Xato("UPLOAD_QUOTA_EXCEEDED", {"max": CHAT_MAX_FAYL})
    jami = db.scalar("""
        SELECT COALESCE(sum(y.size_bytes), 0) FROM chat_yuklama cy
          JOIN yuklama y ON y.id = cy.yuklama_id
         WHERE cy.session_id=%(s)s AND cy.uzildi_at IS NULL""",
        {"s": _uuid(session_id)}) or 0
    yangi = db.scalar("SELECT size_bytes FROM yuklama WHERE id=%(i)s",
                      {"i": _uuid(yuklama_id)}) or 0
    if int(jami) + int(yangi) > CHAT_MAX_BAYT:
        raise xatolar.Xato("UPLOAD_QUOTA_EXCEEDED",
                           {"max": CHAT_MAX_BAYT // (1024 * 1024)})

    # Ijarachi mosligini BAZA ham tekshiradi (trigger). Bu yerda
    # xato foydalanuvchiga tushunarli kod bilan qaytadi.
    db.execute_returning("""
        INSERT INTO chat_yuklama (session_id, yuklama_id, company_id)
        VALUES (%(s)s, %(y)s, %(c)s)
        ON CONFLICT (session_id, yuklama_id)
        DO UPDATE SET uzildi_at = NULL
        RETURNING session_id""",
        {"s": _uuid(session_id), "y": _uuid(yuklama_id), "c": company_id})


def chatdan_uz(session_id: str, yuklama_id: str, company_id: int) -> None:
    """Biriktirishni UZADI — o'chirmaydi.

    Javob allaqachon shu faylga tayangan bo'lsa iqtibos ishlayverishi
    kerak (§22). Shuning uchun qator qoladi, faqat `uzildi_at`
    qo'yiladi va fayl keyingi savollarda ishlatilmaydi.
    """
    r = db.execute_returning("""
        UPDATE chat_yuklama SET uzildi_at = now()
         WHERE session_id=%(s)s AND yuklama_id=%(y)s AND company_id=%(c)s
           AND uzildi_at IS NULL
        RETURNING session_id""",
        {"s": _uuid(session_id), "y": _uuid(yuklama_id), "c": company_id})
    if not r:
        raise xatolar.Xato("FILE_NOT_FOUND")


def chat_fayllari(session_id: str, company_id: int,
                  faol_only: bool = True) -> List[Dict[str, Any]]:
    return [dict(r) for r in db.query("""
        SELECT * FROM v_chat_fayl
         WHERE session_id=%(s)s AND company_id=%(c)s
           AND (%(faol)s IS FALSE OR uzildi_at IS NULL)
         ORDER BY created_at""",
        {"s": _uuid(session_id), "c": company_id, "faol": faol_only})]


# =============================================================================
# 5. QIDIRUV — KORPUSLAR ARALASHMAYDI
# =============================================================================
#: Leksik qidiruv. Semantik qism `qidir()` da qo'shiladi.
#:
#: `company_id` HAR IKKALA so'rovda ham WHERE bandida TURADI —
#: `yuklama_id` ro'yxati orqali filtrlash YETARLI EMAS: ro'yxat
#: chaqiruvchidan keladi va bir kun tekshirilmagan joydan kelishi
#: mumkin.
_SQL_LEKSIK = """
SELECT c.id, c.yuklama_id, c.chunk_no, c.text, c.char_start, c.char_end,
       c.sahifa, y.original_nom, y.manba_turi,
       ts_rank(to_tsvector('simple', c.text),
               to_tsquery('simple', %(tsq)s)) AS ball
  FROM yuklama_chunk c
  JOIN yuklama y ON y.id = c.yuklama_id
 WHERE c.company_id = %(company_id)s
   AND y.arxiv_at IS NULL
   AND (%(faylar)s::uuid[] IS NULL OR c.yuklama_id = ANY(%(faylar)s::uuid[]))
   AND (%(manba)s::text IS NULL OR y.manba_turi = %(manba)s)
   AND to_tsvector('simple', c.text) @@ to_tsquery('simple', %(tsq)s)
 ORDER BY ball DESC
 LIMIT %(k)s
"""

#: Vektor qidiruvi — aniq (exact), HNSW siz. Sabab `doc_chunk` da
#: o'lchangan: kichik korpusda aniq qidiruv tezroq VA to'g'riroq.
_SQL_VEKTOR = """
SELECT c.id, c.yuklama_id, c.chunk_no, c.text, c.char_start, c.char_end,
       c.sahifa, y.original_nom, y.manba_turi,
       1 - (c.embedding <=> %(qvec)s::vector) AS ball
  FROM yuklama_chunk c
  JOIN yuklama y ON y.id = c.yuklama_id
 WHERE c.company_id = %(company_id)s
   AND y.arxiv_at IS NULL
   AND c.embedding IS NOT NULL
   AND (%(faylar)s::uuid[] IS NULL OR c.yuklama_id = ANY(%(faylar)s::uuid[]))
   AND (%(manba)s::text IS NULL OR y.manba_turi = %(manba)s)
 ORDER BY c.embedding <=> %(qvec)s::vector
 LIMIT %(k)s
"""


def qidir(company_id: int, savol: str, *,
          faylar: Optional[List[str]] = None,
          manba_turi: Optional[str] = None,
          k: int = 6) -> List[Dict[str, Any]]:
    """Yuklangan fayllardan bo'lak qidiradi.

    `faylar=None` — kompaniyaning HAMMA yuklamasi (chegara `manba_turi`
    bilan qo'yiladi). `faylar=[...]` — FAQAT o'sha fayllar (§19).

    Vektor va leksik natijalar QO'SHILADI, biri ikkinchisini
    almashtirmaydi: embedder yo'q mashinada leksik yolg'iz ishlaydi
    va bu HOLAT NORMAL, degradatsiya emas.
    """
    savol = (savol or "").strip()
    if not savol:
        return []
    fayl_param = [str(uuid.UUID(str(f))) for f in faylar] if faylar else None
    p = {"company_id": company_id, "faylar": fayl_param,
         "manba": manba_turi, "k": k}

    natija: Dict[int, Dict[str, Any]] = {}

    try:
        from api.ai_chat import embed_query, tsquery, vec_literal
    except Exception:                                         # noqa: BLE001
        return []

    tsq = tsquery(savol)
    if tsq:
        for r in db.query(_SQL_LEKSIK, {**p, "tsq": tsq}):
            natija[r["id"]] = {**dict(r), "topilish": "leksik"}

    try:
        qvec = vec_literal(embed_query(savol))
    except Exception:                                         # noqa: BLE001
        qvec = None
    if qvec:
        for r in db.query(_SQL_VEKTOR, {**p, "qvec": qvec}):
            oldin = natija.get(r["id"])
            if oldin:
                oldin["topilish"] = "leksik+semantik"
            else:
                natija[r["id"]] = {**dict(r), "topilish": "semantik"}

    # `leksik+semantik` oldinda: ikki mustaqil usul bir bo'lakni
    # topgani — eng kuchli signal.
    tartib = {"leksik+semantik": 0, "semantik": 1, "leksik": 2}
    return sorted(natija.values(),
                  key=lambda r: (tartib[r["topilish"]], -float(r["ball"] or 0))
                  )[:k]
