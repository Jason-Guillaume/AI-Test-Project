"""ZAP 集成侧的平台内部契约（数据模型 + 枚举）。

设计要点：
- 本模块只放**平台自己的**数据结构，业务层一律依赖这里的数据类，不接触 ZAP 原始 JSON。
  Connector 负责把 ZAP 响应转换过来（§六「ZAP 的响应必须转换成平台内部 Schema」）。
- 全部枚举都是字符串常量而不是 Enum，与仓库其它 feature 的口径一致
  （security_testing.schemas / agent.schemas 都是 frozenset + Literal 写法）。
- 数据类用 dataclass 而不是 Pydantic：这些结构只在进程内流转（Worker → 归一化 →
  落库），不需要序列化校验开销，也不该被路由层直接引用。

不在此处定义的内容：
- ZAP API Key、Token 等凭据——只以明文参数在进程内传递，从不入库（§十一）。
- Finding / TestRun / Report 的字段——复用现有模型，禁止重建第二套。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

# --------------------------------------------------------------------------- 扫描目标类型

#: 扫描目标形态。API = 只喂 OpenAPI；WEB = 只爬页面；HYBRID = 两者都做。
TARGET_TYPE_API = "API"
TARGET_TYPE_WEB = "WEB"
TARGET_TYPE_HYBRID = "HYBRID"
TARGET_TYPES = frozenset({TARGET_TYPE_API, TARGET_TYPE_WEB, TARGET_TYPE_HYBRID})

# --------------------------------------------------------------------------- 扫描模式

#: 六档扫描模式（需求 §五）。默认只能选 PASSIVE 系列。
SCAN_MODE_API_PASSIVE = "API_PASSIVE"
SCAN_MODE_WEB_PASSIVE = "WEB_PASSIVE"
SCAN_MODE_HYBRID_PASSIVE = "HYBRID_PASSIVE"
SCAN_MODE_API_ACTIVE = "API_ACTIVE"
SCAN_MODE_WEB_ACTIVE = "WEB_ACTIVE"
SCAN_MODE_FULL_AUTHORIZED = "FULL_AUTHORIZED"
SCAN_MODES = frozenset(
    {
        SCAN_MODE_API_PASSIVE,
        SCAN_MODE_WEB_PASSIVE,
        SCAN_MODE_HYBRID_PASSIVE,
        SCAN_MODE_API_ACTIVE,
        SCAN_MODE_WEB_ACTIVE,
        SCAN_MODE_FULL_AUTHORIZED,
    }
)

#: 模式 → 是否属于「受控主动扫描」。只按模式名判定，不让前端字符串绕过去。
ACTIVE_SCAN_MODES = frozenset(
    {SCAN_MODE_API_ACTIVE, SCAN_MODE_WEB_ACTIVE, SCAN_MODE_FULL_AUTHORIZED}
)

#: 模式 → 是否爬 Web 页面（含 XHR/Fetch 采集）。
WEB_CRAWL_MODES = frozenset(
    {SCAN_MODE_WEB_PASSIVE, SCAN_MODE_HYBRID_PASSIVE, SCAN_MODE_WEB_ACTIVE,
     SCAN_MODE_FULL_AUTHORIZED}
)

#: 模式 → 是否导入 OpenAPI 做 API 面扫描。
API_SCAN_MODES = frozenset(
    {SCAN_MODE_API_PASSIVE, SCAN_MODE_HYBRID_PASSIVE, SCAN_MODE_API_ACTIVE,
     SCAN_MODE_FULL_AUTHORIZED}
)


def is_active_scan(scan_mode: str) -> bool:
    """判定是否为受控主动扫描；未登记的模式按被动处理（保守）。"""
    return scan_mode in ACTIVE_SCAN_MODES


# --------------------------------------------------------------------------- 认证模式

#: 认证方式（需求 §十一/§十二/§十三）。
AUTH_MODE_NONE = "NONE"
AUTH_MODE_BEARER_TOKEN = "BEARER_TOKEN"
AUTH_MODE_HEADER_BASED = "HEADER_BASED"
AUTH_MODE_BROWSER_AUTH = "BROWSER_AUTH"
AUTH_MODE_MANUAL = "MANUAL"
AUTH_MODES = frozenset(
    {
        AUTH_MODE_NONE,
        AUTH_MODE_BEARER_TOKEN,
        AUTH_MODE_HEADER_BASED,
        AUTH_MODE_BROWSER_AUTH,
        AUTH_MODE_MANUAL,
    }
)

#: 需要「浏览器里真实存在登录态」才能扫出登录页的模式。
#: 只配 Authorization 头不等于 React 页面已登录（§十二），这两档必须单独验证。
BROWSER_AUTH_MODES = frozenset({AUTH_MODE_BROWSER_AUTH, AUTH_MODE_MANUAL})

#: 登录态验证的三种结果。只有 LOGGED_IN 允许继续爬业务页面。
AUTH_STATUS_LOGGED_IN = "LOGGED_IN"
AUTH_STATUS_LOGGED_OUT = "LOGGED_OUT"
AUTH_STATUS_UNVERIFIABLE = "UNVERIFIABLE"
AUTH_STATUSES = frozenset(
    {AUTH_STATUS_LOGGED_IN, AUTH_STATUS_LOGGED_OUT, AUTH_STATUS_UNVERIFIABLE}
)

# --------------------------------------------------------------------------- 任务状态机

#: SecurityScanJob 状态（需求 §七）。
JOB_STATUS_PENDING = "PENDING"
JOB_STATUS_PREPARING = "PREPARING"
JOB_STATUS_AUTHENTICATING = "AUTHENTICATING"
JOB_STATUS_CRAWLING = "CRAWLING"
JOB_STATUS_PASSIVE_SCANNING = "PASSIVE_SCANNING"
JOB_STATUS_ACTIVE_SCANNING = "ACTIVE_SCANNING"
JOB_STATUS_IMPORTING_RESULTS = "IMPORTING_RESULTS"
JOB_STATUS_COMPLETED = "COMPLETED"
JOB_STATUS_FAILED = "FAILED"
JOB_STATUS_CANCELLED = "CANCELLED"
JOB_STATUS_TIMED_OUT = "TIMED_OUT"
JOB_STATUSES = frozenset(
    {
        JOB_STATUS_PENDING,
        JOB_STATUS_PREPARING,
        JOB_STATUS_AUTHENTICATING,
        JOB_STATUS_CRAWLING,
        JOB_STATUS_PASSIVE_SCANNING,
        JOB_STATUS_ACTIVE_SCANNING,
        JOB_STATUS_IMPORTING_RESULTS,
        JOB_STATUS_COMPLETED,
        JOB_STATUS_FAILED,
        JOB_STATUS_CANCELLED,
        JOB_STATUS_TIMED_OUT,
    }
)

#: 终态：进入后不再推进，也不再被 Worker 领取。
JOB_TERMINAL_STATUSES = frozenset(
    {JOB_STATUS_COMPLETED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED, JOB_STATUS_TIMED_OUT}
)

#: 已在 ZAP 上跑起来的中间态：进程重启时这些任务必须被判为中断（§八 任务恢复）。
#: 注意 PENDING 不在其中——待领取任务没有心跳，不能当作中断任务清扫。
JOB_INFLIGHT_STATUSES = frozenset(
    {
        JOB_STATUS_PREPARING,
        JOB_STATUS_AUTHENTICATING,
        JOB_STATUS_CRAWLING,
        JOB_STATUS_PASSIVE_SCANNING,
        JOB_STATUS_ACTIVE_SCANNING,
        JOB_STATUS_IMPORTING_RESULTS,
    }
)

#: 未结束的状态：PENDING 加上所有中间态。用于「同一目标不允许重复发起」的查重。
#: 不能只用 JOB_INFLIGHT_STATUSES——PENDING 的任务同样占着这个目标的扫描名额，
#: 否则管理员可以无限堆积同一目标的待执行任务。
JOB_NOT_DONE_STATUSES = JOB_STATUSES - JOB_TERMINAL_STATUSES

# --------------------------------------------------------------------------- 覆盖率口径

#: 覆盖统计阶段（需求 §三十一）。顺序即推进顺序。
COVERAGE_DISCOVERED = "DISCOVERED"
COVERAGE_REQUESTED = "REQUESTED"
COVERAGE_RESPONDED = "RESPONDED"
COVERAGE_PASSIVE_ANALYZED = "PASSIVE_ANALYZED"
COVERAGE_ACTIVE_SCANNED = "ACTIVE_SCANNED"
COVERAGE_NOT_COVERED = "NOT_COVERED"
COVERAGE_STAGES = frozenset(
    {
        COVERAGE_DISCOVERED,
        COVERAGE_REQUESTED,
        COVERAGE_RESPONDED,
        COVERAGE_PASSIVE_ANALYZED,
        COVERAGE_ACTIVE_SCANNED,
        COVERAGE_NOT_COVERED,
    }
)

#: 阶段排序：用于「已达到的最高阶段」比较。NOT_COVERED 排在最前。
COVERAGE_ORDER: dict[str, int] = {
    COVERAGE_NOT_COVERED: 0,
    COVERAGE_DISCOVERED: 1,
    COVERAGE_REQUESTED: 2,
    COVERAGE_RESPONDED: 3,
    COVERAGE_PASSIVE_ANALYZED: 4,
    COVERAGE_ACTIVE_SCANNED: 5,
}

# --------------------------------------------------------------------------- 严重级别映射

#: ZAP Risk → 平台 Severity 的**唯一**映射表（§十八）。
#: 只允许往下映射：ZAP 最高档 High → 平台 HIGH，平台 CRITICAL 只由 Phase 1 变异规则表产生，
#: 不由扫描器声明。Confidence 不参与此映射——它是独立维度，原样保留。
ZAP_RISK_TO_SEVERITY: dict[str, str] = {
    "Informational": "INFO",
    "Info": "INFO",
    "Low": "LOW",
    "Medium": "MEDIUM",
    "High": "HIGH",
}

#: 平台 Severity 合法取值，与 security_testing.schemas.SEVERITY_LEVELS 对齐。
SCAN_SEVERITY_LEVELS = frozenset({"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"})

#: ZAP Risk 原文保留在 evidence 里，映射失败时落 MEDIUM（与 Phase 1 默认值一致）。
DEFAULT_ZAP_ALERT_SEVERITY = "MEDIUM"

#: ZAP Confidence 是 1-5 的整数，直接透传，不做语义改写。
ZAP_CONFIDENCE_RANGE = (1, 5)


def map_zap_risk(risk: str | None) -> str:
    """ZAP Risk 文本 → 平台 Severity；未识别值落默认 MEDIUM。"""
    if not risk:
        return DEFAULT_ZAP_ALERT_SEVERITY
    return ZAP_RISK_TO_SEVERITY.get(risk.strip(), DEFAULT_ZAP_ALERT_SEVERITY)


# --------------------------------------------------------------------------- 扫描事件

#: SecurityScanEvent.event_type。事件流是「可审计的过程记录」，不是日志替代品。
EVENT_TYPE_STAGE = "STAGE"
EVENT_TYPE_PROGRESS = "PROGRESS"
EVENT_TYPE_REQUEST = "REQUEST"
EVENT_TYPE_ALERT = "ALERT"
EVENT_TYPE_AUTH = "AUTH"
EVENT_TYPE_WARNING = "WARNING"
EVENT_TYPE_ERROR = "ERROR"
SCAN_EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_STAGE,
        EVENT_TYPE_PROGRESS,
        EVENT_TYPE_REQUEST,
        EVENT_TYPE_ALERT,
        EVENT_TYPE_AUTH,
        EVENT_TYPE_WARNING,
        EVENT_TYPE_ERROR,
    }
)

# --------------------------------------------------------------------------- 凭据脱敏

#: 绝对不允许进日志 / 事件表 / prompt 的键名（§十一、§三十四 第 8 条）。
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "authorization",
        "bearer token",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "api_key",
        "apikey",
        "x-zap-api-key",
        "cookie",
        "set-cookie",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "session",
        "credential",
        "credentials",
        "webhook_url",
        "webhook_url_encrypted",
        "sign",
        "timestamp",
    }
)

#: 脱敏后统一替换成的占位符，保证不同场景输出一致、便于搜索断言。
REDACTED_PLACEHOLDER = "******"

#: 证据字段最大长度：超过就截断，避免单次扫描把整张表撑爆。
MAX_EVIDENCE_TEXT_LENGTH = 2000

#: 请求头回显里的凭据形态（编译一次，redact_text 反复用）。
_RE_BEARER_HEADER = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+",
)
_RE_BEARER_BARE = re.compile(r"(?i)(bearer\s+)\S+")
_RE_COOKIE_HEADER = re.compile(r"(?i)(cookie\s*[:=]\s*)[^\r\n]+")
MAX_EVIDENCE_ITEMS = 200  # 单个列表型证据最多保留的条目数


#: 键名归一化时剥掉的一切字符：连字符、下划线、空格、点、斜杠……
_NON_NAME_CHAR = re.compile(r"[^a-z0-9]")


def _canonical_key(name: Any) -> str:
    """把键名规范成「小写、只剩字母数字」的形式用于比较。

    两侧必须用**同一套**口径：前端表单、ZAP 请求头回显、配置文件里同一个凭据键
    的写法各不相同（`x-zap-api-key` / `x_zap_api_key` / `xZapApiKey`、
    `Set-Cookie` / `set_cookie`、`Client Secret` / `client_secret`）。这里剥掉所有
    分隔符再比较，只要有一个变体没命中，那一条通道就等于没脱敏
    （§三十四 第 8 条：不允许在日志中保存 JWT 和凭据）。

    取舍：这个口径会连带把「空格写法」也并入（`accesstoken` 与 `access_token` 同形），
    属于**过度脱敏**——只影响非敏感字段的可读性，不会造成凭据外泄，
    比漏脱敏划算。
    """
    return _NON_NAME_CHAR.sub("", str(name).lower())


#: 由 SENSITIVE_FIELD_NAMES 派生的规范化集合：键名匹配只查这里（O(1) 且口径唯一）。
SENSITIVE_KEY_CANONICAL = frozenset(_canonical_key(name) for name in SENSITIVE_FIELD_NAMES)


def _redact_key(key: Any) -> bool:
    """判断一个键名是否属于敏感字段（大小写与分隔符均不敏感，口径见 `_canonical_key`）。"""
    if key is None:
        return False
    return _canonical_key(key) in SENSITIVE_KEY_CANONICAL


def redact_value(key: Any, value: Any) -> Any:
    """按键名脱敏单个值。

    键名命中敏感集合时整值替换为占位符；否则原样返回。
    注意：**只认键名不认值**——JWT 长字符串无法可靠识别，凭据一律靠配置端标记。
    """
    if _redact_key(key):
        return REDACTED_PLACEHOLDER
    return value


def redact_mapping(data: dict[str, Any] | None) -> dict[str, Any]:
    """递归脱敏一个 dict：字符串值超过长度上限先截断，敏感键整值替换。"""
    if not data:
        return {}
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out[str(key)] = redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            items = [
                redact_mapping(item) if isinstance(item, dict)
                else redact_value(key, item)
                for item in list(value)[:MAX_EVIDENCE_ITEMS]
            ]
            out[str(key)] = items
        else:
            redacted = redact_value(key, value)
            if isinstance(redacted, str) and len(redacted) > MAX_EVIDENCE_TEXT_LENGTH:
                redacted = redacted[:MAX_EVIDENCE_TEXT_LENGTH] + "…（已截断）"
            out[str(key)] = redacted
    return out


def redact_text(text: str | None, *, replace: str = REDACTED_PLACEHOLDER) -> str:
    """把文本里的 ``Bearer <token>`` / ``Authorization: *** 片段替换掉。

    只做两段常见形态的替换，不做通用正则猜测——扫描器 evidence 里的凭据绝大多数
    出现在请求头回显中，这两段覆盖了主要形态；其余靠调用方只存结构化字段。
    """
    if not text:
        return ""
    result = text
    # 脱敏前后示例："Authorization: Bearer eyJ..." → "Authorization: Bearer ******"
    result = _RE_BEARER_HEADER.sub(r"\1" + replace, result)
    # "Bearer eyJ..." 单独出现
    result = _RE_BEARER_BARE.sub(r"\1" + replace, result)
    # Cookie 头整行
    result = _RE_COOKIE_HEADER.sub(r"\1" + replace, result)
    return result


#: URL 查询串里按「凭据」处理的键名。刻意比 SENSITIVE_FIELD_NAMES 窄：
#: 只有真会承载凭证的参数才抹值，`timestamp` / `sign` 之类在 URL 里通常是业务参数，
#: 抹掉会让同一问题聚不成同一行（指纹依赖参数名）。
URL_CREDENTIAL_KEYS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "jwt",
        "api_key",
        "apikey",
        "session",
        "sid",
        "cookie",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "credential",
        "credentials",
    }
)

#: 与 URL_CREDENTIAL_KEYS 同源的规范化集合：判定用同一套口径，避免
#: `?client-secret=` 与 `?client_secret=` 被区别对待（同一条凭据两种拼写）。
URL_CREDENTIAL_KEY_CANONICAL = frozenset(_canonical_key(name) for name in URL_CREDENTIAL_KEYS)


def redact_url(url: str | None) -> str:
    """把 URL 查询串里的凭据参数值抹掉，保留键名与其余参数。

    ZAP 会把爬到的完整 URL（含 query）回显在告警里，覆盖率清单也用 URL 做主键；
    不脱敏的话 JWT 会直接进覆盖率表和告警快照（§二十一、§三十四 第 8 条）。
    键名保留是为了让「同一个参数位」仍能聚成同一行。
    """
    if not url:
        return ""
    parts = urlsplit(str(url))
    if not parts.query:
        return str(url)
    pairs = [
        (key, REDACTED_PLACEHOLDER if _canonical_key(key) in URL_CREDENTIAL_KEY_CANONICAL else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    # 用 quote 手工编码：urlencoding 默认会把掩码里的 * 转成 %2A，
    # 掩码要肉眼可辨，所以只把 * 额外列为安全字符。
    query = "&".join(
        f"{quote(key, safe='')}={quote(str(value), safe='*')}" for key, value in pairs
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


# --------------------------------------------------------------------------- 连接器结果结构


@dataclass(slots=True)
class ZAPAbout:
    """ZAP 实例的版本与插件清单（来自 /JSON/core/about）。"""

    version: str
    add_on_names: list[str] = field(default_factory=list)
    add_on_versions: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ZAPCapability:
    """单个能力探测结果。

    supported=False 时 capability_name 仍要写清楚，前端据此显示「受限」而不是假装成功。
    """

    name: str
    supported: bool
    detail: str = ""


@dataclass(slots=True)
class ZAPCapabilities:
    """一次能力探测的全部结果（§三 第 7 条：版本、插件能力检测）。"""

    version: str
    about: ZAPAbout
    capabilities: list[ZAPCapability]

    def as_dict(self) -> dict[str, Any]:
        """转成可入库 / 可返回前端的普通 dict。"""
        return {
            "version": self.version,
            "addon_names": self.about.add_on_names,
            "addon_versions": dict(self.about.add_on_versions),
            "capabilities": [
                {"name": cap.name, "supported": cap.supported, "detail": cap.detail}
                for cap in self.capabilities
            ],
        }

    def has(self, name: str) -> bool:
        """按名称判断能力是否可用。"""
        return any(cap.name == name and cap.supported for cap in self.capabilities)


@dataclass(slots=True)
class ZAPScanContext:
    """一次扫描在 ZAP 侧的上下文句柄。

    不包含任何凭据明文——认证参数只在 configure_authentication 时传一次。
    """

    host_pattern: str
    context_name: str | None = None


@dataclass(slots=True)
class ZAPAuthResult:
    """登录态验证结果。

    authenticated=False 时 Worker 必须停扫，不能把登录页当成已覆盖的业务页面（§十一）。
    verified=True 但 authenticated=False 属于「明确未登录」；
    verified=False 属于「无法判定」，前端必须显示限制而不是成功。
    """

    authenticated: bool
    verified: bool
    auth_mode: str
    status: str
    detail: str = ""


@dataclass(slots=True)
class ZAPPagesStats:
    """爬取阶段的页面与请求计数（不含精确总体百分比）。"""

    pages: int = 0
    requests: int = 0
    urls: int = 0


@dataclass(slots=True)
class ZAPProgress:
    """某一步的进度。

    percentage 为 None 表示 ZAP 没给百分比——此时**不能**虚构精确进度，
    前端只能显示阶段 + 计数（§十七）。
    """

    running: bool
    percentage: int | None = None
    stage: str = ""
    pages: int = 0
    requests: int = 0
    alerts: int = 0
    urls: int = 0


@dataclass(slots=True)
class ZAPAlert:
    """一条归一化前的 ZAP 告警（已从 ZAP JSON 取出必要字段）。

    evidence 已经是**脱敏后**的文本——ZAP 的 evidence 常回显请求头。
    """

    rule_id: str
    name: str
    risk: str
    confidence: int
    url: str
    method: str = ""
    parameter: str = ""
    description: str = ""
    remediation: str = ""
    evidence: str = ""
    cwe_id: int | None = None
    wasc_id: int | None = None
    reference: str = ""


@dataclass(slots=True)
class ZAPAlertCounts:
    """按严重级别汇总的告警数。"""

    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    def as_dict(self) -> dict[str, int]:
        """转成 dict。"""
        return {
            "total": self.total,
            "high": self.high,
            "medium": self.medium,
            "low": self.low,
            "info": self.info,
        }


@dataclass(slots=True)
class ScanCoverageRow:
    """一个扫描对象（URL 或 API）的覆盖阶段。"""

    identifier: str
    stage: str
    method: str = ""
    status_code: int | None = None
    passive_analyzed: bool = False
    active_scanned: bool = False

    def as_dict(self) -> dict[str, Any]:
        """转成 dict。"""
        return {
            "identifier": self.identifier,
            "stage": self.stage,
            "method": self.method,
            "status_code": self.status_code,
            "passive_analyzed": self.passive_analyzed,
            "active_scanned": self.active_scanned,
        }
