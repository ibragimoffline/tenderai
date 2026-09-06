---
name: grill-me
description: Bajarilgan ishni RAQIB sifatida buzishga urinish. Kod yozib bo'lgach, "tayyor" deyishdan OLDIN yurgiziladi. Bu loyihada takrorlangan o'n uch nosozlik sinfini nomma-nom qidiradi va har biriga JAVOB talab qiladi. Foydalanuvchi "grill", "so'roq qil", "buzishga urin", "tekshir o'zingni" desa ham chaqiriladi.
---

# So'roq

Siz o'z ishingizni himoya qilmaysiz. **Buzishga urinasiz.**

Boshlash nuqtasi: *"Bu o'zgarish qanday qilib JIMGINA ishlamay
qoladi — va men buni qachon bilib qolaman?"*

"Jimgina" muhim so'z. Baland yiqilgan kod muammo emas: uni jurnal
ko'rsatadi, sinov tutadi. Bu loyihada yo'qotilgan har bir hafta
**jimgina** yo'qolgan.

---

## Qoida: xulosa MUSBAT shartdan chiqsin

So'roq oxirida "muammo topilmadi" deyish — **taqiqlangan**, agar u
faqat "hech narsa ko'rmadim" ma'nosida bo'lsa.

Har bir sinf uchun ikkitadan biri yozilishi shart:

| | yoziladigan narsa |
|---|---|
| Tegishli | topilgan narsa + qayerda + qanday tekshirdim |
| Tegishli emas | **nima uchun** tegishli emasligi, bir jumla |

"Ko'rib chiqdim, yaxshi" — javob emas. Bu aynan shu skill
qidiradigan xatoning o'zi: salbiy shartdan olingan xulosa.

---

## O'n uch sinf

Bularning har biri bu loyihada **haqiqatan sodir bo'lgan**. Taxminiy
ro'yxat emas — kechirim.

### 1. Asbob o'zini o'lchaydi

O'lchov vositasi tekshirayotgan narsasining xatosini takrorlaydi va
natija chiroyli chiqadi.

> `.doc` mezoni faqat kirillni sanardi → 64% ko'rsatdi, haqiqiy
> qamrov 92% edi. `taqqosla()` faqat raqamga qarardi → 55%, haqiqiy
> 79%. `_cheklov_xatosimi()` NOT NULL ni CHECK deb yutdi.

**Savol:** o'lchovim tekshirayotgan kod bilan bir xil taxminni
ishlatadimi? Agar kod xato bo'lsa, o'lchov ham xato chiqaradimi?

**Tekshiruv:** o'lchovni QO'LDA bir necha holatda tasdiqlang.
Ikkalasi bir manbadan kelmasin.

### 2. Muvaffaqiyat SALBIY shartdan olingan

"Xato chiqmadi" ≠ "ish bajarildi".

> `ok = all(results)` post-qadamlarni ko'rmasdi. Skript `0` qaytarar,
> hech narsa qilmasdi, quvur "hammasi muvaffaqiyatli" derdi. Ikki
> hafta.

**Savol:** bu qadam ish qilganini QANDAY isbotlaydi?

**Tekshiruv:** oldin/keyin sonini o'lchang. Navbat bor edi-yu
kamaymasa — bu XATO, garchi istisno chiqmagan bo'lsa ham.
O'lchab bo'lmagan holat ham xato: o'lchovsiz da'vo asossiz.

### 3. Qadam yozilgan, ulangan, lekin CHAQIRILMAYDI

> `etl_requirement.py` yozildi, sinaldi, quvurga qo'shildi — va
> `sole_company_id()` `load_dotenv()` dan oldin turgani uchun har
> soat jimgina o'chirilardi.

**Savol:** bu kod HAQIQATAN yurdimi? Qayerdan bilaman?

