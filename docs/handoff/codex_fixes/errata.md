# 审查报告勘误（对 docs/handoff/codex_review/review_report.md）

> 原报告保留不改；本文件按修复轮新证据补充勘误与状态更新（2026-11-10，Codex 修复轮）。

## 1. 结论维持项

审查报告全部 8 项 P1 结论经修复轮逐项核实**全部成立**，无一条被反证推翻。
P2 清单中 P2-1/P2-2/P2-3/P2-5 已随本轮修复；其余分类见 fix_report §P2。

## 2. 需修正/补充的表述

| 原表述 | 勘误 |
|---|---|
| P1-4 判定"任务不会因租约超时被无休止回收"尚缺动态复现 | 修复轮以真实 executor/调度器复现并修复（tests/commercial/test_platform_lifecycle.py 7 项）；原判定正确且现已闭环 |
| P1-2 仅以 repro 脚本复现 | 已转正式回归测试（test_budget_lifecycle.py 8 项，修复前全失败→全通过） |
| 审查报告"运行中的 8000 服务"描述 | 该服务为无 reload 的旧代码实例（系统 Python 直启）；修复轮按项目启停文档重启为修复版（venv），幂等、仅本地开发服务 |
| P1-1 修复建议"改为 768p 或动态选择" | 已按更强方案落地：新增 /api/commercial/capabilities，前端选项完全由能力档案驱动（不引入新的硬编码默认值） |

## 3. 修复轮新发现的两个缺陷（原审查未列出）

1. **商品版本 ID 错配**（P2 级，影响核心操作）：list_products 仅返回版本号，
   前端将其当版本行 ID 使用——多商品场景下换商品实际命中第一个商品的版本
   （卖点/图片错配）。浏览器实测发现并修复（4d31c74）。
2. **多 selection 字幕只输出最后一段**（P1 级，Codex 在 P1-3 重构时引入后即修）：
   字幕块被移出 selection 循环。浏览器实测发现并修复（4d31c74），
   已补回归测试。此缺陷从未进入任何已发布分支（仅存在于 9535de1..4d31c74 之间的
   修复分支中间态）。

## 4. 历史验收文件状态变更

`artifacts/acceptance/` 下的无声成片（export-2/export-4 系列）不再代表当前系统能力，
以 `artifacts/codex_fixes/codex_fix_master_30s.mp4`（含 aac 音轨）为准。原文件保留作历史证据。

## 5. 业务库变更说明（修复轮内发生的）

- **增量 schema**（应用启动自动应用，additive）：`cv_usage_ledger.event_key` 列 +
  `uq_cv_ledger_attempt_event` 唯一索引；历史 13 行回填 `legacy.<id>`（金额/状态未动）。
- **新增演示数据**（浏览器验证创建，未改动既有行）：模板「Codex修复验证模板」、
  达人「Codex验证达人」、商品「Codex验证商品」、作品 #5-#7、attempt #14-#17、
  导出 #5/#6 及其成片文件。
- **未清理的既有悬挂预留**：13 条 mock 演示预留（$1.425）保持原样，
  见 artifacts/codex_fixes/recon_checklist.md，处置待用户决定。
