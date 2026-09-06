/**
 * XATTI-HARAKAT SINOVI: AI yordamchi kutib olish ekrani.
 *
 * NEGA BU KOMPONENT SINALADI — O'LCHANGAN NUQSON (2026-09-05).
 * Bu fayl FAQAT `erp-yonaltirish` shoxida bor edi. Ishlab chiqarishga
 * `main` SHOX NOMI bilan joylashtirilgan, ya'ni `git archive main`
 * uni arxivga UMUMAN olmagan. Vite yo'q faylni **xatosiz** o'tkazib
 * yuboradi: qurilma yashil, sahifa ishlaydi, UI esa YO'Q. Nuqson
 * bir kun jimgina turdi va uni hech qanday avtomatik tekshiruv
 * ushlamadi.
 *
 * `tsc` va `vite build` buni TUTMAYDI — ular tiplarni va qurilmani
 * tekshiradi, XULQNI emas. Qurilmadagi satrni `grep` bilan izlash
 * ham yetarli emas: u "fayl bog'landi" ni isbotlaydi, "foydalanuvchi
 * ko'radi" ni emas. Komponent chizilmasa ham satrlar bandlda qolishi
 * mumkin (o'lik kod eliminatsiyasi har doim ham ishlamaydi).
 *
 * Shuning uchun bu yerda AYNAN CHIZILISH va BOSISH o'lchanadi.
 *
 * TARJIMA LUG'ATDAN KELADI (`<I18nProvider>`), ya'ni sinov
 * foydalanuvchi ko'radigan matnni tekshiradi, dasturchi yozgan
 * qattiq satrni emas. Kalit yo'qolsa yoki tarjima o'chsa — yiqiladi.
 */
import { render as rtlRender, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '@/i18n'
import { describe, expect, it, vi } from 'vitest'

import { AIAssistantInterface } from './ai-assistant-interface'
import { uz } from '@/locales/uz'

const render = (ui: React.ReactElement) =>
  rtlRender(<I18nProvider>{ui}</I18nProvider>)

describe('AIAssistantInterface — kutib olish ekrani', () => {
  it('uchala turkum ham CHIZILADI', () => {
    render(<AIAssistantInterface onPick={vi.fn()} />)
    // Matn LUG'ATDAN olinadi: kalit o'zgarsa sinov yiqiladi va
    // "kalit bor, tarjimasi yo'q" holati ham ushlanadi.
    for (const k of ['chat.cat.tender', 'chat.cat.docs',
                     'chat.cat.decide'] as const) {
      expect(screen.getByText(uz[k])).toBeInTheDocument()
    }
  })

  it('turkum YOPIQ boshlanadi — takliflar ko`rinmaydi', () => {
    render(<AIAssistantInterface onPick={vi.fn()} />)
    // MUSBAT LANGAR AVVAL. Bu shart SALBIY ("ko'rinmasin") va
    // salbiy shart hech narsa chizilmaganda ham YASHIL bo'ladi —
    // ya'ni u aynan o'zi qo'riqlashi kerak bo'lgan nuqsonni
    // (komponent umuman chizilmagan) jimgina o'tkazib yuborardi.
    // O'LCHANDI: komponent `null` qaytarganda 5 ta shartdan 4 tasi
    // yiqildi, MANA SHUNISI o'tdi. Endi avval chizilgani
    // tasdiqlanadi, keyin yo'qligi.
    expect(screen.getByText(uz['chat.cat.tender'])).toBeInTheDocument()
    // Yopiq holat MUHIM: 440px li panelda uchala turkum ochiq
    // bo'lsa ro'yxat kirish maydonini ekrandan surib chiqarardi.
    expect(screen.queryByText(uz['chat.cat.tender.1'])).toBeNull()
  })

  it('turkum bosilsa takliflar OCHILADI', async () => {
    const u = userEvent.setup()
    render(<AIAssistantInterface onPick={vi.fn()} />)
    await u.click(screen.getByText(uz['chat.cat.tender']))
    expect(screen.getByText(uz['chat.cat.tender.1'])).toBeInTheDocument()
  })

  it('taklif bosilsa `onPick` TARJIMA QILINGAN matn bilan chaqiriladi', async () => {
    // ENG QIMMAT SHART. Ilgari bunga o'xshash joyda KALIT uzatilardi
    // va kirish maydoniga `chat.cat.tender.1` degan matn tushardi —
    // ya'ni komponent "ishlagan" ko'rinardi, model esa kalitni savol
    // deb o'qirdi.
    const onPick = vi.fn()
    const u = userEvent.setup()
    render(<AIAssistantInterface onPick={onPick} />)
    await u.click(screen.getByText(uz['chat.cat.tender']))
    await u.click(screen.getByText(uz['chat.cat.tender.1']))
    expect(onPick).toHaveBeenCalledTimes(1)
    expect(onPick).toHaveBeenCalledWith(uz['chat.cat.tender.1'])
    // Kalitning O'ZI uzatilmaganiga ALOHIDA shart: yuqoridagi
    // tenglik lug'at o'zgarsa ham o'tib ketishi mumkin edi.
    expect(onPick.mock.calls[0][0]).not.toBe('chat.cat.tender.1')
  })

  it('tender konteksti bo`lsa ham chiziladi (`tenderId` ixtiyoriy)', () => {
    // `tenderId` sarlavhaga ta'sir qiladi. Bu shart uning YIQILMASLIGINI
    // qulflaydi: ikkala chaqiruv shakli ham ishlashi kerak, chunki
    // `ChatPanel` global chatda `tenderId={null}` beradi.
    render(<AIAssistantInterface onPick={vi.fn()} tenderId={12345} />)
    expect(screen.getByText(uz['chat.cat.tender'])).toBeInTheDocument()
  })
})
