/**
 * 达人库 / 商品库（设计体系版）：图片预览、音色试听（鉴权 blob）、授权状态、卖点分组。
 * 业务接口不变（listActors/listProducts/createX/bindVoice/uploadAsset）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import Button from '../../components/ui/Button'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import { commercialApi, uploadAsset, type ActorItem, type ProductItem } from './api'
import { AssetImage, AssetAudio } from './assetPreview'
import './commercial.css'

/* ---------------------------------------------------------------- 达人库 */
export function CommercialActorsPage() {
  const [actors, setActors] = useState<ActorItem[]>([])
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const [pending, setPending] = useState<{ images?: number[]; voice?: number }>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const imgRef = useRef<HTMLInputElement>(null)
  const voiceRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    setLoading(true); setError('')
    commercialApi.listActors()
      .then(r => setActors(r.items))
      .catch(e => setError(String(e instanceof Error ? e.message : e)))
      .finally(() => setLoading(false))
  }, [])
  useEffect(refresh, [refresh])

  const create = async () => {
    if (!pending.images?.length) { setMsg('请先上传达人形象图'); return }
    try {
      const r = await commercialApi.createActor(name || '未命名达人', pending.images, '页面创建')
      if (pending.voice != null) {
        await commercialApi.bindVoice(r.actor_id, pending.voice)
      }
      setMsg(`达人已创建${pending.voice != null ? '并绑定音色' : '（未绑定音色——生成前必须绑定）'}`)
      setName(''); setPending({}); refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <CommercialLayout>
      <CommercialPageHead title="达人库" desc="管理我方达人形象、授权音色与绑定状态；生成口播前必须完成声音绑定。" />
      <MockModeNote />

      <div className="pf-card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="cv-field" style={{ margin: 0, width: 200 }}>
            <label>达人名称</label>
            <input className="cv-input" value={name} onChange={e => setName(e.target.value)} placeholder="如：达人一号" />
          </div>
          <div className="cv-field" style={{ margin: 0 }}>
            <label>形象图（授权）</label>
            <input ref={imgRef} type="file" accept="image/*" multiple hidden onChange={async e => {
              const files = Array.from(e.target.files || []); if (!files.length) return
              try { const assets = await Promise.all(files.map(f => uploadAsset(f, 'owned_actor_image', '达人授权形象'))); setPending(p => ({ ...p, images: [...(p.images || []), ...assets.map(a => a.id)] })) } catch (err) { setMsg(String(err)) }
            }} />
            <Button variant="outline" size="sm" onClick={() => imgRef.current?.click()}>上传形象图</Button>
          </div>
          <div className="cv-field" style={{ margin: 0 }}>
            <label>音色样本（授权）</label>
            <input ref={voiceRef} type="file" accept="audio/*" hidden onChange={async e => {
              const f = e.target.files?.[0]; if (!f) return
              try { const a = await uploadAsset(f, 'owned_voice_reference', '达人授权音色'); setPending(p => ({ ...p, voice: a.id })) } catch (err) { setMsg(String(err)) }
            }} />
            <Button variant="outline" size="sm" onClick={() => voiceRef.current?.click()}>上传音色样本</Button>
          </div>
          <Button variant="lime" onClick={create}>创建达人</Button>
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 10, alignItems: 'center' }}>
          {(pending.images || []).map(id => <AssetImage key={id} assetId={id} alt="待绑定形象图" />)}
          {pending.voice != null && <AssetAudio assetId={pending.voice} />}
          {msg && <span style={{ fontSize: 13, color: 'var(--pf-ink)' }}>{msg}</span>}
        </div>
      </div>

      <div className="pf-template-grid">
        {loading && <p className="pf-muted">加载达人中…</p>}
        {!loading && error && <p style={{ color: '#b3261e' }}>加载失败：{error}</p>}
        {actors.map(a => {
          const latest = a.versions[0]
          const voice = a.voices[0]
          return (
            <div key={a.id} className="pf-template-card" style={{ cursor: 'default' }}>
              <div style={{ display: 'flex', gap: 10, padding: 14, alignItems: 'center' }}>
                <AssetImage assetId={latest?.image_asset_ids?.[0]} alt={`${a.name} 形象`} size={88} />
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ margin: 0 }}>{a.name}</h3>
                  <p className="pf-muted" style={{ fontSize: 12, margin: '4px 0 0' }}>V{a.current_version}</p>
                </div>
              </div>
              <div className="body">
                <p className="pf-muted" style={{ fontSize: 12 }}>音色试听（授权样本仅作绑定，不直接入片）：</p>
                {voice ? <AssetAudio assetId={voice.audio_asset_id} /> : <p style={{ fontSize: 13 }}>未绑定音色（不能生成口播）</p>}
                <div className="pf-tags">
                  <span>{voice ? (voice.authorized_until ? `授权至 ${voice.authorized_until.slice(0, 10)}` : '长期授权') : '待授权'}</span>
                  <span>{a.versions.length} 个版本</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      {!loading && !error && actors.length === 0 && <p className="pf-muted" style={{ padding: '24px 0', textAlign: 'center' }}>还没有达人，先在上方创建。</p>}
    </CommercialLayout>
  )
}

