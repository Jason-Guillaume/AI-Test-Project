"""统一分页、查询参数校验与列表响应。

旧项目使用 skip/limit 偏移分页且各接口各自实现；这里集中成一套：
- 查询参数：page（ge=1, 默认 1）、page_size（ge=1, le=200, 默认 20）、keyword
- 响应：{items, total, page, page_size}
"""

from __future__ import annotations

from typing import Any

from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import Query as SqlAlchemyQuery

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> tuple[int, int]:
    """声明统一分页查询参数，供各路由直接依赖注入。"""
    return page, page_size


def apply_page(query: SqlAlchemyQuery, page: int, page_size: int) -> SqlAlchemyQuery:
    """按页码与页大小截取查询结果。"""
    # page 从 1 开始，故偏移量为 (page - 1) * page_size。
    return query.offset((page - 1) * page_size).limit(page_size)


def apply_keyword(query: SqlAlchemyQuery, columns: list[Any], keyword: str | None) -> SqlAlchemyQuery:
    """对指定列做不区分大小写的模糊匹配；keyword 为空时不附加条件。"""
    value = (keyword or "").strip()
    if not value:
        return query
    pattern = f"%{value}%"
    from sqlalchemy import or_

    # ilike 是不区分大小写的模式匹配，前后通配表示「包含关键字」。
    conditions = [col.ilike(pattern) for col in columns]
    return query.filter(or_(*conditions))


def paginate(query: SqlAlchemyQuery, page: int, page_size: int, items: list[Any] | None = None) -> dict[str, Any]:
    """构建统一分页响应。items 为 None 时按偏移执行查询。

    Args:
        page: 页码，从 1 开始（已由 page_params 约束 ge=1）。
        page_size: 每页条数（已由 page_params 约束 1..200）。
        items: 调用方已取好的行；为 None 时本函数自己按偏移查询，便于复用同一段查询。

    Returns:
        dict[str, Any]: {items, total, page, page_size}。total 为未分页的总条数，
        前端据此判断是否还有下一页。
    """
    # 单独构造计数查询：先剥掉任何既有排序，避免排序表达式干扰 count 聚合。
    count_query = query.order_by(None) if query.statement is not None else query
    total = int(count_query.with_entities(func.count()).order_by(None).scalar() or 0)
    if items is None:
        items = apply_page(query, page, page_size).all()
    # 响应结构对前端稳定：page/page_size 回显请求值，total 与 items 数量可以不一致。
    return {"items": items, "total": total, "page": page, "page_size": page_size}
