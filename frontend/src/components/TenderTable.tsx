import { useState } from 'react'
import { useFormat, DEADLINE_CLASS } from '@/format'
import Icon from './Icon'
import { useT } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { cn } from '@/lib/utils'
import type { TenderRow } from '@/types'

// Ball rozetkasi rangi (Sizga mos ko'rinishi uchun).
// Tailwind sinf nomlarini DINAMIK QURIB bo'lmaydi (JIT ularni topa olmaydi),
// shuning uchun to'liq sinflar shu yerda yozilgan.
/**
 * Ball rangi. `null` — O'LCHANMAGAN, nol EMAS.
 *
 * O'LCHANGAN NUQSON (2026-09-04): bu yerda `m?.score ?? 0` turardi
 * va moslik hisoblanmagan qatorga QIZIL "0" chiqarardi — ya'ni
 * "o'lchanmadi" foydalanuvchiga "eng yomon moslik" bo'lib
 * ko'rinardi. `v_routing_agreement` dagi `review: 0%` bilan bir
 * xil sinf, faqat teskari tomonga og'gan.
 */
function scoreClass(s: number | null | undefined) {
  if (s == null) return 'bg-muted/50 text-muted-foreground'
  if (s >= 70) return 'bg-ok-soft text-ok-strong'
  if (s >= 40) return 'bg-soon-soft text-soon-strong'
  return 'bg-muted text-muted-foreground'
}

/** O'lchanmagan ball uchun belgi — `0` YOZILMAYDI. */
const BALL_YOQ = '—'

// Manba qisqa yorlig'i — qaysi platformadan kelganini bir qarashda bilish uchun.
const SRC: Record<string, { label: string; cls: string }> = {
  'xt-xarid': { label: 'xt-xarid', cls: 'bg-secondary text-primary' },
  'uzex': { label: 'etender', cls: 'bg-soon-soft text-soon-strong' },
}

interface ThProps {
  label: string
  col?: string
  sort?: string
  onSort?: (col: string) => void
  num?: boolean
  className?: string
}

/**
 * Ustun sarlavhasi. Tartiblanadigan bo'lsa — ichida HAQIQIY tugma.
 *
 * Avval `onClick` to'g'ridan-to'g'ri `<th>` da edi: sichqoncha bilan
 * ishlardi, klaviatura bilan esa umuman yo'q (`th` fokus olmaydi), va
 * ekran o'quvchi ustunning tartiblanganini bilmasdi. `aria-sort` shuni
 * aytadi, `<button>` esa Tab va Enter'ni qaytaradi.
 */
function Th({ label, col, sort, onSort, num, className }: ThProps) {
  const t = useT()
  if (!col) {
    return <TableHead className={cn(num && 'text-right', className)}>{label}</TableHead>
  }
  const asc = sort === col
  const desc = sort === `-${col}`
  return (
    <TableHead
      aria-sort={asc ? 'ascending' : desc ? 'descending' : 'none'}
      className={cn(num && 'text-right', className)}
    >
      <button
        type="button"
        onClick={() => onSort?.(col)}
        title={t('table.sortBy', { col: label })}
        className={cn(
          'inline-flex select-none items-center gap-1 rounded-sm py-1 transition-colors hover:text-foreground',
          num && 'flex-row-reverse',
          (asc || desc) && 'text-foreground',
        )}
      >
        {label}
        <Icon
          name={desc ? 'sortDesc' : 'sortAsc'}
          size={12}
          className={cn('transition-opacity', asc || desc ? 'opacity-100' : 'opacity-30')}
        />
      </button>
    </TableHead>
  )
}

interface TenderTableProps {
  items: TenderRow[]
  mode: string
  onSelect: (id: number) => void
  sort: string
  onSort: (col: string) => void
  loading: boolean
  showStatus: boolean
}

