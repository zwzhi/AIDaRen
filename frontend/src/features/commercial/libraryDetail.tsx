/**
 * 三库详情页：商品（状态+候选审核）/ 服饰（AI 生成）/ 达人（参考图选择）。
 * 列表页点"详情"进入；返回按钮回到对应列表。
 */
import { useCallback, useEffect, useState } from 'react'
import { Check, RefreshCw, Sparkles, Upload, X } from 'lucide-react'
import Button from '../../components/ui/Button'
import { requestResponse } from '../../api/client'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { AssetImage } from './assetPreview'
import { request } from './templatesApi'
import './commercial.css'

/* ---------------------------------------------------------------- 商品详情 */
type ProductState = {
  id: number; state_key: string; label: string; status: string
  assets?: Array<{ asset_id: number; review_status: string; source_type: string }>
}
type ResearchCandidate = {
  id: number; field_name: string; value_json: unknown; confidence: number | null
  status: string; conflict_key: string
}
type ResearchRun = {
  id: number; status: string; model_id: string; refresh_reason: string
  candidates: ResearchCandidate[]; usage?: { input_tokens: number; output_tokens: number; estimated_amount: string }
}
type ProductDetailData = {
  id: number; name: string; form: string; specs_text: string
  current_version_id: number | null
  image_asset_ids: number[]
  states: ProductState[]
  research_runs: ResearchRun[]
  claims: Array<{ claim_id: string; text: string; approved: boolean }>
}

