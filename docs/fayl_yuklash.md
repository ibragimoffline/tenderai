# Fayl yuklash — kompaniya hujjatlari va AI chat

**Sana:** 2026-09-06 · **Migratsiya:** `schema_patch_yuklama.sql` (`0083_yuklama`)

---

## 1. Nima uchun

`company_document.file_ref` MATN maydoni edi va u *"tashqi havola yoki
yo'l"* deb hujjatlashtirilgan. Amalda o'lchandi: **13 qatorning 13 tasida
ham** shunday turardi —

```
file:///D:/MVP%20projects/tender-ai/.runtime/company_documents/2/documents/….docx
```

ya'ni **bitta ishlab chiquvchi mashinasining mutlaq yo'li**. Uch qavat
buzilgan edi:

1. brauzer `http://` sahifadan `file://` ga o'tishni **bloklaydi** —
   havola bosilardi va **hech narsa bo'lmasdi**, xato ham chiqmasdi;
2. serverda bu yo'l umuman mavjud emas;
3. fizik fayl **asl nom** bilan yotardi, ya'ni foydalanuvchi bergan matn
   fayl tizimi yo'liga aylanardi.

Uchinchisi eng jimi: nuqson faqat kimdir havolani bosganda bilinardi.

---

## 2. Model

```
yuklama              fayl yozuvi — YAGONA haqiqat manbai
  ├── company_id     ijarachi (NOT NULL, FK)
  ├── manba_turi     company_doc | chat
  ├── original_nom   KO'RSATISH uchun (fayl tizimiga BORMAYDI)
  ├── kalit          <company_id>/<uuid>.<ext>  (brauzerga CHIQMAYDI)
  ├── sha256         butunlik
  ├── holat          holat mashinasi (pastda)
  └── arxiv_at       hard delete YO'Q

yuklama_chunk        bo'laklar + vektor (384)
chat_yuklama         fayl <-> suhbat (M:N), trigger bilan ijarachi tekshiruvi
company_document.yuklama_id → yuklama(id)
```

### Nega `doc_chunk` ga qo'shilmadi

O'lchandi (2026-09-06):

```
doc_chunk.tender_id  BIGINT NOT NULL → FK tender(id)
UNIQUE (tender_id, file_ref, chunk_no)
company_id ustuni YO'Q,  236 578 qator
```

Kompaniya faylini u yerga qo'yish uchun `tender_id` NULL bo'lishi kerak
edi — ya'ni **236 ming qatordagi cheklovni zaiflashtirish**. Bundan
tashqari `doc_chunk` **ommaviy** tender korpusi: kompaniya hujjati u
yerga tushsa, kompaniya chegarasi bo'lmagan har qanday so'rov uni
ko'rardi.

Shakl ataylab bir xil: **ayni** `chunk_text()` va **ayni** embedder
ishlatiladi, ikkinchi quvur qurilmaydi.

---

## 3. Holat mashinasi

| holat | ma'nosi | UI |
|---|---|---|
| `yuklandi` | saqlandi, navbatda | Ishlanmoqda |
| `ajratilmoqda` | matn ajratilyapti | Ishlanmoqda |
| `tayyor` | **AI ishlata oladi** | Tayyor |
| `qollab_quvvatlanmaydi` | parser formatni bilmaydi | sabab bilan |
| `oqilmadi` | skan/chizma — OCR kerak | sabab bilan |
| `yiqildi` | kutilmagan xato | sabab bilan |

**`too_large` holati ataylab YO'Q**: chegara faylni saqlashdan *oldin*
ishlaydi (`_yuklangani`), ya'ni bunday qator hech qachon yaratilmaydi.
Yaratilmaydigan holatni ro'yxatga qo'shish "bunday holat bo'lishi
mumkin" degan yolg'on berardi.

**`tayyor` yolg'on bo'la olmaydi** — bazada CHECK:

```sql
CHECK (holat <> 'tayyor' OR (matn_belgi IS NOT NULL AND matn_belgi > 0))
```

---

## 4. Xavfsizlik

| nazorat | qayerda |
|---|---|
| hajm **o'qishdan oldin** | `main._yuklangani()` — bo'laklab, oshsa darhol to'xtaydi |
| kengaytma oq ro'yxati | `yuklama.RUXSAT_EXT` |
| **magic bayt** | `etl_doc_text.sniff_magic()` |
| kengaytma↔mazmun ziddiyati | `yuklama._ext_aniqla()` → `FILE_TYPE_MISMATCH` |
| nom tozalash | `saqlash.tozala_nom()` — yo'l qismi, boshqaruv belgilari, `"` |
| generatsiya qilingan kalit | `saqlash.kalit_yasa()` — asl nom **qabul qilmaydi** |
| yo'l chiqib ketishi | `MahalliyDisk._yol()` — `commonpath`, `startswith` emas |
| ijarachi | `company_id_of(request)` + `WHERE company_id` + trigger |
| autentifikatsiyalangan yuklab olish | ommaviy URL **yo'q** |
| ZIP bomba | `etl_doc_text` — a'zolar soni, jami hajm, chuqurlik |
| `inline` faqat pdf/txt | qolganida `attachment` (saqlangan XSS) |

**404, 403 EMAS.** Begona fayl uchun ham `FILE_NOT_FOUND` qaytadi: 403
faylning *mavjudligini* tasdiqlardi va id ni taxmin qilib korpusni
sanash mumkin bo'lardi.

### Qolgan xavf — zararli dastur skaneri YO'Q

Loyihada antivirus/ClamAV infratuzilmasi mavjud emas va **bu yerda
soxta qilinmadi**. Yuklangan fayl serverda **bajarilmaydi** (statik
saqlash, `inline` cheklovi), lekin u **boshqa foydalanuvchining
mashinasiga** yuklab olinishi mumkin. Skaner qo'shilgunicha bu ochiq
xavf.

