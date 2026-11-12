# 商业短视频复刻系统正式设计规格

**日期**：2026-11-12  
**状态**：待用户审阅  
**适用项目**：AIDaRen 商业短视频模板化生产系统

## 1. 目标

在现有商业模板生产系统上增加“参考驱动的复刻生成”能力。系统接收一条有权使用的参考视频，理解其镜头结构、动作、节奏、商品露出和叙事逻辑，使用我方达人、商品、授权音色和自有文案生成新视频。

系统提供两个用户模式。

### 1.1 结构改写

结构改写保留爆款视频的 Hook、痛点、冲突、证明方式、情绪曲线和 CTA 节奏。系统重新生成剧情细节、台词、动作、商品表达、达人声音和必要的视觉锚帧。

结构改写是全局默认模式，适用于跨商品、跨类目、卖点变化和源片权利或画面质量不足的场景。

### 1.2 高保真复刻

高保真复刻保留镜头顺序、镜头时长、机位、构图、关键动作、商品出现时机、字幕和 CTA 位置。系统替换达人、商品、台词、声音和经过审核的视觉锚帧。

高保真复刻只在同 SKU 或高度相似商品、卖点一致、源片可拆解、人物和声音权利完整时推荐。首阶段通过 feature flag 和运营审核控制开放范围。

### 1.3 内部混合路由

混合策略不作为单独的用户入口。系统可以保留已验证的开场钩子和节奏，重写中后段剧情、商品表达和 CTA。

## 2. 范围

### 2.1 本次范围

- 视频解析和镜头结构化
- 爆款结构提取
- 结构改写脚本生成
- 高保真脚本生成
- 镜头级商品出现判断
- 视觉锚帧候选选择
- Image2.6 图生图达人和商品替换
- 人工确认后的锚帧冻结
- 授权达人音色生成或 H3 音频参考
- 15 秒上限下的长视频分段规划和连续性锚点
- H3 低清预览和正式渲染
- 脚本、锚帧、声音和生成任务版本化
- 商品、声音、画面和合规质检
- 分阶段报价、重试和失败恢复

### 2.2 不在本次范围

- 自动绕过版权或声音授权
- 未验证供应商契约下的真实付费调用
- 将原始参考视频或原始关键帧直接发送给 H3
- 自动复制原人物原声
- 逐帧生成整段视频的图生图替换
- 新增独立账号体系
- 替换现有任务调度器

## 3. 核心约束

### 3.1 模型约束

- Gemini 3 Flash Preview 负责视频分析、结构提取、脚本编排和生成后质检。
- GPT Image 2.6 Flare Edit 负责候选锚帧，GPT Image 2.6 Sunburst Edit 负责最终批准锚帧。真实 Atlas model ID、端点、输入槽位和返回格式必须通过能力探针确认后写入配置。
- MiniMax H3 Developer Reference-to-Video 负责视频生成。H3 只消费冻结后的锚帧、脚本、声音条件和生成参数。
- H3 的多图顺序、音频参考、声音复刻、最大参考图数、分辨率和响应映射必须通过真实或沙箱契约验证。

### 3.2 输出约束

- 预览默认使用 9:16、最低已验证分辨率，当前候选为 480P。
- 单次 H3 生成段的请求时长不得超过 15 秒。60 秒、120 秒等长片必须先生成外部 render plan。
- 正式输出复用冻结版本，可选择 480P、768P 或 2K 等已验证分辨率。
- H3 单次请求最多 9 张参考图。超过限制时按连续镜头片段分批生成，由外部时间轴合成。
- 生成时序由系统的 shot graph、shot_key、序号和时间戳控制，不依赖 H3 自行推断多图顺序。

### 3.3 INV-01 调整

原始参考视频、原始关键帧和未审核的源片派生帧不能进入 H3。

经过图生图处理、完整血缘记录和人工审核的替换锚帧可以进入 H3。该资产必须标记为 `approved_source_derived_anchor`，并保存父级源帧、变换操作、模型版本、prompt hash、审核人和审核时间。

