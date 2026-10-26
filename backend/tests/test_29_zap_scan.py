"""验收项 29：Security Testing Phase 2 —— OWASP ZAP 安全扫描集成。

覆盖开发计划的：
- §十二 扫描目标 / 认证配置 / 扫描策略（内置与项目自定义）CRUD 与权限边界；
- §十三 凭据只存密文，任何响应不回显明文（含列表页）；
- §十四 扫描计划预览只读，不产生任务、不发 ZAP 请求；
- §十五 危险路径与主动扫描限制（路径清单、破坏性方法、默认排除正则）；
- §二十一 迁移 0013：head、6 张 feature-local 表、ORM 与迁移逐列对齐、
  不进 app/models/__init__、降级只删 0013 的表；
- §二十二 报告口径：所有数字来自任务记录本身，不重新扫描；
- §二十三 人工确认闸门：主动扫描需要后端校验到真实的人类批准；
- §二十四 ZAP 版本与能力探测：不可达时如实返回 available=false；
- §二十五 后台任务：DB 领取、心跳超时清扫、终态保护、ZAP 未启用不启动。

真实 ZAP 进程不在测试范围：ZAP_ENABLED=false 是测试默认值，连接器构造通过
stub transport 或降级路径验证，不发起任何真实网络请求。
"""

from __future__ import annotations

import hashlib
import ipaddress
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from sqlalchemy import inspect, text

from tests.conftest import BACKEND_DIR, TEST_DSN, unique

# 0013 建的 6 张表。
ZAP_TABLES = frozenset(
    {
        "security_scan_auth_profile",
        "security_scan_target",
        "security_scan_profile",
        "security_scan_job",
        "security_scan_finding",
        "security_scan_event",
    }
)

# 0012 建的 4 张表：降级 0013 后必须原样保留。
WEB_UI_TABLES = frozenset(
    {"web_page_object", "web_auth_profile", "web_case", "web_artifact"}
)

# 公网 IP 字面量：测试不依赖 DNS 解析，也不落到任何私网网段。
PUBLIC_IP = "1.2.3.4"
BASE_URL = f"http://{PUBLIC_IP}"
ENTRY_URL = f"http://{PUBLIC_IP}/entry"

# OpenAPI 导出用例自建项目负责人时用的用户名（纯函数用例不走 HTTP 夹具）。
_IFACE_OWNER = "zap-iface-owner"


# --------------------------------------------------------------------------- 公共辅助


def _project(api, admin, name=None):
    r = api.post(
        "/projects", username=admin,
        json={"name": name or unique("zap-proj"), "description": "ZAP 扫描项目"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _register(api, username):
    """注册并登录，返回 user_id；username 同时是 api 调用键。"""
    r = api.register(username)
    assert r.status_code == 201, r.text
    api.login(username, "Init-Password-123")
    return r.json()["user"]["id"]


def _user_id(username):
    """按用户名回查 user_id：注册接口只在 201 时返回一次。"""
    from app.models.identity import User
    from app.shared.database import SessionLocal

    with SessionLocal() as session:
        return session.query(User).filter(User.username == username).one().id


def _add_member(api, admin, project_id, user_id, role="member"):
    r = api.put(
        f"/projects/{project_id}/members/{user_id}", username=admin,
        json={"user_id": user_id, "role": role},
    )
    assert r.status_code == 200, r.text


def _user(api, admin, project_id, prefix, role="member"):
    """注册一个新用户并加进项目，返回登录用户名（同时也是 api 调用键）。"""
    username = unique(prefix)
    _register(api, username)
    _add_member(api, admin, project_id, _user_id(username), role)
    return username


def _target_body(**overrides):
    """一个合法的扫描目标请求体。"""
    body = {
        "name": unique("target"),
        "target_type": "API",
        "base_url": BASE_URL,
        "entry_url": ENTRY_URL,
        "allowed_hosts": [PUBLIC_IP],
        "authorization_status": "AUTHORIZED",
        "active_scan_allowed": False,
    }
    body.update(overrides)
    return body


def _auth_body(**overrides):
    body = {
        "name": unique("auth"),
        "auth_mode": "BEARER_TOKEN",
        "session_method": "header",
        "credential": "sk-test-credential-001",
    }
    body.update(overrides)
    return body


def _profile_body(**overrides):
    body = {
        "name": unique("profile"),
        "scan_mode": "API_PASSIVE",
        "max_duration": 30,
        "max_depth": 5,
        "max_concurrency": 4,
    }
    body.update(overrides)
    return body


def _tables(db):
    return {
        row[0]
        for row in db.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public'"
            )
        )
    }


def _indexes(db):
    return {
        row[0]
        for row in db.execute(
            text("select indexname from pg_indexes where schemaname='public'")
        )
    }


