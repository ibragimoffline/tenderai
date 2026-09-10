/**
 * XATTI-HARAKAT SINOVI: "SIZGA MOS" BO'SH EKRANI.
 *
 * NEGA SOF MANTIQ SINOVI YETARLI EMAS — `katalogBosh.test.ts`
 * FUNKSIYA to'g'ri kalit qaytarishini isbotlaydi, lekin JADVAL uni
 * ISHLATISHINI isbotlamaydi. Aynan shu bo'g'in uzilgan edi: backend
 * `holat` ni ANCHADAN BERI berardi, frontend esa uni umuman
 * o'qimasdi va ekranda baribir "Filtrlarni o'zgartirib ko'ring"
 * turardi.
 *
 * Shuning uchun bu yerda ROSTDAN RENDER qilinadi va EKRANDAGI MATN
 * o'qiladi.
 */
import { render as rtlRender, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
import { uz } from '@/locales/uz'
import { katalogBoshHolat } from '@/katalogBosh'
import type { KodlashHolat } from '@/types'

import TenderTable from './TenderTable'

const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

function h(over: Partial<KodlashHolat>): KodlashHolat {
  return {
    mahsulot: 0, kodlangan: 0, kodsiz: 0,
    kutayotgan_taklif: 0, qamrov_pct: null, ...over,
  }
}

function jadval(holat: KodlashHolat | null | undefined, katalog = vi.fn()) {
  return render(
    <TenderTable
      items={[]} mode="match" loading={false} showStatus={false}
      sort="" onSort={vi.fn()} onSelect={vi.fn()}
      bosh={katalogBoshHolat(holat)} onKatalog={katalog} />,
  )
}

/** Ekranda "filtrlarni o'zgartiring" maslahati bormi. */
const filtrMaslahatiBor = () =>
  screen.queryByText(uz['table.empty']) !== null

describe('TenderTable — bo`sh "Sizga mos"', () => {
  it('1. katalog bo`sh: mahsulot qo`shish deyiladi', () => {
    jadval(h({}))
    expect(screen.getByText(uz['match.emptyNoProducts'])).toBeTruthy()
    expect(filtrMaslahatiBor()).toBe(false)
  })

  it('2. katalog KODLANMAGAN: sabab aytiladi, FILTR MASLAHATI BERILMAYDI', () => {
    // AYNAN ISHLAB CHIQARISHDAGI HOLAT (2026-09-10).
    jadval(h({ mahsulot: 1796, kodsiz: 1796 }))
    expect(screen.getByText(uz['match.emptyUncoded'])).toBeTruthy()
    // ENG QIMMAT DA'VO — yolg'on maslahat qaytib kelmasin.
    expect(filtrMaslahatiBor()).toBe(false)
    // Mahsulot soni o'rniga qo'yildi, `{n}` qolib ketmadi.
    expect(screen.queryByText(/\{n\}/)).toBeNull()
    expect(screen.getByText(/1796/)).toBeTruthy()
  })

  it('3. taklif kutmoqda: KODSIZ dan boshqa matn', () => {
    jadval(h({ mahsulot: 1796, kodsiz: 1796, kutayotgan_taklif: 214 }))
    expect(screen.getByText(uz['match.emptyPending'])).toBeTruthy()
    expect(screen.queryByText(uz['match.emptyUncoded'])).toBeNull()
    expect(filtrMaslahatiBor()).toBe(false)
  })

  it('4. qisman kodlangan: qamrov to`liq emasligi aytiladi', () => {
    jadval(h({ mahsulot: 1796, kodlangan: 300, kodsiz: 1496 }))
    expect(screen.getByText(uz['match.emptyPartial'])).toBeTruthy()
    expect(filtrMaslahatiBor()).toBe(false)
  })

  it('5. to`liq kodlangan: moslik CHINAKAM yo`q — filtr maslahati O`RINLI', () => {
    jadval(h({ mahsulot: 1796, kodlangan: 1796, kodsiz: 0, qamrov_pct: 100 }))
    expect(screen.getByText(uz['match.emptyNoMatch'])).toBeTruthy()
    expect(filtrMaslahatiBor()).toBe(true)
  })

  it('holat O`LCHANMAGAN bo`lsa hech qanday sabab DA`VO QILINMAYDI', () => {
    jadval(null)
    expect(screen.getByText(uz['common.notFound'])).toBeTruthy()
    expect(screen.queryByText(uz['match.emptyUncoded'])).toBeNull()
    expect(screen.queryByText(uz['match.emptyNoProducts'])).toBeNull()
    // Eski umumiy matn qoladi — bu ATAYLAB.
    expect(filtrMaslahatiBor()).toBe(true)
  })

  it('katalogga o`tish tugmasi TUZATILADIGAN holatlarda ko`rinadi', () => {
    const ket = vi.fn()
    jadval(h({ mahsulot: 1796, kodsiz: 1796 }), ket)
    screen.getByText(uz['match.toCatalog']).click()
    expect(ket).toHaveBeenCalled()
  })

  it('moslik CHINAKAM yo`q bo`lsa katalog tugmasi ko`rinmaydi', () => {
    // Katalogda tuzatadigan narsa yo'q — tugma yolg'on ish va'da qilardi.
    jadval(h({ mahsulot: 5, kodlangan: 5, kodsiz: 0, qamrov_pct: 100 }))
    expect(screen.queryByText(uz['match.toCatalog'])).toBeNull()
  })

  it('bo`sh EMAS natijada bo`sh ekran umuman chiqmaydi', () => {
    render(
      <TenderTable
        items={[{
          id: 1, name: 'Sinov tenderi', status: 'open', status_name: null,
          totalcost: null, currency: null, close_at: null,
          publicated_at: null, source_platform: 'xt-xarid',
        }]}
        mode="match" loading={false} showStatus={false}
        sort="" onSort={vi.fn()} onSelect={vi.fn()}
        bosh={katalogBoshHolat(h({ mahsulot: 1796, kodsiz: 1796 }))} />,
    )
    expect(screen.queryByText(uz['match.emptyUncoded'])).toBeNull()
    // Jadval va mobil kartochka — bir nom IKKI marta chiqadi, bu normal.
    expect(screen.getAllByText(/Sinov tenderi/).length).toBeGreaterThan(0)
  })
})
