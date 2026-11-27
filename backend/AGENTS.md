# 后端开发约定

- 业务接口在所属模块的 router 中定义，在 `app/main.py` 通过 `include_router(..., prefix=API_PREFIX)` 接入现有 `/api/v1`。调整接口时核对请求模型、返回结构、状态码及前端调用方。
- 功能代码跟随 `app/features/` 内同域的 schemas、models 和 services。用户、组织和项目相关逻辑先查 `app/platform/`。多个接口共享的业务逻辑放进所属服务，避免路由模块互相调用。
- 资源读写沿用同域的鉴权、组织及项目范围校验。新增批量操作时逐项验证资源归属，明确事务边界，并测试部分输入无效时的结果。并行数据库任务各用独立会话。
- 数据结构调整在 `alembic/versions/` 编写迁移，核对当前 head、模型和历史数据兼容性。先在隔离测试库验证。对已有业务库执行迁移前确认目标环境和操作授权。
- 在 backend 目录使用 Python 3.12 环境，依赖见 `requirements.txt`。按改动运行 `python -m pytest -q tests/<相关测试文件>` 或模块内测试。涉及迁移时用 `python -m alembic heads` 核对单一 head，完整检查范围见仓库根目录的 `.github/workflows/quality.yml`。
