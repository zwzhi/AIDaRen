/**
 * 合成选版纯逻辑：按计划单元挑选“最新审核通过”的尝试并检测缺失。
 * 从任务页组件抽出，便于对“缺镜头阻断→补齐→可再次合成”做回归测试。
 * （用户明确选择采用版本的能力属第三轮；当前保持“最新合格”语义不变。）
 */
export type ComposeUnit = {
  unit_key: string
  adopt_ranges?: Array<[string, number, number]>
}

export type ComposeAttempt = {
  id: number
  unit_key?: string | null
  status: string
}

export type ComposeSelection = { attempt_id: number; ranges: number[][] }

export type ComposePlan =
  | { ok: true; selections: ComposeSelection[] }
  | { ok: false; missing: string[] }

/** 每个必需单元取最新 REVIEW_APPROVED 尝试；任一单元缺失 → ok:false 列出缺失。 */
export function buildComposeSelections(units: ComposeUnit[], attempts: ComposeAttempt[]): ComposePlan {
  const selections: ComposeSelection[] = []
  const missing: string[] = []
  for (const unit of units) {
    const mine = attempts
      .filter(a => a.unit_key === unit.unit_key && a.status === 'REVIEW_APPROVED')
      .sort((x, y) => y.id - x.id)
    if (!mine.length) { missing.push(unit.unit_key); continue }
    selections.push({
      attempt_id: mine[0].id,
      ranges: (unit.adopt_ranges || []).map(([, s, e]) => [s, e]),
    })
  }
  if (missing.length) return { ok: false, missing }
  return { ok: true, selections }
}
