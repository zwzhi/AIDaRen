/**
 * 商业模板库（接回 PRINTFILM 设计体系版）。
 * 流程与数据链路不变：上传参考片 → 解析 → 分镜校准编辑 → 发布版本；
 * UI 复用 AppShell / pf-template-grid / pf-template-card / pf-field / Button。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Film, UploadCloud } from 'lucide-react'
import Button from '../../components/ui/Button'
import { requestResponse } from '../../api/client'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { commercialApi, uploadAsset, type TemplateItem } from './api'

/** 校准中的分镜行（解析结果 → 可编辑）。 */
type CalibShot = {
  shot_id: string
  start_ms: number
  end_ms: number
  observation: string
  inference: string
  dialogue_template: string
}

export default function CommercialTemplatesPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [uploading, setUploading] = useState(false)
  const [msg, setMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  // 校准区：解析完成后的镜头编辑状态
  const [analysis, setAnalysis] = useState<{ runId: number } | null>(null)
  const [calib, setCalib] = useState<CalibShot[]>([])
  const [name, setName] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    commercialApi.listTemplates()
      .then(r => setTemplates(r.items))
      .catch(e => setErrorMsg(String(e instanceof Error ? e.message : e)))
  }, [])
  useEffect(refresh, [refresh])

  const onUpload = async (file: File) => {
    setUploading(true); setErrorMsg(''); setMsg('')
    try {
      const asset = await uploadAsset(file, 'reference_source_video', '页面上传·确认有权使用')
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
      setMsg(`解析完成：${detail.result.shots.length} 个镜头，请逐镜校准后发布。`)
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  const patchShot = (idx: number, patch: Partial<CalibShot>) => {
    setCalib(prev => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  }

  const publish = async () => {
    if (!analysis) return
    // 校验：时间码必须递增且为正
    for (const s of calib) {
      if (s.end_ms <= s.start_ms) { setErrorMsg(`镜头 ${s.shot_id} 的结束时间必须大于开始时间`); return }
    }
    try {
      await commercialApi.createTemplate(name || '未命名模板', analysis.runId, calib as never[])
      setMsg('模板已发布（V1）')
      setName(''); setAnalysis(null); setCalib([]); refresh()
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
      <MockModeNote />

      {/* 上传与解析（主操作） */}
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

      {/* 分镜校准编辑（真实编辑能力：时间码 / 观察 / 推断 / 台词模板） */}
      {analysis && calib.length > 0 && (
        <div className="pf-card" style={{ padding: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>分镜校准（共 {calib.length} 镜 · 合计 {(totalCalibMs / 1000).toFixed(1)}s）</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input className="pf-search" style={{ maxWidth: 220 }} placeholder="模板名称"
                value={name} onChange={e => setName(e.target.value)} />
              <Button variant="lime" onClick={publish}>发布模板 V1</Button>
            </div>
          </div>
          <div className="pf-field" style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: 720 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--pf-muted)' }}>
                  <th style={{ padding: '6px 8px' }}>镜头</th>
                  <th style={{ padding: '6px 8px' }}>开始(ms)</th>
                  <th style={{ padding: '6px 8px' }}>结束(ms)</th>
                  <th style={{ padding: '6px 8px' }}>画面观察（事实）</th>
                  <th style={{ padding: '6px 8px' }}>内容作用（推断）</th>
                  <th style={{ padding: '6px 8px' }}>台词模板（可留空）</th>
                </tr>
              </thead>
              <tbody>
                {calib.map((s, i) => (
                  <tr key={s.shot_id} style={{ borderTop: '1px solid var(--pf-line)' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 600 }}>{s.shot_id}</td>
                    <td style={{ padding: '4px 8px' }}>
                      <input className="pf-search" style={{ width: 84 }} type="number" value={s.start_ms}
                        onChange={e => patchShot(i, { start_ms: Number(e.target.value) })} />
                    </td>
                    <td style={{ padding: '4px 8px' }}>
                      <input className="pf-search" style={{ width: 84 }} type="number" value={s.end_ms}
                        onChange={e => patchShot(i, { end_ms: Number(e.target.value) })} />
                    </td>
                    <td style={{ padding: '4px 8px' }}>
                      <input className="pf-search" style={{ width: '100%' }} value={s.observation}
                        onChange={e => patchShot(i, { observation: e.target.value })} />
                    </td>
                    <td style={{ padding: '4px 8px' }}>
                      <input className="pf-search" style={{ width: '100%' }} value={s.inference}
                        onChange={e => patchShot(i, { inference: e.target.value })} />
                    </td>
                    <td style={{ padding: '4px 8px' }}>
                      <input className="pf-search" style={{ width: '100%' }} placeholder="如 {{开场提问}}"
                        value={s.dialogue_template}
                        onChange={e => patchShot(i, { dialogue_template: e.target.value })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="pf-muted" style={{ fontSize: 12, marginTop: 8 }}>
            校准仅保存文字结构与时间码；原片与关键帧仅用于分析（INV-01），不会成为生成素材。
          </p>
        </div>
      )}

      {/* 模板卡片网格 */}
      <div className="pf-template-grid">
        {templates.map(t => {
          const v = t.versions[0]
          const count = v?.shot_count ?? 0
          const dur = v?.total_duration_ms ?? 0
          return (
            <div key={t.id} className="pf-template-card" style={{ cursor: 'default' }}>
              {/* 无封面占位：明确状态，不编造画面 */}
              <div style={{
                aspectRatio: '16 / 10', display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 6,
                background: 'var(--pf-lime-soft)', color: 'var(--pf-muted)', fontSize: 12,
              }}>
                <Film size={28} aria-hidden />
                <span>解析校准模板 · 暂无封面</span>
                <span>{count} 镜 · {(dur / 1000).toFixed(0)}s</span>
              </div>
              <div className="body">
                <h3>{t.name}</h3>
                <p className="pf-muted" style={{ fontSize: 13 }}>
                  已发布 {t.versions.length} 个版本；当前 V{t.current_version}
                  {v?.variables?.length ? ` · 变量 ${v.variables.join(' / ')}` : ''}
                </p>
                <div className="pf-tags">
                  <span>{v?.status === 'published' ? '已发布' : (v?.status ?? '—')}</span>
                  <span>复用免重解析</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      {templates.length === 0 && !analysis && (
        <p className="pf-muted" style={{ padding: '24px 0', textAlign: 'center' }}>
          还没有模板。上传一条参考视频开始第一次解析。
        </p>
      )}
    </CommercialLayout>
  )
}
