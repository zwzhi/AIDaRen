# Codex 定向修复报告（P1-1～P1-8 + 相关 P2）

- 修复人：Codex（依据 docs/handoff/codex_review/review_report.md 与用户修复授权）
- 分支：`fix/codex-review-p1`（自审查基线 `98bf62b` 创建；未动 feature 分支）
- 提交序列（8 个，均小步可回溯）：

| SHA | 内容 |
|---|---|
| `0000b81` | P1-6 付费门禁三层接线（9 项新测试） |
| `584904e` | P1-4 调度生命周期打通（7 项生命周期测试） |
| `8b8e089` | P1-2/P1-5 幂等入账与预算生命周期（8 项测试 + 业务库核对清单） |
| `9535de1` | P1-8/P1-7/P1-3 新台词、音轨、严格覆盖（4+5 项测试） |
| `7d407f8` | P1-1/P2-5 前端能力档案驱动 + hooks 修复（1 项测试） |
| `4490791` | §八 平台级端到端集成测试（真实应用链） |
| `4d31c74` | 浏览器实测发现的两个缺陷修复（商品版本 ID + 多段字幕）+ 回归测试 |
| `06bccbe` | 测试基建稳定性（Fake Atlas 报价号唯一化） |

全程零真实付费调用：外部 HTTP 仅指向本地回环 Fake Atlas（uvicorn 随机端口）；
真实付费执行保持默认关闭；live 冒烟 2 项保持 skipped。

## 逐项：编号 → 根因 → 修改 → 证据

### P1-6 付费门禁（第一优先，§二）

- **根因**：`client.resolve_provider(require_verified=True)` 的完整保护在生产路径从未调用；
  API 门不检查付费总开关且模型 ID 全空时放行；`_build_unit_params`/`sources.analyze` 回落占位模型 ID。
- **修改**：`client.py`（require_verified 增加双模型角色必须配置）、`productions.py`
  `_require_mock_or_verified` 与 `sources.py` 解析门统一走 `resolve_provider(require_verified=True)`、
  `generation.py` 首次提交前重检门禁（排队期间配置降级不提交）、移除两处占位回落。
- **恢复区分**：已有上游任务号的查询/下载/对账不过新任务门（`generation.py` 恢复分支 +
  轮询路径显式不加门）。
- **首次验证入口**：`commercial_verified_models` 仍只能由管理员显式写入（保存密钥不自动开启，
  测试锁定 `test_saving_key_does_not_enable_paid_execution`）；未伪造任何"已验证"状态。
- **测试**：`tests/commercial/test_paid_gate.py` 9 项（修复前 5 失败）——付费开关关/模型ID缺失/
  未验证三种配置下 quote 全阻断且不触达上游；真实解析同门；handler 执行前重检（submit 替身
  断言不可达）；恢复路径不受门影响；无占位 ID；Mock 模式不受影响；配置保存语义。

### P1-4 真实模式调度生命周期（§三）

- **根因**：两处断链——(a) `generate_unit` 建任务 `next_action_at=None`，调度器只认领
  "非空且到期"的 pending 任务，永不认领；(b) handler 收到的是 executor 脱管 task 实例，
  对其属性赋值不持久化，且从不设置 awaiting_poll/next_action_at——任务卡 running→
  租约过期→孤儿回收→无限重跑，永不轮询。
- **修改**：`generation.py` 新增 `_transition_task_to_poll`（按 id 在当前会话重载任务行 →
  awaiting_poll + provider_task_id + next_action_at=退避到期 + 清租约），恢复与提交成功两处调用；
  `productions.py` 建任务 `next_action_at=now`。
- **测试**：`tests/commercial/test_platform_lifecycle.py` 7 项（修复前 3 失败）——
  executor 执行后任务行进入 awaiting_poll（含上游 ID/到期时间/清租约）→ 轮询 → 下载 → succeeded
  全链；**真实调度器 `_claim_queue` 认领链**；API 建任务带到期时间；重启恢复只查询不重提
  （prediction 调用数不增）；SUBMIT_UNKNOWN 冻结（重跑执行器不二次提交）；
  查询 429 退避（不判死不重建任务号）；下载失败仅重试下载（恢复后完成）。
  commercial 始终走 Atlas 分派（既有 test_task_recovery 锁定继续通过，旧业务平台抽样 99 项通过）。

