/**
 * XATTI-HARAKAT SINOVI: chatga fayl biriktirish.
 *
 * NEGA SINALADI — `tsc` va `vite build` bu sinfdagi xatolarning
 * BIRORTASINI ham tutmaydi. Ular tiplarni va qurilmani tekshiradi,
 * XULQNI emas. Bu loyihada aynan shu farq qimmatga tushgan: AI chat
 * UI qurilmaga umuman kirmagan holda ham qurilish YASHIL edi.
 *
 * ENG QIMMAT INVARIANT — "TAYYOR" YOLG'ON BO'LMASIN.
 * Foydalanuvchi "Tayyor" yozuvini ko'rib savol beradi. Agar u
 * `yuklandi` holatida ham chiqsa, model fayldan hech narsa topmaydi
 * va foydalanuvchi buni FAQAT javobdan bilib qoladi — sabab esa
 * hech qayerda ko'rinmaydi (§17).
 */
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '@/i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatFayllar from './ChatFayllar'
import { uz } from '@/locales/uz'
import type { ChatFayl } from '@/types'

const chatFiles = vi.fn()
const chatUploadFile = vi.fn()
const chatDetachFile = vi.fn()

vi.mock('@/api', () => ({
  api: {
    chatFiles: (...a: unknown[]) => chatFiles(...a),
    chatUploadFile: (...a: unknown[]) => chatUploadFile(...a),
    chatDetachFile: (...a: unknown[]) => chatDetachFile(...a),
  },
}))

const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

function fayl(over: Partial<ChatFayl> = {}): ChatFayl {
  return {
    id: 'f1', nom: 'shartnoma.pdf', ext: 'pdf', mime: 'application/pdf',
    size_bytes: 1024, holat: 'tayyor', xato: null, matn_belgi: 500,
    sahifa_soni: 3, chunk_soni: 2, ...over,
  }
}

beforeEach(() => {
  chatFiles.mockReset().mockResolvedValue([])
  chatUploadFile.mockReset().mockResolvedValue(fayl({ holat: 'yuklandi' }))
  chatDetachFile.mockReset().mockResolvedValue(null)
})

