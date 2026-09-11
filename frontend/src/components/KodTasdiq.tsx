/**
 * MAHSULOT KODINI TASDIQLASH — INSON HALQASI.
 *
 * NEGA BU EKRAN BOR (o'lchangan, 2026-09-11). Backendda uch endpoint
 * ANCHADAN BERI turardi — `kod-takliflar`, `kod-tasdiq`, `kod-rad` —
 * va interfeys ularning BIRORTASINI ham chaqirmasdi. Zanjir aynan shu
 * yerda uzilgan edi:
 *
 *     nomzod yasalmaydi -> catalog_product_code bo'sh
 *       -> v_catalog_code_active bo'sh -> "Sizga mos" HECH QACHON
 *          natija bermaydi
 *
 * Ya'ni tizim ishlamayotgandek ko'rinardi, aslida qaror qabul
 * qiladigan joy qurilmagan edi.
 *
 * --- NEGA TANLOVNI ODAM QILADI ---
 * Ikki daraja ko'rsatiladi va bu ATAYLAB:
 *
 *   keng (5 belgi)  guruh. Ko'proq tender topadi, begonasini ham.
 *   aniq (8 belgi)  sinf. Kamroq, lekin toza.
 *
 * Qaysi kenglik to'g'ri ekanini FAQAT broker biladi. O'lchangan
 * holat: "Tibbiy muzlatgich" uchun `28.25` guruhi ventilyatsiyani
 * ham qamraydi va lokomotiv ta'miridagi "Калорифер" mos chiqadi.
 *
 * --- BALL KO'RSATILMAYDI ---
 * `skor` — RRF yig'indisi, FOIZ EMAS. Undan "% moslik" yasash
 * yolg'on bo'lardi (o'lchandi: markazlangan kosinus shovqindan
 * ajralmaydi). Shuning uchun ekranda RAQAM emas, OQIBAT turadi:
 * tasdiqlansa nechta OCHIQ tender ko'rinadi.
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api'
import Icon from './Icon'
import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import type { MahsulotKodTaklif, MahsulotKodTakliflar, Product } from '@/types'

interface KodTasdiqProps {
  product: Product
  onClose: () => void
  /** Qaror yozilgach katalog ro'yxati yangilanadi (`codes` o'zgaradi). */
  onChanged: () => void
}