---

## 5. AI chat qamrovi

Uchta korpus **aralashmaydi** va har birining o'z tool'i bor:

| tool | qamrov | iqtibos `manba_turi` |
|---|---|---|
| `search_documents` | ommaviy tender hujjatlari | `tender` |
| `search_uploaded_file` | **shu suhbatga** yuklangan fayllar | `chat_upload` |
| `search_company_documents` | kompaniyaning o'z hujjatlari | `company_document` |

**Kompaniya hujjatlari avtomatik qidirilmaydi** — faqat foydalanuvchi
ataylab so'raganda. Aks holda u so'ramagan joyda o'z hujjati matni
javobga tushardi.

**Faqat-fayl rejimi** (§19): foydalanuvchi *"faqat shu fayl asosida
javob ber"* desa, model boshqa qidiruv tool'ini chaqirmaydi va javob
topilmasa **"yuklangan faylda topilmadi"** deydi — umumiy korpusdan
to'ldirmaydi.

### Sahifa raqami

`sahifa` **faqat PDF da va faqat ishonchli bo'lganda** to'ldiriladi.
`extract_pdf` sahifalarni `\n` bilan qo'shadi va ofset→sahifa
xaritasini saqlamaydi, shuning uchun ko'p sahifali PDF da ham `NULL`
qoladi va UI **bo'lak raqamini** ko'rsatadi. Soxta sahifa raqami
yasalmaydi.

---

## 6. Umr va o'chirish

| amal | natija |
|---|---|
| hujjat faylini almashtirish | eski `yuklama` **arxivlanadi**, yangisi `almashtirdi` bilan unga ishora qiladi |
| chatdan olib tashlash | `chat_yuklama.uzildi_at` — qator **qoladi** |
| hujjatni o'chirish | `company_document` ketadi, `yuklama` **qoladi** |

**Hech qayerda hard delete yo'q.** Sabab: fayl muvofiqlik
tekshiruvida, malakada yoki o'tgan AI javobining iqtibosida
ishlatilgan bo'lishi mumkin. Faylni yo'q qilish o'sha qarorlarning
**dalilini** yo'q qiladi.

---

## 7. Zaxira — **baza yolg'iz yetarli emas**

`pg_dump` faqat bazani oladi. Fizik fayl `UPLOAD_ROOT` da yotadi.
Ikkisi ajralib qolsa tizim eng yomon shaklda buziladi: interfeys
hujjatni "bor" deb ko'rsatadi, foydalanuvchi bosadi va **fayl
topilmaydi**.

```
deploy/bin/backup.sh        → tenderai-<muhit>-<stamp>-fayllar.tar.gz
deploy/bin/restore-test.sh  → arxiv bor-yo'qligini va sha256 ni tekshiradi
```

`backup.sh` bazadagi faol `yuklama` soni bilan arxivdagi fayl sonini
solishtiradi: bazada fayl bor-u arxiv bo'sh bo'lsa — **xato bilan
to'xtaydi**. Aks holda noto'g'ri `UPLOAD_ROOT` bilan zaxira yashil
ko'rinardi.

### `UPLOAD_ROOT` reliz ichida bo'lmasin

`deploy.sh` har relizda **yangi katalog** yasaydi. Yo'l reliz ichida
bo'lsa fayllar keyingi joylashtiruvda ko'rinmay qoladi. Ishlab
chiqarishda:

```
UPLOAD_ROOT=/var/lib/tenderai/uploads
```

`backup.sh` yo'l reliz ichida ekanini sezsa **ogohlantiradi**.

---

## 8. Sozlamalar

| o'zgaruvchi | standart | izoh |
|---|---|---|
| `UPLOAD_ROOT` | `<repo>/.runtime/uploads` | ishlab chiqarishda relizdan **tashqarida** |
| `MAX_UPLOAD_MB` | 25 | `MAX_IMPORT_MB` (5) dan **alohida** |
| `CHAT_MAX_FAYL` | 5 | bitta suhbatga |
| `CHAT_MAX_BAYT` | 60 MB | bitta suhbatga jami |
| `STORAGE_BACKEND` | `local` | noma'lum qiymat — **xato**, jim `local` ga tushmaydi |

`MAX_UPLOAD_MB` o'zgartirilsa `deploy/caddy/Caddyfile` dagi tana
chegarasi ham birga o'zgarishi kerak — aks holda so'rov ilovaga yetib
kelmaydi va foydalanuvchi tushunarsiz 413 oladi.

---

## 9. Endpointlar

```
POST   /company/documents/{id}/fayl        yuklash / almashtirish
GET    /company/documents/{id}/fayl        holat
GET    /company/documents/{id}/download    attachment
GET    /company/documents/{id}/view        inline (pdf/txt), aks holda attachment

POST   /chat/sessions                      BO'SH sessiya (fayl savoldan oldin)
POST   /chat/sessions/{sid}/fayl           yuklash + biriktirish
GET    /chat/sessions/{sid}/fayl           ro'yxat + holat
DELETE /chat/sessions/{sid}/fayl/{yid}     UZADI (o'chirmaydi)
GET    /chat/fayl/{yid}/download           attachment
```

---

## 10. Sinovlar

```
_tests/yuklama_test.py                          108 tekshiruv
frontend/src/components/ChatFayllar.xulq.test.tsx  10 tekshiruv
```

Sinov **haqiqiy** PDF va DOCX baytlarini yasaydi (`pdf_yasa`,
`docx_yasa`) — "PDF ga o'xshash bayt" emas, aks holda u parser yo'lini
emas, xato yo'lini o'lchardi.