## 4. 路由规则

系统使用确定性规则先路由，Gemini 提供证据和置信度。

| 条件 | 路由 |
|---|---|
| 同 SKU、同规格、卖点一致、权利完整 | 推荐高保真复刻 |
| 同类目不同 SKU | 推荐结构改写 |
| 跨类目 | 结构改写 |
| 功效、价格或规格冲突 | 结构改写并人工确认 |
| 人物、声音、视频或音乐权利不明确 | 禁止高保真复刻 |
| 源视频质量不足或镜头难拆 | 结构改写 |
| 商品匹配置信度 < 0.85 | 暂停自动生成，进入人工 |
| 只需保留开场和节奏 | 混合路由 |

用户可以覆盖系统推荐，但页面必须显示推荐原因、风险、预计耗时和费用。

## 5. 端到端流程

```text
上传参考视频与目标商品
  ↓
权利和商品资料确认
  ↓
Gemini 视频分析
  ↓
Shot Graph 与商品露出判断
  ↓
规则路由：结构改写 / 高保真 / 混合
  ↓
Gemini 生成结构化脚本
  ↓
用户确认脚本、商品映射和声音
  ↓
按镜头和动作边界规划 ≤15 秒 render segments
  ↓
抽取镜头锚帧候选
  ↓
Image2.6 替换达人和必要商品
  ↓
用户确认并冻结 Anchor Set
  ↓
授权音色生成或 H3 音频参考
  ↓
H3 生成 9:16 低清预览
  ↓
自动质检与人工预览确认
  ↓
使用冻结版本生成正式分辨率
  ↓
外部时间轴合成、字幕和最终导出
```

## 6. 模型适配器设计

### 6.1 GeminiAdapter

职责：

- `analyze_video`：输出 ASR、OCR、镜头边界、动作、构图、商品露出、声音信息和锚帧候选。
- `extract_story_structure`：输出 Hook、痛点、冲突、证明、利益点和 CTA。
- `adapt_script`：根据模式、商品目录、已审核 claims、达人设定和营销目标生成新脚本。
- `quality_check`：检查镜头结构、商品事实、台词、CTA、禁用表述和目标模式约束。

要求：

- 所有输出使用 Pydantic 或等价结构化 Schema。
- 商品事实必须引用 `claim_id`。
- 低置信度必须输出证据和人工复核原因。
- 不让 Gemini 决定 H3 图片顺序，图片顺序由外部 shot graph 管理。
- 每个 prompt、模型版本和 schema 版本必须进入版本记录。

### 6.2 ImageEditAdapter

职责：

- 输入源锚帧、达人图、可选商品图和镜头编辑提示。
- 候选阶段默认使用 GPT Image 2.6 Flare Edit，最终锚帧默认使用 GPT Image 2.6 Sunburst Edit。
- 输出替换锚帧、模型响应 ID、图片 URL、尺寸、hash 和成本信息。
- 支持单张重做，不重新解析视频和重写全部脚本。

要求：

- 图生图结果进入 `anchor_candidate`，未经人工确认不能进入 H3。
- 商品为 `absent` 时禁止注入商品参考。
- 商品为 `required` 时必须进行商品形态、包装和露出校验。
- 保存父级资产和变换参数。
- 失败只影响当前锚帧或当前镜头。

### 6.3 H3VideoAdapter

职责：

- 接收冻结的 `approved_anchor_set`、脚本、声音条件和生成参数。
- 生成低清预览和正式版本。
- 记录 H3 请求 hash、响应 ID、预测任务 ID、输入锚帧映射和成本。
- 支持查询、退避、下载重试和提交结果不明状态。

要求：

