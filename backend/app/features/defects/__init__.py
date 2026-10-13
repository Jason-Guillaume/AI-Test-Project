"""缺陷管理模块。

Phase-1 范围（**已接入**）：
- Bug 表的 CRUD（新增、列表、详情、修改、删除）
- 项目内可见性：只有对该 project 有访问权限的用户能看到与修改该项目的缺陷
- 权限：读为 viewer+，写（增/改/删）为 member+；对齐旧项目 ROLE_MEMBER 语义
- 通知：defect.created / defect.assigned / defect.status_changed 三个事件

Phase-1 范围外（**未接入**，属后续阶段）：
- 缺陷回归关联（DefectRegressionLink）：依赖 CaseGenerationRun / TestPoint 表，
  Phase-1 尚未建立
- 各渠道执行证据（Jenkins/GitLab/禅道 等）：与测试执行链路一起接入
- 缺陷趋势看板、修复时长统计等聚合指标
- 通知渠道推送（邮件/短信/IM）：目前只写库，未做实际推送
"""
