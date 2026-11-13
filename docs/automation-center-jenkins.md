# 自动化中心 Jenkins 接入

自动化中心复用现有执行、Allure 报告、历史趋势、回调幂等和飞书通知。Jenkins API Token 由服务端 Fernet 加密保存；Jenkins 执行通过统一 CI Provider 管理。

## 部署前准备

1. Jenkins 使用受支持的 LTS/JDK 组合，并安装 Pipeline、Git、Credentials Binding 插件。
2. 配置一个只供自动化使用的 Jenkins 服务账号。最少授予 Overall/Read、Job/Read、Job/Build、Job/Cancel；Folder 权限沿目录继承。
3. 以该账号创建 API Token。平台使用 HTTPS Basic Auth；Jenkins 若启用 CSRF crumb，客户端会在 POST 被拒绝后读取 crumb 并重试一次。
4. Jenkins Agent 安装 Python 3、`venv`、`zip`、Allure CLI，并具备访问仓库、依赖源和平台 HTTPS 回调地址的能力。
5. Jenkins Controller 需能访问平台配置的 Git 仓库；平台后端需能访问 Jenkins Base URL。两端都应使用可验证的 TLS 证书。
6. 平台设置 `PUBLIC_APP_BASE_URL` 为 Jenkins Agent 可访问的 HTTPS 地址，并配置稳定的 Fernet 加密密钥（`MODEL_CONFIG_ENCRYPTION_KEY`，或项目现有的 `SECRET_KEY`）。密钥轮换前需先迁移已保存凭证。

Jenkins URL 只允许 HTTPS，端口为 443、8443 或 9443。公网地址默认可用；内网地址需由项目管理员在 CI 接入表单中显式授权。重定向不会跟随到其他站点。

## 配置 CI 接入

在自动化中心的 **CI 接入管理** 创建 Jenkins 配置：

- 填写实例名称、Base URL、Username 和 API Token。
- 填写回调密钥。该值由管理员生成并保存；平台只显示是否已配置。
- 若 Jenkins 位于内网，勾选内网授权。这个选项要求项目管理员权限。
- 测试连接时填写一个可执行 Jenkins Job 路径，例如 `qa/regression/nightly`。

回调密钥不会再次通过查询 API 返回。将创建时使用的同一个值保存到 Jenkins Credentials：类型 **Secret text**，默认 ID 为 `test-platform-automation-callback-secret`。不要把密钥放进 Git、构建参数或 Jenkinsfile。

API Token 单独保存到平台配置的密文凭据表；修改时填写新 Token，留空会继续使用旧值。删除配置会进入平台回收站，硬删除配置后其 Jenkins 凭据随外键级联清理。

## 创建 Jenkins Job

1. 将本仓库根目录的 [Jenkinsfile](../Jenkinsfile) 和 `scripts/automation_callback.py`、`scripts/automation_run_tests.py` 放入测试仓库。
2. 创建 **Pipeline** Job，Job 路径可包含多级 Folder。
3. 使用 Pipeline script from SCM，配置仓库凭据 ID `automation-codeup-readonly`。凭据应限定在仓库域；不要把账号密码写进仓库 URL。
4. 更新 Jenkinsfile 中的 `AUTOMATION_CALLBACK_ORIGIN` 为平台准确的 HTTPS Origin，并按组织情况更新 Codeup 仓库 Host allowlist。
5. 将 Allure CLI 安装到 `python-allure` Agent 标签对应的节点。测试依赖中应包含 `pytest` 和 `allure-pytest`。
6. 在 Jenkins 手动运行一次 Job，使 Jenkins 读取 Jenkinsfile 并注册参数，然后在平台查询 Job 参数。
7. Jenkinsfile 使用 `disableConcurrentBuilds()`，并且不会自动重试 pytest，避免非幂等测试重复执行。需要并发时，应由 Job 管理员确认测试环境允许并发，再移除此选项。

平台触发时会传递以下参数：

