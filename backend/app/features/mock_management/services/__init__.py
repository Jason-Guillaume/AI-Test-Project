"""Mock Management 服务层。

服务无状态，路由层复用单例（与 test_data / test_management 一致）。每个服务 owns commit，
事务边界与现有 feature 对齐。跨 feature 不互 import service（红线 17），可见性校验
各自维护一份 ``_access.py``；本 feature 的执行面（runtime）由 ``MockRuntimeService``
单独承担，与管理面（本包 CRUD）共享同一组模型与 ``_access`` 口径。
"""

from __future__ import annotations
