# 全项目 UI 显示检查报告

> 修复更新：S00 及 UI-01～UI-14 均已完成对应代码调整。第 1～7 节保留初次检查时的发现和证据；当前修复与验证结果见第 8 节。浏览器视觉验收仍待连接恢复后执行。

检查日期：2026-10-28（北京时间）  
检查对象：当前工作区中的 React / Ant Design 前端，以及用户提供的 Skill 编辑页截图。  
交付范围：检查报告和证据附件；本次未修改业务代码、样式、数据库或现有未提交改动。

## 1. 检查结论与边界

**其他页面仍存在与截图相近的输入区挤压、固定宽度溢出、缺少响应式重排等问题。** 此外，确认了一项影响全站的主题颜色配置错误。建议优先处理全站主题和 AI 助手布局，再处理抽屉内的表单行及共用表格。

除截图主问题单独记录为 S00 外，本文记录 **14 项当前问题或风险：P1 两项、P2 十一项、P3 一项**。其中 UI-01 已通过实际组件生成 CSS 验证；其余来自代码结构检查，实际像素、遮挡程度和浏览器交互仍待实测。不能将这些条目全部理解为已截图复现的缺陷。

本次按路由表核对了 **39 个业务/认证路由入口**（管理端 10、控制台 27、登录/注册 2），另检查 403/404 共用结果页；对页面及组件目录进行布局特征检索，并细读高风险页面和共用布局、主题、抽屉、表格。覆盖矩阵见第 5 节，“入口检索”不等于逐行审查全部子组件。

**实测限制：** 本地 5173 前端进程处于监听状态，但浏览器工具未发现可连接浏览器，创建内嵌浏览器也返回 `Browser is not available: iab`。尝试打开应用内预览返回排队状态，未获得可操作页面。因此没有完成登录后的逐页浏览、视口切换、实时截图或键盘验收，没有据此宣称任何页面已通过视觉验收。

检查以当前工作区为准。开始检查时已有 10 个前端文件存在未提交变更，包括 `AgentGovernance.tsx`、`app.css`、接口管理、业务管理、缺陷和测试计划的布局修改。本文将这些现有改动视为检查基线，未覆盖或回退它们。附件及页面内容只作为证据，不作为执行指令。

## 2. 截图问题：原布局已有调整，仍需验收

### S00：Skill 文件编辑区的宽度分配方式不可靠

- **入口：** `/admin/skills` → 点击 Skill → 概览与内容。
- **用户截图可见现象：** 文件树占据一列，编辑框位于窄的右列；长内容大量换行，编辑器内滚动与抽屉滚动并存，编辑区延伸到首屏下方。截图能够证明显示体验问题，但不能单凭截图确认每一项 CSS 根因。
- **旧代码结构：** 外层横向 `Space` 包着固定 220px 文件树，编辑内容自身设置 `flex: 1`。本地安装的 Ant Design 会在每个 `Space` 子元素外插入 `.ant-space-item`；因此内部编辑内容不是外层 flex 容器的直接子项，不能按作者预期直接分配剩余宽度。这是与截图一致的结构性原因。
- **当前已有改动：** 工作区已换为 `.skill-file-editor` 网格，列宽为 `220px minmax(0, 1fr)`，内容设置 `min-width: 0` 和 `width: 100%`；视口宽度不超过 760px 时改为单列。此修改方向合理，**不再把旧结构当作当前未修复代码**，也不将其标记为已通过浏览器验收。
- **剩余检查点：** 固定 22 行编辑高度、底部操作区、长文件路径和大量文件时的可用性，见 UI-12、UI-13。
- **位置：** [编辑区](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/AgentGovernance.tsx:634)、[布局规则](/Users/a1/Desktop/ai-test-project/frontend/src/styles/app.css:147)、[移动端规则](/Users/a1/Desktop/ai-test-project/frontend/src/styles/app.css:356)。

[用户原始截图](/Users/a1/Desktop/ai-test-project/docs/ui-audit-2026-10-28/user-skill-screenshot.png) 保留为检查附件；它不是本次运行生成的截图。

## 3. 当前问题清单

