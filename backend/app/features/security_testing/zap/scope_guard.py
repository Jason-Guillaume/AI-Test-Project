"""扫描目标合法性与 SSRF 守卫。

这一层只做一件事：在**任何一次发往 ZAP 的请求之前**判断目标是否允许扫描。
前端确认、Profile 里的 include/exclude 都只是体验，范围限制必须落在后端
（§三十四 第 1 条「在所有扫描请求发出前实施范围限制」）。

必须覆盖的绕过路径（§四）：
- DNS 解析变化：解析出的是保留地址（回环 / 私网 / 链路本地 / 云元数据 169.254.169.254）
  就拒绝，不只看主机名拼写；
- 重定向：跳转目标要重新走同一套校验，不能凭原始 URL 通过；
- 代理出口：传输层用 ``trust_env=False``，不走系统代理，避免经代理绕到内网。

解析结果只做**拒绝判断**，不把 IP 写进任何记录——保留地址主机名本来就能被
解析到保留地址，拒绝即可，不需要把解析结果留档。
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from ipaddress import ip_address
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from app.core.http.errors import (
    CODE_SECURITY_SCAN_SCOPE_VIOLATION,
    CODE_SECURITY_SCAN_PRODUCTION_FORBIDDEN,
    AppError,
)

logger = logging.getLogger(__name__)

#: 允许的 URL 协议。
#:
#: 注意：本阶段**只放行解析到公网地址的目标**（见 is_reachable_public_ip），
#: 内网测试环境（10.x / 192.168.x / 172.16-31.x 等私网段）目前一律拒绝。
#: 这是有意的保守口径——防止扫描器把请求走私进内网（SSRF / 横向移动）。
#: 代价是「授权的内网测试环境」这个场景一期覆盖不到，需要单独的
#: 「授权私网段白名单」设计；**不要**为了覆盖内网而放宽 is_reachable_public_ip。
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: 常见生产环境命名（§五：Production 第一阶段禁止主动扫描）。
#: 环境表里没有 mode 字段，只能按 name/display_name 判断——判断口径必须偏保守。
#: 保留导出是为了向后兼容（历史代码与文档引用过这个集合）。
PRODUCTION_NAME_TOKENS = frozenset(
    {"prod", "production", "prd", "online", "live", "生产", "线上", "正式"}
)

#: 环境名里的分隔符：连字符、下划线、点、斜杠、空白等。
#: 必须按分隔符切开逐段判断——中文环境名（「生产环境」「线上环境」）本身没有分隔符，
#: 整串比较会把它漏判掉，导致 §三十四「Production 禁止主动扫描」整段失效。
_NAME_SEPARATORS = re.compile(r"[\s\-_./\\、,，&|]+")

#: 英文生产环境标识：按词元精确匹配，或作为词元前缀（prod01 / production1）。
_ENGLISH_PRODUCTION_PREFIXES = ("prod", "online", "live")

#: 中文生产环境标识：只能按子串匹配（生产环境 / 线上环境 / 正式环境）。
_CHINESE_PRODUCTION_TOKENS = ("生产", "线上", "正式")

#: 主动扫描默认排除候选（§十五）。
#: 重要：这只是**候选**，不能仅凭路径字符串认定安全——路径匹配不到但语义危险
#: （如 POST /orders 的批量修改）不会被排除，需要 Profile 里显式配 exclude_paths。
HIGH_RISK_ACTIVE_PATH_PATTERNS: tuple[str, ...] = (
    "logout",
    "logoff",
    "delete",
    "remove",
    "destroy",
    "payment",
    "pay",
    "transfer",
    "withdraw",
    "refund",
    "production",
    "admin/dangerous",
)

#: 主动扫描不允许的方法候选（破坏性默认不发，§九）。
DESTRUCTIVE_METHODS = frozenset({"DELETE", "PATCH", "PUT", "OPTIONS", "TRACE", "CONNECT"})

#: 可注入的解析函数：(host) -> list[ip_address]。测试用它固定解析结果，
#: 避免单测依赖真实 DNS（也可能被本地 DNS 重定向污染）。
Resolver = Callable[[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]


def scope_violation(message: str) -> AppError:
    """范围违规的统一异常工厂。"""
    return AppError(message, status_code=403, code=CODE_SECURITY_SCAN_SCOPE_VIOLATION)


def is_production_environment(*names: str | None) -> bool:
    """按环境名判断是否属于生产环境（偏保守：命中即视为生产）。

    口径故意偏保守：宁可把 staging-prod 当成生产而拒绝一次扫描，也不能漏判
    生产环境后放行主动扫描（§三十四 第 2 条）。中文环境名没有分隔符，
    只能按子串判断，否则「生产环境」这类最常见的写法会被整段漏掉。
    """
    for name in names:
        for token in _NAME_SEPARATORS.split((name or "").strip().lower()):
            if not token:
                continue
            if token in PRODUCTION_NAME_TOKENS:
                return True
            # "prod01" / "production1" 这类把序号贴在后面的写法也按生产处理。
            if token.startswith(_ENGLISH_PRODUCTION_PREFIXES):
                return True
            # 「生产环境」「线上环境」「正式环境」：标识词只是环境名的一部分。
            if any(piece in token for piece in _CHINESE_PRODUCTION_TOKENS):
                return True
    return False


def _public_ipv4_networks() -> list[ipaddress.IPv4Network]:
    """云厂商元数据服务地址；169.254.169.254 本身就是链路本地，这里单独列出便于说明。"""
    return [ipaddress.IPv4Network("169.254.169.254/32")]


def is_reachable_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断 IP 是否是允许扫描的地址。

    保守原则：**只放行明确的公网地址**。回环、私网、链路本地、保留、组播、
    未指定、云元数据全部拒绝（§四「避免 SSRF」）。
    """
    if ip.version == 4:
        for network in _public_ipv4_networks():
            if ip in network:
                return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    # 0.0.0.0/8 之类的「本地」前缀在不同库里归类不一致，单独再挡一道。
    if ip.version == 4 and (int(ip) >> 24) == 0:
        return False
    return True


