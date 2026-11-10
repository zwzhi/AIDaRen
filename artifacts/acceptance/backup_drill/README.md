# 备份恢复演练记录（更新：2026-11-10 19:00，含密钥恢复语义澄清）

## 命令与结果
- 备份：`wsl -u postgres -- pg_dump -p 15432 -d printfilm > /tmp/printfilm_backup_HHMM.sql`（473,972 字节）
- 恢复：新建 `printfilm_restore` → `psql -f 备份.sql` → **132 张表**完整恢复，关键表行数与业务库全等
  （users=2 / cv_media_assets=11 / cv_productions=4 / cv_generation_attempts=9 / cv_exports=2 /
   cv_usage_ledger=9 / app_settings=1）→ 演练后删除恢复库

## 三类恢复的实际验证范围（分开声明，不以行数替代）
| 恢复对象 | 已验证 | 未验证/说明 |
|---|---|---|
| 数据库 | pg_dump/restore 全量演练，行数与结构一致 | — |
| 私有素材 | 目录 `backend/data/commercial/` 随库一同文件系统复制即恢复 | 未做异机恢复演练（列入 T10 正式交付前） |
| 加密密钥 | 见下节"密钥恢复语义"，单测覆盖加解密与错误密钥行为 | 真实密钥保管由管理员执行 |

## SECRET_KEY 与备份的关系（澄清）
- **含义**：SECRET_KEY（backend/.env）是 Atlas 等密文配置（app_settings.flat）的 Fernet 派生密钥。
  恢复数据库后，必须用**备份当时的同一 SECRET_KEY** 才能解出密文配置。
- **保管方式**：SECRET_KEY 本身**不进入**数据库备份、仓库、报告或日志明文；应独立受控保存
  （如密码管理器/加密 U 盘），并与数据库备份**版本对应**（换钥需记录时间与影响范围）。
  推荐做法：备份清单记录 `备份时间 + SECRET_KEY 版本号`，密钥实体存独立受控位置。
- **密钥缺失/错误时的行为（单测锁定，tests/commercial/test_secret_recovery.py）**：
  - 解密返回空串并告警降级 → 系统视作"密钥未配置"，**真实付费调用被阻断**（ProviderNotConfigured）；
  - **不回落默认密钥**（默认 dev-secret-change-me 无法解出生产密文，同等于错误密钥路径）；
  - **原密文不被破坏**，补回正确 SECRET_KEY 后即可恢复（round-trip 测试证明）。
- 验证方式：使用测试密钥完成加解密与错误密钥行为验证，**零真实 API 调用**。
