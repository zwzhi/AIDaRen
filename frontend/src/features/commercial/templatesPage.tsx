/**
 * 商业模板库（设计体系版·校准完善轮）。
 * 交互：上传解析 → 概览行 + 展开编辑（秒展示/毫秒存储）→ 原片预览时间定位 → 发布；
 * 复用 AppShell / pf-* / Button；素材预览走鉴权 blob，不公开私有存储。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Film, UploadCloud } from 'lucide-react'
import Button from '../../components/ui/Button'
import { API_BASE, requestResponse } from '../../api/client'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { commercialApi, uploadAsset, type TemplateItem } from './api'
import './commercial.css'

/** 校准分镜（存储为毫秒，展示为秒，转换不取整）。 */
type CalibShot = {
  shot_id: string
  start_ms: number
  end_ms: number
  observation: string
  inference: string
  dialogue_template: string
}

/** 变量内部名 → 用户中文名（仅展示层映射，不改字段）。 */
const VARIABLE_LABELS: Record<string, string> = {
  opening_question: '开场提问',
  approved_core_claim: '审核卖点',
  closing_cta: '结尾引导',
}
const varLabel = (v: string) => VARIABLE_LABELS[v] ?? v

const msToSec = (ms: number) => ms / 1000
const timecode = (ms: number) => {
  const s = ms / 1000
  const m = Math.floor(s / 60)
  return `${String(m).padStart(2, '0')}:${(s - m * 60).toFixed(1).padStart(4, '0')}`
}