export function ProductDetailPage({ productId }: { productId: number }) {
  const [data, setData] = useState<ProductDetailData | null>(null)
  const [error, setError] = useState('')
  const [researching, setResearching] = useState(false)
  const [reviewMsg, setReviewMsg] = useState('')

  const load = useCallback(() => {
    request<ProductDetailData>(`/api/commercial/products/${productId}`)
      .then(setData)
      .catch(e => setError(String(e instanceof Error ? e.message : e)))
  }, [productId])
  useEffect(load, [load])

  const startResearch = async () => {
    setResearching(true); setReviewMsg('')
    try {
      const resp = await requestResponse(`/api/commercial/products/${productId}/research`, { method: 'POST' })
      const run = await resp.json()
      setReviewMsg(`研究已启动（#${run.run_id ?? run.id}），状态：${run.status ?? 'queued'}`)
      load()
    } catch (e) { setReviewMsg(e instanceof Error ? e.message : String(e)) }
    finally { setResearching(false) }
  }

  const reviewCandidate = async (candidateId: number, approve: boolean) => {
    try {
      await requestResponse(`/api/commercial/product-research/${data?.research_runs[0]?.id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify({ decisions: [{ candidate_id: candidateId, action: approve ? 'approve' : 'reject' }] }),
      })
      setReviewMsg(approve ? '候选已确认' : '候选已拒绝')
      load()
    } catch (e) { setReviewMsg(e instanceof Error ? e.message : String(e)) }
  }

  if (error) return <CommercialLayout><CommercialPageHead title="商品详情" backTo="/commercial/products" backLabel="返回商品库" /><p className="cv-error">{error}</p></CommercialLayout>
  if (!data) return <CommercialLayout><CommercialPageHead title="商品详情" backTo="/commercial/products" backLabel="返回商品库" /><p className="cv-loading">加载中…</p></CommercialLayout>

  const pendingCandidates = data.research_runs?.[0]?.candidates?.filter(c => c.status === 'candidate') ?? []
  const confirmedClaims = data.claims?.filter(c => c.approved) ?? []

  return (
    <CommercialLayout>
      <CommercialPageHead
        title={data.name}
        desc={`形态：${data.form || '—'} · 规格：${data.specs_text || '—'}`}
        backTo="/commercial/products"
        backLabel="返回商品库"
      />
      <MockModeNote />

      {/* 图片 */}
      <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 className="cv-form-title">商品图集</h3>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {data.image_asset_ids?.map(id => <AssetImage key={id} assetId={id} alt={data.name} size={100} />)}
          {!data.image_asset_ids?.length && <p className="cv-empty">暂无图片</p>}
        </div>
      </div>

      {/* 已确认卖点 */}
      {confirmedClaims.length > 0 && (
        <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
          <h3 className="cv-form-title">已确认卖点（可进入台词）</h3>
          <div className="pf-tags">{confirmedClaims.map(c => <span key={c.claim_id}>{c.text}</span>)}</div>
        </div>
      )}

      {/* 商品状态 */}
      {data.states?.length > 0 && (
        <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
          <h3 className="cv-form-title">商品状态（包装/开盖/质地/使用/效果）</h3>
          {data.states.map(s => (
            <div key={s.id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--pf-line)' }}>
              <span className={`cv-status-tag ${s.status === 'confirmed' ? 'is-approved' : 'is-pending'}`}>
                {s.label || s.state_key}
              </span>
              <span className="pf-muted" style={{ fontSize: 12 }}>
                {s.status === 'confirmed' ? '已确认' : '候选'} · {s.assets?.length ?? 0} 张图
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                {s.assets?.slice(0, 5).map(a => <AssetImage key={a.asset_id} assetId={a.asset_id} alt={s.label} size={44} />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* AI 研究 */}
      <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <h3 className="cv-form-title" style={{ margin: 0 }}>联网商品研究</h3>
          <Button variant="outline" size="sm" disabled={researching} onClick={startResearch}>
            <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <RefreshCw size={14} aria-hidden />{researching ? '研究中…' : '启动研究'}
            </span>
          </Button>
        </div>
        {reviewMsg && <p style={{ fontSize: 13, color: 'var(--pf-ink)', margin: '6px 0' }}>{reviewMsg}</p>}
        {data.research_runs?.map(run => (
          <div key={run.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--pf-line)' }}>
            <span className={`cv-status-tag ${run.status === 'completed' ? 'is-approved' : 'is-pending'}`}>
              {run.status}
            </span>
            <span className="pf-muted" style={{ fontSize: 12, marginLeft: 8 }}>
              {run.model_id} · {run.refresh_reason}
              {run.usage && ` · ${run.usage.input_tokens}/${run.usage.output_tokens} tokens ≈$${run.usage.estimated_amount}`}
            </span>
          </div>
        ))}
        {/* 待审核候选 */}
        {pendingCandidates.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <p className="pf-muted" style={{ fontSize: 12, margin: '0 0 6px' }}>待审核候选（{pendingCandidates.length} 条）：</p>
            {pendingCandidates.map(c => (
              <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0' }}>
                <span className="cv-status-tag is-pending">{c.field_name}</span>
                <span style={{ fontSize: 13, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {JSON.stringify(c.value_json).slice(0, 80)}
                </span>
                {c.confidence != null && <span className="pf-muted" style={{ fontSize: 11 }}>置信度 {(c.confidence * 100).toFixed(0)}%</span>}
                <Button variant="outline" size="sm" onClick={() => reviewCandidate(c.id, true)}>
                  <Check size={14} aria-hidden />
                </Button>
                <Button variant="outline" size="sm" onClick={() => reviewCandidate(c.id, false)}>
                  <X size={14} aria-hidden />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </CommercialLayout>
  )
}

/* ---------------------------------------------------------------- 服饰详情 */
type WardrobeVersion = {
  id: number; version: number; color: string; material: string; description: string
  asset_ids: number[]; rights_status: string; status: string
}
type WardrobeDetailData = {
  id: number; name: string; category: string; scope: string
  versions: WardrobeVersion[]
}

export function WardrobeDetailPage({ wardrobeId }: { wardrobeId: number }) {
  const [data, setData] = useState<WardrobeDetailData | null>(null)
  const [error, setError] = useState('')
  const [genPrompt, setGenPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genMsg, setGenMsg] = useState('')

  const load = useCallback(() => {
    request<WardrobeDetailData>(`/api/commercial/wardrobes/${wardrobeId}`)
      .then(setData)
      .catch(e => setError(String(e instanceof Error ? e.message : e)))
  }, [wardrobeId])
  useEffect(load, [load])

  const generateImage = async (mode: 'text-to-image' | 'image-to-image') => {
    if (!genPrompt.trim()) { setGenMsg('请输入描述'); return }
    setGenerating(true); setGenMsg('')
    try {
      // 调用服饰 AI 生成（后端 wardrobes API 扩展点）
      const resp = await requestResponse(`/api/commercial/wardrobes/${wardrobeId}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify({ mode, prompt: genPrompt, base_version_id: data?.versions[0]?.id }),
      })
      const result = await resp.json()
      setGenMsg(`生成完成：${result.asset_id ? '已添加到版本' : result.message ?? '候选已创建'}`)
      load()
    } catch (e) { setGenMsg(e instanceof Error ? e.message : String(e)) }
    finally { setGenerating(false) }
  }

  if (error) return <CommercialLayout><CommercialPageHead title="服饰详情" backTo="/commercial/wardrobes" backLabel="返回服饰库" /><p className="cv-error">{error}</p></CommercialLayout>
  if (!data) return <CommercialLayout><CommercialPageHead title="服饰详情" backTo="/commercial/wardrobes" backLabel="返回服饰库" /><p className="cv-loading">加载中…</p></CommercialLayout>

  return (
    <CommercialLayout>
      <CommercialPageHead
        title={data.name}
        desc={`分类：${data.category} · 共享：${data.scope === 'personal' ? '个人' : data.scope === 'team' ? '团队' : '项目'} · ${data.versions.length} 个版本`}
        backTo="/commercial/wardrobes"
        backLabel="返回服饰库"
      />
      <MockModeNote />

      {/* 版本图集 */}
      {data.versions.map(v => (
        <div key={v.id} className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 className="cv-form-title" style={{ margin: 0 }}>V{v.version}</h3>
            <div style={{ display: 'flex', gap: 6 }}>
              <span className={`cv-status-tag ${v.status === 'published' ? 'is-approved' : 'is-pending'}`}>{v.status}</span>
              <span className={`cv-status-tag ${v.rights_status === 'cleared' ? 'is-approved' : 'is-pending'}`}>
                权利：{v.rights_status}
              </span>
            </div>
          </div>
          {v.color && <p className="pf-muted" style={{ fontSize: 12, margin: '0 0 4px' }}>颜色：{v.color}</p>}
          {v.material && <p className="pf-muted" style={{ fontSize: 12, margin: '0 0 4px' }}>材质：{v.material}</p>}
          {v.description && <p className="pf-muted" style={{ fontSize: 12, margin: '0 0 8px' }}>{v.description}</p>}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {v.asset_ids?.map(id => <AssetImage key={id} assetId={id} alt={`${data.name} V${v.version}`} size={100} />)}
            {!v.asset_ids?.length && <p className="cv-empty">暂无图片</p>}
          </div>
        </div>
      ))}

      {/* AI 生成 */}
      <div className="pf-card" style={{ padding: 16 }}>
        <h3 className="cv-form-title">AI 生成服饰图</h3>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="cv-field" style={{ margin: 0, flex: 1, minWidth: 240 }}>
            <label>描述（如：白色棉质圆领T恤，正面平铺）</label>
            <input className="cv-input" value={genPrompt} onChange={e => setGenPrompt(e.target.value)} placeholder="描述想要的服饰…" />
          </div>
          <Button variant="outline" disabled={generating} onClick={() => generateImage('text-to-image')}>
            <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <Sparkles size={14} aria-hidden />文生图
            </span>
          </Button>
          <Button variant="outline" disabled={generating} onClick={() => generateImage('image-to-image')}>
            <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <Upload size={14} aria-hidden />图生图（基于 V{data.versions[0]?.version ?? 1}）
            </span>
          </Button>
        </div>
        {genMsg && <p style={{ fontSize: 13, margin: '8px 0 0' }}>{genMsg}</p>}
      </div>
    </CommercialLayout>
  )
}
