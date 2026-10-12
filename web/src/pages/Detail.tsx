import { useState, type ReactNode } from 'react'
import { api } from '../data/api'
import { derive, displayName, fmtTime, reasons, statusText, formatScore, modelName, type Derived } from '../data/logic'
import { BUSY_REASON, useActiveJob, useAppState } from '../data/useStore'
import { Badge, Button, DownloadButton, Meter, PhotoCanvas, StatusText, Tabs, useUI } from '../components/ui'
import Icon from '../components/icons'
import { modeStatus, useScanAction } from './Overview'
import type { Person, Photo, Settings } from '../data/types'

type Tab = 'top' | 'all' | 'history'

export default function Detail({ id }: { id: string }) {
  const state = useAppState()
  const job = useActiveJob()
  const scan = useScanAction()
  const { toast } = useUI()
  const [tab, setTab] = useState<Tab>('top')
  const person = state.people.find((p) => p.id === id)
  if (!person)
    return (
      <div className="py-24 text-center">
        <div className="font-medium">找不到该人物</div>
        <a href="#/" className="mt-2 inline-block text-[13px] text-moss">
          返回人物图库
        </a>
      </div>
    )
  const s = state.settings
  const d = derive(person, s)
  const busy = !!job
  const st = modeStatus(d)

  const lock = async (ph: Photo) => {
    if (busy) return toast(BUSY_REASON, 'amber')
    await api.lock(person.id, ph.id)
    !ph.qualified ? toast('已锁定。该照片质量不足，将持续显示警示', 'amber') : toast('已设为基线并锁定')
  }
  const unlock = async () => {
    await api.unlock(person.id)
    toast('已取消锁定，恢复自动选择')
  }
  const bad = person.photos.length - d.scored.length

  return (
    <div>
      {/* 头部 */}
      <nav className="flex items-center gap-1.5 text-[13px] text-muted">
        <a href="#/" className="-ml-1 inline-flex h-8 items-center gap-1 rounded-md px-1 hover:text-ink">
          <Icon name="back" size={14} />
          人物图库
        </a>
        <span>/</span>
        <span className="text-ink-2">{person.name}</span>
      </nav>
      <header className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="text-[26px] font-semibold tracking-tight sm:text-[28px]">{person.name}</h1>
            <StatusText tone={st.tone} className="text-[13px]">
              {st.label}
            </StatusText>
          </div>
          <p className="mt-1 text-[13px] text-muted">
            可选单人照片 {d.scored.length} 张 · 共 {person.photos.length} 张 · 最近扫描 {fmtTime(person.lastScan)}
          </p>
        </div>
        <Button icon={busy ? 'refresh' : 'scan'} onClick={() => scan(person.id)} className="w-full sm:w-auto">
          {busy ? '扫描进行中…' : '扫描此人物'}
        </Button>
      </header>

      {person.pendingOperations.length > 0 && <div role="status" className="mt-4 rounded-lg bg-amber-soft p-3 text-sm text-amber">有 {person.pendingOperations.length} 项文件操作待修复。{person.pendingOperations.find(o => o.error)?.error}</div>}
      <p className="mt-3 break-all text-xs text-muted">{person.directory}{!person.available && <span className="text-amber"> · 目录不可用</span>}</p>
      <Workbench person={person} d={d} s={s} busy={busy} onUnlock={unlock} />

      <section className="mt-10">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            ['top', `候选 Top ${s.k}`, d.top.length],
            ['all', '全部照片', person.photos.length],
            ['history', '基线历史', person.history.length],
          ]}
        />
        <div className="pt-5">
          {tab === 'top' && <TopView d={d} s={s} busy={busy} onLock={lock} />}
          {tab === 'all' && <AllView person={person} d={d} s={s} busy={busy} onLock={lock} bad={bad} />}
          {tab === 'history' && <HistoryView person={person} />}
        </div>
      </section>
    </div>
  )
}

/* ---------- 查看区 + 检查器 ---------- */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[64px_1fr] gap-3 py-1.5 text-[13px]">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-all text-ink">{children}</dd>
    </div>
  )
}

