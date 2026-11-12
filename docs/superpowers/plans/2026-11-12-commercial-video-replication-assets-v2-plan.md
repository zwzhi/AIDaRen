# 商业视频复刻资产与自动化编排 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将商品持久研究/状态、共享服饰、达人参考集、授权声音样本和自动化编排正式接入商业视频复刻链路，并保持历史版本和真实 API 门禁。

**Architecture:** 在现有 `CvProduct`、`CvActor`、`CvVoiceProfile`、`CvReplicationProject` 和 `CvRenderBatch` 之上增加不可变版本化资产对象。研究服务只生成候选，人工确认后发布版本；镜头编译器按镜头语义选择状态、服饰和达人参考；Workflow DAG 编排并行阶段和人工门，H3 仍只消费冻结后的锚帧、脚本和声音。

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL additive schema patches, React/TypeScript/Vite, pytest, Node test runner, existing Atlas adapters and task runtime.

**Spec:** `docs/superpowers/specs/2026-11-12-commercial-video-replication-assets-v2-design.md`

## Global Constraints

- 商品创建默认入口是图片 + 名称 + 自然语言描述；研究异步补全，不阻塞草稿保存。
- 已确认商品事实、卖点和状态不得被刷新覆盖；冲突必须生成候选并进入人工确认。
- 商品状态首期覆盖包装态、打开/取用态、使用/细节态、质地/试色态、效果态。
- 服饰素材可个人、团队或项目共享；达人穿搭效果按 `actor_version + wardrobe_version` 缓存。
- 每个镜头只向 Image2.6 传 Top 1～3 张达人参考图和已匹配的商品/服饰状态素材。
- H3 单段请求时长不超过 15 秒；最终时间轴支持 4～15 秒可变片段、重叠、转场和裁剪。
- 真实供应商角色必须分别通过 capability gate；未通过时只能使用 Mock/Fixture/Sandbox。
- 原始声音样本与新生成的主声音轨必须分开保存；主声音轨是最终音频权威。

## Review Focus

- 同一商品第二次使用只读取已发布研究版本，不重复联网研究；测试归入 Task 2。
- 变体缺少 SKU/色号/规格时使用 single_variant/user_defined，歧义时阻断生成；测试归入 Task 2。
- 刷新不能覆盖已确认字段，冲突必须可回滚；测试归入 Task 2。
- 同一服饰跨达人共享但穿搭效果必须按达人隔离；测试归入 Task 3。
- 片段并发失败只重试失败 segment，边界异常只做局部修复；测试归入 Task 6。

---

### Task 1: Persisted asset schema and version links

**Files:**
- Modify: `backend/app/models_commercial.py`
- Modify: `backend/app/commercial_schema.py`
- Modify: `backend/app/main.py` (startup additive patch registration if required)
- Create: `backend/tests/commercial/test_asset_v2_schema.py`

**Interfaces:**
- Produces SQLAlchemy models and additive tables for product research/source/facts/variants/states/capabilities, wardrobe items/versions/sets/looks, actor reference sets/frames, voice sources, workflow runs/stages.
- Adds shot/anchor/render lineage fields without changing existing production IDs.

- [ ] **Step 1: Write failing schema tests** asserting table creation, foreign keys, statuses, uniqueness, source hash, scope, and immutable version references.
- [ ] **Step 2: Run `pytest tests/commercial/test_asset_v2_schema.py -q` and verify failures.**
- [ ] **Step 3: Add SQLAlchemy models and additive DDL** with nullable compatibility fields for existing rows; use JSON only for extensible metadata and normalized columns for identity/status/scope.
- [ ] **Step 4: Add indexes and constraints** for `(product_id, variant_key)`, `(research_run_id, content_hash)`, `(actor_version_id, sequence)`, `(scope, status)`, workflow idempotency keys, and render lineage.
- [ ] **Step 5: Run the schema tests and a compile check.**
- [ ] **Step 6: Commit** `feat: add v2 commercial asset schema`.

### Task 2: Product research, variant resolution, state persistence, and merge

**Files:**
- Create: `backend/app/services/commercial/product_research.py`
- Create: `backend/app/services/commercial/product_states.py`
- Modify: `backend/app/api/commercial/productions.py` or create `backend/app/api/commercial/products_v2.py`
- Modify: `backend/app/services/commercial/rights.py`
- Create: `backend/tests/commercial/test_product_research_v2.py`

**Interfaces:**
- `start_product_research(db, product_id, *, image_asset_ids, name, description, source_urls=()) -> CvProductResearchRun`
- `merge_product_candidates(db, run_id, decisions, *, user_id) -> CvProductVersion`
- `list_product_states(db, product_version_id) -> list[ProductStateView]`
- `resolve_product_variant(identity) -> VariantResolution`

