# 商业短视频复刻系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有商业模板系统上交付结构改写 MVP，并为高保真复刻建立可审计、可恢复、可控成本的生产链路。

**Architecture:** 以 `CvProduction` 为现有作品入口，新增一对一 `CvReplicationProject` 管理复刻模式和版本状态。Gemini 负责结构化分析、脚本编排和质量检查，确定性媒体服务负责抽帧、锚帧采样和时间轴，Image2.6 与 H3 通过独立 provider adapter 接入。所有脚本、锚帧、声音和导出均使用不可变 revision，H3 只消费冻结版本。

**Tech Stack:** FastAPI、Pydantic 2、SQLAlchemy async、PostgreSQL 增量 schema patch、React 19、TypeScript、Node test、FFmpeg、HTTPX MockTransport。

**Spec:** [2026-11-12-commercial-video-replication-design.md](<D:/AI Project/AIDaRen/docs/superpowers/specs/2026-11-12-commercial-video-replication-design.md>)

## Global Constraints

- 默认模式是 `structural_rewrite`，`high_fidelity` 通过 feature flag 和权利/商品硬门控制。
- 原始参考视频、原始关键帧和未审核源片派生帧不得进入 H3。
- 只有带完整血缘并经人工审核的 `approved_source_derived_anchor` 可以进入 H3。
- H3 单次调用最多 9 张参考图。第一版按单镜头或连续短片段使用 1～3 张锚帧。
- 预览默认使用 9:16 和最低已验证分辨率，正式渲染复用冻结版本。
- 真实供应商契约未通过探针前只能使用 Mock、Fixture 或沙箱。
- 商品 claim 必须来自已审核商品目录，模型不得自由生成事实、价格或功效承诺。
- 用户没有接受报价前不得触发真实付费任务。
- 所有写接口使用 `idempotency_key` 或 `expected_version`，重试从最近成功节点恢复。

## Review Focus

- 权利证据缺失或撤回时，任何真实模型调用都必须在 H3 前阻断。由 Task 1 测试。
- 商品状态从 `required`、`optional`、`absent`、`unknown` 发生变化时，旧脚本、锚帧和报价必须失效。由 Task 2 测试。
- H3 不支持有序多图或参考图超过 9 张时，系统必须按连续片段降级并保持时间轴顺序。由 Task 5 测试。
- 同一输入、同一 revision 的重复请求不得重复调用供应商或重复扣费。由 Task 1 和 Task 6 测试。
- 预览和正式版必须引用同一脚本、Anchor Set、声音和字幕 revision。由 Task 6 和 Task 7 测试。

## 文件结构

- `backend/app/models_commercial.py`：复刻、Shot Graph、脚本、锚帧、声音和字幕模型。
- `backend/app/commercial_schema.py`：增量表、列、索引和唯一约束。
- `backend/app/services/commercial/rights.py`：权利证据和硬门。
- `backend/app/services/commercial/frames.py`：帧抽取、候选筛选和锚帧采样。
- `backend/app/services/commercial/timeline.py`：镜头、字幕、声音和片段时间轴。
- `backend/app/services/commercial/replication.py`：模式路由、状态转移和 revision 失效。
- `backend/app/services/providers/atlas/gemini.py`：Gemini 分析和脚本适配契约。
- `backend/app/services/providers/atlas/image_edit.py`：Image2.6 适配器和能力探针。
- `backend/app/services/providers/atlas/h3_reference.py`：H3 参考视频适配器和能力探针。
- `backend/app/api/commercial/replications.py`：复刻项目、脚本、锚帧、声音和预览接口。
- `frontend/src/features/commercial/replicationPages.tsx`：创建、分析、脚本、锚帧、预览流程。
- `frontend/src/features/commercial/replicationApi.ts`：复刻领域 API 和类型。

### Task 1: 权利、报价接受和复刻状态基础