def resolve_host_ips(host: str, resolver: Resolver | None = None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """解析主机名；resolver 可注入以便测试固定结果。

    解析失败不静默通过——解析不出来通常是主机名拼错或域名被撤销，
    直接拒绝比「解析不到就放行」安全（§四）。
    """
    if resolver is None:
        resolver = _system_resolver
    try:
        raw = resolver(host)
    except Exception as exc:  # noqa: BLE001 - 解析失败必须转成范围拒绝，不能放行
        logger.warning("扫描目标解析失败，按范围拒绝处理：%s（%s）", host, exc)
        raise scope_violation(f"扫描目标无法解析：{host}") from exc
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in raw:
        try:
            if isinstance(item, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
                # 默认解析器直接产出 ip 对象：不能对它取下标，否则域名目标一律 TypeError → 500。
                ips.append(item)
            elif isinstance(item, str):
                ips.append(ip_address(item))
            elif item and not isinstance(item, str):
                # 原始 getaddrinfo 元组形态：取第一项。
                ips.append(ip_address(str(item[0])))
            else:
                ips.append(ip_address(str(item)))
        except (ValueError, TypeError):
            continue
    if not ips:
        raise scope_violation(f"扫描目标无法解析：{host}")
    return ips


def _system_resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """默认解析器：标准库 getaddrinfo，不做代理。"""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [ip_address(item[4][0]) for item in infos]


def validate_target_url(
    base_url: str,
    *,
    allowed_hosts: Iterable[str] = (),
    resolver: Resolver | None = None,
) -> str:
    """校验并规范化一个扫描根 URL，返回去掉尾部斜杠的规范形式。

    校验项：协议、必须含 host、端口合法、host 必须在 allowed_hosts 白名单里（非空时）、
    不允许 URL 里带用户名密码、主机名不允许是保留地址的字面量。
    """
    text = (base_url or "").strip()
    if not text:
        raise scope_violation("扫描目标地址为空")
    try:
        parts = urlsplit(text)
        # hostname / port / username 三个属性在畸形输入下会抛 ValueError
        # （未加方括号的 IPv6、端口越界），必须在 try 里取值，否则 403 变 500。
        host = parts.hostname or ""
        port = parts.port
        has_credential = bool(parts.username or parts.password)
    except ValueError as exc:
        raise scope_violation("扫描目标地址格式不合法") from exc
    if parts.scheme not in ALLOWED_SCHEMES:
        raise scope_violation(f"不支持的协议：{parts.scheme or '（缺失）'}，只允许 http / https")
    if not host:
        raise scope_violation("扫描目标缺少主机名")
    if has_credential:
        raise scope_violation("扫描目标地址不允许包含用户名或密码")
    # port 为 None 表示「未写端口」，这是合法情况；
    # 直接比较 1 <= None 会抛 TypeError，让所有无端口目标变成 500 而不是正常放行。
    if port is not None and not (1 <= port <= 65535):
        raise scope_violation(f"扫描目标端口不合法：{port if port is not None else '（缺失）'}")

    hosts = _normalize_host_set(allowed_hosts)
    if hosts and host.lower() not in hosts:
        raise scope_violation(f"扫描目标 {host} 不在允许的主机范围内")
    if hosts and port is not None:
        # 白名单里的 host:port 必须完整匹配；否则管理员只想放 8443，
        # 结果同一主机的 ssh / redis 端口也被拿去扫。
        if f"{host.lower()}:{port}" not in _normalize_host_port_set(allowed_hosts):
            raise scope_violation(
                f"扫描目标端口 {port} 不在允许范围内，"
                f"请在白名单中写成 {host}:{port}"
            )

    if _is_ip_literal(host):
        try:
            ip = ip_address(host)
        except ValueError:
            raise scope_violation(f"扫描目标主机名不合法：{host}") from None
        if not is_reachable_public_ip(ip):
            raise scope_violation(f"扫描目标是保留地址，禁止扫描：{host}")
    else:
        for ip in resolve_host_ips(host, resolver=resolver):
            if not is_reachable_public_ip(ip):
                raise scope_violation(f"扫描目标解析到保留地址，禁止扫描：{host}")

    path = parts.path.rstrip("/") or ""
    # 端口必须原样带回：parts.hostname 不含端口，直接拼 host 会让 8443 的目标
    # 落库成 443/80，扫描会打到另一个服务并且全程不报错（§四 范围限制）。
    netloc = f"[{host}]" if host.count(":") > 0 else host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, path, parts.query, parts.fragment))