`REPOSITORY_URL`、`REPOSITORY_ID`、`BRANCH_NAME`、`TEST_ENV`、`PYTEST_ARGS`、`TEST_TAGS`、`TEST_SCOPE`、`BUILD_TIMEOUT_MINUTES`、`AUTOMATION_EXECUTION_ID`、`AUTOMATION_PROJECT_ID`、`AUTOMATION_CALLBACK_KEY`、`AUTOMATION_CALLBACK_URL`、`AUTOMATION_HISTORY_URL`、`AUTOMATION_PROVIDER`。

Job 中若配置额外的平台参数，也要在 Jenkins Job 参数定义里声明同名参数。pytest 参数由 `automation_run_tests.py` 通过参数白名单检查，再以 argv 数组执行，不经过 Shell 拼接。测试范围仅支持仓库内相对路径。

## 自动化项目与报告闭环

1. 在平台创建自动化项目，选择 Jenkins 接入；通过 Folder 逐级选择 Job，也可手动填写路径。
2. 填写仓库 HTTPS/SSH 地址、默认分支、环境、pytest 参数、标签、测试范围、超时和飞书策略。
3. 执行后先保存 Jenkins Queue ID，平台状态保持 `PENDING`。分配 Executor 并获得 Build Number 后转为 `RUNNING`。
4. Jenkinsfile 在执行前尝试下载上一份 Allure history；没有历史时继续首轮运行。
5. `post { always }` 会收集 HTML、Allure Results 和 pytest 日志，并用 `AUTOMATION_CALLBACK_SECRET` 对平台原有 HMAC 协议签名。回调最多重试四次，使用稳定幂等键。
6. 报告压缩包在根目录包含 `index.html`。平台执行既有 Zip Slip、文件数、解压大小和压缩比检查；相同回调不会重复生成报告。
7. 回调成功后，平台展示报告、执行统计和 Jenkins Build 链接，并按自动化项目策略发送飞书通知。Console 日志由后端经 Jenkins API 读取并截断、脱敏。

## 数据库升级

在发布版本中执行 Alembic 迁移：

```bash
cd backend
alembic upgrade head
```

迁移 `0082` 将旧接入和执行记录标记为 `YUNXIAO`，新增 Jenkins 独立凭据表、执行平台快照、Queue/Build 字段及多级 Job 长度。原有云效字段、历史执行、报告和外键继续保留。

## 网络要求

- 平台后端 → Jenkins Controller：HTTPS Remote API、Job/Queue/Build/Console API。
- Jenkins Agent → 平台：HTTPS history GET 与签名 multipart callback POST。
- Jenkins Controller/Agent → Git 仓库和依赖源：按项目 Pipeline 配置开放。
- 平台与 Jenkins 都不需要开放入站公网端口给对方；由部署网络或内网路由提供双向出站访问。

## 排查

| 现象 | 检查项 |
| --- | --- |
| 连接测试返回 401 | 确认服务账号、Username 和 API Token；重建 Token 后在平台更新。 |
| 连接测试返回 403 | 检查 Overall/Read、Job/Read 权限，以及 Jenkins crumb 配置。 |
| Job 查询 404 | 确认 Folder 路径大小写、Job 名称、Context Path 和账号可见权限。 |
| Build 触发成功但一直排队 | 检查 Agent 标签、Executor 数量、Job 锁和 Jenkins Queue 的 `why`。 |
| 构建运行但平台未更新 | 检查 `PUBLIC_APP_BASE_URL`、平台 HTTPS 证书、Agent 到平台的出站网络和回调日志。 |
| 回调签名失败 | Jenkins Secret text 与平台创建时输入的回调密钥必须完全一致；检查系统时间同步和重复请求是否超出五分钟签名窗口。 |
| Allure 报告无法打开 | 检查 Agent 是否安装 Allure CLI、`allure-report.zip` 根目录是否有 `index.html`，以及报告是否超过平台大小限制。 |
| 报告上传失败 | 查看 Jenkins `post` 日志和归档的 `allure-report.zip`、`allure-results.zip`、`run.log`；平台回调不会无限重试。 |

## 上线验证清单

使用真实 Jenkins 环境执行一次：连接测试、Job/参数查询、平台触发、Queue 到 Build 状态同步、取消任务、pytest 运行、Allure history 继承、失败情况下的 post 回调、报告在线打开/下载、Console 日志读取和飞书通知。Mock HTTP 测试不能替代这一步。
