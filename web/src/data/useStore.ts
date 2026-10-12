import { useSyncExternalStore } from 'react'
import { api } from './api'

export function useAppState() {
  return useSyncExternalStore(api.subscribe, api.getState)
}
export function useActiveJob() {
  const s = useAppState()
  return s.jobs.find((j) => j.status === 'queued' || j.status === 'running') ?? null
}
export const BUSY_REASON = '扫描进行中，为避免与文件写回冲突，完成后再操作'
