import { useEffect, useRef, useState } from 'react'
import { api, faylniYuklabOl } from '@/api'
import Icon from './Icon'
import DocumentTemplate from './DocumentTemplate'
import { useT } from '@/i18n'
import type { TKey } from '@/i18n'
import { Label } from './CatalogView'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog, useConfirm } from '@/components/ui/confirm-dialog'
import { cn } from '@/lib/utils'
import type { CompanyDocument, DocumentType } from '@/types'

// KOMPANIYA HUJJATLARI (TZ P0-8) — akkaunt sahifasidagi bo'lim.
//
// TZ P0-8 qabul mezoni AYNAN ikki band:
//     [ ] Tender talablaridan kelib chiqadigan majburiy hujjatlar ro'yxati.
//     [ ] Har bir band bo'yicha "kompaniya bazasida bor / yo'q" belgisi.
// Foydalanuvchi hikoyasi: "majburiy hujjatlar cheklistini «bazada bor / yo'q»
// belgisi bilan ko'rishni xohlayman, muhim narsani ilova qilishni unutmaslik
// uchun."
//
// SHUNING UCHUN BU BO'LIM — JADVAL EMAS, CHEKLIST. Oddiy jadval faqat
// KIRITILGAN hujjatlarni ko'rsatardi, ya'ni eng muhim ma'lumot — YETISHMAYOTGAN
// hujjat — umuman ko'rinmasdi. Cheklistda ro'yxat MAJBURIY TURLARdan
// boshlanadi, hujjat esa bandning ichiga tushadi.
//
// Tender panelidagi cheklist (CompliancePanel) bilan BIR XIL TILDA gapiradi:
// o'sha belgilar (✓ ! ×), o'sha atamalar ("Bazada bor" / "Bazada yo'q"),
// o'sha "Nega kerak?" dalili. Ikki ekranda ikki xil atama bo'lsa, broker
// ularni boshqa-boshqa narsa deb o'ylardi.
//
// FARQ: bu yerda TENDER yo'q, shuning uchun "nega kerak" dalili tender
// matnidan emas — turning kanonik izohidan (`hint`) olinadi. Bazaviy turlar
// (`base`) deyarli har tenderda so'raladi, qolganlari tenderga qarab.
//
// FAYL YUKLASH BOR (2026-09-06 dan). `file_ref` matn maydoni ESKI
// qatorlar uchun qoldi va formada KO'RSATILMAYDI: unga mahalliy yo'l
// yozilardi va u brauzerda ochilmasdi.
//
// `MAX_UPLOAD_MB` server bilan AYNI bo'lishi shart (`api/saqlash.py`).
// Ikki joyda turgani yoqimsiz, lekin brauzer chegarani BILISHI kerak:
// 25 MB ni yuborib keyin rad javobini kutish ma'nosiz. Server baribir
// o'zi tekshiradi — bu qulaylik, himoya EMAS.
const MAX_UPLOAD_MB = 25

// `accept` — QULAYLIK. Foydalanuvchi dialogda faqat mos fayllarni
// ko'radi, lekin uni chetlab o'tish oson va server HAR DOIM o'zi
// tekshiradi (kengaytma + magic bayt).
const QABUL_QILINADI = '.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,.zip'
const STATUS: Record<ItemStatus, { mark: string; text: TKey; cls: string }> = {
  ok: { mark: '✓', text: 'compliance.status.ok', cls: 'bg-ok-soft text-ok-strong' },
  expiring_soon: {
    mark: '!', text: 'compliance.status.expiring_soon', cls: 'bg-soon-soft text-soon-strong',
  },
  expired: { mark: '×', text: 'compliance.status.expired', cls: 'bg-urgent-soft text-urgent-strong' },
  missing: { mark: '×', text: 'compliance.status.missing', cls: 'bg-urgent-soft text-urgent-strong' },
}

type ItemStatus = CompanyDocument['status'] | 'missing'

