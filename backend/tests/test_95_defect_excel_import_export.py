"""缺陷 Excel 导入、导出与模板下载端到端集成测试。

覆盖方案要求的核心与边界场景：
- 模板下载结构（「缺陷明细」「填写说明」、下拉校验、文本格式、示例隔离、权限）；
- 全样本导入预览与确认（中文、多行步骤、含逗号引号 JSON、001.02、公式样纯文本、空值默认、
  两种等级 4、历史值「后端」→「接口」、调换列顺序、跳过空行保留 Excel 行号、未知列提示）；
- 安全与校验拒绝（缺表头、重复映射、公式单元格、.xls/.xlsm/损坏文件、接口字段冲突、100/101 行边界）；
- 事务原子性与幂等（失败整体回滚、同一预览重试返回同一回执、相同文件重传历史批次提示与显式确认、
  预览后权限降级拦截）；
- 导出与回导（默认排除接口详情、开启接口详情脱敏并在说明页标记、展示状态「待验证」、UTC+8 时区、
  公式样文本显式字符串、跨页筛选与草稿/归档可见性、勾选项失效 409、零条反馈、超 32767 字拦截、
  已有缺陷 ID 回导阻止与清空 ID 复制新建）；
- 性能与 SQL 计数检查（10 条 vs 80 条导出验证无 N+1 查询增长）。
"""

from __future__ import annotations

import json
import time
from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from sqlalchemy import event

from app.core.database.session import engine
from app.features.defects.models.activity import BugActivity
from app.features.defects.models.bug import Bug
from app.features.defects.models.import_batch import DefectImportBatch
from app.features.defects.services.defect_service import DefectService
from app.features.defects.services.excel_io_service import (
    DETAIL_SHEET_NAME,
    EXCEL_CELL_MAX_LENGTH,
    GUIDE_SHEET_NAME,
    IMPORT_COLUMNS,
)
from tests.conftest import unique


