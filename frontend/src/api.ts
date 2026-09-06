// Backend API qatlami — barcha so'rovlar shu yerdan o'tadi.
// Bazaviy manzil .env dagi VITE_API_BASE dan (zaxira: `/api`, same-origin).
import type {
  AiMatchResult, CatalogMatchResponse, Category, CompanyDocument,
  CompanyProfileData, ComplianceResult,
  DocumentTextResult, DocumentType, Freshness, GoNoGoResult, Paged, PricingInputs,
  PricingSaved, Product, ProductSuggestion, Region, SavedSearch, Stats, Status,
  StockCheckResult, TelegramBot, TelegramLink, TelegramLinkStatus,
  Aktor, AktorHolat, AktorRol, AuditYozuv, Kimlik,
  HujjatTuri, InsonQarori, ManbaSonlari, ReviewRejim, ReviewTezlik,
  Talab, TalabHolat, TalabNavbat,
  AiQaror, InsonQaror, MalakaNatija, NavbatFiltr, RoutingHolat,
  RoutingItem, TalabFiltr,
  KodNavbat, KodQaror, KodQidiruv, KodOlchov, Manba,
  RoutingMoslik,
  TalabXulosa,
  TelegramSubscriber, TenderDetail, TenderRow, NotifySettingsData, Nullable,
  ValidatsiyaHolat, Yonaltirish,
} from './types'

// ZAXIRA QIYMAT `/api` — SAME-ORIGIN.
//
// Ilgari `http://localhost:8000` edi va bu O'LCHANGAN nosozlik berdi:
// `deploy/bin/deploy.sh` relizni `git archive` bilan yasaydi,
// `frontend/.env` esa KUZATILMAGAN fayl — ya'ni relizga tushmaydi.
// Natijada `npm run build` `VITE_API_BASE` siz yurardi va qurilmaga
// `localhost:8000` SINGIB QOLARDI: ishlab chiqarish sahifasidagi HAR
// so'rov foydalanuvchi brauzerida `localhost:8000` ga ketardi.
//
// `/api` zaxirasi ikki sababdan to'g'ri: (1) joylashtirishda Caddy
// aynan shu yo'lni backendga uzatadi, (2) sessiya cookie'si
// `SameSite=Lax` va u FAQAT same-origin so'rovda ketadi — to'liq
// manzil yozilsa kirish umuman ishlamaydi.
const BASE = import.meta.env.VITE_API_BASE || '/api'

// --- KIMLIK (auth-4) ---------------------------------------------------------
// Tender-AI ga KOMPANIYA hisobi bilan kiriladi (odam emas — hodimlar ERP da).
//
// Sessiya tokeni `HttpOnly` COOKIE'da va bu fayl uni KO'RMAYDI: XSS bo'lsa
// ham JavaScript tokenni o'qiy olmaydi (`localStorage` da esa o'qirdi).
//
// COOKIE'NING NARXI — CSRF: brauzer cookie'ni HAR so'rovga o'zi qo'shadi.
// Shuning uchun o'zgartiruvchi so'rovlarga `X-CSRF-Token` sarlavhasi
// qo'yiladi; qiymati `HttpOnly BO'LMAGAN` cookie'dan (yoki `/auth/me`
// javobidan) olinadi va serverdagi SESSIYA qiymati bilan solishtiriladi.
//
// MUHIM: cookie ishlashi uchun so'rov SAME-ORIGIN bo'lishi kerak —
// `VITE_API_BASE=/api` (Vite proksisi). To'liq manzil yozilsa cookie
// cross-site bo'lib qoladi.
import { xatoMatni, type TVars } from './i18n'

const CSRF_COOKIE = 'tai_csrf'
const SEEN_KEY = 'tender-ai:seen'

// --- AKTOR (auth-6) ----------------------------------------------------------
// Tender-AI ga KOMPANIYA kiradi, odam emas. Qaror KIM tomonidan qo'yilganini
// ajratish uchun sahifa `X-Actor` sarlavhasida ro'yxatdagi aktorni KO'RSATADI.
//
// BU ISBOT EMAS VA SHUNDAY YOZILADI. Server uni `aktor_elon` darajasi bilan
// saqlaydi — "e'lon qilingan", "isbotlangan" emas. Sessiya egasi sarlavhani
// o'zgartira oladi; foydasi shundaki, u ijarachi ICHIDAGI mas'uliyatni
// ajratadi va tasodifan chalkashish yo'qoladi.
//
// Isbotlangan daraja (`erp_sessiya`) ERP `erp.v_tai_actor` shartnoma-view ini
// chop etganda paydo bo'ladi — `docs/erp_kimlik.md` §4.
const AKTOR_KEY = 'tender-ai:aktor'

