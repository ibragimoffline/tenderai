# Joylashtirish — staging birinchi

**Sana:** 2026-08-31 · **Maqsad:** ishlab chiqarishga **faqat staging'dan
o'tgan** kod tushsin

---

## 1. Arxitektura — eng kichik saqlab turiladigan shakl

```
                    Internet
                       │  HTTPS (avtomatik sertifikat)
                       v
            ┌──────────────────────┐
            │  Caddy               │  bitta konfiguratsiya fayli
            │  staging.example.uz  │  → basic_auth ortida
            │  tender.example.uz   │
            └──────┬───────────────┘
       /api/*      │      /  (statik)
                   │
      ┌────────────┴────────────┐        ┌──────────────────────┐
      │ uvicorn 127.0.0.1:8000  │        │ frontend/dist        │
      │ tenderai-api@production │        │ (npm run build)      │
      │ Restart=always          │        └──────────────────────┘
      └────────────┬────────────┘
                   │
      ┌────────────┴────────────┐   ┌──────────────────────────────┐
      │ PostgreSQL + pgvector   │   │ systemd timer'lar            │
      │ rol: tai_app (DDL yo'q) │   │  etl@          soatiga 1     │
      └─────────────────────────┘   │  backup@       har kuni 02:30│
                                    │  restore-test@ yakshanba 04:00│
                                    └──────────────────────────────┘
```

### Nega shunday

| Qaror | Sabab |
|---|---|
| **systemd**, Docker emas | Bitta VPS, bitta ilova. Konteyner qatlami bu yerda foyda bermay, `pgvector`, model keshi (~470 MB) va GPU'siz CPU ip sozlamalari uchun qo'shimcha murakkablik qo'shardi. |
| **Caddy**, nginx+certbot emas | HTTPS sertifikati avtomatik olinadi va yangilanadi. nginx bir xil natijaga ikkita harakatlanuvchi qism bilan yetadi. |
| **Shablon birlik** (`@`) | Staging va production uchun ikkita deyarli bir xil fayl — ular ajralib ketishining eng qisqa yo'li. |
| **systemd timer**, cron emas | Odam kirmagan bo'lsa ham ishlaydi; `Persistent=true` o'tkazib yuborilgan yurishni bajaradi; jurnal `journalctl` da. |
| **`current` simvolik havolasi** | Orqaga qaytarish bitta atomar amal (`ln -sfn`) — "yarmi eski, yarmi yangi" holati yuzaga kelmaydi. |

---

## 2. Bir marta: serverni tayyorlash

```bash
# Talablar: Debian/Ubuntu, Python 3.11+, Node 20+, PostgreSQL 16+, Caddy, git
sudo apt install -y python3-venv postgresql postgresql-contrib caddy git curl

# Repozitoriyani serverga oling (bare repo — push shu yerga)
sudo -u tenderai git init --bare /opt/tenderai/repo.git   # bootstrap.sh o'zi qiladi

# Katalog, rol, systemd birliklari, sudo qoidalari
sudo deploy/bin/bootstrap.sh staging
sudo deploy/bin/bootstrap.sh production
```

`bootstrap.sh` **sir yaratmaydi va so'ramaydi**. U faqat tuzilmani
qo'yadi va `/etc/tenderai/<muhit>.env` ni namunadan nusxalaydi
(`0640`, `root:tenderai`).

---

## 3. Sirlar

**Repozitoriyaga hech qachon tushmaydi.** `.gitignore` da
`deploy/env/*.env` chetlatilgan, faqat `*.env.example` kuzatiladi;
`_tests/deploy_test.py` buni har yurishda tekshiradi.

```bash
sudo -e /etc/tenderai/staging.env      # qiymatlarni to'ldiring
sudo chmod 0640 /etc/tenderai/staging.env
sudo chown root:tenderai /etc/tenderai/staging.env
```

**Majburiy:** `APP_PUBLIC_URL`, `XT_DB_DSN`, `XT_DB_DSN_OWNER`.

---

## 4. Baza

```sql
CREATE DATABASE tenderai_staging;
\c tenderai_staging
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
```

Migratsiyalar **egasi** roli bilan yuriladi (`XT_DB_DSN_OWNER`), ilova
esa **eng kam huquqli** `tai_app` bilan (`schema_patch_huquq.sql`,
`docs/xavfsizlik.md` §4):

```sql
CREATE ROLE tai_service LOGIN PASSWORD '<kuchli tasodifiy parol>';
GRANT tai_app TO tai_service;
```

`tai_app` da **DDL huquqi ataylab yo'q** — ilova sxemani o'zgartira
olmasligi kerak.

---

## 5. Joylashtirish

