<!-- ASR 开发后独立验收：记录本次实跑、可复现缺陷与验证边界。供修复与复验使用，不代替开发交付记录。 -->
# ASR 开发后验证报告

日期：2026-11-02。范围：当前工作区 ASR 新增代码、HTTP 共享层改动、迁移与前端。

## 验收结论

当前不通过验收。页面、通用协议和部分人工操作已实现，但夜间计划、对齐完整性与任务恢复存在已复现缺陷，不能据现有 15 项单元测试通过就认定完整流程可用。

本次只新增验收文档、截图及独立复现资产，不修改业务实现、不覆盖其他未提交改动。未调用收费 ASR 或真实文本模型，未读取真实音频；浏览器数据及故障均为隔离合成数据。

## 1. 实跑结果

| 验证项 | 结果 | 说明 |
|---|---|---|
| 现有 ASR 定向测试 | 15 passed | `backend/.venv/bin/python -m pytest app/features/asr_evaluation/tests -q` |
| Python 编译 | 通过 | ASR 领域、共享 HTTP、Worker 脚本 |
| 前端测试 | 14 passed | `npm test` |
| 前端静态检查 | 通过 | `npm run lint`、`npm run typecheck` |
| 前端生产构建 | 通过 | `npm run build` |
| 本次新增边界复现 | 7 failed | 按预期业务行为断言；这些失败证明缺陷仍在，非预期失败被标成通过 |
| 真实 ASR HTTP 路由的隔离检查 | 3 项通过 | 创建批次返回 202、确认空文本、过期人审版本返回 409；鉴权身份为测试替身，不能替代真实认证测试 |
| 浏览器带数据页面 | 已验证 | 三方文本显示、采用参考 A、保存人工确认、刷新仍保留、候选参数草稿与启动候选批次 |
| PostgreSQL 后端回归 | 1086 passed，2 failed，47 warnings | 完整执行结束，耗时 311.28 秒；两处失败见下方，不归零忽略 |
| 真实长音频及三家服务 | 未验证 | 本次未提供实际接口合同、凭据及获授权的长音频 URL |

首次本机网络访问受沙箱限制；获准在沙箱外执行本机测试后，PostgreSQL 连接成功。全量测试使用唯一命名的隔离库 `testplatform_asr_review_<随机后缀>`，不重置或迁移开发库。

日志：[后端回归](asr-evaluation-validation/asr-review-backend-regression-20261102.log)、[缺陷复现](asr-evaluation-validation/asr-review-reproductions-20261102.log)。

后端回归失败项：

- `tests/test_31_web_ui_console.py::test_real_console_create_confirm_debug_report`：期待「Web UI 工作区」heading，但当前页面为「请先选择项目」。
- `tests/test_36_agent_governance_details.py::test_skill_usage_read_model_counts_distinct_runs_and_limits_recent_tasks`：recent_tasks 第一项预期 usage task 10，实际 usage task 0。

两项分别位于既有 Web UI 控制台和治理详情测试；当前工作区同时存在其他功能修改，尚未通过干净基线对照确定引入来源，不能直接算作 ASR 引入，也不能宣称全量回归通过。

## 2. 必须修复的问题

### R1 / P1：夜间计划到期后不能创建任务，并被误判为配置错误

位置：`backend/app/features/asr_evaluation/runtime/worker.py:161`。

`_trigger_schedule` 调用 `create_job`，但该模块未定义或导入此符号。有效计划通过权限与资源检查后触发 NameError，异常被通用分支捕获，计划变成 `AUTHORIZATION_OR_CONFIGURATION_ERROR` 并被停用。

复现：在内存库创建有效用户、项目、一个音频、三方连接及参数方案，触发刚到期的每日计划。预期 QUEUED，实际错误状态且 enabled=false。本次还直接确认模块全局字典没有 create_job。

修复要求：从所属公开服务导入创建入口，并保证计划推进和批次创建的事务边界。补充真正执行到创建批次路径的定时测试，不能仅测试时区和退避。