- H3 请求最多 9 张参考图。
- 未验证多图顺序时，按单镜头或连续片段调用。
- 每个 segment 只能消费自己的 1～3 张锚帧、片段时间轴和连续性锚点。
- H3 生成不重新编写全片台词。全片脚本和 master voice track 由外部时间轴统一管理。
- 真实契约未验证时只能使用 Mock 或 Fixture。
- 预览和正式输出必须引用同一份冻结脚本、Anchor Set、声音和商品版本。

### 6.4 VoiceStrategy

主适配器仍归属于生成链路，不新增第四个核心模型入口。

优先路径：

```text
授权达人音色版本 + approved_dialogue → H3 音频参考或原生声音生成
```

备用路径：

```text
授权达人音色版本 + approved_dialogue → 独立 TTS / 声音克隆 → 生成音频资产
```

两条路径都必须保存声音授权凭证、音色版本、脚本 hash、模型版本、实测时长和审核状态。

## 7. 数据库对象

复用现有 `CvReferenceSource`、`CvAnalysisRun`、`CvProduction`、`CvGenerationAttempt`、`CvExport`、`CvActor`、`CvProduct`、`CvVoiceProfile`、`CvUsageLedger`。

### 7.1 `cv_replication_projects`

记录一次复刻任务的模式和路由结果。

核心字段：

- `id`
- `production_id`
- `mode`：`structural_rewrite` / `high_fidelity`
- `route_reason`
- `route_confidence`
- `rights_status`
- `status`
- `current_script_version_id`
- `current_anchor_set_id`
- `current_voice_render_id`
- `created_by`
- `created_at`
- `updated_at`

### 7.2 `cv_shot_graphs`

记录 Gemini 解析和规则处理后的镜头图。

核心字段：

- `replication_project_id`
- `shot_key`
- `start_ms`
- `end_ms`
- `purpose`
- `camera_json`
- `composition_json`
- `action_json`
- `emotion_json`
- `product_presence`
- `product_confidence`
- `product_evidence_json`
- `anchor_candidates_json`
- `source_span_json`
- `analysis_version`
- `status`

### 7.3 `cv_script_versions`

记录结构改写或高保真脚本的不可变版本。

核心字段：

- `replication_project_id`
- `version`
- `mode`
- `script_json`
- `claim_ids_json`
- `prompt_version`
- `model_id`
- `model_version`
- `input_hash`
- `status`
- `approved_by`
- `approved_at`

### 7.4 `cv_anchor_sets`

记录一次锚帧候选或冻结版本。

核心字段：

- `replication_project_id`
- `version`
- `status`：`candidate` / `approved` / `rejected`
- `mode`
- `frame_count`
- `input_hash`
- `approved_by`
- `approved_at`

### 7.5 `cv_anchor_frames`

记录单张源帧、替换帧和血缘。

核心字段：

- `anchor_set_id`
- `shot_key`
- `sequence`
- `time_ms`
- `role`
- `source_asset_id`
- `edited_asset_id`
- `parent_anchor_id`
- `actor_version_id`
- `product_version_id`
- `provider`
- `model_id`
- `model_version`
- `prompt_hash`
- `seed`
- `quality_status`
- `review_status`

### 7.6 `cv_voice_renders`

记录脚本对应的声音输出。

核心字段：

- `replication_project_id`
- `script_version_id`
- `voice_profile_id`
- `model_id`
- `model_version`
- `audio_asset_id`
- `duration_ms`
- `script_hash`
- `rights_evidence_id`
- `quality_status`
- `approved_by`
- `approved_at`

### 7.7 `cv_render_batches` 和 `cv_render_segments`

`cv_render_batches` 是一次预览或正式渲染的全片协调对象。`cv_render_segments` 是单次 H3 调用对应的可恢复片段。

`cv_render_batches` 核心字段：

- `replication_project_id`
- `script_version_id`
- `anchor_set_id`
- `voice_render_id`
- `subtitle_version_id`
- `stage`：`preview` / `final`
- `status`
- `master_voice_track_id`
- `total_duration_ms`
- `frozen_version_hash`
- `expected_version`

