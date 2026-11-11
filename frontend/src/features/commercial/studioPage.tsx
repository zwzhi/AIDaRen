/**
 * 制作工作台（设计体系版）：三区布局——①选模板与素材 ②文案与分镜 ③逐单元参数与费用。
 * 支持 ?template={versionId} 带入已发布版本、?production={id} 服务端恢复、
 * 单镜重做（新报价→新尝试，旧版本与费用保留）；业务接口全部沿用。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Button from '../../components/ui/Button'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import {
  commercialApi, type ActorItem, type ProductItem, type TemplateItem,
} from './api'
import './commercial.css'

const sec = (ms: number) => `${(ms / 1000).toFixed(1)}s`

/** 单镜重做入口：改台词 → 新报价（参数变废旧批准）→ 确认费用 → 新 attempt。 */
function RedoEntry({ unitKey, productionId, attempts, dialogueOverride, onDialogueChange, onDone }: {
  unitKey: string; productionId: number
  attempts: { id: number; unit_key?: string | null; status: string; attempt_no?: number }[]
  dialogueOverride?: string
  onDialogueChange: (v: string) => void
  onDone: () => void
}) {
  const [busy, setBusy] = useState<'quote' | 'generate' | null>(null)
  const [quote, setQuote] = useState<{ id: number; amount: string } | null>(null)
  const [msg, setMsg] = useState('')
  const dialogueInputRef = useRef<HTMLInputElement>(null)
  const mine = attempts.filter(a => a.unit_key === unitKey)
  const latest = mine[mine.length - 1]
  const redo = async () => {
    setBusy('quote'); setMsg('')
    try {
      const override = (document.querySelector<HTMLInputElement>(`input[data-unit-key="${unitKey}"]`)?.value ?? dialogueInputRef.current?.value ?? dialogueOverride ?? '').trim()
      const q = await commercialApi.quote(productionId, unitKey, override)
      setQuote({ id: q.quote_id, amount: q.amount }); setBusy(null)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); setBusy(null) }
  }
  const confirmRedo = async () => {
    setBusy('generate')
    try {
      const reqId = `redo-${productionId}-${unitKey}-${Date.now()}`
      const override = (document.querySelector<HTMLInputElement>(`input[data-unit-key="${unitKey}"]`)?.value ?? dialogueInputRef.current?.value ?? dialogueOverride ?? '').trim()
      const r = await commercialApi.generate(productionId, unitKey, quote!.id, reqId, override)
      setMsg(`已创建新尝试 #${r.attempt_id}（${r.attempt_status}）；旧版本与费用保留`)
      setQuote(null); onDone()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(null) }
  }
  if (!latest) return null
  return (
    <div style={{ marginTop: 10, borderTop: '1px dashed var(--pf-line)', paddingTop: 8 }}>
      <span className="pf-muted" style={{ fontSize: 12 }}>
        本单元尝试：{mine.map(a => `#${a.id}${a.attempt_no && a.attempt_no > 1 ? `（第${a.attempt_no}次）` : ''}·${a.status}`).join('、')}
      </span>
      <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <input ref={dialogueInputRef} data-unit-key={unitKey} className="cv-input" style={{ width: 300 }} placeholder="重做台词（留空沿用；修改后旧批准自动失效）"
          value={dialogueOverride ?? ''} onChange={e => onDialogueChange(e.target.value)} />
        {!quote
          ? <Button variant="outline" size="sm" disabled={busy != null} onClick={redo}>重做 → 重新报价</Button>
          : <>
              <span className="pf-muted" style={{ fontSize: 13 }}>新报价 ${quote.amount}</span>
              <Button variant="lime" size="sm" disabled={busy != null} onClick={confirmRedo}>确认并重做</Button>
            </>}
      </div>
      {msg && <p style={{ color: 'var(--pf-ink)', fontSize: 12, margin: '6px 0 0' }}>{msg}</p>}
    </div>
  )
}

