# AIDaRen 商业短视频模板化生产系统 · 独立审查报告

- 审查人：Codex（独立代码审查，非本轮开发方）
- 审查日期：2026-11-10
- 审查对象：`D:\AI Project\AIDaRen`，分支 `feature/commercial-template-web`
- **审查范围结论先行**：代码审查发现了 8 项 P1（其中 4 项已复现/有产物证据、4 项静态确认）与若干 P2。模拟主流程在 Mock 供应商下基本可操作且测试资产质量较高，但**存在一个当前即触发的浏览器端回归（P1-1）**，且**真实模式（调度器路径）存在任务永不完成的断链（P1-4）与付费防护门漏洞（P1-6）**。在修复清单完成前，不建议开始真实付费联调。底座本身可继续沿用，无需重写。

---

## 1. 审查范围、起止提交与工作区状态

| 项 | 值 |
|---|---|
| 起始快照 | HEAD=`98bf62b0b17440e3639eda3087c56e996d3f6f2e`，工作区干净（0 未提交/未跟踪） |
| 结束快照 | 同一提交；期间仅新增本审查文件（`docs/handoff/codex_review/`、`artifacts/codex_review/`），业务代码零改动（结束时 `git status` 复核） |
| 与报告线索比对 | 审查 HEAD 比阶段报告末尾提交 `fe1a4c8` 多 1 个提交（`98bf62b`，契约对齐轮）；`cb37d87`、`fe1a4c8` 均在历史中，未切换 |
| 上游基线 | `26daa3f`（与 baseline_audit 一致） |

**未覆盖范围与限制**：
1. 《PRINTFILM_Web_ZCode_开发任务书_V1.0.md》**不在仓库中**（全仓搜索未命中）。需求以用户审查指令 + handoff 文档交叉重建，任务书原文条款号无法逐条核对。
2. 真实 Atlas/Gemini/H3 调用一律未执行（2 项 live 测试保持 skipped）；模型效果、真实费用、供应商契约语义均为"待验证"，本报告不将其计为代码缺陷。
3. 后端全量 ~2200 项测试未整体重跑（基线已有干净全量日志 `pytest_run2_clean.txt`）；以商业域全量 + 依赖路径抽样 + 基线失败文件抽查替代。
4. 浏览器端未起服务实操；以代码链路审查 + 既有归档截图/产物（`artifacts/acceptance/`）+ 隔离复现脚本为证据。720p 回归已由"静态代码 + 脚本复现"闭环。

## 2. 当前真实架构与业务调用链（源码核实）

```
浏览器（frontend/src/features/commercial/{api.ts,pages.tsx}，六页面 + ?production=N 状态恢复）
 → REST /api/commercial/*（backend/app/api/commercial/{sources,productions}.py，23 路由）
 → 权限：登录可读；写操作 _ensure_writer（创建者/管理员）；素材下载 ensure_asset_readable（上传者/团队/管理员，404 语义）
 → 服务层 services/commercial/*：analysis（缓存键六要素）→ template_service（版本不可变+expected_version）
   → adaptation（只吃模板文本+商品资料）→ planning（三时长分离/能力档案驱动/台词不截断）
   → budget_service（报价指纹→批准→FOR UPDATE 条件预留）→ generation_request（报价与生成同一构造器）
   → generation（提交/恢复/轮询/下载；SUBMIT_UNKNOWN 冻结）→ review_service（八维/阻断项/只追加）
   → compose（FFmpeg 只剪不生成/母版不可变/烧录独立副本）
 → 数据：cv_* 13 张表（Decimal NUMERIC(20,8) 账本，与底座 fen 钱包隔离）
 → 任务平台：TaskRun(domain=commercial) 注册于 handlers.py:406；poller 专属 Atlas 分派（poller.py:201-204），
   ephemeral 兜底已排除 commercial（poller.py:237）
 → Mock 供应商（mock_provider.py，本地 FFmpeg testsrc，零网络）；真实适配器 providers/atlas/*
   （gemini inline_data 真实视频字节构造；H3 显式字段映射+能力校验；SSRF 防护下载）
 → 渠道隔离：atlas_* 独立配置命名空间，不受 TokenFree overlay/启动归一影响（测试锁定）
```

Mock 模式下 `generate` 请求内联驱动（真实 handler + 真实轮询函数）；真实模式交调度器——**该路径存在断链，见 P1-4**。

