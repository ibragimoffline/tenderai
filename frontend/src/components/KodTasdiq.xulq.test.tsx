/**
 * XATTI-HARAKAT SINOVI: MAHSULOT KODINI TASDIQLASH.
 *
 * ENG QIMMAT INVARIANT — EKRAN ENDPOINTNI ROSTDAN CHAQIRSIN.
 *
 * Bu quruq shakliylik emas. Aynan shu bo'g'in uzilgani o'lchangan:
 * `kod-takliflar`, `kod-tasdiq`, `kod-rad` backendda anchadan beri
 * bor edi va frontend ularning birortasini ham chaqirmasdi. Ya'ni
 * kod yozilmasdi, `v_catalog_code_active` bo'sh qolardi va "Sizga
 * mos" hech qachon natija bermasdi -- tizim buzuq ko'rinardi.
 *
 * `tsc` ham, `vite build` ham bu sinfdagi nuqsonni TUTMAYDI.
 */
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
import { uz } from '@/locales/uz'
import type { MahsulotKodTaklif, Product } from '@/types'

import KodTasdiq from './KodTasdiq'

const kodTakliflar = vi.fn()
const kodTasdiq = vi.fn()
const kodRad = vi.fn()

vi.mock('@/api', () => ({
  api: {
    kodTakliflar: (...a: unknown[]) => kodTakliflar(...a),
    kodTasdiq: (...a: unknown[]) => kodTasdiq(...a),
    kodRad: (...a: unknown[]) => kodRad(...a),
  },
}))

const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

const MAHSULOT = { id: 42, name: 'DS-2CD1043G2 Videokamera' } as Product

function taklif(over: Partial<MahsulotKodTaklif> = {}): MahsulotKodTaklif {
  return {
    code: '26.40.33', name_ru: 'Камера видеонаблюдения',
    namunalar: ['Камера купольная', 'IP камера'],
    n_tender_open: 9, n_position: 31, skor: 0.031,
    signallar: ['leksik'], tasdiqlandi: null, rad_etildi: null, ...over,
  }
}

function ekran(javob: unknown, onChanged = vi.fn()) {
  kodTakliflar.mockResolvedValue(javob)
  render(<KodTasdiq product={MAHSULOT} onClose={vi.fn()} onChanged={onChanged} />)
  return { onChanged }
}

beforeEach(() => {
  kodTakliflar.mockReset()
  kodTasdiq.mockReset().mockResolvedValue(null)
  kodRad.mockReset().mockResolvedValue(null)
})

describe('KodTasdiq', () => {
  it('ochilganda TAKLIFLAR SO`RALADI', async () => {
    ekran({ product_id: 42, keng: [], aniq: [] })
    await waitFor(() => expect(kodTakliflar).toHaveBeenCalledWith(42))
  })

  it('nomzodlar ko`rinadi: kod, nomi va OCHIQ TENDER soni', async () => {
    ekran({ product_id: 42, keng: [], aniq: [taklif()] })
    expect(await screen.findByText('26.40.33')).toBeTruthy()
    expect(screen.getByText('Камера видеонаблюдения')).toBeTruthy()
    // OQIBAT ko'rsatiladi -- "tasdiqlasam nima bo'ladi".
    expect(screen.getByText(
      uz['kod.openTenders'].replace('{n}', '9'))).toBeTruthy()
  })

  it('BALL raqam sifatida KO`RSATILMAYDI', async () => {
    // `skor` — RRF yig'indisi, foiz emas. Undan "% moslik" yasash
    // yolg'on bo'lardi.
    ekran({ product_id: 42, keng: [], aniq: [taklif({ skor: 0.031 })] })
    await screen.findByText('26.40.33')
    expect(screen.queryByText(/0\.031/)).toBeNull()
    expect(screen.queryByText(/3\.1\s*%/)).toBeNull()
  })

  it('namunalar — DALIL sifatida ko`rinadi', async () => {
    ekran({ product_id: 42, keng: [], aniq: [taklif()] })
    expect(await screen.findByText(/Камера купольная/)).toBeTruthy()
  })

  it('TASDIQLASH endpointni AYNAN shu kod bilan chaqiradi', async () => {
    const user = userEvent.setup()
    const { onChanged } = ekran({ product_id: 42, keng: [], aniq: [taklif()] })
    await user.click(await screen.findByRole('button', { name: new RegExp(uz['kod.approve']) }))
    await waitFor(() => expect(kodTasdiq).toHaveBeenCalledWith(42, '26.40.33'))
    // Katalog ro'yxati yangilanadi: `codes` o'zgardi.
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('RAD ETISH endpointni chaqiradi', async () => {
    const user = userEvent.setup()
    ekran({ product_id: 42, keng: [], aniq: [taklif()] })
    await user.click(await screen.findByRole('button', { name: uz['kod.reject'] }))
    await waitFor(() => expect(kodRad).toHaveBeenCalledWith(42, '26.40.33'))
  })

  it('qarordan keyin ro`yxat QAYTA O`QILADI, mahalliy tuzatilmaydi', async () => {
    const user = userEvent.setup()
    ekran({ product_id: 42, keng: [], aniq: [taklif()] })
    await user.click(await screen.findByRole('button', { name: new RegExp(uz['kod.approve']) }))
    // Server tasdiqlashda keng kodlarni O'ZI o'chiradi; mahalliy
    // holatni tuzatish o'sha qoidani ikkinchi marta yozish bo'lardi.
    await waitFor(() => expect(kodTakliflar.mock.calls.length).toBeGreaterThan(1))
  })

  it('TASDIQLANGAN kodda tasdiqlash tugmasi YO`Q', async () => {
    ekran({ product_id: 42, keng: [],
            aniq: [taklif({ tasdiqlandi: '2026-09-11T10:00:00' })] })
    expect(await screen.findByText(uz['kod.approved'])).toBeTruthy()
    expect(screen.queryByRole('button',
                              { name: new RegExp(uz['kod.approve']) })).toBeNull()
  })

  it('IKKI DARAJA ajratib ko`rsatiladi', async () => {
    ekran({ product_id: 42,
            aniq: [taklif({ code: '26.40.33' })],
            keng: [taklif({ code: '26.40', name_ru: 'Guruh' })] })
    expect(await screen.findByText(uz['kod.exact'])).toBeTruthy()
    expect(screen.getByText(uz['kod.broad'])).toBeTruthy()
  })

  it('nomzod YO`Q bo`lsa SABABI aytiladi', async () => {
    ekran({ product_id: 42, keng: [], aniq: [] })
    expect(await screen.findByText(uz['kod.emptyTitle'])).toBeTruthy()
    // Sabab MODEL RAQAMI ekanini aytadi -- "qayta urinib ko'ring" emas.
    // Sarlavhada mahsulot nomi ham bor, shuning uchun ANIQ matn
    // qidiriladi: keng naqsh ikkalasini topib, hech narsani
    // isbotlamasdi.
    expect(screen.getByText(uz['kod.emptyBody'])).toBeTruthy()
  })

  it('notanish signal YASHIRILMAYDI', async () => {
    ekran({ product_id: 42, keng: [],
            aniq: [taklif({ signallar: ['yangi_signal'] })] })
    expect(await screen.findByText('yangi_signal')).toBeTruthy()
  })
})