export function getAktorId(): number | null {
  try {
    const v = localStorage.getItem(AKTOR_KEY)
    return v ? Number(v) || null : null
  } catch { return null }
}

export function setAktorId(id: number | null): void {
  try {
    if (id) localStorage.setItem(AKTOR_KEY, String(id))
    else localStorage.removeItem(AKTOR_KEY)
  } catch { /* localStorage yo'q — sarlavha yuborilmaydi, xato emas */ }
}

/** Cookie o'qilmasa ishlatiladigan nusxa (login yoki `/auth/me` dan). */
let csrfFallback: string | null = null

export function setCsrf(token: string | null): void {
  csrfFallback = token
}

function readCsrf(): string | null {
  try {
    const hit = document.cookie.split('; ')
      .find((c) => c.startsWith(CSRF_COOKIE + '='))
    if (hit) return decodeURIComponent(hit.slice(CSRF_COOKIE.length + 1))
  } catch { /* document yo'q — pastdagi nusxa ishlatiladi */ }
  return csrfFallback
}

/** "Avval kirgan edikmi" belgisi. Tokenning O'ZI emas — u HttpOnly
 *  cookie'da. Faqat sahifa ochilganda kirish ekrani chaqnamasin uchun. */
export function getToken(): string | null {
  try { return localStorage.getItem(SEEN_KEY) } catch { return null }
}

export function setToken(v: string | null): void {
  try {
    if (v) localStorage.setItem(SEEN_KEY, '1')
    else localStorage.removeItem(SEEN_KEY)
  } catch { /* localStorage yopiq — zarari yo'q */ }
}

/** Xom `fetch` ishlatadigan joylar uchun (fayl yuklash — FormData).
 *  Cookie'ni brauzer o'zi qo'shadi, biz faqat CSRF sarlavhasini beramiz. */
export function authHeaders(): Record<string, string> {
  const c = readCsrf()
  return c ? { 'X-CSRF-Token': c } : {}
}

/** 401 kelganda chaqiriladi: ilova kirish ekraniga qaytadi. */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn
}

// Nisbiy havolalarni (masalan fayl yuklab olish proksisi) to'liq manzilga aylantiradi
export const apiUrl = (path?: string): string =>
  path?.startsWith('/') ? BASE + path : (path ?? '')

/** FastAPI 422 validatsiya xatosining bir elementi */
interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

// FastAPI xato tanasini o'qiladigan matnga aylantiradi.
// 400 -> detail satr; 422 (validatsiya) -> detail MASSIV: [{loc, msg}, ...].
// Massivni to'g'ridan-to'g'ri satrga qo'shsak "[object Object]" chiqadi va
// foydalanuvchi qaysi maydon xato ekanini bilmaydi.
export function errMatn(detail: unknown): string {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return String(detail)
  return (detail as ValidationIssue[]).map((e) => {
    const maydon = (e.loc || []).filter((x) => x !== 'body').join('.')
    const msg = String(e.msg || '').replace(/^Value error,\s*/, '')
    return maydon ? `${maydon}: ${msg}` : msg
  }).join('; ')
}

/** Xato + STRUKTURALI `detail`.
 *  `errMatn()` obyekt-detail'ni satrga aylantira olmaydi ("[object Object]"),
 *  ERP esa 409 da {message, opportunity_id} qaytaradi — mavjud kartaga havola
 *  qurish uchun xom tana kerak.
 *
 *  `code` — SERVER BERGAN, TILGA BOG'LIQ BO'LMAGAN kod
 *  (`api/xatolar.py:KODLAR`). `message` esa SHU KODNING joriy tildagi
 *  tarjimasi: shu tufayli xatoni ko'rsatadigan 24 ta komponent
 *  o'zgarmasdan uch tilli bo'ldi — ular avvalgidek `e.message` ni
 *  chizadi.
 *
 *  `diagnosticId` — server jurnalidagi so'rov identifikatori
 *  (`X-Request-Id` bilan bir xil). Texnik tafsilot javobga
 *  tushmaydi; foydalanuvchi shu belgilarni aytsa, jurnaldan aynan
 *  o'sha so'rov topiladi. */