## 3. 需求覆盖表

| # | 需求 | 实现位置 | 测试证据 | 状态 |
|---|---|---|---|---|
| 1 | 上传 30s–3min 参考视频 | `api/commercial/sources.py:51`（私有存储+ffprobe/Pillow 真实探测+500MB 上限） | test_media_security 等 | **部分**：180s 上限有，**30s 下限未校验** |
| 2 | Gemini 分析画面与声音 | `providers/atlas/gemini.py`（inline_data 视频字节+系统指令+Schema 校验，时长以后端探测为准） | test_gemini_contract 7 项 | **部分**：适配器工程完成；真实契约 DRAFT 待联调；声音理解（音轨）未单独验证 |
| 3 | 结构化分镜/动作/台词节奏/关键帧/可替换变量 | `analysis.py`+`schemas_commercial.AnalysisResult`（时间轴校验/倒序拒绝） | test_analysis_and_templates | **部分**：分镜/关键帧 ✓；**可替换变量硬编码 3 个**（productions.py:118，P2-7） |
| 4 | 人工校准并发布版本化模板 | `template_service.py`（版本不可变+冲突检测）；前端模板库页 | test_analysis_and_templates | **部分**：版本化 ✓；**人工校准无编辑 UI**（解析结果一键发布，P2-9） |
| 5 | 用模板创建任务，选达人/音色/商品/文案 | `productions.py:294`（绑定校验 validate_voice_binding） | test_asset_binding | ✅（Mock 口径） |
| 6 | H3 Reference-to-Video 生成 | `h3_reference.py`（显式字段映射、音色/图片/台词入请求体、能力校验、INV-01 兜底） | test_h3_contract 14 项 | **部分**：构造层完成；真实端点 DRAFT |
| 7 | 逐镜审核；单镜重做 | `review_service.py`（阻断项不抵消）；`productions.py:613` 审核、RedoEntry 重做 | test_review_and_compose | **部分**：审核 ✓；**重做的"改台词"未接线**（P1-8） |
| 8 | 字幕校对、合成、下载 | `compose.py`+`productions.py:673/776/811`（SRT 草稿/烧录副本/双下载） | test_compose_rules | **部分**：流程 ✓；**成片无音轨**（P1-7）；完整成片覆盖校验可绕过（P1-3） |
| 9 | 同模板换第二套素材复用，不重解析 | E2E `test_e2e_mock_flow`（断言无新解析任务、生成参数无原片资产） | ✅ | ✅（Mock 口径） |
| 10 | 底线：原片禁入生成 | 构造层 INV-01 + 策略层血缘/同哈希洗白拦截（asset_policy.py:95） | test_no_source_reuse | ✅ |
| 11 | 底线：达人与音色正确绑定 | `actors.py`（归属/撤销/过期/跨达人显式批准） | test_asset_binding | ✅ |
| 12 | 底线：商品卖点适配 | `adaptation.py`（只吃审核卖点；新事实标记待审；形态动作不适配明示） | test_plan_compiler | ✅（Mock 口径） |
| 13 | 底线：不跳过不合格必需镜头伪装成片 | `productions.py:647` `_unit_coverage_error` | test_compose_rules（仅覆盖数量不足场景） | **部分**：**兼容回退可绕过**（P1-3，已复现） |
| 14 | 底线：真实成本可追踪 | `budget_service.py`+`cv_usage_ledger`（Decimal 原币；mock/real 池隔离） | test_quote_and_budget | **部分**：**重放重复记账（P1-2）+ 预留只进不出（P1-5）使账实失真** |
| 15 | 模板真正复用（非复制项目） | 版本化 + production 引用 version_id + 缓存键隔离 | test_analysis_and_templates | ✅ |
| 16 | 付费防护（未验证不调用） | `client.py:73` resolve_provider(require_verified) | test_provider_routing（仅测试内调用） | **部分**：**生产路径从未以 require_verified=True 调用，且 API 门有空模型 ID 放行漏洞**（P1-6） |

## 4. 问题清单（按严重程度）

> 等级定义：P0=未授权支出/严重越权/数据破坏；P1=阻断核心流程/重复付费风险/错误成片/无法恢复；P2=不阻断核心流程。
> 证据状态三类：已复现 / 静态确认 / 待验证假设。本轮 **未发现 P0**（当前默认配置 commercial_enabled=false、key 空、mock=true，真实付费路径默认关闭且不可达）。

