# 隔离模拟环境

本轮 harness 不停止来源不明的现有服务，也不复用现有业务数据库进行写操作。

已核实：

- 8000 的监听 PID 是 46284；其父进程是 PID 2496，两个进程分别使用项目 .venv 与系统 Python 3.11。PID 2496 由 zCode 启动 shell 继承，父命令含有启动 uvicorn 的记录。
- 15432 的 PostgreSQL 实例可连接，但本 harness 只连接维护库 postgres 创建独立数据库，再单独验证独立库连接。
- 已创建独立数据库 printfilm_ui_fix_20261111_8a63de。没有向 printfilm 业务库执行清表、迁移或初始化。
- Redis 6379 可用，隔离使用 DB 15；创建前 DBSIZE=0，没有执行 FLUSH。
- FFmpeg/ffprobe 可用。
- 测试素材和商业私有素材根目录固定为 artifacts/codex_ui_fixes/media，不使用 backend/app/data 或 backend/static/generated。

启动：

    .\docs\handoff\codex_ui_fixes\launch_isolated_api.ps1
    .\docs\handoff\codex_ui_fixes\launch_isolated_frontend.ps1

默认地址为 API http://127.0.0.1:8100、前端 http://127.0.0.1:5180。API 启动脚本从 backend/.env 读取连接凭据到进程内存，仅把数据库名、Redis DB、Mock 标记和私有素材根覆盖为本轮资源；脚本不会写出凭据文件。
