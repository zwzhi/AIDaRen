/** 商业短视频模板业务域 API 客户端（与后端 /api/commercial 一一对应）。 */
import { createJsonRequester, requestResponse } from '../../api/client'

const request = createJsonRequester()

export type CommercialAsset = {
  id: number; kind: string; source_role: string; mime: string
  size_bytes: number; duration_ms?: number | null; has_audio?: boolean | null
  storage: string
}

export type AnalysisOut = { analysis_run_id: number; status: string; mock: boolean; error?: string | null }
export type AnalysisResult = { id: number; status: string; error?: string | null; result: { shots: Shot[] } | null }
export type Shot = {
  shot_id: string; start_ms: number; end_ms: number
  observation?: string; inference?: string; uncertainty?: string; dialogue_template?: string; action_template?: string
  dialogue?: string; action?: string; target_duration_ms?: number
}
export type TemplateItem = {
  id: number; name: string; current_version: number
  versions: { id: number; version: number; status: string; published_at: string | null
    shot_count?: number; total_duration_ms?: number; variables?: string[] }[]
}
export type ActorItem = {
  id: number; name: string; current_version: number
  versions: { id: number; version: number; image_asset_ids: number[] }[]
  voices: { id: number; audio_asset_id: number; authorized_until: string | null; status: string }[]
}
export type ProductItem = {
  id: number; name: string; current_version: number; latest_version_id?: number | null
  form?: string; specs_text?: string; image_asset_ids?: number[]
  claims?: { claim_id: string; text: string; approved?: boolean }[]
  forbidden_phrases?: string[]; allowed_actions?: string[]
}
export type Unit = {
  unit_key: string; request_duration_ms: number
  covered_shot_keys: string[]; adopt_ranges: [string, number, number][]; notes?: string[]
}
export type AttemptOut = {
  id: number; status: string; attempt_no?: number; unit_key?: string | null; prediction_id: string | null
  output_asset_key: string | null; preview_url?: string | null; preview_mime?: string | null
  error_code: string | null; error_message: string | null
}
export type ProductionDetail = {
  id: number; status: string; dialogue_locked: boolean
  resolution_id: string; aspect_ratio: string
  plan: { shots: Shot[]; units: Unit[] | null; pending_review?: { shot_key: string; reason: string }[] } | null
  attempts: AttemptOut[]
  latest_export?: { id: number; kind: string } | null
  costs: { total_usd: string; pending_usd: string; settlement_note: string; mock: boolean }
}

/** 上传素材（multipart：file + source_role + 权利声明）。 */
export async function uploadAsset(file: File, sourceRole: string, rightsNote: string): Promise<CommercialAsset> {
  const body = new FormData()
  body.append('file', file)
  body.append('source_role', sourceRole)
  body.append('rights_declaration', rightsNote)
  // 复用统一传输层：自动附带 Bearer 令牌与错误解析
  const resp = await requestResponse('/api/commercial/sources', { method: 'POST', body })
  return (await resp.json()) as CommercialAsset
}

/** 当前生成能力档案（选项唯一来源；DRAFT 时不得声称已验证）。 */
export type Capabilities = {
  duration_min_ms: number; duration_max_ms: number; duration_step_ms: number
  resolutions: string[]; aspect_ratios: string[]
  audio_supported: boolean; voice_reference_supported: boolean
  capability_verified: boolean; capability_version: string
}