```bash
# 0) SOZLAMA TEKSHIRUVI — namunadan qolgan qiymatlarni ko'rsatadi
deploy/bin/oldindan-tekshir.sh staging

# 1) STAGING — har doim birinchi
git push server main:refs/heads/main          # yoki: git push server v1.2.3
deploy/bin/deploy.sh staging v1.2.3

# 2) Tekshiring: interfeys, chat, ETL
journalctl -u tenderai-api@staging -f
systemctl list-timers 'tenderai-*'

# 3) PRODUCTION — faqat AYNAN SHU ref staging'da o'tgan bo'lsa
deploy/bin/deploy.sh production v1.2.3
```

`deploy.sh production` **staging tasdig'isiz ishlamaydi**:
`/opt/tenderai/staging/.verified` faylida saqlangan ref bilan
solishtiriladi va **boshqa ref bo'lsa to'xtaydi**. Tasdiqni staging
joylashtiruvi **sog'liq tekshiruvidan o'tgach** o'zi yozadi.

### Joylashtirish qadamlari

0. **Sozlama tekshiruvi** (`oldindan-tekshir.sh`) — to'ldirilmagan
   qiymat bo'lsa **hech narsa qilinmasdan** to'xtaydi (§5b)
1. `git archive` → yangi reliz katalogi (`releases/<vaqt>-<ref>`)
2. `python -m venv` + `pip install -r requirements-api.txt`
3. **Muhit fayli o'qiladi** (`/etc/tenderai/<muhit>.env`) va
   `APP_ENV` beriladi — **qurilmadan oldin**, chunki frontend
   qurilmasi ham muhit qiymatlariga muhtoj (§10)
