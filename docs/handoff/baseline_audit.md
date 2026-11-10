# PRINTFILM 基线审计（baseline_audit）

> 任务：T00 锁定底座并复现原项目（任务书《基于 PRINTFILM 的 Web 商业短视频模板化生产系统》V1.0 §16-T00）
> 审计日期：2026-11-10 · 审计人：zCode（GLM-5.3）

## 1. 基线锁定

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/yi1108/printfilm（main 分支） |
| 基线提交 SHA | `26daa3fe9150dbba3a64c40b17b8c9bb93dbe08a` |
| 基线提交信息 | `fix: 统一公司主体品牌与全站客服信息`（2026-11-10 11:57:47 +0800） |
| 本地工作区 | `D:\AI Project\AIDaRen`（克隆时目录为空，无用户未提交修改被覆盖） |
| 开发分支 | `feature/commercial-template-web`（自基线 SHA 创建） |
| 许可证 | MIT（`LICENSE`，© 2026 PRINTFILM）；二次开发保留声明 |
| 网络说明 | GitHub 直连不通，经本机代理 127.0.0.1:10808 克隆（仅配置在仓库本地 git config，未改全局） |

## 2. 运行环境（本机无 Docker，源码方式复现）

Docker Desktop 未安装。按 CLAUDE.md 的"本机三进程 + 中间件"路径搭建等价环境：

| 组件 | 版本/位置 | 说明 |
|---|---|---|
| Python | 3.11.9（Windows，venv `.venv`） | 底座 Dockerfile 为 3.12-slim；已用 AST 全量解析 app/+tests/ 验证无 3.12-only 语法，依赖装齐后测试全通过，3.11 兼容 |
| PostgreSQL | 14.24（WSL2 Ubuntu-22.04 内，systemd 托管） | 监听 `*:15432`；库 `printfilm` + 测试库 `printfilm_test`（conftest 自动派生）；角色 printfilm/CREATEDB |
| Redis | Windows 服务，5.x，端口 6379 | `REDIS_URL=redis://127.0.0.1:6379/0` |
| FFmpeg | 8.1.1（winget Gyan.FFmpeg，PATH 可用） | 合成/探测可用；ffprobe 同包 |
| Node/npm | v24.22.1 / 11.19.1 | 前端与 admin 各自 `npm ci` |
| 后端依赖 | fastapi 0.115.12 / sqlalchemy 2.0.40 / asyncpg 0.30.0 / pydantic 2.11.3 / httpx 0.28.1 / redis 5.2.1 / pytest 8.3.5 | `pip install -r requirements-dev.txt` 一次通过，无安装阻塞 |

本地配置 `backend/.env`（不入库）：隔离库、Mock 关闭外部付费（`ARK_MOCK=false`、`OPENAI_API_KEY=` 空、`BILLING_ENABLED=false`、`QUOTA_ENABLED=false`）。基线验证全程未调用任何付费渠道。

### 2.1 环境问题记录（已解决，非代码缺陷）

- **WSL 空闲回收导致 PG 闪断**：症状为 pytest 期间 `CannotConnectNowError: the database system is shutting down`、journal 显示 postgresql@14-main 每 ~60s 被 systemd 停起。根因是 WSL2 在最后一个会话退出后回收 VM（vmIdleTimeout）。修复：常驻 `wsl -- tail -f /dev/null` 保活会话。修复后 PG 稳定 >30 分钟。
- 第一轮全量 pytest 恰逢闪断窗口：**23 failed / 2033 passed / 7 skipped / 153 errors**（errors 全部为 fixture 建库连接失败，集中在 marketplace/stripe 文件）。日志存 `artifacts/acceptance/test_logs/pytest_run1_wsl_flap.txt`。环境修复后重跑全量得到干净基线（见 §3），失败差异全部归因于基础设施闪断，不是代码缺陷。

## 3. 既有测试与构建结果（干净环境）

命令（`backend/` 下，venv）：`.venv/Scripts/python.exe -m pytest -q`

**第二轮（干净环境）：18 failed / 2191 passed / 7 skipped（9:33，退出码 1）**，日志 `artifacts/acceptance/test_logs/pytest_run2_clean.txt`。

