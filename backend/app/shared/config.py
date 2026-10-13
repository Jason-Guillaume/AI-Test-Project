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

    # 图形验证码：签发频率与图片参数。
    # AUTH_CAPTCHA_IP_LIMIT_PER_MINUTE 是每个 IP 每分钟的签发次数上限，
    # 独立于注册桶计数，用于阻止自动化脚本刷图。
    AUTH_CAPTCHA_IP_LIMIT_PER_MINUTE: int = 30
    CAPTCHA_TTL_SECONDS: int = 300
    CAPTCHA_LENGTH: int = 5
    CAPTCHA_IMAGE_WIDTH: int = 120
    CAPTCHA_IMAGE_HEIGHT: int = 40

    # 初始化管理员凭据，只被 scripts/seed_admin.py 读取，运行期无作用。
    INIT_ADMIN_USERNAME: str | None = None
    INIT_ADMIN_PASSWORD: str | None = None

    # 默认关闭：表结构只通过 Alembic 变更，应用启动不自动改正式表结构。
    AUTO_CREATE_SCHEMA: bool = False

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
