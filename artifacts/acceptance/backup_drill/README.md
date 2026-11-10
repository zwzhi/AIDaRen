# 备份恢复演练记录（2026-11-10 18:33）

## 命令
- 备份：`wsl -u postgres -- pg_dump -p 15432 -d printfilm > /tmp/printfilm_backup_HHMM.sql`（本次产物 473,972 字节）
- 恢复：新建 `printfilm_restore` 库 → `psql -f 备份.sql` → 校验行数 → 演练后删除

## 结果（恢复库 == 业务库）
- users=2（demo admin + viewer）；cv_media_assets=11；cv_productions=4；cv_generation_attempts=9；cv_exports=2；cv_usage_ledger=9；app_settings=1（含加密字段）
- 全库 132 张表完整恢复

## 加密密钥管理（重要）
- Atlas 等密钥以 SECRET_KEY 派生 Fernet 加密存于 app_settings.flat。
- **SECRET_KEY（backend/.env）必须与数据库备份一起安全保存**；丢失后密文不可解，
  系统降级为"密钥未配置"（启动仅告警不致命），需管理员重新录入密钥。
- 密钥本身绝不进入数据库备份明文、仓库或报告。

## 素材目录
- `backend/data/commercial/`（私有素材/输出/导出）需与数据库一同备份：文件系统直接复制即可。
