# PRINTFILM 二次开发集成地图（integration_map）

> 基线提交：`26daa3fe9150dbba3a64c40b17b8c9bb93dbe08a`（main，2026-11-10 11:57:47 +0800）
> 审查分支：`feature/commercial-template-web`
> 本文档记录商业模板业务域（commercial）与底座的复用/改造关系，作为 T01～T10 的落点依据。

## 1. 底座关键机制摘要（源码核实）

### 1.1 任务平台（复用，不复制）

| 机制 | 位置 | 结论 |
|---|---|---|
| TaskRun 状态机与字段 | `backend/app/models_tasks.py` | 已有 `client_request_id`/`dedupe_key`/`provider_task_id`/`lease_token`/`lease_until`/`cancel_requested`/`billing_*`/`media_provider_tasks` 等字段；商业域直接复用 TaskRun，不另建任务表 |
| handler 注册表 | `backend/app/services/tasks/handlers.py` | `TASK_HANDLERS[(domain, task_type)]`；现有 kepu/drama/studio/tools 四域。**T07 落点：注册 `commercial` 域 7 个任务类型** |
| 调度器（租约） | `backend/app/services/tasks/scheduler.py` | DB 租约 10 分钟 + 10s 心跳续租；`recover_orphaned_tasks()` 把过期 leased/running 重新排队（`task.recovered` 事件）；inline 租约任务中断直接 failed（`inline_execution_interrupted`），**不会重发 POST** —— 与 INV-04 要求一致 |
| 轮询器 | `backend/app/services/tasks/poller.py` | `_select_and_poll_due` 只处理 `fragment_video` 与 studio `tool_video`；**`_poll_ephemeral_deferred_tasks` 会接管所有 domain 不在 `["drama","kepu"]` 的 `awaiting_poll` 任务并用 TokenFree 协议轮询（`studio_tools.poll_video_task`）**。⚠️ T07 必须把 `commercial` 显式排除并新增 Atlas 轮询分派，否则商业任务会被误送旧渠道 |
| 执行器 | `backend/app/services/tasks/executor.py` | `freeze_for_task` → `billing_scope` → handler → `settle_task`；`retry_download` 结果只重试下载不重新生成（下载中断保留上游任务号） |
| 上游任务号持久化模式 | `handlers.py` `_remember_provider_task`（drama asset_video） | 上游任务号一创建立即落库，重启后恢复只查询不重提交 —— 商业域 H3 提交沿用同一模式 |
| 队列容量 | `tasks/queues.py` + config `task_queue_*_concurrency` | text/image/video 三队列；商业域并发上限（任务书 0.2 默认 1/2/1）挂到新配置，不动全局默认 |

### 1.2 渠道锁定（T01 的三个真实改造点）

| 锁定点 | 位置 | 行为 | T01 改造 |
|---|---|---|---|
| 渠道常量 | `services/tokenfree_gateway.py` | `TOKENFREE_CHANNEL_ID="tokenfree"`，Base URL 硬编码 `https://www.tokenfree.com/v1`；`apply_tokenfree_flat_overlay()` 把 `openai_base_url`/`ark_base_url` 强制刷回 TokenFree、Key 非空时覆盖 `openai_api_key`/`ark_api_key` | Atlas 配置**独立命名空间**（`atlas_*` 字段），不进 SystemModelChannelRow，不被该 overlay 触碰 |
| 启动渠道归一 | `services/model_settings.py` `_ensure_tokenfree_channel()` | 每次启动把 base_url/api_format/enabled 强制写回，且**把所有非 tokenfree 渠道行 `enabled=False`** | Atlas 不作为渠道行存在，规避该逻辑；为防回归，新增测试证明 Atlas 配置在保存+重启后不被覆盖 |
| 管理端路由保存 | `services/model_settings.py` `patch_admin_routing_settings()` | 只接受 TokenFree 渠道，忽略其他渠道输入 | 商业域 Atlas 配置走独立的管理端设置接口，不改此函数 |
| overlay 流向 | `config.py` `get_settings()` + `schemas_settings.model_config_field_names()` | DB overlay 以 `model_copy(update=...)` 叠加到 env 之上；flat 只接受 `model_config_field_names()` 白名单字段 | T01 需在 `Settings` 与白名单中新增 `atlas_*`/`commercial_*` 字段才能入 overlay；`apply_tokenfree_flat_overlay` 仅写 `openai_*`/`ark_*`，与 `atlas_*` 无交集（需测试锁定） |