`cv_render_segments` 核心字段：

- `render_batch_id`
- `segment_index`
- `shot_keys_json`
- `source_start_ms`
- `source_end_ms`
- `overlap_ms`
- `continuity_anchor_time_ms`
- `request_duration_ms`
- `anchor_frame_ids_json`
- `segment_audio_start_ms`
- `segment_audio_end_ms`
- `provider_task_id`
- `status`
- `output_asset_id`
- `error_code`

单个 segment 的 `request_duration_ms` 必须小于等于 15,000。无法找到安全切点时，batch 进入 `needs_human_review`，系统暂停自动生成。

全片声音使用一个 `master_voice_track_id`。各 segment 只引用该音轨的时间范围，不能为每段重新生成完整台词。

### 7.8 现有表扩展

- `CvGenerationAttempt` 增加 `replication_project_id`、`script_version_id`、`anchor_set_id`、`voice_render_id`、`preview_or_final`。
- `CvCostQuote` 增加模式复杂度、锚帧数量、声音路径和人工审核预留快照。
- `CvExport` 增加脚本版本、锚帧版本、声音版本和质量检查摘要。

## 8. 后端接口拆分

### 8.1 复刻项目

- `POST /api/commercial/replications`
  - 创建复刻项目并保存模式、目标商品和声音路径。
- `GET /api/commercial/replications/{id}`
  - 返回当前状态、模式、版本和待确认门。
- `POST /api/commercial/replications/{id}/route`
  - 执行规则路由，返回推荐模式和证据。

### 8.2 分析和 Shot Graph

- `POST /api/commercial/replications/{id}/analyze`
- `GET /api/commercial/replications/{id}/shot-graph`
- `POST /api/commercial/replications/{id}/shot-graph/confirm`

### 8.3 脚本

- `POST /api/commercial/replications/{id}/scripts`
- `GET /api/commercial/replications/{id}/scripts`
- `POST /api/commercial/scripts/{version_id}/approve`
- `POST /api/commercial/scripts/{version_id}/reject`

### 8.4 锚帧

- `POST /api/commercial/replications/{id}/anchor-sets`
- `POST /api/commercial/anchor-sets/{id}/generate`
- `GET /api/commercial/anchor-sets/{id}`
- `POST /api/commercial/anchor-sets/{id}/approve`
- `POST /api/commercial/anchor-frames/{id}/regenerate`

### 8.5 声音

- `POST /api/commercial/replications/{id}/voice-renders`
- `GET /api/commercial/replications/{id}/voice-renders`
- `POST /api/commercial/voice-renders/{id}/approve`
- `POST /api/commercial/voice-renders/{id}/regenerate`

### 8.6 预览和正式生成

- `POST /api/commercial/replications/{id}/render-plan`
  - 根据 shot graph、脚本和声音时间轴生成 render batch 与 segments。
- `GET /api/commercial/render-batches/{id}`
  - 返回全片 segment 状态、时间范围、连续性锚点和恢复节点。
- `POST /api/commercial/replications/{id}/quote`
- `POST /api/commercial/replications/{id}/preview`
- `GET /api/commercial/replications/{id}/preview`
- `POST /api/commercial/replications/{id}/finalize`
- `GET /api/commercial/replications/{id}/manifest`

现有 `/productions/{id}/quote`、`/generate`、`/compose` 和任务恢复机制继续复用。新接口负责版本和门状态，现有任务接口负责执行。

## 9. 前端流程

### 9.1 创建入口

用户填写：

- 参考视频
- 目标商品或商品目录
- 目标达人
- 声音路径
- 营销目标

系统展示两个模式卡片：

- 结构改写：保留爆款结构，重写脚本与画面
- 高保真复刻：保留镜头节奏，替换商品、达人和声音，需要授权

卡片展示推荐模式、推荐原因、预计耗时、预计消耗和风险。

### 9.2 分析页

展示：

