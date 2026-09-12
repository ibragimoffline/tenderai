import * as Dialog from '@radix-ui/react-dialog'
import Icon from './Icon'
import PrefsMenu from './PrefsMenu'
import { useT } from '@/i18n'
import type { TKey } from '@/i18n'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { CompanyProfileData, SavedSearch } from '@/types'
import AktorTanlash from './AktorTanlash'

// Chap navigatsiya paneli.
const NAV: { key: string; icon: string; label: TKey; section?: TKey }[] = [
  { key: 'tenders', icon: 'tenders', label: 'nav.tenders', section: 'nav.section.main' },
  { key: 'match', icon: 'match', label: 'nav.match' },
  { key: 'catalog', icon: 'box', label: 'nav.catalog' },
  { key: 'kod-korik', icon: 'check', label: 'nav.codeReview' },
  { key: 'documents', icon: 'clip', label: 'nav.documents' },
  { key: 'requirements', icon: 'check', label: 'nav.requirements' },
  // Talablardan KEYIN: zanjir tender -> talab -> malaka -> NAVBAT.
  { key: 'broker', icon: 'send', label: 'nav.broker' },
  { key: 'stats', icon: 'stats', label: 'nav.stats' },
]

interface SidebarProps {
  active: string
  onNavigate: (key: string) => void
  newMatchCount: number
  account: CompanyProfileData | null
  /** Sessiyani tugatish (auth-2). Berilmasa tugma ko'rsatilmaydi. */
  onSignOut?: () => void
  searches: SavedSearch[]
  activeSearchId: number | null
  onApplySearch: (s: SavedSearch) => void
  onNewSearch: () => void
  onEditSearch: (s: SavedSearch) => void
  onDeleteSearch: (s: SavedSearch) => void
  /** Kichik ekranda panel chetdan surilib chiqadi — holati `App` da. */
  mobileOpen: boolean
  onMobileOpenChange: (open: boolean) => void
}

/**
 * BELGI. Avval bu yerda ko'k kvadrat ichida bitta "B" harfi turardi — har
 * qanday shablon boshqaruv panelida uchraydigan o'rin egallovchi. O'rniga
 * ishning O'ZINI ko'rsatadigan shakl: uch xil uzunlikdagi chiziq (uch manba
 * reyestri) bitta vertikal o'qqa yig'iladi. Agregator aynan shuni qiladi.
 */
function Mark() {
  return (
    <svg
      width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      className="shrink-0 text-primary"
    >
      <line x1="3" y1="6" x2="14" y2="6" />
      <line x1="3" y1="12" x2="10" y2="12" />
      <line x1="3" y1="18" x2="17" y2="18" />
      <line x1="20" y1="4" x2="20" y2="20" />
    </svg>
  )
}

