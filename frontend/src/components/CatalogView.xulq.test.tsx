/**
 * XATTI-HARAKAT SINOVI: KATALOGNI OMMAVIY TOZALASH.
 *
 * NEGA RENDER, STATIK SINOV EMAS — `catalog_kod_test.py` SERVER
 * qo'riqlarini qulflaydi, lekin interfeys ularni ISHLATISHINI
 * isbotlamaydi. Bu loyihada aynan shu bo'g'in uzilgan edi:
 * `/catalog/{id}/kod-takliflar` backendda ANCHADAN BERI bor, frontend
 * esa uni hech qachon chaqirmagan.
 *
 * ENG QIMMAT INVARIANT — O'CHIRISH AYNAN BELGILANGANINI o'chirsin.
 * Noto'g'ri id yuborilsa foydalanuvchi buni FAQAT ma'lumot
 * yo'qolgandan keyin biladi va qaytarib bo'lmaydi.
 */
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/i18n'
import { uz } from '@/locales/uz'
import type { Product } from '@/types'

import CatalogView from './CatalogView'

const catalogBulkDelete = vi.fn()
const deleteProduct = vi.fn()

vi.mock('@/api', () => ({
  api: {
    catalogBulkDelete: (...a: unknown[]) => catalogBulkDelete(...a),
    deleteProduct: (...a: unknown[]) => deleteProduct(...a),
  },
}))

const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

function mahsulot(id: number, nom: string): Product {
  return {
    id, name: nom, category_code: null, keywords: [], unit: null,
    price: null, currency: null, stock_qty: null, stock_unit: null,
    match_count: 0,
  } as unknown as Product
}

const UCHTA = [mahsulot(1, 'Birinchi'), mahsulot(2, 'Ikkinchi'),
               mahsulot(3, 'Uchinchi')]

function ekran(items = UCHTA, onChanged = vi.fn()) {
  render(<CatalogView items={items} categories={[]} onChanged={onChanged}
                      onOpenMatch={vi.fn()} />)
  return { onChanged }
}

/** Mahsulot qatoridagi belgilash katagi. */
const katak = (nom: string) =>
  screen.getByLabelText(`${nom} — ${uz['cat.select']}`)

async function tasdiqla(user: ReturnType<typeof userEvent.setup>) {
  const tugmalar = await screen.findAllByRole('button',
                                              { name: uz['common.delete'] })
  await user.click(tugmalar[tugmalar.length - 1])
}

beforeEach(() => {
  catalogBulkDelete.mockReset().mockResolvedValue({ ochirildi: 2, rejim: 'tanlangan' })
  deleteProduct.mockReset().mockResolvedValue(null)
})

describe('CatalogView — ommaviy tozalash', () => {
  it('belgilanmaganda ommaviy panel KO`RINMAYDI', () => {
    ekran()
    expect(screen.queryByText(/belgilandi/)).toBeNull()
  })

  it('belgilangach panel va SON chiqadi', async () => {
    const user = userEvent.setup()
    ekran()
    await user.click(katak('Birinchi'))
    expect(screen.getByText(uz['cat.selected'].replace('{n}', '1'))).toBeTruthy()
  })

  it('AYNAN belgilangan id lar yuboriladi', async () => {
    const user = userEvent.setup()
    ekran()
    await user.click(katak('Birinchi'))
    await user.click(katak('Uchinchi'))
    await user.click(screen.getByRole('button', { name: new RegExp(uz['cat.deleteSelected']) }))
    await tasdiqla(user)
    await waitFor(() => expect(catalogBulkDelete).toHaveBeenCalled())
    // ENG QIMMAT DA'VO.
    expect(catalogBulkDelete.mock.calls[0][0]).toEqual({ ids: [1, 3] })
  })

  it('belgilashni bekor qilish panelni yopadi', async () => {
    const user = userEvent.setup()
    ekran()
    await user.click(katak('Birinchi'))
    await user.click(screen.getByRole('button', { name: uz['cat.clearSelection'] }))
    expect(screen.queryByText(/belgilandi/)).toBeNull()
  })

  it('sahifani belgilash HAMMASINI oladi', async () => {
    const user = userEvent.setup()
    ekran()
    await user.click(screen.getByLabelText(uz['cat.selectAll']))
    expect(screen.getByText(uz['cat.selected'].replace('{n}', '3'))).toBeTruthy()
  })

  it('TOZALASH `kutilgan` bilan yuboriladi — ekrandagi son', async () => {
    const user = userEvent.setup()
    catalogBulkDelete.mockResolvedValue({ ochirildi: 3, rejim: 'hammasi' })
    ekran()
    await user.click(screen.getByRole('button', { name: new RegExp(uz['cat.clearAll']) }))
    await tasdiqla(user)
    await waitFor(() => expect(catalogBulkDelete).toHaveBeenCalled())
    expect(catalogBulkDelete.mock.calls[0][0]).toEqual({ hammasi: true, kutilgan: 3 })
  })

  it('tozalash dialogida SON ko`rinadi — hajm yashirilmaydi', async () => {
    const user = userEvent.setup()
    ekran()
    await user.click(screen.getByRole('button', { name: new RegExp(uz['cat.clearAll']) }))
    // Sarlavhaning O'ZI tekshiriladi: "3" raqami sahifada boshqa
    // joyda ham uchraydi va keng qidiruv hech narsani isbotlamasdi.
    expect(await screen.findByText(
      uz['cat.confirmClear'].replace('{n}', '3'))).toBeTruthy()
  })

  it('katalog BO`SH bo`lsa tozalash tugmasi YO`Q', () => {
    ekran([])
    expect(screen.queryByRole('button',
                              { name: new RegExp(uz['cat.clearAll']) })).toBeNull()
  })

  it('so`ralgan va o`chirilgan FARQ qilsa — shunday deyiladi', async () => {
    const user = userEvent.setup()
    // 2 ta so'raldi, 1 tasi o'chdi: id eskirgan.
    catalogBulkDelete.mockResolvedValue({ ochirildi: 1, rejim: 'tanlangan' })
    ekran()
    await user.click(katak('Birinchi'))
    await user.click(katak('Ikkinchi'))
    await user.click(screen.getByRole('button', { name: new RegExp(uz['cat.deleteSelected']) }))
    await tasdiqla(user)
    // "2 ta o'chirildi" DEYILMAYDI — bu yolg'on bo'lardi.
    await waitFor(() => expect(
      screen.queryByText(uz['cat.deleted'].replace('{n}', '2'))).toBeNull())
    expect(screen.getByText(
      uz['cat.deletedPartial'].replace('{n}', '1').replace('{yoq}', '1'))).toBeTruthy()
  })

  it('409 — katalog oradan o`zgargani AYTILADI va ro`yxat yangilanadi', async () => {
    const user = userEvent.setup()
    const xato = Object.assign(new Error('conflict'),
                               { code: 'CATALOG_COUNT_MISMATCH' })
    catalogBulkDelete.mockRejectedValue(xato)
    const { onChanged } = ekran()
    await user.click(screen.getByRole('button', { name: new RegExp(uz['cat.clearAll']) }))
    await tasdiqla(user)
    await waitFor(() => expect(screen.getByText(uz['cat.staleCount'])).toBeTruthy())
    // Ro'yxat YANGILANADI: odam yangi sonni ko'rmasa qayta urinishi
    // ham ayni xato bilan tugardi.
    expect(onChanged).toHaveBeenCalled()
  })
})
