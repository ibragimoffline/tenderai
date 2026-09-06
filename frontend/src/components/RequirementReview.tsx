import { useCallback, useEffect, useState } from 'react'
import { api, errMatn } from '@/api'
import Icon from './Icon'
import { DarvozaProgress } from './DarvozaProgress'
import { useT } from '@/i18n'
import { useFormat } from '@/format'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import NavbatFilters, { Kesildi, TRIGGER, filtrga, tanlovga, HAMMASI }
  from './NavbatFilters'
import type { HujjatTuri, InsonQarori, ManbaSonlari, Region, ReviewRejim,
  ReviewTezlik, Talab, TalabFiltr, TalabNavbat, TalabUsul,
  TalabXulosa, Yonaltirish } from '@/types'

// TALABLARNI TASDIQLASH (J3)
// ══════════════════════════
// NEGA BU PANEL BOR: ajratilgan talab AI natijasi, ya'ni XATO bo'lishi
// mumkin. Uni to'g'ridan-to'g'ri cheklistga ulash AI xatosini QAROR
// QATLAMIGA jimgina o'tkazadi.
//
// Misol (t7886728): model "kafolat muddati ko'rsatilmagan (shablon
// bo'sh)" deb TO'G'RI yozdi. Cheklist buni ko'r-ko'rona o'qisa —
// ARVOH BLOCKER chiqadi: "kafolat sharti bajarilmagan", holbuki shart
// umuman QO'YILMAGAN. Broker bunday ogohlantirishni bir-ikki marta
// ko'rgach BUTUN cheklistga ishonishni to'xtatadi.
//
// PANEL UCH ISHNI QILADI (ro'yxat chizish emas):
//   1. tasdiqlash / rad etish / tuzatish — navbat HARAKATLANSIN;
//   2. manbaga sakrash — tasdiqlovchi matnni KO'RMASDAN tasdiqlamasin;
//   3. ishonch va usulni AJRATIB ko'rsatish — c=0.35 va c=0.96 bir xil
//      ko'rinmasin.

/** Usul bo'yicha vizual farq — `reyestr` tasdiqlash talab qilmaydi. */
const USUL: Record<TalabUsul, { rang: string; nom: string }> = {
  reyestr: { rang: 'bg-ok-soft text-ok border-ok/30', nom: 'reyestr' },
  naqsh: { rang: 'bg-muted text-muted-foreground border-border', nom: 'naqsh' },
  llm: { rang: 'bg-accent-soft text-accent border-accent/30', nom: 'model' },
}

/** Ishonch darajasi — RAQAM YETARLI EMAS, rang ham kerak. */
function ishonchRang(c: number): string {
  if (c >= 0.85) return 'text-ok'
  if (c >= 0.60) return 'text-soon'
  return 'text-urgent'
}

interface Props {
  /** Berilsa faqat shu tender ko'rsatiladi (tender panelidan). */
  tenderId?: number | null
  /** Manbaga sakrash — hujjat matnini ochadi. */
  onOpenSource?: (fileRef: string, charStart: number) => void
  /** Hudud filtri uchun — `App` dan keladi. */
  regions?: Region[]
}

const BOSH_FILTR: TalabFiltr = {
  q: '', region: '', past: false, manba: '', otgan: false, katalog: false,
}

