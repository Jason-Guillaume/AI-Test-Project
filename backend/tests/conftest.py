"""测试夹具：隔离测试数据库 + Alembic 迁移 + 共享 TestClient + API 助手。

约定：
- 每个测试会话使用独立数据库（默认 ``testplatform_test-p<pid>``），与开发库隔离，
  绝不复用 ``testplatform_dev``，也不对生产库执行任何写操作；pid 后缀保证两个
  pytest 进程并发跑时互不删库。
- 表结构一律由 Alembic 从 base 迁移到 head 生成，测试不依赖应用启动期建表。
- 密钥与速率限制通过环境变量固定/放宽，避免测试之间相互影响。
- 本模块被 tests/ 下所有测试文件隐式复用：pytest 自动发现 fixture，测试函数
  自己只写断言，不重复搭库、迁移与登录样板。
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

# 后端仓库根目录（tests/ 的上一级）：必须先注入 sys.path，app.* 才能被导入。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 隔离 PostgreSQL 的连接参数：全部可由环境变量覆盖，默认连本机 5432。
TEST_DB_HOST = os.environ.get("TEST_POSTGRES_HOST", "127.0.0.1")
TEST_DB_PORT = os.environ.get("TEST_POSTGRES_PORT", "5432")
TEST_DB_USER = os.environ.get("TEST_POSTGRES_USER", "root")
TEST_DB_PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))
if not TEST_DB_PASSWORD:
    raise RuntimeError("运行后端测试前请显式设置 TEST_POSTGRES_PASSWORD")
# 测试库名在物理上仍与开发库、生产库分离，但按进程加唯一后缀：两个 pytest 进程
# 并发跑（本地一份 + CI 一份，或两个人各起一份）时各用各的库，后启动的会话不再
# DROP 掉前者仍在用的库、也不再 terminate 掉其连接——否则两边会批量报
# connection already closed / database does not exist，看起来像产品缺陷。
# 这里定义一次即为单一事实源：test_01 / test_07 都靠 TEST_DSN 里的库名派生自己
# 的目标库，不需要各自重复拼后缀。PostgreSQL 标识符上限 63 字符，
# "testplatform_test-p12345678" 远未越界。
TEST_DATABASE_NAME = (
    os.environ.get("TEST_DATABASE_NAME") or f"testplatform_test-p{os.getpid()}"
)

# 应用侧 DSN 用 SQLAlchemy 方言 psycopg。
TEST_DSN = (
    f"postgresql+psycopg://{TEST_DB_USER}:{TEST_DB_PASSWORD}"
    f"@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DATABASE_NAME}"
)
# 管理 DSN 指向 postgres 维护库：只有它有权执行 DROP / CREATE DATABASE。
ADMIN_DSN = (
    f"postgresql://{TEST_DB_USER}:{TEST_DB_PASSWORD}"
    f"@{TEST_DB_HOST}:{TEST_DB_PORT}/postgres"
)

# 必须在导入 app 之前设置，Settings 在导入时即读取环境变量。
# 库名回写环境变量：test_07 等文件直接从 os.environ 读库名，与 TEST_DSN 里的
# 库名不一致时 TEST_DSN.replace 会留下 "-p<pid>" 尾巴，探测库名整个错掉。
os.environ["TEST_DATABASE_NAME"] = TEST_DATABASE_NAME
os.environ["DATABASE_URL"] = TEST_DSN
os.environ["AUTO_CREATE_SCHEMA"] = "false"
# 测试进程绝不启动 ZAP 扫描 Worker；需要验证 job_service 的用例会在应用 lifespan
# 启动后单独切换设置，因此不会对外部扫描器发出网络请求。
os.environ["ZAP_ENABLED"] = "false"
os.environ["SECRET_KEY"] = os.environ.get(
    "TEST_SECRET_KEY", "unit-test-secret-not-for-production"
)
# 限流阈值全部调到极大值：测试只想验功能，不想被限流干扰。
os.environ["AUTH_LOGIN_IP_LIMIT_PER_MINUTE"] = "1000000"
os.environ["AUTH_LOGIN_USERNAME_LIMIT_PER_MINUTE"] = "1000000"
os.environ["AUTH_REGISTER_IP_LIMIT_PER_HOUR"] = "1000000"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

API = "/api/v1"
DEFAULT_PASSWORD = "Init-Password-123"
DEFAULT_NEW_PASSWORD = "New-Password-4567"

# 迁移产物应覆盖的全部业务表；test_01 / test_07 用它断言「表结构由 Alembic 生成」。
EXPECTED_TABLES = frozenset(
    {
        "user",
        "organization",
        "organization_member",
        "project",
        "project_member",
        "project_outbound_target",
        "model_configuration",
        "environment",
        "notification",
        "bug",
    }
)


def unique(prefix: str) -> str:
    """生成全局唯一标识，避免测试间数据冲突。

    Args:
        prefix: 语义前缀（如 "alice"），便于失败时从日志里认出是哪组数据。
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _terminate_connections(database_name: str) -> None:
    """断开指向目标库的连接，便于重建数据库。

    必须排除本连接自身（pg_backend_pid()），否则 DROP DATABASE 会杀掉
    自己所在的会话，随后语句报错。
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid <> pg_backend_pid()",
                (database_name,),
            )


def _run_migrations() -> str:
    """用 Alembic 从 base 迁移到 head，返回当前版本。

    Returns:
        Alembic head 版本字符串（例如 "0001"），供调用方断言迁移落到位。
    """
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DSN)
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.stamp(config, "base")
    command.upgrade(config, "head")
    return ScriptDirectory.from_config(config).get_current_head()


def migration_head() -> str:
    """读取仓库当前 Alembic head，避免功能测试把迁移版本写死。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


