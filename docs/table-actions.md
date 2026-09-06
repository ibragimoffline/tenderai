# JADVAL AMALLARI — AUDIT

> **Sana:** 2026-09-03
> **Usul:** har ekran KOD bo'yicha tekshirildi (`api.*` chaqiruvlari,
> umumiy komponentlar, baza cheklovlari). Hujjatga emas, kodga
> qaralди — hujjat eskirgan bo'lishi mumkin.
>
> **Belgilar:** `EXISTED` — bor edi · `ADDED` — shu ishda qo'shildi ·
> `NOT NEEDED` — biznes amali yo'q · `BLOCKED` — qaror yoki
> backend yetishmaydi.

---

## 0. Asosiy topilma — QATTIQ O'CHIRISH INSON QARORINI YO'Q QILADI

```
catalog_product_code -> catalog_product   ON DELETE CASCADE
```

`api.deleteProduct` mahsulotni o'chirganda uning kodlash yozuvi ham
ketadi — `tasdiqlandi`, `tasdiq_actor_id`, `tasdiq_ishonch`,
`qaror_id` bilan birga. **Hozir 1 048 mahsulotda tasdiqlangan kod
bor.**

Himoya ASSIMETRIK va zaif tomoni foydalanuvchi bosadigan tomon:

| yo'nalish | himoya |
|---|---|
| kodni tasdiqlagan **aktorni** o'chirish | `ON DELETE RESTRICT` — **to'silgan** |
| kodlangan **mahsulotni** o'chirish | `ON DELETE CASCADE` — **ochiq** |

`kod_qaror` dagi qaror yozuvi omon qoladi (`qaror_id ... ON DELETE
SET NULL`), lekin u endi QAYSI mahsulotga tegishli ekanini
ko'rsatmaydi — ya'ni qaror bor, predmeti yo'q.