function Workbench({ person, d, s, busy, onUnlock }: { person: Person; d: Derived; s: Settings; busy: boolean; onUnlock: () => void }) {
  const b = d.baseline
  const ver = person.history[0]
  return (
    <div className="mt-6 grid overflow-hidden rounded-xl bg-card ring-1 ring-line lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="border-b border-line bg-[#f6f5f1] p-3 sm:p-4 lg:border-r lg:border-b-0">
        <PhotoCanvas
          url={b?.url ?? null}
          thumbnailUrl={b?.thumbnailUrl}
          faceBox={b?.assessmentFace}
          imageSize={b?.imageSize}
          alt={`${person.name} 当前基线`}
          className="aspect-[4/5] sm:aspect-auto sm:h-[440px] lg:h-full lg:min-h-[440px]"
          empty={{
            title: '缺少可靠基线',
            note: d.scored.length ? '可在下方候选中手动锁定，或补充更清晰的正脸照片' : '暂无可评分的单人照片',
            tone: 'amber',
          }}
        />
      </div>

      <aside className="flex flex-col p-5 sm:p-6">
        <div className="text-xs font-medium tracking-wider text-muted">当前基线</div>
        {b ? (
          <>
            <div className="mt-3 flex items-end justify-between">
              <div className="flex items-baseline gap-1.5">
                <span className={`text-[44px] leading-none font-semibold tracking-tight tabular-nums ${d.reliable ? '' : 'text-amber'}`}>{formatScore(b.score)}</span>
                <span className="text-xs text-muted">/ 100</span>
              </div>
              <div className="flex flex-col items-end gap-1">
                {d.mode === 'locked' ? <Badge tone="ink" icon="lock">已锁定</Badge> : <Badge tone="moss">自动选择</Badge>}
                {d.reliable ? <Badge tone="moss" icon="check">合格</Badge> : <Badge tone="amber" icon="alert">质量不足</Badge>}
              </div>
            </div>
            <div className="mt-3">
              <Meter value={b.score!} threshold={s.thresholds[b.model]} />
              <div className="mt-1.5 text-[11px] text-muted">{modelName(b.model)} 总分 · 合格门槛 {s.thresholds[b.model]}</div>
            </div>
            {!d.reliable && (
              <div className="mt-4 rounded-lg bg-amber-soft px-3 py-2.5 text-[13px] leading-relaxed text-amber">
                <span className="font-medium">缺少可靠基线。</span>该照片未通过全部质量检查，仅作为手动选择保留。
              </div>
            )}

            <p className="mt-3 text-[11px] text-muted">绿色框标出实际评分人脸。{modelName(b.model)} 总分独立计算，下方 OFIQ 分项用于检查基线适用性。</p>
            {b.qualityIssues.length > 0 && <ul className="mt-3 space-y-1 text-xs text-amber">{b.qualityIssues.map(issue => <li key={issue}>{issue}</li>)}</ul>}

            <div className="mt-5 space-y-2.5 border-t border-line pt-4">
              {reasons(b).map((r) => (
                <div key={r.label} className="grid grid-cols-[56px_1fr_26px] items-center gap-3 text-xs">
                  <span className="text-ink-2">{r.label}</span>
                  <Meter value={r.value} tone={r.value < 50 ? 'amber' : 'moss'} />
                  <span className="text-right text-muted tabular-nums">{r.value}</span>
                </div>
              ))}
            </div>

            <dl className="mt-5 border-t border-line pt-3">
              <Row label="引擎">{b.engine}</Row>
              <Row label="文件名">{displayName(b, true)}</Row>
              <Row label="写回">
                {b.writeback === 'failed' ? (
                  <span className="text-amber">写回待修复 · 手动扫描可重试</span>
                ) : (
                  <span className="text-moss">已写回</span>
                )}
              </Row>
              <Row label="版本">
                v{ver?.version}
                <span className="text-muted"> · {ver && fmtTime(ver.at)}</span>
              </Row>
              {d.lockedOutOfTop && (
                <Row label="排名">
                  第 {d.rankOf.get(b.id)} 名<span className="text-muted"> · 不在 Top {s.k}，锁定仍有效</span>
                </Row>
              )}
            </dl>

            <details className="mt-3 text-xs text-muted">
              <summary className="cursor-pointer">完整评分记录</summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-well p-2 text-[10px]">{JSON.stringify(b.metrics, null, 2)}</pre>
            </details>
            <div className="mt-auto flex flex-col gap-2 pt-5 sm:flex-row lg:flex-col">
              <DownloadButton url={b.url} fileName={displayName(b, true)} className="sm:flex-1 [&>button]:w-full">
                下载基线照片
              </DownloadButton>
              {d.mode === 'locked' && (
                <Button variant="ghost" icon="unlock" onClick={onUnlock} disabled={busy} title={busy ? BUSY_REASON : undefined} className="sm:flex-1">
                  取消锁定，恢复自动
                </Button>
              )}
            </div>
            {busy && d.mode === 'locked' && <p className="mt-2 text-xs text-muted">{BUSY_REASON}</p>}
          </>
        ) : (
          <div className="mt-3 flex flex-1 flex-col">
            <div className="text-[22px] font-semibold text-amber">缺少可靠基线</div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
              {d.scored.length
                ? `${d.scored.length} 张已复核单人照片未能通过全部质量检查。可在候选或全部照片中查看原因、手动锁定，或补充更清晰的正脸照片。`
                : '暂无通过新版单人复核的照片。旧结果需重新扫描；无脸、多人或评分失败的照片不能作为基线。'}
            </p>
            <dl className="mt-5 border-t border-line pt-3">
              <Row label="最高分">{d.top[0] ? `${formatScore(d.top[0].score)} 分` : '—'}</Row>
              <Row label="门槛">{s.threshold} 分</Row>
            </dl>
            {person.lockedPhotoId && <Button variant="ghost" icon="unlock" onClick={onUnlock} disabled={busy} className="mt-5">取消锁定，恢复自动</Button>}
          </div>
        )}
      </aside>
    </div>
  )
}

/* ---------- 候选卡 ---------- */
function Candidate({ p, rank, d, s, busy, onLock, dup }: { p: Photo; rank?: number; d: Derived; s: Settings; busy: boolean; onLock: (p: Photo) => void; dup?: number }) {
  const [open, setOpen] = useState(false)
  const scored = p.eligible
  const isLocked = d.locked?.id === p.id
  const isBase = d.baseline?.id === p.id
  const pass = p.qualified
  return (
    <div className="group flex flex-col">
      <PhotoCanvas
        url={p.url}
        thumbnailUrl={p.thumbnailUrl}
        faceBox={p.assessmentFace}
        imageSize={p.imageSize}
        alt={p.name}
        dim={!scored}
        className={`aspect-[4/5] sm:aspect-auto sm:h-[250px] ${isBase ? 'ring-2 ring-moss ring-offset-2 ring-offset-paper' : ''}`}
        empty={{ title: statusText[p.status] }}
      >
        {rank != null && (
          <span className="absolute top-2 left-2 grid h-6 min-w-6 place-items-center rounded-md bg-white/92 px-1.5 text-xs font-semibold tabular-nums shadow-sm">{rank}</span>
        )}
        {isLocked ? (
          <span className="absolute top-2 right-2 flex h-6 items-center gap-1 rounded-md bg-ink px-1.5 text-[11px] font-medium text-white">
            <Icon name="lock" size={11} strokeWidth={2} />
            已锁定
          </span>
        ) : isBase ? (
          <span className="absolute top-2 right-2 flex h-6 items-center rounded-md bg-moss px-1.5 text-[11px] font-medium text-white">当前基线</span>
        ) : null}
      </PhotoCanvas>

      <div className="mt-2.5 flex flex-1 flex-col px-0.5">
        {scored ? (
          <>
            <div className="flex items-baseline justify-between gap-2">
              <span className={`text-[17px] font-semibold tabular-nums ${pass ? '' : 'text-amber'}`}>{formatScore(p.score)}</span>
              <StatusText tone={pass ? 'moss' : 'amber'}>{pass ? '合格' : '质量不足'}</StatusText>
            </div>
            <div className="mt-0.5 truncate text-xs text-muted" title={p.name}>
              {p.name}
              {dup ? ` · 合并 ${dup} 张相同图像` : ''}
            </div>
            {p.writeback === 'failed' && (
              <div className="mt-1 flex items-center gap-1 text-xs text-amber">
                <Icon name="alert" size={12} />
                写回待修复
              </div>
            )}
            <button
              onClick={() => setOpen(!open)}
              aria-expanded={open}
              className="mt-1.5 -ml-1 flex h-8 items-center gap-1 self-start rounded px-1 text-xs text-ink-2 hover:text-ink"
            >
              质量检查
              <Icon name="chevron" size={12} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>
            {open && (
              <ul className="mb-2 space-y-1.5 rounded-lg bg-well/70 p-2.5">
                <li className="text-[11px] text-muted">{modelName(p.model)} 总分独立计算；OFIQ 分项用于检查基线适用性。</li>
                {p.qualityIssues.map(issue => <li key={issue} className="text-xs text-amber">{issue}</li>)}
                {reasons(p).map((r) => (
                  <li key={r.label} className="flex justify-between gap-2 text-xs">
                    <span className="text-ink-2">{r.label}</span>
                    <span className={`text-right ${r.value < 50 ? 'text-amber' : 'text-muted'}`}>
                      {r.note} · {r.value}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-auto">
              {isLocked ? (
                <div className="flex h-9 items-center gap-1.5 text-xs text-ink-2 sm:h-8">
                  <Icon name="check" size={13} />
                  已锁定为基线
                </div>
              ) : (
                <Button
                  size="sm"
                  icon="lock"
                  className="w-full transition-opacity lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100 lg:group-focus-within:opacity-100"
                  disabled={busy}
                  title={busy ? BUSY_REASON : undefined}
                  onClick={() => onLock(p)}
                >
                  设为基线并锁定
                </Button>
              )}
            </div>
          </>
        ) : (
          <>
            <StatusText tone={p.status === 'incomplete' || p.status === 'ok' ? 'amber' : 'danger'}>{p.status === 'ok' ? '待重新核对' : statusText[p.status]}</StatusText>
            <div className="mt-0.5 truncate text-xs text-muted">{p.name}</div>
            <div className="mt-1 text-xs text-muted">{p.status === 'incomplete' ? '下次扫描时自动重试' : '不能设为基线'}</div>
            <p className="mt-1 break-words text-xs text-amber">{p.qualityIssues.join('；')}</p>
          </>
        )}
      </div>
    </div>
  )
}

const grid = 'grid grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-4 md:grid-cols-3 lg:grid-cols-5'

function TopView({ d, s, busy, onLock }: { d: Derived; s: Settings; busy: boolean; onLock: (p: Photo) => void }) {
  return (
    <div>
      {d.top.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line-2 px-6 py-14 text-center text-[13px] text-muted">暂无已评分的单人照片，候选为空。</div>
      ) : (
        <div className={grid}>
          {d.top.map((p, i) => (
            <Candidate key={p.id} p={p} rank={i + 1} d={d} s={s} busy={busy} onLock={onLock} dup={d.dupOf.get(p.id)} />
          ))}
        </div>
      )}
      {d.lockedOutOfTop && d.locked && (
        <div className="mt-10 border-t border-line pt-6">
          <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Icon name="lock" size={14} />
              锁定照片
            </h3>
            <span className="text-[13px] text-muted">
              {d.locked.eligible ? `排名第 ${d.rankOf.get(d.locked.id)}，不在 Top ${s.k}；锁定选择保持不变` : d.baseline?.id === d.locked.id ? '锁定照片等待当前模型复核，原基线继续保留' : '锁定记录保留；通过当前检测复核后才能作为基线'}
            </span>
          </div>
          <div className={grid}>
            <Candidate p={d.locked} rank={d.rankOf.get(d.locked.id)} d={d} s={s} busy={busy} onLock={onLock} />
          </div>
        </div>
      )}
    </div>
  )
}

function AllView({ person, d, s, busy, onLock, bad }: { person: Person; d: Derived; s: Settings; busy: boolean; onLock: (p: Photo) => void; bad: number }) {
  const [only, setOnly] = useState(false)
  const rest = person.photos.filter((p) => !p.eligible)
  const list = only ? d.scored : [...d.scored, ...rest]
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted">
        <span>
          可选 <span className="text-ink">{d.scored.length}</span> 张 · 不可作为基线 <span className="text-ink">{bad}</span> 张（无脸、多人、解码或评分失败）
        </span>
        <label className="flex h-9 cursor-pointer items-center gap-2 text-ink-2">
          <input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} className="size-4 accent-[#2d5b47]" />
          仅显示可选照片
        </label>
      </div>
      <div className={grid}>
        {list.map((p) => (
          <Candidate key={p.id} p={p} rank={d.rankOf.get(p.id)} d={d} s={s} busy={busy} onLock={onLock} />
        ))}
      </div>
    </div>
  )
}

function HistoryView({ person }: { person: Person }) {
  return (
    <ol className="relative">
      {person.history.map((h, i) => (
        <li key={h.version} className="relative flex gap-4 pb-6 pl-6 last:pb-0">
          {i < person.history.length - 1 && <span className="absolute top-3 bottom-0 left-[5px] w-px bg-line" />}
          <span className={`absolute top-1.5 left-0 size-[11px] rounded-full ring-[3px] ring-paper ${i === 0 ? 'bg-moss' : 'bg-line-2'}`} />
          <div className="w-14 shrink-0 sm:w-16">
            <PhotoCanvas url={h.snapshotUrl} alt={`v${h.version} 快照`} className="aspect-[4/5]" empty={{ title: '无' }} />
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">v{h.version}</span>
                {i === 0 && <Badge tone="moss">当前</Badge>}
                <span className="text-xs text-muted">
                  {h.mode === 'locked' ? '锁定' : h.mode === 'auto' ? '自动' : '缺少可靠基线'} · {fmtTime(h.at)}
                </span>
              </div>
              <div className="mt-1 text-[13px] text-ink">{h.reason}</div>
              {h.fileName && (
                <div className="mt-0.5 truncate text-xs text-muted">
                  {h.fileName} · {modelName(h.model)} {formatScore(h.score)} 分
                </div>
              )}
            </div>
            {h.snapshotUrl && (
              <DownloadButton size="sm" variant="ghost" url={h.snapshotUrl} fileName={`v${h.version}_${h.fileName}`}>
                下载快照
              </DownloadButton>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
