# 模拟体验环境说明（2026-11-11）

分支 fix/codex-review-p1 @ df2a42b（体验期间保持不变）

## 环境

| 项 | 值 |
|---|---|
| 前端 | http://localhost:5173 （Vite dev，热载 df2a42b 前端代码） |
| 后端 | http://localhost:8000 （同分支代码；独立 demo 实例） |
| 数据库 | **printfilm_demo**（独立库，业务库 printfilm 未连接、未改动） |
| 素材目录 | artifacts/demo_env/storage/commercial（独立私有存储根） |
| 预算 | mock 池 $50.00（与真实授权无关） |
| 模式 | COMMERCIAL_MOCK_MODE=true；付费执行关闭；解析/报价/生成/合成全为本地模拟 |
| 启动命令 | uvicorn，环境变量覆盖 DATABASE_URL / COMMERCIAL_STORAGE_ROOT / COMMERCIAL_MOCK_MODE 等（见 shell 历史 /tmp/uvicorn_demo.log 同目录） |

## 账号

- demo@printfilm-demo.com / （演示口令A·本地开发库专用）（管理员，demo 库独立账号）

## 预置数据（均走真实 REST 播种）

- 模板：「体验模板（30秒·三镜头）」V1（30s 带音轨参考片解析发布）
- 达人A（音色#1）/ 达人B（音色#2）
- 商品A「清凉贴敷八小时持久降温」/ 商品B「温和配方敏感肌也能安心用」

## 重置

如需重来：停止后端 → `DROP DATABASE printfilm_demo` → 重建 → 重跑
`backend/.venv/Scripts/python.exe ../artifacts/demo_env/seed_demo.py`（先注册账号并
在 demo 库提权 admin，脚本内含说明）。
