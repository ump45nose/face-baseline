import { createContext, useContext, useEffect, useState, type ReactNode, type ButtonHTMLAttributes } from 'react'
import type { JobStatus } from '../data/types'
import Icon, { type IconName } from './icons'

export type Tone = 'neutral' | 'moss' | 'amber' | 'danger' | 'ink'

/* ---------- 按钮 ---------- */
export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  className = '',
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'warn'
  size?: 'sm' | 'md'
  icon?: IconName
}) {
  const { toast } = useUI()
  const onClick = rest.onClick
  const v = {
    primary: 'bg-moss text-white hover:bg-moss-2 disabled:bg-moss/35 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]',
    secondary: 'bg-card text-ink ring-1 ring-line-2/80 hover:bg-paper hover:ring-line-2 disabled:text-muted disabled:hover:bg-card',
    ghost: 'text-ink-2 hover:bg-well hover:text-ink disabled:text-muted disabled:hover:bg-transparent',
    warn: 'bg-amber-soft text-amber ring-1 ring-amber/25 hover:ring-amber/50',
  }[variant]
  const sz = size === 'sm' ? 'h-9 sm:h-8 px-2.5 text-[13px] gap-1.5' : 'h-10 sm:h-9 px-3.5 text-sm gap-2'
  return (
    <button
      className={`inline-flex shrink-0 items-center justify-center rounded-lg font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed ${sz} ${v} ${className}`}
      {...rest}
      onClick={async (event) => { try { await onClick?.(event) } catch (error) { toast(error instanceof Error ? error.message : String(error), 'danger') } }}
    >
      {icon && <Icon name={icon} size={size === 'sm' ? 14 : 16} />}
      {children}
    </button>
  )
}

/* ---------- 标签与状态 ---------- */
const toneText: Record<Tone, string> = { neutral: 'text-ink-2', moss: 'text-moss', amber: 'text-amber', danger: 'text-danger', ink: 'text-ink' }
const toneBg: Record<Tone, string> = {
  neutral: 'bg-well text-ink-2',
  moss: 'bg-moss-soft text-moss',
  amber: 'bg-amber-soft text-amber',
  danger: 'bg-danger-soft text-danger',
  ink: 'bg-ink text-white',
}
const toneDot: Record<Tone, string> = { neutral: 'bg-muted', moss: 'bg-moss', amber: 'bg-amber', danger: 'bg-danger', ink: 'bg-ink' }

export function Badge({ tone = 'neutral', icon, children, className = '' }: { tone?: Tone; icon?: IconName; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex h-[22px] items-center gap-1 rounded-md px-1.5 text-xs font-medium whitespace-nowrap ${toneBg[tone]} ${className}`}>
      {icon && <Icon name={icon} size={12} strokeWidth={2} />}
      {children}
    </span>
  )
}

export function Dot({ tone }: { tone: Tone }) {
  return <span className={`inline-block size-1.5 shrink-0 rounded-full ${toneDot[tone]}`} />
}

export function StatusText({ tone, children, className = '' }: { tone: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${toneText[tone]} ${className}`}>
      <Dot tone={tone} />
      {children}
    </span>
  )
}

