"""项目模块：项目、项目成员与出站目标。

负责项目的 CRUD、成员角色管理（viewer/member/editor）与项目出站白名单目标。
可见性统一收敛到 service 层，router 不重复判断。
"""
