"""ZAP 告警归一化 + 指纹 + Finding 字段拼装（§十八 / §十九 / §二十）。

关键口径：
- 保留 ZAP 原始信息：source=ZAP、source_rule_id、alert_name、risk、confidence、
  CWE、WASC、reference，**不丢弃规则原始 ID**（§十八）。
- Severity 映射走 ``map_zap_risk``；**Confidence 与 Severity 是两个独立维度**，
  Confidence 原样透传，不参与映射。
- 告警先作为 **Potential Finding** 落库（security_finding.status='OPEN'），
  不宣称「已经验证存在漏洞」——人工复核才置 CONFIRMED（§十八）。
- 指纹：``sha256("zap|{project_id}|{target_id}|{rule_id}|{normalized_url}|{param}|{sig}")``，
  64 位十六进制，与 Phase 1 的 ``sha256(api_id|mutation_type|...)`` 落在同一列
  （security_finding.fingerprint 是 String(64)），靠输入里的命名空间前缀避免碰撞，
  不改列宽度。来源标记同时写进 Finding 的 evidence.source，便于人眼区分。
- 证据先脱敏再落库（redact_url / redact_text / redact_mapping），原始 Request/Response
  不存储（§二十一）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.features.security_testing.zap.contracts import (
    MAX_EVIDENCE_TEXT_LENGTH,
    ZAP_CONFIDENCE_RANGE,
    ZAPAlert,
    map_zap_risk,
    redact_mapping,
    redact_text,
    redact_url,
)

#: 指纹命名空间：写在 hash 输入里而不是输出前缀，避免超出 String(64)。
FINGERPRINT_NAMESPACE = "zap"

#: ZAP 告警统一记录的来源工具名。
SCANNER_SOURCE = "ZAP"

#: 来源工具的指纹来源标记（写进 evidence，便于审计时区分 Phase 1 / Phase 2）。
#: 取值：PHASE1_MUTATION = Phase 1 变异；ZAP = Phase 2 扫描。
FINGERPRINT_SOURCE_ZAP = "ZAP"

#: Finding 的 mutation_type 取值（ZAP 告警统一落这个值，便于前端聚合）。
ZAP_MUTATION_TYPE = "ZAP_ALERT"


def normalize_url(url: str) -> str:
    """归一化 URL 用于指纹：scheme/host 小写、丢 fragment、query 排序、去尾斜杠。

    不改变路径大小写（很多 Web 框架区分大小写），也不做「同一路径不同参数」的
    合并——不同参数位可能是不同的注入点（§二十「不同参数独立问题」）。
    """
    if not url:
        return ""
    parts = urlsplit(str(url).strip())
    if parts.scheme or parts.netloc:
        scheme = (parts.scheme or "https").lower()
        netloc = (parts.hostname or "").lower()
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        path = parts.path.rstrip("/") or "/"
    else:
        # 相对 URL：只用 path（ZAP 一般返回绝对 URL，这里是兜底）。
        scheme, netloc, path = "", "", (parts.path or "").rstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def evidence_signature(evidence: str) -> str:
    """证据签名：脱敏后的 evidence 摘要，前 12 位。

    同一位置、同一规则的告警若证据不同（例如不同参数值），签名不同 → 指纹不同，
    符合「不同参数是独立问题」；同一问题重复扫描证据一致 → 指纹相同，聚成一条。
    """
    text = (redact_text(evidence) or "").strip()[:MAX_EVIDENCE_TEXT_LENGTH]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_fingerprint(
    *,
    project_id: int,
    target_id: int,
    rule_id: str,
    normalized_url: str,
    parameter: str = "",
    evidence_sig: str = "",
) -> str:
    """构造 Finding 指纹（§二十）。

    组成：project + target + scanner(ZAP) + rule_id + normalized_url + parameter
    + evidence_signature。不含 job_id，所以**跨次扫描**能识别同一问题；
    含 target_id，所以不同项目/目标不会互相串号。
    """
    raw = "|".join(
        [
            FINGERPRINT_NAMESPACE,
            str(project_id),
            str(target_id),
            str(rule_id),
            normalized_url,
            str(parameter or ""),
            evidence_sig,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clamp_confidence(value: object) -> int:
    """ZAP Confidence 是 1-5 整数，越界值收到边界而不是丢弃。"""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return ZAP_CONFIDENCE_RANGE[0]
    return max(ZAP_CONFIDENCE_RANGE[0], min(ZAP_CONFIDENCE_RANGE[1], number))


def _truncate(text: str, limit: int = MAX_EVIDENCE_TEXT_LENGTH) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…（已截断）"


@dataclass(slots=True)
class NormalizedZAPAlert:
    """一条归一化后的 ZAP 告警（§十八 字段齐全）。

    confidence 与 severity 分开存放，任何消费方都不该把它们混用。
    """

    rule_id: str
    name: str
    risk: str
    confidence: int
    severity: str
    url: str
    method: str = ""
    parameter: str = ""
    description: str = ""
    remediation: str = ""
    evidence: str = ""
    cwe_id: int | None = None
    wasc_id: int | None = None
    reference: str = ""
    fingerprint: str = ""
    normalized_url: str = ""
    evidence_signature: str = ""
    source: str = SCANNER_SOURCE
    evidence_payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """转成可入库 / 可返回前端的普通 dict。"""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "risk": self.risk,
            "confidence": self.confidence,
            "severity": self.severity,
            "url": self.url,
            "method": self.method,
            "parameter": self.parameter,
            "description": self.description,
            "remediation": self.remediation,
            "evidence": self.evidence,
            "cwe_id": self.cwe_id,
            "wasc_id": self.wasc_id,
            "reference": self.reference,
            "fingerprint": self.fingerprint,
            "source": self.source,
        }


@dataclass(slots=True)
class FindingProposal:
    """拟写入 security_finding 的字段（由 service 决定是否真的建行）。"""

    mutation_type: str
    severity: str
    title: str
    description: str
    recommendation: str
    evidence: dict
    fingerprint: str


class ZAPAlertNormalizer:
    """ZAP 告警 → 平台内部结构的唯一转换入口。

    实例持有本次扫描的上下文（project_id / target_id），这样指纹在
    同一任务内稳定、跨任务也稳定。
    """

    def __init__(self, *, project_id: int, target_id: int, scanner: str = SCANNER_SOURCE) -> None:
        """初始化归一化器。

        Args:
            project_id: 所属项目 ID（进指纹）。
            target_id: 扫描目标 ID（进指纹，避免跨目标串号）。
            scanner: 来源工具标记，默认 ZAP。
        """
        self.project_id = int(project_id)
        self.target_id = int(target_id)
        self.scanner = scanner or SCANNER_SOURCE

    def normalize(self, alert: ZAPAlert, *, scan_job_id: int | None = None) -> NormalizedZAPAlert:
        """把一条 ZAP 告警归一化为平台结构（含指纹与脱敏证据）。"""
        redacted_url = redact_url(alert.url)
        redacted_evidence = _truncate(redact_text(alert.evidence or ""))
        normalized_url = normalize_url(redacted_url)
        sig = evidence_signature(redacted_evidence)
        fingerprint = build_fingerprint(
            project_id=self.project_id,
            target_id=self.target_id,
            rule_id=alert.rule_id,
            normalized_url=normalized_url,
            parameter=alert.parameter or "",
            evidence_sig=sig,
        )
        payload = redact_mapping(
            {
                "scanner": self.scanner,
                "source_rule_id": alert.rule_id,
                "source_alert_name": alert.name,
                "risk": alert.risk,
                "confidence": _clamp_confidence(alert.confidence),
                "method": alert.method,
                "parameter": alert.parameter,
                "cwe_id": alert.cwe_id,
                "wasc_id": alert.wasc_id,
                "reference": alert.reference,
                "evidence": redacted_evidence or None,
                "scan_job_id": scan_job_id,
            }
        )
        return NormalizedZAPAlert(
            rule_id=str(alert.rule_id),
            name=alert.name or "",
            risk=alert.risk or "",
            confidence=_clamp_confidence(alert.confidence),
            severity=map_zap_risk(alert.risk),
            url=redacted_url,
            method=alert.method or "",
            parameter=alert.parameter or "",
            description=_truncate(alert.description or ""),
            remediation=_truncate(alert.remediation or ""),
            evidence=redacted_evidence,
            cwe_id=alert.cwe_id,
            wasc_id=alert.wasc_id,
            reference=alert.reference or "",
            fingerprint=fingerprint,
            normalized_url=normalized_url,
            evidence_signature=sig,
            source=self.scanner,
            evidence_payload=payload,
        )

    def finding_fields(self, item: NormalizedZAPAlert) -> FindingProposal:
        """拼装 security_finding 的字段。

        状态永远由 service 决定（这里是「建议值」）：ZAP 告警只算 Potential Finding，
        落库为 OPEN，人工复核才置 CONFIRMED。
        """
        title = f"{item.name}（规则 {item.rule_id}）"
        description = (
            f"扫描器告警：{item.name}\n\n"
            f"位置：{item.method or 'GET'} {item.url}\n"
            f"参数：{item.parameter or '（无）'}\n\n"
            f"{item.description}\n\n"
            f"本次扫描置信度（Confidence）：{item.confidence}/5；"
            f"严重级别（Severity）：{item.severity}\n"
            f"CWE {item.cwe_id or 0} / WASC {item.wasc_id or 0}\n\n"
            "这是扫描器报告的疑似问题，尚未经过人工验证。"
        )
        recommendation = item.remediation or "按扫描器建议整改，并在整改后重新扫描确认。"
        return FindingProposal(
            mutation_type=ZAP_MUTATION_TYPE,
            severity=item.severity,
            title=title,
            description=description,
            recommendation=recommendation,
            evidence={
                "source": FINGERPRINT_SOURCE_ZAP,
                "source_rule_id": item.rule_id,
                "source_alert_name": item.name,
                "risk": item.risk,
                "confidence": item.confidence,
                "severity": item.severity,
                "url": item.url,
                "method": item.method,
                "parameter": item.parameter,
                "cwe_id": item.cwe_id,
                "wasc_id": item.wasc_id,
                "reference": item.reference,
                "evidence": item.evidence,
                "normalized_url": item.normalized_url,
                "evidence_signature": item.evidence_signature,
            },
            fingerprint=item.fingerprint,
        )
