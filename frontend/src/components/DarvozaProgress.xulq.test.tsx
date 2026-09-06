/**
 * XATTI-HARAKAT SINOVI: sifat darvozasi ko'rsatkichi.
 *
 * NEGA AYNAN BU KOMPONENT BIRINCHI: u loyihaning ENG QIMMAT
 * invariantini ekranga chiqaradi — "qaysi qaror SANALADI". Uch marta
 * shu yerda xato bo'lgan (o'lchangan):
 *
 *   - `v_review_disagreement` avto-tasdiqlangan qatorlarni inson
 *     qarori deb sanadi -> "0% kelishmovchilik";
 *   - `v_kod_pilot` anonim qarorni maqsadga qo'shdi -> ekran
 *     "40/40", darvoza esa "0/40";
 *   - `n_reviewed` shishib, "bir talabga necha soniya" KAM chiqdi.
 *
 * Uchalasi bir sinf: ATRIBUTSIZ yozuv ATRIBUTLANGAN deb sanaldi.
 * Bu sinov shu sinfni FRONTENDDA qulflaydi: ko'rsatkich faqat
 * `aktorli` ni ko'rsatsin va atributsizni QO'SHMASIN.
 *
 * `tsc` va `vite build` bu xatolarning BIRORTASINI ham tutmaydi —
 * ular tiplarni va qurilmani tekshiradi, XULQNI emas.
 */
import { render as rtlRender, screen } from '@testing-library/react'
import { I18nProvider } from '@/i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DarvozaProgress } from './DarvozaProgress'

// KOMPONENT `useT()` NI ISHLATADI va u `<I18nProvider>` SIZ
// ISTISNO KO'TARADI. Bu yerda provayder QO'SHILADI — matn lug'atdan
// keladi, ya'ni sinov ham AYNAN foydalanuvchi ko'radigan matnni
// tekshiradi, dasturchi yozgan qattiq satrni emas.
const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

const validatsiyaHolat = vi.fn()
vi.mock('../api', () => ({ api: { validatsiyaHolat: () => validatsiyaHolat() } }))

function qatlam(over: Record<string, unknown> = {}) {
  return {
    qatlam: 'yonaltirish',
    eng_kam: 50,
    aktorli: 18,
    qolgan: 32,
    anonim: 0,
    mashina: 0,
    navbatda: 278,
    holat: 'YETARLI_EMAS',
    ulush_foiz: null,
    tosiq: null,
    ...over,
  }
}

beforeEach(() => {
  validatsiyaHolat.mockReset()
})

describe('DarvozaProgress — sifat darvozasi ko‘rsatkichi', () => {
  it('ATRIBUTLANGAN qarorni maqsad bilan ko‘rsatadi ("18 / 50")', async () => {
    validatsiyaHolat.mockResolvedValue({ qatlamlar: [qatlam()], izoh: {} })
    render(<DarvozaProgress qatlam="yonaltirish" />)
    expect(await screen.findByText('18 / 50')).toBeInTheDocument()
  })

  it('ANONIM va MASHINA qatorlarini maqsadga QO‘SHMAYDI', async () => {
    // Darvoza qoidasi: `aktorli` sanaladi, `anonim`/`mashina` YO'Q.
    // Agar ular qo'shilsa 18+7+29 = 54 bo'lardi va ko'rsatkich
    // maqsad OSHIB KETGANDEK ko'rinardi.
    validatsiyaHolat.mockResolvedValue({
      qatlamlar: [qatlam({ anonim: 7, mashina: 29 })],
      izoh: {},
    })
    render(<DarvozaProgress qatlam="yonaltirish" />)
    expect(await screen.findByText('18 / 50')).toBeInTheDocument()
    expect(screen.queryByText('54 / 50')).not.toBeInTheDocument()
    // Lekin ular YASHIRILMAYDI ham — alohida ko'rinadi.
    expect(screen.getByText(/7 anonim/)).toBeInTheDocument()
    expect(screen.getByText(/29 mashina/)).toBeInTheDocument()
  })

  it('TUGALLANMAGAN darvozani YASHIRMAYDI (nol ham ko‘rinadi)', async () => {
    validatsiyaHolat.mockResolvedValue({
      qatlamlar: [qatlam({ aktorli: 0, holat: 'TASDIQLANMAGAN' })],
      izoh: {},
    })
    render(<DarvozaProgress qatlam="yonaltirish" />)
    expect(await screen.findByText('0 / 50')).toBeInTheDocument()
  })

  it('TO‘SIQ sababini ko‘rsatadi (pilot nega yurmayapti)', async () => {
    validatsiyaHolat.mockResolvedValue({
      qatlamlar: [qatlam({ tosiq: 'AKTOR YOQ — qarorlar anonim yoziladi' })],
      izoh: {},
    })
    render(<DarvozaProgress qatlam="yonaltirish" />)
    expect(await screen.findByText(/AKTOR YOQ/)).toBeInTheDocument()
  })

  it('API XATOSIDA ham satr QOLADI — yo‘qolib ketmaydi', async () => {
    // Komponentning yo'qolishi "darvoza yopildi / muammo yo'q" deb
    // o'qilardi. O'lchovsizlik KO'RINISHI shart.
    validatsiyaHolat.mockRejectedValue(new Error('tarmoq yiqildi'))
    render(<DarvozaProgress qatlam="yonaltirish" />)
    expect(await screen.findByText(/darvoza holati o‘qilmadi/)).toBeInTheDocument()
  })

  it('progressbar ACCESSIBLE — ekran o‘qigich uchun yorliq va qiymat', async () => {
    validatsiyaHolat.mockResolvedValue({ qatlamlar: [qatlam()], izoh: {} })
    render(<DarvozaProgress qatlam="yonaltirish" />)
    const bar = await screen.findByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '18')
    expect(bar).toHaveAttribute('aria-valuemax', '50')
    expect(bar).toHaveAccessibleName(/18 \/ 50/)
  })

  it('BOSHQA qatlamning raqamini KO‘RSATMAYDI', async () => {
    // Uch qatlamning maqsadi har xil (40 / 200 / 50). Noto'g'ri
    // qatlam tanlansa ko'ruvchi boshqa pilotning holatini ko'rardi.
    validatsiyaHolat.mockResolvedValue({
      qatlamlar: [
        qatlam({ qatlam: 'kod_tasdigi', eng_kam: 40, aktorli: 3 }),
        qatlam({ qatlam: 'yonaltirish', eng_kam: 50, aktorli: 18 }),
      ],
      izoh: {},
    })
    render(<DarvozaProgress qatlam="kod_tasdigi" />)
    expect(await screen.findByText('3 / 40')).toBeInTheDocument()
    expect(screen.queryByText('18 / 50')).not.toBeInTheDocument()
  })
})
