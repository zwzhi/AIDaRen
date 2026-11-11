/** 第一轮回归：合成选版纯逻辑（缺镜头阻断→补齐→可再次合成）。 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { buildComposeSelections } from '../src/features/commercial/composeSelection.ts'

const U = (key, ranges) => ({ unit_key: key, adopt_ranges: ranges ?? [['S', 0, 4000]] })
const A = (id, key, status) => ({ id, unit_key: key, status })

test('缺镜头 → ok:false 列出缺失单元，不产生任何选版', () => {
  const plan = buildComposeSelections(
    [U('U1'), U('U2'), U('U3')],
    [A(1, 'U1', 'REVIEW_APPROVED')],
  )
  assert.equal(plan.ok, false)
  assert.deepEqual(plan.missing, ['U2', 'U3'])
})

test('补齐缺失镜头后同一函数立即给出完整选版（阻断可恢复）', () => {
  const units = [U('U1'), U('U2')]
  const before = buildComposeSelections(units, [A(1, 'U1', 'REVIEW_APPROVED')])
  assert.equal(before.ok, false)
  // 补齐 U2 后无需任何刷新/重置即可成功
  const after = buildComposeSelections(units, [
    A(1, 'U1', 'REVIEW_APPROVED'),
    A(9, 'U2', 'REVIEW_APPROVED'),
  ])
  assert.equal(after.ok, true)
  assert.deepEqual(after.selections, [
    { attempt_id: 1, ranges: [[0, 4000]] },
    { attempt_id: 9, ranges: [[0, 4000]] },
  ])
})

test('同单元多次尝试取最新合格版本（现有语义保持）', () => {
  const plan = buildComposeSelections(
    [U('U1')],
    [A(1, 'U1', 'REVIEW_REJECTED'), A(2, 'U1', 'REVIEW_APPROVED'), A(3, 'U1', 'REVIEW_APPROVED')],
  )
  assert.equal(plan.ok, true)
  assert.equal(plan.selections[0].attempt_id, 3)
})

test('驳回中的单元视为缺失（不静默跳过）', () => {
  const plan = buildComposeSelections([U('U1')], [A(1, 'U1', 'REVIEW_REJECTED')])
  assert.equal(plan.ok, false)
  assert.deepEqual(plan.missing, ['U1'])
})
