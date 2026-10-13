"""ORM 基类（与 shared.database 中的 Base 为同一对象）。"""

# 本文件只做再导出，不重复声明 declarative_base()。
# 真正的 Base 由 app.shared.database 定义，模型模块与 Alembic 都从这里拿到同一个
# metadata 命名空间；若在多处各建一个 Base，迁移将看不到另一半的表。
from app.shared.database import Base  # noqa: F401