- 镜头时间线
- ASR 和 OCR
- Hook、痛点、证明和 CTA
- 商品露出
- 声音轨和音乐轨
- 权利状态
- 商品匹配状态

用户可以修改镜头边界、商品状态和营销目标。

### 9.3 脚本页

展示每个镜头的：

- 目的
- 台词
- 动作
- 画面提示
- 商品状态
- claim 来源
- 预计口播时长

用户批准后才能进入锚帧和声音阶段。

### 9.4 锚帧页

展示：

- 原始候选帧
- 替换后的锚帧
- 镜头编号和时间
- 商品是否出现
- 达人和商品版本
- 质量检查结果

用户可以重做单张锚帧、切换商品状态和批准 Anchor Set。

### 9.5 预览页

默认生成 9:16、最低已验证分辨率的低清预览。页面展示：

- 预览视频
- 目标商品检查
- 字幕检查
- 音画同步检查
- 达人一致性
- 待修改镜头

用户确认后进入正式渲染。

## 10. 计费与任务状态

对外展示成片报价，内部拆分：

- 基础分析
- 模式复杂度
- 图生图锚帧数量
- H3 生成秒数
- 声音路径
- 人工审核
- 修改轮次
- 输出变体

分析、脚本、锚帧和声音确认后锁定报价。所有报价关联具体版本 hash。

每个阶段使用输入 hash 和幂等键缓存。阶段失败从最近成功节点恢复。H3 提交结果不明时先查询原请求，不自动重发。

## 11. 质量验收

### 11.0 长视频连续性

- 优先在原始镜头切点切分 segment。
- 单镜头超过 15 秒时，在动作中性点或可解释的节奏点切分。
- 相邻 segment 使用连续性锚点，保留人物、服装、商品、背景和镜头方向。
- `overlap_ms` 由 render plan 明确记录，外部时间轴只保留一个连续对白时间轴。
- 跨段人物或商品跳变、重复台词、音频重复、黑帧和断帧都阻断 final。
- 无安全切点时进入人工规划，不自动压缩、截断或重写整段台词。

### 通用硬门槛

- 渲染成功率 ≥ 98%
- 时长误差 ≤ 0.1 秒
- 黑帧和花帧为 0
- 音画漂移 ≤ 80ms
- 字幕不截断、不出框
- 目标商品完整出现
- 源商品露出清零
- 禁止功效词和绝对化承诺命中率为 0

### 高保真指标

- 镜头顺序保持率 ≥ 90%
- 关键镜头时间偏差 ≤ 5%
- 关键动作保留率 ≥ 95%
- 首轮人工通过率 ≥ 80%

### 结构改写指标

- Hook、痛点、证明/演示、利益点、CTA 五段结构完整
- 商品事实与目录一致
- 脚本与目标商品匹配
- 首轮人工评分达到 4/5 的比例 ≥ 80%

## 12. 能力探针

在真实付费联调前，必须完成：

### H3 探针

- 最大参考图数
- 多图顺序语义
- 每张图的用途映射
- 参考音频字段
- 声音复刻是否支持
- 9:16 的 480P、768P、2K 尺寸
- 输出时长
- seed 和幂等键
- 任务响应和成本字段

### Image2.6 探针

- 输入锚帧、达人图、商品图的槽位
- 区域编辑能力
- 人物和商品保持能力
- 返回图片和成本字段
- seed 和幂等键
- 图像尺寸和格式
- 失败和限流语义

### Gemini 探针

- ASR 和 OCR 结构化结果
- 镜头边界稳定性
- 结构化脚本输出
- claim 引用完整性
- 低置信度识别
- 生成后质检输出

## 13. 开发任务拆分

### A. 数据和血缘

1. 新增复刻项目、Shot Graph、脚本版本、Anchor Set、Anchor Frame、Voice Render 表。
2. 扩展现有生产、报价、尝试和导出表。
3. 增加不可变 revision、hash、parent ID 和审核字段。
4. 增加 Mock 数据迁移和回滚测试。

