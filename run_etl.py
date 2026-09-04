#!/usr/bin/env python3
"""
ETL ORKESTRATORI (H bosqich) — barcha manbalarni yangilaydi + jurnal yozadi
===========================================================================
Cron/launchd/Task Scheduler shu skriptni chaqiradi. Har MANBA yurishi
`etl_run` jadvaliga yoziladi (sog'lik + yangi topilgan tenderlar soni).
Bu tufayli:
  - "oxirgi yangilanish qachon", "nechta yangi topildi" — o'lchanadigan
  - biror manba buzilsa (sayt o'zgardi/tushdi) — status='error' qoladi (jimgina
    o'tkazib yuborilmaydi, TZ NFT talabi)

first_seen_at (schema_patch_freshness.sql) UPSERT'da saqlanadi, shuning uchun
"biz birinchi qachon ko'rdik" aniq qoladi -> aniqlash-kechikishini o'lchaymiz.

QAMROV (nega bir manbada bir nechta qadam bor)
----------------------------------------------
Har platforma BIR EMAS, bir nechta ochiq reyestrni chop etadi. Faqat bittasini
yig'ish ochiq lotlarning katta qismini yo'qotadi:
  xt-xarid : ref_tender_public  +  ref_selection_public
  uzex     : TypeId=2 (tender)  +  TypeId=1 ("eng yaxshi taklifni tanlash")
Shuning uchun har platforma "guruh" bo'lib, ichida bir nechta qadam bor.

PARALLELIK QOIDASI (ongli qaror)
--------------------------------
  - GURUHLAR (platformalar) O'ZARO PARALLEL yuriladi — turli hostlar, bir-biriga
    xalaqit bermaydi. Umumiy vaqt = eng sekin platforma vaqti.
  - GURUH ICHIDA qadamlar KETMA-KET yuriladi — ular BITTA hostga uriladi va
    parallel yurgizish so'rov tezligini ikki barobar oshirib, manba
    rate-limitini hurmat qilmaslikka olib keladi.
  - `etl_run` guruh boshida bitta qator ochadi va guruh oxirida yopadi, ya'ni
    jurnalda har platforma uchun bitta yozuv qoladi (dashboard "Yangilangan"
    ko'rsatkichi shunga tayanadi) va `new` metrikasi ikki marta sanalmaydi.

Ishga tushirish:
    # DSN .env dan avtomatik o'qiladi (XT_DB_DSN)
    python run_etl.py                 # tez: barcha manbalar + kategoriyalar
    python run_etl.py --with-docs     # + hujjatlar (sekinroq)
    python run_etl.py --all-statuses  # ochiq emas, hammasi (qimmat)
    python run_etl.py --limit 3       # SINOV: har manbadan 3 yozuv
    python run_etl.py --sequential    # parallelsiz (nosozlikni izlashda)
"""
import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

try:
    import psycopg2
except ImportError:
    psycopg2 = None

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv bo'lmasa ham muhit o'zgaruvchisi bilan ishlayveradi
    load_dotenv = None

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable  # o'sha venv python'i

# Chiqishni parallel oqimlarda aralashtirib yubormaslik uchun
_PRINT_LOCK = threading.Lock()


def emit(lines: List[str]) -> None:
    """Bir nechta qatorni ATOMAR chiqaradi (parallel guruhlar aralashmasin)."""
    with _PRINT_LOCK:
        for ln in lines:
            print(ln)
        sys.stdout.flush()


#: `.env` o'qildimi. IZOH EMAS, QULF: 1-nosozlikda `sole_company_id()`
#: `load_dotenv()` DAN OLDIN chaqirilgan edi va buni hech narsa
#: to'xtatmagan — izoh esa aynan o'sha xato sinfini tasvirlab turardi.
#: Endi bazaga tegadigan har yo'l shu bayroqni talab qiladi.
_ENV_YUKLANDI = False


def env_shart(kim: str) -> None:
    """Baza yo'li `.env` o'qilishidan OLDIN ochilmasin."""
    if not _ENV_YUKLANDI:
        raise RuntimeError(
            f"{kim}: `.env` hali o'qilmagan. DSN ga bog'liq har chaqiruv "
            "`load_dotenv()` DAN KEYIN turishi shart — aks holda "
            "`XT_DB_DSN` topilmaydi va qadam JIMGINA o'tkazib "
            "yuboriladi (2026-08 da shu sababli talab ajratish ikki "
            "hafta ishlamagan).")


def db():
    env_shart("db()")
    return psycopg2.connect(os.environ["XT_DB_DSN"])