### P1-1【已复现】前端硬编码 720p 与新能力档案冲突：浏览器新建作品无法报价（当前回归）

- 证据状态：已复现（repro R2）
- 代码：`frontend/src/features/commercial/pages.tsx:319`（`resolution_id: '720p'`）；`backend/app/services/providers/atlas/h3_reference.py:45-54`（能力档案 {480p,768p,2k}）；校验在 `h3_reference.py:76`（PROVIDER_RESOLUTION_UNSUPPORTED）
- 触发：HEAD 提交 `98bf62b` 将后端默认改为 768p 并更新能力档案，但前端未同步。浏览器"制作工作台 → 创建作品 → 报价"第一步即 422。
- 预期/实际：E2E 测试用 `768p`（test_e2e_mock_flow.py）所以 115 项全过，但**页面真实操作必然失败**。Phase2/3 的浏览器验收基于旧能力档案（当时含 720p），在 HEAD 上已不成立。
- 影响：浏览器端主流程在当前提交不可用。
- 归属：本轮回归（98bf62b 引入）。
- 最小修复：pages.tsx:319 改为 `768p`（或改为从 `/plan` 返回的 capabilities 动态选择）。
- 回归测试：前端构建产物断言 + 一条 API 集成测试锁定"前端使用的分辨率 ∈ 能力档案"。

### P1-2【已复现】幂等重放触发的二次轮询重复写费用账本

- 证据状态：已复现（repro R1：同一 attempt 轮询两次，账本 1→2 行）
- 代码链：`api/commercial/productions.py:500-546`（`approve_and_reserve` 返回 `idempotent_replay=True` 时**仍无条件新建 TaskRun 并驱动轮询**）→ `services/commercial/generation.py:151-177`（`poll_attempt` 的 MOCK 分支与真实成功分支均无 `GENERATED` 短路）→ `_record_pending_usage` 每次追加 `SETTLEMENT_PENDING` 行
- 触发：双击/刷新重放（同 client_request_id）即可；E2E 只断言 attempt_id 与 replay 标志，未断言账本行数，故测试不报。
- 预期：重放返回原 attempt，不再产生第二行费用、不重复下载。实际：每次重放追加一条费用行（作品费用页 total/pending 虚增）；真实模式下还会重复进入下载阶段。
- 影响：费用可追踪性失真（业务底线 14）；演示池下也能观察到金额翻倍。
- 归属：本轮实现缺陷。
- 最小修复：`poll_attempt` 开头对 `attempt.status == "GENERATED"` 直接返回；或 `generate_unit` 对 replay 不再建 TaskRun/不驱动。
- 回归测试：E2E 重放后断言 `cv_usage_ledger` 恰好 1 行/attempt。

### P1-3【已复现】完整成片"必需单元覆盖"校验存在数量回退绕过

- 证据状态：已复现（repro R3：4 单元中 U002–U004 无合格版本，`_unit_coverage_error` 返回 None 放行）
- 代码：`api/commercial/productions.py:647-670`——`if missing and len(attempts) < len(units): return missing`；当合格 attempt 数 ≥ 单元数（例如 U001 重做 4 次）时缺失单元不阻断。注释声称"早期 attempt 无 unit_key 的兼容回退"，但条件与 unit_key 有无无关。
- 触发：直接 POST `/compose {complete:true}`（前端有自检，但服务端必须兜底）。
- 预期：任一必需单元无 REVIEW_APPROVED 版本即 422。实际：可导出缺失必需镜头的 kind=master 成片。
- 影响：违反"不允许跳过不合格必需镜头伪装完整成片"底线（Phase3 修复声明只覆盖数量不足场景）。
- 归属：本轮实现缺陷（修复不完整）。
- 最小修复：删除数量回退；仅当 attempt 确实无 unit_key（历史数据）才回退数量比较。
- 回归测试：`test_complete_compose_blocked_when_required_unit_unapproved` 增加"同单元多次重做使总数达标"的反例。

### P1-4【静态确认】真实模式调度路径：任务提交后永不进入轮询、永不完成（断链）

