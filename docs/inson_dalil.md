# Inson tasdig'i — dalil bilan, yorliq bilan emas

**Xulosa:** loyihada inson validatsiyasi **hali yo'q**. Ilgari
"bor" deb ko'rsatilgan raqam tekshirildi va u **mashina chiqishi**
edi. Endi hisoblagich halol va yo'l ochiq, lekin **qaror soni
noldan boshlanadi**.

O'lchov sanasi: **2026-09-02**.

---

## 1. O'lchangan nuqson

Tayyorlik auditi "inson halqasi kod tasdig'ida **73.4%** to'lgan"
deb ko'rsatardi. Raqam `catalog_product_code.tasdiqlandi` dan
kelardi. Tekshirilganda:

| `tasdiqlagan` | qator | turli sekund | tezlik |
|---|---|---|---|
| `kompaniya` | 581 | 2 | ~290 qator/sek |
| `tizim:auto` | 467 | 14 | ~34 qator/sek |
| **jami** | **1 048** | **16** | — |

1 048 ta "tasdiq" atigi **16 ta turli sekundda** yozilgan. Ikkala
tezlik ham inson uchun mumkin emas. Ustiga:

- `tasdiqlagan` da atigi **ikki** qiymat bor va ikkalasi ham odam
  nomi emas (`tizim:auto` — so'zma-so'z "tizim");
- 1 048 tasining **hammasida** `qaror_id IS NULL`, ya'ni hech biri
  inson qaroriga bog'lanmagan;
- `kod_qaror` jadvalining o'zida **0 ta** qator.

> **Mashina chiqishi inson tasdig'i sifatida sanalgan edi.**

### Nega yuz berdi: ikki yozuv yo'li

```
/kod/qaror                 -> kod_qaror (aktor, ishonch, audit)
/catalog/{id}/kod-tasdiq   -> catalog_product_code (faqat MATN)
```

Ikkinchisi `tasdiqlagan` ustuniga **istalgan bo'sh bo'lmagan
satrni** qabul qilardi. Bazadagi yagona qo'riqchi
(`catalog_product_code_tasdiq_odam`) aynan shu kuchsiz shartni
tekshirardi. **"Bo'sh bo'lmagan satr" odam degani emas.**

`/catalog/{id}/kod-rad` esa umuman kimlik so'ramasdi — "kim rad
etdi" savoli javobsiz edi.

---

## 2. Uch daraja — qo'shilmaydi

| Daraja | Ma'nosi | Darvozada sanaladimi |
|---|---|---|
| `aktorli` | `erp_sessiya` / `aktor_elon` — **qaysi odam** ma'lum | **ha** |
| `anonim` | `kompaniya_sessiyasi` — odam, lekin shaxsan noma'lum | yo'q |
| `mashina` | `servis` / `kuzatuvdan_oldin` — **inson emas** | yo'q |

Ilgari uchalasi bitta raqamga qo'shilardi. Ajratilmasa yana
o'sha xato takrorlanardi.

**Avtomatika taqiqlanmadi.** U yoza oladi, lekin `servis` deb
belgilanadi va inson ulushiga kirmaydi. Bu taqiq emas —
**oshkoralik**.

---

## 3. Hozirgi holat (o'lchangan)

| Qatlam | jami | **aktorli** | anonim | mashina | navbatda |
|---|---|---|---|---|---|
| kod tasdig'i | 1 427 | **0** | 0 | 1 048 | 379 |
| talab ko'rigi | 11 099 | **0** | 0 | 0 | 8 445 |
| yo'naltirish | 310 | **0** | 1 | 30 | 279 |

Ma'lumot **o'chirilmadi**. 1 048 bog'lanish joyida qoladi va
moslashtirish avvalgidek ishlaydi — ular **yaroqsiz emas**, ular
**inson qarori emas**.

`kompaniya` importidagi 581 qator `servis` deb ham
**belgilanmadi**: uning manbasi aniq emas. Ular
`kuzatuvdan_oldin` — loyihaning mavjud "manbasi noma'lum"
yorlig'i. **UNKNOWN — UNKNOWN bo'lib qoladi.**

---

## 4. Sifat darvozasi

Uch holat **bir-birini almashtirmaydi**:

| Holat | Ma'nosi |
|---|---|
| `AMALGA_OSHIRILDI` | kod bor |
| `SINALDI` | avtomatik sinov o'tadi |
| `INSON_TASDIQLADI` | yetarli sondagi **aktorli** qaror bor |

### Eng kam namuna

| Qatlam | eng kam | sabab |
|---|---|---|
| kod tasdig'i | **40** | mavjud pilot maqsadi (`v_kod_pilot`) |
| talab ko'rigi | **200** | atribut turlari bo'yicha tarqalishi kerak |
| yo'naltirish | **50** | 2×2 matritsaning har katagi bo'sh qolmasin |

> Bu raqamlar **siyosat, statistika emas**. Ular ishonch
> oralig'idan chiqarilmagan — bu "shu qatlamni baholash uchun eng
> kami" degan muhandislik qarori.

