// Backend javoblarining turlari.
//
// MANBA: `api/queries.py` SELECT'lari va `api/main.py` javob modellari.
// Bu yerda FAQAT interfeys ko'rinishida yozilgan — hech qanday mantiq yo'q,
// shuning uchun backend maydonni o'zgartirsa, xato KOMPILYATSIYA paytida
// chiqadi, foydalanuvchi ekranida "undefined" bo'lib emas.
//
// Ixtiyoriy (`?`) va `| null` farqi ataylab: `?` — maydon javobda BO'LMASLIGI
// mumkin (endpointga qarab), `| null` — maydon bor, lekin qiymati bo'sh.

export type Nullable<T> = T | null

// --- umumiy ---------------------------------------------------------------
export interface Paged<T> {
  items: T[]
  total: number
}

export interface Region {
  area_id: string
  name: Nullable<string>
  level: number
}

export interface Status {
  status_code: string
  name: Nullable<string>
}

export interface Category {
  code: string
  name: string
  /** Shu kategoriyadagi tenderlar soni (filtr ro'yxatida ko'rsatiladi) */
  count?: number
  children: Category[]
}

// --- tender ---------------------------------------------------------------
export interface LotSummary {
  lot_id: number
  title: Nullable<string>
  total_sum_lot: Nullable<number>
  item_count: Nullable<number>
  delivery_period: Nullable<number>
  guarantee: Nullable<number>
}

export interface Good {
  good_code: string
  name: Nullable<string>
  unit: Nullable<string>
  amount: Nullable<number>
  price: Nullable<number>
}

export interface LotItemProperty {
  prop_name: string
  val_name: string | number
}

export interface LotItem {
  item_id: number
  name: Nullable<string>
  product_code: Nullable<string>
  delivery_period: Nullable<number>
  guarantee: Nullable<number>
  prod_year: Nullable<number>
  spec: Nullable<string>
  properties?: LotItemProperty[]
}

export interface Lot {
  lot_id: number
  title: Nullable<string>
  total_sum_lot: Nullable<number>
  goods?: Good[]
  items?: LotItem[]
}

/** Moslik balli — ikki manbadan keladi: katalog va saqlangan qidiruv.
 *  Shuning uchun maydonlar IXTIYORIY (manbaga qarab to'plam farq qiladi). */
export interface MatchInfo {
  score?: number
  matched_keywords?: string[]
  reasons?: string[]
}

export interface CatalogMatchInfo {
  score: number
  products: string[]
  by: 'kod' | 'nom'
  positions?: {
    pozitsiya: string
    mahsulot: Nullable<string>
    aniq: boolean
    kod: Nullable<string>
  }[]
  position_count?: number
}

export interface TenderRow {
  id: number
  source_id?: number
  name: Nullable<string>
  status: string
  status_name: Nullable<string>
  totalcost: Nullable<number>
  currency: Nullable<string>
  close_at: Nullable<string>
  publicated_at: Nullable<string>
  first_seen_at?: Nullable<string>
  source_platform: string
  doc_count?: number
  company?: { name: Nullable<string> }
  region?: { name: Nullable<string> }
  lots_summary?: LotSummary[]
  goods_preview?: string[]
  match?: MatchInfo
  catalog?: CatalogMatchInfo
  /**
   * Tender kompaniya profilida ko'rsatilgan hududlardan TASHQARIDA.
   *
   * `false` ikki holatni bildiradi: hudud ichida YOKI o'lchab
   * bo'lmadi (cheklov qo'yilmagan / tender hududi noma'lum).
   * Faqat `true` aniq da'vo — shuning uchun belgi ham shunda
   * ko'rsatiladi.
   */
  hudud_tashqari?: boolean
}

/**
 * "Sizga mos" natijasidagi hudud xulosasi.
 *
 * SAHIFADAN emas, BUTUN natijadan hisoblanadi: sahifadagi son
 * "2 tasi tashqarida" derdi, holbuki jami 11 ta bo'lishi mumkin.
 */
export interface HududXulosa {
  regions: string[]
  tashqari: number
  jami: number
}

export interface CatalogMatchResponse extends Paged<TenderRow> {
  hudud?: HududXulosa
  atama_kesildi?: number
}

export interface AiSummary {
  summary_uz: string
  supplier_profile: Nullable<string>
  key_points?: string[]
  category_tags?: string[]
}

export interface TenderDetail extends TenderRow {
  lot_count?: number
  good_count?: number
  ai?: Nullable<AiSummary>
  detail?: {
    method_marks?: Nullable<string>
    close_time?: Nullable<string>
    company_details?: Nullable<string>
  }
  document_sections?: {
    section: string
    files: {
      file_id: string
      file_ref: Nullable<string>
      name: Nullable<string>
      file_type: Nullable<string>
      size_bytes: Nullable<number>
      download_url: string
    }[]
  }[]
  lots?: Lot[]
}

// --- statistika -----------------------------------------------------------
export interface StatsRegion {
  area_id: Nullable<string>
  name: Nullable<string>
  tender_count: number
  totals_by_currency: { currency: Nullable<string>; total_value: number }[]
}

export interface Stats {
  status: string
  scope: 'provinces' | 'localities'
  selected_region: Nullable<{ area_id: string; name: string }>
  count: number
  by_currency: { currency: string; total_value: number; tender_count: number }[]
  by_region: StatsRegion[]
  by_status?: { status: string; name: Nullable<string>; tender_count: number }[]
}