export default function RequirementReview({
  tenderId, onOpenSource, regions = [],
}: Props) {
  const t = useT()
  const f = useFormat()
  const [navbat, setNavbat] = useState<TalabNavbat[]>([])
  /** Ko'rik tugagach navbatga nima bo'lgani. */
  const [navbatXabar, setNavbatXabar] = useState<string | null>(null)
  const [filtr, setFiltr] = useState<TalabFiltr>(BOSH_FILTR)
  // Filtrga MOS KELGANLARNING to'liq soni (sahifa 100 ta).
  const [jami, setJami] = useState(0)
  // Har manba qancha natija berishi — variant yonida ko'rsatiladi.
  const [manbalar, setManbalar] = useState<ManbaSonlari>({ naqsh: 0, llm: 0 })
  const [tanlangan, setTanlangan] = useState<number | null>(tenderId ?? null)
  const [items, setItems] = useState<Talab[]>([])
  const [xulosa, setXulosa] = useState<TalabXulosa | null>(null)
  const [loading, setLoading] = useState(true)
  const [saqlanmoqda, setSaqlanmoqda] = useState<number | null>(null)
  const [xato, setXato] = useState<string | null>(null)
  const [tahrir, setTahrir] = useState<{ id: number; qiymat: string } | null>(null)
  const [turlar, setTurlar] = useState<HujjatTuri[]>([])
  const [tezlik, setTezlik] = useState<ReviewTezlik | null>(null)
  const [rejim, setRejim] = useState<ReviewRejim>('anchored')
  // YOPIQ rejimda ochilgan qatorlar — inson javobini yozgach ochiladi.
  const [ochilgan, setOchilgan] = useState<Set<number>>(new Set())
  const [javob, setJavob] = useState<Record<number, string>>({})

  // Lug'at BIR MARTA yuklanadi — u o'zgarmaydi.
  useEffect(() => { api.hujjatTurlari().then((r) => setTurlar(r.doc_types))
    .catch(() => {}) }, [])

  const filtrBor = !!(filtr.q || filtr.region || filtr.past
                      || filtr.manba || filtr.otgan || filtr.katalog)

  const navbatniYukla = useCallback(async () => {
    if (tenderId) return                       // tender paneli — navbat kerak emas
    try {
      const r = await api.talabNavbat(100, filtr)
      setNavbat(r.queue)
      setJami(r.jami)
      // `?? {0,0}` — ESKI SERVER qo'riqchisi. Bu maydon 2026-09-03
      // da qo'shildi; qayta yuklanmagan backend uni YUBORMAYDI va
      // `manbalar.naqsh` o'qilishi butun panelni yiqitardi. Aynan
      // shu holat bir marta yuz bergan (server `--reload`siz turgan
      // edi va yangi filtrlarni umuman ko'rmagan).
      setManbalar(r.manbalar ?? { naqsh: 0, llm: 0 })
      api.talabTezlik().then(setTezlik).catch(() => {})
      setTanlangan((oldingi) => oldingi ?? r.queue[0]?.tender_id ?? null)
    } catch (e) {
      setXato(errMatn(e))
    }
  }, [tenderId, filtr])

  const talablarniYukla = useCallback(async (id: number) => {
    setLoading(true)
    try {
      const r = await api.tenderTalablar(id)
      setItems(r.items)
      setXulosa(r.summary)
      setRejim(r.rejim)
      // Yangi tender — yopiq holat tozalanadi.
      setOchilgan(new Set())
      setJavob({})
      setXato(null)
    } catch (e) {
      setXato(errMatn(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void navbatniYukla() }, [navbatniYukla])
  useEffect(() => {
    if (tanlangan) void talablarniYukla(tanlangan)
    else setLoading(false)
  }, [tanlangan, talablarniYukla])

  /**
   * Bitta talabga INSON qarorini yozadi. Navbat SHU YERDA yangilanadi.
   *
   * Tur `InsonQarori` — `extracted` yoki `pending_review` ni bu
   * yerdan yuborib bo'lmaydi. Server ham ularni rad etadi
   * (`Literal` sxemasi), lekin xato KOMPILYATSIYADA tutilsin.
   */
  async function belgila(it: Talab, status: InsonQarori,
                         qiymat?: string, docType?: string) {
    setSaqlanmoqda(it.id)
    try {
      const r = await api.talabReview(it.id, {
        status, corrected_value: qiymat, doc_type: docType,
        // Yopiq rejimda yozilgan MUSTAQIL javob. Server tomonda
        // `COALESCE` — bir marta yozilgach o'zgarmaydi.
        blind_value: javob[it.id]?.trim() || undefined,
      })
      // Ro'yxatni JOYIDA yangilaymiz — butun sahifani qayta yuklash
      // ko'rib chiqish ritmini buzadi.
      setItems((xs) => xs.map((x) => x.id === it.id
        ? { ...x, review_status: r.review_status,
            corrected_value: qiymat ?? x.corrected_value,
            doc_type: docType ?? x.doc_type }
        : x))
      setTahrir(null)
      // Tender navbatdan CHIQDIMI — foydalanuvchi ish qilinganini
      // ko'rishi kerak (aks holda raqam o'zgarmaydi).
      // NAVBAT SERVERDA QAYTA HISOBLANDI — natija ko'rsatiladi.
      setNavbatXabar(yonaltirishMatni(r.yonaltirish))
      if (r.qolgan_kutayotgan === 0 && !tenderId) {
        setNavbat((q) => q.filter((x) => x.tender_id !== r.tender_id))
        setTanlangan(null)
        // Tender tugadi — o'lchov yangilandi.
        api.talabTezlik().then(setTezlik).catch(() => {})
      } else if (!tenderId) {
        setNavbat((q) => q.map((x) => x.tender_id === r.tender_id
          ? { ...x, kutayotgan: r.qolgan_kutayotgan } : x))
      }
      if (xulosa) {
        setXulosa({ ...xulosa, kutayotgan: r.qolgan_kutayotgan })
      }
    } catch (e) {
      setXato(errMatn(e))
    } finally {
      setSaqlanmoqda(null)
    }
  }

  async function hammasini(status: 'approved' | 'rejected') {
    if (!tanlangan) return
    setSaqlanmoqda(-1)
    try {
      const r = await api.talabReviewAll(tanlangan, status)
      setNavbatXabar(yonaltirishMatni(r.yonaltirish))
      await talablarniYukla(tanlangan)
      if (!tenderId) {
        setNavbat((q) => q.filter((x) => x.tender_id !== tanlangan))
        setTanlangan(null)
      }
    } catch (e) {
      setXato(errMatn(e))
    } finally {
      setSaqlanmoqda(null)
    }
  }

  /**
   * KO'RIK TUGAGACH NAVBATGA NIMA BO'LGANI -> matn.
   *
   * JIM QOLMASLIK QOIDASI (`BrokerQueue` dagi `erpXabar` naqshi):
   * tasdiq muvaffaqiyatli bo'lib, navbat esa yangilanmagan bo'lishi
   * MUMKIN (muddat o'tgan, malaka o'tmadi, xato). Buni jimgina
   * o'tkazib yuborish "hammasi joyida" degan yolg'on qoldirardi.
   *
   * ENG SHOSHILINCH HOLAT BIRINCHI: broker allaqachon qaror bergan
   * va tahlil o'zgargan bo'lsa, qolgan hamma narsa ikkinchi darajali.
   */
  function yonaltirishMatni(y: Yonaltirish | null): string | null {
    if (!y) return null                        // ko'rik hali tugamagan
    if (y.holat === 'xato') return `${t('req.route.failed')}: ${y.xato ?? ''}`
    if (y.inson_qarori_eskirdi) return t('req.route.stale')
    if (y.holat === 'yopiq') return t('req.route.closed')
    if (y.holat === 'tender_yoq') return t('req.route.missing')
    if (y.holat === 'no_go') {
      // IKKI XIL "no_go": navbatda YO'Q EDI va navbatdan CHIQDI.
      // Ikkinchisi brokerga ta'sir qiladi, birinchisi yo'q.
      return y.ozgardi ? t('req.route.left') : t('req.route.nogo')
    }
    const q = y.ai_qaror ?? '—'
    return y.ozgardi ? t('req.route.queued', { q })
                     : t('req.route.same', { q })
  }

  /** Bu qator hozir YOPIQmi (model javobi yashirinmi). */
  function yopiq(it: Talab): boolean {
    return rejim === 'blind'
      && it.review_status === 'pending_review'
      && !ochilgan.has(it.id)
  }

  /** Inson javobini yozgach model javobi ochiladi. */
  function ochib(it: Talab) {
    setOchilgan((s) => new Set(s).add(it.id))
  }

  const kutayotgan = items.filter((x) => x.review_status === 'pending_review')
  /** MASHINA chiqargani — inson ko'rmagan va navbatda ham emas. */
  const mashinaChiqargan = items.filter(
    (x) => x.review_status === 'extracted')

  return (
    <>
      <DarvozaProgress qatlam="talab_korigi" />
      <div className="space-y-4">
      {xato && (
        <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3
                        py-2 text-body text-urgent">{xato}</div>
      )}

      {/* KO'RIK TUGAGACH NAVBATGA NIMA BO'LGANI. Tasdiq YOZILGAN
          bo'lib navbat yangilanmagan bo'lishi mumkin — sabab shu
          yerda ochiq aytiladi (`BrokerQueue` dagi ERP xabari
          bilan bir xil naqsh). */}
      {navbatXabar && (
        <div className="flex items-start gap-2 rounded-lg border
                        border-soon/40 bg-soon-soft px-3 py-2
                        text-caption text-soon-strong">
          <span className="flex-1">{navbatXabar}</span>
          <button type="button" className="underline"
                  onClick={() => setNavbatXabar(null)}>×</button>
        </div>
      )}

      {/* --- NAVBAT ------------------------------------------------- */}
      {!tenderId && (
        <Card className="p-0">
          <div className="flex items-center gap-2 border-b px-4 py-3">
            <Icon name="clip" size={16} className="text-accent" />
            <div className="text-body font-medium">{t('req.queue.title')}</div>
            <span className="ml-auto text-xs text-muted-foreground">
              {t('req.queue.count', { n: jami })}
            </span>
          </div>
          {/* PILOT O'LCHOVI — ish davomida ko'rinib tursin.
              "Har talabni inson tasdiqlaydi" modeli ishlaydimi degan
              savolning javobi shu raqamda: mediana x navbat. */}
          {tezlik && (tezlik.olchangan_tender > 0
                      || tezlik.sutkalik_osish > 0) && (
            <div className="border-b bg-muted/40 px-4 py-2 text-xs
                            text-muted-foreground">
              {tezlik.olchangan_tender > 0 && (
                <>
                  {t('req.speed', {
                    n: tezlik.olchangan_tender,
                    med: Math.round(tezlik.mediana_sekund),
                  })}
                  {tezlik.qolgan_soat != null && (
                    <>
                      {' · '}
                      <span className={cn(
                        tezlik.qolgan_soat > 60 && 'text-urgent font-medium')}>
                        {t('req.speedLeft', {
                          soat: tezlik.qolgan_soat,
                          n: tezlik.navbatda_qolgan,
                        })}
                      </span>
                    </>
                  )}
                  {tezlik.olchangan_tender < 10 && (
                    <span className="ml-1 opacity-70">
                      {t('req.speedEarly')}
                    </span>
                  )}
                </>
              )}
              {/* NAVBAT O'SISHI. `qolgan_soat` navbat MUZLAB turganini
                  taxmin qiladi — aslida ETL soatiga ishlaydi. Agar
                  o'sish quvvatdan yuqori bo'lsa, "har talabni inson
                  tasdiqlaydi" modeli umuman ishlamaydi, va buni
                  pilotdan KEYIN emas, hozir ko'rish kerak. */}
              {tezlik.sutkalik_osish > 0 && (
                <>
                  {tezlik.olchangan_tender > 0 && ' · '}
                  {t('req.growth', { n: tezlik.sutkalik_osish })}
                  {/* SOVUQ START: birinchi kunlarda "oxirgi 24 soat"
                      butun navbatni qamrab oladi. Bu sur'at emas —
                      yorliqsiz qoldirilsa xulosa teskari chiqardi. */}
                  {!tezlik.osish_ishonchli ? (
                    <span className="ml-1 opacity-70">
                      {t('req.growthCold')}
                    </span>
                  ) : tezlik.quvvat_yetadimi != null && (
                    <span className={cn(
                      'ml-1',
                      tezlik.quvvat_yetadimi
                        ? 'text-ok'
                        : 'text-urgent font-medium')}>
                      {t(tezlik.quvvat_yetadimi
                         ? 'req.growthOk' : 'req.growthBad',
                         { q: tezlik.kunlik_quvvat ?? 0 })}
                    </span>
                  )}
                </>
              )}
            </div>
          )}
          <div className="px-4 pt-3">
            {/* FILTR SERVERDA — navbat 455, sahifa 100. Mijoz
                tomonida filtrlash ikkinchi yuzlikni KO'RMASDI. */}
            <NavbatFilters
              q={filtr.q} region={filtr.region} regions={regions}
              katalog={filtr.katalog}
              onChange={(patch) => setFiltr((f) => ({ ...f, ...patch }))}
              onReset={() => setFiltr(BOSH_FILTR)}
            >
              <Select value={tanlovga(filtr.manba)}
                onValueChange={(v) => setFiltr((f) => ({
                  ...f, manba: filtrga(v) as TalabFiltr['manba'] }))}>
                <SelectTrigger className={TRIGGER}><SelectValue /></SelectTrigger>
                <SelectContent>
                  {/* SON YONIDA, NOLI O'CHIRILGAN.
                      Bugun kutayotgan talablarning HAMMASI naqshdan
                      (LLM qatlami pullik va qulflangan), ya'ni
                      "Naqshdan" jamini o'zgartirmaydi, "Modeldan" esa
                      ro'yxatni bo'shatadi. Sonsiz ikkalasi ham BUZUQ
                      tugma bo'lib ko'rinardi — foydalanuvchi aynan
                      shuni xabar qildi. */}
                  <SelectItem value={HAMMASI}>{t('talab.f.allSources')}</SelectItem>
                  <SelectItem value="naqsh" disabled={!manbalar.naqsh}>
                    {t('talab.f.pattern')} ({manbalar.naqsh})
                  </SelectItem>
                  <SelectItem value="llm" disabled={!manbalar.llm}>
                    {t('talab.f.model')} ({manbalar.llm})
                  </SelectItem>
                </SelectContent>
              </Select>

              <Button
                variant={filtr.past ? 'default' : 'outline'} size="sm"
                onClick={() => setFiltr((f) => ({ ...f, past: !f.past }))}>
                {t('talab.f.lowOnly')}
              </Button>

              {/* MUDDATI O'TGANLAR standart holda CHIQARILGAN, lekin
                  YASHIRILMAGAN: bu tugma ularni qaytaradi. Ko'rik
                  natijasi J6 oltin to'plamiga ham ketadi va yopilgan
                  tenderning yorlig'i ham qimmatli. */}
              <Button
                variant={filtr.otgan ? 'default' : 'outline'} size="sm"
                onClick={() => setFiltr((f) => ({ ...f, otgan: !f.otgan }))}>
                {t('talab.f.expired')}
              </Button>
            </NavbatFilters>
            <Kesildi jami={jami} korsatildi={navbat.length} />
          </div>

          {navbat.length === 0 ? (
            <div className="px-4 py-6 text-center text-body text-muted-foreground">
              {/* BO'SH NATIJANING SABABI: filtr qo'yilgan bo'lsa
                  "navbat bo'sh" YOLG'ON bo'lardi. */}
              {filtr.katalog
                ? t('navbat.noCatalogMatch')
                : filtrBor ? t('navbat.noMatch') : t('req.queue.empty')}
            </div>
          ) : (
            <ul className="max-h-64 divide-y overflow-y-auto">
              {navbat.map((q) => (
                <li key={q.tender_id}>
                  <button type="button"
                    onClick={() => setTanlangan(q.tender_id)}
                    className={cn(
                      'flex w-full items-center gap-3 px-4 py-2 text-left',
                      'hover:bg-muted',
                      tanlangan === q.tender_id && 'bg-muted')}>
                    <span className="min-w-0 flex-1 truncate text-body">
                      {q.tender_name || `#${q.tender_id}`}
                    </span>
                    {q.close_at && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {f.dateFmt(q.close_at)}
                      </span>
                    )}
                    <span className="shrink-0 rounded bg-accent-soft px-1.5
                                     py-0.5 text-xs text-accent tabular-nums">
                      {q.kutayotgan}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {/* --- TALABLAR ----------------------------------------------- */}
      {loading ? (
        <Card className="space-y-2 p-4">
          <Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" />
        </Card>
      ) : !tanlangan ? null : (
        <Card className="p-0">
          <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
            <div className="text-body font-medium">{t('req.items.title')}</div>
            {rejim === 'blind' && (
              <span className="rounded border border-accent/40 bg-accent-soft
                               px-1.5 py-0.5 text-xs text-accent">
                {t('req.blindMode')}
              </span>
            )}
            {xulosa && (
              <span className="text-xs text-muted-foreground">
                {/* MASHINA CHIQARGANI ALOHIDA SANALADI.
                    Ilgari u "tasdiqlangan" ga qo'shilardi va
                    interfeys inson ko'rmagan 1 487 talabni
                    "tasdiqlangan" deb ko'rsatardi. */}
                {t('req.items.stats', {
                  jami: xulosa.jami,
                  kutayotgan: xulosa.kutayotgan ?? 0,
                  mashina: xulosa.mashina_chiqargan ?? mashinaChiqargan.length,
                  tasdiqlangan: xulosa.tasdiqlangan ?? 0,
                })}
              </span>
            )}
            {/* Yopiq rejimda ommaviy tasdiqlash YO'Q: u butun
                maqsadni bekor qiladi. */}
            {kutayotgan.length > 0 && rejim !== 'blind' && (
              <div className="ml-auto flex gap-1.5">
                <Button variant="outline" size="sm"
                  disabled={saqlanmoqda !== null}
                  onClick={() => void hammasini('approved')}>
                  {t('req.approveAll')}
                </Button>
              </div>
            )}
          </div>

          {items.length === 0 ? (
            <div className="px-4 py-6 text-center text-body text-muted-foreground">
              {t('req.items.empty')}
            </div>
          ) : (
            <ul className="divide-y">
              {items.map((it) => {
                const u = USUL[it.method]
                const band = saqlanmoqda === it.id || saqlanmoqda === -1
                // "Ko'rilgan" = INSON qaror qilgan. `extracted`
                // (reyestr) ham `pending_review` emas, lekin uni
                // ko'rilgan deb ko'rsatish aynan tuzatilgan yolg'on.
                const insonKordi = it.reviewed_by != null
                const navbatda = it.review_status === 'pending_review'
                return (
                  <li key={it.id}
                    className={cn('px-4 py-3', insonKordi && 'opacity-60')}>
                    <div className="flex flex-wrap items-center gap-2">
                      {it.is_mandatory && (
                        <span className="rounded bg-urgent-soft px-1.5 py-0.5
                                         text-xs font-medium text-urgent">
                          {t('req.mandatory')}
                        </span>
                      )}
                      <span className="min-w-0 flex-1 truncate text-body font-medium">
                        {it.name}
                      </span>
                      {/* USUL va ISHONCH — yopiq rejimda YASHIRIN:
                          "model, c=0.96, yashil" ning o'zi ham
                          anchoring beradi. */}
                      {!yopiq(it) && (
                        <>
                          <span className={cn(
                            'shrink-0 rounded border px-1.5 py-0.5',
                            'text-xs', u.rang)}>
                            {u.nom}
                          </span>
                          <span className={cn('shrink-0 text-xs tabular-nums',
                                              ishonchRang(Number(it.confidence)))}>
                            {Number(it.confidence).toFixed(2)}
                          </span>
                        </>
                      )}
                    </div>

                    {/* YOPIQ REJIM — ANCHORING ga qarshi.

                        Model javobini oldindan ko'rsatsak, inson
                        TEKSHIRMAYDI — TASDIQLAYDI: yashil qatorda ko'z
                        hujjatdan "12 oy" ni izlaydi va topadi. Agar
                        hujjatda "12 oy (ehtiyot qismlar)" va "24 oy
                        (asosiy uzellar)" bo'lsa — birinchisini topib
                        tasdiqlab ketadi, ya'ni MODEL XATOSI GROUND
                        TRUTH ga aylanadi.

                        Shuning uchun avval inson O'ZI o'qib yozadi. */}
                    {yopiq(it) ? (
                      <div className="mt-2 space-y-1.5">
                        <div className="text-xs text-muted-foreground">
                          {t('req.blindHint')}
                        </div>
                        <div className="flex items-center gap-2">
                          <input
                            value={javob[it.id] ?? ''}
                            onChange={(e) => setJavob((j) =>
                              ({ ...j, [it.id]: e.target.value }))}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') ochib(it)
                            }}
                            placeholder={t('req.blindPlaceholder')}
                            className="min-w-0 flex-1 rounded-md border
                                       bg-background px-2 py-1 text-body
                                       outline-none focus:border-accent" />
                          <Button size="sm" onClick={() => ochib(it)}>
                            {t('req.blindReveal')}
                          </Button>
                        </div>
                      </div>
                    ) : (
                    <div className="mt-1 text-body">
                      {it.blind_value && (
                        <div className="mb-1 text-xs">
                          <span className="text-muted-foreground">
                            {t('req.blindYours')}{' '}
                          </span>
                          <span className="font-medium">{it.blind_value}</span>
                        </div>
                      )}
                      {it.corrected_value ? (
                        <>
                          <span className="text-ok">{it.corrected_value}</span>
                          <span className="ml-2 text-xs text-muted-foreground
                                           line-through">
                            {String((it.attrs as { qiymat?: string })?.qiymat ?? '')}
                          </span>
                        </>
                      ) : (
                        String((it.attrs as { qiymat?: string })?.qiymat ?? '—')
                      )}
                    </div>
                    )}

                    {it.raw_snippet && !yopiq(it) && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {it.raw_snippet.slice(0, 180)}
                      </p>
                    )}

                    {/* HUJJAT TURI — faqat MAJBURIY yoki SERTIFIKAT
                        tipidagi talablarda. "Kafolat muddati 12 oy" ga
                        hujjat turi kerak emas va uni so'rash ko'rib
                        chiqishni sekinlashtiradi.

                        Bir pass — IKKI natija: J6 oltin to'plami va
                        `compliance` moslashtiruvining ground truth i.
                        Aks holda o'sha talablarni compliance uchun
                        QAYTADAN ko'rib chiqish kerak bo'lardi. */}
                    {(it.is_mandatory
                      || (it.attrs as { tur?: string })?.tur === 'sertifikat')
                      && navbatda && turlar.length > 0 && (
                      <div className="mt-2 flex items-center gap-2">
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {t('req.docType')}
                        </span>
                        <select
                          value={it.doc_type ?? ''}
                          onChange={(e) => setItems((xs) => xs.map((x) =>
                            x.id === it.id ? { ...x, doc_type: e.target.value }
                              : x))}
                          className="min-w-0 flex-1 rounded-md border
                                     bg-background px-2 py-1 text-xs outline-none
                                     focus:border-accent">
                          <option value="">{t('req.docTypeEmpty')}</option>
                          {turlar.map((d) => (
                            <option key={d.code} value={d.code}>{d.label}</option>
                          ))}
                        </select>
                      </div>
                    )}
                    {it.doc_type && !navbatda && (
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t('req.docType')}{' '}
                        {turlar.find((d) => d.code === it.doc_type)?.label
                          ?? it.doc_type}
                      </div>
                    )}

                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {/* MANBAGA SAKRASH — ko'rmasdan tasdiqlamasin */}
                      {it.file_ref && it.char_start != null && onOpenSource && (
                        <Button variant="ghost" size="sm"
                          onClick={() => onOpenSource(it.file_ref!, it.char_start!)}>
                          <Icon name="clip" size={12} />
                          <span className="ml-1">{t('req.source')}</span>
                        </Button>
                      )}
                      {yopiq(it) ? null : navbatda ? (
                        <>
                          <Button size="sm" disabled={band}
                            onClick={() => void belgila(
                              it, 'approved', undefined,
                              it.doc_type ?? undefined)}>
                            {t('req.approve')}
                          </Button>
                          <Button variant="outline" size="sm" disabled={band}
                            onClick={() => void belgila(
                              it, 'rejected', undefined,
                              it.doc_type ?? undefined)}>
                            {t('req.reject')}
                          </Button>
                          <Button variant="ghost" size="sm" disabled={band}
                            onClick={() => setTahrir({
                              id: it.id,
                              qiymat: String(
                                (it.attrs as { qiymat?: string })?.qiymat ?? ''),
                            })}>
                            {t('req.correct')}
                          </Button>
                        </>
                      ) : insonKordi ? (
                        /* INSON qarori — kim va qachon ekani ham
                           ko'rinadi. Ilgari bu yerda faqat holat
                           turardi va reyestr pozitsiyalari ham
                           "tasdiqlangan" bo'lib chiqardi. */
                        <span className="text-xs text-ok">
                          {t(`req.status.${it.review_status}` as
                             'req.status.approved')}
                          {it.reviewed_at && (
                            <span className="ml-1 text-muted-foreground">
                              · {f.dateFmt(it.reviewed_at)}
                            </span>
                          )}
                        </span>
                      ) : (
                        /* MASHINA chiqargan, INSON KO'RMAGAN.
                           Bu yorliq ATAYLAB "tasdiqlangan" demaydi. */
                        <span className="text-xs text-muted-foreground">
                          {t('req.status.extracted')}
                        </span>
                      )}
                    </div>

                    {tahrir?.id === it.id && (
                      <div className="mt-2 flex items-center gap-2">
                        <input
                          autoFocus
                          value={tahrir.qiymat}
                          onChange={(e) => setTahrir({
                            id: it.id, qiymat: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && tahrir.qiymat.trim()) {
                              void belgila(it, 'corrected', tahrir.qiymat.trim())
                            }
                            if (e.key === 'Escape') setTahrir(null)
                          }}
                          className="flex-1 rounded-md border bg-background px-2
                                     py-1 text-body outline-none focus:border-accent"
                          placeholder={t('req.correctHint')}
                        />
                        <Button size="sm"
                          disabled={band || !tahrir.qiymat.trim()}
                          onClick={() => void belgila(
                            it, 'corrected', tahrir.qiymat.trim(),
                            it.doc_type ?? undefined)}>
                          {t('common.save')}
                        </Button>
                        <Button variant="ghost" size="sm"
                          onClick={() => setTahrir(null)}>
                          {t('common.cancel')}
                        </Button>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      )}
    </div>
    </>
  )
}