export default function CommercialTemplatesPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [msg, setMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const [analysis, setAnalysis] = useState<{ runId: number } | null>(null)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [calib, setCalib] = useState<CalibShot[]>([])
  const [openShot, setOpenShot] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [expandedTech, setExpandedTech] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  const refresh = useCallback(() => {
    setLoading(true); setErrorMsg('')
    commercialApi.listTemplates()
      .then(r => setTemplates(r.items))
      .catch(e => setErrorMsg(String(e instanceof Error ? e.message : e)))
      .finally(() => setLoading(false))
  }, [])
  useEffect(refresh, [refresh])

  // 未保存校准提示（刷新/离开不静默丢失）
  useEffect(() => {
    if (!calib.length) return
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [calib.length])

  // 鉴权加载原片为 blob 预览（不经公开地址）
  const loadVideoPreview = useCallback(async (assetId: number) => {
    try {
      const resp = await fetch(`${API_BASE}/api/commercial/assets/${assetId}/download`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      })
      if (!resp.ok) return
      const blob = await resp.blob()
      setVideoUrl(URL.createObjectURL(blob))
    } catch { /* 预览失败不阻塞校准 */ }
  }, [])

  const onUpload = async (file: File) => {
    setUploading(true); setErrorMsg(''); setMsg('')
    try {
      const asset = await uploadAsset(file, 'reference_source_video', '页面上传·确认有权使用')
      void loadVideoPreview(asset.id)
      const resp = await requestResponse(`/api/commercial/sources/by-asset/${asset.id}`, { method: 'POST' })
      const sourceId = ((await resp.json()) as { source_id: number }).source_id
      const run = await commercialApi.analyze(sourceId)
      const detail = await commercialApi.getAnalysis(run.analysis_run_id)
      if (detail.status !== 'completed' || !detail.result?.shots?.length) {
        setErrorMsg(detail.status === 'failed' ? `解析失败：${detail.error ?? ''}` : '解析未返回镜头，请重试')
        return
      }
      setAnalysis({ runId: run.analysis_run_id })
      setCalib(detail.result.shots.map(s => ({
        shot_id: String(s.shot_id),
        start_ms: Number(s.start_ms) || 0,
        end_ms: Number(s.end_ms) || 0,
        observation: String(s.observation ?? ''),
        inference: String(s.inference ?? ''),
        dialogue_template: '',
      })))
      setOpenShot(0)
      setMsg(`解析完成：${detail.result.shots.length} 个镜头，请逐镜校准后发布。`)
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  const patchShot = (idx: number, patch: Partial<CalibShot>) =>
    setCalib(prev => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))

  const patchTime = (idx: number, key: 'start_ms' | 'end_ms', raw: string) => {
    const value = Number(raw)
    const decimals = raw.includes('.') ? raw.split('.')[1]?.length ?? 0 : 0
    if (!Number.isFinite(value) || raw.trim() === '') { setErrorMsg('时间必须是有限数字'); return }
    if (decimals > 3) { setErrorMsg('时间最多支持 3 位小数（毫秒精度）'); return }
    patchShot(idx, { [key]: Math.round(value * 1000) })
    setErrorMsg('')
  }

  const seekTo = (ms: number) => {
    if (videoRef.current) videoRef.current.currentTime = msToSec(ms)
  }

  const publish = async () => {
    if (!analysis) return
    try {
      await commercialApi.createTemplate(name || '未命名模板', analysis.runId, calib as never[])
      setMsg('模板已发布（V1）')
      setName(''); setAnalysis(null); setCalib([]); setOpenShot(null)
      if (videoUrl) { URL.revokeObjectURL(videoUrl); setVideoUrl(null) }
      refresh()
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e))
    }
  }

  const totalCalibMs = calib.reduce((acc, s) => acc + Math.max(0, s.end_ms - s.start_ms), 0)

  return (
    <CommercialLayout>
      <CommercialPageHead
        title="商业模板库"
        desc="上传有权使用的参考短视频，解析一次、人工校准分镜后发布为可复用模板；后续换达人 / 商品 / 文案不再重新解析。"
      />
      <MockModeNote onToggleTech={() => setExpandedTech(v => !v)} techOpen={expandedTech} />

      <div className="pf-card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <input ref={fileRef} type="file" accept="video/mp4,video/quicktime" hidden
            onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = '' }} />
          <Button variant="lime" onClick={() => fileRef.current?.click()} disabled={uploading}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <UploadCloud size={16} aria-hidden />{uploading ? '上传与解析中…' : '上传参考视频并解析'}
            </span>
          </Button>
          <span className="pf-muted" style={{ fontSize: 13 }}>
            MP4 / MOV，≤500MB，建议 30–180 秒且包含对白；仅用于分析与人工校准，不会进入生成请求。
          </span>
        </div>
        {msg && <p style={{ color: 'var(--pf-ink)', margin: '10px 0 0', fontSize: 13 }}>{msg}</p>}
        {errorMsg && <p style={{ color: '#b3261e', margin: '10px 0 0', fontSize: 13 }}>{errorMsg}</p>}
      </div>

      {analysis && calib.length > 0 && (
        <div className="pf-card" style={{ padding: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>分镜校准（共 {calib.length} 镜 · 合计 {(totalCalibMs / 1000).toFixed(1)}s）</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input className="cv-input" style={{ width: 220 }} placeholder="模板名称"
                value={name} onChange={e => setName(e.target.value)} />
              <Button variant="lime" onClick={publish}>发布模板 V1</Button>
            </div>
          </div>

          {/* 原片预览（鉴权 blob）：点击镜头行定位到对应时间 */}
          {videoUrl && (
            <div style={{ marginBottom: 14 }}>
              <video ref={videoRef} className="cv-media-preview" src={videoUrl} controls
                style={{ maxHeight: 300, width: '100%', maxWidth: 480 }} preload="metadata" />
              <p className="pf-muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
                原片仅用于校准参考（鉴权加载）；点击镜头行可定位到对应时间。
              </p>
            </div>
          )}

          {/* 概览 + 展开编辑：桌面与窄屏同构，核心编辑不依赖横向宽表 */}
          {calib.map((s, i) => {
            const open = openShot === i
            return (
              <div key={s.shot_id} className="cv-shot">
                <div className="cv-shot-head" onClick={() => { setOpenShot(open ? null : i); if (!open) seekTo(s.start_ms) }}>
                  {open ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
                  <strong style={{ minWidth: 36 }}>{s.shot_id}</strong>
                  <span className="pf-muted" style={{ fontSize: 13 }}>
                    {timecode(s.start_ms)} → {timecode(s.end_ms)}（{((s.end_ms - s.start_ms) / 1000).toFixed(1)}s）
                  </span>
                  <span style={{ fontSize: 13, flex: 1, minWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.observation || '—'}
                  </span>
                </div>
                {open && (
                  <div className="cv-shot-body">
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      <div className="cv-field" style={{ margin: 0, width: 130 }}>
                        <label>开始（秒）</label>
                        <input className="cv-input compact" type="number" step="0.001" min="0"
                          value={msToSec(s.start_ms)}
                          onChange={e => patchTime(i, 'start_ms', e.target.value)} />
                      </div>
                      <div className="cv-field" style={{ margin: 0, width: 130 }}>
                        <label>结束（秒）</label>
                        <input className="cv-input compact" type="number" step="0.001" min="0"
                          value={msToSec(s.end_ms)}
                           onChange={e => patchTime(i, 'end_ms', e.target.value)} />
                      </div>
                      <Button variant="outline" size="sm" onClick={() => seekTo(s.start_ms)}>定位到原片</Button>
                    </div>
                    <div className="cv-field">
                      <label>画面观察（事实，可长文）</label>
                      <textarea className="cv-textarea" value={s.observation}
                        onChange={e => patchShot(i, { observation: e.target.value })} />
                    </div>
                    <div className="cv-field">
                      <label>内容作用（推断，可长文）</label>
                      <textarea className="cv-textarea" value={s.inference}
                        onChange={e => patchShot(i, { inference: e.target.value })} />
                    </div>
                    <div className="cv-field">
                      <label>台词模板（可留空，如 {'{{开场提问}}'}）</label>
                      <textarea className="cv-textarea" style={{ minHeight: 48 }} value={s.dialogue_template}
                        onChange={e => patchShot(i, { dialogue_template: e.target.value })} />
                    </div>
                  </div>
                )}
              </div>
            )
          })}
          <p className="pf-muted" style={{ fontSize: 12, marginTop: 10 }}>
            时间以秒展示、毫秒存储；校准仅保存文字结构与时间码，原片与关键帧仅用于分析（INV-01），不会成为生成素材。
          </p>
        </div>
      )}

      <div className="pf-template-grid">
        {loading && <p className="pf-muted">加载模板中…</p>}
        {templates.map(t => {
          const v = t.versions[0]
          const count = v?.shot_count ?? 0
          const dur = v?.total_duration_ms ?? 0
          return (
            <div key={t.id} className="pf-template-card" style={{ cursor: 'default', display: 'flex', flexDirection: 'column' }}>
              <div style={{
                aspectRatio: '16 / 10', display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 6,
                background: 'var(--pf-lime-soft)', color: 'var(--pf-muted)', fontSize: 12,
              }}>
                <Film size={28} aria-hidden />
                <span>解析校准模板 · 暂无封面</span>
                <span>{count} 镜 · {(dur / 1000).toFixed(0)}s</span>
              </div>
              <div className="body" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                <h3>{t.name}</h3>
                <p className="pf-muted" style={{ fontSize: 13, flex: 1 }}>
                  已发布 {t.versions.length} 个版本；当前 V{t.current_version}
                  {v?.variables?.length ? ` · ${v.variables.map(varLabel).join(' / ')}` : ''}
                </p>
                <div className="pf-tags">
                  <span>{v?.status === 'published' ? '已发布' : (v?.status ?? '—')}</span>
                  <span>复用免重解析</span>
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <Button variant="lime" size="sm" to={`/commercial/studio?template=${v?.id ?? ''}`}>
                    使用模板
                  </Button>
                  <Button variant="outline" size="sm" to={`/commercial/templates/${v?.id ?? ''}`}>
                    查看详情
                  </Button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      {!loading && !errorMsg && templates.length === 0 && !analysis && (
        <p className="pf-muted" style={{ padding: '24px 0', textAlign: 'center' }}>
          还没有模板。上传一条参考视频开始第一次解析。
        </p>
      )}
    </CommercialLayout>
  )
}