export interface FreshnessPlatform {
  source_platform: string
  status: string
  age_sec: Nullable<number>
  new: number
}

export interface Freshness {
  overall_age_sec: Nullable<number>
  any_error: boolean
  platforms: FreshnessPlatform[]
  detection?: {
    sample: number
    median_hours: Nullable<number>
    within_1h_pct: Nullable<number>
  }
  /**
   * KORPUS holati — semantik qidiruv qancha tenderni ko'radi.
   *
   * `caught_up` ATAYLAB "tugadi" deb nomlanmagan: korpus o'sib
   * turadi (har soat yangi tender, yangi hujjat, yangi bo'lak), ya'ni
   * yagona to'g'ri holat "quvib yetdi". "Tugadi" deb yozilsa odam ish
   * bitgan deb o'ylardi va navbat yana o'sganini payqamasdi.
   */
  corpus?: Nullable<{
    chunks: number
    unvectorized: number
    tenders: number
    new_24h: number
    /**
     * SOVUQ START yorlig'i. Bo'laklash endigina yurgan bo'lsa
     * `new_24h` butun korpusga teng chiqadi (118 426 dan 118 426) —
     * bu sur'at emas, bir martalik to'ldirish. `false` bo'lsa
     * `new_24h` ni sur'at sifatida KO'RSATMANG.
     */
    growth_reliable: boolean
    caught_up: boolean
  }>
}

// --- BROKERGA YO'NALTIRISH ------------------------------------------------

/** AI tavsiyasi. `ai_gonogo.DECISIONS` bilan bir xil so'zlar. */
export type AiQaror = 'go' | 'review' | 'no_go'

/** Brokerning O'Z qarori — AI dan MUSTAQIL saqlanadi. */
export type InsonQaror = 'olindi' | 'rad' | 'kutilsin'

export type RoutingHolat = 'yangi' | 'korilmoqda' | 'yopildi'

/**
 * Broker navbatining filtri. Bo'sh satr / `false` = filtr yo'q.
 *
 * FILTR SERVERGA KETADI. Mijoz tomonida filtrlash faqat olingan
 * sahifaga tegardi (navbat 180, sahifa 100) va ikkinchi yuzlikdagi
 * tender "topilmadi" bo'lib ko'rinardi.
 */
export interface NavbatFiltr {
  q: string
  region: string
  holat: '' | RoutingHolat
  qaror: '' | AiQaror
  eskirgan: boolean
  /**
   * Faqat "Sizga mos" bo'limidagi tenderlar.
   *
   * Ta'rif SERVERDA, `kodlash.mos_tender_idlari()` da — ya'ni
   * ro'yxatning O'ZI bilan bir xil to'plam. Mijoz tomonida
   * hisoblash ikkinchi haqiqat yasardi.
   */
  katalog: boolean
}

/**
 * Har manba QANCHA natija berishi.
 *
 * O'LCHANGAN NUQSON (2026-09-03): "Manba" filtri qo'shilganda
 * ko'rinishdagi `naqshdan`/`modeldan` ustunlariga qaraldi, lekin ular
 * HAQIQATAN farq qiladimi degan savol berilmadi. Bugun ko'rik
 * navbatidagi HAMMA talab `naqsh` dan (LLM qatlami pullik va
 * qulflangan) — ya'ni "Naqshdan" hech narsani o'zgartirmasdi,
 * "Modeldan" esa ro'yxatni bo'shatardi. Ikkalasi ham BUZUQ deb
 * o'qilardi.
 *
 * Endi son yoniga yoziladi va noli o'chiriladi: hech narsa
 * o'zgartira olmaydigan boshqaruv elementi — boshqaruv yo'qligidan
 * yomonroq, u interfeys buzuq degan xulosani o'rgatadi.
 */
export interface ManbaSonlari {
  naqsh: number
  llm: number
}

/** Ko'rib chiqish (Talablar) navbatining filtri. */
export interface TalabFiltr {
  q: string
  region: string
  /** Faqat past ishonchli talabi borlar. */
  past: boolean
  /** Talab manbai: naqsh yoki model. */
  manba: '' | 'naqsh' | 'llm'
  /** Faqat "Sizga mos" bo'limidagi tenderlar. */
  katalog: boolean
  /**
   * Muddati O'TGAN tenderlarni ham ko'rsatish.
   *
   * Standart `false`. O'LCHANGAN NUQSON (2026-09-03): navbatda
   * muddat sharti YO'Q edi va tartib `close_at` bo'yicha o'sish —
   * ya'ni butun birinchi sahifa allaqachon yopilgan tenderlardan
   * iborat edi (989 dan 534 tasi o'tgan).
   */
  otgan: boolean
}

export interface RoutingItem {
  id: number
  tender_id: number
  tender_name: Nullable<string>
  close_at: Nullable<string>
  totalcost: Nullable<number>
  currency: Nullable<string>
  kun_qoldi: Nullable<number>

  ai_qaror: Nullable<AiQaror>
  /** 0..1. Maxraj — O'LCHANGAN mezonlar, jami emas. */
  ai_ball: Nullable<number>
  ai_manba: Nullable<'malaka' | 'gonogo'>
  /** Qamrovni ham aytadi: "3/3 mezon o'tdi, 4 ta O'LCHANMADI". */
  ai_sabab: Nullable<string>

