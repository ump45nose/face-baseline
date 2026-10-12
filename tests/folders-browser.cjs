const fs = require('node:fs/promises')
const path = require('node:path')
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

async function main() {
  const [baseUrl, root, output] = process.argv.slice(2)
  await fs.mkdir(output, { recursive: true })
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const state = () => page.request.get(baseUrl + '/api/state').then(response => response.json())
  const before = await state()
  const directories = (await (await page.request.get(baseUrl + '/api/folders', { params: { path: root } })).json()).directories
  assert(directories.length >= 2)
  assert.deepEqual([...before.settings.folders].sort(), directories.map(d => d.path).sort())
  const openPicker = async () => {
    await page.getByRole('button', { name: '选择文件夹', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '选择图库文件夹', exact: true })
    await dialog.getByRole('button', { name: '打开 ' + root, exact: true }).click()
    await dialog.getByRole('checkbox', { name: '选择 ' + directories[0].name, exact: true }).waitFor()
    return dialog
  }
  try {
    await page.goto(baseUrl + '/#/settings', { waitUntil: 'networkidle' })
    let dialog = await openPicker()
    assert.equal(await dialog.locator('input:checked').count(), directories.length)
    await page.screenshot({ path: path.join(output, 'desktop-picker.png') })
    await dialog.getByRole('button', { name: '清空选择', exact: true }).click()
    for (const directory of directories.slice(0, 2)) {
      await dialog.getByRole('checkbox', { name: '选择 ' + directory.name, exact: true }).check()
    }
    await dialog.getByRole('button', { name: '使用所选目录（2）', exact: true }).click()
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('button') && [...document.querySelectorAll('button')].some(b => b.textContent === '保存设置' && b.disabled))
    const two = await state()
    assert.deepEqual(two.settings.folders, directories.slice(0, 2).map(d => d.path))
    assert.equal(two.people.length, 2)
    assert.deepEqual(two.jobs, before.jobs)
    dialog = await openPicker()
    await dialog.getByRole('button', { name: '全选本层文件夹', exact: true }).click()
    await dialog.getByRole('button', { name: `使用所选目录（${directories.length}）`, exact: true }).click()
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === '保存设置' && b.disabled))
    const restored = await state()
    assert.deepEqual([...restored.settings.folders].sort(), [...before.settings.folders].sort())
    assert.deepEqual(restored.people, before.people)
    assert.deepEqual(restored.jobs, before.jobs)
    await page.screenshot({ path: path.join(output, 'desktop-settings.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    dialog = await openPicker()
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    assert(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth))
    await page.screenshot({ path: path.join(output, 'mobile-picker.png') })
    await dialog.getByRole('button', { name: '清空选择', exact: true }).click()
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    assert.deepEqual((await state()).settings, restored.settings)
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ selected: directories.length, multiSelect: true, restore: true, noAutomaticScan: true, mobileOverflow: false, pageErrors: errors }))
  } finally {
    await page.request.put(baseUrl + '/api/settings', { data: before.settings })
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
