export type PhotoStatus = 'ok' | 'no_face' | 'multi_face' | 'decode_failed' | 'score_failed' | 'incomplete'
export type WritebackState = 'ok' | 'failed' | 'none'

export interface SubScores {
  sharpness: number | null
  lighting: number | null
  eyes: number | null
  pose: number | null
  occlusion: number | null
}

export interface Photo {
  id: string
  name: string // 原始文件名
  fileName: string
  thumbnailUrl: string | null
  metrics: Record<string, unknown>
  engine: string | null
  error: string | null
  url: string | null
  status: PhotoStatus
  score: number | null
  sub: SubScores | null
  hash: string
  addedAt: number
  writeback: WritebackState
  retries?: number
}

export interface HistoryEntry {
  version: number
  at: number
  reason: string
  mode: 'auto' | 'locked' | 'none'
  photoId: string | null
  fileName: string | null
  score: number | null
  snapshotUrl: string | null
}

export interface Person {
  id: string
  name: string
  photos: Photo[]
  lockedPhotoId: string | null
  baselineId: string | null
  mode: string
  pendingOperations: { id: number; kind: string; photo_id: string; error: string | null }[]
  lastScan: number
  history: HistoryEntry[]
}

export interface Settings {
  root: string
  k: number
  threshold: number
}

export type JobStatus = 'queued' | 'running' | 'done' | 'partial' | 'failed'

export interface ScanJob {
  id: string
  scope: 'all' | string
  scopeLabel: string
  trigger: 'manual' | 'cron'
  status: JobStatus
  processed: number
  total: number
  startedAt: number
  finishedAt: number | null
  merged: number
  scored: number
  fileProcessed: number
  fileTotal: number
  log: { level: 'info' | 'warn' | 'error'; text: string }[]
}

export interface AppState {
  settings: Settings
  people: Person[]
  jobs: ScanJob[] // newest first
  loaded: boolean
  error: string | null
  libraryAvailable: boolean
  engine: string
}
