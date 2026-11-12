# 真实联调准备单（2026-11-10｜只做准备，不执行付费请求）

> 开发端已完成全部公开资料核实（来源与日期见文末）；账号内才能确认的项单独标出。
> 联调顺序（用户指定）：**Gemini 真实视频理解 → H3 我方图片+音色说出不同新台词 → 真实 T1/C1 → 同模板换第二套素材 C2 → 审核/导出/费用对账**，每步通过后进下一步，不批量生成长视频。

## 1. 两个选定模型的精确 Model ID 与参数依据

### ① Gemini 4 Argon Developer（视频解析）
- **协议**：原生 `POST /v1beta/models/{model_id}:generateContent`（Bearer 鉴权；inline_data 携带视频字节 + `response_mime_type: application/json` 结构化输出）——适配器已按此实现，Fixture 测试通过
- **精确 model_id**：❗账号内核实（控制台模型列表复制原串）。Atlas 模型 ID 存在 `命名空间/名称/能力` 形态（官方图像示例为 `google/nano-banana-2/text-to-image`），Gemini 形态待账号确认，**不猜造**
- **参数依据（公开）**：视频/音轨多模态输入、结构化输出、思考预算可配；Token 用量随响应返回（联调时记录实测）
- 联调动作：填入 ID 后 `POST /api/commercial/sources/{id}/analyze` 走真实解析（新建解析记录，不命中 Mock）

### ② MiniMax H3 Developer Reference-to-Video（视频生成）
- **公开核实（2026-11-10 官方模型页）**：
  - Developer 系列三条路线（T2V/I2V/**Reference**）均含**生成音频**（仅 Developer 有音频，标准 H3/H3 Fast/H3 Max 无）
  - **时长 5–15 秒**；分辨率 **480P / 768P / 2K**（无 1080p）；画幅 **16:9 / 9:16 / 1:1**
  - **标准价 $0.05/秒**（按生成秒计费；历史清单的 $0.015/s 已过时，不以它做预算）
  - 家族级参考输入上限：至多 **9 图 / 3 视频 / 3 音轨**（Developer Reference 具体字段名以端点 Schema 为准）
- **能力档案已对齐**：duration 5–15s / resolutions {480p,768p,2k} / 9:16 等（`capability_verified` 仍为 False，直到真实契约验证）
- **异步协议（官方文档核实）**：`generateVideo` → `{"data":{"id"}}`；轮询 `GET /prediction/{id}` → `{"data":{"status": processing|completed|failed, "outputs":[url]}}`；视频典型 30s–3min。适配器已支持 data 包装（契约测试 18 项）
- **精确 model_id**：❗账号内核实（预期形如 `minimax/h3-developer/reference-to-video`，以控制台为准）

## 2. 素材输入方式与规格（系统已实现的通道）

| 类型 | 入口 | 系统校验/规格 | 服务商侧（待联调核实） |
|---|---|---|---|
| 参考视频 | 模板库上传 | MP4/MOV；真实 ffprobe 探测；≤500MB；≤180s；有音轨 | Gemini inline_data 大小上限；超限需分段/转码预案 |
| 达人图 | 达人库上传 | PNG/JPEG/WEBP，Pillow 解码 | uploadMedia 支持格式/大小/保留期 |
| 音色样本 | 达人库上传 | MP3 等，ffprobe 音轨 | 同上 + 音色字段引用语法 |
| 商品图 | 商品库上传 | 同达人图 | 同上 |
| 服务商句柄 | 自动 | 内部资产→校验授权/血缘→uploadMedia→句柄/有效期留痕→过期重传 | 响应字段（handle/url/expires_at）以真实返回为准 |

## 3. 最小测试内容与请求参数（联调首两步）

**Step A｜Gemini 理解（一次性，最小成本）**
- 素材：**一段 5–15 秒带清晰对白的竖屏短视频**（用户授权素材）
- 请求：`generateContent`（inline_data video/mp4 + JSON Schema 提示词，temperature 0.1）
- 通过标准：返回结构化分镜（≥1 镜头，时间码合理）且**能听到的对白内容**出现在 transcript（不是只看画面）——人工核对；费用=按 Token 计（单次预计 <$0.01 量级，以账单为准）

**Step B｜H3 音色+新台词（单次 5s，最小成本）**
- 素材：我方达人图 ×1 + **授权音色样本 ×1**（样本内容与台词不同）
- 参数：Reference 路线；768p（首测低成本档）；**duration 5s**；9:16；audio=on；台词=与新商品卖点一致、且**不同于音色样本原文**的新台词
- 流程：`/calculate` **先报价**（预计 5s × $0.05 = **$0.25**，以接口返回为准）→ 用户批准 → generateVideo → 轮询 → 下载归档
- 通过标准：人工审核（人物/商品/音色/台词/口型/动作/时长）——API 200 不算通过

**Step C/D｜真实 T1/C1 → 换素材 C2**：按 A 的解析→校准发布→B 的单元流程逐镜执行（30–60s 片拆 5–15s 单元）；C2 复用 T1 **不重新解析**（系统断言持续生效）；最后对账 `/productions/{id}/costs` vs Atlas 账单。

## 4. 需要您提供/批准的清单

| # | 项 | 说明 |
|---|---|---|
| 1 | Atlas API Key | **设置与费用→安全配置**页面填写（加密存库，不回显/不入日志） |
| 2 | 两个精确 model ID | 从您的控制台模型详情复制原串（或告诉我账户内模型页路径截图内容，由我转录） |
| 3 | 授权素材 | ① 一条 5–15s 带对白竖屏参考片（Step A/B 用）② 一条 30–60s 参考片（真实 T1）③ **两套**我方素材：达人图+音色样本+商品图（含音色授权确认） |
| 4 | 预算批准（另行的明确授权） | 需含：总额（建议首日 ≤ $10：A≈$0.01 + B≈$0.25 + C1 四单元 30s≈$1.5 + 重做余量）、单次上限（建议 $0.5）、调用次数上限（建议首日 ≤ 30 次生成）、重试规则（建议：生成 0 次自动重试，仅查询/下载按退避重试） |
| 5 | 联调开关 | 环境变量 `COMMERCIAL_LIVE_TESTS=1` + `COMMERCIAL_MOCK_MODE=false`（我配置，需您知悉：关闭 Mock 后演示池立即失效） |

## 5. 防混规则（系统已内建，联调时继续执行）

- 真实任务**必须**新建解析记录/attempt：Mock 关闭后 Mock 缓存（`MOCK-*` 前缀）天然不可命中；真实运行证据归档 `live_outputs/`，与 `fixture_outputs/` 分离
- 模拟能力状态不继承：`commercial_verified_models` 清单为空=付费阻断（只读展示）；填入真实 model ID 需在 Step A/B 各通过一次后由管理员写入（页面配置，不手工改库）
- 预算池 scope=real 独立初始化（演示 $50 不带入）；未结算显示待结算不写 0
- 字幕草稿/已校对状态区分保持；异机私有素材恢复列为 T10 前待验项（数据库恢复已演练≠全系统恢复完成）

## 附：核实来源（开发端完成，2026-11-10）

- `atlascloud.ai/models/minimax-h3`（H3 家族路线/价格/时长/分辨率/音频——官方页）
- `atlascloud.ai/docs/predictions`（data 包装、状态机、轮询节奏、失败样例）
- `atlascloud.ai/docs/llm-protocols`（Gemini 原生协议路径，任务书 S11 期已核）
- `atlascloud.ai/docs/upload-files`、`/docs/billing/model-billing`（uploadMedia/calculate，字段细节联调时以真实响应回填 provider_contracts.md）