**Holat: BLOCKED.** Tuzatish arxiv mexanizmini talab qiladi
(`catalog_product.arxivlandi_at` + ro'yxatdan chiqarish), va u
mahsulot qarori: bu ishda YARIM qilinmadi, chunki yarim arxiv
qattiq o'chirishdan yomonroq bo'lardi. Qaror kerak: arxiv
qo'shiladimi yoki kodlangan mahsulotni o'chirish taqiqlanadimi.

`company_document` da bunday xavf **yo'q** — unga bog'langan qaror
jadvali yo'q.

---

## 1. Yakuniy matritsa

| Ekran | Search | Filter | Sort | View | Edit | Delete/Archive | Domen amali | Sinov |
|---|---|---|---|---|---|---|---|---|
| **TenderTable** | EXISTED | EXISTED | EXISTED | EXISTED | NOT NEEDED | NOT NEEDED | NOT NEEDED | BLOCKED |
| **CatalogView** | NOT NEEDED | EXISTED | NOT NEEDED | EXISTED | EXISTED | **BLOCKED** | create/update | BLOCKED |
| **KodNavbat** | EXISTED | NOT NEEDED | NOT NEEDED | EXISTED | NOT NEEDED | NOT NEEDED | kod / talabsiz / dalilsiz / o'tkazish | BLOCKED |
| **RequirementReview** | NOT NEEDED | EXISTED | NOT NEEDED | EXISTED | EXISTED | NOT NEEDED | approve / reject / correct / **bulk** | BLOCKED |
| **BrokerQueue** | NOT NEEDED | EXISTED | NOT NEEDED | EXISTED | NOT NEEDED | NOT NEEDED | olindi / rad / kutilsin / qayta hisob | ADDED (darvoza) |
| **CompanyDocuments** | EXISTED | EXISTED | NOT NEEDED | EXISTED | EXISTED | EXISTED | create/update/delete | BLOCKED |
| **SavedSearch** | — | — | — | — | — | — | — | **BLOCKED** |
| **Telegram obunachilar** | NOT NEEDED | NOT NEEDED | NOT NEEDED | EXISTED | EXISTED | EXISTED | test yuborish / havola | BLOCKED |
| **Analitika (v_*)** | NOT NEEDED | NOT NEEDED | NOT NEEDED | EXISTED | NOT NEEDED | NOT NEEDED | — | BLOCKED |

`Sinov` ustunidagi `BLOCKED` — xatti-harakat sinovi hali yozilmagan
(frontend xulq qamrovi 14 ekrandan 1 tasida). Bu "kerak emas"
EMAS, "hali yo'q".

---

## 2. Ekran bo'yicha dalil

### TenderTable
- Qidiruv, filtr, saralash va sahifalash **`TenderTable.tsx` da EMAS** —
  ular `App.tsx` + `Filters.tsx` + `Pagination.tsx` da. Faylni yakka
  o'qiganda "qidiruv yo'q" degan noto'g'ri xulosa chiqadi.
- Saralash: `close_at`, `-totalcost`, `-publicated_at` (`Filters.tsx`).
- Filtr tozalash: **bor** (`onReset` -> `DEFAULT_FILTERS`).
- URL holati: faqat `?tender=<id>` deep-link. Filtrlar URL ga
  **yozilmaydi** — sahifa yangilanganda tanlov yo'qoladi. `NOT NEEDED`
  emas, `BLOCKED`: bu qulaylik, lekin biznes invariantiga tegmaydi.
- Qatorda o'chirish/tahrir **yo'q va bo'lmasligi kerak**: tender —
  manba ma'lumoti, biz uni faqat o'qiymiz.

### CatalogView
- `api.createProduct` / `updateProduct` / `deleteProduct`.
- Sahifalash **bor** (`Pagination`), tasdiqlash dialogi **bor**.
- O'chirish — yuqoridagi 0-bo'lim. **BLOCKED.**

### KodNavbat
- `api.kodQidir` — qidiruv **bor** va u domen amali (muqobil kod
  izlash), oddiy jadval filtri emas.
- Amallar: `kod` / `talabsiz` / `dalilsiz` / `otkazildi` — to'rttasi
  ham `kod_qaror` ga yoziladi va `actor_id` + `ishonch` bilan
  atributlanadi.
- Pilot ko'rsatkichi ekranda **bor** (`Pilot: N/40 atama`) va u
  2026-09-03 dan boshlab FAQAT atributlangan qarorlarni sanaydi
  (migratsiya 0078) — ilgari anonim qarorlar ham maqsadga kirardi.

### RequirementReview
- `api.talabReview` (bitta) va `api.talabReviewAll` (**ommaviy**).
- Ommaviy amal ham atributlanadi: `main.py` `ruxsat(k, ...)` va
  `actor_id=k.actor_id, ishonch=k.ishonch` uzatadi.
- `approve` / `reject` / `corrected` — uchalasi bor, `uncertain` ham.
- O'chirish **yo'q va bo'lmasligi kerak**: talab ko'rigi — inson
  qarori, u faqat qo'shiladi.

### BrokerQueue
- `api.brokerQaror` (olindi/rad/kutilsin), `brokerOch` (ochish),
  `brokerYangila` (AI ni qayta hisoblash).
- **OCHISH QAROR EMAS** — `brokerOch` `qaror_ishonch` yozmaydi.
  Bu invariant darvoza hisoblagichida ham saqlanadi.
- `DarvozaProgress` **ADDED** (bu ishda) — "18 / 50" ekranda.

### CompanyDocuments
- CRUD to'liq, tasdiqlash dialoglari bor.
- Hujjat — kompaniya artefakti, qaror emas; qattiq o'chirish o'rinli.

### SavedSearch — **BLOCKED**
- Alohida komponent **yo'q**; `App.tsx` `api.searches()` ni o'qiydi.
- `saved_search` jadvalida **0 qator** (o'lchandi). Ya'ni xususiyat
  hech qachon ishlatilmagan.
- Jadval amallari qo'shish **erta**: ishlatilmagan xususiyat ustiga
  interfeys qurish — `UPDATED.md` §18 saboqining aynan takrori.

### Telegram obunachilar
- `telegramSetSubscriber` / `telegramDeleteSubscriber` / `telegramTest`.
- Obunachi — sozlama, qaror emas; o'chirish o'rinli.

### Analitika ko'rinishlari
- `v_*` ko'rinishlari faqat o'qish uchun. Jadval amallari **kerak emas**;
  ular ustidan amal qilish ma'lumot manbasini buzardi.

---

## 3. Asboblar paneli standarti — hozirgi holat

Talab qilingan shakl:

```
[ Qidiruv ] [Filtrlar] [Saralash]                    [Asosiy amal]
```

`TenderTable` shu shaklga **mos** (`App.tsx` toolbar + `Filters`).
Qolgan ekranlar bitta maqsadli navbat va ularda to'liq panel
KERAK EMAS — ular jadval emas, ish navbati.

## 4. Buzuvchi amal matni

`CatalogView` va `CompanyDocuments` da tasdiqlash dialogi bor.
Matn ANIQ bo'lishi shart ("Mahsulot o'chirilsinmi?"), umumiy
"Ishonchingiz komilmi?" emas. Bu `docs/ui-copy-style.md` qoidasi
bilan bir xil va u yerda tekshiriladi.

## 5. Qo'shilmagan amallar — ataylab

| amal | nega yo'q |
|---|---|
| Export | biznes so'rovi yo'q; CSV eksporti ma'lumotni tashqariga chiqaradi va huquqiy tekshiruvga bog'liq |
| Bulk delete | inson qarori ustida ommaviy o'chirish — eng xavfli kombinatsiya |
| Retry | faqat ETL da ma'noli, u yerda `keyingi_urinish_at` bilan avtomatik |
| History (qator bo'yicha) | `audit_jurnal` da bor, lekin qatorga bog'langan ko'rinish hali yo'q — `BLOCKED` |