def close_stale_runs(stale_hours: float = 2.0) -> int:
    """Muzlab qolgan `running` yozuvlarini yopadi (yurish BOSHIDA chaqiriladi).

    NEGA KERAK: `run_group` yozuvni faqat NORMAL tugaganda `UPDATE` qiladi.
    Jarayon majburan o'ldirilsa (Task Scheduler vaqt chegarasi, kompyuter
    uxlashi, `taskkill /F` — LastTaskResult 0xC000013A) qator abadiy
    'running' bo'lib qoladi. Buning ikki oqibati bor edi:
      - /freshness "yangilanmoqda" deb ko'rsatardi, aslida hech narsa yurmasdi
      - haqiqiy nosozlik 'error' sifatida ko'rinmasdi (TZ NFT talabiga zid)

    `try/finally` bu yerda YORDAM BERMAYDI: SIGKILL/taskkill /F da Python
    umuman kod bajarmaydi. Shuning uchun tozalash keyingi yurish boshida.

    O'LCHOV TUZATILDI (2026-08-30). Ilgari `finished_at = now()` edi,
    ya'ni "qachon PAYQADIK". Natijada 3-daqiqada o'lgan yurish jurnalda
    45 SOAT davom etgan bo'lib ko'rinardi va davomiylik metrikasi
    butunlay ma'nosiz edi:

        uzex 'error' davomiyligi: o'rtacha 421 daq, maksimum 2700 daq
        uzex 'ok'    davomiyligi: o'rtacha 1.9 daq

    Endi `finished_at = heartbeat_at`, ya'ni "qachon ishlashdan
    TO'XTADI". Heartbeat yo'q bo'lsa (darhol o'lgan yoki eski qator)
    `finished_at` NULL qoladi — bu O'LCHANMAGANLIK, va
    `v_etl_run_olchov` uni o'rtachaga QO'SHMAYDI. O'lchanmagan narsani
    nolga aylantirish "tez ishladi" degan yolg'on berardi.

    Qaytadi: yopilgan qatorlar soni.
    """
    conn = db()
    try:
        with conn.cursor() as cur:
            # `terminal_reason` HAR DOIM 'uzildi' bo'ladi, bolaning oxirgi
            # yozganidan qat'i nazar. Sabab: bola qadam TUGATGAN bo'lishi
            # mumkin ('tugadi'), lekin YURISH baribir uzilgan — ota-jarayon
            # qatorni yopishga ulgurmagan. `status='error'` +
            # `terminal_reason='tugadi'` ziddiyatli o'qilardi.
            # Bolaning oxirgi sababi YO'QOLMAYDI: u `error` matniga qo'shiladi.
            cur.execute(
                "UPDATE etl_run SET status='error', "
                "  finished_at = heartbeat_at, "
                "  error = COALESCE(NULLIF(error, '') || E'\\n', '') || %s "
                "          || COALESCE(' (bola oxirgi holati: '"
                "                      || terminal_reason || ')', ''), "
                "  terminal_reason = 'uzildi' "
                "WHERE status='running' "
                "  AND started_at < now() - (%s * interval '1 hour')",
                ("yurish tugamasdan uzildi (jarayon majburan to'xtatilgan yoki "
                 "kompyuter uxlagan); keyingi yurish boshida yopildi",
                 stale_hours))
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def expire_stale_tenders(platforms: List[str]) -> int:
    """Muddati o'tgan 'open' yozuvlarni 'expired' ga o'tkazadi.

    NEGA KERAK: manba tenderni yopgach uni ochiq reyestrdan OLIB TASHLAYDI —
    "yopildi" degan xabar KELMAYDI. Ya'ni bizdagi 'open' o'z-o'zidan hech
    qachon o'zgarmaydi va yig'ilib boraveradi (2026-08-12 da 915 ta yozuv).
    Ro'yxat so'rovlari buni `close_at > now()` yamog'i bilan yashirardi, lekin
    yamoq faqat status='open' filtrida ishlaydi: "Barcha statuslar" ko'rinishida
    va tender kartochkasida muddati o'tgan yozuv baribir "Ochiq" bo'lib turardi.

    FAQAT MUVAFFAQIYATLI yurgan platformalar supuriladi. Manba javob bermay
    qolgan bo'lsa bizdagi ma'lumot ESKI — o'shanga qarab "muddati tugadi" deb
    xulosa chiqarish bugun tugaydigan tenderlarni noto'g'ri o'chirib qo'yardi.

    Qaytadi: o'zgargan qatorlar soni.
    """
    if not platforms:
        return 0
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tender SET status='expired' "
                "WHERE status='open' AND close_at IS NOT NULL AND close_at <= now() "
                "  AND source_platform = ANY(%s)",
                (platforms,))
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def _lugat_va_markaz() -> List[str]:
    """Tasniflagich lug'atini va embedding markazini qayta hisoblaydi.

    SOF SQL — model chaqirilmaydi. Qaytadi: xatolar ro'yxati (bo'sh =
    muvaffaqiyat).

    MUVAFFAQIYAT MUSBAT SHARTDAN TEKSHIRILADI: `recompute_centroid()`
    namuna 50 dan kam bo'lsa NULL qaytaradi va istisno CHIQARMAYDI.
    Ya'ni "xato bo'lmadi" bu yerda "ish bajarildi" degani EMAS —
    natijani ALOHIDA o'qiymiz.
    """
    xatolar: List[str] = []
    try:
        env_shart("_lugat_va_markaz()")
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('dim_good_code') AS t")
                if cur.fetchone()[0] is None:
                    emit(["  [i] tasniflagich sxemasi yo'q — o'tkazildi "
                          "(schema_patch_goodcode.sql)"])
                    return ["dim_good_code yo'q: schema_patch_goodcode.sql qo'llanmagan"]

                cur.execute("SELECT count(*) FROM dim_good_code")
                oldin = cur.fetchone()[0]
                cur.execute("SELECT * FROM rebuild_good_code_dict()")
                cur.fetchall()
                cur.execute("SELECT count(*) FROM dim_good_code")
                keyin = cur.fetchone()[0]
                emit([f"  [i] lug'at: {oldin} -> {keyin} kod"])

                cur.execute("SELECT recompute_centroid()")
                markaz = cur.fetchone()[0]
                if markaz is None:
                    # JIMGINA O'TKAZIB YUBORMAYMIZ.
                    xatolar.append(
                        "recompute_centroid() NULL qaytardi — namuna 50 dan kam. "
                        "Markazlangan qidiruv ESKI markaz bilan ishlaydi.")
                else:
                    cur.execute("SELECT n_source FROM embed_centroid WHERE id=%s",
                                (markaz,))
                    emit([f"  [i] markaz #{markaz} ({cur.fetchone()[0]} tender)"])

                cur.execute("SELECT * FROM v_centroid_stale")
                st = cur.fetchall()
                for r in st:
                    # r = (model, faol_markaz, jami, markazlanmagan, eskirgan)
                    if (r[3] or 0) or (r[4] or 0):
                        xatolar.append(
                            f"markazlanmagan={r[3]} eskirgan={r[4]} ({r[0]})")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:                                   # noqa: BLE001
        xatolar.append(f"lug'at/markaz: {e}")
    return xatolar


def _hub_yangila() -> List[str]:
    """Hublik tuzatmasini qayta hisoblaydi (markaz o'zgargach MAJBURIY).

    Markaz o'zgarsa `embedding_c` o'zgaradi, ya'ni eski `hub_bias`
    boshqa fazoning o'lchovi bo'lib qoladi. Buni o'tkazib yuborish
    semantik taklifni jimgina yomonlashtiradi.
    """
    xatolar: List[str] = []
    try:
        env_shart("_hub_yangila()")
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM recompute_hub_bias(10)")
                n, o_rt, mx = cur.fetchone()
                emit([f"  [i] hublik: {n} kod, o'rtacha {o_rt:.3f}, max {mx:.3f}"])
                cur.execute("SELECT * FROM v_hub_stale")
                v, biassiz, eskirgan = cur.fetchone()
                if (biassiz or 0) or (eskirgan or 0):
                    xatolar.append(f"hublik: biassiz={biassiz} eskirgan={eskirgan}")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:                                   # noqa: BLE001
        xatolar.append(f"hublik: {e}")
    return xatolar


def platform_count(conn, platform: str, since=None) -> int:
    with conn.cursor() as cur:
        if since:
            cur.execute("SELECT count(*) FROM tender WHERE source_platform=%s "
                        "AND first_seen_at >= %s", (platform, since))
        else:
            cur.execute("SELECT count(*) FROM tender WHERE source_platform=%s", (platform,))
        return cur.fetchone()[0]


# Chiqish kodlarining ma'nosi — Windows'da bola jimgina o'lishi mumkin.
_EXIT_MEANING = {
    -1073741510: "Ctrl+C yoki majburiy to'xtatish (STATUS_CONTROL_C_EXIT)",
    -1073741819: "segmentatsiya xatosi (ACCESS_VIOLATION)",
    -1: "jarayon tashqaridan o'ldirilgan",
}


#: Foydalanuvchi konsolda Ctrl+C bosganida ota-jarayon ham signal oladi.
#: Shu bayroq `run_script` ga "bu HAQIQIY uzilish, qayta urinma" deb
#: aytadi. Aks holda qayta urinish foydalanuvchi to'xtatgan yurishni
#: o'jarlik bilan davom ettirardi.
_UZILDI = False


def _yuv() -> None:
    """Jurnalni DISKKA majburan yozadi.

    Seans tugaganda Windows `CTRL_LOGOFF_EVENT` yuboradi va ~5 soniya
    beradi. Ota-jarayon chiqishi FAYLGA yo'naltirilgan, ya'ni Python
    uni BLOK-buferlaydi (~8 KB) — o'sha 5 soniyada bufer yuvilmasa
    butun jurnal yo'qoladi. `flush()` yetarli emas: u faqat OT
    buferigacha olib boradi.
    """
    try:
        sys.stdout.flush()
        os.fsync(sys.stdout.fileno())
    except Exception:                                       # noqa: BLE001
        pass                    # quvur yoki konsol bo'lsa fsync ishlamaydi


def _uzilish_qabul(signum, frame):        # noqa: ARG001
    global _UZILDI
    _UZILDI = True
    _yuv()
    raise KeyboardInterrupt


#: 0xC000013A — "majburan to'xtatildi". Windows'da bu FAQAT Ctrl+C
#: degani emas: mashina uyquga ketsa yoki o'chsa ham bola shu kod bilan
#: o'ladi. Jurnalda 14 kun ichida 100 marta uchradi (uchta har xil
#: skriptda, kunning har soatida, ~10% yurish) va shu vaqt ichida
#: hech kim konsolda o'tirmagan edi.
#:
#: Kernel-Power 109 hodisalari (14 kunda 31 ta) buning bir qismini
#: tushuntiradi. Sababni to'liq aniqlab bo'lmadi, lekin oqibati aniq:
#: yangi tenderlar YIG'ILMAY qolardi va yurish baribir "OK" derdi.
UZILISH_KODI = 3221225786


