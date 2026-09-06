# Saqlangan qidiruv — holat va chegara

**Xulosa:** CRUD **ishlaydi** va interfeysda **topiladi**.
`notify` **2026-09-01 da ulandi** (T-1). Qolgan **ikki** qism
**KEYINGA QOLDIRILGAN** va ular ishlayotgandek ko'rsatilmaydi.

O'lchov sanasi: **2026-09-02**. Bazadagi `saved_search` qatorlari:
**1 ta**.

> **BIRINCHI HAQIQIY ISHLATISH** (2026-09-02). Asosiy kompaniyada
> bitta qidiruv saqlangan ("Kompyuter test"). Bu sinov qoldig'i
> emas — sinov hisoblari `zz` prefiksi bilan yuradi va tozalanadi.
> Ya'ni "0 ta ishlatish" davri tugadi, lekin **bitta** qator hali
> hech narsani isbotlamaydi: u imkoniyat topilishini ko'rsatadi,
> foydali ekanini emas.

---

## 1. Nol ishlatishning ikki ma'nosi

Nol yoki bir qator ikki xil narsani anglatishi mumkin va ular
aralashtirilmasin:

| Ma'no | Kim hal qiladi |
|---|---|
| "kerak emas ekan" | mahsulot qarori |
| "ishlamaydi yoki topilmaydi" | muhandislik nuqsoni |

`_tests/saved_search_test.py` ikkinchisini **inkor etadi**: yaratish,
o'qish, tahrirlash, o'chirish, ijarachi ajratilishi va filtr
saqlanishi **haqiqiy HTTP so'rovlar** bilan tekshiriladi. Shundan
keyingina nol ishlatish mahsulot savoli bo'lib qoladi.

> Nol ishlatish **muvaffaqiyatli qabul EMAS**. Bu hujjat aynan shu
> xulosa chiqmasligi uchun yozilgan.

---

## 2. Ishlaydigan qism

| Amal | Yo'l | Holat |
|---|---|---|
| Yaratish | `POST /searches` | ishlaydi |
| Ro'yxat + mos tenderlar soni | `GET /searches` | ishlaydi |
| Tahrirlash (**qisman**) | `PUT /searches/{id}` | ishlaydi |
| O'chirish | `DELETE /searches/{id}` | ishlaydi |
| Qo'llash ("bajarish") | interfeys, `applySearch()` | ishlaydi |

**Interfeysda topiladi:** yon panelda `Saqlangan qidiruvlar` bo'limi,
yonida `+` tugmasi, har element ustida tahrirlash va o'chirish.
Bo'sh holatda `nav.noSearches` matni ko'rinadi.

**Ijarachi ajratilishi baza darajasida:**

```
company_id NOT NULL
company_id -> company_account(id) ON DELETE CASCADE
```

Har SQL `WHERE company_id = %(company_id)s` bilan cheklangan. Sinov
ikkinchi ijarachi nomidan o'qish, tahrirlash va o'chirishga urinadi
— uchalasi ham **404** beradi.

---

## 3. KEYINGA QOLDIRILGAN — saqlanadi, lekin HECH NARSA QILMAYDI

`notify` **2026-09-01 da ulandi** (§3.1). Qolgan **ikkitasi**
jadvalda va API javobida **bor**, ya'ni "tayyor"dek ko'rinadi,
lekin ulanmagan:

### 3.1 ~~`notify`~~ — ULANDI (2026-09-01, T-1)

Bayroq endi **haqiqatan ishlaydi**. `api/notify.py` har nomzodni
`company_profile` bilan bir qatorda **`notify` yoqilgan har
saqlangan qidiruv** bilan ham skorlaydi.

| Xossa | Qaror |
|---|---|
| Skorlash mantig'i | **ayni** `matching.score_tender()` — ikkinchi mantiq yozilmadi |
| Ball | eng yuqorisi yutadi (katalog/profil bilan bir xil qoida) |
| Sabab | xabarda **qaysi qidiruv** ekani yoziladi (`reason.savedSearch`) |
| Manba yorlig'i | `by.search` (uz/ru/en) |
| Filtr | `notify = TRUE` bo'lganlari, ijarachi shartida |

**O'lchandi:** kalit so'zi mos qidiruv tenderni **0 → 80** ballga
ko'taradi va sabab qidiruv nomini aytadi.

