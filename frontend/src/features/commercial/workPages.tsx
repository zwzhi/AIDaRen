/**
 * 任务与作品 / 设置与费用（设计体系版）。
 * - 任务页：作品列表入口（GET /productions，免手输 ID）+ 详情（镜头预览/审核/重做提示/导出下载）
 * - 设置页：安全配置 / 能力状态 / 演示预算 / 费用摘要 分组卡片
 */
import { useCallback, useEffect, useState } from 'react'
import Button from '../../components/ui/Button'
import { API_BASE } from '../../api/client'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { commercialApi, type AttemptOut, type ProductionDetail } from './api'
import { request } from './templatesApi'
import './commercial.css'

type ProductionItem = {
  id: number; status: string; template_name: string
  resolution_id: string; aspect_ratio: string
  unit_count: number; attempt_count: number; approved_count: number
  created_at: string | null
}

function AttemptPreview({ url, mime }: { url: string; mime?: string | null }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setBlobUrl(null); setFailed(false)
    const target = url.startsWith('http') ? url : `${API_BASE}${url}`
    fetch(target, { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } })
      .then(response => response.ok ? response.blob() : Promise.reject(new Error(String(response.status))))
      .then(blob => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setBlobUrl(objectUrl)
      })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [url])
  if (failed) return <p className="pf-muted" style={{ fontSize: 12 }}>媒体预览加载失败</p>
  if (!blobUrl) return <p className="pf-muted" style={{ fontSize: 12 }}>媒体预览加载中…</p>
  return (mime || '').startsWith('audio/')
    ? <audio controls preload="metadata" src={blobUrl} style={{ width: '100%', height: 32 }} />
    : <video controls preload="metadata" src={blobUrl} style={{ display: 'block', width: 'min(100%, 420px)', maxHeight: 260, borderRadius: 8 }} />
}

const DIMS = ['人物身份', '商品准确', '音色', '台词', '口型', '动作与画面', '模板表达', '技术输出'] as const

