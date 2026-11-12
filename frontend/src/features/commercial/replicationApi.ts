import { createJsonRequester } from '../../api/client'

const request = createJsonRequester()

export type ReplicationMode = 'structural_rewrite' | 'high_fidelity'
export type ReplicationStatus = 'draft' | 'analyzing' | 'analyzed' | 'script_review' | 'anchor_review' | 'voice_ready' | 'preview_ready' | 'completed'

export type ReplicationProject = {
  id: number
  production_id: number
  mode: ReplicationMode
  recommended_mode: ReplicationMode
  route_reason: string
  risks: string[]
  estimated_minutes: number
  estimated_cost: string
  status: ReplicationStatus
  rights_status: 'verified' | 'pending' | 'blocked'
  product_match_status: 'matched' | 'pending' | 'mismatch'
  script_approved: boolean
  anchors_approved: boolean
  voice_approved: boolean
  preview_status: 'idle' | 'queued' | 'ready' | 'failed'
  reference_video_name?: string
  target_product_name?: string
}

export type ShotGraphShot = {
  shot_key: string
  start_ms: number
  end_ms: number
  purpose: string
  product_presence: 'required' | 'optional' | 'absent' | 'unknown'
  product_confidence: number
  product_evidence: string
  action: string
}

export type ShotGraph = { id: number; replication_id: number; shots: ShotGraphShot[]; confirmed: boolean }

export type ScriptVersion = {
  id: number
  version: number
  status: 'draft' | 'approved' | 'rejected'
  shots: { shot_key: string; dialogue: string; action: string; claim_id?: string | null }[]
}

export type AnchorSet = { id: number; status: 'candidate' | 'approved'; frame_count: number }
export type VoiceRender = { id: number; status: 'ready' | 'approved'; duration_ms: number }
export type PreviewResult = { id: number; status: 'queued' | 'ready' | 'failed'; preview_url?: string | null; recovery_stage?: string | null }

function normalizeShotGraph(raw: any): ShotGraph {
  return {
    id: Number(raw.id || 0),
    replication_id: Number(raw.replication_id || raw.replication_project_id || 0),
    confirmed: Boolean(raw.confirmed),
    shots: (raw.shots || []).map((shot: any) => ({
      ...shot,
      start_ms: Number(shot.start_ms ?? shot.start ?? 0),
      end_ms: Number(shot.end_ms ?? shot.end ?? 0),
    })),
  }
}

function normalizeScript(raw: any): ScriptVersion {
  return {
    id: Number(raw.id || 0),
    version: Number(raw.version || 0),
    status: raw.status || 'draft',
    shots: (raw.shots || raw.scripts || []).map((shot: any) => ({
      shot_key: String(shot.shot_key || ''),
      dialogue: String(shot.dialogue || ''),
      action: String(shot.action || shot.action_prompt || ''),
      claim_id: shot.claim_id || shot.claim_ids?.[0] || null,
    })),
  }
}

type CreatePayload = {
  production_id: number
  mode: ReplicationMode
  reference_video_name: string
  target_product_name: string
  actor_name: string
  voice_profile_id?: number | null
  marketing_goal: string
}

const mockProject = (payload: CreatePayload): ReplicationProject => ({
  id: 1,
  production_id: payload.production_id,
  mode: payload.mode,
  recommended_mode: 'structural_rewrite',
  route_reason: '默认保留 Hook、痛点、证明和 CTA 节奏，并重写商品表达。',
  risks: ['参考视频权利与商品匹配仍需人工确认'],
  estimated_minutes: payload.mode === 'high_fidelity' ? 18 : 12,
  estimated_cost: payload.mode === 'high_fidelity' ? '¥18.00' : '¥12.00',
  status: 'draft',
  rights_status: 'pending',
  product_match_status: 'pending',
  script_approved: false,
  anchors_approved: false,
  voice_approved: false,
  preview_status: 'idle',
  reference_video_name: payload.reference_video_name,
  target_product_name: payload.target_product_name,
})

export const replicationApi = {
  create: (payload: CreatePayload) => request<ReplicationProject>('/api/commercial/replications', { method: 'POST', body: JSON.stringify(payload) }),
  get: (id: number) => request<ReplicationProject>(`/api/commercial/replications/${id}`),
  analyze: (id: number) => request<any>(`/api/commercial/replications/${id}/analyze`, { method: 'POST' }).then(normalizeShotGraph),
  getShotGraph: (id: number) => request<any>(`/api/commercial/replications/${id}/shot-graph`).then(normalizeShotGraph),
  assignWardrobe: (id: number, shotKey: string, wardrobeVersionId: number | null) => request<any>(`/api/commercial/replications/${id}/shot-graph/${encodeURIComponent(shotKey)}/wardrobe`, { method: 'PATCH', body: JSON.stringify({ wardrobe_version_id: wardrobeVersionId }) }),
  confirmShotGraph: (id: number) => request<any>(`/api/commercial/replications/${id}/shot-graph/confirm`, { method: 'POST' }).then(normalizeShotGraph),
  createScript: (id: number) => request<any>(`/api/commercial/replications/${id}/scripts`, { method: 'POST', body: JSON.stringify({}) }).then(normalizeScript),
  listScripts: (id: number) => request<any>(`/api/commercial/replications/${id}/scripts`).then(raw => ({ items: (raw.items || raw.scripts || []).map(normalizeScript) })),
  approveScript: (versionId: number) => request<any>(`/api/commercial/scripts/${versionId}/approve`).then(normalizeScript),
  approveAnchors: (anchorSetId: number) => request<AnchorSet>(`/api/commercial/anchor-sets/${anchorSetId}/approve`, { method: 'POST' }),
  approveVoice: (voiceRenderId: number) => request<VoiceRender>(`/api/commercial/voice-renders/${voiceRenderId}/approve`, { method: 'POST' }),
  createPreview: (id: number) => request<PreviewResult>(`/api/commercial/replications/${id}/preview`, { method: 'POST' }),
}

/** Fixture used by local storybook-like flows when the backend is not available. */
export function createReplicationFixture(payload: CreatePayload): {
  project: ReplicationProject; shotGraph: ShotGraph; script: ScriptVersion; anchorSet: AnchorSet; voice: VoiceRender
} {
  const project = mockProject(payload)
  const shotGraph: ShotGraph = {
    id: 1, replication_id: project.id, confirmed: false,
    shots: [
      { shot_key: 'shot-01', start_ms: 0, end_ms: 3200, purpose: 'Hook', product_presence: 'absent', product_confidence: 0.96, product_evidence: '开场口播与动作', action: '达人直视镜头提出痛点' },
      { shot_key: 'shot-02', start_ms: 3200, end_ms: 7600, purpose: 'Proof', product_presence: 'required', product_confidence: 0.88, product_evidence: '包装与手持动作', action: '展示目标商品并演示使用' },
      { shot_key: 'shot-03', start_ms: 7600, end_ms: 12000, purpose: 'CTA', product_presence: 'required', product_confidence: 0.9, product_evidence: '结尾商品特写', action: '总结卖点并给出行动号召' },
    ],
  }
  const script: ScriptVersion = { id: 1, version: 1, status: 'draft', shots: shotGraph.shots.map(shot => ({ shot_key: shot.shot_key, dialogue: `${shot.purpose}：围绕${payload.target_product_name}重新表达。`, action: shot.action, claim_id: shot.product_presence === 'required' ? 'claim-demo-01' : null })) }
  return { project, shotGraph, script, anchorSet: { id: 1, status: 'candidate', frame_count: 3 }, voice: { id: 1, status: 'ready', duration_ms: 12000 } }
}

