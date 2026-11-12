import hashlib
import os
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("SECRET_KEY", "unit-test-secret-not-for-production")

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.core.models.project import Project
from app.features.test_management.models.test_case import TestCase as CaseRow
from app.features.test_management.services import excel_case_import_service as importer


class _Query:
    def filter(self, *_args):
        return self

    def all(self):
        return []

    def first(self):
        return None


class _Session:
    def __init__(self):
        self.pending = []
        self.committed = False
        self.rolled_back = False

    def get(self, model, _key):
        return object() if model is Project else None

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


def _xlsx(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "测试用例"
    sheet.append(importer.HEADERS)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _actor():
    return SimpleNamespace(id=7, role="admin", username="admin")


def test_preview_applies_defaults_and_reports_duplicate_rows():
    content = _xlsx([
        ["登录成功", None, None, "核对登录后的显示名称"],
        ["登录成功", "P4", "UNKNOWN", "重复行"],
    ])
    preview = importer.SERVICE.parse(
        content, project_id=3, direction="API", scope_node_id=None,
        db=_Session(), actor=_actor(),
    )

    assert preview["items"][0]["priority"] == "P1"
    assert preview["items"][0]["case_type"] == "FUNCTIONAL"
    assert {(error["row"], error["column"]) for error in preview["errors"]} == {
        (3, "用例名称"), (3, "优先级"), (3, "测试维度"),
    }


def test_confirm_rolls_back_when_mid_batch_creation_fails(monkeypatch):
    content = _xlsx([["第一条", "P1", "FUNCTIONAL", ""], ["第二条", "P2", "BOUNDARY", ""]])
    session = _Session()

    def fail_after_first(self, db: Session, case: CaseRow):
        if case.name == "第二条":
            raise RuntimeError("simulated write failure")

    monkeypatch.setattr(importer.ScopeService, "attach_new_case", fail_after_first)
    try:
        importer.SERVICE.confirm(
            content, project_id=3, direction="UI", scope_node_id=None,
            request_key=str(uuid4()), expected_source_hash=hashlib.sha256(content).hexdigest(),
            db=session, actor=_actor(),
        )
    except RuntimeError as exc:
        assert "simulated write failure" in str(exc)
    else:
        raise AssertionError("expected the injected write failure")

    assert session.rolled_back
    assert not session.committed
    assert session.pending == []