**Tekshiruv:** haqiqiy muhitda yurgizing (rejalashtiruvchi muhitini
taqlid qiling: muhit o'zgaruvchisisiz, boshqa katalogdan). Jurnalda
uning izini toping. Yo'q bo'lsa — u yurmagan.

### 4. Sovuq start artefakti

"Oxirgi 24 soat" yangi tizimda BUTUN tarixni qamraydi.

> `sutkalik_osish = 604` — butun navbat. `new_24h = 118 426` — butun
> korpus. Ikkalasi ham "sur'at" deb ko'rsatilardi. Ikkinchisi
> birinchisi tuzatilgandan **bir necha soat keyin** paydo bo'ldi.

**Savol:** bu raqam ma'lumot yetarli to'planganda ham shu ma'noni
beradimi?

**Tekshiruv:** ma'lumot yoshini o'lchang. Yosh bo'lsa raqamni
yorliqlang va undan XULOSA CHIQARMANG (`None` qaytaring).

### 5. Izoh himoya deb hisoblangan

> `load_dotenv` qatorining izohida aynan o'sha xato sinfi
> tasvirlangan edi — va yangi kod uning USTIGA qo'yildi.

**Savol:** bu qoidani izoh saqlaydimi yoki struktura?

**Tekshiruv:** qoidani bajarilishga majburlang — bayroq + `assert`,
`CHECK` cheklovi, `UNIQUE` indeks, statik skaner. Izoh o'qilmaydi.

### 6. Tuzatish saqlanmaydi

Qo'lda tuzatilgan narsa keyingi qayta o'rnatishda qaytadi.

> RAG vazifasi `register_task.ps1` dan o'tmagan edi. Batareya
> bayroqlarini qo'lda tuzatsam ham, skriptdan qayta ro'yxatdan
> o'tkazish ularni QAYTARARDI.

**Savol:** bu tuzatish qayerda YOZILGAN? Uni qaytaradigan boshqa
manba bormi?

**Tekshiruv:** yagona haqiqat manbaini toping va tuzatishni O'SHA
YERGA qo'ying. Ikki manba bo'lsa — sinov ularni taqqoslasin.

### 7. Sinov o'z farazini tekshiradi

> `items[0]` deb tanlandi, lekin `review_items()` ishonch bo'yicha
> saralaydi — sinov boshqa qatorni ko'rib "xato" dedi. Kod sog'lom
> edi.

**Savol:** sinov TARTIBGA, indeksga yoki tasodifiy holatga
bog'liqmi?

**Tekshiruv:** nom yoki `id` bo'yicha tanlang, indeks bo'yicha emas.
Salbiy sinovlar (xato KUTILGAN holatlar) qulflansin — ular jimgina
"o'tib" ketishi eng oson.

### 8. `ON CONFLICT` tuynugi

Konflikt maqsadi himoya qilgan narsa ≠ himoya kerak bo'lgan narsa.

> `ON CONFLICT (company_id, tender_id)` tenderni tutdi, `tartib`
> raqamini emas. To'plam 30 dan 50 ga o'sdi, yopiq ulush 10 dan 16
> ga suzdi.

**Savol:** UNIQUE nimani qamraydi? Qaysi ustun himoyasiz qoldi?
Kirish vaqt bilan o'zgarsa nima bo'ladi?

**Tekshiruv:** funksiyani IKKI MARTA chaqiring — lekin turli
holatda (ma'lumot o'zgargandan keyin), faqat ketma-ket emas.

### 9. Skaner QAMROVI tor

Skaner ikki xil yolg'on gapira oladi:

| | qanday |
|---|---|
| **ko'radi-yu tanimaydi** | naqsh tor — nom bo'yicha qulflangan |
| **umuman qaramaydi** | mezon tor — obyekt ro'yxatga tushmaydi |

Ikkinchisi xavfliroq: birinchisida hech bo'lmaganda soxta topilma
chiqadi va skaner ishlayotgani ko'rinadi. Ikkinchisida hammasi
yashil.

> `company_id` skaneri mezoni "shu nomli PARAMETR" edi. Kompaniyaga
> tegadigan 127 funksiyadan 69 tasini ko'rardi; qolgan 58 tasi
> endpointlar — ular kompaniyani `company_id_of(request)` dan oladi.
> Mezon kengaytirilgach UCH haqiqiy buzilish chiqdi.

**Savol:** skaner NECHTA narsani ko'rdi? Ko'rmagani nima?

**Tekshiruv:** har skaner IKKI raqam qaytarsin — topilgan buzilish
va **qamrov**. Qamrovni ham sinovga qo'ying, aks holda kimdir
mezonni torlashtirsa "0 buzilish" yana yolg'on gapiradi.

Qattiq son (`>= 120`) mo'rt: kod o'sganda qamrov joyida qolsa ham
sinov yashil bo'ladi. NISBAT (ko'radigan / tegadigan) barqarorroq.

