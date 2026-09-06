#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SINOV: HAQIQIY FAYL YUKLASH — kompaniya hujjatlari va AI chat
=============================================================

O'LCHANGAN MUAMMO (2026-09-06). `company_document.file_ref` MATN
maydoni edi va u "tashqi havola yoki yo'l" deb hujjatlashtirilgan.
Amalda 13 qatorning 13 tasida ham shunday turardi:

    file:///D:/MVP%20projects/tender-ai/.runtime/company_documents/2/...

ya'ni BITTA ISHLAB CHIQUVCHI MASHINASINING mutlaq yo'li. Uch qavat
buzilgan edi:
  1. brauzer `http://` sahifadan `file://` ga o'tishni BLOKLAYDI —
     havola bosilardi va HECH NARSA bo'lmasdi, xato ham chiqmasdi;
  2. serverda bu yo'l umuman mavjud emas;
  3. fizik fayl ASL NOM bilan yotardi, ya'ni foydalanuvchi bergan
     matn fayl tizimi yo'liga aylanardi.

BU SINOV NIMANI QO'RIQLAYDI

  A. KOMPANIYA HUJJATI (§30)
     haqiqiy PDF/DOCX yuklanadi, hajm/tur/soxta kengaytma rad
     etiladi, yo'l chiqib ketmaydi, ijarachi ajratiladi, yuklab
     olingan BAYT yuklanganiga TENG, almashtirish tarixni
     buzmaydi, muvofiqlik ishlayveradi.

  B. AI CHAT BIRIKTIRMASI (§31)
     fayl sessiyaga bog'lanadi, parser yuradi, holat mashinasi
     haqiqatni aytadi, bo'lak yaratiladi, FAYL-ONLY qidiruv
     ommaviy korpusni QO'SHMAYDI, iqtibos yuklangan faylga
     ishora qiladi, pullik AI qulfi joyida qoladi.

Ishga tushirish:
    .venv\\Scripts\\python.exe _tests\\yuklama_test.py
    .venv\\Scripts\\python.exe _tests\\yuklama_test.py --bazasiz
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import time
import uuid
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import konsol  # noqa: E402
import rejim  # noqa: E402

konsol.sozla()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

_natija = []

#: Sinov hisoblari — `zz` prefiksi bilan, ishlab chiqarish nomlariga
#: o'xshamaydigan qilib. BELGI QONUNIY QIYMAT BO'LMASIN qoidasi:
#: `Karimov` kabi haqiqiy bo'lishi mumkin nom ISHLATILMAYDI.
U_A, U_B = "zzyuklama_a", "zzyuklama_b"
PAROL = "zzYuklama12345!x"


def check(nom, ok, tafsilot=""):
    _natija.append((nom, ok, tafsilot))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nom}"
          + (f" -- {tafsilot}" if tafsilot else ""))
    return ok


def bolim(t):
    print(f"\n--- {t} ---")


