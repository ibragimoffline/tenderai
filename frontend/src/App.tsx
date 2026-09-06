import { useEffect, useState, useCallback, useRef, lazy, Suspense } from 'react'
import { api, getToken, setUnauthorizedHandler } from '@/api'
import type { CompanyAccount } from '@/api'
import type { ChatManba } from '@/hooks/useChatStream'
import Icon from './components/Icon'
import Sidebar from './components/Sidebar'
import Filters from './components/Filters'
import type { FiltersState } from './components/Filters'
import SourceChips from './components/SourceChips'
import StatsStrip from './components/StatsStrip'
import TenderTable from './components/TenderTable'
import Pagination from './components/Pagination'
import ProfileForm from './components/ProfileForm'
import CatalogView from './components/CatalogView'
import AccountSettings from './components/AccountSettings'
import CompanyDocuments from './components/CompanyDocuments'
import Freshness from './components/Freshness'
import LoginPage from './components/LoginPage'
import { useI18n } from '@/i18n'
import type { TKey } from '@/i18n'
import { Button } from '@/components/ui/button'
import { ConfirmDialog, useConfirm } from '@/components/ui/confirm-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

// Statistika sahifasi ALOHIDA CHUNK'da. Sabab: u yagona joy bo'lib Recharts
// ni tortadi (~400 KB) — uni asosiy paketga qo'shsak, tenderlar ro'yxatini
// ochgan HAR BIR foydalanuvchi hech qachon ko'rmasligi mumkin bo'lgan grafik
// kutubxonasini yuklab olardi.
const StatsView = lazy(() => import('./components/StatsView'))
// LAZY: tasdiqlash paneli kundalik ish emas — broker unga
// vaqti-vaqti bilan kiradi. Boshlang'ich yuklamaga qo'shmaymiz.
const RequirementReview = lazy(() =>
  import('./components/RequirementReview'))
const BrokerQueue = lazy(() => import('./components/BrokerQueue'))

// Tender paneli ham alohida: u AI, narx hisobi, cheklist va ombor
// panellarini tortadi, lekin faqat qatorga bosilganda ochiladi.
const TenderDrawer = lazy(() => import('./components/TenderDrawer'))

// AI-Chat ham alohida chunk: u `marked` + `DOMPurify` ni tortadi
// (~13 KB gzip). Chat ochilmaguncha bu kod yuklab olinmaydi.
const ChatPanel = lazy(() => import('./components/ChatPanel'))
import type {
  Category, CompanyProfileData, CatalogMatchInfo, Freshness as FreshnessData,
  HududXulosa, Product, Region, SavedSearch, Stats, Status, TenderRow,
} from '@/types'

const PAGE_SIZE = 25
const REFRESH_MS = 180_000

// `products` / `services` — tender tarkibidagi pozitsiyalar bo'yicha filtr.
// `q` dan alohida: `q` buyurtmachi nomini ham qidiradi va soxta natija beradi
// ("qurilish" -> "Курилиш дирекцияси" MCHJ). Ikkalasi tanlansa — ORASIDA "yoki".
const DEFAULT_FILTERS: FiltersState = {
  status: 'open', region: '', currency: '', q: '', category: '',
  products: [], services: [], sort: 'close_at',
}

// Katalog mosligini o'qiladigan sabablarga aylantiradi (drawer shuni ko'rsatadi).
function catalogReasons(c: CatalogMatchInfo | undefined,
                        t: (k: TKey, v?: Record<string, string | number>) => string): string[] {
  const items = c?.products || []
  if (!items.length) return []
  const key: TKey = c!.by === 'kod' ? 'app.matchedBy.code' : 'app.matchedBy.name'
  return [t(key, { items: items.join(', ') })]
}

const VIEW_TITLES: Record<string, TKey> = {
  tenders: 'nav.tenders',
  match: 'nav.match',
  catalog: 'nav.catalog',
  documents: 'nav.documents',
  requirements: 'nav.requirements',
  broker: 'nav.broker',
  stats: 'nav.stats',
  profile: 'nav.profile',
  account: 'nav.account',
}