- 证据状态：静态确认（Mock 内联路径掩盖；需平台路径运行才能动态复现，本轮未起服务）
- 代码链：`services/tasks/executor.py:98-105`（读事务关闭后把**脱管** task 传给 handler）→ `services/tasks/handlers.py:369`（handler 用自己的新 session）→ `services/commercial/generation.py:56-60/135-140`（`execute_generation_task` 从不设置 `task.status="awaiting_poll"`、从不设置 `next_action_at`；对脱管对象的 `task.provider_task_id=` 赋值不会随 `db.commit()` 持久化）→ `executor.py:115-117`（见到 awaiting_poll 结果仅 commit 返回）→ `poller.py:134-148`（`_select_and_poll_due` 只选 `status=="awaiting_poll" 且 next_action_at 非空`的任务）
- 对照：drama 域正确模式在 `services/drama/jobs.py:1358-1361`（自身 session 重载 task 行 + 置 awaiting_poll + next_action_at + 清租约）。
- 后果（真实模式）：任务行停在 `running` → 10 分钟租约过期 → 孤儿回收重新 pending → 再执行恢复路径（只返回 awaiting_poll）→ **无限循环**；上游任务号只在 attempt 上，任务永不 succeeded、永不结算。Mock 模式之所以可用，是因为 `productions.py:530-546` 内联驱动时由 API 层手动设置状态。
- 影响：真实联调的核心执行链不可用；这也是"115 项测试全过"未覆盖的盲区（测试全部走内联/direct 调用）。
- 归属：本轮实现缺陷（T07 恢复语义只测了函数层，未测 executor 接线）。
- 最小修复：handler 内 `db.get(TaskRun, task.id)` 重载后设置 `status="awaiting_poll"`+`next_action_at=now+间隔`+清租约并提交（对齐 drama 模式）。
- 回归测试：走 `executor.execute_leased_task`（或等价平台入口）的集成测试，断言任务行进入 awaiting_poll 且被 `_select_and_poll_due` 选中。

### P1-5【静态确认】预算预留"单行道"：失败/取消/重放永不释放，成功也永不结算

- 证据状态：静态确认（grep 全仓：`release_reservation`、`settle_reservation` 在业务代码零调用；`execute_generation_task` 取消分支注释写"释放预留"但无调用，`generation.py:45-49`）
- 影响：`pool.reserved_amount` 只增不减——失败、取消、SUBMIT_UNKNOWN、报价过期的预留全部永久占用；生成成功也只写 `SETTLEMENT_PENDING` 账本行而不把预留转 `settled`。可用额度单调下降直至全部新报价 BUDGET_EXCEEDED；真实联调时表现为"没花钱但预算没了"，且账本/池两个口径无法对账。
- 归属：本轮实现缺陷（结算语义有函数无接线）。
- 最小修复：失败/取消路径调 `release_reservation`；生成终态（GENERATED/failed）后调 `settle_reservation`（金额先用报价快照，真实账单对账后调整）；`reserve_budget_atomic`（无 scope 过滤，P2-6）删除或补 scope。
- 回归测试：失败任务后断言池 reserved 回落；成功后 reserved→settled。

### P1-6【静态确认】付费防护门三处漏洞叠加：`require_verified=True` 生产路径从未调用 + API 门不查付费总开关 + 模型 ID 全空时放行

- 证据状态：静态确认（grep：`require_verified=True` 仅出现在测试）
- 代码：
  1. `providers/atlas/client.py:73-108` 完整实现了"付费开关+已验证清单"双检，但 `handlers.py:364` 与 `generation.py:309` 均以默认 `require_verified=False` 调用；
  2. `productions.py:75-87` `_require_mock_or_verified` 不检查 `commercial_paid_execution_enabled`，且 `models` 集合为空（两个 model ID 都留空）时直接放行；
  3. `sources.py:213-217`（解析）同样只查 key+enabled；`sources.py:204` 与 `productions.py:412` 在 ID 为空时分别回落占位符 `"gemini-3-flash-preview"`、`"minimax-h3-developer-reference"`。
