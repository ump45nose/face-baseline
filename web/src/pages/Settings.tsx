import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../data/api'
import { fmtTime } from '../data/logic'
import { BUSY_REASON, useActiveJob, useAppState } from '../data/useStore'
import { Button, JobBadge, Progress, useUI } from '../components/ui'
import Icon from '../components/icons'
import { useScanAction } from './Overview'
import type { ScanJob } from '../data/types'

function Section({ title, desc, action, children }: { title: string; desc?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-10 first:mt-0">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {desc && <p className="mt-0.5 text-[13px] text-muted">{desc}</p>}
        </div>
        {action}
      </div>
      <div className="divide-y divide-line rounded-xl bg-card ring-1 ring-line">{children}</div>
    </section>
  )
}

function FormRow({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-2 px-4 py-4 sm:grid-cols-[220px_1fr] sm:items-center sm:gap-6 sm:px-5">
      <div>
        <div className="text-[13px] font-medium">{label}</div>
        {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export default function SettingsPage() {
  const state = useAppState()
  const job = useActiveJob()
  const scan = useScanAction()
  const { toast } = useUI()
  const init = () => ({ root: state.settings.root, k: String(state.settings.k), threshold: String(state.settings.threshold) })
  const [form, setForm] = useState(init)
  useEffect(() => setForm(init()), [state.settings])

  const k = Number(form.k)
  const t = Number(form.threshold)
  const errs = {
    root: !form.root.trim().startsWith('/') ? '请输入以 / 开头的绝对路径' : '',
    k: form.k === '' || !Number.isInteger(k) || k < 1 || k > 100 ? '需为 1–100 的整数' : '',
    threshold: form.threshold === '' || !Number.isInteger(t) || t < 0 || t > 100 ? '需为 0–100 的整数' : '',
  }
  const dirty = form.root.trim() !== state.settings.root || k !== state.settings.k || t !== state.settings.threshold
  const valid = !errs.root && !errs.k && !errs.threshold
  const busy = !!job
  const last = state.jobs.find((j) => j.status !== 'queued' && j.status !== 'running')
  const latest = state.jobs[0]

  const save = async () => {
    await api.saveSettings({ root: form.root.trim(), k, threshold: t })
    toast('设置已保存，候选与自动选择已重新计算')
  }

  const input = (key: 'root' | 'k' | 'threshold', extra: string, props: object = {}) => (
    <div>
      <input
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        disabled={busy}
        aria-invalid={!!errs[key]}
        className={`h-10 w-full rounded-lg bg-card px-3 text-sm ring-1 outline-none focus:ring-2 disabled:bg-well disabled:text-muted sm:h-9 ${extra} ${
          errs[key] ? 'ring-danger/70 focus:ring-danger/50' : 'ring-line-2/80 focus:ring-moss/50'
        }`}
        {...props}
      />
      {errs[key] && <div className="mt-1 text-xs text-danger">{errs[key]}</div>}
    </div>
  )

  return (
    <div className="max-w-[880px]">
      <header>
        <h1 className="text-[26px] font-semibold tracking-tight sm:text-[28px]">扫描与设置</h1>
        <p className="mt-1 text-sm text-ink-2">管理图库位置、候选规则与扫描任务</p>
      </header>

      <div className="mt-8">
        <Section title="扫描" desc="仅对新增或图像变化的照片评分；改名与元数据写回不会重复评分">
          <div className="flex flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
            <div className="min-w-0 flex-1">
              {job ? (
                <>
                  <div className="flex items-center justify-between gap-3 text-[13px]">
                    <span className="flex items-center gap-2">
                      <JobBadge status={job.status} />
                      <span className="text-ink-2">{job.scopeLabel}</span>
                    </span>
                    <span className="text-muted tabular-nums">
                      {job.processed} / {job.total} 位人物
                    </span>
                  </div>
                  <div className="mt-2">
                    <Progress value={job.processed / job.total} />
                  </div>
                  <p className="mt-2 text-xs text-muted">
                    {job.fileProcessed}/{job.fileTotal} 张照片 · 本次评分 {job.scored} 张 · {' '}
                    {job.merged > 0 ? `已合并 ${job.merged} 次重复请求 · ` : ''}
                    {BUSY_REASON}
                  </p>
                </>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2 text-[13px]">
                    {last && <JobBadge status={last.status} />}
                    <span className="text-ink-2">上次扫描 {last ? fmtTime(last.startedAt) : '—'}</span>
                  </div>
                  {last?.status === 'failed' && <p className="mt-1 text-xs text-danger">上次扫描失败，已完成的档案和文件操作保留，可继续重试。</p>}
                  {last?.status === 'partial' && <p className="mt-1 text-xs text-amber">有待处理项，查看运行记录；再次扫描会继续处理。</p>}
                  {last?.status === 'done' && <p className="mt-1 text-xs text-muted">一切正常。</p>}
                </>
              )}
            </div>
            <Button variant="primary" icon={job ? 'refresh' : 'scan'} onClick={() => scan('all')} className="w-full sm:w-auto">
              {job ? '再次请求（将合并）' : last?.status === 'failed' || last?.status === 'partial' ? '立即重试扫描' : '扫描全部人物'}
            </Button>
          </div>
          <FormRow label="定时扫描" hint="由系统 cron 管理，不做实时监听">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
              <span className="flex items-center gap-1.5 font-medium">
                <Icon name="clock" size={14} className="text-muted" />
                每日 03:00
              </span>
              <span className="text-muted">Asia/Taipei</span>
            </div>
          </FormRow>
        </Section>

        <Section title="基线规则" desc="保存后重新计算候选；更换根目录后请扫描建立新图库档案">
          <FormRow label="图库根目录" hint="直接子目录即人物；递归扫描 JPG / JPEG / PNG">
            {input('root', 'font-mono text-[13px]', { spellCheck: false })}
          </FormRow>
          <FormRow label="候选数量 K" hint="每人保留 Top K，1–100">
            {input('k', 'sm:w-28 tabular-nums', { inputMode: 'numeric' })}
          </FormRow>
          <FormRow label="合格门槛" hint="OFIQ 总分，0–100">
            {input('threshold', 'sm:w-28 tabular-nums', { inputMode: 'numeric' })}
          </FormRow>
          <div className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-end sm:px-5">
            {busy && <span className="text-xs text-amber sm:mr-auto">{BUSY_REASON}</span>}
            {dirty && !busy && <span className="text-xs text-muted sm:mr-auto">有未保存的更改</span>}
            {dirty && (
              <Button variant="ghost" disabled={busy} onClick={() => setForm(init())}>
                还原
              </Button>
            )}
            <Button variant="primary" disabled={!dirty || !valid || busy} onClick={save}>
              保存并重新计算
            </Button>
          </div>
        </Section>

        <Section title="运行记录" desc="最近的定时与手动扫描">
          {state.jobs.map((j) => (
            <JobRow key={j.id} j={j} canRetry={j === latest && (j.status === 'failed' || j.status === 'partial')} busy={busy} onRetry={() => scan(j.scope)} />
          ))}
        </Section>
      </div>
    </div>
  )
}

function JobRow({ j, canRetry, busy, onRetry }: { j: ScanJob; canRetry: boolean; busy: boolean; onRetry: () => void }) {
  const [open, setOpen] = useState(j.status !== 'done')
  const issues = j.log.filter((l) => l.level !== 'info').length
  return (
    <div className="px-4 py-3 sm:px-5">
      <div className="flex items-center gap-3">
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="-mx-1 flex min-h-10 min-w-0 flex-1 items-center gap-3 rounded-md px-1 text-left hover:bg-paper">
          <Icon name="chevron" size={14} className={`shrink-0 text-muted transition-transform ${open ? '' : '-rotate-90'}`} />
          <span className="w-24 shrink-0 sm:w-28">
            <JobBadge status={j.status} />
          </span>
          <span className="min-w-0 flex-1 truncate text-[13px]">
            {j.scopeLabel}
            <span className="text-muted">
              {' '}
              · {j.trigger === 'cron' ? '定时' : '手动'}
              {j.merged > 0 && ` · 合并 ${j.merged} 次`}
              {issues > 0 && ` · ${issues} 条提示`}
            </span>
          </span>
          <span className="hidden shrink-0 text-xs text-muted tabular-nums sm:block">{fmtTime(j.startedAt)}</span>
        </button>
        {canRetry && (
          <Button size="sm" variant="warn" icon="refresh" disabled={busy} onClick={onRetry}>
            {j.status === 'failed' ? '重新扫描' : '重试写回'}
          </Button>
        )}
      </div>
      {open && (
        <div className="mt-1 space-y-1 pb-1 pl-7 sm:pl-[152px]">
          <div className="text-xs text-muted sm:hidden">{fmtTime(j.startedAt)}</div>
          {(j.status === 'running' || j.status === 'queued') && (
            <div className="max-w-xs py-1">
              <Progress value={j.processed / j.total} />
            </div>
          )}
          {j.log.map((l, i) => (
            <p key={i} className={`text-xs leading-relaxed ${l.level === 'error' ? 'text-danger' : l.level === 'warn' ? 'text-amber' : 'text-ink-2'}`}>
              {l.text}
            </p>
          ))}
          {j.log.length === 0 && <p className="text-xs text-muted">进行中…</p>}
        </div>
      )}
    </div>
  )
}
