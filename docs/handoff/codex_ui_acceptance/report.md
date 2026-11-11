# AIDaRen 商业短视频模板化生产系统 · 独立 UI 与业务验收报告

- 验收日期：2026-11-11（Asia/Shanghai）
- 验收者：Codex，独立验收者
- 项目目录：D:\AI Project\AIDaRen
- 当前分支：fix/codex-review-p1
- 当前 HEAD：f3afb62faf8540f9c8756bba407e9095d281b776
- 与远端：相对 origin/fix/codex-review-p1 ahead 2
- zCode 提交核对：a851167d990770e9f4132783061c197602f0df7e、f3afb62faf8540f9c8756bba407e9095d281b776、b4d5900acec1fd53f980b3ad25abc7a6ac27b499 均存在；前两者属于当前 HEAD 历史，b4d5900 为远端对照。
- git diff --check a851167..HEAD 无输出，退出码 0。
- 当前工作区未发现业务源码修改；验收新增日志、截图、报告和 Playwright 快照为未跟踪文件。未执行 checkout、reset、pull、push、merge、force-push 或源码修复。

## 最终判断

1. **zCode 本轮 UI 与校准交付：不通过。**
2. **暂不能开始完整的本地模拟操作。** 当前环境没有可确认隔离的浏览器后端/数据库，且静态代码已确认商品版本引用、归属权限、版本 V2、能力档案和媒体预览存在阻断。完成修复并用隔离环境重跑 C1/C2 后再开始完整操作。
3. **必须先修的问题**：P1-UI-01、P1-SEC-01、P1-CAL-01、P1-CAL-02、P1-CAP-01、P1-ENV-01，以及当前 HEAD 已有的 P1-REG-01。P2 项目可在主流程恢复后处理。
4. **此前核心修复是否回归：有回归/未闭环。** 商业测试中的幂等、预算、审核覆盖、台词、音轨等断言通过，但新页面重新引入硬编码分辨率、商品版本 ID 错用和完整工作页媒体预览缺口；平台级历史记录回归测试失败。
5. **影响真实付费联调的已知阻断仍存在。** 当前 /api/health 返回 ark_mock:false，两个真实供应商 smoke 测试因没有授权而跳过；能力验证、真实模型契约、费用和音色/口型效果均未验证。不得把 Mock 或测试提示音写成真实模型效果已验证。

## 审查范围与差异

本轮重点差异（a851167..HEAD，21 个路径）包括：

