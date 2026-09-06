import { useCallback, useState } from 'react'
import Icon from './Icon'
import CompanyProfile from './CompanyProfile'
import type { Section, SectionProgress } from './CompanyProfile'
import NotifySettings from './NotifySettings'
import PasswordPanel from './PasswordPanel'
import ErrorBoundary from './ErrorBoundary'
import { useT } from '@/i18n'
import type { TKey } from '@/i18n'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { CompanyProfileData } from '@/types'

// AKKAUNT SOZLAMALARI — kategoriyalarga bo'lingan menyu.
//
// NEGA MENYU: ilgari butun akkaunt bitta uzun sahifada edi (aloqa, kompaniya,
// salohiyat, tender mezonlari, email va Telegram — hammasi ketma-ket).
// "Minimal foyda"ni topish uchun ekranni to'liq aylantirish kerak edi.
//
// KATTA QAROR: profil paneli DOIM mount holida qoladi (`hidden` bilan
// yashiriladi), chunki bo'lim almashtirish SAQLANMAGAN o'zgarishlarni yo'q
// qilmasligi kerak. Bildirishnoma paneli esa birinchi ochilgunicha umuman
// mount qilinmaydi — u ochilishida Telegram Bot API ga so'rov yuboradi.
// `security` — parol (auth-6). U Go/No-Go mezonlariga kirmaydi, ya'ni
// rozetkasi ham yo'q: bu profil to'liqligi emas, xavfsizlik sozlamasi.
const SECTIONS: { key: Section | 'notify' | 'security'; icon: string; label: TKey; hint: TKey }[] = [
  { key: 'profile', icon: 'user', label: 'acc.profile', hint: 'acc.profileHint' },
  { key: 'company', icon: 'briefcase', label: 'acc.company', hint: 'acc.companyHint' },
  { key: 'capacity', icon: 'stats', label: 'acc.capacity', hint: 'acc.capacityHint' },
  { key: 'criteria', icon: 'match', label: 'acc.criteria', hint: 'acc.criteriaHint' },
  { key: 'notify', icon: 'bell', label: 'acc.notify', hint: 'acc.notifyHint' },
  { key: 'security', icon: 'lock', label: 'acc.security', hint: 'acc.securityHint' },
]

interface AccountSettingsProps {
  onSaved?: (p: CompanyProfileData) => void
}

export default function AccountSettings({ onSaved }: AccountSettingsProps) {
  const t = useT()
  const [section, setSection] = useState<Section | 'notify' | 'security'>('profile')
  const [notifySeen, setNotifySeen] = useState(false)
  // Bo'lim bo'yicha to'ldirilgan Go/No-Go mezonlari — menyudagi rozetka.
  const [prog, setProg] = useState<Record<string, SectionProgress>>({})

  // `useCallback` SHART: `CompanyProfile` buni `useEffect` bog'liqligida
  // ishlatadi. Har renderda yangi funksiya bo'lsa effekt cheksiz aylanardi.
  const onProgress = useCallback((m: Record<string, SectionProgress>) => setProg(m), [])

  const done = Object.values(prog).reduce((s, x) => s + x.done, 0)
  const total = Object.values(prog).reduce((s, x) => s + x.total, 0)
  const isNotify = section === 'notify'
  const isSecurity = section === 'security'
  const current = SECTIONS.find((s) => s.key === section)

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[236px_minmax(0,1fr)]">
      {/* `Card` — oddiy `div` (`asChild` qo'llab-quvvatlanmaydi), shuning uchun
          semantik teg ustiga uning sinflari qo'lda qo'yiladi. */}
      <nav
        aria-label={t('acc.navLabel')}
        className="sticky top-4 rounded-xl border bg-card p-2 text-card-foreground max-lg:static max-lg:flex max-lg:overflow-x-auto"
      >
          {SECTIONS.map((s) => {
            const pr = prog[s.key]
            const on = section === s.key
            return (
              <button key={s.key} type="button"
                className={cn(
                  'flex w-full shrink-0 items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors',
                  on ? 'bg-secondary text-primary' : 'hover:bg-accent',
                )}
                aria-current={on ? 'page' : undefined}
                onClick={() => {
                  setSection(s.key)
                  if (s.key === 'notify') setNotifySeen(true)
                }}>
                <Icon name={s.icon} size={16} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-body font-semibold leading-tight">{t(s.label)}</span>
                  <span className={cn('truncate text-micro leading-tight max-lg:hidden',
                    on ? 'text-primary/75' : 'text-muted-foreground')}>{t(s.hint)}</span>
                </span>
                {/* Rozetka faqat mezon yopadigan bo'limlarda. To'liq bo'lsa yashil. */}
                {pr && (
                  <span className={cn(
                    'tabular shrink-0 rounded px-1.5 py-0.5 text-micro font-semibold',
                    pr.done === pr.total ? 'bg-ok-soft text-ok-strong' : 'bg-muted text-muted-foreground',
                  )} title={t('acc.badgeTitle')}>
                    {pr.done}/{pr.total}
                  </span>
                )}
              </button>
            )
          })}

          {total > 0 && (
            <div className="mt-1.5 border-t px-2.5 pb-1 pt-2.5 max-lg:hidden"
              title={t('acc.progressTitle')}>
              <div className="mb-1.5 flex items-baseline justify-between text-micro text-muted-foreground">
                <span>{t('acc.completeness')}</span>
                <b className="tabular text-foreground">{done}/{total}</b>
              </div>
              <Progress value={(done / total) * 100} className="h-1.5" />
            </div>
          )}
      </nav>

      <section
        aria-label={current ? t(current.label) : undefined}
        className="min-w-0 rounded-xl border bg-card p-5 text-card-foreground"
      >
        <h2 className="mb-3 text-title font-semibold">{current ? t(current.label) : ''}</h2>

        {/* Chegara SHU YERDA: bitta panel qulasa yon menyu tirik qoladi va
            foydalanuvchi boshqa bo'limga o'tib ketaveradi. `resetKey` — ochiq
            bo'lim: almashtirilsa xato tozalanadi. */}
        <ErrorBoundary resetKey={section}>
          <div hidden={isNotify || isSecurity}>
            <CompanyProfile section={section as Section} onSaved={onSaved} onProgress={onProgress} />
          </div>
          {isSecurity && <PasswordPanel />}
          {notifySeen && (
            <div hidden={!isNotify}>
              <NotifySettings />
            </div>
          )}
        </ErrorBoundary>
      </section>
    </div>
  )
}
