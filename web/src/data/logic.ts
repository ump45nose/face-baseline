import type { Person, Photo, Settings, PhotoStatus } from './types'

export const BASELINE_PREFIX = '基线__'
export const modelName = (model: 'faceqnet' | 'ofiq') => model === 'faceqnet' ? 'FaceQnet' : 'OFIQ'
export const formatScore = (score: number | null) => score == null ? '—' : Number.isInteger(score) ? String(score) : score.toFixed(1)

export function isScored(p: Photo) {
  return p.eligible
}

export const statusText: Record<PhotoStatus, string> = {
  ok: '单人',
  no_face: '未检测到人脸',
  multi_face: '多人照片',
  face_mismatch: '评分人脸位置不一致',
  decode_failed: '解码失败',
  score_failed: '评分失败',
  incomplete: '文件未写完，待下次重试',
}

export interface Derived {
  scored: Photo[]
  top: Photo[]
  dupOf: Map<string, number> // photoId -> 合并的相同图像数量
  autoPick: Photo | null
  locked: Photo | null
  baseline: Photo | null
  mode: 'auto' | 'locked' | 'missing'
  reliable: boolean
  lockedOutOfTop: boolean
  rankOf: Map<string, number>
  writebackIssues: Photo[]
}

export function derive(person: Person, s: Settings): Derived {
  const scored = person.photos.filter(isScored).sort((a, b) => Number(b.qualified) - Number(a.qualified) || b.score! - a.score! || Number(a.id !== person.lockedPhotoId) - Number(b.id !== person.lockedPhotoId) || a.addedAt - b.addedAt || a.id.localeCompare(b.id))
  const seen = new Map<string, Photo>()
  const dupOf = new Map<string, number>()
  const unique: Photo[] = []
  for (const p of scored) {
    const first = seen.get(p.hash)
    if (first) dupOf.set(first.id, (dupOf.get(first.id) ?? 0) + 1)
    else {
      seen.set(p.hash, p)
      unique.push(p)
    }
  }
  const rankOf = new Map(unique.map((p, i) => [p.id, i + 1]))
  const top = scored.filter(p => p.rank !== null).sort((a, b) => a.rank! - b.rank!)
  const autoPick = top.find((p) => p.qualified) ?? null
  const locked = person.lockedPhotoId ? (person.photos.find((p) => p.id === person.lockedPhotoId) ?? null) : null
  const baseline = person.photos.find(p => p.id === person.baselineId) ?? null
  return {
    scored,
    top,
    dupOf,
    autoPick,
    locked,
    baseline,
    mode: person.lockedPhotoId ? 'locked' : baseline ? 'auto' : 'missing',
    reliable: !!baseline && baseline.qualified,
    lockedOutOfTop: !!locked && !top.some((p) => p.id === locked.id),
    rankOf,
    writebackIssues: person.photos.filter((p) => p.writeback === 'failed'),
  }
}

export function displayName(p: Photo, isBaseline: boolean) {
  return p.fileName
}

export function reasons(p: Photo): { label: string; value: number; note: string }[] {
  if (!p.sub) return []
  const n = (v: number | null, good: string, bad: string) => (v == null ? '无法评估' : v >= 70 ? good : v >= 50 ? '一般' : bad)
  const rows = [
    { label: '清晰度', value: p.sub.sharpness, note: n(p.sub.sharpness, '对焦清晰', '存在模糊') },
    { label: '光照', value: p.sub.lighting, note: n(p.sub.lighting, '光照均匀', '过暗或阴影明显') },
    { label: '眼睛可见', value: p.sub.eyes, note: n(p.sub.eyes, '双眼清楚可见', '眼睛被遮挡或闭眼') },
    { label: '头部偏航', value: p.sub.pose, note: n(p.sub.pose, '接近正脸', '侧脸角度较大') },
    { label: '遮挡', value: p.sub.occlusion, note: n(p.sub.occlusion, '面部无遮挡', '面部有遮挡') },
  ]
  return rows.filter((r): r is {label: string; value: number; note: string} => r.value != null)
}

export function fmtTime(ts: number) {
  if (!ts) return '尚未扫描'
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