### 10. AVTO-YARATILGAN ma'lumot INSON QARORI bilan bir hovuzda

Xato MANTIQDA emas — shartda ikki xil narsa BIR narsa deb
hisoblanadi.

> `v_review_disagreement` `review_status <> 'pending'` ni ishlatardi.
> Reyestr pozitsiyalari AVTO-tasdiqlanadi va shu shartga QONUNIY
> tushadi. Natija: "yuqori ishonchda 12 tadan 0% kelishmovchilik" —
> ya'ni model hech qachon xato qilmaydi. Holbuki
> `reviewed_by IS NOT NULL` bo'lgan qator BITTA HAM yo'q edi.
>
> Xuddi shu chalkashlik vaqt o'lchovida ham: `n_reviewed` shishib,
> "bir talabga necha soniya" KAM chiqardi.

Ikkala holatda ham xato **noto'g'ri tomonga** og'di: avto-tasdiqni
oqladi va insonni haqiqiydan tezroq ko'rsatdi.

**Savol:** bu shart INSON QARORINI o'lchaydimi yoki shunchaki
"holat o'zgardimi" ni? Ma'lumot qayerdan kelgani ajratilganmi?

**Tekshiruv:** manba ustunini toping (`method`, `reviewed_by`,
`manba_turi`) va shartga QO'SHING. "Tasdiqlangan" — holat,
"inson tasdiqladi" — boshqa narsa.

### 11. Tiklash mexanizmi QOLDIQNI ABADIYLASHTIRADI

Oldingilardan farq qiladi: **kodda tuzatiladigan xato yo'q.**
Mexanizm to'g'ri ishlaydi va aynan shuning uchun buzilgan holatni
saqlaydi.

> `notify_test` boshida sozlamani suratga oladi, oxirida tiklaydi.
> Bir marta yurish o'ldirilib sinov qiymati qolgach — keyingi har
> yurish uni "asl holat" deb oladi va SODIQLIK BILAN qaytaradi.
> `sinov@example.invalid` ishlab chiqarish sozlamasiga aylandi.

Umumiy shakl: **holatni saqlab, keyin tiklaydigan har mexanizm
buzilgan holatni ham saqlaydi.** Bu backup, migratsiya, kesh va
`content_hash` ga ham tegishli — noto'g'ri tahlil hash o'zgarmaguncha
qoladi.

**Savol:** saqlangan "asl holat" ning O'ZI qoldiq bo'lishi mumkinmi?

**Tekshiruv:** mexanizm O'Z FIKSTURASINI tanisin — saqlangan qiymat
sinov qiymatiga teng bo'lsa, u "asl" emas. Va standart sinov:
**"oldin" va "keyin" ni solishtiring** — bir xil chiqsa, tiklash
qoldiqni saqlagan bo'lishi mumkin.

BELGI QONUNIY QIYMAT BO'LMASIN. Ikki marta buzildi:

| belgi | natija |
|---|---|
| `sinov@example.invalid` (RFC 2606) | yaxshi |
| `ZZTEST-` prefiksi | yaxshi |
| `Karimov` — familiya va ko'cha nomi | **30 ta haqiqiy qator** |
| `http://localhost:5173` — dev manzili | soxta xato |

### 12. Muammo HUJJATLASHTIRILDI, ya'ni YOPILGANDEK tuyuldi

Izoh yozish tuzatish o'rnini bosgandek his qilinadi.

> `kodlash.py:39-43` da: *"bu loyihada `tender_requirement` da 1514
> qator `review_status='approved'` bo'lib turibdi va ularni HECH KIM
> ko'rmagan. Natijada `v_review_disagreement` '0% kelishmovchilik'
> ko'rsatadi"*. Sana bor, ta'sir bor, tuzatish YO'Q.

Bu 5-sinf bilan qo'shni, lekin boshqa: u yerda izoh xatoni
tasvirlab, kod uning USTIGA qo'yilgan. Bu yerda izoh muammoni
tasvirlab, HECH NARSA qilinmagan — va yozilgani uchun ish bajarilgan
kabi tuyulgan.

