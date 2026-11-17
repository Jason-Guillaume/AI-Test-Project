# 五大资源管理模块设计说明

本次参考用户提供的 [ARTEX 仓库](https://github.com/RuoJi6/ARTEX)布局意图，沿用当前项目 API 和权限规则，不迁移 ARTEX 技术栈。

## LLM / 模型中心

- **职责与路由**：`/admin/model-configs` 是平台统一管理入口，包装现有 `ModelCenterPage`；旧 `/console/model-center`、`/console/asr/connections` 按现有兼容逻辑处理，不再维护第二份模型状态。
- **布局与交互**：文本推理、ASR、说话人分段分类；主视图为卡片，可切回表格。增加分类资源总量、启用/停用、诊断异常统计、搜索和操作入口。点击卡片详情打开共享 Drawer。
- **详情分组**：基本信息、脱敏连接配置、参数方案、用途默认策略、诊断与连接修订历史。连接配置不显示 `revision.config` 或凭据明文。
- **实际 API**：`modelCenterApi.catalog/list/create/addRevision/addProfile/setDefault/createDiagnostic/getDiagnostic`；真实诊断仍由用户明确触发并需确认模型调用。
- **数据边界**：模型使用次数/成本没有该页面可消费的汇总接口，不展示假统计。连接历史来自实际 `revisions`。

## Agent

- **主页面**：默认卡片视图，搜索名称/说明/工作流，可按测试类型和绑定模型筛选；超过 12 个卡片时分页。主子关系树、表格和批量删除作为可选视图保留。
- **详情分组**：配置与提示词、收尾提示词、MCP、Skill、Tools、触发器；明确模型优先级“Agent 固定模型 → 任务会话模型 → 全局默认”，系统提示词和触发器随版本快照。
- **关联与权限**：卡片区分子 Agent、Skill、系统工具与 MCP 工具数；Agent 表单继续仅允许选择当前处于连接状态且管理员审批的只读 MCP 工具。
- **实际 API**：`agentGovernanceApi.agents/createAgent/updateAgent/agentVersions/restoreAgentVersion`；数据保存、版本和恢复继续走原服务端逻辑。

## MCP

- **主页面**：卡片展示地址、认证类型、真实连接状态、最近错误、已发现/已审批工具、启停和 Agent 关联；支持按名称、地址、状态搜索，支持原有批量回收。
- **配置 Drawer**：连接配置与连接状态分 Tab；仅提供服务端当前实现的 Streamable HTTP 和 none/Bearer 认证。Bearer Token 留空保留已保存凭据，服务端不回传明文。
- **服务详情 Drawer**：发现与审批 Tab 展示 `inputSchema`、readOnly/destructive/idempotent/openWorld 注解；Agent 关联 Tab 展示真实绑定。醒目标明审批、Agent 授权和可执行是三个不同状态。
- **实际 API**：`mcpServers/createMcpServer/updateMcpServer/discoverMcpTools/approveMcpTools/deleteMcpServer`。
- **数据边界**：当前服务端连接器只提供 Streamable HTTP；没有为 STDIO 或调用历史添加静态入口。

## Skill

- **工作区**：左侧目录/文件树、搜索和分类筛选，右侧概览及编辑器；文件树和当前编辑文件绑定同一 draft 状态。未选具体文件时展示真实用量、版本、MCP 绑定和关联 Agent 摘要。
- **编辑规则**：文本/Markdown 可编辑并预览；未知或二进制扩展名不进入文本编辑器。保存要求非空 `SKILL.md` 且最多 200 个文件；保存通过既有 `files_json` API 创建新版本。
- **生命周期**：提供 ZIP 导入、创建、软删除/回收站跳转、版本历史和“恢复成新版本”；新建/文件编辑与离开页面都检查未保存内容。
- **实际 API**：`skills/createSkill/importSkillZip/updateSkill/skillUsage/skillVersions/restoreSkillVersion/deleteSkill`。

## Tool

- **主页面**：卡片展示类别、风险、启停、执行器接入状态和真实 Agent 绑定；支持搜索、分类/风险/状态/执行器接入筛选。
- **详情 Drawer**：配置与说明、运行详情、绑定 Agent 三个 Tab。Schema/执行器结构只读；仅更新治理描述、参数描述/默认值、启用状态和 Agent 绑定。未接入工具明确显示不可运行。
- **实际 API**：`tools/updateTool/restoreToolDefaults`。恢复默认、保存成功后清缓存并反馈。
- **数据边界**：后端未提供工具调用次数/每次运行详情 API，本页不伪造运行次数。
