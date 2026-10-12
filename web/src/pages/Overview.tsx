import { useMemo, useState } from 'react'
import { api } from '../data/api'
import { derive, fmtTime, type Derived } from '../data/logic'
import { useActiveJob, useAppState } from '../data/useStore'
import { Button, JobBadge, PhotoCanvas, Progress, StatusText, useUI } from '../components/ui'
import Icon from '../components/icons'
import type { Person, Settings } from '../data/types'

type Filter = 'all' | 'auto' | 'locked' | 'missing' | 'writeback'

export function useScanAction() {
  const { toast } = useUI()
  return async (scope: 'all' | string) => {
    const r = await api.startScan(scope)
    toast(r.merged ? '已有扫描正在进行，本次请求已合并到同一任务' : '扫描已开始')
  }
}

export function modeStatus(d: Derived): { tone: 'moss' | 'ink' | 'amber'; label: string } {
  if (d.mode === 'locked') return d.reliable ? { tone: 'ink', label: '已锁定' } : { tone: 'amber', label: '已锁定 · 质量不足' }
  if (d.mode === 'auto') return { tone: 'moss', label: '自动选择' }
  return { tone: 'amber', label: '缺少可靠基线' }
}

export default function Overview() {
  const state = useAppState()
  const job = useActiveJob()
  const scan = useScanAction()
  const [q, setQ] = useState('')
  const [f, setF] = useState<Filter>('all')
  const rows = useMemo(() => state.people.map((p) => ({ p, d: derive(p, state.settings) })), [state])
  const last = state.jobs.find((j) => j.status !== 'queued' && j.status !== 'running')

  const count = {
    all: rows.length,
    auto: rows.filter((r) => r.d.mode === 'auto').length,
    locked: rows.filter((r) => r.d.mode === 'locked').length,
    missing: rows.filter((r) => !r.d.reliable).length,
    writeback: rows.filter((r) => r.d.writebackIssues.length > 0).length,
  }
  const reliable = rows.filter((r) => r.d.reliable).length
  const filters: [Filter, string][] = [
    ['all', '全部'],
    ['auto', '自动'],
    ['locked', '已锁定'],
    ['missing', '待补充'],
    ['writeback', '写回待修复'],
  ]
  const shown = rows.filter(({ p, d }) => {
    if (q.trim() && !p.name.includes(q.trim())) return false
    if (f === 'auto') return d.mode === 'auto'
    if (f === 'locked') return d.mode === 'locked'
    if (f === 'missing') return !d.reliable
    if (f === 'writeback') return d.writebackIssues.length > 0
    return true
  })

  const summary = [
    ['人物', count.all],
    ['可靠基线', reliable],
    ['手动锁定', count.locked],
    ['待补充', count.missing],
  ] as const

  return (
    <div>
      <header className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight sm:text-[28px]">人物图库</h1>
          <p className="mt-1 text-sm text-ink-2">从每个人的照片中，找到清晰可靠的参考</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <a href="#/settings" className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-card px-3.5 text-sm font-medium ring-1 ring-line-2 sm:h-9"><Icon name="folder" size={16} />选择文件夹</a>
          <Button disabled={!state.settings.folders.length} variant="primary" icon={job ? 'refresh' : 'scan'} onClick={() => scan('all')} className="w-full sm:w-auto">
            {job ? (job.status === 'queued' ? '等待开始…' : `扫描中 ${job.processed}/${job.total}`) : '扫描所选图库'}
          </Button>
        </div>
      </header>

      {/* 紧凑摘要 */}
      <div className="mt-6 flex flex-col gap-3 border-y border-line py-3 md:flex-row md:items-center md:justify-between">
        <dl className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          {summary.map(([label, v]) => (
            <div key={label} className="flex items-baseline gap-1.5">
              <dd className={`text-[17px] font-semibold tabular-nums ${label === '待补充' && v ? 'text-amber' : label === '可靠基线' ? 'text-moss' : ''}`}>{v}</dd>
              <dt className="text-xs text-muted">{label}</dt>
            </div>
          ))}
        </dl>
        <a href="#/settings" className="group flex min-w-0 items-center gap-2 text-xs text-muted hover:text-ink">
          <Icon name="clock" size={14} />
          {job ? (
            <span className="flex items-center gap-2">
              <JobBadge status={job.status} />
              <span className="w-24">
                <Progress value={job.processed / job.total} />
              </span>
            </span>
          ) : last ? (
            <span className="flex flex-wrap items-center gap-2">
              最近扫描 {fmtTime(last.startedAt)}
              <JobBadge status={last.status} />
            </span>
          ) : null}
          <Icon name="back" size={12} className="rotate-180 opacity-0 transition-opacity group-hover:opacity-100" />
        </a>
      </div>

      {/* 工具栏 */}
      <div className="mt-5 flex flex-col-reverse gap-3 md:flex-row md:items-center md:justify-between">
        <div className="-mx-4 flex gap-1 overflow-x-auto px-4 md:mx-0 md:px-0">
          {filters.map(([k, label]) => (
            <button
              key={k}
              onClick={() => setF(k)}
              className={`flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors sm:h-8 ${
                f === k ? 'bg-ink text-white' : 'text-ink-2 hover:bg-well hover:text-ink'
              }`}
            >
              {label}
              <span className={`text-xs tabular-nums ${f === k ? 'text-white/60' : 'text-muted'}`}>{count[k]}</span>
            </button>
          ))}
        </div>
        <label className="relative block md:w-64">
          <Icon name="search" size={15} className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索人物"
            className="h-10 w-full rounded-lg bg-card pr-3 pl-9 text-sm ring-1 ring-line outline-none placeholder:text-muted focus:ring-moss/60 sm:h-9"
          />
        </label>
      </div>

      {/* 画廊 */}
      {shown.length === 0 ? (
        <div className="mt-10 flex flex-col items-center rounded-xl border border-dashed border-line-2 px-6 py-20 text-center">
          <Icon name="person" size={28} className="text-line-2" />
          <div className="mt-3 text-[15px] font-medium">{state.settings.folders.length ? '没有符合条件的人物' : '请先选择图库目录'}</div>
          <p className="mt-1 max-w-sm text-[13px] text-muted">
            {state.settings.folders.length === 0 ? '选择一个或多个文件夹，再手动扫描其中的照片。' : q.trim() ? `未找到名称包含“${q.trim()}”的人物。` : '当前筛选下暂无人物。每个已选文件夹单独作为一个图库。'}
          </p>
          {state.settings.folders.length ? <Button className="mt-5" size="sm" onClick={() => (setQ(''), setF('all'))}>清除筛选</Button> : <a href="#/settings" className="mt-5 text-sm font-medium text-moss">选择文件夹</a>}
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-5 sm:gap-y-8 md:grid-cols-3 xl:grid-cols-4">
          {shown.map(({ p }) => (
            <PersonCard key={p.id} person={p} settings={state.settings} />
          ))}
        </div>
      )}
    </div>
  )
}

