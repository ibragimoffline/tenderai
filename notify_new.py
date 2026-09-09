#!/usr/bin/env python3
"""
BILDIRISHNOMA (TZ P0-10) — "yangi mos tender" xabarini yuboradi
===============================================================
ETL DAN KEYIN chaqiriladi: ETL yangi tenderlarni bazaga yozadi, bu skript esa
oxirgi tsiklда BIRINCHI MARTA ko'rilganlar orasidan moslik chegarasidan
yuqorilarini tanlab xabar yuboradi.

IKKI KANAL — EMAIL (SMTP) va TELEGRAM (Bot API). Ikkalasi mustaqil yoqiladi
(`notify_settings.enabled` / `telegram_enabled`) va MUSTAQIL ISHLAYDI: biri
xato bersa ikkinchisi baribir yuboriladi. Har kanal o'z jurnalini yuritadi
(`notify_sent.kind`), shuning uchun Telegram keyinroq yoqilsa u email
"yuborilgan" deb belgilagan tenderlarga bog'lanib qolmaydi.

TZ qabul qilish mezonlari:
  [x] SOATLIK KUZATISH TSIKLI DAVOMIDA keladi — `tender.first_seen_at` oxirgi
      `etl_run` tsikli boshlanganidan keyin bo'lganlari olinadi.
  [x] TIZIMDAGI TENDER KARTOCHKASIGA HAVOLA — xabarда har tender uchun
      `base_url + /?tender=<id>` havolasi bor (email matn, email HTML va
      Telegram versiyalarида).

TAKRORLANMAYDI: yuborilgan tenderlar `notify_sent` jadvaliga yoziladi, keyingi
yurishda ular tashlab ketiladi (`--force` bilan chetlab o'tish mumkin).

SIRLAR BAZADA EMAS — `.env` dagi `SMTP_PASSWORD` va `TELEGRAM_BOT_TOKEN`.
Yo'q bo'lsa skript ANIQ XATO bilan tugaydi (exit 2), jimgina "yuborildi" demaydi.

Ishga tushirish:
    python notify_new.py --dry-run       # nima ketishini ko'rsatadi (yubormaydi)
    python notify_new.py                 # haqiqiy yuborish (yoqilgan kanallarga)
    python notify_new.py --min-score 85  # chegarani shu yurish uchun o'zgartirish
    python notify_new.py --limit 5       # xabarда ko'pi bilan 5 ta tender
    python notify_new.py --force         # allaqachon xabar ketganlarni ham
    python notify_new.py --since-hours 24  # oxirgi 24 soatда ko'rilganlar
"""
import argparse
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()  # api.db DSN'ni ko'rishi uchun importdan OLDIN

from api import auth, db, notify, ommaviy_url  # noqa: E402

