/**
 * BROKER NAVBATI — "bu tender kimga tegishli va u nima qildi?"
 *
 * `RequirementReview` DAN FARQI: u talabni TASDIQLASH uchun. Bu esa
 * QATNASHISH QARORI uchun — broker "olindi / rad / kutilsin" deydi.
 *
 * UCHTA QOIDA INTERFEYSDA HAM AMAL QILADI
 * ═══════════════════════════════════════
 *
 * 1. QAMROV KO'RINADI. `ball = 1.000` "mukammal" deb o'qiladi,
 *    holbuki 7 mezondan 4 tasi UMUMAN o'lchanmagan bo'lishi mumkin.
 *    Shuning uchun har qatorda "o'lchandi N/7" yoziladi.
 *
 * 2. SINOV PROFILI YORLIG'I YO'QOLMAYDI. Profil o'ylab topilgan
 *    qiymatlar bilan to'ldirilgan bo'lsa, butun panel tepasida
 *    ogohlantirish turadi — aks holda raqamlar haqiqiy deb
 *    o'qilardi.
 *
 * 3. ESKIRGAN QAROR ENG TEPADA VA QIZIL. Broker allaqachon qaror
 *    bergan, lekin tahlil o'zgargan — u YOLG'ON ISHONCH bilan
 *    yuribdi. Bu navbatdagi eng shoshilinch holat.
 *
 * "OLINDI" ENDI ISH TAQSIMOTI HAM
 * ═══════════════════════════════
 * Qaror ERP da ish kartasiga aylanadi (`api/topshiriq.py`), shuning
 * uchun u bilan birga uchta narsa yuboriladi: KIMGA, qanchalik
 * SHOSHILINCH va QACHONGACHA. Ular ixtiyoriy — hodim tanlanmasa ERP
 * kartani "Taqsimlanmagan" ga qo'yadi va menejerga xabar beradi
 * (jimgina yo'qolmaydi).
 *
 * HODIM RO'YXATI — AKTORLARDAN (`/aktor`), ya'ni ERP hodimlariga
 * xaritalangan odamlardan. Xaritalanmagan aktor ham ko'rinadi:
 * uni tanlash mumkin, lekin ERP kartani biriktira olmaydi va buni
 * javobda AYTADI.
 */
import { useCallback, useEffect, useState } from 'react'

import { api } from '@/api'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { useFormat } from '@/format'
import type {
  Aktor, AiQaror, InsonQaror, MalakaNatija, MalakaHolat, NavbatFiltr,
  Region, RoutingItem, RoutingMoslik,
} from '@/types'

import Icon from './Icon'
import { DarvozaProgress } from './DarvozaProgress'
import NavbatFilters, { Kesildi, TRIGGER, filtrga, tanlovga, HAMMASI }
  from './NavbatFilters'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { Skeleton } from './ui/skeleton'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from './ui/select'

/** AI qarorining rangi. `no_go` navbatga tushmaydi, lekin to'liqlik uchun. */
const QAROR_RANG: Record<AiQaror, string> = {
  go:     'bg-ok-soft text-ok-strong border-ok/30',
  review: 'bg-soon-soft text-soon-strong border-soon/30',
  no_go:  'bg-urgent-soft text-urgent-strong border-urgent/30',
}

/** Mezon hukmi rangi. `malumot_yoq` ATAYLAB kulrang — u xato emas. */
const HOLAT_RANG: Record<MalakaHolat, string> = {
  ok:          'text-ok',
  risk:        'text-soon',
  fail:        'text-urgent',
  malumot_yoq: 'text-muted-foreground',
}

const BOSH_FILTR: NavbatFiltr = {
  q: '', region: '', holat: '', qaror: '', eskirgan: false, katalog: false,
}

