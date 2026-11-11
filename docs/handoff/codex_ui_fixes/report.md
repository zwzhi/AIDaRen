# AIDaRen UI 验收阻断修复与隔离模拟交付报告

- 项目：D:\AI Project\AIDaRen
- 验收分支：fix/codex-review-p1
- HEAD：f3afb62faf8540f9c8756bba407e9095d281b776
- 工作区：保留原验收报告与证据；本轮业务源码为未提交修改，未执行提交、推送、合并、回滚或历史重写。
- 隔离 API：http://127.0.0.1:8100
- 隔离前端：http://127.0.0.1:5180
- 隔离数据库：printfilm_ui_fix_20261111_8a63de
- 隔离 Redis：DB 15，创建前 DBSIZE=0；未 FLUSH。
- 隔离素材根：artifacts/codex_ui_fixes/media
- 外部供应商：本地 Mock；ark_mock=true、commercial_mock_mode=true、付费执行关闭。

## 已修复的问题

### P1-UI-01 商品版本 ID

工作台现在使用商品列表返回的 latest_version_id；后端校验版本行存在、属于对应商品且在当前用户/团队范围内。隔离数据中两款商品都为 V1，但版本行分别为 1 和 2：

- 商品 A：product_version_id=1，图片资产 4。
- 商品 B：product_version_id=2，图片资产 5。

C1 作品使用商品 A，C2 作品使用商品 B；生成尝试快照中的 product_image_asset_ids 分别为 [4] 和 [5]。

### P1-SEC-01 归属权限

模板、达人、商品、作品、参考源、解析记录和绑定素材均加入个人/团队读取校验。创建作品时同时校验模板版本、商品版本、达人版本、音色及素材归属。团队成员读写路径使用团队成员资格检查，个人资源仍只允许所有者或管理员访问。

新增/重跑了商业域权限相关测试、资产绑定和平台链路。未把客户端传入的 team_id 当作授权依据。

### P1-CAP-01 能力档案

当前加载的 studioPage 从 /api/commercial/capabilities 读取分辨率，页面显示：

- capability_version=draft-2026-11-10
- DRAFT，未完成真实契约验证
- 2k / 480p / 768p

创建作品使用实际选择值 480p；代码没有再硬编码 768p。能力读取失败或选项失效时创建按钮阻止提交。

### P1-CAL-01 / P1-CAL-02 V2 校准

新增 POST /api/commercial/templates/{template_id}/versions，V1 保持不可变，发布后用实际 CvTemplateVersion.id 复用。

浏览器实际完成：

1. 打开 V1 详情。
2. 进入编辑。
3. 修改画面描述、台词模板和时间边界。
4. 点击“保存草稿”。
5. 点击“保存并发布 V2”。
6. 重新读取 V2 并从模板库使用 V2。

浏览器提交的时间边界包含 8.350 秒和 20.001 秒；HTTP 回读为 8350ms 和 20001ms。V1 回读仍保留旧描述、旧台词和旧时间。

时间规则已统一到 API 与 template_service：整数毫秒、非负、结束大于开始、不重叠、不超过源视频探测时长。前端对空值、非有限数和超过 3 位小数给出明确提示，草稿同时保存在当前浏览器，并对刷新和站内导航离开提示。

### P1-REG-01 历史生成记录

generation_references.enrich_references 现在只返回映射到当前用户/团队可读资产的引用；未经授权的历史原始 URL 被移除，不按 private 字符串特判。

此前失败的 generation_history 测试已通过。

### P2 页面状态、模式与媒体

- 模板、达人、商品、作品列表区分 loading、error、empty。
- 商品列表返回页面需要的图片、规格、卖点、禁用词和允许动作。
- 顶部模式徽标读取 /api/health，隔离环境显示“本地模拟”；无法读取时显示“运行模式未确认”。
- 任务详情提供受控 GET /api/commercial/attempts/{attempt_id}/preview；前端用 Bearer 下载 blob 后播放。实测 3 个 C1 片段的 video.readyState=4，duration 分别为 9、12、15 秒。
- 任务页提供字幕草稿编辑与烧录按钮；烧录版是独立副本，母版不改。
- 成功、错误和处理中消息区分显示。
- 重做台词最终请求接线已修复：浏览器请求体和生成请求体均出现 dialogue_override=C1接线最终确认；数据库尝试 #10 的 approved_dialogue 为该新台词。

## 浏览器 C1/C2 证据

隔离账号（仅本地测试库）：

- 主账号：ui.fix.owner@example.com
- 密码：（隔离主账号口令·仅本地测试库）
- 普通成员：ui.fix.member@example.com
- 密码：（隔离成员口令·仅本地测试库）
- 隔离账号：ui.fix.other@example.com
- 密码：（隔离他人口令·仅本地测试库）
- 管理员：ui.fix.admin@example.com
- 密码：（隔离管理员口令·仅本地测试库）

C1：

- 模板 V2、达人 A/音色 A、商品 A、480p。
- 浏览器完成创建、适配、计划、报价、三镜 Mock 生成。
- 在任务页播放了生成片段。
- 驳回 U001，回到工作台填写新台词并重新报价、重做。
- 重做后尝试历史保留，最终新尝试通过审核。
- U002/U003 和 U001 新尝试通过审核。
- 浏览器完成完整合成、字幕校对、烧录和双下载。
- 最终导出 #3 选择了 attempt #10、#2、#3；SRT 首条为 C1接线最终确认。

