# 浏览器完整流程验证记录（Codex 修复轮 · 2026-11-10）

环境：真实开发栈（前端 :5173 / 后端 :8000 修复版代码 / PostgreSQL 业务库 / Redis）。
方式：Chrome DevTools MCP 实操页面（DOM 快照取证；MCP 工作区限制无法落盘截图，
以文本快照 + 最终成片文件 + ffprobe 为证）。**仅新增记录，未改动既有作品 #1-#4 数据。**

账号：demo@printfilm-demo.com（管理员；演示凭据，沿用现有）。

## 步骤与证据

| # | 步骤 | 结果 | 证据要点 |
|---|---|---|---|
| 1 | 登录 | ✅ | 默认落点 /commercial/templates |
| 2 | 模板库上传 6s 参考视频（带音轨 testsrc+sine） | ✅ | 解析 completed·3镜头；发布「Codex修复验证模板 V1」 |
| 3 | 达人库：形象图+音色样本上传 → 创建 | ✅ | 「Codex验证达人 V1 + 音色#3（长期）」 |
| 4 | 商品库：商品图+卖点创建 | ✅ | 「Codex验证商品 V1」卖点=Codex验证卖点：八小时长效贴敷 |
| 5 | 工作台：能力档案驱动选项 | ✅ | 分辨率下拉={2k,480p,768p} 默认 768p，**无 720p**（P1-1）；DRAFT 提示可见（capability_version=draft-2026-11-10，"不代表已具备真实生成能力"） |
| 6 | 创建作品 #5（6s 模板）→ 适配后计划 | ✅ 正确阻断 | DialoguePacing 守卫：S01 区间 1.8s < 台词 2250ms，提示缩短/延长/合并，不自动加速 |
| 7 | 创建作品 #6（30s 模板）→ 适配 | ⚠️ 发现缺陷 | 台词显示 P1 商品卖点 → 定位为商品下拉传版本号而非版本ID（既有缺陷，见修复 4d31c74） |
| 8 | 创建作品 #7 → 适配+计划 | ✅ | 三单元 U001(9s)/U002(15s)/U003(6s)，台词=本商品卖点（商品版本修复生效） |
| 9 | 三单元报价+生成（Mock 驱动） | ✅ | attempt #14/#15/#16 GENERATED |
| 10 | 任务页审核 3/3 通过 | ✅ | REVIEW_APPROVED ×3 |
| 11 | 工作台 U003 单镜重做改台词「温和配方敏感肌也能放心用」 | ✅ | 新报价 $0.0900（模拟价）→ 新尝试 #17 GENERATED，旧 #16 保留（P1-8 浏览器闭环） |
| 12 | 任务页审核 #17 → 合成 | ✅ | 导出 #5 完整成片 30.0s |
| 13 | 字幕检查 | ❌→✅ | 发现仅 1 段字幕（0-6s）→ 定位 P1-3 重构时字幕块缩进缺陷 → 修复（4d31c74）→ 重合成导出 #6：**三段字幕 0-9/9-24/24-30s，U003 段=新台词，U001/U002=商品卖点** |
| 14 | 烧录字幕 | ✅ | 独立副本，母版未动 |
| 15 | 双下载（母版 840KB / 烧录版 509KB，页面 fetch 流） | ✅ | 均为合法 mp4（ftyp 头） |

## 成片物证（归档于 artifacts/codex_fixes/）

- `codex_fix_master_30s.mp4`：h264 + **aac 音轨**，30.023s=计划采用区间（9+15+6）
- `codex_fix_subtitled_30s.mp4`：烧录版，音轨保留
- 音频非静音：mean_volume -24.1 dB / max_volume -15.1 dB（volumedetect）

```
ffprobe codex_fix_master_30s.mp4    → stream h264 video + aac audio · duration 30.023220
ffprobe codex_fix_subtitled_30s.mp4 → stream h264 video + aac audio · duration 30.023220
ffmpeg -i master -af volumedetect   → mean_volume: -24.1 dB · max_volume: -15.1 dB
```

## 导出 #6 字幕全文（SRT）

```
1
00:00:00,000 --> 00:00:09,000
Codex验证卖点：八小时长效贴敷

2
00:00:09,000 --> 00:00:24,000
Codex验证卖点：八小时长效贴敷

3
00:00:24,000 --> 00:00:30,000
温和配方敏感肌也能放心用
```

## 本轮浏览器实测新发现并已修复的两个缺陷

1. **商品版本 ID 错配**（既有缺陷）：`list_products` 只返回版本号（多商品皆为 1），
   前端把它当版本行 ID → 换商品实际命中第一个商品版本（卖点/图片错配）。
   修复：返回 `latest_version_id`，前端改传该值（4d31c74）。
2. **多 selection 字幕只出最后一段**（P1-3 重构引入）：字幕块移出 selection 循环。
   修复：移回循环内逐段生成（4d31c74）+ 回归测试
   `test_multi_selection_subtitles_cover_every_selection`。

## 旧无声验收文件状态

`artifacts/acceptance/export-*-30s.mp4`（Phase2/3/4 产物，无声）**标记失效**：
仅作历史证据保留，不再代表当前合成链路能力；新的可核验产物以上方两文件为准。