def _is_ip_literal(host: str) -> bool:
    """判断主机名本身是不是 IP 字面量或数字形态写法（IPv6 的方括号已被 urlsplit 去掉）。

    不能只靠 ``ipaddress`` 能不能解析：``0177.0.0.1``（八进制 127.0.0.1）、
    ``0x7f000001``、``2130706433``、``127.1`` 这些写法 ipaddress 不认识，但系统解析器
    会按数字形态解析——而且**不同平台结果不同**：macOS 的 getaddrinfo 把
    ``0177.0.0.1`` 解成 ``177.0.0.1``（公网地址），Linux 解成 ``127.0.0.1``。
    放行的话，扫描实际打到哪个地址完全取决于目标机器装了什么解析器，
    必须直接拒绝（§四「避免 SSRF」）。
    """
    try:
        ip_address(host)
        return True
    except ValueError:
        return _looks_numeric_ip(host)


def _host_port_or_raise(raw: Any) -> tuple[str, int | None]:
    """解析白名单条目为 (主机名, 端口)；条目非空但解析不出主机名时报范围违规。

    空条目（None / 空串）按未填写处理——管理员留空一格是常见情况，不该因为
    一个空格就把整条白名单判违规。真正的风险是「非空但拆不出主机名」，
    那意味着白名单条目被静默丢弃，可能把声明过的扫描范围变成空限制。
    """
    if raw is None:
        return "", None
    text = str(raw).strip()
    if not text:
        return "", None
    host, port = _split_host_port(text)
    if not host:
        raise scope_violation(f"允许主机条目无法解析出主机名：{text}")
    return host, port


