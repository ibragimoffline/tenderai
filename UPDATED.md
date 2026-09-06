# Tender AI — BAJARILGAN ISHLAR

**Loyiha:** O'zbekiston davlat xaridlari agregatori va broker yordamchisi
**Holat sanasi:** 2026-08-30 · **Tarmoq:** `main` · **Asos:** `тз.docx` (PRD/TZ v0.1, MVP), `REJA.md`, `REJA_UX.md`

Bu fayl — **nima qurilgani** ro'yxati va loyihaning YAGONA bajarilgan-ishlar
jurnali. Reja hujjatlari (`REJA.md`, `REJA_UX.md`) nima qilish kerakligini
aytadi; `LOYIHA.md` tizim qanday tuzilganini tushuntiradi; bu yerda esa AYNAN
NIMA ISHLAYAPTI, qayerda va qanday tekshirilgani yozilgan.

**Bu hujjatning qoidasi:** har raqam O'LCHANGAN bo'lishi shart. Taxminiy son
yozilsa, yoniga "taxminiy" deb belgilanadi. O'lchanmagan narsa "0" deb ham,
"ishlaydi" deb ham yozilmaydi — u "ma'lum bo'shliqlar" bo'limiga tushadi.

> Quyidagi barcha raqamlar 2026-08-30 da ishlaydigan bazada va kodda
> o'lchandi (`_tests/*_test.py --offline`, to'g'ridan-to'g'ri SQL sanoq).

---

## Mundarija