# =====================================================================
# Sinov fayllari — HAQIQIY formatlar, xom bayt
# =====================================================================
def pdf_yasa(matn: str) -> bytes:
    """Eng kichik HAQIQIY PDF.

    `%PDF` imzosi bilan va `pypdf` o'qiy oladigan tuzilishda —
    "PDF ga o'xshash bayt" emas. Aks holda sinov parser YO'LINI
    emas, xato yo'lini o'lchardi.
    """
    oqim = f"BT /F1 12 Tf 40 700 Td ({matn}) Tj ET".encode("latin-1", "replace")
    obj = []
    obj.append(b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n")
    obj.append(b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n")
    obj.append(b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
               b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n")
    obj.append(b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n")
    obj.append(b"5 0 obj<</Length " + str(len(oqim)).encode()
               + b">>stream\n" + oqim + b"\nendstream endobj\n")
    out = bytearray(b"%PDF-1.4\n")
    ofset = []
    for o in obj:
        ofset.append(len(out))
        out += o
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(obj) + 1)
    for x in ofset:
        out += b"%010d 00000 n \n" % x
    out += (b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
            % (len(obj) + 1, xref))
    return bytes(out)


def docx_yasa(matn: str) -> bytes:
    """Eng kichik HAQIQIY DOCX (ZIP + `word/document.xml`)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxml'
                   'formats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.'
                   'wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats'
                   '.org/officeDocument/2006/relationships/officeDocument" '
                   'Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.'
                   'openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   f'<w:p><w:r><w:t>{matn}</w:t></w:r></w:p>'
                   '</w:body></w:document>')
    return buf.getvalue()


#: Matni ANIQ BILINADIGAN sinov hujjati — javobni tekshirish uchun.
#: Raqamlar ATAYLAB g'ayrioddiy (`18 oy`, `45 kun`, `30 foiz`): ular
#: ommaviy korpusda uchramasligi kerak, aks holda "fayldan topildi"
#: bilan "korpusdan topildi" ni ajratib bo'lmasdi.
SINOV_MATN = ("TEXNIK TOPSHIRIQ ZZTEST\n"
              "Kafolat muddati: 18 oy.\n"
              "Yetkazib berish: 45 kun.\n"
              "Oldindan tolov: 30 foiz.\n"
              "Sertifikat: ISO 9001 talab qilinadi.\n") * 4


def kodsiz(src: str) -> str:
    """IZOH va DOCSTRING ni olib tashlaydi. SQL doimiylari QOLADI.

    NEGA KERAK — SHU SINOVNING O'ZIDA SODIR BO'LDI (2026-09-06):
    "yo'l tekshiruvi `commonpath` bilan (startswith EMAS)" sharti
    yiqildi, chunki `startswith` so'zi `_yol()` ning DOCSTRINGIDA
    turardi -- u yerda aynan NEGA ishlatilmagani tushuntirilgan.
    Xuddi shunday "`doc_chunk` ga tegmaydi" sharti ham izohdagi
    havolaga urildi. Kod TO'G'RI edi, skaner NASRni o'qidi.

    `_kodsiz` (`doc_qamrov_test`) faqat `#` ni oladi. Bu yerda
    DOCSTRING ham kerak, LEKIN atalgan doimiylar (`_SQL_LEKSIK =
    \"\"\"...\"\"\"`) QOLISHI shart -- ular KOD va aynan ular
    tekshirilyapti. Shuning uchun `ast` bilan FAQAT haqiqiy
    docstring (funksiya/klass/modul boshidagi ifoda) o'chiriladi.
    """
    import ast as _ast
    qatorlar = src.splitlines()
    ochir = set()
    try:
        daraxt = _ast.parse(src)
    except SyntaxError:
        daraxt = None
    if daraxt is not None:
        for tugun in _ast.walk(daraxt):
            tana = getattr(tugun, "body", None)
            if not isinstance(tugun, (_ast.Module, _ast.FunctionDef,
                                      _ast.AsyncFunctionDef, _ast.ClassDef)):
                continue
            if not tana:
                continue
            b = tana[0]
            if (isinstance(b, _ast.Expr) and isinstance(b.value, _ast.Constant)
                    and isinstance(b.value.value, str)):
                for n in range(b.lineno, (b.end_lineno or b.lineno) + 1):
                    ochir.add(n)
    toza = []
    for i, ln in enumerate(qatorlar, 1):
        if i in ochir:
            continue
        if ln.lstrip().startswith("#"):
            continue
        if "  # " in ln and ln.count("'") % 2 == 0 and ln.count('"') % 2 == 0:
            ln = ln.split("  # ")[0]
        toza.append(ln)
    return chr(10).join(toza)


# =====================================================================
# 1. MANBA — kod darajasidagi qoidalar (bazasiz)
# =====================================================================
def test_manba():
    bolim("1. Manba — qoidalar kodda")
    from api import saqlash, yuklama

    # --- nom tozalash: YO'L QISMI YO'QOLADI ---
    for xom, kutilgan in [
        ("../../etc/passwd", "passwd"),
        (r"C:\Windows\system32\a.pdf", "a.pdf"),
        ("/etc/shadow", "shadow"),
        ("..", "fayl"),
        (".", "fayl"),
        ("", "fayl"),
    ]:
        check(f"nom tozalanadi: {xom!r}",
              saqlash.tozala_nom(xom) == kutilgan,
              saqlash.tozala_nom(xom))
    # `"` VA `\` — `Content-Disposition` sarlavhasini ochadi.
    check("qo'shtirnoq nomdan olib tashlanadi",
          '"' not in saqlash.tozala_nom('a"b.pdf'))

    # --- kengaytma: NUQTASIZ NOMDA YO'Q ---
    check("nuqtasiz nomda kengaytma YO'Q",
          saqlash.ext_ol("passwd") == "", saqlash.ext_ol("passwd"))
    check("ikki nuqtali nomda OXIRGISI",
          saqlash.ext_ol("a.b.docx") == "docx")
    check("kengaytma kichik harfga tushadi",
          saqlash.ext_ol("A.PDF") == "pdf")

    # --- kalit: ASL NOM KIRMAYDI ---
    d = saqlash.MahalliyDisk()
    k = d.kalit_yasa(7, "pdf")
    check("kalit `<company_id>/<uuid>` shaklida",
          k.startswith("7/") and len(k.split("/")[1].split(".")[0]) == 32, k)
    check("kalitga asl nom KIRMAYDI",
          "hujjat" not in d.kalit_yasa(7, saqlash.ext_ol("hujjat.pdf")))
    check("yaroqsiz kengaytma kalitga TUSHMAYDI",
          "." not in d.kalit_yasa(7, "../x"), d.kalit_yasa(7, "../x"))

    # --- YO'L CHIQIB KETISHI ---
    from api import xatolar
    for yomon in ["../../../etc/passwd", "2/../../x", "/etc/passwd",
                  "", "2/\x00a"]:
        try:
            d._yol(yomon)
            check(f"yo'l bloklanadi: {yomon!r}", False, "RUXSAT BERILDI")
        except xatolar.Xato:
            check(f"yo'l bloklanadi: {yomon!r}", True)
    # ILDIZ PREFIKSI YETARLI EMAS: `/data/uploads-eski` `/data/uploads`
    # bilan boshlanadi. `commonpath` ishlatilgani shu sabab.
    src = io.open(os.path.join(ROOT, "api", "saqlash.py"),
                  encoding="utf-8").read()
    kod = kodsiz(src)
    check("yo'l tekshiruvi `commonpath` bilan (startswith EMAS)",
          "commonpath" in kod
          and "startswith" not in kod.split("def _yol")[1][:900],
          "izoh emas, KOD tekshiriladi")

    # --- RUXSAT ETILGAN FORMATLAR ---
    check("bajariladigan kengaytmalar ro'yxatda YO'Q",
          not ({"exe", "bat", "cmd", "sh", "js", "html", "svg"}
               & yuklama.RUXSAT_EXT), str(sorted(yuklama.RUXSAT_EXT)))
    check("`inline` faqat pdf/txt",
          set(yuklama.INLINE_MIME) == {"pdf", "txt"},
          str(sorted(yuklama.INLINE_MIME)))

    # --- CHEGARA IMPORTNIKIDAN ALOHIDA ---
    from api import main as M
    check("`MAX_UPLOAD_MB` import chegarasidan ALOHIDA",
          saqlash.MAX_UPLOAD_MB != M.MAX_IMPORT_MB,
          f"upload={saqlash.MAX_UPLOAD_MB} import={M.MAX_IMPORT_MB}")

    # --- CHEGARA O'QISHDAN OLDIN ---
    #
    # Bu yerda `_yuklangani` KODI tekshiriladi, chunki xatoning o'zi
    # aynan shunday edi: chegara bor edi, lekin butun fayl xotiraga
    # o'qilgandan KEYIN ishlardi.
    msrc = io.open(os.path.join(ROOT, "api", "main.py"),
                   encoding="utf-8").read()
    tana = msrc.split("def _yuklangani")[1][:1400]
    check("chegara BO'LAKLAB o'qishda tekshiriladi",
          "while True" in tana and "read(1024" in tana
          and tana.index("FILE_TOO_LARGE") > tana.index("while True"))
    check("yuklash endpointlari `_yuklangani` ni ishlatadi",
          msrc.count("_yuklangani(file, max_mb=saqlash.MAX_UPLOAD_MB)") >= 2)

    # --- PARSER TAKRORLANMAGAN ---
    ysrc = io.open(os.path.join(ROOT, "api", "yuklama.py"),
                   encoding="utf-8").read()
    check("parser QAYTA YOZILMAGAN (etl_doc_text qayta ishlatiladi)",
          "from etl_doc_text import" in ysrc
          and "def extract_pdf" not in ysrc and "PdfReader" not in ysrc)
    check("chunklash QAYTA YOZILMAGAN (etl_embed qayta ishlatiladi)",
          "from etl_embed import chunk_text" in ysrc
          and "def chunk_text" not in ysrc)

    # --- PULLIK AI QULFI ---
    check("vektorlash mahalliy, pullik yo'l `paid_guard` ortida",
          "paid_guard" in io.open(os.path.join(ROOT, "api", "ai_chat.py"),
                                  encoding="utf-8").read())
    check("`qabul_qil` pullik AI ni CHAQIRMAYDI",
          "anthropic" not in ysrc.lower() and "claude" not in ysrc.lower())


def test_holat_mashinasi():
    bolim("2. Holat mashinasi — `tayyor` YOLG'ON bo'lmasin")
    sql = io.open(os.path.join(ROOT, "schema_patch_yuklama.sql"),
                  encoding="utf-8").read()
    check("`tayyor` matnsiz QO'YILMAYDI (CHECK)",
          "yuklama_tayyor_matn_chk" in sql and "matn_belgi > 0" in sql)
    check("xato holatda SABAB majburiy (CHECK)",
          "yuklama_xato_sabab_chk" in sql)
    check("`too_large` holati YO'Q (u hech qachon saqlanmaydi)",
          "'too_large'" not in sql)
    check("hard delete emas — `arxiv_at` bor", "arxiv_at" in sql)
    check("almashtirish zanjiri bor", "almashtirdi" in sql)
    check("ijarachi mosligi TRIGGER bilan",
          "chat_yuklama_ijarachi_tekshir" in sql
          and "BEFORE INSERT OR UPDATE ON chat_yuklama" in sql)
    check("`yuklama_chunk` da `company_id` BEVOSITA bor",
          "yuklama_chunk" in sql
          and sql.split("CREATE TABLE IF NOT EXISTS yuklama_chunk")[1][:900]
              .count("company_id") >= 1)
    # KORPUSLAR ARALASHMAYDI.
    ysrc = io.open(os.path.join(ROOT, "api", "yuklama.py"),
                   encoding="utf-8").read()
    check("qidiruvda `company_id` HAR IKKALA so'rovda WHERE da",
          ysrc.count("c.company_id = %(company_id)s") == 2)
    ykod = kodsiz(ysrc)
    check("yuklama qidiruvi `doc_chunk` ga TEGMAYDI",
          "doc_chunk" not in ykod.split("_SQL_LEKSIK")[1],
          "izoh emas, KOD tekshiriladi")


def test_migratsiya():
    bolim("3. Migratsiya — id BARQAROR")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m", os.path.join(ROOT, "migratsiya.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    y = m.manifest_oqi()
    nomlar = {z.fayl: z.mid for z in y}
    check("`schema_patch_yuklama.sql` manifestda",
          "schema_patch_yuklama.sql" in nomlar)
    # QO'LDA QO'SHILGAN ID REGENERATSIYADA O'ZGARMAYDI.
    q = {z.fayl: z.mid for z in m.manifest_yasa()}
    o = {f: (nomlar[f], q[f]) for f in nomlar if f in q and nomlar[f] != q[f]}
    check("regeneratsiya mavjud id larni o'zgartirmaydi", not o, str(o)[:120])
    check("tartib QAT'IY o'suvchi",
          all(b.tartib > a.tartib for a, b in zip(y, y[1:])))


# =====================================================================
# BAZALI — HAQIQIY HTTP
# =====================================================================
def _hisoblar(db, A):
    """Sinov hisoblari — QAYTA ISHLATILADI, o'chirilmaydi.

    O'LCHANGAN TO'SIQ (2026-09-06): dastlab bu funksiya hisobni
    `DELETE` qilib qayta yaratardi. `company_account` o'chirilishi
    `audit_jurnal` ga kaskad qiladi, u yerda esa FAQAT-QO'SHISH
    triggeri bor va `DELETE` ni RAD ETADI:

        audit_jurnal FAQAT QO'SHILADI: DELETE taqiqlangan.

    Trigger TO'G'RI ishladi -- audit izini o'chirib bo'lmaydi va bu
    aynan shunday bo'lishi kerak. Sinov unga moslashadi: hisob bir
    marta yaratiladi va keyingi yurishlarda QAYTA ISHLATILADI.
    """
    out = []
    for u, nom in ((U_A, "ZZ Yuklama A"), (U_B, "ZZ Yuklama B")):
        bor = db.scalar("SELECT id FROM company_account WHERE username=%(u)s",
                        {"u": u})
        if bor:
            # Oldingi yurish uni NOFAOL qilgan — qayta yoqamiz.
            db.execute_returning("UPDATE company_account SET active = TRUE "
                                 " WHERE id=%(i)s RETURNING id", {"i": bor})
            out.append(int(bor))
        else:
            out.append(A.create_account(u, nom, PAROL)["id"])
    return out[0], out[1]


def _kut(c, H, yol, sekund=25):
    """Holat hal bo'lgunicha kutadi. `tayyor`/xato — ikkalasi ham hal."""
    oxirgi = None
    for _ in range(int(sekund / 0.4)):
        r = c.get(yol, headers=H)
        if r.status_code != 200:
            return None
        oxirgi = r.json()
        if isinstance(oxirgi, list):
            oxirgi = oxirgi[0] if oxirgi else None
        if oxirgi and oxirgi["holat"] not in ("yuklandi", "ajratilmoqda"):
            return oxirgi
        time.sleep(0.4)
    return oxirgi


def test_kompaniya_hujjati(db):
    bolim("4. Kompaniya hujjati — yuklash, yuklab olish, ijarachi")
    from fastapi.testclient import TestClient
    from api import auth as A
    from api.main import app

    cid_a, cid_b = _hisoblar(db, A)
    HA = {"Authorization": f"Bearer {A.login(U_A, PAROL)['token']}"}
    HB = {"Authorization": f"Bearer {A.login(U_B, PAROL)['token']}"}

    pdf = pdf_yasa("ZZTEST kafolat 18 oy")
    docx = docx_yasa(SINOV_MATN)

    with TestClient(app) as c:
        c.cookies.clear()
        d = c.post("/company/documents", headers=HA,
                   json={"doc_type": "guarantee_letter",
                         "name": "ZZ Kafolat"}).json()
        did = d["id"]

        # --- 1. HAQIQIY PDF ---
        r = c.post(f"/company/documents/{did}/fayl", headers=HA,
                   files={"file": ("zz.pdf", pdf, "application/pdf")})
        check("PDF yuklandi -> 200", r.status_code == 200,
              r.text[:160] if r.status_code != 200 else "")
        if r.status_code == 200:
            f = r.json()["fayl"]
            check("javobda YO'L YO'Q",
                  "kalit" not in f and not any(
                      isinstance(v, str) and ("/" in v and ":" in v)
                      for v in f.values()), str(f)[:120])
            h = _kut(c, HA, f"/company/documents/{did}/fayl")
            check("PDF holati `tayyor`", (h or {}).get("holat") == "tayyor",
                  str(h)[:160])
            check("matn HAQIQATAN ajratildi",
                  (h or {}).get("matn_belgi", 0) > 0, str((h or {}).get("matn_belgi")))

            # --- 2. YUKLAB OLINGAN BAYT = YUKLANGAN BAYT ---
            dl = c.get(f"/company/documents/{did}/download", headers=HA)
            check("yuklab olish -> 200", dl.status_code == 200)
            check("BAYT AYNAN teng", dl.content == pdf,
                  f"{len(dl.content)} vs {len(pdf)}")
            check("sha256 mos",
                  hashlib.sha256(dl.content).hexdigest()
                  == hashlib.sha256(pdf).hexdigest())
            cd = dl.headers.get("content-disposition", "")
            check("`attachment` sifatida beriladi", cd.startswith("attachment"), cd[:70])
            check("nom RFC 5987 bilan ham beriladi", "filename*=UTF-8''" in cd)
            check("`nosniff` sarlavhasi bor",
                  dl.headers.get("x-content-type-options") == "nosniff")
            check("kesh O'CHIQ (proksi boshqa ijarachiga bermasin)",
                  "no-store" in (dl.headers.get("cache-control") or ""))
            # PDF `inline` KO'RSATILADI, boshqasi YO'Q.
            vw = c.get(f"/company/documents/{did}/view", headers=HA)
            check("PDF `view` -> inline",
                  (vw.headers.get("content-disposition") or "").startswith("inline"),
                  (vw.headers.get("content-disposition") or "")[:40])

            # --- 2b. DESKRIPTOR SIZMAYDI ---
            #
            # O'LCHANGAN NUQSON (2026-09-06): `StreamingResponse` ga
            # OCHIQ FAYL OBYEKTI berilardi. Starlette uni o'qiydi,
            # lekin `.close()` CHAQIRMAYDI -- har yuklab olish bitta
            # deskriptorni ochiq qoldirardi. Linuxda bu SEKIN sizish
            # (`ulimit -n` gacha), Windowsda esa fayl QULFLANADI.
            #
            # Nuqson sinov tozalashida `PermissionError` bilan
            # chiqdi, lekin u `except: pass` bilan YUTILGAN edi va
            # shart faqat "fayl qoldi" derdi -- sababini emas.
            #
            # TEKSHIRUV YO'LNI EMAS, NATIJANI o'lchaydi: bir necha
            # marta yuklab olingandan keyin fayl KO'CHIRILA olishi
            # kerak. Ochiq deskriptor buni Windowsda IMKONSIZ qiladi.
            # PORTATIV O'LCHOV — DESKRIPTOR SONI.
            #
            # Quyidagi "ko'chirib ko'rish" sinovi WINDOWSDA kuchli
            # (ochiq fayl ko'chirilmaydi), lekin LINUXDA ochiq
            # deskriptor bilan ham ko'chirish ISHLAYDI — ya'ni u
            # yerda shart JIMGINA o'tib ketardi. Joylashtirish esa
            # aynan Linuxda. Shuning uchun `/proc/self/fd` bo'lsa
            # deskriptor SONI ham o'lchanadi.
            def _fd_soni():
                try:
                    return len(os.listdir("/proc/self/fd"))
                except OSError:
                    return None

            oldin_fd = _fd_soni()
            for _ in range(5):
                c.get(f"/company/documents/{did}/download", headers=HA)
            keyin_fd = _fd_soni()
            if oldin_fd is not None and keyin_fd is not None:
                # 5 ta yuklab olish 5 ta deskriptor qoldirmasin.
                # Kichik tebranish (jurnal, ulanish) bo'lishi mumkin,
                # shuning uchun chegara 2.
                check("5 ta yuklab olish deskriptor QOLDIRMAYDI",
                      keyin_fd - oldin_fd <= 2,
                      f"{oldin_fd} -> {keyin_fd}")
            else:
                print("        [i] `/proc/self/fd` yo'q — deskriptor "
                      "SONI o'lchanmadi (quyidagi ko'chirish sinovi qoladi)")
            from api import saqlash as _sq
            _s = _sq.saqlagich()
            yuk = db.query_one("SELECT kalit FROM yuklama WHERE id=%(i)s",
                               {"i": h["id"]})
            try:
                yangi_kalit = _s.archive(yuk["kalit"])
                # Darhol JOYIGA qaytaramiz: keyingi shartlar shu
                # faylni yuklab oladi.
                import shutil as _sh
                _sh.move(_s._yol(yangi_kalit), _s._yol(yuk["kalit"]))
                check("yuklab olishdan keyin fayl QULFLANMAGAN "
                      "(deskriptor sizmaydi)", True)
            except Exception as e:                            # noqa: BLE001
                check("yuklab olishdan keyin fayl QULFLANMAGAN "
                      "(deskriptor sizmaydi)", False,
                      f"{type(e).__name__}: {str(e)[:60]}")

            # --- 3. IJARACHI ---
            check("BEGONA kompaniya yuklab ololmaydi",
                  c.get(f"/company/documents/{did}/download",
                        headers=HB).status_code == 404)
            check("BEGONA kompaniya holatni ham ko'rmaydi",
                  c.get(f"/company/documents/{did}/fayl",
                        headers=HB).status_code == 404)
            check("tokensiz -> 401",
                  c.get(f"/company/documents/{did}/download").status_code == 401)
            check("TAXMIN QILINGAN id -> 404",
                  c.get("/company/documents/999999999/download",
                        headers=HA).status_code == 404)

            # --- 4. ALMASHTIRISH TARIXNI BUZMAYDI ---
            eski_id = h["id"]
            r2 = c.post(f"/company/documents/{did}/fayl", headers=HA,
                        files={"file": ("zz2.docx", docx, "application/octet-stream")})
            check("almashtirish -> 200", r2.status_code == 200, r2.text[:140])
            if r2.status_code == 200:
                yangi_id = r2.json()["fayl"]["id"]
                check("yangi yuklama BOSHQA id oldi", yangi_id != eski_id)
                eski = db.query_one("SELECT arxiv_at, id FROM yuklama "
                                    "WHERE id=%(i)s", {"i": eski_id})
                check("ESKI yuklama O'CHIRILMADI", eski is not None)
                check("ESKI yuklama ARXIVLANDI",
                      eski and eski["arxiv_at"] is not None)
                zanjir = db.scalar("SELECT almashtirdi::text FROM yuklama "
                                   "WHERE id=%(i)s", {"i": yangi_id})
                check("almashtirish ZANJIRI yozildi", zanjir == eski_id)
                check("auditda almashtirish izi bor",
                      db.scalar("SELECT count(*) FROM audit_jurnal "
                                "WHERE amal='hujjat_fayl_almashtirildi'") > 0)

        # --- 5. RAD ETISH YO'LLARI ---
        check("qo'llab-quvvatlanmaydigan tur rad etiladi",
              c.post(f"/company/documents/{did}/fayl", headers=HA,
                     files={"file": ("zz.exe", b"MZ\x90\x00" + b"x" * 100,
                                     "application/octet-stream")}
                     ).status_code == 422)
        check("kengaytmasiz fayl rad etiladi",
              c.post(f"/company/documents/{did}/fayl", headers=HA,
                     files={"file": ("passwd", b"root:x:0:0", "text/plain")}
                     ).status_code == 422)
        # SOXTA KENGAYTMA: mazmun DOCX, nomi `.pdf`.
        r3 = c.post(f"/company/documents/{did}/fayl", headers=HA,
                    files={"file": ("soxta.pdf", docx, "application/pdf")})
        check("soxta kengaytma (docx -> .pdf) rad etiladi",
              r3.status_code == 422, str(r3.status_code))
        check("rad sababi KODLI",
              (r3.json().get("error") or {}).get("code") == "FILE_TYPE_MISMATCH",
              str(r3.json())[:120])
        check("bo'sh fayl rad etiladi",
              c.post(f"/company/documents/{did}/fayl", headers=HA,
                     files={"file": ("bosh.txt", b"", "text/plain")}
                     ).status_code == 422)
        # HAJM — chegaradan KATTA.
        from api import saqlash
        katta = b"a" * (saqlash.MAX_UPLOAD_MB * 1024 * 1024 + 2048)
        rk = c.post(f"/company/documents/{did}/fayl", headers=HA,
                    files={"file": ("katta.txt", katta, "text/plain")})
        check("chegaradan katta fayl -> 413", rk.status_code == 413,
              str(rk.status_code))
        check("hajm xatosi KODLI",
              (rk.json().get("error") or {}).get("code") == "FILE_TOO_LARGE")
        # YO'L QISMLI NOM — saqlansa ham yo'l yasalmaydi.
        r5 = c.post(f"/company/documents/{did}/fayl", headers=HA,
                    files={"file": ("../../evil.txt", SINOV_MATN.encode(),
                                    "text/plain")})
        check("yo'l qismli nom QABUL qilinadi, lekin tozalanadi",
              r5.status_code == 200 and "/" not in r5.json()["fayl"]["nom"],
              str(r5.json().get("fayl", {}).get("nom"))[:60] if r5.status_code == 200
              else str(r5.status_code))

        # --- 6. MUVOFIQLIK ISHLAYVERADI ---
        lst = c.get("/company/documents", headers=HA)
        check("hujjatlar ro'yxati ishlayveradi", lst.status_code == 200)
        check("ro'yxatda `yuklama_id` bor",
              any("yuklama_id" in x for x in lst.json()), "")
        from api import compliance
        try:
            compliance.check(db.scalar("SELECT id FROM tender LIMIT 1"),
                             company_id=cid_a)
            check("`compliance.check` yiqilmaydi", True)
        except Exception as e:                                # noqa: BLE001
            check("`compliance.check` yiqilmaydi", False, str(e)[:110])

    return cid_a, cid_b, HA, HB


def test_chat_biriktirma(db, cid_a, cid_b, HA, HB):
    bolim("5. AI chat biriktirmasi")
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as c:
        c.cookies.clear()
        s = c.post("/chat/sessions", headers=HA, json={"manba": "global"})
        check("bo'sh sessiya ochiladi -> 201", s.status_code == 201,
              s.text[:140])
        sid = s.json()["session_id"]

        r = c.post(f"/chat/sessions/{sid}/fayl", headers=HA,
                   files={"file": ("zz_topshiriq.txt",
                                   SINOV_MATN.encode("utf-8"), "text/plain")})
        check("chatga yuklash -> 201", r.status_code == 201, r.text[:160])
        yid = r.json()["id"]
        check("javob DARHOL `tayyor` EMAS",
              r.json()["holat"] in ("yuklandi", "ajratilmoqda"),
              r.json()["holat"])

        h = _kut(c, HA, f"/chat/sessions/{sid}/fayl")
        check("holat `tayyor` ga o'tdi", (h or {}).get("holat") == "tayyor",
              str(h)[:160])
        check("bo'lak YARATILDI", (h or {}).get("chunk_soni", 0) > 0,
              str((h or {}).get("chunk_soni")))
        check("bo'lakda `company_id` to'g'ri",
              db.scalar("SELECT count(*) FROM yuklama_chunk "
                        "WHERE yuklama_id=%(i)s AND company_id=%(c)s",
                        {"i": yid, "c": cid_a}) > 0)
        # VEKTOR — mahalliy embedder bo'lsa hisoblanadi. YO'Q BO'LSA
        # HAM FAYL ISHLAYDI (leksik qidiruv), shuning uchun bu shart
        # HOLATGA bog'lanmaydi.
        vek = db.scalar("SELECT count(*) FROM yuklama_chunk "
                        "WHERE yuklama_id=%(i)s AND embedding IS NOT NULL",
                        {"i": yid})
        check("vektor hisoblandi (mahalliy embedder)", vek > 0,
              f"{vek} ta — 0 bo'lsa embedder yo'q, leksik qidiruv ishlayveradi")

        # --- IJARACHI ---
        check("BEGONA kompaniya sessiyani ko'rmaydi",
              c.get(f"/chat/sessions/{sid}/fayl", headers=HB).status_code == 404)
        check("BEGONA kompaniya faylni yuklab ololmaydi",
              c.get(f"/chat/fayl/{yid}/download", headers=HB).status_code == 404)
        check("o'z faylini yuklab oladi",
              c.get(f"/chat/fayl/{yid}/download", headers=HA).status_code == 200)
        check("buzuq UUID -> 404 (500 EMAS)",
              c.get("/chat/fayl/emas-uuid/download", headers=HA).status_code == 404)

        # --- QIDIRUV VA IQTIBOS (pullik model CHAQIRILMAYDI) ---
        from api.ai_chat import (ChatContext, _t_search_uploaded_file,
                                 _t_search_company_documents)
        ctx = ChatContext(company_id=cid_a, session_id=sid)
        out = _t_search_uploaded_file({"query": "kafolat muddati"}, ctx)
        check("fayldan bo'lak TOPILDI", bool(out.get("natija")), str(out)[:160])
        check("javob matni HAQIQIY fayldan",
              any("ZZTEST" in (x.get("text") or "") for x in out.get("natija", [])))
        check("iqtibos yaratildi", len(ctx.citations) > 0)
        if ctx.citations:
            it = ctx.citations[0]
            check("iqtibos manba turi `chat_upload`",
                  it.get("manba_turi") == "chat_upload", str(it.get("manba_turi")))
            check("iqtibos YUKLANGAN faylga ishora qiladi",
                  it.get("yuklama_id") == yid)
            check("iqtibosda fayl nomi bor",
                  it.get("file_name") == "zz_topshiriq.txt", str(it.get("file_name")))
            check("TXT da SOXTA sahifa raqami YO'Q",
                  it.get("sahifa") is None, str(it.get("sahifa")))
            check("bo'lak raqami bor (sahifa o'rniga)",
                  it.get("chunk_no") is not None)

        # --- QAMROV ARALASHMAYDI ---
        ctx_b = ChatContext(company_id=cid_b, session_id=sid)
        out_b = _t_search_uploaded_file({"query": "kafolat muddati"}, ctx_b)
        check("BEGONA kontekst hech narsa ko'rmaydi",
              not out_b.get("natija"), str(out_b)[:120])

        ctx_k = ChatContext(company_id=cid_a, session_id=sid)
        out_k = _t_search_company_documents({"query": "ZZTEST kafolat"}, ctx_k)
        chat_fayli = [x for x in out_k.get("natija", [])
                      if x.get("fayl") == "zz_topshiriq.txt"]
        check("kompaniya hujjati qidiruvi CHAT faylini KO'RMAYDI",
              not chat_fayli, str(out_k)[:140])

        # --- OMMAVIY KORPUS SIZIB CHIQMAYDI ---
        # `search_uploaded_file` `doc_chunk` ga UMUMAN bormaydi;
        # natijadagi HAR bo'lak `yuklama_chunk` dan bo'lishi shart.
        idlar = [x["manba_raqami"] for x in out.get("natija", [])]
        check("fayl qidiruvi FAQAT yuklamadan qaytaradi",
              all(ct.get("yuklama_id") for ct in ctx.citations),
              str(len(idlar)))

        # --- QO'LLAB-QUVVATLANMAYDIGAN / O'QILMAYDIGAN ---
        # Matnsiz PDF — parser "skan/chizma, OCR kerak" deydi.
        bosh_pdf = pdf_yasa(" ")
        r2 = c.post(f"/chat/sessions/{sid}/fayl", headers=HA,
                    files={"file": ("bosh.pdf", bosh_pdf, "application/pdf")})
        if r2.status_code == 201:
            h2 = _kut(c, HA, f"/chat/sessions/{sid}/fayl")
            hh = db.query_one("SELECT holat, xato FROM yuklama WHERE id=%(i)s",
                              {"i": r2.json()["id"]})
            check("matnsiz PDF `tayyor` BO'LMAYDI",
                  hh["holat"] != "tayyor", str(dict(hh))[:140])
            check("sabab AYTILADI (OCR kerak)",
                  bool(hh["xato"]) and "OCR" in (hh["xato"] or ""),
                  str(hh["xato"])[:100])

        # --- KVOTA ---
        for i in range(6):
            c.post(f"/chat/sessions/{sid}/fayl", headers=HA,
                   files={"file": (f"zz{i}.txt", SINOV_MATN.encode(), "text/plain")})
        oxirgi = c.post(f"/chat/sessions/{sid}/fayl", headers=HA,
                        files={"file": ("ortiqcha.txt", SINOV_MATN.encode(),
                                        "text/plain")})
        check("fayl kvotasi ISHLAYDI -> 413", oxirgi.status_code == 413,
              str(oxirgi.status_code))

        # --- UZISH: O'CHIRMAYDI ---
        u = c.delete(f"/chat/sessions/{sid}/fayl/{yid}", headers=HA)
        check("biriktirmani uzish -> 204", u.status_code == 204, str(u.status_code))
        check("yuklama qatori O'CHIRILMADI",
              db.scalar("SELECT count(*) FROM yuklama WHERE id=%(i)s",
                        {"i": yid}) == 1)
        check("bo'laklar ham QOLDI (eski iqtibos ishlasin)",
              db.scalar("SELECT count(*) FROM yuklama_chunk "
                        "WHERE yuklama_id=%(i)s", {"i": yid}) > 0)
        keyin = c.get(f"/chat/sessions/{sid}/fayl", headers=HA).json()
        check("uzilgan fayl FAOL ro'yxatda YO'Q",
              all(x["id"] != yid for x in keyin))
        ctx2 = ChatContext(company_id=cid_a, session_id=sid)
        out2 = _t_search_uploaded_file({"query": "kafolat muddati",
                                        "file_ids": [yid]}, ctx2)
        check("uzilgan fayl QIDIRUVDA ishlatilmaydi",
              not out2.get("natija"), str(out2)[:120])

        check("auditda biriktirish izi bor",
              db.scalar("SELECT count(*) FROM audit_jurnal "
                        "WHERE amal='chat_fayl_biriktirildi'") > 0)


def test_tozala(db):
    """Sinov FAYLLARINI arxivlaydi va yozuvlarini olib tashlaydi.

    HISOB QOLADI (yuqoridagi izohga qarang) va bu YOZIB QO'YILADI:
    "hammasi tozalandi" deb yolg'on gapirilmaydi.
    """
    bolim("6. Tozalash")
    # HOVUZNI QAYTA OCHAMIZ: `TestClient` kontekstdan chiqqanda
    # ilovaning `shutdown` hodisasi `close_pool()` ni chaqiradi.
    db.init_pool()
    from api import saqlash

    idlar = [int(r["id"]) for r in db.query(
        "SELECT id FROM company_account WHERE username = ANY(%(u)s)",
        {"u": [U_A, U_B]})]
    if not idlar:
        check("tozalash uchun hisob topildi", False, "hisob yo'q")
        return

    kalitlar = [r["kalit"] for r in db.query(
        "SELECT kalit FROM yuklama WHERE company_id = ANY(%(i)s)",
        {"i": idlar})]

    # `chat_yuklama` va `yuklama_chunk` KASKAD bilan ketadi.
    n = db.scalar("SELECT count(*) FROM yuklama WHERE company_id = ANY(%(i)s)",
                  {"i": idlar})
    db.execute_returning(
        "DELETE FROM yuklama WHERE company_id = ANY(%(i)s) RETURNING id",
        {"i": idlar})
    check("sinov yuklamalari o'chirildi",
          db.scalar("SELECT count(*) FROM yuklama WHERE company_id = ANY(%(i)s)",
                    {"i": idlar}) == 0, f"{n} ta edi")
    check("bo'laklar KASKAD bilan ketdi",
          db.scalar("SELECT count(*) FROM yuklama_chunk "
                    "WHERE company_id = ANY(%(i)s)", {"i": idlar}) == 0)
    check("chat biriktirmalari KASKAD bilan ketdi",
          db.scalar("SELECT count(*) FROM chat_yuklama "
                    "WHERE company_id = ANY(%(i)s)", {"i": idlar}) == 0)

    db.execute_returning(
        "UPDATE chat_session SET archived = TRUE "
        " WHERE company_id = ANY(%(i)s) AND NOT archived RETURNING id",
        {"i": idlar})
    db.execute_returning(
        "DELETE FROM company_document WHERE company_id = ANY(%(i)s) RETURNING id",
        {"i": idlar})

    s = saqlash.saqlagich()
    # XATO YUTILMAYDI. Ilgari bu yerda `except: pass` turardi va
    # arxivlash NEGA yiqilgani hech qayerda ko'rinmasdi — quyidagi
    # shart faqat "fayl qoldi" derdi, sababini emas.
    kochmadi = []
    for k in kalitlar:
        try:
            if s.exists(k):
                s.archive(k)
        except Exception as e:                                # noqa: BLE001
            kochmadi.append(f"{k}: {type(e).__name__}")
    check("arxivlashda xato bo'lmadi", not kochmadi, "; ".join(kochmadi[:3]))

    # SHART "NECHTASI KO'CHDI" EMAS, "TIRIK QOLDIMI".
    #
    # O'LCHANGAN NUQSON (2026-09-06): ilgari bu yerda ko'chirilgan
    # fayllar SANALARDI va "2 ta ko'chirilmadi" deb yiqilardi. Lekin
    # ko'chirilmagani YO'QOLGAN degani emas: avvalgi YIQILGAN yurish
    # yozuvni o'chirib, faylni arxivga qo'ygan bo'lishi mumkin.
    # Ya'ni shart NATIJANI emas, YO'LNI o'lchardi va o'tmish
    # qoldig'idan yiqilardi.
    #
    # Endi HAQIQIY invariant tekshiriladi: sinov kompaniyalarining
    # TIRIK (arxivdan tashqari) katalogida fayl QOLMASIN. Bu
    # o'tmishga befarq va KUCHLIROQ -- u haqiqiy sizishni ushlaydi.
    tirik = []
    for cid in idlar:
        kat = os.path.join(s.ildiz, str(cid))
        if os.path.isdir(kat):
            tirik += [os.path.join(kat, f) for f in os.listdir(kat)
                      if os.path.isfile(os.path.join(kat, f))]
    check("sinov kompaniyalarida TIRIK fayl qolmadi",
          not tirik, f"{len(tirik)} ta: {[os.path.basename(x) for x in tirik][:3]}")
    print(f"        [i] {len(kalitlar)} kalit ko'rib chiqildi, "
          f"arxivga ko'chirildi.")
    # HISOB NOFAOL QILINADI — BU MAJBURIY, QULAYLIK EMAS.
    #
    # O'LCHANGAN NUQSON (2026-09-06): hisob FAOL qolgani uchun
    # `auth.sole_company_id()` "bir nechta faol kompaniya" deb
    # yiqildi va TO'QQIZ ta boshqa to'plam qizil bo'ldi
    # (`catalog_kod`, `chat`, `compliance`, `import`, `notify`, ...).
    # Ya'ni bu sinovning qoldig'i BUTUN darvozani buzardi.
    db.execute_returning(
        "UPDATE company_account SET active = FALSE "
        " WHERE id = ANY(%(i)s) AND active RETURNING id", {"i": idlar})
    check("sinov hisoblari NOFAOL qilindi",
          db.scalar("SELECT count(*) FROM company_account "
                    "WHERE id = ANY(%(i)s) AND active", {"i": idlar}) == 0)
    print(f"        [i] `{U_A}` va `{U_B}` hisoblari O'CHIRILMADI, "
          f"NOFAOL qilindi: `audit_jurnal` DELETE ni rad etadi "
          f"(bu TO'G'RI qoida).")


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Fayl yuklash sinovi")
    rejim.bayroqlar(ap)
    args = rejim.moslash(ap.parse_args())

    print("=" * 70)
    print("SINOV: HAQIQIY FAYL YUKLASH")
    print("=" * 70)

    test_manba()
    test_holat_mashinasi()
    test_migratsiya()

    bazali = (not args.bazasiz) and bool(os.environ.get("XT_DB_DSN"))
    if not bazali:
        print("\n[i] Bazali tekshiruvlar O'TKAZIB YUBORILDI "
              "(--bazasiz yoki XT_DB_DSN yo'q).")
    else:
        from api import db
        db.init_pool()
        rejim.rol_tekshir(db)
        try:
            cid_a, cid_b, HA, HB = test_kompaniya_hujjati(db)
            test_chat_biriktirma(db, cid_a, cid_b, HA, HB)
        except Exception as e:                                # noqa: BLE001
            import traceback
            traceback.print_exc()
            check("bazali tekshiruv", False, str(e)[:140])
        finally:
            try:
                test_tozala(db)
            except Exception as e:                            # noqa: BLE001
                check("tozalash", False, str(e)[:110])

    otdi = sum(1 for _n, ok, _d in _natija if ok)
    jami = len(_natija)
    print("\n" + "=" * 70)
    for n, ok, d in _natija:
        if not ok:
            print(f"  YIQILDI: {n}" + (f" -- {d}" if d else ""))
    print(f"NATIJA: {otdi}/{jami} o'tdi")
    print("=" * 70)
    sys.exit(0 if otdi == jami else 1)


if __name__ == "__main__":
    main()
