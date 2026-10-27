"""全局配置。

所有配置项均来自环境变量或 .env，代码中不内置任何默认密钥或管理员凭据。
与旧项目对齐的关键项：DATABASE_URL / SECRET_KEY / ACCESS_TOKEN_EXPIRE_MINUTES。

CORS_ORIGINS 采用逗号分隔写法（如 `http://localhost:5173,http://127.0.0.1:5173`），
由 _CsvListSettingsSources 在设置来源层完成拆分，避免 pydantic-settings 默认按 JSON 解析。
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from dotenv import load_dotenv
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# 先加载 .env，再实例化 Settings，保证环境变量可以覆盖 .env 中的值。
load_dotenv()

# 需要在「设置来源层」特殊拆分的字段名集合；只有命中它的字段才走 _split_csv，
# 其余 list 字段仍交给 pydantic-settings 默认按 JSON 解析。
CORRELATION_FIELDS = ("CORS_ORIGINS",)


def _split_csv(value: str) -> list[str]:
    """把逗号分隔的字符串切成列表，去首尾空白并丢掉空段。

    Args:
        value: 形如 "a, b,,c" 的原始配置字符串（可能不是 list，统一先转 str）。

    Returns:
        list[str]: 拆分并清洗后的条目列表；输入为空串时返回空列表。
    """
    return [item.strip() for item in str(value).split(",") if item.strip()]


# 两个自定义设置来源成对出现：env 与 .env 各一份，行为完全一致，
# 保证同一个逗号分隔字段无论从哪种来源读取都得到同样的拆分结果。
class _CsvListEnvSource(EnvSettingsSource):
    """环境变量来源：逗号分隔的列表字段在此拆分。"""

    def decode_complex_value(self, field_name, field, value):
        """解码复杂类型字段：白名单字段按逗号拆分，其余转发给基类的 JSON 解析。

        Args:
            field_name: 配置字段名，用来判断是否命中 CORRELATION_FIELDS 白名单。
            field: 字段元信息（拆分路径不使用，仅原样转发给基类）。
            value: 环境变量中的原始字符串。

        Returns:
            list[str] | Any: 白名单字段返回拆分后的列表；其余返回基类解码结果。
        """
        if field_name in CORRELATION_FIELDS:
            return _split_csv(value)
        # 未命中白名单：保持 pydantic-settings 默认的 JSON 解析，避免误拆普通字段。
        return super().decode_complex_value(field_name, field, value)


class _CsvListDotEnvSource(DotEnvSettingsSource):
    """ .env 来源：同样支持逗号分隔的列表字段。"""

    def decode_complex_value(self, field_name, field, value):
        """解码复杂类型字段（.env 版本），行为与 _CsvListEnvSource 完全一致。

        Args:
            field_name: 配置字段名，用来判断是否命中 CORRELATION_FIELDS 白名单。
            field: 字段元信息（拆分路径不使用，仅原样转发给基类）。
            value: .env 文件中的原始字符串。

        Returns:
            list[str] | Any: 白名单字段返回拆分后的列表；其余返回基类解码结果。
        """
        if field_name in CORRELATION_FIELDS:
            return _split_csv(value)
        # 未命中白名单：保持 pydantic-settings 默认的 JSON 解析，避免误拆普通字段。
        return super().decode_complex_value(field_name, field, value)


class Settings(BaseSettings):
    """应用配置。"""

    # 应用标识：用作 OpenAPI 标题，并由 /api/v1/meta 接口对外暴露。
    PROJECT_NAME: str = "测试开发平台"
    VERSION: str = "1.0.0"

    # PostgreSQL 连接串，格式：postgresql+psycopg://用户:密码@主机:端口/库名
    DATABASE_URL: str | None = None

    # 主库连接池参数。
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800

    # 允许跨域的前端地址，逗号分隔。
    CORS_ORIGINS: Annotated[list[str], "逗号分隔"] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # 认证：JWT 密钥必须由环境变量显式提供，避免开发机之间的令牌可互相验签。
    SECRET_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # 模型 API Key 加密密钥；留空时由 SECRET_KEY 派生（旧项目同款规则）。
    MODEL_CONFIG_ENCRYPTION_KEY: str | None = None

    # 登录/注册速率限制（进程内滑动窗口）。
    AUTH_LOGIN_IP_LIMIT_PER_MINUTE: int = 60
    AUTH_LOGIN_USERNAME_LIMIT_PER_MINUTE: int = 10
    AUTH_REGISTER_IP_LIMIT_PER_HOUR: int = 10

    # 初始化管理员凭据，只被 scripts/seed_admin.py 读取，运行期无作用。
    INIT_ADMIN_USERNAME: str | None = None
    INIT_ADMIN_PASSWORD: str | None = None

    # Langfuse LLM 可观测（Agent 埋点）。
    # 三环境隔离约定：每个环境使用独立的 Langfuse project（各一套 key），
    # key 只通过部署侧环境变量 / 本地 .env 注入，绝不进版本库；
    # LANGFUSE_ENVIRONMENT 是 trace 上的 environment 标签，供同 project 内过滤。
    # 未启用或 key 不齐时埋点全部为 no-op，不影响主流程。
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"
    # trace 环境标签：development / test / production 之一。
    LANGFUSE_ENVIRONMENT: str = "development"

    # 默认关闭：表结构只通过 Alembic 变更，应用启动不自动改正式表结构。
    AUTO_CREATE_SCHEMA: bool = False

    # OWASP ZAP 安全扫描（Security Testing Phase 2）。
    # 部署形态：ZAP 官方 daemon 镜像与平台同网段运行，只在本机/内网监听；
    # ZAP 管理 API 不对外暴露（§三、§三十四 第 11 条）。
    # 未配置或 ZAP_ENABLED=False 时扫描入口可用但会明确返回「ZAP 服务未启用」，
    # 不伪造扫描结果（§三十九）。
    ZAP_ENABLED: bool = False
    # ZAP daemon REST API 地址，例如 http://127.0.0.1:8090。
    ZAP_BASE_URL: str | None = None
    # API Key 只以密文形式存在（§三「API Key 加密保存」）：环境变量给明文，
    # 落库/展示前一律先过 encrypt_secret；这里保存的是已加密的值。
    ZAP_API_KEY_ENCRYPTED: str | None = None
    # API Key 传递方式：header（推荐）或 query。query 模式会被代理日志记录，仅应急用。
    ZAP_API_KEY_MODE: str = "header"
    ZAP_VERIFY_TLS: bool = True
    ZAP_TIMEOUT_SECONDS: float = 30.0
    # 第一版同一 ZAP 实例同一时间只执行一个需要修改全局配置的任务（§八）。
    ZAP_MAX_CONCURRENT_JOBS: int = 1
    # Worker 轮询间隔与心跳：心跳超时用于判定「进程重启后残留的在跑任务」。
    ZAP_WORKER_POLL_INTERVAL_SECONDS: float = 3.0
    ZAP_HEARTBEAT_TIMEOUT_SECONDS: int = 180
    # 单个任务总时长上限（超时判 TIMED_OUT）与被动扫描等待上限。
    ZAP_MAX_JOB_DURATION_SECONDS: int = 7200
    ZAP_PASSIVE_WAIT_SECONDS: int = 300
    ZAP_REQUEST_BUDGET: int = 5000

    # 大小写敏感：环境变量名必须与字段名完全一致，避免 DATABASE_URL / database_url 双写歧义；
    # extra="ignore" 让 .env 里的历史遗留变量不报错，便于从旧项目平滑迁移。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """返回设置读取来源；元组的顺序就是取值优先级（靠前者覆盖靠后者）。

        约定：构造参数 > 环境变量 > .env 文件 > secret 文件。
        其中环境变量与 .env 两个来源被替换成逗号分隔版本的自定义实现，
        保证同一个字段无论从哪一层读取，拆分行为都一致。

        Returns:
            tuple[PydanticBaseSettingsSource, ...]: 供 pydantic-settings 依次读取的来源序列。
        """
        return (
            init_settings,
            _CsvListEnvSource(settings_cls),
            _CsvListDotEnvSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的配置单例。

    Returns:
        Settings: 首次调用时按环境变量/.env 实例化一次，之后由 lru_cache 复用同一对象；
        运行期修改环境变量不会生效，需重启进程重新导入。
    """
    return Settings()