  /**
   * INSON QARORI ESKIRDI: broker qaror bergandan keyin `ai_qaror`
   * o'zgardi. Bu eng shoshilinch holat — broker YOLG'ON ISHONCH
   * bilan yuribdi, shuning uchun navbatda eng tepada turadi.
   */
  ai_ozgardi: boolean
  ai_qaror_eski: Nullable<AiQaror>

  inson_qaror: Nullable<InsonQaror>
  broker_nomi: Nullable<string>
  holat: RoutingHolat
  created_at: Nullable<string>
  /**
   * ERP integratsiyasi UMUMAN mavjudmi — GLOBAL bayroq.
   * Bu AYNAN SHU tender ERP da borligini BILDIRMAYDI. Aralashtirish
   * brauzerda topilgan xato edi: har yopilgan qatorga "ERP da bor"
   * yozilardi.
   */
  erp_bor: boolean
  /** AYNAN SHU tender ERP da ochilganmi. */
  erp_ish: boolean
}

export interface RoutingMoslik {
  qatorlar: {
    ai_manba: string; ai_qaror: AiQaror; jami: number
    olindi: number; rad: number
    /**
     * `null` — HISOBLANMAGAN, nol EMAS. Sababi yonidagi
     * ustunda; interfeys uni `?? 0` bilan nolga AYLANTIRMAYDI.
     */
    moslik_foiz: Nullable<number>
    /**
     * Foiz nega yo'q:
     *   `ai_qaror_yoq`  `review` — AI qaror qilmagan, formula
     *                   struktura bo'yicha nol beradi
     *   `namuna_kam`    qator `MOSLIK_MIN` dan kam kuzatuvga tayanadi
     */
    foiz_yoq_sababi: Nullable<'ai_qaror_yoq' | 'namuna_kam'>
  }[]
  inson_qarorlari: number
  /** Foiz ma'noli bo'lishi uchun kerakli minimal qaror soni. */
  kerakli_qaror: number
  is_sample: boolean
  /**
   * O'LCHANDIMI — kamida `kerakli_qaror` ta qaror bormi.
   *
   * `false` bo'lsa "moslik 0%" EMAS, "hali o'lchanmagan" deb
   * ko'rsatiladi. BITTA qarordan "100%" chiqarish eng zararli
   * shakl edi: u haqiqiy o'lchov kabi ko'rinardi.
   */
  olchandi: boolean
  izoh: Nullable<string>
}

/** Malaka mezoni hukmi. `ai_gonogo.STATUSES` bilan bir xil. */
export type MalakaHolat = 'ok' | 'risk' | 'fail' | 'malumot_yoq'

export interface MalakaDalil {
  requirement_id: number
  name: string
  qiymat: Nullable<string>
  confidence: number
  review_status: string
  file_ref: Nullable<string>
  char_start: Nullable<number>
  /** Talabni hech kim tekshirmagan va ishonchi chegaradan past. */
  tasdiqlanmagan: boolean
}

export interface MalakaMezon {
  key: string
  label: string
  status: MalakaHolat
  izoh: string
  dalillar: MalakaDalil[]
}

export interface MalakaNatija {
  tender_id: number
  decision: AiQaror
  criteria: MalakaMezon[]
  ok: number
  fail: number
  risk: number
  /** O'LCHANGAN mezonlar soni. `jami_mezon` dan kam bo'lishi normal. */
  olchandi: number
  jami_mezon: number
  talablar_soni: number
  profil_toldirilgan: Nullable<number>
  profil_jami: Nullable<number>
  /**
   * Profil O'YLAB TOPILGAN sinov qiymatlari bilan to'ldirilgan.
   * Natijadan statistik xulosa CHIQARILMAYDI.
   */
  is_sample: boolean
  sample_note: Nullable<string>
}

// --- katalog / profil -----------------------------------------------------
export interface Product {
  id: number
  name: string
  category_code: Nullable<string>
  keywords: string[]
  unit: Nullable<string>
  price: Nullable<number>
  currency: Nullable<string>
  stock_qty: Nullable<number>
  stock_unit: Nullable<string>
  /** Katta katalogda ro'yxatni tez ochish uchun null — hisob keyinga qoldirilgan. */
  match_count: Nullable<number>
  match_count_deferred?: boolean
  notify: boolean
}

export interface ProductSuggestion {
  name: string
  tender_count: number
}

export interface CompanyProfileData {
  contact_name: Nullable<string>
  email: Nullable<string>
  phone: Nullable<string>
  position: Nullable<string>
  name: Nullable<string>
  about: Nullable<string>
  constraints_note: Nullable<string>
  certificates: string[]
  clearances: string[]
  experience_years: Nullable<number>
  max_contract_value: Nullable<number>
  max_contract_currency: Nullable<string>
  employees: Nullable<number>
  capacity_note: Nullable<string>
  lead_time_days: Nullable<number>
  min_margin_percent: Nullable<number>
  regions: string[]
  min_cost: Nullable<number>
  max_cost: Nullable<number>
  keywords: string[]
  currency: Nullable<string>
}

export interface SavedSearch {
  id: number
  name: string
  keywords: string[]
  regions: string[]
  currency: Nullable<string>
  min_cost: Nullable<number>
  max_cost: Nullable<number>
  /** Ochiq tenderlardan nechtasi shu filtrga mos (server hisoblaydi). */
  match_count?: number