export class ApiError extends Error {
  status: number
  detail: unknown
  /** Server bergan barqaror xato kodi (`TENDER_NOT_FOUND`). Kodsiz
   *  javoblarda (masalan proksi bergan 502 HTML) `undefined`. */
  code?: string
  /** Tarjimaga qo'yiladigan qiymatlar (`{id}`, `{max_mb}`). */
  params?: Record<string, unknown>
  /** 422 da: qaysi maydon, qaysi kod bilan. */
  fields?: { field: string; code: string }[]
  diagnosticId?: string
  /** 429 dagi `Retry-After` (soniya). Server matni bitta tilda keladi,
   *  interfeys esa uch tilli — shuning uchun xabarni MATNDAN emas, shu
   *  SONDAN yig'amiz. */
  retryAfter?: number
  constructor(message: string, status: number, detail: unknown,
              retryAfter?: number, kod?: string,
              params?: Record<string, unknown>,
              fields?: { field: string; code: string }[],
              diagnosticId?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.retryAfter = retryAfter
    this.code = kod
    this.params = params
    this.fields = fields
    this.diagnosticId = diagnosticId
  }
}

type Params = Record<string, string | number | boolean | string[] | null | undefined>

interface RequestOpts {
  params?: Params
  body?: unknown
}

async function request<T>(
  method: string, path: string, { params, body }: RequestOpts = {},
): Promise<T> {
  // Ikkinchi argument SHART: BASE nisbiy bo'lishi mumkin (masalan '/api' —
  // ngrok ortida Vite proxy'si orqali). `new URL('/api/tenders')` bazasiz
  // TypeError beradi. BASE absolyut bo'lsa ikkinchi argument e'tiborga olinmaydi.
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue
      // Massiv -> takrorlanuvchi parametr (?product=a&product=b), chunki
      // FastAPI List[str] ni shunday kutadi. set() bo'lsa vergul bilan
      // birlashib bitta qatorga aylanib qolardi.
      if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x))
      else url.searchParams.set(k, String(v))
    }
  }
  // `credentials: 'include'` — sessiya cookie'si yuborilishi uchun SHART.
  const headers: Record<string, string> = {}
  // CSRF faqat O'ZGARTIRUVCHI so'rovlarda: GET da server ham tekshirmaydi.
  if (method !== 'GET' && method !== 'HEAD') Object.assign(headers, authHeaders())
  // AKTOR HAR SO'ROVGA qo'yiladi (GET ga ham): `/aktor/holat` va `/audit`
  // ham "men kimman" degan savolga javob berishi kerak.
  const aktorId = getAktorId()
  if (aktorId) headers['X-Actor'] = String(aktorId)
  const opts: RequestInit = { method, headers, credentials: 'include' }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(url, opts)
  if (!res.ok) {
    // 401 — sessiya tugadi yoki kirilmagan. Tokenni tozalab, ilovani
    // kirish ekraniga qaytaramiz: aks holda har bir panel alohida
    // "401" xatosini ko'rsatib, ekran xatolar bilan to'lardi.
    if (res.status === 401) {
      setToken(null)
      onUnauthorized?.()
    }
    let detail = res.statusText
    let raw: unknown = null
    let kod: string | undefined
    let params: Record<string, unknown> | undefined
    let fields: { field: string; code: string }[] | undefined
    let tashxis: string | undefined
    let kodli = false
    try {
      const b = await res.json()
      raw = b.detail
      const xato = b.error
      // KODLI JAVOB (20-vazifadan keyin server shunday qaytaradi):
      // matn SHU YERDA, foydalanuvchi tilida yig'iladi. Ilgari
      // server o'zbekcha jumla yuborardi va u rus/ingliz
      // interfeysiga o'zbekcha yetib borardi.
      if (xato && typeof xato === 'object' && typeof xato.code === 'string') {
        kod = xato.code
        params = (xato.params || {}) as Record<string, unknown>
        fields = xato.fields
        tashxis = xato.diagnostic_id || undefined
        detail = xatoMatni(kod!, params as TVars)
        kodli = true
      } else {
        detail = errMatn(b.detail) || (typeof xato === 'string' ? xato : '')
          || detail
      }
    } catch { /* JSON emas — masalan proksi bergan HTML */ }
    const ra = Number(res.headers.get('Retry-After'))
    // KODSIZ javobda holat raqami MATNDA qoladi: u yagona
    // ma'lumot va uni yashirsak xato "sababsiz" ko'rinardi.
    throw new ApiError(kodli ? detail : `${res.status}: ${detail}`,
      res.status, raw, Number.isFinite(ra) && ra > 0 ? ra : undefined,
      kod, params, fields, tashxis)
  }
  // 204 No Content — TANA BO'SH. DELETE va /catalog/seen shunday javob beradi.
  // Shartsiz res.json() chaqirilsa bu yerda SyntaxError chiqadi va chaqiruvchi
  // muvaffaqiyatli amalni XATO deb qabul qiladi: o'chirish serverda bajarilib,
  // interfeys yangilanmay qolardi.
  if (res.status === 204) return null as T
  const text = await res.text()
  return (text ? JSON.parse(text) : null) as T
}

