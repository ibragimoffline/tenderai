// =============================================================================
// AI YORDAMCHI — KUTIB OLISH EKRANI
// =============================================================================
// Manba: 21st.dev `ai-assistant-interface`. Loyihaga MOSLASHTIRILDI va
// har o'zgarish SABABI bilan yozilgan.
//
// 1. `"use client"` OLIB TASHLANDI — loyiha Vite'da yuradi (Next.js emas,
//    `components.json` da `rsc: false`). U yerda bu direktiva ma'nosiz.
//
// 2. QOTIRILGAN RANGLAR TOKENLARGA almashtirildi (`bg-white` ->
//    `bg-card`, `text-gray-500` -> `text-muted-foreground` va h.k.).
//    Loyihada QORONG'I MAVZU bor (`src/theme.tsx`) va qotirilgan oq fon
//    qorong'i mavzuda oq ustiga oq matn berardi.
//
// 3. `min-h-screen` OLIB TASHLANDI — bu 440px li yon panel ichida
//    yuradi, butun ekran emas.
//
// 4. SOXTA BOSHQARUVLAR OLIB TASHLANDI. Asl namunada "Search",
//    "Deep Research", "Reason", mikrofon va "Upload Files" bor edi;
//    ularning HECH BIRI backendda mavjud emas, "Upload" esa
//    `setTimeout` bilan TAQLID qilingan va soxta `Document.pdf`
//    qo'shardi.
//
//    Ishlamaydigan tugma — eng qimmat nuqson turi: foydalanuvchi uni
//    bosadi, hech narsa bo'lmaydi va u BUTUN mahsulotga ishonmay
//    qo'yadi. Backendda o'sha imkoniyat paydo bo'lganda tugma ham
//    qaytariladi.
//
// 5. INGLIZCHA MATNLAR i18n GA ko'chirildi. Asl namunadagi takliflar
//    ("Explain the Big Bang theory", "Create a React component") bu
//    mahsulotga umuman aloqasiz edi. Takliflar endi TENDER sohasidan
//    va uch tilda.
// =============================================================================
import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, FileSearch, Scale } from 'lucide-react'

import type { TKey } from '@/i18n'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

/** Taklif guruhlari — har biri HAQIQIY qobiliyatga mos keladi. */
const GURUHLAR = [
  {
    id: 'tender',
    icon: BookOpen,
    label: 'chat.cat.tender' as TKey,
    takliflar: ['chat.cat.tender.1', 'chat.cat.tender.2',
                'chat.cat.tender.3'] as TKey[],
  },
  {
    id: 'hujjat',
    icon: FileSearch,
    label: 'chat.cat.docs' as TKey,
    takliflar: ['chat.cat.docs.1', 'chat.cat.docs.2',
                'chat.cat.docs.3'] as TKey[],
  },
  {
    id: 'qaror',
    icon: Scale,
    label: 'chat.cat.decide' as TKey,
    takliflar: ['chat.cat.decide.1', 'chat.cat.decide.2',
                'chat.cat.decide.3'] as TKey[],
  },
] as const

interface Props {
  /** Taklif tanlanganda — matn kirish maydoniga qo'yiladi. */
  onPick: (matn: string) => void
  /** Tender konteksti bo'lsa sarlavha shuni aytadi. */
  tenderId?: number | null
}

