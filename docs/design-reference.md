# DIZAYN ETALONI — QAYSI TIZIMGA TAYANAMIZ

Manba: [`voltagent/awesome-design-md`](https://github.com/voltagent/awesome-design-md)
(73 ta `DESIGN.md`, MIT).

Tanlangan etalon: **`design-md/linear.app/DESIGN.md`**

---

## 1. Nega aynan Linear

Etalon "chiroyli ko'ringani" uchun emas, **domen modeli mos kelgani**
uchun tanlandi. Tender-AI da allaqachon bor:

| Tender-AI kaliti | Linear tushunchasi |
|---|---|
| `broker.assignee` | assignee |
| `broker.priority.low/medium/high` | priority |
| `broker.due` | due date |
| `broker.status.*` | status badge |
| Yo'naltirish navbati, kodlash navbati | queue / triage |

Ya'ni bu — matn sayti emas, **kuniga o'nlab marta ochiladigan zich ish
quroli**. Linear aynan shu turdagi interfeys uchun yozilgan.

Qo'shimcha dalil: `index.css` da tanlov ALLAQACHON qilingan edi —
o'lcham pog'onasi izohida "asos 13px (Linear, Retool kabi)" deb yozilgan.
Bu hujjat shuni rasmiylashtiradi.

Ko'rib chiqilgan, lekin olinmagan variantlar: `stripe` va `posthog`
(B2B, zich — mos, lekin navbat/triage modeli yo'q), `vercel` (uning
o'zaro ta'sir qoidalari loyihada `AGENTS.md` sifatida allaqachon bor).

---

## 2. NIMA OLINMADI — palitra

Linear ning rang qiymatlari (`#5e6ad2`, `#010102`, surface 1–4)
**ko'chirilmadi**. Sabab: Tender-AI palitrasi undan kuchliroq asosga
qurilgan —

* OKLCH da, har ROL uchun yorug'lik qat'iy;
* to'yinganlik **shoshilinchlik bilan o'sadi** (`ok` C 0.016 →
  `urgent` C 0.055), shuning uchun ro'yxatda faqat bugun tugaydigani
  ko'zga tashlanadi;
* har juftlik o'lchangan: matn 4.5:1, to'ldirish 3:1 dan past emas;
* grafik seriyalari rang ko'rish buzilishiga tekshirilgan.

Tayyor palitrani ustiga yozish bu ishni **yo'q qilardi**. Etalondan
faqat **tuzilma qoidalari** olindi.

---

## 3. NIMA OLINDI

### 3.1. Chuqurlik — soya emas, SIRT va CHEGARA

> Linear: *"Depth relies on surface ladder and hairline borders — no
> drop shadows."*

Bu qoida loyihada YARIM qo'llangan edi: `button.tsx` da soyalar olib
tashlangan va sabab ham yozilgan ("zich panelda har tugma ostidagi soya
— shovqin"), lekin `card.tsx` ga o'tkazilmagan. Natijada bitta ekranda
soyasiz tugma va soyali karta yonma-yon turardi.

Olib tashlandi: `card.tsx`, `AccountSettings.tsx` (2 joy),
`LoginPage.tsx`.

**Suzuvchi qatlamlar soyani SAQLAYDI** — `popover`, `sheet`,
`confirm-dialog`, `select`, mobil yon panel. Ular haqiqatan kontent
USTIDA turadi va buni bildirishi kerak. Bu Linear qoidasiga zid emas:
u sirt pog'onasi haqida, modal qatlam haqida emas.

### 3.2. Yorliq — gap kabi, BAQIRIQ emas

`broker.status.*` yagona BOSH HARFLI to'plam edi (`O'TDI` / `ПРОШЛО` /
`PASS`), qolgan hamma holat lug'ati esa gap kabi yozilgan. Tuzatildi —
batafsil `ui-copy-style.md` §4.1 da.

### 3.3. Faqat kerakli xususiyat animatsiya qilinadi

`transition-all` ikki joyda bor edi (`progress.tsx`, `switch.tsx`).
U kelajakda qo'shilgan HAR QANDAY xususiyatni ham animatsiya qiladi —
shu jumladan `width`/`height` kabi joylashuvni qayta hisoblatadiganini.

* `progress.tsx` → `transition-transform` (u aynan `translateX` ni
  o'zgartiradi);
* `switch.tsx` ildizi → `transition-[background-color,box-shadow]`
  (thumb allaqachon to'g'ri edi).

### 3.4. Brauzer chrome rangi fon bilan mos

`<meta name="theme-color">` umuman yo'q edi. Qo'shildi va **uch joyda**
qo'lda takrorlanadi (`index.css`, `theme.tsx`, `theme-init.js`) —
ulardan biri React dan oldin ishlagani uchun CSS o'zgaruvchisini o'qiy
olmaydi.

`media="(prefers-color-scheme: …)"` ATAYIN ishlatilmadi: ilovada mavzu
tanlovi uchta holatli va `media` faqat TIZIM sozlamasini biladi —
foydalanuvchi atayin yorug'ni tanlaganda panel qora bo'lib qolardi.

Takrorlanish `colors.test.ts` da qo'riqlanadi (uch qiymat farq qilsa
sinov yiqiladi; qo'riqchining o'zi ham buzib sinab ko'rilgan).

---

## 4. Keyingi ish uchun

Etalonni **qoida manbai** sifatida o'qing, ko'chirma sifatida emas.
Har safar savol bitta: *"bu qoida zich, ko'p tilli, uzun matnli tender
jadvaliga nima beradi?"* Bermasa — olinmaydi.

Matn qoidalari alohida: [`ui-copy-style.md`](./ui-copy-style.md).
O'zaro ta'sir va qulaylik qoidalari: ildizdagi `AGENTS.md`.
