"""纯计算评测与 ASR 摘要读取；不调用外部模型或启动计费任务。"""
from __future__ import annotations

import json
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.core.models.identity import User
from app.features.asr_evaluation.models import AsrComparison, AsrJob
from app.features.asr_evaluation.services import comparison_service, job_service
from app.platform.projects.services.access_service import get_project_or_404
from app.tools.registry import register_handler


class TranscriptScoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(max_length=4000)
    hypothesis: str = Field(max_length=4000)
    unit: Literal["character", "word"] = "character"
    ignore_case: bool = False
    ignore_punctuation: bool = False


class OutputCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output: str = Field(max_length=20000)
    expected: str | None = Field(default=None, max_length=20000)
    required_phrases: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=50)
    forbidden_phrases: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=50)
    require_json_object: bool = False


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: int = Field(gt=0)


class ComparisonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comparison_id: int = Field(gt=0)


def score_transcript(reference: str, hypothesis: str, unit: str = "character",
                     ignore_case: bool = False, ignore_punctuation: bool = False) -> dict:
    """标准 Levenshtein / 标准答案长度；插入多时错误率允许大于 1。"""
    def tokens(value: str) -> list[str]:
        value = unicodedata.normalize("NFC", value)
        if ignore_case:
            value = value.casefold()
        if ignore_punctuation:
            value = "".join(c for c in value if not unicodedata.category(c).startswith("P"))
        return value.split() if unit == "word" else [c for c in value if not c.isspace()]

    left, right = tokens(reference), tokens(hypothesis)
    if len(left) * len(right) > 2_000_000:
        return {"status": "LIMIT_EXCEEDED", "metric": "WER" if unit == "word" else "CER", "error_rate": None}
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    distance = previous[-1]
    return {"status": "COMPLETED" if left else "EMPTY_REFERENCE", "metric": "WER" if unit == "word" else "CER",
            "edit_distance": distance, "reference_units": len(left), "hypothesis_units": len(right),
            "error_rate": distance / len(left) if left else None,
            "normalization": {"unicode": "NFC", "ignore_case": ignore_case, "ignore_punctuation": ignore_punctuation,
                              "whitespace": "split" if unit == "word" else "remove"}}


def check_output(output: str, expected: str | None = None, required_phrases: list[str] | None = None,
                 forbidden_phrases: list[str] | None = None, require_json_object: bool = False) -> dict:
    checks = []
    if expected is not None:
        checks.append({"rule": "exact_match", "passed": output == expected})
    for index, phrase in enumerate(required_phrases or []):
        checks.append({"rule": "required_phrase", "index": index, "passed": bool(phrase) and phrase in output})
    for index, phrase in enumerate(forbidden_phrases or []):
        checks.append({"rule": "forbidden_phrase", "index": index, "passed": bool(phrase) and phrase not in output})
    if require_json_object:
        try:
            valid = isinstance(json.loads(output), dict)
        except (ValueError, RecursionError):
            valid = False
        checks.append({"rule": "json_object", "passed": valid})
    passed = sum(item["passed"] for item in checks)
    return {"status": "COMPLETED" if checks else "NO_RULES", "checks": checks, "total": len(checks),
            "passed": passed, "pass_rate": passed / len(checks) if checks else None,
            "scope": "仅验证指定规则；不能据此判断事实性、幻觉、安全性或 RAG 引用真实性。"}


def get_job_summary(db: Session, project_id: int, actor: User, job_id: int) -> dict:
    get_project_or_404(db, project_id, actor)
    row = db.get(AsrJob, job_id)
    if row is None or row.project_id != project_id:
        raise not_found("评测任务不存在")
    result = job_service.get_job(db, job_id, actor, summary_only=True, include_text=False)
    return {key: result[key] for key in ("id", "project_id", "status", "cancel_requested", "created_at", "finished_at")}


def get_comparison_summary(db: Session, project_id: int, actor: User, comparison_id: int) -> dict:
    get_project_or_404(db, project_id, actor)
    row = db.get(AsrComparison, comparison_id)
    if row is None or row.project_id != project_id:
        raise not_found("识别结果对比不存在")
    result = comparison_service.get_comparison(db, comparison_id, actor)
    return {key: result[key] for key in ("id", "project_id", "job_id", "version", "status", "degraded", "summary")}


EVALUATION_INPUTS = {
    "asr.score_transcript": TranscriptScoreInput,
    "asr.get_job_summary": JobInput,
    "asr.get_comparison_summary": ComparisonInput,
    "ai.check_output": OutputCheckInput,
}

for _key, _handler in (
    ("asr.score_transcript", score_transcript), ("ai.check_output", check_output),
    ("asr.get_job_summary", get_job_summary), ("asr.get_comparison_summary", get_comparison_summary),
):
    register_handler(_key, _handler, risk="read", allowed_channels=("fixed",))