**Files:**
- Create: `backend/app/services/commercial/rights.py`
- Create: `backend/app/services/commercial/replication.py`
- Modify: `backend/app/models_commercial.py`
- Modify: `backend/app/commercial_schema.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/commercial/test_replication_gates.py`

**Interfaces:**
- Produces `check_rights_gate(db, subject_ids, *, operation) -> RightsDecision`.
- Produces `transition_replication(project, target_status, *, expected_version, actor_id) -> project`.
- Produces quote states `draft`, `pending_user_acceptance`, `accepted`, `expired`, `settled`, `disputed`.

- [ ] **Step 1: 写失败测试**
  - 权利缺失阻断高保真和真实模型调用。
  - 用户未接受报价时禁止 preview/finalize。
  - 错误的 `expected_version` 返回冲突。
  - 同一 `idempotency_key` 返回同一结果。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_replication_gates.py -q`
  - Expected: 新接口和状态约束失败。
- [ ] **Step 3: 实现模型、schema patch 和服务**
  - 添加 `cv_replication_projects`、`cv_rights_evidence`、报价状态和必要唯一索引。
  - `production_id` 唯一外键，所有 revision 关联 replication project。
  - 在 `commercial_schema.py` 和测试注册路径中加入增量 DDL。
- [ ] **Step 4: 运行测试确认通过**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_replication_gates.py -q`
  - Expected: PASS。
- [ ] **Step 5: 提交**

### Task 2: Shot Graph、商品证据和 revision 失效

**Files:**
- Create: `backend/app/services/commercial/frames.py`
- Create: `backend/app/services/commercial/timeline.py`
- Modify: `backend/app/models_commercial.py`
- Modify: `backend/app/commercial_schema.py`
- Test: `backend/tests/commercial/test_shot_graph_and_invalidation.py`

**Interfaces:**
- `extract_source_frame(source_asset_id, time_ms) -> CvMediaAsset`。
- `sample_anchor_candidates(shot_graph, *, max_frames) -> list[AnchorCandidate]`。
- `invalidate_downstream_revisions(project_id, *, changed_shot_keys, reason) -> None`。

- [ ] **Step 1: 写失败测试**
  - 15 秒简单镜头采样 3 张，商品展示镜头采样 5 张。
  - 商品状态变化使受影响脚本、锚帧、声音和报价失效。
  - 源帧只能创建私有 `reference_source_frame` 资产。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_shot_graph_and_invalidation.py -q`
- [ ] **Step 3: 实现抽帧、采样和失效传播**
  - 使用 FFmpeg 抽取私有帧，记录 source asset、时间点、hash 和父级。
  - 使用镜头边界、运动变化、清晰度和商品证据选择候选。
  - 为 Shot Graph、Anchor Set、Anchor Frame、Subtitle Version 增加 revision 和索引。
- [ ] **Step 4: 运行测试确认通过**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_shot_graph_and_invalidation.py -q`
- [ ] **Step 5: 提交**

### Task 3: Gemini 分析和结构化脚本

**Files:**
- Modify: `backend/app/services/providers/atlas/gemini.py`
- Create: `backend/app/services/commercial/replication.py`（分析和脚本编排部分）
- Create: `backend/app/api/commercial/replications.py`
- Create: `backend/tests/commercial/test_replication_script_contract.py`
- Create: `frontend/src/features/commercial/replicationApi.ts`

**Interfaces:**
- `GeminiAdapter.analyze_video(request) -> ShotGraphPayload`。
- `GeminiAdapter.adapt_script(request) -> ScriptVersionPayload`。
- `POST /api/commercial/replications/{id}/analyze`。
- `POST /api/commercial/replications/{id}/scripts`。
- `POST /api/commercial/scripts/{version_id}/approve`。