| § | Bo'lim |
|---|---|
| 0 | [Bir qarashda](#0-bir-qarashda) |
| 1 | [Ma'lumot yig'ish (ETL)](#1-malumot-yigish-etl--p0-1) |
| 2 | [Hujjat matni](#2-hujjat-matni--p0-2) |
| 3 | [Kimlik va ko'p-ijarachilik (auth)](#3-kimlik-va-kop-ijarachilik-auth) |
| 4 | [Katalog va ombor](#4-katalog-va-ombor--p0-4-p0-6) |
| 5 | [Kodlash — rasmiy tasniflagich bo'yicha moslashtirish](#5-kodlash--rasmiy-tasniflagich-boyicha-moslashtirish) |
| 6 | [Moslashtirish (matching)](#6-moslashtirish-matching) |
| 7 | [Tender talablari (requirement)](#7-tender-talablari-requirement) |
| 8 | [Malaka tekshiruvi (qualification)](#8-malaka-tekshiruvi-qualification) |
| 9 | [Brokerga yo'naltirish (routing)](#9-brokerga-yonaltirish-routing) |
| 10 | [AI qatlami va RAG/chat](#10-ai-qatlami-va-ragchat) |
| 11 | [Narx hisobi](#11-narx-hisobi--p0-7) |
| 12 | [Hujjatlar cheklisti](#12-hujjatlar-cheklisti--p0-8) |
| 13 | [Bildirishnoma](#13-bildirishnoma--p0-10) |
| 14 | [Ko'p tillilik](#14-kop-tillilik--interfeys-va-bildirishnoma) |
| 15 | [Interfeys](#15-interfeys) |
| 16 | [Sifat va nazorat](#16-sifat-va-nazorat) |
| 17 | [Ishga tushirish](#17-ishga-tushirish) |
| 18 | [Ma'lum bo'shliqlar va keyingi qadamlar](#18-malum-boshliqlar-va-keyingi-qadamlar) |
| 19 | [Vaqt bo'yicha yo'l xaritasi](#19-vaqt-boyicha-yol-xaritasi) |
| 20 | [Hujjatlar xaritasi](#20-hujjatlar-xaritasi) |

---

## 0. Bir qarashda

```
2 platforma → ETL (soatlik) → PostgreSQL (47 jadval) → FastAPI (94 endpoint) → React
       ↓              ↓                  ↓                      ↓                ↓
  etl_run jurnali  hujjat matni    pgvector HNSW          auth + ijarachi    3 til
       ↓              ↓            (157 266 bo'lak)        darvozasi        (uz/ru/en)
  first_seen_at   talab ajratish        ↓                      ↓
                  (8 785 talab)   RAG/chat + tool        kodlash → moslik → malaka
                                                                    ↓
                                                        yo'naltirish → broker navbati
                                                                    ↓
                                                        bildirishnoma (email + Telegram)
```

### Hajm — o'lchangan (2026-08-30)

| O'lchov | Qiymat |
|---|---|
| Manbalar | 2 ta (`xt-xarid.uz`, `etender.uzex.uz`) |
| Bazadagi tenderlar | **3 457** (uzex 2 535, xt-xarid 922) |
| Turi bo'yicha | tanlov (`selection`) 2 993, tender 464 |
| Holati bo'yicha | `expired` 2 337, `open` 847, `close` 165, `cancel` 82, boshqa 26 |
| **Hozir ochiq** (muddati o'tmagan) | **625** (uzex 469, xt-xarid 156) |
| Lotlar / pozitsiyalar | 3 475 / 9 015 |
| Tender bandlari (`tender_item`) | 11 146 |
| Hujjatlar (metadata + havola) | 10 168 |
| Matni ajratilgan hujjatlar | **2 892 `ok`**, 269 `unreadable`, 252 `unsupported`, 18 `too_large` |
| Hujjat bo'laklari (chunk) | 157 266, shundan **95 874 tasi vektorlangan** |
| Tender vektorlari | 1 134 |
| Tasniflagich vektorlari (`good_code`) | 1 173 (lug'atda 1 264 kod) |
| Kategoriya bog'lanishlari | 4 206 (lug'atda 841 kategoriya, 247 hudud) |
| Katalog mahsulotlari | 1 797, shundan **960 tasi kodlangan (53%)**, 837 ataylab kodsiz |
| Ajratilgan talablar | **8 785** (1 013 ta tenderda) |
| Yo'naltirish navbati | 260 qator, **30 tasida inson qarori** (olindi 16, rad 8, kutilsin 6) |
| Chat sessiyalari / xabarlari / tool chaqiruvlari | 123 / 245 / 134 |
| ETL yurishlari | 399 (oxirgi 7 kunda: 64 `ok`, 61 `error`, 3 `running`) |
| **API endpointlari** | **94** (49 GET, 31 POST, 9 PUT, 5 DELETE) |
| Backend modullari | **29 ta** (`api/*.py`) |
| Frontend komponentlari | **38 ta** + 16 ta `ui/` primitivi |
| Baza patchlari | **48 ta** idempotent `schema_patch_*.sql` |
| Baza obyektlari | 47 jadval + 17 ko'rinish (`v_*`) |
| Avtomatlashtirilgan sinovlar | **920 ta tekshiruv o'tadi** (15 to'plam) |
| Tarjima kalitlari | ~800 qator × 3 til |
| ETL skriptlari | 10 ta + orkestrator (`run_etl.py`) |

---

## 1. Ma'lumot yig'ish (ETL) — P0-1

**Fayllar:** `etl_tenders.py`, `etl_uzex.py`, `etl_lots.py`, `etl_details.py`,
`etl_dims.py`, `etl_categorize.py`, `etl_doc_text.py`, `etl_embed.py`,
`etl_requirement.py`, `etl_ai_summary.py`, orkestrator `run_etl.py`

| Nima | Holat |
|---|---|
| `xt-xarid.uz` — `ref_tender_public` + `ref_selection_public` | ✅ |
| `etender.uzex.uz` — `TypeId=1` (tanlov) + `TypeId=2` (tender) | ✅ |
| Lot va pozitsiyalar (`tender_lot`, `tender_good`, `tender_item`) | ✅ |
| Lug'atlar (`dim_status`, `dim_area`, `dim_category`, `dim_good_code`) | ✅ |
| Kategoriyalash (ИКПУ → kanonik teglar) | ✅ 4 206 bog'lanish |
| `first_seen_at` — aniqlash kechikishini o'lchash | ✅ |
| `etl_run` jurnali (manba, holat, topildi, yangi, xato) | ✅ 399 yurish |
| Soatlik jadval — Windows Task Scheduler (`register_task.ps1`) | ✅ ro'yxatdan o'tgan |
| Yakka nusxa qulfi (lock) va uzilgan yurishni yopish | ✅ |

**Parallellik qoidasi:** platformalar o'zaro parallel, platforma ICHIDAGI
qadamlar ketma-ket — bitta hostga parallel urilish manba rate-limitini
hurmat qilmaslik bo'lardi.

**O'lchangan vaqt:** xt-xarid 7 s · uzex `TypeId=2` 101 s · uzex `TypeId=1`
1 196 s (~21 daqiqa, ~650 yozuvning har biriga alohida `GetTrade` so'rovi).

> ⚠️ **Ma'lum nuqson:** uzex yurishlari muntazam `error` bilan tugaydi —
> "yurish tugamasdan uzildi (jarayon majburan to'xtatilgan yoki kompyuter
> uxlagan)". Oxirgi 7 kunda 61 `error` / 64 `ok`. Batafsil §18 da.

---

## 2. Hujjat matni — P0-2

**Fayl:** `etl_doc_text.py` (36 KB) · **Jadval:** `tender_document_text`

| Format | Holat |
|---|---|
| PDF (matnli) | ✅ |
| PDF (skan) | `unreadable` deb belgilanadi — TAXMIN QILINMAYDI |
| DOCX / DOC | ✅ (`.doc` uchun alohida ajratgich) |
| XLSX / XLS | ✅ |
| ZIP/RAR ichidagilar | ✅ ochiladi |
| Qo'llab-quvvatlanmaydigan | `unsupported` — jimgina tashlanmaydi |
| Juda katta | `too_large` — chegara `.env` da |

**Natija:** 2 892 hujjat matni ajratildi, 539 tasi ataylab belgilangan holatda
(`unreadable` 269, `unsupported` 252, `too_large` 18) — ya'ni **hech biri
jimgina yo'qolmaydi**.

**Bo'laklash (chunk):** `_tests/chunk_test.py` (25/25). 157 266 bo'lak,
shundan 95 874 tasi `multilingual-e5-small` bilan vektorlangan (384 o'lcham,
lokal, **pulsiz**), pgvector HNSW indeksi bilan.

---

## 3. Kimlik va ko'p-ijarachilik (auth)

**Fayl:** `api/auth.py` (25 KB) · **Sinov:** `auth_test.py` 130/130,
`multitenant_test.py` 20/20

| Nima | Holat |
|---|---|
| Kompaniya hisobi (`company_account`) — ODAM emas, KOMPANIYA kiradi | ✅ 2 hisob |
| Parol xeshi — PBKDF2-HMAC-SHA256 (stdlib, yangi bog'liqliksiz) | ✅ |
| Sessiya (`company_session`), CSRF himoyasi | ✅ |
| Kirish urinishlari jurnali (`login_attempt`) + cheklov | ✅ |
| **Global darvoza** — himoyalanmagan endpoint qoldirib bo'lmaydi | ✅ |
| `company_id_of(request)` — ijarachi ID FAQAT sessiyadan | ✅ |
| Skaner: har yangi endpoint darvozaga tushganini tekshiradi | ✅ sinovda |
| Hisob sozlamalari, parol o'zgartirish (`AccountSettings`, `PasswordPanel`) | ✅ |

**Arxitektura qarori:** hodim hisoblari bu yerda EMAS — ular ERP tushunchasi
(`erp.app_user`). Chegara simmetrik va sinov bilan qulflangan:
ERP `public.*` dan faqat O'QIYDI; Tender-AI `erp.v_tender_status` dan faqat
O'QIYDI. Ikkala tomon o'z kimligini o'zi tekshiradi, tarmoqqa chiqmaydi.

**Ko'p-ijarachilik ikki qismga aniq ajratilgan:**

| Qism | Misol | Filtr |
|---|---|---|
| **Umumiy korpus** | `tender`, `tender_good`, `dim_good_code` | Filtr QO'YILMAYDI — qo'yilsa natija bo'shab qolardi |
| **Kompaniya ma'lumoti** | `catalog_product`, `kod_qaror`, `tender_routing` | `company_id_of(request)` majburiy |

---

## 4. Katalog va ombor — P0-4, P0-6

**Fayllar:** `api/importer.py` (31 KB), `api/stock.py`, `api/erp_stock.py`
**Sinov:** `import_test.py`

| Nima | Holat |
|---|---|
| Excel/CSV import — standart shablon (nom, xususiyat, birlik, qoldiq, tannarx) | ✅ 1 797 mahsulot |
| Xato QATOR bo'yicha ajratiladi — bitta xato importni to'xtatmaydi | ✅ |
| Qator raqami = Excel'dagi HAQIQIY raqam | ✅ |
| `dry-run` bazaga umuman tegmaydi | ✅ |
| Import partiyasi (`catalog_import_batch`) — orqaga qaytarish uchun | ✅ |
| Shablon yuklab olish (`/catalog/import/template`) | ✅ |
| Ombor qoldiqlari, ERP dan qoldiq o'qish (`/tenders/{id}/stock-check`) | ✅ |
| Kompaniya hujjatlari (`company_document`) — 13 yozuv, muddat nazorati | ✅ |

**Tamoyil:** TAXMIN QILINMAYDI. Sonni ishonchli o'qib bo'lmasa — xato, "0" emas.

---

## 5. Kodlash — rasmiy tasniflagich bo'yicha moslashtirish

**Fayl:** `api/kodlash.py` (54 KB) · **Sinov:** `kodlash_test.py` 55/55 offline,
67/67 baza bilan · **Patch:** `schema_patch_goodcode*.sql`,
`schema_patch_semantik.sql`, `schema_patch_kod_qaror*.sql`

Bu — 2026-08-28..30 dagi asosiy ish. Sabab **o'lchangan**:

```
matn bo'yicha qidiruv TILGA BOG'LIQ va shu sababli yiqiladi
    "dori"                              → Сосуд Дьюара, Чай зеленый   XATO
    "дори" (transliteratsiya)           → Урна                        XATO
    "лекарственные средства препараты"  → 21.40, 86.23                TO'G'RI

kod esa TILGA BOG'LIQ EMAS
    good_code LIKE '21%'   → 63 ochiq tender, 124 pozitsiya
```

### Qurilgani

| Nima | Holat |
|---|---|
| `atama.normal()` — kanonik kalit: "Коммутаторы" == "Kommutatorlar" == "kommutator" | ✅ 72/72 |
| `kodlash.dalil()` — har kod ostidagi HAQIQIY pozitsiyalar + ochiq tender soni | ✅ |
| `kodlash.qidir()` — teskari yo'nalish: pozitsiya nomi → kod (0.05–0.11 s) | ✅ |
| `kodlash.navbat()` — kodsiz atamalar navbati, DALIL bilan (19.2 s → 9.5 s) | ✅ |
| **Qoldiqsiz toifalash** — `jami_mahsulot == toifa_yig'indisi`, sinovda tekshiriladi | ✅ 837 = 837 |
| Markazlangan vektorlar + hublik tuzatmasi (CSLS) | ✅ |
| `kod_qaror` jadvali — inson qarorlarini YOZIB OLADI | ✅ (0 qaror, §18) |
| Uch raqam AVTOMATIK yoziladi: vaqt, manba, `qidiruv_soni` | ✅ |
| `v_kod_qaror_olchov` — o'lchanmagan qatorlar o'rtachaga QO'SHILMAYDI | ✅ |
| Baza CHECK qulflari (qaror bor + kim yo'q → RAD, va h.k.) | ✅ bazada sinaldi |
| Ekran: `KodNavbat.tsx` | ✅ |
| Endpointlar: `/kod/qidir`, `/kod/qaror`, `/kod/qaror/ochish`, `/kod/qaror/olchov`, `/catalog/kod-navbat`, `/catalog/kodlash-holati` | ✅ |

### O'lchangan natija

Foydalanuvchi tasdiqlagan yadro to'plami (2026-08-28) → **960 mahsulot kodlandi**:

```
26.40  Камера видеонаблюдения, Микрофон, Аудио спикерфон
26.30  Коммутатор, Мини АТС, Веб-камера, Видеорегистратор
26.20  Ноутбук, Жесткий диск, Блок питания, Сервер
```

RAD ETILGANLAR (qamrovni oshirardi, lekin mos emas): `26.51` Дефектоскоп,
Термопара, Кульман (26 tender) · `25.72` Петля мебельная (2) · `27.32`
Кабель СИЛОВОЙ (12).

**"Sizga mos" bo'limining o'zgarishi:**

| | Ilgari | Endi |
|---|---|---|
| Mos tender | 18 | **44** |
| Ball manbai | hammasi 60 (matn) | 34 tasi **100 (kod)** + 10 matn |
| Soxta moslik | 16 dan 14 tasi | kod yo'lida 0 |

**837 mahsulot ATAYLAB kodsiz** (Кронштейн, Шкафы, Замок, Датчики...) —
"bilmayman" ni "mos" ga aylantirmaymiz. Ular `v_catalog_kodsiz` da ko'rinadi.

### Qidiruv nega MAJBURIY (o'lchov taxminni rad etdi)

"40 tadan 35 tasi taklifdan tanlanadi" degan asos noto'g'ri chiqdi: navbatning
yuqori 10 tasidan faqat 1–2 tasida ishonchli nomzod bor edi, `28.41` (Пресс
гидравлический) esa hub bo'lib qolaverdi. Broker `Кульман` yoki `Трубка
рентгеновская` degan RASMIY nomlarni tanimaydi, lekin POZITSIYA nomlarini
taniydi — shuning uchun qidiruv korpus pozitsiyalari bo'yicha ishlaydi:

```
"kabel" → 27.32  23 poz  9 ochiq | Кабели силовые, Монтажный провод
          27.33   6 poz  2 ochiq | Кабель-канал, Короб кабельный
          26.20  14 poz  1 ochiq | Кабель питания, Сетевой кабель ← sizga mos

turniket  → 26.30 Турникет   (avtomatik taklif: 28.41 Пресс гидравлический)
shlagbaum → 27.90 Шлагбаум   (avtomatik taklif: 28.41)
```

### Ikki tuzatilgan o'lchov nuqsoni (2026-08-30)

1. `count(*)` = 40 "40 qaror" bo'lib ko'rinardi — aslida 40 ta RENDER edi.
   **Asbob o'zi yaratgan qatorni sanardi.**
2. `qaror_at − ochilgan_at` "sahifa ochilganidan beri" ni o'lchardi, "shu
   atamaga sarflangan vaqt" ni emas — ya'ni vaqt o'lchovi BOSHQA narsani
   o'lchayotgan edi.

Endi `ochilgan_at` birinchi HARAKATDA (qidiruv yoki qaror) yoziladi va NULL
bo'la oladi — NULL aynan **"o'lchanmadi"** degani, u nol deb hisoblanmaydi.

`kod_qaror` da `UNIQUE(kalit)` **ATAYLAB yo'q**: aynan o'sha cheklov
o'lchamoqchi bo'lgan holatni to'sardi (bir atamaga ikki kod — "Кабель" →
27.32 kuchlanish va 26.20 tarmoq kabeli). `kop_kodli_atama` ustuni buni
SANAYDI.

---

## 6. Moslashtirish (matching)

**Fayllar:** `api/matching.py`, `api/queries.py`, `api/catalog_auto.py` (yangi)

| Yo'l | Ball | Holat |
|---|---|---|
| **Kod bo'yicha** (`catalog_product_code` → `tender_good.good_code`) | 100 | ✅ |
| Matn bo'yicha (atama indeksi, SQL da) | 60 | ✅ |
| Atribut bo'yicha | qo'shimcha | ✅ |
| Profil bo'yicha (kalit so'z, hudud, narx oralig'i) | — | ✅ |

### Tezlik — o'lchangan tuzatish (2026-08-28)

```
/catalog/match     ~29 daqiqa  →  3 soniya
notify ballashi    ~59 daqiqa  →  1.2 soniya
```

Uch xato tuzatildi:

1. Naqsh HAR MAHSULOT uchun takrorlanardi: 22 100 naqsh (81.2 s) →
   GLOBAL takrorsiz atama: 925 naqsh (0.25 s). Natija AYNAN bir xil.
2. Solishtirish Python siklida edi → `queries.build_catalog_text_match`
   bilan SQL ga ko'chirildi.
3. Bir xil nuqson `notify.py` da ham bor edi — bitta chaqiruv joyi
   tuzatilib ikkinchisi qolgandi.

**Muhim:** "Sizga mos" bo'limi bo'sh ko'rinardi — sabab moslik yo'qligi EMAS,
**so'rov tugamasdi**. Brauzer uzilib bo'sh ro'yxat qolardi va u "mos tender
yo'q" deb o'qilardi. Soatlik ETL ning bildirishnoma qadami esa hech qachon
tugamasdi (buni `notify_test` ning `exit=124` i ochdi).

**Yagona manba:** atama qoidasi ikki joyda ikki xil edi (`/catalog/match`
faqat kalit so'z, `notify` SKU nomini ham → indeks 1 325 atamaga shishgandi).
Endi `queries.catalog_terms()` — yagona manba.

**Halol bo'sh holat:** endpoint `holat` (nechta mahsulot, nechtasi kodlangan)
va `atama_kesildi` qaytaradi. "Moslik yo'q" va "katalog kodlanmagan" —
boshqa-boshqa holatlar va interfeys ularni farqlaydi.

---

## 7. Tender talablari (requirement)

**Fayllar:** `api/requirement.py` (41 KB), `requirement_naqsh.py`,
`requirement_ai.py` · **Sinov:** `requirement_test.py` 189/189

Muammo: "tenderda nima talab qilinadi" degan savol uch joyda uch xil javob
olardi (`tender_good`, `ai_gonogo` nasri, chat qidiruvi) — ularni JOIN qilib
ham, filtrlab ham bo'lmasdi ("GOST talab qiladigan tenderlarni ko'rsat").

| Manba | Usul | Narx | Holat |
|---|---|---|---|
| `source='api'` | reyestr pozitsiyalari | bepul | ✅ |
| `method='naqsh'` | shablon naqshlari (`atama + raqam + birlik`) | bepul | ✅ |
| `source='document'` | model ajratadi (`json_schema`, iqtibos bilan) | **pullik** | ⛔ qulflangan |

**Natija:** 8 785 talab, 1 013 tenderda. Turlari bo'yicha: sertifikat 1 347,
moliyaviy 524, to'lov 257, bazis 149, kafolat 134, muddat 54.

**Nega naqsh ishlaydi:** O'zbekiston tender hujjatlari SHABLON asosida
yoziladi — "Гарантийный срок ... 12 месяцев", "Форма платежа – предоплата
в 50 %", "Yetkazib berish muddati ... 30 (o'ttiz) ish kuni". Hammasi
`atama + raqam + birlik` shaklida.

**Iqtibos TAXMIN QILINMAYDI:** bo'laklar raqamlanadi (`[1]`, `[2]`), model
o'zi qaysi bo'lakdan olganini aytadi, `save()` uni `file_ref` + `char_start`
ga aylantiradi. `extract(dry_run=True)` — STANDART.

**Ko'rib chiqish (review) apparati qurilgan:** `review_pilot` (30 qator),
`v_requirement_labeled`, `v_review_speed`, `v_review_disagreement`,
`RequirementReview.tsx`, `/requirements/queue|labeled|speed|pilot`.

> 🔴 1 487 talab `review_status='approved'` bo'lib turibdi, lekin
> `reviewed_by = 0` — ya'ni **ularni hech kim ko'rmagan**. Batafsil §18.

---

## 8. Malaka tekshiruvi (qualification)

**Fayl:** `api/qualification.py` · **Sinov:** `qualification_test.py` 79/79

`ai_gonogo.py` DAN FARQI: u 11 mezonni PULLIK modelga nasr sifatida beradi.
Bu modul o'sha taqqoslashning **deterministik** qismini bajaradi —
model chaqirmasdan, xarajatsiz, takrorlanadigan.

Mumkin bo'lgani: ikkala tomon ham allaqachon STRUKTURALI —
`tender_requirement.attrs->>'tur'` va `company_profile` (sertifikatlar,
ruxsatlar, tajriba yili, maksimal shartnoma qiymati, hodimlar soni,
yetkazish muddati, minimal marja, hududlar). Yetishmagani ularni
BIRLASHTIRISH edi.

Endpoint: `GET /tenders/{id}/qualification`.

---

## 9. Brokerga yo'naltirish (routing)

**Fayl:** `api/routing.py` · **Ekran:** `BrokerQueue.tsx`

Zanjir: tender → talab ajratish → malaka tekshiruvi → **NAVBAT** → broker qarori.

| Nima | Holat |
|---|---|
| `tender_routing` — 260 qator | ✅ |
| `ai_qaror` va `inson_qaror` — ALOHIDA ustun, aralashmaydi | ✅ |
| AI qarori o'zgarganini kuzatish (`ai_ozgardi`, `ai_qaror_eski`) | ✅ |
| `v_routing_queue`, `v_routing_agreement` (AI ↔ inson kelishuvi) | ✅ |
| Endpointlar: `/routing/queue`, `/routing/refresh`, `/routing/{id}/decision|open` | ✅ |

**✅ Inson halqasi shu yerda ISHLAGAN:** 30 ta inson qarori qabul qilingan —
**olindi 16, rad 8, kutilsin 6**. Bu — butun loyihada inson halqasi haqiqatan
ishlagan yagona nuqta.

**Nega ERP da emas:** yo'naltirishni `erp.*` ga yozish simmetrik chegara
shartnomasini buzardi va ikkala loyihaning sinovini yiqitardi. Tender-AI
"kimga tavsiya qilaman" deydi, ERP o'zi bilganini qiladi; ikkisi
`erp.v_tender_status` orqali solishtiriladi.

---

## 10. AI qatlami va RAG/chat

**Fayllar:** `api/ai.py`, `ai_chat.py` (70 KB), `ai_docs.py`, `ai_gonogo.py`,
`ai_match.py` · **Sinov:** `chat_test.py` 61/61, `paid_guard_test.py` 13/13

| Nima | Holat |
|---|---|
| Lokal embedding — `multilingual-e5-small` (118M, 384 o'lcham, **pulsiz**) | ✅ |
| pgvector + HNSW indeks | ✅ 95 874 vektor |
| RAG qidiruv (semantik + leksik gibrid) | ✅ |
| Tool-calling — `queries`, `pricing`, `stock`, `compliance` ustidagi yupqa qobiq | ✅ 134 chaqiruv |
| Har javobda `citations[]`, har tool `chat_tool_call` ga yoziladi | ✅ |
| Tool'lar FAQAT O'QIYDI — yozuv amali yo'q | ✅ |
| `company_id` SESSIYADAN olinadi, model undan bermaydi | ✅ |
| Xato ham saqlanadi (`chat_message.error`) — jimgina yo'qolmaydi | ✅ |
| Chat sessiyalari, oqim (`useChatStream.ts`), `ChatPanel.tsx` | ✅ 123 sessiya |
| Kvota va sarf hisobi (`ai_quota`, `ai_usage`, `v_ai_spend_current`) | ✅ |
| Go/No-Go tahlili (`GoNoGo.tsx`), AI moslik (`AiMatch.tsx`) | ✅ 9 tahlil |

**Asosiy dizayn qarori:** chat YANGI MANTIQ YOZMAYDI. Sabab: narx formulasi
allaqachon ikki joyda (Python + JS) va sinov ularni solishtirib turadi —
uchinchi nusxa yaratilmaydi.

### ⛔ PULLIK AI QULFI

`AI_PAID_ENABLED` (`api/ai.py:227`) — **standart holat O'CHIQ**. Qulf ataylab
`.env` orqali, kod orqali emas. `paid_guard_test.py` (13/13) uni qulflangan
holda ushlab turadi. Jami sarf bugungacha: **$4.18** (2 ta chaqiruv).

**Tamoyil:** AI ixtiyoriy. Kalit yo'q bo'lsa `AIUnavailable` qaytadi va
tizimning qolgan qismi ishlashda davom etadi.

---

## 11. Narx hisobi — P0-7

**Fayl:** `api/pricing.py` · **Sinov:** `pricing_test.py` 26/26

| Nima | Holat |
|---|---|
| Tannarx → soliq → marja → tavsiya narx | ✅ |
| Sozlamalar kompaniya bo'yicha (`pricing_settings`) | ✅ |
| `PricingPanel.tsx` — jonli hisob | ✅ |

**Muhim kafolat:** formula ikki joyda (Python `pricing.py` + JS `pricing.ts`)
va sinov ularni **solishtirib turadi**.

---

## 12. Hujjatlar cheklisti — P0-8

**Fayl:** `api/compliance.py` (63 KB) · **Sinov:** `compliance_test.py` — 114 o'tdi / 5 yiqildi

| Nima | Holat |
|---|---|
| Tender talab qiladigan hujjat turlari | ✅ |
| Kompaniyada bori bilan solishtirish | ✅ |
| Muddati o'tgan / yaqinlashgan rekvizit ogohlantirishi | ⚠️ 5 sinov yiqiladi |
| Import + shablon (`/company/documents/import|template|parse`) | ✅ |
| `CompliancePanel.tsx`, `CompanyDocuments.tsx`, `DocumentTemplate.tsx` | ✅ |

> ⚠️ `expiring_soon` (7 kun qolgan rekvizit) sinovi 5 ta real tenderda
> yiqiladi. Batafsil §18.

---

## 13. Bildirishnoma — P0-10

**Fayl:** `api/notify.py` (68 KB), `api/telegram.py` · **Sinov:** `notify_test.py` 29/29

| Kanal | Holat |
|---|---|
| Email (SMTP) | ✅ |
| Telegram bot + kanal ulash (token orqali) | ✅ |
| Obunachi boshqaruvi (`/notify/telegram/subscribers`) | ✅ |
| Sinov yuborish (`/notify/test`, `/notify/telegram/test`) | ✅ |
| Takror yuborilmasligi (`notify_sent`) | ✅ 22 yuborilgan |
| Foydalanuvchi tilida yuborish | ✅ |
| `NotifySettings.tsx` | ✅ |

---

## 14. Ko'p tillilik — interfeys VA bildirishnoma

**Fayllar:** `api/i18n.py`, `frontend/src/i18n.tsx`, `locales/{uz,ru,en}.ts`

| Nima | Holat |
|---|---|
| Interfeys uz / ru / en (~800 qator × 3) | ✅ |
| Bildirishnoma foydalanuvchi tilida | ✅ |
| Lug'at nomlari (`dim_*.name_uz`, `name_ru`) | ✅ |
| Alifbo normallashtirish — lotin/kirill (`translit.py`) | ✅ |
| Atama lug'ati — uch yozuv, bitta manba (`atama.py`) | ✅ 72/72 |

**Nega `atama.py` bor:** loyihada bir xil xato UCH MARTA takrorlandi —
(1) transliteratsiya TARJIMA emas (`kafolat` → `кафолат`, hujjatda esa
`гарантийный`, leksik qidiruv tillararo 0/8 berardi); (2) eval baholovchisining
"topilmadi" naqshi tor edi — model "duch kelinmadi" deganda to'g'ri javob
yiqilgan deb sanaldi; (3) `.doc` ajratgichining sifat mezonida faqat kirill
kalit so'zlar bor edi — 92% o'rniga 64% ko'rsatdi. Uchinchi marta takrorlangan
xato tasodif emas, **arxitektura bo'shlig'i**.

**Ataylab qilingan istisno:** `_QOSHIMCHALAR` ro'yxatida `ing` YO'Q, chunki
aynan "monitor" / "monitoring" juftligi soxta moslik manbai bo'lgan.

> Server xato matnlari hamon faqat o'zbekcha — bu qolgan ish (§18).

---

## 15. Interfeys

**38 ta komponent** + 16 ta `ui/` primitivi.

| Guruh | Komponentlar |
|---|---|
| Ro'yxat va filtr | `TenderTable`, `Filters`, `CategoryFilter`, `ProductFilter`, `Pagination`, `SourceChips` |
| Tender kartasi | `TenderDrawer`, `DocumentText`, `GoNoGo`, `AiMatch`, `CompliancePanel`, `PricingPanel`, `StockCheck`, `ErpLink` |
| Katalog | `CatalogView`, `CatalogImport`, **`KodNavbat`** |
| Kompaniya | `CompanyProfile`, `ProfileForm`, `CompanyDocuments`, `DocumentTemplate`, `AccountSettings`, `PasswordPanel` |
| Ish jarayoni | **`BrokerQueue`**, **`RequirementReview`** |
| Chat | `ChatPanel`, `CitationChip`, `ToolBadge`, `AiDocsNote` |
| Tizim | `LoginPage`, `Sidebar`, `PrefsMenu`, `Freshness`, `StatsStrip`, `StatsView`, `NotifySettings`, `ErrorBoundary`, `Icon` |

Qo'shimcha: `theme.tsx` (yorug'/qorong'i), `markdown.ts` (+ sinov),
`format.ts`, `colors.test.ts`; TypeScript `tsc` toza.

**`KodNavbat.tsx` da ATAYLAB YO'Q:** tahrirlash, o'chirish, tarix, filtr,
sahifalash. 40 qator bir ekranga sig'adi. `keng`/`aniq` yonma-yon
ko'rsatiladi va farq 2 barobardan katta bo'lsa qator sariq rangda
ogohlantiradi — `_talab()` ning YUQORI CHEGARA ekani interfeysda ham ko'rinadi.

---

## 16. Sifat va nazorat

### Sinov to'plamlari — 2026-08-30 da yurgizilgan (`--offline`)

| To'plam | Natija |
|---|---|
| `requirement_test` | **189 / 189** ✅ |
| `auth_test` | **130 / 130** ✅ |
| `compliance_test` | 114 o'tdi, **5 yiqildi** ⚠️ |
| `qualification_test` | **79 / 79** ✅ |
| `atama_test` | **72 / 72** ✅ |
| `chat_test` | **61 / 61** ✅ |
| `doctext_test` | **59 / 59** ✅ |
| `kodlash_test` | **55 / 55** offline (baza bilan 67/67) ✅ |
| `etl_coverage_test` | **48 / 48** ✅ |
| `notify_test` | **29 / 29** ✅ |
| `pricing_test` | **26 / 26** ✅ |
| `chunk_test` | **25 / 25** ✅ |
| `multitenant_test` | **20 / 20** ✅ |
| `paid_guard_test` | **13 / 13** ✅ |
| `import_test` | ⛔ **yiqilmadi — YURMADI** (konsol kodlash xatosi) |
| **JAMI** | **920 tekshiruv o'tadi**, 5 yiqiladi, 1 to'plam yurmaydi |

### AI baholash (`_tests/ai_eval/`)

`cases.jsonl`, `run_eval.py`, `recall_eval.py`, `retrieval_eval.py`,
`kod_eval.py`, `kod_biriktir.py`, `seed_catalog.py`, `yakunlash.py`.

### Loyihada takrorlangan nuqson sinflari — himoyaga aylantirilgani

| Sinf | Himoya |
|---|---|
| **Jimgina yo'qolish** — 837 kodsiz mahsulotdan 185 tasi na navbatda, na "talabsiz" da ko'rinardi (turi 30 belgidan uzun). Bu sinf loyihada **o'ninchi marta** uchradi | Har toifalashda QOLDIQ toifa + `jami == yig'indi` tekshiruvi |
| **O'zi yaratgan qatorni sanash** — 40 render "40 qaror" bo'lib ko'rindi | `ochilgan_at` birinchi HARAKATDA yoziladi |
| **O'lchanmagan = nol** | `ochilgan_at` NULL bo'la oladi; ko'rinish uni o'rtachaga qo'shmaydi, alohida sanaydi (`olchovsiz`) |
| **Yuqori chegarani o'lchov deb o'qish** (`_talab()`) | Docstring aytadi + interfeysda `keng`/`aniq` yonma-yon, 2× farqda ogohlantirish |
| **Izoh bilan himoyalangan qoida** — 1 487 qator "approved" bo'lib turibdi va hech kim ko'rmagan | Qoida CHECK va VIEW bilan qulflanadi, sinov aynan qulfni sinaydi |
| **Bir tuzatish, ikki chaqiruv joyi** (`notify.py` da qolgandi) | Yagona manba (`queries.catalog_terms()`) |
| **Til devori** (uch yozuv aralashmasi) | Hamma kirish `atama.normal()` dan o'tadi |
| **Ikki joyda ikki formula** (narx) | Sinov ikkalasini solishtirib turadi |
| **O'lchov kechiktirilsa qarz o'sadi** (12a-sinf, `grill-me`) | Yangi qatlamdan OLDIN inson halqasi hisoblagichi ko'rsatiladi (§18) |
| **Ikki qatlam alohida to'g'ri, orasidagi holat yo'qolgan** (13-sinf) — `POST /chat` `session_id` ni tiklaydi, `useChatStream` uni saqlaydi, lekin `App.tsx` `ChatPanel` ni SHARTLI chizadi: panel yopilganda state o'ladi. 133 sessiyaning 131 tasida ANIQ 2 xabar. Jiddiyrogʻi — `seansOch()` transkriptni ekranga chiqarib `sessionId` ni nolga tushirardi: **ekranda tarix, modelda bo'sh kontekst** | Sessiya ochilganda tiklanadi (`ChatPanel`, `DAVOM_SOAT`), `davom()` `reset()` o'rniga ipni saqlaydi; jurnalda CHEGARA qidiriladi (taqsimot emas) |
| **Avto-yaratilgan ma'lumot foydalanuvchi OQIMIGA tushishi** (10-sinf kengaytmasi) — eval `EVAL_COMPANY_ID = 2`, ya'ni haqiqiy ijarachi: 122 `[eval]` sessiyasi tiklash mexanizmiga ilinishi mumkin edi | `chat_session.manba` (migratsiya 0080); tiklash ham, tarix ro'yxati ham `manba <> 'eval'` bilan filtrlaydi |

---

## 17. Ishga tushirish

```powershell
# 1) Baza migratsiyalari — 58 ta, KUZATILADIGAN va TARTIBLI
#    Alfavit tartibi 67 ta bog'liqlikni buzadi (o'lchandi) — shuning
#    uchun `Get-ChildItem` BILAN QO'LLAMANG.
.venv\Scripts\python.exe migratsiya.py --holat      # nima qo'llangan
.venv\Scripts\python.exe migratsiya.py --qolla      # bo'sh/yangi baza
.venv\Scripts\python.exe migratsiya.py --bootstrap  # MAVJUD bazani ro'yxatga olish

# 2) .env — 35 ta sozlama (.env.example dan nusxa oling)
#    XT_DB_DSN, DB_POOL_MIN/MAX, ANTHROPIC_API_KEY, AI_PAID_ENABLED(=0),
#    AI_EFFORT, EMBED_MODEL_PATH, CORS_ORIGINS,
#    SMTP_HOST/PORT/USER/PASSWORD/FROM/TLS, TELEGRAM_BOT_TOKEN, ...

# 3) pgvector (bir marta)
.\install_pgvector.ps1

# 4) API + interfeys
.\run_api.ps1                             # FastAPI :8000
cd frontend; npm install; npm run dev     # Vite :5173

# 5) ETL — sinov yoki soatlik jadval
.venv\Scripts\python.exe run_etl.py --limit 3
.\register_task.ps1                       # soatlik Task Scheduler

# 6) Sinovlar — HAMMASI, nointeraktiv (CI shakli)
.venv\Scripts\python.exe run_tests.py              # 21 to'plam, chiqish kodi 0/1
.venv\Scripts\python.exe run_tests.py --only kod   # nomida "kod" bori
.venv\Scripts\python.exe run_tests.py --list       # ro'yxat, yurgizmaydi
```

Batafsil: `AVTOMATLASHTIRISH.md` (jadval), `docs/integration/*.md` (har modul).

---

## 18. Ma'lum bo'shliqlar va keyingi qadamlar

> Bu bo'lim ATAYLAB muhim o'ringa qo'yilgan. Loyihada takrorlangan naqsh:
> qatlam quriladi, sinovlari o'tadi, **lekin uni hech kim ishlatmaydi**.
> Yangi qatlam qo'shishdan OLDIN quyidagi hisoblagichlarni ko'ring.

### 🔴 Inson halqasi hisoblagichlari — qayta o'lchandi (2026-09-01)

**DA'VO ANIQLASHTIRILDI.** Avval bu bo'lim "halqa bo'sh" degan bitta
xulosa berardi. Qatlam bo'yicha o'lchanganda manzara boshqa chiqdi:
halqa **bo'sh emas, NOTEKIS**. Endi u `v_inson_halqasi` da o'lchanadi.

| Qatlam | Jami | Inson qarori | Navbatda | Ulush |
|---|---|---|---|---|
| Kod tasdig'i | 1 427 | **1 048** | 379 | 🟢 **73.4%** |
| Yo'naltirish | 310 | **31** | 279 | 🟡 10.0% |
| Talab ko'rigi | 11 099 | **0** | 8 445 | 🔴 **0.0%** |

"Halqa bo'sh" degan bitta raqam bu farqni **yashirardi** va kod
tasdig'i qatlamini ham "ishlamayapti" deb hisoblashga olib borardi.

**"Ishlatilmagan" ≠ "ishlamaydi".** Talab ko'rigi yo'li endi
uchidan-uchiga sinaladi (`POST /requirements/{id}/review`): darvoza,
kimlik, **bazaga yozilishi** va ijarachi izolyatsiyasi. Yo'l
**ishlaydi** — bo'shlik muhandislik nuqsoni emas.

| Pilot | Qiymat |
|---|---|
| Yaratilgan | 2026-08-26 |
| Jami | 30 |
| Hali ochiq | **8** |
| **Eskirgan** | **22** |
| Kutayotgan talab | 352 |
| **Qaror berilgan** | **0** |

`pilot_yarat()` ataylab idempotent va **qayta qurish yo'li yo'q** —
ya'ni muddati o'tgan to'plam yangisini **bloklab** turibdi. Bu
**mahsulot qarori**: eskirgan namunani tashlash xolislikni buzadi,
saqlash esa halqani bloklaydi. `v_pilot_holat` holatni ko'rsatadi,
qarorni emas.

**Soxta tasdiq YO'Q QILINDI.** Avval 1 487 ta talab `review_status='approved'`
va `reviewed_by = 0` bilan turardi. Hozir o'lchangan taqsimot:

| `review_status` | `mashina_holat` | Soni |
|---|---|---|
| `pending_review` | `ajratilgan` | 8 440 |
| `extracted` | `manba` | 1 455 |
| **`approved`** | — | **0** |

Migratsiya `requirement_migratsiya_jurnali` ga yozildi (oldin/keyin
suratlari bilan): o'sha paytda 1 487 ta satr `extracted` ga ko'chgan.
Bugun 1 455 — farq migratsiyadan keyingi ETL upsert'laridan. **Aniq
sababi satr darajasida O'LCHANMADI**; taxmin yozilmaydi. Muhimi:
invariant buzilmagan — `approved` = 0 va inson ko'rgan satr = 0, ya'ni
hech qaysi satr odam ko'rmasdan tasdiqlangan holatga QAYTA kira olmadi
(CHECK buni jismonan taqiqlaydi).

Bu — "tasdiqlanmaganini ishlatmang" qoidasi faqat IZOH bilan himoya
qilinganda nima bo'lishining aynan misoli. Shuning uchun qoida endi
CHECK va VIEW bilan qulflangan.

**Keyingi qadam (eng ustuvor): 40 ta haqiqiy kodlash qarori.** Qoida jadvali
SHUNDAN KEYIN quriladi — uning shakli (`UNIQUE(atama)` bo'ladimi, yoki
atama → ko'p kod) qarorlar paytida ma'lum bo'ladi.

**Qarama-qarshi qoida (ham yozilgan):** bitta o'lchov ikkita narsani isbotlay
olmaydi. Yorliqlash naqsh ajratgichining ANIQLIGINI o'lchaydi;
`ISHONCH_CHEGARA` ni isbotlamaydi, chunki `confidence` uchta qiymat oladi
(0.40 / 0.75 / 1.00) va 0.85 aslida `WHERE manba_turi = 'reyestr'` ning
raqam kiyimidagi shakli.

### 🟠 Texnik nuqsonlar

| Nuqson | Tafsilot |
|---|---|
| **uzex ETL muntazam yiqiladi** | Oxirgi 7 kunda 61 `error` / 64 `ok` (~51%). Xato: "yurish tugamasdan uzildi — jarayon majburan to'xtatilgan yoki kompyuter uxlagan". Yurish ~21 daqiqa, noutbuk uxlasa uziladi. |
| **`compliance_test` 5 ta yiqilish** | `expiring_soon` (7 kun qolgan rekvizit) 5 ta real tenderda kutilgan natijani bermayapti. |
| **`import_test` umuman yurmaydi** | `UnicodeEncodeError: cp1251` — sinov natijani chop etayotganda yiqiladi. Bu MANTIQ xatosi emas, konsol kodlash xatosi, lekin to'plam **hech narsani tekshirmayapti**. |
| **Matn yo'lining shovqini** | Kodlanmagan qism uchun matn mosligining 20 tasidan 18 tasi BITTA atamadan — "Кабель" (tenderlarda kuchlanish kabeli va kabel kanali, katalogda tarmoq/HDMI kabeli). Ular 60 ball oladi, ya'ni 100 ballli kod mosliklaridan PASTDA. |
| **Katalogda sinov qoldiqlari** | `[SINOV]` qatorlari va eval-review tasdiqlari real katalog bilan aralash. |
| **`notify_settings.base_url`** | Hamon `http://localhost:5173` — bildirishnomadagi havolalar telefondan ochilmaydi. |
| **Server xato matnlari** | Faqat o'zbekcha (bildirishnoma tarjima qilingan, API xatolari yo'q). |
| **`saved_search` bo'sh** | Apparat bor (`/searches` CRUD), 0 ta saqlangan qidiruv — ishlatilmagan. |

### 🟡 Commit qilinmagan ish (ishchi nusxada, 2026-08-30 holatiga)

| Fayl | Nima |
|---|---|
| `api/catalog_auto.py` (yangi) | Ko'rinmas avtomatik kodlash — mahsulot nomi/turi tender lotlarining tarixiy nomlari bilan solishtiriladi. Faqat barcha mazmunli so'zlar bir lotda uchragan va bitta kod mutlaq ustun bo'lgan holat qabul qilinadi (`MIN_EVIDENCE=2`, `MIN_SHARE=0.75`). Noaniq holatda kod TAXMIN QILINMAYDI — recall hisobiga precision saqlanadi. |
| `schema_patch_kod_qaror_2.sql` (yangi) | O'lchov tuzatishi: `ochilgan_at` NULL bo'la oladi ("o'lchanmadi" ≠ "0 soniya"); qator soni yoniga AJRATILGAN ATAMA soni qo'yiladi. |
| 14 ta o'zgartirilgan fayl | +496 / −57 qator (`kodlash.py`, `main.py`, `matching.py`, `queries.py`, `kodlash_test.py`, `KodNavbat.tsx`, `CatalogView.tsx`, `App.tsx`, `Sidebar.tsx`, `types.ts`, uch til fayli) |

### ⚪ Qilinmagani

- **Huquqiy tekshiruv o'tkazilmagan**
- **Production joylashtirish yo'q** — hamma narsa lokal mashinada
- Ish jarayoni holati (`yangi / baholanmoqda / qaror qabul qilingan`) — P0-11 ning qolgan qismi
- Hujjatdan talab ajratish (`source='document'`) — pullik, qulf ostida
- Qoida jadvali + `qoida_id` + qoida o'zgarganda qayta ko'rish

---

## 19. Vaqt bo'yicha yo'l xaritasi

| Sana | Commit | Nima qilindi |
|---|---|---|
| 2026-07-26 | `aa4b351` | **MVP:** 2 platforma ETL, FastAPI, React dashboard, ИКПУ kategoriyalari, katalog, saqlangan qidiruv, aniqlik quvuri |
| 2026-07-31 | `1ab5c06` | P0 bosqichi yopildi |
| 2026-08-02 | — | *(bu hujjatning avvalgi versiyasi shu sanada to'xtagan edi)* |
| 2026-08-27 | `ec15da8` | **Katta saqlash commit'i** (88 kuzatilmagan fayl): auth, RAG/chat, talab ajratish, kodlash, malaka, yo'naltirish, i18n |
| 2026-08-27 | `43616a0` | `grill-me` skiliga 12a-sinf: "o'lchov kechiktirilsa qarz foiz bilan o'sadi" |
| 2026-08-28 | `a50b9b8` | **Tezlik:** moslashtirish 29 daq → 3 s, bildirishnoma 59 daq → 1.2 s |
| 2026-08-28 | `6f95929` | Katalogga tasniflagich kodi biriktirildi — "Sizga mos" ishlay boshladi (18 → 44 tender) |
| 2026-08-28 | `6352f17` | Kanonik kalit (`atama.normal`), DALIL ko'rinishi, talab bo'yicha tartib |
| 2026-08-28 | `39c620e` | Qidiruv korpus pozitsiyalari bo'yicha (lug'at nomlari bo'yicha EMAS) |
| 2026-08-28 | `88cf81e` | Kod qidiruvi + navbat endpointlari, **qoldiqsiz toifalash** |
| 2026-08-28 | `a1c13de` | Kodlash navbati ekrani — **o'lchov asbobi sifatida** |
| 2026-08-30 | `a4c2f5d` | O'lchov nuqsoni tuzatildi: qator BIRINCHI HARAKATDA ochiladi, render paytida emas |
| 2026-08-31 | `c360174` | UTF-8 konsol + `run_tests.py` — `import_test` 143 tekshiruvni BAJARMASDAN o'lardi |
| 2026-08-31 | `b3e819f` | ETL ishonchliligi: qayta urinish, checkpoint, `partial` holati, hujjat UPSERT |
| 2026-08-31 | `373ca50` | Hujjat qamrovi qoldiqsiz: 11 026 satr, `hisobga_olinmagan = 0` |
| 2026-08-31 | `47c82d2` | Embedding qamrovi kuzatiladigan; takror mazmun nusxalanadi (chaqiruv −72%) |
| 2026-08-31 | `04fc42b` | 1 487 ta soxta `approved` ko'chirildi; invariant CHECK bilan qulflandi |
| 2026-08-31 | `5d8b207` | Kodlash piloti: har qaror DALIL bilan |
| 2026-08-31 | `530b9d8` | Muvofiqlik biznes vaqt mintaqasiga (UTC+5) o'tdi — 5 yiqilish tuzaldi |
| 2026-08-31 | `24ed971` | RAG bazaviy o'lchovi: gibrid Recall@8 = 0.705, MRR = 0.699 |
| 2026-08-31 | `7825fd3` | **Ishchi daraxt tozalandi** — 64 ta o'zgarish 13 ta commit'ga ajratildi (§21) |
| 2026-08-31 | (§22) | **Migratsiya versiyalash** — 55 ta patch kuzatuvga olindi; alfavit tartibi 67 bog'liqlikni buzardi |
| 2026-08-31 | (§23) | **Aktor kimligi va audit** — qaror endi odamga bog'lanadi; ijarachi izolyatsiyasi kompozit FK bilan |
| 2026-08-31 | (§24) | **Xavfsizlik qattiqlashtirish** — 1 Critical + 5 High tuzatildi; eng kam huquqli rol 24/24 bilan tasdiqlandi |
| 2026-08-31 | (§25) | **Ma'lumot xaritasi** — 7 manba endpointi, kelib chiqish qamrovi 0 yetishmovchilik, 8 ta NOMA'LUM belgilandi |
| 2026-08-31 | (§26) | **Joylashtirish** — staging majburiy, systemd + Caddy, zaxira + haftalik tiklash mashqi |

---

## 20. Hujjatlar xaritasi

| Fayl | Nima haqida |
|---|---|
| **`UPDATED.md`** | **shu fayl — bajarilgan ishlar jurnali (yagona manba)** |
| `LOYIHA.md` | To'liq texnik hujjat — arxitektura, ma'lumot modeli, endpointlar |
| `REJA.md` | TZ ga o'tish rejasi — bosqichlar, ma'lumot modeli, xavflar |
| `REJA_UX.md` | Saqlangan qidiruv, kategoriya, xabarnoma rejasi |
| `AVTOMATLASHTIRISH.md` | Soatlik ETL jadvali (Windows / macOS / Linux) |
| `reja_ai_chat.md` | AI-chat / RAG ish jurnali (§16.x saboqlar shu yerda) |
| `docs/erp_arxitektura.md` | ERP bilan chegara — arxitektura |
| `docs/erp_bosqichlar.md` | ERP integratsiya bosqichlari |
| `docs/erp_integratsiya.md`, `_2.md` | ERP integratsiya tafsilotlari |
| `docs/erp_texnik.md` | ERP texnik shartnoma |
| `docs/deploy.md` | **Joylashtirish — staging birinchi, orqaga qaytarish, zaxira** |
| `docs/legal-data-map.md` | **Ma'lumot xaritasi — huquqiy tekshiruv uchun (faktlar)** |
| `docs/xavfsizlik.md` | **Xavfsizlik: tahdid modeli, topilmalar, nazoratlar** |
| `docs/erp_kimlik.md` | **Aktor kimligi va audit — arxitektura qarori (ADR)** |
| `docs/integration/migratsiya.md` | **Migratsiya versiyalash — operator qo'llanmasi** |
| `docs/integration/etl.md` | ETL integratsiya qadamlari |
| `docs/integration/import.md` | Katalog importi |
| `docs/integration/doctext.md` | Hujjat matni |
| `docs/integration/pricing.md` | Narx hisobi |
| `docs/integration/compliance.md` | Hujjatlar cheklisti |
| `docs/integration/notify.md` | Email bildirishnoma |
| `docs/integration/notify_telegram.md` | Telegram kanali |
| `docs/integration/notify_lang.md` | Bildirishnoma tili |

---

## 21. Ishchi daraxt gigiyenasi — 2026-08-31

Bu bo'lim **repozitoriyning haqiqiy holati tekshirilgandan KEYIN** yozildi,
oldin emas.

### Nima bor edi

Seans boshida `a4c2f5d` ustida **64 ta o'zgarish** turardi: 44 ta o'zgargan,
20 ta kuzatilmagan fayl. Ular ichida ikki xil ish ARALASH edi — shu seansda
qilingani va undan OLDIN qilingani.

### Tasniflash — kim nima qilgan

Seans boshidagi `git status` surati hakam sifatida ishlatildi. Unga ko'ra
quyidagilar **seansdan oldin** iflos edi va `b0ad429` da ALOHIDA saqlandi,
shu seans ishiga qo'shib yuborilmadi:

`api/catalog_auto.py`, `schema_patch_kod_qaror_2.sql`, `api/matching.py`,
`api/queries.py`, `frontend/src/App.tsx`, `CatalogView.tsx`, `Sidebar.tsx`.

Yana beshta fayl **ikkala ishni ham** saqlaydi va ajratib bo'lmadi
(bu muhitda interaktiv `git add -i` yo'q): `api/kodlash.py`, `api/main.py`,
`KodNavbat.tsx`, `types.ts`, uch tarjima fayli, `_tests/kodlash_test.py`.
Bu holat commit izohlarida AYTIB o'tildi — yashirilmadi.

### Sir tekshiruvi

`a4c2f5d..HEAD` oralig'idagi **12 489 ta qo'shilgan satr** naqshlar bo'yicha
skanerlandi: parol, API kalit, `Bearer`, parolli DSN, AWS kaliti, shaxsiy
kalit, Telegram bot tokeni, mahalliy absolyut yo'l. **Natija: 0 ta moslik.**

`.env` va `ngrok.yml` `.gitignore:4` va `:6` bilan chetlatilgan va
kuzatilmaydi (`git check-ignore -v` bilan tasdiqlandi). `.env.example`
kuzatiladi, lekin u shablon: parol o'rnida `SIZNING_PAROLINGIZ`,
`ANTHROPIC_API_KEY=` bo'sh.

### Sinov fixture'lari — manba emas, chiqish

`_tests/fixtures/` dagi 5 fayl kuzatilardi, lekin ularni
`import_test.py:make_fixtures()` har yurishda qayta yasaydi. Shuning uchun
daraxt har sinovdan keyin "iflos" bo'lardi. O'lchandi: `.xlsx` da farq faqat
`docProps/core.xml` ichidagi vaqt tamg'asi. Beshalasi o'chirilib sinov
yurgizildi — **149/149 o'tdi va beshalasi qayta yasaldi**, ya'ni ular
kodning ishlashiga kerak emas. Kuzatuvdan chiqarildi (`642258b`, `7825fd3`).

### Commit'lar

| SHA | Qatlam |
|---|---|
| `642258b` | Fixture'lar kuzatuvdan chiqarildi |
| `b0ad429` | Katalog avtokodlash qatlami — **seansdan oldingi ish** |
| `c360174` | UTF-8 konsol + `run_tests.py` |
| `b3e819f` | ETL ishonchliligi (+ sxema patchi) |
| `373ca50` | Hujjat qamrovi (+ sxema patchi) |
| `47c82d2` | Embedding qamrovi (+ sxema patchi) |
| `04fc42b` | Talab tekshiruvi butunligi (+ sxema patchi) |
| `5d8b207` | Kodlash piloti (+ sxema patchi) |
| `530b9d8` | Muvofiqlik — biznes vaqt mintaqasi |
| `9c3b6a1` | API yuzasi |
| `bf555c9` | Frontend |
| `24ed971` | RAG baholash |
| `7825fd3` | `.gitignore` qoidasi (`642258b` ni to'ldiradi) |

Sxema patchlari o'z qatlami bilan BIRGA qo'yildi, alohida "migratsiya"
commit'iga yig'ilmadi — aks holda oraliq commit'da kod bor, jadval yo'q
holat chiqib, daraxt o'sha nuqtada ishlamas edi.

`7825fd3` alohida commit bo'lib qoldi, chunki `642258b` da `.gitignore`
sahnaga qo'yilmay qolgan va uni tuzatish uchun 12 ta commit'ni qayta yozish
kerak edi. Kamchilik yashirilmadi — izohda yozildi.

### Tekshirilgan holat

| Nima | Natija |
|---|---|
| Commit'gacha sinovlar | `run_tests.py` → **21/21 to'plam, chiqish kodi 0** (157 s) |
| Commit'dan keyin sinovlar | `run_tests.py` → **21/21, chiqish kodi 0** |
| Sir | 12 489 satrda **0 ta moslik** |
| `git status` | **toza** (kuzatilmagan fayl yo'q) |
| Fixture'lar sinovdan keyin | e'tiborsiz — daraxt toza qoladi |


---

## 22. Migratsiya versiyalash — 2026-08-31

`schema_patch_*.sql` fayllari **kuzatiladigan** migratsiyaga aylandi.
Batafsil: `docs/integration/migratsiya.md`.

### Nima o'lchandi

Bazada `schema_migration` jadvali **yo'q edi** — "qaysi patch qo'llangan"
degan savolga javob beradigan hech narsa yo'q edi. Yagona qo'llash usuli
`Get-ChildItem schema_patch_*.sql` edi, ya'ni **alfavit tartibi**.

Fayllardan bog'liqlik grafi chiqarildi (e'lon qilingan `Talab:` sarlavhalari,
raqamli suffikslar, obyekt bog'liqliklari). **Alfavit tartibi bu grafdagi
67 ta yoyni teskari qo'yadi.** Masalan `notify_subscribers.sql` sarlavhasida
"OLDIN `notify_telegram.sql` qo'llanilgan bo'lishi kerak" deb **yozgan**,
alfavitda esa `_subscribers` `_telegram` dan oldin keladi.

Va tartib natijani belgilaydi: 8 ta obyektni bir nechta patch yaratadi —
`v_requirement_review` ni **to'rtta**.

### Nega Alembic emas

Qaror o'lchovga tayanadi: 53 fayl sof SQL (~4 800 satr DDL); 4 tasi psql
meta-buyruqlarini ishlatadi va `multitenant.sql` `\if :{?tenant_id}` —
psql **o'zgaruvchisi**, SQLAlchemy ulanishi orqali yurmaydi; ORM modellari
yo'q, ya'ni `autogenerate` foydasi mavjud emas; chiziqli `down_revision`
zanjiri yo'q va uni retroaktiv tiklash taxminni fakt qilib ko'rsatish
bo'lardi.

### Nima qurildi

| Fayl | Nima |
|---|---|
| `schema_patch_migratsiya.sql` | `schema_migration` jurnali + 2 ko'rinish |
| `migratsiya.py` | Yurgizuvchi (manifest, checksum, qulf, bootstrap) |
| `migratsiya_manifest.tsv` | **Muzlatilgan** tartib, 55 yozuv |
| `_tests/migratsiya_test.py` | 62 tekshiruv, 4 stsenariy |

**Qayta qo'llash to'sig'i izohda emas, indeksda:**

```sql
CREATE UNIQUE INDEX schema_migration_bir_marta
    ON schema_migration (migratsiya_id) WHERE holat IN ('ok','bootstrap');
```

Yana 6 ta CHECK — `xato` uchun **dalil**, `bootstrap` uchun **izoh**
majburiy. 11 ta buzuq yozuv sinab ko'rildi, **11 tasi ham rad etildi**.

`ok` va `bootstrap` **ataylab farqli atalgan**: birinchisi *bajarilgan*,
ikkinchisi *o'lchangan*.

### Tekshirilgan holat

| Stsenariy | Natija |
|---|---|
| Bo'sh baza → joriy sxema | **55/55**. Ishlab chiqarishdagi har jadval, ko'rinish va ustun qurilgan bazada bor — **0 ta yetishmaydi** |
| Mavjud baza → qayta qo'llash yo'q | `--qolla` hech narsa qilmadi; **52 jadvalda** qator soni o'zgarmadi |
| Uzilgan migratsiya | To'xtadi (kod 2); tranzaksionlikka qarab boshqa maslahat |
| Checksum o'zgarishi | To'xtadi; izohsiz qayta muhrlash rad etildi; eski qator saqlandi |

**`xtxarid` bazasi ro'yxatga olindi:** 55/55, yetishmaydigan 0 ta,
checksum farqi 0.

### Ochiq yozilgan cheklovlar

1. **`multitenant.sql` bo'sh bazada to'xtaydi** — u faol `company_account`
   talab qiladi. Yurgizuvchi buni oldindan tekshiradi va tushunarli xabar
   beradi, migratsiyani **umuman boshlamaydi**.
2. **Tartib chiqarish jadval darajasida** — `ADD COLUMN` bog'liqligini
   ko'rmaydi. Bunday yoylar `QOLDA_YOY` da, har biri aynan bitta psql
   xatosidan. Shuning uchun manifest **bo'sh bazada qurib** tekshiriladi.
3. **`erp` sxemasi boshqa repozitoriyda.** `auth_2.sql` `public.app_user`
   ni faqat `erp.app_user` to'la bo'lsa tashlaydi. Toza qurilgan bazada
   `app_user` **qoladi** — bu patchning himoya xulqi. Migratsiya kuzatuvi
   bu old shartni majburlay olmaydi.


---

## 23. Aktor kimligi, ruxsat va audit — 2026-08-31 (auth-6)

Arxitektura qarori: `docs/erp_kimlik.md`.

### Nima o'lchandi

Tender-AI ga KOMPANIYA kiradi, odam emas (ataylab — hodimlar ERP da).
Lekin inson qarorlari uch xil, mos kelmaydigan usulda yozilardi:

| Qayerda | Aktor | Manba | Ishonchlimi |
|---|---|---|---|
| `tender_requirement.reviewed_by` | `INT` -> `company_account` | sessiya | Ha, lekin bu **kompaniya** |
| `kod_qaror.kim` | `TEXT` (sessiya login'i) | sessiya | O'sha muammo |
| `tender_routing.broker_nomi` | `TEXT` | **`body.broker` — mijozdan** | **Yo'q** |

O'lchandi: 310 ta yo'naltirish qatoridan **30 tasida** inson qarori
bor, `broker_nomi` esa **0 tasida** yozilgan — ya'ni yolg'on yozuv
hali yo'q edi, lekin yo'l ochiq edi.

### Qaror — cheklangan integratsiya xaritasi

`erp.app_user` aynan shu bazada va unda haqiqiy hodimlar bor, LEKIN
chegara shartnomasi VIEW orqali ishlashni talab qiladi, va
`erp.own_company` BITTA qator — ya'ni ERP hodimida ijarachi
tushunchasi YO'Q. Mahalliy sub-foydalanuvchi tizimi esa
`erp.app_user` ni takrorlardi (aynan `auth_2` olib tashlagan narsa).

Tanlandi: `actor` — **xarita**, kimlik ombori emas. Parol yo'q,
token yo'q, sessiya yo'q, **kirish bermaydi**. Autentifikatsiya
o'zgarmadi.

### Yorliq dalildan oshmaydi

Har atribut yoniga uning QANCHALIK ishonchli ekani yoziladi:
`erp_sessiya` (isbotlangan) · `aktor_elon` (e'lon qilingan) ·
`kompaniya_sessiyasi` (faqat kompaniya) · `servis` (odam yo'q) ·
`kuzatuvdan_oldin`.

Birinchi ikkisi ATAYLAB ajratilgan — biri tekshirilgan, ikkinchisi
aytilgan.

### Ijarachi izolyatsiyasi — kompozit FK

    FOREIGN KEY (company_id, reviewed_actor_id)
        REFERENCES actor (company_id, id)

Boshqa ijarachining aktorini yozish **jismonan mumkin emas**.
O'qish alohida: FK yozishni to'sadi, o'qishni emas — shuning uchun
`aktor.bitta()`/`royxat()` `company_id` ni har doim shartda saqlaydi.

### Audit — faqat qo'shiladi

`audit_jurnal`: company_id, actor_id, ishonch, amal, entity,
entity_id, oldin, keyin, izoh, ip, user_agent, at. `UPDATE`/`DELETE`
bazada trigger bilan to'silgan, **kaskad yo'l ham**.

Halol cheklov: superuser triggerni o'chira oladi — to'siq
"imkonsiz" degani emas, "tasodifan bo'lmaydi va izsiz ketmaydi".

### Tekshirilgan holat

`_tests/aktor_test.py` **63/63**; to'liq to'plam **23/23**.
Ijarachilararo soxtalashtirish bazada ham, API da ham rad etiladi;
API javobi id mavjudligini SIZDIRMAYDI.

Sinovlar HAQIQIY qatorlarda o'lchaydi. Birinchi urinishda ular bo'sh
to'plamda "rad etildi" degan **yolg'on PASS** bergan edi — bu
tuzatildi va sinov ichida izohlandi.

### Ochiq qolgan qarz

1. `erp.v_tai_actor` shartnoma-view i ERP da **chop etilmagan** —
   ungacha eng yuqori daraja `aktor_elon`.
2. **Ishlab chiqarishda aktor ro'yxatga olinmagan:**
   `erp.own_company` = "ZZFIX Kompaniya", ijarachi 2 esa "BARAKA
   PROFIT MChJ" — mos kelmaydi, shuning uchun ERP hodimlari
   avtomatik xaritalanmadi. Xaritalash operatorning ANIQ qarori.
3. 30 ta eski qaror `kuzatuvdan_oldin` — aktor **tayinlanmaydi**.
4. `aktor_majburiy` hech qayerda yoqilmagan (standart `false`,
   hozirgi xulq saqlanadi).


---

## 24. Ishlab chiqarish xavfsizligi — 2026-08-31

To'liq hisobot: `docs/xavfsizlik.md` (tahdid modeli, topilmalar,
tekshirilgan nazoratlar va TAVSIYALAR ALOHIDA).

### Topilmalar

| # | Daraja | Topilma | Holat |
|---|---|---|---|
| C-1 | **Critical** | Ilova bazaga `postgres` SUPERUSER (`bypassrls=true`) sifatida ulanadi | Repozitoriyda hal qilindi; DSN almashtirish operatorda |
| H-2 | High | Javoblarda BIRORTA xavfsizlik sarlavhasi yo'q | Tuzatildi |
| H-3 | High | Yuklangan fayl butunlay xotiraga, chegara KEYIN | Tuzatildi |
| H-4 | High | `.xlsx` zip bombasidan himoya yo'q | Tuzatildi |
| H-5 | High | `/docs`, `/openapi.json` ochiq — butun API yuzasi | Tuzatildi |
| H-6 | High | `erp_stock.py` `erp.stock_move` JADVALINI o'qiydi | Tuzatildi |
| M-6..M-9 | Medium | PBKDF2 240k; DB xatosi sizishi; npm 4 zaiflik; dev-server 0.0.0.0 | Tuzatildi / yumshatildi |

### C-1 nega Critical edi

O'lchandi: `rolsuper=true, rolbypassrls=true`. Uchta oqibat:
SQL inyeksiyasi TO'LIQ egallash bo'lardi; audit append-only qulfini
ILOVANING O'ZI yecha olardi; ERP chegarasi FAQAT sinov bilan
himoyalangan edi (sinov KEYIN aytadi, huquq OLDIN to'sadi).

`schema_patch_huquq.sql` — `tai_app` roli. `public` da CRUD lekin
`CREATE` yo'q; `audit_jurnal` da `UPDATE`/`DELETE` yo'q; `erp.*` dan
FAQAT uchta shartnoma-view. Parol repozitoriyaga tushmasin uchun rol
LOGIN'SIZ — operator o'z LOGIN rolini yaratadi.

**13/13 huquq chegarasi empirik tekshirildi** (haqiqiy ulanish bilan):
`erp.app_user` o'qish/yozish, `erp.opportunity`, audit `UPDATE`/
`DELETE`, triggerni tashlash, `CREATE`/`DROP TABLE` — hammasi RAD
ETILDI. **To'liq sinov to'plami shu rol bilan yurgizildi: 24/24.**
Ya'ni almashtirish ilovani buzmaydi — tekshirilgan, taxmin emas.

### Yo'l-yo'lakay topilgan ikki narsa

1. **`npm run build` bu seansdan OLDIN buzuq edi** (`a1c13de` dan
   beri, `KodOlchov` turi). Mening avvalgi `tsc --noEmit`
   tekshiruvim KUCHSIZROQ konfiguratsiyani o'lchagan va buni
   ko'rsatmagan. `tsc -b` bilan aniqlandi va tuzatildi.
2. **Eng kam huquq HAQIQIY chegara buzilishini ochdi:**
   `erp_stock.py` `erp.stock_move` JADVALINI o'qirdi — o'sha faylning
   o'z izohi "jadvalga emas, view ga bog'lanamiz" deb yozganiga
   qaramay. Superuser bilan buni hech narsa ko'rsatmasdi.

### Halol cheklovlar

- **`pip-audit` o'rnatilmagan va PyPI maslahat bazasiga so'rov
  yuborilmadi.** Python paketlari VERSIYA bo'yicha yangi deb
  tasdiqlandi, CVE bo'yicha TEKSHIRILMADI.
- HSTS standart O'CHIQ — yoqish domenni HTTPS ga qulflaydi va TLS'siz
  muhitda saytni yo'q qiladi. Bu infratuzilma qarori.
- `XT_DB_DSN` hali `postgres` — rol tayyor, almashtirish operatorda.
  `xavfsizlik_test` buni OGOHLANTIRISH bilan ko'rsatadi.

### Tekshirilgan holat

`_tests/xavfsizlik_test.py` — 95/95 (oflayn) / 105/105 (baza bilan).
To'liq to'plam **24/24**. `npm audit` = **0 zaiflik**.


---

## 25. Ma'lumot xaritasi — huquqiy tekshiruv uchun texnik asos

To'liq hujjat: `docs/legal-data-map.md`.

**BU HUJJATDA HUQUQIY XULOSA YO'Q** — faqat o'lchangan faktlar.
Aniqlanmagan narsa NOMA'LUM deb belgilangan (8 ta band).

### Tashqi manbalar (7 ta endpoint, 2 ta domen)

`api.xt-xarid.uz` (`/rpc`, `/urpc`, `/file/`) va
`apietender.uzex.uz` (`/api/common/TradeList`, `GetTrade`,
`DownloadFile`, `Libs/GetRegions`).

Chastota **Windows Task Scheduler'dan o'qildi**, taxmin emas:
`TenderAI-ETL-Hourly` va `TenderAI-RAG` — ikkalasi ham `PT1H`, faol.

Manbalarga **kalit yoki hisob ishlatilmaydi** — so'rovlar anonim.

### Qayta tarqatish

Hujjat **fayli SAQLANMAYDI** — yuklab olish manbadan proksi
qilinadi. Hujjat **MATNI** esa saqlanadi: 4 011 qator, **134 MB**,
188 561 bo'lak.

### Shaxsiy bo'lishi mumkin bo'lgan maydonlar — o'lchandi

Qiymatlar hujjatga KO'CHIRILMAGAN, faqat naqsh sanog'i:

| Maydon | To'ldirilgan | Xususiyat |
|---|---|---|
| `tender_detail.director` | 2 964 | 2 959 tasida ism ko'rinishidagi matn |
| `raw_json->detail->contacts` | 2 683 | 78 tasida telefonga o'xshash raqam, 50 tasida email |
| `tender_detail.company_details` | 2 960 | tuzilishi TAHLIL QILINMAGAN |
| `tender_item.delivery_address` | 9 973 | — |
| hujjat matni | 4 011 | 441 tasida email, 212 tasida telefon naqshi |

### Kelib chiqish — bo'shliq topildi va to'ldirildi

Metama'lumot to'liq edi, LEKIN ommaviy havolani qurish naqshi
FAQAT FRONTENDDA edi — bazadan so'ralganda mashina o'qiy oladigan
javob yo'q edi. `schema_patch_manba_url.sql` uni bazaga ko'chirdi:
`manba_url()`, `v_tender_manba`, `v_hujjat_manba`, `v_manba_qamrov`
+ `GET /manba/tender/{id}`, `GET /manba/qamrov`.

**Qamrov o'lchandi:** `tender` 3 605, `tender_document` 10 634,
`doc_chunk` 188 561 — **har ustunda 0 ta yetishmovchilik**.

### Tashqi AI — tasdiqlandi

`paid_allowed()` = **False**, `get_client()` **BLOKLANADI**,
`EMBED_PROVIDER` = **local**, `.env` da `AI_PAID_ENABLED` **umuman
yo'q**. Qulf YAGONA NUQTADA: har Anthropic chaqiruvi
`ai.get_client()` dan o'tadi va `paid_guard()` kesh tekshiruvidan
ham OLDIN ishlaydi.

### Saqlash va o'chirish — o'lchangan cheklov

Avtomatik tozalash faqat 2 ta (sessiya, `login_attempt` 90 kun).
Tender ma'lumoti, hujjat matni, bo'laklar, chat, audit — **muddat
YO'Q**.

**Ijarachini hozir o'chirib BO'LMAYDI** (tranzaksiyada tekshirildi,
qaytarildi): `audit_jurnal` append-only trigger'i kaskadni to'sadi.
Audit kafolati va o'chirish talabi bir-biriga QARSHI turadi — bu
arxitekturaviy qaror talab qiladi, texnik "tuzatish" emas.

### Sinov

`_tests/manba_test.py` — 41/41. Kelib chiqish qamrovi nolga teng
bo'lib qolishini qo'riqlaydi. To'liq to'plam **25/25**.


---

## 26. Joylashtirish — staging birinchi (2026-08-31)

To'liq qo'llanma: `docs/deploy.md`.

> **Server hali yo'q**, lekin skriptlar endi **MASHQ QILINGAN**
> (`_tests/deploy_test.py` 193/193). Zaxira, tiklash, sog'liq,
> orqaga qaytarish va joylashtirish darvozasi HAQIQATAN
> yurgizildi va **7 nuqson** topildi — beshtasi faqat skript
> ishga tushirilganda ko'rindi.
>
> Hali bajarilmagani: `deploy.sh` ning qurish qismi (`venv`,
> `npm ci`, migratsiya), Caddy/HTTPS va systemd taymerlar —
> ular haqiqiy Linux mashinasini talab qiladi. Bu ochiq
> aytiladi (`docs/deploy.md` §13.5).

### Arxitektura

Caddy (avtomatik HTTPS) -> uvicorn 127.0.0.1 -> PostgreSQL+pgvector.
Frontend QURILGAN statik fayllar (`npm run build`), dev-server
ISHLATILMAYDI. systemd timer'lar: ETL soatiga 1, zaxira har kuni,
tiklash mashqi haftalik.

**Shablon birlik** (`tenderai-api@.service`): staging va production
BITTA fayldan — ikkita nusxa ajralib ketishining eng qisqa yo'li.

### Staging'siz ishlab chiqarishga joylashtirib BO'LMAYDI

`deploy.sh production` `/opt/tenderai/staging/.verified` faylini
tekshiradi va AYNAN SHU ref staging'da o'tganini solishtiradi.
Tasdiqni staging joylashtiruvi SOG'LIQ TEKSHIRUVIDAN O'TGACH o'zi
yozadi.

Joylashtirish ATOMAR (`ln -sfn current`), sog'liq tekshiruvi
o'tmasa AVTOMATIK orqaga qaytariladi.

### To'rt sog'liq tekshiruvi ATAYLAB ajratilgan

| Endpoint | Nima | Yiqilsa |
|---|---|---|
| `/health` | jarayon tirikmi | xizmat o'lgan |
| `/ready` | baza **va migratsiya** | **503** — proksi trafik yubormaydi |
| `/freshness` | ETL yangiligi | ogohlantirish |
| `psql` | baza to'g'ridan-to'g'ri | ulanish yo'q |

Ularni qo'shish "tirik = ishlayapti" degan YOLG'ON berardi: jarayon
ko'tarilgan, lekin migratsiya qo'llanmagan holat HAQIQIY.

`/ready` OCHIQ (proksi token ushlamaydi), lekin javobi TAFSILOTSIZ —
sabablar server jurnalida. `auth_test` dagi ochiq yo'llar soni 8 -> 9
ONGLI ravishda yangilandi.

### `localhost` havolasi — o'lchangan va to'silgan

Bazada `notify_settings.base_url = 'http://localhost:5173'` YOZILGAN
edi (haqiqiy ijarachi uchun). Bildirishnoma o'chiq bo'lgani uchun
buzuq havola hali yuborilmagan.

Uch qatlam: `PUBLIC_BASE_URL` muhitdan; bazadagi qiymat mahalliy
bo'lsa MUHIT yutadi; `url_tekshir()` `APP_ENV != dev` da yuborishni
TO'XTATADI. Jimgina almashtirmaydi — to'g'ri manzil noma'lum.

Tekshiruv `card_url()` ICHIDA, ya'ni uchala ko'rinish (email matni,
email HTML, Telegram) avtomatik qamrab olinadi.

> **KEYIN O'ZGARDI (19-vazifa).** Bu qatlam yetarli emasdi:
> tekshiruv faqat YUBORISHDA edi, ya'ni noto'g'ri sozlama soatlab
> ko'rinmasdi; frontend QURILMASI esa umuman qamrab olinmagan edi
> va unga `localhost:8000` singib qolardi. Mantiq
> `api/ommaviy_url.py` ga ko'chdi (yagona manba), asosiy
> o'zgaruvchi `APP_PUBLIC_URL` bo'ldi va tekshiruv ISHGA TUSHISHGA
> ko'chdi. Batafsil: `docs/deploy.md` §10.

### Zaxira — sinalmagani zaxira emas

`backup.sh` dump oladi va DARHOL `pg_restore --list` bilan
ochilishini tekshiradi (buzuq faylni haftalab saqlab yurmaslik
uchun); jadval soni 10 dan kam bo'lsa dump O'CHIRILADI.

`restore-test.sh` HAR HAFTA vaqtinchalik bazaga tiklaydi, jadval /
qator / migratsiya / pgvector ni tekshiradi va TIKLASH VAQTINI
o'lchaydi (RTO uchun haqiqiy raqam). Ishlab chiqarish bazasi bilan
adashmaslik tekshiruvi bor va u bajarilmasa skript TO'XTAYDI.

### Tuzilmali jurnal

`api/jurnal.py` — JSON qatorlar, har so'rovda `sorov_id` (javobda
`X-Request-Id`). SIRLAR NIQOBLANADI: `password`, `token`, `api_key`,
`dsn`, `cookie` nomli maydonlar — NOM bo'yicha, mazmun bo'yicha emas.
`/health` va `/ready` so'rovlari yozilmaydi (faqat xato bo'lganda) —
ular har 30 soniyada keladi.

### Ochiq qolgan

1. Server yo'q — hech narsa haqiqiy mashinada yurgizilmagan.
2. Domenlar va staging `basic_auth` xeshi NAMUNAVIY.
3. Zaxira faqat mahalliy diskda — tashqi nusxa yo'q.
4. Monitoring/ogohlantirish yo'q: systemd xizmatni qayta ko'taradi,
   lekin buni HECH KIM bilmaydi.
5. RTO raqami hali O'LCHANMAGAN — mashq birinchi marta yurgandan
   keyin ma'lum bo'ladi. Taxminiy raqam yozilmadi.



---

## 27. Sifat qatlami: 15–21-vazifalar va ochiq muammolar reyestri — 2026-09-01

Bu qatlamda **yangi imkoniyat qo'shilmadi**. Mavjudlarining
**o'lchovi, halolligi va qo'riqchilari** ustida ishlandi.

### 27.1 Vazifalar (15–21)

| № | Ish | O'lchangan natija |
|---|---|---|
| 15 | Katalog kodlash qamrovi | 0 → **467** aniq kod, chegara **o'zgarmadi**; 383 inson yorlig'iga nisbatan **99.7%** |
| 16 | `Кабель` soxta musbatlari | precision **0.689 → 1.000**, recall yo'qotilmadi |
| 17 | Yo'naltirish kelishuvi | `review` endi 0% emas — u **maxrajga kirmaydi**; tarixiy haqiqat saqlanadi |
| 18 | Talab qamrovi | **sifat 100%** va **o'tkazuvchanlik 32.2%** ajratildi; `hisobga_olinmagan = 0` |
| 19 | Ommaviy manzil | yagona manba `api/ommaviy_url.py`; qurilmadan **4 ta `localhost` chiqarildi** |
| 20 | API xatolari | **105 kod**, 315 tarjima; `raise HTTPException` **75 → 0** |
| 21 | Saqlangan qidiruv | CRUD **ishlaydi**; 3 qism **keyinga qoldirilgan** deb yozildi |

### 27.2 Ochiq muammolar reyestri

`docs/ochiq_muammolar.md` — 9–21-vazifalar davomida topilgan va
**tuzatilmagan** narsalar bir joyda, har biri **o'lchangan dalil**
bilan. Boshlanishda **22 band**; shundan **8 tasi yopildi**.

| Band | Natija |
|---|---|
| **S-1** | Sinovlar standart holatda **bazasiz** yurardi → ikki o'q; **+527 tekshiruv (+27%)** |
| **B-1** | Skriptlar **hech qachon bajarilmagan** edi → mashq qilindi, **2 nuqson** topildi |
| **B-2** | ~~Manba HTTP 400 doimiy~~ — **da'vo noto'g'ri edi**, xato o'tkinchi |
| **B-3** | Halqa **bo'sh emas, notekis**; yo'l **ishlaydi** |
| **M-1** | **30 hujjat dalilsiz `ok`** — sabab isbotlandi, baza endi rad etadi |
| **M-2** | ~~Aktor noma'lum~~ — **aniq belgilangan** edi; izchillik endi bazada |
| **M-3** | Audit artefakti — **storno** yozuvi bilan belgilandi |
| **Q-1** | Ochiq tenderlar qamrovi **100%**; quvurdagi bo'shliq yopildi |
| **Q-2** | Xeshdan ommaviy nusxalash — ochiq qamrov **33.1% → 77.2%** |
| **O-4** | `pip-audit`: **8 zaiflik** topildi va tuzatildi |

### 27.3 Ikki da'vom noto'g'ri chiqdi

Halollik uchun yoziladi: **B-2** da "doimiy" so'zini, **M-2** da
`NULL aktor` ni **dalil** deb o'qidim. Ikkalasi ham tizimning
**o'z yorlig'i** edi, manba haqidagi fakt emas. Ikkala holatda ham
asl nuqson boshqa joyda chiqdi (diagnostika yo'qligi; qoidaning
bazada emasligi) va o'sha tuzatildi.

### 27.4 Takrorlangan naqsh: eskirgan sinov

Uch sinov eskirgan edi va **buni hech narsa ko'rsatmasdi** — chunki
ular **yurmasdi**:

| Sinov | Nima bo'lgan |
|---|---|
| `review_butunlik_test` | fikstura 11-vazifadan beri eskirgan |
| `paid_guard_test` | ishlagan ajratgichni yiqilgan deb hisoblardi |
| `doctext_test` | **haqiqiy hujjat matnini o'chirardi** (M-1 sababi) |

Ildiz sabab **S-1** edi.

### 27.5 O'lchangan raqamlar (2026-09-01)

| Ko'rsatkich | Qiymat |
|---|---|
| Sinov to'plamlari | **33**, hammasi o'tadi |
| `deploy_test` tekshiruvlari | **193** (oldin 164) |
| Standart rejimda tekshiruvlar | **2 478** (oldin 1 951) |
| Migratsiyalar | **68** |
| Xato kodlari | **105** × 3 til |
| Embedding qamrovi | **95.9%** (ochiq tenderlar **96.7%**) |
| Talab qamrovi (ochiq) | **100%** |
| **RTO** (o'lchangan) | **405 s** |
| Zaxira | 440 MB / **5 daq 28 s** |
| Ma'lum zaifliklar | **0** |

### 27.6 Hali ochiq (8 band)

Eng muhimi: **B-1** — `deploy.sh` ning qurish qismi, Caddy/HTTPS
va systemd taymerlar HAQIQIY Linux mashinasini talab qiladi.
Tiklash yo'li (zaxira, restore, sog'liq, orqaga qaytarish) endi
**mashq qilingan**.

Qolganlari: **O-5** (HTTPS majburiy emas), **T-1** (saqlangan
qidiruvning `last_seen_at` va `categories` qismlari — `notify`
ulandi), va **K-1..K-5** (kichik bandlar).

Yopilganlar: B-2, B-3, M-1, M-2, M-3, Q-1, Q-2, Q-3, O-1, O-2,
O-3, O-4, S-1, T-2 — **14 band**.

To'liq ro'yxat: `docs/ochiq_muammolar.md`.

---

*Oxirgi yangilanish: 2026-09-02. Bu faylni yangilash qoidasi — har commit'dan
keyin emas, har QATLAM tugagandan keyin, va §18 dagi hisoblagichlarni
QAYTA O'LCHAB.*