export default function Sidebar(props: SidebarProps) {
  const t = useT()
  const { mobileOpen, onMobileOpenChange } = props

  return (
    <>
      {/* Keng ekran — doimiy ustun */}
      <aside className="sticky top-0 hidden h-screen flex-col border-r bg-sidebar px-3 py-4 md:flex">
        <Nav {...props} />
      </aside>

      {/* Tor ekran — chetdan suriladigan panel.
          Avval bu panel mobil ekranda ham `h-screen` bilan chiziladigan
          oddiy blok edi: ilova ochilganda BIRINCHI ekranni butunlay egallab,
          tenderlar ro'yxatiga yetish uchun pastga aylantirish kerak edi. */}
      <Dialog.Root open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-foreground/40 data-[state=open]:animate-in data-[state=open]:fade-in-0 md:hidden" />
          <Dialog.Content
            className="fixed inset-y-0 left-0 z-50 flex w-[17rem] max-w-[85vw] flex-col border-r bg-sidebar px-3 py-4 shadow-lg data-[state=open]:animate-in data-[state=open]:slide-in-from-left md:hidden"
          >
            <Dialog.Title className="sr-only">{t('nav.menu')}</Dialog.Title>
            <Nav {...props} onDismiss={() => onMobileOpenChange(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}

function Nav({
  active, onNavigate, newMatchCount, account, onSignOut,
  searches, activeSearchId, onApplySearch, onNewSearch, onEditSearch, onDeleteSearch,
  onDismiss,
}: SidebarProps & { onDismiss?: () => void }) {
  const t = useT()
  // Ism/email akkaunt profilidan o'qiladi; to'ldirilmagan bo'lsa — taklif.
  const uname = account?.contact_name || account?.name || t('nav.account')
  const uinfo = account?.email || account?.position || t('nav.accountEmpty')
  const initials = (account?.contact_name || account?.name || '?')
    .split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase()

  // Panelda harakat qilingach mobil oyna yopiladi — aks holda tanlangan
  // ro'yxat panel ortida pana bo'lib qolardi.
  const go = (fn: () => void) => () => { fn(); onDismiss?.() }

  const item = 'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-body transition-colors'

  return (
    <>
      <div className="mb-5 flex items-center gap-2.5 px-1">
        <Mark />
        <div className="min-w-0">
          <div className="truncate text-body font-semibold leading-tight">{t('nav.brandName')}</div>
          <div className="truncate text-micro text-muted-foreground">{t('nav.brandTag')}</div>
        </div>
      </div>

      <AktorTanlash />
      <nav className="min-h-0 flex-1 overflow-y-auto" aria-label={t('nav.section.main')}>
        {NAV.map((nav) => (
          <div key={nav.key}>
            {nav.section && (
              <div className="mb-1 px-2.5 text-micro font-semibold uppercase text-muted-foreground">
                {t(nav.section)}
              </div>
            )}
            <button
              className={cn(item, active === nav.key
                ? 'bg-sidebar-accent font-semibold text-sidebar-accent-foreground'
                : 'text-foreground hover:bg-accent')}
              aria-current={active === nav.key ? 'page' : undefined}
              onClick={go(() => onNavigate(nav.key))}
            >
              <Icon name={nav.icon} size={17} />
              <span className="flex-1 truncate">{t(nav.label)}</span>
              {nav.key === 'match' && newMatchCount > 0 && (
                <span
                  className="tabular rounded-full bg-primary px-1.5 py-px text-micro font-semibold text-primary-foreground"
                  title={t('nav.newMatchTitle')}
                >{newMatchCount}</span>
              )}
            </button>
          </div>
        ))}

        {/* Saqlangan qidiruvlar */}
        <div className="mb-1 mt-5 flex items-center gap-1 px-2.5 text-micro font-semibold uppercase text-muted-foreground">
          <span className="flex-1">{t('nav.savedSearches')}</span>
          <button
            className="rounded p-1 transition-colors hover:bg-accent hover:text-foreground"
            aria-label={t('nav.newSearch')} title={t('nav.newSearch')}
            onClick={go(onNewSearch)}
          >
            <Icon name="plus" size={14} />
          </button>
        </div>

        {searches.length === 0 && (
          <p className="px-2.5 py-1 text-caption text-muted-foreground">
            {t('nav.noSearches')}
          </p>
        )}
        {searches.map((s) => (
          <div
            key={s.id}
            className={cn(
              'group flex items-center gap-0.5 rounded-md pr-1 transition-colors',
              active === 'match' && activeSearchId === s.id
                ? 'bg-sidebar-accent' : 'hover:bg-accent',
            )}
          >
            <button
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-2 text-left text-body"
              onClick={go(() => onApplySearch(s))} title={s.name}
            >
              <span className="flex-1 truncate">{s.name}</span>
              {!!s.match_count && (
                <span className="tabular rounded bg-muted px-1.5 text-micro text-muted-foreground">
                  {s.match_count}
                </span>
              )}
            </button>
            {/* Amal tugmalari sichqoncha olib borilganda ko'rinadi, LEKIN
                klaviatura bilan yurilganda ham (`focus-within`) — aks holda
                ular Tab bilan yetib boriladigan, ammo KO'RINMAYDIGAN
                nishonlar bo'lib qolardi. */}
            <span className="flex shrink-0 gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
              <button
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
                aria-label={t('nav.editSearch', { name: s.name })} title={t('common.edit')}
                onClick={go(() => onEditSearch(s))}
              >
                <Icon name="edit" size={13} />
              </button>
              <button
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-card hover:text-urgent-strong"
                aria-label={t('nav.deleteSearch', { name: s.name })} title={t('common.delete')}
                onClick={() => onDeleteSearch(s)}
              >
                <Icon name="trash" size={13} />
              </button>
            </span>
          </div>
        ))}
      </nav>

      {/* AKKAUNT — kompaniya profili shu yerda. Katalog "nima sotasiz",
          profil esa "kim siz" — bular boshqa-boshqa narsa. */}
      <div className="mt-3 space-y-0.5 border-t pt-3">
        <PrefsMenu />
        <Button
          variant="ghost"
          className={cn('h-auto w-full justify-start gap-2.5 px-2.5 py-2',
            active === 'account' && 'bg-sidebar-accent text-sidebar-accent-foreground')}
          onClick={go(() => onNavigate('account'))}
          aria-current={active === 'account' ? 'page' : undefined}
          title={t('nav.accountTitle')}
        >
          <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-caption font-semibold text-primary">
            {initials}
          </span>
          <span className="min-w-0 flex-1 text-left">
            <span className="block truncate text-body font-semibold">{uname}</span>
            <span className="block truncate text-micro font-normal text-muted-foreground">
              {uinfo}
            </span>
          </span>
          <Icon name="right" size={13} className="text-muted-foreground" />
        </Button>
        {/* CHIQISH — sessiyani tugatadi (auth-2). Akkaunt blokining
            yonida: "kim kirgan" va "chiqish" bir joyda bo'lsin. */}
        {onSignOut && (
          <Button
            variant="ghost"
            className="h-auto w-full justify-start gap-2.5 px-2.5 py-2 text-caption text-muted-foreground"
            onClick={go(onSignOut)}
          >
            <Icon name="close" size={14} />
            {t('auth.signOut')}
          </Button>
        )}
      </div>
    </>
  )
}