def _fail_reason(res: "subprocess.CompletedProcess") -> str:
    """Muvaffaqiyatsiz bola uchun O'QILADIGAN sabab.

    Ilgari `res.stderr or res.stdout or ""` qaytarilardi va bola hech narsa
    chiqarmasdan o'lsa BO'SH satr qolardi: jurnalda "!! XATO:" bor, sabab yo'q.
    """
    code = res.returncode
    head = f"chiqish kodi {code}"
    meaning = _EXIT_MEANING.get(code)
    if meaning:
        head += f" — {meaning}"
    body = (res.stderr or "").strip() or (res.stdout or "").strip()
    return f"{head}\n{body[-500:]}" if body else f"{head} (chiqish bo'sh)"


def _sanoq(sql: str, params: Optional[dict] = None) -> Optional[int]:
    """Bitta son o'qiydi. Baza yetib bo'lmasa `None` — bu O'LCHOVSIZLIK,
    xato emas, va shunday ham hisoblanadi."""
    try:
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                row = cur.fetchone()
                return int(row[0]) if row else None
        finally:
            conn.close()
    except Exception:                                       # noqa: BLE001
        return None


#: Vektorlanmagan bo'laklar.
SQL_VEKTOR_QOLGAN = "SELECT count(*) FROM doc_chunk WHERE embedding IS NULL"

#: Vektorlash bo'lagining hajmi.
#:
#: 500 ~ 85 soniya (o'lchangan: 1000 bo'lak 170 s). Kichikroq bo'lak
#: ko'proq jurnal beradi, lekin har chaqiruv model yuklashini qayta
#: qiladi — 500 shu ikkisi orasidagi muvozanat.
VEKTOR_BOLAK = 500

#: Yo'naltirish navbati hajmi. Bu qadam navbatni QISQARTIRMAYDI —
#: aksincha to'ldiradi, shuning uchun `siljish_tekshir()` mos kelmaydi
#: va o'z tekshiruvi bor (quyida).
SQL_NAVBAT_HAJMI = ("SELECT count(*) FROM v_routing_queue "
                    "WHERE company_id = %(company_id)s")

#: Shu usul bilan hali ajratilmagan OCHIQ tenderlar. `api.requirement`
#: dagi `SQL_PENDING` bilan BIR XIL shart — u yerda o'zgarsa bu yer ham
#: o'zgarishi kerak, shuning uchun sinov ikkalasini taqqoslaydi.
SQL_TALAB_QOLGAN = """
SELECT count(*) FROM tender t
WHERE (t.close_at IS NULL OR t.close_at > now())
  AND (
    NOT EXISTS (
        SELECT 1 FROM tender_requirement_run r
        WHERE r.tender_id = t.id AND r.company_id = %(company_id)s
          AND r.method = %(method)s)
    OR EXISTS (
        SELECT 1 FROM tender_requirement_run r
        WHERE r.tender_id = t.id AND r.company_id = %(company_id)s
          AND r.method = %(method)s AND r.status = 'no_text'
          AND EXISTS (SELECT 1 FROM doc_chunk c WHERE c.tender_id = t.id))
  )
"""


def siljish_tekshir(nom: str, oldin: Optional[int], keyin: Optional[int],
                    xatolar: List[str]) -> None:
    """MUSBAT TASDIQ: navbat bor edi — kamaydimi?

    NEGA KERAK. `post_xatolar` — to'g'ri, lekin u hali SALBIY shart:
    "istisno chiqmadi". Skript `0` qaytarib, hech narsa qilmasligi
    ham mumkin — aynan shu ikki hafta davomida sodir bo'ldi:
    talab ajratish har soat o'tkazib yuborilar, quvur esa
    "hammasi muvaffaqiyatli" derdi.

    Endi yurish ISH QILGANINI ISBOTLASIN.

    `None` — o'lchab bo'lmadi (baza yetib bo'lmadi). Bu ham xato
    sanaladi: o'lchovsiz "muvaffaqiyat" da'vosi asossiz.
    """
    if oldin is None or keyin is None:
        xatolar.append(f"{nom}: siljish O'LCHANMADI (bazaga yetib bo'lmadi)")
        return
    if oldin == 0:
        print(f"  [i] {nom}: navbat bo'sh edi — qiladigan ish yo'q")
        return
    if keyin >= oldin:
        xatolar.append(
            f"{nom}: navbatda {oldin} ta bor edi, lekin KAMAYMADI "
            f"({oldin} -> {keyin}). Skript istisno bermadi, ammo ISH "
            "HAM QILMADI")
        return
    print(f"  [OK] {nom}: {oldin} -> {keyin} ({oldin - keyin} ta bajarildi)")


#: Bola skriptlarining KELISHILGAN chiqish kodlari. 0/1 dan boshqa
#: kodlar ATAYLAB: "tugallanmagan" va "band" — bu XATO ham, MUVAFFAQIYAT
#: ham emas, va ularni bir-biriga qo'shib yuborish quvur sog'ligini
#: noto'g'ri ko'rsatardi.
KOD_TUGADI = 0
KOD_QISMAN = 7      # vaqt byudjeti/to'xtash — checkpoint yozilgan
KOD_BAND   = 8      # boshqa yurish shu manbani olib turibdi

#: Chiqish kodi -> (guruh holati uchun hissa, tugash sababi)
_KOD_MANOSI = {
    KOD_TUGADI: ("ok",      "tugadi"),
    KOD_QISMAN: ("partial", "qisman"),
    KOD_BAND:   ("band",    "band"),
}


def run_script(script: str, extra_args: List[str],
               run_id: Optional[int] = None
               ) -> Tuple[bool, Optional[str], float, List[str], int]:
    """Bitta ETL skriptini bola-jarayon sifatida yurgizadi.

    Qaytadi: (ok, xato_matni, sekund, chiqish_qatorlari, chiqish_kodi)

    `run_id` bola muhitiga `ETL_RUN_ID` bo'lib beriladi. Bola metrikani
    (processed/succeeded/failed/...) SHU qatorga O'ZI yozadi.

    NEGA MUHIT ORQALI, chiqishni parsing qilib emas: majburan
    to'xtatilgan bola HECH NARSA CHOP ETMAYDI (bufer yuvilmaydi), ya'ni
    chiqishga tayangan metrika aynan biz o'lchamoqchi bo'lgan holatda —
    o'ldirilgan yurishda — yo'qolardi. Bazaga to'g'ridan-to'g'ri yozuv
    esa o'lim paytigacha bo'lgan hamma narsani saqlab qoladi.

    MUHIM (Windows): bola-jarayon chiqishi UTF-8 deb dekodlanadi va
    PYTHONIOENCODING=utf-8 bola muhitiga beriladi. Aks holda kirill matnда
    UnicodeDecodeError chiqib, BOLA CHIQISHI BUTUNLAY YO'QOLADI — ya'ni xato
    jimgina o'tib ketishi mumkin edi.

    PYTHONUNBUFFERED=1 ham beriladi. Bola chiqishi QUVURGA ketadi, ya'ni Python
    uni blok-buferlaydi (~8 KB). Jarayon majburan o'ldirilsa (konsolda Ctrl+C,
    Task Scheduler vaqt chegarasi) bufer YUVILMAYDI va butun chiqish yo'qoladi.
    Jurnalda aynan shu ko'rinardi: "!! XATO:" — keyin BO'SHLIQ, sababi yo'q.
    """
    out: List[str] = [f"--- {script} {' '.join(extra_args)} ---"]
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if run_id is not None:
        env["ETL_RUN_ID"] = str(run_id)
    ok, err, kod = False, None, -1
    for urinish in (1, 2):
        try:
            res = subprocess.run([PY, os.path.join(HERE, script), *extra_args],
                                 cwd=HERE, env=env,
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace",
                                 timeout=3600)
            kod = res.returncode
            # `ok` = "xato bo'lmadi". QISMAN va BAND xato EMAS: birinchisi
            # checkpoint yozib toza to'xtadi, ikkinchisi ataylab
            # o'tkazib yuborildi. Ularni 'error' deb belgilash
            # quvurni sog'lom bo'lgani holda kasal ko'rsatardi.
            ok = kod in _KOD_MANOSI
            tail = "\n".join((res.stdout or "").strip().splitlines()[-4:])
            if tail:
                out.extend(f"    {ln}" for ln in tail.splitlines())
            # Chiqish umuman bo'lmasa ham xato SABABSIZ qolmasin: kod har
            # doim yoziladi (0xC000013A = majburiy to'xtatish, 1 = Python).
            err = None if ok else _fail_reason(res)
            # BIR MARTA qayta urinish — faqat MAJBURAN TO'XTATILGANDA.
            # Boshqa xatolar (Python xatosi, tarmoq, DSN) qayta
            # urinishdan tuzalmaydi va vaqtni behuda sarflardi.
            if (not ok and urinish == 1 and res.returncode == UZILISH_KODI
                    and not _UZILDI):
                out.append("    !! majburan to'xtatildi — qayta urinilmoqda")
                out = out[:1] + out[-1:]        # birinchi urinish chiqishi
                continue
        except subprocess.TimeoutExpired:
            ok, err, kod = False, "timeout (1 soat)", -2
        except KeyboardInterrupt:
            ok, err, kod = False, "foydalanuvchi to'xtatdi (Ctrl+C)", -3
        except Exception as e:  # noqa: BLE001
            ok, err, kod = False, str(e)[:500], -4
        break

    dt = time.time() - t0
    if not ok:
        out.append(f"    !! XATO: {(err or '').strip()[:300]}")
    belgi = {KOD_TUGADI: "OK", KOD_QISMAN: "QISMAN",
             KOD_BAND: "BAND"}.get(kod, "XATO")
    out.append(f"  [{belgi}] {script} — {dt:.0f}s")
    return ok, err, dt, out, kod


