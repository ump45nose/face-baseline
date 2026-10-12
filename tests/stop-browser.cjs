const fs = require('node:fs/promises')
const path = require('node:path')
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

async function main() {
  const [baseUrl, personId, output] = process.argv.slice(2)
  await fs.mkdir(output, { recursive: true })
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const before = await (await page.request.get(baseUrl + '/api/people/' + personId)).json()
    await page.goto(baseUrl + '/#/settings', { waitUntil: 'networkidle' })
    await page.getByRole('heading', { name: '图库目录', exact: true }).waitFor()
    const response = await page.request.post(baseUrl + '/api/scans', { data: { scope: personId } })
    assert.equal(response.status(), 202)
    const { job } = await response.json()
    const stop = page.getByRole('button', { name: '停止扫描', exact: true })
    await stop.waitFor()
    await page.screenshot({ path: path.join(output, 'stop-button.png') })
    await stop.click()
    await page.getByRole('button', { name: '继续扫描所选图库', exact: true }).waitFor({ timeout: 45000 })
    const cancelled = await (await page.request.get(baseUrl + '/api/scans/' + job.id)).json()
    assert.equal(cancelled.status, 'cancelled')
    assert.equal(cancelled.cancelRequested, true)
    assert.equal(cancelled.scored, 0)
    const after = await (await page.request.get(baseUrl + '/api/people/' + personId)).json()
    assert.deepEqual(after.photos.map(p => p.id).sort(), before.photos.map(p => p.id).sort())
    assert.equal(after.baselineId, before.baselineId)
    assert.equal(after.lockedPhotoId, before.lockedPhotoId)
    assert.deepEqual(after.history, before.history)
    await page.screenshot({ path: path.join(output, 'stopped.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    await page.screenshot({ path: path.join(output, 'mobile-stopped.png') })
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ jobId: job.id, status: cancelled.status, scored: cancelled.scored,
      fileProcessed: cancelled.fileProcessed, baselinePreserved: true, historyPreserved: true,
      horizontalOverflow: false, pageErrors: errors }))
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