export default function KodTasdiq({ product, onClose, onChanged }: KodTasdiqProps) {
  const t = useT()
  const [data, setData] = useState<MahsulotKodTakliflar | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [band, setBand] = useState<string | null>(null)

  const yukla = useCallback(() => {
    setError(null)
    api.kodTakliflar(product.id)
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [product.id])

  useEffect(() => { yukla() }, [yukla])

  async function qaror(code: string, tasdiq: boolean) {
    setBand(code); setError(null)
    try {
      if (tasdiq) await api.kodTasdiq(product.id, code)
      else await api.kodRad(product.id, code)
      // RO'YXAT QAYTA O'QILADI, mahalliy holat TUZATILMAYDI: server
      // tasdiqlashda keng kodlarni o'zi o'chiradi (aniq kod bor
      // ekan, guruh natijani shishirmasin). Mahalliy tuzatish o'sha
      // qoidani IKKINCHI marta yozish bo'lardi va ikkisi bir kun
      // ajralib ketardi.
      yukla()
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBand(null)
    }
  }

  const bosh = data && data.keng.length === 0 && data.aniq.length === 0

  return (
    <Sheet open onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent side="right" closeLabel={t('common.close')}
        className="w-[34rem] max-w-[94vw] overflow-y-auto p-0 sm:max-w-[94vw]">
        <SheetHeader className="sticky top-0 z-10 border-b bg-card px-5 py-3 pr-14">
          <SheetTitle className="line-clamp-2 text-body font-semibold">
            {product.name}
          </SheetTitle>
          <p className="text-caption text-muted-foreground">{t('kod.lead')}</p>
        </SheetHeader>

        <div className="space-y-5 px-5 py-4">
          {error && (
            <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
              {error}
            </div>
          )}

          {!data && !error && (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          )}

          {/* BO'SH NATIJANING SABABI AYTILADI.
              "Taklif yo'q" o'zi hech narsa tushuntirmaydi va odam
              qayta-qayta ochib ko'rardi. `katalogBosh.ts` bilan
              ayni tamoyil. */}
          {bosh && (
            <Empty className="rounded-xl border border-dashed">
              <EmptyHeader>
                <EmptyTitle>{t('kod.emptyTitle')}</EmptyTitle>
                <EmptyDescription>{t('kod.emptyBody')}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}

          {data && data.aniq.length > 0 && (
            <Guruh nom={t('kod.exact')} izoh={t('kod.exactHint')}
                   items={data.aniq} band={band} onQaror={qaror} />
          )}
          {data && data.keng.length > 0 && (
            <Guruh nom={t('kod.broad')} izoh={t('kod.broadHint')}
                   items={data.keng} band={band} onQaror={qaror} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

/**
 * Signal yorlig'i. NOTANISH signal XOM holda ko'rsatiladi.
 *
 * Yashirilsa yoki "boshqa" deyilsa, backendda yangi signal
 * qo'shilgani interfeysda JIMGINA yo'qolardi -- va aynan shu
 * signal nega bu kod taklif qilinganini tushuntirayotgan bo'lishi
 * mumkin.
 */
function signalNomi(sg: string, t: (k: never, v?: never) => string): string {
  const kalit: Record<string, string> = {
    leksik: 'kod.signal.leksik',
    semantik: 'kod.signal.semantik',
    oila: 'kod.signal.oila',
  }
  const k = kalit[sg]
  return k ? t(k as never) : sg
}

interface GuruhProps {
  nom: string
  izoh: string
  items: MahsulotKodTaklif[]
  band: string | null
  onQaror: (code: string, tasdiq: boolean) => void
}

function Guruh({ nom, izoh, items, band, onQaror }: GuruhProps) {
  const t = useT()
  return (
    <section>
      <h3 className="text-body font-semibold">{nom}</h3>
      <p className="mb-2 text-caption text-muted-foreground">{izoh}</p>
      <ul className="space-y-2">
        {items.map((x) => {
          const qaror = x.tasdiqlandi ? 'tasdiq' : x.rad_etildi ? 'rad' : null
          return (
            <li key={x.code}
                data-kod={x.code}
                data-qaror={qaror ?? undefined}
                className="rounded-lg border bg-card p-3">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="tabular font-semibold">{x.code}</span>
                <span className="text-body">{x.name_ru || '—'}</span>
              </div>

              {/* OQIBAT — BALL EMAS. Odam "tasdiqlasam nima
                  bo'ladi" degan savolga javob ko'rishi kerak. */}
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Badge variant="secondary">
                  {t('kod.openTenders', { n: x.n_tender_open })}
                </Badge>
                {x.signallar.map((sg) => (
                  <Badge key={sg} variant="outline" className="text-caption">
                    {signalNomi(sg, t)}
                  </Badge>
                ))}
              </div>

              {/* DALIL: kod ostidagi HAQIQIY nomlar. Kod nomi begona
                  bo'lishi mumkin, namunalar esa tanish -- qaror
                  ko'pincha aynan shulardan chiqadi. */}
              {x.namunalar.length > 0 && (
                <p className="mt-1.5 line-clamp-2 text-caption text-muted-foreground">
                  {x.namunalar.join(' · ')}
                </p>
              )}

              <div className="mt-2 flex items-center gap-2">
                {qaror === 'tasdiq' && (
                  <Badge className="bg-ok-soft text-ok-strong">
                    {t('kod.approved')}
                  </Badge>
                )}
                {qaror === 'rad' && (
                  <Badge variant="outline" className="text-muted-foreground">
                    {t('kod.rejected')}
                  </Badge>
                )}
                {qaror !== 'tasdiq' && (
                  <Button size="sm" disabled={band === x.code}
                          onClick={() => onQaror(x.code, true)}>
                    <Icon name="check" size={14} /> {t('kod.approve')}
                  </Button>
                )}
                {qaror !== 'rad' && (
                  <Button size="sm" variant="outline" disabled={band === x.code}
                          onClick={() => onQaror(x.code, false)}>
                    {t('kod.reject')}
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