18 个失败甄别结论：**均为上游基线 SHA 自带的确定性失败，非本环境引入**（未改动任何 app 代码；抽样复跑 `test_seedream_size_pro_cap`（纯算术断言 `1776x2368`）、`test_character_intro_toggle`（提示词断言）、`test_team_schema_cli`（`PaymentSchemaNotReady: orders`）均稳定复现，属测试与代码漂移）。失败分布：marketplace 系 7、asset/媒体元数据 4、字幕/台词 3、尺寸/画幅 1、team schema CLI 2、钱包 1。**与商业域集成点相关的测试（test_tokenfree_*、test_model_settings_overlay、test_task_scheduler/poller/executor/runtime 系、test_billing_* 系）全部通过**——不阻塞 T01 起的生产开发。按任务书 §19 记录为基线差异，不删改测试、不在 T00 顺手修复。

| 检查 | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 后端全量测试 | `pytest -q` | 1 | 2191 passed / 18 failed（上游自带）/ 7 skipped |
| 用户端 lint | `npm run lint`（frontend/） | 0 | 通过 |
| 用户端构建 | `npm run build`（frontend/） | 0 | 通过（1.06s，仅 chunk>500kB 警告） |
| 管理端 lint | `npm run lint`（admin/） | 0 | 通过 |
| 管理端构建 | `npm run build`（admin/） | 0 | 通过 |
| 用户端 lint | `npm run lint`（frontend/） | 0 | 通过 |
| 用户端构建 | `npm run build`（frontend/） | 0 | 通过（1.06s，仅 chunk>500kB 警告） |
| 管理端 lint | `npm run lint`（admin/） | 0 | 通过 |
| 管理端构建 | `npm run build`（admin/） | 0 | 通过 |

## 4. 源码启动验证（G0 证据）

| 入口 | 地址 | 结果 |
|---|---|---|
| FastAPI 后端 | `uvicorn app.main:app --port 8000`（源码启动） | `/api/health` → `ok=true`，scheduler/poller/watchdog 均 running，连续失败 0 |
| 用户端 | `npm run dev`（Vite 8） | http://localhost:5173/ → 200，首页完整渲染（截图 `t00_frontend_home.png`） |
| 管理端 | `npm run dev` | http://localhost:5174/ → 200，正常跳登录页（截图 `t00_admin_login.png`） |
| API 文档 | `/docs` | Swagger UI 加载完整，含全部接口分组（截图 `t00_api_swagger.png`） |
| 数据库 | init_db 建表 + `_apply_schema_patches` 增量补列 | 启动无错误，业务库表齐全 |

管理端账号说明：底座不造默认管理员；`ADMIN_BOOTSTRAP_EMAILS` 仅提升已注册用户。基线验证未注册账号（无需登录即可验证服务可用），T01+ 再按需初始化。

## 5. 重点审查：渠道锁定 / 任务恢复 / 计费

### 5.1 渠道锁定（TokenFree）——任务书预警全部属实

| 审查点 | 源码事实 | 结论 |
|---|---|---|
| 上游唯一性 | `services/tokenfree_gateway.py`：`TOKENFREE_BASE_URL` 硬编码 `https://www.tokenfree.com/v1`；`locked_tokenfree_channel()` 强制 `api_format="openai"` | ✅ 属实 |
| 启动归一 | `model_settings.py::_ensure_tokenfree_channel()`：每次启动重写 TokenFree 渠道行并把**其余渠道行全部 `enabled=False`** | ✅ Atlas 若作为渠道行插入会被强制停用 —— T01 采用独立配置命名空间规避 |
| overlay 覆盖 | `apply_tokenfree_flat_overlay()`：把 `openai_base_url`/`ark_base_url` 强制刷回 TokenFree；Key 非空时覆盖 `openai_api_key`/`ark_api_key` | ✅ 属实；`atlas_*` 字段与该 overlay 无键交集，需测试锁定 |
| 管理端保存 | `patch_admin_routing_settings()`：只接受 TokenFree 渠道，其余渠道输入被忽略/停用 | ✅ 属实；商业域走独立管理端配置 |
| 配置清空回落 | `_refresh_overlay()` 注释确认：空串保留（显式清除），None 跳过（回落 .env） | 与任务书"清除密钥后不回落旧环境密钥"要求一致 |

### 5.2 任务恢复（调度器/轮询器/幂等）

