import { useState } from 'react'
import { api } from '@/api'
import Icon from './Icon'
import AiDocsNote from './AiDocsNote'
import { useT } from '@/i18n'
import type { TKey } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { GoNoGoResult } from '@/types'

// GO / NO-GO TAVSIYASI — "bu tenderda qatnashaymi?"
//
// AiMatch dan farqi: u faqat "mahsulotim mos keladimi" deydi. Bu esa
// qatnashish qarorini butun kesimda ko'radi — muddat, byudjet, sertifikat,
// tajriba, resurs. 11 mezon alohida ko'rsatiladi.
//
// MVP CHEKLOVI OCHIQ KO'RSATILADI: profil to'ldirilmagan bo'lsa, tegishli
// mezon "ma'lumot yo'q" bo'lib chiqadi va qaror Review ga tushadi.
const DECISION: Record<string, { label: TKey; edge: string; text: string }> = {
  go: { label: 'gonogo.decision.go', edge: 'border-l-ok', text: 'text-ok-strong' },
  review: { label: 'gonogo.decision.review', edge: 'border-l-soon', text: 'text-soon-strong' },
  no_go: { label: 'gonogo.decision.no_go', edge: 'border-l-urgent', text: 'text-urgent-strong' },
}

const STATUS: Record<string, { cls: string; text: TKey }> = {
  ok: { cls: 'bg-ok', text: 'gonogo.status.ok' },
  risk: { cls: 'bg-soon', text: 'gonogo.status.risk' },
  fail: { cls: 'bg-urgent', text: 'gonogo.status.fail' },
  malumot_yoq: {
    cls: 'bg-border ring-1 ring-inset ring-muted-foreground/40',
    text: 'gonogo.status.unknown',
  },
}

/**
 * @param onAskAi Tahlil haqida suhbat ochadi (`manba='gonogo'`).
 *   Berilmasa tugma CHIZILMAYDI — panel chatsiz ham ishlaydi.
 */
export default function GoNoGo({ tenderId, onAskAi }: {
  tenderId: number
  onAskAi?: (tenderId: number) => void
}) {
  const t = useT()
  const [data, setData] = useState<GoNoGoResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function run(refresh = false) {
    setLoading(true); setError(null)
    api.aiGoNogo(tenderId, refresh ? { refresh: true } : undefined)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  if (!data && !loading && !error) {
    return (
      <Button variant="outline" className="mb-4 w-full justify-start" onClick={() => run(false)}
        title={t('gonogo.buttonTitle')}>
        <Icon name="check" size={14} />
        {t('gonogo.button')}
      </Button>
    )
  }
  if (loading) {
    return (
      <div className="mb-4 rounded-lg border bg-card px-4 py-3 text-body text-muted-foreground">
        {t('gonogo.loading')}
      </div>
    )
  }
  if (error) {
    return (
      <div className="mb-4 space-y-2 rounded-lg border border-urgent/40 bg-urgent-soft px-4 py-3 text-body text-urgent-strong">
        <div>{error}</div>
        <Button variant="outline" size="sm" onClick={() => run(false)}>{t('common.retry')}</Button>
      </div>
    )
  }

  const known = DECISION[data!.decision]
  const d = known || { label: null, edge: 'border-l-border', text: '' }
  const decisionLabel = known ? t(known.label) : data!.decision
  const labels = new Map((data!.criteria_labels || []).map((c) => [c.key, c.label]))

  return (
    <Card className={cn('mb-4 border-l-4', d.edge)}>
      <div className="space-y-3 p-4">
        <div className="flex items-center gap-3">
          <span className={cn('text-lead font-semibold', d.text)}>{decisionLabel}</span>
          <div className="ml-auto flex items-center gap-2" title={t('gonogo.confidence')}>
            <Progress value={data!.confidence} className="h-1.5 w-16" />
            <span className="tabular text-body font-semibold">{data!.confidence}%</span>
          </div>
          <button
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label={t('gonogo.reassess')} title={t('gonogo.reassess')} onClick={() => run(true)}
          >
            <Icon name="refresh" size={12} />
          </button>
        </div>

        <p className="text-body leading-relaxed">{data!.summary_uz}</p>

        {/* ZANJIR SHU YERDA UZILARDI. Foydalanuvchi hukmni ko'radi va
            "nega?" deb so'ramoqchi bo'ladi — lekin chat boshqa joyda
            va u tahlilni KO'RMAGAN. Natijada model yagona yo'lni
            tanlardi: `run_gonogo`, ya'ni endigina ko'rilgan
            natijani 30-60 soniyada QAYTA hisoblash.
            Endi suhbat `manba='gonogo'` bilan ochiladi va server
            tizim blokiga saqlangan tahlil sharhini qo'yadi
            (`api/tahlil.py`). */}
        {onAskAi && (
          <Button variant="outline" size="sm" className="w-full justify-start"
            onClick={() => onAskAi(tenderId)}
            title={t('gonogo.askTitle')}>
            <Icon name="sparkle" size={13} />
            {t('gonogo.ask')}
          </Button>
        )}

        {!!data!.blockers?.length && (
          <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2">
            <div className="mb-1 text-micro font-semibold text-urgent-strong">
              {t('gonogo.blockers')}
            </div>
            <ul className="list-disc space-y-0.5 pl-4 text-body">
              {data!.blockers!.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          </div>
        )}

        <table className="w-full text-body">
          <tbody>
            {(data!.criteria || []).map((c) => {
              const s = STATUS[c.status] || STATUS.malumot_yoq
              return (
                <tr key={c.key} className="border-b border-border-soft last:border-0">
                  <td className="w-4 py-1.5 align-top">
                    <span className={cn('mt-1.5 block size-2 rounded-full', s.cls)} title={t(s.text)} />
                  </td>
                  <td className="w-[38%] py-1.5 pr-3 align-top font-medium">
                    {labels.get(c.key) || c.key}
                  </td>
                  <td className="py-1.5 align-top text-muted-foreground">{c.note_uz}</td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {!!data!.next_steps?.length && (
          <div className="rounded-lg bg-muted px-3 py-2">
            <div className="mb-1 text-micro font-semibold text-muted-foreground">
              {t('gonogo.nextSteps')}
            </div>
            <ul className="list-disc space-y-0.5 pl-4 text-body">
              {data!.next_steps!.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        )}

        {!!data!.missing_data?.length && (
          <div className="rounded-lg border border-soon/40 bg-soon-soft px-3 py-2">
            <div className="mb-1 text-micro font-semibold text-soon-strong">
              {t('gonogo.missing')}
            </div>
            <ul className="list-disc space-y-0.5 pl-4 text-body">
              {data!.missing_data!.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        )}

        <AiDocsNote meta={data!.documents} />

        <div className="text-micro text-muted-foreground">
          {t(data!.cached ? 'ai.cached' : 'ai.fresh')}
          {data!.model ? ` · ${data!.model}` : ''} · {t('gonogo.yoursDecision')}
        </div>
      </div>
    </Card>
  )
}
