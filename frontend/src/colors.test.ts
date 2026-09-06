/**
 * SINOV: O'LIK RANG SINFLARI
 * ══════════════════════════
 * Nega alohida sinov: Tailwind v4 mavjud bo'lmagan tokendan sinf
 * YARATMAYDI va XATO HAM BERMAYDI. `text-danger` yozilsa, element
 * shunchaki meros rangda qoladi — hech qayerda hech narsa aytilmaydi.
 *
 * HAQIQATAN SODIR BO'LDI. `index.css` da `--color-ok`, `--color-soon`,
 * `--color-urgent` bor; `danger` va `warn` YO'Q. Lekin uchta komponent
 * ularni ishlatardi:
 *
 *     ChatPanel.tsx         3 ta
 *     RequirementReview.tsx 8 ta
 *     ToolBadge.tsx         3 ta
 *
 * Qurilgan CSS da tekshirildi: `text-ok` BOR, `text-danger` YO'Q.
 * Ya'ni OGOHLANTIRISH va XATO signallari rangsiz chiqardi — aynan
 * ko'rinishi eng zarur joyda.
 *
 * Ishga tushirish (loyiha ildizidan):
 *     cd frontend && npm run test:colors
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(fileURLToPath(new URL('.', import.meta.url)))

let pass = 0
let fail = 0

function check(nom: string, shart: boolean, izoh = ''): void {
  if (shart) {
    pass++
    console.log(`  OK   ${nom}`)
  } else {
    fail++
    console.log(`  XATO ${nom}${izoh ? `\n       ${izoh}` : ''}`)
  }
}

/** Barcha `.tsx` / `.ts` fayllar (sinovlardan tashqari). */
function fayllar(dir: string, out: string[] = []): string[] {
  for (const nom of readdirSync(dir)) {
    const p = join(dir, nom)
    if (statSync(p).isDirectory()) {
      fayllar(p, out)
    } else if (/\.tsx?$/.test(nom) && !/\.test\.tsx?$/.test(nom)) {
      out.push(p)
    }
  }
  return out
}

/**
 * `index.css` dagi `@theme` blokida e'lon qilingan rang tokenlari.
 *
 * FAQAT `@theme` bloki: yuqoridagi `:root` da `--ok`, `--soon` kabi
 * XOM o'zgaruvchilar ham bor, lekin Tailwind sinfni `--color-*` dan
 * yaratadi. Ikkalasini aralashtirish sinovni yolg'on qilardi —
 * `--ok` bor, `--color-ok` yo'q bo'lsa ham "joyida" derdi.
 */
function tokenlar(prefiks: string): Set<string> {
  const css = readFileSync(join(SRC, 'index.css'), 'utf8')
  const i = css.indexOf('@theme')
  if (i < 0) return new Set()
  const blok = css.slice(i)
  const out = new Set<string>()
  const re = new RegExp(`--${prefiks}-([a-z0-9-]+)\\s*:`, 'g')
  for (const m of blok.matchAll(re)) out.add(m[1])
  return out
}

/**
 * Kodda ishlatilgan rang sinflari.
 *
 * `-soft` / `-strong` qo'shimchasi va `/40` shaffofligi olib
 * tashlanadi — Tailwind ularni asosiy tokendan yasaydi.
 */
const SINF_RE =
  /\b(text|bg|border|ring|fill|stroke|from|via|to|divide|outline|shadow)-([a-z][a-z0-9]*(?:-[a-z0-9]+)*)(?:\/\d+)?\b/g

/**
 * YO'NALISH qo'shimchalari: `border-l-ok` da token `ok`, `l-ok` emas.
 * Birinchi yurishda skaner aynan shu sababli `l-ok`, `l-soon`,
 * `l-urgent`, `l-primary`, `l-border` deb SOXTA xato bergan edi.
 */
const YONALISH = /^(?:l|r|t|b|x|y|s|e|se|ss|ee|es)-/