//: Bandning holati — o'sha turdagi ENG YAROQLI hujjat bo'yicha. Kompaniyada
//: eski va yangilangan nusxa birga turishi mumkin; eskisi tufayli butun band
//: "muddati tugagan" bo'lib qolmasin (server tomonda compliance._pick_best()).
const RANK: Record<ItemStatus, number> = {
  ok: 0, expiring_soon: 1, expired: 2, missing: 3,
}

const dateFmt = (iso?: string | null) => (iso ? iso.split('-').reverse().join('.') : '—')

const itemStatus = (list?: CompanyDocument[]): ItemStatus =>
  !list?.length ? 'missing'
    : list.reduce<ItemStatus>((a, d) => (RANK[d.status] < RANK[a] ? d.status : a), 'missing')

export default function CompanyDocuments({ focusType }: { focusType?: string | null }) {
  const t = useT()
  const [docs, setDocs] = useState<CompanyDocument[]>([])
  const [types, setTypes] = useState<DocumentType[] | null>(null)
  const [editing, setEditing] = useState<CompanyDocument | 'new' | { doc_type: string } | null>(null)
  const [template, setTemplate] = useState(false)
  const [showExtra, setShowExtra] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function load() {
    setError(null)
    api.companyDocuments().then(setDocs).catch((e: Error) => setError(e.message))
  }

  useEffect(() => {
    load()
    api.documentTypes().then(setTypes).catch(() => setTypes([]))
  }, [])

  // Cheklistdan "hujjatlarim bo'limiga o'tish" bosilganda — darhol shu
  // turdagi hujjat formasi ochiladi (foydalanuvchi qidirib yurmasin).
  useEffect(() => {
    if (focusType) setEditing({ doc_type: focusType })
  }, [focusType])

  const confirmDelete = useConfirm<CompanyDocument>()
  async function remove(d: CompanyDocument) {
    setError(null)
    try {
      await api.deleteCompanyDocument(d.id)
      load()
    } catch (e) {
      setError(t('common.deleteFailed', { name: d.name, msg: (e as Error).message }))
    }
  }

  // Tur bo'yicha guruhlash. Notanish kod (turlar ro'yxatidan chiqarilgan
  // hujjat) YO'QOLMAYDI — pastda alohida ro'yxatda qoladi.
  const byType = new Map<string, CompanyDocument[]>()
  for (const d of docs) byType.set(d.doc_type, [...(byType.get(d.doc_type) || []), d])

  const known = new Set((types || []).map((x) => x.code))
  const otherDocs = docs.filter((d) => !known.has(d.doc_type))

  const baseTypes = (types || []).filter((x) => x.base)
  const extraTypes = (types || []).filter((x) => !x.base)
  const ready = baseTypes.filter((x) => itemStatus(byType.get(x.code)) === 'ok').length
  const blocking = baseTypes.filter(
    (x) => ['missing', 'expired'].includes(itemStatus(byType.get(x.code)))).length

  const problems = docs.filter((d) => d.status === 'expired' || d.status === 'expiring_soon')

  const itemProps = {
    byType, onAdd: (code: string) => setEditing({ doc_type: code }),
    onEdit: setEditing as (d: CompanyDocument) => void, onRemove: confirmDelete.ask,
    // Yuklab olish xatosi MAVJUD xato maydoniga chiqadi — yangi
    // ko'rsatish joyi yasalmaydi.
    onFaylXato: setError,
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button onClick={() => setEditing('new')}>
          <Icon name="plus" size={14} /> {t('docs.addDoc')}
        </Button>
        <Button variant="outline" onClick={() => setTemplate((v) => !v)}>
          <Icon name="checklist" size={14} /> {t('docs.template')}
        </Button>
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
          {error}
        </div>
      )}

      {/* Muddat ogohlantirishi — biznes-jarayon talabi: "muddati tugagan
          bo'lsa tizim brokerga xabar beradi va yangilashni so'raydi".
          Cheklistda holat har bandda ko'rinadi, lekin bazaviy bo'lmagan
          turlar yig'ilgan holda turadi — u yerdagi tugayotgan muddat
          e'tibordan chetda qolmasin. */}
      {problems.length > 0 && (
        <div className="mb-3 max-w-[860px] rounded-lg border border-soon/40 bg-soon-soft px-3.5 py-2.5 text-body text-soon-strong">
          <b>{t('docs.updateNeeded', { n: problems.length })}</b>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {problems.map((d) => (
              <li key={d.id}>
                {d.name} — {d.status === 'expired'
                  ? t('docs.expiredOn', { date: dateFmt(d.valid_until) })
                  : t('docs.daysLeftOn', { n: d.days_left ?? 0, date: dateFmt(d.valid_until) })}
              </li>
            ))}
          </ul>
        </div>
      )}

      {editing && (
        <DocumentForm
          // `key` SHART: ketma-ket ikki xil turga "Hujjat qo'shish" bosilsa
          // komponent qayta o'rnatilmasa forma eski turda qolardi.
          key={editing === 'new' ? 'new' : ((editing as CompanyDocument).id ?? editing.doc_type)}
          doc={editing === 'new' ? null : (editing as CompanyDocument)}
          types={types || []}
          onSaved={() => { setEditing(null); load() }}
          onCancel={() => setEditing(null)}
        />
      )}

      {template && (
        <DocumentTemplate
          types={types || []}
          docs={docs}
          onImported={load}
          onClose={() => setTemplate(false)}
        />
      )}

      {types === null && <Skeleton className="h-48 w-full max-w-[860px] rounded-xl" />}

      {types !== null && types.length === 0 && (
        <div className="rounded-lg border border-urgent/40 bg-urgent-soft px-3 py-2 text-body text-urgent-strong">
          {t('docs.typesFailed')}
        </div>
      )}

      {types !== null && types.length > 0 && (
        <Card className="max-w-[860px] overflow-hidden">
          {/* Sarlavha — TZ dagi "to'liqlik" o'lchovi: nechtasi tayyor */}
          <div className="flex flex-wrap items-center gap-2 border-b px-3.5 py-2.5">
            <Icon name="check" size={14} className="text-primary" />
            <span className="text-body font-semibold">{t('docs.setTitle')}</span>
            <div className="ml-auto flex flex-wrap gap-1.5">
              <span className="rounded bg-ok-soft px-1.5 py-0.5 text-micro font-semibold text-ok-strong">
                {t('docs.readyOf', { n: ready, total: baseTypes.length })}
              </span>
              {blocking > 0 && (
                <span className="rounded bg-urgent-soft px-1.5 py-0.5 text-micro font-semibold text-urgent-strong"
                  title={t('docs.blockingTitle')}>
                  {t('docs.blocking', { n: blocking })}
                </span>
              )}
              {blocking === 0 && (
                <span className="rounded bg-ok-soft px-1.5 py-0.5 text-micro font-semibold text-ok-strong">
                  {t('compliance.complete')}
                </span>
              )}
            </div>
          </div>

          <div className="border-b bg-muted px-3.5 py-2 text-caption text-muted-foreground">
            {t('docs.intro')}
          </div>

          <ul className="divide-y divide-border-soft">
            {baseTypes.map((t) => (
              <ChecklistItem key={t.code} type={t} {...itemProps} />
            ))}
          </ul>

          {/* Bazaviy emas turlar — yig'iladi: ular faqat tender matnida talab
              topilganda majburiy bo'ladi, doimo ochiq tursa ro'yxat 11 ta
              majburiy hujjatga o'xshab ko'rinardi. */}
          <button
            className="flex w-full items-center gap-2 border-t bg-muted/40 px-3.5 py-2 text-left text-caption font-semibold text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => setShowExtra((v) => !v)} aria-expanded={showExtra}
          >
            <Icon name="chevron" size={13}
              className={cn('transition-transform', !showExtra && '-rotate-90')} />
            {t('docs.byTender', { n: extraTypes.length })}
            <span className="ml-auto font-normal">
              {t('docs.byTenderHave', {
                n: extraTypes.filter((x) => byType.get(x.code)?.length).length,
              })}
            </span>
          </button>
          {showExtra && (
            <ul className="divide-y divide-border-soft border-t">
              {extraTypes.map((t) => (
                <ChecklistItem key={t.code} type={t} {...itemProps} />
              ))}
            </ul>
          )}

          {/* Kanonik ro'yxatdan tashqaridagi hujjatlar — jimgina yo'qolmasin */}
          {otherDocs.length > 0 && (
            <div className="border-t px-3.5 py-2.5">
              <p className="mb-1.5 text-caption font-semibold text-muted-foreground">
                {t('docs.otherDocs', { n: otherDocs.length })}
              </p>
              {otherDocs.map((d) => (
                <DocumentRow key={d.id} doc={d} onEdit={itemProps.onEdit}
                  onRemove={confirmDelete.ask} onFaylXato={setError} />
              ))}
            </div>
          )}

          <div className="border-t bg-muted px-3.5 py-2 text-micro text-muted-foreground">
            {t('docs.disclaimer')}
          </div>
        </Card>
      )}

      <ConfirmDialog
        {...confirmDelete.props}
        title={t('common.confirmDelete', { name: confirmDelete.target?.name ?? '' })}
        onConfirm={() => confirmDelete.target && remove(confirmDelete.target)}
      />
    </div>
  )
}

