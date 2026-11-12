# 云效 Allure 自动化测试中心

## 1. 架构审计

现有平台已经有三套相邻能力，但都不能直接拿来跑外部仓库里的 pytest：

- 测试计划执行器只跑平台内的用例，结果进入 `TestRun` / `CaseExecution`。它不拉取 Codeup，也不生成 Allure HTML。
- 统一任务和 Agent 负责平台内的规划、生成和工具调用。云效流水线不进入这条执行链。
- `TestReport` 只保存汇总、风险和 AI 总结，明细仍读执行记录。它没有 HTML 文件、版本目录和在线 Allure 视图。
- 飞书已经有 `NotificationChannel` 密文配置和 `FeishuNotificationService`。卡片内容由调用方组装，传输、签名和发送审计可以复用。
- 文件持久化已有 ASR 产物目录这种“数据库存路径、磁盘存正文”的模式。当前没有 OSS。
- 权限继续使用业务项目的 viewer / member。跨项目访问返回 404。

因此新增独立 feature `automation_center`。它复用项目权限、Fernet 密文、飞书传输和分页契约，不复制执行引擎、报告引擎或通知系统。

## 2. 复用与数据

迁移 `0079`，接在当前 `0078` 之后。新增表：

- `automation_integration_config`：API 地址、企业 ID、令牌密文、回调标识、回调密钥密文。
- `automation_project`：仓库、默认分支、环境、pytest 参数、通知策略。
- `automation_pipeline`：云效流水线 ID。
- `automation_execution`：每次运行一条记录。`(automation_project_id, pipeline_run_id)` 在运行 ID 非空时唯一。
- `automation_report`：统计和相对目录。一次执行最多一份报告。
- `automation_artifact`：压缩包、原始结果和日志索引。
- `automation_callback_receipt`：回调幂等。
- `automation_report_grant`：报告文件短期凭据哈希。

HTML、ZIP 和日志写到 `AUTOMATION_REPORT_DIR/{业务项目ID}/{执行ID}/`。PostgreSQL 不保存文件正文。

通过率 = 成功 / (成功 + 失败 + 中断 + unknown) × 100。跳过用例不进入分母。全部跳过且没有失败时通过率为 100，执行状态保持成功。存在失败或中断用例时，即使云效步骤返回 SUCCESS，平台执行状态也记为 FAILED。

## 3. API

全部挂在 `/api/v1`。除回调和报告静态文件外都要登录。

- `GET/POST /projects/{project_id}/automation-integrations`
- `PATCH/DELETE /automation-integrations/{config_id}`
- `POST /automation-integrations/{config_id}/test-connection?pipeline_id=`
- `POST /automation-integrations/{config_id}/rotate-callback-key`
- `GET/POST /projects/{project_id}/automation-projects`
- `PATCH/DELETE /automation-projects/{automation_project_id}`
- `POST /automation-projects/{automation_project_id}/verify`
- `POST /automation-projects/{automation_project_id}/executions`
- `GET /projects/{project_id}/automation-executions`
- `GET /automation-executions/{execution_id}`
- `POST /automation-executions/{execution_id}/cancel`
- `POST /automation-executions/{execution_id}/sync`
- `GET /projects/{project_id}/automation-reports`
- `GET /projects/{project_id}/automation-report-trend`
- `GET /automation-reports/compare?left_id=&right_id=`
- `GET /automation-reports/{report_id}`
- `POST /automation-reports/{report_id}/view-grant`
- `GET /automation-reports/{report_id}/download`
- `GET /automation-reports/{report_id}/content/{token}/{file_path}`
- `POST /automation-callbacks/{callback_key}`
- `GET /automation-callbacks/{callback_key}/history?automation_project_id=`

触发调用云效中心版：

`POST https://openapi-rdc.aliyuncs.com/oapi/v1/flow/organizations/{organizationId}/pipelines/{pipelineId}/runs`

请求头 `x-yunxiao-token`。运行参数放在官方要求的 `params` JSON 字符串中，包含分支、环境、pytest 参数和回调地址。回调密钥不会放进这个请求。Region 版去掉 organizations 路径段。