  // --- SERVER QAYTARADI, LEKIN HALI HECH NARSA QILMAYDI ---
  // Ular interfeysda KO'RSATILMAYDI: ishlamaydigan tugmani
  // ko'rsatish yolg'on va'da bo'lardi. Holati va nima uchun
  // qoldirilgani `docs/saved_search.md` §3 da.
  //
  // Tur ta'rifida ATAYLAB turibdi: server javobida ular bor va
  // "yo'q" deb ko'rsatish turni haqiqatdan uzoqlashtirardi.
  /** Bildirishnoma tsikli buni O'QIMAYDI (`company_profile` dan oladi). */
  notify?: boolean
  /** Skorlashda ISHLATILMAYDI. */
  categories?: string[]
  /** Hech qayerda to'ldirilmaydi — "yangi moslar" belgisi yo'q. */
  last_seen_at?: Nullable<string>
  created_at?: string
}

// --- AI -------------------------------------------------------------------
export interface AiMatchResult {
  documents?: AiDocsMeta
  verdict: 'mos' | 'qisman' | 'mos_emas'
  score: number
  reason_uz: string
  matched_items?: string[]
  requirements?: string[]
  risks?: string[]
  cached: boolean
  model: Nullable<string>
}

export interface GoNoGoResult {
  documents?: AiDocsMeta
  decision: 'go' | 'review' | 'no_go'
  confidence: number
  summary_uz: string
  blockers?: string[]
  next_steps?: string[]
  missing_data?: string[]
  criteria?: { key: string; status: string; note_uz: string }[]
  criteria_labels?: { key: string; label: string }[]
  cached: boolean
  model: Nullable<string>
}

// --- hujjatlar ------------------------------------------------------------
export interface DocumentTextItem {
  file_ref: string
  name: Nullable<string>
  status: string
  reason: Nullable<string>
  char_count: Nullable<number>
  page_count: Nullable<number>
  preview: Nullable<string>
}

export interface DocumentTextResult {
  documents: DocumentTextItem[]
  summary: { ok: number; manual_review: number }
}

/** AI tahlili qaysi hujjat matniga tayangani (api/ai_docs.py `meta`). */
export interface AiDocsMeta {
  available: boolean
  total_files?: number
  readable?: number
  chars: number
  truncated: boolean
  used: { name: string; chars_used: number; chars_total: number; partial: boolean }[]
  unreadable: { name: string; reason: string }[]
  skipped_for_budget?: string[]
}

export interface DocumentType {
  code: string
  label: string
  hint: Nullable<string>
  // `true` — biznes-jarayonning odatiy ariza to'plami: tender matnida
  // yozilmagan bo'lsa ham cheklistда turadi (api/compliance.py BASE_CODES).
  base: boolean
}

export interface CompanyDocument {
  id: number
  doc_type: string
  label: Nullable<string>
  name: string
  number: Nullable<string>
  issued_at: Nullable<string>
  valid_until: Nullable<string>
  file_name: Nullable<string>
  file_ref: Nullable<string>
  note: Nullable<string>
  status: 'ok' | 'expiring_soon' | 'expired'
  days_left: Nullable<number>
}

export interface ComplianceItem {
  doc_type: string
  label: string
  status: 'ok' | 'expiring_soon' | 'expired' | 'missing'
  required_by: 'tender' | 'base'
  evidence: string
  evidence_source: Nullable<string>
  confidence: Nullable<number>
  hint: Nullable<string>
  days_left: Nullable<number>
  document: Nullable<CompanyDocument>
}

export interface ComplianceResult {
  items: ComplianceItem[]
  extra_documents?: { label: string }[]
  summary: {
    ready: number
    expiring_soon: number
    expired: number
    missing: number
    blocking: number
    note: string
    disclaimer: string
  }
}

// --- ombor ----------------------------------------------------------------
export interface StockItem {
  lot_id: number
  item_id: number
  name: string
  unit: Nullable<string>
  required_qty: Nullable<number>
  available_qty: Nullable<number>
  shortfall_qty: Nullable<number>
  status: 'yetarli' | 'yetishmaydi' | 'nomalum'
  status_label: string
  reason: Nullable<string>
  qty_note: Nullable<string>
  product: { name: string; stock_age_days: Nullable<number> }
}

export interface StockCheckResult {
  items: StockItem[]
  shortages: StockItem[]
  preliminary: boolean
  stock?: { warning: Nullable<string> }
  summary: {
    positions: number
    matched: number
    ok: number
    short: number
    unknown: number
    unmatched: number
  }
}

// --- import ---------------------------------------------------------------
export interface ImportIssue {
  row: number
  field: string
  column: string
  value: Nullable<string>
  message: string
}

export interface ImportResult {
  rows_total: number
  rows_ok: number
  rows_error: number
  inserted: number
  updated: number
  header_row: number
  format: string
  errors?: ImportIssue[]
  warnings?: ImportIssue[]
  columns?: { detected: Record<string, string>; unknown: string[] }
  preview?: {
    row: number
    name: string
    keywords: string[]
    unit: Nullable<string>
    stock_qty: Nullable<number>
    cost_price: Nullable<number>
  }[]
}

