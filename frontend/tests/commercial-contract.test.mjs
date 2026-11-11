import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const read = (file) => fs.readFileSync(path.join(root, 'src', 'features', 'commercial', file), 'utf8')

test('commercial studio uses capability resolutions and product version row ids', () => {
  const source = read('studioPage.tsx')
  assert.match(source, /getCapabilities\(\)/)
  assert.match(source, /resolution_id: sel\.resolution/)
  assert.match(source, /p\.latest_version_id/)
  assert.doesNotMatch(source, /value=\{p\.current_version\}/)
})

test('commercial pages distinguish loading from empty state', () => {
  for (const file of ['templatesPage.tsx', 'libraryPages.tsx', 'workPages.tsx']) {
    const source = read(file)
    assert.match(source, /loading/)
    assert.match(source, /加载/) 
  }
})

test('commercial mode banner reads health status instead of claiming mock unconditionally', () => {
  const source = read('CommercialLayout.tsx')
  assert.match(source, /getHealth\(\)/)
  assert.match(source, /运行模式未确认/)
  assert.doesNotMatch(source, /当前为本地演示：生成与费用均为模拟数据/)
})