### R2 / P1：参考模型末尾文本会从对比结果中消失

位置：`backend/app/features/asr_evaluation/alignment/align.py:65`；替换块分配另见 41–48 行。

插入内容可以存于 anchor 长度位置，但输出循环仅遍历已有 anchor，不处理末尾插入。参考替换块长于待测时也会遗漏内容。

复现一：待测「会议结束。」，两家参考「会议结束。请提交报告。」；实际输出三方均为「会议结束。」，degraded=false。关键的疑似漏识别被隐藏，界面可能显示三方一致。

复现二：待测「甲。乙。」，参考「一。二。三。四。」；参考对比只剩「一。二。」。

修复要求：对齐后拼接每方文本必须与输入全文完全一致；处理首尾插入和不等长替换，并用不变量测试检查所有文本被消费一次。

### R3 / P1：达到 500 块上限后丢弃尾部，却提示全文已保留

位置：`backend/app/features/asr_evaluation/alignment/align.py:72`。

超过块数直接返回前 500 块。调用方的降级说明声称保留全文，但差异块、人工确认入口及 CSV 中已没有尾部。原始转写仍保存在模型运行中，不能因此认为对比视图保留了尾部。

复现：501 个不同短句，总字符数小于 20,000；结果为 500 块、degraded=true，第 501 句不在任何对比块中。

修复要求：分页或把未处理尾部作为明确的未对齐块完整保留，不把被丢弃内容算成无差异。

### R4 / P1：工作项先删除并提交，结果落库失败后任务永久失去恢复入口

位置：`backend/app/features/asr_evaluation/runtime/worker.py:399`；成功路径 339–342 行及其他删除后写结果的分支存在同类窗口。

当前先删除工作项并 commit，再调用 `record_run_result`。若进程此时退出，或结果/对齐写入抛错，数据库仍显示 SUBMITTING/REMOTE_RUNNING，但没有可重新领取的工作项。下次 Worker 仅查询工作项，不能恢复该运行。

复现：真实领取合成任务后，注入结果落库异常；实际工作项不存在、运行仍为 SUBMITTING。不是未验证的并发猜测。

修复要求：租约核验、运行终态及工作项完成同事务持久化；对齐另排幂等工作。写回使用锁或带所有者/代次条件的原子更新，不能仅先读后无条件删除。

### R5 / P1：修改音频 URL 后，历史对比指向了新音频

位置：`backend/app/features/asr_evaluation/services/comparison_service.py:221`；媒体服务读取当前 AsrAudio 的 URL。

运行虽然保存了当时 URL 的执行快照，但对比详情和 media_url 均按可变 audio_id 读取当前资源。链接更新后，历史识别文本不变，界面音频版本和回听源却换成新版本，人工可能针对错误录音确认文本，校对集也记录当前版本。

复现：先生成 v1 三方结果，再将音频 URL 改成另一文件；读取原对比返回 content_version=2、替换后的链接显示和同一当前媒体接口。

修复要求：音频版本持久化并作为运行、对比、媒体及校对样本的引用；若旧版本不可播放，应明确失败，不自动播放新版本。参数复跑、计划及重试也须校验其音频版本口径。

### R6 / P1：正常返回“运行中”的任务不会执行轮询截止限制

位置：`backend/app/features/asr_evaluation/runtime/worker.py:361`、`422`。

24 小时/200 次的限制只在异常重调度 `_reschedule` 中检查。服务每次正常返回 RUNNING 会走另一分支，永不检查上限；远端返回明确失败也被统一当作暂时查询失败继续轮询，缺少可重试和终态错误区分。

复现：将运行创建时间设为 25 小时前，工作项 attempts=250，注入正常 RUNNING 轮询响应。处理后仍为 REMOTE_RUNNING、继续排队。

修复要求：领取/请求前统一校验截止时间及次数；状态失败与暂时网络失败分开处理。多 Worker/连接级远端在途配额还需另外实现，当前只限制本进程线程数。

## 3. 其他已确认问题与范围缺口