/** Suhbat — `chat_session` jadvalidan (`SQL_SESSION_LIST`). */
export interface ChatSession {
  id: string
  tender_id: Nullable<number>
  title: Nullable<string>
  lang: Nullable<string>
  /**
   * Suhbat manbasi. `'eval'` -- AVTO-YARATILGAN sessiya
   * (`run_eval.py`), inson suhbati EMAS: eval haqiqiy ijarachi
   * bilan yuradi (`EVAL_COMPANY_ID = 2`), shuning uchun u shu
   * ro'yxatga TUSHADI va interfeys uni ajratishi shart.
   * `null` -- manba yozilmagan davr.
   */
  manba: Nullable<'eval' | 'gonogo' | 'match' | 'panel' | 'global'>
  created_at: string
  updated_at: string
}

/**
 * Saqlangan xabar — `chat_message` jadvalidan (`SQL_MESSAGES`).
 *
 * `error` MAYDONI ATAYLAB BOR: backend xatoli javoblarni ham
 * saqlaydi va qaytaradi ("jimgina o'tkazib yuborilmaydi" tamoyili).
 * Interfeys ularni YASHIRMASLIGI kerak.
 */
export interface ChatStoredMessage {
  id: number
  seq: number
  role: string
  content: unknown
  citations: Nullable<unknown>
  model: Nullable<string>
  latency_ms: Nullable<number>
  stop_reason: Nullable<string>
  error: Nullable<string>
  created_at: string
}

export interface CompanyAccount {
  id: number
  username: string
  company_name: string
  email: Nullable<string>
  active: boolean
  last_login_at: Nullable<string>
  /** CSRF tokeni (auth-4) — sir emas, sarlavhaga qo'yiladi */
  csrf?: string
}

