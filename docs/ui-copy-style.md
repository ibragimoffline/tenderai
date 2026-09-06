# INTERFEYS MATNI — USLUB QO'LLANMASI

Tender-AI va ERP interfeyslaridagi **foydalanuvchi matni** uchun qoidalar.
Backend izohlari, hujjatlar va jurnalga bu qoidalar tegishli emas — ular
boshqa auditoriya uchun yoziladi.

Manba: 2026-09-02 dagi matn tozalash ishi (`vibe-coding` matnini olib
tashlash). Misollar shu ikki loyihadan olingan.

---

## 1. Qisqa yozing, lekin ma'noni yo'qotmang

| Tur | Uzunlik |
|---|---|
| Tugma | 1–3 so'z |
| Sahifa sarlavhasi | 2–5 so'z |
| Yordam matni | bitta jumla (zarur bo'lsa ikkita) |
| Bo'sh holat | holat + keyingi qadam |
| Xato | nima bo'ldi + nima qilish kerak |

**OLDIN:** "Qoldiq alohida saqlanmaydi — u harakatlar yig'indisi. Qatorni
bosing: kim, qachon va nima uchun o'zgartirgani ko'rinadi. Mahsulot
katalogi Tender-AI da."
**KEYIN:** "Qoldiq — harakatlar yig'indisi. Qatorni oching: kim, qachon,
qancha. Katalog Tender-AI da."

---

## 2. Bitta tushuncha — bitta atama

Aralashtirmang: "Rad etish" / "Rad qilish" / "Bekor qilish".

Kelishilgan atamalar:

| Amal | Atama |
|---|---|
| Oynani yopish, formadan chiqish | **Bekor** |
| Hujjatni storno qilish (faktura, akt) | **Bekor qilish** |
| Yo'naltirishda rad javobi | **Rad etish** |
| Yozuvni bazadan o'chirish | **O'chirish** |

---

## 3. Ichki mexanizmni emas, natijani yozing

Foydalanuvchi ekranida bo'lmaydi: `SQL`, `endpoint`, `trigger`, `kesh`,
`backend`, `NULL`, `HTTP 500`, `jsonb`, `embedding`, port raqami, ichki
model nomi.

**OLDIN:** "Jurnalni bazaning o'zi yozadi (trigger), ERP kodi emas — qo'lda
yozilgan SQL ham shu yerga tushadi."
**KEYIN:** "Jurnalni baza o'zi yozadi: uni chetlab o'tib ham, yozuvni
o'zgartirib ham bo'lmaydi."

**OLDIN:** "Backend ishlayaptimi? (:8000)"
**KEYIN:** "Server javob bermayapti."

**Istisno:** administrator diagnostikasi. Migratsiya nomi (`schema_patch_
erp_18.sql`) admin ekranida qoladi — uni aynan administrator qo'llaydi.
Lekin `psql` buyrug'ining o'zi ekranga chiqmaydi, u hujjatda.

---

## 4. Hissiy va suhbat ohangi yo'q

Emoji yo'q. "Ajoyib!", "Hammasi muvaffaqiyatli bajarildi 🎉" — yo'q.
"Import yakunlandi" — ha.

### 4.1. BOSH HARF bilan BAQIRMANG

Gap o'rtasidagi bosh harfli so'z — urg'u emas, baqiriq. Urg'u kerak
bo'lsa u **belgilash bilan** (`<b>`, rang, `Badge`) beriladi, matn
bilan emas. Ekran o'quvchi bunday so'zni harflab o'qishi mumkin.

**OLDIN:** "Moslik hali O'LCHANMAGAN — broker qarorlari yig'ilgach chiqadi."
**KEYIN:** "Moslik hali o'lchanmagan — broker qarorlari yig'ilgach chiqadi."

**OLDIN:** "Cheklist hujjat BORLIGINI va MUDDATINI tekshiradi…"
**KEYIN:** "Cheklist hujjat borligini va muddatini tekshiradi…"

Diqqat: **ma'no yo'qolmaydi** — so'zlar joyida qoladi, faqat registr
o'zgaradi. `broker.sampleTitle` allaqachon `<b>` ichida chiqardi, ya'ni
bosh harf ortiqcha edi.

**Istisno — qisqartmalar:** `ERP`, `ETL`, `QQS`/`НДС`/`VAT`, `ISO`,
`CSV`, `UTF-8`, `SMTP_HOST`, `TELEGRAM_BOT_TOKEN`. Bular atama, baqiriq
emas.

**Holat yorlig'i (`Badge`) ham gap kabi yoziladi.** Bir loyihada ikki xil
uslub bo'lmasin:

| Kalit | Uslub |
|---|---|
| `gonogo.status.*` | `Bajariladi`, `Xavf bor` |
| `compliance.status.*` | `Bazada bor`, `Muddati tugagan` |
| `broker.status.*` | `O'tdi`, `Xavf`, `To'siq`, `Ma'lumot yo'q` |

`broker.status.*` ilgari yagona BOSH HARFLI to'plam edi
(`O'TDI` / `ПРОШЛО` / `PASS`) va `MA'LUMOT YO'Q` bilan
`gonogo.status.unknown` = `Ma'lumot yo'q` aynan bir xil so'zlar,
ikki xil registrda edi.

---

## 5. Takrorlamang

Sarlavha, izoh va matn bir narsani uch marta aytmasin.

**OLDIN (karta):** "Hisobingiz hodimga bog'lanmagan — shuning uchun
"mening kartalarim" bo'sh. Administratordan hisobni hodimga bog'lashni
so'rang." (yuqorida banner allaqachon shuni aytadi)
**KEYIN:** "Hisobingiz hodimga bog'lanmagan — kartalaringiz ko'rinmaydi."

---

## 6. Tugma amalni aytsin

Yomon: "Yuborish", "Davom etish", "Bosish".
Yaxshi: "Import qilish", "So'rash", "Tasdiqlash", "Rad etish", "Saqlash".

**OLDIN:** "Yuborish" (qayta taqsimlash so'rovi)
**KEYIN:** "So'rash"

---

## 7. Noaniqlikni ishonchga aylantirmang

AI va mashina natijasi haqida: "AI aniqladi", "AI to'g'ri topdi" — yo'q.

Ishlatiladigan iboralar: **AI tavsiyasi**, **taxminiy moslik**,
**tekshirish tavsiya etiladi**, **ko'rilmagan**, **tekshirilmagan**,
**ma'lumot yetarli emas**, **aniqlanmadi**.

Tender-AI da bu qoida ikki joyda ayniqsa muhim:

* tahlildagi **talab** — odam tasdiqlamagan bo'lsa "ko'rilmagan" yorlig'i
  bilan chiqadi;
* **ishonch darajasi** — `aktor_elon` "e'lon qilingan" deb ko'rsatiladi,
  "tasdiqlangan" deb emas.

---

## 8. Ogohlantirishda oqibat bo'lsin

Bitta gap + oqibat + harakat.

**OLDIN:** "Rezerv "Qatnashish tasdiqlandi" bosqichidan boshlab qo'yiladi.
Yakuniy statusda esa avtomatik yopiladi: yutilsa — chiqimga aylanadi,
yutqazilsa — bo'shaydi."
**KEYIN:** "Yutilganda chiqimga aylanadi, yutqazilganda bo'shaydi."

---

## 9. Qisqartirilmaydigan matnlar

Quyidagilar **qisqartirilmaydi** (aniqlashtiriladi, lekin ma'no
to'liq qoladi):

* qaytarib bo'lmaydigan amal tasdig'i (hujjat stornosi, karta yakuni);
* xavfsizlik ogohlantirishi (parol, sessiya, huquq);
* huquqiy va soliq bilan bog'liq izoh ("bu shakl yuridik hujjat emas");
* ma'lumot sifati qoidasi ("muddat bo'sh — muddatsiz deb olinadi");
* AI/mashina natijasining noaniqligi;
* nima uchun amal bajarilmagani (sabab).

---

## 10. Uch til — bir xil hajm

Kalit o'zgarsa `uz`, `ru`, `en` **birga** o'zgaradi. Bir til ikkinchisidan
sezilarli uzun bo'lib qolmasin; so'zma-so'z tarjima shart emas —
tabiiyroq qisqa ibora afzal.

Tekshirish (ikkalasi ham majburiy):

```
npx tsc -b --noEmit          # kalit yetishmasa xato beradi
npm run build
```

`uz.ts` — manba lug'at; `ru.ts` va `en.ts` `Record<keyof typeof uz, string>`
deb e'lon qilingan, shuning uchun kalit tushib qolsa kompilyator
to'xtatadi. O'zgaruvchilar (`{n}`, `{lang}`) uch tilda **bir xil** bo'lishi
kerak.

---

## 11. Tipografiya

* Uch nuqta emas, **bitta belgi**: `…` (`...` emas). Kutish holati va
  davomi bor amal shu belgi bilan tugaydi — "O'ylayapman…",
  "Yuklanmoqda…", "Nomini o'zgartirish…".
* Qo'shtirnoq: `«…»` (ru/uz) va `“…”` (en) — to'g'ri qo'shtirnoq `"`
  ishlatilmaydi.
* O'lchov birligi raqamdan **uzilmaydi**: `10 MB`, `7 kun`.

---

## 12. Kalit takrorlanmasin

Bir xil matn ikki kalitda turgan bo'lsa, ular **bir xil** bo'lib
qolishi kerak — biri o'zgarib, ikkinchisi qolib ketmasin.

Hozirgi ataylab takrorlanadiganlar (server xatosi + ekran matni):

| Ekran kaliti | Server xato kaliti |
|---|---|
| `aktor.required` | `err.ACTOR_REQUIRED` |

`en` da bular bir vaqtlar `pick one` va `select one` bo'lib ketgan edi —
bitta ma'no, ikki ibora. Endi ikkisi ham `select one`.

Tekshirish: `node` bilan lug'atdagi bir xil qiymatli kalitlarni sanash
(`docs/` dagi audit skripti) yoki qo'lda `grep`.