def _host_or_raise(raw: Any) -> str:
    """校验目标主机是否位于允许范围内，不符合时抛出错误。"""
    host, _port = _host_port_or_raise(raw)
    return host


#: 一个不含字母的 IP 段：纯数字（可带八进制前导零），或 0x 十六进制。
_NUMERIC_IP_SEGMENT = re.compile(r"^(0x[0-9a-f]+|[0-9]+)$")


def _looks_numeric_ip(host: str) -> bool:
    """判断主机名是不是「看起来像 IP 的非法写法」。

    口径：**每一个**点分段都能被当成数字段解释（纯数字，或 0x 十六进制）。

    不能用「整串不含 g-z 之间的字母」来预判——十六进制前缀 0x 里的字面 ``x``
    正好落在 g-z 区间，``0x7f000001`` / ``127.0x1`` 这类写法会被误当成普通域名
    交给系统解析器，而解析器会按数字形态解析它们（不同平台结果不同）。
    反过来也不会误伤真正的域名：域名至少有一个段带字母（``api.example.com``、
    ``www.a.co``），那个段匹配不上数字段正则。
    """
    text = (host or "").strip().lower().rstrip(".")
    if not text:
        return False
    return all(_NUMERIC_IP_SEGMENT.match(part) for part in text.split("."))


def _split_host_port(raw: str) -> tuple[str, int | None]:
    """把白名单条目拆成 (纯主机名, 端口)，兼容 scheme / 凭据 / IPv6 方括号写法。"""
    text = str(raw or "").strip().lower()
    if not text:
        return "", None
    # 带 scheme 的按 URL 解析，不带 scheme 的不能交给 urlsplit（会被当 path）。
    if "://" in text:
        text = urlsplit(text).netloc
    else:
        text = text.split("/", 1)[0]
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if not text:
        return "", None
    # IPv6 形如 [::1]:80，主机名包含冒号，必须先剥离方括号再拆端口。
    if text.startswith("["):
        # [::1]:80 → 主机名 ::1，剩余部分是 ":80"，需要再剥一个冒号。
        inner, sep, rest = text.partition("]")
        host = inner[1:]
        rest = rest[1:] if sep and rest.startswith(":") else ""
    else:
        # partition 之后 rest 已经是纯端口（"8443"），不能再切片——
        # 多切一次会把 8443 变成 443，端口白名单从此永远匹配不上。
        host, _sep, rest = text.partition(":")
    port: int | None = None
    if rest:
        try:
            port = int(rest)
        except ValueError:
            return host, None
    return host, port


def _normalize_host_set(hosts: Iterable[str]) -> frozenset[str]:
    """把用户填的主机名清单规范化成纯主机名集合（忽略端口，小写、无 scheme 与凭据）。

    非空条目必须能解析出主机名，解析不出就报范围违规。静默丢弃是最危险的做法：
    ``allowed_hosts=["::1"]``（未加方括号的 IPv6）会被拆成空主机名，白名单随之变成
    空集，而空集在 validate_target_url 里等于「不做任何主机限制」——管理员声明的
    扫描范围从这一刻起完全失效。空列表仍表示「未配置限制」，这是有意区分开的。
    """
    out: set[str] = set()
    for raw in hosts or []:
        host = _host_or_raise(raw)
        if host:
            out.add(host)
    return frozenset(out)


def _normalize_host_port_set(hosts: Iterable[str]) -> frozenset[str]:
    """把白名单条目规范化成「主机[:端口]」集合。

    未写端口的条目只放行默认端口——白名单如果只保留主机名，
    ``allowed_hosts=["api.example.com"]`` 就会放行该主机上的**所有**端口。
    解析不出主机名的条目同样直接报错，不能静默丢掉。
    """
    out: set[str] = set()
    for raw in hosts or []:
        host, port = _host_port_or_raise(raw)
        if not host:
            continue
        out.add(f"{host}:{port}" if port is not None else host)
    return frozenset(out)


