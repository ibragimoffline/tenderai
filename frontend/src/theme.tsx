import { createContext, useCallback, useContext, useEffect, useState } from 'react'

// YORUG'/QORONG'I MAVZU
// ════════════════════
// Ranglar `index.css` dagi CSS o'zgaruvchilarida: `:root` — yorug', `.dark`
// — qorong'i. Butun ilova FAQAT shu tokenlarni ishlatadi (`text-foreground`,
// `bg-card`, `text-muted-foreground`, `bg-ok-soft` …), qat'iy rang yozilmagan.
// Shuning uchun bu yerdagi yagona ish — ildiz elementiga `.dark` sinfini
// qo'yish yoki olib tashlash. Matn ranglari shundan avtomatik moslashadi.
//
// UCH HOLAT, IKKI EMAS:
//     'light' | 'dark' — foydalanuvchi ATAYIN tanlagan;
//     'system'         — operatsion tizim sozlamasiga ergashadi (standart).
// "system" ni alohida holat qilib saqlash SHART: aks holda foydalanuvchi
// kunduzi ochsa "light" deb yozib qo'yardik va kechqurun tizim qorong'iga
// o'tganda ilova yorug'ligicha qolardi.
export type ThemeChoice = 'light' | 'dark' | 'system'

//: Haqiqiy qo'llanadigan mavzu (`system` allaqachon hal qilingan).
export type ResolvedTheme = 'light' | 'dark'

export const THEME_KEY = 'tender-ai:theme'

const mq = () => window.matchMedia('(prefers-color-scheme: dark)')

/** Brauzer chrome rangi — `index.css` dagi `--background` bilan AYNAN
 *  bir xil bo'lishi kerak (yorug' `:root`, qorong'i `.dark`).
 *  `theme-init.js` da ham shu ikki qiymat turadi: u React dan oldin,
 *  birinchi bo'yashdan avval ishlaydi. Qiymat o'zgarsa — uch joyda ham. */
export const THEME_COLOR: Record<ResolvedTheme, string> = {
  light: '#f6f8fc',
  dark: '#11151e',
}

export function readThemeChoice(): ThemeChoice {
  const v = localStorage.getItem(THEME_KEY)
  return v === 'light' || v === 'dark' ? v : 'system'
}

export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  if (choice !== 'system') return choice
  return mq().matches ? 'dark' : 'light'
}

/** Sinfni ildizga qo'yadi. `index.html` dagi FOUC-skript ham SHU mantiqni
 *  takrorlaydi — u yerda React hali ishga tushmagan bo'ladi. */
export function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  // Brauzerning O'ZI chizadigan elementlar (skrollbar, `<input type=date>`
  // kalendari, avtoto'ldirish foni) `color-scheme` ga qaraydi. Busiz
  // qorong'i sahifada oq skrollbar va oq kalendar qolib ketardi.
  root.style.colorScheme = resolved
  // Mobil brauzerning manzil paneli sahifa foni bilan qo'shilib ketsin.
  // Tag `index.html` da turadi; topilmasa jimgina o'tiladi — mavzu
  // almashishi bundan to'xtamasligi kerak.
  document.querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', THEME_COLOR[resolved])
}

interface ThemeCtx {
  choice: ThemeChoice
  resolved: ResolvedTheme
  setChoice: (c: ThemeChoice) => void
  /** Yorug' <-> qorong'i. `system` da bo'lsa — hozirgining teskarisiga. */
  toggle: () => void
}

const Ctx = createContext<ThemeCtx | null>(null)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readThemeChoice)
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(readThemeChoice()))

  useEffect(() => {
    const r = resolveTheme(choice)
    setResolved(r)
    applyTheme(r)
  }, [choice])

  // Tizim mavzusi ish paytida o'zgarishi mumkin (kunduz/tun rejimi) —
  // faqat 'system' holatida ergashamiz.
  useEffect(() => {
    if (choice !== 'system') return
    const m = mq()
    const onChange = () => { const r = resolveTheme('system'); setResolved(r); applyTheme(r) }
    m.addEventListener('change', onChange)
    return () => m.removeEventListener('change', onChange)
  }, [choice])

  const setChoice = useCallback((c: ThemeChoice) => {
    setChoiceState(c)
    // 'system' — YOZILMAYDI, o'chiriladi: kalit yo'qligi "tizimga ergash"
    // degani. Shunda keyingi ochilishda ham tanlov saqlanadi.
    if (c === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, c)
  }, [])

  const toggle = useCallback(
    () => setChoice(resolveTheme(readThemeChoice()) === 'dark' ? 'light' : 'dark'),
    [setChoice])

  return <Ctx.Provider value={{ choice, resolved, setChoice, toggle }}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useTheme faqat <ThemeProvider> ichida ishlaydi.')
  return c
}
