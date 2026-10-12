import { useEffect, useRef, useState } from 'react'
import { api } from '../data/api'
import type { FolderListing } from '../data/types'
import { Button } from './ui'
import Icon from './icons'

const contains = (parent: string, child: string) => parent === child || child.startsWith(parent.replace(/\/$/, '') + '/')

export default function FolderPicker({ value, onApply, onClose }: {
  value: string[]; onApply: (folders: string[]) => void; onClose: () => void
}) {
  const [selected, setSelected] = useState([...value])
  const [listing, setListing] = useState<FolderListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(0)
  const open = async (path?: string) => {
    const id = ++request.current
    setLoading(true); setError('')
    try {
      const result = await api.browseFolders(path)
      if (id === request.current) setListing(result)
    } catch (error) {
      if (id === request.current) setError(error instanceof Error ? error.message : String(error))
    } finally { if (id === request.current) setLoading(false) }
  }
  useEffect(() => {
    void open()
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', key)
    return () => { ++request.current; window.removeEventListener('keydown', key) }
  }, [])
  const blocked = (path: string) => selected.some(p => p !== path && (contains(p, path) || contains(path, p)))
  const toggle = (path: string) => setSelected(selected.includes(path) ? selected.filter(p => p !== path) : [...selected, path])
  const chooseLevel = () => {
    if (!listing) return
    const available = listing.directories.filter(d => d.available && !blocked(d.path)).map(d => d.path)
    setSelected([...new Set([...selected, ...available])])
  }
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/20 p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="选择图库文件夹">
      <div className="flex max-h-[90vh] w-full max-w-[720px] flex-col overflow-hidden rounded-2xl bg-card shadow-xl ring-1 ring-line">
        <div className="flex items-start justify-between gap-3 border-b border-line p-5">
          <div>
            <h2 className="text-lg font-semibold">选择图库文件夹</h2>
            <p className="mt-1 text-xs text-muted">可多选。每个选中的目录单独作为一个图库，包含目录内的照片和子目录。</p>
          </div>
          <button aria-label="关闭文件夹选择器" onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-lg hover:bg-well"><Icon name="x" size={18} /></button>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
          <Button size="sm" disabled={loading} onClick={() => open(listing?.parent ?? undefined)} icon="back">上一级</Button>
          <div className="min-w-0 flex-1 break-all text-xs text-muted">{listing?.path ?? '可选位置'}</div>
        </div>
        <div className="flex items-center justify-between border-b border-line px-5 py-2">
          <span className="text-xs text-muted">已选 {selected.length} 个目录</span>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" disabled={loading || !listing?.directories.length} onClick={chooseLevel}>全选本层文件夹</Button>
            <Button variant="ghost" size="sm" disabled={!selected.length} onClick={() => setSelected([])}>清空选择</Button>
          </div>
        </div>
        <div className="min-h-32 flex-1 overflow-y-auto px-3 py-2">
          {error && <p role="alert" className="break-words p-3 text-sm text-danger">{error}</p>}
          {loading ? <p className="p-5 text-center text-sm text-muted">正在读取文件夹…</p> : listing?.directories.map(directory => {
            const disabled = !directory.available || blocked(directory.path)
            return (
              <div key={directory.path} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-paper">
                <input type="checkbox" aria-label={`选择 ${directory.name}`} checked={selected.includes(directory.path)} disabled={disabled} onChange={() => toggle(directory.path)} className="size-4 shrink-0 accent-[#2d5b47]" />
                <button disabled={!directory.available} onClick={() => open(directory.path)} className="min-w-0 flex-1 text-left disabled:opacity-50">
                  <span className="block truncate text-sm">{directory.name}</span>
                  {disabled && <span className="block text-[11px] text-muted">{!directory.available ? '目录不可用' : '与已选父级或子级目录重叠'}</span>}
                </button>
                <button aria-label={`打开 ${directory.name}`} disabled={!directory.available} onClick={() => open(directory.path)} className="grid size-9 shrink-0 place-items-center rounded-md text-muted hover:bg-well"><Icon name="chevron" size={16} className="-rotate-90" /></button>
              </div>
            )
          })}
          {!loading && !error && listing?.directories.length === 0 && <p className="p-5 text-center text-sm text-muted">没有子文件夹；可在上一级勾选这个目录。</p>}
        </div>
        <div className="border-t border-line bg-paper px-5 py-3">
          <p className="text-[11px] text-muted">父子目录只选一个，避免重复归类。取消选择不会删除原照片、评分或历史。</p>
          <div className="mt-3 flex justify-end gap-2"><Button onClick={onClose}>取消</Button><Button variant="primary" onClick={() => { onApply(selected); onClose() }}>使用所选目录（{selected.length}）</Button></div>
        </div>
      </div>
    </div>
  )
}