@pytest.fixture(scope="session")
def test_database():
    """准备隔离测试数据库并执行迁移；会话结束后删除自己派生的库。

    隔离手法：会话开始就 DROP + CREATE 一个全新库，因此绝不继承上一次
    运行残留的行；表结构只由 Alembic 生成，不依赖应用 create_all。

    库名带 pid 后缀（见 TEST_DATABASE_NAME），两个 pytest 进程并发跑时各建各的
    库，不会互相 DROP。teardown 只删自己的库名，因此两个后缀一起才安全：pid
    复用后可能撞上上一次会话留下的同名旧库，靠 teardown 让残留变得无关紧要。

    Yields:
        str: 本次会话使用的测试库名。
    """
    # CREATE / DROP DATABASE 不能在事务里执行，必须 autocommit + 走维护库。
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DATABASE_NAME,)
            )
            if cursor.fetchone():
                # 库里已有残留连接时先全部断开，否则 DROP 会被拒绝。残留通常来自
                # 上一次会话没走到 teardown，或 pid 被复用撞上旧库。
                _terminate_connections(TEST_DATABASE_NAME)
                cursor.execute(f'DROP DATABASE "{TEST_DATABASE_NAME}"')
            cursor.execute(f'CREATE DATABASE "{TEST_DATABASE_NAME}"')

    _run_migrations()
    yield TEST_DATABASE_NAME

    # 只删除本会话派生的库名：pid 后缀保证了这个库名唯一属于本进程。要先断开
    # 残留连接（SQLAlchemy engine 池在会话结束时并不会自动 dispose）。
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            _terminate_connections(TEST_DATABASE_NAME)
            cursor.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}"')


@pytest.fixture(scope="session")
def client(test_database):
    """共享 TestClient，覆盖应用 lifespan（记录启动、不建表）。

    整个会话只启动一次应用，避免每个用例都重跑启动流程；依赖的表结构
    已经在 test_database 里由迁移建好。

    Yields:
        TestClient: 可直接发 HTTP 请求的客户端。
    """
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(test_database):
    """每测试独立会话，避免读到其它测试未提交的旧数据。

    每个测试拿到一个全新的 SQLAlchemy Session：既保证读到的都是已提交数据，
    也在测试结束时 close，不泄漏连接。

    Yields:
        Session: 与隔离测试库绑定的数据库会话。
    """
    from app.core.database.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def api(client):
    """带鉴权上下文的请求助手。

    Yields:
        ApiClient: 封装了 /api/v1 前缀、Bearer 头与令牌缓存的客户端。
    """
    return ApiClient(client)


@pytest.fixture(scope="session")
def admin_user():
    """返回平台管理员用户名（固定名称，便于多个测试复用同一管理员）。

    Yields:
        str: 固定管理员用户名。
    """
    return "platform_admin"


@pytest.fixture()
def admin(api, admin_user):
    """用显式命令方式初始化的管理员：等价于 seed_admin.py 产生的账号。

    直接在测试库写入，模拟「管理员由显式初始化命令创建」的前置条件，
    再通过 HTTP 登录，保证后续所有请求都走真实鉴权链路。

    Args:
        api: 请求助手，登录成功后令牌被缓存，重复调用不会重复建号。
        admin_user: 固定管理员用户名。
    Returns:
        str: 管理员用户名，可直接作为 api 调用的 username 参数。
    """
    if admin_user in api.tokens:
        return admin_user
    from app.core.models.identity import Organization, User
    from app.core.database.session import SessionLocal
    from app.core.security.passwords import hash_password
    from app.platform.organizations.services.organization_service import ensure_personal_organization

    with SessionLocal() as session:
        existing = (
            session.query(User).filter(User.username == admin_user).first()
        )
        if existing is None:
            # token_version 初值 0：与注册接口保持一致，改密/改角色时递增。
            admin = User(
                username=admin_user,
                hashed_password=hash_password(DEFAULT_PASSWORD),
                role="admin",
                token_version=0,
            )
            session.add(admin)
            session.flush()
            ensure_personal_organization(session, admin)
            session.commit()
    api.login(admin_user, DEFAULT_PASSWORD)
    return admin_user


