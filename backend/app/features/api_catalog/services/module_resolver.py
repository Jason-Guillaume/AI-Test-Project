"""统一 ModuleResolver：所有外部格式统一在此决定接口归属模块，不在各 parser 里写。

优先级（spec §6 唯一实现）：
1. user_module_id 非空且属于本项目 → 直接用；
2. tag_to_module_map 命中 schema.tags → 用映射的 module_id；
3. schema.tags 非空 → 按首个 tag find-or-create 一级模块；
4. 已有 path→module 映射：本项目同 path 首段前缀的接口复用其 module_id；
5. schema.suggested_module（parser 由 URL 路径推断）→ find-or-create；
6. 都失败 → ensure_default_module（未分类）。

模块最大两级：find_or_create_module 校验 parent 的 parent 必须为 None。
未分类模块 is_default=True，不可删/不可改名（由 api_service 强制）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.schemas import InternalApiSchema
from app.shared.errors import bad_request

DEFAULT_MODULE_NAME = "未分类"

# URL 路径推断时过滤的公共段：这些段不携带业务语义，不应作为模块名。
_PATH_NOISE_SEGMENTS: frozenset[str] = frozenset(
    {
        "api", "apis", "v1", "v2", "v3", "v4", "rest", "openapi", "swagger",
        "service", "services", "app", "public", "private", "internal",
        "gateway", "gw", "backend", "server",
    }
)


def infer_module_name_from_path(path: str) -> str | None:
    """从 URL 路径推断模块名：取首个非公共、非纯数字段，去花括号，截 100 字符。"""
    for seg in (path or "").split("/"):
        if not seg or seg.startswith("{") or " " in seg:
            continue
        low = seg.lower()
        if low in _PATH_NOISE_SEGMENTS or low.isdigit():
            continue
        clean = seg.strip("{}")
        if not clean:
            continue
        return clean[:100]
    return None


def _path_first_segment(path: str) -> str:
    """取路径第一个实际段，用于同源前缀复用。"""
    for seg in (path or "").split("/"):
        if seg:
            return seg
    return ""


class ModuleResolver:
    """统一模块解析器。无状态，可跨调用复用。"""

    def ensure_default_module(self, db: Session, project_id: int) -> ApiModule:
        """get-or-create 未分类模块（is_default=True）。"""
        existing = (
            db.query(ApiModule)
            .filter(
                ApiModule.project_id == project_id,
                ApiModule.is_default.is_(True),
            )
            .one_or_none()
        )
        if existing is not None:
            return existing
        default = ApiModule(
            project_id=project_id,
            name=DEFAULT_MODULE_NAME,
            is_default=True,
            sort=0,
        )
        db.add(default)
        db.flush()
        return default

    def find_or_create_module(
        self,
        db: Session,
        project_id: int,
        name: str,
        parent_id: int | None = None,
    ) -> ApiModule:
        """按名查找本项目模块，找不到则创建；parent_id 指定时校验两级。"""
        name = (name or "").strip()
        if not name:
            return self.ensure_default_module(db, project_id)
        existing = (
            db.query(ApiModule)
            .filter(
                ApiModule.project_id == project_id,
                ApiModule.name == name,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing
        if parent_id is not None:
            parent = db.get(ApiModule, parent_id)
            if parent is None or parent.project_id != project_id:
                raise bad_request("父模块不存在或不属于当前项目")
            if parent.parent_id is not None:
                raise bad_request("模块最多两级，不能嵌套到第三级")
            if parent.is_default:
                # 未分类作为父模块没有意义，拒绝以保持树整洁。
                raise bad_request("未分类模块不能作为父模块")
        mod = ApiModule(project_id=project_id, name=name, parent_id=parent_id, sort=0)
        db.add(mod)
        db.flush()
        return mod

    def resolve(
        self,
        db: Session,
        project_id: int,
        schema: InternalApiSchema,
        *,
        user_module_id: int | None = None,
        tag_to_module_map: dict[str, int] | None = None,
    ) -> int:
        """按优先级解析模块，返回 module_id。"""
        # 1. 用户显式指定
        if user_module_id is not None:
            mod = db.get(ApiModule, user_module_id)
            if mod is not None and mod.project_id == project_id:
                return mod.id
            # 不属于本项目 → 视为无效，继续后续策略（保证批量导入韧性）。
        # 2. tag→module 显式映射
        if tag_to_module_map and schema.tags:
            for tag in schema.tags:
                mid = tag_to_module_map.get(tag)
                if mid is not None:
                    m = db.get(ApiModule, mid)
                    if m is not None and m.project_id == project_id:
                        return m.id
        # 3. tags 非空 → 按首个 tag find-or-create 一级模块
        if schema.tags:
            first = (schema.tags[0] or "").strip()
            if first:
                return self.find_or_create_module(db, project_id, first).id
        # 4. 已有 path→module 映射：同首段前缀的接口复用其 module_id
        first_seg = _path_first_segment(schema.path)
        if first_seg:
            like_pattern = f"/{first_seg}%"
            iface = (
                db.query(ApiInterface)
                .filter(ApiInterface.project_id == project_id)
                .filter(ApiInterface.path.like(like_pattern))
                .order_by(ApiInterface.id.asc())
                .first()
            )
            if iface is not None and iface.module_id is not None:
                return iface.module_id
        # 5. URL 路径推断（parser 已写入 suggested_module）
        if schema.suggested_module:
            return self.find_or_create_module(db, project_id, schema.suggested_module).id
        # 6. 未分类
        return self.ensure_default_module(db, project_id).id

    def resolve_dry(
        self,
        db: Session,
        project_id: int,
        schema: InternalApiSchema,
        *,
        user_module_id: int | None = None,
        tag_to_module_map: dict[str, int] | None = None,
    ) -> tuple[int | None, str]:
        """预览用 dry-run 解析：只查找已有模块，不创建任何模块（含未分类）。

        返回 (module_id_or_None, module_name)。module_id 为 None 表示确认时将新建该模块。
        """
        # 1. 用户显式指定
        if user_module_id is not None:
            mod = db.get(ApiModule, user_module_id)
            if mod is not None and mod.project_id == project_id:
                return mod.id, mod.name
        # 2. tag→module 显式映射
        if tag_to_module_map and schema.tags:
            for tag in schema.tags:
                mid = tag_to_module_map.get(tag)
                if mid is not None:
                    m = db.get(ApiModule, mid)
                    if m is not None and m.project_id == project_id:
                        return m.id, m.name
        # 3. tags 非空 → 查已有同名模块，找不到则提议新建
        if schema.tags:
            first = (schema.tags[0] or "").strip()
            if first:
                existing = (
                    db.query(ApiModule)
                    .filter(ApiModule.project_id == project_id, ApiModule.name == first)
                    .one_or_none()
                )
                if existing is not None:
                    return existing.id, existing.name
                return None, first
        # 4. 已有 path→module 映射
        first_seg = _path_first_segment(schema.path)
        if first_seg:
            like_pattern = f"/{first_seg}%"
            iface = (
                db.query(ApiInterface)
                .filter(ApiInterface.project_id == project_id)
                .filter(ApiInterface.path.like(like_pattern))
                .order_by(ApiInterface.id.asc())
                .first()
            )
            if iface is not None and iface.module_id is not None:
                mod = db.get(ApiModule, iface.module_id)
                return iface.module_id, (mod.name if mod else DEFAULT_MODULE_NAME)
        # 5. URL 路径推断 → 查已有同名模块，找不到则提议新建
        if schema.suggested_module:
            existing = (
                db.query(ApiModule)
                .filter(ApiModule.project_id == project_id, ApiModule.name == schema.suggested_module)
                .one_or_none()
            )
            if existing is not None:
                return existing.id, existing.name
            return None, schema.suggested_module
        # 6. 未分类（只查找，不创建）
        default = (
            db.query(ApiModule)
            .filter(ApiModule.project_id == project_id, ApiModule.is_default.is_(True))
            .one_or_none()
        )
        if default is not None:
            return default.id, default.name
        return None, DEFAULT_MODULE_NAME


__all__ = [
    "DEFAULT_MODULE_NAME",
    "infer_module_name_from_path",
    "ModuleResolver",
]