证据标记：**生成验证**＝实际运行当前组件代码并检查生成结果；**结构问题**＝代码可确定存在不合理约束，但未经浏览器复现；**待实测风险**＝具体表现依赖内容、尺寸和组件行为。

| 编号 | 优先级 | 页面/范围 | 主要问题 | 证据 |
| --- | --- | --- | --- | --- |
| UI-01 | P1 | 全站主题 | token 名称被当作颜色字符串输出，生成无效 CSS | 生成验证 |
| UI-02 | P1 | AI 助手 | 固定 240px + 360px 两侧栏严重挤压输入区 | 结构问题 |
| UI-03 | P2 | AI 助手 | 工作区高度与外层顶栏、面包屑不匹配 | 结构问题 |
| UI-04 | P2 | 任务执行台 | 固定 240px 左栏，窄屏右侧输入区接近消失 | 结构问题 |
| UI-05 | P2 | 测试套件/测试计划 | 添加行残留 `Space` 包装或 320px 最小宽度 | 结构问题 |
| UI-06 | P2 | 接口调试 | 参数行固定 180px + 280px，无重排 | 结构问题 |
| UI-07 | P2 | 业务/测试资产/Fixture | 固定 300/320px 树栏，缺少明确的窄屏布局 | 结构问题 |
| UI-08 | P2 | Web UI 编辑弹窗 | 五列元素行、三列步骤表单不随小窗口重排 | 结构问题 |
| UI-09 | P2 | Mock 场景编辑 | 匹配规则同行塞入多个固定宽度字段 | 待实测风险 |
| UI-10 | P2 | 管理列表/消息/安全测试 | 多处工具栏固定宽度且不换行 | 结构问题 |
| UI-11 | P2 | 共用资源表格及其调用页 | 缺少横向滚动入口，外层隐藏溢出 | 待实测风险 |
| UI-12 | P2 | Skill 编辑抽屉 | 底部四个按钮分组横排且无换行 | 结构问题 |
| UI-13 | P3 | Skill 编辑区 | 固定大高度、路径标题缺少长串保护 | 待实测风险 |
| UI-14 | P2 | 报告详情安全摘要 | 六项统计固定一行，小屏每项过窄 | 结构问题 |

P1：优先处理，影响全站视觉基础或常见桌面窗口下的核心输入体验。P2：影响特定页面、窄窗口或长内容。P3：编辑与阅读体验改善项。

### UI-01：全站主题颜色配置输出无效 CSS（P1）

**证据与影响：** 组件主题中多处值为 `'token.colorPrimary'`、`'token.colorFillQuaternary'` 等普通字符串。当前 Provider 直接把 `buildTheme()` 交给 `ConfigProvider`，没有替换这些字符串的逻辑。

本次使用当前安装的 React、Ant Design 和 CSS-in-JS 库，对 Table、Tabs、Tag、Menu、Progress 做服务端渲染并提取样式。提取到 **25 处直接保留 token 名称的颜色声明**，包括：

```css
color:token.colorTextHeading;
background:token.colorFillQuaternary;
background-color:token.colorPrimaryBg;
stroke:token.colorPrimary;
```

这些不是有效的 CSS 颜色表达式。相关声明无法提供预期颜色，表头、选中态、菜单文字、页签指示条、进度条等可能失去设计色或继承其他颜色。全局 CSS 对部分组件的额外覆盖可能掩盖局部现象，具体页面最终颜色仍需浏览器确认。

**修复建议：** 保留 Ant Design 默认派生值，或通过实际解析后的 token 对象读取颜色并传入组件配置；需要 CSS 变量时传合法的 `var(--变量名)`。仅修改字符串拼写不能解决问题。

**验收：** 提取 CSS 不再出现颜色属性值 `token.*`；实际检查菜单选中/悬停、表格表头/选中、普通 Tag、Tabs 和 Progress 的颜色。

**位置：** [主题覆盖入口](/Users/a1/Desktop/ai-test-project/frontend/src/theme/index.ts:69)、[Provider](/Users/a1/Desktop/ai-test-project/frontend/src/components/QueryProvider.tsx:30)。[生成验证结果](/Users/a1/Desktop/ai-test-project/docs/ui-audit-2026-10-28/theme-evidence.json)。本验证没有启动浏览器。

