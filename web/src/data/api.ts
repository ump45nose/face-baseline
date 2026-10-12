import type { AppState, FolderListing, ScanJob, Settings } from './types'

class HttpBaselineApi {
  private state: AppState = {
    settings: { folders: [], k: 5, threshold: 60 },
    people: [], jobs: [], loaded: false, error: null, libraryAvailable: false, engine: '',
  }
  private subs = new Set<() => void>()
  private timer: ReturnType<typeof setTimeout> | null = null
  getState = () => this.state
  subscribe = (cb: () => void) => {
    this.subs.add(cb)
    if (this.subs.size === 1) void this.poll()
    return () => {
      this.subs.delete(cb)
      if (this.subs.size === 0 && this.timer) clearTimeout(this.timer)
    }
  }
  private publish() { this.subs.forEach(cb => cb()) }
  private async request(path: string, method = 'GET', body?: unknown) {
    const response = await fetch('/api' + path, {
      method, headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const result = await response.json()
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求未成功，请检查输入')
    return result
  }
  private async refresh() {
    const result: AppState = await this.request('/state')
    if (JSON.stringify(result.settings) === JSON.stringify(this.state.settings)) result.settings = this.state.settings
    this.state = { ...result, loaded: true, error: null }
    this.publish()
  }
  private async poll() {
    try { await this.refresh() }
    catch (error) {
      this.state = { ...this.state, error: error instanceof Error ? error.message : String(error) }
      this.publish()
    }
    if (this.subs.size) this.timer = setTimeout(() => void this.poll(), 2000)
  }
  async lock(personId: string, photoId: string) {
    await this.request(`/people/${personId}/lock`, 'POST', { photoId })
    await this.refresh()
  }
  async unlock(personId: string) {
    await this.request(`/people/${personId}/unlock`, 'POST')
    await this.refresh()
  }
  async saveSettings(settings: Settings) {
    await this.request('/settings', 'PUT', settings)
    await this.refresh()
  }
  async browseFolders(path?: string): Promise<FolderListing> {
    return this.request('/folders' + (path ? '?path=' + encodeURIComponent(path) : ''))
  }
  async startScan(scope: 'all' | string): Promise<{ merged: boolean; job: ScanJob }> {
    const result = await this.request('/scans', 'POST', { scope })
    await this.refresh()
    return result
  }
}

export const api = new HttpBaselineApi()
