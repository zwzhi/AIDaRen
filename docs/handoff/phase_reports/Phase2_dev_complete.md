# 阶段二报告：开发版系统完成（模拟供应商全流程可操作）

> 提交范围：`a604da6`（上阶段末）→ 本次末提交；详见 git log。
> **验收状态：功能开发完成、开发测试通过，真实 API 契约与付费联调、模型效果及最终业务验收待验证。**

## 1. 本阶段完成项（对应用户指令 §三～§六）

| 项 | 状态 | 说明 |
|---|---|---|
| 素材上传适配（uploadMedia 路径） | ✅ | `providers/atlas/media.upload_media` + `cv_provider_media_handles`（句柄/有效期/来源哈希）；`media_delivery` 编排：归属→授权→血缘校验→上传→留痕→过期刷新；Mock 模式零网络（成功/失败/过期/刷新/原片拦截 5 测试） |
| 完整报价（去占位） | ✅ | `generation_request` 共享构造器：报价与生成同一份计划参数快照（模型/提示词/台词/图片/音色/分辨率/画幅/时长/音轨全量映射）；任一变更 → QUOTE_CHANGED 失效重报 |
| 商业 REST 全量 | ✅ | 23 路由（模板/达人/音色/商品/作品/适配/计划/报价/生成/详情/审核/合成/导出下载/预算/解析/资产），服务端权限（登录读、写限创建者/管理员、未登录 401） |
| T08 六页面 | ✅ | `/commercial/{templates,actors,products,studio,tasks,settings}`，连接真实后端；Mock 状态显著标注；生成/采用时长分列；三时长来源能力档案 |
| T09 接通页面 | ✅ | 任务页八维审核（通过/驳回含原因）、FFmpeg 合成、字幕草稿、导出下载（blob+鉴权） |
| 模拟供应商 E2E（两次复用） | ✅ | `test_e2e_mock_flow`：30s 片→解析→T1→两套达人/音色/商品→C1/C2→双击幂等→审核→合成→下载；断言**无新解析任务**且**生成参数无原片资产**（INV-01） |
| 失败与恢复场景 | ✅ | 单元/集成层：J01-J06、C01-C04、S01/S02、越权 404/403、伪 MIME、SSRF、SUBMIT_UNKNOWN 冻结、下载仅重试、poller 误送阻断（含旧业务回归 129 项） |

## 2. 测试与构建（机器输出，当前代码）

- 商业域：`103 passed, 2 skipped`（skip=live 真实联调，无密钥自动跳过）
  命令：`cd backend && .venv/Scripts/python.exe -m pytest tests/commercial -q`
- 平台回归抽样：`32 passed`（poller/scheduler/billing/overlay）
- 前端：`npm run lint` 0 errors（40 warnings 为上游存量）；`npm run build` ✅（两次，含商业页面）
- 上游基线对照不变：2191 passed / 18 failed（上游自带，清单见上阶段报告 §3）
- 环境同前：WSL PG 15432（保活为开发处理）+ Win Redis 6379 + venv Python 3.11

## 3. 浏览器验收记录（截图 `artifacts/acceptance/screenshots/t08_*.png`）

账号：`demo@printfilm-demo.com / （演示口令A·本地开发库专用）`（admin；密码仅存本地演示库，非密钥）

1. 设置与费用：预算池 $50 保存成功；能力状态明确"真实契约未验证（BLOCKED）"
2. 模板库：上传 30s 参考片 → Mock 解析 3 镜头 → 发布 T1（V1）
3. 达人库：两位达人（形象图+授权音色绑定，授权状态展示）
4. 商品库：两款商品（审核卖点+展示动作）
5. 工作台 C1：适配（台词=P1 卖点）→ 计划（S02 15s 自动拆分 U002+U003，**生成 X s / 采用 X-X s 分列**）→ 报价 $0.135（模拟价标注）→ 页面内生成完成
6. 任务与作品：#1/#3/#4 通过、#2 驳回（"台词: 商品名读错"）→ FFmpeg 合成 12s 成片+字幕 → 导出 #1 下载成功；费用 $0.45 待结算（不写 0）
7. C2 复用：E2E 测试证明同 T1 换第二套素材零重新解析、零原片上传（浏览器侧由同一 REST 链路承载）

## 4. 真实付费联调待补清单（不变 + 操作入口）

1. Atlas API Key → 管理端 `POST /api/commercial/budget` 同页未来将挂密钥配置（当前经 `patch_admin_model_settings` 字段 `atlas_api_key`）
2. 两个精确 model ID → `gemini_analysis_model_id` / `h3_developer_reference_model_id`（留空=付费自动阻断）
3. 授权素材两套 + 预算批准 → 上传走 `/commercial/templates|actors|products` 页面
4. 联调入口（已备）：`tests/commercial/live/test_provider_smoke.py`（COMMERCIAL_LIVE_TESTS=1 + ATLAS_API_KEY）；顺序：Gemini 短片理解 → H3 图片+音色+新台词（先报价）→ T1/C1 → C2
5. **未批准预算前不执行任何付费请求；Fixture 通过≠能力验证通过；不为测试移除付费保护**

## 5. 已知限制（本地功能层面，逐项）

- 工作台刷新丢失当前作品上下文（需从"任务与作品"按 ID 恢复）——计划 T10 前补 URL 参数化
- 单镜"重新生成"按钮未在页面暴露（API 已支持新 attempt 语义；当前页面重做需重新报价+新请求 ID）
- 报价 TTL 10 分钟为应用策略；服务商侧更短 TTL 待联调核实
- 管理端（:5174）商业设置页未做；预算经用户端设置页（admin 权限）操作
- 上传接口 500MB 上限为应用默认；Atlas 请求体大小限制待联调（分段/转码预留于 media.py）
- 字幕烧录（burn）服务已实现，页面仅导出 SRT 草稿，烧录按钮未暴露

## 6. 启动/停止（开发环境，Windows）

```bash
# WSL PostgreSQL（开发机；保活会话为开发处理，正式启动恢复方案见 §5 限制与 T10 计划）
wsl -d Ubuntu-22.04 -u root -- pg_ctlcluster 14 main start
wsl -- tail -f /dev/null   # 开发保活（勿用于生产）
# Redis：Windows 服务已自启（6379）
# 后端
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# 前端/管理端
cd frontend && npm run dev   # 5173
cd admin && npm run dev      # 5174
```

备份/恢复：数据库 `pg_dump printfilm`；私有素材目录 `backend/data/commercial/`；恢复演练列入 T10。
