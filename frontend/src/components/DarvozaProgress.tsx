/**
 * SIFAT DARVOZASI — ko'ruvchi ekranida "18 / 40".
 *
 * NEGA BU KOMPONENT BOR. Darvoza raqamlari (`v_sifat_darvoza`) faqat
 * bazada va `/validatsiya/holat` javobida bor edi — ya'ni ularni
 * FAQAT SQL yozadigan odam ko'rardi. Ko'ruvchi o'z ekranida
 * "qanchasi qoldi" degan savolga javob ololmasdi va pilot
 * o'z-o'zidan to'xtab qolardi.
 *
 * IKKI QOIDA:
 *
 *   1. FAQAT ATRIBUTLANGAN qarorlar sanaladi (`aktorli`). "Ochildi",
 *      "ko'rindi", "mashina yozdi" — SANALMAYDI va bu yerda ham
 *      qo'shilmaydi. Ular alohida ko'rsatiladi, aks holda raqam
 *      shishib, darvoza yopiq bo'la turib ochiqdek ko'rinardi.
 *
 *   2. TUGALLANMAGAN DARVOZA YASHIRILMAYDI. Nol bo'lsa ham
 *      ko'rsatiladi — "0 / 40" halol, ko'rsatkichning yo'qligi esa
 *      "muammo yo'q" deb o'qilardi.
 */
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useT } from '@/i18n'
import type { ValidatsiyaQatlam } from '../types'

/** Qaysi ekran qaysi qatlamni ko'rsatadi. */
export type Qatlam = 'kod_tasdigi' | 'talab_korigi' | 'yonaltirish'

export function DarvozaProgress({ qatlam }: { qatlam: Qatlam }) {
  // MATN LUG'ATDAN. Ilgari u shu faylda QATTIQ yozilgan edi va
  // ru/en foydalanuvchi o'zbekcha ko'rardi — tarjima to'liqligi
  // `Record<TKey, string>` bilan kafolatlangan bo'lsa ham, lug'atga
  // TUSHMAGAN matn bu kafolatdan TASHQARIDA qoladi.
  const t = useT()
  const [q, setQ] = useState<ValidatsiyaQatlam | null>(null)
  const [xato, setXato] = useState<string | null>(null)

  useEffect(() => {
    let bekor = false
    api
      .validatsiyaHolat()
      .then((r) => {
        if (bekor) return
        setQ(r.qatlamlar.find((x) => x.qatlam === qatlam) ?? null)
      })
      .catch((e) => !bekor && setXato(String(e?.message ?? e)))
    return () => {
      bekor = true
    }
  }, [qatlam])

  // O'LCHOVSIZLIK YASHIRILMAYDI. Xato bo'lsa ham satr qoladi —
  // komponentning yo'qolishi "darvoza yopildi" deb o'qilardi.
  if (xato) {
    return (
      <div className="text-xs text-muted-foreground">
        {t(`gate.${qatlam}`)}: {t('gate.unreadable')}
      </div>
    )
  }
  if (!q) {
    return (
      <div className="text-xs text-muted-foreground">
        {t(`gate.${qatlam}`)}: {t('gate.loading')}
      </div>
    )
  }

  const bor = q.aktorli ?? 0
  const kerak = q.eng_kam ?? 0
  const foiz = kerak > 0 ? Math.min(100, Math.round((bor * 100) / kerak)) : 0
  const ochiq = q.holat === 'INSON_TASDIQLADI'

  return (
    <div className="flex flex-col gap-1 text-xs">
      <div className="flex items-baseline gap-2">
        <span className="text-muted-foreground">{t(`gate.${qatlam}`)}</span>
        <span
          className={ochiq ? 'font-semibold text-green-600' : 'font-semibold'}
          title={t('gate.onlyAttributed')}
        >
          {bor} / {kerak}
        </span>
        {q.tosiq ? (
          <span className="text-amber-600" title={t('gate.blocker')}>
            {q.tosiq}
          </span>
        ) : null}
      </div>
      <div
        className="h-1 w-full overflow-hidden rounded bg-muted"
        role="progressbar"
        aria-valuenow={bor}
        aria-valuemin={0}
        aria-valuemax={kerak}
        aria-label={`${t(`gate.${qatlam}`)}: ${bor} / ${kerak}`}
      >
        <div
          className={ochiq ? 'h-full bg-green-600' : 'h-full bg-primary'}
          style={{ width: `${foiz}%` }}
        />
      </div>
      {/* ATRIBUTSIZ qatorlar ALOHIDA — darvoza raqamiga QO'SHILMAYDI. */}
      {(q.anonim ?? 0) > 0 || (q.mashina ?? 0) > 0 ? (
        <div className="text-muted-foreground">
          {t('gate.notCounted', { anonim: q.anonim ?? 0,
                                  mashina: q.mashina ?? 0 })}
        </div>
      ) : null}
    </div>
  )
}