/* ---------- 照片画布 ---------- */
export function PhotoCanvas({
  url,
  thumbnailUrl,
  alt,
  className = 'aspect-[4/5]',
  dim = false,
  zoomable = true,
  empty,
  children,
}: {
  url: string | null
  thumbnailUrl?: string | null
  alt: string
  className?: string
  dim?: boolean
  zoomable?: boolean
  empty?: { title: string; note?: string; tone?: 'amber' | 'neutral' }
  children?: ReactNode
}) {
  const { zoom } = useUI()
  const base = `relative isolate overflow-hidden rounded-[10px] bg-canvas ring-1 ring-inset ring-black/[0.04] ${className}`
  if (!url)
    return (
      <div className={base}>
        <EmptyArt title={empty?.title ?? '无可显示图像'} note={empty?.note} tone={empty?.tone ?? 'neutral'} />
        {children}
      </div>
    )
  const img = <img src={thumbnailUrl ?? url} alt={alt} loading="lazy" className={`size-full object-contain transition duration-300 ${dim ? 'opacity-40 grayscale' : ''}`} />
  if (!zoomable)
    return (
      <div className={base}>
        {img}
        {children}
      </div>
    )
  return (
    <div className={`group/canvas ${base}`}>
      <button type="button" onClick={() => zoom(url, alt)} className="block size-full cursor-zoom-in" aria-label={`放大查看 ${alt}`}>
        {img}
      </button>
      <span className="pointer-events-none absolute right-2 bottom-2 grid size-7 place-items-center rounded-md bg-white/90 text-ink-2 opacity-0 shadow-sm transition-opacity group-hover/canvas:opacity-100">
        <Icon name="zoom" size={14} />
      </span>
      {children}
    </div>
  )
}

function EmptyArt({ title, note, tone }: { title: string; note?: string; tone: 'amber' | 'neutral' }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[radial-gradient(circle_at_50%_38%,#f6f5f1_0,#ecebe5_70%)] p-4 text-center">
      <svg viewBox="0 0 80 96" className="w-[30%] max-w-20 text-line-2" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
        <ellipse cx="40" cy="36" rx="17" ry="21" strokeDasharray="3 4" />
        <path d="M10 94c2-18 14-28 30-28s28 10 30 28" strokeDasharray="3 4" />
      </svg>
      <div>
        <div className={`text-[13px] font-medium ${tone === 'amber' ? 'text-amber' : 'text-ink-2'}`}>{title}</div>
        {note && <div className="mt-0.5 text-xs text-muted">{note}</div>}
      </div>
    </div>
  )
}

/* ---------- 度量 ---------- */
export function Meter({ value, threshold, tone }: { value: number; threshold?: number; tone?: 'moss' | 'amber' }) {
  const t = tone ?? (threshold != null && value < threshold ? 'amber' : 'moss')
  return (
    <div className="relative h-1 w-full rounded-full bg-well">
      <div className={`h-full rounded-full ${t === 'amber' ? 'bg-amber' : 'bg-moss'}`} style={{ width: `${value}%` }} />
      {threshold != null && <span className="absolute -top-1 h-3 w-px bg-ink/40" style={{ left: `${threshold}%` }} />}
    </div>
  )
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-well">
      <div className="h-full rounded-full bg-moss transition-[width] duration-500" style={{ width: `${Math.round((Number.isFinite(value) ? value : 0) * 100)}%` }} />
    </div>
  )
}

export const jobMeta: Record<JobStatus, { label: string; tone: Tone }> = {
  queued: { label: '等待中', tone: 'neutral' },
  running: { label: '扫描中', tone: 'moss' },
  done: { label: '完成', tone: 'moss' },
  partial: { label: '完成 · 有待处理项', tone: 'amber' },
  failed: { label: '扫描失败', tone: 'danger' },
}
export function JobBadge({ status }: { status: JobStatus }) {
  const m = jobMeta[status]
  return <StatusText tone={m.tone}>{m.label}</StatusText>
}

/* ---------- 标签页 ---------- */
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: [T, string, number?][] }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {items.map(([k, label, count]) => (
        <button
          key={k}
          role="tab"
          aria-selected={value === k}
          onClick={() => onChange(k)}
          className={`relative -mb-px flex h-10 shrink-0 items-center gap-1.5 px-2.5 text-sm transition-colors ${
            value === k ? 'font-medium text-ink after:absolute after:inset-x-2 after:bottom-0 after:h-[2px] after:rounded-full after:bg-ink' : 'text-muted hover:text-ink'
          }`}
        >
          {label}
          {count != null && <span className={`rounded px-1 text-xs tabular-nums ${value === k ? 'bg-well text-ink-2' : 'text-muted'}`}>{count}</span>}
        </button>
      ))}
    </div>
  )
}