状态查询和终止分别是同一个运行资源的 `GET` 和 `PUT`。

## 4. 云效流水线

1. 在平台创建接入配置，保存个人访问令牌和回调密钥。
2. 创建自动化项目，填写 Codeup 仓库地址和流水线 ID。
3. 在云效流水线添加秘密变量 `AUTOMATION_CALLBACK_SECRET`，值与平台回调密钥一致。
4. 平台触发时会传入 `AUTOMATION_EXECUTION_ID`、`AUTOMATION_PROJECT_ID`、`AUTOMATION_CALLBACK_KEY`、`AUTOMATION_CALLBACK_URL`、`AUTOMATION_HISTORY_URL`、`TEST_ENV`、`PYTEST_ARGS`、`TEST_TAGS`、`TEST_SCOPE`。这些地址要求配置 `PUBLIC_APP_BASE_URL`。
5. 脚本在生成 Allure 前下载上一份 history。首次执行该接口返回 404，继续生成即可。
6. 测试失败也要继续上传报告，不要让上传步骤被 pytest 的退出码跳过。

签名字符串是五段用换行连接：

```text
时间戳
callback_key
幂等键
报告文件 SHA256，没有文件时对空字节计算
metadata 原文 SHA256
```

请求头：`X-Automation-Timestamp`、`X-Automation-Signature`、`X-Idempotency-Key`。时间窗 5 分钟。

`metadata` 至少包含 `automation_project_id`、`execution_id` 或 `pipeline_run_id`、`status`、`branch`、`environment`、`git_commit`、`duration_ms`。统计可以放在 `stats`，也可以只依赖压缩包里的 `widgets/summary.json`。

代码提交触发且平台没有对应执行时，回调会新建一条 `CODE_PUSH` 执行。轮询也会登记最近 24 小时内、项目创建之后出现的新运行，但没有开始时间的旧记录不会被整批导入。

## 5. 报告访问

报告页面先申请两小时有效的文件凭据，再把完整 `index.html` 放进 iframe。凭据写在路径里，Allure 的相对资源会落在同一路径前缀下。iframe 不给予同源权限，因此报告里的脚本不能读取平台登录态。文件接口只校验这份凭据和持有人仍有项目查看权。

压缩包拒绝绝对路径、`..`、符号链接、超过 `AUTOMATION_REPORT_MAX_BYTES` 的文件、过多条目和异常压缩比。同一执行已有报告时，新的压缩包返回 409，不覆盖目录。

服务重启后目录仍在，数据库里的相对路径不变，报告可以继续打开。

## 6. 飞书

通知复用项目里已启用的飞书渠道；自动化项目也可以指定 `notification_channel_id`。卡片包含项目、分支、环境、用例统计、通过率、耗时和“查看 Allure 报告”按钮。按钮指向需要登录的 `/console/automation-reports/{id}`，前提是配置了 `PUBLIC_APP_BASE_URL`。

报告没到时先等待。终态超过两分钟仍没有报告，才会发送“报告尚未上传”。同一执行成功通知后不会重发。发送失败最多再试，累计 3 次后停止。仅跳过的成功执行在“仅失败通知”策略下不发送。

## 7. 验证与限制

`backend/tests/test_78_automation_center.py` 覆盖通过率、ZIP 路径穿越、官方触发路径和报文、密钥不出现在响应或流水线参数、失败用例仍保存完整 HTML、重复回调不覆盖不重复通知、越权 404，以及 history 压缩包。

当前环境没有云效企业令牌，不能代替用户完成真实流水线执行。对官方地址 `GET https://openapi-rdc.aliyuncs.com/oapi/v1/flow/organizations/probe/pipelines/1/runs` 的未授权请求返回 `401 InvalidToken`，说明中心版运行列表路径是通的。客户端按 CreatePipelineRun、GetPipelineRun、ListPipelineRuns 和 UpdatePipelineRun 实现；自动化测试只替换 HTTP 传输层，用来锁定路径、请求头和 `params` 报文。

后续可以补的内容：把取消结果再查询一次确认、报告目录容量清理、多流水线绑定的独立页面，以及把 history 继承放进平台提供的流水线模板仓库。