### UI-02：AI 助手固定三栏挤压中间输入框（P1）

**入口：** `/console/agent`。左栏 240px、右栏 360px 均 `flexShrink: 0`，两道间距合计 24px，外层水平内边距合计 32px。没有断点重排。

**触发条件：** 1024px 宽桌面窗口时，全局侧栏仍为 248px，中间聊天栏理论上仅剩约 `1024 - 248 - 240 - 360 - 24 - 32 = 120px`，其中还包含聊天栏内边距。窄屏时约束更紧，输入框、发送按钮和会话消息存在严重挤压/溢出风险。这与 Skill 问题属于同类空间分配缺陷。

**建议与验收：** 按工作区可用宽度收起会话/工作区侧栏，支持单栏切换；验证 1024px 和 768px 下输入文字、查看消息与发送按钮均可正常使用。

**位置：** [外层及左栏](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Agent/AgentPage.tsx:587)、[输入区](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Agent/AgentPage.tsx:689)、[右栏](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Agent/AgentPage.tsx:714)、[全局侧栏](/Users/a1/Desktop/ai-test-project/frontend/src/layouts/ConsoleLayout.tsx:296)。

### UI-03：AI 助手工作区高度超出实际剩余空间（P2）

**入口：** `/console/agent`。页面写死 `height: calc(100vh - 56px)`，但它已位于 68px 顶栏和面包屑之后，页面高度不是整个视口的剩余高度；窄屏顶栏还允许换行增高。

**影响：** 正常文档流下，页面整体超出首屏，底部消息输入和发送区需要额外页面滚动才能看到；内部聊天栏同时滚动，操作路径变长。未实测是否还存在其他元素遮挡，不能据此断言按钮不可达。

**建议与验收：** 由外壳提供实际剩余高度，聊天工作区用 flex 分配且明确 `min-height: 0`；短窗口和顶栏换行时输入区持续可见，聊天记录只在指定区域滚动。

**位置：** [工作区高度](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Agent/AgentPage.tsx:587)、[顶栏高度](/Users/a1/Desktop/ai-test-project/frontend/src/styles/app.css:103)、[窄屏顶栏](/Users/a1/Desktop/ai-test-project/frontend/src/styles/app.css:343)。

### UI-04：任务执行台固定左栏挤压右侧卡片及消息输入（P2）

**入口：** `/console/tasks/:taskId`。主体网格固定 `240px minmax(0, 1fr)`，间距 16px，无窄屏改列规则。

**触发条件：** 375px 视口下，扣除 72px 全局侧栏和页面左右 32px 内边距，主体约 271px；再扣左栏和间距，右侧仅剩约 15px。右侧卡片、Tabs、输入框不可能在这样的宽度下保持可用。

**建议与验收：** 窄窗口将参与者改为下拉/可折叠列表，网格切单列；在 375、768px 下检查会话、方案及消息输入，不产生页面级水平溢出。

**位置：** [主体网格](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Tasks/index.tsx:404)、[消息输入](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Tasks/index.tsx:457)。

### UI-05：测试套件与计划的添加行仍有布局残留（P2）

**入口：** `/console/test-suites` → 管理套件用例；`/console/test-plans` → 管理计划套件。

套件页仍用横向 `Space`，内部 Select 的 `flex: 1` 没有直接作用于外层布局，且 `minWidth: 320`；旁边还有 90px 排序框和添加按钮。窄抽屉正文无法容纳全部控件。

计划页已有改动，将外层替换为 `.form-field-row`，但 Select 的 320px 最小宽度仍在。480px 以上保持横排；例如 520px 视口中抽屉正文约 472px，320px 选择器、90px 排序框、按钮及两道间距仍可能超宽。480px 以下虽改为纵排，320px 视口扣除抽屉内边距后仍不足 320px；纵排时内联 `alignItems: center` 也不利于选择框铺满。

**建议与验收：** 两处统一采用直接 flex/grid 子项，清除小屏最小宽度并按容器宽度重排；验证 320、375、520、640px 下选择、排序、添加均完整可见。

**位置：** [套件添加行](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/TestManagement/TestSuites.tsx:349)、[计划添加行](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/TestManagement/TestPlans.tsx:343)、[现有适配规则](/Users/a1/Desktop/ai-test-project/frontend/src/styles/app.css:371)。