export default function CommercialStudioPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [actors, setActors] = useState<ActorItem[]>([])
  const [products, setProducts] = useState<ProductItem[]>([])
  const [sel, setSel] = useState({ template: 0, actorVersion: 0, voice: 0, productVersion: 0, resolution: '' })
  const [productionId, setProductionIdState] = useState<number | null>(null)
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof commercialApi.getProduction>> | null>(null)
  const [quotes, setQuotes] = useState<Record<string, { id: number; amount: string }>>({})
  const [redoDialogue, setRedoDialogue] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState('')
  const [msgKind, setMsgKind] = useState<'info' | 'error'>('info')
  const [caps, setCaps] = useState<Awaited<ReturnType<typeof commercialApi.getCapabilities>> | null>(null)
  const [capsLoading, setCapsLoading] = useState(true)
  const [capsError, setCapsError] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()
  const hasUnsavedRedo = Object.values(redoDialogue).some(v => v && v.trim())
  const reqIdBase = useRef(`ui-${Date.now()}`)
  const restoredRef = useRef(false)

  const setProductionId = (pid: number | null) => {
    setProductionIdState(pid)
    if (pid == null) setSearchParams({}, { replace: true })
    else setSearchParams({ production: String(pid) }, { replace: true })
  }

  useEffect(() => {
    let alive = true
    setCapsLoading(true)
    Promise.all([commercialApi.listTemplates(), commercialApi.listActors(), commercialApi.listProducts(), commercialApi.getCapabilities()])
      .then(([tpl, actor, product, capabilities]) => {
        if (!alive) return
        setTemplates(tpl.items); setActors(actor.items); setProducts(product.items); setCaps(capabilities)
        setSel(s => ({ ...s, resolution: capabilities.resolutions.includes(s.resolution) ? s.resolution : (capabilities.resolutions[0] ?? '') }))
      })
      .catch(e => { if (alive) setCapsError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (alive) setCapsLoading(false) })
    return () => { alive = false }
  }, [])
  useEffect(() => {
    if (restoredRef.current) return
    const fromUrl = Number(searchParams.get('production'))
    const tplFromUrl = Number(searchParams.get('template'))
    if (fromUrl > 0) { restoredRef.current = true; setProductionIdState(fromUrl) }
    else if (tplFromUrl > 0) { restoredRef.current = true; setSel(s => ({ ...s, template: tplFromUrl })) }
  }, [searchParams])
  useEffect(() => {
    if (!hasUnsavedRedo) return
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [hasUnsavedRedo])
  useEffect(() => {
    if (!hasUnsavedRedo) return
    const guard = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      const link = target?.closest('a[href]') as HTMLAnchorElement | null
      if (!link || !link.getAttribute('href')?.startsWith('/')) return
      if (!window.confirm('当前重做台词尚未提交，确定离开吗？')) event.preventDefault()
    }
    document.addEventListener('click', guard, true)
    return () => document.removeEventListener('click', guard, true)
  }, [hasUnsavedRedo])

  const refreshDetail = useCallback((pid: number) => {
    commercialApi.getProduction(pid).then(setDetail).catch(e => setMsg(String(e instanceof Error ? e.message : e)))
  }, [])
  useEffect(() => { if (productionId) refreshDetail(productionId) }, [productionId, refreshDetail])

  const create = async () => {
    try {
      if (!caps || capsLoading || !caps.resolutions.includes(sel.resolution)) {
        setMsgKind('error'); setMsg('能力档案未加载或当前分辨率已失效，无法创建作品'); return
      }
      const r = await commercialApi.createProduction({
        template_version_id: sel.template, actor_version_id: sel.actorVersion,
        voice_profile_id: sel.voice, product_version_id: sel.productVersion,
        dialogue_locked: false, resolution_id: sel.resolution,
      })
      setProductionId(r.production_id); setMsgKind('info'); setMsg('')
    } catch (e) { setMsgKind('error'); setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const step = async () => {
    if (!productionId) return
    try {
      await commercialApi.adapt(productionId, '种草推荐')
      await commercialApi.plan(productionId)
      refreshDetail(productionId); setMsg('')
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const quoteUnit = async (unitKey: string) => {
    if (!productionId) return
    try {
      const q = await commercialApi.quote(productionId, unitKey)
      setQuotes(prev => ({ ...prev, [unitKey]: { id: q.quote_id, amount: q.amount } }))
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const generateUnit = async (unitKey: string) => {
    if (!productionId) return
    const q = quotes[unitKey]; if (!q) { setMsg('请先报价并确认'); return }
    try {
      const r = await commercialApi.generate(productionId, unitKey, q.id, `${reqIdBase.current}-${unitKey}`)
      setMsg(r.attempt_status === 'GENERATED' ? `单元 ${unitKey} 生成完成（模拟输出）` : `单元 ${unitKey}：${r.attempt_status}`)
      refreshDetail(productionId)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  const units = detail?.plan?.units || []
  return (
    <CommercialLayout>
      <CommercialPageHead
        title="制作工作台"
        desc="选模板与素材 → 文案与分镜 → 逐单元报价确认与生成；重做只影响所选单元。"
      />
      <MockModeNote />

      {/* ① 选模板与素材 */}
      <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>① 选择模板与素材</h3>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div className="cv-field" style={{ margin: 0, minWidth: 220 }}>
            <label>模板版本</label>
            <select className="cv-input" value={sel.template || ''} onChange={e => setSel(s => ({ ...s, template: +e.target.value }))}>
              <option value="" disabled>选择模板</option>
              {templates.flatMap(t => t.versions.map(v => (
                <option key={v.id} value={v.id}>{t.name} V{v.version}（{v.shot_count ?? '—'} 镜 · {sec(v.total_duration_ms ?? 0)}）</option>
              )))}
            </select>
          </div>
          <div className="cv-field" style={{ margin: 0, minWidth: 220 }}>
            <label>达人（含音色）</label>
            <select className="cv-input" value={sel.actorVersion ? `${sel.actorVersion}:${sel.voice}` : ''} onChange={e => {
              const [av, vo] = e.target.value.split(':').map(Number)
              setSel(s => ({ ...s, actorVersion: av, voice: vo }))
            }}>
              <option value="" disabled>选择达人</option>
              {actors.flatMap(a => a.versions.flatMap(v => a.voices.map(vo => (
                <option key={`${v.id}:${vo.id}`} value={`${v.id}:${vo.id}`}>{a.name} V{v.version} + 音色#{vo.id}</option>
              ))))}
            </select>
          </div>
          <div className="cv-field" style={{ margin: 0, minWidth: 180 }}>
            <label>商品</label>
            <select className="cv-input" value={sel.productVersion || ''} onChange={e => setSel(s => ({ ...s, productVersion: +e.target.value }))}>
              <option value="" disabled>选择商品</option>
              {products.map(p => <option key={p.id} value={p.latest_version_id ?? ''} disabled={!p.latest_version_id}>{p.name}{p.latest_version_id ? '' : '（无可用版本）'}</option>)}
            </select>
          </div>
          <div className="cv-field" style={{ margin: 0, minWidth: 150 }}>
            <label>生成分辨率</label>
            <select className="cv-input" value={sel.resolution} disabled={capsLoading || Boolean(capsError)}
              onChange={e => setSel(s => ({ ...s, resolution: e.target.value }))}>
              <option value="">{capsLoading ? '能力加载中…' : '选择分辨率'}</option>
              {(caps?.resolutions ?? []).map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <Button variant="lime" disabled={!sel.template || !sel.actorVersion || !sel.voice || !sel.productVersion || !sel.resolution || capsLoading || Boolean(capsError)} onClick={create}>
              创建作品
            </Button>
          </div>
        </div>
        {capsError && <p style={{ fontSize: 13, color: '#b3261e', margin: '10px 0 0' }}>能力档案加载失败：{capsError}。请刷新后重试。</p>}
        {msg && <p style={{ fontSize: 13, color: msgKind === 'error' ? '#b3261e' : 'var(--pf-ink)', margin: '10px 0 0' }}>{msg}</p>}
        {caps && <p className="pf-muted" style={{ fontSize: 12, margin: '8px 0 0' }}>能力档案 {caps.capability_version} · {caps.capability_verified ? '已验证' : 'DRAFT，未完成真实契约验证'} · 分辨率：{caps.resolutions.join(' / ') || '无'}</p>}
      </div>

      {/* ② 文案与分镜 */}
      {productionId && detail && (
        <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>② 文案与分镜（作品 #{productionId} · {detail.status}）</h3>
            <Button variant="outline" size="sm" onClick={step}>执行文案适配 + 编译生成计划</Button>
          </div>
          {detail.dialogue_locked && <p className="pf-muted" style={{ fontSize: 12 }}>台词已锁定：适配只建议动作与时间。</p>}
          {detail.plan?.pending_review?.length ? (
            <p className="pf-muted" style={{ fontSize: 12, color: '#b26a00' }}>
              {detail.plan.pending_review.length} 处新内容待人工确认（不在审核卖点内）。
            </p>
          ) : null}
          {(detail.plan?.shots || []).map(s => (
            <div key={s.shot_id} className="cv-shot">
              <div className="cv-shot-head" style={{ cursor: 'default' }}>
                <strong style={{ minWidth: 36 }}>{s.shot_id}</strong>
                <span className="pf-muted" style={{ fontSize: 12 }}>目标 {sec(s.target_duration_ms ?? (s.end_ms - s.start_ms))}</span>
                <span style={{ fontSize: 13, flex: 1, minWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.dialogue || '—'}
                </span>
              </div>
              <div style={{ padding: '0 12px 10px', fontSize: 13, color: 'var(--pf-muted)' }}>动作：{s.action || '—'}</div>
            </div>
          ))}
        </div>
      )}

      {/* ③ 逐单元参数与费用 */}
      {units.length > 0 && productionId && (
        <div className="pf-card" style={{ padding: 16 }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15 }}>③ 逐单元报价与生成（生成 / 采用时长分列）</h3>
          {units.map(u => (
            <div key={u.unit_key} className="cv-shot">
              <div className="cv-shot-head" style={{ cursor: 'default' }}>
                <strong>{u.unit_key}</strong>
                <span className="pf-muted" style={{ fontSize: 12 }}>
                  覆盖 {u.covered_shot_keys.join('+')} · 生成 {sec(u.request_duration_ms)} · 采用{' '}
                  {(u.adopt_ranges || []).map(([, a, b]) => `${sec(a)}-${sec(b)}`).join('、')}
                </span>
              </div>
              <div style={{ padding: '4px 12px 12px', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {!quotes[u.unit_key]
                  ? <Button variant="outline" size="sm" onClick={() => quoteUnit(u.unit_key)}>① 报价</Button>
                  : <>
                      <span className="pf-muted" style={{ fontSize: 13 }}>预计 ${quotes[u.unit_key].amount}（模拟价）</span>
                      <Button variant="lime" size="sm" onClick={() => generateUnit(u.unit_key)}>② 确认并生成</Button>
                    </>}
              </div>
              <div style={{ padding: '0 12px 4px' }}>
                <RedoEntry unitKey={u.unit_key} productionId={productionId}
                  attempts={detail?.attempts || []} dialogueOverride={redoDialogue[u.unit_key]}
                  onDialogueChange={v => setRedoDialogue(prev => ({ ...prev, [u.unit_key]: v }))}
                  onDone={() => refreshDetail(productionId)} />
              </div>
            </div>
          ))}
          <p className="pf-muted" style={{ fontSize: 12, marginTop: 10 }}>
            时长边界来自能力档案（当前 5–15s/档）；报价与生成使用同一份参数快照，任何修改都会使旧确认失效。
          </p>
        </div>
      )}
    </CommercialLayout>
  )
}
