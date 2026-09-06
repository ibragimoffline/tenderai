import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon'
import ToolBadge from './ToolBadge'
import CitationChip from './CitationChip'
import { Button } from '@/components/ui/button'
import { useI18n, useT } from '@/i18n'
import { useChatStream } from '@/hooks/useChatStream'
import type { ChatManba, Citation } from '@/hooks/useChatStream'
import { renderMarkdown } from '@/markdown'
import { cn } from '@/lib/utils'
import { AIAssistantInterface } from '@/components/ui/ai-assistant-interface'
import { api, type ChatSession, type ChatStoredMessage } from '@/api'

// AI-CHAT PANELI
// ══════════════
// LAZY CHUNK: bu fayl `marked` + `DOMPurify` ni tortadi (~13 KB gzip).
// `App.tsx` uni `lazy()` bilan yuklaydi — chat ochilmaguncha bu kod
// umuman yuklab olinmaydi (`StatsView`/`TenderDrawer` bilan bir xil naqsh).
//
// QAMROV: panel `tenderId` bilan ochilsa — suhbat SHU TENDER kontekstida
// (server `ChatContext.tender_id` ni promptga qo'yadi va "bu tender"
// iborasi shunga bog'lanadi). Kontekstsiz ochilsa — umumiy suhbat.

/**
 * Oldingi suhbat QANCHA VAQT ichida davom ettiriladi (soat).
 *
 * Bitta joyda turadi: chegara O'LCHANMAGAN taxmin va u
 * o'lchanganda SHU YERDA o'zgaradi.
 */
const DAVOM_SOAT = 24

interface Msg {
  role: 'user' | 'assistant'
  text: string
  citations?: Citation[]
}

/**
 * Go/No-Go dan kelgan suhbat uchun TAYYOR savollar.
 *
 * STATIK — modelga yaratdirilmaydi. Sabab oddiy: to'rtta savol
 * uchun pullik chaqiruv qilish ma'nosiz va ular baribir bir xil.
 * Ro'yxat `manba` ga bog'langan, chunki savol KONTEKSTGA tegishli:
 * "nega review?" umumiy suhbatda ma'nosiz.
 */
const GONOGO_CHIPLAR = ['gonogo.chip.why', 'gonogo.chip.criteria',
                        'gonogo.chip.docs', 'gonogo.chip.improve'] as const

interface ChatPanelProps {
  /** Tender konteksti. `null` — umumiy suhbat. */
  tenderId?: number | null
  /**
   * Suhbat QAYERDAN ochilgani. Serverga YANGI sessiya ochilganda
   * uzatiladi va `chat_session.manba` ga yoziladi.
   *
   * `gonogo` bo'lsa server tizim blokiga saqlangan tahlil sharhini
   * qo'shadi — model uni QAYTA HISOBLAMAYDI (`api/tahlil.py`).
   */
  manba?: ChatManba
  onClose: () => void
  /** Iqtibos bosilganda hujjat matnini ochish. */
  onOpenCitation?: (c: Citation) => void
}