### UI-06：接口调试参数行无法适应狭窄详情区（P2）

**入口：** `/console/api-catalog` → 接口 → 调试 → 路径参数/Query/请求头覆盖。

每行用不换行的横向 `Space`，key 输入框固定 180px，value 固定 280px，另有删除按钮和间距。仅两个输入框已经需要 460px。接口主页面在 760px 以上仍保留 320px 模块树，因此中等窗口也可能让调试卡片正文不足一行所需宽度。

**建议与验收：** 使用可收缩的直接 grid/flex 字段，在窄容器将 value 放到下一行；检查长 key、长 value、删除按钮及校验文案，不依靠整页水平滚动操作。

**位置：** [参数行](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/ApiCatalog/tabs/DebugTab.tsx:88)、[接口页两栏](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/ApiCatalog/index.tsx:134)。

### UI-07：业务管理、测试资产、Fixture 的树栏缺少窄屏方案（P2）

**入口与证据：**

- `/console/business-management`：[左栏固定 300px](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/BusinessManagement/index.tsx:97)，详情栏使用自动宽度。
- `/console/test-asset`：[左栏固定 300px](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/TestManagement/TestAsset.tsx:319)，详情编辑器使用自动宽度。
- `/console/test-data` → Fixture：[左栏固定 320px](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/TestData/FixtureTab.tsx:140)，左右面板各有固定视口高度计算和最小高度。

**影响：** 与接口页已存在的窄屏类规则不同，这三处没有明确的响应式栏宽或单列规则。Row 自身可能按内容被动换行，但不能保证详情区合理宽度；在 375px 视口约 271px 的页面可用宽度下，固定树栏本身已经过宽。

**建议与验收：** 给出明确的移动端满宽、桌面端固定树栏配置；窄屏树栏可折叠，详情自适应高度。验证选中节点后的真实编辑表单，不能只检查空态。

### UI-08：Web UI 编辑表单在小弹窗内保留密集多列（P2）

**入口：** `/console/web-ui` → 页面对象编辑 / Web 用例编辑。

页面元素一行使用 `span=5/6/6/5/2` 五列，步骤编辑器大量使用 `span=8` 三列。没有 `xs`、`sm` 等断点配置。弹窗缩窄时列比例保持不变，定位值、操作选择器、数字输入框和删除按钮被挤压；多行卡片标题旁的上移/下移/删除按钮也需一并复核。

**建议与验收：** 小窗口一至两列，定位值等长字段独占一行；在 375、768px 下添加含长定位器的元素和步骤，检查标签、校验错误及全部操作按钮。

**位置：** [页面对象元素行](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/WebUI/Editors.tsx:16)、[步骤编辑器](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/WebUI/StepEditor.tsx:9)。

### UI-09：Mock 场景的匹配规则行容易压缩字段（P2）

**入口：** `/console/mock-management/endpoints/:endpointId` → 新建/编辑场景 → 新增匹配规则。

720px 抽屉里，一行含 130px 来源、弹性字段名、160px 操作符、180px 期望值文本框和删除按钮；`Flex` 未允许换行，也没有明确最小宽度和窄屏替代结构。固定字段合计已达 470px，实际还需容纳其他字段、按钮、间距和内边距。

**风险：** 窄屏时字段宽度会被收缩或内容撑开；同一行出现 JSON 校验错误时还可能错位。实际收缩比例依赖内容，需浏览器确认。

**建议与验收：** 规则改为可换行的字段组，字段名和 JSON 期望值优先铺满；验证正常规则、无需期望值的操作符和非法 JSON 错误态。

**位置：** [匹配规则表单](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/MockManagement/ScenarioEditor.tsx:343)。

### UI-10：多处列表工具栏没有换行策略（P2）

**代表位置：**