TESKARI shakli ham bor: `ai_chat.py` §12 bloki endpointlarni "HALI
ULANMAGAN" deb aytardi, ular esa allaqachon ulangan edi. Ikkalasida
ham izoh KODNI aks ettirmaydi.

**Savol:** bu izoh muammoni TASVIRLAYDIMI yoki YOPADIMI?

**Tekshiruv:** aniqlangan har muammo ikkitadan biri bo'lsin —

| shakl | xatti-harakati |
|---|---|
| `xfail` sinov | YIQILIB turadi, tuzatilgach yashillanadi |
| `TODO(§16.xx)` | statik skaner sanaydi va bo'limga havola talab qiladi |

Oddiy izoh — uchinchi variant emas.

### 12a. O'LCHOV KECHIKTIRILSA, QARZ FOIZ BILAN O'SADI

12-sinfning vaqt bo'yicha ko'rinishi. Alohida yozilgan, chunki uni
bitta izohda emas, **oylar davomida** ko'rish mumkin.

> Pilot 2026-07 da kelishilgan. `review_pilot` 30 qator qo'shilgan,
> `requirement_review_open` 3 seans ochilgan — va **bittasi ham
> tugatilmagan**. O'shandan beri ustiga qurilgan qatlamlar: talab
> ajratish, kodlash, malaka tekshiruvi, yo'naltirish navbati.
> Har biri sinovlari bilan, har biri ishlaydi, va **hech biri inson
> qaroriga tegmagan**: `reviewed_by = 0`, `inson_qaror = 0`,
> `v_requirement_labeled = 0`.

**QOIDA:** o'lchov kechiktirilganda uning ustiga qurilgan qatlamlar
soni o'sadi, va **har qatlam o'lchovni qimmatroq qiladi**. Chunki
endi o'lchov faqat "model haqmi" ni emas, "qaysi qatlam aybdor" ni
ham ajratishi kerak.

Nega bu sodir bo'ladi — sabab ma'naviy emas, amaliy: **qurish
natijasi darhol ko'rinadi, o'lchash esa noqulay haqiqat chiqarishi
mumkin.** Shuning uchun "keyingi navbatda o'lchaymiz" har safar
oqilona tuyuladi.

**Savol:** oxirgi INSON qarori qachon yozilgan? O'shandan beri
nechta qatlam qo'shildi?

**Tekshiruv:** inson halqasining hisoblagichini quvurga qo'ying
(`reviewed_by IS NOT NULL` soni) va u NOL bo'lsa yangi qatlam
qo'shishdan oldin shu raqamni ko'rsating. Nol qolgan hisoblagich —
"qurishni to'xtat" signali, "keyinroq" emas.

**QARAMA-QARSHI QOIDA:** bitta o'lchov ikkita boshqa narsani
isbotlay olmaydi. Yorliqlash naqsh ajratgichining ANIQLIGINI
o'lchaydi ("0.75 haqiqatan 75% ga to'g'ri keladimi"). U
`ISHONCH_CHEGARA` ni isbotlamaydi — chunki `confidence` uchta
qiymat oladi (`0.40 / 0.75 / 1.00`) va 0.85 chegarasi aslida
`WHERE manba_turi = 'reyestr'` ning raqam kiyimidagi shakli.
Isbotlanadigan chegara YO'Q. Maqsadni almashtirmang.

### 13. IKKI QATLAM ALOHIDA TO'G'RI, ORASIDAGI HOLAT YO'QOLGAN

Oldingi hech biriga o'xshamaydi: **tuzatiladigan xato ikkala
qatlamda ham yo'q.** Server to'g'ri, komponent to'g'ri, sinovlar
yashil — holat esa ular *orasida* yo'qoladi.

> `POST /chat` `session_id` ni to'g'ri tiklaydi. `useChatStream`
> `sessionId` ni to'g'ri saqlaydi. Lekin `App.tsx:562` `ChatPanel`
> ni SHARTLI chizadi — panel yopilganda unmount bo'ladi va state
> u bilan birga o'ladi. Natijada har ochilish yangi sessiya:
> 133 sessiyaning 131 tasida ANIQ 2 xabar, bitta tender uchun
> 28 ta alohida sessiya.
>
> IKKINCHI, jiddiyroq ko'rinishi shu faylda: `seansOch()` eski
> suhbatni ekranga chiqarib `reset()` chaqirardi — u `sessionId`
> ni ham nolga tushiradi. **Ekranda transkript, modelda bo'sh
> kontekst.** Foydalanuvchi "yuqorida aytganimdek" deydi, model
> hech narsa ko'rmaydi va ISHONCH BILAN javob beradi. Jimgina
> yolg'on javobning aniq mexanizmi — va uni hech qanday sinov
> ushlamasdi, chunki ikkala tomon ham "to'g'ri" edi.