// Hujjatlar shabloni importi — katalog importi bilan bir xil shartnoma
// (qator bo'yicha xato, dry-run), faqat `preview` qatorlari boshqa.
export interface DocumentImportResult {
  dry_run: boolean
  rows_total: number
  rows_ok: number
  rows_error: number
  inserted: number
  updated: number
  header_row: number
  format: string
  errors?: ImportIssue[]
  warnings?: ImportIssue[]
  columns?: { detected: Record<string, string>; unknown: string[]; missing: string[] }
  preview?: {
    row: number
    doc_type: string
    label: string
    name: string
    number: Nullable<string>
    issued_at: Nullable<string>
    valid_until: Nullable<string>
    status: 'ok' | 'expiring_soon' | 'expired' | 'missing'
    file_ref: Nullable<string>
  }[]
}

// --- narx hisobi ----------------------------------------------------------
export interface PricingItem {
  name: string
  unit: string
  qty: number | string
  unit_cost: number | string
  ref_price?: Nullable<number>
}

export interface PricingInputs {
  markup_percent: number | string
  risk_reserve_percent: number | string
  risk_reserve_fixed: number | string
  logistics_percent: number | string
  logistics_fixed: number | string
  vat_percent: number | string
  currency: Nullable<string>
  items: PricingItem[]
  manual_price: number | string | null
  budget?: Nullable<number>
  budget_currency?: Nullable<string>
  min_margin_percent?: Nullable<number>
}

export interface PricingSaved {
  inputs: PricingInputs
  note: Nullable<string>
  updated_at: string
}

// --- bildirishnoma --------------------------------------------------------
export interface NotifySettingsData {
  enabled: boolean
  /** Foydalanuvchi kiritadigan YAGONA email maydoni — qabul qiluvchi. */
  email: Nullable<string>
  min_score: number
  base_url: string
  telegram_enabled: boolean
  /** ESKI maydon — obunachilar jadvaliga ko'chirilgan, endi ishlatilmaydi. */
  telegram_chat_id: Nullable<string>
  /**
   * Xabar tili — INTERFEYS tili bilan bir xil ('uz' | 'ru' | 'en').
   * Bazada turadi, chunki xabarni server yuboradi (ETL dan keyin, ilova
   * ochiq bo'lmaganda ham) va u brauzerdagi tanlovni ko'rmaydi.
   */
  lang: string
  /** `schema_patch_notify_lang.sql` qo'llanganmi (yo'q bo'lsa til saqlanmaydi) */
  lang_ready: boolean
  /** Platforma email yubora oladimi (server .env sozlamasi) */
  smtp_ready: boolean
  /** Xabar qaysi manzildan ketadi (server .env: SMTP_FROM) */
  smtp_from: Nullable<string>
  telegram_token_set: boolean
  telegram_ready: boolean
  /** `notify_telegram_subscriber` jadvali bazadami (patch qo'llanganmi) */
  subscribers_ready: boolean
  effective_email: Nullable<string>
}

/** Bir martalik Telegram ulash havolasi */
export interface TelegramLink {
  token: string
  url: string
  bot: string
  expires_at: Nullable<string>
  ttl_minutes: number
}

export interface TelegramLinkStatus {
  found: boolean
  connected: boolean
  chat_id?: Nullable<string>
  expired?: boolean
  subscribers: TelegramSubscriber[]
}

/** Telegram obunachisi — botga /start bosgan suhbat.
 *  Ro'yxatni server yuritadi (`notify_telegram_subscriber`), interfeys faqat
 *  `enabled` ni o'zgartira oladi: qolgani Telegramdan keladi. */
export interface TelegramSubscriber {
  chat_id: string
  title: Nullable<string>
  chat_type: Nullable<string>
  username: Nullable<string>
  enabled: boolean
  /** 'link' = ulash havolasi bilan tasdiqlangan; 'legacy' = eski usulda */
  source: string
  first_seen_at: Nullable<string>
  last_seen_at: Nullable<string>
}

export interface TelegramBot {
  id: number
  username: Nullable<string>
  first_name: Nullable<string>
}

// --- J3: TENDER TALABLARI va ularni TASDIQLASH ---------------------
//
// `method` — talab QANDAY olingani. UI da vizual farqlanadi:
// `reyestr` rasmiy yozuv (tasdiqlash talab qilmaydi), `naqsh` va
// `llm` esa AI natijasi va TEKSHIRILISHI kerak.
export type TalabUsul = 'reyestr' | 'naqsh' | 'llm'
/**
 * Talabning KO'RIB CHIQISH holati — FAQAT INSON o'qi.
 *
 * `extracted` va `pending_review` — mashina qo'yadi.
 * `approved` / `rejected` / `corrected` — INSON qarori, va baza
 * ularni `reviewed_by` bo'lmasdan yozishga yo'l qo'ymaydi
 * (`tender_requirement_inson_qarori_chk`).
 *
 * ILGARI `pending | approved | rejected | corrected` edi va reyestr
 * pozitsiyalari `approved` bo'lib yozilardi — interfeys 1 487 ta
 * ko'rilmagan talabni "tasdiqlangan" deb ko'rsatardi.
 */
export type TalabHolat =
  | 'extracted'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'corrected'

