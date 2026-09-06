/*
 * MAVZUNI REACT DAN OLDIN QO'YADI — oq chaqnashga qarshi.
 *
 * NEGA ALOHIDA FAYL, `index.html` ichida EMAS
 * ═══════════════════════════════════════════
 * Ilgari bu kod `index.html` ichida INLINE `<script>` edi. Lekin
 * o'sha faylning O'ZIDA CSP shunday e'lon qilingan:
 *
 *     script-src 'self';
 *
 * `'self'` inline skriptga RUXSAT BERMAYDI. Ya'ni skript hech qachon
 * yurmagan va u to'sishi kerak bo'lgan chaqnash HAR OCHILISHDA
 * bo'lgan. Brauzer konsolida:
 *
 *     Executing inline script violates the following Content Security
 *     Policy directive 'script-src 'self''
 *
 * Xato JIMGINA edi: hech narsa yiqilmaydi, faqat chaqnash qoladi —
 * ya'ni aynan kod to'sishi kerak bo'lgan narsa.
 *
 * Hash (`'sha256-...'`) qo'shish ham yechim edi, lekin u MO'RT:
 * skript bir belgi o'zgarsa hash eskiradi va kod yana jimgina
 * bloklanadi. Alohida fayl `'self'` ga tushadi va tahrirdan
 * buzilmaydi.
 *
 * `public/` da: Vite uni O'ZGARTIRMASDAN nusxalaydi, ya'ni yo'l
 * `/theme-init.js` bo'lib qoladi.
 *
 * Mantiq `src/theme.tsx` dagi bilan bir xil: kalit yo'q = tizimga
 * ergash.
 */
(function () {
  try {
    var v = localStorage.getItem('tender-ai:theme')
    var dark = v === 'dark' || (v !== 'light' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches)
    if (dark) document.documentElement.classList.add('dark')
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
    // Manzil paneli rangi ham BIRINCHI BO'YASHDAN OLDIN qo'yiladi —
    // aks holda qorong'i mavzuda panel bir lahza oq bo'lib turardi.
    // Qiymatlar `src/theme.tsx` dagi `THEME_COLOR` bilan bir xil.
    var tc = document.querySelector('meta[name="theme-color"]')
    if (tc) tc.setAttribute('content', dark ? '#11151e' : '#f6f8fc')
    var l = localStorage.getItem('tender-ai:lang')
    if (l === 'ru' || l === 'en' || l === 'uz') document.documentElement.lang = l
  } catch (e) { /* localStorage yopiq — standart yorug' mavzu */ }
})()