# Windows konsoli standart kodlashда (cp1251/cp866) tender nomlaridagi kirill
# va o'zbekcha belgilarni chiqara olmaydi -> UnicodeEncodeError. Chop etish
# BILDIRISHNOMANI BUZMASLIGI kerak, shuning uchun oqimni UTF-8 ga o'tkazamiz.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):  # eski Python / g'ayrioddiy oqim
    pass


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Yangi mos tenderlar haqida bildirishnoma — email va "
                    "Telegram (TZ P0-10)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Yubormaydi va bazaga yozmaydi — faqat ko'rsatadi")
    ap.add_argument("--limit", type=int, default=notify.DEFAULT_LIMIT,
                    help=f"Xabardagi tenderlar soni (standart {notify.DEFAULT_LIMIT})")
    ap.add_argument("--min-score", type=int, default=None,
                    help="Moslik chegarasi 0-100 (standart: sozlamalardan)")
    ap.add_argument("--force", action="store_true",
                    help="Allaqachon xabar ketganlarni ham qayta yuboradi")
    ap.add_argument("--since-hours", type=float, default=None,
                    help="Oxirgi ETL tsikli o'rniga: oxirgi N soat")
    ap.add_argument("--company", type=int, default=None,
                    help="Faqat shu kompaniya (standart: HAR faol kompaniya)")
    args = ap.parse_args()

    if not os.environ.get("XT_DB_DSN"):
        sys.exit("XATO: XT_DB_DSN o'rnatilmagan (.env faylini tekshiring).")

    # OMMAVIY MANZIL — ISHDAN OLDIN. Bu skript ETL taymeridan yuriladi,
    # ya'ni HAQIQIY yuborish yo'li shu. Manzil yaroqsiz bo'lsa nosozlik
    # `notify.run()` ning O'RTASIDA — nomzodlar hisoblanib, ba'zi
    # xabarlar allaqachon ketgandan KEYIN — chiqardi. Oldin
    # tekshiramiz: `--dry-run` da ham, chunki yaroqsiz sozlamani
    # quruq yurishda ko'rish aynan kerak.
    try:
        ommaviy_url.ishga_tushishda_tekshir()
    except ommaviy_url.OmmaviyUrlXato as e:
        sys.exit(f"XATO: {e}")

    db.init_pool()
    xatolar: list = []
    try:
        # HAR IJARACHI UCHUN ALOHIDA.
        #
        # O'LCHANGAN NUQSON (2026-09-09, staging ETL). Skript
        # kompaniyani UMUMAN so'ramasdi va `notify.run()` ichida
        # `auth.sole_company_id()` ga tushardi — u esa AYNAN BITTA
        # faol kompaniya bo'lishini talab qiladi:
        #
        #     AuthError: Bir nechta faol kompaniya: 1(...), 8(...), ...
        #
        # Bu ko'p-ijarachili tizimda yagona-ijarachi taxmini edi.
        # Production da u faqat SHU KUNGACHA ishlaydi: ikkinchi
        # kompaniya qo'shilgan kunda soatlik ETL ning bildirishnoma
        # qadami yiqila boshlaydi va HECH KIM xabar olmaydi.
        # Nosozlik esa bitta jurnal satri bo'lib qolardi.
        if args.company is not None:
            kompaniyalar = [{"id": args.company, "username": f"id={args.company}"}]
        else:
            kompaniyalar = auth.active_companies()
            if not kompaniyalar:
                sys.exit("XATO: faol kompaniya hisobi yo'q.")

        for k in kompaniyalar:
            cid, nom = int(k["id"]), k.get("username") or f"id={k['id']}"
            # BITTA IJARACHINING NOSOZLIGI QOLGANLARINI TO'XTATMASIN.
            # Aks holda ro'yxatdagi birinchi buzuq sozlama butun
            # tsiklni o'ldirardi va undan keyingilar xabar olmasdi.
            try:
                res = notify.run(min_score=args.min_score, limit=args.limit,
                                 dry_run=args.dry_run, force=args.force,
                                 since_hours=args.since_hours,
                                 company_id=cid)
            except notify.NotifyError as e:
                xatolar.append(f"{nom}: {e}")
                print(f"[XATO] {nom}: {e}")
                continue

            tg = res.get("telegram") or {}
            print(f"--- {nom} (id={cid}) ---")
            print(f"Chegara: {res['min_score']} ball | oyna: {res['since']} dan beri")
            print(f"Topildi: email uchun {res['found']} ta, "
                  f"Telegram uchun {tg.get('found', 0)} ta")
            if args.dry_run and res.get("text"):
                print("\n--- YUBORILADIGAN XABAR (dry-run) ---")
                print(res["subject"])
                print(res["text"])
                print("--- xabar tugadi ---\n")
            print(res["message"])
    except db.DBUnavailable as e:
        sys.exit(f"XATO: baza mavjud emas: {e}")
    finally:
        db.close_pool()

    # JIM O'TMAYDI. Yiqilgan ijarachi bo'lsa chiqish kodi 1 --
    # timer "muvaffaqiyatli" deb yozmasin.
    if xatolar:
        sys.exit("XATO: %d ta kompaniyada nosozlik:\n  %s"
                 % (len(xatolar), "\n  ".join(xatolar)))

    # KANAL XATOSI JIMGINA O'TMAYDI. run() xatoni tashlamaydi (bir kanal
    # yiqilsa ikkinchisi yuborilishi kerak), shuning uchun chiqish kodini
    # SHU YERDA belgilaymiz — cron logда nosozlik ko'rinsin.
    errors = [e for e in (res.get("error"), tg.get("error")) if e]
    if errors:
        for e in errors:
            print(f"XATO: {e}", file=sys.stderr)
        sys.exit(2)
    # Yuborilmagan bo'lsa ham xato emas (yangi tender yo'q bo'lishi normal)
    sys.exit(0)


if __name__ == "__main__":
    main()