/**
 * KO'RIK TUGAGACH NAVBATGA NIMA BO'LGANI.
 *
 * Talab tasdiqlangach server `routing.korik_tugadi()` ni chaqiradi
 * va natija SHU YERDA qaytadi -- ilgari bu jimgina keyingi ETL
 * yurishiga qolardi va broker eski ballni ko'rib turardi.
 *
 *   navbatda    tender navbatda (`go`/`review`)
 *   no_go       malaka o'tmadi -- navbatga qo'shilmadi yoki CHIQDI
 *   yopiq       muddat o'tgan, baholanmaydi (`SQL_NOMZODLAR` qoidasi)
 *   tender_yoq  tender topilmadi
 *   xato        yangilash yiqildi -- KO'RIK BUZILMADI, sabab `xato` da
 */
export type YonaltirishHolat =
  | 'navbatda' | 'no_go' | 'yopiq' | 'tender_yoq' | 'xato'

export interface Yonaltirish {
  holat: YonaltirishHolat
  /** Yozuv HAQIQATAN o'zgardimi (sabab matni ham sanaladi). */
  ozgardi: boolean
  /** Broker allaqachon qaror bergan va AI fikri o'zgargan. */
  inson_qarori_eskirdi: boolean
  ai_qaror: AiQaror | null
  routing_id: number | null
  xato?: string
}

/** INSON qo'ya oladigan holatlar (API `Literal` bilan qulflangan). */
export type InsonQarori = 'approved' | 'rejected' | 'corrected'

/**
 * MASHINA o'qi — ma'lumot QAYERDAN keldi. `TalabHolat` dan MUSTAQIL.
 *   manba       platformaning rasmiy reyestr yozuvi (xulosa emas)
 *   ajratilgan  matndan naqsh yoki model chiqargan
 */
export type MashinaHolat = 'manba' | 'ajratilgan'

/** `blind` — model javobi YASHIRIN (anchoring ga qarshi). */
export type ReviewRejim = 'blind' | 'anchored'

export interface HujjatTuri {
  code: string
  label: string
  /** `base=true` — har tenderda talab qilinadigan asosiy hujjat. */
  base: boolean
}

export interface Talab {
  id: number
  /**
   * Talab QAYSI hujjat turini so'raydi (`compliance.DOC_TYPES` kodi),
   * yoki `'yoq'` / `'boshqa'`.
   *
   * `null` = HALI SO'RALMAGAN — `'yoq'` dan FARQ QILADI: birinchisi
   * "inson qaramagan", ikkinchisi "qaradi va tegishli emas dedi".
   */
  doc_type: Nullable<string>
  /**
   * YOPIQ rejimda inson model javobini KO'RMASDAN yozgan qiymat.
   * Kelishmovchilik darajasi shundan hisoblanadi.
   */
  blind_value: Nullable<string>
  name: string
  method: TalabUsul
  source: string
  attrs: Record<string, unknown> | null
  confidence: number
  is_mandatory: boolean
  raw_snippet: Nullable<string>
  file_ref: Nullable<string>
  char_start: Nullable<number>
  char_end: Nullable<number>
  review_status: TalabHolat
  mashina_holat: MashinaHolat
  review_action: Nullable<'approve' | 'reject' | 'correct'>
  reviewed_by: Nullable<number>
  previous_value: Nullable<string>
  corrected_value: Nullable<string>
  review_note: Nullable<string>
  reviewed_at: Nullable<string>
}

export interface TalabNavbat {
  tender_id: number
  tender_name: Nullable<string>
  close_at: Nullable<string>
  kutayotgan: number
  modeldan: number
  naqshdan: number
  eng_past_ishonch: Nullable<number>
  past_ishonchli: number
  ajratilgan: Nullable<string>
}

export interface TalabXulosa {
  jami: number
  majburiy: number
  hujjatdan: number
  naqshdan: number
  modeldan: number
  past_ishonchli: number
  kutayotgan?: number
  /** MASHINA chiqargani — inson ko'rmagan va navbatda ham emas. */
  mashina_chiqargan?: number
  /** FAQAT inson tasdiqlagani (`approved` + `corrected`). */
  tasdiqlangan?: number
  eng_past_ishonch: Nullable<number>
  usullar: string[]
  holat: Nullable<string>
  izoh: Nullable<string>
}

/**
 * Ko'rib chiqish tezligi — pilotning yagona noma'lum raqami.
 *
 * MEDIANA bo'yicha bashorat qilinadi, o'rtacha bo'yicha emas: bitta
 * juda uzun tender o'rtachani buzadi, medianaga esa ta'sir qilmaydi.
 */
export interface ReviewTezlik {
  olchangan_tender: number
  olchangan_talab: number
  ortacha_sekund: number
  mediana_sekund: number
  eng_tez: number
  eng_sekin: number
  sekund_talabga: number
  navbatda_qolgan: number
  qolgan_soat: Nullable<number>
  /**
   * NAVBAT O'SISH SUR'ATI. `qolgan_soat` navbat MUZLAB turganini
   * taxmin qiladi; aslida ETL soatiga ishlaydi va navbat to'lib
   * boradi. Agar o'sish quvvatdan yuqori bo'lsa, "har talabni inson
   * tasdiqlaydi" modeli umuman ishlamaydi.
   */
  sutkalik_osish: number
  /**
   * SOVUQ START yorlig'i. Birinchi kunlarda "oxirgi 24 soat" butun
   * navbatni qamrab oladi (604 dan 604) — bu bir martalik to'ldirish,
   * sur'at emas. `false` bo'lsa `quvvat_yetadimi` ham `null`.
   */
  osish_ishonchli: boolean
  osish_izohi: Nullable<string>
  kunlik_quvvat: Nullable<number>
  quvvat_yetadimi: Nullable<boolean>
  izoh: Nullable<string>
}