Umumiy shakl: holat qatlam ichida emas, **qatlamlar orasidagi
umr chegarasida** yashaydi — komponent daraxtining shakli,
jarayon umri, ulanish umri, kesh yashash muddati. Bularning
hech biri "mantiq" emas, shuning uchun mantiq sinovlari ularni
ko'rmaydi.

Bu 3-sinf bilan qo'shni ("ulangan, lekin chaqirilmaydi"), lekin
teskari: bu yerda hamma narsa chaqiriladi, faqat **orasidagi
narsa yo'qoladi**.

**Savol:** bu holat kimning umriga bog'langan? O'sha egasi
qachon o'ladi va buni kim biladi?

**Tekshiruv — MANTIQ EMAS, MA'LUMOT.** Ikki tomonni alohida
sinash yetarli emas (ikkalasi ham o'tadi). O'rniga:

| tekshiruv | nimani ochadi |
|---|---|
| Jurnalda *taqsimot* emas, **CHEGARA** ko'rinsa | 131/133 da aynan 2 xabar — bu uslub emas, to'siq |
| Bir obyekt uchun bir necha yozuv qisqa vaqtda | ayni tender bo'yicha 106 juft sessiya, 5 daqiqa ichida |
| Ekranda ko'ringan narsa so'rovda ham boradimi | transkript bor, `session_id` yo'q |

Va React da alohida: **shartli chizilgan (`{x && <C/>}`) har
komponent — umri qisqa idish.** Unda saqlangan hech narsa
davomiylikka ishonmaydi.

---

## Skaner yozish standarti

Uch marta bir xil xato: **skaner O'Z NASRINI o'qidi.**

> Skaner o'z izohiga urildi; o'z sinov namunasiga urildi; yangi
> tushuntirishdagi "Ilgari `<> pending` edi" ni buzilish deb topdi.

**KOD SKANERLANADI, NASR EMAS.** Har skanerda:

1. izoh qatorlari olib tashlansin (`#`, `--`);
2. docstring'lar olib tashlansin;
3. `COMMENT ON`, `description=` kabi matn maydonlari ham nasr;
4. skanerning O'ZI sinalsin — buzilishni tutadimi va to'g'ri
   uslubni tutmaydimi.

---

## Tartib

1. **O'zgarishni sanang.** Nima tegdi? Har fayl uchun: bu o'zgarish
   nimani va'da qiladi?

2. **O'n uchta sinfni yurgizing.** Har biriga javob yozing — topilgan
   narsa yoki nega tegishli emasligi.

3. **Topilganini ISBOTLANG.** "Ehtimol muammo" — hisoblanmaydi.
   Yurgizing, o'lchang, jurnalni ko'rsating. Isbotlanmasa "taxmin"
   deb yorliqlang.

4. **Tuzating va QULFLANG.** Sinov qo'shmasdan tuzatish — vaqtinchalik.

5. **Hisobot bering.** Uch bo'lim:

   - **Topildi va tuzatildi** — dalil bilan
   - **Topildi, tuzatilmadi** — nega, va nima qilish kerak
   - **Isbotlanmagan taxminlar** — qolgan da'volar ro'yxati

Uchinchi bo'lim bo'sh bo'lsa — **yomon belgi**. Har ishda o'lchanmagan
narsa qoladi; uni ko'rmaslik ko'rmaganingizni bildiradi.

---

## Nima QILMASLIK kerak

- **Uslub haqida gapirmang.** Nom, formatlash, izoh uzunligi — bu
  so'roq emas. Faqat *jimgina buzilish*.
- **Yumshatmang.** "Kichik ehtimol bilan..." — raqam bering yoki
  aytmang.
- **Ishni qayta yozmang.** Topasiz, tuzatasiz, qulflaysiz. Qayta
  loyihalash — boshqa vazifa.
- **"Hammasi joyida" bilan tugatmang.** 2-sinfning o'zi shu.
