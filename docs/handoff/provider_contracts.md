# Atlas 服务商契约记录（provider_contracts）

> 任务书 §8.1：能力核实先于字段编码。本文记录当前核实状态；**真实契约验证 BLOCKED**（无 API Key、无预算授权）。

## 1. 状态总览

| 端点 | 状态 | 依据 |
|---|---|---|
| Gemini 原生 `POST /v1beta/models/{model}:generateContent` | **DRAFT**（协议按 Gemini 公开规范实现，Atlas 侧待验证） | 任务书 [S11] Atlas LLM 协议文档（2026-11-10 公开页面） |
| 素材上传 `POST /api/v1/model/uploadMedia` | **未实现**（T05/T07 按真实端点接入） | [S15] |
| 视频报价 `POST /api/v1/model/calculate` | **DRAFT**（请求/响应解析已按公开文档实现，金额字段名 amount/total/cost 兼容解析） | [S12] |
| 视频提交 `POST /api/v1/model/generateVideo` | **DRAFT**（字段映射表见 §3，待真实响应校准） | [S13] |
| 任务查询 `GET /api/v1/model/prediction/{id}` | **DRAFT**（状态映射见 §4） | [S14] |

- Base URL：`https://api.atlascloud.ai`（COMMERCIAL 配置，已与 TokenFree 完全隔离，T01）
- 鉴权：Bearer Token（`atlas_api_key`，DB 加密存储，永不回传前端）
- 精确 model ID：**待管理员从 Atlas 控制台核实后填入**（`gemini_analysis_model_id` / `h3_developer_reference_model_id`），当前留空 → 付费路径被 `MODEL_CAPABILITY_UNVERIFIED` 阻断（T01 机制）

## 2. 已锁定的工程不变量（离线 Fixture 测试覆盖）

| 不变量 | 测试 | 结论 |
|---|---|---|
| Gemini 响应错误体/401/截断 JSON/时间越界/倒序 → 拒绝 | `test_gemini_contract.py` 7 项 | ✅ |
| 生成输入禁止原片字段（INV-01） | `test_source_video_fields_rejected` | ✅ 构造层拒绝 |
| 口播未绑定我方音色 → 拒绝 | `test_missing_voice_binding_rejected` | ✅ VOICE_BINDING_INVALID |
| 分辨率/画幅/时长不受支持 → 拒绝（不静默升降档） | `test_unsupported_resolution_rejected` 等 | ✅ |
| 上游错误体不得判成功（提交/查询/报价） | `test_error_*` | ✅ |
| 报价金额 Decimal 精度（$0.001 不丢） | `test_quote_decimal_precision` | ✅ |
| 成功但无输出 URL → OUTPUT_PENDING_DOWNLOAD 语义 | `test_success_without_output_is_pending_download` | ✅ |

## 3. H3 请求字段映射（DRAFT，待真实端点校准）

| 内部字段 | 上游键 | 说明 |
|---|---|---|
| model_id | model | 精确 Developer Reference ID 待控制台核实 |
| prompt / approved_dialogue | prompt / dialogue | 台词与画面描述分离 |
| resolution_id / aspect_ratio / duration_ms | resolution / aspect_ratio / duration_ms | 按能力档案校验 |
| actor_image_asset_ids / product_image_asset_ids / scene_image_asset_ids | subject_image_asset_ids / product_image_asset_ids / scene_image_asset_ids | 上传后句柄（uploadMedia 待接入） |
| voice_reference_asset_ids | voice_reference_asset_ids | 音色参考（字段名待真实 Schema 校准） |
| audio_required | audio_enabled | — |
| optional_seed | seed | 有则传 |

**草案能力档案**（`DRAFT_H3_CAPABILITIES`）：时长 [5s,10s] 步长 1s；分辨率 480p/720p/1080p；画幅 9:16/16:9/1:1；音频+音色参考=支持；`capability_verified=False`。**以上数值除 9:16/音频外的每一项都必须在真实联调时核实替换，不得当作已确认事实。**

## 4. 状态映射

| Atlas status | 内部状态 |
|---|---|
| succeeded/success/completed + output URL | succeeded（→下载） |
| succeeded 无 output | succeeded + 空输出（下载阶段处理 OUTPUT_PENDING_DOWNLOAD） |
| failed/error/canceled | failed |
| processing/其他非空 | running |
| 空/缺失 | queued |
| error 体（任意 status） | failed |

## 5. 待补清单（真实联调时）

1. 管理员提供 Atlas API Key + 两个精确 model ID（写入管理端配置）。
2. `uploadMedia` 真实请求/响应样本（图片/音频各自的大小、格式、保留期）→ 替换 DRAFT 映射。
3. 用 5～15 秒带对白视频验证 Gemini inline_data 视频输入真实可用（听得到对白、看得到动作）。
4. 用自有图片+音色+**不同新台词**验证 H3（先 `/calculate` 报价，再提交）。
5. 核实：报价字段名、折扣是否已含、任务保留期、取消语义、幂等支持。
6. 每项证据（脱敏请求/响应）回填本文并置 capability_verified（进入 `commercial_verified_models`）。

## 6. live 冒烟入口

`backend/tests/commercial/live/test_provider_smoke.py` —— 无 `ATLAS_API_KEY` + `COMMERCIAL_LIVE_TESTS=1` 时自动跳过，**不会产生任何付费调用**。