- 触发：管理员配置了密钥、打开 commercial_enabled（联调时的常见状态），模型 ID 留空、未开付费开关 → quote/generate/analyze 全部放行，以**猜造的模型 ID**发出真实付费请求。
- 预期：与文档反复声明的"留空=付费自动阻断、未验证禁止调用"一致。实际：留空反而绕过。
- 影响：未验证即付费风险（接近 P0，因需要管理员先配密钥+开开关，判 P1）；另注意"必须调用才能验证、未验证禁止调用"的死锁设计问题：`commercial_verified_models` 清单目前无任何写入入口（只能改库/接口直改），联调时需要明确的人工置位流程（live_integration_prep 已列，但代码无入口）。
- 归属：本轮实现缺陷（防护有设计、未接线）。
- 最小修复：`execute_generation_task` 提交前与三个 API 门统一改用 `resolve_provider_for_commercial_task(require_verified=True)`；模型 ID 为空直接拒绝（去掉占位符回落）。
- 回归测试：`enabled+key+空ID`、`enabled+key+ID未验证`、`付费开关关` 三种配置下 quote/generate/analyze 均拒绝。

### P1-7【已复现（归档产物）】合成成片无音轨——"有声视频"业务在成片环节丢声

- 证据状态：已复现于归档产物（ffprobe：`artifacts/acceptance/export-4-master-30s.mp4` 与 `export-4-subtitled-30s.mp4` 均只有 1 路 h264 视频流，无音频流）
- 代码：`services/commercial/compose.py:99-104`——分段裁剪命令含 **`-an`**（丢弃音轨），随后 concat `-c copy` 得到的母版必然无声；`burn_subtitles` 的 `-c:a copy` 也无音频可拷。
- 预期：H3 生成 `audio_required=True` 且绑定授权音色，成片应保留台词声音。实际：整条合成链路产物无声。Mock 素材本身是 testsrc（无声），掩盖了该问题；真实联调时会产出台词听不见的成片，且字幕审核口径（口播对齐）全部失真。
- 影响：核心交付物（有声带货成片）不可用；Phase2/3/4 的"成片验收"实际验收的是无声视频。
- 归属：本轮实现缺陷。
- 最小修复：分段裁剪保留音频（如 `-c:v libx264 -c:a aac`，必要时统一采样率/声道以保 concat 一致）；Mock 素材改为带正弦音轨（`sine=` 源）以便回归可听。
- 回归测试：compose 后 ffprobe 断言母版含音频流且时长=采用区间之和。

### P1-8【静态确认+归档佐证】单镜重做的"改台词"未接线：新尝试沿用原台词

- 证据状态：静态确认 + 归档佐证（`export-4-snapshot.json` 中 4 段字幕文本完全相同，含重做单元 U003 的第 2 次尝试 #12；Phase3 报告声称的"改台词重做"在产物中无体现）
- 代码：前端 `pages.tsx:219-267` RedoEntry 的台词输入只用于 beforeunload 守卫；`api.ts` quote/generate 请求体无台词字段；服务端 `productions.py:408-430` `_build_unit_params` 从 `plan_json` 重建参数（台词不变）；`locked_dialogue` 只能建作品时设置，计划后无修改入口。
- 影响："参数变→旧批准失效（QUOTE_CHANGED）"在台词维度不可达；重做=同参数新尝试（新预算、同样结果）；与 Phase3 §2"单镜重新生成：改台词→新报价（参数变→旧批准失效）"的声明不符。
- 归属：本轮实现缺陷（报告声明与实现不符）。
- 最小修复：quote/generate 增加可选 `dialogue_override`（进参数快照与指纹，改动即 QUOTE_CHANGED），或提供计划台词编辑端点并联动失效旧报价。
- 回归测试：改台词重做后断言新 attempt 的 `params_json.approved_dialogue` 为新台词、旧 quote 确认时报 QUOTE_CHANGED。

### P2 清单（不阻断核心流程）

