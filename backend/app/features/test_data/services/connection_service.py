"""被测库连接（TargetDatabaseConnection）与数据库访问策略（DatabaseAccessPolicy）服务层。

两条硬约束：
- 连接与策略的写操作只给**平台管理员**（项目成员一律 403）；
- password 只在创建/修改时接收一次明文，服务端用 `encrypt_secret` 加密落库，
  响应体只返回 `password_set`，永远不回传密码。

`/ping` 只做 `SELECT 1` 连通性探测，短连接、显式超时，不做任何 DML。
service owns commit。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.test_data.models.connection import (
    DatabaseAccessPolicy,
    TargetDatabaseConnection,
)
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.schemas import (
    DB_ENV_CLASSES,
    DatabasePolicyListResponse,
    DatabasePolicyResponse,
    DatabasePolicyUpsert,
    TargetDbConnectionCreate,
    TargetDbConnectionListResponse,
    TargetDbConnectionResponse,
    TargetDbConnectionUpdate,
)
from app.features.test_data.security import db_guard
from app.features.environment_configuration.services.environment_service import resolve_project_environment
from app.features.test_data.services._access import (
    get_project_or_404,
    require_admin,
    require_admin_project,
    require_writable_project,
    resolve_connection_project_id,
    resolve_policy_project_id,
)
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import (
    CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
    CODE_DATABASE_OPERATION_FORBIDDEN,
    AppError,
    bad_request,
    conflict,
    not_found,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE

# 连通性探测的最长等待；不重试，失败直接返回给调用方。
PING_TIMEOUT_SECONDS = 5


def _get_environment_or_404(db: Session, project_id: int, environment_id: int) -> Environment:
    """取项目已关联且启用的环境；连接与策略不能跨项目复用环境。"""
    return resolve_project_environment(db, project_id, environment_id)


def _referenced_count(db: Session, project_id: int, connection_id: int) -> int:
    """统计有多少 Provider 配置引用了这个连接。"""
    rows = (
        db.query(DataProvider.config_json)
        .filter(DataProvider.project_id == project_id)
        .all()
    )
    count = 0
    for (config,) in rows:
        if isinstance(config, dict) and config.get("connection_id") == connection_id:
            count += 1
    return count


def _connection_response(conn: TargetDatabaseConnection, db: Session) -> TargetDbConnectionResponse:
    """响应体只有 password_set，没有 password 字段。"""
    resp = TargetDbConnectionResponse.model_validate(conn)
    env = db.get(Environment, conn.environment_id)
    resp.environment_name = env.name if env is not None else None
    resp.environment_class = db_guard.environment_class(env) if env is not None else None
    resp.password_set = bool(conn.password_encrypted)
    resp.referenced_count = _referenced_count(db, conn.project_id, conn.id)
    return resp


def _policy_response(policy: DatabaseAccessPolicy, db: Session) -> DatabasePolicyResponse:
    """构造策略响应数据。"""
    resp = DatabasePolicyResponse.model_validate(policy)
    env = db.get(Environment, policy.environment_id)
    resp.environment_name = env.name if env is not None else None
    from app.features.environment_configuration.models import ProjectEnvironment
    binding = db.query(ProjectEnvironment).filter_by(
        project_id=policy.project_id, environment_id=policy.environment_id
    ).first()
    resp.environment_display_name = (
        (binding.display_name or env.display_name or env.name)
        if binding is not None and env is not None else (env.display_name if env is not None else None)
    )
    resp.environment_class = db_guard.environment_class(env) if env is not None else "STAGING"
    return resp


def _validate_policy_shapes(body: DatabasePolicyUpsert) -> tuple[list[str], list[str]]:
    """保存前校验白名单：表名必须是合法标识符，操作必须在白名单内。"""
    tables = db_guard.validate_allowed_tables(body.allowed_tables)
    operations = db_guard.validate_allowed_operations(body.allowed_operations)
    return tables, operations


class ConnectionService:
    """被测库连接服务。无状态，路由层复用单例。"""

    def list_connections(
        self, db: Session, project_id: int, user: User, *,
        environment_id: int | None = None,
        keyword: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TargetDbConnectionListResponse:
        """列出`connections`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(TargetDatabaseConnection).filter(
            TargetDatabaseConnection.project_id == project_id
        )
        if environment_id is not None:
            q = q.filter(TargetDatabaseConnection.environment_id == environment_id)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(
                TargetDatabaseConnection.name.ilike(f"%{kw}%")
                | TargetDatabaseConnection.host.ilike(f"%{kw}%")
                | TargetDatabaseConnection.database_name.ilike(f"%{kw}%")
            )
        total = int(q.count())
        items = q.order_by(TargetDatabaseConnection.id.desc())
        items = items.offset((page - 1) * page_size).limit(page_size).all()
        return TargetDbConnectionListResponse(
            items=[_connection_response(c, db) for c in items],
            total=total, page=page, page_size=page_size,
        )

    def get_connection(self, db: Session, connection_id: int, user: User) -> TargetDbConnectionResponse:
        """获取连接。"""
        return _connection_response(self._get_or_404(db, connection_id, user), db)

    def create_connection(
        self, db: Session, project_id: int, body: TargetDbConnectionCreate, *, actor: User,
    ) -> TargetDbConnectionResponse:
        """创建连接。"""
        project = require_admin_project(db, project_id, actor)
        env = _get_environment_or_404(db, project.id, body.environment_id)
        if db_guard.environment_class(env) not in DB_ENV_CLASSES:
            raise bad_request("环境归类非法")
        name = body.name.strip()
        if not name:
            raise bad_request("连接名称不能为空")
        if db.query(TargetDatabaseConnection).filter(
            TargetDatabaseConnection.project_id == project.id,
            TargetDatabaseConnection.name == name,
        ).first() is not None:
            raise conflict("同项目下连接名称已存在")
        if body.schema_name:
            db_guard.validate_identifier(body.schema_name, field="schema")

        conn = TargetDatabaseConnection(
            project_id=project.id,
            environment_id=env.id,
            name=name,
            host=body.host.strip(),
            port=body.port,
            database_name=body.database_name.strip(),
            username=body.username.strip(),
            password_encrypted=encrypt_secret(body.password),
            schema_name=(body.schema_name or "").strip() or None,
            enabled=body.enabled,
            created_by=actor.id,
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
        return _connection_response(conn, db)

    def update_connection(
        self, db: Session, connection_id: int, body: TargetDbConnectionUpdate, *, actor: User,
    ) -> TargetDbConnectionResponse:
        """更新连接。"""
        conn = self._get_writable_or_404(db, connection_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _connection_response(conn, db)

        name = data.get("name")
        if name is not None:
            if not name.strip():
                raise bad_request("连接名称不能为空")
            if db.query(TargetDatabaseConnection).filter(
                TargetDatabaseConnection.project_id == conn.project_id,
                TargetDatabaseConnection.name == name.strip(),
                TargetDatabaseConnection.id != conn.id,
            ).first() is not None:
                raise conflict("同项目下连接名称已存在")
            conn.name = name.strip()
        for field in ("host", "database_name", "username"):
            value = data.get(field)
            if value is not None:
                if not str(value).strip():
                    raise bad_request(f"{field} 不能为空")
                setattr(conn, field, str(value).strip())
        if data.get("port") is not None:
            conn.port = data["port"]
        if data.get("schema_name") is not None:
            schema = data["schema_name"].strip() or None
            if schema:
                db_guard.validate_identifier(schema, field="schema")
            conn.schema_name = schema
        if data.get("enabled") is not None:
            conn.enabled = bool(data["enabled"])
        # password 缺省表示不改；显式传入才重新加密落库。
        if data.get("password") is not None and str(data["password"]).strip():
            conn.password_encrypted = encrypt_secret(str(data["password"]))

        db.commit()
        db.refresh(conn)
        return _connection_response(conn, db)

    def delete_connection(self, db: Session, connection_id: int, *, actor: User) -> None:
        """删除连接。"""
        conn = self._get_writable_or_404(db, connection_id, actor)
        used = _referenced_count(db, conn.project_id, conn.id)
        if used:
            raise conflict(f"该连接正被 {used} 个 Provider 引用，请先移除引用")
        db.delete(conn)
        db.commit()

    def ping(self, db: Session, connection_id: int, user: User) -> dict:
        """连通性探测：只执行 SELECT 1，短连接、显式超时，不做任何 DML。"""
        conn = self._get_or_404(db, connection_id, user)
        if not conn.enabled:
            raise bad_request("连接已停用")
        password = decrypt_secret(conn.password_encrypted)
        import time

        import psycopg

        started = time.perf_counter()
        try:
            with psycopg.connect(
                host=conn.host,
                port=conn.port,
                dbname=conn.database_name,
                user=conn.username,
                password=password or None,
                connect_timeout=PING_TIMEOUT_SECONDS,
            ) as connection:
                with connection.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
        except Exception as exc:  # noqa: BLE001  网络层异常类型繁多，统一转业务错误
            return {
                "connection_id": conn.id,
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc)[:500],
            }
        return {
            "connection_id": conn.id,
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": None,
        }

    def get_decrypted_for_runtime(self, db: Session, connection_id: int) -> TargetDatabaseConnection:
        """内部使用：runtime 取连接行（不解密，执行方自行解密并短连接）。"""
        return db.get(TargetDatabaseConnection, connection_id)

    def _get_or_404(self, db: Session, connection_id: int, user: User) -> TargetDatabaseConnection:
        """获取或。"""
        row = db.get(TargetDatabaseConnection, connection_id)
        if row is None:
            raise not_found("被测库连接不存在")
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, connection_id: int, actor: User) -> TargetDatabaseConnection:
        """获取可写或。"""
        row = db.get(TargetDatabaseConnection, connection_id)
        if row is None:
            raise not_found("被测库连接不存在")
        require_admin(db, actor)
        require_writable_project(db, resolve_connection_project_id(db, connection_id), actor)
        return row


