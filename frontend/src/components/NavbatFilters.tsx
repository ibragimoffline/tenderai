/**
 * NAVBAT FILTRI — "Broker navbati" va "Talablar" uchun umumiy panel.
 *
 * NEGA `Filters.tsx` QAYTA ISHLATILMADI: u bosh ro'yxatning holatiga
 * (`FiltersState`: status, valyuta, kategoriya, mahsulot, saralash)
 * bog'langan va navbatlarda ularning ko'pi MA'NOSIZ — navbatda
 * faqat ochiq tenderlar bor, valyuta esa qaror uchun ahamiyatsiz.
 * Uni umumlashtirish ikkala tomonga ham keraksiz shartlar qo'shardi.
 *
 * NEGA UMUMIY: qidiruv maydonining XULQI (debounce, joylashuv,
 * o'rin egallovchi matn) ikkala navbatda ham bir xil bo'lishi kerak.
 * Ikki joyda yozilsa ajralib ketardi va foydalanuvchi bir bo'limda
 * o'rgangan narsasi ikkinchisida boshqacha ishlardi.
 *
 * KO'RINISHGA XOS nazoratlar `children` orqali beriladi — panelning
 * o'zi ular haqida hech narsa bilmaydi.
 *
 * FILTR SERVERDA. Bu panel faqat qiymat yig'adi; mijoz tomonida
 * hech narsa filtrlanmaydi. Sabab o'lchangan: navbat 455, sahifa
 * 100 — mijoz tomonida filtrlash ikkinchi yuzlikdagi tenderni
 * "topilmadi" qilib ko'rsatardi.
 */
import { useEffect, useState } from 'react'

import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import type { Region } from '@/types'

import Icon from './Icon'

// Radix `Select` bo'sh satrni qiymat sifatida QABUL QILMAYDI (u
// "tanlanmagan" degani). "Hammasi" varianti maxsus belgi bilan
// yuritiladi va tashqariga bo'sh satr bo'lib chiqadi.
export const HAMMASI = '__all__'
export const filtrga = (v: string) => (v === HAMMASI ? '' : v)
export const tanlovga = (v: string) => (v === '' ? HAMMASI : v)

export const TRIGGER = 'h-9 w-auto min-w-[130px] bg-card text-body'

interface Props {
  q: string
  region: string
  regions: Region[]
  /** Faqat "Sizga mos" tenderlari. */
  katalog: boolean
  onChange: (patch: { q?: string; region?: string; katalog?: boolean }) => void
  onReset: () => void
  /** Ko'rinishga xos qo'shimcha nazoratlar. */
  children?: React.ReactNode
}

export default function NavbatFilters({
  q: qProp, region, regions, katalog, onChange, onReset, children,
}: Props) {
  const t = useT()

  // DEBOUNCE 400 ms — `Filters.tsx` dagi bilan AYNI raqam. Har
  // harfda so'rov yuborish navbat so'rovini (u `count(*)` ham
  // qiladi) daqiqada o'nlab marta urgan bo'lardi.
  const [q, setQ] = useState(qProp || '')
  useEffect(() => { setQ(qProp || '') }, [qProp])
  useEffect(() => {
    const id = setTimeout(() => { if (q !== (qProp || '')) onChange({ q }) }, 400)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="relative min-w-[220px] flex-1">
        <Icon name="search" size={15}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          className="h-9 w-full rounded-md border border-input bg-card pl-9 pr-3
                     text-base outline-none transition-colors md:text-body
                     focus-visible:border-ring focus-visible:ring-1
                     focus-visible:ring-ring placeholder:text-muted-foreground"
          type="search"
          placeholder={t('filters.searchPlaceholder')}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <Select value={tanlovga(region)}
        onValueChange={(v) => onChange({ region: filtrga(v) })}>
        <SelectTrigger className={TRIGGER}><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={HAMMASI}>{t('filters.allRegions')}</SelectItem>
          {regions.map((r) => (
            <SelectItem key={r.area_id} value={r.area_id}>
              {r.name || r.area_id}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* "SIZGA MOS" — ikkala navbatda ham SHU YERDA va SHU
          KO'RINISHDA. Komponent ichida turishining sababi: u ikki
          bo'limda bir xil tushuncha va uni har joyda alohida yozish
          joylashuvi hamda xulqi ajralib ketishiga olib kelardi.

          TO'PLAM SERVERDA hisoblanadi (`kodlash.mos_tender_idlari`)
          — ya'ni "Sizga mos" ro'yxatining O'ZI bilan bir xil. Mijoz
          tomonida hisoblash ikkinchi haqiqat yasardi va bu loyihada
          aynan shu sinf bir necha marta takrorlangan. */}
      <Button
        variant={katalog ? 'default' : 'outline'} size="sm"
        onClick={() => onChange({ katalog: !katalog })}>
        <Icon name="box" size={14} className="mr-1" />
        {t('navbat.catalogOnly')}
      </Button>

      {children}

      <Button variant="ghost" size="sm" onClick={onReset}>
        {t('common.clear')}
      </Button>
    </div>
  )
}

/**
 * "N tadan M ko'rsatildi" — KESILGANI JIM QOLMASIN.
 *
 * O'LCHANGAN SABAB: navbat 455 ta, sahifa esa 100 ta. Bu qatorsiz
 * foydalanuvchi ro'yxat TO'LIQ deb o'ylardi va qidirgani
 * ko'rinmasa "yo'q" degan xulosa chiqarardi — salbiy shartdan
 * olingan xulosa, bu loyihada eng qimmat xato sinfi.
 */
export function Kesildi({ jami, korsatildi }: {
  jami: number; korsatildi: number
}) {
  const t = useT()
  if (korsatildi >= jami) return null
  return (
    <p className="mb-2 text-caption text-soon-strong">
      {t('navbat.truncated', { n: korsatildi, jami })}
    </p>
  )
}