**Eski yo'l saqlandi:** `company_profile` avvalgidek ishlaydi.
Qidiruv profildan kuchli bo'lsa uning **o'rnini egallaydi** —
ikkalasini qo'shish bir xil dalilni ikki marta sanash bo'lardi.

Interfeysda bayroq **hali ko'rsatilmaydi** (shakl uni yubormaydi,
standart `true`) — bu keyingi qadam.

### 3.2 `last_seen_at`

Ustun bor, lekin uni to'ldiradigan yo'l **yo'q**. "Oxirgi ko'rgandan
keyingi yangi moslar" belgisi mavjud emas.

Uni to'ldiradigan `SEARCH_SEEN_SQL` `api/queries.py` da **bor edi**,
lekin **chaqiruvchisi yo'q edi** — o'lik SQL "imkoniyat bor" degan
yolg'on taassurot berardi. U **olib tashlandi**. Ustun jadvalda
qoldi (ma'lumot yo'qotmaslik uchun).

### 3.3 `categories`

Saqlanadi va API javobida qaytadi, lekin **skorlashda ishlatilmaydi**:
`_search_to_profile()` faqat `keywords`, `regions`, `currency`,
`min_cost`, `max_cost` ni uzatadi. Interfeys shakli ham kategoriya
tanlagichini ko'rsatmaydi.

---

## 4. Tuzatilgan nuqsonlar (2026-09-01)

### 4.1 Tahrirlash berilmagan maydonni JIMGINA tozalardi

`ProfileForm.tsx` shakli `categories` va `notify` ni **yubormaydi**.
`PUT` esa to'liq almashtirish edi, ya'ni pydantic standart qiymatlari
(`[]` va `true`) bazaga yozilardi. Foydalanuvchi nomni o'zgartirsa,
kategoriyalari **yo'qolardi** va buni hech qayerda ko'rmasdi.

Endi `SavedSearchPatchIn` — har maydon ixtiyoriy, `exclude_unset=True`
bilan joriy qiymat ustiga qo'yiladi. Bu `notify_settings` dagi bilan
bir xil naqsh (u yerda `{"enabled": false}` yuborish SMTP sozlamasini
o'chirib yuborardi).

### 4.2 O'chirish xatosi yashirilardi

```ts
try { await api.deleteSearch(s.id) } catch { /* ignore */ }
```

O'chirish muvaffaqiyatsiz bo'lsa ham interfeys "o'chdi" deb
ko'rsatardi, ro'yxat yangilanganda element **qayta paydo bo'lardi** —
sababsiz. Endi xato ko'rsatiladi va ro'yxat yangilanmaydi.

---

## 5. Nima qilish kerak (agar imkoniyat davom ettirilsa)

Tartib — qiymati bo'yicha:

1. ~~**`notify` ni ulash**~~ — **BAJARILDI** (2026-09-01, §3.1).
   Bu imkoniyatning **asosiy qiymati** edi: "shu filtrga mos tender
   chiqsa xabar ber".
2. **Interfeysda `notify` tugmasi.** Bayroq ishlaydi, lekin shakl
   uni yubormaydi (standart `true`). Foydalanuvchi uni **o'chira
   olmaydi**.
3. **`last_seen_at`.** "Ko'rildi" endpointi + yon panelda yangi
   moslar soni.
4. **`categories`.** Skorlashga qo'shish va shaklga tanlagich.

Har ulanish qo'shilganda `_tests/saved_search_test.py` dagi
6-bo'lim **yiqiladi** — u hozirgi holatni ataylab qulflaydi va
hujjatni yangilashga majbur qiladi. `notify` da aynan shunday
bo'ldi.

---

## 6. Sinov

`_tests/saved_search_test.py`:

| Bo'lim | Nimani tekshiradi |
|---|---|
| 1 | har SQL ijarachi bilan cheklangan, o'lik SQL yo'q, qisman yangilash |
| 2 | shu hujjat bor va bajarilmagan qismlarni aniq nomlaydi |
| 3 | interfeysda topiladi, o'chirish xatosi yashirilmaydi |
| 4 | bazadagi son hujjatdagi bilan mos, chegara baza darajasida |
| 5 | **haqiqiy CRUD** + ijarachi ajratilishi + filtr saqlanishi |
| 6 | `notify` **ulanganini** HAQIQIY skorlash bilan isbotlaydi; `last_seen_at` hali ulanmaganini qulflaydi |