- [ ] **Step 1: 写失败测试**
  - 分析输出包含 shot_key、时间、商品证据和置信度。
  - 脚本输出的 claim_id 必须存在于商品目录。
  - 低置信商品判定进入人工状态。
  - 高保真脚本不能改变已锁定镜头时长。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_replication_script_contract.py -q`
- [ ] **Step 3: 实现分析、结构提取、脚本适配和版本冻结**
  - Gemini 只负责结构化理解和编排，图片顺序由外部 shot graph 控制。
  - 所有 prompt、schema、model version 和输入 hash 写入版本。
- [ ] **Step 4: 运行测试确认通过**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_replication_script_contract.py -q`
- [ ] **Step 5: 提交**

### Task 4: Image2.6 Mock/沙箱锚帧适配器

**Files:**
- Create: `backend/app/services/providers/atlas/image_edit.py`
- Modify: `backend/app/services/commercial/frames.py`
- Create: `backend/tests/commercial/test_image_edit_adapter.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- `ImageEditAdapter.probe_capabilities() -> ImageEditCapabilities`。
- `ImageEditAdapter.edit_anchor(request) -> EditedAnchorPayload`。
- `POST /api/commercial/replications/{id}/anchor-sets`。
- `POST /api/commercial/anchor-sets/{id}/generate`。
- `POST /api/commercial/anchor-frames/{id}/regenerate`。

- [ ] **Step 1: 写失败测试**
  - `absent` 不传商品图。
  - `required` 缺商品图时拒绝。
  - 图生图输出带 parent_anchor、model、prompt_hash 和 status。
  - 未批准锚帧不能进入 H3 请求。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_image_edit_adapter.py -q`
- [ ] **Step 3: 实现 Mock/沙箱适配器和质量门**
  - 真实 model ID 从配置读取，未通过 probe 时只允许 Mock。
  - 生成结果写入 `anchor_candidate`，人工批准后转 `approved`。
- [ ] **Step 4: 运行测试确认通过**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_image_edit_adapter.py -q`
- [ ] **Step 5: 提交**

### Task 5: 授权 TTS、声音版本和字幕版本

**Files:**
- Create: `backend/app/services/commercial/voice.py`
- Modify: `backend/app/models_commercial.py`
- Modify: `backend/app/commercial_schema.py`
- Create: `backend/tests/commercial/test_voice_and_subtitles.py`
- Modify: `frontend/src/features/commercial/replicationApi.ts`

**Interfaces:**
- `VoiceStrategy.render(script_version_id, voice_profile_id) -> CvVoiceRender`。
- `POST /api/commercial/replications/{id}/voice-renders`。
- `POST /api/commercial/voice-renders/{id}/approve`。

- [ ] **Step 1: 写失败测试**
  - 无声音授权不能生成音频。
  - 脚本修改使旧 voice render 失效。
  - TTS 实测时长回填镜头时间轴。
  - 预览和正式版引用同一字幕版本。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_voice_and_subtitles.py -q`
- [ ] **Step 3: 实现授权 TTS 和字幕 revision**
  - MVP 使用授权 TTS 或 Mock。H3 原生声音路径保留为 probe 后能力。
  - 保存 rights evidence、voice version、script hash、duration 和 audio asset。
- [ ] **Step 4: 运行测试确认通过**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_voice_and_subtitles.py -q`
- [ ] **Step 5: 提交**

### Task 6: H3 低清预览、分批和时间轴

**Files:**
- Modify: `backend/app/services/providers/atlas/h3_reference.py`
- Modify: `backend/app/services/commercial/generation_request.py`
- Modify: `backend/app/services/commercial/timeline.py`
- Modify: `backend/app/services/commercial/generation.py`
- Create: `backend/tests/commercial/test_replication_preview.py`

**Interfaces:**
- `H3VideoAdapter.probe_capabilities() -> H3Capabilities`。
- `H3VideoAdapter.submit_preview(frozen_revision) -> TaskRun`。
- `TimelineCompiler.compose_preview(segment_outputs, timeline) -> CvExport`。

- [ ] **Step 1: 写失败测试**
  - 预览默认 9:16 和最低已验证分辨率。
  - 单次请求超过 9 张参考图被拒绝或按连续片段拆分。
  - H3 只接收 approved anchor set、approved script、approved voice 和 approved subtitles。
  - 同一 frozen revision 重复提交不重复创建任务。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_replication_preview.py -q`
