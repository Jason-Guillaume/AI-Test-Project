# 自动化中心 Jenkins 接入与运维

Automation Center 通过统一 CI Provider 管理 Jenkins 和云效执行。Jenkins API Token 使用平台 Fernet 密文保存；Queue/Build 状态进入现有执行记录；Allure、HMAC 回调和飞书通知沿用自动化中心的既有闭环。

## 部署前准备

### Jenkins Controller 和账号

- 使用受支持的 Jenkins LTS/JDK 组合，启用 Pipeline、Git、Credentials Binding 插件。按团队策略安装 Allure Jenkins 插件；流水线自身调用的 Allure CLI 仍需在 Agent 上安装。
- 为平台建立专用 Jenkins 服务账号，至少授予 Overall/Read、Job/Read、Job/Build、Job/Cancel。Folder 和 Job 权限按最小范围授权。
- 通过该账号创建 Jenkins API Token。平台使用 HTTPS Basic Auth；发生 CSRF 403 时会请求 crumb 并重试一次。
- 只使用 HTTPS 和受信任证书。平台接受 443、8443、9443 端口；内网地址必须由项目管理员显式启用内网授权。请求不跟随跨站重定向，且不读取系统代理配置。

### Agent

将下列工具放在带有 `python-allure` 标签的 Agent：

- Python 3、`venv`、`zip`、Allure CLI。
- 仓库 `requirements.txt` 中列出的 pytest 和 `allure-pytest` 等依赖。
- 到代码仓库、Python 包源和平台 HTTPS 回调地址的出站连接。

Jenkins Controller/Agent 需要读取测试仓库；平台后端需要访问 Jenkins Base URL。将平台 `PUBLIC_APP_BASE_URL` 配置为 Agent 可以访问且证书有效的 HTTPS 地址，并使用稳定的 Fernet 密钥（`MODEL_CONFIG_ENCRYPTION_KEY`，或项目当前使用的 `SECRET_KEY`）。密钥轮换前须迁移已保存凭据。

## 创建 CI 接入

在自动化中心的 **CI 接入管理** 新建 Jenkins 配置：

1. 填写实例名称、HTTPS Base URL、Username 和 API Token。
2. 填写平台回调密钥。密钥只在创建请求中提交，平台之后只显示配置状态。
3. 若 Jenkins 在内网，勾选管理员授权的内网访问。
4. 用一个可执行 Job 路径测试连接，例如 `qa/regression/nightly`。

将创建时的同一个回调密钥保存到 Jenkins Credentials，类型选择 **Secret text**，默认 ID 为 `test-platform-automation-callback-secret`。把 Jenkins API Token 保存于平台的加密凭据表；更新时填写新 Token，留空会保留原凭据。不要把 Token、回调密钥或仓库密码提交到 Git、Jenkinsfile 或普通构建参数。

## 配置 Job 和参数

将仓库根目录的 [Jenkinsfile](../Jenkinsfile)、`scripts/automation_callback.py` 和 `scripts/automation_run_tests.py` 放入测试仓库。创建 Pipeline Job，使用 Pipeline script from SCM；仓库凭据使用 Jenkins Credentials ID `automation-codeup-readonly`，禁止把账号密码嵌入仓库 URL。按实际环境调整 Jenkinsfile 中的平台 HTTPS Origin、Codeup Host allowlist、Credentials ID 和 Agent 标签。

第一次由管理员手动运行 Job，让 Jenkins 注册 Pipeline 参数，再在平台按 Folder 逐层选择 Job。平台传递以下保留参数：

`REPOSITORY_URL`、`REPOSITORY_ID`、`BRANCH_NAME`、`TEST_ENV`、`PYTEST_ARGS`、`TEST_TAGS`、`TEST_SCOPE`、`BUILD_TIMEOUT_MINUTES`、`AUTOMATION_EXECUTION_ID`、`AUTOMATION_PROJECT_ID`、`AUTOMATION_CALLBACK_KEY`、`AUTOMATION_CALLBACK_URL`、`AUTOMATION_HISTORY_URL`、`AUTOMATION_PROVIDER`。

