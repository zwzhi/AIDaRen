/**
 * 模板版本详情：完整结构（含内部字段名）只读展示 + 使用入口。
 * 数据来自 GET /api/commercial/templates/{versionId}（冻结快照）。
 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Button from '../../components/ui/Button'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { request } from './templatesApi'
import { commercialApi, type Shot } from './api'

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
  const nav = useNavigate()
  const [detail, setDetail] = useState<VersionDetail | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [draftShots, setDraftShots] = useState<Shot[]>([])
  const editSnapshotRef = useRef<Shot[] | null>(null)

  useEffect(() => {
    if (!versionId) return
    request<VersionDetail>(`/api/commercial/templates/${versionId}`)
      .then(d => {
        setDetail(d)
        try {
          const saved = localStorage.getItem(`commercial-template-draft:${d.version_id}`)
          setDraftShots(saved ? JSON.parse(saved) as Shot[] : (d.structure?.shots ?? []) as Shot[])
        } catch { setDraftShots((d.structure?.shots ?? []) as Shot[]) }
      })
      .catch(e => setError(String(e instanceof Error ? e.message : e)))
  }, [versionId])

  useEffect(() => {
    if (!editing) return
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [editing])

  useEffect(() => {
    if (!editing) return
    const guard = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      const link = target?.closest('a[href]') as HTMLAnchorElement | null
      if (!link || !link.getAttribute('href')?.startsWith('/')) return
      if (!window.confirm('当前模板草稿尚未发布，确定离开吗？')) event.preventDefault()
    }
    document.addEventListener('click', guard, true)
    return () => document.removeEventListener('click', guard, true)
  }, [editing])

  const patchShot = (index: number, patch: Partial<Shot>) => {
    setDraftShots(previous => previous.map((shot, i) => i === index ? { ...shot, ...patch } : shot))
  }

  const patchTime = (index: number, key: 'start_ms' | 'end_ms', raw: string) => {
    const value = Number(raw)
    const decimals = raw.includes('.') ? raw.split('.')[1]?.length ?? 0 : 0
    if (!Number.isFinite(value) || raw.trim() === '') { setMessage('时间必须是有限数字'); return }
    if (decimals > 3) { setMessage('时间最多支持 3 位小数（毫秒精度）'); return }
    patchShot(index, { [key]: Math.round(value * 1000) })
    setMessage('')
  }

  const publishV2 = async () => {
    if (!detail) return
    setSaving(true); setMessage('')
    try {
      const result = await commercialApi.publishTemplateVersion(detail.template_id, detail.version + 1, draftShots)
      localStorage.removeItem(`commercial-template-draft:${detail.version_id}`)
      setMessage(`已发布 V${result.version}，V${detail.version} 保持不变`)
      setEditing(false)
      const refreshed = await request<VersionDetail>(`/api/commercial/templates/${result.version_id}`)
      setDetail(refreshed); setDraftShots((refreshed.structure?.shots ?? []) as Shot[])
      // 地址同步到新发布的版本，刷新后仍停留在新版本（不留在旧版本 URL）
      nav(`/commercial/templates/${refreshed.version_id}`, { replace: true })
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) } finally { setSaving(false) }
  }

  const saveDraft = () => {
    if (!detail) return
    localStorage.setItem(`commercial-template-draft:${detail.version_id}`, JSON.stringify(draftShots))
    setMessage('草稿已保存在当前浏览器，发布前可继续修改')
  }

  return (
    <CommercialLayout>
      <CommercialPageHead
        title={detail ? `${detail.template_name} · V${detail.version}` : '模板版本详情'}
        desc="已发布版本的冻结快照；历史作品继续引用此版本，编辑需发布新版本。"
        backTo="/commercial/templates"
        backLabel="返回模板库"
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
              <Button variant="outline" size="sm" onClick={() => {
                if (editing) {
                  setDraftShots(editSnapshotRef.current ?? draftShots)
                  setEditing(false)
                  setMessage('')
                } else {
                  editSnapshotRef.current = draftShots.map(shot => ({ ...shot }))
                  setEditing(true)
                }
              }}>{editing ? '取消编辑' : '编辑并发布 V2'}</Button>
              <Button variant="lime" size="sm" to={`/commercial/studio?template=${detail.version_id}`}>使用此版本</Button>
            </div>
          </div>
          {(editing ? draftShots : (detail.structure?.shots ?? []) as Shot[]).map((shot, index) => {
            const s = shot as Record<string, unknown>
            return (
              <div key={String(s.shot_id)} className="pf-card" style={{ padding: 14, marginBottom: 10 }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <strong>{String(s.shot_id)}</strong>
                  <span className="pf-muted" style={{ fontSize: 13 }}>
                    {timecode(Number(s.start_ms) || 0)} → {timecode(Number(s.end_ms) || 0)}
                  </span>
                </div>
                  {editing ? <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
                    <label className="cv-field" style={{ margin: 0 }}>开始（秒）<input className="cv-input" type="number" min="0" step="0.001" value={Number(shot.start_ms) / 1000} onChange={e => patchTime(index, 'start_ms', e.target.value)} /></label>
                    <label className="cv-field" style={{ margin: 0 }}>结束（秒）<input className="cv-input" type="number" min="0" step="0.001" value={Number(shot.end_ms) / 1000} onChange={e => patchTime(index, 'end_ms', e.target.value)} /></label>
                    <label className="cv-field" style={{ margin: 0 }}>画面观察<textarea className="cv-textarea" value={String(shot.observation ?? '')} onChange={e => patchShot(index, { observation: e.target.value })} /></label>
                    <label className="cv-field" style={{ margin: 0 }}>内容作用<textarea className="cv-textarea" value={String(shot.inference ?? '')} onChange={e => patchShot(index, { inference: e.target.value })} /></label>
                    <label className="cv-field" style={{ margin: 0 }}>台词模板<textarea className="cv-textarea" value={String(shot.dialogue_template ?? '')} onChange={e => patchShot(index, { dialogue_template: e.target.value })} /></label>
                  </div> : <dl style={{ margin: '8px 0 0', fontSize: 13, display: 'grid', gap: 4 }}>
                  {(['observation', 'inference', 'dialogue_template', 'action_template'] as const).map(k => (
                    s[k] ? <div key={k} style={{ display: 'flex', gap: 8 }}>
                      <dt className="pf-muted" style={{ minWidth: 96 }}>{{
                        observation: '画面观察', inference: '内容作用',
                        dialogue_template: '台词模板', action_template: '动作模板',
                      }[k]}（{k}）</dt>
                      <dd style={{ margin: 0 }}>{String(s[k])}</dd>
                    </div> : null
                  ))}</dl>}
              </div>
            )
          })}
          {editing && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button variant="outline" disabled={saving} onClick={saveDraft}>保存草稿</Button>
            <Button variant="lime" disabled={saving} onClick={publishV2}>{saving ? '发布中…' : `保存并发布 V${detail.version + 1}`}</Button>
          </div>}
          {message && <p className="pf-muted" style={{ fontSize: 13 }}>{message}</p>}
          <p className="pf-muted" style={{ fontSize: 12 }}>
            <Link to="/commercial/templates">← 返回模板库</Link>；内部字段名（如 dialogue_template）保留在详情中，制作页展示使用中文名称。
          </p>
        </>
      )}
    </CommercialLayout>
  )
}