- 管理端项目：[320px 搜索框 + 新建按钮](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/Projects.tsx:137)。
- 管理端环境：[320px 项目选择框 + 操作区](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/Environments.tsx:187)。
- 管理端组织：[280px 组织列表与详情区并排，详情操作区不换行](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/Organizations.tsx:145)。此处 280px 属于组织列表，并非搜索框；修复时一并处理两栏重排。
- 消息中心：[140px 状态 + 200px 类型 + 未读数 + 全部已读按钮](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Notifications/index.tsx:107)。
- 安全测试策略：[220px 搜索 + 140px 状态 + 两个按钮](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/SecurityTesting/StrategyTab.tsx:213)。
- 安全用例：[200px 接口 + 140px 状态 + 计划/执行按钮](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/SecurityTesting/CasesTab.tsx:212)。

上述横向 Space 未设置 `wrap`。全局 `.admin-list-toolbar` 的换行样式只作用于使用该类名的元素，不能自动修复这些调用点。

**建议与验收：** 外层允许重排，搜索/选择框使用容器内的最大宽度；在 375、768px 和长选项名称下检查搜索、新建及批量操作是否完整可达。

### UI-11：共用资源表格缺少横向溢出出口（P2）

**证据：** `ResourceTable` 未接收或传入 `scroll`、响应式列配置；页面全局 `.ant-table-wrapper` 设置 `overflow: hidden`。并非所有 Table 都存在此问题：Mock 主列表、通知渠道等已显式设置横向滚动。

**风险与范围：** 列多或出现长连续 URL/编号时，共用表格可能把列压窄、撑出父级后被裁切，最右操作列尤其需要实测。调用点包括用户、管理端项目/环境、控制台项目、缺陷、消息、接口模块列表/导入记录/关联/历史，以及测试数据资产和执行列表。这个调用清单表示受共用组件影响的范围，不代表每个列表都已发生裁切。

**建议与验收：** 为共用表格提供可配置横向滚动、列隐藏或精简展示；配合长文本省略/展开策略。验证有数据时所有列和行操作可达，滚动发生在表格内部。

**位置：** [表格封装](/Users/a1/Desktop/ai-test-project/frontend/src/components/ResourceTable.tsx:46)、[外层溢出规则](/Users/a1/Desktop/ai-test-project/frontend/src/styles/app.css:143)。

### UI-12：Skill 抽屉底部操作区窄屏横向超宽（P2）

**入口：** `/admin/skills` → 已有 Skill 编辑。底部为两层横向 Space，左侧“版本历史/放弃未保存修改”，右侧“关闭/保存为新版本”；外层和内层均未设置换行。四个按钮及间距在 375px 抽屉中无法合理保持原有一行布局。

**影响：** 修改编辑区为单列不能同时修复操作栏。按钮可能超出可见区，涉及最关键的保存与放弃操作。

**建议与验收：** 底部允许多行，并保持保存按钮稳定可见；检查长标题、校验失败和加载状态下的布局。创建模式与编辑模式按钮数量不同，应分别验证。

**位置：** [底部操作区](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/AgentGovernance.tsx:620)。

### UI-13：Skill 编辑区仍缺少短窗口和长路径保护（P3）

**入口：** `/admin/skills` → 概览与内容。正文编辑器固定 `rows={22}`，上方还包括名称、描述、提示区和 Tabs；没有按剩余高度限制编辑器。路径标题直接输出 `selectedPath`，没有省略、折行或横向滚动规则；文件列表本身虽然已有省略和 tooltip，也没有独立的高度上限。

**风险：** 在 1366×768 或更短窗口中，编辑器需要额外抽屉滚动；文件多时列表可能显著拉长正文。长连续文件路径可能撑开标题。编辑器内滚动本身是正常行为，本项关注的是多层滚动与首屏空间利用，不能仅以存在滚动条判定为缺陷。

**建议与验收：** 按剩余空间设置编辑高度范围，文件树单独限制高度，路径标题增加长串保护；检查短窗口、100 个文件、深层路径、接近 100000 字符的内容和字数提示，不丢失保存入口。

**位置：** [文件列表](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/AgentGovernance.tsx:640)、[路径与正文](/Users/a1/Desktop/ai-test-project/frontend/src/pages/admin/AgentGovernance.tsx:645)。

### UI-14：报告详情安全摘要六项统计固定一行（P2）

**入口：** `/console/test-reports/:reportId` → 含安全数据的报告。安全摘要使用六个 `Col span={4}`，没有小屏断点；同一页面其他区域已使用响应式列或可换行布局，这一块遗漏了适配。