### R7 / P2：重复短句的回听位置跨越多个出现位置

位置：`backend/app/features/asr_evaluation/services/comparison_service.py:35`。

`_segment_time` 用字符串包含匹配整条 segments，然后取最小起点和最大终点，没有原文偏移与出现次序。当「好的。」分别出现在 5–6 秒和 100–101 秒，任一个同文块会映射成 5–101 秒。已调用函数复现该返回值。

修复要求：保存归一化到原文及分段的偏移映射，匹配对应出现次序。无法消歧就显示未定位/近似，不能标为该块确定时间。

### R8 / P2：中等桌面宽度下文本列侵入右侧建议区

位置：`frontend/src/pages/console/ASREvaluation/asr-evaluation.css:53`、`67`、`135`。

约 1101px 的默认浏览器视口中，中部三列最小宽度与固定右栏同时存在，三方卡片溢出并侵入右侧建议栏。1366px 桌面截图正常；1100px 的媒体查询断点未覆盖紧邻其上的宽度。

证据：`asr-review-confirmed-20261102.jpg` 对比 `asr-review-confirmed-1366-20261102.jpg`。

修复要求：按内容区可用宽度折叠建议栏或让三列容器独立横向滚动，覆盖 1101–1300px，不能只在整页 viewport<=1100 时响应。

### 仍需补验/补齐

- 建议生成路由是同步调用文本模型，不是方案约定的 202 后台任务；夜间识别完成也没有自动生成初步建议的工作项。前端请求仍受共享超时约束。用户次日直接获得初步建议的目标尚未完整落实。
- 本次浏览器没有可用真实 LLM，因此仅验证了已确认文本、手动候选参数和排队，不宣称 AI 建议和远端复跑已成功。
- 当前无真实音频数据，播放器未加载音频属验收夹具边界，不列为已确认的产品播放故障；真实 >30 分钟播放、Range、凭据与云端拉取仍需联调。
- 对比页主要显示当前选中块的三列原文和整段背景，没有参考图中的逐字差异高亮和完整时间轴。已实现部分布局，不能按图片全量还原验收通过。

## 4. 复现与截图资产

复现脚本：[review_reproductions_20261102.py](asr-evaluation-validation/review_reproductions_20261102.py)。只用隔离内存 SQLite、虚构账号和合成识别文本，不访问网络或开发数据库；一例注入落库异常，一例注入正常运行中轮询响应。

```bash
cd /Users/a1/Desktop/ai-test-project/backend
PYTHONPATH=. .venv/bin/python -m pytest \
  ../docs/asr-evaluation-validation/review_reproductions_20261102.py -q --tb=short
```

当前预期实测为 7 failed。修复后应变为通过，同时把相应回归用例移入正式测试目录并扩展 PostgreSQL 并发与事务验证；不要把当前失败改成 xfail 来消除验收问题。

浏览器通过临时本机服务连接真实 ASR router/services 和隔离 SQLite；仅全局身份和项目选择器使用合成夹具。没有使用生产 Cookie，没有将用户真实数据发往任何第三方。

| 截图 | 内容 |
|---|---|
| [人工确认后的实际页面](asr-evaluation-validation/asr-review-confirmed-20261102.jpg) | 默认视口，包含人工确认，能看到中部列宽问题 |
| [1366px 对比页](asr-evaluation-validation/asr-review-confirmed-1366-20261102.jpg) | 刷新后确认状态仍保留，三方内容与建议栏 |
| [候选参数草稿](asr-evaluation-validation/asr-review-candidate-20261102.jpg) | 候选 VAD 值 0.4，基线仍为 0.5，状态待复跑 |
| [候选批次已排队](asr-evaluation-validation/asr-review-candidate-queued-20261102.jpg) | 显式启动复跑后生成 ASR-2，三个运行 PENDING；未运行真实云端识别 |

验收服务为临时进程，完成后停止；不会留下新增计划或后台云端调用。建议先修复 R1–R6，再做夜间三方真实联调、故障恢复与最终完整验收。
