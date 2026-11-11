import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..', 'src')
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), 'utf8')

test('studio uses a real adapt-section id and shot_key for planned shots', () => {
  const source = read('features', 'commercial', 'studioPage.tsx')
  assert.match(source, /productionId && detail && \(\s*<div id="cv-section-adapt"/)
  assert.match(source, /key=\{s\.shot_key \|\| `shot-\$\{index \+ 1\}`\}/)
  assert.match(source, /<strong[^>]*>\{s\.shot_key \|\| `shot-\$\{index \+ 1\}`\}<\/strong>/)
  assert.doesNotMatch(source, /key=\{s\.shot_id\}/)
})

test('successful redo clears its dialogue draft before refreshing', () => {
  const source = read('features', 'commercial', 'studioPage.tsx')
  assert.match(source, /setRedoDialogue\(prev => \{[\s\S]*delete next\[u\.unit_key\]/)
})

test('task downloads report network failures and burning disables the button while busy', () => {
  const source = read('features', 'commercial', 'workPages.tsx')
  assert.match(source, /try \{[\s\S]*fetch\(.*exports\//)
  assert.match(source, /下载失败，请检查网络后重试/)
  assert.match(source, /const \[burning, setBurning\] = useState\(false\)/)
  assert.match(source, /disabled=\{burning\}/)
  assert.match(source, /finally \{ setBurning\(false\) \}/)
})

test('settings distinguishes forbidden administrators and hides budget editing for regular users', () => {
  const source = read('features', 'commercial', 'workPages.tsx')
  assert.match(source, /providerForbidden/)
  assert.match(source, /status === 403/)
  assert.match(source, /管理员权限/)
  assert.match(source, /providerForbidden \?/) 
  assert.match(source, /providerForbidden[\s\S]*需要管理员权限查看和编辑预算/)
  assert.match(source, /<Button variant="lime" onClick=\{setBudget\}>保存<\/Button>/)
})

test('cancelling template editing restores the entry snapshot', () => {
  const source = read('features', 'commercial', 'templateDetail.tsx')
  assert.match(source, /editSnapshotRef/)
  assert.match(source, /setDraftShots\(editSnapshotRef\.current/)
})

test('budget scope is optional and omitted from the display when absent', () => {
  const api = read('features', 'commercial', 'api.ts')
  const page = read('features', 'commercial', 'workPages.tsx')
  assert.match(api, /scope\?: string/)
  assert.match(page, /pool\.scope \? `（scope=\$\{pool\.scope\}）` : ''/)
})

test('non-commercial auth keeps language switching and returns logout to the public home', () => {
  const auth = read('pages', 'AuthPage.tsx')
  const nav = read('components', 'layout', 'SiteNav.tsx')
  assert.match(auth, /!COMMERCIAL_PROJECT && <LanguageSwitch \/>/)
  assert.match(nav, /nav\(COMMERCIAL_PROJECT \? '\/auth' : '\/'\)/)
})
