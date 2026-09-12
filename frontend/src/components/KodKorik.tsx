import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api'
import { useT } from '@/i18n'
import type { KodKorikQator } from '@/types'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import KodTasdiq from './KodTasdiq'

/**
 * KO'RIK NAVBATI — siyosatdan o'tmagan, LEKIN hali FAOL kodlar.
 *
 * ENG MUHIM XULQ: bu ekran KODNI O'ZGARTIRMAYDI. Sahifa ochilishi
 * kodni deaktivatsiya qilmaydi; bog'lanish faqat odam "Saqlash" yoki
 * "Rad etish" bosganda o'zgaradi.
 *
 * NEGA SHUNDAY (2026-09-12 qarori): 187 ta kod siyosat yozilishidan
 * OLDIN qo'llangan va yangi siyosat ulardan 49 tasini o'tkazmaydi.
 * Ular orasida haqiqiy xato bor (server SHKAFI `Сервер` deb
 * kodlangan), lekin HAMMASI xato degani emas. Birdan o'chirish
 * "Sizga mos" ni 49 mahsulot bo'yicha kamaytirardi va TO'G'RI
 * kodlarni ham yo'qotardi.
 *
 * UCH AMAL, YANGI ENDPOINTSIZ:
 *   Saqlash    -> kodTasdiq(o'sha kod) — tizim qarori INSON qaroriga
 *   Boshqa kod -> mavjud KodTasdiq paneli
 *   Rad etish  -> kodRad
 */
export default function KodKorik() {
  const t = useT()
  const [qatorlar, setQatorlar] = useState<KodKorikQator[] | null>(null)
  const [jami, setJami] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [band, setBand] = useState<number | null>(null)
  const [boshqa, setBoshqa] = useState<KodKorikQator | null>(null)

  const yukla = useCallback(() => {
    setError(null)
    api.kodKorik()
      .then((r) => { setQatorlar(r.qatorlar); setJami(r.jami) })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => { yukla() }, [yukla])

  async function qaror(r: KodKorikQator, saqla: boolean) {
    setBand(r.product_id); setError(null)
    try {
      if (saqla) await api.kodTasdiq(r.product_id, r.code)
      else await api.kodRad(r.product_id, r.code)
      yukla()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBand(null)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-title font-semibold">{t('korik.title')}</h1>
        <p className="text-caption text-muted-foreground">{t('korik.lead')}</p>
      </div>

      {error && (
        <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
          {error}
        </div>
      )}

      {!qatorlar && !error && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-lg" />
          ))}
        </div>
      )}

      {qatorlar && qatorlar.length === 0 && (
        <Empty>
          <EmptyHeader><EmptyTitle>{t('korik.empty')}</EmptyTitle></EmptyHeader>
        </Empty>
      )}

      {qatorlar && qatorlar.length > 0 && (
        <>
          <p className="text-caption text-muted-foreground">
            {t('korik.count', { n: String(jami) })}
          </p>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>{t('korik.thProduct')}</TableHead>
                  <TableHead className="w-[130px]">{t('korik.thCode')}</TableHead>
                  <TableHead className="w-[220px]">{t('korik.thReason')}</TableHead>
                  <TableHead className="w-[110px] text-right">
                    {t('korik.thTenders')}
                  </TableHead>
                  <TableHead className="w-[260px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {qatorlar.map((r) => (
                  <TableRow key={`${r.product_id}-${r.code}`}
                            className="hover:bg-transparent">
                    <TableCell className="font-medium">{r.mahsulot}</TableCell>
                    <TableCell className="tabular">{r.code}</TableCell>
                    <TableCell className="text-caption text-muted-foreground">
                      {r.siyosat_sabab || '—'}
                    </TableCell>
                    <TableCell className="tabular text-right">
                      {r.ochiq_tender}
                    </TableCell>
                    <TableCell className="space-x-2 text-right">
                      <Button size="sm" variant="outline"
                              disabled={band === r.product_id}
                              onClick={() => qaror(r, true)}>
                        {t('korik.keep')}
                      </Button>
                      <Button size="sm" variant="outline"
                              disabled={band === r.product_id}
                              onClick={() => setBoshqa(r)}>
                        {t('korik.other')}
                      </Button>
                      <Button size="sm" variant="ghost"
                              disabled={band === r.product_id}
                              onClick={() => qaror(r, false)}>
                        {t('korik.reject')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}

      {boshqa && (
        <KodTasdiq
          product={{ id: boshqa.product_id, name: boshqa.mahsulot }}
          onClose={() => setBoshqa(null)}
          onChanged={yukla}
        />
      )}
    </div>
  )
}