def run_group(platform: str, steps: List[Tuple[str, List[str]]],
              log: bool = True) -> bool:
    """Bitta platformaning barcha qadamlarini KETMA-KET yurgizadi va butun
    guruh uchun BITTA `etl_run` yozuvini ochadi/yopadi.

    Bir host = bir guruh: guruh ichida ketma-ketlik manba rate-limitini
    hurmat qiladi, guruhlar esa tashqarida parallel yuriladi.
    """
    conn = db() if log else None
    run_id = started = None
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO etl_run (source_platform, status) VALUES (%s,'running') "
                        "RETURNING id, started_at", (platform,))
            run_id, started = cur.fetchone()
        conn.commit()

    # Har qadam TUGAGACH atomar chiqariladi (butun guruhni kutmasdan) — uzex
    # qadami ~10 daqiqa yurishi mumkin, jonli qayta aloqa yo'qolmasin.
    emit([f"\n===== {platform}: {len(steps)} qadam ====="])
    all_ok = True
    qismanmi = False
    bandmi = True                 # hamma qadam BAND bo'lsagina guruh band
    errors: List[str] = []
    t0 = time.time()
    for script, extra in steps:
        ok, err, _dt, out, kod = run_script(script, extra, run_id)
        emit([f"[{platform}] " + ln for ln in out])
        if kod != KOD_BAND:
            bandmi = False
        if kod == KOD_QISMAN:
            qismanmi = True
        if not ok:
            all_ok = False
            errors.append(f"{script} {' '.join(extra)}: {(err or '').strip()[:200]}")
    dt = time.time() - t0

    # HOLAT UCH XIL, IKKI XIL EMAS.
    #   error   — haqiqiy nosozlik, ma'lumot eskirgan bo'lishi mumkin
    #   partial — ish bajarildi, lekin tugamadi; checkpoint bor,
    #             keyingi yurish davom ettiradi
    #   ok      — to'liq tugadi
    # `partial` ni 'ok' deb belgilash TUGALLANMAGAN YURISHNI
    # MUVAFFAQIYATLI ko'rsatardi; 'error' deb belgilash esa ishlagan
    # quvurni kasal ko'rsatardi. Ikkalasi ham yolg'on.
    if not all_ok:
        status, sabab = "error", "manba_xato"
    elif bandmi and steps:
        status, sabab = "ok", "band"
    elif qismanmi:
        status, sabab = "partial", "qisman"
    else:
        status, sabab = "ok", "tugadi"

    lines: List[str] = []
    belgi = {"ok": "OK", "partial": "QISMAN", "error": "XATO"}[status]
    if conn is not None:
        found = platform_count(conn, platform)
        new = platform_count(conn, platform, since=started) if started else None
        with conn.cursor() as cur:
            cur.execute("UPDATE etl_run SET finished_at=now(), heartbeat_at=now(), "
                        "status=%s, found=%s, new=%s, error=%s, "
                        "terminal_reason=COALESCE(terminal_reason, %s) "
                        "WHERE id=%s",
                        (status, found, new, "\n".join(errors)[:2000] or None,
                         sabab, run_id))
            cur.execute("SELECT processed, succeeded, failed, retried, resumed, "
                        "skipped FROM etl_run WHERE id=%s", (run_id,))
            m = cur.fetchone() or (0, 0, 0, 0, 0, 0)
        conn.commit()
        lines.append(f"  => {platform}: [{belgi}/{sabab}] {dt:.0f}s | "
                     f"jami {found}, yangi {new}")
        lines.append(f"     ko'rildi {m[0]}, yozildi {m[1]}, yiqildi {m[2]}, "
                     f"qayta urinish {m[3]}, tiklandi {m[4]}, o'tkazildi {m[5]}")
    else:
        lines.append(f"  => {platform}: [{belgi}/{sabab}] {dt:.0f}s")
    if conn is not None:
        conn.close()

    emit(lines)
    # Qaytadigan qiymat "MA'LUMOT ISHONCHLIMI" degani — `expire_stale_tenders`
    # shunga tayanadi. QISMAN yurishda manba to'liq ko'rilmagan, ya'ni
    # "manbada yo'q => muddati tugadi" xulosasi noto'g'ri bo'lardi.
    return status == "ok"


def build_groups(args) -> List[Tuple[str, List[Tuple[str, List[str]]]]]:
    """Platforma -> ketma-ket qadamlar ro'yxati.

    VAQT BYUDJETI GURUH BO'YICHA TAQSIMLANADI. Guruh ichidagi qadamlar
    KETMA-KET yuradi (bir host, rate-limit hurmati), ya'ni ularning
    byudjetlari QO'SHILADI. Byudjetni har qadamga to'liq berish
    guruhni ikki barobar uzaytirardi va rejalashtiruvchi chegarasidan
    oshib ketardi — o'shanda Windows uni O'LDIRADI va aynan biz
    tuzatmoqchi bo'lgan holat qaytadi.
    """
    status_args = ["--all-statuses"] if args.all_statuses else []
    limit_args = ["--limit", str(args.limit)] if args.limit else []

    xt_steps: List[Tuple[str, List[str]]] = [
        # Ikkala ochiq reyestr ham kerak — bittasi ochiq lotlarning katta
        # qismini yo'qotadi (ID fazolari kesishmaydi, tekshirilgan).
        ("etl_tenders.py", ["--ref", "ref_tender_public", *status_args, *limit_args]),
        ("etl_tenders.py", ["--ref", "ref_selection_public", *status_args, *limit_args]),
    ]
    if args.with_docs:
        # Hujjatlar ham xt-xarid hostiga uriladi -> shu guruh ichida, ketma-ket
        xt_steps.append(("etl_details.py", []))

    uzex_steps: List[Tuple[str, List[str]]] = [
        ("etl_uzex.py", ["--type-id", "2", *limit_args]),
        ("etl_uzex.py", ["--type-id", "1", *limit_args]),
    ]

    guruhlar = [("xt-xarid", xt_steps), ("uzex", uzex_steps)]

    byudjet = getattr(args, "max_seconds", 0) or 0
    if byudjet > 0:
        for _platform, steps in guruhlar:
            # Byudjeti bor skriptlar: uzex va details. `etl_tenders.py`
            # ~7 sekundda tugaydi va unga byudjet kerak emas.
            byudjetli = [s for s in steps
                         if s[0] in ("etl_uzex.py", "etl_details.py")]
            if not byudjetli:
                continue
            ulush = max(60.0, byudjet / len(byudjetli))
            for script, extra in byudjetli:
                extra.extend(["--max-seconds", f"{ulush:.0f}"])
    return guruhlar