// --- KODLASH NAVBATI (o'lchov bosqichi) ---
//
// Ekran O'LCHOV ASBOBI sifatida quriladi: 40 ta haqiqiy qaror qabul
// qilinadi va uch raqam AVTOMATIK yoziladi (vaqt, manba, qidiruv
// soni). Qoida jadvalining shakli o'sha raqamlardan aniqlanadi.
export interface KodPozitsiya {
  code: string
  n_poz: number
  n_ochiq: number
  namunalar: string[]
}

/** Qaror turlari — baza `kod_qaror_turi` CHECK i bilan AYNAN mos. */
export type KodQaror = 'kod' | 'talabsiz' | 'dalilsiz' | 'otkazildi'

/** Qaror QAYERDAN keldi. */
/** Aktor — ERP hodimiga XARITA. Kimlik ombori EMAS: parol yo'q,
 *  kirish bermaydi. Faqat "qarorni kim qo'ydi" savoliga javob beradi. */
export type AktorRol = 'kuzatuvchi' | 'koruvchi' | 'tasdiqlovchi' | 'admin'

export interface Aktor {
  id: number
  company_id: number
  manba: 'erp' | 'mahalliy'
  erp_user_id: number | null
  login: string
  ism: string
  rol: AktorRol
  active: boolean
  izoh: string | null
}

/** Atribut QANCHALIK ishonchli. `erp_sessiya` — isbotlangan;
 *  `aktor_elon` — e'lon qilingan, isbotlanmagan; `kompaniya_sessiyasi`
 *  — faqat kompaniya ma'lum; `servis` — odam yo'q;
 *  `kuzatuvdan_oldin` — aktor kuzatuvi joriy etilishidan oldin. */
export type Ishonch = 'erp_sessiya' | 'aktor_elon' | 'kompaniya_sessiyasi'
  | 'servis' | 'kuzatuvdan_oldin'

export interface Kimlik {
  company_id: number
  actor_id: number | null
  ishonch: Ishonch
  rol: AktorRol | null
  login: string | null
  ism: string | null
}

export interface AtributSifati {
  jadval: string
  inson_qarori: number
  isbotlangan: number
  elon_qilingan: number
  faqat_kompaniya: number
  nomalum: number
  aktorli: number
}

export interface AktorHolat {
  tayyor: boolean
  sabab?: string
  meniki?: Kimlik
  aktor_majburiy?: boolean
  erp_kontekst?: boolean
  erp_moslik?: { tekshirildi: boolean; sabab?: string; erp_aktorlari: number
                 yetim: { actor_id: number; login: string; erp_user_id: number }[] }
  atribut_sifati?: AtributSifati[]
  rollar?: AktorRol[]
  ruxsat_matritsasi?: Record<string, AktorRol[]>
}

export interface AuditYozuv {
  id: number
  at: string
  amal: string
  entity: string
  entity_id: number
  ishonch: Ishonch
  actor_id: number | null
  actor_login: string | null
  actor_ism: string | null
  actor_rol: AktorRol | null
  oldin: Record<string, unknown> | null
  keyin: Record<string, unknown> | null
  izoh: string | null
  ip: string | null
}

export type Manba = 'taklif' | 'qidiruv' | 'qolda'

export interface KodTaklif {
  code: string
  name_ru: Nullable<string>
  /** Mashina skori — kelishuv foizini hisoblashda yozib olinadi. */
  skor?: Nullable<number>
  n_tender_open: number
  /** DALIL — kod ostidagi HAQIQIY pozitsiyalar. Qaror shundan chiqadi:
   *  kod nomi begona bo'lishi mumkin, pozitsiyalar esa tanish. */
  pozitsiyalar: { nom: Nullable<string>; n_ochiq: number }[]
}

export interface KodAtama {
  kalit: string
  atama: string
  n_mahsulot: number
  /** `keng` qisqartirilgan o'zak bo'yicha (YUQORI CHEGARA),
   *  `aniq` to'liq so'z bo'yicha. Farq katta bo'lsa o'zak kengligi
   *  sabab ekani ko'rinadi — bitta raqam ko'rsatilsa u aniq deb
   *  o'qilardi. */
  korpus_ochiq: number
  korpus_ochiq_aniq: number
  korpus_jami: number
  takliflar: KodTaklif[]
}

export interface KodNavbat {
  atamalar: KodAtama[]
  qolgan: number
  talabsiz: { kalit: string; atama: string; n_mahsulot: number }[]
  talabsiz_jami: number
  turi_aniqmas: { id: number; name: string }[]
  turi_aniqmas_jami: number
  /** Inson allaqachon qaror qilgan atamalar — navbatda KO'RSATILMAYDI,
   *  lekin yig'indida sanaladi. Filtrsiz ular navbatga qaytardi
   *  ('talabsiz'/'otkazildi' kod bermaydi) va navbat tugamasdi. */
  qaror_qilingan: { kalit: string; atama: string; n_mahsulot: number }[]
  qaror_qilingan_jami: number
  /** Toifalar yig'indisi JAMIGA teng bo'lishi shart. */
  jami_mahsulot: number
  toifa_yigindi: number
}