### P1-2 + P1-5 幂等入账与预算生命周期（§四）

- **根因**：重放路径仍建新 TaskRun 并二次驱动轮询，poll 对 GENERATED 无短路 → 重复入账；
  `release_reservation`/`settle_reservation` 业务代码零调用 → 预留单行道；账本无事件级幂等。
- **修改**：
  - `productions.py`：重放复用原 TaskRun（崩溃窗口仅补建一个恢复任务；响应带 `task_replayed`）
  - `generation.py`：`poll_attempt` GENERATED 短路；未提交的失败/取消/门禁阻断/明确 HTTP 失败
    → 释放预留；SUBMIT_UNKNOWN（含 HTTP200 无 ID，P2-3）→ 冻结不释放；
    上游返回可核实费用（prediction `cost` 字段）→ `settle_reservation(实收)` + 账本行转 SETTLED；
    无费用信息 → SETTLEMENT_PENDING（估算金额，预留保留，不写 0）；Mock 确定性本地价生成即结算
  - `budget_service.py`：`record_usage` 事件键去重；settle/release FOR UPDATE + 幂等
    （重复结算通知不二次生效）；`approve_and_reserve` 并发唯一约束冲突回收为重放语义
  - `models_commercial.py` + `commercial_schema.py`（启动增量补丁）：`event_key` 列 +
    (attempt_ref, event_key) 唯一索引；历史行回填 `legacy.<id>`，金额/状态不动
- **测试**：`tests/commercial/test_budget_lifecycle.py` 8 项（修复前全失败）——重放同 attempt
  同任务且账本≤1 行；并发同 ID 恰一份 attempt/预留；未提交失败/取消释放；SUBMIT_UNKNOWN 保留；
  200 无 ID → SubmitOutcomeUnknownError；带费用结算（预留清零/settled=实收 $0.12/账本 SETTLED）；
  无费用保持 PENDING（估算 $0.10 不写 0）。
- **对账**：`artifacts/codex_fixes/recon_checklist.py`（只读）+ `recon_checklist.md`——
  业务库 13 条悬挂预留（mock 演示 $1.425，全部 attempt 已终态）、无重复/缺失账本行、
  池余额与明细一致。**未删除任何账目**，处置（如按 mock 语义批量结算或保留）待用户决定。
  refund/调整事件保留独立 event_key 空间（generation.settled / 后续 refund.*），
  未实现"一个 attempt 仅一条总账"式的粗暴限制。

### P1-3 完整成片严格校验（§六）

- **根因**：`_unit_coverage_error` 的"合格数≥单元数即放行"兼容回退可被同单元重做绕过。
- **修改**：`productions.py` 重写——(a) 覆盖以「用户明确选中的 attempt」的 unit_key 为准，
  逐一映射，无数量回退；历史 attempt 无 unit_key → 待处理阻断（不按数量猜全）；
  (b) 每条 selection 校验：属于本作品（P2-1，他人/他作品合格 attempt 不能凑数）+
  unit_key 匹配计划 + params_version 一致（旧参数版本不能冒充当前计划）；
  (c) 采用区间 vs 实际媒体时长 ffprobe 预检（P2-2，超界 422 不静默截短）。
- **测试**：`test_compose_rules.py` 新增 5 项反例（4 合格 attempt 全属 U001 → U002-U004 仍缺失；
  无 unit_key 历史数据阻断；他作品 attempt 拒绝；参数版本不一致拒绝；合法替代选中放行 master）
  + 原有 5 项继续通过。partial_preview 仍不可升级为 master（kind 由 complete 决定，原有测试锁定）。

### P1-8 新台词接线（§七）

- **根因**：前端台词输入仅用于离开提示，quote/generate 请求体无台词字段，服务端从
  plan_json 原样重建 → 重做=同参数新尝试，"参数变→旧批准失效"在台词维度不可达。
- **修改**：`QuoteBody`/`GenerateBody` 增 `dialogue_override` → 进入 `_build_unit_params`
  参数快照与报价指纹（台词变化=QUOTE_CHANGED）→ attempt.params_json → 字幕导出读取选中
  attempt 快照；前端 RedoEntry 真正发送覆盖台词。