- frontend/src/features/commercial/CommercialLayout.tsx
- frontend/src/features/commercial/commercial.css
- frontend/src/features/commercial/templatesPage.tsx
- frontend/src/features/commercial/templateDetail.tsx
- frontend/src/features/commercial/libraryPages.tsx
- frontend/src/features/commercial/studioPage.tsx
- frontend/src/features/commercial/workPages.tsx
- frontend/src/features/commercial/templatesApi.ts
- frontend/src/features/commercial/assetPreview.tsx
- frontend/src/features/commercial/api.ts
- frontend/src/App.tsx
- backend/app/api/commercial/productions.py
- backend/tests/commercial/test_calibration_roundtrip.py
- artifacts/acceptance/screenshots/ui_redesign_v2/*

源码确认商业布局复用了 AppShell hideFooter（CommercialLayout.tsx:7-14），商业导航来自 COMMERCIAL_NAV（App.tsx:74-80、projectScope.ts:10-22），输入控件和镜头编辑使用 --pf-* 变量（commercial.css:4-51）。App.tsx:114 在商业项目开关下不渲染旧微信浮窗。设计体系复用在源码层成立，但交互与业务验收不能由这些静态证据替代。

## 运行环境与安全隔离

现有进程未经我停止：

- 用户端 Vite：PID 21520，D:\AI Project\AIDaRen\frontend\node_modules\.bin\vite --host，监听 5173。
- 管理端 Vite：PID 40192，监听 5174（127.0.0.1 访问被拒，IPv6 访问也受本机权限限制）。
- uvicorn：PID 2496 使用项目 .venv，命令为 uvicorn app.main:app --port 8000。
- uvicorn：PID 46284 使用系统 Python 3.11，同样命令为 uvicorn app.main:app --port 8000。实际端口由 PID 46284 占用，存在版本/工作目录来源不明的争用。
- Redis：PID 4680，监听 6379。
- 项目 .env 的 DATABASE_URL 指向 127.0.0.1:15432/printfilm，但 15432 当前没有监听；无法证明 8000 服务使用的是可安全隔离的该目标库。
- /api/health 返回 200、任务调度器/轮询器健康，但同时返回 ark_mock:false。这与新商业布局中无条件显示“当前为本地演示”的 MockModeNote（CommercialLayout.tsx:32-54）不一致。
- 未找到 zCode 进程，也没有观察到验收期间业务源码被并发修改；无法仅凭进程列表证明 zCode 已停止修改工作区。

由于无法确认独立数据库、Redis 作用域和素材目录，我没有注册新账号、上传参考视频、创建生产、调用生成、写入预算或下载新成片。现有登录页要求账号密码，仓库文档只保留脱敏占位口令；没有使用未知真实凭据。

## 浏览器验收

实际执行：

- npx --yes --package @playwright/cli playwright-cli open http://127.0.0.1:5173/ --headed：成功打开公共首页。
- 点击“商业模板库”：实际跳转到 /auth?next=%2Fcommercial%2Ftemplates，证明未登录保护存在。
- 保存了登录页桌面和 390px 截图：
  - [auth_login_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_acceptance/screenshots/auth_login_desktop.png)
  - [auth_login_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_acceptance/screenshots/auth_login_390.png)
- 未登录商业 API 逐项返回 401；健康接口返回 200。原始结果见 [unauth_api_smoke.json](D:/AI%20Project/AIDaRen/artifacts/codex_ui_acceptance/logs/unauth_api_smoke.json)。

因此，本轮没有实际打开登录后的模板库、达人库、商品库、制作工作台、任务与作品、设置与费用六页，也没有实际验证桌面/390px 的登录后布局、加载态、空态、失败态、窄屏编辑、媒体播放、下载或 C1/C2。六页视觉验收结论为未执行，受环境隔离与凭据限制阻塞，不能写成通过。

zCode 归档截图也不能替代本轮实测：artifacts/acceptance/screenshots/ui_redesign_v2/1_templates.png 至 8_studio_flow_plan.png 八个 PNG 的 SHA-256 全部相同（EACA41D7E8A8B70F8777D0AEFAD4FF0E46B777F3830980BFE77D30D57ED051AC），文件大小也全部为 205269 字节；抽查图像内容是模板库页面。因此这些文件不能证明达人库、商品库、任务页、工作台、设置页或 390px 工作台已分别渲染。

## 关键问题

### P1-UI-01 商品选择传入错误的版本 ID

- 证据：frontend/src/features/commercial/studioPage.tsx:183-186 使用 p.current_version 作为 product_version_id。
- 后端 backend/app/api/commercial/productions.py:351-354 明确说明 latest_version_id 才是版本行 ID，current_version 只是版本号，多个商品可以同为 V1。
- 影响：C1/C2 选择商品时可能传入不存在的版本行，或因版本号重用而引用错误商品；商品 B 可能进入商品 A/其他商品的快照。该问题直接阻断“同模板换第二套商品并确认后端快照”。
- 最小修复：前端 option value 使用 latest_version_id，后端创建作品同时校验版本行存在且属于所选商品、用户/团队可见。

### P1-SEC-01 商业资源读取和创建缺少团队/用户归属校验

- 模板详情 GET /templates/{version_id} 直接 db.get 后返回结构（productions.py:165-185）；模板列表没有按 created_by/team_id 过滤（188-219）。
- 达人和商品列表直接读取全表（productions.py:280-303, 338-355）。
- 作品列表读取所有 CvProduction（productions.py:673-700）；作品详情直接 db.get，没有使用已有的归属检查（703-710）。
- 创建作品只读取 actor/voice 并做音色绑定，未校验模板版本、商品版本、达人版本、音色和资产的用户/团队归属（productions.py:373-402）。
- 参考源登记 POST /sources/by-asset/{asset_id} 直接读取指定素材，没有调用素材可读性检查（sources.py:166-185）；解析详情 GET /analyses/{run_id} 直接按 ID 返回（sources.py:255-270）。
- 影响：已登录的普通用户可枚举或读取其他用户/团队的模板结构、达人、商品、作品计划和费用元数据，也可能用跨归属 ID 组装新作品。前端 RequireAuth 不能替代服务端授权。
- 最小修复：所有列表按当前个人空间或明确 X-Team-Id 过滤；详情、创建、素材登记、分析读取统一走归属校验；跨团队请求返回 404/403，补 HTTP 级跨用户测试。

### P1-CAL-01 浏览器没有已发布模板编辑与 V2 发布路径

- 当前 HTTP 只有 POST /api/commercial/templates，用于从解析结果创建并发布 V1（productions.py:133-162）。
- templateDetail.tsx:37-58 是只读冻结快照和“使用此版本”，没有编辑或发布新版本。
- 前端模板页只显示“发布模板 V1”（templatesPage.tsx:158-166）。
- 新增测试 T3 通过直接调用 publish_template(... expected_version=2)（test_calibration_roundtrip.py:116-129），不是浏览器/HTTP 的 V2 路径。
- 影响：无法按要求在网页修改校准内容、建立 V2、刷新/离开后复用实际发布版本 ID；只能后台/服务层人为操作，不能称为端到端成立。
- 最小修复：增加带模板归属校验的草稿读取/编辑/发布 V2 API 和页面入口，保留 V1 不可变；“使用模板”必须传实际选中的 CvTemplateVersion.id。

### P1-CAL-02 校准输入没有完整的时间边界和精度规则

- 服务端创建模板仅校验可转换为整数、start >= 0、end > start（productions.py:143-150），没有校验 end_ms <= source.duration_ms、镜头连续性、零时长和跨镜头越界。
- 模板服务 _validate_draft 只校验必需字段存在（template_service.py:26-33）；直接发布 V2 可绕过 API 的时间校验。
- 前端使用 Math.round(Number(value) * 1000)（templatesPage.tsx:198-208），没有对非数字、负数、倒序、越界、空值和超出 1ms 精度提供明确提示；超精度值会被静默改变。
- 影响：8.350 秒/20.001 秒这两个正例能由测试覆盖，但非法值和“用户意图被静默取整”没有完整保护。
- 最小修复：使用明确的毫秒输入模型和源时长上限；客户端与服务端共享规则，拒绝 NaN/Infinity/负数/倒序/零时长/越界/超精度并显示可操作错误。

### P1-CAP-01 新工作台重新硬编码分辨率且没有能力档案 UI

- studioPage.tsx:112-118 发送固定 resolution_id: '768p'，全文件没有调用 getCapabilities 或展示当前能力档案。
- 旧的未使用实现 features/commercial/pages.tsx:291-303,385-401 曾从 /capabilities 选择分辨率并在 DRAFT 时明确提示；App.tsx:37-41,78-80 已改为加载新的 studioPage.tsx。
- 当前 DRAFT 能力集合静态包含 480p/768p/2k，所以该环境下不必然立即报错；但能力档案一变，页面会继续发送旧值，且用户无法完成“查看计划和能力档案中的分辨率”。这是此前硬编码修复在新 UI 中的回归。
- 最小修复：工作台加载并展示 /api/commercial/capabilities，只能从返回集合选择；能力为 DRAFT/未验证时保持明确阻断文案。

### P1-ENV-01 模式提示与实际服务状态可能相反

- CommercialLayout.tsx:40-53 无条件显示“测试模式/当前为本地演示”，而实际 /api/health 返回 ark_mock:false。
- 两个 uvicorn 争用 8000，进一步放大了前后端版本/配置不一致风险。
- 影响：用户可能把真实模式误认为安全的 Mock，或把未验证能力当成已可运行。
- 最小修复：模式徽标必须来自受保护的服务状态接口；当状态未知、真实模式或能力未验证时分别显示，不得硬编码“本地演示”。

### P1-REG-01 当前 HEAD 平台历史记录回归失败

- 命令：.venv\Scripts\python.exe -m pytest tests/test_task_executor_sessions.py tests/test_billing_wallet_lock_concurrency.py tests/test_generation_history.py tests/test_media_pricing_api.py -q
- 结果：28 passed, 1 failed, 4 warnings，退出码 1。
- 失败：tests/test_generation_history.py::test_history_restores_actual_submission_without_other_attempts_or_helper_images。
- 失败证据：接口响应仍包含 https://private.test/reference.png；服务层 generation_history.py:198-205,229 会把 public_references 的 URL 放入响应，generation_references.py:45-64 允许该主机形式。
- 归属：a851167..f3afb62 差异未修改该模块，因此不能把它归因于本轮 UI 提交；但当前 HEAD 不能作为核心回归全绿交付。
- 最小修复：按测试契约过滤不可公开的历史引用或仅返回受授权资产标识，并重跑该回归。

### P2-PRODUCT-01 商品列表响应缺少商品详情字段

- 后端商品列表只返回 id/name/current_version/latest_version_id（productions.py:338-355）。
- 前端把响应强转为含 form/specs_text/claims/allowed_actions/image_asset_ids 的 ProductFull 并渲染（libraryPages.tsx:106-112,177-190）。
- 影响：已存在商品卡片无法显示图片、审核卖点、动作和规格，图片预览也没有可用的 asset ID；商品 B 的浏览器确认无法成立。
- 最小修复：补商品详情字段或使用受保护的商品详情接口，保持列表分页和归属过滤。

### P2-UI-01 列表没有独立加载态

- 模板、达人、商品、作品列表初始化为空数组并直接显示“还没有…”；请求只在 useEffect 中发起，没有 loading 状态（templatesPage.tsx:39-58,277-280；libraryPages.tsx:20-38,123-128；workPages.tsx:24-38,104-123）。
- 影响：加载中、真实空状态和请求失败无法区分，违反验收要求。
- 最小修复：每个列表显示 loading/empty/error 三态，错误态不得同时显示空态文案。

### P2-UI-02 任务与作品页没有媒体预览

- workPages.tsx:131-168 只显示 attempt 状态、prediction ID、审核按钮和下载按钮，没有 video、audio 或图片预览。
- 影响：浏览器无法确认生成视频可播放、音轨存在、字幕版与母版对应；验收要求的播放验证只能靠下载后的外部检查。
- 最小修复：详情页使用鉴权媒体 URL/blob 提供视频播放、音频试听和明确加载/失败态；下载仍需保留。

### P2-UI-03 未保存提示只覆盖刷新/关闭，不覆盖站内离开

- 模板页和工作台用 beforeunload（templatesPage.tsx:60-66、studioPage.tsx:99-105），但站内 Link/路由切换没有确认拦截。
- 影响：修改校准或重做台词后点击其他商业页，可能静默丢失。
- 最小修复：对站内导航增加脏状态阻断，并在保存/发布后清除脏状态。

### P2-UI-04 成功/失败反馈语义不统一

- 工作台统一在 studioPage.tsx:194 以红色显示 msg，但成功生成、创建作品和错误均写入同一消息状态。
- 影响：成功与失败容易混淆，难以在浏览器记录真实结果。
- 最小修复：拆分 success/error/info 状态，成功提示使用明确语义和颜色。

## 校准和版本测试证据

独立重跑新增校准测试：

- 命令：.venv\Scripts\python.exe -m pytest tests/commercial/test_calibration_roundtrip.py tests/commercial/test_analysis_and_templates.py tests/commercial/test_no_source_reuse.py tests/commercial/test_platform_e2e.py -q
- 结果：16 passed，退出码 0。
- 完整商业域命令：.venv\Scripts\python.exe -m pytest tests/commercial -q
- 结果：156 passed, 2 skipped, 6 warnings，退出码 0。
- 两个跳过为 tests/commercial/live/test_provider_smoke.py，需要 ATLAS_API_KEY 和 COMMERCIAL_LIVE_TESTS=1；本轮没有输入密钥，也没有打开真实付费开关。

这些测试证明现有断言可通过，不能证明：

- 浏览器 HTTP 发布 V2；
- 空值/零时长/越界/超精度校准；
- 跨用户/团队模板、作品、素材权限；
- 真实商品版本 ID 进入 C2 快照；
- C1/C2 生成请求没有原片；
- 刷新/离开不重复提交；
- 下载的新文件有视频流、音频流、正确时长和新台词字幕。

新增测试本身的覆盖空洞：

- T3 直接调用 service 的 V2 发布，不走浏览器或发布 API。
- T4 没有创建作品、计划、报价和生成，只检查模板详情结构及已有 attempts。
- T5 检查列表/详情稳定，不检查实际站内离开提示。
- 没有覆盖源视频时长上限、8.350/20.001 字符边界、超精度、跨团队和版本 ID 复用。

## C1/C2 操作记录

由于不能安全确认数据库、Redis 和素材目录，以下步骤均未执行，没有伪造后台数据或用旧作品 #9 代替：

- 新建模板：未执行；无法上传/解析本地合成测试视频。
- 校准修改、重新打开、V2 发布：未执行；浏览器当前只有登录页。
- C1 选择达人 A/声音 A/商品 A、报价、批准、模拟生成、驳回、改单镜、审核、字幕校对、合成、下载：未执行。
- C2 同模板切换达人 B/声音 B 或商品 B、刷新恢复和不重复提交：未执行。
- 新生成母版、烧录字幕版和本次字幕：没有新文件可核验。
- 仓库内历史 artifacts/acceptance/screenshots/ui_redesign_v2/9_export_master.mp4 只作为旧材料检查过：ffprobe 显示 H.264 视频流和 AAC 音频流；它不是本轮新下载产物，不能作为本轮通过证据。

## 现有媒体/私有素材预览结论

源码层可确认以下实现方向：

- 原片预览在 templatesPage.tsx:68-77,169-176 使用 Bearer 下载 blob 并通过 video 控件定位。
- 图片/音频预览在 assetPreview.tsx:9-52 使用 Bearer 下载 blob，失败显示占位。
- 这些链路没有在登录后的浏览器中实测；商品列表字段缺失还会使已保存商品无法拿到图片 asset ID。
- 任务详情页没有生成媒体预览，因此播放、音轨和字幕验收未闭环。

## 测试清单

| 检查 | 命令/动作 | 结果 |
|---|---|---|
| 商业域 | .venv\Scripts\python.exe -m pytest tests/commercial -q | 156 passed, 2 skipped, 6 warnings，exit 0 |
| 校准/平台商业子集 | .venv\Scripts\python.exe -m pytest tests/commercial/test_calibration_roundtrip.py tests/commercial/test_analysis_and_templates.py tests/commercial/test_no_source_reuse.py tests/commercial/test_platform_e2e.py -q | 16 passed，exit 0 |
| 真实供应商 smoke | .venv\Scripts\python.exe -m pytest tests/commercial/live/test_provider_smoke.py -q -rs | 2 skipped，exit 0；需要授权 |
| 平台/历史回归集合 | .venv\Scripts\python.exe -m pytest tests/test_task_executor_sessions.py tests/test_billing_wallet_lock_concurrency.py tests/test_generation_history.py tests/test_media_pricing_api.py -q | 28 passed, 1 failed，exit 1 |
| 用户端 lint | npm run lint（frontend） | exit 0；有既有 warning，商业新增 assetPreview.tsx:9 warning |
| 用户端 build | npm run build（frontend） | exit 0；动态导入和大 chunk warning |
| 用户端测试 | npm test（frontend） | 160 passed, 0 failed |
| 管理端 lint | npm run lint（admin） | exit 0；warnings |
| 管理端 build | npm run build（admin） | exit 0 |
| 管理端测试 | npm test（admin） | 50 passed, 0 failed |
| API 未登录 smoke | health + 六个商业入口 | health 200；商业入口均 401 |
| 浏览器 | Playwright 首页、商业入口重定向、登录页桌面/390px截图 | 首页和登录页已执行；登录后六页未执行 |

原始日志均在 [artifacts/codex_ui_acceptance](D:/AI%20Project/AIDaRen/artifacts/codex_ui_acceptance/)。

## Git 素材与忽略规则

- 当前提交/索引仍包含大量历史运行时素材差异；本轮只检查，不清理历史，不推送。
- 当前规则可忽略 backend/app/data/、backend/static/generated/、artifacts/demo_env/ 等运行时路径；git check-ignore 对这些路径返回了规则来源。
- artifacts/codex_ui_acceptance/ 当前未被忽略，验收报告和证据会显示为未跟踪文件；这是本轮允许的交付目录，但不要将其与业务提交一起推送。
- .playwright-cli/ 也未被忽略，当前仅保存本轮快照，未加入索引。未发现新截图/日志已经进入索引。
- 没有逐项审查历史“1046 个路径”，因此不宣布历史素材全部安全或全部泄露；本轮没有复制或公开任何真实凭据/敏感内容。

## 最小修复顺序

1. 先修 P1-SEC-01 和 P1-UI-01，补跨归属测试；否则 C2 和权限验收没有意义。
2. 补浏览器可用的 V2 校准发布、源时长/精度校验和实际版本 ID 复用。
3. 将能力档案接回新工作台，修正模式状态提示，补加载/错误/媒体预览。
4. 修复 P1-REG-01，重跑平台级离线回归。
5. 在专用数据库、Redis namespace 和临时素材目录中重新启动单一版本的 API/前端，登录后逐页保存桌面/390px截图，再按 C1/C2 操作并核验新下载文件。