class ApiClient:
    """对 /api/v1 的薄封装：登录缓存令牌，减少重复样板。

    职责只有两件事：自动补全 /api/v1 前缀与 Bearer 头，以及在 self.tokens 里
    缓存「用户名 -> access_token」，让同一测试会话不必反复登录。
    """

    def __init__(self, client: TestClient):
        """保存底层 TestClient 并初始化令牌缓存表。

        Args:
            client: pytest client fixture 产出的 TestClient（已走过应用 lifespan）。
        """
        self.client = client
        self.tokens: dict[str, str] = {}

    # ------------------------------------------------------------ 认证

    def register(self, username: str, password: str = DEFAULT_PASSWORD):
        """调用 POST /register 创建账号，返回原始响应（由调用方断言状态码）。

        Args:
            username: 新用户名的用户名，约定由 unique() 生成以避免冲突。
            password: 注册密码，默认使用测试统一初始密码。
        """
        return self.client.post(
            f"{API}/register",
            json={"username": username, "password": password},
        )

    def login(self, username: str, password: str = DEFAULT_PASSWORD) -> str:
        """调用 POST /login 换取 access_token，并写入令牌缓存后返回。

        登录失败直接 assert 报错——测试里出现「登录不上」永远是环境或前置
        数据问题，没有「优雅处理」的必要。

        Args:
            username: 已存在且处于启用状态的用户名。
            password: 登录密码；改密类用例会显式传入新密码。
        Returns:
            str: 新签发的 access_token，同时被缓存到 self.tokens[username]。
        """
        response = self.client.post(
            f"{API}/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        self.tokens[username] = token
        return token

    def create_admin(
        self, admin_username: str, username: str, password: str = DEFAULT_PASSWORD
    ):
        """以管理员身份调用 POST /users 创建账号（角色固定写死为 test 角色）。

        Args:
            admin_username: 已在缓存中登录过令牌的管理员用户名。
            username: 待创建账号的用户名。
            password: 待创建账号的初始密码。
        """
        return self.post(
            f"{API}/users",
            json={"username": username, "password": password, "role": "test"},
            token=self.tokens[admin_username],
        )

    # ------------------------------------------------------------ 鉴权头

    def headers(self, username: str | None = None, token: str | None = None) -> dict[str, str]:
        """按优先级拼装 Authorization 头：显式 token > 缓存用户名 > 无头。

        两个参数都缺省时返回空 dict，用于「未登录」类负向用例。

        Args:
            username: 从缓存取令牌的登录用户名。
            token: 直接使用的令牌（用于验证「特定令牌」是否失效）。
        """
        if token:
            return {"Authorization": f"Bearer {token}"}
        if username:
            stored = self.tokens.get(username)
            if stored:
                return {"Authorization": f"Bearer {stored}"}
        return {}

    # ------------------------------------------------------------ 请求

    def get(
        self, path: str, username: str | None = None, token: str | None = None, **kwargs: Any
    ):
        """发 GET 请求；path 以 / 开头，自动拼上 /api/v1 前缀。

        Args:
            path: 相对 /api/v1 的路径（如 "/me"）。
            kwargs: 透传给 TestClient，例如 params=、json=。
        """
        return self.client.get(f"{API}{path}", headers=self.headers(username, token), **kwargs)

    def post(
        self,
        path: str,
        username: str | None = None,
        token: str | None = None,
        **kwargs: Any,
    ):
        """发 POST 请求，语义与 get 相同，只是方法不同。"""
        return self.client.post(
            f"{API}{path}", headers=self.headers(username, token), **kwargs
        )

    def patch(
        self,
        path: str,
        username: str | None = None,
        token: str | None = None,
        **kwargs: Any,
    ):
        """发 PATCH 请求，用于部分更新（改密码、改角色、改用户名等）。"""
        return self.client.patch(
            f"{API}{path}", headers=self.headers(username, token), **kwargs
        )

    def put(
        self,
        path: str,
        username: str | None = None,
        token: str | None = None,
        **kwargs: Any
    ):
        """发 PUT 请求，主要用于成员授权这类幂等 upsert 接口。"""
        return self.client.put(
            f"{API}{path}", headers=self.headers(username, token), **kwargs
        )

    def delete(
        self,
        path: str,
        username: str | None = None,
        token: str | None = None,
        **kwargs: Any,
    ):
        """发 DELETE 请求，成功时服务端返回 204（无响应体）。"""
        return self.client.delete(
            f"{API}{path}", headers=self.headers(username, token), **kwargs
        )