describe('ChatFayllar', () => {
  it('biriktirma tugmasi KO`RINADI', async () => {
    render(<ChatFayllar sessionId={null} sessiyaOch={vi.fn()} />)
    expect(screen.getByRole('button', { name: uz['chat.attach'] }))
      .toBeInTheDocument()
  })

  it('fayl biriktirilsa RO`YXATDA ko`rinadi', async () => {
    chatFiles.mockResolvedValue([fayl()])
    render(<ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    expect(await screen.findByText('shartnoma.pdf')).toBeInTheDocument()
  })

  it('"Tayyor" FAQAT `tayyor` holatida chiqadi', async () => {
    // ASOSIY SHART. `yuklandi` va `ajratilmoqda` — ikkalasi ham
    // "Ishlanmoqda": foydalanuvchi kutadi va hech nima qila olmaydi.
    chatFiles.mockResolvedValue([
      fayl({ id: 'a', nom: 'a.pdf', holat: 'yuklandi' }),
      fayl({ id: 'b', nom: 'b.pdf', holat: 'ajratilmoqda' }),
    ])
    render(<ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    await screen.findByText('a.pdf')
    expect(screen.queryByText(uz['chat.fileReady'])).toBeNull()
    expect(screen.getAllByText(uz['chat.fileProcessing'])).toHaveLength(2)
  })

  it('o`qilmagan faylda SERVER SABABI ko`rsatiladi', async () => {
    // "Tayyor emas" deb qoldirish foydalanuvchini KUTISHGA majbur
    // qilardi — holbuki kutish hech narsani o'zgartirmaydi.
    chatFiles.mockResolvedValue([fayl({
      holat: 'oqilmadi',
      xato: 'matn topilmadi (skan yoki chizma — OCR kerak)',
    })])
    render(<ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    expect(await screen.findByText(/OCR kerak/)).toBeInTheDocument()
    expect(screen.queryByText(uz['chat.fileReady'])).toBeNull()
  })

  it('sessiya YO`Q bo`lsa biriktirishda YARATILADI', async () => {
    // Sessiya ilgari FAQAT birinchi savolda paydo bo'lardi. Fayl
    // esa undan oldin biriktiriladi — usiz "Ishlanmoqda" holati
    // savol berilgunicha KO'RINMAS edi.
    const sessiyaOch = vi.fn().mockResolvedValue('yangi-sid')
    const u = userEvent.setup()
    const { container } = render(
      <ChatFayllar sessionId={null} sessiyaOch={sessiyaOch} />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await u.upload(input, new File(['salom'], 'a.pdf', { type: 'application/pdf' }))
    await waitFor(() => expect(sessiyaOch).toHaveBeenCalledTimes(1))
    expect(chatUploadFile).toHaveBeenCalledWith('yangi-sid', expect.any(File))
  })

  it('CHEGARADAN katta fayl YUBORILMAYDI', async () => {
    const u = userEvent.setup()
    const { container } = render(
      <ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    // 26 MB — server chegarasi 25 MB.
    const katta = new File([new Uint8Array(26 * 1024 * 1024)], 'katta.pdf',
      { type: 'application/pdf' })
    await u.upload(input, katta)
    // SO'ROV UMUMAN YUBORILMAYDI: 26 MB ni yuborib rad javobini
    // kutish foydalanuvchi uchun ma'nosiz.
    await waitFor(() => expect(screen.getByText(/25/)).toBeInTheDocument())
    expect(chatUploadFile).not.toHaveBeenCalled()
  })

  it('yuklash XATOSI ko`rsatiladi, jimgina yutilmaydi', async () => {
    chatUploadFile.mockRejectedValue(new Error('Bu fayl turi qo`llab-quvvatlanmaydi.'))
    const u = userEvent.setup()
    const { container } = render(
      <ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await u.upload(input, new File(['x'], 'a.pdf', { type: 'application/pdf' }))
    expect(await screen.findByText(/qo`llab-quvvatlanmaydi/)).toBeInTheDocument()
  })

  it('biriktirmani OLIB TASHLASH mumkin', async () => {
    chatFiles.mockResolvedValue([fayl()])
    const u = userEvent.setup()
    render(<ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    await screen.findByText('shartnoma.pdf')
    await u.click(screen.getByRole('button', { name: uz['chat.fileRemove'] }))
    await waitFor(() =>
      expect(chatDetachFile).toHaveBeenCalledWith('s1', 'f1'))
  })

  it('kvota to`lsa tugma O`CHADI', async () => {
    chatFiles.mockResolvedValue([
      fayl({ id: '1' }), fayl({ id: '2' }), fayl({ id: '3' }),
      fayl({ id: '4' }), fayl({ id: '5' }),
    ])
    render(<ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: uz['chat.attach'] }))
        .toBeDisabled())
  })

  it('ISHLANAYOTGAN fayl bo`lmasa QAYTA SO`RAMAYDI', async () => {
    // Taymer faqat kutilayotgan fayl bo'lsa yurishi kerak. Aks holda
    // ochiq panel serverga ABADIY so'rov yuborardi va buni hech kim
    // sezmasdi — chunki u ishlayotgandek ko'rinadi.
    vi.useFakeTimers()
    try {
      chatFiles.mockResolvedValue([fayl({ holat: 'tayyor' })])
      render(<ChatFayllar sessionId="s1" sessiyaOch={vi.fn()} />)
      await vi.advanceTimersByTimeAsync(50)
      const boshlangich = chatFiles.mock.calls.length
      await vi.advanceTimersByTimeAsync(10_000)
      expect(chatFiles.mock.calls.length).toBe(boshlangich)
    } finally {
      vi.useRealTimers()
    }
  })
})
