// AI-CHAT OQIMI (SSE) — `POST /chat`
// ══════════════════════════════════
// NEGA `EventSource` EMAS (standart SSE mijozi):
//   1. U faqat GET qiladi — bizga POST kerak (savol matni tanada);
//   2. U maxsus sarlavha yubora olmaydi — CSRF tokeni (`X-CSRF-Token`)
//      o'tmaydi va `gate()` so'rovni 403 bilan rad etadi.
// Shuning uchun `fetch` + `ReadableStream` bilan qo'lda o'qiymiz.
//
// OQIM NEGA KERAK: tahlil 10-60 soniya davom etishi mumkin (hujjat
// qidiruvi, tool chaqiruvlari). Oddiy javobda foydalanuvchi bo'sh ekranga
// qarab turardi. Endi u matn paydo bo'lishini va QAYSI TOOL ishlayotganini
// ko'radi — "qora quti bo'lmasin" tamoyilining chatdagi ko'rinishi.
import { useCallback, useRef, useState } from 'react'
import { apiUrl, authHeaders, setToken } from '@/api'

/** IQTIBOS QAYERDAN kelgani.
 *
 *  `tender`           — ommaviy tender hujjati korpusi (`doc_chunk`)
 *  `chat_upload`      — foydalanuvchi SHU SUHBATGA yuklagan fayl
 *  `company_document` — kompaniyaning O'Z hujjati
 *
 *  Foydalanuvchi buni KO'RISHI kerak: "tender hujjatida shunday
 *  yozilgan" bilan "sizning litsenziyangizda shunday" bir xil
 *  vaznda emas va ularni aralashtirish noto'g'ri qarorga olib
 *  kelardi.
 *
 *  ESKI JAVOBLARDA MAYDON YO'Q — `chat_message.citations` jsonb va
 *  o'tgan qatorlar o'zgarmaydi. Shuning uchun ixtiyoriy va bo'sh
 *  bo'lsa `tender` deb o'qiladi (o'sha paytda boshqa manba yo'q edi).
 */
export type CitationManba = 'tender' | 'chat_upload' | 'company_document'

export interface Citation {
  manba_turi?: CitationManba
  /** `doc_chunk.id` yoki `yuklama_chunk.id`. */
  chunk_id?: number
  /** Tender korpusida SHART; yuklangan faylda YO'Q. */
  tender_id?: number
  /** Yuklangan fayl id si — `chat_upload` va `company_document` da. */
  yuklama_id?: string
  /** Bo'lak raqami — sahifa MA'LUM BO'LMAGANDA shu ko'rsatiladi. */
  chunk_no?: number
  /** Sahifa. FAQAT PDF da va faqat ishonchli bo'lsa; aks holda
   *  `null` — soxta sahifa raqami YASALMAYDI (§20). */
  sahifa?: number | null
  file_ref?: string | null
  file_name: string | null
  char_start: number
  char_end: number
  snippet: string
}

export interface ToolEvent {
  name: string
  status: 'start' | 'done' | 'error'
}

export interface ChatDone {
  input_tokens: number
  output_tokens: number
  cache_read: number
  cost_usd: number
  latency_ms: number
  stop_reason: string | null
  citations: Citation[]
}

/**
 * Suhbat QAYERDAN boshlangani. `eval` bu yerda ATAYLAB YO'Q:
 * uni faqat `_tests/ai_eval/run_eval.py` yozadi va server ham
 * mijozdan qabul qilmaydi.
 */
export type ChatManba = 'panel' | 'global' | 'gonogo' | 'match'

export interface ChatState {
  /** Oqib kelayotgan javob matni (markdown). */
  text: string
  /** Hozir ishlayotgan va tugagan tool'lar — tartib saqlanadi. */
  tools: ToolEvent[]
  citations: Citation[]
  streaming: boolean
  error: string | null
  /** `done` hodisasidan: token va xarajat. */
  done: ChatDone | null
  sessionId: string | null
}

const BOSH: ChatState = {
  text: '', tools: [], citations: [], streaming: false,
  error: null, done: null, sessionId: null,
}

/** SSE bloklarini ajratadi: `event: X\ndata: {...}\n\n`. */
function* parseSse(buf: string): Generator<{ event: string; data: string }> {
  for (const blok of buf.split('\n\n')) {
    if (!blok.trim()) continue
    let event = 'message'
    const data: string[] = []
    for (const line of blok.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trim())
    }
    if (data.length) yield { event, data: data.join('\n') }
  }
}