function PersonCard({ person, settings }: { person: Person; settings: Settings }) {
  const d = derive(person, settings)
  const b = d.baseline
  const st = modeStatus(d)
  return (
    <a href={`#/person/${person.id}`} className="group block rounded-xl outline-offset-4">
      <PhotoCanvas
        url={b?.url ?? null}
          thumbnailUrl={b?.thumbnailUrl}
        alt={`${person.name} 当前基线`}
        zoomable={false}
        className="aspect-[4/5] transition-shadow group-hover:shadow-[0_10px_30px_-14px_rgba(0,0,0,0.35)] sm:aspect-auto sm:h-[290px]"
        empty={{ title: '缺少可靠基线', note: d.scored.length ? `${d.scored.length} 张照片均未达标` : '暂无可用单人照片', tone: 'amber' }}
      >
        {d.mode === 'locked' && (
          <span className="absolute top-2 left-2 grid size-6 place-items-center rounded-md bg-white/90 text-ink shadow-sm" title="已锁定">
            <Icon name="lock" size={13} />
          </span>
        )}
      </PhotoCanvas>
      <div className="mt-2.5 px-0.5">
        <div className="mb-1 truncate text-[11px] text-muted" title={person.directory}>{person.directory}</div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[15px] font-medium group-hover:text-moss">{person.name}</span>
          {b && <span className={`text-[15px] font-semibold tabular-nums ${d.reliable ? 'text-ink' : 'text-amber'}`}>{b.score}</span>}
        </div>
        <div className="mt-1 flex items-center justify-between gap-2">
          <StatusText tone={st.tone} className="truncate">
            {st.label}
          </StatusText>
          <span className="shrink-0 text-xs text-muted">{person.photos.length} 张</span>
        </div>
        {d.writebackIssues.length > 0 ? (
          <div className="mt-1 flex items-center gap-1 text-xs text-amber">
            <Icon name="alert" size={12} />
            写回待修复 · {d.writebackIssues.length} 张
          </div>
        ) : (
          <div className="mt-1 text-xs text-muted">扫描于 {fmtTime(person.lastScan)}</div>
        )}
      </div>
    </a>
  )
}
