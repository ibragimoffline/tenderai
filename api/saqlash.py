# =============================================================================
# FAYL SAQLASH — backenddan MUSTAQIL interfeys
# =============================================================================
# NEGA ABSTRAKSIYA. Ishlab chiqarishda fayllar hozircha server diskida
# yotadi va bu joriy arxitekturaga mos. Lekin `company_document.file_ref`
# da AYNAN SHU xato allaqachon sodir bo'lgan: yo'l KODGA VA BAZAGA
# to'g'ridan-to'g'ri yozilgan edi —
#
#     file:///D:/MVP%20projects/tender-ai/.runtime/company_documents/2/...
#
# ya'ni bitta ishlab chiquvchi mashinasining mutlaq yo'li 13 ta bazaviy
# qatorga muhrlanib qolgan. Diskni almashtirish uchun ma'lumot
# migratsiyasi kerak bo'lardi.
#
# Shuning uchun bu yerda BAZAGA faqat `kalit` yoziladi (`2/ab12...pdf`)
# va yo'lni FAQAT backend biladi. S3/MinIO ga o'tish — yangi sinf,
# bazaga tegilmaydi.
#
# NIMA QILINMAYDI: bu taqsimlangan saqlash platformasi EMAS. Beshta
# amal bor va boshqasi yo'q.
# =============================================================================
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Optional

from api import xatolar