// ============================================================================
// Cheklistning bitta bandi: tur + "bazada bor / yo'q" belgisi + hujjatlar
// ============================================================================
function ChecklistItem({ type, byType, onAdd, onEdit, onRemove, onFaylXato }: {
  type: DocumentType
  byType: Map<string, CompanyDocument[]>
  onAdd: (code: string) => void
  onEdit: (d: CompanyDocument) => void
  onRemove: (d: CompanyDocument) => void
  onFaylXato?: (matn: string) => void
}) {
  const t = useT()
  const list = byType.get(type.code) || []
  const st = itemStatus(list)
  const s = STATUS[st]

  return (
    <li className="px-3.5 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn('flex size-5 shrink-0 items-center justify-center rounded-full text-caption font-semibold',
            s.cls)}
          aria-hidden="true"
        >{s.mark}</span>
        <span className="text-body font-medium">{type.label}</span>
        <span className={cn('ml-auto rounded px-2 py-0.5 text-caption font-semibold', s.cls)}>
          {t(s.text)}
        </span>
      </div>

      {/* Bir turda bir nechta hujjat bo'lishi mumkin (2 ta litsenziya) —
          hammasi ko'rinadi, band holati esa eng yaroqlisi bo'yicha. */}
      {list.length > 0 && (
        <div className="mt-1 pl-7">
          {list.map((d) => (
            <DocumentRow key={d.id} doc={d} onEdit={onEdit} onRemove={onRemove}
              onFaylXato={onFaylXato} />
          ))}
        </div>
      )}

      <div className="mt-1 flex flex-wrap items-center gap-3 pl-7">
        <button
          className="text-caption font-semibold text-primary underline-offset-2 hover:underline"
          onClick={() => onAdd(type.code)}
        >
          {t(st === 'missing' ? 'compliance.addDoc'
            : st === 'expired' ? 'compliance.renewDoc' : 'compliance.addMore')}
        </button>
      </div>

      {/* DALIL — shaffoflik: talab qayerdan kelib chiqdi. Tender panelidagi
          "Nega kerak?" bilan bir xil, faqat manba tender matni emas. */}
      <details className="mt-1 pl-7 text-caption">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
          {t('compliance.why')}
        </summary>
        <div className="mt-1 rounded-md bg-muted p-2 leading-relaxed">
          {type.hint}
          <div className="mt-1 text-micro text-muted-foreground">
            {t(type.base ? 'docs.whyBase' : 'docs.whyExtra')}
          </div>
        </div>
      </details>
    </li>
  )
}

