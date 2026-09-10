/**
 * SINOV: "SIZGA MOS" BO'SH BO'LGANDA SABAB TO'G'RI AYTILADIMI
 * ═══════════════════════════════════════════════════════════
 * O'LCHANGAN NUQSON (2026-09-10, ishlab chiqarish): katalogda
 * 1 796 mahsulot, lug'atda 0 kod. Interfeys "Filtrlarni o'zgartirib
 * ko'ring" dedi. Filtrning aloqasi yo'q edi — katalog KODLANMAGAN
 * edi. Foydalanuvchi bir soat filtr bilan ovora bo'ldi.
 *
 * SHU SABABLI ENG QIMMAT INVARIANT — pastdagi
 * "filtr maslahati" tekshiruvi: kodlanmagan katalogda u
 * BERILMASLIGI shart. Qolgan tekshiruvlar matnni emas, HOLAT
 * TANLOVINI sinaydi: beshala shoxning har biri o'z kalitini
 * beradi va ular bir-biriga siljib ketmaydi.
 *
 * Ishga tushirish (frontend/ dan):
 *     npm run test:katalog
 */
import { katalogBoshHolat } from './katalogBosh.ts'
import { uz } from './locales/uz.ts'
import type { KodlashHolat } from './types.ts'

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

function h(over: Partial<KodlashHolat>): KodlashHolat {
  return {
    mahsulot: 0, kodlangan: 0, kodsiz: 0,
    kutayotgan_taklif: 0, qamrov_pct: null, ...over,
  }
}

function main(): void {
  console.log('\nKATALOG BO`SH-HOLAT SINOVI\n' + '='.repeat(62))

  // ── 1. KATALOG BO'SH ────────────────────────────────────────────
  const b1 = katalogBoshHolat(h({}))
  check('1. mahsulot yo`q -> `mahsulot_yoq`', b1.kalit === 'mahsulot_yoq',
        b1.kalit)

  // ── 2. MAHSULOT BOR, KOD YO'Q, TAKLIF HAM YO'Q ──────────────────
  // AYNAN ISHLAB CHIQARISHDAGI HOLAT.
  const b2 = katalogBoshHolat(
    h({ mahsulot: 1796, kodlangan: 0, kodsiz: 1796, kutayotgan_taklif: 0 }))
  check('2. kodlanmagan katalog -> `kodsiz`', b2.kalit === 'kodsiz', b2.kalit)
  check('2. mahsulot soni matnga uzatiladi', b2.vars?.n === 1796,
        String(b2.vars?.n))

  // ── 3. TAKLIF TASDIQ KUTMOQDA ──────────────────────────────────
  const b3 = katalogBoshHolat(
    h({ mahsulot: 1796, kodlangan: 0, kodsiz: 1796, kutayotgan_taklif: 214 }))
  check('3. tasdiqlanmagan taklif -> `taklif_kutmoqda`',
        b3.kalit === 'taklif_kutmoqda', b3.kalit)
  check('3. `kodsiz` dan AJRATILADI', b3.kalit !== b2.kalit)
  check('3. taklif soni uzatiladi', b3.vars?.n === 214, String(b3.vars?.n))

  // ── 4. QISMAN KODLANGAN ────────────────────────────────────────
  const b4 = katalogBoshHolat(
    h({ mahsulot: 1796, kodlangan: 300, kodsiz: 1496 }))
  check('4. qisman qamrov -> `qisman`', b4.kalit === 'qisman', b4.kalit)
  check('4. kodsiz VA jami sonlar uzatiladi',
        b4.vars?.n === 1496 && b4.vars?.jami === 1796, JSON.stringify(b4.vars))

  // ── 5. TO'LIQ KODLANGAN, MOSLIK YO'Q ───────────────────────────
  const b5 = katalogBoshHolat(
    h({ mahsulot: 1796, kodlangan: 1796, kodsiz: 0, qamrov_pct: 100 }))
  check('5. to`liq qamrov -> `moslik_yoq`', b5.kalit === 'moslik_yoq',
        b5.kalit)

  // ── BESHALASI HAR XIL ──────────────────────────────────────────
  const kalitlar = [b1, b2, b3, b4, b5].map((b) => b.kalit)
  check('beshala holat BIR-BIRIDAN farq qiladi',
        new Set(kalitlar).size === 5, kalitlar.join(', '))

  // ── ENG QIMMAT INVARIANT: YOLG'ON FILTR MASLAHATI ──────────────
  const yolgon = [b1, b2, b3, b4].filter((b) => b.filtrMaslahati)
  check('KODLANMAGAN katalogda filtr maslahati BERILMAYDI',
        yolgon.length === 0, yolgon.map((b) => b.kalit).join(', '))
  check('to`liq kodlanganda filtr maslahati BERILADI', b5.filtrMaslahati)

  // ── O'LCHANMAGAN — NOL EMAS ────────────────────────────────────
  // Eski javob `holat` bermaydi. Unda HECH QANDAY sabab
  // da'vo qilinmaydi: "katalog bo'sh" deb yozish YOLG'ON bo'lardi.
  for (const [nom, qiymat] of [['undefined', undefined],
                               ['null', null]] as const) {
    const b0 = katalogBoshHolat(qiymat)
    check(`holat ${nom} -> \`olchanmadi\``, b0.kalit === 'olchanmadi',
          b0.kalit)
    check(`holat ${nom} -> "katalog bo'sh" DEB AYTILMAYDI`,
          b0.kalit !== 'mahsulot_yoq')
  }

  // ── HAR KALIT LUG'ATDA BOR ─────────────────────────────────────
  // Yo'q kalit `t()` dan kalitning O'ZI bo'lib qaytadi va
  // foydalanuvchi ekranda `match.emptyUncoded` ko'radi.
  const barcha = [b1, b2, b3, b4, b5, katalogBoshHolat(null)]
  const yoq = barcha.flatMap((b) => [b.sarlavha, b.izoh])
    .filter((k) => !(k in uz))
  check('har sarlavha/izoh kaliti `uz` lug`atida bor', yoq.length === 0,
        yoq.join(', '))

  // ── MATNDAGI `{belgi}` LAR UZATILGAN VARS DA BOR ───────────────
  // Aks holda ekranda `{n}` qoladi — bu foydalanuvchiga ko'rinadigan
  // nuqson va `tsc` uni TUTMAYDI.
  const yetishmagan: string[] = []
  for (const b of barcha) {
    for (const kalit of [b.sarlavha, b.izoh]) {
      const matn = (uz as Record<string, string>)[kalit] ?? ''
      for (const m of matn.matchAll(/\{(\w+)\}/g)) {
        if (!b.vars || !(m[1] in b.vars)) yetishmagan.push(`${kalit}:{${m[1]}}`)
      }
    }
  }
  check('har `{belgi}` uchun qiymat uzatiladi', yetishmagan.length === 0,
        yetishmagan.join(', '))

  console.log('\n' + '='.repeat(62))
  console.log(`NATIJA: ${pass}/${pass + fail} o'tdi`)
  console.log('='.repeat(62))
  process.exit(fail ? 1 : 0)
}

main()