export default function ChatPanel({ tenderId, manba, onClose,
                                    onOpenCitation }: ChatPanelProps) {
  const t = useT()
  const { lang } = useI18n()
  const { state, send, stop, reset, davom } = useChatStream()
  const [savol, setSavol] = useState('')
  const [tarix, setTarix] = useState<Msg[]>([])
  const oxiriRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // --- SUHBATLAR TARIXI ---------------------------------------------
  // Backend `GET /chat/sessions` ni ANCHADAN BERI beradi, lekin
  // frontend uni HECH QACHON chaqirmagan: suhbat sahifa yangilanishi
  // bilan yo'qolardi va foydalanuvchi savolini qaytadan yozardi.
  /** Ochilganda oldingi suhbat tiklandimi (banner uchun). */
  const [davomEtdi, setDavomEtdi] = useState(false)
  /** Qaysi sessiya tiklangani — rad etilsa O'SHANGA yoziladi. */
  const [tiklangan, setTiklangan] = useState<string | null>(null)

  /**
   * "Yangi suhbat" — tiklanishni RAD ETISH.
   *
   * O'LCHOV SHU YERDA. `DAVOM_SOAT = 24` o'lchanmagan taxmin:
   * global suhbat uchun ko'p bo'lishi mumkin (ertalabki mavzu
   * kechqurun tiklanadi), tender uchun esa oz. Rad etish ulushi
   * `v_chat_tiklash` da ikki kesimda alohida sanaladi va
   * chegarani SHU raqam tuzatadi.
   *
   * Faqat TIKLANGAN suhbat rad etilishi qayd etiladi: bo'sh
   * paneldan "Yangi suhbat" bosish signal emas.
   */
  function yangiSuhbat() {
    if (tiklangan) {
      // XATO YUTILADI: o'lchov foydalanuvchi ishini to'xtatmasin.
      api.chatTiklash(tiklangan, 'rad').catch(() => {})
    }
    reset()
    setTarix([])
    setDavomEtdi(false)
    setTiklangan(null)
  }
  const [tarixOchiq, setTarixOchiq] = useState(false)
  const [seanslar, setSeanslar] = useState<ChatSession[] | null>(null)
  const [seansXato, setSeansXato] = useState<string | null>(null)

  const seanslarniYukla = useCallback(async () => {
    setSeansXato(null)
    try {
      // EVAL SESSIYALARI RO'YXATDA KO'RSATILMAYDI. Ular
      // foydalanuvchining suhbatlari EMAS, lekin haqiqiy ijarachi
      // bilan yozilgani uchun shu ro'yxatga tushadi -- o'lchandi:
      // 133 dan 122 tasi. Filtrsiz "Suhbatlar tarixi" benchmark
      // yurishining ro'yxati bo'lib qolardi.
      setSeanslar((await api.chatSessions())
        .filter((x) => x.manba !== 'eval'))
    } catch (e) {
      // XATO YUTILMAYDI: bo'sh ro'yxat va yiqilgan so'rov BOSHQA
      // holatlar va foydalanuvchi farqni ko'rishi kerak.
      setSeanslar([])
      setSeansXato((e as Error).message)
    }
  }, [])

  /** Saqlangan xabar bloklaridan matnni ajratadi. */
  function blokMatni(m: ChatStoredMessage): string {
    const c = m.content
    if (typeof c === 'string') return c
    if (!Array.isArray(c)) return ''
    return c
      .filter((b): b is { type?: string; text?: string } =>
        !!b && typeof b === 'object')
      .filter((b) => typeof b.text === 'string')
      .map((b) => b.text as string)
      .join(String.fromCharCode(10))
  }

  /** Sessiya transkriptini ekran xabarlariga aylantiradi. */
  function transkript(r: { messages: ChatStoredMessage[] }): Msg[] {
    return r.messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        role: m.role as 'user' | 'assistant',
        // XATOLI javob ham KO'RSATILADI — backend uni ataylab
        // saqlaydi, interfeys uni yashirsa sabab yo'qolardi.
        text: m.error ? `⚠ ${m.error}` : blokMatni(m),
      }))
      .filter((m) => m.text)
  }

  async function seansOch(id: string) {
    setSeansXato(null)
    try {
      const r = await api.chatHistory(id)
      // SESSIYA IPI SAQLANADI.
      //
      // NUQSON EDI: bu yerda `reset()` chaqirilardi va u
      // `sessionId` ni ham NULL qilardi. Ya'ni foydalanuvchi eski
      // suhbatni ochib savol bersa, transkript ko'rinib turgani
      // holda savol YANGI sessiyaga ketardi — model oldingi
      // xabarlarni ko'rmasdi, garchi ekranda ular turgan bo'lsa
      // ham. Ekran bilan kontekst BIR XIL narsani ko'rsatishi kerak.
      davom(id)
      setDavomEtdi(true)
      // QO'LDA OCHISH O'LCHOVGA KIRMAYDI: foydalanuvchi suhbatni
      // O'ZI tanlagan, ya'ni bu `DAVOM_SOAT` chegarasi haqida hech
      // narsa aytmaydi. Maxrajga qo'shilsa `rad_foiz` suyulardi.
      setTiklangan(null)
      setTarix(transkript(r))
      setTarixOchiq(false)
    } catch (e) {
      setSeansXato((e as Error).message)
    }
  }

  /**
   * OCHILGANDA OXIRGI SUHBATNI DAVOM ETTIRADI.
   *
   * O'LCHANGAN NUQSON (2026-09-04). `App.tsx` `ChatPanel` ni
   * SHARTLI chizadi (`chatFor !== null`), ya'ni panel yopilganda
   * unmount bo'ladi va `useChatStream` state'i — `sessionId` bilan
   * birga — yo'qoladi. Foydalanuvchi panelni qayta ochib savol
   * bersa, u YANGI sessiyaga tushardi.
   *
   * Jurnal buni aniq ko'rsatdi: 133 sessiyadan 131 tasida ANIQ
   * 2 xabar; ayni tender bo'yicha ketma-ket ochilgan 114 juft
   * sessiyaning 106 tasi 5 daqiqa ichida; `#20000509580` haqida
   * bitta foydalanuvchi IKKI xil sessiyada so'ragan.
   *
   * 24 SOAT CHEGARASI: eski suhbatni cheksiz davom ettirish ham
   * xato bo'lardi — bir hafta oldingi kontekst bugungi savolga
   * aloqasiz. Chegara ATAYLAB qo'pol: aniq raqam o'lchanmagan,
   * shuning uchun u `DAVOM_SOAT` da bitta joyda turadi.
   *
   * KONTEKST MOS KELISHI SHART: tender suhbati boshqa tenderning
   * ipiga ulanmaydi, umumiy suhbat esa faqat umumiyga.
   */
  useEffect(() => {
    let bekor = false
    setDavomEtdi(false)
    setTiklangan(null)
    setTarix([])
    reset()
    ;(async () => {
      try {
        const xs = await api.chatSessions()
        const chegara = Date.now() - DAVOM_SOAT * 3600_000
        const mos = xs.find(
          // EVAL SESSIYASI HECH QACHON TIKLANMAYDI.
          //
          // `run_eval.py` HAQIQIY ijarachi bilan yuradi
          // (`EVAL_COMPANY_ID = 2`), ya'ni uning sessiyalari shu
          // ro'yxatda turadi. Belgilamasdan tiklaganda benchmark
          // suhbati foydalanuvchining chatida ochilardi va model
          // "kafolat muddati necha oy?" degan 122 ta savolni
          // kontekst sifatida ko'rardi.
          (x) => x.manba !== 'eval'
                 && (x.tender_id ?? null) === (tenderId ?? null)
                 && Date.parse(x.updated_at) >= chegara)
        if (!mos || bekor) return
        const r = await api.chatHistory(mos.id)
        if (bekor) return
        const msgs = transkript(r)
        if (!msgs.length) return
        davom(mos.id)
        setTarix(msgs)
        setDavomEtdi(true)
        setTiklangan(mos.id)
        api.chatTiklash(mos.id, 'tiklandi').catch(() => {})
      } catch {
        // TIKLASH YIQILSA CHAT ISHLAYVERADI — yangi sessiya
        // ochiladi, bu avvalgi xulq. Xato ko'rsatilmaydi:
        // foydalanuvchi hech narsa so'ramagan edi.
      }
    })()
    return () => { bekor = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenderId])

  async function seansArxivla(id: string) {
    try {
      await api.chatArchive(id)
      setSeanslar((xs) => (xs || []).filter((x) => x.id !== id))
    } catch (e) {
      setSeansXato((e as Error).message)
    }
  }

  // Oqim tugagach javobni tarixga ko'chiramiz — shunda keyingi savol
  // ekranni tozalamaydi va suhbat ko'rinib turadi.
  useEffect(() => {
    if (state.streaming || !state.text) return
    setTarix((h) => {
      if (h.length && h[h.length - 1].role === 'assistant') return h
      return [...h, { role: 'assistant', text: state.text, citations: state.citations }]
    })
  }, [state.streaming, state.text, state.citations])

  // Yangi matn kelganda pastga suramiz.
  useEffect(() => {
    oxiriRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [state.text, tarix.length, state.tools.length])

  useEffect(() => () => stop(), [stop])   // panel yopilsa oqimni to'xtatamiz

  // MANBA RAQAMI bosilganda hujjatni ochamiz.
  //
  // Nega delegatsiya: `[3]` elementlari `dangerouslySetInnerHTML` ichida
  // yaratiladi — React ularga `onClick` bera olmaydi. Konteynerdagi
  // bitta ishlovchi hammasini qamrab oladi.
  //
  // Raqam -> massiv indeksi: server `manba_raqami` ni `ctx.citations`
  // dagi o'rni (1 dan) qilib beradi, frontend ham AYNAN shu tartibda
  // saqlaydi. Ya'ni [3] === citations[2].
  function manbaOch(e: React.MouseEvent | React.KeyboardEvent,
                    citations?: Citation[]) {
    const el = (e.target as HTMLElement | null)?.closest?.('[data-manba]')
    if (!el || !citations?.length || !onOpenCitation) return
    if ('key' in e && e.key !== 'Enter' && e.key !== ' ') return
    const n = Number(el.getAttribute('data-manba'))
    const c = Number.isFinite(n) ? citations[n - 1] : undefined
    if (!c) return          // model mavjud bo'lmagan raqam yozgan bo'lsa
    e.preventDefault()
    onOpenCitation(c)
  }

  function yubor() {
    const q = savol.trim()
    if (!q || state.streaming) return
    setTarix((h) => [...h, { role: 'user', text: q }])
    setSavol('')
    // MANBA: kirish nuqtasidan kelgani ustun. Berilmasa — panel
    // yoki global, tender konteksti bor-yo'qligiga qarab.
    void send(q, { sessionId: state.sessionId, tenderId, lang,
                   manba: manba ?? (tenderId ? 'panel' : 'global') })
    inputRef.current?.focus()
  }

  // Markdown FAQAT tugagan javoblar uchun: oqim davomida har token'da
  // qayta parse qilish sezilarli yuk beradi (o'rta serverda ham,
  // brauzerda ham) va yarim markdown baribir noto'g'ri ko'rinadi.
  const oqimHtml = useMemo(
    () => (state.streaming ? null : renderMarkdown(state.text)),
    [state.streaming, state.text],
  )

  const bosh = !tarix.length && !state.text && !state.error

  return (
    <div className="flex h-full flex-col bg-card">
      {/* --- Sarlavha va QAMROV chipi --------------------------------- */}
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <Icon name="sparkle" size={16} className="text-accent" />
        <div className="min-w-0 flex-1">
          <div className="text-body font-medium">{t('chat.title')}</div>
          {/* Foydalanuvchi chat NIMAGA qarayotganini ko'rishi kerak */}
          <div className="truncate text-xs text-muted-foreground">
            {tenderId
              ? t('chat.scope.tender', { id: tenderId })
              : t('chat.scope.global')}
          </div>
        </div>
        <Button variant="ghost" size="sm"
          aria-pressed={tarixOchiq}
          onClick={() => {
            const yangi = !tarixOchiq
            setTarixOchiq(yangi)
            if (yangi && seanslar === null) void seanslarniYukla()
          }}
          title={t('chat.history')}>
          <Icon name="checklist" size={14} />
        </Button>
        {tarix.length > 0 && (
          <Button variant="ghost" size="sm"
            onClick={yangiSuhbat}
            title={t('chat.new')}>
            <Icon name="plus" size={14} />
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onClose} title={t('common.close')}>
          <Icon name="close" size={14} />
        </Button>
      </div>

      {/* --- Suhbat ---------------------------------------------------- */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* DAVOM ETTIRISH JIM QOLMAYDI. Model oldingi xabarlarni
            ko'radi, foydalanuvchi esa buni BILISHI kerak — aks holda
            "nega u men aytmagan narsani biladi?" degan savol qoladi.
            Yonida chiqish yo'li: "Yangi suhbat" tugmasi yuqorida. */}
        {davomEtdi && (
          <div className="flex items-center gap-2 rounded-lg border border-accent/30
                          bg-accent/5 px-3 py-2 text-caption text-muted-foreground">
            <Icon name="refresh" size={13} className="shrink-0 text-accent" />
            <span className="flex-1">
              {t('chat.resumed', { n: tarix.length })}
            </span>
            <button type="button" className="underline"
              onClick={yangiSuhbat}>
              {t('chat.new')}
            </button>
          </div>
        )}
        {tarixOchiq && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">
              {t('chat.history')}
            </div>
            {seansXato && (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-caption
                            text-destructive">
                {t('chat.history.failed', { msg: seansXato })}
              </p>
            )}
            {seanslar !== null && !seanslar.length && !seansXato && (
              <p className="text-caption text-muted-foreground">
                {t('chat.history.empty')}
              </p>
            )}
            <ul className="divide-y divide-border overflow-hidden rounded-lg border">
              {(seanslar || []).map((sn) => (
                <li key={sn.id} className="flex items-center gap-1">
                  <button type="button"
                    onClick={() => void seansOch(sn.id)}
                    title={t('chat.history.open')}
                    className="min-w-0 flex-1 px-3 py-2 text-left transition-colors
                               hover:bg-accent/10">
                    <div className="truncate text-caption">
                      {sn.title || t('chat.scope.global')}
                    </div>
                    <div className="text-micro text-muted-foreground">
                      {new Date(sn.updated_at).toLocaleString()}
                      {sn.tender_id ? ` · #${sn.tender_id}` : ''}
                    </div>
                  </button>
                  <Button variant="ghost" size="sm"
                    title={t('chat.history.archive')}
                    onClick={() => void seansArxivla(sn.id)}>
                    <Icon name="trash" size={13} />
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* GO/NO-GO CHIPLARI — tahlildan kelgan suhbat uchun.
            Bo'sh chat "nima so'rasam bo'ladi?" degan savol bilan
            boshlanadi; bu yerda javob ma'lum, chunki foydalanuvchi
            endigina hukmni ko'rdi. Chip bosilishi ODDIY xabar
            bo'lib ketadi — alohida yo'l yo'q. */}
        {bosh && !tarixOchiq && manba === 'gonogo' && (
          <div className="flex flex-wrap gap-1.5">
            {GONOGO_CHIPLAR.map((k) => (
              <button key={k} type="button"
                className="rounded-full border border-accent/40 bg-accent/5
                           px-3 py-1 text-caption transition-colors
                           hover:bg-accent/10"
                onClick={() => { setSavol(t(k)); inputRef.current?.focus() }}>
                {t(k)}
              </button>
            ))}
          </div>
        )}

        {bosh && !tarixOchiq && manba !== 'gonogo' && (
          <AIAssistantInterface tenderId={tenderId} onPick={(m) => {
            setSavol(m)
            inputRef.current?.focus()
          }} />
        )}

        {tarix.map((m, i) => (
          <div key={i} className={cn('text-body', m.role === 'user' && 'flex justify-end')}>
            {m.role === 'user' ? (
              <div className="max-w-[85%] rounded-lg bg-muted px-3 py-2">{m.text}</div>
            ) : (
              <>
                <div className="chat-markdown"
                  onClick={(e) => manbaOch(e, m.citations)}
                  onKeyDown={(e) => manbaOch(e, m.citations)}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
                {!!m.citations?.length && (
                  /* ATAYLAB "iqtibos" EMAS, "topilgan bo'laklar".
                     Bular RETRIEVAL natijasi — model qaysi biriga
                     tayanganini bildirmaydi. Jonli evalda o'lchandi:
                     A5 holatida model to'g'ri raqam aytdi, lekin
                     BOSHQA bandga tayangan edi va bo'laklar ro'yxati
                     buni ko'rsatmasdi. "Manba" deb nomlash
                     foydalanuvchini chalg'itadi. */
                  <div className="mt-2">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      {t('chat.sources.title')}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {m.citations.map((c, j) => (
                        <CitationChip key={j} citation={c} index={j} onOpen={onOpenCitation} />
                      ))}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground/80">
                      {t('chat.sources.hint')}
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
        ))}

        {/* --- Ishlayotgan tool'lar --------------------------------- */}
        {!!state.tools.length && (
          <div className="flex flex-wrap gap-1.5">
            {state.tools.map((tl, i) => <ToolBadge key={i} tool={tl} />)}
          </div>
        )}

        {/* --- Oqib kelayotgan javob -------------------------------- */}
        {state.text && !tarix.some((m) => m.role === 'assistant' && m.text === state.text) && (
          <div className="text-body">
            {state.streaming
              // Oqim davomida XOM MATN: markdown hali to'liq emas.
              ? <div className="whitespace-pre-wrap">{state.text}</div>
              : <div className="chat-markdown"
                  onClick={(e) => manbaOch(e, state.citations)}
                  onKeyDown={(e) => manbaOch(e, state.citations)}
                  dangerouslySetInnerHTML={{ __html: oqimHtml ?? '' }} />}
          </div>
        )}

        {state.streaming && !state.text && !state.tools.length && (
          <div className="flex items-center gap-2 text-body text-muted-foreground"
            role="status" aria-live="polite">
            <Icon name="sparkle" size={14} />
            {t('chat.thinking')}
          </div>
        )}

        {state.error && (
          <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2
                          text-body text-urgent">
            {state.error}
          </div>
        )}

        {/* Xarajat — chat HAR SAVOLDA pul sarflaydi, buni yashirmaymiz */}
        {state.done && (
          <div className="text-xs text-muted-foreground">
            {t('chat.cost', {
              tokens: state.done.input_tokens + state.done.output_tokens,
              usd: state.done.cost_usd.toFixed(4),
              sec: (state.done.latency_ms / 1000).toFixed(1),
            })}
          </div>
        )}
        <div ref={oxiriRef} />
      </div>

      {/* --- Savol maydoni --------------------------------------------- */}
      <div className="border-t p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={savol}
            onChange={(e) => setSavol(e.target.value)}
            onKeyDown={(e) => {
              // Enter = yuborish, Shift+Enter = yangi qator.
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); yubor() }
            }}
            rows={2}
            placeholder={t('chat.placeholder')}
            disabled={state.streaming}
            className="min-h-[2.5rem] flex-1 resize-none rounded-md border bg-background
                       px-3 py-2 text-body outline-none focus:border-accent
                       disabled:opacity-60"
          />
          {state.streaming ? (
            <Button variant="outline" onClick={stop} title={t('chat.stop')}>
              <Icon name="close" size={14} />
            </Button>
          ) : (
            <Button onClick={yubor} disabled={!savol.trim()} title={t('chat.send')}>
              <Icon name="send" size={14} />
            </Button>
          )}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">{t('chat.disclaimer')}</p>
      </div>
    </div>
  )
}