// Bitta hujjat qatori — nomi, raqami, muddati va amallar
function DocumentRow({ doc, onEdit, onRemove, onFaylXato }: {
  doc: CompanyDocument
  onEdit: (d: CompanyDocument) => void
  onRemove: (d: CompanyDocument) => void
  /** Yuklab olish yiqilsa — xato YUQORIGA chiqadi.
   *  `catch {}` bilan yutilsa foydalanuvchi tugmani bosardi va
   *  hech narsa bo'lmasdi (aynan `file://` havolasidagi nuqson). */
  onFaylXato?: (matn: string) => void
}) {
  const t = useT()
  return (
    <div className="group flex flex-wrap items-center gap-1.5 py-0.5 text-caption text-muted-foreground">
      <span className="text-foreground">{doc.name}</span>
      {doc.number && <span className="tabular">· № {doc.number}</span>}
      <span className="tabular">
        · {doc.valid_until
          ? t('compliance.validUntil', { date: dateFmt(doc.valid_until) })
          : t('compliance.perpetual')}
      </span>
      {/* CHEGARA ANIQ KO'RSATILADI. `valid_until` — hujjat yaroqli
          OXIRGI kun va u KIRADI: "0 kun qoldi" aslida "BUGUN tugaydi"
          degani, ya'ni bugun hali amal qiladi. Raqam bilan ko'rsatish
          uni "allaqachon tugagan" deb o'qishga yo'l qo'yardi. */}
      {doc.status === 'expiring_soon' && doc.days_left != null && (
        <span className="text-soon-strong">
          {doc.days_left === 0
            ? t('compliance.expiresToday')
            : t('compliance.daysLeft', { n: doc.days_left })}
        </span>
      )}
      {doc.status === 'expired' && doc.days_left != null && (
        <span className="text-urgent-strong">
          {t('compliance.daysAgo', { n: Math.abs(doc.days_left) })}
        </span>
      )}
      {/* HAQIQIY FAYL — autentifikatsiyalangan yuklab olish.
          `<a href>` EMAS: server yo'li brauzerga UMUMAN chiqmaydi va
          so'rov sessiya bilan ketadi. */}
      {doc.yuklama_id && (
        <button type="button" title={t('docs.download')}
          className="text-primary hover:underline"
          onClick={() => {
            faylniYuklabOl(`/company/documents/${doc.id}/download`,
                           doc.file_name || 'hujjat')
              .catch((e) => onFaylXato?.((e as Error).message))
          }}>
          <Icon name="external" size={11} />
        </button>
      )}
      {/* ESKI QATOR: `file_ref` matn havolasi. Yangi hujjatlarda
          yaratilmaydi, lekin 13 ta mavjud qator uchun ko'rsatiladi —
          aks holda ular jimgina yo'qolardi. */}
      {!doc.yuklama_id && doc.file_ref && (
        <a href={doc.file_ref} target="_blank" rel="noreferrer"
          className="text-muted-foreground hover:underline" title={doc.file_ref}>
          <Icon name="external" size={11} />
        </a>
      )}
      <span className="ml-auto flex shrink-0 items-center opacity-60 transition-opacity group-hover:opacity-100">
        <button
          className="rounded p-1 transition-colors hover:bg-accent hover:text-foreground"
          title={t('common.edit')} aria-label={`${doc.name} — ${t('common.edit')}`}
          onClick={() => onEdit(doc)}
        >
          <Icon name="edit" size={12} />
        </button>
        <button
          className="rounded p-1 transition-colors hover:bg-urgent-soft hover:text-urgent-strong"
          title={t('common.delete')} aria-label={`${doc.name} — ${t('common.delete')}`}
          onClick={() => onRemove(doc)}
        >
          <Icon name="trash" size={12} />
        </button>
      </span>
    </div>
  )
}

