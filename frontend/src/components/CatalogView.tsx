import { useEffect, useState } from 'react'
import { api } from '@/api'
import Icon from './Icon'
import CatalogImport from './CatalogImport'
import KodTasdiq from './KodTasdiq'
import { useFormat } from '@/format'
import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog, useConfirm } from '@/components/ui/confirm-dialog'
import { Checkbox } from '@/components/ui/checkbox'
import Pagination from './Pagination'
import { cn } from '@/lib/utils'
import type { Category, Product } from '@/types'

// Mahsulot katalogi: mijoz sotadigan mahsulot/xizmatlar. Har biriga kategoriya
// biriktiriladi -> "Sizga mos" shu katalogga qarab tenderlarni topadi.
interface CatalogViewProps {
  items: Product[]
  categories: Category[]
  loading?: boolean
  loadError?: string | null
  onChanged: () => void
  onOpenMatch: (p: Product) => void
}

const PAGE_SIZE = 50

export default function CatalogView({
  items, categories, loading = false, loadError, onChanged, onOpenMatch,
}: CatalogViewProps) {
  const t = useT()
  const f = useFormat()
  const [editing, setEditing] = useState<Product | 'new' | null>(null)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE))
  const shownItems = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  // O'chirish xatosi KO'RINISHI kerak. Ilgari `await api.deleteProduct(...)`
  // to'g'ridan-to'g'ri onClick ichida edi: rad etilgan promise jimgina yo'qolar,
  // foydalanuvchi esa "tugma ishlamayapti" deb ko'rardi.
  // BELGILANGANLAR — id TO'PLAMI, indeks EMAS.
  //
  // Indeks bo'yicha saqlash saralash yoki sahifa o'zgarganda jimgina
  // BOSHQA mahsulotni belgilab qo'yardi va o'chirish paytida buni
  // hech narsa ko'rsatmasdi.
  const [tanlangan, setTanlangan] = useState<Set<number>>(() => new Set())
  const [xabar, setXabar] = useState<string | null>(null)
  const [band, setBand] = useState(false)

  // Katalog o'zgarsa (import, o'chirish) belgilash TOZALANADI: ro'yxatda
  // yo'q id ni belgilab turish "12 ta tanlandi" degan yolg'on hisob
  // berardi.
  useEffect(() => {
    setTanlangan((oldingi) => {
      if (oldingi.size === 0) return oldingi
      const bor = new Set(items.map((p) => p.id))
      const yangi = new Set([...oldingi].filter((id) => bor.has(id)))
      return yangi.size === oldingi.size ? oldingi : yangi
    })
  }, [items])

  function belgila(id: number, on: boolean) {
    setTanlangan((oldingi) => {
      const n = new Set(oldingi)
      if (on) n.add(id); else n.delete(id)
      return n
    })
  }

  const sahifaBelgilangan = shownItems.length > 0
    && shownItems.every((p) => tanlangan.has(p.id))

  function sahifaniBelgila(on: boolean) {
    setTanlangan((oldingi) => {
      const n = new Set(oldingi)
      for (const p of shownItems) { if (on) n.add(p.id); else n.delete(p.id) }
      return n
    })
  }

  /** Ommaviy o'chirish. `hammasi` — butun katalog. */
  async function ommaviyOchir(hammasi: boolean) {
    setError(null); setXabar(null); setBand(true)
    const soralgan = hammasi ? items.length : tanlangan.size
    try {
      const r = hammasi
        ? await api.catalogBulkDelete({ hammasi: true, kutilgan: items.length })
        : await api.catalogBulkDelete({ ids: [...tanlangan] })
      setTanlangan(new Set())
      // SO'RALGAN VA BAJARILGAN BIR XIL EMAS. Id eskirgan bo'lsa server
      // uni topmaydi va JIMGINA o'tkazib yuborardi -- foydalanuvchi esa
      // hammasi o'chdi deb o'ylardi.
      setXabar(r.ochirildi === soralgan
        ? t('cat.deleted', { n: r.ochirildi })
        : t('cat.deletedPartial', { n: r.ochirildi, yoq: soralgan - r.ochirildi }))
      onChanged()
    } catch (e) {
      const kod = (e as { code?: string }).code
      // 409 — XATO EMAS, HOLAT: katalog oradan o'zgargan.
      setError(kod === 'CATALOG_COUNT_MISMATCH'
        ? t('cat.staleCount') : (e as Error).message)
      if (kod === 'CATALOG_COUNT_MISMATCH') onChanged()
    } finally {
      setBand(false)
    }
  }

  // Kod tasdiqlash ekrani ochiq bo'lgan mahsulot.
  const [kodlanadigan, setKodlanadigan] = useState<Product | null>(null)

  const confirmBulk = useConfirm<number[]>()
  const confirmClear = useConfirm<number>()
  const confirmDelete = useConfirm<Product>()
  async function remove(p: Product) {
    setError(null)
    try {
      await api.deleteProduct(p.id)
      onChanged()
    } catch (e) {
      setError(t('common.deleteFailed', { name: p.name, msg: (e as Error).message }))
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-body text-muted-foreground">
          {t('cat.lead')} {items.length > 0 && (
            <span className="ml-1 font-semibold text-foreground">
              {t('cat.count', { n: items.length.toLocaleString() })}
            </span>
          )}
        </p>
        <div className="flex gap-2">
          {/* P0-4 — Excel/CSV/Google Sheets dan ommaviy import */}
          <Button variant="outline" onClick={() => setImporting((v) => !v)}>
            <Icon name="download" size={14} /> {t('cat.import')}
          </Button>
          {/* TOZALASH — faqat katalog BO'SH EMAS bo'lganda. Bo'sh
              katalogda u hech narsa qilmaydi va tugmaning o'zi
              "bu yerda nimadir bor" degan yolg'on ishora bo'lardi. */}
          {items.length > 0 && (
            <Button variant="outline" disabled={band}
                    onClick={() => confirmClear.ask(items.length)}
                    className="text-urgent-strong hover:bg-urgent-soft">
              <Icon name="trash" size={14} /> {t('cat.clearAll')}
            </Button>
          )}
          <Button onClick={() => setEditing('new')}>
            <Icon name="plus" size={14} /> {t('cat.addProduct')}
          </Button>
        </div>
      </div>

      {importing && <CatalogImport onImported={onChanged} onClose={() => setImporting(false)} />}

      {error && (
        <div className="mb-3 rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
          {error}
        </div>
      )}

      {xabar && (
        <div className="mb-3 rounded-lg border border-ok/40 bg-ok-soft px-3 py-2 text-body text-ok-strong">
          {xabar}
        </div>
      )}

      {loadError && (
        <div className="mb-3 rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
          {t('common.errorWith', { msg: loadError })}
        </div>
      )}

      {editing && (
        <ProductForm
          product={editing === 'new' ? null : editing}
          categories={categories}
          onSaved={() => { setEditing(null); onChanged() }}
          onCancel={() => setEditing(null)}
        />
      )}

      {loading && items.length === 0 && <Skeleton className="h-56 w-full rounded-xl" />}

      {!loading && items.length === 0 && !editing && !loadError && (
        <Empty className="rounded-xl border border-dashed bg-card">
          <EmptyHeader>
            <EmptyTitle>{t('cat.empty')}</EmptyTitle>
            <EmptyDescription>{t('cat.emptyHint')}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}

      {/* OMMAVIY PANEL — faqat belgilangan BO'LSA ko'rinadi.
          Doim turgan bo'sh panel joy egallaydi va "nimadir tanlangan"
          degan yolg'on ishora beradi. */}
      {tanlangan.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border bg-secondary px-3 py-2">
          <span className="text-body font-semibold">
            {t('cat.selected', { n: tanlangan.size })}
          </span>
          <Button size="sm" variant="outline" disabled={band}
                  onClick={() => setTanlangan(new Set())}>
            {t('cat.clearSelection')}
          </Button>
          <Button size="sm" variant="outline" disabled={band}
                  onClick={() => confirmBulk.ask([...tanlangan])}
                  className="text-urgent-strong hover:bg-urgent-soft">
            <Icon name="trash" size={14} /> {t('cat.deleteSelected')}
          </Button>
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <Table className="text-body">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[44px]">
                  <Checkbox
                    checked={sahifaBelgilangan}
                    onCheckedChange={(v) => sahifaniBelgila(v === true)}
                    aria-label={t('cat.selectAll')}
                  />
                </TableHead>
                <TableHead>{t('cat.thProduct')}</TableHead>
                <TableHead className="w-[180px]">{t('cat.thCategory')}</TableHead>
                <TableHead className="w-[150px]">{t('cat.thCode')}</TableHead>
                <TableHead className="w-[140px] text-right">{t('cat.thPrice')}</TableHead>
                <TableHead className="w-[110px] text-right">{t('cat.thStock')}</TableHead>
                <TableHead className="w-[110px] text-right">{t('cat.thMatches')}</TableHead>
                <TableHead className="w-[86px] text-right">{t('cat.thActions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shownItems.map((p) => (
                <TableRow key={p.id} className="hover:bg-transparent"
                          data-tanlangan={tanlangan.has(p.id) ? 'ha' : undefined}>
                  <TableCell>
                    <Checkbox
                      checked={tanlangan.has(p.id)}
                      onCheckedChange={(v) => belgila(p.id, v === true)}
                      aria-label={`${p.name} — ${t('cat.select')}`}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{p.name}</div>
                    {p.keywords.length > 0 && (
                      <div className="text-caption text-muted-foreground">
                        {p.keywords.join(' · ')}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {catName(categories, p.category_code) ?? t('cat.noCategory')}
                  </TableCell>
                  {/* KOD — TASDIQLANGANI. `codes` bo'sh bo'lsa mahsulot
                      moslashtirishda UMUMAN qatnashmaydi va buni
                      ekran ANIQ aytishi kerak: jimgina bo'sh katak
                      "hammasi joyida" deb o'qilardi. */}
                  <TableCell>
                    {p.codes && p.codes.length > 0 ? (
                      <button
                        className="tabular text-left font-medium text-primary underline-offset-2 hover:underline"
                        onClick={() => setKodlanadigan(p)}
                        title={t('cat.codeAssign')}
                      >{p.codes.join(', ')}</button>
                    ) : (
                      <button
                        className="text-caption text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                        onClick={() => setKodlanadigan(p)}
                      >{t('cat.uncoded')}</button>
                    )}
                  </TableCell>
                  <TableCell className="tabular text-right">
                    {p.price != null ? f.money(p.price, p.currency) : '—'}
                    {p.unit ? <span className="text-muted-foreground"> /{p.unit}</span> : null}
                  </TableCell>
                  <TableCell className="tabular text-right">
                    {p.stock_qty != null
                      ? <>{p.stock_qty}<span className="text-muted-foreground"> {p.stock_unit || ''}</span></>
                      : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="tabular text-right">
                    {p.match_count == null ? (
                      <span className="text-muted-foreground" title={t('cat.matchesDeferred')}>—</span>
                    ) : p.match_count > 0 ? (
                      <button
                        className="font-semibold text-primary underline-offset-2 hover:underline"
                        onClick={() => onOpenMatch(p)}
                      >{p.match_count}</button>
                    ) : <span className="text-muted-foreground">0</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <button
                      className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      title={t('common.edit')} aria-label={`${p.name} — ${t('common.edit')}`}
                      onClick={() => setEditing(p)}
                    >
                      <Icon name="edit" size={14} />
                    </button>
                    <button
                      className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-urgent-soft hover:text-urgent-strong"
                      title={t('common.delete')} aria-label={`${p.name} — ${t('common.delete')}`}
                      onClick={() => confirmDelete.ask(p)}
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {items.length > 0 && (
        <Pagination
          page={page} totalPages={totalPages}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
        />
      )}

      {kodlanadigan && (
        <KodTasdiq
          product={kodlanadigan}
          onClose={() => setKodlanadigan(null)}
          onChanged={onChanged}
        />
      )}

      <ConfirmDialog
        {...confirmBulk.props}
        title={t('cat.confirmBulk', { n: confirmBulk.target?.length ?? 0 })}
        onConfirm={() => void ommaviyOchir(false)}
      />

      {/* TOZALASHDA SON SARLAVHADA. "Hammasini o'chirasizmi?" degan
          savol hajmni yashiradi -- 12 ta bilan 1796 ta bir xil
          ko'rinardi. */}
      <ConfirmDialog
        {...confirmClear.props}
        title={t('cat.confirmClear', { n: confirmClear.target ?? 0 })}
        description={t('cat.confirmClearBody')}
        onConfirm={() => void ommaviyOchir(true)}
      />

      <ConfirmDialog
        {...confirmDelete.props}
        title={t('common.confirmDelete', { name: confirmDelete.target?.name ?? '' })}
        onConfirm={() => confirmDelete.target && remove(confirmDelete.target)}
      />
    </div>
  )
}

function catName(tree: Category[], code: string | null): string | null {
  if (!code) return null
  for (const p of tree) {
    if (p.code === code) return p.name
    for (const c of p.children) if (c.code === code) return c.name
  }
  return code
}

// Mahsulot qo'shish/tahrirlash formasi
function ProductForm({ product, categories, onSaved, onCancel }: {
  product: Product | null
  categories: Category[]
  onSaved: () => void
  onCancel: () => void
}) {
  const t = useT()
  const editing = !!product?.id
  const [name, setName] = useState(product?.name || '')
  const [cat, setCat] = useState(product?.category_code || '')
  const [price, setPrice] = useState(product?.price != null ? String(product.price) : '')
  const [unit, setUnit] = useState(product?.unit || '')
  const [currency, setCurrency] = useState(product?.currency || 'UZS')
  const [keywords, setKeywords] = useState<string[]>(product?.keywords || [])
  const [kwInput, setKwInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  function addKw() {
    const v = kwInput.trim()
    if (v && !keywords.includes(v)) setKeywords([...keywords, v])
    setKwInput('')
  }

  async function save() {
    if (!name.trim()) { setMsg({ ok: false, text: t('cat.errNoName') }); return }
    setSaving(true); setMsg(null)
    const body = {
      name: name.trim(), category_code: cat || null, keywords,
      unit: unit || null, price: price === '' ? null : Number(price),
      currency: currency || null, notify: true,
    }
    try {
      if (editing) await api.updateProduct(product!.id, body)
      else await api.createProduct(body)
      onSaved()
    } catch (e) {
      setMsg({ ok: false, text: t('common.errorWith', { msg: (e as Error).message }) })
    }
    finally { setSaving(false) }
  }

  return (
    <Card className="mb-4 max-w-[760px] p-5">
      <h3 className="mb-4 text-title font-semibold">
        {t(editing ? 'cat.formEdit' : 'cat.formNew')}
      </h3>

      <div className="mb-4 grid gap-3 sm:grid-cols-[2fr_1fr]">
        <Label text={t('cat.fName')} note={t('cat.fNameNote')}>
          <Input value={name} onChange={(e) => setName(e.target.value)}
            placeholder={t('cat.fNamePlaceholder')} autoFocus />
        </Label>
        <Label text={t('cat.fCategory')}>
          <Select value={cat || 'none'} onValueChange={(v) => setCat(v === 'none' ? '' : v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t('common.select')}</SelectItem>
              {categories.map((p) => (
                <SelectGroup key={p.code}>
                  <SelectLabel>{p.name}</SelectLabel>
                  <SelectItem value={p.code}>{t('cat.fCategoryAll', { name: p.name })}</SelectItem>
                  {p.children.map((c) => (
                    <SelectItem key={c.code} value={c.code}>— {c.name}</SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </Label>
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Label text={t('cat.fPrice')}>
          <Input className="tabular" type="number" value={price}
            onChange={(e) => setPrice(e.target.value)} placeholder="0" />
        </Label>
        <Label text={t('cat.fCurrency')}>
          <Select value={currency} onValueChange={setCurrency}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="UZS">UZS</SelectItem>
              <SelectItem value="USD">USD</SelectItem>
            </SelectContent>
          </Select>
        </Label>
        <Label text={t('cat.fUnit')}>
          <Input value={unit} onChange={(e) => setUnit(e.target.value)}
            placeholder={t('cat.fUnitPlaceholder')} />
        </Label>
      </div>

      <details className="rounded-lg border bg-muted/20 px-3 py-2">
        <summary className="cursor-pointer select-none text-body font-medium text-muted-foreground">
          {t('cat.moreOptions')}
        </summary>
        <div className="mt-3">
          <Label text={t('cat.fKeywords')} note={t('cat.fKeywordsNote')}>
            <TagField value={keywords} input={kwInput} setInput={setKwInput} add={addKw}
              onRemove={(k) => setKeywords(keywords.filter((x) => x !== k))}
              placeholder={t('cat.fKeywordsPlaceholder')} />
          </Label>
        </div>
      </details>

      <div className="mt-5 flex items-center gap-3">
        <Button onClick={save} disabled={saving}>
          {saving ? t('common.saving') : t(editing ? 'common.update' : 'common.add')}
        </Button>
        <Button variant="ghost" onClick={onCancel}>{t('common.cancel')}</Button>
        {msg && (
          <span className={cn('text-body', msg.ok ? 'text-ok-strong' : 'text-urgent-strong')}>{msg.text}</span>
        )}
      </div>
    </Card>
  )
}

export function Label({ text, note, children }: {
  text: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-body font-semibold">{text}</span>
      {children}
      {note && <span className="mt-1 block text-micro text-muted-foreground">{note}</span>}
    </label>
  )
}

export function TagField({ value, input, setInput, add, onRemove, placeholder }: {
  value: string[]
  input: string
  setInput: (v: string) => void
  add: () => void
  onRemove: (k: string) => void
  placeholder?: string
}) {
  return (
    <div className="flex flex-wrap gap-1.5 rounded-md border border-input bg-card p-1.5">
      {value.map((k) => (
        <span key={k}
          className="inline-flex items-center gap-1 rounded-full bg-secondary py-0.5 pl-2.5 pr-1 text-caption text-primary">
          {k}
          <button className="px-0.5 text-lead leading-none" onClick={() => onRemove(k)}>×</button>
        </span>
      ))}
      <input
        className="min-w-[160px] flex-1 bg-transparent p-1 text-base md:text-body outline-none placeholder:text-muted-foreground"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        onBlur={add}
        placeholder={placeholder}
      />
    </div>
  )
}
