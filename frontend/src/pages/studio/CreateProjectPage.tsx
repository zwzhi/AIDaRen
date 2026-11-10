import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { COMMERCIAL_PROJECT, COMMERCIAL_HOME } from '../../lib/projectScope'
import { ArrowLeft, ArrowRight, Check, Clapperboard, Clock3, LoaderCircle, Save, Sparkles } from 'lucide-react'
import { api, type PipelineMode, type Project, type Template, type VoicePreset } from '../../api'
import AppShell from '../../components/layout/AppShell'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import Button from '../../components/ui/Button'
import Stepper from '../../components/ui/Stepper'
import { MediaCostNotice } from '../../components/billing/MediaCostNotice'
import { useMediaModelsCatalog } from '../../hooks/useMediaModelsCatalog'
import { creationTemplateId } from '../../lib/creationTemplates'
import { resolveShortVideoMediaSettings, shortVideoPipelineMode } from '../../lib/shortVideoSettings'
import { isRunning, kepuSteps } from '../../lib/status'
import { dialog } from '../../lib/dialog'
import './shortVideoCreate.css'

const EXAMPLES = ['给小学生讲讲为什么天空是蓝色的', '一只胆小的小猫在雨天遇见新朋友', '用轻松的方式介绍二十四节气里的霜降']

export default function CreateProjectPage() {
  const [params] = useSearchParams()
  // 商业项目：无参数的旧"新建"页不再进入旧制作流程，引导到商业模板入口；
  // 携带旧作品/模板参数的地址保持原行为（历史数据与正在进行的编辑不受影响）。
  // 早返回必须位于所有条件 Hooks 之前（rules-of-hooks）：本组件只保留
  // useSearchParams（无条件调用），其余 Hooks 全部移入 CreateProjectForm。
  if (COMMERCIAL_PROJECT && params.size === 0) {
    return <OldEntryGuide />
  }
  return <CreateProjectForm params={params} />
}