自定义参数可以使用其他名称。参数名不区分大小写地检查平台保留字段；名称限 64 个字符，最多 50 项（为平台的 14 个参数保留 Jenkins 的总参数上限空间），值限 2000 个字符。命令控制字符和分隔符会被拒绝。包含 Token、Secret、Password、Credential、API Key 等词的自定义参数会过滤，不写入执行详情；此类值应存放为 Jenkins Credentials 并由受控 Pipeline 读取。

保留字段还覆盖 Jenkinsfile 的回调凭据/状态变量和 Jenkins 自带的 Build、Job、Workspace、Node 及 Shell 环境变量，避免自定义参数改变流水线运行环境。

pytest 参数由脚本白名单验证后作为 argv 执行，不会拼接进 Shell 命令；测试范围必须是仓库内的相对路径。

## 执行、状态和超时

平台、Schema、Service、Provider 和 Jenkins `BUILD_TIMEOUT_MINUTES` 使用同一个执行上限：60 至 10,800 秒（3 小时）。Jenkinsfile 全 Pipeline 的 300 分钟上限覆盖 Agent 阶段、依赖安装、报告处理和回调；单独的 checkout、依赖安装、history、报告和回调也有各自限时。

正常状态流：

```text
PENDING -> RUNNING -> SUCCESS / FAILED
                   -> CANCELLED / TIMEOUT
```

- Jenkins 触发成功后先保存 Queue ID，状态为 `PENDING`。Queue 分配 Executor 并返回 Build Number 后状态变成 `RUNNING`。
- Jenkins `SUCCESS` 对应平台 `SUCCESS`；`FAILURE` 和 `UNSTABLE` 对应 `FAILED`。未知的已结束 Build 和未被平台请求取消的 `ABORTED` 都按 `FAILED` 处理。
- Queue 404 时，平台只在该 Job 最近 50 条 Build 中按相同 Queue ID 精确匹配，不会把“最新 Build”猜成当前执行。Queue 长时间缺失时，10 分钟后结束为失败；已记录的取消请求会在无 Build 可确认后结束为取消。
- 取消 API 只登记停止请求并调用 Jenkins Stop/Queue Cancel。平台保持请求中的状态，继续轮询；只有观察到 Jenkins 终态后才清除停止请求。重复取消具有幂等性。
- 平台超时立即记为 `TIMEOUT`，保存超时原因并尽力停止 Jenkins。后续轮询持续确认外部 Build 终止；Console 日志仍可通过 Jenkins API 查询。

## Allure 失败闭环和回调

pytest 的退出码通过 `returnStatus` 保存；测试失败不会提前中断流水线。`run.log` 在子进程运行时持续写入并 flush。Jenkins `post { always }` 对已有 `allure-results` 尝试生成 HTML，再分别打包 HTML、Results 和日志。即使 Allure CLI 缺失、HTML 生成失败或没有 Results，也会继续尝试上传可用 Results、日志和执行元数据。

回调元数据同时携带平台执行状态和 Jenkins Build Result。平台保留明确的 `CANCELLED`/`TIMEOUT` 原因；未知 `ABORTED` 按失败处理；测试用例失败会将流水线结果修正为失败。回调请求使用 Jenkins Job/Build 的稳定幂等键，最多尝试 4 次，单次请求超时 20 秒；流水线回调阶段最多运行 90 秒。报告上传成功后，同一执行只保留一份报告并触发既有飞书通知。

## 数据库升级和回滚

当前迁移链为：

```text
0081 -> 0082_api_response_keys -> 0083 -> 0084 -> 0085_automation_jenkins_provider
```

发布时在后端执行：

```bash
cd backend
alembic upgrade head
```