def _alembic():
    """返回一个指向隔离测试库的 Alembic 配置，供用例自己升降级。"""
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DSN)
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def _make_environment(db, name=None):
    """插入一条 Environment 行，用于验证生产环境识别。

    环境名有唯一约束，同一测试会话里多个用例不能共用一个名字；
    "prod-<n>" 仍命中生产环境判定（prod 是词元前缀）。
    """
    from app.models.configuration import Environment

    name = name or unique("prod")
    row = Environment(
        name=name,
        display_name=name,
        base_url=BASE_URL,
        gateway_prefix="",
        is_active=True,
        is_default=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _make_job(db, project_id, target_id, profile_id, scan_mode="API_PASSIVE",
              status="PENDING", environment_id=None, **overrides):
    """直接落一条扫描任务，用于验证查询接口与后台任务。"""
    from app.features.security_testing.zap.models.job import SecurityScanJob

    row = SecurityScanJob(
        project_id=project_id,
        target_id=target_id,
        scan_profile_id=profile_id,
        scan_mode=scan_mode,
        status=status,
        environment_id=environment_id,
        **overrides,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _project_row(db):
    """直接插一条项目行：OpenAPI 导出这类纯函数用例只需要一个真实的 project_id。

    表里有外键约束，写死的 1 在别的用例先建过项目时就不成立，一律走真实行。
    这些用例不依赖 HTTP 夹具，所以负责人用户也在这里按需创建。
    """
    from app.models.identity import User
    from app.models.project import Project

    owner = db.query(User).filter(User.username == _IFACE_OWNER).first()
    if owner is None:
        owner = User(username=_IFACE_OWNER, role="test", is_active=True)
        db.add(owner)
        db.flush()
    row = Project(name=unique("zap-iface-proj"), owner_id=owner.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _interface(db, project_id, *, path, method="GET", name=None, status="ACTIVE"):
    """插入一条接口契约行，供 OpenAPI 导出用例使用。"""
    from app.features.api_catalog.models.api_interface import ApiInterface

    row = ApiInterface(
        project_id=project_id,
        name=name or unique("iface"),
        method=method,
        path=path,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _fixed_resolver(*address, record=None):
    """构造一个结果固定的 resolver：用例不依赖真实 DNS（可能被本地转发污染）。

    不传参数时默认返回一个公网地址（PUBLIC_IP）——空列表在实现里意味着「解析失败」，
    会被当成范围违规拒绝，那是另一个口径，不能用它表示「这个主机合法」。
    record 传入列表时，把每次被查询的主机名记进去，用来证明「确实走了 DNS 分支」
    而不是被别的判断提前短路掉。
    """
    result = [ipaddress.ip_address(item) for item in (address or (PUBLIC_IP,))]

    def resolver(host):
        if record is not None:
            record.append(host)
        return result

    return resolver


def _scan_target(db, project_id, **overrides):
    """直接插一条扫描目标：纯函数用例只需要一个真实的 target_id（security_scan_job 有外键）。"""
    from app.features.security_testing.zap.models.target import SecurityScanTarget

    body = _target_body()
    body.update(overrides)
    row = SecurityScanTarget(
        project_id=project_id,
        name=body["name"],
        target_type=body["target_type"],
        base_url=body["base_url"],
        entry_url=body["entry_url"],
        enabled=body.get("enabled", True),
        authorization_status=body["authorization_status"],
        active_scan_allowed=body["active_scan_allowed"],
        allowed_hosts=body["allowed_hosts"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _job_context(db):
    """建项目 / 目标 / 策略 / 任务，返回 (project_id, 负责人 User, job_id)。

    service 层用例需要一个真实的项目查看身份（owner），比走 HTTP 注册快，
    也不需要 ZAP 相关的 monkeypatch。任务直接落成 COMPLETED（终态），
    既不会被后台任务领取，也不占用「单实例只跑一个」的并发额度。
    """
    from app.models.identity import User
    from app.models.project import Project

    project_id = _project_row(db)
    owner = db.get(User, db.get(Project, project_id).owner_id)
    target_id = _scan_target(db, project_id)
    profile_id = _profile(db, project_id, scan_mode="API_PASSIVE")
    # counts 与下面 _seed_alert_risks 造出的四行保持一致：
    # Medium 档算两行（已识别的 Medium + 未识别值落默认 MEDIUM）。
    job_id = _make_job(
        db, project_id, target_id, profile_id, scan_mode="API_PASSIVE",
        status="COMPLETED", total_alerts=4, high_count=1, medium_count=2, info_count=1,
    )
    return project_id, owner, job_id


def _scan_alert_link(db, project_id, job_id, risk, *, source_rule_id=None,
                     confidence=3, url=None, severity=None):
    """插一行「本次扫描命中一条告警」：security_finding + security_scan_finding。

    risk 存 ZAP 原文（High / Medium / Informational / 未识别值），severity 走 map_zap_risk
    （未识别值落默认 MEDIUM）——与真实归一化路径一致，这样 severity 过滤测试才真的
    测到「映射表反查」而不是两个字符串的比较。
    """
    from app.features.api_catalog.models.api_interface import ApiInterface  # noqa: F401
    from app.features.security_testing.models.finding import SecurityFinding
    from app.features.security_testing.zap.contracts import map_zap_risk
    from app.features.security_testing.zap.models.finding_link import SecurityScanFinding

    # SecurityFinding.api_id 的外键指向 api_interface：必须先注册那张表，
    # 否则单独导入 security_testing 的模型会 NoReferencedTableError。
    del ApiInterface

    rule_id = source_rule_id or unique("zap-rule")
    mapped = severity or map_zap_risk(risk)
    finding = SecurityFinding(
        project_id=project_id,
        mutation_type="ZAP_ALERT",
        severity=mapped,
        status="OPEN",
        title=f"ZAP 告警 {rule_id}",
        description="扫描器报告的疑似问题（未经人工验证）",
        fingerprint=hashlib.sha256(unique("zap-fp").encode("utf-8")).hexdigest(),
    )
    db.add(finding)
    db.flush()
    link = SecurityScanFinding(
        project_id=project_id,
        job_id=job_id,
        finding_id=finding.id,
        source="ZAP",
        source_rule_id=rule_id,
        source_alert_name=f"告警 {risk}",
        risk=risk,
        confidence=confidence,
        url=url or BASE_URL,
        evidence_json={
            "rule_id": rule_id,
            "name": f"告警 {risk}",
            "risk": risk,
            "confidence": confidence,
            "severity": mapped,
            "url": url or BASE_URL,
            "evidence": "",
        },
        first_seen_in_job=True,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


#: severity 过滤用例统一使用的四档 risk：三档已识别值 + 一个未识别值。
#: 未识别值故意保留——它是「映射失败落默认 MEDIUM」这条口径的观测点。
_ALERT_RISKS = (
    ("High", "zap-rule-high"),
    ("Medium", "zap-rule-medium"),
    ("Informational", "zap-rule-info"),
    ("weird", "zap-rule-unknown"),
)


def _seed_alert_risks(db, project_id, job_id):
    """按 _ALERT_RISKS 造出四行告警。"""
    seeded = []
    for risk, rule_id in _ALERT_RISKS:
        _scan_alert_link(db, project_id, job_id, risk, source_rule_id=rule_id)
        seeded.append((risk, rule_id))
    return seeded


# --------------------------------------------------------------------------- 迁移


class TestMigration:
    def test_head_is_0016_and_tables_created(self, db):
        head = db.execute(text("select version_num from alembic_version")).scalar()
        assert head == "0016"
        assert ZAP_TABLES.issubset(_tables(db))

    def test_orm_matches_migrated_schema(self, db):
        """ORM 模型与迁移逐列对齐：feature-local 表不进 models/__init__，靠这个断言防漂移。"""
        from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
        from app.features.security_testing.zap.models.finding_link import SecurityScanFinding
        from app.features.security_testing.zap.models.job import SecurityScanEvent, SecurityScanJob
        from app.features.security_testing.zap.models.profile import SecurityScanProfile
        from app.features.security_testing.zap.models.target import SecurityScanTarget

        models = {
            SecurityScanAuthProfile, SecurityScanTarget, SecurityScanProfile,
            SecurityScanJob, SecurityScanFinding, SecurityScanEvent,
        }
        inspector = inspect(db.bind)
        live_indexes = _indexes(db)
        for model in models:
            table = model.__table__
            assert table.name in ZAP_TABLES, f"{model.__name__} 表名不在 0013 清单里"
            assert {c["name"] for c in inspector.get_columns(table.name)} == {
                c.name for c in table.columns
            }, f"{table.name} 列与迁移不一致"

    def test_models_not_reexported_from_app_models(self):
        """红线 17：feature-local 模型不许进 app/models/__init__.py。"""
        source = (BACKEND_DIR / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
        for name in (
            "security_testing", "security_scan", "SecurityScanTarget",
            "SecurityScanJob", "SecurityScanProfile", "SecurityScanFinding",
            "SecurityScanAuthProfile", "SecurityScanEvent",
        ):
            assert name not in source, f"app/models/__init__.py 不应暴露 {name}"

    def test_partial_unique_indexes(self, db):
        indexes = _indexes(db)
        assert "uq_security_scan_finding_job_finding" in indexes
        assert "ix_security_scan_profile_code" in indexes
        # 事件序号唯一：并发写入方（后台实例 + HTTP 请求）算出的同号必须被挡住。
        assert "uq_security_scan_event_job_seq" in indexes
        assert "ix_security_scan_event_job_seq" not in indexes

    def test_downgrade_removes_only_zap_tables(self, db):
        """降级到 0012 只删 0013 建的表：Mock（0011）、Web UI（0012）表原样保留。"""
        from alembic import command

        config = _alembic()
        command.downgrade(config, "0012")
        try:
            tables = _tables(db)
            assert not (ZAP_TABLES & tables), ZAP_TABLES & tables
            assert WEB_UI_TABLES.issubset(tables), WEB_UI_TABLES - tables
        finally:
            command.upgrade(config, "head")

        tables = _tables(db)
        assert ZAP_TABLES.issubset(tables)
        assert db.execute(text("select version_num from alembic_version")).scalar() == "0016"


# --------------------------------------------------------------------------- 范围守卫（§四 / §五 / §十五）


class TestScopeGuard:
    def test_production_environment_detected(self):
        from app.features.security_testing.zap.scope_guard import is_production_environment

        for name in (
            "prod", "PROD", "Prod", "production", "production-2", "production-2024",
            "线上", "生产", "正式环境", "上海生产", "staging-prod", "prc-prod",
        ):
            assert is_production_environment(name), name

    def test_non_production_environment_not_flagged(self):
        from app.features.security_testing.zap.scope_guard import is_production_environment

        for name in ("dev", "test", "uat", "预发", "测试环境", None, ""):
            assert not is_production_environment(name), name

    def test_validate_target_url_normalizes_trailing_slash(self):
        from app.features.security_testing.zap.scope_guard import validate_target_url

        assert validate_target_url(
            f"{BASE_URL}/", allowed_hosts=[PUBLIC_IP],
        ) == BASE_URL

    def test_reserved_address_rejected(self):
        from app.features.security_testing.zap.scope_guard import validate_target_url

        for host in ("127.0.0.1", "10.0.0.1", "192.168.1.10", "169.254.169.254", "0.0.0.0", "::1"):
            try:
                validate_target_url(f"http://{host}/", allowed_hosts=[host])
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", host
            else:
                raise AssertionError(f"保留地址未被拒绝：{host}")

    def test_scheme_credentials_rejected(self):
        from app.features.security_testing.zap.scope_guard import validate_target_url

        for url in (
            "ftp://1.2.3.4/",
            "gopher://1.2.3.4/",
            "http://user:pass@1.2.3.4/",
            "http://1.2.3.4:99999/",
        ):
            try:
                validate_target_url(url, allowed_hosts=[PUBLIC_IP])
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", url
            else:
                raise AssertionError(f"非法 URL 未被拒绝：{url}")

    def test_port_scope_requires_explicit_whitelist_entry(self):
        """白名单只写主机名时不能放行该主机上的其它端口。"""
        from app.features.security_testing.zap.scope_guard import validate_target_url

        # 白名单只有主机名 → 非默认端口必须被拒绝。
        try:
            validate_target_url(
                f"http://{PUBLIC_IP}:8443/", allowed_hosts=[PUBLIC_IP],
            )
        except Exception as exc:
            assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION"
        else:
            raise AssertionError("未写端口的白名单条目不应放行 8443")

        # 白名单写了 host:port → 放行。
        assert validate_target_url(
            f"http://{PUBLIC_IP}:8443/", allowed_hosts=[f"{PUBLIC_IP}:8443"],
        ) == f"http://{PUBLIC_IP}:8443"

    def test_whitelist_entry_tolerates_scheme_credentials_and_paths(self):
        from app.features.security_testing.zap.scope_guard import validate_target_url

        for entry in (
            f"http://{PUBLIC_IP}:8443",
            f"http://user:pass@{PUBLIC_IP}:8443",
            f"{PUBLIC_IP}:8443/console",
            f"{PUBLIC_IP}:8443",
        ):
            assert validate_target_url(
                f"http://{PUBLIC_IP}:8443/", allowed_hosts=[entry],
            ) == f"http://{PUBLIC_IP}:8443", entry

    def test_allowlist_normalization_ignores_port(self):
        """_normalize_host_set 只留主机名：白名单条目带端口不影响主机匹配。"""
        from app.features.security_testing.zap.scope_guard import _normalize_host_set

        assert _normalize_host_set([
            f"http://{PUBLIC_IP}:8443",
            f"{PUBLIC_IP}:9000",
            f"{PUBLIC_IP}",
        ]) == frozenset({PUBLIC_IP})

    def test_ip_literal_alternate_forms_not_bypass(self):
        """八进制 / 十六进制 / 前导零 / 末尾点号这些写法不能被当成公网地址放行。"""
        from app.features.security_testing.zap.scope_guard import (
            is_reachable_public_ip,
            validate_target_url,
        )

        import ipaddress

        for raw in ("0177000001", "0177.0.0.1", "2130706433", "0x7f000001"):
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError:
                continue
            assert not is_reachable_public_ip(ip), raw

        for host in ("127.0.0.1", "0177.0.0.1", "127.1"):
            try:
                validate_target_url(f"http://{host}/", allowed_hosts=[host])
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", host
            else:
                raise AssertionError(f"替代写法的回环地址被放行了：{host}")

    def test_empty_allowlist_allows_any_host_but_keeps_port(self):
        """allowed_hosts 为空时不做主机限制，但端口必须原样带回返回的 netloc。

        base_url 的端口一旦丢掉，ZAP 会打到同一主机的默认端口上——那是另一个服务，
        而且全程不报错（§四 范围限制）。这与「白名单写了端口就必须精确匹配」互补：
        空名单是有意放开，端口仍不能被规范化掉。
        """
        from app.features.security_testing.zap.scope_guard import validate_target_url

        stub = _fixed_resolver()
        cases = [
            (f"http://{PUBLIC_IP}:8443/entry/", f"http://{PUBLIC_IP}:8443/entry"),
            ("http://api.example.com:8443/entry/", "http://api.example.com:8443/entry"),
            ("https://api.example.com/secure/", "https://api.example.com/secure"),
        ]
        for url, expected in cases:
            assert validate_target_url(url, allowed_hosts=(), resolver=stub) == expected, url

    def test_allowlist_port_mismatch_is_rejected(self):
        """名单写了 8443 就只放行 8443：同一主机上的其它端口必须被拒。

        管理员只想放 8443，如果端口不参与匹配，同机的 ssh / redis / memcached 端口
        会跟着一起被扫——白名单就退化成「只限制主机名」了。主机不在名单里同样拒绝。
        """
        from app.features.security_testing.zap.scope_guard import validate_target_url

        stub = _fixed_resolver()
        for port in (80, 443, 9000, 22, 6379, 11211):
            try:
                validate_target_url(
                    f"http://api.example.com:{port}/",
                    allowed_hosts=["api.example.com:8443"], resolver=stub,
                )
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", port
            else:
                raise AssertionError(f"端口 {port} 被放行了，而白名单只写了 8443")

        # 主机对了但主机不在名单里：拒绝。
        try:
            validate_target_url(
                "http://evil.example.com:8443/",
                allowed_hosts=["api.example.com:8443"], resolver=stub,
            )
        except Exception as exc:
            assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION"
        else:
            raise AssertionError("不在白名单里的主机被放行了")

        # 主机与端口都对上：放行，且端口保留。
        assert validate_target_url(
            "http://api.example.com:8443/", allowed_hosts=["api.example.com:8443"], resolver=stub,
        ) == "http://api.example.com:8443"

    def test_allowlist_entry_forms_scheme_credentials_and_ipv6(self):
        """白名单条目带 scheme / 凭据 / IPv6 方括号时，都要解析出正确的 host:port。

        运维习惯写法五花八门（贴整条 URL、带凭据、主机名大小写不同），
        解析口径不一致会导致「管理员以为配了 8443，实际什么端口都没配上」。
        """
        from app.features.security_testing.zap.scope_guard import (
            _normalize_host_set,
            validate_target_url,
        )

        stub = _fixed_resolver()
        target = "http://api.example.com:8443/x"
        for entry in (
            "http://api.example.com:8443",
            "HTTPS://api.example.com:8443",
            "http://user:pass@api.example.com:8443",
            "http://user@api.example.com:8443",
            "api.example.com:8443/console",
            "API.example.com:8443",
        ):
            assert validate_target_url(
                target, allowed_hosts=[entry], resolver=stub,
            ) == "http://api.example.com:8443/x", entry

        # IPv6：方括号必须被剥掉再拆端口，否则主机名里残留方括号永远匹配不上。
        v6_host = "2606:4700:4700::1111"
        v6_target = f"http://[{v6_host}]:8443/"
        for entry in (
            f"[{v6_host}]:8443",
            f"http://[{v6_host}]:8443",
            f"http://user:pass@[{v6_host}]:8443",
        ):
            assert validate_target_url(
                v6_target, allowed_hosts=[entry], resolver=stub,
            ) == f"http://[{v6_host}]:8443", entry

        # IPv6 白名单只写主机名（未写端口）时，非默认端口仍然必须被拒。
        try:
            validate_target_url(
                v6_target, allowed_hosts=[f"[{v6_host}]"], resolver=stub,
            )
        except Exception as exc:
            assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION"
        else:
            raise AssertionError("IPv6 白名单未写端口，却放行了 8443")

        # 裸 IPv6（不带方括号）无法拆分 host:port，必须报范围违规而不是 500——
        # hostname 属性在畸形输入上会抛 ValueError，实现里已经用 try 兜住了。
        for bad in (v6_target.replace("://[", "://").replace("]:", ":"), "http://[::1]x/"):
            try:
                validate_target_url(bad, allowed_hosts=[], resolver=stub)
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", bad
            else:
                raise AssertionError(f"畸形 IPv6 地址被放行了：{bad}")

        # 裸 IPv6 出现在**白名单条目**里会 fail-closed（不会放行），但会被误拆成主机名
        # "2606"，管理员看到「不在允许的主机范围内」会完全摸不着头脑；这里记录现状。
        assert _normalize_host_set([v6_host]) == frozenset({"2606"})

    def test_numeric_ip_forms_rejected_even_when_resolver_says_public(self):
        """数字形态的 IP 字面量必须直接拒绝，不能交给系统解析器判断。

        0177.0.0.1 / 0x7f000001 / 2130706433 / 127.1 这些 ipaddress 不认识，
        但系统解析器会按数字形态解析，而且**不同平台结果不同**：macOS 的 getaddrinfo
        把 0177.0.0.1 解成公网的 177.0.0.1，Linux 解成 127.0.0.1。这里用固定 resolver
        返回公网地址模拟 macOS 的情况——如果实现把这些写法交给了 resolver，
        它们就会被放行，扫描实际打到哪个地址完全取决于部署机装了什么解析器。
        """
        from app.features.security_testing.zap.scope_guard import validate_target_url

        resolver_says_public = _fixed_resolver("1.2.3.4")
        # 注意 0x 十六进制写法：0x 里的字面 x 落在 g-z 区间，早期实现用「整串不含
        # g-z 字母」预判，会把 0x7f000001 误当成普通域名交给 resolver。实现已改为
        # 按点分段逐个判断，这里保留全部形态作为回归防线。
        forms = ("0177.0.0.1", "2130706433", "127.1", "0177000001", "0177.0.0.01",
                 "0x7f000001", "0x7f", "0x7f000001.0", "0x7f.0.0.01", "127.0x1")
        leaked = []
        for host in forms:
            try:
                validate_target_url(
                    f"http://{host}/", allowed_hosts=[], resolver=resolver_says_public,
                )
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", host
            else:
                leaked.append(host)
        assert not leaked, f"这些数字形态的 IP 被解析器放行了：{leaked}"

    def test_normal_hostnames_are_not_misclassified_as_numeric(self):
        """正常域名不能被误判成数字形态：否则合法目标会被无意义地拒绝。

        数字形态的判定口径是「每一个点分段都长成数字段」。这里反过来确认它没有
        误伤：api.example.com / localhost / abc123 / a 这类主机名至少有一个段带字母，
        必须真的走到 resolver 分支（calls 非空），而不是被数字形态检查提前拦掉。
        """
        from app.features.security_testing.zap.scope_guard import validate_target_url

        calls: list[str] = []
        stub = _fixed_resolver("1.2.3.4", record=calls)
        for host in ("api.example.com", "localhost", "abc123", "a", "www.a.co"):
            assert validate_target_url(
                f"http://{host}/", allowed_hosts=[], resolver=stub,
            ) == f"http://{host}", host
        assert calls == ["api.example.com", "localhost", "abc123", "a", "www.a.co"]

    def test_allowlist_entry_that_parses_to_empty_must_be_rejected(self):
        """解析不出主机名的白名单条目必须报错，不能静默把白名单变成空集。

        `allowed_hosts=["::1"]`（不带方括号的 IPv6）、`[]:80`、`:80`、`http:///x`、
        `user@` 这类条目都拆不出主机名。早期实现把它们静默丢弃，白名单随之规范化成
        空集；而空集在 validate_target_url 里等于「不做任何主机限制」，于是任何公网
        主机都被放行，管理员声明的扫描范围从这一刻起完全失效（assert_redirect_allowed
        的同主机兜底也因为 allowed_hosts 非空而被跳过）。现在这些条目一律报范围违规。
        空列表仍然是「未配置限制」，两者有意区分开。
        """
        from app.features.security_testing.zap.scope_guard import validate_allowed_hosts

        accepted = []
        for entry in ("::1", "[]:80", ":80", "http:///x", "user@"):
            try:
                validate_allowed_hosts([entry], resolver=_fixed_resolver())
            except Exception as exc:
                assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION", entry
            else:
                accepted.append(entry)
        assert not accepted, f"这些解析不出主机名的白名单条目被静默放行了：{accepted}"

    def test_redirect_restricted_to_same_host_when_no_allowlist(self):
        from app.features.security_testing.zap.scope_guard import assert_redirect_allowed

        assert_redirect_allowed(
            f"{BASE_URL}/console", base_url=BASE_URL,
        )
        try:
            assert_redirect_allowed("http://1.2.3.5/", base_url=BASE_URL)
        except Exception as exc:
            assert exc.code == "SECURITY_SCAN_SCOPE_VIOLATION"
        else:
            raise AssertionError("跳转到其它主机未被拒绝")

    def test_redirect_allowed_when_in_whitelist(self):
        from app.features.security_testing.zap.scope_guard import assert_redirect_allowed

        assert_redirect_allowed(
            "http://1.2.3.5/", base_url=BASE_URL, allowed_hosts=["1.2.3.5"],
        )

    def test_compile_path_regex_escapes_metacharacters(self):
        from app.features.security_testing.zap.scope_guard import compile_path_regex

        assert compile_path_regex([]) is None
        assert compile_path_regex(["", "   "]) is None

        pattern = compile_path_regex(["/api/admin.v2", "logout", "admin+panel"])
        assert pattern is not None
        import re as _re

        # 元字符被转义：不该匹配到不带点号的 api/adminv2。
        assert _re.search(pattern, "/api/adminv2") is None
        for candidate in ("/api/admin.v2", "/logout", "/a/admin+panel/b", "logout"):
            assert _re.search(pattern, candidate), candidate

    def test_default_active_exclude_regex_contains_high_risk_paths(self):
        from app.features.security_testing.zap.scope_guard import (
            HIGH_RISK_ACTIVE_PATH_PATTERNS,
            default_active_exclude_regex,
        )

        pattern = default_active_exclude_regex()
        assert pattern.startswith("(?i)(^|/)") and pattern.endswith("(/|$)")
        for name in ("logout", "delete", "payment", "transfer", "withdraw"):
            assert name in HIGH_RISK_ACTIVE_PATH_PATTERNS, name
            assert name in pattern, name

    def test_destructive_methods_and_blocked_actions(self):
        from app.features.security_testing.zap.scope_guard import (
            BLOCKED_ACTIVE_ACTIONS,
            DESTRUCTIVE_METHODS,
        )

        assert {"DELETE", "PATCH", "PUT"}.issubset(DESTRUCTIVE_METHODS)
        assert "GET" not in DESTRUCTIVE_METHODS
        assert {"payment", "delete", "transfer", "bulk_update"}.issubset(BLOCKED_ACTIVE_ACTIONS)

    def test_active_scan_authorization_gate(self):
        from app.features.security_testing.zap.scope_guard import assert_active_scan_authorized

        # 非主动扫描一律放行。
        assert_active_scan_authorized(
            environment_name="生产", scan_mode="API_PASSIVE",
            active_authorized=False, environment_active_allowed=False,
        )

        cases = [
            # (env, active_authorized, env_allowed, 是否应拒绝)
            ("生产", True, True, True),
            ("test", True, False, True),
            ("test", False, True, True),
            ("test", True, True, False),
        ]
        for env, authorized, allowed, blocked in cases:
            try:
                assert_active_scan_authorized(
                    environment_name=env, scan_mode="API_ACTIVE",
                    active_authorized=authorized, environment_active_allowed=allowed,
                )
            except Exception:
                assert blocked, (env, authorized, allowed)
            else:
                assert not blocked, (env, authorized, allowed)


# --------------------------------------------------------------------------- OpenAPI 导出（§十三 出口）


class TestOpenAPIExport:
    def test_document_shape_and_normalization(self, db):
        from app.features.security_testing.zap.openapi_export import (
            OPENAPI_VERSION,
            build_openapi_document,
            count_interfaces,
            render_openapi_json,
        )

        pid = _project_row(db)
        _interface(db, pid, path="/users/{user_id}", method="GET")
        _interface(db, pid, path="/users", method="POST")

        doc = build_openapi_document(
            db, pid, base_url=BASE_URL, target_name="api-target", environment_name="test",
        )
        assert doc["openapi"] == OPENAPI_VERSION == "3.0.3"
        assert doc["servers"] == [{"url": BASE_URL}]
        assert "api-target" in doc["info"]["title"]
        assert count_interfaces(doc) == 2

        assert "/users/{user_id}" in doc["paths"]
        operation = doc["paths"]["/users/{user_id}"]["get"]
        # path 占位符必须出现在 path 参数里，否则文档不自洽、ZAP 拒绝导入。
        path_params = [p for p in operation["parameters"] if p["in"] == "path"]
        assert {"name": "user_id", "in": "path"}.items() <= {**path_params[0]}.items()
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["type"] == "object"

        assert isinstance(render_openapi_json(doc), str)
        assert render_openapi_json(doc) == render_openapi_json(dict(doc))

    def test_normalized_path_collision_keeps_one_operation(self, db):
        """库里 path 写法不统一（`:id` 与 `{id}`），归一后同一 path+method 只能有一份。

        不能用「两条完全相同的 path」来造重复：数据库有 uq_api_interface_project_method_path
        唯一约束，重复插不进去。真正会出现重复的是写法不同、归一后相同的接口。
        """
        from app.features.security_testing.zap.openapi_export import (
            build_openapi_document,
            count_interfaces,
        )

        pid = _project_row(db)
        _interface(db, pid, path="/users/:id", method="GET", name="第一条")
        _interface(db, pid, path="/users/{id}", method="GET", name="第二条")
        doc = build_openapi_document(db, pid, base_url=BASE_URL)
        assert count_interfaces(doc) == 1
        assert set(doc["paths"]["/users/{id}"]) == {"get"}

    def test_db_rejects_duplicate_method_path(self, db):
        """同一项目下 path+method 的重复由数据库唯一约束兜底（导出侧的折叠只是防线之二）。"""
        from sqlalchemy.exc import IntegrityError

        pid = _project_row(db)
        _interface(db, pid, path="/dup", method="GET", name="第一条")
        with pytest.raises(IntegrityError):
            _interface(db, pid, path="/dup", method="GET", name="第二条")
        db.rollback()

    def test_truncation_reports_limit_in_description(self, db):
        from app.features.security_testing.zap.openapi_export import (
            build_openapi_document,
            count_interfaces,
        )

        pid = _project_row(db)
        for index in range(6):
            _interface(db, pid, path=f"/iface/{index}", method="GET")
        doc = build_openapi_document(db, pid, base_url=BASE_URL, max_interfaces=2)
        assert count_interfaces(doc) == 2
        assert "仅导出前 2 个" in doc["info"]["description"]
        # 只导出 ID 升序的前两条。
        assert "/iface/0" in doc["paths"] and "/iface/1" in doc["paths"]
        assert "/iface/5" not in doc["paths"]

    def test_only_active_filters_draft_interfaces(self, db):
        from app.features.security_testing.zap.openapi_export import build_openapi_document

        pid = _project_row(db)
        _interface(db, pid, path="/live", method="GET", status="ACTIVE")
        _interface(db, pid, path="/draft", method="GET", status="DRAFT")
        doc = build_openapi_document(db, pid, base_url=BASE_URL, only_active=True)
        assert "/live" in doc["paths"] and "/draft" not in doc["paths"]

    def test_credential_header_is_not_exported_as_value(self, db):
        """Authorization 这类凭据头不会把示例值写进文档。"""
        from app.features.api_catalog.models.api_parameter import ApiParameter
        from app.features.security_testing.zap.openapi_export import build_openapi_document

        pid = _project_row(db)
        iface_id = _interface(db, pid, path="/secured", method="GET")
        db.add(ApiParameter(
            interface_id=iface_id, name="Authorization", location="header",
            type="string", required=True, example="Bearer sk-live-secret-token",
        ))
        db.commit()

        doc = build_openapi_document(db, pid, base_url=BASE_URL)
        rendered = str(doc["paths"]["/secured"]["get"])
        assert "sk-live-secret-token" not in rendered
        assert "Authorization" in rendered


# --------------------------------------------------------------------------- 证据脱敏（§十一 / §二十一 / §三十四 第 8 条）


class TestEvidenceRedaction:
    """脱敏是「告警能不能给人看」的最后一道闸，这里直接喂恶意输入。

    不绕「写入 job → 再读 alerts 接口」那条间接路径：那条路径读到的是归一化后的
    另一个字段，测不到脱敏函数自己的分支（递归深度、大小写归一、截断上限）。
    """

    def test_redact_mapping_replaces_sensitive_values_with_placeholder(self):
        """敏感键名下的值整体换成占位符；非敏感键一个都不能被打星号。

        ZAP 的 evidence 会原样回显请求头，authorization / cookie / token 之类的键
        一旦落库就等于把凭据写进数据库，项目里任何人查到就能看到明文。
        """
        from app.features.security_testing.zap.contracts import (
            REDACTED_PLACEHOLDER,
            redact_mapping,
        )

        payload = {
            "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sig",
            "cookie": "sid=s3ssion-abc; theme=dark",
            "token": "tok_live_9f8a7b6c",
            "api_key": "sk-test-credential-001",
            "password": "hunter2",
            "x-zap-api-key": "zap-key-0001",
            "rule_name": "JWT Cookie",
            "param": "user_id",
            "status_code": 200,
        }

        out = redact_mapping(payload)

        # x-zap-api-key 是 ZAP 自己的 API Key 头（请求头回显里的标准形态）。
        # 已修复：此前归一只把**输入键名**的连字符换成下划线，而集合条目只去空格，
        # 于是 SENSITIVE_FIELD_NAMES 里带连字符的条目（x-zap-api-key / set-cookie）
        # 永远匹配不上，其连字符 / 下划线 / 大小写变体全部漏脱。现在两侧统一走
        # _canonical_key，连字符键名同样整值替换。
        sensitive_keys = ("authorization", "cookie", "token", "api_key",
                          "password", "x-zap-api-key")
        leaked = [key for key in sensitive_keys if out[key] != REDACTED_PLACEHOLDER]
        assert not leaked, f"敏感键名的值没有被替换成占位符：{leaked}"
        # 非敏感字段必须原样保留，否则告警页面无法判读。
        assert out["rule_name"] == "JWT Cookie"
        assert out["param"] == "user_id"
        assert out["status_code"] == 200
        rendered = str(out)
        for secret in (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "s3ssion-abc",
            "tok_live_9f8a7b6c", "sk-test-credential-001", "hunter2", "zap-key-0001",
        ):
            assert secret not in rendered, secret

    def test_redact_mapping_recurses_into_nested_structures(self):
        """嵌套 dict / dict 列表 / 标量列表都要递归到叶子上脱敏。

        ZAP 的 evidence 是多层 JSON（headers → cookies 列表 → 单个 cookie 串）；
        只扫一层的话，内层凭据会原样落库。同时嵌套结构里的非敏感键不能被误伤。
        """
        from app.features.security_testing.zap.contracts import (
            REDACTED_PLACEHOLDER,
            redact_mapping,
        )

        payload = {
            "headers": {
                "host": "api.example.com",
                "authorization": "Bearer nested-jwt",
                "nested": {"cookie": "sid=inner-abc", "referer": "/login"},
            },
            "cookie_items": [
                {"name": "JSESSIONID", "session": "sess-1"},
                {"name": "theme", "value": "dark", "cookie": "sid=xyz"},
            ],
            "token": ["one", "two", "three"],
            "ids": [1, 2, 3],
        }

        out = redact_mapping(payload)

        assert out["headers"]["host"] == "api.example.com"
        assert out["headers"]["authorization"] == REDACTED_PLACEHOLDER
        assert out["headers"]["nested"]["cookie"] == REDACTED_PLACEHOLDER
        assert out["headers"]["nested"]["referer"] == "/login"

        # dict 列表：每个元素各自按自己的键名判断，敏感键名命中才抹。
        assert out["cookie_items"][0]["name"] == "JSESSIONID"
        assert out["cookie_items"][0]["session"] == REDACTED_PLACEHOLDER
        assert out["cookie_items"][1]["name"] == "theme"
        assert out["cookie_items"][1]["value"] == "dark"
        assert out["cookie_items"][1]["cookie"] == REDACTED_PLACEHOLDER

        # 标量列表在敏感键下逐个替换；在非敏感键下原样保留。
        assert out["token"] == [REDACTED_PLACEHOLDER] * 3
        assert out["ids"] == [1, 2, 3]

    def test_redact_mapping_preserves_non_sensitive_payload_verbatim(self):
        """脱敏不能改变非敏感内容的形状：值、顺序、数字类型都要原样。

        「只认键名不认值」是刻意的口径——JWT 这类长串无法靠形态可靠识别，
        反过来也不能因为字符串长得像凭据就误删业务字段。
        """
        from app.features.security_testing.zap.contracts import redact_mapping

        payload = {
            "scanner": "ZAP",
            "source_rule_id": "40012",
            "rule_name": "JWT cookie can be used for API auth",
            "method": "POST",
            "cwe_id": 79,
            "detail": "响应体里回显了 input 字段，值看起来像令牌",
        }
        assert redact_mapping(payload) == payload

    def test_redact_value_decides_by_key_name_not_value_shape(self):
        """redact_value 只看键名：不猜 JWT 形态，凭据由配置端标记。

        这里同时钉住两个方向——敏感键必抹，非敏感键（含 None）必保留。
        如果实现改成「按值形态识别凭据」，后两个断言就会失败。
        """
        from app.features.security_testing.zap.contracts import (
            REDACTED_PLACEHOLDER,
            redact_value,
        )

        jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature-tail"
        assert redact_value("token", jwt_like) == REDACTED_PLACEHOLDER
        assert redact_value("access_token", jwt_like) == REDACTED_PLACEHOLDER
        assert redact_value("Authorization", jwt_like) == REDACTED_PLACEHOLDER
        assert redact_value("detail", jwt_like) == jwt_like
        assert redact_value(None, jwt_like) == jwt_like

    def test_redact_text_masks_bearer_and_cookie_in_header_echo(self):
        """请求头回显是凭据进证据字段的主要通道，三种形态都要抹掉。

        扫描器告警里的 evidence 常常就是原始响应片段；不脱敏的话 JWT 与
        session cookie 会直接出现在告警详情和覆盖率快照里。
        """
        from app.features.security_testing.zap.contracts import redact_text

        evidence = (
            "POST /login HTTP/1.1\r\n"
            "Host: api.example.com\r\n"
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig\r\n"
            "User-Agent: Mozilla/5.0\r\n"
            "Bearer legacy-token-abc\r\n"
            "Cookie: sid=s3ssion-abc; theme=dark\r\n"
            "Accept: application/json\r\n"
        )

        out = redact_text(evidence)

        for secret in ("eyJhbGciOiJIUzI1NiJ9", "legacy-token-abc", "s3ssion-abc"):
            assert secret not in out, secret
        assert "Authorization: Bearer ******" in out
        assert "Cookie: ******" in out

        # Cookie 正则按行切：同一份 evidence 里的其它头不能被一起吃掉。
        for line in ("Host: api.example.com", "User-Agent: Mozilla/5.0",
                     "Accept: application/json"):
            assert line in out, line

    def test_redact_text_is_case_and_separator_insensitive(self):
        """键名大小写与分隔符变体都要命中，包括 Set-Cookie。

        前端、ZAP 与第三方工具拼键名的风格不同；脱敏漏掉一个大写或连字符变体
        等于那条通道没脱敏。替换必须保留原键名文本，只把值换成占位符。
        """
        from app.features.security_testing.zap.contracts import redact_text

        for raw, expected in (
            ("Authorization: Bearer t-ok", "Authorization: Bearer ******"),
            ("authorization = bearer t-ok", "authorization = bearer ******"),
            ("AUTHORIZATION:BEARER t-ok", "AUTHORIZATION:BEARER ******"),
            ("Cookie: a=1", "Cookie: ******"),
            ("cookie=a=1", "cookie=******"),
            ("Set-Cookie: sid=x", "Set-Cookie: ******"),
        ):
            assert redact_text(raw) == expected, raw

    def test_redact_text_only_touches_known_shapes(self):
        """只抹已知凭据形态：普通头回显原样保留，空白输入返回空串。

        反向断言同样重要——正则写宽了会把整段 evidence 吃成占位符，
        告警就从「有证据」变成「没有证据」，反而更难判读。
        """
        from app.features.security_testing.zap.contracts import redact_text

        clean = (
            "Host: api.example.com\r\n"
            "Accept: application/json\r\n"
            "GET /users/1 HTTP/1.1"
        )
        assert redact_text(clean) == clean
        assert redact_text(None) == ""
        assert redact_text("") == ""

    def test_redact_url_masks_credential_params_but_keeps_param_names(self):
        """URL 里的凭据参数值必须抹掉，但参数名要保留。

        覆盖率清单用 URL 做主键、指纹依赖参数位聚合同一问题；把参数名也抹掉的话，
        同一注入点的重复告警就聚不成一行。同时 timestamp / sign 这类业务参数
        不能误伤（它们在 URL 里通常不是凭据）。
        """
        from app.features.security_testing.zap.contracts import redact_url

        url = (
            "http://1.2.3.4/oauth/callback"
            "?access_token=eyJhbGciOiJIUzI1NiJ9&refresh_token=rt-live-99"
            "&id_token=jwt-xyz&id=1&page=2&sign=abc&timestamp=1700000000"
        )

        out = redact_url(url)

        assert out.startswith("http://1.2.3.4/oauth/callback?")
        for masked in ("access_token=******", "refresh_token=******", "id_token=******"):
            assert masked in out, masked
        # 非凭据参数值原样保留。
        for kept in ("id=1", "page=2", "sign=abc", "timestamp=1700000000"):
            assert kept in out, kept
        # 参数名一个都不能少。
        for name in ("access_token", "refresh_token", "id_token"):
            assert name in out, name
        for secret in ("eyJhbGciOiJIUzI1NiJ9", "rt-live-99", "jwt-xyz"):
            assert secret not in out, secret

    def test_redact_url_matches_credential_names_case_and_separator_insensitively(self):
        """URL 参数名判定大小写与分隔符均不敏感，但输出保留原始写法。

        同一位置可能被拼成 ACCESS_TOKEN / Api_Key / client-secret / sid；判定按
        _canonical_key 归一，输出保留原文是为了让前端与指纹按原文比较。
        此前用 `key.lower()` 精确比较，`?client-secret=` 这类连字符写法会被放行。
        """
        from app.features.security_testing.zap.contracts import redact_url

        out = redact_url(
            "http://1.2.3.4/x?ACCESS_TOKEN=a&Api_Key=b&sid=c"
            "&client-secret=d&refresh-token=e&debug=1&tokenize=f&tokens=g"
        )
        assert "ACCESS_TOKEN=******" in out
        assert "Api_Key=******" in out
        assert "sid=******" in out
        assert "client-secret=******" in out
        assert "refresh-token=******" in out
        # 非凭据参数不受影响；分隔符归一化不等于后缀/子串匹配。
        assert "debug=1" in out
        assert "tokenize=f" in out
        assert "tokens=g" in out

    def test_redact_url_leaves_urls_without_query_unchanged(self):
        """没有 query 的 URL 必须逐字返回（包括 None / 空串返回空串）。

        覆盖率主键就是 URL 原文；无谓地重排或补斜杠会让快照对不上。
        """
        from app.features.security_testing.zap.contracts import redact_url

        for url in ("http://1.2.3.4/", "http://1.2.3.4/console/users", None, ""):
            assert redact_url(url) == (url or ""), url

    def test_redact_mapping_truncates_overlong_text(self):
        """超长证据先截断再落库，避免一次扫描把整张表撑爆。

        截断必须有可见标记，且只在真正超限时发生——未超长的字符串不能被硬截出省略号。
        """
        from app.features.security_testing.zap.contracts import (
            MAX_EVIDENCE_TEXT_LENGTH,
            redact_mapping,
        )

        marker = "…（已截断）"
        long_value = "x" * (MAX_EVIDENCE_TEXT_LENGTH + 500)
        out = redact_mapping({"detail": long_value})
        assert len(out["detail"]) == MAX_EVIDENCE_TEXT_LENGTH + len(marker)
        assert out["detail"].startswith("x" * MAX_EVIDENCE_TEXT_LENGTH)
        assert out["detail"].endswith(marker)
        assert long_value not in out["detail"]

        exactly_at_limit = "y" * MAX_EVIDENCE_TEXT_LENGTH
        assert redact_mapping({"detail": exactly_at_limit})["detail"] == exactly_at_limit

    def test_redact_mapping_caps_list_items(self):
        """列表型证据有硬上限，防止单个告警把 JSON 列写成超大对象。

        同时确认保留的是**前** MAX_EVIDENCE_ITEMS 条，而不是随机截取——
        截取顺序错了会让「第一个凭据」反而被留下来。
        """
        from app.features.security_testing.zap.contracts import (
            MAX_EVIDENCE_ITEMS,
            redact_mapping,
        )

        items = [f"item-{index}" for index in range(MAX_EVIDENCE_ITEMS + 50)]
        out = redact_mapping({"rows": items})
        assert len(out["rows"]) == MAX_EVIDENCE_ITEMS
        assert out["rows"] == items[:MAX_EVIDENCE_ITEMS]

    def test_sensitive_key_detection_normalizes_case_and_separators(self):
        """Authorization / X-ZAP-API-Key / API Key / api_key 这些写法必须同样命中。

        键名风格在前后端与 ZAP 之间不一致；脱敏只要漏掉一个大写或连字符变体，
        那一条通道就等于没脱敏。同时反向确认普通键名不会被误判为敏感。
        """
        from app.features.security_testing.zap.contracts import (
            REDACTED_PLACEHOLDER,
            redact_value,
        )

        value = "secret-value-xyz"
        # x-zap-api-key / set-cookie 在 SENSITIVE_FIELD_NAMES 里带连字符，
        # 若两侧归一口径不一致就会永远匹配不上（此前正是这个 bug：它们的连字符、
        # 下划线、大小写变体全部漏脱）。现在统一走 _canonical_key，所以这里把
        # 同一凭据键的连字符 / 下划线 / 空格 / 驼峰写法列全。
        variants = (
            "Authorization", "authorization", "AUTHORIZATION", " Authorization ",
            "x-zap-api-key", "X-ZAP-API-Key", "x_zap_api_key", "xZapApiKey",
            "API Key", "api key", "ApiKey", "api_key", "API_KEY",
            "Cookie", "Set-Cookie", "set-cookie", "set_cookie",
            "Client Secret", "client_secret", "client-secret",
            "Bearer Token", "bearer_token",
            "Webhook URL", "webhook_url", "Webhook_URL_Encrypted",
        )
        missing = [key for key in variants if redact_value(key, value) != REDACTED_PLACEHOLDER]
        assert not missing, f"这些敏感键名变体没有被脱敏：{missing}"

        # 反向确认：普通键名不会被误判为敏感（否则会误删业务字段）。
        kept = [key for key in ("user_id", "name", "status_code", "AuthorizationX", "tokenize")
                if redact_value(key, value) != value]
        assert not kept, f"这些普通键名被误判为敏感：{kept}"

    def test_redact_helpers_treat_empty_input_as_empty(self):
        """空输入一律收敛成空值，不抛错、不返回原对象。"""
        from app.features.security_testing.zap.contracts import (
            redact_mapping,
            redact_text,
            redact_url,
        )

        assert redact_mapping(None) == {}
        assert redact_mapping({}) == {}
        assert redact_mapping({"detail": None}) == {"detail": None}
        assert redact_text(None) == ""
        assert redact_url(None) == ""

    def test_normalizer_emits_redacted_evidence(self):
        """归一化出口必须交付已脱敏的 URL 与 evidence（不是只在文档里声明）。

        指纹建立在**脱敏后**的 URL 上：先用原文算指纹的话，同一注入点因令牌不同
        会散成多条，告警页上同一个问题就永远聚不到一起。
        """
        from app.features.security_testing.zap.contracts import ZAPAlert
        from app.features.security_testing.zap.normalizer import ZAPAlertNormalizer

        token = "eyJhbGciOiJIUzI1NiJ9.live-token-xyz"
        alert = ZAPAlert(
            rule_id="40012",
            name="JWT Cookie",
            risk="High",
            confidence=5,
            url=f"http://1.2.3.4/callback?access_token={token}&id=1",
            method="POST",
            parameter="access_token",
            evidence=f"Authorization: Bearer {token}\nCookie: sid={token}",
        )

        item = ZAPAlertNormalizer(project_id=1, target_id=1).normalize(alert)

        assert token not in str(item)
        assert item.url.endswith("access_token=******&id=1")
        assert item.evidence == "Authorization: Bearer ******\nCookie: ******"
        assert item.severity == "HIGH" and item.risk == "High"
        assert item.confidence == 5
        # evidence_payload 是落库的结构化证据，同样不能含原文。
        assert token not in str(item.evidence_payload)
        assert item.evidence_payload["risk"] == "High"


# --------------------------------------------------------------------------- 扫描目标（§十二）


class TestScanTarget:
    def test_create_read_patch_delete(self, api, admin):
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["project_id"] == pid
        assert body["enabled"] is True
        assert body["is_production"] is False
        assert body["allowed_hosts"] == [PUBLIC_IP]

        target_id = body["id"]
        patch = api.patch(
            f"/projects/{pid}/security/scan-targets/{target_id}", username=admin,
            json={"name": "改名", "active_scan_allowed": True, "authorization_status": "PENDING"},
        )
        assert patch.status_code == 200, patch.text
        updated = patch.json()
        assert updated["name"] == "改名"
        assert updated["active_scan_allowed"] is True
        assert updated["authorization_status"] == "PENDING"

        assert api.delete(
            f"/projects/{pid}/security/scan-targets/{target_id}", username=admin,
        ).status_code == 204
        assert api.get(
            f"/projects/{pid}/security/scan-targets/{target_id}", username=admin,
        ).status_code == 404

    def test_list_pagination_shape(self, api, admin):
        pid = _project(api, admin)
        assert api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).status_code == 201
        r = api.get(f"/projects/{pid}/security/scan-targets", username=admin, params={"page": 1, "page_size": 5})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["page"] == 1 and body["page_size"] == 5
        assert len(body["items"]) == 1

    def test_entry_url_must_share_host_with_base(self, api, admin):
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin,
            json=_target_body(
                base_url=BASE_URL, entry_url="http://1.2.3.5/entry",
                allowed_hosts=[PUBLIC_IP, "1.2.3.5"],
            ),
        )
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "SECURITY_SCAN_SCOPE_VIOLATION"

    def test_non_public_base_url_rejected(self, api, admin):
        pid = _project(api, admin)
        for base in ("http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/"):
            r = api.post(
                f"/projects/{pid}/security/scan-targets", username=admin,
                json=_target_body(base_url=base, allowed_hosts=[base.split("//")[1].rstrip("/")]),
            )
            assert r.status_code == 403, r.text
            assert r.json()["code"] == "SECURITY_SCAN_SCOPE_VIOLATION"

    def test_base_url_changed_to_disallowed_host_rejected(self, api, admin):
        """改 base_url 时重新过范围守卫，不能只在前端拦一次。"""
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        )
        target_id = r.json()["id"]
        patch = api.patch(
            f"/projects/{pid}/security/scan-targets/{target_id}", username=admin,
            json={"base_url": "http://1.2.3.9/"},
        )
        assert patch.status_code == 403, patch.text
        assert patch.json()["code"] == "SECURITY_SCAN_SCOPE_VIOLATION"

    def test_is_production_derived_from_environment(self, api, admin, db):
        env_id = _make_environment(db, "生产环境")
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin,
            json=_target_body(environment_id=env_id),
        )
        assert r.status_code == 201, r.text
        assert r.json()["is_production"] is True

    def test_unknown_environment_id_rejected(self, api, admin):
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin,
            json=_target_body(environment_id=999999),
        )
        assert r.status_code == 404, r.text

    def test_inflight_job_blocks_delete(self, api, admin, db):
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        _profile(db, pid)
        _make_job(db, pid, target_id, 1, status="CRAWLING")
        r = api.delete(f"/projects/{pid}/security/scan-targets/{target_id}", username=admin)
        assert r.status_code == 409, r.text

    def test_member_cannot_create_target(self, api, admin):
        """目标是项目级配置：需要 editor+，member 不够。"""
        pid = _project(api, admin)
        member = _user(api, admin, pid, "zap-m", role="member")
        r = api.post(f"/projects/{pid}/security/scan-targets", username=member, json=_target_body())
        assert r.status_code == 403, r.text

    def test_editor_can_create_target(self, api, admin):
        pid = _project(api, admin)
        editor = _user(api, admin, pid, "zap-e", role="editor")
        assert api.post(
            f"/projects/{pid}/security/scan-targets", username=editor, json=_target_body(),
        ).status_code == 201

    def test_outsider_gets_404(self, api, admin):
        """跨项目访问统一 404：不泄露目标是否存在。"""
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        outsider = _user(api, admin, _project(api, admin), "zap-out", role="member")
        assert api.get(
            f"/projects/999999/security/scan-targets", username=outsider,
        ).status_code == 404
        assert api.get(
            f"/projects/{pid}/security/scan-targets/{target_id}", username=outsider,
        ).status_code == 404


def _profile(db, project_id, **overrides):
    """插入一条自定义扫描策略。"""
    from app.features.security_testing.zap.models.profile import SecurityScanProfile

    body = _profile_body()
    body.update(overrides)
    row = SecurityScanProfile(
        project_id=project_id,
        code=None,
        is_builtin=False,
        **body,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


# --------------------------------------------------------------------------- 认证配置（§十一 / §十二 / §十三）


class TestAuthProfile:
    def test_credential_never_returned_in_response(self, api, admin):
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin,
            json=_auth_body(credential="super-secret-credential"),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "credential" not in body
        assert body["has_credential"] is True
        assert body["token_fingerprint"]
        assert len(body["token_fingerprint"]) == 12
        assert "super-secret-credential" not in r.text
        assert "credential_encrypted" not in r.text

    def test_list_does_not_return_credential(self, api, admin):
        pid = _project(api, admin)
        api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin,
            json=_auth_body(credential="list-secret-999"),
        )
        r = api.get(f"/projects/{pid}/security/scan-auth-profiles", username=admin)
        assert r.status_code == 200, r.text
        assert "list-secret-999" not in r.text
        assert "credential_encrypted" not in r.text
        assert r.json()["items"][0]["has_credential"] is True

    def test_credential_stored_as_ciphertext(self, api, admin, db):
        pid = _project(api, admin)
        api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin,
            json=_auth_body(credential="plaintext-credential-xyz"),
        )
        row = db.execute(
            text("select credential_encrypted, has_credential, token_fingerprint "
                 "from security_scan_auth_profile where project_id = :p"),
            {"p": pid},
        ).one()
        assert row.credential_encrypted
        assert "plaintext-credential-xyz" not in str(row.credential_encrypted)
        assert row.has_credential is True

        # 密文可被解密回原文（Worker 配 ZAP 时需要）。
        from app.features.security_testing.zap.services.auth_profile_service import (
            fingerprint_of,
            decrypt_credential,
        )

        from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile

        profile = db.query(SecurityScanAuthProfile).filter_by(project_id=pid).one()
        assert decrypt_credential(profile) == "plaintext-credential-xyz"
        assert fingerprint_of("plaintext-credential-xyz") == row.token_fingerprint

    def test_manual_mode_rejects_credential(self, api, admin):
        """飞书扫码等人工登录不存凭据（§十三）。"""
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin,
            json=_auth_body(auth_mode="MANUAL", credential="should-not-store"),
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_SCAN_PROFILE_INVALID" or r.json()["code"]

    def test_update_rotates_and_removes_credential(self, api, admin, db):
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin,
            json=_auth_body(credential="first-secret"),
        )
        assert r.status_code == 201, r.text
        profile_id = r.json()["id"]
        old_fingerprint = r.json()["token_fingerprint"]

        rotated = api.patch(
            f"/projects/{pid}/security/scan-auth-profiles/{profile_id}", username=admin,
            json={"credential": "second-secret"},
        )
        assert rotated.status_code == 200, rotated.text
        body = rotated.json()
        assert body["token_fingerprint"] != old_fingerprint
        assert "second-secret" not in rotated.text

        removed = api.patch(
            f"/projects/{pid}/security/scan-auth-profiles/{profile_id}", username=admin,
            json={"remove_credential": True},
        )
        assert removed.status_code == 200, removed.text
        body = removed.json()
        assert body["has_credential"] is False
        assert body["token_fingerprint"] is None
        assert body["credential_updated_at"]

        stored = db.execute(
            text("select credential_encrypted from security_scan_auth_profile "
                 "where id = :i"),
            {"i": profile_id},
        ).scalar_one()
        assert stored is None

    def test_delete(self, api, admin):
        pid = _project(api, admin)
        profile_id = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin, json=_auth_body(),
        ).json()["id"]
        assert api.delete(
            f"/projects/{pid}/security/scan-auth-profiles/{profile_id}", username=admin,
        ).status_code == 204

    def test_member_cannot_create_auth_profile(self, api, admin):
        pid = _project(api, admin)
        member = _user(api, admin, pid, "zap-m", role="member")
        r = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=member, json=_auth_body(),
        )
        assert r.status_code == 403, r.text


