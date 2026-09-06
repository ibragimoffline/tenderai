# -*- coding: utf-8 -*-
"""
KUZATUVCHANLIK — operator SQL yozmasdan javob olsin
=====================================================

BU MODUL NIMA QILADI:
  * so'rov o'lchovlarini yig'adi (soni, kechikish, 4xx, 5xx);
  * disk bo'sh joyini o'lchaydi;
  * baza ko'rinishlari bilan birga YAGONA javob yasaydi.

CHEKLOV OCHIQ AYTILADI: so'rov o'lchovlari JARAYON ICHIDA
saqlanadi. Bir necha `uvicorn` ishchisi bo'lsa, har biri O'Z
raqamini ko'radi va qayta ishga tushirilganda ular NOLLANADI.

Bu Prometheus o'rnini BOSMAYDI. U "hozir nima bo'lyapti" degan
savolga javob beradi — tarixiy trend uchun tashqi yig'uvchi
kerak. Shuni aytmaslik "bizda metrikalar bor" degan yolg'on
xotirjamlik berardi.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

#: Oxirgi N so'rov — kechikish protsentillari uchun.
#: 2000 ta ~ bir necha daqiqalik trafik; xotira ~200 KB.
_OYNA = int(os.environ.get("OPS_LATENCY_WINDOW", "2000"))

#: Diskda shu foizdan kam qolsa — ogohlantirish / xato.
DISK_OGOH_FOIZ = float(os.environ.get("OPS_DISK_WARN_PCT", "15"))
DISK_XATO_FOIZ = float(os.environ.get("OPS_DISK_CRIT_PCT", "7"))

#: ETL yurak urishi shuncha sekund jim tursa — osilgan.
ETL_JIMLIK_OGOH = int(os.environ.get("OPS_ETL_SILENT_WARN", "1800"))
ETL_JIMLIK_XATO = int(os.environ.get("OPS_ETL_SILENT_CRIT", "3600"))

#: 5xx ulushi shu foizdan oshsa — ogohlantirish / xato.
XATO_OGOH_FOIZ = float(os.environ.get("OPS_5XX_WARN_PCT", "2"))
XATO_XATO_FOIZ = float(os.environ.get("OPS_5XX_CRIT_PCT", "10"))

_qulf = threading.Lock()
_boshlandi = time.time()
_soni = 0
_4xx = 0
_5xx = 0
#: (vaqt, ms) — eskisi o'zi tushib ketadi.
_kechikish: Deque[Tuple[float, int]] = deque(maxlen=_OYNA)
#: Yo'l bo'yicha 5xx — qaysi endpoint yiqilayotganini aytadi.
_5xx_yol: Dict[str, int] = {}


def yoz(yol: str, kod: int, ms: int) -> None:
    """Middleware har so'rovdan keyin chaqiradi. ARZON bo'lishi shart."""
    global _soni, _4xx, _5xx
    with _qulf:
        _soni += 1
        _kechikish.append((time.time(), ms))
        if 400 <= kod < 500:
            _4xx += 1
        elif kod >= 500:
            _5xx += 1
            # YO'L NORMALLASHTIRILADI: `/tenders/123` va
            # `/tenders/456` bitta yo'l. Aks holda lug'at
            # cheksiz o'sardi (xotira sizishi).
            _5xx_yol[normal_yol(yol)] = _5xx_yol.get(normal_yol(yol), 0) + 1


def normal_yol(yol: str) -> str:
    """Raqamli bo'laklarni `{id}` ga almashtiradi."""
    bolaklar = []
    for b in (yol or "/").split("/"):
        bolaklar.append("{id}" if b.isdigit() else b)
    return "/".join(bolaklar) or "/"


def _protsentil(qiymatlar: List[int], p: float) -> Optional[int]:
    if not qiymatlar:
        return None
    s = sorted(qiymatlar)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[i]


def sorov_olchovi() -> Dict[str, Any]:
    with _qulf:
        soni, c4, c5 = _soni, _4xx, _5xx
        oyna = list(_kechikish)
        yollar = dict(_5xx_yol)
    ms = [m for _t, m in oyna]
    # OXIRGI 5 DAQIQA — "sekinlashyaptimi" savoli AYNAN shu.
    kesim = time.time() - 300
    yaqin = [m for t, m in oyna if t >= kesim]
    return {
        "ishlash_sek": round(time.time() - _boshlandi),
        "sorov": soni,
        "kod_4xx": c4,
        "kod_5xx": c5,
        "xato_foiz_5xx": round(100.0 * c5 / soni, 2) if soni else None,
        "kechikish_ms": {
            "oyna": len(ms),
            "p50": _protsentil(ms, 50),
            "p95": _protsentil(ms, 95),
            "p99": _protsentil(ms, 99),
        },
        "oxirgi_5daq": {
            "sorov": len(yaqin),
            "p95_ms": _protsentil(yaqin, 95),
        },
        "eng_kop_5xx": sorted(yollar.items(), key=lambda x: -x[1])[:5],
        "cheklov": ("JARAYON ICHIDA yig'iladi: har `uvicorn` ishchisi "
                    "o'z raqamini ko'radi va qayta ishga tushganda "
                    "NOLLANADI. Tarixiy trend uchun tashqi yig'uvchi kerak."),
    }