旧版本曾有 Jenkins 迁移也占用 revision `0082`。新 `0085` 会检查实际表结构，补齐 API response key 和 Jenkins 列/表/索引，因此可兼容已打过旧 `0082` 标签但缺少其中一侧结构的数据库；重复执行升级不会重复添加字段。升级前仍应先做数据库备份，并确认 Alembic head 为 `0085`。

`0085` 的 downgrade 会在发现 Jenkins 配置、凭据、Queue/Build 记录或超过旧长度限制的 Job 路径时拒绝执行，不会静默删除 Jenkins 数据。需要回滚时先迁移或清理 Jenkins 数据并单独审查回滚计划；回滚不等于恢复备份。

## Jenkins Pipeline 语法校验

本地可先运行静态闭环检查；在可访问目标 Jenkins 的环境配置以下环境变量后加 `--jenkins`，运行 Jenkins Declarative Linter。凭据只通过环境变量传递，脚本不会打印 Token：

```bash
python scripts/jenkins_pipeline_lint.py
export JENKINS_BASE_URL='https://jenkins.example.com'
export JENKINS_USERNAME='automation-bot'
export JENKINS_API_TOKEN='从凭据管理器注入'
python scripts/jenkins_pipeline_lint.py --jenkins
```

没有 Jenkins 地址和凭据时，不要把静态检查当作 Jenkins Linter 或真实执行通过。

## 真实环境联调清单

| 场景 | 验收条件 |
| --- | --- |
| Jenkins 连接和认证 | API Token 认证成功，TLS 验证通过 |
| 根目录和多级 Folder | Folder 浏览、Job 查询和参数读取正常 |
| 平台触发 | 返回唯一 Queue ID，执行记录只创建一次 |
| Queue/Build 同步 | 依次展示 `PENDING`、`RUNNING` 和正确终态 |
| pytest 成功 | Jenkins 与平台均为 `SUCCESS`，Allure 可查看 |
| 部分/全部测试失败 | 两端为 `FAILED`，可查看 Results；HTML 生成成功时可在线查看 |
| Allure CLI 缺失或生成失败 | Jenkins 仍回调日志和可用 Results，执行不会伪报成功 |
| 排队取消/运行取消 | Stop 请求可重试；确认 Jenkins 终止后平台为 `CANCELLED` |
| 超时 | 平台为 `TIMEOUT`，Jenkins 尽力终止，保留 Console 日志 |
| 重复回调/重复发现 | 同一 Build 只有一条执行记录、一份报告 |
| 外部手动 Build | 新 Build 可被发现，重复发现更新原记录 |
| 云效执行 | 既有配置、执行历史和报告正常 |

真实验收应使用受限的 Jenkins 测试 Job 和安全注入的凭据。当前本地自动化环境没有 Jenkins 端点或凭据，真实 Jenkins Linter 和上述联调需要在部署环境完成；MockTransport、数据库回归和浏览器模拟均不替代真实 Jenkins 验收。

## 排查

| 现象 | 检查项 |
| --- | --- |
| 连接测试 401/403 | 检查服务账号、Token、Overall/Read、Job/Read 和 crumb 插件权限 |
| Job 查询 404 | 检查大小写、Folder 路径、Jenkins Context Path 和 Job 可见权限 |
| 运行长期排队 | 查看 Jenkins Queue `why`、Agent 标签、Executor 和 Job 锁；Queue 丢失后按 Queue ID 精确恢复 |
| 平台未更新 | 检查 `PUBLIC_APP_BASE_URL`、证书、Agent 出站网络、callback key 与 Jenkins Secret Text 是否一致 |
| 回调签名过期 | 同步 Jenkins/平台系统时间；回调签名有效窗口为 5 分钟 |
| 报告只有 Results 没有 HTML | 检查 Agent 的 Allure CLI 和 Jenkins post 日志；原始 Results 仍会尝试上传 |
| 回调 4 次仍失败 | 查看本次 Jenkins 归档和日志；恢复平台连接后按运维流程重新投递，不要改用新的执行幂等键 |