/* ---------------------------------------------------------------- 任务与作品 */
export function CommercialTasksPage() {
  const [items, setItems] = useState<ProductionItem[]>([])
  const [detail, setDetail] = useState<ProductionDetail | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [msg, setMsg] = useState('')
  const [composing, setComposing] = useState(false)
  const [exportId, setExportId] = useState<number | null>(null)
  const [exportKind, setExportKind] = useState<string>('master')
  const [subtitled, setSubtitled] = useState(false)
  const [exportDetail, setExportDetail] = useState<{ srt_content: string | null; subtitled_path: string | null } | null>(null)
  const [srtDraft, setSrtDraft] = useState('')
  const [burnMsg, setBurnMsg] = useState('')
  const [loading, setLoading] = useState(true)

  const refreshList = useCallback(() => {
    setLoading(true); setMsg('')
    request<{ items: ProductionItem[] }>('/api/commercial/productions')
      .then(r => setItems(r.items))
      .catch(e => setMsg(String(e instanceof Error ? e.message : e)))
      .finally(() => setLoading(false))
  }, [])
  useEffect(refreshList, [refreshList])

  const openDetail = useCallback((id: number) => {
    setActiveId(id)
    commercialApi.getProduction(id).then(d => {
      setDetail(d)
      if (d.latest_export) {
        setExportId(d.latest_export.id); setExportKind(d.latest_export.kind)
        commercialApi.getExport(d.latest_export.id).then(ex => {
          setSubtitled(Boolean(ex.subtitled_path)); setExportDetail(ex); setSrtDraft(ex.srt_content || '')
        }).catch(() => {})
      } else { setExportId(null); setSubtitled(false); setExportDetail(null); setSrtDraft('') }
    }).catch(e => setMsg(String(e instanceof Error ? e.message : e)))
  }, [])
  useEffect(() => { if (activeId) openDetail(activeId) }, [activeId, openDetail])

  const review = async (attempt: AttemptOut, pass: boolean) => {
    const dims: Record<string, string | string[]> = {}
    for (const d of DIMS) dims[d] = pass ? 'PASS' : (d === '台词' ? ['FAIL', '页面驳回：台词不合格'] : 'PASS')
    try {
      await commercialApi.review(attempt.id, dims)
      openDetail(activeId!)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  const compose = async () => {
    if (!detail || composing) return
    setComposing(true)
    const units = detail.plan?.units || []
    const selections: { attempt_id: number; ranges: number[][] }[] = []
    const missing: string[] = []
    for (const u of units) {
      const mine = detail.attempts
        .filter(a => a.unit_key === u.unit_key && a.status === 'REVIEW_APPROVED')
        .sort((x, y) => y.id - x.id)
      if (!mine.length) { missing.push(u.unit_key); continue }
      selections.push({ attempt_id: mine[0].id, ranges: (u.adopt_ranges || []).map(([, s, e]) => [s, e]) })
    }
    if (missing.length) {
      setMsg(`缺少合格版本，不能导出完整成片：${missing.join('、')}（可在制作工作台重做后审核）`)
      return
    }
    try {
      const r = await commercialApi.compose(detail.id, selections, true)
      setExportId(r.export_id); setExportKind(r.kind)
      setMsg(`合成完成：导出 #${r.export_id}（${r.kind === 'partial_preview' ? '部分预览' : '完整成片'}，${(r.total_adopt_ms / 1000).toFixed(1)}s）`)
      openDetail(activeId!)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
    finally { setComposing(false) }
  }

  const download = async (variant: 'master' | 'subtitled') => {
    if (!exportId) return
    const q = variant === 'subtitled' ? '?variant=subtitled' : ''
    const resp = await fetch(`${API_BASE}/api/commercial/exports/${exportId}/download${q}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
    if (!resp.ok) { setMsg('下载失败'); return }
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `export-${exportId}${variant === 'subtitled' ? '-subtitled' : ''}.mp4`
    a.click(); URL.revokeObjectURL(a.href)
  }

  const burn = async () => {
    if (!exportId || !srtDraft.trim()) { setBurnMsg('请先校对字幕草稿'); return }
    setBurnMsg('烧录中…')
    try {
      await commercialApi.burnExport(exportId, srtDraft)
      const ex = await commercialApi.getExport(exportId)
      setExportDetail(ex); setSubtitled(Boolean(ex.subtitled_path)); setBurnMsg('烧录完成，母版未改动')
    } catch (e) { setBurnMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <CommercialLayout>
      <CommercialPageHead title="任务与作品" desc="浏览全部作品：镜头状态、审核、重做与导出；无需记住内部编号。" />
      <MockModeNote />

      <div className="pf-template-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
        {loading && <p className="pf-muted">加载作品中…</p>}
        {items.map(p => (
          <button key={p.id} type="button" className="pf-template-card"
            style={{ cursor: 'pointer', textAlign: 'left', border: activeId === p.id ? '2px solid var(--pf-lime)' : undefined }}
            onClick={() => setActiveId(p.id)}>
            <div className="body">
              <h3>#{p.id} · {p.template_name}</h3>
              <p className="pf-muted" style={{ fontSize: 12 }}>
                {p.created_at?.slice(0, 16).replace('T', ' ')} · {p.resolution_id} · {p.aspect_ratio}
              </p>
              <p className="pf-muted" style={{ fontSize: 12 }}>
                {p.unit_count} 单元 · {p.approved_count}/{p.attempt_count} 次尝试通过审核
              </p>
              <div className="pf-tags"><span>{p.status}</span></div>
            </div>
          </button>
        ))}
      </div>
      {!loading && items.length === 0 && !msg && <p className="pf-muted" style={{ padding: '24px 0', textAlign: 'center' }}>还没有作品，去制作工作台创建。</p>}
      {msg && <p style={{ fontSize: 13, color: 'var(--pf-ink)', margin: '12px 0' }}>{msg}</p>}

      {detail && (
        <div className="pf-card" style={{ padding: 16, marginTop: 16 }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 16 }}>作品 #{detail.id} · {detail.status}</h3>
          <p className="pf-muted" style={{ fontSize: 13, margin: '0 0 12px' }}>
            费用：总计 ${detail.costs.total_usd} · 待结算 ${detail.costs.pending_usd}（{detail.costs.settlement_note}）
          </p>
          {detail.attempts.map(a => (
            <div key={a.id} className="cv-shot" style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '8px 10px' }}>
                <strong>#{a.id}</strong>
                {a.unit_key && <span className="pf-tags"><span>{a.unit_key}</span></span>}
                {a.attempt_no != null && a.attempt_no > 1 && <span className="pf-tags"><span>第{a.attempt_no}次</span></span>}
                <span className="pf-tags"><span>{a.status}</span></span>
                <span className="pf-muted" style={{ fontSize: 12 }}>{a.prediction_id ?? ''}</span>
                <span style={{ flex: 1 }} />
                {a.status === 'GENERATED' && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => review(a, true)}>通过</Button>
                    <Button variant="outline" size="sm" onClick={() => review(a, false)}>驳回</Button>
                  </>
                )}
              </div>
              {a.preview_url && (
                <div style={{ padding: '0 10px 8px' }}>
                  <AttemptPreview url={a.preview_url} mime={a.preview_mime} />
                </div>
              )}
              {a.error_message && <p style={{ fontSize: 12, color: '#b3261e', margin: '0 0 6px 10px' }}>{a.error_message}</p>}
            </div>
          ))}
          <p className="pf-muted" style={{ fontSize: 12 }}>
            重做请到<a href={`/commercial/studio?production=${detail.id}`}>制作工作台</a>对应单元操作（新报价 → 新尝试，旧版本与费用保留）。
          </p>
          {detail.attempts.some(a => a.status === 'REVIEW_APPROVED') && (
            <div>
              <Button variant="lime" disabled={composing} onClick={compose}>
                {composing ? '合成中…（FFmpeg 拼接中，请稍候）' : '合成完整成片（FFmpeg）并生成字幕草稿'}
              </Button>
              {msg && <p style={{ fontSize: 13, margin: '8px 0 0', color: msg.includes('合成完成') ? 'var(--pf-ink)' : '#b26a00' }}>{msg}</p>}
            </div>
          )}
          {exportId != null && (
            <div style={{ marginTop: 14, borderTop: '1px solid var(--pf-line)', paddingTop: 12 }}>
              <strong>导出 #{exportId}</strong>
              {exportKind === 'partial_preview' && <span className="pf-tags"><span>部分预览（非完整成片）</span></span>}
              <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                <Button variant="outline" size="sm" onClick={() => download('master')}>下载无字幕母版</Button>
                {subtitled
                  ? <Button variant="outline" size="sm" onClick={() => download('subtitled')}>下载烧录字幕版</Button>
                  : <span className="pf-muted" style={{ fontSize: 12, alignSelf: 'center' }}>烧录版未生成</span>}
              </div>
              {exportDetail && <div style={{ marginTop: 10 }}>
                <label className="cv-field" style={{ margin: 0 }}>字幕校对
                  <textarea className="cv-textarea" value={srtDraft} onChange={e => setSrtDraft(e.target.value)} />
                </label>
                <Button variant="outline" size="sm" onClick={burn}>校对完成并烧录字幕</Button>
                {burnMsg && <span className="pf-muted" style={{ fontSize: 12, marginLeft: 8 }}>{burnMsg}</span>}
              </div>}
              <p className="pf-muted" style={{ fontSize: 12, marginTop: 8 }}>字幕为未校对草稿；校对后烧录只生成独立副本，母版不变。</p>
            </div>
          )}
        </div>
      )}
    </CommercialLayout>
  )
}

/* ---------------------------------------------------------------- 设置与费用 */
export function CommercialSettingsPage() {
  const [total, setTotal] = useState('')
  const [msg, setMsg] = useState('')
  const [pool, setPool] = useState<{ total_usd: string; scope: string; paused: boolean } | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [geminiId, setGeminiId] = useState('')
  const [h3Id, setH3Id] = useState('')
  const [provider, setProvider] = useState<{ has_atlas_api_key: boolean; gemini_analysis_model_id: string; h3_developer_reference_model_id: string; commercial_verified_models: string; commercial_mock_mode: boolean; commercial_paid_execution_enabled: boolean } | null>(null)
  const [providerMsg, setProviderMsg] = useState('')

  useEffect(() => {
    commercialApi.getProviderSettings().then(s => {
      setProvider(s); setGeminiId(s.gemini_analysis_model_id || ''); setH3Id(s.h3_developer_reference_model_id || '')
    }).catch(() => setProvider(null))
  }, [])

  const setBudget = async () => {
    try { const r = await commercialApi.setBudget(total, 'mock'); setPool(r); setMsg('演示预算已更新') }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const saveProvider = async () => {
    try {
      await commercialApi.saveProviderSettings({
        ...(apiKey.trim() ? { atlas_api_key: apiKey.trim() } : {}),
        gemini_analysis_model_id: geminiId.trim(),
        h3_developer_reference_model_id: h3Id.trim(),
      })
      setApiKey('')
      const s = await commercialApi.getProviderSettings(); setProvider(s)
      setProviderMsg('已保存（密钥加密存库，不回传显示；未发起任何付费调用）')
    } catch (e) { setProviderMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <CommercialLayout>
      <CommercialPageHead title="设置与费用" desc="密钥与模型配置、能力验证状态、演示预算与费用摘要分组管理。" />
      <MockModeNote />

      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>
        <div className="pf-card" style={{ padding: 16 }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>安全配置（管理员）</h3>
          {provider == null
            ? <p className="pf-muted">需要管理员权限查看。</p>
            : <>
                <div className="cv-field"><label>Atlas API 密钥（只写不读）</label>
                  <input className="cv-input" type="password" placeholder={provider.has_atlas_api_key ? '已配置，输入以更换' : '未配置'}
                    value={apiKey} onChange={e => setApiKey(e.target.value)} /></div>
                <div className="cv-field"><label>Gemini 解析模型精确 ID</label>
                  <input className="cv-input" value={geminiId} onChange={e => setGeminiId(e.target.value)} placeholder="待账号控制台核实" /></div>
                <div className="cv-field"><label>H3 生成模型精确 ID</label>
                  <input className="cv-input" value={h3Id} onChange={e => setH3Id(e.target.value)} placeholder="待账号控制台核实" /></div>
                <div style={{ marginTop: 10 }}><Button variant="lime" onClick={saveProvider}>保存配置</Button></div>
                {providerMsg && <p style={{ fontSize: 12, color: 'var(--pf-ink)', marginTop: 8 }}>{providerMsg}</p>}
              </>}
        </div>

        <div className="pf-card" style={{ padding: 16 }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>能力状态</h3>
          <ul style={{ fontSize: 13, color: 'var(--pf-muted)', margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
            <li>密钥：{provider?.has_atlas_api_key ? '已配置（不显示）' : '未配置'}</li>
            <li>已验证能力清单：{provider?.commercial_verified_models || '（空——未经真实契约验证，付费执行保持阻断）'}</li>
            <li>模式：{provider == null ? '运行模式未确认（需管理员权限）' : (provider.commercial_mock_mode ? '开发模拟（mock）' : '真实')} · 付费总开关：{provider == null ? '未确认' : (provider.commercial_paid_execution_enabled ? '开' : '关（默认）')}</li>
          </ul>
        </div>

        <div className="pf-card" style={{ padding: 16 }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>演示预算（mock 池）</h3>
          <p className="pf-muted" style={{ fontSize: 12, margin: '0 0 8px' }}>演示预算不构成真实付费授权；真实模式使用独立 real 池，需另行初始化。</p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input className="cv-input" style={{ width: 160 }} placeholder="USD，如 50.00" value={total} onChange={e => setTotal(e.target.value)} />
            <Button variant="lime" onClick={setBudget}>保存</Button>
          </div>
          {pool && <p className="pf-muted" style={{ fontSize: 12, marginTop: 8 }}>当前：${pool.total_usd}（scope={pool.scope}）{pool.paused ? ' · 已暂停' : ''}</p>}
          {msg && <p className="pf-muted" style={{ fontSize: 12, marginTop: 4 }}>{msg}</p>}
        </div>

        <div className="pf-card" style={{ padding: 16 }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>费用摘要</h3>
          <p className="pf-muted" style={{ fontSize: 13 }}>
            各作品费用在「任务与作品」详情查看（总计 / 待结算分列）；真实费用对账在联调后提供。
            当前全部记录均标记为演示（mock），不计入真实支出。
          </p>
        </div>
      </div>
    </CommercialLayout>
  )
}
