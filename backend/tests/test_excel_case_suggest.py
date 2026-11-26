"""Excel 用例导入建议：规则优先，模型失败时仍可手动确认。"""

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from openpyxl import Workbook

from app.features.test_management.models.test_case import TestCase as CaseRow
from app.features.test_management.services import excel_case_import_service as importer
from app.features.test_management.services import excel_case_suggest_service as suggest
from app.llm.contracts import LLMError
from app.llm.providers.openai_compatible import FakeLLMProvider


class _Query:
    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return []

    def first(self):
        return None

    def delete(self, **_kwargs):
        return 0


class _Session:
    def __init__(self):
        self.pending = []
        self.committed = False
        self.rolled_back = False

    def get(self, *_args, **_kwargs):
        return None

    def query(self, *_entities):
        return _Query()

    def add(self, row):
        self.pending.append(row)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True
        self.pending.clear()

    def begin_nested(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _actor():
    return SimpleNamespace(id=7, role="admin", username="admin")


def _xlsx(headers, rows, title="用例"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _allow(monkeypatch, interfaces):
    allow = lambda *_args, **_kwargs: SimpleNamespace(id=3)
    monkeypatch.setattr("app.platform.projects.services.access_service.require_writable_project", allow)
    monkeypatch.setattr(importer, "require_writable_project", allow)
    monkeypatch.setattr(suggest, "load_project_interfaces", lambda *_args, **_kwargs: interfaces)


def _interfaces():
    return [{"id": 9, "name": "客户资料新增", "method": "POST", "path": "/customers"}]


def test_exact_path_wins_over_unknown_model_api(monkeypatch):
    content = _xlsx(["用例名称", "接口", "说明"], [["新增客户", "POST /customers", "边界：名称为空"]])
    provider = FakeLLMProvider()
    provider.set_response("excel_case_import_suggest", {
        "sheets": [{"worksheet": "用例", "role": "cases", "header_row": 1}],
        "columns": [
            {"column_index": 1, "field": "name", "reason": "名称"},
            {"column_index": 2, "field": "path", "reason": "路径"},
            {"column_index": 9, "field": "drop", "reason": "不存在的列"},
        ],
        "rows": [{"worksheet": "用例", "row": 2, "case_type": "BOUNDARY", "api_id": 99, "reason": "猜测", "confidence": 2}],
    })
    _allow(monkeypatch, _interfaces())

    result = suggest.suggest(
        content, project_id=3, direction="API", scope_node_id=None,
        db=_Session(), actor=_actor(), provider=provider,
    )

    row = result["rows"][0]
    assert row["rule_status"] == "recommended"
    assert row["rule_api_id"] == 9
    assert row["model_api_id"] is None
    assert row["model_case_type"] == "BOUNDARY"
    assert row["model_confidence"] == 1
    assert result["columns"] == [
        {"column_index": 1, "field": "name", "reason": "名称"},
        {"column_index": 2, "field": "path", "reason": "路径"},
    ]
    assert result["model_status"] == "ok"
    assert result["model_calls"] == 1


def test_ambiguous_match_is_not_forced_by_model(monkeypatch):
    content = _xlsx(["说明"], [["POST /customers"]])
    provider = FakeLLMProvider()
    provider.set_response("excel_case_import_suggest", {
        "rows": [{"worksheet": "用例", "row": 2, "api_id": 1, "case_type": "FUNCTIONAL", "reason": "选第一个", "confidence": 0.9}],
    })
    _allow(monkeypatch, [
        {"id": 1, "name": "客户甲", "method": "POST", "path": "/customers"},
        {"id": 2, "name": "客户乙", "method": "POST", "path": "/customers"},
    ])

    result = suggest.suggest(
        content, project_id=3, direction="API", scope_node_id=None,
        db=_Session(), actor=_actor(), provider=provider,
    )

    assert result["rows"][0]["rule_status"] == "ambiguous"
    assert result["rows"][0]["rule_api_id"] is None
    assert result["rows"][0]["model_api_id"] is None
    assert [item["id"] for item in result["rows"][0]["candidates"]] == [1, 2]


def test_model_failure_keeps_rule_match(monkeypatch):
    content = _xlsx(["接口"], [["POST /customers"]])
    provider = FakeLLMProvider()

    def fail(*_args, **_kwargs):
        raise LLMError("NO_DEFAULT_MODEL", "没有可用的文本模型")

    provider.generate_structured = fail
    _allow(monkeypatch, _interfaces())

    result = suggest.suggest(
        content, project_id=3, direction="API", scope_node_id=None,
        db=_Session(), actor=_actor(), provider=provider,
    )

    assert result["model_status"] == "unavailable"
    assert result["rows"][0]["rule_api_id"] == 9
    assert result["rows"][0]["model_case_type"] is None


def test_skip_model_does_not_call_provider(monkeypatch):
    content = _xlsx(["接口"], [["POST /customers"]])
    provider = FakeLLMProvider()
    _allow(monkeypatch, _interfaces())

    result = suggest.suggest(
        content, project_id=3, direction="API", scope_node_id=None,
        db=_Session(), actor=_actor(), use_model=False, provider=provider,
    )

    assert provider.calls == []
    assert result["model_status"] == "skipped"
    assert result["rows"][0]["rule_status"] == "recommended"


def test_confirm_writes_api_only_when_accepted(monkeypatch):
    content = _xlsx(list(importer.HEADERS), [["新增客户", "P1", "FUNCTIONAL", "说明"]])
    _allow(monkeypatch, _interfaces())
    monkeypatch.setattr(importer.ScopeService, "attach_new_case", lambda *_args, **_kwargs: None)
    session = _Session()
    adoption = json.dumps({
        "mode": "template",
        "rows": [{
            "worksheet": "用例", "row": 2, "accept_case_type": True, "case_type": "BOUNDARY",
            "accept_api": True, "api_id": 9,
        }],
    })

    result = importer.SERVICE.confirm(
        content, project_id=3, direction="API", scope_node_id=None,
        request_key=str(uuid4()), expected_source_hash=hashlib.sha256(content).hexdigest(),
        db=session, actor=_actor(), adoption_json=adoption,
    )

    cases = [row for row in session.pending if isinstance(row, CaseRow)]
    assert cases[0].api_id == 9
    assert cases[0].case_type == "BOUNDARY"
    assert cases[0].priority == "P1"
    assert result["applied"] == [{"worksheet": "用例", "row": 2, "case_type": "BOUNDARY", "api_id": 9}]
    assert session.committed


def test_confirm_rejects_interface_outside_project(monkeypatch):
    content = _xlsx(list(importer.HEADERS), [["新增客户", "P1", "FUNCTIONAL", "说明"]])
    _allow(monkeypatch, _interfaces())
    session = _Session()
    adoption = json.dumps({
        "mode": "template",
        "rows": [{"worksheet": "用例", "row": 2, "accept_api": True, "api_id": 404}],
    })

    try:
        importer.SERVICE.confirm(
            content, project_id=3, direction="API", scope_node_id=None,
            request_key=str(uuid4()), expected_source_hash=hashlib.sha256(content).hexdigest(),
            db=session, actor=_actor(), adoption_json=adoption,
        )
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("项目外接口不应写入")

    assert not session.committed


def test_mapping_confirm_imports_custom_headers(monkeypatch):
    content = _xlsx(["名称", "级别", "备注"], [["新增客户", "P0", "保留原文"]])
    _allow(monkeypatch, [])
    monkeypatch.setattr(importer.ScopeService, "attach_new_case", lambda *_args, **_kwargs: None)
    session = _Session()
    adoption = json.dumps({
        "mode": "mapping",
        "worksheet": "用例",
        "header_row": 1,
        "name_column": 1,
        "priority_column": 2,
        "description_column": 3,
        "rows": [],
    })

    importer.SERVICE.confirm(
        content, project_id=3, direction="UI", scope_node_id=None,
        request_key=str(uuid4()), expected_source_hash=hashlib.sha256(content).hexdigest(),
        db=session, actor=_actor(), adoption_json=adoption,
    )

    cases = [row for row in session.pending if isinstance(row, CaseRow)]
    assert cases[0].name == "新增客户"
    assert cases[0].priority == "P0"
    assert cases[0].description == "保留原文"
    assert cases[0].api_id is None
    assert session.committed