| # | 问题 | 证据 | 位置 | 建议 |
|---|---|---|---|---|
| P2-1 | compose 不校验 selections 的 attempt 归属/作品绑定（可拼接他人或其他作品的已审核片段；仅查状态） | 静态确认 | `productions.py:693-698`（无 `attempt.production_id==production.id`/`_ensure_writer(attempt)`） | 补归属校验 |
| P2-2 | 采用区间不与实际媒体时长校验；超长区间被 ffmpeg 静默截短而 `total_adopt_ms` 按请求值累计 | 静态确认 | `compose.py:93-112` | compose 前 ffprobe 实际时长并 422 超界区间 |
| P2-3 | 提交 HTTP 200 但无任务 ID 被判"明确失败"（PROVIDER_FAILED），语义应为 SUBMIT_UNKNOWN（上游可能已建任务，重做=双付费风险） | 静态确认 | `h3_reference.py:200-202` 与 `generation.py:127-133` | 该分支改置 SUBMIT_UNKNOWN 冻结 |
| P2-4 | 审核空维度 dict 直接过审（overall=APPROVED）；非阻断维度 FAIL 不影响结论；维度名不校验 | 静态确认 | `review_service.py:50-63` | 要求覆盖全部 8 维且维度名合法 |
| P2-5 | 前端 lint 28 errors（hooks 条件调用；`CreateProjectPage.tsx` 早返回在 hooks 之前，cb37d87 引入）——**与 Phase3/4/dev_baseline"lint 0 errors"声明矛盾**；且存在 params 0↔非0 切换时 hooks 数量变化导致 React 崩溃的潜在路径 | 已复现（lint 输出全部指向该文件） | `frontend/src/pages/studio/CreateProjectPage.tsx:27-30` | OldEntryGuide 拆为独立路由/包装组件 |
| P2-6 | `reserve_budget_atomic` 原子预留无 scope 过滤（`WHERE name=:pname` 会同时命中 mock/real 池）；当前无生产调用方（死代码隐患） | 静态确认 | `budget_service.py:182-205` | 删除或补 scope 并接线 |
| P2-7 | 模板"可替换变量"硬编码 3 个，非解析产物 | 静态确认 | `productions.py:116-119` | 从解析/校准结果生成 |
| P2-8 | 参考视频无 30s 下限校验；音频探测 mime 硬编码 audio/mpeg（wav/flac 误标）；`probe_media_bytes(role_is_video)` 参数未用 | 静态确认 | `sources.py:73-79`、`storage.py:147-155` | 补下限与真实 mime |
| P2-9 | "人工校准分镜"无编辑 UI（解析结果直接发布 V1） | 静态确认 | `pages.tsx:67-73` | 增加分镜校准编辑步骤 |
| P2-10 | set_budget 可将总额改到低于已占用（reserved>total 无校验）；且无 GET 预算接口（页面保存后才能看） | 静态确认 | `productions.py:840-856` | 下调校验 + 查询接口 |
| P2-11 | 无手动选择旧合格版本的入口（合成自动取最新合格） | 静态确认 | `pages.tsx:464-479` | 版本选择下拉 |
| P2-12 | 商业数据目录默认在 `backend/app/data/commercial`（应用包内，部署打包易被覆盖；备份文档已单独演练） | 静态确认 | `storage.py:21,42-48` | 部署配置显式绝对路径 |

**未发现某类问题的明确声明**：未发现越权读取私有素材的路径（下载/元数据 404 语义 + 团队归属校验齐全）；未发现密钥明文泄漏（Fernet 加密、masked 视图、日志脱敏声明与实现一致，test_secret_recovery 锁定错钥降级不破坏密文）；未发现开放重定向（safeNextPath 拦截 `//`、`://`）；未发现 SSRF 防护缺失（HTTPS-only、DNS 全解析校验、逐跳重定向校验）；未发现 mock 缓存错误命中真实任务（mock/real 预算池隔离有测试锁定；解析缓存键含 team+sha+model+prompt+schema）；未发现商业任务进入 TokenFree 兜底轮询（poller 排除 + 专属分派，测试锁定）；未发现模板发布后被原地修改（版本表不可变 + expected_version 冲突）；未发现跨请求/重启数据丢失（审核、导出、任务状态均落库；Phase3 重启演练与 E2E 断言一致）。

## 5. 实际运行的测试（命令、环境、结果）

详见 `artifacts/codex_review/test_logs.md`。摘要：

