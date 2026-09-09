"""
KOMPANIYA hisobini yaratish / parolini almashtirish — buyruq qatoridan.

    .venv/Scripts/python.exe create_company.py alfa "Alfa Savdo MChJ"
    .venv/Scripts/python.exe create_company.py alfa --password   # parol almashtirish
    .venv/Scripts/python.exe create_company.py --list

NEGA HODIM EMAS: tender-ai ga KOMPANIYA kiradi. Hodim hisoblari ERP da va
ular uchun alohida skript bor (`tender erp/create_user.py`). Auth-1 da bu
skript (`create_user.py`) shu yerda edi — xato, u ERP ga ko'chirildi.

NEGA SKRIPT, "ro'yxatdan o'tish" endpointi EMAS: har qanday bunday
endpoint — ochiq eshik. U "hisob yo'q bo'lsa ishlaydi" degan shart bilan
yopilsa ham, baza tozalangan paytda yana ochiladi.

Parol terilganda EKRANDA KO'RINMAYDI (`getpass`) va buyruq tarixiga
tushmaydi.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):            # pragma: no cover
    pass

from dotenv import load_dotenv

load_dotenv()

from api import auth, db  # noqa: E402


def _stdin_password() -> str:
    """Parolni STDIN dan oladi (`--parol-stdin`).

    NEGA KERAK. `getpass` avval `/dev/tty` ni ochadi va terminal
    bo'lsa AYNAN O'SHANDAN o'qiydi -- quvurdan berilgan parolni
    ko'rmaydi va operator oldida OSILIB qoladi. Ya'ni skriptdan
    parol o'rnatish `getpass` bilan ishonchli emas.

    NEGA ARGUMENT EMAS. Buyruq argumenti `ps` da har bir
    foydalanuvchiga ko'rinadi va qobiq tarixiga tushadi. STDIN
    ikkalasida ham ko'rinmaydi.

    Faqat BIRINCHI qator olinadi va oxiridagi qator uzilishi
    tashlanadi. Ichki bo'shliqlar SAQLANADI -- ular parolning
    qismi bo'lishi mumkin.
    """
    p = sys.stdin.readline()
    if not p:
        print("STDIN bo'sh: parol berilmadi.")
        raise SystemExit(1)
    p = p.rstrip("\r\n")
    if not p:
        print("Parol bo'sh.")
        raise SystemExit(1)
    return p


def _ask_password() -> str:
    p1 = getpass.getpass("Parol: ")
    p2 = getpass.getpass("Yana bir marta: ")
    if p1 != p2:
        print("Parollar mos kelmadi.")
        raise SystemExit(1)
    return p1


def _parol(a) -> str:
    return _stdin_password() if getattr(a, "parol_stdin", False) else _ask_password()


def main() -> int:
    ap = argparse.ArgumentParser(description="Kompaniya hisobini yaratish")
    ap.add_argument("username", nargs="?", help="kirish nomi")
    ap.add_argument("company_name", nargs="?", help="kompaniya nomi")
    ap.add_argument("--email", default=None)
    ap.add_argument("--password", action="store_true",
                    help="mavjud hisobning parolini almashtirish")
    ap.add_argument("--list", action="store_true", help="hisoblar ro'yxati")
    ap.add_argument("--parol-stdin", action="store_true",
                    help="parolni STDIN dan olish (skriptlar uchun; "
                         "argumentga tushmaydi)")
    a = ap.parse_args()

    db.init_pool()
    try:
        if not auth.schema_ready():
            print("Auth jadvallari yo'q. Avval:")
            print('  psql "dbname=xtxarid user=postgres host=localhost" '
                  "-f schema_patch_auth_2.sql")
            return 1

        if a.list:
            rows = auth.accounts()
            if not rows:
                print("Hisob yo'q.")
            for u in rows:
                flag = "" if u["active"] else "  (faol emas)"
                print(f"  {u['username']:<16} {u['company_name']}{flag}")
            return 0

        if not a.username:
            ap.print_help()
            return 1

        if a.password:
            cur = db.query_one(auth.ACC_BY_NAME_SQL,
                               {"username": a.username.strip().lower()})
            if not cur:
                print(f"'{a.username}' topilmadi.")
                return 1
            auth.set_password(cur["id"], _parol(a))
            print(f"'{a.username}' paroli almashtirildi.")
            return 0

        acc = auth.create_account(a.username, a.company_name or a.username,
                                  _parol(a), email=a.email)
        print(f"Yaratildi: {acc['username']} ({acc['company_name']})")
        return 0
    except auth.AuthError as e:
        print(f"XATO: {e}")
        return 1
    finally:
        db.close_pool()


if __name__ == "__main__":
    sys.exit(main())