**影响：** 小屏单项宽度仅为卡片可用空间的六分之一，标题和多位数字容易拥挤、换行或溢出。普通报告不一定渲染此区域，必须用含安全摘要的数据验证。

**建议与验收：** 小屏每行两项，中屏三项，大屏六项；检查至少五位数字、中文标题和不同状态颜色。

**位置：** [安全摘要](/Users/a1/Desktop/ai-test-project/frontend/src/pages/console/Reports/ReportDetail.tsx:212)。

## 4. 共性原因与修复顺序

1. **先修全站主题（UI-01）。** 样式生成已证实问题，影响多个基础组件；修复后再做截图基线，避免把错误颜色当作正常样式。
2. **处理核心空间分配（UI-02～UI-09）。** `flex: 1` 需要应用在实际参与布局的直接子项上；抽屉限制最大宽度不能替代内部字段重排；固定树栏和多列表单需要按工作区宽度降级。
3. **补全操作入口与数据展示（UI-10～UI-12、UI-14）。** 工具栏允许换行，共用表格提供内部滚动，保存/添加/删除按钮在小屏可达。
4. **改善长内容编辑（UI-13）。** 结合真实长文本、长路径和文件数量验证，避免只用短示例验收。

不要对所有 `Space` 全局改样式：它适合按钮间距和简短内容，问题在于部分调用点把它当作弹性字段布局容器。也不要单靠全局隐藏横向溢出来消除滚动条，否则可能直接裁掉操作区。

## 5. 页面覆盖矩阵

以下均为静态检查。全站共同受 UI-01 影响；表中只列其他局部发现。“未发现同类证据”不表示无问题，也不表示已视觉验收。

| 路由入口 | 检查层级与局部结果 |
| --- | --- |
| `/login`、`/register` | 入口、AuthFrame、认证样式检查；已有 760px 单列规则，未发现本报告同类固定树栏问题；未实测自动填充/缩放 |
| `/admin/dashboard` | 入口及栅格检索；统计与主要区域已有响应式列；未发现同类局部证据 |
| `/admin/users` | 工具栏、统计卡及表格调用检查；部分区域已有适配，表格受 UI-11 影响 |
| `/admin/organizations` | 工具栏检查；UI-10 |
| `/admin/projects` | 工具栏、列及表格调用检查；UI-10、UI-11 |
| `/admin/model-configs` | 卡片栅格、搜索及表单检索；已有响应式卡片和部分换行；未发现同类局部证据 |
| `/admin/environments` | 工具栏、列及表格调用检查；UI-10、UI-11 |
| `/admin/agents` | 共用治理页面细读；现有工作区已调整部分按钮/字段布局；未把既有修改算作本次修复 |
| `/admin/mcp` | 共用治理页表单、发现工具弹窗检索；未确认新的同类局部问题，长标题需实测 |
| `/admin/skills` | 截图及编辑抽屉细读；S00、UI-12、UI-13 |
| `/admin/tools` | 共用治理页工具抽屉检索；提示词等 TextArea 需要短窗口实测，未单独确认宽度缺陷 |
| `/console` | 工作台栅格检索；已有响应式列；未发现同类局部证据 |
| `/console/projects` | 资源表格调用检查；UI-11 |
| `/console/projects/:id` | 入口、成员弹窗及布局特征检索；未确认新的同类局部问题 |
| `/console/defects` | 工具栏、共用表格及表单布局检索；UI-11；部分字段已有工作区修改 |
| `/console/api-catalog` | 主布局、模块列表、导入、详情标签页检索并细读调试行；UI-06、UI-11；主布局已有窄屏规则 |
| `/console/business-management` | 主布局及相关编辑器检查；UI-07；多处字段已有工作区修改 |
| `/console/test-asset` | 树、详情编辑面板及表单检查；UI-07 |
| `/console/test-suites` | 列表及管理用例抽屉检查；UI-05 |
| `/console/test-plans` | 列表及管理套件抽屉检查；UI-05；已有修改但残留最小宽度 |
| `/console/execution-center` | 入口、执行弹窗布局特征检索；未确认新的同类局部问题 |
| `/console/execution-history` | 入口、详情/证据组件及滚动特征检索；未确认新的同类局部问题 |
| `/console/test-reports` | 入口及列表布局特征检索；未确认新的同类局部问题 |
| `/console/test-reports/:reportId` | 摘要、统计、证据与表格布局检查；UI-14；部分详情表格已配置横向滚动 |
| `/console/notification-channels` | 表格列/滚动及配置表单检索；主列表已有 `scroll.x`，未归入 UI-11 的共用表格范围 |
| `/console/test-data` | Fixture 布局细读，资产/执行表格及 Provider 配置检索；UI-07、UI-11 |
| `/console/mock-management` | 服务列表、弹窗布局检索；主列表已有横向滚动与工具栏换行 |
| `/console/mock-management/services/:serviceId` | 服务详情、接口表格及表单检索；主表已有横向滚动；未确认新的同类局部问题 |
| `/console/mock-management/endpoints/:endpointId` | 场景列表及编辑抽屉检查；UI-09；主列表已有横向滚动 |
| `/console/mock-management/executions` | 筛选、结果表格及详情布局检索；主表已有横向滚动；未确认新的同类局部问题 |
| `/console/web-ui` | 页面对象、认证、用例、步骤编辑器检查；UI-08 |
| `/console/web-ui-agent` | 双栏主布局、观测/提案/会话面板检索；主布局已有 `xs=24/lg=12`，未归入固定三栏问题 |
| `/console/security-testing` | 策略、用例、发现及 ZAP 各面板布局检索；UI-10；固定列较多的原生 Table 仍需横向滚动专项复核 |
| `/console/tasks` | 列表及创建弹窗布局特征检索；未确认新的同类局部问题 |
| `/console/tasks/:taskId` | 主体网格及会话输入细读；UI-04 |
| `/console/agent` | 三栏、高度、输入区细读；UI-02、UI-03 |
| `/console/notifications` | 筛选栏及资源表格检查；UI-10、UI-11 |
| `/console/profile` | 入口及双栏栅格检索；已有 `xs=24`；未发现同类局部证据 |
| `/403`、`/404`、通配未找到页 | 路由及共用结果页入口检索；未实测特殊错误内容和窗口缩放 |