export const commercialApi = {
  getHealth: () => request<{ ok: boolean; ark_mock?: boolean }>('/api/health'),
  getCapabilities: () => request<Capabilities>('/api/commercial/capabilities'),
  analyze: (sourceId: number) =>
    request<AnalysisOut & { analysis_run_id: number }>(`/api/commercial/sources/${sourceId}/analyze`, { method: 'POST' }),
  getAnalysis: (runId: number) => request<AnalysisResult>(`/api/commercial/analyses/${runId}`),
  createTemplate: (name: string, analysisRunId: number, shots: Shot[]) =>
    request<{ template_id: number; version_id: number }>('/api/commercial/templates', {
      method: 'POST', body: JSON.stringify({ name, analysis_run_id: analysisRunId, shots }),
    }),
  publishTemplateVersion: (templateId: number, expectedVersion: number, shots: Shot[]) =>
    request<{ template_id: number; version_id: number; version: number }>(`/api/commercial/templates/${templateId}/versions`, {
      method: 'POST', body: JSON.stringify({ expected_version: expectedVersion, shots }),
    }),
  listTemplates: () => request<{ items: TemplateItem[] }>('/api/commercial/templates'),
  createActor: (name: string, imageAssetIds: number[], appearanceDesc: string) =>
    request<{ actor_id: number; actor_version_id: number }>('/api/commercial/actors', {
      method: 'POST', body: JSON.stringify({ name, image_asset_ids: imageAssetIds, appearance_desc: appearanceDesc }),
    }),
  bindVoice: (actorId: number, audioAssetId: number, authorizedUntil?: string) =>
    request<{ voice_profile_id: number }>(`/api/commercial/actors/${actorId}/voices`, {
      method: 'POST', body: JSON.stringify({ audio_asset_id: audioAssetId, authorized_until: authorizedUntil ?? null }),
    }),
  listActors: () => request<{ items: ActorItem[] }>('/api/commercial/actors'),
  createProduct: (payload: {
    name: string; form: string; image_asset_ids: number[]; claims: { claim_id: string; text: string; approved: boolean; source?: string }[]
    forbidden_phrases: string[]; allowed_actions: string[]; specs_text?: string
  }) => request<{ product_id: number; product_version_id: number }>('/api/commercial/products', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  listProducts: () => request<{ items: ProductItem[] }>('/api/commercial/products'),
  createProduction: (payload: Record<string, unknown>) =>
    request<{ production_id: number }>('/api/commercial/productions', { method: 'POST', body: JSON.stringify(payload) }),
  adapt: (productionId: number, marketingGoal: string) =>
    request<{ shots: Shot[]; pending_review: unknown[]; mock: boolean }>(`/api/commercial/productions/${productionId}/adapt`, {
      method: 'POST', body: JSON.stringify({ marketing_goal: marketingGoal }),
    }),
  plan: (productionId: number) =>
    request<{ units: Unit[]; capabilities: { duration_min_ms: number; duration_max_ms: number; capability_verified: boolean } }>(
      `/api/commercial/productions/${productionId}/plan`, { method: 'POST' }),
  quote: (productionId: number, unitKey: string, dialogueOverride = '') =>
    request<{ quote_id: number; amount: string; currency: string; price_source: string; expires_at: string | null; mock: boolean }>(
      `/api/commercial/productions/${productionId}/quote`, {
        method: 'POST',
        body: JSON.stringify({ unit_key: unitKey, dialogue_override: dialogueOverride }),
      }),
  generate: (productionId: number, unitKey: string, quoteId: number, clientRequestId: string, dialogueOverride = '') =>
    request<{ attempt_id: number; attempt_status: string; prediction_id: string | null; idempotent_replay: boolean; task_replayed?: boolean; mock: boolean }>(
      `/api/commercial/productions/${productionId}/generate`, {
        method: 'POST',
        body: JSON.stringify({ unit_key: unitKey, quote_id: quoteId, client_request_id: clientRequestId, drive: true, dialogue_override: dialogueOverride }),
      }),
  getProduction: (productionId: number) => request<ProductionDetail>(`/api/commercial/productions/${productionId}`),
  review: (attemptId: number, dimensions: Record<string, string | string[]>, speechRequired = true) =>
    request<{ overall: string }>(`/api/commercial/attempts/${attemptId}/review`, {
      method: 'POST', body: JSON.stringify({ dimensions, speech_required: speechRequired }),
    }),
  compose: (productionId: number, selections: { attempt_id: number; ranges: number[][] }[],
            complete = true, subtitles = true) =>
    request<{ export_id: number; total_adopt_ms: number; subtitles: boolean; kind: string }>(
      `/api/commercial/productions/${productionId}/compose`, {
        method: 'POST', body: JSON.stringify({ selections, subtitles, complete }),
      }),
  getExport: (exportId: number) =>
    request<{ id: number; kind: string; srt_content: string | null; srt_aligned: boolean; subtitled_path: string | null; total_adopt_ms: number }>(
      `/api/commercial/exports/${exportId}`),
  burnExport: (exportId: number, srtContent: string) =>
    request<{ export_id: number; subtitled_path: string }>(`/api/commercial/exports/${exportId}/burn`, {
      method: 'POST', body: JSON.stringify({ srt_content: srtContent }) }),
  getProviderSettings: () =>
    request<{ atlas_api_key: string; has_atlas_api_key: boolean; gemini_analysis_model_id: string; h3_developer_reference_model_id: string; commercial_verified_models: string; commercial_mock_mode: boolean; commercial_paid_execution_enabled: boolean }>('/api/admin/settings/models'),
  saveProviderSettings: (payload: Record<string, unknown>) =>
    request('/api/admin/settings/models', { method: 'PATCH', body: JSON.stringify(payload) }),
  setBudget: (totalUsd: string, scope: string = 'mock') =>
    request<{ pool_id: number; total_usd: string; scope: string; paused: boolean }>('/api/commercial/budget', {
      method: 'POST', body: JSON.stringify({ total_usd: totalUsd, scope }),
    }),
}