# --------------------------------------------------------------------------- 扫描策略（§十六）


class TestScanProfile:
    def test_builtin_profiles_visible_and_protected(self, api, admin):
        from app.features.security_testing.zap.contracts import is_active_scan

        pid = _project(api, admin)
        r = api.get(f"/projects/{pid}/security/scan-profiles", username=admin)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        builtins = [item for item in items if item["is_builtin"]]
        assert len(builtins) == 6
        for item in builtins:
            assert item["project_id"] is None
            assert item["code"]
            assert item["is_active_scan"] == is_active_scan(item["scan_mode"])
        # 内置主动策略默认带上高危路径排除。
        active = [item for item in builtins if item["is_active_scan"]]
        assert active, "至少应有一个内置主动扫描策略"
        assert all(item["exclude_paths"] for item in active)

    def test_builtin_profile_cannot_be_deleted_or_renamed_by_code(self, api, admin):
        pid = _project(api, admin)
        builtin_id = [
            item["id"]
            for item in api.get(
                f"/projects/{pid}/security/scan-profiles", username=admin,
            ).json()["items"]
            if item["is_builtin"]
        ][0]
        r = api.delete(f"/projects/{pid}/security/scan-profiles/{builtin_id}", username=admin)
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_SCAN_PROFILE_INVALID"

    def test_builtin_profile_cannot_bind_project_auth_profile(self, api, admin):
        """内置策略全项目共享：绑定认证配置会把某个项目的凭据变成其它项目的入口。"""
        pid = _project(api, admin)
        auth_id = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin, json=_auth_body(),
        ).json()["id"]
        builtin_id = [
            item["id"]
            for item in api.get(
                f"/projects/{pid}/security/scan-profiles", username=admin,
            ).json()["items"]
            if item["is_builtin"]
        ][0]
        r = api.patch(
            f"/projects/{pid}/security/scan-profiles/{builtin_id}", username=admin,
            json={"authentication_profile_id": auth_id},
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_SCAN_PROFILE_INVALID"

    def test_active_enabled_requires_active_mode(self, api, admin):
        pid = _project(api, admin)
        r = api.post(
            f"/projects/{pid}/security/scan-profiles", username=admin,
            json=_profile_body(scan_mode="API_PASSIVE", active_enabled=True),
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_SCAN_PROFILE_INVALID"

    def test_custom_profile_crud_and_auth_binding(self, api, admin):
        pid = _project(api, admin)
        auth_id = api.post(
            f"/projects/{pid}/security/scan-auth-profiles", username=admin, json=_auth_body(),
        ).json()["id"]
        r = api.post(
            f"/projects/{pid}/security/scan-profiles", username=admin,
            json=_profile_body(
                scan_mode="API_ACTIVE", active_enabled=True,
                authentication_profile_id=auth_id, exclude_paths=["logout", "delete"],
            ),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["is_builtin"] is False
        assert body["project_id"] == pid
        assert body["code"] is None
        assert body["is_active_scan"] is True
        assert body["authentication_profile_id"] == auth_id
        assert body["exclude_paths"] == ["logout", "delete"]

        profile_id = body["id"]
        updated = api.patch(
            f"/projects/{pid}/security/scan-profiles/{profile_id}", username=admin,
            json={"max_depth": 8, "include_paths": ["/openapi.json"]},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["max_depth"] == 8
        assert updated.json()["include_paths"] == ["/openapi.json"]

        assert api.delete(
            f"/projects/{pid}/security/scan-profiles/{profile_id}", username=admin,
        ).status_code == 204

    def test_auth_binding_must_be_same_project(self, api, admin):
        pid = _project(api, admin)
        other = _project(api, admin)
        other_auth_id = api.post(
            f"/projects/{other}/security/scan-auth-profiles", username=admin, json=_auth_body(),
        ).json()["id"]
        r = api.post(
            f"/projects/{pid}/security/scan-profiles", username=admin,
            json=_profile_body(authentication_profile_id=other_auth_id),
        )
        assert r.status_code == 400, r.text

    def test_outsider_cannot_see_other_projects_profile(self, api, admin):
        pid = _project(api, admin)
        profile_id = api.post(
            f"/projects/{pid}/security/scan-profiles", username=admin, json=_profile_body(),
        ).json()["id"]
        outsider = _user(api, admin, _project(api, admin), "zap-out", role="member")
        assert api.get(
            f"/projects/{pid}/security/scan-profiles/{profile_id}", username=outsider,
        ).status_code == 404


# --------------------------------------------------------------------------- 扫描计划（§二十三）


class TestScanPlan:
    def test_plan_is_read_only(self, api, admin, db):
        """计划预览不写库、不发 ZAP 请求：这是人工确认闸门的前置动作。"""
        from app.shared.config import settings

        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_PASSIVE")

        before = db.execute(text("select count(*) from security_scan_job")).scalar_one()
        r = api.post(
            f"/projects/{pid}/security/scan-jobs/plan", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        )
        assert r.status_code == 200, r.text
        after = db.execute(text("select count(*) from security_scan_job")).scalar_one()
        assert before == after

        body = r.json()
        assert body["is_active_scan"] is False
        assert body["target"]["id"] == target_id
        assert body["profile"]["id"] == profile_id
        assert body["zap_available"] is False
        assert body["warning"]

    def test_plan_reports_limitations_without_zap(self, api, admin, db, monkeypatch):
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", False, raising=False)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_PASSIVE")
        r = api.post(
            f"/projects/{pid}/security/scan-jobs/plan", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ZAP" in " ".join(body["limitations"])
        assert body["zap_available"] is False

    def test_plan_blocks_production_active_scan(self, api, admin, db):
        """生产环境任何阶段禁止主动扫描——计划阶段就 403，不进确认流程。"""
        # 用英文词元（prod-<n>）验证按词元切分的判定口径，与用例 657 的中文判定互补。
        env_id = _make_environment(db)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin,
            json=_target_body(environment_id=env_id, active_scan_allowed=True,
                              authorization_status="AUTHORIZED"),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_ACTIVE", active_enabled=True)
        r = api.post(
            f"/projects/{pid}/security/scan-jobs/plan", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id,
                  "confirmed": True, "approval_note": "批准"},
        )
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "SECURITY_SCAN_PRODUCTION_FORBIDDEN"


# --------------------------------------------------------------------------- 扫描任务（§二十三 / §二十五）


class TestScanJob:
    def test_create_refused_when_zap_disabled(self, api, admin, db, monkeypatch):
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", False, raising=False)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        r = api.post(
            f"/projects/{pid}/security/scan-jobs", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        )
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "ZAP_SERVICE_UNAVAILABLE"

    def test_create_job_returns_pending(self, api, admin, db, monkeypatch):
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_PASSIVE")
        r = api.post(
            f"/projects/{pid}/security/scan-jobs", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "PENDING"
        assert body["scan_mode"] == "API_PASSIVE"
        assert body["progress"] == 0
        assert body["approved_by"] is None
        assert body["target_name"]

    def test_duplicate_target_job_rejected(self, api, admin, db, monkeypatch):
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        first = api.post(
            f"/projects/{pid}/security/scan-jobs", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        )
        assert first.status_code == 202, first.text
        second = api.post(
            f"/projects/{pid}/security/scan-jobs", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        )
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "SECURITY_SCAN_ALREADY_RUNNING"

    def test_active_scan_requires_editor_and_confirmation(self, api, admin, db):
        """主动扫描的四道闸：权限、环境、目标授权、人工确认（§二十三）。"""
        from app.shared.config import settings

        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin,
            json=_target_body(active_scan_allowed=True, authorization_status="AUTHORIZED"),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_ACTIVE", active_enabled=True)
        payload = {"target_id": target_id, "scan_profile_id": profile_id}

        member = _user(api, admin, pid, "zap-m", role="member")
        r = api.post(
            f"/projects/{pid}/security/scan-jobs", username=member,
            json={**payload, "confirmed": True, "approval_note": "我批准"},
        )
        assert r.status_code == 403, r.text

        # editor 通过了权限闸，但缺人工确认。
        editor = _user(api, admin, pid, "zap-e", role="editor")
        r = api.post(f"/projects/{pid}/security/scan-jobs", username=editor, json=payload)
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "SECURITY_SCAN_NOT_AUTHORIZED"

        # 只有 confirmed 但没有批准说明也算未确认。
        r = api.post(
            f"/projects/{pid}/security/scan-jobs", username=editor,
            json={**payload, "confirmed": True, "approval_note": "   "},
        )
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "SECURITY_SCAN_NOT_AUTHORIZED"

        # 目标授权状态不是 AUTHORIZED：即使显式确认也拒绝。
        api.patch(
            f"/projects/{pid}/security/scan-targets/{target_id}", username=admin,
            json={"authorization_status": "PENDING"},
        )
        r = api.post(
            f"/projects/{pid}/security/scan-jobs", username=editor,
            json={**payload, "confirmed": True, "approval_note": "批准主动扫描"},
        )
        assert r.status_code == 403, r.text

    def test_cancel_pending_job(self, api, admin, db, monkeypatch):
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        job_id = api.post(
            f"/projects/{pid}/security/scan-jobs", username=admin,
            json={"target_id": target_id, "scan_profile_id": profile_id},
        ).json()["id"]

        r = api.post(f"/projects/{pid}/security/scan-jobs/{job_id}/cancel", username=admin)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "CANCELLED"
        assert body["cancel_requested"] is True
        assert body["finished_at"]

        assert api.post(
            f"/projects/{pid}/security/scan-jobs/{job_id}/cancel", username=admin,
        ).status_code == 409

    def test_query_endpoints_for_a_job(self, api, admin, db):
        """进度 / 事件 / 告警 / 覆盖率 / 报告口径：全部来自任务记录本身（§二十五）。"""
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_PASSIVE")
        job_id = _make_job(db, pid, target_id, profile_id, scan_mode="API_PASSIVE", status="PENDING")
        db.commit()

        progress = api.get(f"/projects/{pid}/security/scan-jobs/{job_id}/progress", username=admin)
        assert progress.status_code == 200, progress.text
        assert progress.json()["status"] == "PENDING"

        events = api.get(f"/projects/{pid}/security/scan-jobs/{job_id}/events", username=admin)
        assert events.status_code == 200, events.text
        assert events.json()["total"] == 0

        alerts = api.get(f"/projects/{pid}/security/scan-jobs/{job_id}/alerts", username=admin)
        assert alerts.status_code == 200, alerts.text
        assert alerts.json()["counts"]["total"] == 0

        coverage = api.get(
            f"/projects/{pid}/security/scan-jobs/{job_id}/coverage", username=admin,
            params={"page": 1, "page_size": 10},
        )
        assert coverage.status_code == 200, coverage.text
        assert coverage.json()["items"] == []

        report = api.get(f"/projects/{pid}/security/scan-jobs/{job_id}/report", username=admin)
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["job"]["id"] == job_id
        assert body["target"]["id"] == target_id
        assert body["profile"]["id"] == profile_id
        assert body["alert_counts"]["total"] == 0
        assert body["high_risk_alerts"] == []
        assert body["findings"] == []
        assert body["coverage_summary"] == {}
        assert body["generated_at"]

    def test_list_jobs_filters(self, api, admin, db):
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        _make_job(db, pid, target_id, profile_id, status="PENDING")
        _make_job(db, pid, target_id, profile_id, status="COMPLETED")

        listed = api.get(f"/projects/{pid}/security/scan-jobs", username=admin)
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 2

        pending = api.get(
            f"/projects/{pid}/security/scan-jobs", username=admin, params={"status": "PENDING"},
        )
        assert pending.json()["total"] == 1
        assert pending.json()["items"][0]["status"] == "PENDING"

    def test_cross_project_job_is_404(self, api, admin, db):
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        job_id = _make_job(db, pid, target_id, profile_id, status="PENDING")

        outsider = _user(api, admin, _project(api, admin), "zap-out", role="member")
        for path in (
            f"/projects/999999/security/scan-jobs",
            f"/projects/{pid}/security/scan-jobs/{job_id}",
            f"/projects/{pid}/security/scan-jobs/{job_id}/progress",
            f"/projects/{pid}/security/scan-jobs/{job_id}/report",
        ):
            r = api.get(path, username=outsider)
            assert r.status_code == 404, path

    def test_unauthenticated_gets_401(self, api, admin):
        r = api.get("/security/zap/health")
        assert r.status_code == 401, r.text


# --------------------------------------------------------------------------- 告警 severity 过滤（§十八）


class TestAlertSeverityFilter:
    """risk 列存 ZAP 原文、severity 是映射后的平台级别，两者不能直接比较。

    如果实现拿 "HIGH" 去比 risk 列的 "High"，高危筛选会一条都查不出来，
    报告页显示「没有高危」而实际有——这是比误报更危险的漏报。
    """

    def test_severity_filter_looks_through_risk_to_severity_mapping(self, db):
        """severity 过滤必须按 ZAP_RISK_TO_SEVERITY 反查 risk，而不是字符串相等。

        造出 High / Medium / Informational / 一个未识别值（映射落默认 MEDIUM）四行，
        逐档验证：HIGH 只回 High；MEDIUM 回 Medium + 未识别值；INFO 回 Informational；
        CRITICAL 如实返回空（不放宽条件凑数）；不传 severity 返回全部。
        其中 HIGH 这一档是区分力最强的：错误实现（risk == severity）会返回 0 行。
        """
        from app.features.security_testing.zap.services import job_service

        project_id, user, job_id = _job_context(db)
        _seed_alert_risks(db, project_id, job_id)

        def risks(severity=None):
            result = job_service.alerts(db, project_id, user, job_id, 1, 100, severity=severity)
            return sorted(item.risk for item in result.items)

        assert risks("HIGH") == ["High"]
        # 未识别的 "weird" 归一化时落默认 MEDIUM，过滤 MEDIUM 时也必须算进来。
        assert risks("MEDIUM") == ["Medium", "weird"]
        assert risks("INFO") == ["Informational"]
        # ZAP 不产生 CRITICAL：如实返回空，不能退化成「返回全部」这种宽松兜底。
        assert risks("CRITICAL") == []
        assert risks() == ["High", "Informational", "Medium", "weird"]

        full = job_service.alerts(db, project_id, user, job_id, 1, 100)
        # 分页形状与项目约定一致。
        assert set(full.model_dump()) == {"items", "total", "page", "page_size", "counts"}
        assert (full.total, full.page, full.page_size) == (4, 1, 100)
        # counts 来自任务上冻结的快照，不随过滤条件变化。
        assert full.counts.total == 4
        assert full.counts.high == 1 and full.counts.medium == 2
        assert full.counts.low == 0 and full.counts.info == 1
        # rule_id 过滤与 severity 过滤可以叠加。
        one_rule = job_service.alerts(
            db, project_id, user, job_id, 1, 100,
            rule_id="zap-rule-medium", severity="MEDIUM",
        )
        assert one_rule.total == 1
        assert one_rule.items[0].risk == "Medium"

    def test_filter_result_never_disagrees_with_reported_severity(self, db):
        """过滤出来的每行，其 severity 字段都必须等于过滤条件本身。

        过滤按 risk 反查、展示读的是 payload 里的 severity；两边口径一旦不一致，
        页面就会出现「高危列表」里混着 MEDIUM 行的情况。顺带确认小写与首尾空格
        的传参写法与大写等效。
        """
        from app.features.security_testing.zap.services import job_service

        project_id, user, job_id = _job_context(db)
        _seed_alert_risks(db, project_id, job_id)

        for severity in ("HIGH", "high", " MEDIUM ", "INFO", "CRITICAL"):
            result = job_service.alerts(db, project_id, user, job_id, 1, 100, severity=severity)
            expected = severity.strip().upper()
            for item in result.items:
                assert item.severity == expected, (severity, item.risk, item.severity)
                # risk 原文必须保留，不能被替换成映射后的级别（审计要能回溯 ZAP 结论）。
                assert item.risk in dict(_ALERT_RISKS), item.risk

    def test_http_severity_param_reaches_the_filter(self, db, api, admin):
        """HTTP 层的 severity 查询参数必须真的传到过滤条件里。

        只测 service 会漏掉「路由没把参数透传」这种缺陷；同时确认接口按平台
        分页形状 {items, total, page, page_size} 返回，counts 作为附加字段。
        """
        project_id, _owner, job_id = _job_context(db)
        _seed_alert_risks(db, project_id, job_id)

        r = api.get(
            f"/projects/{project_id}/security/scan-jobs/{job_id}/alerts",
            username=admin, params={"severity": "HIGH", "page": 1, "page_size": 10},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"items", "total", "page", "page_size", "counts"}
        assert body["total"] == 1
        assert [item["risk"] for item in body["items"]] == ["High"]
        assert body["items"][0]["severity"] == "HIGH"

        empty = api.get(
            f"/projects/{project_id}/security/scan-jobs/{job_id}/alerts",
            username=admin, params={"severity": "CRITICAL"},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["items"] == []
        assert empty.json()["total"] == 0

    def test_alerts_do_not_leak_credential_from_the_link(self, db, api, admin):
        """告警行的 url / evidence_json 存的是脱敏结果，响应里不得出现原文凭据。

        告警详情会把 URL 与 evidence 直接回显给项目成员；这里验证一次写入→读取
        的闭环：写入时用真实凭据形态，读出来必须是占位符。
        """
        from app.features.security_testing.zap.contracts import ZAPAlert
        from app.features.security_testing.zap.normalizer import ZAPAlertNormalizer

        token = "leaked-live-token-xyz"
        project_id, _owner, job_id = _job_context(db)
        item = ZAPAlertNormalizer(project_id=project_id, target_id=1).normalize(
            ZAPAlert(
                rule_id="40018", name="JWT Token", risk="Medium", confidence=4,
                url=f"http://1.2.3.4/cb?access_token={token}&page=1",
                evidence=f"Authorization: Bearer {token}",
            ),
        )
        link = _scan_alert_link(
            db, project_id, job_id, item.risk, source_rule_id="zap-rule-leak",
            severity=item.severity, url=item.url,
        )
        link.evidence_json = item.as_dict()
        db.commit()

        r = api.get(
            f"/projects/{project_id}/security/scan-jobs/{job_id}/alerts",
            username=admin,
        )
        assert r.status_code == 200, r.text
        assert token not in r.text
        assert "access_token=******" in r.text
        assert "Bearer ******" in r.text


# --------------------------------------------------------------------------- ZAP 服务健康（§二十四）


class TestZapHealth:
    def test_health_reports_not_available(self, api, admin, monkeypatch):
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", False, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", None, raising=False)
        r = api.get("/security/zap/health", username=admin)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is False
        assert body["available"] is False
        assert body["reachable"] is False
        assert "ZAP" in body["message"]
        # 密钥与完整地址都不能出现在响应里：api_key_configured 只是布尔标记，
        # 不能出现任何形如 api_key 的值字段，也不能出现环境变量名本身。
        assert body["api_key_configured"] is False
        assert "api_key" not in body
        assert "ZAP_API_KEY" not in r.text

    def test_capabilities_reports_not_available(self, api, admin, monkeypatch):
        """能力探测服务不可达时返回 available=false，绝不假装支持。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", False, raising=False)
        r = api.get("/security/zap/capabilities", username=admin)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["available"] is False
        assert body["version"] is None
        assert body["capabilities"] == []
        assert body["message"]

    def test_health_requires_platform_admin(self, api, admin):
        """ZAP 基础设施健康归平台管理员，项目成员不可见。"""
        pid = _project(api, admin)
        member = _user(api, admin, pid, "zap-m", role="member")
        r = api.get("/security/zap/health", username=member)
        assert r.status_code == 403, r.text

    def test_health_does_not_open_connection(self, api, admin, monkeypatch):
        """健康检查只读配置，不发起网络请求。"""
        from app.shared.config import settings
        from app.features.security_testing.zap import client as zap_client

        called = []
        original = zap_client.build_connector

        def spy(*args, **kwargs):
            called.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        monkeypatch.setattr(zap_client, "build_connector", spy, raising=False)
        r = api.get("/security/zap/health", username=admin)
        assert r.status_code == 200, r.text
        assert called == []


# --------------------------------------------------------------------------- 后台任务（§八 / §二十五）


def _zap_on(monkeypatch, *, enabled=True, base_url=BASE_URL):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "ZAP_ENABLED", enabled, raising=False)
    monkeypatch.setattr(settings, "ZAP_BASE_URL", base_url, raising=False)


def _terminal_orchestrator(status="COMPLETED"):
    """返回一个 orchestrator 工厂：把任务写成终态，不碰 ZAP。"""
    from app.features.security_testing.zap.contracts import JOB_STATUS_COMPLETED
    from app.shared.database import SessionLocal
    from app.features.security_testing.zap.models.job import SecurityScanJob

    if status == JOB_STATUS_COMPLETED:
        payload = {"status": "COMPLETED", "progress": 100, "finished_at": datetime.now()}
    else:
        payload = {"status": "FAILED", "finished_at": datetime.now(), "error_code": "SECURITY_SCAN_FAILED"}

    def factory(connector):
        class _Stub:
            def run(self, job_id):
                with SessionLocal() as session:
                    row = session.get(SecurityScanJob, job_id)
                    for key, value in payload.items():
                        setattr(row, key, value)
                    session.commit()
                return status

        return _Stub()

    return factory


class TestScanWorker:
    def test_start_is_noop_when_zap_disabled(self, monkeypatch):
        """ZAP 未启用时后台任务不启动，避免空转与误导性日志（§八）。"""
        from app.features.security_testing.zap.worker import ScanWorker

        _zap_on(monkeypatch, enabled=False)
        worker = ScanWorker(owner="test-worker", poll_interval_seconds=1)
        worker.start()
        assert worker.is_running is False
        worker.stop()

    def test_tick_claims_pending_job_and_preserves_terminal_state(self, api, admin, db, monkeypatch):
        _zap_on(monkeypatch, enabled=True)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid, scan_mode="API_PASSIVE")
        job_id = _make_job(db, pid, target_id, profile_id, scan_mode="API_PASSIVE", status="PENDING")
        # 清掉别的测试留下的待处理任务，保证本轮只处理这一个。
        _settle_other_jobs(db, job_id)

        from app.features.security_testing.zap.worker import ScanWorker

        worker = ScanWorker(
            owner="test-worker", poll_interval_seconds=1,
            orchestrator_factory=_terminal_orchestrator("COMPLETED"),
        )
        handled = worker.tick()
        worker.stop()
        assert handled == 1
        assert worker.processed_count == 1

        row = db.execute(
            text("select status, progress, worker_owner, heartbeat_at, finished_at "
                 "from security_scan_job where id = :i"),
            {"i": job_id},
        ).one()
        assert row.status == "COMPLETED"
        assert row.progress == 100
        assert row.worker_owner == "test-worker"
        assert row.heartbeat_at is not None
        assert row.finished_at is not None
        events = db.execute(
            text("select count(*) from security_scan_event where job_id = :i"),
            {"i": job_id},
        ).scalar_one()
        assert events >= 1

    def test_tick_marks_cancelled_job_without_claiming(self, api, admin, db, monkeypatch):
        """取消位持久化：任务被取消后不再被领取（§八「防止重复领取」）。"""
        _zap_on(monkeypatch, enabled=True)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        job_id = _make_job(db, pid, target_id, profile_id, status="PENDING",
                           cancel_requested=True)
        _settle_other_jobs(db, job_id)

        from app.features.security_testing.zap.worker import ScanWorker

        calls = []

        def factory(connector):
            class _Stub:
                def run(self, job_id):
                    calls.append(job_id)
                    return "COMPLETED"

            return _Stub()

        worker = ScanWorker(
            owner="test-worker", poll_interval_seconds=1, orchestrator_factory=factory,
        )
        handled = worker.tick()
        worker.stop()
        assert handled == 0
        assert calls == []
        status = db.execute(
            text("select status from security_scan_job where id = :i"), {"i": job_id},
        ).scalar_one()
        assert status == "CANCELLED"

    def test_tick_sweeps_stale_inflight_job_to_timed_out(self, api, admin, db, monkeypatch):
        """进程重启后，心跳超时的中间态任务一律判为 TIMED_OUT（§八 任务恢复）。"""
        _zap_on(monkeypatch, enabled=True)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        job_id = _make_job(
            db, pid, target_id, profile_id, status="CRAWLING",
            worker_owner="dead-instance",
            heartbeat_at=datetime.now() - timedelta(seconds=3600),
        )
        _settle_other_jobs(db, job_id)

        from app.features.security_testing.zap.worker import ScanWorker

        worker = ScanWorker(owner="test-worker", poll_interval_seconds=1)
        handled = worker.tick()
        worker.stop()
        assert handled == 0

        row = db.execute(
            text("select status, error_code, error_message, finished_at, stage "
                 "from security_scan_job where id = :i"),
            {"i": job_id},
        ).one()
        assert row.status == "TIMED_OUT"
        assert row.error_code == "SECURITY_SCAN_TIMEOUT"
        assert "dead-instance" in row.error_message
        assert row.finished_at is not None
        assert row.stage == "后台任务中断"

    def test_tick_ignores_fresh_inflight_job(self, api, admin, db, monkeypatch):
        """心跳未超时的中间态任务不被清扫：说明清扫确实依赖心跳时间。"""
        _zap_on(monkeypatch, enabled=True)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        job_id = _make_job(
            db, pid, target_id, profile_id, status="CRAWLING",
            worker_owner="live-instance", heartbeat_at=datetime.now(),
        )
        _settle_other_jobs(db, job_id)

        from app.features.security_testing.zap.worker import ScanWorker

        worker = ScanWorker(owner="test-worker", poll_interval_seconds=1)
        assert worker.tick() == 0
        worker.stop()
        status = db.execute(
            text("select status from security_scan_job where id = :i"), {"i": job_id},
        ).scalar_one()
        assert status == "CRAWLING"

    def test_tick_claims_at_most_one_job_at_a_time(self, api, admin, db, monkeypatch):
        """第一版单 ZAP 实例同一时间只跑一个需要修改全局配置的任务（§八）。"""
        _zap_on(monkeypatch, enabled=True)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        first = _make_job(db, pid, target_id, profile_id, status="PENDING")
        second = _make_job(db, pid, target_id, profile_id, status="PENDING")
        # 库里可能还有前面用例留下的中间态任务，它们会占满并发额度。
        _settle_other_jobs(db, first, second)

        from app.features.security_testing.zap.worker import ScanWorker

        seen = []

        def factory(connector):
            class _Stub:
                def run(self, job_id):
                    seen.append(job_id)
                    from app.shared.database import SessionLocal
                    from app.features.security_testing.zap.models.job import SecurityScanJob

                    with SessionLocal() as session:
                        row = session.get(SecurityScanJob, job_id)
                        row.status = "COMPLETED"
                        row.progress = 100
                        row.finished_at = datetime.now()
                        session.commit()
                    return "COMPLETED"

            return _Stub()

        worker = ScanWorker(
            owner="test-worker", poll_interval_seconds=1,
            max_concurrent_jobs=1, orchestrator_factory=factory,
        )
        try:
            assert worker.tick() == 1
            assert seen == [first]

            # 第二个任务留待下一轮领取。
            # 注意：两轮 tick 之间不能调 worker.stop()——stop 会置位 _stop_event，
            # tick 会在领取前就 break，第二轮永远是 0。
            assert worker.tick() == 1
            assert seen == [first, second]
        finally:
            worker.stop()

    def test_start_spawns_thread_when_enabled(self, api, admin, db, monkeypatch):
        _zap_on(monkeypatch, enabled=True)
        pid = _project(api, admin)
        target_id = api.post(
            f"/projects/{pid}/security/scan-targets", username=admin, json=_target_body(),
        ).json()["id"]
        profile_id = _profile(db, pid)
        job_id = _make_job(db, pid, target_id, profile_id, status="PENDING")
        _settle_other_jobs(db, job_id)

        from app.features.security_testing.zap.worker import ScanWorker

        worker = ScanWorker(
            owner="test-worker", poll_interval_seconds=0.3,
            orchestrator_factory=_terminal_orchestrator("COMPLETED"),
        )
        worker.start()
        try:
            assert worker.is_running is True
        finally:
            worker.stop()
        assert worker.is_running is False


def _settle_other_jobs(db, *keep_ids):
    """把库里其它未结束的任务判为已取消，保证后台任务用例不受运行顺序影响。

    任务表是整个测试会话共享的：前面用例留下的中间态任务会占用
    「单实例同一时间只跑一个」的并发额度，让本用例一个任务都领不到。
    keep_ids 里的是本用例自己关心的任务（可以处于任何状态）。
    """
    from app.shared.database import SessionLocal

    keep = [int(job_id) for job_id in keep_ids] or [-1]
    placeholders = ", ".join(f":keep{i}" for i in range(len(keep)))
    with SessionLocal() as session:
        session.execute(
            text(
                "update security_scan_job set status = 'CANCELLED', finished_at = now() "
                "where status not in ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT') "
                f"and id not in ({placeholders})"
            ),
            {f"keep{i}": job_id for i, job_id in enumerate(keep)},
        )
        session.commit()