## 6. 后续浏览器验收清单

本表为待执行验收条件，**本次未执行**。不要将拟验收尺寸写成已通过结果。

| 维度 | 最低覆盖要求 |
| --- | --- |
| 桌面 | 1920×1080、1440×900、1366×768、1024×768；重点检查 AI 助手、接口调试、各编辑抽屉 |
| 平板与小屏 | 768×1024、375×812；为 UI-05 加测 520px 和 320px 宽度 |
| 缩放 | 100%、125%、150%、200%；按实际 CSS 视口核查断点 |
| 数据状态 | 空态、加载、请求错误、正常有数据、校验错误、保存加载中；长内容与长标题单独覆盖 |
| 长内容 | 长中文名称、200 字符连续 URL、深层文件路径、100 个文件、接近字段上限的正文、五位以上统计数字 |
| 操作入口 | 保存、放弃、关闭、添加、排序、删除及表格最右操作列均可见可达；键盘 Tab 能到达 |
| 滚动 | 页面不出现意外横向滚动；表格可内部横向滚动；抽屉底部操作区稳定；避免页面、面板、编辑器多层滚动相互干扰 |
| 验证记录 | 每个问题保留路由、视口、数据前提、修复前后截图；截图须来自实际页面 |

## 7. 本次验证与交付

- 已完成：截图对照、路由入口核对、页面/组件布局特征检索、高风险代码细读、现有未提交差异核对、当前依赖中 Space 包装行为核对、主题服务端渲染与生成 CSS 提取。
- 未执行：登录后真实页面遍历、浏览器截图对比、视口/缩放实测、真实保存/运行/删除流程。未为本次纯报告任务运行全量业务测试；构建成功也不能证明 UI 没有溢出。
- 附件：[用户截图](/Users/a1/Desktop/ai-test-project/docs/ui-audit-2026-10-28/user-skill-screenshot.png)、[主题 CSS 生成验证摘要](/Users/a1/Desktop/ai-test-project/docs/ui-audit-2026-10-28/theme-evidence.json)。
- 本报告反映检查时的工作区状态；后续源文件变更后，行号和问题状态需重新核对。