/* ---------------------------------------------------------------- 商品库 */
type ProductFull = ProductItem & {
  form?: string; specs_text?: string
  claims?: Array<{ claim_id: string; text: string; approved?: boolean }>
  forbidden_phrases?: string[]; allowed_actions?: string[]
  image_asset_ids?: number[]
}

export function CommercialProductsPage() {
  const [products, setProducts] = useState<ProductFull[]>([])
  const [name, setName] = useState(''); const [form, setForm] = useState('贴片')
  const [claim, setClaim] = useState(''); const [action, setAction] = useState('手持正面展示')
  const [specs, setSpecs] = useState('')
  const [description, setDescription] = useState(''); const [sourceUrl, setSourceUrl] = useState('')
  const [imageIds, setImageIds] = useState<number[]>([])
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const imgRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    setLoading(true); setError('')
    commercialApi.listProducts()
      .then(r => setProducts(r.items))
      .catch(e => setError(String(e instanceof Error ? e.message : e)))
      .finally(() => setLoading(false))
  }, [])
  useEffect(refresh, [refresh])

  const create = async () => {
    if (!imageIds.length) { setMsg('请先上传商品图'); return }
    try {
      await commercialApi.createProduct({
        name: name || '未命名商品', form, specs_text: specs, image_asset_ids: imageIds,
        claims: claim ? [{ claim_id: `c-${Date.now()}`, text: claim, approved: true, source: '品牌资料' }] : [],
        forbidden_phrases: [], allowed_actions: action ? [action] : [],
      })
      setMsg('商品已创建'); setName(''); setClaim(''); setSpecs(''); setDescription(''); setSourceUrl(''); setImageIds([]); refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <CommercialLayout>
      <CommercialPageHead title="商品库" desc="商品图、规格与审核卖点；只有审核通过的卖点可以进入台词。" />
      <MockModeNote />

      <div className="pf-card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="cv-field" style={{ margin: 0, width: 180 }}><label>商品名称</label>
            <input className="cv-input" value={name} onChange={e => setName(e.target.value)} /></div>
          <div className="cv-field" style={{ margin: 0, width: 120 }}><label>形态</label>
            <select className="cv-input" value={form} onChange={e => setForm(e.target.value)}>
              <option value="贴片">贴片</option><option value="瓶装">瓶装</option><option value="盒装">盒装</option>
            </select></div>
          <div className="cv-field" style={{ margin: 0, width: 240 }}><label>审核卖点（进入台词的唯一来源）</label>
            <input className="cv-input" value={claim} onChange={e => setClaim(e.target.value)} /></div>
          <div className="cv-field" style={{ margin: 0, width: 180 }}><label>允许展示动作</label>
            <input className="cv-input" value={action} onChange={e => setAction(e.target.value)} /></div>
          <div className="cv-field" style={{ margin: 0, width: 200 }}><label>规格（可选）</label>
            <input className="cv-input" value={specs} onChange={e => setSpecs(e.target.value)} /></div>
          <div className="cv-field" style={{ margin: 0, width: 260 }}><label>商品描述（可选）</label>
            <input className="cv-input" value={description} onChange={e => setDescription(e.target.value)} placeholder="如：水状质地，滴管取用" /></div>
          <div className="cv-field" style={{ margin: 0, width: 280 }}><label>官方商品页（可选）</label>
            <input className="cv-input" value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="粘贴官网或旗舰店链接" /></div>
          <div className="cv-field" style={{ margin: 0 }}>
            <label>商品图</label>
            <input ref={imgRef} type="file" accept="image/*" multiple hidden onChange={async e => {
              const files = Array.from(e.target.files || []); if (!files.length) return
              try { const assets = await Promise.all(files.map(f => uploadAsset(f, 'owned_product_image', '商品图'))); setImageIds(prev => [...prev, ...assets.map(a => a.id)]) } catch (err) { setMsg(String(err)) }
            }} />
            <Button variant="outline" size="sm" onClick={() => imgRef.current?.click()}>上传商品图</Button>
          </div>
          <Button variant="lime" onClick={create}>创建商品</Button>
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 10, alignItems: 'center' }}>
          {imageIds.map(id => <AssetImage key={id} assetId={id} alt="待保存商品图" />)}
          {msg && <span style={{ fontSize: 13 }}>{msg}</span>}
        </div>
      </div>

      <div className="pf-template-grid">
        {loading && <p className="pf-muted">加载商品中…</p>}
        {!loading && error && <p style={{ color: '#b3261e' }}>加载失败：{error}</p>}
        {products.map(p => (
          <div key={p.id} className="pf-template-card" style={{ cursor: 'default' }}>
            <div style={{ display: 'flex', gap: 10, padding: 14, alignItems: 'center' }}>
              <AssetImage assetId={p.image_asset_ids?.[0]} alt={p.name} size={88} />
              <div style={{ minWidth: 0 }}>
                <h3 style={{ margin: 0 }}>{p.name}</h3>
                <p className="pf-muted" style={{ fontSize: 12, margin: '4px 0 0' }}>
                  {p.form || '—'} · V{p.current_version}{p.specs_text ? ` · ${p.specs_text.slice(0, 18)}` : ''}
                </p>
              </div>
            </div>
            <div className="body">
              <div className="cv-card-actions" style={{ marginBottom: 8 }}>
                <Button variant="outline" size="sm" onClick={async () => {
                  try {
                    const run = await commercialApi.researchProduct(p.id, { image_asset_ids: p.image_asset_ids ?? [], name: p.name, description: description || p.specs_text || '', source_urls: sourceUrl ? [sourceUrl] : [], real_gemini: Boolean(sourceUrl) })
                    setMsg(`商品 #${p.id} 研究任务 #${run.id} 已创建，候选 ${run.candidates.length} 条`)
                  } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
                }}>开始 AI 研究</Button>
              </div>
              {(p.claims ?? []).filter(c => c.approved).length > 0
                ? <div className="pf-tags">{(p.claims ?? []).filter(c => c.approved).map(c => <span key={c.claim_id}>{c.text}</span>)}</div>
                : <p className="pf-muted" style={{ fontSize: 12 }}>暂无审核卖点（台词将无可用内容）</p>}
              {(p.allowed_actions ?? []).length > 0 && (
                <p className="pf-muted" style={{ fontSize: 12, marginTop: 6 }}>展示动作：{(p.allowed_actions ?? []).join('、')}</p>
              )}
              {(p.forbidden_phrases ?? []).length > 0 && (
                <p className="pf-muted" style={{ fontSize: 12 }}>禁止表述：{(p.forbidden_phrases ?? []).join('、')}</p>
              )}
            </div>
          </div>
        ))}
      </div>
      {!loading && !error && products.length === 0 && <p className="pf-muted" style={{ padding: '24px 0', textAlign: 'center' }}>还没有商品，先在上方创建。</p>}
    </CommercialLayout>
  )
}