#: Saqlash ildizi. `.env` bilan almashtiriladi — ishlab chiqarishda
#: `/var/lib/tenderai/uploads`, u yerda `tenderai` foydalanuvchisi
#: yozadi va `deploy/bin/backup.sh` shu katalogni arxivlaydi.
#:
#: STANDART QIYMAT REPOZITORIY ICHIDA emas, `.runtime/` da: u
#: `.gitignore` da va yuklangan fayl hech qachon commitga tushmaydi.
ILDIZ = os.environ.get(
    "UPLOAD_ROOT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 ".runtime", "uploads"))

#: Yuklash chegarasi. `MAX_IMPORT_MB` (5) dan ALOHIDA: u Excel
#: shabloni uchun tanlangan va tender PDF lari uchun kichik.
#: O'zgartirilsa `deploy/caddy/Caddyfile` dagi tana chegarasi ham
#: birga o'zgarishi kerak — aks holda so'rov ilovaga YETIB kelmaydi
#: va foydalanuvchi tushunarsiz 413 oladi.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))

#: Kengaytma uchun ruxsat etilgan belgilar. Kalitga FAQAT shu
#: tushadi — asl nomdan olingan kengaytma ham shu filtrdan o'tadi.
_EXT_OK = re.compile(r"^[a-z0-9]{1,8}$")


@dataclass(frozen=True)
class Malumot:
    """Saqlangan fayl haqidagi backend ma'lumoti."""
    kalit: str
    size_bytes: int
    backend: str


# =============================================================================
# Nom tozalash
# =============================================================================
def tozala_nom(nom: str) -> str:
    """Asl fayl nomini KO'RSATISH uchun xavfsizlaydi.

    BU YO'L YASAMAYDI. Natija faqat `yuklama.original_nom` ga va
    `Content-Disposition` ga boradi. Fizik yo'l `kalit()` dan keladi
    va u foydalanuvchi matnini UMUMAN ishlatmaydi — ya'ni bu funksiya
    buzilsa ham yo'l chiqib ketmaydi (ikki qatlam).

    Nima olib tashlanadi va NEGA:
      * katalog qismi (`../`, `C:\\`, `/etc/`) — nom ichida yo'l
        bo'lishi mumkin, brauzerlar ba'zan to'liq yo'l yuboradi;
      * boshqaruv belgilari — jurnal va sarlavhani buzadi;
      * `"` va `\\r\\n` — `Content-Disposition` sarlavhasini ochadi
        (sarlavha in'ektsiyasi).
    """
    nom = (nom or "").replace("\\", "/").split("/")[-1]
    nom = "".join(c for c in nom if ord(c) >= 32 and c not in '"\\')
    nom = nom.strip().strip(".")           # `.` va `..` ni yo'q qiladi
    return nom[:200] or "fayl"


def ext_ol(nom: str) -> str:
    """Kengaytma — KICHIK harfda va belgi oq ro'yxati bo'yicha.

    NUQTASIZ NOMDA KENGAYTMA YO'Q. O'LCHANGAN NUQSON (2026-09-06):
    `rpartition(".")` ajratgich topilmasa BUTUN satrni uchinchi
    element qilib qaytaradi, ya'ni `passwd` fayli `passwd`
    kengaytmasini olardi va u `_EXT_OK` dan bemalol o'tardi.
    Endi nuqtadan OLDINGI qism ham bo'sh bo'lmasligi tekshiriladi.

    Bu funksiya FAQAT nomdan o'qiydi. Ruxsat etilgan formatlar
    ro'yxati bu yerda EMAS (`api/yuklama.RUXSAT_EXT`) — saqlash
    qatlami biznes qoidasini bilmaydi.
    """
    bosh, nuqta, e = tozala_nom(nom).rpartition(".")
    if not nuqta or not bosh:
        return ""
    e = e.lower().strip()
    return e if _EXT_OK.match(e) else ""


# =============================================================================
# Interfeys
# =============================================================================
class Saqlagich:
    """Beshta amal. Ko'proq emas.

    `save` — bayt oqimini saqlaydi, kalit qaytaradi
    `open` — o'qish uchun ochadi
    `exists` — bormi
    `metadata` — hajm va backend
    `archive` — o'chirmaydi, ARXIVGA ko'chiradi
    """

    nom = "abstract"

    def kalit_yasa(self, company_id: int, ext: str) -> str:
        """`<company_id>/<uuid>[.ext]` — ATAYLAB TAXMIN QILIB BO'LMAYDI.

        ASL NOM UMUMAN QABUL QILINMAYDI. Ilgari bu funksiya nomni
        olib kengaytmani o'zi ajratardi va `virus.exe` uchun `.exe`
        bilan tugaydigan kalit yasardi. Biznes qatlami uni baribir
        rad etardi, lekin SAQLASH qatlamining o'zi bajariladigan
        kengaytmali fayl yozishga qodir bo'lib qolardi.
        Endi kengaytma TEKSHIRILGAN holda tashqaridan keladi va bu
        yerda yana bir marta belgi filtridan o'tadi.
        """
        e = (ext or "").lower().strip().lstrip(".")
        if not _EXT_OK.match(e):
            e = ""
        return f"{int(company_id)}/{uuid.uuid4().hex}" + (f".{e}" if e else "")

    def save(self, company_id: int, ext: str, data: bytes) -> Malumot:
        raise NotImplementedError

    def open(self, kalit: str) -> BinaryIO:
        raise NotImplementedError

    def exists(self, kalit: str) -> bool:
        raise NotImplementedError

    def metadata(self, kalit: str) -> Optional[Malumot]:
        raise NotImplementedError

    def archive(self, kalit: str) -> str:
        raise NotImplementedError


# =============================================================================
# Mahalliy disk
# =============================================================================
class MahalliyDisk(Saqlagich):

    nom = "local"

    def __init__(self, ildiz: str = ILDIZ):
        self.ildiz = os.path.abspath(ildiz)

    # ---- yo'l xavfsizligi -------------------------------------------------
    def _yol(self, kalit: str) -> str:
        """Kalitni yo'lga aylantiradi va ILDIZDAN CHIQMASLIGINI tekshiradi.

        Kalit ODATDA bizniki (`kalit_yasa`), lekin u BAZADAN keladi va
        baza qatori bir kun qo'lda tahrirlanishi mumkin. Shuning uchun
        tekshiruv HAR o'qishda ishlaydi, faqat yozishda emas.

        `os.path.commonpath` ishlatiladi, `startswith` EMAS:
        `/data/uploads-eski` `/data/uploads` bilan boshlanadi va
        `startswith` uni ICHKARIDA deb hisoblardi.
        """
        if not kalit or "\x00" in kalit:
            raise xatolar.Xato("FILE_NOT_FOUND")
        t = os.path.abspath(os.path.join(self.ildiz, kalit.replace("\\", "/")))
        try:
            if os.path.commonpath([self.ildiz, t]) != self.ildiz:
                raise xatolar.Xato("FILE_NOT_FOUND")
        except ValueError:
            # Turli disk (Windows `C:` va `D:`) — `commonpath` yiqiladi.
            raise xatolar.Xato("FILE_NOT_FOUND")
        return t

    # ---- amallar ----------------------------------------------------------
    def save(self, company_id: int, ext: str, data: bytes) -> Malumot:
        kalit = self.kalit_yasa(company_id, ext)
        t = self._yol(kalit)
        os.makedirs(os.path.dirname(t), exist_ok=True)
        # ATOMAR: avval `.qism`, keyin `os.replace`. Yozish yarmida
        # jarayon o'lsa, YARIM fayl `kalit` nomi bilan qolmaydi —
        # aks holda baza "bor" derdi va o'qish buzuq bayt qaytarardi.
        vaqt = t + ".qism"
        with open(vaqt, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(vaqt, t)
        return Malumot(kalit=kalit, size_bytes=len(data), backend=self.nom)

    def open(self, kalit: str) -> BinaryIO:
        t = self._yol(kalit)
        if not os.path.isfile(t):
            raise xatolar.Xato("FILE_NOT_FOUND")
        return open(t, "rb")

    def exists(self, kalit: str) -> bool:
        try:
            return os.path.isfile(self._yol(kalit))
        except xatolar.Xato:
            return False

    def metadata(self, kalit: str) -> Optional[Malumot]:
        t = self._yol(kalit)
        if not os.path.isfile(t):
            return None
        return Malumot(kalit=kalit, size_bytes=os.path.getsize(t),
                       backend=self.nom)

    def archive(self, kalit: str) -> str:
        """FAYLNI O'CHIRMAYDI — `arxiv/` ostiga ko'chiradi.

        NEGA. Hujjat muvofiqlik tekshiruvida, malakada yoki o'tgan
        AI javobining iqtibosida ishlatilgan bo'lishi mumkin. Faylni
        yo'q qilish o'sha qarorlarning DALILINI yo'q qiladi (§11).
        Baza qatori ham qoladi (`yuklama.arxiv_at`).
        """
        manba = self._yol(kalit)
        maqsad = self._yol(os.path.join("arxiv", kalit))
        os.makedirs(os.path.dirname(maqsad), exist_ok=True)
        if os.path.isfile(manba):
            shutil.move(manba, maqsad)
        return os.path.relpath(maqsad, self.ildiz).replace("\\", "/")


# =============================================================================
# Tanlov
# =============================================================================
_saqlagich: Optional[Saqlagich] = None


def saqlagich() -> Saqlagich:
    """Sozlangan backendni qaytaradi.

    Hozircha bitta amalga oshirish bor va `STORAGE_BACKEND` faqat
    `local` ni qabul qiladi. Noma'lum qiymat JIMGINA `local` ga
    tushmaydi: sozlamada xato bo'lsa fayllar kutilmagan joyga
    yozilardi va buni faqat zaxira tiklashda bilib qolardik.
    """
    global _saqlagich
    if _saqlagich is None:
        turi = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
        if turi != "local":
            raise xatolar.Xato("STORAGE_BACKEND_UNKNOWN", {"backend": turi})
        _saqlagich = MahalliyDisk()
    return _saqlagich


def qayta_ochil() -> None:
    """Sinov uchun: keshlangan backendni tashlaydi."""
    global _saqlagich
    _saqlagich = None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