| 命令 | 结果 | 说明 |
|---|---|---|
| `pytest tests/commercial -q`（backend venv，printfilm_test 隔离库） | **115 passed, 2 skipped**（17.19s） | 与 HEAD 提交声明一致；skip=live（无密钥自动跳过，零付费） |
| `pytest tests/test_task_poller_dispatch.py tests/test_task_scheduler_dispatch.py tests/test_model_settings_overlay.py tests/test_billing_settlement.py tests/test_tokenfree_pricing.py -q` | **45 passed**（2.89s） | 商业域实际依赖的平台/计费/overlay 路径 |
| `pytest tests/test_seedream_size_pro_cap.py tests/test_team_schema_cli.py tests/test_unified_wallet_ai.py -q` | 3 failed, 22 passed | 失败项与上游基线 18 项清单一致（单跑时 unified_wallet 通过，疑似全量下的顺序依赖，未深究）→ 上游失败非本轮回归 |
| `frontend: npm run lint` | **39 warnings + 28 errors** | 28 errors 全部在 CreateProjectPage.tsx（P2-5，与各阶段报告"lint 0 errors"矛盾） |
| `frontend: npm run build` | ✓ 1.01s | 通过 |
| 复现脚本 `artifacts/codex_review/repro_checks.py`（隔离库+自清理） | R1/R2/R3 全部复现 | P1-2、P1-1、P1-3 的动态证据 |
| ffprobe 归档成片 ×2 | 均无音轨 | P1-7 证据 |

上游 18 项失败与商业域的关系判定：失败集中在 marketplace/资产元数据/字幕开关/尺寸/团队 schema CLI/钱包——**均不在商业域 import 或调用路径上**；商业域依赖的任务平台/计费结算/overlay 抽样全过。**阻塞等级：不阻塞商业域**。

## 6. 报告声称完成但尚缺证据/与实际不符的项目

| 声明（出处） | 实际 |
|---|---|
| "前端 lint 0 errors"（Phase3 §5、Phase4 §六、dev_baseline §健康回归、98bf62b 提交信息） | **28 errors**（cb37d87 已引入，Phase4 自己的提交就含此问题；"lint 通过"口径失实） |
| "留空=付费自动阻断"（Phase2 §4、T00-T09 §5、provider_contracts §1） | 两个 model ID 均留空时门**放行**且回落占位符模型 ID（P1-6） |
| "单镜重新生成：改台词→新报价（参数变→旧批准失效）"（Phase3 §2） | 台词编辑未接线，新尝试参数不变（P1-8；归档字幕四段同文佐证） |
| "必需单元缺合格版本→完整成片 422 阻断"（Phase3 §1 修复表） | 仅数量不足场景成立，数量回退可绕过（P1-3 已复现） |
| "FFmpeg 合成 12s/16s/30s 成片+字幕→验收"（Phase2/3/4） | 成片**无声**（P1-7），验收口径未覆盖音频 |
| "T07 执行恢复 ✅工程完成（J02–J06 语义）"（T00-T09 §1） | 函数层语义有测试；**executor 接线断链**（P1-4），平台路径无法完成生命周期 |
| "export-4-snapshot.json 含 plan_units/selections"（Phase4 §5.1） | 属实（核对通过） |
| "商业域 111→115 passed 演进"（各阶段） | 属实（115+2 复核通过） |
| "poller 误送修复 + 专属分派"（T07/Phase2） | 属实（poller.py:201-204,237 + test_task_recovery 锁定） |
| "备份恢复演练、密钥恢复语义"（Phase3 §5、Phase4 §5.2） | 文档与测试在库；本轮未重演练（引用其归档 README 与 test_secret_recovery 通过） |

## 7. 真实付费联调前必须处理（按优先级）

1. **P1-6 付费门接线**：require_verified=True 进提交路径、空模型 ID 拒绝、API 门补付费开关检查——否则联调配置阶段就可能以占位模型 ID 产生真实支出。
2. **P1-4 调度路径断链**：真实模式的任务生命周期走不通，联调第一步（H3 提交→轮询→下载）就会卡死。
3. **P1-5 预算结算/释放接线**：真实费用发生前必须能正确预留→结算→释放，否则预算对账不可信。
4. **P1-2 重放重复记账**：联调会反复点同一请求，账本必须幂等。
5. **P1-7 成片音轨**：联调验收以"听得到台词"为准，先修 `-an`；同时把 Mock 素材改为带音轨，让开发环境能暴露此类问题。
6. **P1-3 覆盖校验回退**：真实审核流程中不允许缺失镜头的完整成片。
7. **P1-1 720p 回归**：恢复浏览器端可操作性（联调操作都从页面走）。
8. 联调流程配套：`commercial_verified_models` 需要明确的管理端置位入口（当前只能改库）；`commercial_paid_execution_enabled` 与 real 预算池初始化顺序写入联调 runbook（live_integration_prep 已列项，补操作入口）。

