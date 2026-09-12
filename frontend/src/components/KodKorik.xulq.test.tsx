/**
 * XATTI-HARAKAT SINOVI: KODLARNI KO'RIB CHIQISH NAVBATI.
 *
 * ENG QIMMAT INVARIANT — EKRAN OCHILISHI KODNI O'ZGARTIRMASIN.
 *
 * Bu shakliy tekshiruv emas. `korib_chiqilsin` bayrog'ining butun
 * ma'nosi shu: 187 ta kod siyosat yozilishidan OLDIN qo'llangan va
 * yangi siyosat ulardan 49 tasini o'tkazmaydi. Ular orasida haqiqiy
 * xato bor (server SHKAFI `Сервер` deb kodlangan), lekin HAMMASI
 * xato degani emas. Agar ekran ochilishi bilan deaktivatsiya qilsa,
 * "Sizga mos" 49 mahsulot bo'yicha kamayardi va TO'G'RI kodlar ham
 * yo'qolardi.
 *
 * Bog'lanish FAQAT odam qaror qabul qilganda o'zgaradi.
 */
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
import type { KodKorikQator } from '@/types'

import KodKorik from './KodKorik'

const kodKorik = vi.fn()
const kodTasdiq = vi.fn()
const kodRad = vi.fn()
const kodTakliflar = vi.fn()

vi.mock('@/api', () => ({
  api: {
    kodKorik: (...a: unknown[]) => kodKorik(...a),
    kodTasdiq: (...a: unknown[]) => kodTasdiq(...a),
    kodRad: (...a: unknown[]) => kodRad(...a),
    kodTakliflar: (...a: unknown[]) => kodTakliflar(...a),
  },
}))

const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

const QATOR: KodKorikQator = {
  product_id: 2850,
  mahsulot: 'Server (telekommunikatsiya) shkafi 6U',
  code: '26.20.14',
  tasdiqlagan: 'tizim:auto',
  tasdiqlandi: '2026-09-12T16:50:14+05:00',
  siyosat_sabab: 'siyosat:ziddiyat',
  siyosat_at: '2026-09-12T20:45:04+05:00',
  ochiq_tender: 37,
}

beforeEach(() => {
  kodKorik.mockReset().mockResolvedValue({ jami: 1, qatorlar: [QATOR] })
  kodTasdiq.mockReset().mockResolvedValue(null)
  kodRad.mockReset().mockResolvedValue(null)
  kodTakliflar.mockReset().mockResolvedValue({ product_id: 2850, keng: [], aniq: [] })
})

describe('KodKorik', () => {
  it('navbatni o`qiydi va qatorni ko`rsatadi', async () => {
    render(<KodKorik />)
    expect(await screen.findByText(QATOR.mahsulot)).toBeTruthy()
    expect(screen.getByText('26.20.14')).toBeTruthy()
    // SABAB ko'rinishi SHART: odam NEGA belgilanganini bilmasa,
    // qaror qabul qila olmaydi.
    expect(screen.getByText('siyosat:ziddiyat')).toBeTruthy()
    expect(kodKorik).toHaveBeenCalled()
  })

  it('EKRAN OCHILISHI hech narsani o`zgartirmaydi', async () => {
    render(<KodKorik />)
    await screen.findByText(QATOR.mahsulot)
    // Bu sinovning butun sababi shu ikki qator.
    expect(kodTasdiq).not.toHaveBeenCalled()
    expect(kodRad).not.toHaveBeenCalled()
  })

  it('`Saqlash` O`SHA kodni tasdiqlaydi (tizim qarori -> inson qarori)', async () => {
    render(<KodKorik />)
    await screen.findByText(QATOR.mahsulot)
    await userEvent.click(screen.getByRole('button', { name: /Saqlash/i }))
    await waitFor(() => expect(kodTasdiq).toHaveBeenCalledWith(2850, '26.20.14'))
    expect(kodRad).not.toHaveBeenCalled()
  })

  it('`Rad etish` kodRad ni chaqiradi', async () => {
    render(<KodKorik />)
    await screen.findByText(QATOR.mahsulot)
    await userEvent.click(screen.getByRole('button', { name: /Rad etish/i }))
    await waitFor(() => expect(kodRad).toHaveBeenCalledWith(2850, '26.20.14'))
    expect(kodTasdiq).not.toHaveBeenCalled()
  })

  it('qarordan keyin navbat QAYTA o`qiladi', async () => {
    render(<KodKorik />)
    await screen.findByText(QATOR.mahsulot)
    const oldin = kodKorik.mock.calls.length
    await userEvent.click(screen.getByRole('button', { name: /Saqlash/i }))
    await waitFor(() => expect(kodKorik.mock.calls.length).toBeGreaterThan(oldin))
  })
})
