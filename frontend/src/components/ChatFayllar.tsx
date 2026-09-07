/**
 * CHATGA BIRIKTIRILGAN FAYLLAR — tanlash, holat, olib tashlash.
 *
 * ALOHIDA KOMPONENT: `ChatPanel` allaqachon 600 qatordan oshgan va
 * biriktirma o'z holat mashinasiga ega (yuklanmoqda -> ishlanmoqda ->
 * tayyor / xato). Ikkalasini bitta faylga qo'shish ularni bir-biriga
 * bog'lab qo'yardi.
 *
 * "TAYYOR" HAQIQATNI BILDIRADI. Holat serverdan keladi va u faqat
 * matn HAQIQATAN ajratilganda `tayyor` bo'ladi — bazada CHECK bilan
 * ham qulflangan. Ya'ni bu yerdagi "Tayyor" yorlig'i "AI bu fayldan
 * javob bera oladi" degani, "yuklandi" degani EMAS (§17).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/api'
import Icon from './Icon'
import { useT } from '@/i18n'
import type { ChatFayl, FaylHolatKod } from '@/types'

/** Server bilan AYNI chegara (`api/saqlash.py:MAX_UPLOAD_MB`). */
const MAX_UPLOAD_MB = 25
const QABUL_QILINADI = '.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,.zip'

/** Server bilan AYNI (`api/yuklama.py:CHAT_MAX_FAYL`). */
const MAX_FAYL = 5

/** Holat -> ko'rinish. `yuklandi` va `ajratilmoqda` FOYDALANUVCHI
 *  UCHUN bir xil: ikkalasida ham u kutadi va hech nima qila olmaydi.
 *  Ularni ajratib ko'rsatish ichki mexanikani oshkor qilardi. */
const HOLAT: Record<FaylHolatKod, { kalit: 'chat.fileProcessing' | 'chat.fileReady'
                                    cls: string }> = {
  yuklandi:              { kalit: 'chat.fileProcessing', cls: 'text-muted-foreground' },
  ajratilmoqda:          { kalit: 'chat.fileProcessing', cls: 'text-muted-foreground' },
  tayyor:                { kalit: 'chat.fileReady',      cls: 'text-ok-strong' },
  oqilmadi:              { kalit: 'chat.fileReady',      cls: 'text-urgent-strong' },
  qollab_quvvatlanmaydi: { kalit: 'chat.fileReady',      cls: 'text-urgent-strong' },
  yiqildi:               { kalit: 'chat.fileReady',      cls: 'text-urgent-strong' },
}

const XATOLI: FaylHolatKod[] = ['oqilmadi', 'qollab_quvvatlanmaydi', 'yiqildi']
const KUTMOQDA: FaylHolatKod[] = ['yuklandi', 'ajratilmoqda']

interface Props {
  /** `null` — sessiya hali yo'q; biriktirishda YARATILADI. */
  sessionId: string | null
  /** Sessiya yaratish kerak bo'lsa chaqiriladi va id qaytaradi. */
  sessiyaOch: () => Promise<string>
  /** Fayllar ro'yxati o'zgardi — `ChatPanel` savolga qo'shimcha
   *  ko'rsatma qo'shishi uchun bilishi kerak. */
  onOzgardi?: (fayllar: ChatFayl[]) => void
}