export default function App() {
  const { t, lang } = useI18n()
  const [view, setView] = useState('tenders')
  const [filters, setFilters] = useState<FiltersState>(DEFAULT_FILTERS)
  const [offset, setOffset] = useState(0)
  // Ikkala manba ham yoqilgan — foydalanuvchi hammasini bir joyda ko'rsin.
  const [sources, setSources] = useState<string[]>(['xt-xarid', 'uzex'])

  const [data, setData] = useState<{ items: TenderRow[]; total: number }>({ items: [], total: 0 })
  const [stats, setStats] = useState<Stats | null>(null)
  const [regions, setRegions] = useState<Region[]>([])
  const [statuses, setStatuses] = useState<Status[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [fresh, setFresh] = useState<FreshnessData | null>(null)
  // profile = joriy QO'LLANGAN qidiruv (moslashtirish shunga qarab ballaydi)
  const [profile, setProfile] = useState<Partial<SavedSearch> | null>(null)
  const [searches, setSearches] = useState<SavedSearch[]>([])
  const [activeSearchId, setActiveSearchId] = useState<number | null>(null)
  const [editing, setEditing] = useState<SavedSearch | 'new' | null>(null)
  // Akkaunt profili — yon paneldagi foydalanuvchi bloki shundan o'qiydi
  const [account, setAccount] = useState<CompanyProfileData | null>(null)
  // Cheklistdan "hujjatlarim" ga o'tilganda qaysi tur formasi ochilsin
  const [docFocus, setDocFocus] = useState<string | null>(null)
  const [catalog, setCatalog] = useState<Product[]>([])
  // Katalogdagi son bosilganda aynan shu mahsulot bo'yicha moslar ochiladi.
  // Ichki tasniflagich kodi interfeysga olib chiqilmaydi.
  const [catalogProduct, setCatalogProduct] = useState<Product | null>(null)
  const [catalogNew, setCatalogNew] = useState({ new: 0, total: 0 })
  // "Sizga mos" natijasidagi hudud xulosasi. `null` — hali
  // o'lchanmagan yoki bu ko'rinish katalog rejimida emas.
  const [hudud, setHudud] = useState<HududXulosa | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogError, setCatalogError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ id: number; match?: TenderRow['match'] } | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  // Tor ekrandagi navigatsiya paneli ochiqmi
  const [menuOpen, setMenuOpen] = useState(false)
  // AI-Chat paneli. `null` — yopiq; son — o'sha tender konteksti;
  // `0` — umumiy suhbat (kontekstsiz).
  const [chatFor, setChatFor] = useState<number | null>(null)
  /**
   * Chat QAYERDAN ochilgani. `chatFor` bilan birga yuradi, lekin
   * ALOHIDA holat: `chatFor` faqat "qaysi tender" ni biladi,
   * "nima uchun" ni emas. Server ikkinchisiga qarab tizim blokini
   * quradi (`manba='gonogo'` -> saqlangan tahlil sharhi).
   */
  const [chatManba, setChatManba] = useState<ChatManba | null>(null)

  // KIRISH (auth-2). `undefined` — hali tekshirilmadi (token bor, so'rov
  // ketyapti); `null` — kirilmagan. Ikkisini ajratmasak, sahifa har
  // yangilanganda kirish ekrani bir lahza chaqnab ketardi.
  const [session, setSession] = useState<CompanyAccount | null | undefined>(
    () => (getToken() ? undefined : null))

  useEffect(() => {
    // 401 — sessiya tugadi: kirish ekraniga qaytamiz (api.ts chaqiradi).
    setUnauthorizedHandler(() => setSession(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    if (session === undefined) {
      // Saqlangan token haqiqiymi — bir marta tekshiriladi
      api.me().then(setSession).catch(() => setSession(null))
    }
  }, [session])

  async function signOut() {
    await api.logout().catch(() => {})
    setSession(null)
  }

  // Bir martalik ma'lumotlar
  const loadSearches = useCallback(
    () => api.searches().then(setSearches).catch(() => {}), [])
  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true)
    setCatalogError(null)
    try {
      const [items, count] = await Promise.all([
        api.catalog(), api.catalogNewCount(),
      ])
      setCatalog(items)
      setCatalogNew(count)
    } catch (e) {
      setCatalogError((e as Error).message)
    } finally {
      setCatalogLoading(false)
    }
  }, [])
  // Ma'lumot FAQAT kirgandan keyin so'raladi: aks holda kirish ekrani
  // ochiq turganda o'nlab so'rov ketib, hammasi 401 qaytarardi.
  useEffect(() => {
    if (!session) return
    api.regions().then((rs) => setRegions(rs.filter((r) => r.level === 1))).catch(() => {})
    api.statuses().then(setStatuses).catch(() => {})
    api.categories().then(setCategories).catch(() => {})
    api.freshness().then(setFresh).catch(() => {})
    api.getProfile().then(setAccount).catch(() => {})
    // Bildirishnomadagi kartochka havolasi: /?tender=123 -> drawer ochiladi.
    // TZ P0-10 qabul mezoni: xabardagi havola BOSILGANDA aynan o'sha kartochka.
    const deep = new URLSearchParams(window.location.search).get('tender')
    if (deep) setSelected({ id: Number(deep) })
    loadSearches()
    loadCatalog()
  }, [loadSearches, loadCatalog, session])

  // XABAR TILI = INTERFEYS TILI (TZ P0-10).
  // Bildirishnomani SERVER yuboradi — ETL dan keyin, soatlik jadval bo'yicha,
  // ilova umuman ochiq bo'lmaganда ham. Server brauzerni ko'rmaydi, shuning
  // uchun tanlangan til bazaga yozib qo'yiladi va email ham, Telegram ham
  // aynan shu tilda keladi.
  //
  // FAQAT FARQ BO'LSA yoziladi: aks holda har ochilishda va har qayta
  // chizishda behuda PUT ketib, sozlamaning `updated_at` i o'zgaraverardi.
  // Xato JUTILADI — til afzalligi tufayli ilova ochilmay qolmasin.
  useEffect(() => {
    if (!session) return
    api.notifySettings()
      .then((s) => (s.lang === lang ? null : api.saveNotifySettings({ lang })))
      .catch(() => {})
  }, [lang, session])

  // Saqlangan qidiruvni qo'llash — profilga o'giradi va "Sizga mos"ga o'tadi
  function applySearch(s: SavedSearch) {
    setProfile({
      keywords: s.keywords, regions: s.regions, currency: s.currency,
      min_cost: s.min_cost, max_cost: s.max_cost,
    })
    setActiveSearchId(s.id)
    setCatalogProduct(null)
    setEditing(null)
    setView('match'); setOffset(0)
  }
  function newSearch() { setEditing('new'); setView('profile'); setOffset(0) }
  function editSearch(s: SavedSearch) { setEditing(s); setView('profile'); setOffset(0) }

  const deleteSearch = useConfirm<SavedSearch>()
  async function removeSearch(s: SavedSearch) {
    // XATO YASHIRILMAYDI. Ilgari `catch { }` edi: o'chirish
    // muvaffaqiyatsiz bo'lsa ham interfeys "o'chdi" deb ko'rsatar,
    // ro'yxat yangilanganda element QAYTA PAYDO bo'lardi — sababsiz.
    try {
      await api.deleteSearch(s.id)
    } catch (e) {
      setError((e as Error).message)
      return
    }
    if (activeSearchId === s.id) { setActiveSearchId(null); setProfile(null) }
    loadSearches()
  }

  // MANBA FILTRI UCH HOLATLI, ikki emas. O'LCHANGAN NUQSON
  // (2026-09-02): shart `sources.length === 1 ? sources[0] : ''` edi va
  // u NOL tanlovni HAMMASI bilan bir xil ko'rardi — ikkala manba ham
  // o'chirilganda foydalanuvchi HAMMA tenderni ko'rardi.
  //
  //   2 tanlangan -> filtr YO'Q      (hammasi)
  //   1 tanlangan -> shu manba
  //   0 tanlangan -> HECH NARSA      <- avval "hammasi" edi
  //
  // Nol tanlov "filtr qo'yilmagan" DEGANI EMAS: u "hech qaysi manba
  // kerak emas" degani va javob BO'SH bo'lishi kerak.
  const source = sources.length === 1 ? sources[0] : ''
  const manbaYoq = sources.length === 0

  // Asosiy yuklovchi — view'ga qarab /tenders yoki /match
  const load = useCallback(async (opts: { silent?: boolean } = {}) => {
    // "Yangilangan: N oldin" ko'rsatkichi ETL yurishidan o'qiladi va u
    // BU YERDA yangilanishi kerak — aks holda ETL yurgan bo'lsa ham
    // ko'rsatkich sahifa yangilanmaguncha eski qiymatda qotib qolardi.
    api.freshness().then(setFresh).catch(() => {})

    // Ro'yxatsiz ko'rinishlar tender so'ramaydi
    if (['stats', 'profile', 'catalog', 'account', 'documents',
         'requirements', 'broker'].includes(view)) return
    if (manbaYoq) {
      // So'rov YUBORILMAYDI: bo'sh natija SO'ROVDAN emas, TANLOVDAN
      // kelib chiqadi va buni foydalanuvchi ko'rishi kerak.
      setData({ items: [], total: 0 })
      if (!opts.silent) setLoading(false)
      return
    }
    if (!opts.silent) setLoading(true)
    setError(null)
    try {
      let rows: { items: TenderRow[]; total: number }
      if (view === 'match' && activeSearchId) {
        // Saqlangan qidiruv faol — kalit so'z bo'yicha ballaydi
        setHudud(null)
        rows = await api.match({
          profile: profile || { keywords: [], regions: [], currency: null, min_cost: null, max_cost: null },
          status: filters.status, region: filters.region, currency: filters.currency,
          q: filters.q, category: filters.category,
          products: filters.products, services: filters.services,
          limit: PAGE_SIZE, offset,
        })
      } else if (view === 'match') {
        // Standart "Sizga mos" — katalogning aniq lot kodlari bo'yicha.
        // `q` UZATILADI. O'LCHANGAN NUQSON (2026-09-02): u bu
        // chaqiruvda YO'Q edi, ya'ni "Sizga mos" sahifasida qidiruv
        // maydoni ishlardi, natijaga esa TA'SIR QILMASDI — foydalanuvchi
        // yozgan so'z JIMGINA tashlab yuborilardi.
        const r = await api.catalogMatch({
          product_id: catalogProduct?.id ?? null,
          region: filters.region, currency: filters.currency,
          q: filters.q,
          products: filters.products, services: filters.services,
          limit: PAGE_SIZE, offset,
        })
        // catalog -> match shakliga moslaymiz (TenderTable o'zgarmaydi).
        // `reasons` HAM berilishi SHART: drawer uni ro'yxat qilib ko'rsatadi.
        rows = {
          ...r,
          items: r.items.map((it) => ({
            ...it,
            match: {
              score: it.catalog?.score,
              matched_keywords: it.catalog?.products,
              reasons: catalogReasons(it.catalog, t),
            },
          })),
        }
        setHudud(r.hudud ?? null)
        api.catalogSeen().then(() => setCatalogNew((n) => ({ ...n, new: 0 }))).catch(() => {})
      } else {
        setHudud(null)
        rows = await api.tenders({
          status: filters.status, region: filters.region,
          currency: filters.currency, q: filters.q, category: filters.category,
          product: filters.products, service: filters.services, source,
          limit: PAGE_SIZE, offset, sort: filters.sort,
        })
      }
      const s = await api.stats({ status: filters.status || 'open' })
      setData(rows)
      setStats(s)
      setLastUpdated(new Date())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      if (!opts.silent) setLoading(false)
    }
  }, [view, filters, offset, source, manbaYoq, profile, activeSearchId,
      catalogProduct, t])

  useEffect(() => { load() }, [load])

  // Avtomatik yangilash
  const loadRef = useRef(load); loadRef.current = load
  useEffect(() => {
    const id = setInterval(() => loadRef.current({ silent: true }), REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  function updateFilter(patch: Partial<FiltersState>) {
    setFilters((f) => ({ ...f, ...patch })); setOffset(0)
  }
  function goto(v: string) {
    // "Sizga mos"ga nav orqali kirilsa — katalog rejimi (qidiruv rejimidan chiqamiz)
    if (v === 'match') {
      setActiveSearchId(null); setProfile(null); setCatalogProduct(null)
    }
    setView(v); setOffset(0)
  }
  // Katalogda mahsulot "N mos"ini bosish -> shu mahsulotni mos ko'rsatadi
  function openProductMatch(p: Product) {
    setActiveSearchId(null)
    setProfile(null)
    setCatalogProduct(p)
    updateFilter({ category: '', q: '', products: [], services: [] })
    setView('match'); setOffset(0)
  }
  // Tender cheklistidagi "Hujjatlarim bo'limiga o'tish"
  function openDocuments(docType: string) {
    setDocFocus(docType || null)
    setSelected(null)          // tender panelini yopamiz
    setView('documents'); setOffset(0)
  }
  function toggleSource(id: string) {
    setSources((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id])
    setOffset(0)
  }

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE))
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const isList = view === 'tenders' || view === 'match'
  const activeSearch = searches.find((s) => s.id === activeSearchId)
  const emptyCatalog = view === 'match' && !activeSearchId && catalog.length === 0

  // Token tekshirilmaguncha bo'sh ekran — kirish formasi chaqnamasin
  if (session === undefined) return <div className="min-h-screen bg-background" />
  if (!session) return <LoginPage onLogin={setSession} />

  return (
    <div className="grid min-h-screen md:grid-cols-[232px_1fr]">
      {/* Klaviatura bilan ishlaydiganlar uchun: birinchi Tab — navigatsiyani
          o'tkazib yuborish. Panelda o'nlab havola bor, ular har sahifada
          takrorlanadi. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-body focus:text-primary-foreground"
      >
        {t('app.skipToContent')}
      </a>

      <Sidebar
        active={view} onNavigate={goto}
        newMatchCount={catalogNew.new} account={account} onSignOut={signOut}
        searches={searches} activeSearchId={activeSearchId}
        onApplySearch={applySearch} onNewSearch={newSearch}
        onEditSearch={editSearch} onDeleteSearch={deleteSearch.ask}
        mobileOpen={menuOpen} onMobileOpenChange={setMenuOpen}
      />

      <ConfirmDialog
        {...deleteSearch.props}
        title={t('app.confirmDeleteSearch', { name: deleteSearch.target?.name ?? '' })}
        onConfirm={() => deleteSearch.target && removeSearch(deleteSearch.target)}
      />

      <main id="main" className="min-w-0 px-4 pb-16 pt-4 sm:px-6 sm:pt-5">
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <Button
            variant="outline" size="icon" className="md:hidden"
            aria-label={t('nav.openMenu')}
            onClick={() => setMenuOpen(true)}
          >
            <Icon name="menu" size={18} />
          </Button>
          {/* Sahifa sarlavhasi. Avval bu yerda harflarni bitta-bitta
              ag'daradigan animatsiya turgan edi — u qayerga o'tganingizni
              yon paneldagi belgilangan bandga qaraganda YAXSHIROQ
              ko'rsatmasdi, lekin sarlavhani har almashuvda bir soniya
              o'qib bo'lmas holga keltirardi. */}
          <h1 className="text-display font-semibold">
            {VIEW_TITLES[view] ? t(VIEW_TITLES[view]) : ''}
          </h1>
          <div className="ml-auto flex items-center gap-2">
            <Freshness data={fresh} />
            {/* DIQQAT: quyidagi tugma manba saytlarga BORMAYDI. U ro'yxatni o'z
                bazamizdan qayta o'qiydi. Manbadan yig'ish — ETL ishi. */}
            {isList && (
              <Button variant="outline" size="sm" onClick={() => load()} disabled={loading}
                title={t('app.refreshTitle')}>
                <Icon name="refresh" size={14} className={cn(loading && 'motion-safe:animate-spin')} />
                <span className="max-sm:sr-only">
                  {loading ? t('common.loading') : t('common.refresh')}
                </span>
              </Button>
            )}
          </div>
        </div>

        {isList && (
          <>
            <Filters
              filters={filters} regions={regions} statuses={statuses} categories={categories}
              onChange={updateFilter}
              onReset={() => { setFilters(DEFAULT_FILTERS); setOffset(0) }}
              showSort={view === 'tenders'}
            />
            <SourceChips selected={sources} onToggle={toggleSource} />

            {view === 'match' && activeSearch && (
              <Info>
                {t('app.savedSearch')} <b>{activeSearch.name}</b>
                <button className="ml-1.5 font-semibold underline-offset-2 hover:underline"
                  onClick={() => goto('match')}>{t('app.byCatalog')}</button>
              </Info>
            )}
            {view === 'match' && !activeSearch && catalogProduct && (
              <Info>
                {t('app.catalogProductMatch')} <b>{catalogProduct.name}</b>
                <button
                  className="ml-2 font-semibold underline underline-offset-2"
                  onClick={() => { setCatalogProduct(null); setOffset(0) }}
                >{t('app.allCatalog')}</button>
              </Info>
            )}
            {emptyCatalog && (
              <Info>
                {t('app.emptyCatalog')}
                <button className="ml-1.5 font-semibold underline-offset-2 hover:underline"
                  onClick={() => goto('catalog')}>{t('app.toCatalog')}</button>
              </Info>
            )}

            {/* HUDUD XULOSASI — "nechtasini yo'qotyapman" savoliga javob.
                O'LCHANGAN NOMUVOFIQLIK (2026-09-03): bu ro'yxat profildagi
                hudud cheklovini hisobga olmasdi, broker navbati esa uni
                QATTIQ to'siq sifatida qo'llardi. Natijada katalogga mos 28
                tenderdan 11 tasi navbatda yo'q edi va SABABI hech qayerda
                ko'rinmasdi. Qatorlar YASHIRILMAYDI: hududni kengaytirish
                sotuv qarori va uni kompaniya o'zi qabul qiladi. */}
            {view === 'match' && !!hudud?.tashqari && (
              <Info>
                {t('match.outOfRegionNote', { n: hudud.tashqari })}
                <button className="ml-1.5 font-semibold underline-offset-2 hover:underline"
                  onClick={() => goto('profile')}>{t('match.toProfile')}</button>
              </Info>
            )}

            <StatsStrip stats={stats} total={data.total} lastUpdated={lastUpdated} />

            {/* `role="alert"` — ekran o'quvchi xatoni DARHOL o'qiydi. U
                bo'lmasa xabar sahifada jimgina paydo bo'lardi va faqat
                kursorni o'sha yerga olib borgan odam bilardi. */}
            {error && (
              <div role="alert"
                className="mb-3 rounded-lg border border-urgent/40 bg-urgent-soft px-3.5 py-2.5 text-body text-urgent-strong">
                <p className="font-semibold">{t('common.errorWith', { msg: error })}</p>
                <p className="mt-0.5 text-caption">{t('app.backendHint')}</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={() => load()}>
                  {t('common.retry')}
                </Button>
              </div>
            )}

            <TenderTable
              items={data.items}
              mode={view}
              loading={loading}
              /* Status ustuni behuda: filtr bitta statusda bo'lsa har qator bir xil
                 bo'ladi. Faqat "barcha statuslar" tanlanganda ko'rsatamiz. */
              showStatus={!filters.status}
              sort={filters.sort}
              onSort={(col) => updateFilter({ sort: filters.sort === col ? `-${col}` : col })}
              onSelect={(id) => {
                const row = data.items.find((x) => x.id === id)
                setSelected({ id, match: row?.match })
              }}
            />

            <Pagination
              page={currentPage} totalPages={totalPages}
              onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              onNext={() => setOffset(offset + PAGE_SIZE)}
            />
          </>
        )}

        {view === 'catalog' && (
          <CatalogView
            items={catalog} categories={categories}
            loading={catalogLoading} loadError={catalogError}
            onChanged={loadCatalog}
            onOpenMatch={openProductMatch}
          />
        )}
        {/* Saqlangach yon paneldagi ism/email darhol yangilanadi */}
        {view === 'account' && <AccountSettings onSaved={setAccount} />}
        {view === 'documents' && <CompanyDocuments focusType={docFocus} />}
        {view === 'requirements' && (
          <Suspense fallback={<Skeleton className="h-[420px] w-full rounded-xl" />}>
            {/* Manbaga sakrash: hujjat matni tender panelida ochiladi,
                ya'ni tasdiqlovchi AYNAN o'sha bo'lakni ko'radi. */}
            <RequirementReview
              regions={regions}
              onOpenSource={(_ref, _pos) => { /* keyingi qadam: DocumentText ga chuqur havola */ }}
            />
          </Suspense>
        )}
        {view === 'broker' && (
          <Suspense fallback={<Skeleton className="h-[420px] w-full rounded-xl" />}>
            {/* Tenderni ochish: broker qaror berishdan OLDIN manbani
                ko'rishi kerak — qaror faqat `ai_sabab` ga tayanmasin. */}
            <BrokerQueue regions={regions}
              onOpenTender={(id) => setSelected({ id })} />
          </Suspense>
        )}
        {view === 'stats' && (
          <Suspense fallback={<Skeleton className="h-[420px] w-full rounded-xl" />}>
            <StatsView />
          </Suspense>
        )}
        {view === 'profile' && (
          <ProfileForm
            search={editing === 'new' ? null : editing}
            regions={regions}
            onSaved={() => { loadSearches(); setEditing(null); setView('tenders') }}
            onCancel={() => { setEditing(null); setView(searches.length ? 'match' : 'tenders') }}
          />
        )}
      </main>

      {chatFor !== null && (
        <Suspense fallback={null}>
          {/* QATLAM TARTIBI (o'lchangan nuqson, 2026-09-02).
              Chat `z-40` edi, `Sheet`/`Dialog` esa `z-50` — ya'ni
              tender oynasi ochiq turib "AI dan so'rash" bosilganda
              chat oyna ORTIDA ochilardi va foydalanuvchi HECH NARSA
              ko'rmasdi. Chat oxirgi ochilgan qatlam, shuning uchun
              u eng ustida turishi kerak.

              Tartib:  30 fon paneli < 40 yon menyu < 50 Sheet/Dialog
                       < 60 chat */}
          <div className="fixed inset-y-0 right-0 z-[60] flex w-full max-w-[440px]
                          flex-col border-l shadow-xl">
            <ChatPanel
              tenderId={chatFor || null}
              manba={chatManba ?? undefined}
              onClose={() => { setChatFor(null); setChatManba(null) }}
              onOpenCitation={(c) => setSelected({ id: c.tender_id })} />
          </div>
        </Suspense>
      )}

      {/* AI-Chat tugmasi — chat yopiq bo'lganda ko'rinadi */}
      {chatFor === null && (
        <button
          type="button"
          onClick={() => { setChatFor(0); setChatManba('global') }}
          title={t('chat.title')}
          className="fixed bottom-5 right-5 z-30 flex h-12 w-12 items-center
                     justify-center rounded-full bg-primary text-primary-foreground
                     shadow-lg transition hover:opacity-90"
        >
          <Icon name="sparkle" size={20} />
        </button>
      )}

      {selected && (
        <Suspense fallback={null}>
          <TenderDrawer
            id={selected.id} match={selected.match}
            onOpenDocuments={openDocuments}
            onAskAi={(tid, m) => { setChatFor(tid)
                                 setChatManba(m ?? 'panel') }}
            onClose={() => {
              setSelected(null)
              // Bildirishnomadan kelgan ?tender= parametrini olib tashlaymiz
              if (new URLSearchParams(window.location.search).has('tender')) {
                window.history.replaceState({}, '', window.location.pathname)
              }
            }} />
        </Suspense>
      )}
    </div>
  )
}

function Info({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-3 rounded-lg border border-primary/30 bg-secondary px-3.5 py-2.5 text-body text-primary">
      {children}
    </div>
  )
}