C2：

- 同一模板 V2、达人 B/音色 B、商品 B、480p。
- 浏览器计划中的台词和动作显示商品 B 独立卖点/动作。
- 作品 #2 的 production 快照为 template_version_id=2、actor_version_id=2、voice_profile_id=2、product_version_id=2。
- 3 个生成尝试均使用商品 B 图片资产 [5]，没有重新解析原片。
- 浏览器完成审核、完整合成和 C2 母版下载。

数据库回读摘要：

- production 1：template_version_id=2、actor_version_id=1、voice_profile_id=1、product_version_id=1、status=composed。
- production 2：template_version_id=2、actor_version_id=2、voice_profile_id=2、product_version_id=2、status=composed。
- production 1 的最终重做 attempt #10：status=GENERATED/随后审核通过，product_image_asset_ids=[4]，approved_dialogue=C1接线最终确认。
- production 2 的 attempts #5–#7：product_image_asset_ids=[5]。

## 新截图

桌面截图（实际浏览器桌面宽度 1689 CSS px）：

- [templates_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/templates_desktop.png)
- [actors_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/actors_desktop.png)
- [products_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/products_desktop.png)
- [studio_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/studio_desktop.png)
- [tasks_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/tasks_desktop.png)
- [settings_desktop.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/settings_desktop.png)

窄屏截图使用 390px viewport；带滚动条的全页图像实际内容宽度为 375px，已按实际尺寸记录：

- [templates_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/templates_390.png)
- [actors_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/actors_390.png)
- [products_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/products_390.png)
- [studio_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/studio_390.png)
- [tasks_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/tasks_390.png)
- [settings_390.png](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/screenshots/settings_390.png)

12 张新截图 SHA-256 全部各不相同。旧 zCode 八张同哈希截图保留在原目录，未作为本轮证据使用。

## 媒体产物

新下载产物：

- [C1 最终母版](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/outputs/c1_final_master.mp4)
- [C1 最终字幕版](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/outputs/c1_final_subtitled.mp4)
- [C2 母版](D:/AI%20Project/AIDaRen/artifacts/codex_ui_fixes/outputs/c2_master.mp4)

FFprobe：

- C1 母版：H.264 视频 + AAC 双声道音频，约 34.52 秒。
- C1 字幕版：H.264 视频 + AAC 双声道音频，约 34.52 秒。
- C2 母版：H.264 视频 + AAC 双声道音频，约 34.52 秒。
- C1 SRT 全局时间码为 0–8350ms、8350–20001ms、20001–34416ms，并包含本次新台词。

音频来自本地 Mock 提示音，只证明音频处理链路；不代表真实达人音色克隆或口型验证。

## 测试与构建

最终重跑：

- 商业域：158 passed, 2 skipped, 6 warnings，退出码 0。
- 校准 HTTP 测试：7 passed。
- C1/C2 商业 E2E 与资产绑定：9 passed。
- 历史生成记录回归：1 passed。
- Python compileall：通过。
- 前端测试：163 passed，退出码 0。
- 前端 build：通过；保留动态导入和大 chunk warning。
- 管理端此前 lint/build/test 均通过，本轮未修改管理端。
- 两个真实供应商 smoke 仍 skipped，需要 ATLAS_API_KEY 和 COMMERCIAL_LIVE_TESTS=1；未输入真实密钥，未进行真实付费调用。

原始日志位于 artifacts/codex_ui_fixes/logs/。

## 剩余限制

- 当前服务仍是本地 Mock，真实供应商契约、音色克隆、口型和真实费用没有验证。
- 隔离数据库是本地创建的新库，未连接或清理 printfilm 业务库。
- Redis 使用 DB15，未清空其他 Redis DB。
- 本轮没有处理历史 Git 素材和旧模拟预留。
- 当前源码修改仍未提交、未推送、未合并。

## 运行模式定点复核（2026-11-11）

同一隔离环境的 5180 前端请求实际命中 8100 API（VITE_API_BASE=http://127.0.0.1:8100）。

- GET /api/health：ark_mock=true，任务仅走本地 Mock。
- 主账号 GET /api/admin/settings/models：403；页面现在显示“运行模式未确认（需管理员权限）”和“付费总开关：未确认”，不再把 provider=null 推断成真实模式。
- 管理员 GET /api/admin/settings/models：commercial_mock_mode=true、commercial_paid_execution_enabled=false、commercial_verified_models 为空、has_atlas_api_key=false。
- 本隔离 API 的环境覆盖为 ARK_MOCK=true、COMMERCIAL_MOCK_MODE=true、COMMERCIAL_PAID_EXECUTION_ENABLED=false；未配置 Atlas 密钥。

因此当前生成路径是本地 Mock，真实付费执行关闭，不会发生外部模型调用。设置页旧截图中的“模式：真实”是普通账号无权读取管理员配置时的前端回退问题，已做最小修复并在同一账号同一环境刷新验证。

同一主账号刷新后的列表为：模板 1 个、已发布 V1/V2 两个版本；作品 2 条，均为 composed。早期桌面截图中的 V1/空作品与后来的窄屏截图中的 V2/两条作品来自不同采集时点（V2、C1、C2 创建之前/之后），不是列表权限或数据回退问题。当前回读证据见 artifacts/codex_ui_fixes/logs/owner_current_lists.json 和 mode_status_same_environment.json。