/* ---------- 全局：放大查看与提示 ---------- */
interface UI {
  zoom: (url: string, caption: string) => void
  toast: (text: string, tone?: Tone) => void
}
const Ctx = createContext<UI>({ zoom: () => {}, toast: () => {} })
export const useUI = () => useContext(Ctx)

export function UIProvider({ children }: { children: ReactNode }) {
  const [z, setZ] = useState<{ url: string; caption: string } | null>(null)
  const [t, setT] = useState<{ text: string; tone: Tone; id: number } | null>(null)
  useEffect(() => {
    if (!t) return
    const h = setTimeout(() => setT(null), 3200)
    return () => clearTimeout(h)
  }, [t])
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && setZ(null)
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])
  return (
    <Ctx.Provider
      value={{
        zoom: (url, caption) => setZ({ url: url.replace(/w=\d+/, 'w=1800'), caption }),
        toast: (text, tone = 'ink') => setT({ text, tone, id: Date.now() }),
      }}
    >
      {children}
      {z && (
        <div className="fixed inset-0 z-50 flex flex-col bg-[#141615]/92 p-3 backdrop-blur-sm sm:p-8" onClick={() => setZ(null)} role="dialog" aria-modal>
          <div className="flex items-center justify-between gap-4 pb-3 text-[13px] text-white/75">
            <span className="truncate">{z.caption}</span>
            <button className="grid size-10 place-items-center rounded-lg text-white hover:bg-white/10" onClick={() => setZ(null)} aria-label="关闭">
              <Icon name="x" size={18} />
            </button>
          </div>
          <img src={z.url} alt={z.caption} className="min-h-0 flex-1 object-contain" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
      {t && (
        <div key={t.id} className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
          <div
            className={`max-w-md rounded-[10px] px-4 py-2.5 text-[13px] shadow-[0_8px_30px_-6px_rgba(0,0,0,0.25)] ${
              t.tone === 'amber' ? 'bg-amber-soft text-amber ring-1 ring-amber/25' : t.tone === 'danger' ? 'bg-danger text-white' : 'bg-ink text-white'
            }`}
          >
            {t.text}
          </div>
        </div>
      )}
    </Ctx.Provider>
  )
}

/** 真实下载：fetch 原图字节 → Blob → object URL → 触发保存，不经 canvas 转码 */
export async function download(url: string | null, fileName: string) {
  if (!url) throw new Error('没有可下载的图片')
  let res: Response
  try {
    res = await fetch(url, { mode: 'cors' })
  } catch {
    throw new Error('网络连接失败或图片源不允许跨域下载')
  }
  if (!res.ok) throw new Error(`图片服务返回错误（HTTP ${res.status}）`)
  const blob = await res.blob()
  if (!blob.size) throw new Error('下载的文件为空')
  const objectUrl = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    // 延迟释放，确保浏览器已开始保存
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
}

export function DownloadButton({
  url,
  fileName,
  children,
  size = 'md',
  variant = 'secondary',
  className = '',
}: {
  url: string | null
  fileName: string
  children: ReactNode
  size?: 'sm' | 'md'
  variant?: 'secondary' | 'ghost'
  className?: string
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const run = async () => {
    setLoading(true)
    setError('')
    try {
      await download(url, fileName)
    } catch (e) {
      setError(e instanceof Error ? e.message : '未知错误')
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <Button size={size} variant={variant} icon={error ? 'refresh' : 'download'} onClick={run} disabled={loading}>
        {loading ? '下载中…' : error ? '重试下载' : children}
      </Button>
      {error && (
        <span role="alert" className="max-w-64 text-xs text-danger">
          下载失败：{error}
        </span>
      )}
    </div>
  )
}
