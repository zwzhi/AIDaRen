# 交接文档：zCode 修复轮审查请求（2026-11-11）

> **目的**：请另一个智能体（你）独立审查 zCode 近期全部改动，找出遗漏、不足和需要调整的地方。不需要客气，直接列问题。
>
> **项目**：`D:\AI Project\AIDaRen`（GitHub: zwzhi/AIDaRen, 分支 `fix/codex-review-p1`）
>
> **审查方式**：源码静态审查 + 本地运行验证均可。不执行真实付费 API 调用。

---

## 一、项目背景（30 秒理解）

这是一个基于开源 PRINTFILM（影视平台）二次开发的 **商业短视频模板化生产工具**。核心流程：

```
上传参考视频 → 解析一次 → 人工校准分镜 → 发布模板
→ 选我方达人/音色/商品/新文案 → 逐镜报价确认 → 生成 → 审核 → 合成导出
→ 同一模板换第二套素材复用（不重新解析原片）
```

**需求基线**：`docs/handoff/baseline_audit.md` 引用的《PRINTFILM_Web_ZCode_开发任务书_V1.0.md》（可在 `C:\Users\白名单\Downloads\PRINTFILM_Web_ZCode_开发任务书_V1.0.md` 找到，或以 docs/handoff/ 各阶段报告中的摘要为准）。

**关键约束**：
- 不换底座、不换技术栈。视频解析和脚本优先使用 Gemini 4 Argon Developer，Gemini 4 Argon 作为高成本复核模型，视频生成使用 MiniMax H3 Developer Reference。
- 真实付费 API **始终关闭**（`commercial_paid_execution_enabled=false`），当前全部走本地 Mock
- 模拟与真实费用严格隔离（预算池 `scope=mock/real`）
- 原参考视频及关键帧 **绝不进入** H3 生成请求（INV-01）

---

## 二、待审查的提交范围

从上游基线 `26daa3f` 到当前 HEAD，共约 25 个提交。按时间线：

| 阶段 | 提交范围 | 内容 |
|---|---|---|
| T00-T09 基础功能 | `8ed21f7..0ad2cff` | Atlas通道隔离、私有媒体、契约适配器、模板版本化、素材绑定、报价预算、任务恢复、质检合成 |
| 阶段二：完整Web系统 | `459dc29..1a5f684` | Mock供应商层、素材上传、完整报价、REST全量API、六页面、模拟E2E |
| 阶段三：收尾 | `7cbb46d..fe1a4c8` | 合成完整性规则、预算隔离、Web缺口关闭、旧入口清理、契约对齐 |
| Codex修复轮 | `a909934` | 商品版本ID、归属权限、能力档案、V2校准、模式徽标、attempt预览、重做接线 |
| **zCode 接手修复** | **`f678170..HEAD`** | **本轮审查重点** |

### zCode 接手后的提交（重点审查）

| 提交 | 内容 |
|---|---|
| `f678170` | 第一轮6项确定缺陷（合成卡死/列表先取后滤/V2路由不更新/工作台①区未收起/烧录不留存/费用mock标记） |
| `44665e4` | 旧入口收敛（退出/Logo/帮助/头像菜单/根路径重定向）+ 统一返回按钮 + 登录页居中 |
| `97159d8` | 全量审查修复（删除旧pages.tsx、状态颜色编码、自动轮询、营销目标可编辑、滚动到②区） |
| 最新提交 | 登录页统一设计体系 + 隐藏语言切换 |

---

## 三、运行环境

```bash
# 隔离环境（推荐审查用）
# 前端：http://127.0.0.1:5180
# API：http://127.0.0.1:8100
# 数据库：printfilm_ui_fix_20261111_8a63de（WSL PostgreSQL 15432）
# Redis：DB 15
# 素材根：artifacts/codex_ui_fixes/media

# 测试账号
# admin@admin.com / 123456（管理员）
# ui.fix.owner@example.com / CodexUiFix-2026!Owner（有历史数据）

# 启动（如需恢复）
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8100
# （隔离环境变量见 docs/handoff/codex_ui_fixes/launch_isolated_api.ps1）
cd frontend && npm run dev -- --host 127.0.0.1 --port 5180
```

测试命令：
```bash
# 后端（需 PostgreSQL 运行）
cd backend && .venv/Scripts/python.exe -m pytest tests/commercial -q

# 前端
cd frontend && npm test && npm run build && npm run lint
```

---

## 四、已知设计决策（不要误判为问题）