export const api = {
  // --- kirish ---
  login: async (username: string, password: string) => {
    // Javobda TOKEN YO'Q — u `HttpOnly` cookie'da.
    const r = await request<{ csrf: string; expires_at: string; account: CompanyAccount }>(
      'POST', '/auth/login', { body: { username, password } })
    setCsrf(r.csrf)
    setToken('1')
    return r.account
  },
  /** Parolni almashtirish (auth-6). JORIY parol MAJBURIY; javobda
   *  yopilgan boshqa sessiyalar soni qaytadi. */
  setPassword: (currentPassword: string, password: string) =>
    request<{ ok: boolean; closed_sessions: number }>(
      'PUT', '/auth/password',
      { body: { password, current_password: currentPassword } }),

  logout: async () => {
    try { await request<{ ok: boolean }>('POST', '/auth/logout') } finally {
      setToken(null); setCsrf(null)
    }
  },
  me: async () => {
    // Sahifa yangilanganda CSRF tokeni shu yerdan tiklanadi.
    const a = await request<CompanyAccount>('GET', '/auth/me')
    if (a.csrf) setCsrf(a.csrf)
    return a
  },

  tenders: (params?: Params) => request<Paged<TenderRow>>('GET', '/tenders', { params }),
  tender: (id: number) => request<TenderDetail>('GET', `/tenders/${id}`),
  stats: (params?: Params) => request<Stats>('GET', '/stats', { params }),
  regions: (params?: Params) => request<Region[]>('GET', '/regions', { params }),
  statuses: () => request<Status[]>('GET', '/statuses'),
  categories: () => request<Category[]>('GET', '/categories'),
  freshness: () => request<Freshness>('GET', '/freshness'),
  // Mahsulot bo'yicha filtr uchun takliflar (tenderlardagi haqiqiy tovar nomlari)
  products: (params?: Params) => request<ProductSuggestion[]>('GET', '/products', { params }),
  // AI moslik tahlili — tender katalogga mos keladimi (natija backendда keshlanadi)
  aiMatch: (id: number, params?: Params) =>
    request<AiMatchResult>('POST', `/tenders/${id}/ai-match`, { params }),
  // AI Go/No-Go tavsiyasi — qatnashish kerakmi (11 mezon)
  aiGoNogo: (id: number, params?: Params) =>
    request<GoNoGoResult>('POST', `/tenders/${id}/ai-gonogo`, { params }),

  // --- ERP holati (auth-3): so'rovni SERVER qiladi, brauzer ERP ga
  // to'g'ridan-to'g'ri bormaydi. `api/erp_status.py` ga qarang.
  erpStatus: (id: number) => request<{
    ready: boolean
    opportunities: {
      opportunity_id: number
      status: string
      status_label: string | null
      priority: string | null
      broker_name: string | null
      client_name: string | null
      created_at: string | null
    }[]
  }>('GET', `/tenders/${id}/erp-status`),

  // --- P0-2: hujjat matni holati (deterministik parserlar, AI emas) ---
  documentsText: (id: number) =>
    request<DocumentTextResult>('GET', `/tenders/${id}/documents/text`),

  // --- P0-6: ombor qoldig'ini tekshirish (mos pozitsiyalar bo'yicha) ---
  stockCheck: (id: number) => request<StockCheckResult>('GET', `/tenders/${id}/stock-check`),

  // --- P0-7: narx hisobi (sof formula) ---
  pricingSettings: () => request<Partial<PricingInputs>>('GET', '/pricing/settings'),
  savePricingSettings: (body: unknown) => request<unknown>('PUT', '/pricing/settings', { body }),
  tenderPricing: (id: number) => request<Nullable<PricingSaved>>('GET', `/tenders/${id}/pricing`),
  saveTenderPricing: (id: number, body: unknown) =>
    request<PricingSaved>('POST', `/tenders/${id}/pricing`, { body }),

  // --- J3: talablar va ularni tasdiqlash ---
  //
  // Tasdiqlash MAJBURIY: tekshirilmagan talabni cheklistga ulash AI
  // xatosini qaror qatlamiga o'tkazadi (arvoh blocker).
  talabNavbat: (limit = 100, f?: Partial<TalabFiltr>) =>
    // `manbalar` — har manba QANCHA natija berishi. Filtr o'zgartira
    // olmaydigan variantni interfeys o'chirib qo'yadi va sonini
    // yozadi; aks holda u BUZUQ tugma bo'lib ko'rinardi.
    request<{ queue: TalabNavbat[]; jami: number; korsatildi: number
              manbalar: ManbaSonlari }>(
      'GET', `/requirements/queue?limit=${limit}`
             + (f?.region ? `&region=${encodeURIComponent(f.region)}` : '')
             + (f?.q ? `&q=${encodeURIComponent(f.q)}` : '')
             + (f?.manba ? `&manba=${f.manba}` : '')
             + (f?.past ? '&past=true' : '')
             + (f?.otgan ? '&otgan=true' : '')
             + (f?.katalog ? '&katalog=true' : '')),
  tenderTalablar: (id: number) =>
    request<{ tender_id: number; rejim: ReviewRejim; summary: TalabXulosa
              items: Talab[] }>(
      'GET', `/tenders/${id}/requirements`),
  talabTezlik: () =>
    request<ReviewTezlik>('GET', '/requirements/speed'),
  hujjatTurlari: () =>
    request<{ doc_types: HujjatTuri[] }>('GET', '/requirements/doc-types'),
  /**
   * INSON qarorini yozadi. `status` FAQAT inson qarori bo'lishi
   * mumkin (`InsonQarori`) — mashina holatlarini bu yerdan yuborib
   * bo'lmaydi va server ham ularni rad etadi (`Literal` sxemasi).
   */
  talabReview: (reqId: number, body: {
    status: InsonQarori; corrected_value?: string; note?: string
    doc_type?: string; blind_value?: string
  }) => request<{ id: number; tender_id: number; review_status: TalabHolat
                 review_action: 'approve' | 'reject' | 'correct'
                 reviewed_by: number; reviewed_at: string
                 previous_value: string | null
                 corrected_value: string | null
                 qolgan_kutayotgan: number
                 // KO'RIK TUGAGANDA navbat SHU ZAHOTI qayta
                 // hisoblanadi. `null` — ko'rik hali tugamagan.
                 yonaltirish: Yonaltirish | null }>(
    'POST', `/requirements/${reqId}/review`, { body }),
  talabReviewAll: (tenderId: number, status: 'approved' | 'rejected') =>
    request<{ tender_id: number; ozgardi: number; status: string
              yonaltirish: Yonaltirish | null }>(
      'POST', `/tenders/${tenderId}/requirements/review-all`,
      { body: { status } }),

  // --- BROKERGA YO'NALTIRISH ---
  //
  // Malaka tekshiruvi BEPUL va deterministik: `tender_requirement`
  // (turlangan) bilan `company_profile` (turlangan) SQL da
  // solishtiriladi. O'lchandi: 500 tender 1.3 s, 0 pullik chaqiruv.
  malaka: (tenderId: number) =>
    request<MalakaNatija>('GET', `/tenders/${tenderId}/qualification`),
  // `jami` — MOS KELGANLARNING to'liq soni, qaytarilganlar EMAS.
  // `korsatildi` bilan solishtirib interfeys kesilganini biladi.
  brokerNavbat: (f?: Partial<NavbatFiltr>, limit = 100) =>
    request<{ items: RoutingItem[]; jami: number; korsatildi: number
              moslik: RoutingMoslik }>(
      'GET', `/routing/queue?limit=${limit}`
             + (f?.holat ? `&holat=${f.holat}` : '')
             + (f?.qaror ? `&qaror=${f.qaror}` : '')
             + (f?.region ? `&region=${encodeURIComponent(f.region)}` : '')
             + (f?.q ? `&q=${encodeURIComponent(f.q)}` : '')
             + (f?.eskirgan ? '&eskirgan=true' : '')
             + (f?.katalog ? '&katalog=true' : '')),
  brokerYangila: (limit = 2000) =>
    request<{ baholandi: number; navbatga_tushdi: number
              yangilandi: number; kesildi: number; jami_nomzod: number
              inson_qarori_eskirdi: number
              qarorlar: Record<string, number>; navbat_hajmi: number }>(
      'POST', `/routing/refresh?limit=${limit}`),
  brokerOch: (routingId: number, broker?: string) =>
    request<{ id: number; holat: RoutingHolat }>(
      'POST', `/routing/${routingId}/open`
              + (broker ? `?broker=${encodeURIComponent(broker)}` : '')),
  // `broker` MAYDONI OLIB TASHLANDI: qarorni KIM qo'yganini mijoz
  // yozardi va uni hech narsa tekshirmasdi. Endi aktor SERVERDA
  // `X-Actor` sarlavhasidan aniqlanadi va ro'yxatdan tekshiriladi.
  // `olindi` qarori ERP da ISH KARTASIGA aylanadi (`api/topshiriq.py`),
  // shuning uchun qaror bilan birga ish taqsimoti ham yuboriladi:
  // kimga, qanchalik shoshilinch, qachongacha. Qarorning KIMLIGI esa
  // avvalgidek serverda aniqlanadi (mijoz yozmaydi).
  brokerQaror: (routingId: number, body: {
    qaror: InsonQaror; izoh?: string
    hodim_actor_id?: number | null
    ustuvorlik?: 'low' | 'medium' | 'high'
    muddat?: string | null
  }) => request<{ id: number; tender_id: number; ai_qaror: AiQaror
                  inson_qaror: InsonQaror; holat: RoutingHolat
                  ai_ozgardi: boolean
                  topshiriq?: { holat: string; id?: number
                                hodim_actor_id?: number | null
                                xato?: string } }>(
    'POST', `/routing/${routingId}/decision`, { body }),

  // --- auth-6: aktor va audit ---
  aktorlar: (faqatFaol = false) =>
    request<{ tayyor: boolean; aktorlar: Aktor[]; meniki?: Kimlik
              sabab?: string }>(
      'GET', '/aktor', { params: { faqat_faol: faqatFaol } }),
  aktorQosh: (body: { login: string; ism: string; rol: AktorRol
                      manba?: 'erp' | 'mahalliy'; erp_user_id?: number
                      izoh?: string }) =>
    request<Aktor>('POST', '/aktor', { body }),
  aktorYangila: (id: number, body: { rol?: AktorRol; ism?: string
                                     active?: boolean; izoh?: string }) =>
    request<Aktor>('PATCH', `/aktor/${id}`, { body }),
  aktorHolat: () => request<AktorHolat>('GET', '/aktor/holat'),
  validatsiyaHolat: () =>
    request<ValidatsiyaHolat>('GET', '/validatsiya/holat'),
  audit: (p: { entity?: string; entity_id?: number; actor_id?: number
               limit?: number } = {}) =>
    request<{ tayyor: boolean; yozuvlar: AuditYozuv[] }>(
      'GET', '/audit', { params: p }),

  // --- P0-8: hujjatlar to'liqligi cheklisti ---
  compliance: (id: number) => request<ComplianceResult>('GET', `/tenders/${id}/compliance`),
  documentTypes: () => request<DocumentType[]>('GET', '/company/document-types'),
  companyDocuments: () => request<CompanyDocument[]>('GET', '/company/documents'),
  createCompanyDocument: (body: unknown) =>
    request<CompanyDocument>('POST', '/company/documents', { body }),
  updateCompanyDocument: (id: number, body: unknown) =>
    request<CompanyDocument>('PUT', `/company/documents/${id}`, { body }),
  deleteCompanyDocument: (id: number) =>
    request<null>('DELETE', `/company/documents/${id}`),

  // --- P0-10: bildirishnoma (email + Telegram) ---
  notifySettings: () => request<NotifySettingsData>('GET', '/notify/settings'),
  saveNotifySettings: (body: unknown) =>
    request<NotifySettingsData>('PUT', '/notify/settings', { body }),
  notifyTest: () => request<{ sent: boolean; to: string }>('POST', '/notify/test'),
  // Telegram: bot kim, obunachilar, sinov xabari.
  // BOT TOKENI bu yerdan HECH QACHON o'tmaydi — u serverdagi .env da.
  telegramBot: () => request<TelegramBot>('GET', '/notify/telegram/bot'),
  // Obunachi = botga /start bosgan suhbat. Ro'yxatni server yuritadi.
  telegramSubscribers: () =>
    request<{ subscribers: TelegramSubscriber[]; ready: boolean }>(
      'GET', '/notify/telegram/subscribers'),
  // ULASH: bir martalik havola yaratadi (https://t.me/<bot>?start=<token>)
  telegramCreateLink: () => request<TelegramLink>('POST', '/notify/telegram/link'),
  // Havola bosildimi — interfeys qisqa oraliqda shuni so'rab turadi
  telegramLinkStatus: (token: string) =>
    request<TelegramLinkStatus>(
      'GET', `/notify/telegram/link/${encodeURIComponent(token)}`),
  telegramSetSubscriber: (chatId: string, enabled: boolean) =>
    request<{ subscribers: TelegramSubscriber[] }>(
      'PUT', `/notify/telegram/subscribers/${encodeURIComponent(chatId)}`,
      { body: { enabled } }),
  telegramDeleteSubscriber: (chatId: string) =>
    request<{ subscribers: TelegramSubscriber[] }>(
      'DELETE', `/notify/telegram/subscribers/${encodeURIComponent(chatId)}`),
  // Sinov xabari PLATFORMA TILIDA ketadi (javobdagi `lang` — qaysi tilda).
  telegramTest: (chatId?: string) =>
    request<{
      sent: boolean; chats: string[]; lang: string; messages: number
      errors: { chat_id: string; error: string }[]
    }>('POST', '/notify/telegram/test', { params: { chat_id: chatId } }),

  // Aqlli moslashtirish
  getProfile: () => request<Nullable<CompanyProfileData>>('GET', '/profile'),
  saveProfile: (body: unknown) => request<CompanyProfileData>('PUT', '/profile', { body }),
  match: (body: unknown) => request<Paged<TenderRow>>('POST', '/match', { body }),

  // Saqlangan qidiruvlar (A bosqich)
  searches: () => request<SavedSearch[]>('GET', '/searches'),
  createSearch: (body: unknown) => request<SavedSearch>('POST', '/searches', { body }),
  updateSearch: (id: number, body: unknown) =>
    request<SavedSearch>('PUT', `/searches/${id}`, { body }),
  deleteSearch: (id: number) => request<null>('DELETE', `/searches/${id}`),

  // Mahsulot katalogi + katalog-asosli moslik
  catalog: () => request<Product[]>('GET', '/catalog'),
  createProduct: (body: unknown) => request<Product>('POST', '/catalog', { body }),
  updateProduct: (id: number, body: unknown) => request<Product>('PUT', `/catalog/${id}`, { body }),
  deleteProduct: (id: number) => request<null>('DELETE', `/catalog/${id}`),
  catalogMatch: (body: unknown) => request<CatalogMatchResponse>('POST', '/catalog/match', { body }),
  catalogNewCount: () => request<{ new: number; total: number; deferred?: boolean }>(
    'GET', '/catalog/new-count'),
  catalogSeen: () => request<null>('POST', '/catalog/seen'),

  // --- AI CHAT TARIXI ---------------------------------------------------
  // Backend bu uchtasini ANCHADAN BERI beradi (`GET /chat/sessions`,
  // `/chat/sessions/{id}`, `DELETE /chat/sessions/{id}`), lekin frontend
  // ularni HECH QACHON chaqirmagan: suhbat sahifa yangilanishi bilan
  // yo'qolardi, `chat_session` jadvali esa to'lib borardi.
  chatSessions: (limit = 50) =>
    request<ChatSession[]>('GET', '/chat/sessions', { params: { limit } }),
  chatHistory: (id: string) =>
    request<{ session: ChatSession; messages: ChatStoredMessage[] }>(
      'GET', `/chat/sessions/${encodeURIComponent(id)}`),
  /**
   * TIKLANISH QAYDI — `DAVOM_SOAT` chegarasi uchun o'lchov.
   *
   * `tiklandi` maxraj, `rad` surat. "Yangi suhbat" bosilishi
   * chegara noto'g'ri ekanining signali; global va tenderli
   * kesimlar `v_chat_tiklash` da ALOHIDA sanaladi.
   *
   * XATOSI YUTILADI (chaqiruvchida): o'lchov foydalanuvchi
   * ishini to'xtatmasin.
   */
  chatTiklash: (id: string, holat: 'tiklandi' | 'rad') =>
    request<{ session_id: string; holat: string }>(
      'POST', `/chat/sessions/${encodeURIComponent(id)}/tiklash`,
      { body: { holat } }),
  // O'CHIRMAYDI, ARXIVLAYDI — jurnal va xarajat hisobi saqlanadi.
  chatArchive: (id: string) =>
    request<null>('DELETE', `/chat/sessions/${encodeURIComponent(id)}`),

  // --- KODLASH (o'lchov bosqichi) ---
  // Ekran O'LCHOV ASBOBI: vaqt, manba va qidiruv soni AVTOMATIK
  // yoziladi. Qo'lda yozilsa ular xotiradan tiklanib, taxminga
  // aylanardi.
  kodNavbat: (limit = 40, takliflar = false) =>
    request<KodNavbat>('GET', '/catalog/kod-navbat',
      { params: { limit, takliflar } }),
  /** `kalit` berilsa qidiruv SANOG'I oshadi — "talabsiz" dan oldin
   *  qidirilganmi degan savolning javobi shundan chiqadi. */
  kodQidir: (soz: string, kalit?: string, limit = 6) =>
    request<KodQidiruv>('GET', '/kod/qidir',
      { params: kalit ? { soz, kalit, limit } : { soz, limit } }),
  /**
   * Atama KO'RIB CHIQISHGA ochildi — vaqt hisobi shundan.
   *
   * `qaror` YUBORILMAYDI. Ilgari `qaror: 'kod'` to'ldiruvchi sifatida
   * yuborilardi va u "ochish" ni "qaror" ga o'xshatib qo'yardi —
   * ikkisi BUTUNLAY boshqa hodisa. Server endi alohida model
   * (`AtamaOchishIn`) kutadi va qaror maydonlarini QABUL QILMAYDI.
   */
  kodQarorOchish: (kalit: string, atama: string) =>
    request<{ id: number; ochilgan_at: string }>(
      'POST', '/kod/qaror/ochish', { body: { kalit, atama } }),
  /**
   * INSON qarorini yozadi.
   *
   * `dalil` — inson EKRANDA KO'RGAN hamma narsa. Server uni qayta
   * hisoblamaydi: ML uchun "haqiqat" emas, "inson nimaga qarab
   * qaror qildi" kerak.
   */
  kodQaror: (body: {
    kalit: string; atama: string; qaror: KodQaror
    code?: string | null; manba?: Manba | null
    dalil?: Record<string, unknown> | null
    taklif_code?: string | null; taklif_skor?: number | null
    rad_takliflar?: string[] | null
    qoshimcha_kod?: boolean
    izoh?: string | null
  }) => request<{ id: number; biriktirildi: number; qidiruv_soni: number
                  ochilgan_at: string | null; qaror_at: string }>(
    'POST', '/kod/qaror', { body }),
  kodOlchov: () => request<KodOlchov>('GET', '/kod/qaror/olchov'),
  kodQarorOlchov: () => request<KodOlchov>('GET', '/kod/qaror/olchov'),
  /** Har qaror DALILI bilan — ML to'plamining xom manbai. */
  kodQarorTafsil: (limit = 500) =>
    request<{ tafsil: Record<string, unknown>[] }>(
      'GET', '/kod/qaror/tafsil', { params: { limit } }),
}