export default function BrokerQueue({
  onOpenTender, regions = [],
}: {
  onOpenTender?: (tenderId: number) => void
  regions?: Region[]
}) {
  const { t } = useI18n()
  const fmt = useFormat()
  const [items, setItems] = useState<RoutingItem[]>([])
  const [filtr, setFiltr] = useState<NavbatFiltr>(BOSH_FILTR)
  // `jami` — filtrga MOS KELGANLARNING to'liq soni. Sahifa 100 ta,
  // shuning uchun u `items.length` dan katta bo'lishi mumkin.
  const [jami, setJami] = useState(0)
  const [moslik, setMoslik] = useState<RoutingMoslik | null>(null)
  const [yuklanmoqda, setYuklanmoqda] = useState(true)
  const [xato, setXato] = useState<string | null>(null)
  const [ochilgan, setOchilgan] = useState<number | null>(null)
  const [malaka, setMalaka] = useState<MalakaNatija | null>(null)
  const [malakaYuk, setMalakaYuk] = useState(false)
  const [izoh, setIzoh] = useState('')
  const [band, setBand] = useState(false)
  // --- ERP ga topshiriq: ish taqsimoti ---
  const [hodim, setHodim] = useState('')
  const [ustuvorlik, setUstuvorlik] =
    useState<'low' | 'medium' | 'high'>('medium')
  const [muddat, setMuddat] = useState('')
  const [aktorlar, setAktorlar] = useState<Aktor[]>([])
  const [erpXabar, setErpXabar] = useState<string | null>(null)

  // Aktorlar BIR MARTA: ular ish davomida o'zgarmaydi. Ro'yxat
  // bo'lmasa (patch yo'q yoki huquq yetmasa) tanlov ko'rsatilmaydi
  // va qaror avvalgidek ishlayveradi.
  useEffect(() => {
    void api.aktorlar(true)
      .then((r) => setAktorlar(r.aktorlar || []))
      .catch(() => setAktorlar([]))
  }, [])

  const yukla = useCallback(async () => {
    setYuklanmoqda(true)
    setXato(null)
    try {
      const r = await api.brokerNavbat(filtr, 100)
      setItems(r.items)
      setJami(r.jami)
      setMoslik(r.moslik)
    } catch (e) {
      setXato(e instanceof Error ? e.message : String(e))
    } finally {
      setYuklanmoqda(false)
    }
  }, [filtr])

  useEffect(() => { void yukla() }, [yukla])

  async function och(it: RoutingItem) {
    if (ochilgan === it.id) { setOchilgan(null); setMalaka(null); return }
    setOchilgan(it.id)
    setIzoh('')
    setMalaka(null)
    setMalakaYuk(true)
    try {
      // VAQT O'LCHOVI shu yerdan boshlanadi. `yopildi` yozuv qayta
      // ochilmaydi — server 404 qaytaradi va bu XATO EMAS.
      if (it.holat === 'yangi') await api.brokerOch(it.id).catch(() => null)
      setMalaka(await api.malaka(it.tender_id))
    } catch (e) {
      setXato(e instanceof Error ? e.message : String(e))
    } finally {
      setMalakaYuk(false)
    }
  }

  async function qaror(it: RoutingItem, q: InsonQaror) {
    setBand(true)
    try {
      const r = await api.brokerQaror(it.id, {
        qaror: q,
        izoh: izoh || undefined,
        // Ish taqsimoti FAQAT "olindi" da ma'noga ega.
        ...(q === 'olindi'
          ? { hodim_actor_id: hodim ? Number(hodim) : null,
              ustuvorlik, muddat: muddat || null }
          : {}),
      })
      // ERP GA NIMA BO'LGANI JIM QOLMAYDI. Uchta holat bor va
      // ular bir-biridan farq qiladi: karta ochildi / kimsasiz
      // ochildi / umuman yozilmadi.
      const tp = r.topshiriq
      if (q === 'olindi' && tp) {
        setErpXabar(tp.holat === 'yaratildi'
          ? (tp.hodim_actor_id ? t('broker.erpCard') : t('broker.erpUnassigned'))
          : `${t('broker.erpFailed')}: ${tp.xato || tp.holat}`)
      } else {
        setErpXabar(null)
      }
      setOchilgan(null)
      setMalaka(null)
      setIzoh('')
      setHodim('')
      setMuddat('')
      setUstuvorlik('medium')
      await yukla()
    } catch (e) {
      setXato(e instanceof Error ? e.message : String(e))
    } finally {
      setBand(false)
    }
  }

  async function yangila() {
    setBand(true)
    try {
      await api.brokerYangila()
      await yukla()
    } catch (e) {
      setXato(e instanceof Error ? e.message : String(e))
    } finally {
      setBand(false)
    }
  }

  const eskirgan = items.filter((x) => x.ai_ozgardi).length
  const filtrBor = !!(filtr.q || filtr.region || filtr.holat
                      || filtr.qaror || filtr.eskirgan || filtr.katalog)

  return (
    <div className="space-y-3">
      {/* SIFAT DARVOZASI — "18 / 40". Ko'ruvchi o'z ekranida
          qanchasi qolganini ko'rsin; ilgari bu raqam faqat
          `v_sifat_darvoza` da, ya'ni SQL yozadigan odam uchun
          ko'rinardi. Tugallanmagan darvoza YASHIRILMAYDI. */}
      <DarvozaProgress qatlam="yonaltirish" />
      {/* SINOV PROFILI — eng tepada va yo'qolmaydi.
          "147 ta tender navbatda" degan raqam o'ylab topilgan
          qiymatlarni o'lchaydi; yorliqsiz u haqiqiy deb o'qilardi. */}
      {moslik?.is_sample && (
        <div className="flex items-start gap-2 rounded-lg border
                        border-soon/40 bg-soon-soft px-3 py-2
                        text-caption text-soon-strong">
          <Icon name="alert" size={15} className="mt-px shrink-0" />
          <div>
            <b>{t('broker.sampleTitle')}</b> {t('broker.sampleBody')}
          </div>
        </div>
      )}

      {xato && (
        <div className="rounded-lg border border-urgent/40 bg-urgent-soft
                        px-3 py-2 text-caption text-urgent-strong">
          {xato}
        </div>
      )}

      {/* ERP GA NIMA BO'LGANI. Qaror MUVAFFAQIYATLI bo'lib, ERP
          kartasi ochilmagan bo'lishi mumkin (masalan hodim
          xaritalanmagan) — buni jimgina o'tkazib yuborish "hammasi
          joyida" degan yolg'on taassurot qoldirardi. */}
      {erpXabar && (
        <div className="flex items-start gap-2 rounded-lg border
                        border-soon/40 bg-soon-soft px-3 py-2
                        text-caption text-soon-strong">
          <span className="flex-1">{erpXabar}</span>
          <button type="button" className="underline"
                  onClick={() => setErpXabar(null)}>×</button>
        </div>
      )}

      {/* FILTR — server tomonda. Panel qidiruvni 400 ms kechiktiradi
          (`NavbatFilters`), ya'ni har harf so'rov yubormaydi. */}
      <NavbatFilters
        q={filtr.q} region={filtr.region} regions={regions}
        katalog={filtr.katalog}
        onChange={(patch) => setFiltr((f) => ({ ...f, ...patch }))}
        onReset={() => setFiltr(BOSH_FILTR)}
      >
        <Select value={tanlovga(filtr.holat)}
          onValueChange={(v) =>
            setFiltr((f) => ({ ...f, holat: filtrga(v) as NavbatFiltr['holat'] }))}>
          <SelectTrigger className={TRIGGER}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={HAMMASI}>{t('broker.f.allStates')}</SelectItem>
            <SelectItem value="yangi">{t('broker.f.new')}</SelectItem>
            <SelectItem value="korilmoqda">{t('broker.f.inProgress')}</SelectItem>
            <SelectItem value="yopildi">{t('broker.f.closed')}</SelectItem>
          </SelectContent>
        </Select>

        <Select value={tanlovga(filtr.qaror)}
          onValueChange={(v) =>
            setFiltr((f) => ({ ...f, qaror: filtrga(v) as NavbatFiltr['qaror'] }))}>
          <SelectTrigger className={TRIGGER}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={HAMMASI}>{t('broker.f.allDecisions')}</SelectItem>
            <SelectItem value="go">go</SelectItem>
            <SelectItem value="review">review</SelectItem>
            {/* `no_go` navbatga faqat `--barchasi` bilan yoziladi.
                Variant baribir turadi: yozilgan bo'lsa broker uni
                topa olishi kerak, bo'lmasa ro'yxat bo'sh chiqadi —
                bu "filtr yo'q" dan ANIQROQ javob. */}
            <SelectItem value="no_go">no_go</SelectItem>
          </SelectContent>
        </Select>

        {/* ESKIRGAN QAROR — eng shoshilinch holat, shuning uchun
            alohida tugma: broker uni bir bosishda ajratib olsin. */}
        <Button
          variant={filtr.eskirgan ? 'default' : 'outline'} size="sm"
          onClick={() => setFiltr((f) => ({ ...f, eskirgan: !f.eskirgan }))}>
          {t('broker.f.staleOnly')}
        </Button>
      </NavbatFilters>

      <Card className="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <Icon name="send" size={16} className="text-accent" />
          <div className="text-body font-medium">{t('broker.title')}</div>
          <span className="text-xs text-muted-foreground">
            {t('broker.count', { n: jami })}
          </span>
          {/* ESKIRGAN QAROR — eng shoshilinch raqam. */}
          {eskirgan > 0 && (
            <Badge className="border-urgent/30 bg-urgent-soft
                              text-urgent-strong">
              {t('broker.staleCount', { n: eskirgan })}
            </Badge>
          )}
          <Button variant="ghost" size="sm" className="ml-auto"
                  disabled={band} onClick={() => void yangila()}>
            <Icon name="refresh" size={14} className="mr-1" />
            {t('broker.refresh')}
          </Button>
        </div>

        {/* MOSLIK — o'lchanmagan bo'lsa "0%" EMAS, "o'lchanmagan". */}
        {moslik && (
          <div className="border-b bg-muted/40 px-4 py-2 text-xs
                          text-muted-foreground">
            {moslik.olchandi ? (
              <>
                {t('broker.agreement', { n: moslik.inson_qarorlari })}
                {moslik.qatorlar.map((r) => (
                  <span key={`${r.ai_manba}-${r.ai_qaror}`} className="ml-2">
                    {r.ai_qaror}:{' '}
                    {/* HISOBLANMAGAN QIYMAT O'ZINI TUSHUNTIRADI.
                        Ilgari bu yerda `{r.moslik_foiz ?? 0}%` turardi
                        va NULL ni `0%` ga aylantirardi — ya'ni
                        "o'lchanmadi" broker uchun "AI 0% da haq"
                        bo'lib ko'rinardi. `review` da bu HAR DOIM
                        shunday edi: formula unga nolni KAFOLATLAYDI. */}
                    {/* SHART SABABGA QO'YILGAN, foizga emas.
                        `moslik_foiz === null` bo'yicha tekshirilganda
                        TypeScript `foiz_yoq_sababi` ni hamon
                        `null` bo'lishi mumkin deb ko'rardi va
                        kalit `broker.noPct.null` ga aylanardi —
                        ya'ni tarjimasiz satr. Sababning o'zi
                        mavjudligini so'raymiz: shunda kalit
                        HAR DOIM haqiqiy. */}
                    {r.foiz_yoq_sababi ? (
                      <span title={t(`broker.noPct.${r.foiz_yoq_sababi}`,
                                     { n: r.jami, kerak: moslik.kerakli_qaror })}>
                        {t(`broker.noPct.${r.foiz_yoq_sababi}.short`)}
                      </span>
                    ) : (
                      <b className="tabular text-foreground">
                        {r.moslik_foiz ?? '—'}%
                      </b>
                    )}
                  </span>
                ))}
              </>
            ) : (
              // BITTA QARORDAN FOIZ CHIQMAYDI. `olchandi` false
              // bo'lsa `qatorlar` ham bo'sh keladi — server tomonda.
              <span>
                {t('broker.notMeasured')}
                {moslik.inson_qarorlari > 0 && (
                  <> {t('broker.needMore', {
                    n: moslik.inson_qarorlari,
                    kerak: moslik.kerakli_qaror })}</>
                )}
              </span>
            )}
          </div>
        )}

        {!yuklanmoqda && (
          <div className="px-4 pt-2">
            <Kesildi jami={jami} korsatildi={items.length} />
          </div>
        )}

        {yuklanmoqda ? (
          <div className="p-4">
            <Skeleton className="h-[360px] w-full rounded-lg" />
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-8 text-center text-body
                          text-muted-foreground">
            {/* BO'SH NATIJANING SABABI AYTILADI. Filtr qo'yilgan
                bo'lsa "navbat bo'sh" YOLG'ON bo'lardi — navbatda
                tender bor, faqat filtrga mos kelmagan. */}
            {filtr.katalog
              ? t('navbat.noCatalogMatch')
              : filtrBor ? t('navbat.noMatch') : t('broker.empty')}
          </div>
        ) : (
          <ul className="divide-y">
            {items.map((it) => (
              <li key={it.id} className={cn(
                'px-4 py-3',
                it.ai_ozgardi && 'bg-urgent-soft/40')}>
                <button
                  type="button"
                  className="flex w-full items-start gap-3 text-left"
                  onClick={() => void och(it)}
                >
                  <div className="min-w-0 flex-1">
                    {/* ESKIRGAN QAROR — nima o'zgargani AYNAN ko'rsatiladi.
                        "Nimadir o'zgardi" foydasiz ogohlantirish. */}
                    {it.ai_ozgardi && (
                      <div className="mb-1 flex items-center gap-1.5
                                      text-caption font-medium
                                      text-urgent-strong">
                        <Icon name="alert" size={13} />
                        {t('broker.stale', {
                          eski: it.ai_qaror_eski ?? '—',
                          yangi: it.ai_qaror ?? '—',
                          qaror: it.inson_qaror ?? '—',
                        })}
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-1.5">
                      {it.ai_qaror && (
                        <Badge className={QAROR_RANG[it.ai_qaror]}>
                          {t(`broker.decision.${it.ai_qaror}`)}
                        </Badge>
                      )}
                      {it.ai_ball != null && (
                        <span className="tabular text-micro
                                         text-muted-foreground">
                          {it.ai_ball.toFixed(2)}
                        </span>
                      )}
                      {it.inson_qaror && (
                        <Badge className="border-border bg-muted
                                          text-muted-foreground">
                          {t(`broker.human.${it.inson_qaror}`)}
                        </Badge>
                      )}
                      {/* `erp_bor` GLOBAL bayroq — "integratsiya
                          mavjudmi". `erp_ish` esa AYNAN SHU tender
                          ERP da ochilganmi. Ilgari birinchisi
                          ishlatilardi va har yopilgan qatorga
                          "ERP da bor" yozilardi. */}
                      {it.erp_ish && (
                        <span className="text-micro text-muted-foreground">
                          {t('broker.erp')}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-body">
                      {it.tender_name || `#${it.tender_id}`}
                    </div>
                    {/* SABAB qamrovni ham aytadi:
                        "3/3 mezon o'tdi, 4 ta O'LCHANMADI" */}
                    {it.ai_sabab && (
                      <div className="mt-0.5 text-caption
                                      text-muted-foreground">
                        {it.ai_sabab}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 text-right text-caption
                                  text-muted-foreground">
                    {it.kun_qoldi != null && (
                      <div className={cn('tabular',
                        it.kun_qoldi < 3 && 'font-medium text-urgent')}>
                        {t('broker.daysLeft', {
                          n: Math.max(0, Math.round(it.kun_qoldi)) })}
                      </div>
                    )}
                    {it.close_at && (
                      <div className="tabular">{fmt.dateFmt(it.close_at)}</div>
                    )}
                    {it.totalcost != null && (
                      <div className="tabular">
                        {fmt.shortMoney(it.totalcost, it.currency)}
                      </div>
                    )}
                  </div>
                </button>

                {ochilgan === it.id && (
                  <div className="mt-3 rounded-lg border bg-muted/30 p-3">
                    {malakaYuk && <Skeleton className="h-32 w-full" />}
                    {malaka && <MalakaJadval n={malaka} />}

                    {/* ISH TAQSIMOTI — faqat "Olindi" uchun ma'noli,
                        lekin oldindan to'ldiriladi: qaror bosilgach
                        yana bir oyna ochish ishni sekinlashtirardi. */}
                    {aktorlar.length > 0 && (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <label className="text-caption text-muted-foreground">
                          {t('broker.assignee')}
                        </label>
                        <select
                          className="rounded-md border bg-background px-2
                                     py-1.5 text-caption"
                          value={hodim}
                          onChange={(e) => setHodim(e.target.value)}>
                          <option value="">{t('broker.assignee.none')}</option>
                          {aktorlar.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.ism}{a.erp_user_id ? '' : ' (ERP xaritasi yo‘q)'}
                            </option>
                          ))}
                        </select>

                        <label className="text-caption text-muted-foreground">
                          {t('broker.priority')}
                        </label>
                        <select
                          className="rounded-md border bg-background px-2
                                     py-1.5 text-caption"
                          value={ustuvorlik}
                          onChange={(e) => setUstuvorlik(
                            e.target.value as 'low' | 'medium' | 'high')}>
                          <option value="low">{t('broker.priority.low')}</option>
                          <option value="medium">{t('broker.priority.medium')}</option>
                          <option value="high">{t('broker.priority.high')}</option>
                        </select>

                        <label className="text-caption text-muted-foreground">
                          {t('broker.due')}
                        </label>
                        <input type="date"
                          className="rounded-md border bg-background px-2
                                     py-1.5 text-caption"
                          value={muddat}
                          onChange={(e) => setMuddat(e.target.value)} />
                      </div>
                    )}

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <input
                        className="min-w-40 flex-1 rounded-md border
                                   bg-background px-2 py-1.5 text-caption"
                        placeholder={t('broker.notePlaceholder')}
                        value={izoh}
                        onChange={(e) => setIzoh(e.target.value)}
                      />
                      {onOpenTender && (
                        <Button variant="ghost" size="sm"
                                onClick={() => onOpenTender(it.tender_id)}>
                          <Icon name="external" size={14} className="mr-1" />
                          {t('broker.openTender')}
                        </Button>
                      )}
                      <Button size="sm" disabled={band}
                              onClick={() => void qaror(it, 'olindi')}>
                        {t('broker.human.olindi')}
                      </Button>
                      <Button variant="outline" size="sm" disabled={band}
                              onClick={() => void qaror(it, 'kutilsin')}>
                        {t('broker.human.kutilsin')}
                      </Button>
                      <Button variant="outline" size="sm" disabled={band}
                              onClick={() => void qaror(it, 'rad')}>
                        {t('broker.human.rad')}
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}


/**
 * Malaka mezonlari jadvali.
 *
 * QAMROV TEPADA: "o'lchandi 3/7" birinchi ko'rinadigan narsa
 * bo'lishi kerak, aks holda `ok` belgilari to'liq tekshiruv
 * taassurotini berardi.
 */
function MalakaJadval({ n }: { n: MalakaNatija }) {
  const { t } = useI18n()
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2
                      text-caption text-muted-foreground">
        <span>
          {t('broker.measured', {
            n: n.olchandi, jami: n.jami_mezon })}
        </span>
        <span>·</span>
        <span className="text-ok">{t('broker.okN', { n: n.ok })}</span>
        {n.risk > 0 && (
          <span className="text-soon">
            {t('broker.riskN', { n: n.risk })}
          </span>
        )}
        {n.fail > 0 && (
          <span className="text-urgent">
            {t('broker.failN', { n: n.fail })}
          </span>
        )}
        {n.profil_toldirilgan != null && (
          <>
            <span>·</span>
            <span>
              {t('broker.profile', {
                n: n.profil_toldirilgan, jami: n.profil_jami ?? 0 })}
            </span>
          </>
        )}
      </div>

      <ul className="space-y-1.5">
        {n.criteria.map((m) => (
          <li key={m.key} className="text-caption">
            <div className="flex items-start gap-2">
              <span className={cn('w-24 shrink-0 font-medium',
                                  HOLAT_RANG[m.status])}>
                {t(`broker.status.${m.status}`)}
              </span>
              <span className="w-40 shrink-0">{m.label}</span>
              <span className="min-w-0 flex-1 text-muted-foreground">
                {m.izoh}
              </span>
            </div>
            {/* DALIL — hukm QAYSI talabdan kelgani. Busiz broker
                "nega no_go?" degan savolga javob topolmasdi. */}
            {m.dalillar.length > 0 && (
              <div className="ml-26 mt-0.5 space-y-0.5 pl-2">
                {m.dalillar.slice(0, 3).map((d) => (
                  <div key={d.requirement_id}
                       className="text-micro text-muted-foreground">
                    · {d.name}
                    {d.qiymat ? `: ${d.qiymat}` : ''}
                    {/* TASDIQLANMAGAN talab — hukm kuchi past.
                        Buni yashirish yolg'on ishonch berardi. */}
                    {d.tasdiqlanmagan && (
                      <span className="ml-1 text-soon">
                        {t('broker.unconfirmed')}
                      </span>
                    )}
                  </div>
                ))}
                {m.dalillar.length > 3 && (
                  <div className="text-micro text-muted-foreground">
                    +{m.dalillar.length - 3}
                  </div>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
