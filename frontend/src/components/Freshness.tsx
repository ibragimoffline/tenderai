import { useFormat } from '@/format'
import { useT } from '@/i18n'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { Freshness as FreshnessData } from '@/types'

const SRC_LABEL: Record<string, string> = { 'xt-xarid': 'xt-xarid', 'uzex': 'etender.uzex' }

const DOT: Record<string, string> = {
  ok: 'bg-ok',
  soon: 'bg-soon',
  urgent: 'bg-urgent',
}

// Ma'lumot yangiligi ko'rsatkichi. Yashil = yangi + xatosiz,
// sariq = eskirgan (>2 soat), qizil = biror manbada xato.
export default function Freshness({ data }: { data: FreshnessData | null }) {
  const t = useT()
  const f = useFormat()

  if (!data) return null
  const age = data.overall_age_sec
  const level = data.any_error ? 'urgent' : (age != null && age > 7200 ? 'soon' : 'ok')

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex h-9 items-center gap-2 rounded-md border border-input bg-card px-3 text-caption transition-colors hover:bg-accent"
          title={t('fresh.title')}
        >
          {/* Nuqta rangi YOLG'IZ signal EMAS — yonidagi matn holatni so'z
              bilan ham aytadi. Rang ajratmaydigan foydalanuvchi uchun
              "yashil nuqta" o'zicha hech narsa bildirmaydi (WCAG 1.4.1). */}
          <span aria-hidden="true" className={cn('size-2 shrink-0 rounded-full', DOT[level])} />
          <span className="text-muted-foreground">
            {data.any_error ? t('fresh.etlError') : t('fresh.fromSource', { ago: f.agoSec(age) })}
          </span>
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-[19rem] max-w-[calc(100vw-2rem)] p-1.5">
        <h2 className="px-2.5 py-1.5 text-micro font-semibold uppercase text-muted-foreground">
          {t('fresh.sources')}
        </h2>
        <ul>
          {data.platforms.map((p) => (
            <li className="flex items-center gap-2 px-2.5 py-1.5 text-body" key={p.source_platform}>
              <span aria-hidden="true"
                className={cn('size-2 shrink-0 rounded-full', p.status === 'error' ? DOT.urgent : DOT.ok)} />
              <span className="flex-1 truncate">
                {SRC_LABEL[p.source_platform] || p.source_platform}
              </span>
              <span className={cn('tabular text-caption',
                p.status === 'error' ? 'text-urgent-strong' : 'text-muted-foreground')}>
                {p.status === 'error' ? t('fresh.error') : f.agoSec(p.age_sec)}
              </span>
              {p.new > 0 && (
                <span className="tabular rounded bg-ok-soft px-1.5 py-px text-micro font-semibold text-ok-strong">
                  +{p.new}
                </span>
              )}
            </li>
          ))}
        </ul>
        {/* KORPUS. "Tugadi" ATAYLAB yozilmaydi: har soat yangi tender
            keladi, hujjati chiqariladi, bo'laklarga bo'linadi — ya'ni
            yagona to'g'ri holat "quvib yetdi". "Tugadi" ko'rsatilsa
            odam ish bitgan deb o'ylardi va navbat yana o'sganini
            payqamasdi. */}
        {!!data.corpus && (
          <p
            className="mt-1 border-t px-2.5 pt-2 text-caption
                       text-muted-foreground"
            title={t('fresh.corpusTitle')}
          >
            {t('fresh.corpus', { n: data.corpus.tenders })}{' · '}
            {data.corpus.caught_up ? (
              <b className="text-ok">{t('fresh.corpusCaught')}</b>
            ) : (
              <b className="tabular text-foreground">
                {t('fresh.corpusBehind', { n: data.corpus.unvectorized })}
              </b>
            )}
          </p>
        )}
        {!!data.detection?.sample && (
          <p
            className="mt-1 border-t px-2.5 pb-1 pt-2 text-caption text-muted-foreground"
            title={t('fresh.lagTitle')}
          >
            {t('fresh.lag')}{' '}
            {/* MEDIANA `?? 0` QILINMAYDI. Nol soat "aniqlash bir
                zumda" degani — ya'ni O'LCHANMAGAN holat ENG YAXSHI
                natija bo'lib ko'rinardi. Yonidagi `within_1h_pct`
                allaqachon to'g'ri qilingan (`!= null` bilan
                yashiriladi); mediana undan qolib ketgan edi. */}
            <b className="tabular text-foreground">
              {data.detection.median_hours == null
                ? t('fresh.lagNone')
                : t('fresh.lagHours', { n: data.detection.median_hours })}
            </b>
            {data.detection.within_1h_pct != null &&
              <> · {t('fresh.within1h', { pct: data.detection.within_1h_pct })}</>}
          </p>
        )}
      </PopoverContent>
    </Popover>
  )
}