### B. Gemini 适配器

1. 定义分析 Schema。
2. 定义脚本 Schema。
3. 实现视频分析、结构提取、脚本编排和质量检查。
4. 增加 claim 引用和低置信度门禁。
5. 增加 Fixture 测试和版本化 prompt。

### C. Image2.6 适配器

1. 实现能力探针。
2. 实现源锚帧、达人图和可选商品图上传或句柄处理。
3. 实现单张锚帧生成和重做。
4. 实现质量检查和血缘记录。
5. 增加 3、5、7 张锚帧测试。

### D. H3 适配器

1. 扩展参考图、参考音频和锚帧顺序请求结构。
2. 实现 9 图上限和分批策略。
3. 实现 9:16 低清预览和正式渲染。
4. 实现任务幂等、查询、退避和提交结果不明恢复。
5. 通过能力探针后再启用真实字段。

### E. 声音链路

1. 建立授权音色版本和凭证关联。
2. 实现 H3 原生声音条件路径。
3. 实现独立 TTS/克隆 fallback。
4. 实测音频时长回填时间轴。
5. 增加发音、数字、专名和自然度检查。

### F. 后端接口和状态机

1. 新增复刻项目、分析、脚本、锚帧、声音、预览和正式生成接口。
2. 复用现有 TaskRun、报价、审核和合成机制。
3. 增加模式路由、人工门和状态转移。
4. 增加阶段级幂等和最近成功节点恢复。
5. 增加审计 manifest 下载接口。

### G. 前端流程

1. 模式选择和推荐原因。
2. 分析和商品匹配确认。
3. 脚本编辑和 claim 展示。
4. 锚帧板和单帧重做。
5. 声音预览和授权状态。
6. 低清预览、质检结果和正式渲染。
7. 任务详情中的版本、费用和血缘展示。

### H. 验收和运营

1. 建立至少 30 条分层基准素材，覆盖同 SKU、同类目、跨类目和 15/30/60 秒。
2. 记录结构保持度、商品露出、声音错误、首预览耗时、返工轮次和可发布率。
3. 结构改写先上线，高保真通过 feature flag 试点。
4. 达到质量门槛后再开放高保真规模化。

## 14. 实施顺序

建议顺序：

1. 能力探针、权利对象、报价接受和基础状态机
2. 数据对象、迁移脚本和版本血缘
3. Gemini 分析与脚本 Schema
4. 确定性帧抽取、锚帧采样和外部时间轴
5. Image2.6 Mock/沙箱适配器
6. 授权 TTS 适配器和声音版本
7. H3 Mock/沙箱适配器与结构改写纵向切片
8. 结构改写 MVP 的预览、审核、合成和质量门
9. 高保真锚帧审核和受控试点
10. 真实供应商联调、分层报价和放量

## 15. 待能力探针确认的事项

- Image2.6 的真实 model ID 和图生图接口
- H3 是否支持声音复刻，还是只支持参考音频
- H3 多图是否保留顺序和每图语义
- H3 9:16 各分辨率真实输出尺寸
- 真实供应商返回的成本字段和幂等字段
- 图生图和 H3 的素材保留期、下载 URL 和权限

这些事项确认前，相关功能只在 Mock 或 Fixture 模式运行，不能开启真实付费执行。

## 16. 审查修订与硬门

本节覆盖前述同主题的宽泛表述，作为进入开发前的执行准则。

### 16.1 纵向切片门

结构改写 MVP 必须先完成一条可运行的纵向切片：Gemini 分析 → 结构化脚本 → Mock 或沙箱锚帧 → 授权 TTS → H3 Mock 或沙箱预览 → 外部时间轴合成 → 自动 QA。Image2.6、H3 真实多图和声音能力未通过探针前，不创建依赖真实字段的生产路径。

### 16.2 权利证据和不可绕过规则

