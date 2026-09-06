import { useState } from 'react'
import { api } from '@/api'
import type { ApiError, CompanyAccount } from '@/api'
import Icon from './Icon'
import { useT } from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// KIRISH EKRANI (auth-2).
//
// Tender-AI ga KOMPANIYA hisobi bilan kiriladi — odam emas. Hodimlar ERP
// ning tushunchasi va ular u yerda (`erp.app_user`); bu yerda "kim kirdi"
// degan savolga javob — kompaniya.
//
// Xato matni ATAYLAB umumiy: "login yoki parol noto'g'ri". Qaysi biri xato
// ekanini aytish mavjud loginlarni topishga yo'l ochadi.

export default function LoginPage({ onLogin }: {
  onLogin: (a: CompanyAccount) => void
}) {
  const t = useT()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true); setError(null)
    try {
      onLogin(await api.login(username.trim(), password))
    } catch (err) {
      const a = err as ApiError
      // 503 — jadvallar bazaga qo'llanmagan. Bu parol xatosi EMAS va
      // shunday deb ko'rsatilsa foydalanuvchi parolni qayta-qayta terardi.
      // 429 — parol tanlashdan himoya (auth-5). Bu ham parol xatosi
      // EMAS: hisob joyida, faqat urinishlar vaqtincha to'xtatilgan.
      // Xabar mijoz tilida yig'iladi, server matni tarjima qilinmaydi.
      setError(
        a.status === 503 ? t('auth.schemaMissing')
          : a.status === 429
            ? t('auth.tooManyAttempts',
              { n: Math.max(1, Math.round((a.retryAfter ?? 900) / 60)) })
            : a.message.replace(/^\d+:\s*/, ''))
    } finally { setBusy(false) }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <form onSubmit={submit}
        className="w-full max-w-sm rounded-lg border bg-card p-6">
        <div className="mb-5 flex items-center gap-2.5">
          <Icon name="search" size={22} className="text-primary" />
          <div>
            <div className="text-lead font-semibold leading-tight">
              {t('auth.title')}
            </div>
            <div className="text-micro text-muted-foreground">
              {t('auth.subtitle')}
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <div className="mb-1 text-caption font-semibold text-muted-foreground">
              {t('auth.login')}
            </div>
            <Input autoFocus autoComplete="username" value={username}
              onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div>
            <div className="mb-1 text-caption font-semibold text-muted-foreground">
              {t('auth.password')}
            </div>
            <Input type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </div>

          {error && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
              {error}
            </div>
          )}

          <Button type="submit" className="w-full"
            disabled={busy || !username.trim() || !password}>
            {busy ? t('auth.checking') : t('auth.enter')}
          </Button>
        </div>

        <p className="mt-4 text-micro text-muted-foreground">
          {t('auth.hint')}
        </p>
      </form>
    </div>
  )
}