4. `frontend/.env.production` yoziladi → `npm ci && npm run build`
   → `frontend/dist`, so'ng **qurilmada mahalliy manzil bor-yo'qligi
   tekshiriladi** (topilsa to'xtaydi)
5. **Migratsiya** (egasi roli bilan)
6. `ln -sfn` → `current` (**atomar**)
7. `systemctl restart tenderai-api@<muhit>` + timer'lar
8. **Sog'liq tekshiruvi** — o'tmasa **avtomatik orqaga qaytariladi**
9. Eski relizlar: oxirgi 5 tasi qoladi

---

## 5b. Sozlama tekshiruvi — namunadan qolgan qiymatlar

**O'lchangan bo'shliq (2026-09-03).** `bootstrap.sh` muhit faylini
**namunadan** nusxalaydi va shu holda qoldiradi. Serverda
`password=REPLACE`, `example.uz` va namunaviy bcrypt xeshi bilan
turgan sozlama **butunlay normal** ko'rinadi — hech narsa uni
"to'ldirilmagan" deb belgilamaydi.

Ular ilgari **kech** yoki **umuman** ko'rinmasdi:

| Qiymat | Ilgari qachon ko'rinardi |
|---|---|
| `password=REPLACE` | 5-qadamda (migratsiya) — `venv` va frontend qurilgandan **keyin**, ~4-5 daqiqa |
| `example.uz` (`APP_PUBLIC_URL`) | **HECH QACHON.** Joylashtirish o'tardi, havolalar mavjud bo'lmagan domenga ketaverardi |
| Namunaviy bcrypt xeshi | Caddy qayta yuklanganda — **HTTPS ikkala domen uchun ham o'lardi** |
| `API_PORT` ≠ Caddy porti | Ishlaganда: Caddy **502**, xizmat esa **sog'lom** ko'rinardi |

```bash
deploy/bin/oldindan-tekshir.sh production
```

`deploy.sh` uni **birinchi qadamda** chaqiradi — arxiv ochilishidan
ham oldin. To'siq bo'lsa **hech narsa yaratilmaydi**.

### Uch daraja

| Daraja | Ma'nosi | Joylashtirish |
|---|---|---|
| `TO'SIQ` | bu qiymat bilan xizmat **ishlamaydi** yoki noto'g'ri ishlaydi | **to'xtaydi** |
| `ogohlantirish` | xizmat ishlaydi, **himoya qatlami yo'q** | davom etadi |
| `tekshirilmadi` | **o'lchab bo'lmadi** (asbob yo'q) | davom etadi |

Uchinchisi `production_gate.py` dagi `BLOKLANGAN` bilan **ayni
mantiq**: o'lchay olmaslik "o'tdi" **emas**. Caddy hali
o'rnatilmagan bo'lsa port mosligi haqida **jim qolmaydi** —
"tekshirilmadi" deb yoziladi, "port mos" degan yolg'on xulosa
chiqmaydi.

**Birinchi to'siqda to'xtamaydi:** operator hamma bo'shliqni **bir
yurishda** ko'rsin. **Sir chop etmaydi** — faqat kalit nomlari
(chiqish jurnalga tushadi).

### Nima tekshiriladi

1. **Tirnoq** — bo'shliqli qiymat tirnoqsiz bo'lsa `systemd` butun
   qatorni oladi, shell esa birinchi bo'shliqda **kesadi** (§13.1).
   O'sha safar faqat `XT_DB_DSN` tuzatilgandi; endi tekshiruv
   **har qanday** qiymatga tegadi.
2. **Huquq** — 0640 dan ochiq bo'lsa **ogohlantirish** (xizmat
   ishlayveradi, shuning uchun to'siq emas).
3. **Majburiy qiymatlar** — `APP_ENV` mosligi, `APP_PUBLIC_URL`
   (HTTPS, mahalliy emas, namunaviy emas), ikkala DSN, `VITE_*`
   nisbiyligi, production uchun `API_DOCS=0`,
   `AUTH_COOKIE_SECURE=1`, `TRUST_PROXY=1`. Ikkala DSN **ayni**
   bo'lsa to'siq: ilova DDL huquqi bilan ishlardi.
4. **Bazaga ulanish** — `psql` bilan **haqiqatan** ulanadi va
   `pgvector` borligini tekshiradi. Noto'g'ri host yoki `pg_hba`
   faqat shunda ko'rinadi.
5. **Caddy** — namunaviy domen/xesh, `APP_PUBLIC_URL` uchun sayt
   bloki bor-yo'qligi, **port mosligi**, staging'da `basic_auth`.
6. **Himoya qatlamlari** — zaxira katalogi (`backup.sh` ishlatadigan
   **aynan** `${BACKUP_DIR}/<muhit>`, ota-katalog emas),
   `BACKUP_REMOTE_CMD`, ogohlantirish kanali, `AI_PAID_ENABLED`.

### Mashq qilindi

`_tests/deploy_test.py` 17-bo'limi skriptni **yurgizadi**, o'qimaydi:
xom namuna (rad etiladi va **nima** to'ldirilmagani nomma-nom
ko'rsatiladi), to'ldirilgan sozlama (**0 to'siq**), tirnoqsiz DSN,
port nomuvofiqligi, `basic_auth` siz staging va Caddyfile yo'qligi.
`deploy.sh` uni `git archive` dan **oldin** chaqirishi ham
qulflangan.

---

## 6. Sog'liq, tayyorlik, ETL yangiligi

To'rt tekshiruv **ataylab ajratilgan** — ular boshqa-boshqa narsani
o'lchaydi:

| Endpoint | Nima | Muvaffaqiyatsizlik |
|---|---|---|
| `/health` | Jarayon javob beryaptimi (+ baza) | Xizmat o'lgan |
| `/ready` | Baza **va migratsiya** holati | **503** — proksi trafik yubormaydi |
| `/freshness` | ETL ma'lumoti qancha eski | Ogohlantirish |
| `psql` | Baza to'g'ridan-to'g'ri | Ulanish yo'q |

Ularni bittaga qo'shish "**tirik = ishlayapti**" degan yolg'on
berardi: jarayon ko'tarilgan, lekin migratsiya qo'llanmagan holat
**haqiqiy** va u faqat `/ready` da ko'rinadi.

`/ready` **ochiq** (proksi va systemd token ushlab turolmaydi),
lekin javobi **tafsilotsiz**: faqat `ok | ogohlantirish | xato`.
Sabablar server jurnaliga yoziladi.

```bash
deploy/bin/health-check.sh staging
curl -s https://staging.example.uz/api/ready | jq
```

---

## 7. Orqaga qaytarish

```bash
deploy/bin/rollback.sh production --royxat     # mavjud relizlar
deploy/bin/rollback.sh production              # oldingisiga
deploy/bin/rollback.sh production 20260831-...-v1_2_2
```

**Baza migratsiyasi qaytarilmaydi** va bu ataylab:

- Migratsiyalar **qo'shimcha** (additive): yangi ustun eski kodga
  xalaqit bermaydi — eski kod ularni bilmaydi, xolos.
- Avtomatik `down` skript **ma'lumot yo'qotishning eng qisqa yo'li**
  bo'lardi va u aynan falokat paytida ishga tushardi.
- Migratsiya haqiqatan buzuvchi bo'lsa — **zaxiradan** tiklanadi, va
  bu yo'l **har hafta mashq qilinadi**.

---

## 8. Zaxira va tiklash

```bash
systemctl start tenderai-backup@production          # qo'lda
systemctl start tenderai-restore-test@production    # mashq
journalctl -u tenderai-restore-test@production -n 50
```

**Zaxira o'zi yetarli emas.** `backup.sh` uch narsa qiladi: dump
oladi, **darhol `pg_restore --list` bilan ochilishini tekshiradi**
(buzuq faylni haftalab saqlab yurmaslik uchun), va SHA-256 yozadi.
Jadval soni 10 dan kam bo'lsa dump **o'chiriladi** — shubhali.

**Sinalmagan zaxira — zaxira emas.** `restore-test.sh` har hafta:

1. eng oxirgi zaxirani oladi va SHA-256 ni tekshiradi;
2. **vaqtinchalik** bazaga tiklaydi (nom ishlab chiqarish bazasiga
   teng bo'lsa **to'xtaydi**);
3. jadval soni, `tender`/`doc_chunk` qatorlari, migratsiya jurnali va
   **pgvector kengaytmasi** tiklanganini tekshiradi;
4. **tiklash vaqtini o'lchaydi** — bu **RTO** uchun haqiqiy raqam,
   taxmin emas;
5. vaqtinchalik bazani tashlaydi.

> **Hali o'lchanmagan:** RTO raqami faqat mashq birinchi marta
> yurgandan keyin ma'lum bo'ladi. Bu yerda taxminiy raqam
> yozilmaydi.

### Yuklangan fayllar — **baza yolg'iz yetarli emas**

`pg_dump` faqat bazani oladi. Foydalanuvchi yuklagan hujjat esa
**diskda** (`UPLOAD_ROOT`) va bazada faqat kalit saqlanadi. Ikkisi
ajralib qolsa tizim eng yomon shaklda buziladi: interfeys hujjatni
"bor" deb ko'rsatadi, foydalanuvchi bosadi va **fayl topilmaydi** —
ya'ni yo'qotish faqat bosilganda bilinadi.

Shuning uchun `backup.sh` **ikkinchi arxiv** yasaydi:

```
tenderai-<muhit>-<stamp>.dump                 baza
tenderai-<muhit>-<stamp>-fayllar.tar.gz       yuklangan fayllar
```

Ikkalasi ham `.sha256` bilan va ikkalasi ham `BACKUP_REMOTE_CMD`
orqali uzoqqa ketadi.

**Bo'sh arxiv jim o'tmaydi.** `backup.sh` bazadagi faol `yuklama`
soni bilan arxivdagi fayl sonini solishtiradi: bazada fayl bor-u
arxiv bo'sh bo'lsa — **xato bilan to'xtaydi**. Aks holda noto'g'ri
`UPLOAD_ROOT` bilan zaxira yashil ko'rinardi.

`restore-test.sh` mashqda fayl arxivini ham tekshiradi: mavjudligi,
SHA-256 va bo'sh emasligi.

> **`UPLOAD_ROOT` reliz ichida bo'lmasin.** `deploy.sh` har relizda
> **yangi katalog** yasaydi; yo'l reliz ichida bo'lsa fayllar keyingi
> joylashtiruvda ko'rinmay qoladi. Ishlab chiqarishda:
> `UPLOAD_ROOT=/var/lib/tenderai/uploads`. `backup.sh` yo'l reliz
> ichida ekanini sezsa **ogohlantiradi**.

Batafsil: [`docs/fayl_yuklash.md`](fayl_yuklash.md).


---

## 9. Jurnal

```bash
journalctl -u tenderai-api@production -f
journalctl -u tenderai-etl@production --since today
journalctl -u tenderai-api@production -o cat | jq 'select(.daraja=="ERROR")'
```

`LOG_FORMAT=json` — bir qator = bir JSON obyekt. Har so'rovda
`sorov_id` bor va u javobning `X-Request-Id` sarlavhasida ham
qaytadi: foydalanuvchi xato haqida aytganda o'sha id bo'yicha
jurnalni topish mumkin.

**Sirlar niqoblanadi** — `password`, `token`, `api_key`, `dsn`,
`cookie` nomli maydonlar `***` bilan almashtiriladi (nom bo'yicha,
mazmun bo'yicha emas: nom bo'yicha aniq, mazmun bo'yicha ehtimolli).

`/health` va `/ready` so'rovlari **yozilmaydi** (faqat xato bo'lganda)
— ular har 30 soniyada keladi va haqiqiy hodisalarni ko'mib
tashlardi.

---

## 10. Ommaviy havolalar `localhost` bo'lmasin

**Yagona manba: `api/ommaviy_url.py`.** Qabul qiluvchi bosadigan
har qanday havola shu moduldan quriladi.

### Muhit o'zgaruvchisi

| Nom | Holat |
|---|---|
| `APP_PUBLIC_URL` | **asosiy** |
| `PUBLIC_BASE_URL` | eski (ishlaydi, ogohlantirish yozadi) |

Ikkalasi ham berilib, qiymatlari **boshqa** bo'lsa — xizmat ishga
tushmaydi. "Qaysi biri to'g'ri" degan savolga taxmin bilan javob
berish ikkita haqiqat manbai demak.

`localhost` ga ruxsat **faqat** `APP_ENV=dev` da. Alohida "ruxsat
bayrog'i" ataylab qo'shilmadi: uni ishlab chiqarishga ham yozib
qo'yish mumkin bo'lardi va qo'riqchi o'z-o'zini o'chirardi.

### To'rt qatlam

1. **Ishga tushish** — `ommaviy_url.ishga_tushishda_tekshir()`
   `api/main.py` dagi `lifespan` da va `notify_new.py` da (ETL
   yuborish yo'li). `staging`/`production` da manzil berilmagan
   yoki mahalliy bo'lsa **xizmat ko'tarilmaydi**.
2. **Tanlash** — bazadagi ijarachi qiymati mahalliy bo'lsa va
   muhitda haqiqiysi bo'lsa, **muhit yutadi** (ogohlantirish bilan).
3. **Qurish** — `ommaviy_url.havola()` yagona quruvchi. Email
   matni, email HTML va Telegram uchalasi shundan o'tadi, ya'ni
   yangi kanal qo'shilganda tekshiruvni unutib bo'lmaydi.
4. **Yozish** — sozlama shaklida **aniq berilgan** mahalliy qiymat
   `dev` dan boshqa muhitda rad etiladi. Jimgina almashtirilmaydi:
   "saqladim" deb ko'rsatib boshqa narsani saqlash yolg'on bo'lardi.

### Frontend qurilmasi (o'lchangan nosozlik)

Reliz `git archive` bilan yasaladi, `frontend/.env` esa
kuzatilmagan fayl — u **relizga tushmaydi**. Shu sababli qurilma
`VITE_API_BASE` siz yurardi va zaxira qiymat singib qolardi:

```
dist/assets/index-*.js:  localhost:8000  x1   butun API
dist/assets/index-*.js:  localhost:5173  x3   sozlama shakli
```

Ya'ni ishlab chiqarish sahifasidagi **har so'rov** foydalanuvchi
brauzerida `localhost:8000` ga ketardi va qurilma muvaffaqiyatli
tugardi.

Endi uch qatlam:

1. Manbada qotirilgan mahalliy manzil **yo'q** (`VITE_API_BASE`
   zaxirasi `/api` — same-origin, cookie shuni talab qiladi).
2. `deploy.sh` muhit faylidan `frontend/.env.production` ni
   **yozadi** va `APP_ENV` ni beradi.
3. `vite.config.ts` dagi qo'rovul plagin `staging`/`production` da
   sozlama yaroqsiz bo'lsa **qurilmani to'xtatadi**; `deploy.sh`
   esa qurilma natijasini `grep` bilan tekshiradi.

> `VITE_*` qiymatlari ta'rifi bo'yicha brauzerga tushadi — ular
> **ommaviy**. Sir hech qachon `VITE_` prefiksi bilan berilmasin.

### Sinov

`_tests/ommaviy_url_test.py` — 96 tekshiruv (`dev`/`staging`/
`production` xulqi, eski nom va ziddiyat, uchala kanalning ayni
havolasi, frontend manbasi va qurilma qo'rovuli).

---

## 11. Kundalik amallar

```bash
systemctl status tenderai-api@production
systemctl list-timers 'tenderai-*'
systemctl restart tenderai-api@production

# ETL ni qo'lda yurgizish
systemctl start tenderai-etl@production

# Migratsiya holati (egasi roli bilan)
sudo -u tenderai /opt/tenderai/production/current/.venv/bin/python \
     /opt/tenderai/production/current/migratsiya.py --holat --dsn "$XT_DB_DSN_OWNER"
```

---

## 12. Hali bajarilmagan (ochiq)

1. **Server hali yo'q.** Bu yerdagi hamma narsa repozitoriyada
   tayyor va sinovdan o'tgan (`_tests/deploy_test.py` 103/103), lekin
   **haqiqiy mashinada yurgizilmagan**. Birinchi `bootstrap.sh` dan
   keyin domen, sertifikat va RTO raqamlari aniqlashadi.
2. **Domenlar namunaviy** (`staging.example.uz`,
   `tender.example.uz`) — `Caddyfile` da almashtirilishi kerak.
3. **Staging `basic_auth` xeshi namunaviy** — `caddy hash-password`
   bilan o'zingiznikini qo'ying.
4. **Zaxira faqat mahalliy diskda.** Tashqi nusxa (S3 yoki boshqa
   mashina) yo'q — disk yo'qolsa zaxira ham yo'qoladi.
5. **Monitoring/ogohlantirish yo'q.** `systemd` xizmatni qayta
   ko'taradi, lekin buni **hech kim bilmaydi**. `OnFailure=` bilan
   xabar yuborish keyingi qadam.

---

## 12b. TASHQI NUSXA — bitta disk yetarli emas (O-2)

`backup.sh` zaxirani **mahalliy** diskka yozadi. Disk yo'qolsa
(yoki shifrlovchi dastur tegsa) **zaxira ham u bilan ketadi**.

`BACKUP_REMOTE_CMD` — **buyruq shabloni**, manzil emas:

```bash
BACKUP_REMOTE_CMD='rclone copy {fayl} uzoq:tenderai/'
BACKUP_REMOTE_CMD='aws s3 cp {fayl} s3://chelak/tenderai/'
BACKUP_REMOTE_CMD='rsync -a {fayl} zaxira@host:/srv/tenderai/'
```

**Nega shablon, manzil emas:** nusxalash usuli har joyda boshqacha.
Manzilga qarab usulni taxmin qilish **noto'g'ri buyruqni jimgina
yurgizardi**.

| Holat | Xulq |
|---|---|
| Sozlanmagan | **ogohlantirish** yoziladi, zaxira davom etadi |
| Sozlangan, muvaffaqiyatli | dump **va** `.sha256` yuboriladi |
| Sozlangan, **yiqildi** | skript **exit 1** — "zaxira bor" yolg'on xulosa bo'lmasin |

**Tartib muhim:** tashqi nusxa **tozalashdan oldin**. Aks holda
mahalliy fayl o'chirilib, uzoqqa hech narsa ketmagan bo'lishi
mumkin edi.

Uchala yo'l ham **mashq qilib ko'rildi** (2026-09-01).

> **Halol cheklov:** tashqi nusxaning tiklanishi hali sinalmagan.
> `restore-test.sh` **mahalliy** fayldan tiklaydi; uzoqdagi nusxa
> o'qilishini alohida tekshirish kerak.

---

## 12c. NOSOZLIK OGOHLANTIRISHI (O-3)

`systemd` xizmatni qayta ko'taradi, ETL taymeri qayta uradi —
**lekin buni hech kim bilmasdi**. `/ready` bor edi, uni
**so'raydigan narsa yo'q** edi.

### Ikki qatlam, ikki xil nosozlik

| Qatlam | Nimani ushlaydi | Qanday |
|---|---|---|
| **Krash** | xizmat yiqildi (chiqish kodi ≠ 0) | `OnFailure=` har birlikda |
| **Sog'liq** | xizmat ko'tarilgan, **lekin sog'lom emas** | `tenderai-health@.timer`, har 10 daq |

Ikkinchisi muhim: migratsiya qo'llanmagan yoki baza yetib
bo'lmayotgan xizmat uchun **`systemd` da hammasi joyida** ko'rinadi.

### Kanal

**Mavjud kanal ishlatiladi, yangisi qurilmaydi** — loyihada
allaqachon Telegram boti va SMTP bor.

```bash
ALERT_TELEGRAM_CHAT=   # bot tokeni TELEGRAM_BOT_TOKEN dan
ALERT_EMAIL=           # SMTP rekvizitlari yuqoridan
```

**Operator kanali mijoz kanalidan alohida.** Bildirishnoma
obunachilari — mijozlar; nosozlik xabari operatorga ketishi kerak.
Aralashtirish mijozga texnik xabar yuborardi.

**Ikkalasi ham bo'sh bo'lsa** `ogohlantir.sh` buni `journald` ga
**baland ovozda** yozadi: *"OGOHLANTIRISH HECH QAYERGA
YUBORILMADI"*. "Nosozlik bor, xabar yo'q" holati ko'rinmasdan
qolmasin.

### Ogohlantirish asl nosozlikni yashirmasin

`ogohlantir.sh` **har doim 0 qaytaradi** va `Restart=no` — u
`OnFailure=` dan chaqiriladi, uning yiqilishi yoki takrorlanishi
asl nosozlikning ustiga ikkinchi shovqin qo'shardi.

### Mashq qilindi (2026-09-01)

| Holat | Natija |
|---|---|
| Kanal sozlanmagan | `journald` ga "HECH QAYERGA YUBORILMADI", exit 0 |
| Email sozlangan | **soxta SMTP serveri xabarni qabul qildi** — mavzu, oluvchi va matn tekshirildi |
| Ikki argument shakli | `mashq:birlik` ham, `mashq birlik` ham ishlaydi |

```bash
export TENDERAI_ENVFILE=/tmp/mashq.env
bash deploy/bin/ogohlantir.sh "production:tenderai-api@production.service"
```

> **Halol cheklov:** `OnFailure=` va taymerlar **systemd da
> sinalmagan** — bu muhitda systemd yo'q. Skriptning o'zi va
> email yuborish yo'li mashq qilindi.

---

## 13. MASHQ — skriptlar HAQIQATAN yurgizildi (B-1)

**O'lchov: 2026-09-01.** Joylashtirish skriptlari shu paytgacha
**hech qachon, hech qayerda bajarilmagan** edi — ular faqat
`deploy_test` da **matn** sifatida tekshirilardi. Mashq
o'tkazildi va u **birinchi qadamdayoq haqiqiy nuqson topdi**.

### 13.1 Topilgan nuqson: bitta fayl, ikki parser

`XT_DB_DSN` muhit namunasida **tirnoqsiz** edi:

```
XT_DB_DSN=dbname=tenderai_production user=tai_service password=REPLACE host=127.0.0.1 port=5432
```

| O'quvchi | Natija |
|---|---|
| systemd `EnvironmentFile=` | butun qatorni oladi — **to'g'ri** |
| shell `. envfile` | birinchi bo'shliqda **kesadi** |

Ya'ni API xizmati to'g'ri DSN olardi, `backup.sh` /
`restore-test.sh` / `deploy.sh` esa `dbname=tenderai_production`
ni — **user, parol va host yo'qolgan holda**. Qolgani
(`user=...`, `password=...`) shellda **o'zgaruvchi tayinlash**
bo'lib ketardi, ya'ni **xato ham bermasdi**.

Tuzatildi: qiymatlar tirnoqqa olindi. `deploy_test` buni
`shlex` bilan (POSIX so'z ajratish qoidasi) qo'riqlaydi.

### 13.2 Topilgan nuqson: `XT_DB_DSN_OWNER` namunada YO'Q edi

`deploy.sh` va `restore-test.sh` uni **talab qiladi** (`:?`) va
`docs/deploy.md` §3 uni **majburiy** deb yozadi — lekin
namunada u yo'q edi. Namunaga qarab tayyorlangan server
birinchi joylashtirishda to'xtardi. Qo'shildi.

### 13.3 O'lchangan raqamlar

Mashq **haqiqiy 1.5 GB baza** ustida yurgizildi:

| Amal | Natija |
|---|---|
| `backup.sh` | **5 daq 28 s** · dump **440 MB** · 74 jadval · SHA-256 yozildi |
| `restore-test.sh` | **RTO = 405 s (6 daq 45 s)** |
| Tiklashdan keyin tekshiruv | jadval 53 · tender 3 608 · bo'lak 189 787 · migratsiya 67 · pgvector **bor** |
| Vaqtinchalik baza | **tashlandi** (nom qo'riqchisi ishladi) |

> **RTO endi o'lchangan raqam** — O-1 shu bilan yopildi. Taxminiy
> qiymat hech qachon yozilmagan edi va bu to'g'ri edi.

### 13.4 Qanday mashq qilinadi

Skriptlar muhit faylini `/etc/tenderai/<muhit>.env` dan o'qiydi.
Mashq uchun yo'l **almashtiriladi**:

```bash
export TENDERAI_ENVFILE=/tmp/mashq.env
export PATH="/usr/lib/postgresql/18/bin:$PATH"   # Windows'da PostgreSQL/18/bin
bash deploy/bin/backup.sh mashq
bash deploy/bin/restore-test.sh mashq
```

`mashq.env` da `XT_DB_DSN`, `XT_DB_DSN_OWNER`, `BACKUP_DIR`
bo'lishi yetadi. `restore-test.sh` **vaqtinchalik** bazaga
tiklaydi va nomi asosiy baza bilan bir xil bo'lsa **to'xtaydi**.

### 13.5 MASHQ HOLATI (2026-09-02 da yangilandi)

| Qism | Holat |
|---|---|
| `backup.sh` | **MASHQ QILINDI** (§13.4) — 5 daq 28 s, 440 MB |
| `restore-test.sh` | **MASHQ QILINDI** — RTO 405 s |
| `health-check.sh` | **MASHQ QILINDI** — 4 ssenariy, quyida |
| `rollback.sh` | **MASHQ QILINDI** — 6 ssenariy, quyida |
| `deploy.sh` darvozasi | **MASHQ QILINDI** — 3 ssenariy |
| `deploy.sh` to'liq | HALI EMAS — `venv`, `npm ci`, migratsiya, `systemd` kerak |
| Caddy / HTTPS | HALI EMAS — domen va sertifikat kerak |
| systemd taymerlar | HALI EMAS — Linux kerak |

#### Mashq qanday qilindi

Skriptlar **o'zgartirilmagan holda** yurgizildi. Uchta narsa
almashtirildi va uchalasi ham SKRIPTDAN TASHQARIDA:

| Almashtirildi | Nima bilan | Nega |
|---|---|---|
| `/opt/tenderai/<muhit>` | `TENDERAI_ILDIZ` | yo'l qotirilgan bo'lsa mashq umuman mumkin emas |
| `sudo systemctl` | PATH dagi shim, chaqiruvlar YOZILADI | mashqda haqiqiy xizmat yo'q |
| `ln -s` (Windows) | NTFS junction shimi | MSYS `ln -s` imtiyozsiz JIMGINA katalog NUSXASI qoldiradi |

Oxirgisi muhim: shimsiz `current` simvolik havola bo'lmasdi va
**atomar almashtirish mashqi SOXTA** bo'lardi — skript "qaytardim"
deb yozardi, aslida hech narsa almashmasdi.

#### Topilgan nuqsonlar

Beshtasi ham `grep` bilan KO'RINMASDI. Ular faqat skript
YURGIZILGANDA chiqdi:

| # | Nuqson | Oqibati |
|---|---|---|
| 1 | tiriklik sikli 210 s gacha, birlikda `TimeoutStartSec=120` | xizmat yiqilganda tekshiruvning O'ZI o'ldirilardi; sabab yo'qolardi |
| 2 | `psql` byudjetsiz | baza qora tuynuk bo'lsa xuddi shu holat |
| 3 | uzilishda javob kodi `000000` | operator jurnalda BUZUQ kod ko'rardi |
| 4 | `--royxat` da `*` belgisi yo'qolardi | uzilish paytida QAYSI reliz tirikligi noma'lum |
| 5 | `rollback.sh` avval almashtirib, KEYIN tekshirardi | yarim relizga qaytarish UZILISHNI O'ZI keltirardi |

5-nuqson eng og'iri va u **tasodifan** topildi: `deploy.sh`
mashqda yiqilib, bo'sh reliz katalogi qoldirdi. O'sha katalog
`--royxat` da ENG YANGI reliz bo'lib turardi — ya'ni yiqilgan
joylashtiruvdan keyin tiklanayotgan operatorga aynan eng yaroqsiz
nishon ko'rsatilardi. Unga qaytarilsa:

```
current -> bo'sh katalog        xizmat O'LIK
health-check.sh                 TOPILMADI (127)
chiqish                         "qo'lda qarang", kod 1
```

Endi ikkala tomon ham yopildi: `deploy.sh` yiqilsa o'z yarim
relizini o'chiradi (`trap`), `rollback.sh` esa hedefni
ALMASHTIRISHDAN OLDIN tekshiradi va `current` ga tegmaydi.
Operator qamalib qolmasin uchun `--majburiy` chiqish yo'li bor.

#### Vaqt byudjeti

`health-check.sh` endi MUDDAT bilan cheklangan (takror soni bilan
emas — `curl` bloklansa "30 ta urinish" istalgancha cho'ziladi):

```
tiriklik   HEALTH_WAIT_SEC        45 s
tayyorlik  --max-time             10 s
ETL        --max-time             15 s
baza       PGCONNECT_TIMEOUT       5 s
-------------------------------------
jami                              75 s  <  TimeoutStartSec 120 s
```

O'LCHANDI: xizmat butunlay yo'q bo'lganda **129 s -> 53 s**.
Arifmetika `_tests/deploy_test.py` 16-bo'limida QULFLANGAN —
birlikdagi `TimeoutStartSec` kamaytirilsa sinov yiqiladi.

#### Mashq endi TAKRORLANADI

`_tests/deploy_test.py` 16-bo'limi yuqoridagi ssenariylarni
skriptlarni HAQIQATAN yurgizib tekshiradi (soxta API, soxta
`systemctl`, vaqtinchalik reliz daraxti). 1-15 bo'limlar
`"satr" in fayl` shaklida edi va ular beshta nuqsonning HECH
BIRINI ko'rmagan edi.

Mashq muhiti topilmasa (repozitoriyani ko'radigan `bash` yo'q)
sinov **YIQILADI**, jimgina o'tmaydi: mashq qilib bo'lmasligi ham
natija.

Ya'ni **B-1 hali ham yopilmadi**: `deploy.sh` ning qurish qismi,
Caddy va systemd haqiqiy Linux mashinasini talab qiladi.