- **测试**：`test_dialogue_and_audio.py`——两段明显不同台词（`清晨的第一杯水` /
  `温和不刺激敏感肌也能放心贴`）：新 attempt 快照=新台词、旧 attempt/旧导出不被覆盖、
  旧报价+新台词确认 → 409 QUOTE_CHANGED、新导出字幕=新台词而旧导出保持旧台词。
  字幕文本始终来自选中 attempt（改字幕文本不冒充视频说了新台词——字幕编辑仅作用于烧录层）。

### P1-7 音轨保留（§七）

- **根因**：`compose.py` 分段裁剪 `-an` 丢弃全部音频 → 拼接母版必然无声（审查已以归档
  产物 ffprobe 实证）；Mock 素材本身无声掩盖该问题。
- **修改**：分段统一重编码 H264+AAC 44.1k 立体声（aresample 对齐）；未要求口播且无音轨的
  片段用 anullsrc 补静音轨维持流一致；**audio_required 片段无音轨 → 422 AUDIO_MISSING
  （不填充静音冒充通过）**；全部无音轨且未要求 → 无声模板按计划合法；烧录 `-c:a copy`。
  Mock 生成片段自带 440Hz 正弦音轨（测试基建）。
- **测试与物证**：`test_dialogue_and_audio.py` 4 项（Mock 片段有音轨；母版含音轨且
  时长=采用区间±150ms；烧录版保留音轨；audio_required 无音轨 422；区间超界 422）。
  浏览器成片：`artifacts/codex_fixes/codex_fix_master_30s.mp4`（h264+aac，30.023s，
  mean -24.1dB 非静音）与 `codex_fix_subtitled_30s.mp4`。未调用任何付费 TTS/口型服务；
  旧无声验收文件保留并标记失效（见 errata）。

### P1-1 + P2-5 前端（§五）

- **根因**：前端硬编码 `resolution_id: '720p'`（能力档案已不含 720p）；
  `CreateProjectPage` 早返回位于大量 Hooks 之前（rules-of-hooks 28 errors）。
- **修改**：新增 `GET /api/commercial/capabilities`（档案视图，capability_verified=false
  显式标注）；工作台分辨率下拉完全由档案驱动（默认优先 768p 其次档案首档，无新增硬编码）；
  旧作品分辨率失效 → 页面明确提示重建/等待（服务端仍兜底 422）；DRAFT 提示常显
  （"不代表已具备真实能力"）；`CreateProjectPage` 拆分：无条件 `useSearchParams` 后早返回，
  其余 Hooks 全部下沉 `CreateProjectForm`（未禁用/忽略任何 lint 规则；旧入口引导与带参
  历史作品访问行为保持）。
- **测试与结果**：capabilities 端点测试 1 项；**前端 lint `0 errors`（39 warnings 上游存量）**
  · build ✓（多次）；浏览器实测分辨率下拉={2k,480p,768p} 默认 768p 无 720p（browser_walkthrough #5）。

### 浏览器实测新发现并修复（原审查未列）

1. 商品版本 ID 错配（P2 级）：下拉传版本号当 ID → 换商品命中第一个商品版本。
   修复 `list_products.latest_version_id` + 前端改传（4d31c74）。
2. 多 selection 字幕只出最后一段（P1-3 重构中间态引入）：字幕块移出循环。
   修复 + `test_multi_selection_subtitles_cover_every_selection`（4d31c74）。

## 测试命令与结果（当前分支 HEAD `06bccbe`）

| 命令（backend/ 下 venv） | 结果 | 退出码 |
|---|---|---|
| `pytest tests/commercial -q`（连跑三轮） | **151 passed, 2 skipped** ×3（修复前基线 115+2；新增 36 项） | 0 |
| `pytest tests/test_task_poller_dispatch.py test_task_scheduler_dispatch.py test_model_settings_overlay.py test_billing_settlement.py test_tokenfree_pricing.py test_task_executor_freeze_steps.py test_task_runtime_lifecycle.py -q` | **99 passed** | 0 |
| `cd frontend && npm run lint` | **39 warnings, 0 errors** | 0 |
| `cd frontend && npm run build` | ✓ built（~1s） | 0 |
| `pytest tests/commercial/test_platform_e2e.py -q`（单跑） | 1 passed | 0 |

