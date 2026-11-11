/**
 * 模板版本详情：完整结构（含内部字段名）只读展示 + 使用入口。
 * 数据来自 GET /api/commercial/templates/{versionId}（冻结快照）。
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Button from '../../components/ui/Button'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { request } from './templatesApi'

type VersionDetail = {
  version_id: number; template_id: number; template_name: string
  version: number; status: string
  structure: { shots?: Array<Record<string, unknown>>; variables?: string[] } | null
  source_available: boolean; published_at: string | null
}

const timecode = (ms: number) => {
  const s = ms / 1000
  const m = Math.floor(s / 60)
  return `${String(m).padStart(2, '0')}:${(s - m * 60).toFixed(1).padStart(4, '0')}`
}

export default function TemplateVersionDetail() {
  const { versionId } = useParams()
  const [detail, setDetail] = useState<VersionDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!versionId) return
    request<VersionDetail>(`/api/commercial/templates/${versionId}`)
      .then(setDetail)
      .catch(e => setError(String(e instanceof Error ? e.message : e)))
  }, [versionId])

  return (
    <CommercialLayout>
      <CommercialPageHead
        title={detail ? `${detail.template_name} · V${detail.version}` : '模板版本详情'}
        desc="已发布版本的冻结快照；历史作品继续引用此版本，编辑需发布新版本。"
      />
      <MockModeNote />
      {error && <p style={{ color: '#b3261e' }}>{error}</p>}
      {!detail && !error && <p className="pf-muted">加载中…</p>}
      {detail && (
        <>
          <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="pf-tags"><span>{detail.status === 'published' ? '已发布' : detail.status}</span></span>
              <span className="pf-muted" style={{ fontSize: 13 }}>
                发布于 {detail.published_at?.slice(0, 19).replace('T', ' ') ?? '—'}
              </span>
              <span className="pf-muted" style={{ fontSize: 13 }}>
                原片复查：{detail.source_available ? '可用' : '不可用（源已删除或撤销）'}
              </span>
              <span style={{ flex: 1 }} />
              <Button variant="lime" size="sm" to={`/commercial/studio?template=${detail.version_id}`}>使用此版本</Button>
            </div>
          </div>
          {(detail.structure?.shots ?? []).map(shot => {
            const s = shot as Record<string, unknown>
            return (
              <div key={String(s.shot_id)} className="pf-card" style={{ padding: 14, marginBottom: 10 }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <strong>{String(s.shot_id)}</strong>
                  <span className="pf-muted" style={{ fontSize: 13 }}>
                    {timecode(Number(s.start_ms) || 0)} → {timecode(Number(s.end_ms) || 0)}
                  </span>
                </div>
                <dl style={{ margin: '8px 0 0', fontSize: 13, display: 'grid', gap: 4 }}>
                  {(['observation', 'inference', 'dialogue_template', 'action_template'] as const).map(k => (
                    s[k] ? <div key={k} style={{ display: 'flex', gap: 8 }}>
                      <dt className="pf-muted" style={{ minWidth: 96 }}>{{
                        observation: '画面观察', inference: '内容作用',
                        dialogue_template: '台词模板', action_template: '动作模板',
                      }[k]}（{k}）</dt>
                      <dd style={{ margin: 0 }}>{String(s[k])}</dd>
                    </div> : null
                  ))}
                </dl>
              </div>
            )
          })}
          <p className="pf-muted" style={{ fontSize: 12 }}>
            <Link to="/commercial/templates">← 返回模板库</Link>；内部字段名（如 dialogue_template）保留在详情中，制作页展示使用中文名称。
          </p>
        </>
      )}
    </CommercialLayout>
  )
}
