"""SQLAlchemy 声明式基类。

本模块只定义唯一的 Base 与 metadata，供核心模型、能力模型及 Alembic 共用；
不读取运行配置、不创建引擎，也不导入模型或上层业务包。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型共用的唯一声明式基类与 metadata。"""