失败解释：修复过程中间态的失败均已在对应提交内闭环；当前 HEAD 无已知失败。
skip=2 为 live 真实冒烟（无密钥自动跳过，零付费）。

隔离说明：商业域测试自动派生 `_test` 库；提交真实行的新测试文件自带按 marker 的
清理夹具；外部 HTTP 仅本地回环 Fake Atlas（`tests/commercial/fake_atlas.py`）；
下载地址映射垫片仅在测试内（生产 SSRF 策略原样，另有单测锁定）。

## 平台级集成与浏览器证据

- **离线全链**（`test_platform_e2e.py`，§八）：真实 HTTP 路由 → 报价（Fake Atlas
  /calculate + 台词覆盖）→ 生成排队（drive=false）→ **真实调度器认领执行** → 提交 →
  轮询（completed + 可核实费用 $0.14）→ 下载 → **结算（池 settled=实收/预留清零）** →
  账本 SETTLED → 人工审核 → FFmpeg 合成 → 字幕含覆盖台词 → 导出下载 → 母版带音轨且
  时长=采用区间。数据库/权限/预算/调度/审核/合成全部真实，仅最外层供应商为本地替身。
- **浏览器完整流程**：`artifacts/codex_fixes/browser_walkthrough.md`（15 步全记录 +
  成片 ffprobe/volumedetect 物证 + SRT 全文）。同一套参数口径：页面所选 768p 即请求参数
  （能力档案同源）；E2E 不再绕过页面另传值。
- **业务库核对清单**：`artifacts/codex_fixes/recon_checklist.md`（只读盘点）。

## P2 清单分类处置（原审查 12 项）

| P2 | 处置 |
|---|---|
| P2-1 compose attempt 归属 | ✅ 本轮修复（P1-3 批次） |
| P2-2 采用区间 vs 媒体时长 | ✅ 本轮修复（P1-7 批次） |
| P2-3 200 无 ID 判明确失败 | ✅ 本轮修复（SubmitOutcomeUnknownError → SUBMIT_UNKNOWN） |
| P2-4 审核空维度直通 | 未修（内部人工流程兜底；建议下轮：要求覆盖全部 8 维） |
| P2-5 CreateProjectPage hooks | ✅ 本轮修复（lint 0 errors） |
| P2-6 reserve_budget_atomic 无 scope | 未修（无生产调用方的死代码；建议下轮直接删除） |
| P2-7 变量清单硬编码 | 未修（待人工校准功能一并设计） |
| P2-8 30s 下限/mime 硬编码 | 未修（边界校验补充，联调前建议完成下限） |
| P2-9 人工校准无 UI | 未修（模板深度使用后再补） |
| P2-10 set_budget 可低于占用 | 未修（管理端输入校验，低风险） |
| P2-11 无手动版本选择入口 | 未修（体验项） |
| P2-12 数据目录在 app 包内 | 未修（部署项：生产配置显式绝对路径即可规避） |

## 剩余：只能授权后实测的事项（不变）

Atlas 密钥 + 两个精确 model ID → uploadMedia 真实样本 → Gemini 5–15s 带对白理解 →
H3 图片+音色+不同新台词（先报价）→ T1/C1/C2 真实闭环与费用对账。本轮新增接线后的
联调注意：prediction 响应若含 `cost.amount` 将自动结算（无则保持待结算）；
`commercial_paid_execution_enabled` 打开前所有真实提交仍被阻断（含排队中任务执行前重检）。

## 结论与边界

- 8 项 P1 全部修复并以失败先行测试闭环；相关 P2 四项同步修复；新增 36 项回归测试。
- 开发测试通过 ≠ 真实 API 验证通过 ≠ 商业成片质量通过 ≠ 生产就绪（区分声明不变）。
- 本轮授权范围：代码修复 + 离线开发测试 + 本地浏览器验证。未执行：真实付费调用、
  对外部署、生产迁移。等待独立复核与用户决定（含：13 条悬挂预留的处置、
  P1-3 修复分支合回 feature 的时机）。
