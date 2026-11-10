/**
 * 商业短视频模板：六个业务页面（T08）。
 * 连接真实 /api/commercial；Mock 供应商模式下全流程可用，
 * 页面明确标识“测试/模拟”状态，不冒充真实联调。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { commercialApi, uploadAsset, type ProductItem, type TemplateItem, type ActorItem, type Unit } from './api'
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

/* ---------------------------------------------------------------- 制作工作台 */
export function CommercialStudioPage() {
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [actors, setActors] = useState<ActorItem[]>([])
  const [products, setProducts] = useState<ProductItem[]>([])
  const [sel, setSel] = useState({ template: 0, actorVersion: 0, voice: 0, productVersion: 0 })
  const [productionId, setProductionId] = useState<number | null>(null)
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof commercialApi.getProduction>> | null>(null)
  const [quotes, setQuotes] = useState<Record<string, { id: number; amount: string }>>({})
  const [msg, setMsg] = useState('')
  const reqIdBase = useRef(`ui-${Date.now()}`)

  useEffect(() => {
    commercialApi.listTemplates().then(r => setTemplates(r.items))
    commercialApi.listActors().then(r => setActors(r.items))
    commercialApi.listProducts().then(r => setProducts(r.items))
  }, [])
  const refreshDetail = useCallback((pid: number) => {
    commercialApi.getProduction(pid).then(setDetail).catch(e => setMsg(String(e instanceof Error ? e.message : e)))
  }, [])
  useEffect(() => { if (productionId) refreshDetail(productionId) }, [productionId, refreshDetail])

  const create = async () => {
    try {
      const r = await commercialApi.createProduction({
        template_version_id: sel.template, actor_version_id: sel.actorVersion,
        voice_profile_id: sel.voice, product_version_id: sel.productVersion,
        dialogue_locked: false, resolution_id: '720p',
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
            {products.map(p => <option key={p.id} value={p.current_version}>{p.name}（最新版）</option>)}
          </select>
          <button style={btn} disabled={!sel.template || !sel.actorVersion || !sel.voice || !sel.productVersion} onClick={create}>创建作品</button>
        </div>
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
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof commercialApi.getProduction>> | null>(null)
  const [msg, setMsg] = useState('')
  const refresh = useCallback(() => {
    if (productionId) commercialApi.getProduction(productionId).then(setDetail).catch(e => setMsg(String(e instanceof Error ? e.message : e)))
  }, [productionId])
  useEffect(refresh, [refresh])

  const review = async (attemptId: number, pass: boolean) => {
    const dims: Record<string, string | string[]> = {
      人物身份: 'PASS', 商品准确: 'PASS', 音色: 'PASS', 台词: pass ? 'PASS' : ['FAIL', '页面驳回：台词不合格'],
      口型: 'PASS', 动作与画面: 'PASS', 模板表达: 'PASS', 技术输出: 'PASS',
    }
    try { await commercialApi.review(attemptId, dims); refresh() } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  const compose = async () => {
    if (!detail) return
    const approved = detail.attempts.filter(a => a.status === 'REVIEW_APPROVED')
    if (!approved.length) { setMsg('没有通过审核的镜头，不能合成'); return }
    try {
      const r = await commercialApi.compose(detail.id, approved.map(a => ({ attempt_id: a.id, ranges: [[0, 4000]] })))
      setExportId(r.export_id)
      setMsg(`合成完成：导出 #${r.export_id}（采用总长 ${(r.total_adopt_ms / 1000).toFixed(1)}s）`)
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
              <b>尝试 #{a.id}</b><span style={tag}>{a.status}</span>
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
            <button style={btnAlt} onClick={async () => {
              const { API_BASE } = await import('../../api/client')
              const resp = await fetch(`${API_BASE}/api/commercial/exports/${exportId}/download`, {
                headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
              })
              if (!resp.ok) { setMsg('下载失败'); return }
              const blob = await resp.blob()
              const a = document.createElement('a')
              a.href = URL.createObjectURL(blob)
              a.download = `export-${exportId}.mp4`
              a.click()
              URL.revokeObjectURL(a.href)
            }}>下载成片（导出 #{exportId}）</button>
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
  const [pool, setPool] = useState<{ total_usd: string; paused: boolean } | null>(null)
  const set = async () => {
    try { const r = await commercialApi.setBudget(total); setPool(r); setMsg('预算已更新') } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div>
      <CommercialNav />
      <h2>设置与费用</h2>
      <Section title="测试总预算（管理员）" note={MOCK_NOTE}>
        <input style={input} placeholder="USD 金额，如 50.00" value={total} onChange={e => setTotal(e.target.value)} />
        <button style={btn} onClick={set}>保存预算</button>
        {pool && <p>当前预算池：${pool.total_usd}{pool.paused ? '（已暂停：真实费用超预留）' : ''}</p>}
        {msg && <p>{msg}</p>}
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