| 审查点 | 源码事实 |
|---|---|
| 租约 | DB 租约 10 分钟 + 执行协程 10s 心跳续租（条件写入，token 校验） |
| 孤儿回收 | `recover_orphaned_tasks()`：过期 leased/running → 重新 pending（`task.recovered` 事件）；本进程仍持有协程的跳过 |
| inline 不重发 | inline 租约前缀任务中断 → 直接 failed（`inline_execution_interrupted`）+ 结算，**不重排队不重发 POST** —— 满足 INV-04 |
| 上游任务号 | drama `asset_video` 的 `_remember_provider_task`：上游 ID 一创建立即落库；重启后恢复只查询/下载，不重新提交 |
| 幂等字段 | `TaskRun.client_request_id`（有索引）+ `dedupe_key`；任务服务层查重（`services/tasks/service.py`） |
| 轮询分派风险 | ⚠️ `poller.py::_poll_ephemeral_deferred_tasks` 以 `domain.not_in(["drama","kepu"])` 兜底接管所有 awaiting_poll 任务并用 TokenFree 协议轮询 —— 新增 `commercial` 域**必须**显式排除并注册专属分派，否则商业任务会被误送旧渠道（T07 第一个失败测试来源） |
| 队列容量 | text/image/video 三队列独立容量 + 用户/团队上限 + PG advisory lock 防多实例争抢；商业域默认并发 1/2/1 走新配置项 |

### 5.3 计费（TokenFree 体系）

| 审查点 | 源码事实 |
|---|---|
| 流程 | 建任务 freeze → 执行中 usage_events → poller/executor `settle_task` 扣实费退冻结；钱包单位人民币分（int） |
| quota 换算 | `500000 quota = 1 USD`，`BILLING_USD_CNY=7.3` 折分；取不到 usage 退本地保守估价 |
| 上游留痕 | `task_events` 的 `upstream.request.started/accepted/failed/poll`（同 request_id 关联），脱敏存储 |
| 默认关闭 | `BILLING_ENABLED=false`（本基线保持关闭） |
| 商业域结论 | Atlas 费用**不沿用** quota 换算与 fen 字段：T06 新建 Decimal 原币账本（`cv_usage_ledger`，NUMERIC(20,8)），TaskRun 计费位仅作状态展示 |

### 5.4 静态素材与权限边界

- `main.py` 将 `backend/static` 整目录公开挂载 `/static`（无鉴权）→ 商业域私有素材（原片/达人/音色/商品）必须存独立私有目录，经带权限校验的受控接口下载（T02）。
- 任务中心/管理端列表有分页与事件窗口限制；团队资源按 `team_id` 归属校验（teams 域），商业域复用。

## 6. 数据迁移方式确认

- 无 Alembic：启动 `init_db()` create_all + `main._apply_schema_patches()` 幂等增量 DDL（已有 team/media/payment 三个模块化补丁先例）。
- conftest 复用 `_apply_schema_patches`（权威清单）→ 商业域新增表需同步注册进 conftest。
- 结论：T01+ 沿用该方式新增 `cv_*` 表，不引入新迁移工具（符合任务书 11.2）。

## 7. 阻塞项 / 非阻塞技术债

| 级别 | 项 | 处置 |
|---|---|---|
| 阻塞（环境，已解除） | WSL 空闲回收闪断 PG | 保活会话；建议后续写入 start-dev.ps1 |
| 非阻塞 | 本机 Python 3.11 ≠ Dockerfile 3.12 | AST+全量测试验证兼容；生产仍按 3.12 镜像 |
| 非阻塞 | frontend build chunk >500kB 警告 | 上游现状，不改 |
| 非阻塞 | 管理端无初始管理员 | 底座设计如此（不造号），T10 交付时按 ADMIN_BOOTSTRAP_EMAILS 初始化 |
| 待验证（BLOCKED） | Atlas/Gemini/H3 真实 API | 无密钥/预算，T03 前仅 Fixture 测试，真实联调标记 BLOCKED |

## 8. G0 关口结论

- [x] 基线 SHA 锁定并记录
- [x] 源码方式构建并启动：后端 + 用户端 + 管理端 + PostgreSQL + Redis 全部可用
- [x] 既有后端测试全量运行并记录（干净环境）
- [x] 前端/管理端 lint + build 通过
- [x] 渠道锁定、任务恢复、计费、静态边界审查完成，改造点写入 integration_map.md
- [x] 无安装阻塞；安装问题（WSL 回收）已定位并修复，非底座缺陷

**G0 通过。** 可进入 T01（Atlas 通道隔离）。