def _create_project(api, actor: str, name: str | None = None) -> int:
    """以 actor 创建项目并返回 project_id。"""
    resp = api.post("/projects", username=actor, json={"name": name or unique("defect-io"), "description": "io test"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _register_and_login(api, username: str) -> int:
    """注册普通用户并登录，返回 user_id。"""
    resp = api.register(username)
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user"]["id"]
    api.login(username, "Init-Password-123")
    return user_id


def _set_member_role(api, actor: str, project_id: int, user_id: int, role: str) -> None:
    """设置项目成员角色。"""
    resp = api.put(
        f"/projects/{project_id}/members/{user_id}",
        username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert resp.status_code == 200, resp.text


def _build_xlsx(
    rows: list[list[object]],
    *,
    headers: list[str] | None = None,
    sheet_name: str = DETAIL_SHEET_NAME,
    text_cells: set[tuple[int, int]] | None = None,
) -> bytes:
    """构造测试用 .xlsx 字节流；text_cells 指定的 (row, col) 显式以纯文本写入。"""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    actual_headers = headers if headers is not None else [col[0] for col in IMPORT_COLUMNS]
    ws.append(actual_headers)
    for r_offset, row in enumerate(rows, start=2):
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_offset, column=c_idx)
            if text_cells and (r_offset, c_idx) in text_cells:
                cell.value = val
                cell.data_type = "s"
                cell.number_format = "@"
            else:
                cell.value = val
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_preview(api, username: str, project_id: int, content: bytes, filename: str = "defects.xlsx"):
    """调用导入预览接口。"""
    return api.post(
        "/bugs/import-preview",
        username=username,
        data={"project_id": str(project_id)},
        files={"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def test_download_template_structure_and_permissions(api, admin):
    """模板下载包含两张表、下拉选项、文本格式与示例隔离，并校验项目写权限。"""
    project_id = _create_project(api, admin)
    viewer_name = unique("viewer")
    viewer_id = _register_and_login(api, viewer_name)
    _set_member_role(api, admin, project_id, viewer_id, "viewer")
    outsider_name = unique("outsider")
    _register_and_login(api, outsider_name)

    # 只读成员无权下载导入模板（403）；不可见项目按 404 隐藏。
    assert api.get("/bugs/import-template", username=viewer_name, params={"project_id": project_id}).status_code == 403
    assert api.get("/bugs/import-template", username=outsider_name, params={"project_id": project_id}).status_code == 404

    resp = api.get("/bugs/import-template", username=admin, params={"project_id": project_id})
    assert resp.status_code == 200, resp.text
    assert "spreadsheetml.sheet" in resp.headers["content-type"]

    wb = load_workbook(BytesIO(resp.content), data_only=False)
    try:
        assert wb.sheetnames == [DETAIL_SHEET_NAME, GUIDE_SHEET_NAME]
        detail = wb[DETAIL_SHEET_NAME]
        header_row = [cell.value for cell in next(detail.iter_rows(min_row=1, max_row=1))]
        assert header_row == [col[0] for col in IMPORT_COLUMNS]
        # 确认明细页只有首行表头，没有误导性示例数据行。
        data_values = [
            cell.value
            for row in detail.iter_rows(min_row=2, max_row=10)
            for cell in row
            if cell.value is not None
        ]
        assert data_values == []
        # 下拉数据验证存在，发现环境/影响版本列设为文本格式 @。
        assert len(detail.data_validations.dataValidation) == 4
        assert detail["I2"].number_format == "@"
        assert detail["J2"].number_format == "@"
        # 填写说明页包含版本与示例。
        guide_text = "\n".join(
            str(cell.value) for row in wb[GUIDE_SHEET_NAME].iter_rows() for cell in row if cell.value
        )
        assert "v1" in guide_text
        assert "示例 1" in guide_text
        assert "001.02" in guide_text
    finally:
        wb.close()


def test_import_full_sample_swapped_columns_and_blank_rows(api, admin, db):
    """全样本导入：调换列序、跳过空白行保留行号、后端→接口、两种等级4、JSON、001.02、公式样纯文本与未知列提示。"""
    project_id = _create_project(api, admin)
    # 刻意调换列顺序，并加入一列未知列「备注」与第 3 行完全空白行。
    headers = [
        "影响版本", "标题", "前后端划分", "严重度", "优先级", "发现环境",
        "复现步骤", "请求方法", "请求地址", "请求头", "请求体", "实际响应结果", "备注",
    ]
    json_body = json.dumps({"sku": "A-01", "note": '含逗号,与"引号"'}, ensure_ascii=False)
    rows = [
        # Excel 第 2 行：接口缺陷（使用历史值「后端」、两种等级 4、前导零、多行步骤、JSON、敏感请求头）
        [
            "001.02",
            "提交订单返回 500",
            "后端",
            "严重",
            "紧急",
            "001.02",
            "1. 打开下单页\n2. 提交订单\n3. 查看响应",
            "post",
            "/api/v1/orders",
            "Authorization: Bearer super-secret-token-123456\nContent-Type: application/json",
            json_body,
            '{"code": 500, "msg": "internal error"}',
            "未知列值应提示但忽略",
        ],
        # Excel 第 3 行：完全空白行，应跳过且下一行保留原始行号 4
        [None] * len(headers),
        # Excel 第 4 行：公式样纯文本标题、空值严重度/优先级沿用默认 2
        [
            "001.02",
            "=SUM(1,2)",
            "前端",
            None,
            "",
            "staging",
            "1. 输入公式样文本",
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        # Excel 第 5 行：数字型等级 4
        [
            "v2.0",
            "数字等级 4 样本",
            "前后端",
            4,
            4,
            "prod",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
    ]
    # 明确把第 4 行第 2 列（=SUM(1,2)）写为纯文本单元格（公式样文本），而非公式。
    content = _build_xlsx(rows, headers=headers, text_cells={(4, 2)})

    preview_resp = _upload_preview(api, admin, project_id, content, "sample.xlsx")
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()
    assert preview["errors"] == []
    assert preview["preview_token"]
    assert preview["total_rows"] == 3
    assert preview["valid_rows"] == 3
    assert preview["unknown_columns"] == ["备注"]
    assert any("备注" in msg for msg in preview["warnings"])
    assert [item["excel_row"] for item in preview["items"]] == [2, 4, 5]
    assert preview["items"][0]["category"] == "接口"
    assert preview["items"][0]["severity"] == 4
    assert preview["items"][0]["priority"] == 4
    assert preview["items"][0]["affected_version"] == "001.02"
    assert preview["items"][0]["api_method"] == "POST"
    assert preview["items"][1]["title"] == "=SUM(1,2)"
    assert preview["items"][1]["severity"] == 2
    assert preview["items"][1]["priority"] == 2
    assert preview["items"][2]["severity"] == 4
    assert preview["items"][2]["priority"] == 4

    confirm_resp = api.post(
        "/bugs/import-confirm",
        username=admin,
        json={"project_id": project_id, "preview_token": preview["preview_token"]},
    )
    assert confirm_resp.status_code == 201, confirm_resp.text
    receipt = confirm_resp.json()
    assert receipt["created_count"] == 3
    assert receipt["replayed"] is False
    assert [item["excel_row"] for item in receipt["items"]] == [2, 4, 5]

    # 校验落库结果、活动事件、请求头脱敏与初始待确认状态。
    first_bug_id = receipt["items"][0]["bug_id"]
    bug_resp = api.get(f"/bugs/{first_bug_id}", username=admin)
    assert bug_resp.status_code == 200
    bug_data = bug_resp.json()
    assert bug_data["status"] == "待确认"
    assert bug_data["category"] == "接口"
    assert bug_data["affected_version"] == "001.02"
    assert bug_data["environment"] == "001.02"
    assert bug_data["steps_to_reproduce"] == "1. 打开下单页\n2. 提交订单\n3. 查看响应"
    assert bug_data["api_request_body"] == json_body
    assert "super-secret-token-123456" not in (bug_data["api_request_headers"] or "")

    activities = db.query(BugActivity).filter(BugActivity.bug_id == first_bug_id).all()
    assert len(activities) == 1
    assert activities[0].action == "created"
    assert activities[0].detail["source"] == "excel_import"
    assert activities[0].detail["import_batch_id"] == receipt["batch_id"]


def test_import_validation_errors_security_and_boundaries(api, admin, db):
    """覆盖各类校验拦截：公式、接口字段冲突、等级非法、重复映射、不支持文件格式、100/101 行边界。"""
    project_id = _create_project(api, admin)

    # 1. 不支持的 .xls OLE2 魔数与含宏 .xlsm
    ole_resp = _upload_preview(api, admin, project_id, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "old.xlsx")
    assert ole_resp.status_code == 200
    assert ole_resp.json()["preview_token"] is None
    assert "xls" in ole_resp.json()["errors"][0]["message"].lower()

    macro_buf = BytesIO()
    with ZipFile(macro_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types>macroEnabled</Types>")
        zf.writestr("xl/vbaProject.bin", b"fake-vba")
    macro_resp = _upload_preview(api, admin, project_id, macro_buf.getvalue(), "macro.xlsx")
    assert macro_resp.status_code == 200
    assert macro_resp.json()["preview_token"] is None
    assert "宏" in macro_resp.json()["errors"][0]["message"]

    # 2. 缺失必需表头 & 重复映射
    dup_map_xlsx = _build_xlsx([["a", "b"]], headers=["创建时间", "创建时间（UTC+8）"])
    dup_resp = _upload_preview(api, admin, project_id, dup_map_xlsx)
    assert dup_resp.status_code == 200
    err_msgs = [e["message"] for e in dup_resp.json()["errors"]]
    assert any("重复映射" in m for m in err_msgs)
    assert any("标题" in m for m in err_msgs)

    # 3. 公式单元格 + 接口字段冲突 + 非法优先级
    bad_rows = [
        # 第 2 行：真正的公式单元格（非纯文本）
        ["=1+1", "前端", None, None, None, None, "高", "高", None, None, None, None, None, None, None],
        # 第 3 行：前后端划分为前端，却填写了请求地址与请求方法；优先级非法
        ["接口字段冲突测试", "前端", None, None, None, None, "高", "特急", None, None, "GET", "/api/x", None, None, None],
    ]
    bad_xlsx = _build_xlsx(bad_rows)
    bad_resp = _upload_preview(api, admin, project_id, bad_xlsx)
    assert bad_resp.status_code == 200
    bad_data = bad_resp.json()
    assert bad_data["preview_token"] is None
    errors = bad_data["errors"]
    assert any(e["row"] == 2 and "公式" in e["message"] for e in errors)
    assert any(e["row"] == 3 and e["column"] == "优先级" and "低、中、高、紧急" in e["message"] for e in errors)
    assert any(e["row"] == 3 and e["column"] == "请求方法" for e in errors)
    assert any(e["row"] == 3 and e["column"] == "请求地址" for e in errors)
    # 存在错误时绝不写入任何缺陷。
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 0

    # 4. 101 行超限拒绝；100 行边界成功导入。
    rows_101 = [[f"超限缺陷 {i}", "前端"] + [None] * 13 for i in range(1, 102)]
    resp_101 = _upload_preview(api, admin, project_id, _build_xlsx(rows_101))
    assert resp_101.status_code == 200
    assert resp_101.json()["preview_token"] is None
    assert any("100" in e["message"] and "101" in e["message"] for e in resp_101.json()["errors"])

    rows_100 = [[f"边界缺陷 {i}", "前端"] + [None] * 13 for i in range(1, 101)]
    resp_100 = _upload_preview(api, admin, project_id, _build_xlsx(rows_100))
    assert resp_100.status_code == 200
    token_100 = resp_100.json()["preview_token"]
    assert token_100
    confirm_100 = api.post(
        "/bugs/import-confirm",
        username=admin,
        json={"project_id": project_id, "preview_token": token_100},
    )
    assert confirm_100.status_code == 201
    assert confirm_100.json()["created_count"] == 100
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 100


def test_import_idempotency_duplicate_reupload_permission_and_rollback(api, admin, db, monkeypatch):
    """覆盖同一预览重试幂等、相同文件重传历史提示、文件内重复提示、权限变化拦截与异常整体回滚。"""
    project_id = _create_project(api, admin)
    member_name = unique("member")
    member_id = _register_and_login(api, member_name)
    _set_member_role(api, admin, project_id, member_id, "member")

    # 含文件内重复标题与重复内容。
    xlsx = _build_xlsx([
        ["重复标题样例", "前端"] + [None] * 13,
        ["重复标题样例", "前端"] + [None] * 13,
    ])
    p1 = _upload_preview(api, member_name, project_id, xlsx, "dup.xlsx")
    assert p1.status_code == 200
    p1_data = p1.json()
    assert len(p1_data["duplicate_warnings"]) >= 1
    assert p1_data["duplicate_warnings"][0]["rows"] == [2, 3]
    token1 = p1_data["preview_token"]
    assert token1

    # 1. 首次确认成功，二次重试同一 preview_token 返回同一回执且不重复建单。
    c1 = api.post("/bugs/import-confirm", username=member_name, json={"project_id": project_id, "preview_token": token1})
    assert c1.status_code == 201
    c2 = api.post("/bugs/import-confirm", username=member_name, json={"project_id": project_id, "preview_token": token1})
    assert c2.status_code == 201
    assert c2.json()["replayed"] is True
    assert c2.json()["batch_id"] == c1.json()["batch_id"]
    assert c2.json()["items"] == c1.json()["items"]
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 2

    # 2. 重新上传相同文件：预览提示最近成功批次，不勾选 confirm_duplicate 返 409，勾选后新建成功。
    p2 = _upload_preview(api, member_name, project_id, xlsx, "dup-again.xlsx")
    assert p2.status_code == 200
    p2_data = p2.json()
    assert p2_data["recent_matching_batch"]["batch_id"] == c1.json()["batch_id"]
    token2 = p2_data["preview_token"]

    c_conflict = api.post(
        "/bugs/import-confirm",
        username=member_name,
        json={"project_id": project_id, "preview_token": token2, "confirm_duplicate": False},
    )
    assert c_conflict.status_code == 409
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 2

    c_dup_ok = api.post(
        "/bugs/import-confirm",
        username=member_name,
        json={"project_id": project_id, "preview_token": token2, "confirm_duplicate": True},
    )
    assert c_dup_ok.status_code == 201
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 4

    # 3. 预览后权限变化（降为 viewer）：确认时应被 403 拒绝。
    p3 = _upload_preview(api, member_name, project_id, _build_xlsx([["权限变化测试", "前端"] + [None] * 13]))
    assert p3.status_code == 200
    token3 = p3.json()["preview_token"]
    _set_member_role(api, admin, project_id, member_id, "viewer")
    c_denied = api.post(
        "/bugs/import-confirm",
        username=member_name,
        json={"project_id": project_id, "preview_token": token3},
    )
    assert c_denied.status_code == 403
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 4

    # 4. 事务原子性：中途写活动失败，整个导入回滚，不留孤立缺陷或错误 COMMITTED 状态。
    p4 = _upload_preview(api, admin, project_id, _build_xlsx([["回滚测试单", "前端"] + [None] * 13]))
    token4 = p4.json()["preview_token"]

    def _boom(*args, **kwargs):
        raise RuntimeError("模拟活动写入异常")

    monkeypatch.setattr(DefectService, "_record_activity", _boom)
    try:
        try:
            api.post("/bugs/import-confirm", username=admin, json={"project_id": project_id, "preview_token": token4})
        except RuntimeError:
            pass
    finally:
        monkeypatch.undo()

    db.expire_all()
    assert db.query(Bug).filter(Bug.project_id == project_id, Bug.title == "回滚测试单").count() == 0
    batch4 = db.query(DefectImportBatch).filter(DefectImportBatch.preview_token == token4).one()
    assert batch4.status == "PREVIEW"


def test_export_filtering_masking_reimport_and_edge_cases(api, admin, db):
    """覆盖默认导出脱敏排除、接口详情脱敏标记、展示状态、公式文本、跨页导出、勾选失效、零条、超长拦截与回导规则。"""
    project_id = _create_project(api, admin)
    member_name = unique("member2")
    member_id = _register_and_login(api, member_name)
    _set_member_role(api, admin, project_id, member_id, "member")

    # 零条反馈。
    empty_resp = api.post("/bugs/export", username=admin, json={"project_id": project_id, "mode": "filtered"})
    assert empty_resp.status_code == 400
    assert "没有可导出" in empty_resp.json()["message"]

    # 创建一条含公式样标题、前导零与敏感接口详情的缺陷，推进到「已修复」（展示为「待验证」）。
    created = api.post(
        "/bugs",
        username=admin,
        json={
            "project_id": project_id,
            "title": "=CMD('calc')",
            "category": "接口",
            "severity": 4,
            "priority": 4,
            "affected_version": "001.02",
            "environment": "001.02",
            "description": "首行\n次行",
            "api_method": "POST",
            "api_url": "/api/v1/pay",
            "api_request_headers": "Authorization: Bearer my-real-secret-header-token",
            "api_request_body": '{"password": "plain-secret-password", "amount": 100}',
            "api_response": '{"access_token": "resp-secret-token-xyz", "ok": false}',
        },
    ).json()
    bug_id = created["id"]
    api.post(f"/bugs/{bug_id}/actions", username=admin, json={"action": "confirm"})
    api.post(f"/bugs/{bug_id}/actions", username=admin, json={"action": "ready_for_regression", "fix_version": "1.0.1"})

    # 创建一条草稿（admin 的草稿不应出现在 member 导出中）。
    api.post("/bugs", username=admin, json={"project_id": project_id, "title": "管理员私有草稿", "is_draft": True})

    # 1. 默认导出：不含请求头/请求体/实际响应结果，状态显示「待验证」，公式样标题为纯文本。
    exp_default = api.post("/bugs/export", username=member_name, json={"project_id": project_id, "mode": "filtered"})
    assert exp_default.status_code == 200, exp_default.text
    assert exp_default.headers["x-export-count"] == "1"

    wb = load_workbook(BytesIO(exp_default.content), read_only=False, data_only=False)
    try:
        ws = wb[DETAIL_SHEET_NAME]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        assert "请求头" not in headers
        assert "请求体" not in headers
        assert "实际响应结果" not in headers
        assert "创建时间（UTC+8）" in headers
        row2 = {headers[i]: cell for i, cell in enumerate(next(ws.iter_rows(min_row=2, max_row=2)))}
        assert row2["标题"].value == "=CMD('calc')"
        assert row2["标题"].data_type == "s"
        assert row2["当前状态"].value == "待验证"
        assert row2["严重度"].value == "严重"
        assert row2["优先级"].value == "紧急"
        assert row2["影响版本"].value == "001.02"
    finally:
        wb.close()

    # 2. 已有缺陷 ID 直接回导 -> 阻止；清空缺陷 ID 后回导 -> 成功新建。
    reimport_blocked = _upload_preview(api, admin, project_id, exp_default.content, "exported.xlsx")
    assert reimport_blocked.status_code == 200
    assert reimport_blocked.json()["preview_token"] is None
    assert any(e["row"] == 2 and e["column"] == "缺陷 ID" for e in reimport_blocked.json()["errors"])

    wb_copy = load_workbook(BytesIO(exp_default.content), data_only=False)
    ws_copy = wb_copy[DETAIL_SHEET_NAME]
    ws_copy["A2"].value = None
    copy_buf = BytesIO()
    wb_copy.save(copy_buf)
    wb_copy.close()

    reimport_ok = _upload_preview(api, admin, project_id, copy_buf.getvalue(), "exported-clean-id.xlsx")
    assert reimport_ok.status_code == 200
    reimport_data = reimport_ok.json()
    assert reimport_data["errors"] == []
    assert reimport_data["preview_token"]
    assert reimport_data["items"][0]["action"] == "create"
    assert reimport_data["items"][0]["title"] == "=CMD('calc')"
    assert reimport_data["ignored_system_columns"]

    # 3. 启用接口详情导出：脱敏生效且在说明页标注。
    exp_api = api.post(
        "/bugs/export",
        username=admin,
        json={"project_id": project_id, "mode": "selected", "bug_ids": [bug_id], "include_api_details": True},
    )
    assert exp_api.status_code == 200, exp_api.text
    wb_api = load_workbook(BytesIO(exp_api.content), data_only=False)
    try:
        ws_api = wb_api[DETAIL_SHEET_NAME]
        headers = [c.value for c in next(ws_api.iter_rows(min_row=1, max_row=1))]
        row2 = {headers[i]: cell.value for i, cell in enumerate(next(ws_api.iter_rows(min_row=2, max_row=2)))}
        assert "my-real-secret-header-token" not in (row2["请求头"] or "")
        assert "plain-secret-password" not in (row2["请求体"] or "")
        assert "resp-secret-token-xyz" not in (row2["实际响应结果"] or "")
        assert "100" in (row2["请求体"] or "")
        guide_text = "\n".join(
            str(c.value) for r in wb_api[GUIDE_SHEET_NAME].iter_rows() for c in r if c.value
        )
        assert "脱敏" in guide_text
    finally:
        wb_api.close()

    # 4. 勾选项失效（包含不存在 ID）-> 409 并返回 missing_ids。
    stale_resp = api.post(
        "/bugs/export",
        username=admin,
        json={"project_id": project_id, "mode": "selected", "bug_ids": [bug_id, 999999]},
    )
    assert stale_resp.status_code == 409
    assert 999999 in stale_resp.json()["meta"]["missing_ids"]

    # 5. 超单元格 32767 字上限 -> 明确报错指出缺陷 ID 和列，不静默截断。
    huge_bug = Bug(
        project_id=project_id,
        title="超长步骤缺陷",
        steps_to_reproduce="x" * (EXCEL_CELL_MAX_LENGTH + 10),
        severity=2,
        priority=2,
        status="待确认",
    )
    db.add(huge_bug)
    db.commit()
    huge_resp = api.post(
        "/bugs/export",
        username=admin,
        json={"project_id": project_id, "mode": "selected", "bug_ids": [huge_bug.id]},
    )
    assert huge_resp.status_code == 400
    assert str(huge_bug.id) in huge_resp.json()["message"]
    assert "复现步骤" in huge_resp.json()["message"]


def test_export_sql_count_does_not_grow_with_row_count(api, admin):
    """性能基线检查：10 条 vs 80 条跨页筛选导出，SQL 查询次数保持常数（无 N+1）。"""
    proj_small = _create_project(api, admin, unique("perf-10"))
    proj_large = _create_project(api, admin, unique("perf-80"))

    api.post(
        "/bugs/batch",
        username=admin,
        json={"project_id": proj_small, "items": [{"title": f"S-{i}", "category": "前端"} for i in range(10)]},
    )
    api.post(
        "/bugs/batch",
        username=admin,
        json={"project_id": proj_large, "items": [{"title": f"L-{i}", "category": "前端"} for i in range(80)]},
    )

    def _measure_export(pid: int) -> tuple[int, float, int]:
        sql_count = 0

        def _before_cursor_execute(*_args, **_kwargs):
            nonlocal sql_count
            sql_count += 1

        event.listen(engine, "before_cursor_execute", _before_cursor_execute)
        t0 = time.perf_counter()
        try:
            resp = api.post("/bugs/export", username=admin, json={"project_id": pid, "mode": "filtered"})
            elapsed_ms = (time.perf_counter() - t0) * 1000
        finally:
            event.remove(engine, "before_cursor_execute", _before_cursor_execute)
        assert resp.status_code == 200, resp.text
        return sql_count, elapsed_ms, int(resp.headers["x-export-count"])

    sql_10, ms_10, count_10 = _measure_export(proj_small)
    sql_80, ms_80, count_80 = _measure_export(proj_large)
    assert count_10 == 10
    assert count_80 == 80
    # 两者均在一个 500 条分批窗口内，SQL 次数必须完全一致，绝不随缺陷数线性增长。
    assert sql_10 == sql_80, f"导出存在 N+1 风险：10 条={sql_10} 次 SQL（{ms_10:.1f}ms），80 条={sql_80} 次 SQL（{ms_80:.1f}ms）"