/**
 * TUZILMA SINFLARI — prefiks RANGNIKI, sinf esa rang EMAS.
 *
 * O'LCHANGAN SOXTA XATO (2026-09-03, reliz darvozasi). Skaner
 * `bg-gradient-to-r` da `gradient-to-r` ni, `bg-clip-text` da
 * `clip-text` ni TOKEN deb o'qidi va ikkalasini ham "o'lik rang"
 * deb e'lon qildi. Darvoza qizarardi, sabab esa YO'Q edi.
 *
 * Bu OLDINDAN ro'yxatiga qo'shilmadi: u BITTA so'zlar uchun, bular
 * esa QO'SHMA. Naqsh bilan yozilgani ham ataylab — `clip-padding`
 * yoki `gradient-to-bl` ertaga yozilsa, sinov yana soxta qizarardi.
 *
 * DIQQAT: har naqsh Tailwind'ning O'Z kalit so'zi. Ular hech qachon
 * `--color-*` tokeni bo'la olmaydi, ya'ni bu yerda haqiqiy o'lik
 * sinf YASHIRINIB qololmaydi.
 */
const TUZILMA: RegExp[] = [
  /^gradient-to-(?:t|tr|r|br|b|bl|l|tl)$/,        // bg-gradient-to-r
  /^clip-(?:border|padding|content|text)$/,        // bg-clip-text
  /^origin-(?:border|padding|content)$/,           // bg-origin-border
  /^(?:no-)?repeat(?:-(?:x|y|round|space))?$/,     // bg-no-repeat
  /^blend-/,                                       // bg-blend-multiply
  /^offset-/,                                      // ring-offset-2
  /^spacing-/,                                     // border-spacing-2
  /^(?:collapse|separate|double|fixed|local)$/,    // border-collapse
]

/**
 * `style={{ ... }}` bloklari — u yerda CSS QIYMATI turadi, sinf emas.
 *
 * O'LCHANGAN SOXTA XATO (2026-09-03): `style={{ transformBox:
 * 'fill-box' }}` da skaner `fill-box` ni ko'rib `box` tokenini
 * "o'lik" deb e'lon qildi. Skaner butun FAYL matnini o'qiydi,
 * `className` ni emas — ya'ni CSS qiymati sinf bo'lib sanaldi.
 *
 * NEGA `box` ni OLDINDAN ga qo'shmadik: u holda haqiqiy
 * `--color-box` tokeni bo'lsa-yu, `bg-box` yozilsa — sinov jim
 * qolardi. Bu yerda MANBA chetlatiladi, TOKEN emas.
 */
const STIL_RE = /style=\{\{[\s\S]*?\}\}/g

/** Tailwind'ning O'Z so'zlari — token emas. */
const OLDINDAN = new Set([
  'transparent', 'current', 'inherit', 'white', 'black', 'auto', 'none',
  'left', 'right', 'top', 'bottom', 'center', 'x', 'y', 'b', 't', 'l', 'r',
  'clip', 'ellipsis', 'nowrap', 'wrap', 'balance', 'pretty',
  'sm', 'md', 'lg', 'xl', 'full', 'px', 'dashed', 'dotted', 'solid',
  'hidden', 'visible', 'scroll', 'contain', 'cover', 'start', 'end',
  'micro', 'caption', 'body', 'xs', '2xl', '3xl', 'base', 'inner',
  'inset', 'offset', 'width', 'reverse', 'opacity',
])