export default function ChatFayllar({ sessionId, sessiyaOch, onOzgardi }: Props) {
  const t = useT()
  const [fayllar, setFayllar] = useState<ChatFayl[]>([])
  const [yuklanmoqda, setYuklanmoqda] = useState(false)
  const [xato, setXato] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const yangila = useCallback(async (sid: string) => {
    const r = await api.chatFiles(sid)
    setFayllar(r)
    onOzgardi?.(r)
    return r
  }, [onOzgardi])

  // Sessiya o'zgarsa ro'yxatni qayta o'qiymiz (tarixdan suhbat
  // ochilganda ham biriktirmalar ko'rinishi kerak).
  useEffect(() => {
    if (!sessionId) { setFayllar([]); return }
    yangila(sessionId).catch(() => { /* ro'yxat yo'q — jim, chunki
                                        bu yordamchi ma'lumot */ })
  }, [sessionId])

  // ISHLANAYOTGAN FAYL BO'LSA SO'RAB TURAMIZ.
  //
  // Server tomondan push yo'q (SSE faqat javob oqimi uchun). 1.5 s —
  // ataylab: ajratish odatda 1-3 s oladi, tez-tez so'rash esa foyda
  // bermaydi. TAYMER FAQAT KUTILAYOTGAN FAYL BO'LSA yuradi va
  // hammasi hal bo'lgach TO'XTAYDI — aks holda ochiq panel serverga
  // abadiy so'rov yuborardi.
  useEffect(() => {
    if (!sessionId) return
    if (!fayllar.some((f) => KUTMOQDA.includes(f.holat))) return
    const id = setInterval(() => {
      yangila(sessionId).catch(() => { /* keyingi urinishda */ })
    }, 1500)
    return () => clearInterval(id)
  }, [sessionId, fayllar, yangila])

  async function tanlandi(f: File | null) {
    if (!f) return
    setXato(null)
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      // Chegara brauzerda ham — 25 MB ni yuborib rad javobini kutish
      // ma'nosiz. Server baribir o'zi tekshiradi.
      setXato(t('err.FILE_TOO_LARGE', { max_mb: MAX_UPLOAD_MB }))
      return
    }
    if (fayllar.length >= MAX_FAYL) {
      setXato(t('err.UPLOAD_QUOTA_EXCEEDED'))
      return
    }
    setYuklanmoqda(true)
    try {
      const sid = sessionId || await sessiyaOch()
      await api.chatUploadFile(sid, f)
      await yangila(sid)
    } catch (e) {
      setXato((e as Error).message)
    } finally {
      setYuklanmoqda(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function olibTashla(id: string) {
    if (!sessionId) return
    setXato(null)
    try {
      await api.chatDetachFile(sessionId, id)
      await yangila(sessionId)
    } catch (e) {
      setXato((e as Error).message)
    }
  }

  return (
    <div>
      {fayllar.length > 0 && (
        <ul className="mb-2 flex flex-col gap-1">
          {fayllar.map((f) => {
            const h = HOLAT[f.holat]
            return (
              <li key={f.id}
                className="flex items-center gap-2 rounded-md border bg-muted/40 px-2 py-1">
                <Icon name="clip" size={12} />
                <span className="min-w-0 flex-1 truncate text-caption" title={f.nom}>
                  {f.nom}
                </span>
                <span className={`shrink-0 text-micro ${h.cls}`}>
                  {/* XATO HOLATIDA SERVER SABABINI KO'RSATAMIZ.
                      "Tayyor emas" deb qoldirish foydalanuvchini
                      kutishga majbur qilardi — holbuki kutish
                      HECH NARSANI o'zgartirmaydi. */}
                  {XATOLI.includes(f.holat) ? (f.xato || t('docs.fileFailed'))
                                            : t(h.kalit)}
                </span>
                <button type="button" title={t('chat.fileRemove')}
                  className="shrink-0 opacity-60 hover:opacity-100"
                  onClick={() => olibTashla(f.id)}>
                  <Icon name="close" size={11} />
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {xato && (
        <p className="mb-1.5 text-caption text-urgent-strong">{xato}</p>
      )}

      <input ref={inputRef} type="file" className="sr-only"
        accept={QABUL_QILINADI}
        onChange={(e) => void tanlandi(e.target.files?.[0] || null)} />
      <button type="button"
        title={t('chat.attach')} aria-label={t('chat.attach')}
        disabled={yuklanmoqda || fayllar.length >= MAX_FAYL}
        onClick={() => inputRef.current?.click()}
        className="flex h-9 w-9 items-center justify-center rounded-md border
                   text-muted-foreground transition-colors hover:bg-muted
                   disabled:opacity-40">
        {yuklanmoqda ? <Icon name="refresh" size={14} />
                     : <Icon name="clip" size={14} />}
      </button>
    </div>
  )
}
