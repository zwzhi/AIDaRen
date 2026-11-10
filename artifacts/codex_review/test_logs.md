# codex_review 实测日志（2026-11-10）

审查提交：`98bf62b0b17440e3639eda3087c56e996d3f6f2e`（feature/commercial-template-web）
环境：Windows · Python 3.11.9 venv · PostgreSQL 14 (WSL2 :15432, 测试库 printfilm_test) · FFmpeg 8.1.1
隔离：商业域测试自动派生 `_test` 库（conftest）；复现脚本显式连 printfilm_test 并自清理；
全程零真实外部调用（mock 供应商 + 本地 FFmpeg）。

## 1. 商业域后端测试

```
命令：cd backend && .venv/Scripts/python.exe -m pytest tests/commercial -q
结果：115 passed, 2 skipped, 4 warnings in 17.19s（退出码 0）
skip=live 冒烟（无 ATLAS_API_KEY 自动跳过，零付费调用）
```

与 HEAD 提交信息声称一致（115 passed + 2 live skipped）。

## 2. 平台回归抽样（商业域实际依赖路径）

```
命令：.venv/Scripts/python.exe -m pytest tests/test_task_poller_dispatch.py \
      tests/test_task_scheduler_dispatch.py tests/test_model_settings_overlay.py \
      tests/test_billing_settlement.py tests/test_tokenfree_pricing.py -q
结果：45 passed, 4 warnings in 2.89s（退出码 0）
```

## 3. 上游基线失败抽查（18 项中取 3 个文件）

```
命令：.venv/Scripts/python.exe -m pytest tests/test_seedream_size_pro_cap.py \
      tests/test_team_schema_cli.py tests/test_unified_wallet_ai.py -q
结果：3 failed, 22 passed
失败：test_pro_character_default_ratio、test_team_schema_cli×2 —— 与基线清单一致
（test_unified_wallet_ai 在单跑时通过；基线为全量运行下失败，未深究顺序依赖）
结论：上游失败不在商业域依赖路径上，行为与基线一致，非本轮回归。
```

## 4. 前端

```
命令：cd frontend && npm run lint
结果：Found 39 warnings and 28 errors —— 28 errors 全部位于 src/pages/studio/CreateProjectPage.tsx
      （react-hooks/rules-of-hooks：早返回 <OldEntryGuide> 位于 hooks 调用之前，
       该代码在 cb37d87 已存在；与 Phase3/Phase4/dev_baseline 报告"lint 0 errors"矛盾）

命令：npm run build
结果：✓ built in 1.01s（退出码 0；chunk>500kB 警告为上游存量）
```

## 5. 复现脚本（artifacts/codex_review/repro_checks.py，隔离库+自清理）

```
[R2] 复现：720p 报价构造被拒 code=PROVIDER_RESOLUTION_UNSUPPORTED；当前能力档案=['2k','480p','768p']
     （frontend/src/features/commercial/pages.tsx:319 硬编码 resolution_id='720p' → 浏览器新建作品报价必 422）
[R1] 复现：同一 attempt 轮询两次，账本行 1 → 2
     （幂等重放路径 productions.generate_unit 对 replay 仍建新任务并驱动 poll_attempt，
       MOCK/真实分支均无 GENERATED 短路 → 每次重放追加一条 SETTLEMENT_PENDING 费用行）
[R3] 复现：4 单元中 U002-U004 无任何合格版本，覆盖校验返回 None（放行完整成片）
     （_unit_coverage_error 仅在 合格数<单元数 时阻断；同单元多次重做使数量达标即可绕过）
```

## 6. 归档产物核验（只读）

```
ffprobe artifacts/acceptance/export-4-master-30s.mp4     → 仅 1 路 h264 视频流，无音轨
ffprobe artifacts/acceptance/export-4-subtitled-30s.mp4  → 仅 1 路 h264 视频流，无音轨
export-4-snapshot.json：kind=master、total_adopt_ms=30000、selections 含 4 个第2次尝试（#10-#13），
  SRT 四段文本全部相同（"贴敷八小时持久清凉"），含重做单元 U003 —— 重做台词编辑未生效的佐证。
```

## 7. 未执行项与原因

- 后端全量 pytest（~2200 项）：基线已有干净全量日志（pytest_run2_clean.txt），本次以商业域 +
  依赖路径抽样 + 失败文件抽查覆盖审查目标；全量重跑对本审查结论无增量。
- 浏览器端到端操作：本次审查以代码链路 + 既有归档截图/产物 + 复现脚本为证据；
  720p 回归已由静态+脚本复现闭环，无需起服务。
- 真实 API/live 冒烟：按审查边界明确不执行（2 项 live 测试保持 skipped）。