export function useChatStream() {
  const [state, setState] = useState<ChatState>(BOSH)
  const abortRef = useRef<AbortController | null>(null)

  /** Oqimni to'xtatadi (foydalanuvchi bekor qilsa yoki panel yopilsa). */
  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setState((s) => (s.streaming ? { ...s, streaming: false } : s))
  }, [])

  const reset = useCallback(() => {
    stop()
    setState(BOSH)
  }, [stop])

  /**
   * MAVJUD SESSIYANI DAVOM ETTIRADI.
   *
   * O'LCHANGAN NUQSON (2026-09-04). `sessionId` FAQAT shu hook'ning
   * state'ida yashardi. Panel yopilganda `ChatPanel` unmount bo'lardi
   * (`App.tsx` uni shartli chizadi), state yo'qolardi va keyingi
   * savol `session_id: null` bilan ketardi -- ya'ni HAR OCHILISH
   * yangi sessiya.
   *
   * Jurnalda bu shunday ko'rindi: 133 sessiyadan 131 tasida ANIQ
   * 2 xabar (1 savol + 1 javob), ayni tender bo'yicha 114 juft
   * sessiyaning 106 tasi 5 daqiqa ichida, bitta tender uchun 28 ta
   * alohida sessiya. "2 xabar/sessiya" o'lchovi FOYDALANUVCHI
   * USLUBI deb o'qilgan edi -- aslida u shu nuqsonning izi.
   *
   * `reset()` DAN FARQI: u hammasini tozalaydi (`sessionId` ni ham),
   * bu esa yangi kontekstni ochib sessiya ipini SAQLAYDI.
   */
  const davom = useCallback((sessionId: string | null) => {
    stop()
    setState({ ...BOSH, sessionId })
  }, [stop])

  const send = useCallback(async (
    message: string,
    opts: { sessionId?: string | null; tenderId?: number | null
            lang?: string; manba?: ChatManba } = {},
  ) => {
    stop()
    const ac = new AbortController()
    abortRef.current = ac
    setState((s) => ({
      ...BOSH, streaming: true,
      sessionId: opts.sessionId ?? s.sessionId,
    }))

    try {
      const res = await fetch(apiUrl('/chat'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          message,
          session_id: opts.sessionId ?? null,
          tender_id: opts.tenderId ?? null,
          lang: opts.lang ?? null,
          // MANBA -- faqat YANGI sessiya ochilganda ma'noga ega
          // (server `session_id` bo'lsa uni o'qimaydi). Belgisiz
          // sessiya o'lchovda "noma'lum" bo'lib qoladi.
          manba: opts.manba ?? null,
        }),
        signal: ac.signal,
      })

      if (!res.ok) {
        // 401 — sessiya tugadi: ilovaning qolgan qismi bilan bir xil
        // xatti-harakat (`api.ts` request() ham shunday qiladi).
        if (res.status === 401) setToken(null)
        let detail = `${res.status}`
        try {
          const b = await res.json()
          detail = (typeof b.detail === 'string' ? b.detail : null) || detail
        } catch { /* JSON emas */ }
        setState((s) => ({ ...s, streaming: false, error: detail }))
        return
      }
      if (!res.body) {
        setState((s) => ({ ...s, streaming: false, error: 'Oqim ochilmadi.' }))
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      // TO'LIQ BO'LMAGAN blok keyingi bo'lakka qo'shiladi: tarmoq paketi
      // `\n\n` chegarasida uzilishi mumkin va yarim JSON parse xatosi berardi.
      let buf = ''

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const oxirgi = buf.lastIndexOf('\n\n')
        if (oxirgi < 0) continue
        const toliq = buf.slice(0, oxirgi)
        buf = buf.slice(oxirgi + 2)

        for (const { event, data } of parseSse(toliq)) {
          let d: Record<string, unknown>
          try { d = JSON.parse(data) } catch { continue }

          setState((s) => {
            switch (event) {
              case 'meta':
                return { ...s, sessionId: String(d.session_id ?? s.sessionId) }
              case 'token':
                return { ...s, text: s.text + String(d.text ?? '') }
              case 'tool': {
                const name = String(d.name)
                const status = String(d.status) as ToolEvent['status']
                const bor = s.tools.findIndex((t) => t.name === name && t.status === 'start')
                // Tugagan tool YANGI qator qo'shmaydi — mavjudining
                // holatini yangilaydi, aks holda ro'yxat ikkilanardi.
                if (status !== 'start' && bor >= 0) {
                  const tools = s.tools.slice()
                  tools[bor] = { name, status }
                  return { ...s, tools }
                }
                return { ...s, tools: [...s.tools, { name, status }] }
              }
              case 'citation': {
                const c = d as unknown as Citation
                // Bir xil iqtibos ikki marta kelishi mumkin (bir necha
                // tool chaqiruvi) — takrorlamaymiz.
                const kalit = `${c.tender_id}:${c.file_ref}:${c.char_start}`
                if (s.citations.some(
                  (x) => `${x.tender_id}:${x.file_ref}:${x.char_start}` === kalit)) return s
                return { ...s, citations: [...s.citations, c] }
              }
              case 'done':
                return {
                  ...s, streaming: false,
                  done: d as unknown as ChatDone,
                  citations: (d.citations as Citation[] | undefined) ?? s.citations,
                }
              case 'error':
                // Xato oqimni TUGATADI, lekin allaqachon kelgan matn
                // SAQLANADI: yarim javob ham foydali bo'lishi mumkin.
                return { ...s, streaming: false, error: String(d.message ?? 'Xato') }
              default:
                return s
            }
          })
        }
      }
      setState((s) => (s.streaming ? { ...s, streaming: false } : s))
    } catch (e) {
      // Bekor qilish XATO EMAS — foydalanuvchining o'z harakati.
      if ((e as Error)?.name === 'AbortError') return
      setState((s) => ({ ...s, streaming: false, error: (e as Error).message }))
    } finally {
      abortRef.current = null
    }
  }, [stop])

  return { state, send, stop, reset, davom }
}
