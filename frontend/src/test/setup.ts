/**
 * Xatti-harakat sinovlari uchun umumiy sozlash.
 *
 * QOIDA: bu yerda HECH QANDAY xatti-harakat YASHIRILMAYDI. Sozlash
 * faqat brauzer API larining jsdom da yo'q qismini to'ldiradi. Agar
 * biror narsa "sinovni o'tkazish uchun" o'chirilsa — u sinov emas,
 * bezak bo'lardi.
 */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Har sinovdan keyin DOM tozalanadi — qoldiq keyingi sinovni
// chalg'itmasin (bu loyihada "qoldiq keyingi yurishga o'tadi"
// sinfidagi xato bir necha marta chiqqan).
afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

// Radix UI komponentlari (`Select`, `Popover`, `Dialog`) jsdom da
// yo'q ikki API ni talab qiladi. Ular BO'LMASA komponent umuman
// render bo'lmaydi — ya'ni bu "sinovni yengillashtirish" emas,
// muhitning yetishmagan qismini to'ldirish.
if (!window.matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.setPointerCapture = () => {}
  Element.prototype.releasePointerCapture = () => {}
}
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

// `fetch` ATAYLAB o'rnatilmaydi: har sinov o'zi kutayotgan javobni
// AYNAN belgilasin. Global soxta javob "hamma narsa ishlaydi"
// degan yolg'on bergan bo'lardi.
vi.stubGlobal('fetch', vi.fn(() => {
  throw new Error(
    "Sinov `fetch` ni o'zi belgilashi SHART — global soxta javob yo'q",
  )
}))