// Hujjat qo'shish / tahrirlash formasi
function DocumentForm({ doc, types, onSaved, onCancel }: {
  doc: CompanyDocument | null
  types: DocumentType[]
  onSaved: () => void
  onCancel: () => void
}) {
  const t = useT()
  const editing = !!doc?.id
  const [docType, setDocType] = useState(doc?.doc_type || '')
  // Shablon yoki cheklistdan kelinganda tur oldindan tanlangan bo'ladi —
  // nomni ham kanonik nom bilan to'ldiramiz, foydalanuvchi qayta yozmasin.
  const [name, setName] = useState(
    () => doc?.name || (doc?.doc_type
      ? types.find((t) => t.code === doc.doc_type)?.label || ''
      : ''))
  const [number, setNumber] = useState(doc?.number || '')
  const [issuedAt, setIssuedAt] = useState(doc?.issued_at || '')
  const [validUntil, setValidUntil] = useState(doc?.valid_until || '')
  const [perpetual, setPerpetual] = useState(!!doc?.id && !doc?.valid_until)
  const [fileName, setFileName] = useState(doc?.file_name || '')
  // ESKI QATORLAR UCHUN O'QILADI, LEKIN TAHRIRLANMAYDI: formada
  // maydon yo'q, qiymat esa saqlashda YO'QOLMASLIGI kerak — aks
  // holda mavjud 13 ta havola birinchi tahrirda o'chib ketardi.
  const [fileRef] = useState(doc?.file_ref || '')
  // TANLANGAN, LEKIN HALI YUBORILMAGAN fayl. Yuklash SAQLASHDAN KEYIN
  // bo'ladi: `POST /company/documents/{id}/fayl` hujjat id sini talab
  // qiladi va yangi hujjatda u hali yo'q.
  const [fayl, setFayl] = useState<File | null>(null)
  const [faylXato, setFaylXato] = useState<string | null>(null)
  const faylRef = useRef<HTMLInputElement>(null)
  const [note, setNote] = useState(doc?.note || '')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // Turlar ro'yxati formadan KEYIN kelishi mumkin (cheklistdan o'tilganda
  // ikkalasi parallel yuklanadi) — kelganda nomni yana bir bor to'ldiramiz.
  useEffect(() => {
    if (name || !docType) return
    const t = types.find((x) => x.code === docType)
    if (t) setName(t.label)
  }, [types, docType])

  // Tur tanlanganda nom bo'sh bo'lsa — kanonik nom bilan to'ldiramiz
  function pickType(code: string) {
    setDocType(code)
    const t = types.find((x) => x.code === code)
    if (t && !name.trim()) setName(t.label)
  }

  async function save() {
    if (!docType) { setMsg({ ok: false, text: t('docs.errNoType') }); return }
    if (!name.trim()) { setMsg({ ok: false, text: t('docs.errNoName') }); return }
    setSaving(true); setMsg(null)
    const body = {
      doc_type: docType,
      name: name.trim(),
      number: number.trim() || null,
      issued_at: issuedAt || null,
      // "Muddatsiz" belgilansa valid_until = null: cheklist buni "ma'lumot
      // yo'q" emas, "cheklanmagan" deb tushunadi.
      valid_until: perpetual ? null : (validUntil || null),
      file_name: fileName.trim() || null,
      file_ref: fileRef.trim() || null,
      note: note.trim() || null,
    }
    try {
      const saqlangan = editing
        ? await api.updateCompanyDocument(doc!.id, body)
        : await api.createCompanyDocument(body)
      // FAYL METAMA'LUMOTDAN KEYIN. Tartib ataylab: fayl yuklanib,
      // metama'lumot saqlanmasa, diskda EGASIZ fayl qolardi.
      if (fayl) {
        try {
          await api.uploadCompanyDocumentFile(saqlangan.id, fayl)
        } catch (e) {
          // HUJJAT SAQLANDI, FAYL YO'Q. Buni JIM O'TKAZIB
          // YUBORMAYMIZ: foydalanuvchi "saqlandi" degan xabarni
          // ko'rib, faylni yuklandi deb o'ylardi.
          setMsg({ ok: false, text: (e as Error).message })
          setSaving(false)
          onSaved()
          return
        }
      }
      onSaved()
    } catch (e) {
      setMsg({ ok: false, text: t('common.errorWith', { msg: (e as Error).message }) })
    }
    finally { setSaving(false) }
  }

  const hint = types.find((t) => t.code === docType)?.hint

  return (
    <Card className="mb-4 max-w-[760px] p-5">
      <h3 className="mb-4 text-title font-semibold">
        {t(editing ? 'docs.formEdit' : 'docs.formNew')}
      </h3>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Label text={t('docs.fType')} note={hint || undefined}>
          <Select value={docType || 'none'} onValueChange={(v) => pickType(v === 'none' ? '' : v)}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t('common.select')}</SelectItem>
              {types.map((x) => <SelectItem key={x.code} value={x.code}>{x.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </Label>
        <Label text={t('docs.fName')}>
          <Input value={name} onChange={(e) => setName(e.target.value)}
            placeholder={t('docs.namePlaceholder')} />
        </Label>
        <Label text={t('docs.fNumber')}>
          <Input value={number} onChange={(e) => setNumber(e.target.value)} placeholder="AA 1234567" />
        </Label>
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Label text={t('docs.fIssued')}>
          <Input type="date" value={issuedAt || ''} onChange={(e) => setIssuedAt(e.target.value)} />
        </Label>
        <Label text={t('docs.fValid')}>
          <Input type="date" value={validUntil || ''} disabled={perpetual}
            onChange={(e) => setValidUntil(e.target.value)} />
        </Label>
        <label className="flex items-end gap-2 pb-2.5 text-body">
          <Checkbox checked={perpetual} onCheckedChange={(v) => setPerpetual(v === true)} />
          <span>{t('docs.fPerpetual')}</span>
        </label>
      </div>

      {/* FAYL — foydalanuvchi SERVER YO'LINI yozmaydi.
          Ilgari bu yerda `file_ref` matn maydoni turardi va unga
          `file:///D:/...` kabi MAHALLIY yo'l yozilardi: brauzer
          `http://` sahifadan `file://` ga o'tishni bloklaydi, ya'ni
          havola bosilardi va HECH NARSA bo'lmasdi — xato ham
          chiqmasdi. 13 ta bazaviy qatorda aynan shunday. */}
      <div className="mb-4">
        <Label text={t('docs.fFile')}>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={faylRef} type="file" className="sr-only"
              accept={QABUL_QILINADI}
              onChange={(e) => {
                const f = e.target.files?.[0] || null
                setFaylXato(null)
                if (f && f.size > MAX_UPLOAD_MB * 1024 * 1024) {
                  // CHEGARA BRAUZERDA HAM: server baribir tekshiradi
                  // (`_yuklangani`), lekin 25 MB ni yuborib keyin rad
                  // javobini kutish foydalanuvchi uchun ma'nosiz.
                  setFaylXato(t('err.FILE_TOO_LARGE', { max_mb: MAX_UPLOAD_MB }))
                  setFayl(null)
                  return
                }
                setFayl(f)
                if (f) setFileName(f.name)
              }} />
            <Button type="button" variant="outline" size="sm"
              onClick={() => faylRef.current?.click()}>
              {t('docs.chooseFile')}
            </Button>
            <span className="text-caption text-muted-foreground">
              {fayl ? `${fayl.name} · ${(fayl.size / 1024).toFixed(0)} KB`
                    : (doc?.yuklama_id ? (doc.file_name || t('docs.hasFile'))
                                       : t('docs.noFile'))}
            </span>
            {fayl && (
              <button type="button" className="text-caption underline"
                onClick={() => { setFayl(null); if (faylRef.current) faylRef.current.value = '' }}>
                {t('common.cancel')}
              </button>
            )}
          </div>
        </Label>
        {faylXato && (
          <p className="mt-1 text-caption text-urgent-strong">{faylXato}</p>
        )}
        <p className="mt-1 text-caption text-muted-foreground">
          {t('docs.fileHint', { max_mb: MAX_UPLOAD_MB })}
        </p>
      </div>

      <Label text={t('docs.fNote')}>
        <Input value={note} onChange={(e) => setNote(e.target.value)} />
      </Label>

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