class PolicyService:
    """数据库访问策略服务：项目成员可读，平台管理员可写。"""

    def list_policies(
        self, db: Session, project_id: int, user: User, *,
        environment_id: int | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> DatabasePolicyListResponse:
        """列出`policies`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(DatabaseAccessPolicy).filter(
            DatabaseAccessPolicy.project_id == project_id
        )
        if environment_id is not None:
            q = q.filter(DatabaseAccessPolicy.environment_id == environment_id)
        total = int(q.count())
        items = q.order_by(DatabaseAccessPolicy.id.desc())
        items = items.offset((page - 1) * page_size).limit(page_size).all()
        return DatabasePolicyListResponse(
            items=[_policy_response(p, db) for p in items],
            total=total, page=page, page_size=page_size,
        )

    def get_policy(self, db: Session, policy_id: int, user: User) -> DatabasePolicyResponse:
        """获取策略。"""
        row = db.get(DatabaseAccessPolicy, policy_id)
        if row is None:
            raise not_found("数据库访问策略不存在")
        get_project_or_404(db, row.project_id, user)
        return _policy_response(row, db)

    def get_policy_for(
        self, db: Session, project_id: int, environment_id: int
    ) -> DatabaseAccessPolicy | None:
        """内部使用：按项目 + 环境取策略行（供执行前校验）。"""
        return (
            db.query(DatabaseAccessPolicy)
            .filter(
                DatabaseAccessPolicy.project_id == project_id,
                DatabaseAccessPolicy.environment_id == environment_id,
            )
            .first()
        )

    def upsert_policy(
        self,
        db: Session,
        project_id: int,
        environment_id: int,
        body: DatabasePolicyUpsert,
        *,
        actor: User,
    ) -> DatabasePolicyResponse:
        """设置某环境下的策略：环境必须存在；PRODUCTION 不允许 enabled=true。"""
        project = require_admin_project(db, project_id, actor)
        env = _get_environment_or_404(db, project.id, environment_id)
        env_class = db_guard.environment_class(env)
        if body.enabled and env_class == "PRODUCTION":
            raise AppError(
                "生产环境禁止开启数据库造数策略",
                status_code=400,
                code=CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
            )
        tables, operations = _validate_policy_shapes(body)
        if body.enabled and not operations:
            raise AppError(
                "策略开启时操作白名单不能为空",
                status_code=400,
                code=CODE_DATABASE_OPERATION_FORBIDDEN,
            )

        row = (
            db.query(DatabaseAccessPolicy)
            .filter(
                DatabaseAccessPolicy.project_id == project.id,
                DatabaseAccessPolicy.environment_id == env.id,
            )
            .first()
        )
        if row is None:
            row = DatabaseAccessPolicy(
                project_id=project.id,
                environment_id=env.id,
                created_by=actor.id,
            )
            db.add(row)
        row.enabled = bool(body.enabled)
        row.allowed_tables = tables
        row.allowed_operations = operations
        db.commit()
        db.refresh(row)
        return _policy_response(row, db)

    def _get_writable_or_404(self, db: Session, policy_id: int, actor: User) -> DatabaseAccessPolicy:
        """获取可写或。"""
        row = db.get(DatabaseAccessPolicy, policy_id)
        if row is None:
            raise not_found("数据库访问策略不存在")
        require_admin(db, actor)
        require_writable_project(db, resolve_policy_project_id(db, policy_id), actor)
        return row


__all__ = ["ConnectionService", "PolicyService"]
