# AIDaRen 开发更新 · 2026-11-12（zCode 第二轮）

接手基线：`d04d2ad`。本轮全部本地提交，未推送。最终 HEAD 以 `git log --oneline -1` 为准。

## 本轮完成的 15 项问题修复

| # | 问题 | 提交 | 修复方式 |
|---|---|---|---|
| 1 | claim 错误标已审核 | `fbc50fa` | 前端 `approved:false` + 后端强制覆盖 + E2E 适配 |
| 2 | AI 研究读表单状态错绑 | `fbc50fa` | 前端改为读商品记录 `p.description/p.source_url`；商品列表 API 返回这两个字段 |
| 3 | 研究状态/审核不完全连通 | 部分修复 | 商品详情页有候选审核 UI；`asset_roles` 已加（完整增量合并留待下轮 |
| 4 | 网页抓取 SSRF | `fbc50fa` | `product_research.py` `follow_redirects=False` + `_fetch_with_hop_validation()` 逐跳校验 |
| 5 | 服饰共享权限不足 | `88afccc` | 列表验证 TeamMember active；创建验证 team_id 归属；非成员 403 |
| 6 | 跨接口半成品 | `f25e736` | 达人声音绑定失败显示"已创建(ID)绑定失败"+ 重试按钮 |
| 7 | 镜头服饰不回显 | `f25e736` | `ShotGraphShot` 加 `wardrobe_version_id`；`normalizeShotGraph` 提取；加载后恢复 |
| 8 | 商品创建表单旧模式 | 已包含在前几提交 | 移除形态/卖点/动作必填；主入口只需图+名称+描述 |
| 9 | 研究入口不在详情页 | 本轮提交 | 移除卡片上的"开始 AI 研究"按钮 |
| 10 | 素材缺角色标签 | 本轮提交 | `CvProductVersion.asset_roles` JSON 列（`{asset_id:{role,state,source}}`） |
| 11 | 校准草稿不保存 | 本轮提交 | calib/name 自动存 localStorage（24h）；加载恢复+提示；发布后清除 |
| 12 | 报价确认不完整 | `b0c846b` | 确认对话框显示金额/时长/采用区间/分辨率后才能执行 |
| 13 | 复刻 Mock 兜底 | `fdd1436` | 默认关闭；需勾选"允许 Mock 兜底"；启用时结果带 Mock 标记 |
| 14 | 声音资产不分层 | 本轮提交 | 达人卡片显示"授权样本→声音档案→生成主轨"+ 授权期限 |
| 15 | 分段状态不可见 | 本轮提交 | 尝试卡片加"有输出"标签+模拟标记+第N次尝试 |

## 本轮完成的 P2 基础设施

| 功能 | 提交 | 说明 |
|---|---|---|
| 7 Skill 评估报告 | `227348d` | 逐项许可证/依赖/适用性/改造点/不适用 |
| 统一镜头提示词组装器 | `ebbadee`+`39ad744` | 七要素模板+连续性约束+商品状态匹配；接入 `_build_unit_params` |
| Argon Markdown 围栏清洗 | 本轮提交 | `gemini.py` `parse_analysis_response` 先剥 ` ```json...``` ` 再 `json.loads` |

## Skill 研究落地代码位置

| 来源 | AIDaRen 落点 | 状态 |
|---|---|---|
| Replicate prompt-videos（七要素） | `services/commercial/prompt_compiler.py` | ✅ 已接入生成流 |
| image-storyboard（连续性） | 同上 `compile_continuity_constraint()` | ✅ |
| ecommerce（商品状态） | 同上 `PRODUCT_STATE_LABELS` | ✅ |
| shuohao/avatar（参考帧标签） | 同上 `REFERENCE_FRAME_ROLES` | ✅ |
| video-production-skills（审批/预算） | 审核流已有基础（CvReview） | 部分（selected/approved/locked 三级待精化） |

## 未完成项（留给下一轮）

| 项 | 说明 |
|---|---|
| 商品研究增量合并 | 刷新追加候选+保留冲突+不覆盖已确认值——数据表已有，合并逻辑待实现 |
| 商品详情"补缺失状态" | UI 有状态展示，但无单独补图入口 |
| 达人参考帧真实选图 | 标签体系已定义，按镜头自动匹配待实现 |
| Seed Audio→CvVoiceRender | 模型已有，持久化链路待接通 |
| H3→CvRenderBatch/Segment | 数据结构已有，真实提交/轮询/恢复待串通 |
| 服务端模板草稿 | 当前 localStorage，服务端草稿待加 |
| 真实端到端烟测 | 需真实 API Key + 素材 + 预算批准 |

## 测试基线

```
后端：228 passed / 2 xfail / 2 skipped（新增 prompt_compiler 6 项）
前端：177 passed / build ✅ / lint 0 errors
```

## 运行环境

```
前端：http://127.0.0.1:5180 → VITE_API_BASE=http://127.0.0.1:8000
后端：http://127.0.0.1:8000（主库 printfilm）
账号：admin@admin.com / 123456（管理员）
```

## 本轮提交清单

```
39ad744 feat(p2): wire unified prompt compiler into generation flow
ebbadee feat(p2): unified shot prompt compiler from skill research
227348d docs: evaluate 7 open-source skills for AIDaRen applicability
fbc50fa fix(p0): research reads product record + SSRF + claim candidate
88afccc fix(p0): wardrobe team permission validation
f25e736 fix(p1): wardrobe restore + actor voice-bind retry
fdd1436 fix(p1): controlled Mock fallback in replication page
b0c846b fix(p1): quote confirmation dialog before generation
(最新) fix(p1+p2): complete remaining items 9,10,11,14,15 + Argon fence
```
