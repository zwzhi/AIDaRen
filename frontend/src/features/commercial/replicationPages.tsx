import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Button from '../../components/ui/Button'
import CommercialLayout, { CommercialPageHead, MockModeNote } from './CommercialLayout'
import {
  createReplicationFixture,
  replicationApi,
  type AnchorSet,
  type ReplicationMode,
  type ReplicationProject,
  type ScriptVersion,
  type ShotGraph,
  type VoiceRender,
} from './replicationApi'
import './commercial.css'

type LocalState = ReturnType<typeof createReplicationFixture>

const stages = ['分析', 'Shot Graph', '脚本', '脚本批准', '锚帧 / 声音', '预览']

function stageIndex(project: ReplicationProject | null, graph: ShotGraph | null, script: ScriptVersion | null, anchors: AnchorSet | null, voice: VoiceRender | null) {
  if (!project) return 0
  if (project.preview_status === 'ready') return 6
  if (anchors?.status === 'approved' && voice?.status === 'approved') return 5
  if (script?.status === 'approved') return 4
  if (script) return 3
  if (graph?.confirmed) return 2
  if (project.status === 'analyzed') return 1
  return 0
}

export default function CommercialReplicationPage() {
  const [searchParams] = useSearchParams()
  const initialProductionId = Number(searchParams.get('production_id') || searchParams.get('production') || 0)
  const [productionId, setProductionId] = useState(initialProductionId)
  const [mode, setMode] = useState<ReplicationMode>('structural_rewrite')
  const [referenceVideo, setReferenceVideo] = useState('参考视频（本地 Mock）')
  const [targetProduct, setTargetProduct] = useState('目标商品')
  const [actorName, setActorName] = useState('授权达人')
  const [marketingGoal, setMarketingGoal] = useState('种草推荐')
  const [project, setProject] = useState<ReplicationProject | null>(null)
  const [graph, setGraph] = useState<ShotGraph | null>(null)
  const [script, setScript] = useState<ScriptVersion | null>(null)
  const [anchors, setAnchors] = useState<AnchorSet | null>(null)
  const [voice, setVoice] = useState<VoiceRender | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState('')
  const [fixture, setFixture] = useState<LocalState | null>(null)

  const routeReason = project?.route_reason || '跨商品复刻默认保留结构并重写台词。'
  const risks = project?.risks || ['需要确认参考视频改编权、达人肖像权和声音授权']
  const highFidelityAllowed = project?.rights_status === 'verified' && project.product_match_status === 'matched'
  const scriptApproved = script?.status === 'approved' || project?.script_approved === true
  const currentStage = stageIndex(project, graph, script, anchors, voice)

  useEffect(() => {
    if (!productionId) return
    let alive = true
    replicationApi.get(productionId).then(value => { if (alive) setProject(value) }).catch(() => undefined)
    return () => { alive = false }
  }, [productionId])

  const create = async () => {
    if (!productionId) { setMsg('请先从现有作品进入，或填写 production_id'); return }
    setBusy('create'); setMsg('')
    const payload = { production_id: productionId, mode, reference_video_name: referenceVideo, target_product_name: targetProduct, actor_name: actorName, marketing_goal: marketingGoal }
    try {
      const value = await replicationApi.create(payload)
      setProject(value)
      setMsg('复刻项目已创建')
    } catch {
      const local = createReplicationFixture(payload)
      setFixture(local); setProject(local.project); setGraph(null); setScript(null); setAnchors(null); setVoice(null)
      setMsg('后端未连接，已切换本地 Mock/Fixture')
    } finally { setBusy('') }
  }

  const analyze = async () => {
    if (!project) return
    setBusy('analyze')
    try {
      const graphValue = await replicationApi.analyze(project.id)
      setGraph(graphValue)
      setProject({ ...project, status: 'analyzed' })
    } catch {
      const local = fixture || createReplicationFixture({ production_id: project.production_id, mode: project.mode, reference_video_name: referenceVideo, target_product_name: targetProduct, actor_name: actorName, marketing_goal: marketingGoal })
      local.project.status = 'analyzed'; setFixture(local); setProject(local.project); setGraph(local.shotGraph); setScript(null); setAnchors(null); setVoice(null); setMsg('分析使用本地 Fixture 完成')
    } finally { setBusy('') }
  }

  const confirmGraph = async () => {
    if (!project || !graph) return
    setBusy('graph')
    try { setGraph(await replicationApi.confirmShotGraph(project.id)) }
    catch { setGraph({ ...graph, confirmed: true }); setProject({ ...project, status: 'script_review' }); setMsg('Shot Graph 已确认（Mock）') }
    finally { setBusy('') }
  }

  const generateScript = async () => {
    if (!project || !graph?.confirmed) return
    setBusy('script')
    try { setScript(await replicationApi.createScript(project.id)) }
    catch {
      const local = fixture || createReplicationFixture({ production_id: project.production_id, mode: project.mode, reference_video_name: referenceVideo, target_product_name: targetProduct, actor_name: actorName, marketing_goal: marketingGoal })
      setScript(local.script); setMsg('脚本已生成（Mock）')
    } finally { setBusy('') }
  }

  const approveScript = async () => {
    if (!script) return
    setBusy('approve-script')
    try { setScript(await replicationApi.approveScript(script.id)); setProject(project ? { ...project, script_approved: true, status: 'anchor_review' } : project) }
    catch { setScript({ ...script, status: 'approved' }); setProject(project ? { ...project, script_approved: true, status: 'anchor_review' } : project); setMsg('脚本已批准，可进入锚帧与声音') }
    finally {
      const local = fixture || createReplicationFixture({ production_id: project?.production_id || productionId, mode: project?.mode || mode, reference_video_name: referenceVideo, target_product_name: targetProduct, actor_name: actorName, marketing_goal: marketingGoal })
      setFixture(local); setAnchors(local.anchorSet); setVoice(local.voice); setBusy('')
    }
  }

  const approveAssets = async () => {
    if (!scriptApproved || !anchors || !voice) return
    setBusy('assets')
    try { await replicationApi.approveAnchors(anchors.id); await replicationApi.approveVoice(voice.id) }
    catch { /* fixture path */ }
    setAnchors({ ...anchors, status: 'approved' }); setVoice({ ...voice, status: 'approved' }); setProject(project ? { ...project, anchors_approved: true, voice_approved: true, status: 'voice_ready' } : project); setMsg('锚帧和声音占位已批准')
    setBusy('')
  }

  const createPreview = async () => {
    if (!project || !scriptApproved) return
    setBusy('preview')
    try { const result = await replicationApi.createPreview(project.id); setProject({ ...project, preview_status: result.status === 'ready' ? 'ready' : 'queued', status: result.status === 'ready' ? 'preview_ready' : project.status }); setMsg(result.status === 'ready' ? '预览已就绪' : '预览任务已排队') }
    catch { setProject({ ...project, preview_status: 'ready', status: 'preview_ready' }); setMsg('预览已生成（Mock），可从最近成功阶段恢复') }
    finally { setBusy('') }
  }

  const modeCards = useMemo(() => [
    { id: 'structural_rewrite' as const, title: '结构改写', description: '保留 Hook、痛点、证明与 CTA 节奏，重写脚本和画面。', recommended: project?.recommended_mode === 'structural_rewrite' || !project, risk: '商品事实与商品露出需复核', estimate: '约 12 分钟 · ¥12.00' },
    { id: 'high_fidelity' as const, title: '高保真复刻', description: '保留镜头顺序、时长和构图，替换达人、商品与声音。', recommended: project?.recommended_mode === 'high_fidelity', risk: highFidelityAllowed ? '需完整权利和同 SKU 证据' : '权利或商品匹配未通过，暂不可用', estimate: '约 18 分钟 · ¥18.00' },
  ], [highFidelityAllowed, project])

  return (
    <CommercialLayout>
      <CommercialPageHead title="商业短视频复刻" desc="使用现有 production_id，从分析到 Mock 预览完成可审核的最小流程。" backTo="/commercial/studio" backLabel="返回制作工作台" />
      <MockModeNote />

      <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>① 创建入口</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}>
          <label className="cv-field" style={{ margin: 0 }}>production_id<input className="cv-input" type="number" value={productionId || ''} onChange={e => setProductionId(Number(e.target.value))} /></label>
          <label className="cv-field" style={{ margin: 0 }}>参考视频<input className="cv-input" value={referenceVideo} onChange={e => setReferenceVideo(e.target.value)} /></label>
          <label className="cv-field" style={{ margin: 0 }}>目标商品<input className="cv-input" value={targetProduct} onChange={e => setTargetProduct(e.target.value)} /></label>
          <label className="cv-field" style={{ margin: 0 }}>目标达人<input className="cv-input" value={actorName} onChange={e => setActorName(e.target.value)} /></label>
          <label className="cv-field" style={{ margin: 0 }}>营销目标<input className="cv-input" value={marketingGoal} onChange={e => setMarketingGoal(e.target.value)} /></label>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 10, marginTop: 14 }}>
          {modeCards.map(card => <button key={card.id} type="button" disabled={card.id === 'high_fidelity' && !highFidelityAllowed} onClick={() => setMode(card.id)} className="cv-shot" style={{ textAlign: 'left', padding: 14, cursor: card.id === 'high_fidelity' && !highFidelityAllowed ? 'not-allowed' : 'pointer', border: mode === card.id ? '2px solid var(--pf-lime)' : undefined, opacity: card.id === 'high_fidelity' && !highFidelityAllowed ? 0.62 : 1 }}>
            <strong>{card.title}</strong>{card.recommended && <span className="cv-section-badge" style={{ marginLeft: 8 }}>推荐</span>}
            <p style={{ margin: '8px 0 4px', fontSize: 13 }}>{card.description}</p><p className="pf-muted" style={{ margin: 0, fontSize: 12 }}>推荐原因：{routeReason}</p><p className="pf-muted" style={{ margin: '4px 0', fontSize: 12 }}>风险：{card.risk}{risks.length ? ` · ${risks[0]}` : ''}</p><p className="pf-muted" style={{ margin: 0, fontSize: 12 }}>预计：{card.estimate}</p>
          </button>)}
        </div>
        <div className="cv-card-actions"><Button variant="lime" disabled={!productionId || busy === 'create'} onClick={create}>{busy === 'create' ? '创建中…' : '创建复刻项目'}</Button>{msg && <span className="pf-muted" style={{ fontSize: 13 }}>{msg}</span>}</div>
      </div>

      <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>流程状态</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{stages.map((label, index) => <span key={label} className={`cv-status-tag ${index < currentStage ? 'is-approved' : index === currentStage ? 'is-generated' : 'is-pending'}`}>{index + 1}. {label}</span>)}</div>
        {project && <p className="pf-muted" style={{ fontSize: 12, margin: '10px 0 0' }}>项目 #{project.id} · production #{project.production_id} · {project.mode} · {project.status}</p>}
      </div>

      {project && <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>② 分析 → Shot Graph</h3>
        <Button variant="outline" size="sm" disabled={busy !== ''} onClick={analyze}>{busy === 'analyze' ? '分析中…' : '开始分析'}</Button>
        {graph && <div style={{ marginTop: 12 }}>{graph.shots.map(shot => <div className="cv-shot" key={shot.shot_key} style={{ padding: 10, marginTop: 8 }}><strong>{shot.shot_key} · {shot.purpose}</strong><span className="pf-muted" style={{ marginLeft: 8, fontSize: 12 }}>{(shot.start_ms / 1000).toFixed(1)}s–{(shot.end_ms / 1000).toFixed(1)}s · 商品 {shot.product_presence} · 置信度 {Math.round(shot.product_confidence * 100)}%</span><div style={{ fontSize: 13, marginTop: 4 }}>{shot.action}</div></div>)}<div className="cv-card-actions"><Button variant="outline" size="sm" disabled={graph.confirmed || busy !== ''} onClick={confirmGraph}>确认 Shot Graph</Button><Button variant="lime" size="sm" disabled={!graph.confirmed || busy !== ''} onClick={generateScript}>生成脚本</Button></div></div>}
      </div>}

      {project && <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>③ 脚本与脚本批准</h3>
        {!script && <p className="pf-muted" style={{ fontSize: 13 }}>确认 Shot Graph 后生成结构化脚本。</p>}
        {script && <>{script.shots.map(shot => <div className="cv-shot" key={shot.shot_key} style={{ padding: 10, marginTop: 8 }}><strong>{shot.shot_key}</strong><div style={{ fontSize: 13, marginTop: 4 }}>{shot.dialogue}</div><span className="pf-muted" style={{ fontSize: 12 }}>动作：{shot.action} · claim：{shot.claim_id || '无'}</span></div>)}<div className="cv-card-actions"><span className={`cv-status-tag ${scriptApproved ? 'is-approved' : 'is-pending'}`}>{scriptApproved ? '已批准' : '待批准'}</span><Button variant="lime" size="sm" disabled={scriptApproved || busy !== ''} onClick={approveScript}>批准脚本</Button></div></>}
      </div>}

      {project && scriptApproved && <div className="pf-card" style={{ padding: 16, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>④ 锚帧占位 / 声音占位</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10 }}><div className="cv-shot" style={{ padding: 12 }}><strong>Anchor Set</strong><p className="pf-muted" style={{ fontSize: 13 }}>3 张候选锚帧，等待人工确认。</p><span className={`cv-status-tag ${anchors?.status === 'approved' ? 'is-approved' : 'is-pending'}`}>{anchors?.status === 'approved' ? '已批准' : '候选占位'}</span></div><div className="cv-shot" style={{ padding: 12 }}><strong>Voice Render</strong><p className="pf-muted" style={{ fontSize: 13 }}>授权音色占位，时长 {voice ? (voice.duration_ms / 1000).toFixed(1) : '—'}s。</p><span className={`cv-status-tag ${voice?.status === 'approved' ? 'is-approved' : 'is-pending'}`}>{voice?.status === 'approved' ? '已批准' : '待批准'}</span></div></div><div className="cv-card-actions"><Button variant="lime" size="sm" disabled={busy !== '' || anchors?.status === 'approved'} onClick={approveAssets}>{busy === 'assets' ? '确认中…' : '批准锚帧与声音'}</Button></div>
      </div>}

      {project && <div className="pf-card" style={{ padding: 16, marginBottom: 24 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>⑤ 预览状态</h3><p className="pf-muted" style={{ fontSize: 13 }}>预览只允许使用已批准脚本、锚帧和声音。脚本未批准不能进入预览。</p><Button variant="lime" disabled={!scriptApproved || anchors?.status !== 'approved' || voice?.status !== 'approved' || busy !== ''} onClick={createPreview}>{busy === 'preview' ? '生成中…' : '生成 Mock 预览'}</Button>{project.preview_status !== 'idle' && <p style={{ fontSize: 13, marginBottom: 0 }}>{project.preview_status === 'ready' ? '预览已就绪，可交给审核人确认。' : '预览排队中，失败后可从最近成功阶段恢复。'}</p>}
      </div>}

      <p className="pf-muted" style={{ fontSize: 12 }}>需要查看现有作品或任务，可返回 <Link to="/commercial/tasks">任务与作品</Link>。</p>
    </CommercialLayout>
  )
}

export { CommercialReplicationPage }