export default function TenderTable({
  items, mode, onSelect, sort, onSort, loading, showStatus,
}: TenderTableProps) {
  const t = useT()
  const f = useFormat()
  const isMatch = mode === 'match'
  const [open, setOpen] = useState<Set<number>>(() => new Set())

  function toggle(e: React.MouseEvent, id: number) {
    e.stopPropagation()
    setOpen((prev) => {
      const n = new Set(prev)
      if (n.has(id)) n.delete(id); else n.add(id)
      return n
    })
  }

  if (loading && items.length === 0) {
    return (
      <div className="space-y-2 rounded-xl border bg-card p-4">
        {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
      </div>
    )
  }

  if (!loading && items.length === 0) {
    return (
      <Empty className="rounded-xl border border-dashed bg-card">
        <EmptyHeader>
          <EmptyTitle>{t('common.notFound')}</EmptyTitle>
          <EmptyDescription>{t('table.empty')}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  // Qatordan chiqariladigan qiymatlar — jadval ham, kartochka ham shu
  // funksiyani ishlatadi, ya'ni ikki ko'rinish bir-biridan ajralib ketmaydi.
  function derive(row: TenderRow) {
    const lots = row.lots_summary || []
    const titled = lots.filter((l) => l.title)
    return {
      d: f.deadline(row.close_at),
      lots,
      src: SRC[row.source_platform]
        || { label: row.source_platform, cls: 'bg-muted text-muted-foreground' },
      // Sarlavha: lot nomlari (eng aniq), bo'lmasa tender nomi
      title: titled.length > 0
        ? titled.map((l) => l.title).join('  ·  ')
        : (row.name || `#${row.id}`),
      // Yetkazish muddati — lotlar bo'yicha eng uzuni
      dlv: lots.reduce(
        (mx, l) => (l.delivery_period != null && l.delivery_period > mx ? l.delivery_period : mx), 0),
    }
  }

  return (
    <>
    {/* TOR EKRAN — KARTOCHKALAR, jadval emas.
        To'qqiz ustunli jadval telefonda ishlamaydi: qat'iy kengliklar
        yig'indisi ekran enidan katta bo'lgani uchun "xarid predmeti"
        ustuni nolgacha siqilib, sarlavhalar bir-birining ustiga
        chiqib qolardi. Gorizontal aylantirish ham yechim emas — eng
        muhim ustunlar (summa, muddat) ko'rinmay qolaveradi. Kartochkada
        esa har tender uchun o'sha ma'lumot, faqat ustma-ust. */}
    <ul className="space-y-2 lg:hidden">
      {items.map((row) => {
        const { d, src, title, dlv } = derive(row)
        const m = row.match
        return (
          <li key={row.id} className="rounded-lg border bg-card p-3">
            <div className="mb-1.5 flex items-center gap-2">
              {isMatch && (
                <span className={cn('tabular rounded-md px-1.5 py-0.5 text-caption font-semibold',
                  scoreClass(m?.score))}
                  title={m?.score == null ? t('table.scoreNone') : undefined}
                >{m?.score ?? BALL_YOQ}</span>
              )}
              <span className={cn('rounded px-1.5 py-0.5 text-micro font-semibold', src.cls)}>
                {src.label}
              </span>
              <span className={cn('tabular ml-auto rounded px-2 py-0.5 text-caption font-semibold',
                DEADLINE_CLASS[d.level])}>
                <span aria-hidden="true">{d.short}</span>
                <span className="sr-only">{d.text}</span>
              </span>
            </div>

            <button
              type="button"
              onClick={() => onSelect(row.id)}
              className="line-clamp-3 w-full rounded-sm text-left font-medium"
            >
              {title}
            </button>

            <dl className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-caption text-muted-foreground">
              <div className="flex gap-1.5">
                <dt className="sr-only">{t('table.amount')}</dt>
                <dd className="tabular font-semibold text-foreground">
                  {f.shortMoney(row.totalcost, row.currency)}
                </dd>
              </div>
              {!!dlv && (
                <div className="flex gap-1.5">
                  <dt>{t('table.delivery')}</dt>
                  <dd className="tabular">{t('common.days', { n: dlv })}</dd>
                </div>
              )}
              {row.region?.name && (
                <div className="flex gap-1.5">
                  <dt className="sr-only">{t('table.region')}</dt>
                  <dd>
                    {row.region.name}
                    {row.hudud_tashqari && (
                      <span className="ml-1.5 rounded border border-soon/40
                                       bg-soon-soft px-1 text-micro text-soon-strong">
                        {t('match.outOfRegion')}
                      </span>
                    )}
                  </dd>
                </div>
              )}
            </dl>
            {row.company?.name && (
              <p className="mt-1 truncate text-caption text-muted-foreground">
                {row.company.name}
              </p>
            )}
          </li>
        )
      })}
    </ul>

    <div className="hidden overflow-x-auto rounded-xl border bg-card lg:block">
      {/* `table-fixed` — ustun kengliklari SARLAVHADAN olinadi, tarkibidan
          emas. Avtomatik joylashuvda ("table-auto") har qator o'z eniga
          ta'sir qilardi: uzun buyurtmachi nomi butun jadvalni kengaytirib,
          summa va muddat ustunlari o'ng chetdan chiqib ketardi — ya'ni
          qaror uchun kerak bo'lgan ikki ustun ko'rinmay qolardi. */}
      <Table className="table-fixed text-body">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {/* IKKI USTUN TOR EKRANDA YASHIRINADI (`hidden xl:table-cell`).
                1024px da jadvalga ~740px qoladi — sakkiz ustunga yetmaydi va
                xarid predmeti o'qib bo'lmas darajada siqilardi. Yashirilgani
                — manba va yetkazish muddati: ular qaror uchun eng kam
                ahamiyatlisi, ikkalasi ham tender panelida to'liq bor.
                Predmet, summa va muddat HAR QANDAY enda qoladi. */}
            {isMatch && <Th label={t('table.score')} num className="w-[3.75rem]" />}
            <Th label="" className="w-[2rem]" />
            <Th label={t('table.subject')} />
            <Th label={t('table.source')} className="hidden w-[5.5rem] xl:table-cell" />
            <Th label={t('table.customer')} className="w-[15%]" />
            <Th label={t('table.region')} className="w-[8rem]" />
            <Th label={t('table.delivery')} num className="hidden w-[5.25rem] xl:table-cell" />
            <Th label={t('table.amount')} col="totalcost" sort={sort} onSort={onSort} num className="w-[7.5rem]" />
            <Th label={t('table.deadline')} col="close_at" sort={sort} onSort={onSort} className="w-[6rem]" />
          </TableRow>
        </TableHeader>
        <TableBody className={cn(loading && 'opacity-50 transition-opacity')}>
          {items.map((row) => {
            const { d, lots, src, title, dlv } = derive(row)
            const m = row.match
            const isOpen = open.has(row.id)
            const cols = 8 + (isMatch ? 1 : 0)

            // Ikkinchi qator FAQAT yangi ma'lumot qo'shsa ko'rsatiladi:
            // sarlavhada allaqachon bor mahsulotlarni takrorlamaymiz.
            const extra = (row.goods_preview || [])
              .filter((g) => g && !title.includes(g))
              .slice(0, 3)

            return [
              <TableRow key={row.id} className="cursor-pointer" onClick={() => onSelect(row.id)}>
                {isMatch && (
                  <TableCell className="text-right">
                    <span className={cn(
                      'tabular inline-block min-w-[34px] rounded-md px-2 py-0.5 text-center text-body font-semibold',
                      scoreClass(m?.score),
                    )} title={m?.score == null ? t('table.scoreNone') : undefined}
                    >{m?.score ?? BALL_YOQ}</span>
                  </TableCell>
                )}
                <TableCell className="pr-0">
                  {lots.length > 0 && (
                    <button
                      className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      onClick={(e) => toggle(e, row.id)}
                      aria-expanded={isOpen}
                      aria-label={t('table.toggleLots', { n: lots.length })}
                      title={t('table.lots', { n: lots.length })}
                    >
                      <Icon name="right" size={12} className={cn('transition-transform', isOpen && 'rotate-90')} />
                    </button>
                  )}
                </TableCell>

                {/* `whitespace-normal` SHART: `TableCell` ning standart
                    holati `whitespace-nowrap` — sonli ustunlar uchun to'g'ri,
                    lekin xarid predmeti UZUN MATN. Nowrap bilan sarlavha
                    ikkinchi qatorga tushmasdan bitta chiziqda cho'zilib,
                    ustun chetida so'z o'rtasidan KESILARDI va jadval
                    gorizontal aylanardi. */}
                <TableCell className="whitespace-normal py-2.5">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
                    {/* TENDERNI OCHISH — HAQIQIY TUGMA, sarlavhaning o'zida.
                        Avval `onClick` faqat `<tr>` da edi: sichqoncha bilan
                        ishlardi, klaviatura bilan esa umuman yo'q — jadval
                        qatoriga Tab bilan yetib bo'lmaydi. Ya'ni ilovaning
                        ASOSIY harakati klaviaturadan mavjud emas edi.
                        Qatorning o'zidagi bosish saqlanib qoldi — sichqoncha
                        bilan hamma yeriga bosaverish qulay. */}
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); onSelect(row.id) }}
                      title={title}
                      className="line-clamp-2 rounded-sm text-left hover:underline"
                    >
                      {title}
                    </button>
                    {lots.length > 1 && (
                      <span className="rounded bg-muted px-1.5 py-px text-micro text-muted-foreground">
                        {t('table.lots', { n: lots.length })}
                      </span>
                    )}
                    {!!row.doc_count && (
                      <span className="inline-flex items-center gap-0.5 rounded bg-secondary px-1.5 py-px text-micro text-primary"
                        title={t('table.docs', { n: row.doc_count! })}>
                        <Icon name="clip" size={10} />{row.doc_count}
                      </span>
                    )}
                    {showStatus && (
                      <Badge variant="secondary" className="px-1.5 py-0 text-micro">
                        {row.status_name || row.status}
                      </Badge>
                    )}
                  </div>
                  {extra.length > 0 && (
                    <div className="mt-0.5 truncate text-caption text-muted-foreground"
                      title={(row.goods_preview || []).join(', ')}>
                      {extra.join(' · ')}
                    </div>
                  )}
                  {isMatch && !!m?.matched_keywords?.length && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {m.matched_keywords.map((k) => (
                        <span key={k} className="rounded bg-secondary px-1.5 py-px text-micro text-primary">
                          {k}
                        </span>
                      ))}
                    </div>
                  )}
                </TableCell>

                <TableCell className="hidden xl:table-cell">
                  <span className={cn('rounded px-1.5 py-0.5 text-micro font-semibold', src.cls)}>
                    {src.label}
                  </span>
                </TableCell>
                <TableCell className="truncate text-muted-foreground" title={row.company?.name ?? ''}>
                  {row.company?.name || '—'}
                </TableCell>
                <TableCell className="truncate text-muted-foreground" title={row.region?.name ?? ''}>
                  {row.region?.name || '—'}
                  {/* HUDUDDAN TASHQARI — qator YASHIRILMAYDI, belgilanadi.
                      Katalog "mahsulot mos" deydi, profil esa "biz u yerda
                      ishlamaymiz". Ikkinchisini ko'rsatmasa foydalanuvchi
                      broker navbatida nega bu tender yo'qligini bilmasdi. */}
                  {row.hudud_tashqari && (
                    <Badge variant="outline"
                      className="ml-1.5 border-soon/40 bg-soon-soft px-1.5 py-0
                                 text-micro text-soon-strong align-middle">
                      {t('match.outOfRegion')}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="tabular hidden text-right text-muted-foreground xl:table-cell">
                  {dlv ? t('common.days', { n: dlv }) : '—'}
                </TableCell>
                <TableCell className="tabular text-right font-semibold">
                  {f.shortMoney(row.totalcost, row.currency)}
                </TableCell>
                {/* MUDDAT — jadvaldagi eng muhim ustun: qaror shunga qarab
                    qabul qilinadi. `.tabular` bilan raqamlar bir xil
                    kenglikda, ya'ni qatorlar bo'ylab pastga qaraganda
                    sonlar bir chiziqda turadi va "3 kun" bilan "13 kun"
                    ni ajratish uchun o'qish shart emas.
                    To'liq matn (`3 kun qoldi`) — ekran o'quvchiga. */}
                <TableCell>
                  <span className={cn('tabular inline-block rounded px-2 py-0.5 text-caption font-semibold',
                    DEADLINE_CLASS[d.level])}>
                    <span aria-hidden="true">{d.short}</span>
                    <span className="sr-only">{d.text}</span>
                  </span>
                </TableCell>
              </TableRow>,

              isOpen ? (
                <TableRow key={`${row.id}-lots`} className="bg-muted/60 hover:bg-muted/60">
                  <TableCell colSpan={cols} className="py-2">
                    {lots.map((l) => (
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-1 text-caption" key={l.lot_id}>
                        <span className="w-[70px] shrink-0 text-micro font-semibold text-muted-foreground">
                          {t('table.lotNo', { id: l.lot_id })}
                        </span>
                        <span className="flex-1 min-w-[200px]">{l.title || t('table.untitled')}</span>
                        <span className="flex flex-wrap items-baseline gap-x-3 text-muted-foreground">
                          {l.total_sum_lot != null && (
                            <b className="tabular text-foreground">{f.shortMoney(l.total_sum_lot, row.currency)}</b>
                          )}
                          {l.item_count != null && <span>{t('table.positions', { n: l.item_count })}</span>}
                          {l.delivery_period != null && (
                            <span title={t('table.deliveryTitle')}>{t('common.days', { n: l.delivery_period })}</span>
                          )}
                          {l.guarantee != null && (
                            <span title={t('table.guaranteeTitle')}>{t('table.guaranteeDays', { n: l.guarantee })}</span>
                          )}
                        </span>
                      </div>
                    ))}
                    {(row.goods_preview || []).length > 0 && (
                      <div className="flex gap-3 border-t pt-2 text-caption text-muted-foreground">
                        <span className="w-[70px] shrink-0 text-micro font-semibold">{t('table.goods')}</span>
                        <span>{row.goods_preview!.join(' · ')}</span>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ) : null,
            ]
          })}
        </TableBody>
      </Table>
    </div>
    </>
  )
}