export interface KodQidiruv {
  kalit: string
  pozitsiya: KodPozitsiya[]
  kod_nomi: { code: string; name_ru: Nullable<string>; n_ochiq: number }[]
  meniki: number
  qidiruv_soni?: number
}

/** `/kod/qaror/olchov` javobining RAQAMLAR qismi.
 *
 *  `KodOlchov` — BUTUN javob (`{olchov, pilot, qarorlar}`), bu esa
 *  faqat `olchov` ichi. Komponent `o.olchov` ni saqlaydi, ya'ni uning
 *  holati aynan shu turda bo'lishi kerak. Ilgari u `KodOlchov` deb
 *  yozilgan edi va `tsc -b` buni xato deb ko'rsatardi (`npm run build`
 *  shu sababdan yiqilardi). */
export type KodOlchovRaqam = KodOlchov['olchov']

export interface KodOlchov {
  olchov: {
    qaror_soni: number
    /** AJRATILGAN atama soni. `qaror_soni` QATORLARNI sanaydi — bir
     *  atamani takror bosish uni oshiradi, buni oshirmaydi. */
    atama_soni: number
    kod_berildi: number; talabsiz: number
    /** INSON QAROR QILA OLMADI. `talabsiz` dan ATAYLAB alohida:
     *  birinchisi XULOSA, bu XULOSA YO'QLIGI. */
    dalilsiz: number
    otkazildi: number
    /** Qaror qilinmagan ochiq qatorlar. Hisoblagichlarga TUSHMAYDI. */
    ochiq_qator: number
    /** FAQAT `ochilgan_at IS NOT NULL` qatorlar bo'yicha. */
    ortacha_sek: Nullable<number>
    median_sek: Nullable<number>
    olchangan: number
    /** Vaqti O'LCHANMAGAN qarorlar. Nol deb sanalmaydi. */
    olchovsiz: number
    taklifdan: number; qidiruvdan: number; qoldan: number
    talabsiz_qidiruvsiz: number; talabsiz_qidiruvli: number
    kop_kodli_atama: number
    /** --- TAKLIF BILAN KELISHUV --- */
    taklifli_qaror: number
    taklif_qabul: number
    taklif_ozgartirildi: number
    taklif_rad: number
    taklif_kelishuv_foiz: Nullable<number>
    /** ANIQ rad etilgan takliflar — MANFIY misollar. */
    rad_taklif_soni: number
    /** --- QIDIRUV --- */
    qidiruvli_qaror: number
    qidiruv_foiz: Nullable<number>
    /** --- KO'P KOD --- */
    qoshimcha_kod_soni: number
    /** --- DALIL QAMROVI --- dalilsiz qaror ML uchun yaroqsiz. */
    dalilli_qaror: number
    dalil_qamrov_foiz: Nullable<number>
  } | null
  pilot?: KodPilot | null
  qarorlar: {
    kalit: string; atama: string; qaror: KodQaror
    code: Nullable<string>; manba: Nullable<Manba>
    qidiruv_soni: number; qidiruv_sozi: Nullable<string>
    taklif_code: Nullable<string>
    qoshimcha_kod: boolean
    rad_takliflar: Nullable<string[]>
    dalil_bor: boolean
    qaror_at: string
  }[]
}

/**
 * Pilot holati — "40 ta ATAMA qaroriga qancha qoldi".
 *
 * MAQSAD ATAMA BO'YICHA, qator bo'yicha EMAS: bir atamaga ikkinchi
 * kod berish ikki qator yaratadi va qator bo'yicha sanash maqsadni
 * SOXTA yaqinlashtirardi.
 */
export interface KodPilot {
  company_id: number
  maqsad: number
  qaror_soni: number
  atama_soni: number
  qolgan: number
  olchangan: number
  dalilli: number
  /** NULL = O'LCHANMADI (nol EMAS). */
  ortacha_sek: Nullable<number>
  median_sek: Nullable<number>
  taklif_kelishuv_foiz: Nullable<number>
  qidiruv_foiz: Nullable<number>
  kodsiz_mahsulot: number
  /** MAQSADGA QO'SHILMAYDIGAN qarorlar: anonim (`kompaniya_sessiyasi`)
   *  yoki mashina (`servis`). `qaror_soni` FAQAT atributlanganni
   *  sanaydi — ekran va sifat darvozasi bir xil qoidada bo'lsin.
   *  Bu son noldan farq qilsa, ko'ruvchi "bajardim" deb o'ylagan ish
   *  darvozaga o'tmagan degani. */
  atributsiz_qaror?: number
}

/** `/validatsiya/holat` bitta qatlami.
 *
 * `aktorli` — DARVOZA SHUNI sanaydi. `anonim` va `mashina` ALOHIDA
 * turadi va hech qachon qo'shilmaydi: qo'shilsa darvoza yopiq bo'la
 * turib ochiqdek ko'rinardi. */
export interface ValidatsiyaQatlam {
  qatlam: string
  eng_kam: number
  aktorli: number
  qolgan: number
  anonim: number
  mashina: number
  navbatda: number
  holat: string
  ulush_foiz: number | null
  aktor_jami?: number
  aktor_faol?: number
  aktor_koruvchi?: number
  tosiq?: string | null
}

export interface ValidatsiyaHolat {
  qatlamlar: ValidatsiyaQatlam[]
  izoh: Record<string, string>
}
