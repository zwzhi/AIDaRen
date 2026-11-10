# 开发版待用户确认基线（2026-11-10）

## 提交与范围

| 项 | 值 |
|---|---|
| 上游底座 | yi1108/printfilm @ `26daa3fe9150dbba3a64c40b17b8c9bb93dbe08a`（main） |
| **开发版基线提交** | **`fe1a4c8`**（本文件与其后的契约对齐提交见 git log；以用户确认时最新提交为准） |
| 分支 | `feature/commercial-template-web`（基线以来 18+ 提交，全部为本项目增量） |
| 状态 | **开发版待用户确认**：模拟主流程可操作；真实 API/费用/模型效果未验证，付费执行默认关闭 |

## 启动方式（开发机）

```bash
# 0) WSL PostgreSQL（首次安装见 deploy/scripts-local/；开发期保活会话仅限开发机）
wsl -d Ubuntu-22.04 -u root -- pg_ctlcluster 14 main start
wsl -- tail -f /dev/null        # 开发保活（正式启动/恢复方案见 backup_drill 与 T10 待验项）
# Redis：Windows 服务自启（6379）

# 1) 后端（首次：cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt）
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 2) 用户端（首次 npm ci）
cd frontend && npm run dev      # http://localhost:5173

# 3) 管理端（可选，本项目暂未使用）
cd admin && npm run dev         # http://localhost:5174
```

停止：结束 uvicorn/Vite 进程即可；数据卷不清理。备份恢复：`artifacts/acceptance/backup_drill/README.md`。

## 体验入口

- 登录：http://localhost:5173/auth（登录后默认进入 **模板库**）
- 演示账号：`demo@printfilm-demo.com / Demo2026x`（管理员）；`viewer@printfilm-demo.com / Viewer2026x`（普通用户，验证权限）。**正式使用前须更换**
- 六页面：模板库 / 达人库 / 商品库 / 制作工作台 / 任务与作品 / 设置与费用
- Mock 说明：全链路为本地模拟供应商（解析/文案/报价/生成显著标注"模拟"），$ 数字均为演示池（scope=mock），不构成真实付费授权

## 健康与回归（当前提交实测）

- `GET /api/health` → ok=true（调度器/轮询器运行）
- 后端商业域：111 passed + 2 skipped（live）；平台/计费回归抽样通过；前端 lint 0 errors + build ✅
- 既有作品：#3（C1，含驳回历史）、#4（C2，30s 计划成片 导出#4 + 烧录版）可直接在任务页查看