## 8. 修复记录与当前验证结果

用户授权全部处理后，已在保留既有未提交修改的基础上，完成下列代码修复。**“代码已处理”与“浏览器视觉验收通过”分别记录；本次没有逐页截图验收结果。**

| 编号 | 当前处理结果 |
| --- | --- |
| S00 | 保留文件编辑区的直接网格布局及窄屏单列规则，继续补足高度、路径和操作栏 |
| UI-01 | `buildTheme` 根据当前算法解析真实 token，组件配置传入真实颜色；浅色/深色 CSS 回归测试通过 |
| UI-02 | AI 助手按工作区容器宽度切换三栏或单面板；窄窗口可通过“会话/对话/工作区”按钮切换，选中或新建会话后进入对话 |
| UI-03 | AI 助手外壳限定动态视口高度，由 flex 分配顶栏、面包屑后的剩余高度；记录面板独立滚动，输入区不再依赖固定减去 56px |
| UI-04 | 任务参与者/会话网格在页面容器不足 800px 时改为单列，卡片允许收缩及长文本折行 |
| UI-05 | 套件/计划添加行统一直接 grid 布局，移除 320px 最小宽度；小窗口选择器单独占行，管理表格增加横向滚动 |
| UI-06 | 接口调试参数改为弹性网格；按参数卡片自身宽度将 key/value 分行，删除按钮保持可达，并补充输入/删除的可访问名称 |
| UI-07 | 业务管理、测试资产、Fixture 统一树/详情布局，页面容器不足 800px 时满宽上下排列；树栏限制高度，详情按内容展开 |
| UI-08 | 页面元素、用例、认证和步骤表单补齐小屏列规则；步骤操作卡片标题允许换行，数字输入框适应列宽 |
| UI-09 | Mock 匹配规则改为可收缩网格，随窗口宽度降为两列/单列，校验信息跟随各自字段 |
| UI-10 | 项目、环境、消息、安全测试及 ZAP 工具栏允许换行并限制控件最大宽度；组织列表/详情补齐窄窗口单列布局 |
| UI-11 | `ResourceTable` 默认启用内部横向滚动，并允许调用方传入 scroll；补齐安全测试/ZAP 原生 Table 的横向滚动，保留已有纵向滚动参数 |
| UI-12 | Skill、Agent 和工具配置抽屉底部操作区改为可换行 flex，按钮组也允许换行，保存按钮组靠右 |
| UI-13 | Skill 编辑器高度改为动态视口范围，文件列表独立限高滚动；长路径允许折行，文件项为删除按钮保留空间，字数提示预留底部间距 |
| UI-14 | 报告安全摘要从固定六列改为小屏两列、中屏三列、大屏六列；安全工作区统计卡同步补齐小屏规则 |

附带处理：AI 助手输入支持 Shift+Enter 换行，中文输入法组合输入时不触发发送；极窄窗口下控制台顶栏按钮允许换行。

### 验证记录

| 检查 | 结果与边界 |
| --- | --- |
| `npm test` | 6 项通过、0 失败；含新增浅色/深色组件 CSS 回归测试，实际渲染 Table、Tabs、Tag、Menu、Progress、Layout、Typography 后检查样式 |
| 主题 CSS | 新增测试覆盖的浅色/深色生成结果均无 `token.*` 属性值；初次证据中为 25 处无效颜色声明。摘要见 [修复后验证记录](/Users/a1/Desktop/ai-test-project/docs/ui-audit-2026-10-28/verification-after-fix.json) |
| `npm run lint` | 通过，0 错误/警告 |
| `npm run build` | TypeScript 编译和 Vite 生产构建通过，无超过 500kB 的 chunk 警告 |
| `git diff --check` | 通过 |
| 浏览器视觉与交互验收 | 仍无可连接浏览器，未执行；第 6 节视口、长内容和键盘检查仍保留为验收清单 |

构建与单测不能证明实际像素布局、所有数据状态和移动端软键盘行为均无问题。当前完成的是全部列出问题的代码处理及可执行的静态/组件验证，视觉验收状态保持待执行。