Chegaradan o'tmagan qatlam uchun `v_sifat_darvoza` **foiz
qaytarmaydi** (`ulush_foiz = NULL`). 3 ta qarordan "67% aniqlik"
chiqarish yolg'on aniqlik bo'lardi.

---

## 5. Pilot: nima to'sib turibdi

`v_pilot_tayyorlik` sababni aytadi. **O'lchandi:**

| kompaniya | aktor | faol |
|---|---|---|
| **2 (asosiy)** | **0** | **0** |
| 199 | 1 | 0 |
| 200 | 4 | 0 |
| 271 | 2 | 0 |
| 272 | 1 | 0 |

Interfeys `X-Actor` sarlavhasini **yuboradi**
(`frontend/src/api.ts`), lekin tanlash uchun ro'yxat **bo'sh**.
Natijada har qaror `kompaniya_sessiyasi` darajasida yoziladi —
odam qildi, lekin **qaysi odam ekani noma'lum**, va darvoza uni
sanamaydi.

Bu holat **jimgina** yuz berardi: ko'ruvchi ishlaydi, qarorlar
yoziladi, hisoblagich 0 da turadi. Endi `tosiq` ustuni buni
oldindan aytadi.

### Pilotni ishga tushirish (SQL kerak emas)

1. **Aktor qo'shish** — `POST /aktor` (`sozlama` huquqi bilan).
   Rol `koruvchi` yoki `tasdiqlovchi` bo'lsin; `kuzatuvchi`
   qaror qo'ya olmaydi.
2. **Ko'ruvchi aktorni tanlaydi** — interfeys uni `X-Actor` da
   yuboradi.
3. **Qaror qo'yish:**
   - kodlash: `POST /kod/qaror/ochish` -> `POST /kod/qaror`
   - talab: `POST /requirements/{id}/review`
   - yo'naltirish: `POST /routing/{id}/decision`
4. **Kuzatish** — `GET /validatsiya/holat`.

Aktor yaratish **ma'muriy amal** (haqiqiy odam ismi). Migratsiya
aktor **yaratmaydi** va bu ataylab.

---

## 6. Ko'ruvchi qila oladigan amallar

| Amal | Kodlash | Talab | Yo'naltirish |
|---|---|---|---|
| Tasdiqlash | `kod` | `approved` | `olindi` |
| Rad etish | `talabsiz` | `rejected` | `rad` |
| Tuzatish | qayta kod | `corrected` | — |
| **Shubha** | `dalilsiz` | **`uncertain`** | `kutilsin` |
| O'tkazish | `otkazildi` | — | — |
| Muqobil qidirish | `GET /kod/qidir` | — | — |
| Izoh / dalil | `izoh`, `dalil` | `note` | `inson_izoh` |

### `uncertain` nega qo'shildi

Talab ko'rigida faqat `approved` / `rejected` / `corrected` bor
edi. Ishonchi komil bo'lmagan ko'ruvchi **majburan** uchtasidan
birini tanlardi va amalda shubha `approved` bo'lib yozilardi —
u eng kam qarshilikli tugma. Bu o'lchovni **jimgina** buzardi:
aniqlik yuqori ko'rinardi.

`uncertain` **ham inson qarori**: aktor, vaqt va amal shu
darajada majburiy. U "ko'rilmagan" degani **emas**.

---

## 7. Audit

Har inson qarori `audit_jurnal` ga yoziladi: ijarachi, aktor,
ishonch darajasi, amal, obyekt, **eski qiymat**, yangi qiymat,
izoh, vaqt. Jadval **append-only** (trigger bilan) — tarixiy
qaror ustiga yozib bo'lmaydi.

`/catalog/{id}/kod-tasdiq` va `/kod-rad` ilgari audit
**yozmasdi**; endi yozadi.

---

## 8. Metrikalar

| Qatlam | Ko'rinish | Nima beradi |
|---|---|---|
| Kodlash | `v_kod_qaror_olchov` | ko'rilgan soni, taklif qabuli, o'zgartirilgan, dalilsiz |
| Talab | `v_review_disagreement` | ishonch darajasi bo'yicha kelishmovchilik |
| Talab | `v_requirement_review` | tasdiq/rad/tuzatish taqsimoti |
| Yo'naltirish | `v_routing_kelishuv` | to'liq 2×2 matritsa + `kutilsin` |
| Hammasi | `v_inson_dalil` | dalil darajasi bo'yicha ajratma |
| Hammasi | `v_sifat_darvoza` | chegara va holat |
| Hammasi | `v_pilot_tayyorlik` | to'siq nima |

API: `GET /validatsiya/holat`.

---

## 9. Sinov

`_tests/inson_dalil_test.py`:

| Bo'lim | Nimani tekshiradi |
|---|---|
| 1 | mashina va inson ustunlari ALOHIDA |
| 2 | baza cheklovlari mavjud |
| 3 | cheklovlar **haqiqatan rad etadi** (mavjudligi yetarli emas) |
| 4 | ko'ruvchining barcha amallari bor |
| 5 | audit to'liq va **o'zgarmas** |
| 6 | metrik ko'rinishlar **haqiqatan yuradi** |
| 7 | kichik namunadan foiz **chiqmaydi** |
| 8 | inson qarori **ilova orqali** to'liq kiritiladi |