- [ ] **Step 1: Write failing tests** for cached reuse, single_variant/user_defined/ambiguous resolution, field-level conflict preservation, incremental missing-state addition, and source snapshot hash deduplication.
- [ ] **Step 2: Run the focused tests and confirm RED.**
- [ ] **Step 3: Implement the research run state machine** (`queued`, `running`, `candidate`, `needs_review`, `published`, `failed`, `stale`) without calling paid providers; use fixture candidates first.
- [ ] **Step 4: Implement variant resolution** using uploaded image/name/description and optional source URLs; never invent an official SKU.
- [ ] **Step 5: Implement field-level merge** so confirmed values remain locked and conflicts create candidate rows with evidence and confidence.
- [ ] **Step 6: Add API endpoints** for research start/status, candidate review, state list, state upload, refresh and publish version.
- [ ] **Step 7: Run focused tests and commit** `feat: persist product intelligence and states`.

### Task 3: Wardrobe library and actor reference retrieval

**Files:**
- Create: `backend/app/services/commercial/wardrobe.py`
- Create: `backend/app/services/commercial/actor_references.py`
- Create: `backend/app/api/commercial/wardrobes.py`
- Modify: `backend/app/api/commercial/productions.py`
- Modify: `frontend/src/features/commercial/api.ts`
- Create: `frontend/src/features/commercial/wardrobePages.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `backend/tests/commercial/test_wardrobe_and_reference_matching.py`

**Interfaces:**
- `rank_actor_references(reference_frames, source_features, *, limit=3) -> list[ReferenceMatch]`
- `create_actor_wardrobe_look(db, actor_version_id, wardrobe_version_id, ...) -> CvActorWardrobeLook`
- `resolve_wardrobe_for_shot(db, shot_features, actor_version_id, wardrobe_version_id=None) -> WardrobeMatch`

- [ ] **Step 1: Write failing tests** for Top-3 reference selection, wardrobe scope, actor-specific look caching, and per-shot wardrobe timeline.
- [ ] **Step 2: Run focused tests and confirm RED.**
- [ ] **Step 3: Implement wardrobe CRUD and share-scope authorization** with single-item and outfit-set versions.
- [ ] **Step 4: Implement reference metadata extraction/update** for angle, expression, shot scale, pose, wardrobe version and source time.
- [ ] **Step 5: Implement deterministic reference ranking** and actor-wardrobe look cache keys.
- [ ] **Step 6: Add progressive UI**: upload item images, classify, confirm tags, create outfit set, select “keep source wardrobe / wardrobe library / per-shot wardrobe”.
- [ ] **Step 7: Run backend and frontend tests; commit** `feat: add wardrobe library and actor reference matching`.

### Task 4: Authorized voice source extraction and profile binding

**Files:**
- Modify: `backend/app/services/commercial/voice.py`
- Modify: `backend/app/api/commercial/productions.py`
- Modify: `backend/app/models_commercial.py`
- Create: `backend/tests/commercial/test_voice_source_v2.py`

**Interfaces:**
- `extract_voice_source(video_asset_id, *, start_ms=None, end_ms=None) -> CvVoiceSource`
- `score_voice_source(audio_path) -> VoiceQualityReport`
- `bind_voice_source_to_actor(db, actor_id, source_id, rights_evidence_id, ...) -> CvVoiceProfile`

- [ ] **Step 1: Write failing tests** for source hash/duration, quality flags, actor binding, expiry/revocation and master-track lineage.
- [ ] **Step 2: Run focused tests and confirm RED.**
- [ ] **Step 3: Implement deterministic ffmpeg extraction and quality metadata**; keep original media and normalized sample separate.
- [ ] **Step 4: Implement actor-bound version creation** and prevent unbound sources from generation.
- [ ] **Step 5: Add provider-handle fields and capability state without enabling real paid voice calls.**
- [ ] **Step 6: Run tests and commit** `feat: persist authorized voice sources`.

### Task 5: Shot mapping, product/wardrobe/reference bundles, and workflow DAG

**Files:**
- Create: `backend/app/services/commercial/reference_resolver.py`
- Create: `backend/app/services/commercial/workflow.py`
- Modify: `backend/app/services/commercial/segment_planner.py`
- Modify: `backend/app/services/commercial/render_batch.py`
- Modify: `backend/app/api/commercial/replications.py`
- Create: `backend/tests/commercial/test_reference_resolver_and_workflow.py`

**Interfaces:**
- `build_shot_reference_bundle(shot, *, actor_version_id, product_version_id, wardrobe_version_id=None) -> ReferenceBundle`
- `start_workflow(db, replication_project_id, *, mode='balanced') -> CvWorkflowRun`
- `advance_workflow(db, workflow_run_id) -> WorkflowSnapshot`

- [ ] **Step 1: Write failing tests** for parallel-ready stages, human gates, low-confidence pauses, idempotent stage runs, variable 4–15s durations, overlap and transition metadata.
- [ ] **Step 2: Run focused tests and confirm RED.**
- [ ] **Step 3: Implement shot reference resolution**: choose product states, wardrobe looks and Top-3 actor refs; never pass full asset sets to Image2.6.
- [ ] **Step 4: Implement workflow DAG persistence and stage transitions** using existing task runtime queues.
- [ ] **Step 5: Add continuity QA metadata and selective segment repair states.**
- [ ] **Step 6: Run segment/render/continuity tests and commit** `feat: orchestrate asset-aware replication workflow`.

### Task 6: Real provider contract completion and paid gates

**Files:**
- Modify: `backend/app/services/providers/atlas/media.py`
- Modify: `backend/app/services/providers/atlas/image_edit.py`
- Modify: `backend/app/services/providers/atlas/h3_reference.py`
- Modify: `backend/app/services/providers/atlas/gemini.py`
- Modify: `backend/app/services/commercial/voice.py`
- Modify: `backend/app/services/providers/atlas/client.py`
- Create: `backend/tests/commercial/test_provider_contract_v2.py`

**Interfaces:**
- `upload_media(...) -> UpstreamMediaHandle` with URL/expiry/type.
- `edit_anchor_real(...) -> ProviderTaskResult` for Flare/Sunburst.
- `submit_h3_segment(...) -> ProviderTaskResult` with official `refers` mapping.
- `probe_role_capability(role, model_id, ...) -> CapabilityStatus`.

- [ ] **Step 1: Add transport-backed contract tests** for upload, calculate, edit, generate, poll and output download using fixture responses.
- [ ] **Step 2: Verify RED for real image/voice paths and official H3 reference mapping.**
- [ ] **Step 3: Implement real asset handle mapping and persist upstream URL/expiry.**
- [ ] **Step 4: Implement Flare/Sunburst POST, async polling and result validation.**
- [ ] **Step 5: Implement H3 segment submit/poll with per-role capability gates, 429 backoff, jitter, max attempts and dead-letter state.**
- [ ] **Step 6: Wire real Gemini product research only after source-fetch isolation and prompt-injection filtering.**
- [ ] **Step 7: Keep paid execution disabled until all role probes pass; run focused tests and commit** `feat: complete real provider contracts`.

### Task 7: Product/wardrobe/reference frontend flow and operational QA

**Files:**
- Modify: `frontend/src/features/commercial/libraryPages.tsx`
- Modify: `frontend/src/features/commercial/replicationPages.tsx`
- Modify: `frontend/src/features/commercial/replicationApi.ts`
- Create: `frontend/src/features/commercial/researchReview.tsx`
- Create: `backend/tests/commercial/test_manifest_and_quality.py`

- [ ] **Step 1: Write frontend tests** for progressive product creation, research review, missing-state prompt, wardrobe selection and per-shot reference preview.
- [ ] **Step 2: Implement product image + name + description flow** with async research, candidate review, publish and incremental refresh.
- [ ] **Step 3: Implement wardrobe library and actor-specific look confirmation.**
- [ ] **Step 4: Add per-shot review UI** for product state, wardrobe, actor refs, transition and repair reason.
- [ ] **Step 5: Add final manifest and quality summary** to task details and export records.
- [ ] **Step 6: Run full focused commercial and frontend suites; commit** `feat: expose asset-aware replication workflow`.

### Task 8: End-to-end validation and rollout gates

**Files:**
- Create: `backend/tests/commercial/test_e2e_asset_aware_replication.py`
- Modify: `docs/handoff/phase_reports/` with a dated validation report

- [ ] **Step 1: Add isolated E2E fixture** covering one product reused twice, one shared wardrobe reused by two actors, Linzhi0 voice source, variable segments and one selective repair.
- [ ] **Step 2: Run Mock/Fixture E2E and assert no duplicate research run, no cross-actor voice, correct product-state mapping, and complete manifest.**
- [ ] **Step 3: Run sandbox provider contract tests.**
- [ ] **Step 4: Run one authorized real Atlas smoke test only after all role gates and budget approvals pass.**
- [ ] **Step 5: Record latency, cost, 429, output validation, continuity QA and retry metrics; commit** `test: validate asset-aware replication end to end`.