export function CommercialWardrobePage() {
  const [items, setItems] = useState<import('./api').WardrobeItem[]>([])
  const [name, setName] = useState(''); const [category, setCategory] = useState('上衣')
  const [scope, setScope] = useState('team'); const [assetId, setAssetId] = useState<number | null>(null)
  const [msg, setMsg] = useState(''); const fileRef = useRef<HTMLInputElement>(null)
  const refresh = useCallback(() => { commercialApi.listWardrobes().then(r => setItems(r.items)).catch(e => setMsg(String(e))) }, [])
  useEffect(refresh, [refresh])
  const create = async () => {
    if (!name.trim()) { setMsg('请填写服饰名称'); return }
    try {
      const item = await commercialApi.createWardrobe({ name, category, scope })
      if (assetId != null) await commercialApi.createWardrobeVersion(item.id, { asset_ids: [assetId] })
      setMsg('服饰已保存，可在镜头换装中选择'); setName(''); setAssetId(null); refresh()
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <CommercialLayout>
      <CommercialPageHead title="服饰库" desc="维护可复用的服饰单品和穿搭素材，支持团队共享。" />
      <MockModeNote />
      <div className="pf-card" style={{ padding: 16, marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="cv-field" style={{ margin: 0, width: 220 }}><label>服饰名称</label><input className="cv-input" value={name} onChange={e => setName(e.target.value)} placeholder="如：米色针织套装" /></div>
          <div className="cv-field" style={{ margin: 0, width: 140 }}><label>分类</label><select className="cv-input" value={category} onChange={e => setCategory(e.target.value)}><option>上衣</option><option>下装</option><option>连衣裙</option><option>外套</option><option>鞋子</option><option>配饰</option><option>完整穿搭</option></select></div>
          <div className="cv-field" style={{ margin: 0, width: 140 }}><label>共享范围</label><select className="cv-input" value={scope} onChange={e => setScope(e.target.value)}><option value="personal">个人</option><option value="team">团队</option><option value="project">项目</option></select></div>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={async e => { const f=e.target.files?.[0]; if(!f)return; try{const a=await uploadAsset(f,'owned_wardrobe_image','授权服饰素材');setAssetId(a.id)}catch(err){setMsg(String(err))} }} />
          <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>上传服饰图</Button>
          <Button variant="lime" onClick={create}>保存服饰</Button>
        </div>
        {assetId != null && <div style={{ marginTop: 10 }}><AssetImage assetId={assetId} alt="待保存服饰图" /></div>}
        {msg && <p className="pf-muted" style={{ margin: '10px 0 0' }}>{msg}</p>}
      </div>
      <div className="pf-template-grid">
        {items.map(item => <div key={item.id} className="pf-template-card"><div style={{ padding: 14 }}><h3 style={{ margin: 0 }}>{item.name}</h3><p className="pf-muted" style={{ fontSize: 12 }}>{item.category} · {item.scope} · {item.versions.length} 个版本</p></div><div className="body"><p className="pf-muted" style={{ fontSize: 12 }}>服饰版本可以绑定到指定达人，也可以在镜头级换装中选择。</p></div></div>)}
      </div>
    </CommercialLayout>
  )
}
