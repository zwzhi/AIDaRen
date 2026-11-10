# 阶段报告：T00–T09 离线工程（2026-11-10）

## 1. 状态总览（工程与真实验证分列）

| 任务 | 状态 | 提交 | 说明 |
|---|---|---|---|
| T00 基线 | ✅ 工程完成 | `8ed21f7` | 锁定 26daa3f；源码复现；全量测试甄别；审计文档 |
| T01 Atlas 通道 | ✅ 工程完成 | `9c72a25` | 独立命名空间；密钥脱敏；未验证阻断付费 |
| T02 私有媒体 | ✅ 工程完成 | `5d82d11` | 私有存储/血缘/SSRF/越权 404 |
| T03 契约适配器 | ⚠️ **Fixture 完成，真实联调 BLOCKED** | `3d3014e` | Gemini/H3/报价适配器；**G1 未通过**（真实契约未验证） |
| T04 模板版本 | ✅ 工程完成 | `5215592` | 缓存隔离/版本不可变/删源可用 |
| T05 素材与规划 | ✅ 工程完成 | `005ded0` | 绑定边界/三时长分离/能力档案驱动 |
| T06 报价预算 | ✅ 工程完成 | `3e04ca2` | 参数指纹/并发预留/Decimal 账本/幂等 |
| T07 执行恢复 | ✅ 工程完成（含 BLOCKER 修复） | `0767f17` | poller 误送修复；J02–J06 语义 |
| T08 前端工作台 | ❌ **未开始** | — | 计划：六页面 + 管理端设置；REST API 仅 /sources 已挂 |
| T09 质检合成 | ✅ 工程完成 | `0ad2cff` | 八维审核/阻断项/采用区间合成/字幕策略 |
| T10 真实闭环 | ⛔ **BLOCKED（等用户输入）** | — | 见 §5 待补清单 |

关口判定：G0 ✅；G1 ❌（T03 真实联调未做）；G2 ✅（模板复用链路离线可证）；G3 ✅（离线可证）；G4 部分（后端齐，无前端）；G5 ❌。

## 2. 测试范围与命令（重要口径）

- **“96 通过”= 仅 `backend/tests/commercial/` 范围**（通道 6 + 媒体 14 + Gemini 7 + H3 14 + 解析模板 7 + 绑定 8 + 规划 8 + 不复用 3 + 报价 5 + 精度 3 + 幂等 3 + 分派恢复 3 + 提交恢复 4 + 下载 3 + 质检合成 9 ≈ 96），另有 2 项 live 测试在无密钥时自动跳过。
- 底座全量（对照）：2191 passed / **18 failed（上游基线自带，见 §3）** / 7 skipped。
- 旧业务回归抽样：设置/TokenFree/Stripe 113 ✓；计费 42 ✓；任务平台 109 ✓ + 129 ✓。
- 命令（`backend/` 下）：`.venv/Scripts/python.exe -m pytest tests/commercial -q`
- 日志：`artifacts/acceptance/test_logs/pytest_run1_wsl_flap.txt`（第一轮，含环境闪断 153 errors）、`pytest_run2_clean.txt`（干净全量）。

## 3. 18 项基线失败清单（上游 26daa3f 自带，非本项目引入）

复现：`git stash` 后在 26daa3f 检出点运行同样命令即稳定复现；失败均为确定性断言（纯函数或固定 fixture），与环境无关。抽验三例根因：`test_seedream_size_pro_cap`（纯算术，`resolve_seedream_size("3:4","3K","seedream-5.0")` 返回 2592x3456 ≠ 期望 1776x2368）、`test_character_intro_toggle`（提示词断言漂移）、`test_team_schema_cli`（无 orders 表时 PaymentSchemaNotReady）。处置：按任务书 §19 记录不修不删。

1. test_asset_media_metadata.py::test_upload_endpoint_replaces_metadata_and_archives_previous
2. test_asset_media_metadata.py::test_editing_next_generation_freezes_legacy_media_options
3. test_asset_media_metadata.py::test_media_replacement_cannot_keep_previous_model[True]
4. test_asset_media_metadata.py::test_media_replacement_cannot_keep_previous_model[False]
5. test_character_intro_toggle.py::test_prompt_forbids_intro_when_disabled
6. test_drama_subtitle_toggle.py::test_seedance_prompt_text_post_mode_strips_cues
7. test_drama_subtitle_toggle.py::test_build_seedance_generate_body_defaults_no_burn
8. test_generation_history.py::test_history_restores_actual_submission_without_other_attempts_or_helper_images
9. test_kepu_shot_edit_demote.py::test_narration_edit_invalidates_continuous_audio
10. test_marketplace_app_content.py::test_purchased_detail_and_list_share_live_social_without_changing_version[work]
11. test_marketplace_app_content.py::…[series_episode]
12. test_marketplace_app_media.py::test_standalone_market_worker_cannot_create_app_financial_tables[missing0]
13. test_marketplace_app_media.py::…[missing1]
14. test_marketplace_runtime.py::test_app_media_runs_after_existing_jobs_under_same_market_lock
15. test_seedream_size_pro_cap.py::test_pro_character_default_ratio
16. test_team_schema_cli.py::test_schema_patches_use_requested_engine_without_replacing_global[False]
17. test_team_schema_cli.py::…[True]
18. test_unified_wallet_ai.py::test_signup_and_admin_grants_keep_zero_cash_sources

