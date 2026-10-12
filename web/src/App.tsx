import { useEffect, useState } from 'react'
import { UIProvider, Progress } from './components/ui'
import Icon, { type IconName } from './components/icons'
import Overview from './pages/Overview'
import Detail from './pages/Detail'
import SettingsPage from './pages/Settings'
import { useActiveJob, useAppState } from './data/useStore'

function useHash() {
  const [h, setH] = useState(() => window.location.hash.slice(1) || '/')
  useEffect(() => {
    const f = () => {
      setH(window.location.hash.slice(1) || '/')
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  return h
}

function Brand() {
  return (
    <a href="#/" className="flex items-center gap-2.5">
      <span className="relative grid size-8 place-items-center rounded-[9px] bg-ink text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.15)]">
        <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
          <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
          <ellipse cx="12" cy="12" rx="3.6" ry="4.4" />
        </svg>
        <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-[#5f9a7c] ring-2 ring-side" />
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-wide">人脸基线</span>
        <span className="block text-[11px] tracking-wider text-muted">Face Baseline</span>
      </span>
    </a>
  )
}

export default function App() {
  return (
    <UIProvider>
      <Shell />
    </UIProvider>
  )
}

function Shell() {
  const route = useHash()
  const job = useActiveJob()
  const state = useAppState()
  const person = route.match(/^\/person\/(\w+)/)?.[1]
  const tab = route.startsWith('/settings') ? 'settings' : 'people'
  const nav: [string, string, string, IconName, number?][] = [
    ['people', '#/', '人物图库', 'gallery', state.people.length],
    ['settings', '#/settings', '扫描与设置', 'settings'],
  ]

  return (
    <div className="min-h-screen lg:pl-[216px]">
      {/* 桌面侧栏 */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[216px] flex-col border-r border-line bg-side lg:flex">
        <div className="px-5 pt-6 pb-7">
          <Brand />
        </div>
        <div className="px-3">
          <div className="px-2 pb-1.5 text-[11px] font-medium tracking-wider text-muted">图库</div>
          <nav className="space-y-0.5">
            {nav.map(([k, href, label, icon, count]) => (
              <a
                key={k}
                href={href}
                className={`flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors ${
                  tab === k ? 'bg-card font-medium text-ink shadow-[0_1px_2px_rgba(0,0,0,0.05)] ring-1 ring-line' : 'text-ink-2 hover:bg-black/[0.035] hover:text-ink'
                }`}
              >
                <Icon name={icon} size={15} className={tab === k ? 'text-moss' : 'text-muted'} />
                <span className="flex-1">{label}</span>
                {count != null && <span className="text-xs text-muted tabular-nums">{count}</span>}
              </a>
            ))}
          </nav>
        </div>
        <div className="mt-auto space-y-3 p-3">
          {job && (
            <a href="#/settings" className="block rounded-lg bg-card p-2.5 ring-1 ring-line">
              <div className="mb-1.5 flex justify-between text-xs">
                <span className="font-medium text-moss">{job.status === 'queued' ? '等待中' : '扫描中'}</span>
                <span className="text-muted tabular-nums">
                  {job.processed}/{job.total}
                </span>
              </div>
              <Progress value={job.processed / job.total} />
            </a>
          )}
          <div className="rounded-lg px-2 py-1.5">
            <div className="flex items-center gap-1.5 text-xs text-ink-2">
              <span className="size-1.5 rounded-full bg-moss" />
              {state.settings.folders.length === 0 ? '尚未选择图库' : state.libraryAvailable ? '图库已连接' : '有目录不可用'}
            </div>
            <div className="mt-1 truncate text-[11px] text-muted" title={state.settings.folders.join('\n')}>
              {state.settings.folders.length} 个已选目录
            </div>
          </div>

        </div>
      </aside>

      {/* 手机顶栏 */}
      <header className="sticky top-0 z-30 border-b border-line bg-paper/92 backdrop-blur lg:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <Brand />

        </div>
        <nav className="flex gap-1 px-3 pb-2">
          {nav.map(([k, href, label, icon]) => (
            <a
              key={k}
              href={href}
              className={`flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg text-[13px] ${tab === k ? 'bg-card font-medium text-ink ring-1 ring-line' : 'text-ink-2'}`}
            >
              <Icon name={icon} size={14} />
              {label}
            </a>
          ))}
        </nav>
        {job && (
          <div className="px-4 pb-2">
            <Progress value={job.processed / job.total} />
          </div>
        )}
      </header>

      {state.error && <div role="alert" className="mx-4 mt-4 rounded-lg bg-danger-soft p-3 text-sm text-danger">{state.error}</div>}
      <main className="mx-auto max-w-[1240px] px-4 pt-6 pb-24 sm:px-8 lg:px-10 lg:pt-9">
        {!state.loaded ? <p className="py-20 text-center text-muted">正在读取图库档案…</p> : tab === 'settings' ? <SettingsPage /> : person ? <Detail id={person} /> : <Overview />}
      </main>


    </div>
  )
}