def disk(yol: Optional[str] = None) -> Dict[str, Any]:
    """Disk bo'sh joyi. O'LCHAB BO'LMASA — `nomalum`, `ok` EMAS."""
    yol = yol or os.environ.get("OPS_DISK_PATH") or os.path.abspath(os.sep)
    try:
        u = shutil.disk_usage(yol)
    except OSError as e:
        # YASHIRILMAYDI: o'lchab bo'lmagani ham NATIJA.
        return {"yol": yol, "holat": "nomalum", "xato": str(e)[:120]}
    bosh_foiz = round(100.0 * u.free / u.total, 1) if u.total else None
    holat = "nomalum"
    if bosh_foiz is not None:
        holat = ("xato" if bosh_foiz < DISK_XATO_FOIZ
                 else "ogoh" if bosh_foiz < DISK_OGOH_FOIZ else "ok")
    return {
        "yol": yol,
        "holat": holat,
        "bosh_foiz": bosh_foiz,
        "bosh_gb": round(u.free / 2 ** 30, 1),
        "jami_gb": round(u.total / 2 ** 30, 1),
    }


def _api_holati(o: Dict[str, Any]) -> str:
    f = o.get("xato_foiz_5xx")
    if not o.get("sorov"):
        # HALI SO'ROV YO'Q. `ok` deyish yolg'on bo'lardi —
        # hech narsa o'lchanmagan.
        return "nomalum"
    if f is None:
        return "nomalum"
    return ("xato" if f >= XATO_XATO_FOIZ
            else "ogoh" if f >= XATO_OGOH_FOIZ else "ok")


#: HOLAT TARTIBI — eng yomoni g'olib.
_OGIRLIK = {"ok": 0, "nomalum": 1, "ogoh": 2, "xato": 3}


def umumiy(qatorlar: List[Dict[str, Any]]) -> str:
    """Eng yomon holat g'olib.

    `nomalum` `ok` DAN YOMONROQ, lekin `ogoh` dan yengilroq:
    o'lchanmagan narsa "joyida" emas, lekin "yiqilgan" ham emas.
    """
    if not qatorlar:
        return "nomalum"
    return max((q.get("holat", "nomalum") for q in qatorlar),
               key=lambda h: _OGIRLIK.get(h, 1))


def holat(db) -> Dict[str, Any]:
    """OPERATOR JAVOBI — bitta chaqiruv, o'nta savol."""
    qatorlar: List[Dict[str, Any]] = []

    # 1) BAZA. Boshqa hammasi shunga bog'liq, shuning uchun
    #    birinchi va ALOHIDA tekshiriladi.
    baza = {"komponent": "baza", "kesim": "-"}
    t0 = time.time()
    try:
        db.scalar("SELECT 1")
        baza.update(holat="ok", qiymat=round((time.time() - t0) * 1000),
                    olchov="javob vaqti, ms")
    except Exception as e:                                   # noqa: BLE001
        baza.update(holat="xato", qiymat=None,
                    olchov="javob vaqti, ms", izoh=str(e)[:120])
        qatorlar.append(baza)
        # BAZA YIQILGAN BO'LSA qolganini so'rash MA'NOSIZ va u
        # xatolar ustiga xato qo'shardi.
        return {"umumiy": "xato", "qatorlar": qatorlar,
                "api": sorov_olchovi(), "disk": disk(),
                "izoh": "baza yetib bo'lmadi — qolgan o'lchovlar olinmadi"}
    qatorlar.append(baza)

    # 2) BAZADAGI KO'RINISH — ETL, hujjat, embedding, bildirishnoma.
    for r in db.query("SELECT komponent, kesim, holat, qiymat, olchov "
                      "FROM v_ops_holat ORDER BY komponent, kesim"):
        qatorlar.append(dict(r))

    # 3) API o'lchovi.
    o = sorov_olchovi()
    qatorlar.append({
        "komponent": "api", "kesim": "5xx",
        "holat": _api_holati(o),
        "qiymat": o["xato_foiz_5xx"], "olchov": "5xx ulushi, foiz"})

    # 4) DISK.
    d = disk()
    qatorlar.append({
        "komponent": "disk", "kesim": d["yol"], "holat": d["holat"],
        "qiymat": d.get("bosh_foiz"), "olchov": "bo'sh joy, foiz"})

    return {
        "umumiy": umumiy(qatorlar),
        "qatorlar": qatorlar,
        "api": o,
        "disk": d,
        "chegaralar": {
            "etl_jimlik_ogoh_sek": ETL_JIMLIK_OGOH,
            "etl_jimlik_xato_sek": ETL_JIMLIK_XATO,
            "disk_ogoh_foiz": DISK_OGOH_FOIZ,
            "disk_xato_foiz": DISK_XATO_FOIZ,
            "xato_5xx_ogoh_foiz": XATO_OGOH_FOIZ,
            "xato_5xx_xato_foiz": XATO_XATO_FOIZ,
        },
    }
