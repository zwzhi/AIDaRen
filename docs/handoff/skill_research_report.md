# 开源 Skill 研究评估报告（2026-11-12）

> 7 个仓库逐一评估：许可证、依赖、适用价值、需改造部分、不适用部分。
> 结论直接指导 AIDaRen 代码落地，不只写报告。

---

## 1. sb-dev/video-production-skills

| 项 | 结论 |
|---|---|
| 许可证 | MIT（README 声明） |
| 依赖 | Replicate API Token（`find-models`/`prompt-videos`/`run-models`），TypeScript 工具链 |
| 模型绑定 | Replicate 全家桶（图/视频均走 Replicate） |
| 输入输出 | 创意简报 → 视觉方向/角色/产品清单 → 分镜/动画 → 镜头生成 → 剪辑 → 交付 |

### 适用（直接可迁移的模式）

| 模式 | AIDaRen 落点 |
|---|---|
| **selected vs approved vs locked 三级状态** | 锚帧/镜头/成片的状态机：agent 可推进到 `selected`，人工才到 `approved/locked`；`approvedBy` 为空视为未审核 |
| **预算上限+重试上限→停止报告** | `budget_service.py` 增加每层重试计数和 spend ceiling，超限停止并报告（而非默默升级费用） |
| **创意决策审批前执行昂贵生成** | 生成前必经：视觉方向→角色参考→镜头计划→picture lock 各节点审批 |
| **validate-production.ts 结构化 QC** | 参考其确定性验证思路：检查 approvedBy 非空、镜头连续性、规格一致性 |

### 需改造

- Replicate API 全部替换为 Atlas（Gemini/Flare/Sunburst/Seed Audio/H3）
- TypeScript 工具链不适配 Python 后端，改为 pytest 确定性检查

### 不适用

- Replicate-specific 模型发现/比较流程（`find-models`/`compare-models`）
- TypeScript 脚本直接接入

---

## 2. puntorigen/avatar-skills

| 项 | 结论 |
|---|---|
| 许可证 | MIT |
| 依赖 | Replicate + ElevenLabs + Gemini + Higgsfield（多供应商） |
| 模型绑定 | `prunaai/p-video-avatar`（口播）+ MiniMax TTS + Gemini 图像 |
| 输入输出 | 文字→虚构主持人+克隆声音+口播视频+B-roll→成片 |

### 适用

| 模式 | AIDaRen 落点 |
|---|---|
| **avatar-frames：从视频提取干净参考帧** | 参考其"单人脸、清晰、无烧录字幕"的帧筛选标准 → `actor_references.py` |
| **avatar-camera-angles：同一人/服装/房间的角度变体** | 参考帧标签体系（角度/表情/景别） → `CvActorReferenceFrame` 的 yaw/pitch/expression/shot_scale |
| **voice-clone→统一主声音轨** | 声音样本归属达人→新台词生成统一主轨（与 AIDaRen 设计一致） |
| **reel-composer：旁白→逐场景剪辑→B-roll→成片** | 合成管线的编排参考（H3 分段→主轨对齐→FFmpeg 拼接） |
| **skill composition 链式模式** | `avatar-invent→script→composer→talking-video→broll→edit` 链路设计 |

### 需改造

- Replicate `p-video-avatar` 替换为 Atlas H3 Reference-to-Video
- ElevenLabs TTS 替换为 Atlas Seed Audio
- Higgsfield MCP 替换为 Atlas API
- 虚构主持人→用已有真实达人（不可虚构）

### 不适用

- `avatar-invent`（虚构角色——AIDaRen 用真实授权达人）
- `broll-finder`/`reel-discovery`（YouTube/TikTok 下载——版权风险）
- `bg-music-hq`/`sound-effects`（首版不需要 BGM/SFX）

---

## 3. eternityspring/shuohao-skills

| 项 | 结论 |
|---|---|
| 许可证 | 开源（README 声明 free and open source，具体 LICENSE 需查看仓库） |
| 依赖 | Agent-agnostic（支持 Claude Code / Codex），脚本为 Python/Shell |
| 模型绑定 | APIMart 赞助商（非强依赖），ComfyUI 本地生成 |
| 输入输出 | 小说→大纲→角色圣经→美术→剧本→场景调度→分镜→参考图 |

### 适用

| 模式 | AIDaRen 落点 |
|---|---|
| **六阶段流水线：outline→characters→art→script→staging→storyboard** | AIDaRen 的 `analysis→template→adaptation→planning→generation→compose` 已有类似结构 |
| **character bible（角色圣经）** | `CvActorVersion` 的 `appearance_desc`/`wardrobe_desc` 可扩展为结构化角色档案 |
| **novel-staging（场景调度）** | 分镜前的"位置/朝向/动作起点"冻结——对 H3 生成前的锚帧审核有参考价值 |
| **角色参考图分类标签（角色/服装/表情/道具）** | `CvActorReferenceFrame` 的 `role` 字段扩展（identity/wardrobe/expression/prop） |

### 需改造

