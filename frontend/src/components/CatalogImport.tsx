import { useRef, useState } from 'react'
import { apiUrl, authHeaders, errMatn } from '@/api'
import Icon from './Icon'
import { useT } from '@/i18n'
import { useFormat } from '@/format'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { ImportResult } from '@/types'

// KATALOG VA OMBOR QOLDIQLARINI IMPORT QILISH (TZ P0-4)
//
// Oqim: fayl tanlash -> AVTOMATIK DRY-RUN (bazaga yozilmaydi) -> natijani
// ko'rish -> "Tasdiqlash". Foydalanuvchi nima yozilishini OLDINDAN ko'radi.
//
// Xato hisoboti TZ talabiga muvofiq QATOR BO'YICHA: har bir xatoda fayldagi
// haqiqiy qator raqami, ustun nomi va o'zbekcha tushuntirish bor.
//
// Yuklash `fetch` bilan to'g'ridan-to'g'ri bajariladi: api.ts dagi `request()`
// JSON uchun mo'ljallangan, multipart (FormData) ni yubora olmaydi.
// SERVERDAGI `MAX_IMPORT_MB` BILAN BIR XIL BO'LISHI SHART.
//
// Bu yerdagi tekshiruv QULAYLIK uchun: fayl tarmoqqa chiqmasdan
// rad etiladi. Haqiqiy qo'riq serverda. Ikki son ajralib ketsa,
// foydalanuvchi serverda O'TADIGAN faylni yuklay olmasdi va sabab
// hech qayerda ko'rinmasdi.
//
// `deploy_test` ikkisini solishtiradi.
const MAX_MB = 50

interface CatalogImportProps {
  onImported?: () => void
  onClose?: () => void
}

export default function CatalogImport({ onImported, onClose }: CatalogImportProps) {
  const t = useT()
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)   // dry-run natijasi
  const [done, setDone] = useState<ImportResult | null>(null)       // yakuniy import natijasi
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function send(f: File, dryRun: boolean): Promise<ImportResult> {
    const fd = new FormData()
    fd.append('file', f)
    // FormData yuborilyapti, shuning uchun `api.ts` dagi `request()`
    // emas, xom `fetch`. Kimlik sarlavhasini QO'LDA qo'shamiz —
    // aks holda auth-2 darvozasi 401 qaytaradi.
    const res = await fetch(apiUrl(`/catalog/import?dry_run=${dryRun}`), {
      method: 'POST', body: fd, headers: authHeaders(),
      credentials: 'include',
    })
    const text = await res.text()
    const body = text ? JSON.parse(text) : null
    // `errMatn` — 422 dagi `detail` MASSIVini o'qiladigan matnga aylantiradi.
    if (!res.ok) throw new Error(errMatn(body?.detail) || `${res.status}: ${res.statusText}`)
    return body as ImportResult
  }

  async function pick(f?: File | null) {
    if (!f) return
    setError(null); setResult(null); setDone(null); setFile(f)
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(t('tpl.tooBig', { max: MAX_MB, size: (f.size / 1048576).toFixed(1) }))
      return
    }
    setBusy(true)
    try {
      setResult(await send(f, true))          // DRY-RUN — bazaga tegmaydi
    } catch (e) {
      setError((e as Error).message)
    } finally { setBusy(false) }
  }

  async function confirm() {
    if (!file) return
    setBusy(true); setError(null)
    try {
      const r = await send(file, false)
      setDone(r)
      setResult(null)
      onImported?.()
    } catch (e) {
      setError((e as Error).message)
    } finally { setBusy(false) }
  }

  function reset() {
    setFile(null); setResult(null); setDone(null); setError(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div className="mb-4 space-y-3">
      {/* --- Yuklash zonasi --- */}
      <div
        className={cn(
          'rounded-xl border-2 border-dashed px-5 py-6 text-center transition-colors',
          over ? 'border-primary bg-secondary' : 'border-border bg-card',
        )}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]) }}
      >
        <p className="text-body font-semibold">{t('cimp.title')}</p>
        <p className="mt-1 text-caption text-muted-foreground">{t('cimp.hint')}</p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <Button disabled={busy} onClick={() => inputRef.current?.click()}>
            <Icon name="plus" size={14} /> {t('tpl.pickFile')}
          </Button>
          <Button variant="outline" asChild>
            <a href={apiUrl('/catalog/import/template')}>
              <Icon name="download" size={14} /> {t('cimp.templateXlsx')}
            </a>
          </Button>
          <Button variant="outline" asChild>
            <a href={apiUrl('/catalog/import/template?fmt=csv')}>
              <Icon name="download" size={14} /> {t('cimp.templateCsv')}
            </a>
          </Button>
        </div>
        <input ref={inputRef} type="file" accept=".xlsx,.csv,.txt,.tsv" className="hidden"
          onChange={(e) => pick(e.target.files?.[0])} />
        {file && (
          <div className="mt-3 inline-flex items-center gap-2 rounded-md bg-muted px-2.5 py-1.5 text-caption">
            <Icon name="box" size={13} /> <b>{file.name}</b>
            <span className="text-muted-foreground">({(file.size / 1024).toFixed(0)} KB)</span>
            <button className="rounded p-0.5 hover:bg-card" aria-label={t('common.cancel')} title={t('common.cancel')} onClick={reset}>
              <Icon name="close" size={13} />
            </button>
          </div>
        )}
      </div>

      {busy && <Note>{t('tpl.checking')}</Note>}
      {error && <Note tone="err">{error}</Note>}

      {/* --- Yakuniy natija --- */}
      {done && (
        <>
          <Note tone="ok">
            {t('cimp.done', { ins: done.inserted, upd: done.updated })}
            {done.rows_error > 0 && t('tpl.doneSkipped', { n: done.rows_error })}.
          </Note>
          <div className="flex gap-2">
            <Button variant="outline" onClick={reset}>{t('tpl.uploadAgain')}</Button>
            {onClose && <Button variant="ghost" onClick={onClose}>{t('common.close')}</Button>}
          </div>
        </>
      )}

      {/* --- Dry-run natijasi --- */}
      {result && <DryRun result={result} busy={busy} onConfirm={confirm}
        onCancel={reset} onClose={onClose} />}
    </div>
  )
}

