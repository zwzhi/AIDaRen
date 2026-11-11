import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), 'utf8')

test('replication API exposes the staged commercial endpoints and typed modes', () => {
  const source = read('src', 'features', 'commercial', 'replicationApi.ts')
  assert.match(source, /structural_rewrite/)
  assert.match(source, /high_fidelity/)
  for (const endpoint of ['replications', 'analyze', 'shot-graph', 'scripts', 'approve']) {
    assert.match(source, new RegExp(endpoint))
  }
  assert.match(source, /production_id/)
})

test('replication page presents route evidence and the staged workflow', () => {
  const source = read('src', 'features', 'commercial', 'replicationPages.tsx')
  for (const label of ['结构改写', '高保真复刻', '推荐原因', '风险', '预计']) {
    assert.match(source, new RegExp(label))
  }
  for (const stage of ['分析', 'Shot Graph', '脚本', '锚帧', '声音', '预览']) {
    assert.match(source, new RegExp(stage))
  }
  assert.match(source, /scriptApproved/)
  assert.match(source, /disabled=\{!scriptApproved \|\|/)
  assert.match(source, /production_id/)
})

test('replication route is registered without replacing existing commercial routes', () => {
  const source = read('src', 'App.tsx')
  assert.match(source, /replicationPages/)
  assert.match(source, /path="\/commercial\/replications"/)
  assert.match(source, /path="\/commercial\/studio"/)
})