## 4. provider_contracts.md 状态摘要

- 五个端点全部 **DRAFT**（协议按任务书 §8.2 公开文档实现；**未做任何真实调用**）：generateContent / uploadMedia（未实现）/ calculate / generateVideo / prediction。
- 已离线锁定：错误体不判成功、截断 JSON/越界/倒序拒绝、INV-01 构造层禁入、分辨率/时长拒绝、报价 Decimal、成功无输出→待下载语义。
- 草案能力档案 `capability_verified=False`：时长 [5s,10s] 步长 1s、480p/720p/1080p、9:16/16:9/1:1、音频+音色支持——**除画幅外每一项都待真实联调核实替换**。
- live 冒烟：`tests/commercial/live/test_provider_smoke.py`（无 `ATLAS_API_KEY`+`COMMERCIAL_LIVE_TESTS=1` 自动跳过，零付费调用）。

## 5. 真实联调待补清单（仅限账号内可见信息，由用户操作）

| 项 | 操作位置 | 用途 |
|---|---|---|
| Atlas API Key | 管理端 系统设置→模型（atlas_api_key，加密存库） | 全部真实调用 |
| Gemini 3 Flash Preview 精确 model ID | 同上（gemini_analysis_model_id） | 解析；进入联调前保持空 → 付费路径被阻断 |
| MiniMax H3 Developer Reference 精确 model ID | 同上（h3_developer_reference_model_id） | 生成；同上 |
| uploadMedia 真实请求/响应样本（图片与音频各自） | 联调时抓取回填 provider_contracts.md | 替换 DRAFT 字段映射 |
| 授权素材：30–60s 参考视频×1、达人图+音色×2 套、商品图×2 | 用户上传（/api/commercial/sources） | 模板 T1→C1→C2 闭环 |
| 测试总预算（USD 金额）与逐镜确认方式 | 管理端预算池（cv_budget_pools） | 报价→预留→结算 |

联调顺序（已定）：① Gemini 5–15s 带对白视频理解（验证听到+看到）→ ② H3 我方图片+音色+不同新台词（先报价后提交）→ ③ 30–60s 模板 T1 + C1 → ④ 换第二套素材 C2（证明不重新解析、不上传原片）。**未批准预算前不执行任何付费请求；Fixture 通过不改变 capability_verified。**

## 6. 已知阻塞与技术债

| 级别 | 项 | 处置计划 |
|---|---|---|
| BLOCKED | 真实 API 契约验证（G1） | 等密钥/模型 ID/预算；脚本就绪 |
| BLOCKED | T10 真实闭环样片与费用 | 等授权素材两套 + 预算 |
| 未开始 | T08 前端六页面 + 管理端商业设置页 | 下一阶段；REST API 需先补 productions/quote/generate/review/compose 端点 |
| 技术债 | commercial REST API 仅 /sources 已挂载 | T08 一并补齐并出 OpenAPI |
| 技术债 | 报价请求体当前为占位（`prompt` 仅台词） | 真实契约确认后按 §3 映射表补全 |
| 环境 | WSL 空闲回收 PG（开发机） | 已用常驻 `wsl -- tail -f /dev/null` 保活——**仅为开发环境处理**；正式启动与恢复方案（systemd 自启 + 连接重试）在 T10 交付前以真实重启演练验证 |
| 环境 | 本机 Python 3.11 ≠ 镜像 3.12 | 已验证兼容；生产按 3.12 |

## 7. 浏览器可验收页面（截至本报告）

- 用户端 http://localhost:5173（PRINTFILM 原功能，基线验证）——商业域页面未开发（T08）。
- 管理端 http://localhost:5174（登录页可达；商业域设置页未开发）。
- API：GET /api/health（ok=true）；POST /api/commercial/sources 等已可通过 Swagger（/docs）验收。