function main(): void {
  console.log('='.repeat(62))
  console.log("RANG SINFLARI — o'lik sinf CSS bermaydi va XATO ham bermaydi")
  console.log('='.repeat(62))

  const bor = tokenlar('color')
  // SHRIFT o'lchamlari ham `text-` prefiksi bilan yoziladi
  // (`text-lead`, `text-caption`) — ular rang EMAS.
  const shrift = tokenlar('text')
  check('@theme blokida rang tokenlari topildi', bor.size > 10,
        `${bor.size} ta rang, ${shrift.size} ta shrift o'lchami`)
  // MUSBAT TASDIQ: sinov haqiqatan token o'qiyaptimi.
  for (const kutilgan of ['ok', 'soon', 'urgent', 'accent', 'muted']) {
    check(`token e'lon qilingan: ${kutilgan}`, bor.has(kutilgan))
  }

  // Ma'lum O'LIK nomlar — ular QAYTIB KELMASIN.
  for (const olik of ['danger', 'warn']) {
    check(`\`${olik}\` tokeni YO'Q (kutilgan holat)`, !bor.has(olik),
          "agar qo'shilgan bo'lsa, bu sinov yangilansin")
  }

  const ishlatilgan = new Map<string, string[]>()
  for (const p of fayllar(SRC)) {
    // `style={{...}}` bloklari OLIB TASHLANADI (bo'shliqqa
    // almashtiriladi, o'chirilmaydi — qo'shni matn yopishib
    // qolmasin va yangi soxta moslik yasamasin).
    const src = readFileSync(p, 'utf8').replace(STIL_RE, ' ')
    for (const m of src.matchAll(SINF_RE)) {
      const yordamchi = m[1]
      // YO'NALISH qo'shimchasi olib tashlanadi: `border-l-ok` -> `ok`.
      const toliq = m[2].replace(YONALISH, '')
      // `-soft` / `-strong` qo'shimchasini olib tashlaymiz.
      const asos = toliq.replace(/-(soft|strong|foreground)$/, '')
      if (OLDINDAN.has(asos) || /^\[|\d/.test(asos)) continue
      // Tailwind TUZILMA sinfi — prefiks rangniki, sinf rang emas.
      if (TUZILMA.some((rx) => rx.test(toliq))) continue
      // `text-lead` SHRIFT o'lchami, rang emas.
      if (yordamchi === 'text' && shrift.has(asos)) continue
      const ro = ishlatilgan.get(asos) ?? []
      if (!ro.includes(p)) ro.push(p)
      ishlatilgan.set(asos, ro)
    }
  }

  check('kodda rang sinflari topildi', ishlatilgan.size > 3,
        `${ishlatilgan.size} ta token ishlatilgan`)

  const olik: string[] = []
  for (const [tok, joylar] of ishlatilgan) {
    if (!bor.has(tok)) {
      olik.push(`${tok} (${joylar.length} fayl: `
                + joylar.map((x) => x.split(/[\\/]/).pop()).join(', ') + ')')
    }
  }
  check("HAR ishlatilgan rang tokeni @theme da E'LON QILINGAN",
        olik.length === 0,
        olik.length ? olik.join('\n       ') : '')

  // ── BRAUZER CHROME RANGI UCH JOYDA BIR XILMI ──────────────────────
  //
  // `<meta name="theme-color">` qiymati UCH joyda takrorlanadi va
  // buni yo'qotib bo'lmaydi: `index.css` — haqiqiy fon; `theme.tsx` —
  // mavzu almashganda; `theme-init.js` — React dan OLDIN, birinchi
  // bo'yashda. Uchtasi CSS o'zgaruvchisini o'qiy olmaydi (biri
  // brauzergacha ishlaydi), shuning uchun qiymat qo'lda ko'chirilgan.
  //
  // Farq JIMGINA bo'lardi: sahifa foni o'zgaradi, mobil manzil paneli
  // esa eski rangda qolib, ekran tepasida ko'rinadigan chok paydo
  // bo'ladi. Hech qayerda xato chiqmaydi.
  const css = readFileSync(join(SRC, 'index.css'), 'utf8')
  const [yorugQism, qorongiQism] = css.split(/^\.dark\s*\{/m)
  const bgOl = (s = '') => (s.match(/--background:\s*(#[0-9a-fA-F]{3,8})/) || [])[1]
  const cssYorug = bgOl(yorugQism)
  const cssQorongi = bgOl(qorongiQism)

  const th = readFileSync(join(SRC, 'theme.tsx'), 'utf8')
  const thBlok = (th.match(/THEME_COLOR[^=]*=\s*\{([\s\S]*?)\}/) || [])[1] ?? ''
  const thYorug = (thBlok.match(/light:\s*'(#[0-9a-fA-F]{3,8})'/) || [])[1]
  const thQorongi = (thBlok.match(/dark:\s*'(#[0-9a-fA-F]{3,8})'/) || [])[1]

  const init = readFileSync(join(SRC, '..', 'public', 'theme-init.js'), 'utf8')
  const initJuft = init.match(
    /dark\s*\?\s*'(#[0-9a-fA-F]{3,8})'\s*:\s*'(#[0-9a-fA-F]{3,8})'/)
  const initQorongi = initJuft?.[1]
  const initYorug = initJuft?.[2]

  check('`--background` ikkala mavzuda ham topildi',
        Boolean(cssYorug && cssQorongi), `${cssYorug} / ${cssQorongi}`)
  check('`theme-color` YORUG` mavzuda `--background` bilan bir xil',
        Boolean(cssYorug) && thYorug === cssYorug && initYorug === cssYorug,
        `css=${cssYorug} theme.tsx=${thYorug} theme-init.js=${initYorug}`)
  check('`theme-color` QORONG`I mavzuda `--background` bilan bir xil',
        Boolean(cssQorongi) && thQorongi === cssQorongi && initQorongi === cssQorongi,
        `css=${cssQorongi} theme.tsx=${thQorongi} theme-init.js=${initQorongi}`)

  // SKANERNI SINAYMIZ. Salbiy sinov jimgina "o'tib" ketishi eng oson.
  const soxta = 'className="text-qqqfake bg-ok-soft"'
  const topilgan = [...soxta.matchAll(SINF_RE)].map((m) => m[2])
  check('skaner soxta tokenni TOPADI', topilgan.includes('qqqfake'),
        topilgan.join(', '))
  check('skaner haqiqiy tokenni ham ko`radi',
        topilgan.includes('ok-soft'), topilgan.join(', '))

  // ── CHETLATISHLAR IKKI TOMONLAMA SINALADI ─────────────────────────
  //
  // Chetlatish qo'shish eng oson yo'l bilan sinovni O'CHIRIB
  // qo'yadi: soxta xato yo'qoladi va u bilan birga HAQIQIYSI ham.
  // Shuning uchun har chetlatish uchun ikkita tekshiruv — nima
  // CHETLATILGANI va nima CHETLATILMAGANI.
  const tuz = (s: string) => TUZILMA.some((rx) => rx.test(s))
  check('`gradient-to-r` TUZILMA deb tanildi', tuz('gradient-to-r'))
  check('`clip-text` TUZILMA deb tanildi', tuz('clip-text'))
  check('haqiqiy token tuzilma deb SANALMAYDI',
        !tuz('qqqfake') && !tuz('ok') && !tuz('urgent') && !tuz('accent'))

  const stilMatn =
    `<g style={{ transformBox: 'fill-box' }} className="fill-qqqfake">`
  const stilTok = [...stilMatn.replace(STIL_RE, ' ').matchAll(SINF_RE)]
    .map((m) => m[2])
  check('`style={{}}` ichidagi CSS QIYMATI sinf deb sanalmaydi',
        !stilTok.includes('box'), stilTok.join(', '))
  check('`style={{}}` YONIDAGI haqiqiy sinf baribir ko`rinadi',
        stilTok.includes('qqqfake'), stilTok.join(', '))

  console.log('\n' + '='.repeat(62))
  console.log(`NATIJA: ${pass}/${pass + fail} o'tdi`)
  console.log('='.repeat(62))
  process.exit(fail ? 1 : 0)
}

main()
