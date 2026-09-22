import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api'
import { useFormat } from '@/format'
import { useT } from '@/i18n'
import type { KodDalil as Dalil } from '@/types'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'

/**
 * `Ochiq tender` SONI ORTIDAGI DALIL.
 *
 * NEGA IKKI QISM. Son ATAYLAB KENG: mahsulot nomining tokenlari YOKI
 * bilan bog'lanadi, ya'ni bitta umumiy so'z butunlay boshqa tenderni
 * ham olib keladi. O'lchangan misol (#3041 Patch-kord, tokenlar
 * `patch, kabel, kord, vita`): 22 ta ichiga quvvat kabeli va kabel
 * yotqizish XIZMATI ham kirgan.
 *
 * Shuning uchun ekran RAQAMNI EMAS, DALILNI ko'rsatadi:
 *
 *   oilalar    "nega bu kod?" -- nomzodlar kod oilasi bo'yicha.
 *              Ko'rikda odatda SHU hal qiladi: "27.* Патч корд 50 lot"
 *              va "26.* Кабель питания 15 lot" yonma-yon turganda
 *              kod to'g'rimi yoki yo'qmi darhol ko'rinadi.
 *   tenderlar  "qaysi tenderlar?" -- har qatorda QAYSI lot va QAYSI
 *              token olib kelgani yoziladi.
 */
export default function KodDalil({
  productId, ochiqTender, onClose, onOpenTender,
}: {
  productId: number
  /** Ustunda ko'ringan son -- server javobi bilan solishtirish uchun. */
  ochiqTender: number
  onClose: () => void
  onOpenTender?: (tenderId: number) => void
}) {
  const t = useT()
  const f = useFormat()
  const [data, setData] = useState<Dalil | null>(null)
  const [error, setError] = useState<string | null>(null)

  const yukla = useCallback(() => {
    setError(null)
    api.kodDalil(productId)
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [productId])

  useEffect(() => { yukla() }, [yukla])

  return (
    <Sheet open onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent side="right" closeLabel={t('common.close')}
        className="w-[44rem] max-w-[96vw] overflow-y-auto p-0 sm:max-w-[96vw]">
        <SheetHeader className="sticky top-0 z-10 border-b bg-card px-5 py-3 pr-14">
          <SheetTitle className="line-clamp-2 text-body font-semibold">
            {data?.mahsulot ?? t('dalil.title')}
          </SheetTitle>
          <p className="text-caption text-muted-foreground">
            {t('dalil.lead', { n: String(data?.jami ?? ochiqTender) })}
          </p>
        </SheetHeader>

        <div className="space-y-6 px-5 py-4">
          {error && (
            <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
              {error}
            </div>
          )}

          {!data && !error && (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          )}

          {data && (
            <>
              <section className="space-y-2">
                <h3 className="text-body font-semibold">{t('dalil.families')}</h3>
                <p className="text-caption text-muted-foreground">
                  {t('dalil.tokens')}: {data.tokens.join(' · ') || '—'}
                </p>
                {data.oilalar.length === 0 && (
                  <p className="text-caption text-muted-foreground">{t('dalil.none')}</p>
                )}
                {data.oilalar.map((o) => (
                  <div key={o.bolim}
                       className="flex items-baseline gap-3 rounded-lg border px-3 py-2">
                    <span className="tabular font-medium">{o.bolim}.*</span>
                    <span className="tabular text-caption text-muted-foreground">
                      {o.lot} lot
                    </span>
                    <span className="flex-1 truncate">{o.nom ?? '—'}</span>
                    <span className="text-caption text-muted-foreground">
                      {o.tokens.join(', ')}
                    </span>
                  </div>
                ))}
              </section>

              <section className="space-y-2">
                <h3 className="text-body font-semibold">
                  {t('dalil.tenders', { n: String(data.tenderlar.length) })}
                </h3>
                {/* RO'YXAT CHEGARALANGAN bo'lishi mumkin -- uzunligi
                    sondan kam bo'lsa buni AYTAMIZ, aks holda "tender
                    kamaydi" deb o'qilardi. */}
                {data.tenderlar.length < data.jami && (
                  <p className="text-caption text-muted-foreground">
                    {t('dalil.limited', { n: String(data.jami) })}
                  </p>
                )}
                {data.tenderlar.map((x) => (
                  <button key={x.id} type="button"
                    className="block w-full rounded-lg border px-3 py-2 text-left hover:bg-muted/40"
                    onClick={() => onOpenTender?.(x.id)}>
                    <div className="flex items-baseline gap-2">
                      <span className="flex-1 truncate font-medium">
                        {x.name ?? `#${x.id}`}
                      </span>
                      {x.close_at && (
                        <span className="tabular text-caption text-muted-foreground">
                          {f.dateFmt(x.close_at)}
                        </span>
                      )}
                    </div>
                    <div className="text-caption text-muted-foreground">
                      {(x.lotlar[0] ?? '—')}
                      {x.tokens.length > 0 && <> · {x.tokens.join(', ')}</>}
                    </div>
                  </button>
                ))}
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