export function AIAssistantInterface({ onPick, tenderId }: Props) {
  const t = useT()
  const [ochiq, setOchiq] = useState<string | null>(null)

  return (
    <div className="flex flex-col items-center px-1 py-2">
      <Logotip />

      <div className="mb-6 mt-4 text-center">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <h2 className="mb-1 bg-gradient-to-r from-accent to-primary bg-clip-text
                         text-lg font-semibold text-transparent">
            {t('chat.welcome')}
          </h2>
          <p className="text-caption text-muted-foreground">
            {tenderId
              ? t('chat.scope.tender', { id: tenderId })
              : t('chat.welcome.hint')}
          </p>
        </motion.div>
      </div>

      <div className="grid w-full grid-cols-3 gap-2">
        {GURUHLAR.map((g) => (
          <GuruhTugmasi
            key={g.id}
            icon={<g.icon className="h-4 w-4" />}
            label={t(g.label)}
            faol={ochiq === g.id}
            onClick={() => setOchiq(ochiq === g.id ? null : g.id)}
          />
        ))}
      </div>

      <AnimatePresence initial={false}>
        {ochiq && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="w-full overflow-hidden"
          >
            <ul className="mt-2 divide-y divide-border overflow-hidden rounded-lg
                           border bg-card">
              {(GURUHLAR.find((g) => g.id === ochiq)?.takliflar ?? []).map(
                (k, i) => (
                  <motion.li
                    key={k}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.03 }}
                  >
                    <button
                      type="button"
                      onClick={() => onPick(t(k))}
                      className="w-full px-3 py-2.5 text-left text-caption
                                 transition-colors hover:bg-accent/10
                                 focus-visible:bg-accent/10 focus-visible:outline-none"
                    >
                      {t(k)}
                    </button>
                  </motion.li>
                ),
              )}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

interface GuruhProps {
  icon: React.ReactNode
  label: string
  faol: boolean
  onClick: () => void
}

function GuruhTugmasi({ icon, label, faol, onClick }: GuruhProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={faol}
      className={cn(
        'flex flex-col items-center justify-center gap-1.5 rounded-lg border',
        'px-2 py-3 text-micro font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        faol
          ? 'border-accent bg-accent/10 text-accent'
          : 'bg-card text-muted-foreground hover:border-accent/40 hover:text-foreground',
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}

/**
 * Gradient logotip (asl namunadan).
 *
 * `prefers-reduced-motion` HURMAT QILINADI: aylanish `motion-safe:`
 * bilan cheklangan. Asl namunada u shartsiz edi va harakatga sezgir
 * foydalanuvchilar uchun muammo bo'lardi.
 */
function Logotip() {
  return (
    <div className="relative h-14 w-14" aria-hidden="true">
      <svg viewBox="0 0 200 200" className="h-full w-full" fill="none"
           xmlns="http://www.w3.org/2000/svg">
        <g clipPath="url(#tai_clip)">
          <mask id="tai_mask" style={{ maskType: 'alpha' }} maskUnits="userSpaceOnUse"
                x="0" y="0" width="200" height="200">
            <path fill="#fff" fillRule="evenodd" clipRule="evenodd"
                  d="M100 150c27.614 0 50-22.386 50-50s-22.386-50-50-50-50 22.386-50 50 22.386 50 50 50zm0 50c55.228 0 100-44.772 100-100S155.228 0 100 0 0 44.772 0 100s44.772 100 100 100z" />
          </mask>
          <g mask="url(#tai_mask)">
            <path fill="currentColor" className="text-card" d="M200 0H0v200h200V0z" />
            <g filter="url(#tai_blur)"
               className="origin-center motion-safe:animate-[tai-spin_9s_linear_infinite]"
               style={{ transformBox: 'fill-box' }}>
              <path fill="#0066FF" d="M110 32H18v68h92V32z" />
              <path fill="#0044FF" d="M188-24H15v98h173v-98z" />
              <path fill="#0099FF" d="M175 70H5v156h170V70z" />
              <path fill="#00CCFF" d="M230 51H100v103h130V51z" />
            </g>
          </g>
        </g>
        <defs>
          <filter id="tai_blur" x="-75" y="-104" width="385" height="410"
                  filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
            <feGaussianBlur stdDeviation="40" result="b" />
          </filter>
          <clipPath id="tai_clip">
            <path fill="#fff" d="M0 0H200V200H0z" />
          </clipPath>
        </defs>
      </svg>
    </div>
  )
}