### 1.3 计费（复用平台、替换规则）

| 机制 | 位置 | 结论 |
|---|---|---|
| 钱包单位 | `users.balance_fen/frozen_fen`（分，int） | 底座钱包是人民币分；商业域 Atlas 费用按任务书 10.4 使用 **Decimal 原币账本（cv_usage_ledger，NUMERIC(20,8)）**，不复用 quota/500000 换算，也不把美元写进 fen 字段 |
| 预扣→用量→结算 | `services/billing/settlement.py`（freeze_for_task/settle_task）、`usage_events` | 商业域任务沿用 TaskRun billing 状态位（frozen/settled）作展示，金额真相源在 cv_usage_ledger；billing_snapshot 存报价快照引用 |
| TokenFree 价目 | `services/tokenfree_pricing.py` | 仅 TokenFree；Atlas 报价走 `/api/v1/model/calculate`（T03/T06 实测后落 `providers/atlas/pricing.py`） |
| 上游请求留痕 | `task_events` 的 `upstream.request.*` + `billing_scope` | 复用：H3/Gemini 真实请求脱敏后写同结构事件 |

### 1.4 数据与迁移方式

- ORM 按域拆文件（models.py / models_drama.py / models_tasks.py / models_settings.py…）→ 新增 `models_commercial.py`（cv_ 前缀表）。
- 无 Alembic：启动 `init_db()` create_all + `main._apply_schema_patches()` 增量 DDL（另有 `team_schema`/`media_schema`/`payment_schema` 模块化补丁可参照）→ 商业域新增 `app/commercial_schema.py`（或按仓库风格 `prepare_commercial_schema.py` 脚本）并挂进 `_apply_schema_patches`。
- conftest 会复用 `_apply_schema_patches`（权威清单），新表记得 import 进 conftest 注册。

### 1.5 静态与权限边界

- `main.py` 把 `backend/static` 整目录公开挂载 `/static`（StaticFiles 无鉴权）→ **商业域私有素材（原片、达人、音色、商品）不得放 `/static`**，放 `COMMERCIAL_STORAGE_ROOT`，经带权限校验的受控下载接口（T02）。
- 团队归属：TaskRun 已有 `team_id` FK；teams 域模型与 API 可复用做制作人/审核人角色挂载（T04+）。

## 2. commercial 域新增落点（对齐任务书 14.2）

```text
backend/app/models_commercial.py            # cv_* 表
backend/app/schemas_commercial.py
backend/app/api/commercial/                 # sources/templates/actors/products/productions/reviews/costs
backend/app/services/commercial/            # analysis/template_service/asset_policy/adaptation/planning/
                                            # prompt_compiler/generation/review_service/compose/budget_service/atlas_costs/handlers
backend/app/services/providers/atlas/       # client/capabilities/gemini/h3_reference/media/pricing
backend/tests/commercial/
frontend/src/features/commercial/
admin/src/features/commercial/
```

新任务类型（handlers 注册，domain="commercial"）：
`source_probe / source_analyze / template_adapt / video_generate / output_download / video_compose / billing_reconcile`

## 3. 明确不做

- 不改 `tokenfree_gateway.py` 的既有行为（旧业务继续走 TokenFree）。
- 不在 `pipeline.py`（约 2000 行）追加商业流程。
- 不复制调度器/轮询器；commercial 只注册 handler 与 poller 分派。
- 不引入第二套账号体系；复用 users/teams。

## 4. 风险登记（源码层面已确认）

| 风险 | 证据 | 缓解 |
|---|---|---|
| commercial awaiting_poll 被 ephemeral 轮询误接 | poller.py `_poll_ephemeral_deferred_tasks` 的 `domain.not_in(["drama","kepu"])` | T07 先写失败测试复现误送，再把 commercial 排除并加专属分派 |
| Atlas 配置被启动归一覆盖 | model_settings.py `_ensure_tokenfree_channel` 停用一切非 tokenfree 渠道行 | Atlas 不走渠道行 + 回归测试 `test_atlas_config_survives_save_and_restart` |
| overlay 白名单漏字段导致配置不生效 | `_refresh_overlay` 只收 `model_config_field_names()` | T01 同步改 Settings + schemas_settings，测试锁定 |
| `/static` 公开可读 | main.py 直接 mount | 商业私有素材独立存储 + 受控下载 |
| 任务重试可能重复提交上游 | scheduler 孤儿回收重新排队 pending | handler 幂等：提交前先查 `provider_task_id`，存在则走查询/下载路径 |