- [ ] **Step 3: 实现 Mock/沙箱 H3 适配器、分批策略和时间轴**
  - 第一版每个镜头或连续短片段使用 1～3 张锚帧。
  - 外部时间轴负责顺序、字幕、声音和片段拼接。
  - 真实 H3 字段只有 probe 通过后才能启用。
- [ ] **Step 4: 运行测试确认通过**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_replication_preview.py -q`
- [ ] **Step 5: 提交**

### Task 7: 结构改写 MVP 前端和审核门

**Files:**
- Create: `frontend/src/features/commercial/replicationPages.tsx`
- Create: `frontend/src/features/commercial/replicationApi.ts`
- Modify: `frontend/src/features/commercial/CommercialLayout.tsx`
- Create: `frontend/tests/commercial-replication-flow.test.mjs`

**Interfaces:**
- 创建、分析、脚本确认、声音确认、预览和正式渲染页面。
- API 类型必须对应 Task 3、5、6 的响应 Schema。

- [ ] **Step 1: 写失败测试**
  - 模式卡显示推荐原因、风险和预计费用。
  - 脚本未批准时不能进入锚帧或预览。
  - 权利状态或商品匹配状态不通过时禁用高保真。
  - 预览失败可以从最近成功阶段恢复。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `cd frontend; npm test`
- [ ] **Step 3: 实现结构改写 MVP 页面**
  - 分析 → 脚本 → 商品映射 → 声音 → 预览 → 正式渲染。
  - 保持原有商业页面和任务列表入口。
- [ ] **Step 4: 运行测试、构建和 lint**
  - Run: `cd frontend; npm test`
  - Run: `cd frontend; npm run build`
  - Run: `cd frontend; npm run lint`
- [ ] **Step 5: 提交**

### Task 8: 高保真试点、自动 QA 和放量开关

**Files:**
- Modify: `backend/app/services/commercial/replication.py`
- Create: `backend/app/services/commercial/quality.py`
- Modify: `backend/app/api/commercial/replications.py`
- Modify: `frontend/src/features/commercial/replicationPages.tsx`
- Create: `backend/tests/commercial/test_high_fidelity_gates.py`

**Interfaces:**
- `QualityService.check_preview(export_id) -> QualityReport`。
- `RouteService.recommend_mode(evidence) -> RouteDecision`。
- `POST /api/commercial/replications/{id}/finalize`。

- [ ] **Step 1: 写失败测试**
  - 同 SKU、权利和商品证据齐全才允许 high fidelity。
  - 高保真锚帧未批准时不能 finalize。
  - 商品露出不足、源商品未清零、字幕越界或音画漂移失败时阻断发布。
  - feature flag 关闭时强制回落结构改写。
- [ ] **Step 2: 运行测试确认失败**
  - Run: `backend\.venv\Scripts\python.exe -m pytest tests/commercial/test_high_fidelity_gates.py -q`
- [ ] **Step 3: 实现路由、自动 QA 和受控放量**
  - 保存 route reason、evidence snapshot、规则版本和 QA 报告。
  - 配置试点用户、预算上限、质量报警和 kill switch。
- [ ] **Step 4: 运行完整验证**
  - Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/commercial -q`
  - Run: `cd frontend; npm test; npm run build; npm run lint`
- [ ] **Step 5: 提交**

## Test and Release Gates

- Task 1–6 每个任务必须先看到失败测试，再实现最小通过方案。
- 结构改写 MVP 在 30 条分层基准素材上完成首轮评估后才能进入试点。
- 高保真模式必须通过权利、商品、锚帧、声音和质量五道门。
- 真实供应商能力探针未通过时，发布开关保持关闭。
- 现有商业测试和现有前端测试必须在每个集成任务后继续通过。
