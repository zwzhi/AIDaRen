/**
 * 商业短视频模板：六个业务页面（T08）。
 * 连接真实 /api/commercial；Mock 供应商模式下全流程可用，
 * 页面明确标识“测试/模拟”状态，不冒充真实联调。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { commercialApi, uploadAsset, type Capabilities, type ProductItem, type TemplateItem, type ActorItem, type Unit } from './api'
import { requestResponse } from '../../api/client'

const MOCK_NOTE = '当前为开发模拟模式：解析/文案/报价/生成均为本地 Mock，不代表真实模型效果'

function Section({ title, children, note }: { title: string; children: React.ReactNode; note?: string }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <h3 style={{ margin: '0 0 8px' }}>{title}</h3>
      {note && <p style={{ color: '#8a6d3b', background: '#fff8e1', padding: '6px 10px', borderRadius: 6, fontSize: 13 }}>{note}</p>}
      {children}
    </section>
  )
}

const btn: React.CSSProperties = { padding: '6px 14px', borderRadius: 6, border: '1px solid #2f6f4f', background: '#2f6f4f', color: '#fff', cursor: 'pointer', marginRight: 8 }
const btnAlt: React.CSSProperties = { ...btn, background: '#fff', color: '#2f6f4f' }
const input: React.CSSProperties = { padding: '6px 8px', borderRadius: 6, border: '1px solid #ccc', marginRight: 8 }
const card: React.CSSProperties = { border: '1px solid #e2e2e2', borderRadius: 10, padding: 14, marginBottom: 12, background: '#fff' }
const tag: React.CSSProperties = { display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 12, background: '#eef5f0', color: '#2f6f4f', marginLeft: 6 }

export function CommercialNav() {
  return (
    <nav style={{ display: 'flex', gap: 14, padding: '10px 0', borderBottom: '1px solid #eee', marginBottom: 18, flexWrap: 'wrap' }}>
      <Link to="/commercial/templates">模板库</Link>
      <Link to="/commercial/actors">达人库</Link>
      <Link to="/commercial/products">商品库</Link>
      <Link to="/commercial/studio">制作工作台</Link>
      <Link to="/commercial/tasks">任务与作品</Link>
      <Link to="/commercial/settings">设置与费用</Link>
    </nav>
  )
}

/* ---------------------------------------------------------------- 模板库 */
export function CommercialTemplatesPage() {
  const [uploading, setUploading] = useState(false)
  const [analysis, setAnalysis] = useState<{ runId: number; status: string; shots: unknown[] } | null>(null)
  const [name, setName] = useState('')
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [msg, setMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => { commercialApi.listTemplates().then(r => setTemplates(r.items)).catch(e => setMsg(String(e.message))) }, [])
  useEffect(refresh, [refresh])

  const onUpload = async (file: File) => {
    setUploading(true); setMsg('')
    try {
      // 1) 上传参考视频 → 2) 后端建档（当前版本由接口内部登记）→ 3) Mock 解析
      const asset = await uploadAsset(file, 'reference_source_video', '页面上传·确认有权使用')
      const resp = await requestResponse(`/api/commercial/sources/by-asset/${asset.id}`, { method: 'POST' })
      const sourceId = ((await resp.json()) as { source_id: number }).source_id
      const run = await commercialApi.analyze(sourceId)
      const detail = await commercialApi.getAnalysis(run.analysis_run_id)
      setAnalysis({ runId: run.analysis_run_id, status: detail.status, shots: detail.result?.shots || [] })
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setUploading(false) }
  }

  const onPublish = async () => {
    if (!analysis) return
    try {
      await commercialApi.createTemplate(name || '未命名模板', analysis.runId, analysis.shots as never[])
      setMsg('模板已发布（V1）'); setName(''); setAnalysis(null); refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div>
      <CommercialNav />
      <h2>模板库</h2>
      <Section title="上传参考视频并解析" note={MOCK_NOTE}>
        <input ref={fileRef} type="file" accept="video/mp4,video/quicktime" disabled={uploading}
          onChange={e => e.target.files?.[0] && onUpload(e.target.files[0])} />
        {uploading && <span> 上传与解析中…</span>}
        {msg && <p style={{ color: '#b00' }}>{msg}</p>}
        {analysis && (
          <div style={card}>
            <p>解析状态：{analysis.status} · 镜头数 {analysis.shots.length}</p>
            <input style={input} placeholder="模板名称" value={name} onChange={e => setName(e.target.value)} />
            <button style={btn} onClick={onPublish}>人工校准完成，发布模板</button>
          </div>
        )}
      </Section>
      <Section title="已发布模板">
        {templates.length === 0 && <p>暂无模板，请先上传参考视频。</p>}
        {templates.map(t => (
          <div key={t.id} style={card}>
            <b>{t.name}</b><span style={tag}>V{t.current_version}</span>
            <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>
              版本：{t.versions.map(v => `V${v.version}(${v.status})`).join('、')}
            </div>
          </div>
        ))}
      </Section>
    </div>
  )
}

/* ---------------------------------------------------------------- 达人库 */
export function CommercialActorsPage() {
  const [actors, setActors] = useState<ActorItem[]>([])
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const imgRef = useRef<HTMLInputElement>(null)
  const voiceRef = useRef<HTMLInputElement>(null)
  const [pendingImage, setPendingImage] = useState<number | null>(null)
  const [pendingVoice, setPendingVoice] = useState<number | null>(null)
  const refresh = useCallback(() => { commercialApi.listActors().then(r => setActors(r.items)).catch(e => setMsg(String(e instanceof Error ? e.message : e))) }, [])
  useEffect(refresh, [refresh])

  const create = async () => {
    if (pendingImage == null) { setMsg('请先上传达人形象图'); return }
    try {
      const r = await commercialApi.createActor(name || '未命名达人', [pendingImage], '页面创建')
      if (pendingVoice != null) {
        await commercialApi.bindVoice(r.actor_id, pendingVoice)
      }
      setMsg('达人已创建' + (pendingVoice != null ? '并绑定音色' : '（未绑定音色——生成前必须绑定）'))
      setName(''); setPendingImage(null); setPendingVoice(null); refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div>
      <CommercialNav />
      <h2>达人库</h2>
      <Section title="新建达人（形象图 + 授权音色）">
        <div>
          <input style={input} placeholder="达人名称" value={name} onChange={e => setName(e.target.value)} />
          <input ref={imgRef} type="file" accept="image/*" onChange={async e => {
            const f = e.target.files?.[0]; if (!f) return
            try { const a = await uploadAsset(f, 'owned_actor_image', '达人授权形象'); setPendingImage(a.id); setMsg('形象图已上传') } catch (err) { setMsg(String(err)) }
          }} />
          <input ref={voiceRef} type="file" accept="audio/mpeg,audio/mp3" onChange={async e => {
            const f = e.target.files?.[0]; if (!f) return
            try { const a = await uploadAsset(f, 'owned_voice_reference', '达人授权音色样本'); setPendingVoice(a.id); setMsg('音色样本已上传') } catch (err) { setMsg(String(err)) }
          }} />
          <button style={btn} onClick={create}>创建达人</button>
          {pendingImage != null && <span style={tag}>形象图 #{pendingImage} 就绪</span>}
          {pendingVoice != null && <span style={tag}>音色 #{pendingVoice} 就绪</span>}
          {msg && <p style={{ color: '#b00' }}>{msg}</p>}
        </div>
      </Section>
      <Section title="达人列表">
        {actors.length === 0 && <p>暂无达人。</p>}
        {actors.map(a => (
          <div key={a.id} style={card}>
            <b>{a.name}</b><span style={tag}>V{a.current_version}</span>
            <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>
              音色：{a.voices.length ? a.voices.map(v => `#${v.id}（${v.authorized_until ? '授权至 ' + v.authorized_until.slice(0, 10) : '长期'}）`).join('、') : '未绑定（不能生成口播）'}
            </div>
          </div>
        ))}
      </Section>
    </div>
  )
}

/* ---------------------------------------------------------------- 商品库 */
export function CommercialProductsPage() {
  const [products, setProducts] = useState<ProductItem[]>([])
  const [name, setName] = useState(''); const [form, setForm] = useState('贴片')
  const [claim, setClaim] = useState(''); const [action, setAction] = useState('手持正面展示')
  const [imageId, setImageId] = useState<number | null>(null)
  const [msg, setMsg] = useState('')
  const refresh = useCallback(() => { commercialApi.listProducts().then(r => setProducts(r.items)).catch(e => setMsg(String(e instanceof Error ? e.message : e))) }, [])
  useEffect(refresh, [refresh])

  const create = async () => {
    if (imageId == null) { setMsg('请先上传商品图'); return }
    try {
      await commercialApi.createProduct({
        name: name || '未命名商品', form, image_asset_ids: [imageId],
        claims: claim ? [{ claim_id: `c-${Date.now()}`, text: claim, approved: true, source: '品牌资料' }] : [],
        forbidden_phrases: [], allowed_actions: action ? [action] : [],
      })
      setMsg('商品已创建'); setName(''); setClaim(''); setImageId(null); refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div>
      <CommercialNav />
      <h2>商品库</h2>
      <Section title="新建商品">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <input style={input} placeholder="商品名称" value={name} onChange={e => setName(e.target.value)} />
          <select style={input} value={form} onChange={e => setForm(e.target.value)}>
            <option value="贴片">贴片</option><option value="瓶装">瓶装</option><option value="盒装">盒装</option>
          </select>
          <input style={input} placeholder="审核卖点（进入台词的唯一来源）" value={claim} onChange={e => setClaim(e.target.value)} />
          <input style={input} placeholder="允许展示动作" value={action} onChange={e => setAction(e.target.value)} />
          <input type="file" accept="image/*" onChange={async e => {
            const f = e.target.files?.[0]; if (!f) return
            try { const a = await uploadAsset(f, 'owned_product_image', '商品图'); setImageId(a.id) } catch (err) { setMsg(String(err)) }
          }} />
          <button style={btn} onClick={create}>创建商品</button>
        </div>
        {imageId != null && <span style={tag}>商品图 #{imageId} 就绪</span>}
        {msg && <p style={{ color: '#b00' }}>{msg}</p>}
      </Section>
      <Section title="商品列表">
        {products.length === 0 && <p>暂无商品。</p>}
        {products.map(p => <div key={p.id} style={card}><b>{p.name}</b><span style={tag}>V{p.current_version}</span></div>)}
      </Section>
    </div>
  )
}

/* 单镜重做入口：修改台词 → 重新报价 → 确认费用 → 新 attempt（旧版本与费用保留） */
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
  const mine = attempts.filter(a => a.unit_key === unitKey)
  const latest = mine[mine.length - 1]
  const redo = async () => {
    setBusy('quote'); setMsg('')
    try {
      // 修改后的台词随报价请求进入参数快照与指纹；与原计划台词不同时，
      // 旧报价/旧批准自动失效（QUOTE_CHANGED）——重做真正携带新台词
      const q = await commercialApi.quote(productionId, unitKey, (dialogueOverride ?? '').trim())
      setQuote({ id: q.quote_id, amount: q.amount }); setBusy(null)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); setBusy(null) }
  }
  const confirmRedo = async () => {
    setBusy('generate')
    try {
      // 新 client_request_id = 新 attempt（新预算）；台词必须与报价时一致
      const reqId = `redo-${productionId}-${unitKey}-${Date.now()}`
      const r = await commercialApi.generate(productionId, unitKey, quote!.id, reqId, (dialogueOverride ?? '').trim())
      setMsg(`已创建新尝试 #${r.attempt_id}（状态 ${r.attempt_status}）；台词已随请求生效，旧版本与费用保留`)
      setQuote(null); onDone()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(null) }
  }
  if (!latest) return null
  return (
    <div style={{ marginTop: 10, borderTop: '1px dashed #ddd', paddingTop: 8 }}>
      <span style={{ fontSize: 12, color: '#666' }}>
        本单元尝试：{mine.map(a => `#${a.attempt_no ?? a.id}(${a.status})`).join('、')}
      </span>
      <div style={{ marginTop: 6 }}>
        <input style={{ ...input, width: 320 }} placeholder="重做台词（留空沿用原台词；修改后旧批准自动失效）"
          value={dialogueOverride ?? ''} onChange={e => onDialogueChange(e.target.value)} />
        {!quote
          ? <button style={btnAlt} disabled={busy != null} onClick={redo}>重做此单元 → 重新报价</button>
          : <>
              <span style={{ marginRight: 8 }}>新报价 ${quote.amount}（模拟价）</span>
              <button style={btn} disabled={busy != null} onClick={confirmRedo}>确认费用并重做（新尝试）</button>
            </>}
      </div>
      {msg && <p style={{ color: '#2f6f4f', margin: '6px 0 0' }}>{msg}</p>}
    </div>
  )
}

/* ---------------------------------------------------------------- 制作工作台 */
export function CommercialStudioPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [actors, setActors] = useState<ActorItem[]>([])
  const [products, setProducts] = useState<ProductItem[]>([])
  const [sel, setSel] = useState({ template: 0, actorVersion: 0, voice: 0, productVersion: 0 })
  const [productionId, setProductionIdState] = useState<number | null>(null)
  // URL 关联作品 ID：刷新/重进自动恢复服务端状态（只读 GET，不重建不重提交）
  const [searchParams, setSearchParams] = useSearchParams()
  const [redoDialogue, setRedoDialogue] = useState<Record<string, string>>({})
  const setProductionId = (pid: number | null) => {
    setProductionIdState(pid)
    if (pid == null) setSearchParams({}, { replace: true })
    else setSearchParams({ production: String(pid) }, { replace: true })
  }
  const restoredRef = useRef(false)
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof commercialApi.getProduction>> | null>(null)
  const [quotes, setQuotes] = useState<Record<string, { id: number; amount: string }>>({})
  const [msg, setMsg] = useState('')
  const reqIdBase = useRef(`ui-${Date.now()}`)
  // 生成选项唯一来源：服务端能力档案（不硬编码 720p/768p 等默认值）
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [resolution, setResolution] = useState('')

  useEffect(() => {
    commercialApi.listTemplates().then(r => setTemplates(r.items))
    commercialApi.listActors().then(r => setActors(r.items))
    commercialApi.listProducts().then(r => setProducts(r.items))
    commercialApi.getCapabilities().then(c => {
      setCaps(c)
      // 默认优先 768p，其次档案内第一档；不在档案内的值绝不作为默认
      setResolution(c.resolutions.includes('768p') ? '768p' : (c.resolutions[0] ?? ''))
    }).catch(() => setCaps(null))
  }, [])
  // 刷新恢复：?production=N → 自动载入服务端已保存的计划/绑定/任务状态
  useEffect(() => {
    if (restoredRef.current) return
    const fromUrl = Number(searchParams.get('production'))
    if (fromUrl > 0) { restoredRef.current = true; setProductionIdState(fromUrl) }
  }, [searchParams])
  // 未保存的重做台词不静默丢失：关闭/刷新前提示
  useEffect(() => {
    const hasDraft = Object.values(redoDialogue).some(v => v && v.trim())
    if (!hasDraft) return
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [redoDialogue])
  const refreshDetail = useCallback((pid: number) => {
    commercialApi.getProduction(pid).then(setDetail).catch(e => setMsg(String(e instanceof Error ? e.message : e)))
  }, [])
  useEffect(() => { if (productionId) refreshDetail(productionId) }, [productionId, refreshDetail])

  const create = async () => {
    if (!resolution) { setMsg('能力档案未加载或为空，无法创建作品'); return }
    try {
      const r = await commercialApi.createProduction({
        template_version_id: sel.template, actor_version_id: sel.actorVersion,
        voice_profile_id: sel.voice, product_version_id: sel.productVersion,
        dialogue_locked: false, resolution_id: resolution,
      })
      setProductionId(r.production_id); setMsg('')
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const step = async (action: 'adapt' | 'plan') => {
    if (!productionId) return
    try {
      if (action === 'adapt') await commercialApi.adapt(productionId, '种草推荐')
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
      if (r.attempt_status === 'GENERATED') setMsg(`单元 ${unitKey} 生成完成（Mock 输出）`)
      else setMsg(`单元 ${unitKey} 状态：${r.attempt_status}`)
      refreshDetail(productionId)
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  const units: Unit[] = detail?.plan?.units || []
  return (
    <div>
      <CommercialNav />
      <h2>制作工作台</h2>
      <Section title="① 选择模板与素材">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <select style={input} onChange={e => setSel(s => ({ ...s, template: +e.target.value }))} defaultValue="">
            <option value="" disabled>选择模板版本</option>
            {templates.flatMap(t => t.versions.map(v => <option key={v.id} value={v.id}>{t.name} V{v.version}</option>))}
          </select>
          <select style={input} onChange={e => {
            const [actorVersion, voice] = e.target.value.split(':').map(Number)
            setSel(s => ({ ...s, actorVersion, voice }))
          }} defaultValue="">
            <option value="" disabled>选择达人（含音色）</option>
            {actors.flatMap(a => a.versions.flatMap(v => a.voices.map(vo =>
              <option key={`${v.id}:${vo.id}`} value={`${v.id}:${vo.id}`}>{a.name} V{v.version} + 音色#{vo.id}</option>)))}
          </select>
          <select style={input} onChange={e => setSel(s => ({ ...s, productVersion: +e.target.value }))} defaultValue="">
            <option value="" disabled>选择商品</option>
            {products.map(p => <option key={p.id} value={p.latest_version_id ?? p.current_version}>{p.name}（最新版）</option>)}
          </select>
          <select style={input} value={resolution} onChange={e => setResolution(e.target.value)}
            disabled={!caps || caps.resolutions.length === 0} aria-label="生成分辨率">
            <option value="" disabled>{caps ? '选择分辨率' : '能力档案加载中…'}</option>
            {(caps?.resolutions ?? []).map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <button style={btn} disabled={!sel.template || !sel.actorVersion || !sel.voice || !sel.productVersion || !resolution} onClick={create}>创建作品</button>
        </div>
        {caps && !caps.capability_verified && (
          <p style={{ fontSize: 12, color: '#8a6d3b', marginTop: 6 }}>
            能力档案为草案（DRAFT {caps.capability_version}）：分辨率 {caps.resolutions.join('/')}、
            时长 {caps.duration_min_ms / 1000}-{caps.duration_max_ms / 1000}s 来自公开文档，
            真实契约与模型效果尚未验证，不代表已具备真实生成能力。
          </p>
        )}
        {detail && caps && !caps.resolutions.includes(detail.resolution_id) && (
          <p style={{ color: '#b00', background: '#fdecea', padding: '6px 10px', borderRadius: 6, fontSize: 13 }}>
            作品 #{detail.id} 的分辨率 {detail.resolution_id} 已不在当前能力档案
            （{caps.resolutions.join('/')}）内：报价会被服务端拒绝。
            请使用当前支持的分辨率重建作品，或等待能力档案更新后重试。
          </p>
        )}
        {msg && <p style={{ color: '#b00' }}>{msg}</p>}
      </Section>
      {productionId && detail && (
        <>
          <Section title={`② 文案适配与生成计划（作品 #${productionId} · ${detail.status}）`} note={MOCK_NOTE}>
            <button style={btnAlt} onClick={() => step('adapt')}>执行文案适配 + 编译生成计划</button>
            {detail.plan?.shots?.map(s => (
              <div key={s.shot_id} style={card}>
                <b>{s.shot_id}</b>（目标 {((s.target_duration_ms ?? (s.end_ms - s.start_ms)) / 1000).toFixed(1)}s）
                <p style={{ margin: '6px 0' }}>台词：{s.dialogue || '—'}</p>
                <p style={{ margin: 0, color: '#666' }}>动作：{s.action || '—'}</p>
              </div>
            ))}
          </Section>
          {units.length > 0 && (
            <Section title="③ 逐单元报价与生成（生成/采用时长分开显示）">
              {units.map(u => (
                <div key={u.unit_key} style={card}>
                  <b>{u.unit_key}</b> 覆盖镜头 {u.covered_shot_keys.join('+')}
                  <span style={tag}>生成 {u.request_duration_ms / 1000}s</span>
                  <span style={tag}>采用 {u.adopt_ranges.map(([, a, b]) => `${a / 1000}-${b / 1000}s`).join('、')}</span>
                  <div style={{ marginTop: 8 }}>
                    <button style={btnAlt} onClick={() => quoteUnit(u.unit_key)}>① 报价</button>
                    {quotes[u.unit_key] && (
                      <>
                        <span style={{ marginRight: 8 }}>预计 ${quotes[u.unit_key].amount}（模拟价）</span>
                        <button style={btn} onClick={() => generateUnit(u.unit_key)}>② 确认并生成</button>
                      </>
                    )}
                  </div>
                  <RedoEntry unitKey={u.unit_key} productionId={productionId}
                    attempts={detail?.attempts || []} dialogueOverride={redoDialogue[u.unit_key]}
                    onDialogueChange={v => setRedoDialogue(prev => ({ ...prev, [u.unit_key]: v }))}
                    onDone={() => refreshDetail(productionId)} />
                </div>
              ))}
            </Section>
          )}
        </>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- 任务与作品 */
export function CommercialTasksPage() {
  const [productionId, setProductionId] = useState<number | null>(null)
  const [queryId, setQueryId] = useState<string>('')
  const [exportId, setExportId] = useState<number | null>(null)
  const [exportDetail, setExportDetail] = useState<{ id: number; kind: string; srt_content: string | null; srt_aligned: boolean; subtitled_path: string | null; total_adopt_ms: number } | null>(null)
  const [srtDraft, setSrtDraft] = useState('')
  const [burnMsg, setBurnMsg] = useState('')
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof commercialApi.getProduction>> | null>(null)
  const [msg, setMsg] = useState('')
  const refresh = useCallback(() => {
    if (productionId) commercialApi.getProduction(productionId).then(d => {
      setDetail(d)
      // 刷新后从服务端恢复最近导出（含字幕面板与烧录版状态）
      if (d.latest_export && exportId == null) {
        setExportId(d.latest_export.id)
        commercialApi.getExport(d.latest_export.id).then(ex => {
          setExportDetail(ex); setSrtDraft(ex.srt_content || '')
        }).catch(() => {})
      }
    }).catch(e => setMsg(String(e instanceof Error ? e.message : e)))
  }, [productionId, exportId])
  useEffect(refresh, [refresh])

  const review = async (attemptId: number, pass: boolean) => {
    const dims: Record<string, string | string[]> = {
      人物身份: 'PASS', 商品准确: 'PASS', 音色: 'PASS', 台词: pass ? 'PASS' : ['FAIL', '页面驳回：台词不合格'],
      口型: 'PASS', 动作与画面: 'PASS', 模板表达: 'PASS', 技术输出: 'PASS',
    }
    try { await commercialApi.review(attemptId, dims); refresh() } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const downloadExport = async (id: number, variant: 'master' | 'subtitled') => {
    const { API_BASE } = await import('../../api/client')
    const q = variant === 'subtitled' ? '?variant=subtitled' : ''
    const resp = await fetch(`${API_BASE}/api/commercial/exports/${id}/download${q}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
    if (!resp.ok) { setMsg('下载失败'); return }
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `export-${id}${variant === 'subtitled' ? '-subtitled' : ''}.mp4`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  const compose = async () => {
    if (!detail) return
    // 每个必需单元选最新合格版本，采用区间=该单元计划 adopt_ranges
    //（成片时长必须等于用户确认的计划采用区间之和，不被素材或快捷实现截短）
    const units = detail.plan?.units || []
    const selections: { attempt_id: number; ranges: number[][] }[] = []
    const missing: string[] = []
    for (const u of units) {
      const mine = detail.attempts
        .filter(a => a.unit_key === u.unit_key && a.status === 'REVIEW_APPROVED')
        .sort((x, y) => y.id - x.id)
      if (!mine.length) { missing.push(u.unit_key); continue }
      const best = mine[0]
      const ranges = (u.adopt_ranges || []).map(([, s, e]) => [s, e])
      selections.push({ attempt_id: best.id, ranges })
    }
    if (missing.length) {
      setMsg(`以下必需单元没有审核合格的版本，不能导出完整成片：${missing.join('、')}（可先重做并审核，服务端同样会阻断）`)
      return
    }
    if (!selections.length) { setMsg('制作计划缺少生成单元'); return }
    try {
      const r = await commercialApi.compose(detail.id, selections, true)
      setExportId(r.export_id)
      setMsg(`合成完成：导出 #${r.export_id}（${r.kind === 'partial_preview' ? '部分预览' : '完整成片'}，采用总长 ${(r.total_adopt_ms / 1000).toFixed(1)}s）`)
      const ex = await commercialApi.getExport(r.export_id)
      setExportDetail(ex); setSrtDraft(ex.srt_content || '')
      refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div>
      <CommercialNav />
      <h2>任务与作品</h2>
      <Section title="查询作品">
        <input style={input} placeholder="作品 ID" value={queryId} onChange={e => setQueryId(e.target.value)} />
        <button style={btn} onClick={() => setProductionId(Number(queryId) || null)}>查询</button>
        {msg && <p style={{ color: '#b00' }}>{msg}</p>}
      </Section>
      {detail && (
        <Section title={`作品 #${detail.id} · ${detail.status}`} note={detail.costs.mock ? MOCK_NOTE : undefined}>
          <p>费用：总计 ${detail.costs.total_usd} · 待结算 ${detail.costs.pending_usd}（{detail.costs.settlement_note}）</p>
          {detail.attempts.map(a => (
            <div key={a.id} style={card}>
              <b>尝试 #{a.id}</b>
              {a.unit_key && <span style={tag}>{a.unit_key}</span>}
              {a.attempt_no != null && a.attempt_no > 1 && <span style={tag}>第{a.attempt_no}次</span>}
              <span style={tag}>{a.status}</span>
              {a.prediction_id && <span style={tag}>{a.prediction_id}</span>}
              {a.error_message && <p style={{ color: '#b00' }}>{a.error_message}</p>}
              {a.status === 'GENERATED' && (
                <div style={{ marginTop: 8 }}>
                  <button style={btnAlt} onClick={() => review(a.id, true)}>审核通过</button>
                  <button style={btnAlt} onClick={() => review(a.id, false)}>驳回（台词）</button>
                </div>
              )}
            </div>
          ))}
          {detail.attempts.some(a => a.status === 'REVIEW_APPROVED') && (
            <button style={btn} onClick={compose}>合成已审核镜头（FFmpeg）并生成字幕</button>
          )}
          {exportId != null && (
            <div style={{ ...card, borderTop: '1px solid #eee' }}>
              <b>导出 #{exportId}</b>
              {exportDetail?.kind === 'partial_preview' && (
                <span style={{ ...tag, background: '#fff3e0', color: '#b26a00' }}>部分预览（非完整成片）</span>
              )}
              <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button style={btnAlt} onClick={() => downloadExport(exportId, 'master')}>下载无字幕母版</button>
                {exportDetail?.subtitled_path
                  ? <button style={btnAlt} onClick={() => downloadExport(exportId, 'subtitled')}>下载烧录字幕版</button>
                  : <span style={{ fontSize: 12, color: '#888', alignSelf: 'center' }}>烧录版未生成</span>}
              </div>
              {exportDetail && (
                <div style={{ marginTop: 10 }}>
                  {exportDetail.srt_aligned === false && (
                    <p style={{ color: '#b26a00', background: '#fff8e1', padding: '4px 8px', borderRadius: 6, fontSize: 12 }}>
                      字幕为未校对草稿（时间来自计划采用区间），烧录前请人工校对；烧录只生成独立副本，不改母版、不触发重新生成。
                    </p>
                  )}
                  <textarea style={{ width: '100%', minHeight: 120, fontFamily: 'monospace', fontSize: 12 }}
                    value={srtDraft} onChange={e => setSrtDraft(e.target.value)} />
                  <button style={btn} onClick={async () => {
                    setBurnMsg('烧录中…')
                    try {
                      await commercialApi.burnExport(exportId, srtDraft)
                      const ex = await commercialApi.getExport(exportId)
                      setExportDetail(ex); setBurnMsg('烧录完成（母版未改动，可下载烧录版）')
                    } catch (e) { setBurnMsg(e instanceof Error ? e.message : String(e)) }
                  }}>校对完成并烧录字幕</button>
                  {burnMsg && <span style={{ marginLeft: 8, fontSize: 12 }}>{burnMsg}</span>}
                </div>
              )}
            </div>
          )}
        </Section>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- 设置与费用 */
export function CommercialSettingsPage() {
  const [total, setTotal] = useState('')
  const [msg, setMsg] = useState('')
  const [pool, setPool] = useState<{ total_usd: string; scope: string; paused: boolean } | null>(null)
  // 安全配置（管理员）：密钥只写不读；保存不触发任何付费调用
  const [apiKey, setApiKey] = useState('')
  const [geminiId, setGeminiId] = useState('')
  const [h3Id, setH3Id] = useState('')
  const [provider, setProvider] = useState<{ has_atlas_api_key: boolean; gemini_analysis_model_id: string; h3_developer_reference_model_id: string; commercial_verified_models: string; commercial_mock_mode: boolean; commercial_paid_execution_enabled: boolean } | null>(null)
  const [providerMsg, setProviderMsg] = useState('')
  useEffect(() => {
    commercialApi.getProviderSettings().then(s => {
      setProvider(s); setGeminiId(s.gemini_analysis_model_id || ''); setH3Id(s.h3_developer_reference_model_id || '')
    }).catch(() => setProvider(null))  // 非管理员/未配置时静默
  }, [])
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
  const set = async () => {
    try { const r = await commercialApi.setBudget(total); setPool(r); setMsg('预算已更新') } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div>
      <CommercialNav />
      <h2>设置与费用</h2>
      <Section title="演示预算（管理员）" note={`${MOCK_NOTE}；该预算属于演示（mock）池，不构成真实付费授权，切换真实模式不继承`}>
        <input style={input} placeholder="USD 金额，如 50.00" value={total} onChange={e => setTotal(e.target.value)} />
        <button style={btn} onClick={set}>保存演示预算</button>
        {pool && <p>当前预算池：${pool.total_usd}（scope={pool.scope}）{pool.paused ? ' · 已暂停（真实费用超预留）' : ''}</p>}
        {msg && <p>{msg}</p>}
      </Section>
      <Section title="安全配置（管理员）：密钥与模型 ID"
        note="密钥仅写入加密存储、永不回传页面或日志；保存动作不发起付费调用；能力验证状态与真实联调分开">
        {provider == null
          ? <p style={{ color: '#888' }}>需要管理员权限查看。</p>
          : <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
                <input style={{ ...input, width: 260 }} type="password" placeholder={provider.has_atlas_api_key ? 'Atlas API 密钥（已配置，输入以更换）' : 'Atlas API 密钥（未配置）'}
                  value={apiKey} onChange={e => setApiKey(e.target.value)} />
                <input style={{ ...input, width: 260 }} placeholder="Gemini 解析模型精确 ID" value={geminiId} onChange={e => setGeminiId(e.target.value)} />
                <input style={{ ...input, width: 260 }} placeholder="H3 生成模型精确 ID" value={h3Id} onChange={e => setH3Id(e.target.value)} />
                <button style={btn} onClick={saveProvider}>保存配置</button>
              </div>
              {providerMsg && <p style={{ color: '#2f6f4f' }}>{providerMsg}</p>}
              <ul style={{ fontSize: 13, color: '#555', margin: '6px 0 0', paddingLeft: 18 }}>
                <li>密钥：{provider.has_atlas_api_key ? '已配置（不显示）' : '未配置'}</li>
                <li>已验证能力清单：{provider.commercial_verified_models || '（空——模型能力未经真实契约验证，付费执行保持阻断）'}</li>
                <li>模式：{provider.commercial_mock_mode ? '开发模拟（mock）' : '真实'} · 付费执行总开关：{provider.commercial_paid_execution_enabled ? '开' : '关（默认）'}</li>
              </ul>
            </>}
      </Section>
      <Section title="模型能力状态">
        <ul style={{ fontSize: 13, color: '#555' }}>
          <li>Gemini 解析（Gemini 3 Flash Preview）：适配器与 Fixture 完成；<b>真实契约未验证（BLOCKED）</b></li>
          <li>视频生成（MiniMax H3 Developer Reference）：适配器与 Fixture 完成；<b>真实契约未验证（BLOCKED）</b></li>
          <li>付费执行总开关：默认关闭；真实联调需管理员验证能力并批准预算后开启</li>
        </ul>
      </Section>
    </div>
  )
}