# 模块导入即实例化：`from app.shared.config import settings` 的调用方拿到的就是已校验的单例。
settings = get_settings()

# 与旧项目保持一致的模块级别名，便于 `from app.shared.config import SECRET_KEY`。
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

# 启动期硬性校验：密钥缺失时直接让进程无法导入，避免上线后才发现无法签发令牌。
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY 环境变量未设置！请在 .env 或环境中提供。")


def runtime_secret_key() -> str:
    """返回当前生效的 SECRET_KEY，测试中可通过环境变量切换。"""
    return str(settings.SECRET_KEY)


def runtime_model_config_key() -> str:
    """模型配置加密材料，未单独配置时回退 SECRET_KEY。"""
    value = (os.getenv("MODEL_CONFIG_ENCRYPTION_KEY") or "").strip()
    # 降级路径：未单独配置模型加密密钥时回退 SECRET_KEY（旧项目同款规则），保证历史密文可继续解密。
    return value or runtime_secret_key()


def zap_api_key() -> str:
    """返回 ZAP 管理 API 的 API Key 明文；未配置或解密失败返回空串。

    明文只在进程内传递（传给 ZAPTransport 一次性使用），不写日志、不进事件表、
    不进 API 响应（§三「API Key 加密保存」、§三十四 第 8 条）。
    函数内 import 是刻意的：crypto 反向依赖本模块的 runtime_model_config_key，
    模块级 import 会形成循环。
    """
    from app.shared.crypto import decrypt_secret

    return decrypt_secret(settings.ZAP_API_KEY_ENCRYPTED)