## 8. 可以后续再处理、不阻塞当前推进

- P2-1/P2-2（compose 归属与区间校验——共享工作区+内部工具下风险可控，真实联调前修亦可）
- P2-4（审核维度完整性——内部人工流程兜底）
- P2-5 lint errors（功能影响有限，但应尽快修以恢复"lint 通过"的验收口径）
- P2-7/P2-9（变量硬编码、校准 UI——模板深度使用后再补）
- P2-8/P2-10/P2-11/P2-12（边界与体验）
- 模型效果、供应商契约字段（uploadMedia 样本、报价字段名、任务保留期、取消/幂等语义、5–15s/分辨率档位核实）——**只能留待授权后实测**，代码已如实标注 DRAFT/capability_verified=False，未冒充。

## 9. 建议的最小修复顺序（供 zCode/Codex 任一方执行）

```
第 1 批（恢复"浏览器可操作 + 防误付费"，半天量级）：
  P1-1 前端 720p→768p
  P1-6 付费门接线（require_verified=True + 空 ID 拒绝 + API 门补开关检查）
第 2 批（真实模式生命周期，1 天量级）：
  P1-4 handler 重载 task 行并置 awaiting_poll/next_action_at/清租约（对齐 drama 模式）+ executor 级集成测试
  P1-2 poll_attempt GENERATED 短路（或 replay 不建新任务）
第 3 批（账务正确性）：
  P1-5 失败/取消 release、成功 settle（金额先用报价快照）
  P2-6 删除/修复 reserve_budget_atomic
第 4 批（成片质量与完整性）：
  P1-7 合成保留音轨 + Mock 素材带音轨
  P1-3 覆盖校验去数量回退
  P1-8 重做台词接线（dialogue_override 进指纹）
第 5 批：P2 清单按需
```

## 10. 最终结论（四问）

**Q1 这是完整可操作的开发版，还是仍有关键占位/断链？**
模拟供应商口径下，后端链路与六个页面基本完整可操作（存在 P1-1 当前回归，修复前浏览器端报价即失败）；但**真实模式调度路径存在断链（P1-4）**，成片环节丢音轨（P1-7），重做台词为占位（P1-8）。结论：**接近完整开发版，但有明确断链点，非"完成"**。

**Q2 是否适合开始"有预算限制的真实 API 联调"？**
**暂不适合。** 第 7 节 1–5 项完成前，联调要么花不出钱（任务卡死），要么可能花错钱（防护门漏洞/占位模型 ID），要么账对不上（预留单行道/重复记账）。这些全部是小时级/天级可修的集成问题，不是架构问题。

**Q3 进入真实联调前必须修哪些？**
第 7 节清单 1–8（P1-1～P1-7 + 置位入口配套），其中 1/2 为硬前置，3/4/5 强烈建议同批完成。

**Q4 哪些属于模型效果或供应商契约，只能留待授权后实测？**
Gemini 对 5–15s 带对白视频的真实理解效果；H3 对图片+音色+新台词的真实生成质量；uploadMedia/calculate/generateVideo/prediction 的真实字段、错误体、保留期、取消与幂等语义；能力档案数值（时长档/分辨率/价格）；真实费用与报价的差额对账。代码对这些均保持 DRAFT/未验证标注，未发现把 Fixture 假设冒充真实能力的情形。

**Q5 能否继续基于当前底座推进，而不做不必要的重写？**
**可以。** 领域建模（cv_* 13 表、版本化模板、attempt 状态机、Decimal 账本）、不变量构造层（INV-01/音色绑定/能力校验）、测试资产（115 项商业域 + 平台回归）质量与分层都是合理且可延续的；全部问题集中在可定位、可小步修复的集成点与门接线，无一项需要推翻底座或更换技术栈。

**状态区分声明**：
- 代码审查未发现 P0 级紧急风险（当前默认配置下真实付费路径不可达）——**本审查**；
- 开发测试通过（115+2 商业域、45 平台抽样、build ✓；lint 28 errors 除外）——**已独立复核**；
- 真实 API 验证通过——**未验证**（live 保持 skipped，按边界不执行）；
- 商业成片质量通过——**未达成**（成片无声，P1-7；且真实模型效果未验证）；
- 生产部署就绪——**否**（联调未做、上述 P1 未修、正式账号/密钥流转未配置）。