- 小说→短剧的文本流程不适用（AIDaRen 是商品带货不是短剧）
- ComfyUI 本地生成替换为 Atlas API

### 不适用

- 小说改编/剧本创作流程
- ComfyUI 依赖

---

## 4. replicate/skills → prompt-videos

| 项 | 结论 |
|---|---|
| 许可证 | Replicate 官方仓库（开源） |
| 依赖 | Replicate API |
| 模型绑定 | 模型无关（通用提示词技巧） |
| 输入输出 | 视频提示词最佳实践文档（纯知识型 Skill） |

### 适用（**高价值，纯知识迁移**）

| 技巧 | AIDaRen 落点 |
|---|---|
| **七要素分层提示词**：Subject/Context/Action/Style/Camera/Composition/Ambiance | `prompt_compiler.py` 的生成提示词组装模板 |
| **具体描述优于模糊**："car chase"→完整场景描述 | 每个镜头的 prompt 必须包含具体构图/动作/光线，不能只写"S01" |
| **直接命名主体**："the woman in red jacket" 而非代词 | 提示词中用"达人A穿白色T恤"而非"她" |
| **过度描述优于简略**：现代视频模型能处理长密集 prompt | 锚帧 prompt 应包含完整画面描述（角度/服装/商品位置/背景/光线） |
| **标准镜头术语**：wide/medium/close-up/extreme close-up | `CvActorReferenceFrame.shot_scale` 的取值标准 |
| **摄像机语言**：dolly/tracking/static/handheld | 分镜的 `camera.movement` 取值标准 |

### 需改造

- 不需要代码改造——纯提示词模板知识，直接写入 `prompt_compiler.py`

### 不适用

- Replicate-specific API 调用示例

---

## 5. fanshuning/agentara-skills → video-storyboard

| 项 | 结论 |
|---|---|
| 许可证 | 需查看仓库（fork 自 agentara/skills） |
| 依赖 | Agent-agnostic |
| 输入输出 | 场景号+时长→分镜图（PNG）+视频生成提示词脚本（MD） |

### 适用

| 模式 | AIDaRen 落点 |
|---|---|
| **分镜=图+提示词脚本的配对输出** | 每个锚帧应同时保存：图片 + 生成该图的完整提示词（`evidence` 追溯） |
| **grid sizing + timing labels** | 分镜图上标注时长（如"4s"），对应 H3 的 `request_duration_ms` |
| **角色/服装/道具/场景连续性强制** | 提示词中显式声明"same person, same outfit, same location" |

### 不适用

- 具体的 PNG 分镜图板渲染（AIDaRen 用参考帧而非手绘分镜）

---

## 6. SamurAIGPT/open-ai-image-agent → image-storyboard

| 项 | 结论 |
|---|---|
| 许可证 | 需查看仓库 |
| 依赖 | OpenAI DALL-E/GPT Image |
| 输入输出 | 文字→连续分镜图（多张图像叙事序列） |

### 适用

| 模式 | AIDaRen 落点 |
|---|---|
| **连续性约束**：同一角色跨多张分镜图的外观一致 | Flare/Sunburst 锚帧生成的 prompt 必须包含"保持与参考帧完全一致的外观/服装/光线" |

### 不适用

- OpenAI DALL-E 模型绑定
- 纯图序列→无视频/音频的完整工作流

---

## 7. nexu-io/open-design → ecommerce-image-workflow

| 项 | 结论 |
|---|---|
| 许可证 | 需查看仓库 |
| 依赖 | 电商场景特定 |
| 输入输出 | 商品→多状态图（包装/使用/效果） |

### 适用

| 模式 | AIDaRen 落点 |
|---|---|
| **商品多状态拍摄工作流** | `CvProductState` 的 `state_key` 取值参考：`packaging/opening/texture/application/effect` |
| **按状态匹配镜头需求** | 分镜分析时按"本镜头需要什么状态的商品图"检索素材 |

### 不适用

- 具体的电商图片生成流程（AIDaRen 用上传的真实商品图+联网研究，不用 AI 生成商品图）

---

## 综合优先级（按影响排序）

### 立即落地（P2 中实施）

1. **提示词七要素模板**（来自 prompt-videos）→ `prompt_compiler.py`
2. **selected/approved/locked 三级状态 + approvedBy**（来自 video-production-skills）→ 审核流
3. **参考帧标签体系**（来自 avatar-skills + shuohao-skills）→ `CvActorReferenceFrame`
4. **商品状态键标准化**（来自 ecommerce-image-workflow）→ `CvProductState.state_key`
5. **分镜连续性约束提示词**（来自 image-storyboard + video-storyboard）→ `prompt_compiler.py`

### P2 后续落地

6. **预算重试上限+停止报告**（来自 video-production-skills）→ `budget_service.py`
7. **声音→主轨→分段→合成编排**（来自 avatar-skills）→ `voice.py` + `render_batch.py`

### 不引入

- Replicate/ElevenLabs/Higgsfield/ComfyUI 的任何直接依赖
- 虚构角色/小说改编/BGM SFX 生成
- YouTube/TikTok 下载功能
