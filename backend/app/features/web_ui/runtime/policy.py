"""项目授权目标策略：冻结本次执行的白名单与 DNS 地址，覆盖页面、子资源和跳转。"""
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit
from app.models.project import ProjectOutboundTarget
from app.shared.errors import bad_request


class TargetPolicy:
    """执行开始时从项目白名单取快照；浏览器 DNS 固定，避免执行途中解析漂移。"""
    def __init__(self, db, project_id):
        """只读取已启用的精确 scheme/host/port；空白名单禁止执行。"""
        self.targets = {
            (r.scheme.lower(), r.host.lower(), r.port)
            for r in db.query(ProjectOutboundTarget).filter_by(project_id=project_id, enabled=True).all()
        }
        self.resolver_rules = []
        for host in sorted({t[1] for t in self.targets}):
            try:
                addresses = {i[4][0] for i in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
            except socket.gaierror as exc:
                raise bad_request("授权目标 DNS 解析失败") from exc
            safe = [a for a in addresses if not self._forbidden_address(a)]
            if not safe:
                raise bad_request("授权目标解析到禁止的链路本地或未指定地址")
            # 浏览器只访问冻结地址；不将 DNS 重绑定后的地址交给 Chromium。
            address = sorted(safe)[0]
            self.resolver_rules.append(f"MAP {host} {address}")

    @staticmethod
    def _forbidden_address(address):
        """元数据、组播和未指定地址即使误入白名单也不允许使用。"""
        ip = ipaddress.ip_address(address)
        return ip.is_link_local or ip.is_multicast or ip.is_unspecified

    def allows(self, url):
        """拒绝凭证 URL、非法端口与非 HTTP 协议，仅允许精确项目目标。"""
        try:
            parsed = urlsplit(url)
            return bool(
                parsed.scheme in ("http", "https") and parsed.hostname
                and not parsed.username and not parsed.password
                and (parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)) in self.targets
            )
        except (ValueError, AttributeError):
            return False

    def require(self, url):
        """未授权目标在任何网络 IO 前失败；异常不包含带凭据的完整 URL。"""
        if not self.allows(url):
            raise bad_request("页面或资源目标不在项目授权范围内")
        return url

    def route(self, route):
        """拦截全部请求，并在交给浏览器前检查重定向目标。"""
        if not self.allows(route.request.url):
            route.abort("blockedbyclient")
            return
        try:
            # 不让网络层自动跟随跳转，否则首次 URL 的授权会被重定向绕过。
            headers = dict(route.request.headers)
            source, target = urlsplit(getattr(self, "header_origin", "")), urlsplit(route.request.url)
            if (source.scheme, source.netloc) == (target.scheme, target.netloc):
                headers.update(getattr(self, "request_headers", {}))
            remaining = int((getattr(self, "deadline", time.monotonic() + 15) - time.monotonic()) * 1000)
            if remaining <= 0:
                route.abort("timedout")
                return
            response = route.fetch(max_redirects=0, timeout=min(15000, remaining), headers=headers)
            location = response.headers.get("location")
            if 300 <= response.status < 400 and location and not self.allows(urljoin(route.request.url, location)):
                route.abort("blockedbyclient")
            else:
                route.fulfill(response=response)
        except Exception:
            route.abort("failed")