| 决策 | 原因 |
|---|---|
| `projectScope.COMMERCIAL_PROJECT=true` 隐藏旧功能 | 用开关而非删除，设 false 可恢复上游全量 |
| 模拟报价固定 $0.015/s | Mock 层演示价，真实价走 `/calculate`，`capability_verified=false` 时付费被阻断 |
| 登录页不走 AppShell | 独立于应用壳（无顶栏），但样式已在 commercial.css 统一 |
| `backend/app/data/` 在 gitignore 中 | 运行时私有存储；历史中曾误提交约1046个合成测试文件（无真实密钥/素材），待用户决定是否重写历史 |
| 支付/充值/市场模块保留但隐藏 | 属于底座功能，`COMMERCIAL_PROJECT` 开关控制前端入口；后端路由仍注册但商业流程不会调用 |

---

## 五、审查建议切入点

### 代码层
1. `frontend/src/features/commercial/` 全部文件——内联样式仍偏多，是否还有可提取为 CSS 类的重复模式
2. `backend/app/api/commercial/productions.py`——文件已超过1200行，是否有职责混杂
3. 权限检查一致性——`_can_read` / `_ensure_writer` / `_ensure_team_writer` 是否覆盖所有端点
4. 类型安全——`commercialApi` 返回值的前端 TypeScript 类型是否与后端 Pydantic schema 同步
5. 错误处理——网络失败、超时、并发冲突的用户体验是否完整

### 页面层（浏览器实际打开 5180 验证）
1. 模板库：上传→解析→校准→发布全流程是否顺畅，校准表单是否好用
2. 达人库/商品库：创建后是否能正常编辑（当前只有创建，**没有编辑入口**——这可能是个遗漏）
3. 制作工作台：三区布局是否清晰，从"使用模板"进入是否正确预选
4. 任务与作品：作品列表→详情→审核→合成→下载，每一步是否有明确反馈
5. 设置与费用：四个分组卡片是否合理，普通用户 vs 管理员看到的差异
6. 登录页：居中卡片、石灰绿按钮、输入框焦点效果
7. **窄屏（390px）**：所有页面是否可用

### 已知未完成项（不需要重复报告）
- [ ] 真实文案适配器代码（第三轮，当前 adapt 真实分支返回 503）
- [ ] 完整镜头提示词组装（当前 prompt 仅含镜头编号，不含构图/动作/台词详情）
- [ ] 生成前文案与动作编辑（当前 dialogue_locked 固定 false，用户不能在生成前改台词）
- [ ] 审核维度真实输入（当前通过=全PASS，驳回=固定台词FAIL）
- [ ] 合成时用户明确选择采用版本（当前自动选最新合格）
- [ ] 字幕版本历史与导出列表（当前只显示最新一次导出）
- [ ] 服务端模板草稿保存（当前草稿在 localStorage）
- [ ] 旧模块彻底清理（第四轮，当前只是隐藏入口）
- [ ] 达人/商品编辑与版本更新入口

---

## 六、上游基线的18项已知失败（不要归因于本项目）

以下测试在上游基线 `26daa3f` 就已失败，属于上游自身问题：

```
test_asset_media_metadata (4项)
test_character_intro_toggle (1项)
test_drama_subtitle_toggle (2项)
test_generation_history (1项)
test_kepu_shot_edit_demote (1项)
test_marketplace_app_content (2项)
test_marketplace_app_media (2项)
test_marketplace_runtime (1项)
test_seedream_size_pro_cap (1项)
test_team_schema_cli (2项)
test_unified_wallet_ai (1项)
```

本项目增量测试 **163 passed + 2 skipped**（skipped=live真实联调，无密钥自动跳过）。

---

## 七、输出要求

请按以下格式输出审查结论：

```
## 发现的问题

### P0（阻断使用）
- 问题描述 / 代码位置 / 复现步骤 / 建议修复

### P1（影响体验）
- ...

### P2（建议改进）
- ...

## 确认无问题的项
- （列出已检查且正常的关键路径）

## 遗漏的功能
- （对照需求文档，列出尚未实现的功能点）
```

**不要**：
- 不要修改代码（只审查报告）
- 不要执行真实付费 API 调用
- 不要重写 Git 历史或清理 `backend/app/data/`
- 不要因为"旧文件还在"就判定未清理——检查是否有入口可达

---

## 八、相关文档索引

| 文档 | 位置 |
|---|---|
| 开发任务书（需求基线） | `C:\Users\白名单\Downloads\PRINTFILM_Web_ZCode_开发任务书_V1.0.md` |
| 基线审计 | `docs/handoff/baseline_audit.md` |
| 集成地图 | `docs/handoff/integration_map.md` |
| 服务商契约 | `docs/handoff/provider_contracts.md` |
| 联调准备单 | `docs/handoff/live_integration_prep.md` |
| Codex UI 修复报告 | `docs/handoff/codex_ui_fixes/report.md` |
| Codex 验收报告 | `docs/handoff/codex_ui_acceptance/report.md` |
| 阶段报告合集 | `docs/handoff/phase_reports/` |
| 测试证据 | `artifacts/acceptance/` |
| UI 截图 | `artifacts/acceptance/screenshots/ui_redesign_v2/` |

---

*文档结束。请开始审查。*