def validate_allowed_hosts(allowed_hosts: Iterable[str], resolver: Resolver | None = None) -> frozenset[str]:
    """校验 allowed_hosts 本身：每个主机名都必须能解析到公网地址。"""
    hosts = _normalize_host_set(allowed_hosts)
    for host in sorted(hosts):
        if _is_ip_literal(host):
            try:
                ip = ip_address(host)
            except ValueError:
                raise scope_violation(f"允许主机不合法：{host}") from None
            if not is_reachable_public_ip(ip):
                raise scope_violation(f"允许主机是保留地址：{host}")
        else:
            for ip in resolve_host_ips(host, resolver=resolver):
                if not is_reachable_public_ip(ip):
                    raise scope_violation(f"允许主机解析到保留地址：{host}")
    return hosts


def assert_redirect_allowed(
    location: str,
    *,
    base_url: str,
    allowed_hosts: Iterable[str] = (),
    resolver: Resolver | None = None,
) -> None:
    """重定向目标重新走一遍范围校验（§四「重定向」）。

    未配置 allowed_hosts 时收紧到「与扫描根同主机」，避免跳转把范围悄悄扩大。
    """
    if not location:
        return
    validate_target_url(location, allowed_hosts=allowed_hosts, resolver=resolver)
    base = urlsplit(base_url)
    target = urlsplit(location)
    if not allowed_hosts and base.hostname and target.hostname \
            and target.hostname.lower() != base.hostname.lower():
        raise scope_violation(f"跳转目标 {target.hostname} 离开了扫描根域名")


def compile_path_regex(paths: Iterable[str]) -> str | None:
    """把路径清单编译成 ZAP 的 setTargetExcludeFromScanRegex 用正则。

    全部转义——路径里出现 ``.`` ``+`` ``?`` 都不当作通配（正则注入是常见的
    范围逃逸点）。返回 None 表示没有需要排除的路径。
    """
    parts: list[str] = []
    for raw in paths or []:
        text = str(raw or "").strip()
        if not text:
            continue
        parts.append(re.escape(text.lstrip("/")))
    if not parts:
        return None
    return "(?i)(^|/)" + "|".join(parts) + r"(/|$)"


def default_active_exclude_regex() -> str:
    """主动扫描的默认排除正则（§十五 危险路径候选）。"""
    return "(?i)(^|/)" + "|".join(re.escape(p) for p in HIGH_RISK_ACTIVE_PATH_PATTERNS) + r"(/|$)"


def assert_active_scan_authorized(
    *,
    environment_name: str | None,
    scan_mode: str,
    active_authorized: bool,
    environment_active_allowed: bool,
) -> None:
    """主动扫描的授权闸门（§五、§十五、§三十四 第 2 条）。

    - Production 任何阶段禁止主动扫描；
    - Staging 等环境默认禁用主动扫描，必须由授权配置显式打开；
    - 未显式授权（active_authorized=False）一律拒绝。
    """
    from app.features.security_testing.zap.contracts import is_active_scan

    if not is_active_scan(scan_mode):
        return
    if is_production_environment(environment_name):
        raise AppError(
            "生产环境禁止主动扫描",
            status_code=403,
            code=CODE_SECURITY_SCAN_PRODUCTION_FORBIDDEN,
        )
    if not environment_active_allowed:
        raise scope_violation("当前环境未开放主动扫描")
    if not active_authorized:
        raise scope_violation("主动扫描需要显式授权")


# --------------------------------------------------------------------------- 授权标记

#: 目标级测试授权状态（§四）。只有 AUTHORIZED 才允许发起扫描。
AUTHORIZATION_STATUS_PENDING = "PENDING"
AUTHORIZATION_STATUS_AUTHORIZED = "AUTHORIZED"
AUTHORIZATION_STATUS_REVOKED = "REVOKED"
AUTHORIZATION_STATUSES = frozenset(
    {AUTHORIZATION_STATUS_PENDING, AUTHORIZATION_STATUS_AUTHORIZED, AUTHORIZATION_STATUS_REVOKED}
)

#: 默认拒绝的高风险主动扫描动作（§十五：支付/删除/批量修改需单独授权）。
#: Phase 2 直接拒绝，不实现「二次授权」流程。
BLOCKED_ACTIVE_ACTIONS = frozenset({"payment", "delete", "bulk_update", "transfer"})