新增 `cv_rights_evidence`，记录：

- `subject_type`：视频、人物、声音、音乐、商品、图片
- `subject_id`
- `holder_name`
- `scope`
- `territory`
- `channels`
- `valid_from`
- `valid_until`
- `revoked_at`
- `evidence_asset_id`
- `verified_by`
- `verified_at`

用户可以覆盖模式推荐，不能覆盖权利硬门。视频改编权、达人肖像权、达人声音权和音乐权任一缺失时，相关真实模型调用必须阻断。结构改写仍需替换未授权的原声和音乐。

### 16.3 商品证据和状态失效

`product_presence` 的每个决定必须带 `product_evidence_json`，至少包含证据来源、时间范围、检测框、OCR/Logo 结果、SKU 匹配结果、模型版本和置信度。

商品状态、目标商品版本或 claim 发生变化时创建新的 shot graph revision，并使受影响的脚本版本、锚帧版本、声音版本和报价失效。已批准锚帧不能继续复用到新商品状态。

### 16.4 报价接受和预算上限

报价状态固定为：

```text
draft → pending_user_acceptance → accepted → expired → settled
```

报价必须包含币种、有效期、预览费用、正式渲染费用、人工审核费用、重做规则、最大金额和预算池。没有 `accepted` 状态不得触发真实付费任务。自动重试、供应商提交结果不明、用户返工和单帧重做必须分别记录计费原因。

### 16.5 状态机、迁移和并发

复刻项目状态固定为：

```text
draft → analyzing → analyzed → script_review → anchor_review
→ voice_ready → preview_ready → finalizing → completed
```

每个拒绝、取消、超时和失败状态都必须记录原因并支持从最近成功节点恢复。所有批准和生成写操作使用 `expected_version` 或等价乐观锁，所有提交任务使用 `idempotency_key`。

新表和约束沿用项目现有 `commercial_schema.py`、`init_db()` 和测试库注册方式。新增唯一键和索引必须进入增量 schema patch 和 `backend/tests/conftest.py`。

`cv_replication_projects.production_id` 为唯一外键，复刻项目与现有作品保持一对一关系。复刻项目保存路由和版本状态，`CvProduction` 保存最终作品引用，禁止两者分别维护当前脚本、锚帧和声音版本。

### 16.6 确定性媒体服务

在三个模型适配器之外，新增三个无模型服务：

- `FrameExtractor`：按时间点从私有源视频提取帧，生成不可变源帧资产。
- `AnchorSampler`：按镜头边界、运动变化、清晰度和商品证据选择 3、5 或 7 张锚帧。
- `TimelineCompiler`：管理镜头顺序、片段交接、字幕版本、声音时长和最终合成。

第一版 H3 调用按单镜头或连续短片段执行，每段使用 1～3 张锚帧。多图顺序探针通过后，才允许扩大到完整参考图包。

### 16.7 字幕和音频版本

新增 `cv_subtitle_versions`，记录：

- `script_version_id`
- `voice_render_id`
- 字幕文本和时间轴
- 字幕样式、安全区和语言
- `approved_by`
- `approved_at`

预览和正式导出必须引用同一字幕版本。最终 QA 检查字幕安全区、溢出、截断、音画同步和音频响度。

### 16.8 质量测量和放量

所有质量指标都必须绑定基准集、测量算法、分母、观察窗口和责任人。基准集至少包含同 SKU、同类目、跨类目和 15/30/60 秒组合，并分别记录结构改写和高保真结果。

高保真 feature flag 需要配置试点用户、预算上限、首轮通过率、返工率、发布率、成本异常和 kill switch。任一放量门失败时自动回滚到结构改写。

### 16.9 保留和隔离

源视频、源帧、替换锚帧、声纹、授权凭证和下载 URL 必须使用租户隔离、受控下载和访问审计。设计阶段明确每类资产的保留期限、删除流程、授权撤回后的失效行为和人工审核记录留存期限。