function Note({ children, tone }: { children: React.ReactNode; tone?: 'ok' | 'err' | 'warn' }) {
  return (
    <div className={cn(
      'rounded-lg border px-3 py-2 text-body',
      tone === 'ok' && 'border-ok/40 bg-ok-soft text-ok-strong',
      tone === 'err' && 'border-urgent/40 bg-urgent-soft text-urgent-strong',
      tone === 'warn' && 'border-soon/40 bg-soon-soft text-soon-strong',
      !tone && 'bg-muted text-muted-foreground',
    )}>{children}</div>
  )
}

// =============================================================================
// Dry-run hisoboti
// =============================================================================
function DryRun({ result, busy, onConfirm, onCancel, onClose }: {
  result: ImportResult
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
  onClose?: () => void
}) {
  const t = useT()
  const f = useFormat()
  const errors = result.errors || []
  const warnings = result.warnings || []
  const detected = Object.entries(result.columns?.detected || {})
  const unknown = result.columns?.unknown || []

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat n={result.rows_total} label={t('imp.totalRows')} />
        <Stat n={result.rows_ok} label={t('imp.acceptedRows')} tone="ok" />
        <Stat n={result.rows_error} label={t('imp.errorRows')} tone="bad" />
        <Stat n={result.inserted} label={t('imp.willInsert')} />
        <Stat n={result.updated} label={t('imp.willUpdate')} />
      </div>

      <Note>
        <b>{t('imp.dryRun')}</b> {t('imp.notWritten')}{' '}
        {t('imp.headerRow', { n: result.header_row })} · {(result.format || '').toLowerCase()}
      </Note>

      {/* Qaysi sarlavha qaysi maydonga tushdi */}
      {(detected.length > 0 || unknown.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {detected.map(([field, header]) => (
            <span key={field}
              className="rounded bg-secondary px-2 py-0.5 text-caption text-primary">
              <b>{field}</b> ← “{String(header)}”
            </span>
          ))}
          {unknown.map((h) => (
            <span key={h} title={t('cimp.unrecognizedTitle')}
              className="rounded bg-muted px-2 py-0.5 text-caption text-muted-foreground">
              {t('cimp.unrecognized', { h })}
            </span>
          ))}
        </div>
      )}

      {/* --- XATOLAR: qator bo'yicha (TZ P0-4 mezoni) --- */}
      {errors.length > 0 && (
        <Card className="overflow-hidden border-urgent/40">
          <div className="flex flex-wrap items-baseline gap-2 bg-urgent-soft px-3 py-2">
            <p className="text-body font-semibold text-urgent-strong">
              {t('imp.errorsTitle', { n: result.rows_error })}
            </p>
            <span className="text-caption text-urgent-strong/80">{t('imp.errorsHint')}</span>
          </div>
          <IssueTable issues={errors} tone="err" />
        </Card>
      )}

      {/* --- OGOHLANTIRISHLAR: qator qabul qilinadi --- */}
      {warnings.length > 0 && (
        <Card className="overflow-hidden border-soon/40">
          <p className="bg-soon-soft px-3 py-2 text-body font-semibold text-soon-strong"
            title={t('imp.warningsHint')}>
            {t('imp.warningsTitle', { n: warnings.length })}
          </p>
          <IssueTable issues={warnings} tone="warn" />
        </Card>
      )}

      {/* --- QABUL QILINGAN QATORLAR --- */}
      {!!result.preview?.length && (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-baseline gap-2 border-b px-3 py-2">
            <p className="text-body font-semibold">{t('cimp.previewTitle')}</p>
            {result.rows_ok > result.preview.length && (
              <span className="text-caption text-muted-foreground">
                {t('imp.firstN', { n: result.preview.length })}
              </span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-caption">
              <thead>
                <tr className="border-b text-micro text-muted-foreground">
                  <th className="w-16 p-2 text-left font-semibold">{t('imp.thRow')}</th>
                  <th className="p-2 text-left font-semibold">{t('drawer.thName')}</th>
                  <th className="p-2 text-left font-semibold">{t('cimp.thProps')}</th>
                  <th className="w-20 p-2 text-left font-semibold">{t('cimp.thUnit')}</th>
                  <th className="w-24 p-2 text-right font-semibold">{t('cimp.thStock')}</th>
                  <th className="w-28 p-2 text-right font-semibold">{t('cimp.thCost')}</th>
                </tr>
              </thead>
              <tbody>
                {result.preview.map((r) => (
                  <tr key={r.row} className="border-b border-border-soft">
                    <td className="tabular p-2 text-muted-foreground">{r.row}</td>
                    <td className="p-2">{r.name}</td>
                    <td className="p-2 text-muted-foreground">
                      {(r.keywords || []).join(' · ') || '—'}
                    </td>
                    <td className="p-2 text-muted-foreground">{r.unit || '—'}</td>
                    <td className="tabular p-2 text-right">
                      {r.stock_qty ?? <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="tabular p-2 text-right">
                      {r.cost_price != null ? f.num(r.cost_price)
                        : <span className="text-muted-foreground">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={onConfirm} disabled={busy || result.rows_ok === 0}>
          <Icon name="check" size={14} />
          {busy ? t('common.loading') : t('cimp.confirm', { n: result.rows_ok })}
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={busy}>{t('common.cancel')}</Button>
        {onClose && (
          <Button variant="ghost" onClick={onClose} disabled={busy}>{t('common.close')}</Button>
        )}
        {result.rows_ok === 0 && (
          <span className="text-caption text-urgent-strong">{t('cimp.noValidRows')}</span>
        )}
      </div>
    </div>
  )
}

function IssueTable({ issues, tone }: {
  issues: ImportResult['errors'] & object
  tone: 'err' | 'warn'
}) {
  const t = useT()
  return (
    <div className="max-h-[300px] overflow-auto">
      <table className="w-full text-caption">
        <thead className="sticky top-0 bg-card">
          <tr className="border-b text-micro text-muted-foreground">
            <th className="w-16 p-2 text-left font-semibold">{t('imp.thRow')}</th>
            <th className="w-32 p-2 text-left font-semibold">{t('imp.thColumn')}</th>
            {tone === 'err' && (
              <th className="w-36 p-2 text-left font-semibold">{t('imp.thValue')}</th>
            )}
            <th className="p-2 text-left font-semibold">
              {t(tone === 'err' ? 'imp.thError' : 'imp.thNote')}
            </th>
          </tr>
        </thead>
        <tbody>
          {(issues || []).map((e, i) => (
            <tr key={`${e.row}-${e.field}-${i}`} className="border-b border-border-soft">
              <td className="p-2">
                <span className={cn(
                  'tabular rounded px-1.5 py-0.5 font-semibold',
                  tone === 'err' ? 'bg-urgent-soft text-urgent-strong' : 'bg-soon-soft text-soon-strong',
                )}>{e.row}</span>
              </td>
              <td className="p-2 text-muted-foreground">{e.column}</td>
              {tone === 'err' && (
                <td className="p-2">
                  {e.value
                    ? <span className="rounded bg-muted px-1.5 py-0.5">{e.value}</span>
                    : <span className="text-muted-foreground">{t('imp.emptyValue')}</span>}
                </td>
              )}
              <td className="p-2">{e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Stat({ n, label, tone }: { n: number; label: string; tone?: 'ok' | 'bad' }) {
  const color = tone === 'ok' ? 'text-ok-strong' : tone === 'bad' ? 'text-urgent-strong' : 'text-foreground'
  return (
    <div className="rounded-lg border bg-card px-3 py-2 text-center">
      <div className={cn('tabular text-title font-semibold leading-tight', color)}>{n}</div>
      <div className="text-micro text-muted-foreground">{label}</div>
    </div>
  )
}
