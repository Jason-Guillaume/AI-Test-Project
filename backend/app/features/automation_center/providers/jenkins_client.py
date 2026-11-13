"""Small Jenkins Remote API client with HTTPS and destination safeguards."""

from __future__ import annotations

import ipaddress
import base64
import re
import socket
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from app.features.automation_center.providers.base import ProviderError

_JOB_SEGMENT = re.compile(r"^[^/\\?#%\x00-\x1f]{1,120}$")
_QUEUE_ID = re.compile(r"/queue/item/(\d+)/?$")
_PARAMETER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
_SAFE_PORTS = {443, 8443, 9443}


class JenkinsClient:
    """Jenkins API Token client; redirects and ambient proxy settings are disabled."""

    def __init__(
        self,
        base_url: str,
        username: str,
        api_token: str,
        *,
        timeout_seconds: float = 15,
        allow_private_network: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = self.validate_base_url(base_url, allow_private_network=allow_private_network)
        if not username.strip() or not api_token:
            raise ProviderError("Jenkins 用户名或 API Token 未配置")
        self._username = username.strip()
        self._api_token = api_token
        self._allow_private_network = allow_private_network
        self._client = client or httpx.Client(
            auth=(self._username, api_token),
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5)),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json"},
        )
        self._owns_client = client is None

    @classmethod
    def validate_base_url(cls, value: str, *, allow_private_network: bool = False) -> str:
        """Reject non-HTTPS, credential-bearing, unsafe-port, and untrusted targets."""
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ProviderError("Jenkins 地址必须是 HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderError("Jenkins 地址不能包含账号、密码、查询参数或片段")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise ProviderError("Jenkins 地址端口无效") from exc
        if not 1 <= port <= 65535 or port not in _SAFE_PORTS:
            raise ProviderError("Jenkins 仅允许使用 HTTPS 端口 443、8443 或 9443")
        host = parsed.hostname.rstrip(".")
        try:
            addresses = {ipaddress.ip_address(host)}
        except ValueError:
            try:
                addresses = {
                    ipaddress.ip_address(item[4][0].split("%", 1)[0])
                    for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                }
            except (OSError, ValueError) as exc:
                raise ProviderError("无法解析 Jenkins 地址") from exc
        if not addresses:
            raise ProviderError("Jenkins 地址没有可用的网络地址")
        for address in addresses:
            if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
                raise ProviderError("Jenkins 地址解析到不允许访问的网络")
            if not address.is_global and not allow_private_network:
                raise ProviderError("Jenkins 内网地址需要项目管理员明确授权")
            if not address.is_global and not (address.is_private or address.is_global):
                raise ProviderError("Jenkins 地址解析到不允许访问的网络")
        path = parsed.path.rstrip("/")
        return urlunsplit(("https", parsed.netloc, path, "", ""))

    @staticmethod
    def validate_job_path(job_path: str) -> str:
        """Validate a slash-separated Jenkins folder/job path before URL encoding."""
        path = job_path.strip().strip("/")
        segments = path.split("/") if path else []
        if not segments or any(
            not _JOB_SEGMENT.fullmatch(part) or part in {".", ".."} or part.strip() != part
            for part in segments
        ):
            raise ProviderError("Jenkins Job 路径不合法")
        if len(path) > 255:
            raise ProviderError("Jenkins Job 路径超过 255 个字符")
        return "/".join(segments)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def test_connection(self) -> dict:
        return self._get_json("/whoAmI/api/json")

    def get_item(self, job_path: str) -> dict:
        path = self._job_url(job_path)
        return self._get_json(f"{path}/api/json", params={
            "tree": "name,url,_class,color,buildable,concurrentBuild,property[parameterDefinitions[name,type,defaultParameterValue[value]]],lastBuild[number,url,result,building],builds[number,url]",
        })

    def list_items(self, folder_path: str = "") -> list[dict]:
        if folder_path.strip("/"):
            item = self.get_item(folder_path)
            if "Folder" not in str(item.get("_class", "")):
                raise ProviderError("指定路径不是 Jenkins Folder")
            path = self._job_url(folder_path)
        else:
            path = ""
        payload = self._get_json(f"{path}/api/json", params={"tree": "jobs[name,url,_class,color,buildable]"})
        jobs = payload.get("jobs")
        return [item for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else []

    def trigger_build(self, job_path: str, params: dict[str, str] | None = None) -> str:
        safe_path = self.validate_job_path(job_path)
        job = self.get_item(safe_path)
        if "Folder" in str(job.get("_class", "")) or job.get("buildable") is False:
            raise ProviderError("Jenkins Job 不存在或不可执行")
        definitions = self._parameter_definitions(job)
        clean_params = self.validate_parameters(params or {})
        if clean_params and definitions:
            unknown = sorted(set(clean_params) - definitions)
            if unknown:
                raise ProviderError(f"Jenkins Job 未声明参数：{', '.join(unknown)}")
        endpoint = f"{self._job_url(safe_path)}/buildWithParameters" if clean_params else f"{self._job_url(safe_path)}/build"
        response = self._post(endpoint, data=clean_params or None)
        location = response.headers.get("Location", "")
        parsed_location = urlsplit(location)
        parsed_base = urlsplit(self.base_url)
        if parsed_location.netloc and (parsed_location.scheme != "https" or parsed_location.netloc != parsed_base.netloc):
            raise ProviderError("Jenkins 返回了不可信的队列地址")
        queue_id = _QUEUE_ID.search(parsed_location.path)
        if not queue_id:
            raise ProviderError("Jenkins 未返回有效的 Queue ID")
        return queue_id.group(1)

    def get_queue_item(self, queue_id: str) -> dict:
        safe_id = self._safe_number(queue_id, "Queue ID")
        return self._get_json(f"/queue/item/{safe_id}/api/json", params={
            "tree": "id,cancelled,why,blocked,buildable,executable[number,url]",
        })

    def cancel_queue_item(self, queue_id: str) -> bool:
        safe_id = self._safe_number(queue_id, "Queue ID")
        self._post(f"/queue/cancelItem?id={safe_id}")
        item = self.get_queue_item(safe_id)
        return bool(item.get("cancelled"))

    def get_build(self, job_path: str, build_number: int) -> dict:
        number = self._safe_number(build_number, "Build Number")
        path = f"{self._job_url(job_path)}/{number}/api/json"
        return self._get_json(path, params={
            "tree": "number,url,building,result,timestamp,duration,estimatedDuration,description,displayName,changeSet[items[commitId]],actions[parameters[name,value]]",
        })

    def stop_build(self, job_path: str, build_number: int) -> bool:
        number = self._safe_number(build_number, "Build Number")
        path = f"{self._job_url(job_path)}/{number}"
        build = self._get_json(f"{path}/api/json", params={"tree": "building,result"})
        if not build.get("building"):
            return False
        self._post(f"{path}/stop")
        confirmed = self._get_json(f"{path}/api/json", params={"tree": "building,result"})
        return not bool(confirmed.get("building")) or confirmed.get("result") == "ABORTED"

    def get_console_log(self, job_path: str, build_number: int, *, max_bytes: int = 200_000) -> str:
        number = self._safe_number(build_number, "Build Number")
        if not 1 <= max_bytes <= 1_000_000:
            raise ProviderError("Console 日志长度限制无效")
        response = self._request("GET", f"{self._job_url(job_path)}/{number}/consoleText")
        body = response.content[-max_bytes:]
        text = body.decode("utf-8", errors="replace")
        basic = base64.b64encode(f"{self._username}:{self._api_token}".encode()).decode()
        return text.replace(self._api_token, "***").replace(basic, "***")

    def _get_json(self, path: str, params: dict | None = None) -> dict:
        response = self._request("GET", path, params=params)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("Jenkins 返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Jenkins 返回的数据格式无效")
        return payload

    def _post(self, path: str, data: dict | None = None) -> httpx.Response:
        response = self._request("POST", path, data=data, allow_forbidden=True)
        if response.status_code == 403:
            try:
                crumb = self._get_json("/crumbIssuer/api/json")
                field = str(crumb.get("crumbRequestField") or "Jenkins-Crumb")
                value = str(crumb.get("crumb") or "")
                if value:
                    response = self._request("POST", path, data=data, headers={field: value})
            except ProviderError:
                pass
        if response.status_code not in {200, 201, 202, 302}:
            self._raise_status(response)
        return response

    def _request(self, method: str, path: str, *, params=None, data=None, headers=None, allow_forbidden=False):
        self._validate_destination()
        if path.startswith("http://") or path.startswith("https://") or path.startswith("//"):
            raise ProviderError("Jenkins API 路径无效")
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        try:
            response = self._client.request(method, url, params=params, data=data, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("Jenkins 请求超时") from exc
        except httpx.RequestError as exc:
            raise ProviderError("无法连接 Jenkins") from exc
        if response.is_redirect:
            location = response.headers.get("Location", "")
            target = urlsplit(urljoin(str(response.url), location))
            source = urlsplit(self.base_url)
            if target.scheme != "https" or target.netloc != source.netloc:
                raise ProviderError("Jenkins 返回了不可信的重定向目标")
            if method.upper() != "POST":
                raise ProviderError("Jenkins 查询请求发生重定向")
        if response.status_code >= 400 and not (allow_forbidden and response.status_code == 403):
            self._raise_status(response)
        return response

    def _validate_destination(self) -> None:
        parsed = urlsplit(self.base_url)
        # DNS is rechecked before every request to reduce rebinding exposure.
        self.validate_base_url(self.base_url, allow_private_network=self._allow_private_network)
        if parsed.hostname is None:
            raise ProviderError("Jenkins 地址无效")

    @staticmethod
    def _raise_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise ProviderError("Jenkins 认证失败，请检查 Username 和 API Token", 401)
        if response.status_code == 403:
            raise ProviderError("Jenkins 权限不足或 CSRF 校验失败", 403)
        if response.status_code == 404:
            raise ProviderError("Jenkins Job 或 API 不存在", 404)
        raise ProviderError(f"Jenkins API 请求失败（HTTP {response.status_code}）", response.status_code)

    @staticmethod
    def _parameter_definitions(job: dict) -> set[str]:
        names: set[str] = set()
        for prop in job.get("property", []) or []:
            for definition in prop.get("parameterDefinitions", []) or []:
                name = definition.get("name")
                if isinstance(name, str):
                    names.add(name)
        return names

    @staticmethod
    def validate_parameters(params: dict[str, str]) -> dict[str, str]:
        if len(params) > 64:
            raise ProviderError("Jenkins 构建参数数量超过限制")
        clean: dict[str, str] = {}
        for name, value in params.items():
            if not isinstance(name, str) or not _PARAMETER.fullmatch(name):
                raise ProviderError("Jenkins 构建参数名不合法")
            text = str(value)
            if len(text) > 2000 or "\x00" in text:
                raise ProviderError(f"Jenkins 构建参数 {name} 超过长度限制或包含非法字符")
            clean[name] = text
        return clean

    def _job_url(self, job_path: str) -> str:
        normalized = self.validate_job_path(job_path)
        return "/".join(f"job/{quote(part, safe='')}" for part in normalized.split("/"))

    @staticmethod
    def _safe_number(value: str | int, label: str) -> str:
        text = str(value)
        if not text.isdigit() or len(text) > 20:
            raise ProviderError(f"{label} 不合法")
        return text