function CreateProjectForm({ params }: { params: URLSearchParams }) {
  const nav = useNavigate()
  const editId = Number(params.get('project')) || null
  const requestedTemplate = creationTemplateId(params.get('template'))
  const requestedPipelineMode = shortVideoPipelineMode(params.get('mode'))
  const returnPath = `/studio/new${params.size ? `?${params}` : ''}`
  const [templates, setTemplates] = useState<Template[]>([])
  const [voices, setVoices] = useState<VoicePreset[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [templateId, setTemplateId] = useState(requestedTemplate)
  const [ratio, setRatio] = useState('9:16')
  const [pipelineMode, setPipelineMode] = useState<PipelineMode>(requestedPipelineMode)
  const [imageModel, setImageModel] = useState('')
  const [videoModel, setVideoModel] = useState('')
  const [imageResolution, setImageResolution] = useState('')
  const [videoResolution, setVideoResolution] = useState('')
  const mediaCatalog = useMediaModelsCatalog()
  const [duration, setDuration] = useState(60)
  const [voice, setVoice] = useState('')
  const [mode, setMode] = useState<'idea' | 'copy'>('idea')
  const [idea, setIdea] = useState('')
  const [copy, setCopy] = useState('')
  const [title, setTitle] = useState('')
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(Boolean(editId))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [voiceError, setVoiceError] = useState(false)
  const working = useRef(false)
  const savedProject = useRef<Project | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  useEffect(() => {
    let disposed = false
    if (!localStorage.getItem('token')) {
      nav(`/auth?next=${encodeURIComponent(returnPath)}`, { replace: true })
      return
    }
    api.templates().then(rows => { if (!disposed) setTemplates(rows) }).catch(cause => { if (!disposed) setError(cause.message || '模板加载失败') })
    api.voices().then(rows => { if (!disposed) setVoices(rows) }).catch(() => { if (!disposed) setVoiceError(true) })
    return () => { disposed = true }
  }, [nav, editId, returnPath])
  useEffect(() => {
    let disposed = false
    if (!editId) {
      savedProject.current = null
      setProject(null)
      setLoading(false)
      setTemplateId(requestedTemplate)
      setRatio('9:16')
      setPipelineMode(requestedPipelineMode)
      setImageModel('')
      setVideoModel('')
      setImageResolution('')
      setVideoResolution('')
      setDuration(60)
      setVoice('')
      setMode('idea')
      setIdea('')
      setCopy('')
      setTitle('')
      setStep(0)
      return
    }
    // 新建后更新 URL 时，保留当前输入与文案。
    if (savedProject.current?.id === editId) return
    setLoading(true)
    api.getProject(editId).then(value => {
      if (disposed) return
      if (value.creation_session_id) {
        nav(`/studio/sessions/${value.creation_session_id}?project=${value.id}`, { replace: true })
        return
      }
      savedProject.current = value
      setProject(value)
      setTemplateId(creationTemplateId(value.template_id))
      setRatio(value.output_ratio || '9:16')
      setPipelineMode(shortVideoPipelineMode(value.pipeline_mode))
      setImageModel(value.image_model || '')
      setVideoModel(value.video_model || '')
      setImageResolution(value.image_resolution || '')
      setVideoResolution(value.video_resolution || '')
      setDuration(value.target_duration_sec || 60)
      setVoice(value.voice_id || '')
      setTitle(value.title)
      setIdea(value.source_text)
      if (value.source_type === 'script') {
        setCopy(value.source_text)
        setMode('copy')
        setStep(1)
      } else setStep(0)
    }).catch(cause => { if (!disposed) setError(cause.message || '项目加载失败') })
      .finally(() => { if (!disposed) setLoading(false) })
    return () => { disposed = true }
  }, [editId, requestedTemplate, requestedPipelineMode, nav])

  const selectedTemplate = templates.find(item => item.id === templateId)
  const mediaSettings = resolveShortVideoMediaSettings(mediaCatalog, pipelineMode, { imageModel, videoModel, imageResolution, videoResolution, ratio }, project?.ref_image_url ? 3 : 2)
  const running = Boolean(project && (isRunning(project.status) || project.active_tasks?.some(task => ['pending', 'leased', 'running', 'awaiting_poll', 'awaiting_review', 'cancel_requested'].includes(task.status))))
  const disabled = Boolean(busy || loading || running)
  function payload(text: string, name: string) {
    return {
      template_id: templateId, title: name.trim().slice(0, 200) || text.trim().slice(0, 30),
      source_type: 'script' as const, source_text: text.trim(),
      pipeline_mode: pipelineMode, resolution_mode: 'hd' as const,
      output_ratio: mediaSettings.ratio || ratio, target_duration_sec: duration, voice_id: voice,
      image_model: mediaSettings.imageModel, video_model: mediaSettings.videoModel,
      image_resolution: mediaSettings.imageResolution, video_resolution: mediaSettings.videoResolution,
    }
  }
  const draftFields = payload(copy, title)
  const draftChanged = Boolean(project && (
    project.title !== draftFields.title || project.source_text !== draftFields.source_text ||
    project.template_id !== templateId || project.output_ratio !== draftFields.output_ratio ||
    shortVideoPipelineMode(project.pipeline_mode) !== pipelineMode ||
    (project.target_duration_sec || 60) !== duration || (project.voice_id || '') !== voice ||
    (project.image_model || '') !== draftFields.image_model || (project.video_model || '') !== draftFields.video_model ||
    (project.image_resolution || '') !== draftFields.image_resolution || (project.video_resolution || '') !== draftFields.video_resolution
  ))
  const canSaveDraft = !project?.shots.length && !project?.final_video_url
  async function createDraft(text: string, name: string) {
    if (savedProject.current) return savedProject.current
    const value = await api.createProject(payload(text, name))
    savedProject.current = value
    if (mounted.current) {
      setProject(value)
      nav(`/studio/new?project=${value.id}`, { replace: true })
    }
    return value
  }
  async function saveDraft(text: string, name: string) {
    const old = savedProject.current
    if (!old) return createDraft(text, name)
    // Existing generated assets are changed only after the explicit restart confirmation.
    if (old.shots.length || old.final_video_url) return old
    const value = await api.updateProject(old.id, payload(text, name))
    savedProject.current = value
    if (mounted.current) setProject(value)
    return value
  }
  async function saveCopyDraft() {
    if (!copy.trim() || disabled || working.current || !selectedTemplate || !canSaveDraft) return
    working.current = true
    setBusy('正在保存草稿…')
    setError('')
    try {
      await saveDraft(copy, title)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : '草稿保存失败，请重试')
    } finally {
      working.current = false
      if (mounted.current) setBusy('')
    }
  }
  async function prepareCopy(event: FormEvent) {
    event.preventDefault()
    if (!idea.trim() || disabled || working.current || !selectedTemplate) return
    working.current = true
    setError('')
    setBusy(mode === 'idea' ? '正在生成文案…' : '正在保存文案…')
    try {
      const result = mode === 'copy'
        ? { title: title || idea.trim().slice(0, 30), content: idea.trim() }
        : await api.expandContent(`${idea.trim()}\n\n创作要求：约 ${duration} 秒，${selectedTemplate.name} 风格，普通话旁白。请写可直接配音的完整文案，保持内容与时长匹配。`, 'script')
      if (!mounted.current) return
      setCopy(result.content)
      setTitle(result.title)
      setStep(1)
      await saveDraft(result.content, result.title)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : '文案生成失败，请重试')
    } finally {
      working.current = false
      if (mounted.current) setBusy('')
    }
  }
  async function generateStoryboard() {
    if (!copy.trim() || disabled || working.current || !selectedTemplate) return
    if (!mediaSettings.ready) {
      setError('当前模型不可用或参考图数量不足，请重新选择图片和视频模型、清晰度与画面比例。')
      return
    }
    working.current = true
    try {
      const old = savedProject.current
      if (old?.shots.length) {
        const confirmed = await dialog.confirm({ title: '重新生成分镜', message: '新的文案与设置将重新生成分镜，并替换本项目已有的图片、镜头视频、配音和成片。', confirmText: '重新生成', tone: 'danger' })
        if (!confirmed || !mounted.current) return
      }
      setBusy('正在保存并生成分镜…')
      setError('')
      let value = await createDraft(copy, title)
      value = await api.updateProject(value.id, payload(copy, title))
      savedProject.current = value
      setProject(value)
      await api.generate(value.id, { restart: Boolean(value.shots.length) })
      if (mounted.current) nav(`/studio/${value.id}`)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : '分镜生成失败，请重试')
    } finally {
      working.current = false
      if (mounted.current) setBusy('')
    }
  }

  return <AppShell active="studio">
    <div className="sv-create-page">
      <header className="sv-create-header">
        <div><Link className="sv-back" to="/history"><ArrowLeft size={16} /> 我的短片</Link><h1>{editId ? '编辑短片' : '创建短片'}</h1><p>从一个想法开始，每一步都可以查看和调整。</p></div>
        <Stepper steps={kepuSteps(pipelineMode)} current={pipelineMode === 'full' && step === 1 ? 2 : step} />
      </header>
      {error && <BillingErrorNotice message={error} />}
      {loading ? <div className="sv-loading"><LoaderCircle className="sv-spin" size={20} /> 正在加载项目…</div> : <>
        {running && <div className="sv-running-note">项目正在制作中，请在工作台查看进度或停止任务。<Link to={`/studio/${project!.id}`}>查看工作台 <ArrowRight size={15} /></Link></div>}
        <div className="sv-create-grid">
          <main>
            {step === 0 ? <form onSubmit={prepareCopy}>
              <section className="sv-panel">
                <div className="sv-section-heading"><span>01</span><div><h2>选择画面风格</h2><p>四种动画与插画风格，生图时使用画风参考图，逐镜延续角色与视觉风格。</p></div></div>
                <div className="sv-style-grid" role="group" aria-label="画面风格">
                  {templates.map(item => <button key={item.id} type="button" className={`sv-style-card${item.id === templateId ? ' is-selected' : ''}`} disabled={disabled} aria-pressed={item.id === templateId} onClick={() => setTemplateId(item.id)}>
                    <img src={api.assetUrl(item.preview_cover)} alt="" /><div><strong>{item.name}</strong><p>{item.description}</p></div>
                    {item.id === templateId && <span className="sv-style-check"><Check size={14} /></span>}
                  </button>)}
                </div>
              </section>
              <section className="sv-panel">
                <div className="sv-section-heading"><span>02</span><div><h2>写下你想表达的内容</h2><p>描述主题、受众和重点，或直接粘贴已有文案。</p></div></div>
                <div className="sv-input-tabs"><button type="button" className={mode === 'idea' ? 'is-active' : ''} onClick={() => setMode('idea')} disabled={disabled}>输入想法</button><button type="button" className={mode === 'copy' ? 'is-active' : ''} onClick={() => setMode('copy')} disabled={disabled}>已有文案</button></div>
                <label className="sv-field"><span>{mode === 'idea' ? '短片想法' : '完整文案'}</span><textarea aria-label={mode === 'idea' ? '短片想法' : '完整文案'} value={idea} onChange={event => setIdea(event.target.value)} rows={6} maxLength={20000} disabled={disabled} placeholder={mode === 'idea' ? '例如：用 3D 动画给小学生解释天空为什么是蓝色，语言轻松，约 60 秒。' : '粘贴可以直接配音的文案，下一步可以继续编辑。'} required /></label>
                {mode === 'idea' && <div className="sv-examples">{EXAMPLES.map(example => <button type="button" key={example} onClick={() => setIdea(example)} disabled={disabled}>{example}</button>)}</div>}
                <div className="sv-actions"><span>文案生成后可修改，再继续生成分镜。</span><div className="sv-action-buttons">{copy.trim() && <Button variant="outline" disabled={disabled} onClick={() => setStep(1)}>编辑已有文案</Button>}<Button type="submit" variant="lime" disabled={disabled || !idea.trim() || !selectedTemplate}>{busy ? <LoaderCircle size={16} className="sv-spin" /> : <Sparkles size={16} />}{busy || (mode === 'idea' ? '生成文案' : '下一步：检查文案')}<ArrowRight size={16} /></Button></div></div>
              </section>
            </form> : <section className="sv-panel">
              <div className="sv-section-heading"><span>02</span><div><h2>检查文案，再生成分镜</h2><p>这份文案将作为旁白。确认内容后，再拆分画面与镜头。</p></div></div>
              <label className="sv-field"><span>短片名称</span><input value={title} onChange={event => setTitle(event.target.value)} maxLength={200} disabled={disabled} /></label>
              <label className="sv-field"><span>配音文案 <small>{copy.length} 字</small></span><textarea aria-label="配音文案" value={copy} onChange={event => setCopy(event.target.value)} rows={13} maxLength={20000} disabled={disabled} /></label>
              <div className="sv-actions"><Button variant="outline" disabled={disabled} onClick={() => setStep(0)}><ArrowLeft size={15} /> 返回调整</Button><div className="sv-action-buttons">{canSaveDraft && <Button variant="outline" disabled={disabled || !copy.trim() || !selectedTemplate || Boolean(project && !draftChanged)} onClick={() => { void saveCopyDraft() }}><Save size={15} />保存草稿</Button>}<Button variant="lime" disabled={disabled || !copy.trim() || !selectedTemplate} onClick={() => { void generateStoryboard() }}>{busy ? <LoaderCircle size={16} className="sv-spin" /> : <Clapperboard size={16} />}{busy || '生成分镜脚本'}<ArrowRight size={16} /></Button></div></div>
              {project && <p className="sv-saved-note">{draftChanged ? canSaveDraft ? '有未保存的修改，可先保存草稿，或生成分镜时一并保存。' : '修改将在重新生成分镜时保存。' : canSaveDraft ? '草稿已保存。' : '已载入项目文案。'}<Link to={`/studio/${project.id}`}>打开项目工作台</Link></p>}
            </section>}
          </main>
          <aside className="sv-panel sv-settings">
            <h2>短片设置</h2><p>先用默认设置，也可以按需要调整。</p>
            <div className="sv-field"><span>成片方式</span><div className="sv-output-modes" role="group" aria-label="成片方式">{([{ id: 'full', label: 'AI 视频', desc: '参考图生图 → 图生视频 → 合成' }, { id: 'image_text', label: '静图成片', desc: '参考图生图 → 图片运镜与配音' }] as const).map(item => <button key={item.id} type="button" className={pipelineMode === item.id ? 'is-selected' : ''} aria-pressed={pipelineMode === item.id} disabled={disabled} onClick={() => setPipelineMode(item.id)}><strong>{item.label}</strong><span>{item.desc}</span>{pipelineMode === item.id && <Check size={14} />}</button>)}</div></div>
            <label className="sv-field"><span>画面比例</span><select value={mediaSettings.ratio} onChange={event => setRatio(event.target.value)} disabled={disabled || !mediaSettings.ratios.length}>{!mediaSettings.ratios.length && <option value="">暂无共同支持的画幅</option>}{mediaSettings.ratios.map(value => <option key={value} value={value}>{value}{value === '9:16' ? ' 竖屏' : value === '16:9' ? ' 横屏' : value === '1:1' ? ' 方形' : ''}</option>)}</select></label>
            <label className="sv-field"><span>目标时长</span><select value={duration} onChange={event => setDuration(Number(event.target.value))} disabled={disabled}>{[...new Set([30, 60, 90, 120, 180, duration])].sort((a, b) => a - b).map(value => <option key={value} value={value}>约 {value} 秒</option>)}</select></label>
            {pipelineMode === 'image_text' ? <>
              <label className="sv-field"><span>旁白音色</span><select value={voice} onChange={event => setVoice(event.target.value)} disabled={disabled}><option value="">默认普通话音色</option>{voice && !voices.some(item => (item.speaker || item.id) === voice) && <option value={voice}>项目原有音色</option>}{voices.map(item => <option key={item.id} value={item.speaker || item.id}>{item.label}</option>)}</select></label>
              {voiceError && <p className="sv-saved-note">音色列表暂未加载，仍可使用默认配音。</p>}
            </> : <p className="sv-saved-note">视频模型生成旁白与声音。</p>}
            <details className="sv-model-settings" open={pipelineMode === 'full'}><summary>生成模型与清晰度</summary>
              <label className="sv-field"><span>参考图生图模型</span><select value={mediaSettings.imageModel} disabled={disabled || !mediaSettings.imageOptions.length} onChange={event => setImageModel(event.target.value)}>{mediaSettings.imageSelectionUnavailable && <option value={mediaSettings.imageModel} disabled>{mediaSettings.imageModel}（当前不可用）</option>}{!mediaSettings.imageOptions.length && !mediaSettings.imageSelectionUnavailable && <option value="">{mediaCatalog ? '暂无可用参考图模型' : '正在加载模型…'}</option>}{mediaSettings.imageOptions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
              <label className="sv-field"><span>图片清晰度</span><select value={mediaSettings.imageResolution} disabled={disabled || !mediaSettings.imageResolutions.length} onChange={event => setImageResolution(event.target.value)}>{!mediaSettings.imageResolutions.length && <option value={mediaSettings.imageResolution}>{mediaSettings.imageResolution || '请选择可用模型'}</option>}{mediaSettings.imageResolutions.map(value => <option key={value} value={value}>{value}</option>)}</select><MediaCostNotice modelId={mediaSettings.imageModel} resolution={mediaSettings.imageResolution} /></label>
              {pipelineMode === 'full' && <><label className="sv-field"><span>图生视频模型</span><select value={mediaSettings.videoModel} disabled={disabled || !mediaSettings.videoOptions.length} onChange={event => setVideoModel(event.target.value)}>{mediaSettings.videoSelectionUnavailable && <option value={mediaSettings.videoModel} disabled>{mediaSettings.videoModel}（当前不可用）</option>}{!mediaSettings.videoOptions.length && !mediaSettings.videoSelectionUnavailable && <option value="">{mediaCatalog ? '暂无可用图生视频模型' : '正在加载模型…'}</option>}{mediaSettings.videoOptions.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
                <label className="sv-field"><span>视频清晰度</span><select value={mediaSettings.videoResolution} disabled={disabled || !mediaSettings.videoResolutions.length} onChange={event => setVideoResolution(event.target.value)}>{!mediaSettings.videoResolutions.length && <option value={mediaSettings.videoResolution}>{mediaSettings.videoResolution || '请选择可用模型'}</option>}{mediaSettings.videoResolutions.map(value => <option key={value} value={value}>{value}</option>)}</select><MediaCostNotice modelId={mediaSettings.videoModel} resolution={mediaSettings.videoResolution} seconds={1} /></label></>}
              {mediaCatalog && !mediaSettings.ready && <p className="sv-model-error" role="status">请重新选择可用模型，生图需支持 {project?.ref_image_url ? 3 : 2} 张参考图{pipelineMode === 'full' ? '，视频需支持 2 张参考图' : ''}，并确认清晰度和画幅。</p>}
            </details>
            <div className="sv-setting-summary"><Clapperboard size={17} /><div><strong>{selectedTemplate?.name || '3D 动画'}</strong><span>{pipelineMode === 'full' ? '图生视频' : '图片运镜'} · 普通话旁白 · 中文字幕</span><span>使用画风参考图，并参考前镜画面保持一致。</span></div></div>
            <div className="sv-workflow-hint"><Clock3 size={17} /><p>{pipelineMode === 'full' ? '确认分镜后先生成参考图画面，再将图片逐镜生成为视频，检查镜头后合成成片。' : '检查分镜后生成图片和配音，素材准备好后再合成视频。'}</p></div>
          </aside>
        </div>
      </>}
    </div>
  </AppShell>
}


/** 商业项目下旧"新建"页的引导：说明去向并一键进入商业模板库。 */
function OldEntryGuide() {
  return (
    <div className="pf-container" style={{ maxWidth: 640, margin: '80px auto', textAlign: 'center' }}>
      <h2>短视频制作已升级为「商业模板工作台」</h2>
      <p style={{ color: '#666' }}>
        参考视频解析一次、模板长期复用：上传参考片 → 校准模板 → 填入我方达人、音色、商品与新文案 → 分镜生成 → 审核 → 合成导出。
      </p>
      <p>
        <Link to={COMMERCIAL_HOME} className="pf-btn pf-btn-primary">进入商业模板库</Link>
      </p>
      <p style={{ fontSize: 12, color: '#999' }}>历史作品请从「任务与作品」或原历史列表进入；本页保留旧作品编辑能力。</p>
    </div>
  )
}