def limit_args_for(args) -> List[str]:
    """Post-qadamlarga `--limit` ni uzatadi (sinov yurishlarini qisqartirish)."""
    return ["--limit", str(args.limit)] if args.limit else []


def main() -> None:
    ap = argparse.ArgumentParser(description="ETL orkestratori (H bosqich)")
    ap.add_argument("--with-docs", action="store_true", help="Hujjatlarni ham (sekinroq)")
    ap.add_argument("--docs-all", action="store_true",
                    help="Hujjat qamrovini o'chiradi: muddati o'tgan "
                         "tenderlar ham o'qiladi (juda sekin)")
    ap.add_argument("--docs-catalog", action="store_true",
                    help="ESKI tor qamrov: faqat katalogga mos tenderlar "
                         "(2026-08 da amalda tugagan — 3 ta hujjat beradi)")
    ap.add_argument("--only-rag", action="store_true",
                    help="FAQAT RAG quvuri: manba ETL, kategoriyalash va "
                         "bildirishnoma o'tkazib yuboriladi. Alohida "
                         "(kamroq tez-tez) rejalashtirilgan vazifa uchun — "
                         "vektorlash uzoq va soatlik bildirishnomani "
                         "kechiktirmasligi kerak")
    ap.add_argument("--with-rag", action="store_true",
                    help="Bo'laklash + tender vektorlari + bo'lak vektorlari "
                         "(chat YANGI tenderni ko'rishi uchun SHART)")
    ap.add_argument("--with-requirements", action="store_true",
                    help="Talablarni NAQSH bilan ajratadi (bepul). "
                         "`--only-rag` bunda avtomatik yoqiladi")
    ap.add_argument("--company", type=int, default=None,
                    help="Talab ajratish qaysi kompaniya uchun. "
                         "Berilmasa YAGONA faol hisob olinadi")
    ap.add_argument("--vector-budget", type=int, default=3000,
                    help="Bir yurishda nechta bo'lak vektorlanadi (standart "
                         "3000 ~ 15 daqiqa). 0 = vektorlashni o'tkazib yubor")
    ap.add_argument("--all-statuses", action="store_true", help="Barcha statuslar (qimmat)")
    ap.add_argument("--limit", type=int,
                    help="SINOV: har manbadan faqat N yozuv (to'liq yurish o'rniga)")
    ap.add_argument("--sequential", action="store_true",
                    help="Platformalarni parallel emas, ketma-ket yurgiz")
    ap.add_argument("--skip-categorize", action="store_true",
                    help="Kategoriyalash post-qadamini o'tkazib yubor")
    ap.add_argument("--skip-notify", action="store_true",
                    help="Bildirishnoma (email/Telegram) post-qadamini o'tkazib yubor")
    ap.add_argument("--max-seconds", type=float, default=1500.0,
                    help="Bitta PLATFORMA guruhining vaqt byudjeti (standart "
                         "1500 = 25 daqiqa). Byudjet tugaganda skript "
                         "checkpoint yozib TOZA to'xtaydi va keyingi yurish "
                         "shu yerdan davom etadi. Rejalashtiruvchi "
                         "ExecutionTimeLimit dan ANIQ KICHIK bo'lishi shart: "
                         "chegara tugaganda Windows jarayonni O'LDIRADI va "
                         "checkpoint yozilmay qoladi. 0 = cheksiz")
    ap.add_argument("--stale-hours", type=float, default=2.0,
                    help="Shuncha soatdan eski 'running' yozuvlar uzilgan deb "
                         "yopiladi (standart 2; ETL vaqt chegarasi ham 2 soat)")
    args = ap.parse_args()

    # Ctrl+C ni BELGILAB qo'yamiz: shundan keyin `run_script` majburan
    # to'xtatilgan bolani qayta urinmaydi.
    # SIGBREAK ham: Windows'da `CTRL_BREAK_EVENT` shunga tushadi.
    for _sig in ("SIGINT", "SIGBREAK", "SIGTERM"):
        try:
            signal.signal(getattr(signal, _sig), _uzilish_qabul)
        except (ValueError, AttributeError, OSError):
            pass                # bu platformada yo'q yoki asosiy oqim emas

    # Chiqishni QATOR-QATOR yuvamiz. Faylga yo'naltirilganda Python
    # blok-buferlaydi va majburan to'xtatishda butun jurnal yo'qoladi.
    #
    # KODLASH HAM SHU YERDA. O'lchangan nuqson (2026-08-30): orkestrator
    # bola chiqishidagi `✓` belgisini chop etishda `UnicodeEncodeError`
    # bilan YIQILDI va BUTUN yurishni to'xtatdi — ya'ni jurnal yozuvi
    # ish jarayonini o'ldirdi.
    #
    # Rejalashtiruvchi orqali yurganda bu KO'RINMASDI: `register_task.ps1`
    # cmd wrapperi `PYTHONIOENCODING=utf-8` beradi. Ya'ni nuqson faqat
    # qo'lda yurgizganda chiqardi va shu sababli uzoq payqalmadi.
    # Endi skript O'ZI kafolatlaydi, muhitga tayanmaydi.
    for _oqim in (sys.stdout, sys.stderr):
        try:
            _oqim.reconfigure(encoding="utf-8", errors="replace",
                              line_buffering=True)
        except Exception:                                   # noqa: BLE001
            pass

    # `--only-rag` — qulaylik bayrog'i: RAG uchun kerak bo'lgan hamma
    # narsani yoqadi, qolganini o'chiradi. Foydalanuvchi to'rtta
    # bayroqni eslab qolmasin.
    if args.only_rag:
        args.with_docs = True
        args.with_rag = True
        args.with_requirements = True
        args.skip_categorize = True
        args.skip_notify = True

    # .env dan XT_DB_DSN — Windows'da muhit o'zgaruvchisi odatda o'rnatilmagan
    # (uni faqat bash wrapper run_etl.sh berardi). Bu qator bo'lmasa har
    # yurish "XATO: XT_DB_DSN o'rnatilmagan" bilan tugardi.
    if load_dotenv is not None:
        load_dotenv(os.path.join(HERE, ".env"))
    global _ENV_YUKLANDI
    _ENV_YUKLANDI = True

    if psycopg2 is None:
        sys.exit("XATO: pip install psycopg2-binary")
    if not os.environ.get("XT_DB_DSN"):
        sys.exit("XATO: XT_DB_DSN o'rnatilmagan (.env yoki muhit o'zgaruvchisi).")

    # `results` faqat MANBA guruhlarini qamraydi. Post-qadam nosozliklari
    # shu yerga yig'iladi va chiqish kodiga ta'sir qiladi.
    post_xatolar: List[str] = []

    # Kompaniya berilmasa YAGONA faol hisobni olamiz. Bir nechta bo'lsa
    # TAXMIN QILMAYMIZ — J1 saboqi: noto'g'ri kompaniyaga yozish eng
    # qimmat xato turi.
    #
    # DIQQAT — TARTIB MUHIM. Bu blok avval `load_dotenv()` DAN OLDIN
    # turardi, ya'ni `XT_DB_DSN` hali o'qilmagan bo'lardi. `init_pool()`
    # har safar yiqilar, `except` uni ogohlantirishga aylantirar va
    # `with_requirements` JIMGINA o'chirilardi:
    #
    #     [!] Talab ajratish O'TKAZIB YUBORILADI: XT_DB_DSN o'rnatilmagan
    #
    # Rejalashtiruvchida muhit o'zgaruvchisi yo'q, shuning uchun bu HAR
    # SOAT sodir bo'lardi va quvur baribir "muvaffaqiyatli" deb tugardi.
    if args.with_requirements and args.company is None:
        try:
            env_shart("sole_company_id()")
            from api import auth, db as _db
            _db.init_pool()
            args.company = auth.sole_company_id()
        except Exception as e:                              # noqa: BLE001
            # JIMGINA EMAS: talablar ajratilmasa quvur o'z vazifasini
            # bajarmagan — buni chiqish kodi ham ko'rsatsin.
            print(f"[XATO] Talab ajratish O'TKAZIB YUBORILADI: {e}")
            post_xatolar.append(f"talab ajratish: {e}")
            args.with_requirements = False

    # Oldingi uzilib qolgan yurishlarni yopamiz — aks holda ular 'running'
    # bo'lib qolib, /freshness ni ham, xato hisobini ham buzadi.
    try:
        stale = close_stale_runs(args.stale_hours)
        if stale:
            print(f"[i] {stale} ta uzilib qolgan yurish 'error' deb yopildi.")
    except Exception as e:  # noqa: BLE001 — tozalash asosiy ishni to'xtatmasin
        print(f"[!] Eski yurishlarni yopib bo'lmadi: {e}")

    if args.only_rag:
        # MANBA ETL O'TKAZIB YUBORILADI.
        #
        # Sabab: RAG quvuri (hujjat matni + bo'laklash + vektorlash)
        # soatlar oladi. Uni soatlik yurishga qo'shsak BILDIRISHNOMA
        # o'shancha kechikadi — foydalanuvchi yangi tenderni kech
        # ko'radi. Shuning uchun RAG alohida, kamroq tez-tez yuradigan
        # vazifa: manba ETL har soat, RAG kuniga bir necha marta.
        groups, results = [], []
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAQAT RAG quvuri "
              "(manba ETL, kategoriyalash va bildirishnoma o'tkazib yuborildi)")
        sys.stdout.flush()
    else:
        # --- LUG'AT: BO'SH BAZADA BIR MARTA -----------------------------------
        # `tender.area_leaf_id` -> `dim_area(area_id)` ga FOREIGN KEY
        # (`xt_xarid_schema.sql:76`). `dim_area` bo'sh bo'lsa HAR BIR
        # tender yozuvi shu cheklovni buzadi.
        #
        # O'LCHANDI (2026-09-04, bo'sh serverga birinchi o'rnatish):
        #
        #     ! #509465 DB xato: insert or update on table "tender"
        #       violates foreign key constraint "tender_area_leaf_id_fkey"
        #     Metrika: ko'rildi 655, yozildi 0, yiqildi 655
        #
        # `dim_area` ni FAQAT `etl_dims.py` to'ldiradi, u esa bu
        # ro'yxatda YO'Q edi — `LOYIHA.md` ning quvur diagrammasida
        # (117-qator) bor bo'lsa ham. Ya'ni yangi o'rnatma HECH QACHON
        # ma'lumot yoza olmasdi va buni hech narsa AYTMASDI.
        #
        # `etl_uzex.py` dagi `sync_region_names()` bu bo'shliqni
        # yopmaydi: u mavjud qatorlarning NOMINI yangilaydi, yangi
        # qator qo'shmaydi.
        #
        # NEGA HAR YURISHDA EMAS: hududlar reestri kamdan-kam
        # o'zgaradi (`docs/legal-data-map.md`: "kamdan-kam"), soatlik
        # yurishga qo'shish esa manbaga keraksiz yuk berardi. Shart —
        # "jadval BO'SH", ya'ni bu BOOTSTRAP, yangilash emas.
        # Reestrni ataylab yangilash uchun `etl_dims.py` qo'lda
        # yurgiziladi.
        try:
            with db() as _c, _c.cursor() as _cur:
                _cur.execute("SELECT count(*) FROM dim_area")
                _n_area = int(_cur.fetchone()[0])
        except Exception as e:                       # noqa: BLE001
            _n_area = -1
            print(f"[!] `dim_area` sanog'i olinmadi: {e}")

        if _n_area == 0:
            print("[i] `dim_area` BO'SH — lug'at yuklanadi (bir martalik). "
                  "Busiz har bir tender yozuvi FOREIGN KEY ni buzardi.")
            sys.stdout.flush()
            _ok, _err, _dt, out, _kod = run_script("etl_dims.py", [])
            emit(["\n===== pre: lug'at (dim_area bo'sh edi) =====", *out])
            if not _ok:
                # TO'XTATMAYDI, lekin JIMGINA ham o'tmaydi: manba
                # ishlamayotgan bo'lishi mumkin va o'shanda tender
                # yozuvlari baribir yiqiladi — sabab endi KO'RINADI.
                print(f"[XATO] Lug'at yuklanmadi: {_err}")
                post_xatolar.append(f"etl_dims: {_err}")

        groups = build_groups(args)
        mode = "ketma-ket" if args.sequential else "parallel"
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ETL orkestratori boshlandi "
              f"({len(groups)} platforma, {mode})")
        sys.stdout.flush()

        if args.sequential:
            results = [run_group(p, steps) for p, steps in groups]
        else:
            with ThreadPoolExecutor(max_workers=len(groups)) as pool:
                results = list(pool.map(lambda g: run_group(g[0], g[1]), groups))

        # Muddati o'tganlarni supurish — kategoriyalashdan OLDIN, chunki
        # etl_categorize.py va bildirishnoma faqat ochiq tenderlar bilan
        # ishlaydi. `--only-rag` da o'tkazib yuboriladi: manba yangilanmagan
        # bo'lsa "manbada yo'q" degan xulosa chiqarib bo'lmaydi.
        done = [p for (p, _steps), ok in zip(groups, results) if ok]
        try:
            n_exp = expire_stale_tenders(done)
            skipped = [p for (p, _s), ok in zip(groups, results) if not ok]
            note = (f" ({', '.join(skipped)} o'tkazib yuborildi — yurish xato)"
                    if skipped else "")
            emit(["\n===== post: muddati o'tganlar =====",
                  f"  {n_exp} ta tender 'expired' ga o'tkazildi{note}"])
        except Exception as e:  # noqa: BLE001 — supurish ishni to'xtatmasin
            emit([f"\n[!] Muddati o'tganlarni belgilab bo'lmadi: {e}"])

    # Kategoriyalash — barcha manbalar tugagach (yangi tenderlarni belgilaydi).
    # Tender qo'shmaydi, shuning uchun etl_run'ga loglanmaydi.
    if not args.skip_categorize:
        _ok, _err, _dt, out, _kod = run_script("etl_categorize.py", [])
        emit(["\n===== post: kategoriyalash =====", *out])
        if not _ok:
            post_xatolar.append(f"etl_categorize: {_err}")

    # Hujjat matnini ajratish (TZ P0-2) — faqat --with-docs bilan, chunki har
    # faylni manbadan yuklab olish kerak. Hujjatlarning O'ZI etl_details.py da
    # yig'iladi, bu qadam ularning MATNINI chiqaradi.
    #
    # QAMROV — standart BARCHA OCHIQ tenderlar (reja_ai_chat.md §16.33).
    #
    # OLDIN `--catalog` edi. U 2026-08 da amalda TUGADI: katalogga mos +
    # ochiq doirada atigi 3 ta PDF qolgan edi, ya'ni filtr yangi hujjat
    # bermay qo'ygan. Ochiq doiraga o'tilgach qamrov 121 -> 512 tenderga
    # chiqdi (547 ochiqning 94% i).
    #
    # Yopilganlarga kengaytirilmaydi — ularga taklif berib bo'lmaydi.
    # Qamrovni oldindan ko'rish (tarmoqqa chiqmaydi):
    #     python etl_doc_text.py --count-only
    # --- TENDER VEKTORLARI — RAG quvurining BIRINCHI qadami ---
    #
    # O'LCHANGAN MUAMMO: avval u quvurning OXIRIDA turardi, ya'ni eng
    # sekin qadam (`etl_doc_text`, 30+ daqiqa) tugagunicha kutardi.
    # Soatlik yurish tugamay qolsa YANGI TENDER SEMANTIK QIDIRUVDA
    # UMUMAN KO'RINMASDI:
    #     tender_embedding 556  <->  ochiq tender 782
    # ya'ni 226 ta tender `search_tenders` uchun mavjud emas edi.
    #
    # Holbuki bu qadam hujjat matniga UMUMAN BOG'LIQ EMAS (tender nomi
    # + pozitsiyalardan quriladi) va 0.5 daqiqa oladi. Eng arzon va
    # eng ta'sirli qadam BIRINCHI turishi kerak.
    if args.with_rag:
        _ok, _err, _dt, out, _kod = run_script("etl_embed.py", ["--tenders"])
        emit(["\n===== post: tender vektorlari =====", *out])
        if not _ok:
            post_xatolar.append(f"etl_embed --tenders: {_err}")

        # --- TASNIFLAGICH LUG'ATI VA MARKAZ ---
        #
        # NEGA SHU YERDA VA SHU TARTIBDA: ikkalasi ham ESKIRADI va
        # eskirganini HECH NARSA ko'rsatmaydi — semantik qidiruv
        # sekin-asta yomonlashadi, xato chiqmaydi. Bu aynan "jimgina
        # buzilish" sinfi.
        #
        # Tartib majburiy:
        #   1) lug'at   — yangi tenderlar yangi kod olib keladi
        #   2) markaz   — korpus o'sgach o'rtacha suriladi
        #   3) kod vek. — yangi kodlar vektorsiz qolmasin
        #   4) hublik   — markaz o'zgargach `embedding_c` o'zgaradi,
        #                 ya'ni hub_bias ham qayta hisoblanishi kerak
        #
        # 1, 2 va 4 — SOF SQL, model chaqirilmaydi (soniyalar).
        _kod_xato = _lugat_va_markaz()
        if _kod_xato:
            post_xatolar.extend(_kod_xato)
        else:
            _ok, _err, _dt, out, _kod = run_script("etl_embed.py", ["--codes"])
            emit(["\n===== post: tasniflagich vektorlari =====", *out])
            if not _ok:
                post_xatolar.append(f"etl_embed --codes: {_err}")
            else:
                _h = _hub_yangila()
                if _h:
                    post_xatolar.extend(_h)

    # `etl_doc_text` BO'LAKLASHDAN OLDIN turishi SHART — bo'lak matndan
    # quriladi.
    if args.with_docs:
        doc_args = limit_args_for(args)
        if args.docs_all:
            doc_args += ["--no-only-open"]     # yopilganlar ham
        elif args.docs_catalog:
            doc_args += ["--catalog"]          # eski tor qamrov
        # aks holda: `--only-open` standart, katalog filtri YO'Q
        _ok, _err, _dt, out, _kod = run_script("etl_doc_text.py", doc_args)
        emit(["\n===== post: hujjat matni =====", *out])
        if not _ok:
            post_xatolar.append(f"etl_doc_text: {_err}")

    # --- RAG QUVURI ---------------------------------------------------
    #
    # NEGA BU YERDA: bu qadamlarsiz chat YANGI tenderni umuman ko'rmaydi.
    # Hujjat matni chiqarilsa ham, bo'lakka bo'linmasa qidiruvga tushmaydi;
    # bo'linsa ham vektorlanmasa semantik yo'l ishlamaydi. 2026-08-25 gacha
    # uchala qadam ham FAQAT QO'LDA yurgizilardi — ya'ni korpus o'z-o'zidan
    # eskirar edi.
    #
    # VEKTORLASH CHEKLANGAN: o'lchangan tezlik ~3 bo'lak/s, 80k bo'lak esa
    # soatlar oladi. Soatlik yurishni bloklab qo'ymaslik uchun har safar
    # `--vector-budget` tacha bo'lak vektorlanadi. Tanlash sharti
    # `embedding IS NULL` bo'lgani uchun qolgani KEYINGI yurishda davom
    # etadi — ya'ni korpus asta-sekin quvib yetadi.
    if args.with_rag:
        _ok, _err, _dt, out, _kod = run_script("etl_embed.py", ["--chunks"])
        emit(["\n===== post: bo'laklash =====", *out])
        if not _ok:
            post_xatolar.append(f"etl_embed --chunks: {_err}")

        # TALAB AJRATISH — bo'laklashdan KEYIN, vektorlashdan OLDIN.
        #
        # Bo'laklashdan keyin: naqsh ajratgichi `doc_chunk` dan o'qiydi.
        # Vektorlashdan oldin: u BEPUL va TEZ (376 tender ~100 s), ya'ni
        # uzoq vektorlash orqasida turib qolmasligi kerak — §16.49 dagi
        # `--tenders` bilan bir xil saboq.
        #
        # `reyestr` va `naqsh` — IKKALASI HAM BEPUL. LLM ajratish
        # (`requirement_ai`) ATAYLAB quvurda YO'Q: u pul sarflaydi va
        # nazoratsiz yurgizilmasligi kerak.
        if args.with_requirements:
            # IKKI USUL, IKKALASI HAM BEPUL. Ilgari FAQAT `naqsh`
            # yurardi va bu O'LCHANGAN qarz to'plagan edi (Q-1):
            #
            #     reyestr urinilmagan tender   3078
            #       shundan OCHIQ               627
            #
            # `reyestr` HUJJATSIZ ishlaydi (tender pozitsiyalarini
            # o'qiydi), `naqsh` esa hujjat MATNINI talab qiladi va
            # 249 tenderda `no_text` bergan. Ya'ni quvur aynan
            # ISHONCHLI va TEKIN yo'lni yurgizmasdi.
            #
            # O'lchov: 627 ta tender, 1 199 talab, 4 SEKUND, 0 xato.
            #
            # TARTIB: `reyestr` BIRINCHI — u manbaning rasmiy
            # pozitsiyalari, `naqsh` esa hujjatdan TAXMIN qiladi.
            for _usul in ("reyestr", "naqsh"):
                _talab_p = {"company_id": args.company, "method": _usul}
                _talab_oldin = _sanoq(SQL_TALAB_QOLGAN, _talab_p)
                _ok, _err, _dt, out, _kod = run_script(
                    "etl_requirement.py",
                    ["--company", str(args.company), "--method", _usul,
                     "--quiet"])
                emit([f"\n===== post: talablar ({_usul}) =====", *out])
                if not _ok:
                    post_xatolar.append(f"etl_requirement[{_usul}]: {_err}")
                else:
                    siljish_tekshir(f"talab ajratish ({_usul})", _talab_oldin,
                                    _sanoq(SQL_TALAB_QOLGAN, _talab_p),
                                    post_xatolar)

            # --- BROKER NAVBATI ---
            #
            # Talab ajratishdan KEYIN: malaka tekshiruvi
            # `tender_requirement` ni o'qiydi, ya'ni undan oldin
            # yurgizilsa yangi tenderlar "talabsiz" ko'rinardi.
            #
            # BEPUL va TEZ (o'lchandi: 500 tender 1.3 s), shuning
            # uchun vektorlash orqasida turmaydi — §16.49 dagi
            # `--tenders` bilan bir xil saboq.
            #
            # Bu yerda BOLA-JARAYON YO'Q: modul shu jarayonda
            # chaqiriladi, chunki u faqat SQL bajaradi va alohida
            # skript ochish uni sekinlashtirardi.
            try:
                from api import db as _rdb, routing as _routing
                _rdb.init_pool()
                _nav_oldin = _sanoq(SQL_NAVBAT_HAJMI,
                                    {"company_id": args.company})
                _r = _routing.yonaltir_hammasi(args.company, limit=2000)
                _nav_keyin = _sanoq(SQL_NAVBAT_HAJMI,
                                    {"company_id": args.company})
                emit(["\n===== post: broker navbati =====",
                      f"    baholandi {_r['baholandi']}, "
                      f"navbatda {_r['navbat_hajmi']} "
                      f"(yangilandi {_r['yangilandi']})",
                      f"    qarorlar: {_r['qarorlar']}"])
                # MUSBAT TASDIQ. Bu qadam navbatni qisqartirmaydi,
                # shuning uchun "kamaydimi" emas, "BAHOLANDIMI" deb
                # so'raymiz: baholanadigan tender bor edi-yu nol
                # baholangan bo'lsa — nosozlik.
                if _r["baholandi"] == 0 and (_nav_oldin or 0) == 0:
                    print("  [i] broker navbati: baholanadigan tender yo'q")
                elif _r["baholandi"] == 0:
                    post_xatolar.append(
                        "broker navbati: BITTA HAM tender baholanmadi")
                else:
                    print(f"  [OK] broker navbati: {_r['baholandi']} "
                          f"baholandi, navbat {_nav_oldin} -> {_nav_keyin}")
                # JIMGINA KESISH BO'LMASIN: qamrov to'liq emasligi
                # muvaffaqiyat kabi ko'rinmasin.
                if _r.get("kesildi"):
                    post_xatolar.append(
                        f"broker navbati: {_r['kesildi']} ta tender "
                        f"CHEKLOVDAN TASHQARIDA qoldi "
                        f"({_r['jami_nomzod']} nomzod)")
            except Exception as e:                          # noqa: BLE001
                # JIMGINA EMAS: sxema qo'llanmagan bo'lsa ham bilinsin.
                print(f"[XATO] Broker navbati: {e}")
                post_xatolar.append(f"broker navbati: {str(e)[:200]}")

        if args.vector_budget > 0:
            # ARZON ISH BIRINCHI — XESHDAN OMMAVIY NUSXALASH.
            #
            # O'LCHANGAN (2026-09-01, Q-2). Navbatda 81 081 bo'lak
            # bor edi, shundan 42 325 tasi (52%) ALLAQACHON
            # vektorlangan matnning NUSXASI. Ular partiya-partiya,
            # modelning 2.3 bo'lak/s tezligiga BOG'LANIB o'tardi —
            # garchi ularga model UMUMAN kerak bo'lmasa ham.
            #
            #     partiya yo'li  2 000 bo'lak / 5.4 daqiqa
            #     ommaviy SQL   42 052 bo'lak / 3.4 daqiqa
            #
            # Ya'ni o'sha ishning o'zi ~33 marta tez. Endi u
            # model navbatidan OLDIN va BIR YO'LA bajariladi;
            # modelga faqat HAQIQATAN yangi matn qoladi.
            _ok, _err, _dt, out, _kod = run_script(
                "etl_embed.py", ["--xeshdan"])
            emit([chr(10) + "===== post: xeshdan nusxalash =====", *out])
            if not _ok:
                # NUSXALASH IXTIYORIY TEZLASHTIRISH: yiqilsa model
                # yo'li baribir ishlaydi. Lekin JIM qolmaydi.
                post_xatolar.append(f"etl_embed --xeshdan: {_err}")

            _vek_oldin = _sanoq(SQL_VEKTOR_QOLGAN)

            # BO'LAK-BO'LAK va HAR BO'LAKDAN KEYIN YOZILADI.
            #
            # `run_script()` bola chiqishini YIG'ADI va faqat u
            # tugagach yozadi. RAG vazifasi har yurishda majburan
            # to'xtatilyapti, vektorlash esa oxirgi va eng uzun
            # qadam — kill aynan o'sha paytda tushadi. Natijada
            # jurnalda `post: bo'lak vektorlari` NOL MARTA uchragan,
            # garchi bo'laklar commit bo'layotgan bo'lsa ham.
            emit(["\n===== post: bo'lak vektorlari ====="])
            _ok, _err = True, None
            _qolgan, _oldingi, _bolak_n = args.vector_budget, _vek_oldin, 0
            while _qolgan > 0:
                _n = min(VEKTOR_BOLAK, _qolgan)
                _ok, _err, _dt, out, _kod = run_script(
                    "etl_embed.py", ["--vectors", "--limit", str(_n)])
                _bolak_n += 1
                _hozir = _sanoq(SQL_VEKTOR_QOLGAN)
                emit([*out, f"  [{_bolak_n}] qolgan: {_hozir}"])
                if not _ok:
                    break
                # ILGARILAMADI -> qiladigan ish qolmadi. Byudjetni
                # bekorga sarflamaymiz va `siljish_tekshir()` ni
                # soxta "kamaymadi" xatosiga tushirmaymiz.
                if _hozir is None or _oldingi is None or _hozir >= _oldingi:
                    break
                _oldingi = _hozir
                _qolgan -= _n

            if not _ok:
                post_xatolar.append(f"etl_embed --vectors: {_err}")
            else:
                _vek_keyin = _sanoq(SQL_VEKTOR_QOLGAN)
                siljish_tekshir("vektorlash", _vek_oldin, _vek_keyin,
                                post_xatolar)
                # KORPUS O'SIB TURADI — "tugadi" holati YO'Q.
                # Har soat yangi hujjat keladi va yangi bo'lak
                # qo'shiladi, ya'ni to'g'ri xulosa "quvib yetdi",
                # "tamom" emas.
                if _vek_keyin is not None:
                    _q = ("QUVIB YETDI" if _vek_keyin == 0 else
                          f"{_vek_keyin:,} ta qoldi "
                          f"(~{_vek_keyin / max(args.vector_budget, 1):.0f} yurish)")
                    print(f"  [i] vektorlash holati: {_q}")

    # Bildirishnoma (TZ P0-10) — "soatlik kuzatish tsikli davomida keladi".
    # Skript YOQILGAN kanallarga yuboradi: email (SMTP) va/yoki Telegram.
    # Ikkalasi ham o'chirilgan bo'lsa hech narsa qilmaydi, xato bermaydi.
    if not args.skip_notify:
        _ok, _err, _dt, out, _kod = run_script("notify_new.py", [])
        emit(["\n===== post: bildirishnoma =====", *out])
        if not _ok:
            post_xatolar.append(f"notify_new: {_err}")

    # POST-QADAMLAR HAM SANALADI. Avval `results` faqat manba
    # guruhlarini qamrardi, post-qadamlarning `_ok` i esa tashlab
    # yuborilardi. Ya'ni vektorlash, bo'laklash yoki talab ajratish
    # yiqilsa ham yurish "hammasi muvaffaqiyatli" deb tugardi va
    # rejalashtiruvchi `LastTaskResult = 0` ko'rsatardi.
    ok = all(results) and not post_xatolar
    if post_xatolar:
        print("\n[XATO] Post-qadamlar:")
        for x in post_xatolar:
            print(f"  - {x}")
    summary = ("hammasi muvaffaqiyatli" if ok else
               "xato bor (etl_run va yuqoridagi ro'yxatni ko'ring)")
    print(f"\n[{time.strftime('%H:%M:%S')}] Tugadi. {summary}")
    _yuv()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
