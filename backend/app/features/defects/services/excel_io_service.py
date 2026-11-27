"""缺陷 Excel 导入、导出与模板生成服务。

对外暴露 ``DefectExcelIOService`` 及单例 ``EXCEL_IO_SERVICE``，提供四项能力：
1. 生成空白 `.xlsx` 导入模板（含「缺陷明细」「填写说明」两张表、下拉选项与文本格式）；
2. 解析并校验上传的 `.xlsx` 工作簿，生成带有效期的预览记录；
3. 在单事务中按预览标识幂等确认创建缺陷、活动与通知，支持并发防重与失败整体回滚；
4. 按当前用户可见范围与筛选条件（或已勾选缺陷）分批导出 `.xlsx`，默认排除敏感接口详情，
   开启接口详情导出时应用脱敏规则并在说明页标记。

协作模块：
- ``DefectService``：复用列表筛选查询与同事务建单逻辑（不破坏既有批量创建 API 提交语义）；
- ``DefectImportBatch``：持久化预览快照、唯一约束防重与最近成功批次提示；
- ``app.core.security.sensitive`` / ``sanitizer``：接口详情导出脱敏。

已知限制：
- 首版仅支持无宏 `.xlsx` 且仅创建新缺陷，不支持按缺陷 ID 更新存量缺陷；
- CSV 导出、附件/活动历史/分享凭证导出未接入，属后续阶段。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, status
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.http.errors import CODE_CONFLICT, bad_request, not_found
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.core.security.sensitive import mask_header_text
from app.features.defects.models.bug import Bug
from app.features.defects.models.import_batch import DefectImportBatch
from app.features.defects.schemas import (
    API_METHODS,
    BUG_CATEGORIES,
    PRIORITY_LABELS,
    SEVERITY_LABELS,
    BugBatchItem,
    DefectExportRequest,
    DefectImportConfirmRequest,
    DefectImportConfirmResponse,
    DefectImportCreatedItem,
    DefectImportDuplicateWarning,
    DefectImportPreviewItem,
    DefectImportPreviewResponse,
    DefectImportRecentBatch,
    DefectImportRowError,
    normalize_bug_category,
)
from app.features.defects.services.defect_service import DefectService, status_display
from app.platform.projects.services.access_service import check_writable, get_project_or_404

# 模板与安全上限常量。
TEMPLATE_VERSION = "v1"
DETAIL_SHEET_NAME = "缺陷明细"
GUIDE_SHEET_NAME = "填写说明"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 压缩文件上限 5 MiB
MAX_ZIP_ENTRIES = 2000  # ZIP 条目数上限，防压缩炸弹
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 解压后总大小上限 50 MiB
MAX_SHEET_COLUMNS = 256  # 单表最大允许列数
MAX_SCAN_ROWS = 5000  # 预览扫描最大物理行数，防超大空表消耗内存
MAX_IMPORT_ROWS = 100  # 与 BugBatchCreate 保持一致，每次 1–100 条
MAX_EXPORT_ROWS = 5000  # 单次导出上限，超限要求收窄筛选，避免静默截断
EXPORT_BATCH_SIZE = 500  # 导出分批读取大小，控制峰值内存并避免前端翻页拼接
EXCEL_CELL_MAX_LENGTH = 32767  # Excel 单单元格字符上限
PREVIEW_TTL_MINUTES = 30  # 预览标识有效期（分钟）
EXPORT_TIMEZONE = timezone(timedelta(hours=8))
EXPORT_TIMEZONE_LABEL = "UTC+8"

# OLE2 复合文档魔数（旧版 .xls 或加密工作簿）。
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# 可导入的业务列定义：(表头中文名, 内部字段名, 建议列宽, 是否按文本格式预设)
IMPORT_COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
    ("标题", "title", 34, True),
    ("前后端划分", "category", 14, False),
    ("描述", "description", 36, True),
    ("复现步骤", "steps_to_reproduce", 40, True),
    ("预期结果", "expected_result", 32, True),
    ("实际结果", "actual_result", 32, True),
    ("严重度", "severity", 12, False),
    ("优先级", "priority", 12, False),
    ("发现环境", "environment", 18, True),
    ("影响版本", "affected_version", 16, True),
    ("请求方法", "api_method", 12, False),
    ("请求地址", "api_url", 36, True),
    ("请求头", "api_request_headers", 36, True),
    ("请求体", "api_request_body", 40, True),
    ("实际响应结果", "api_response", 40, True),
)

# 仅接口缺陷允许填写的字段集合（内部字段名 -> 中文表头）。
API_ONLY_FIELDS: dict[str, str] = {
    "api_method": "请求方法",
    "api_url": "请求地址",
    "api_request_headers": "请求头",
    "api_request_body": "请求体",
    "api_response": "实际响应结果",
}

# 各文本字段的长度上限，严格对齐 BugBase 契约。
FIELD_MAX_LENGTHS: dict[str, int] = {
    "title": 200,
    "description": 1000,
    "steps_to_reproduce": EXCEL_CELL_MAX_LENGTH,
    "expected_result": 4000,
    "actual_result": 4000,
    "environment": 200,
    "affected_version": 100,
    "api_url": 500,
    "api_request_headers": 2000,
    "api_request_body": 5000,
    "api_response": 5000,
}

# 允许保留单元格内换行的多行文本字段。
MULTILINE_FIELDS: frozenset[str] = frozenset({
    "description",
    "steps_to_reproduce",
    "expected_result",
    "actual_result",
    "api_request_headers",
    "api_request_body",
    "api_response",
})

# 表头到内部字段的映射（含导出只读列及其带时区别名）。
HEADER_TO_FIELD: dict[str, str] = {
    **{header: field for header, field, _, _ in IMPORT_COLUMNS},
    "缺陷 ID": "__bug_id__",
    "缺陷ID": "__bug_id__",
    "当前状态": "__status__",
    "报告人": "__reporter__",
    "创建时间": "__created_at__",
    f"创建时间（{EXPORT_TIMEZONE_LABEL}）": "__created_at__",
    "更新时间": "__updated_at__",
    f"更新时间（{EXPORT_TIMEZONE_LABEL}）": "__updated_at__",
}

# 只读系统列集合：不参与写入，其中 __bug_id__ 有值时阻止作为新单导入。
READONLY_SYSTEM_FIELDS: frozenset[str] = frozenset({
    "__bug_id__",
    "__status__",
    "__reporter__",
    "__created_at__",
    "__updated_at__",
})

# 导出默认列（排除请求头、请求体、实际响应结果；开启接口详情后再追加）。
EXPORT_BASE_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("缺陷 ID", "id", 12),
    ("标题", "title", 34),
    ("前后端划分", "category", 14),
    ("当前状态", "status_display", 12),
    ("严重度", "severity", 12),
    ("优先级", "priority", 12),
    ("发现环境", "environment", 18),
    ("影响版本", "affected_version", 16),
    ("描述", "description", 36),
    ("复现步骤", "steps_to_reproduce", 40),
    ("预期结果", "expected_result", 32),
    ("实际结果", "actual_result", 32),
    ("请求方法", "api_method", 12),
    ("请求地址", "api_url", 36),
    ("报告人", "reporter_username", 16),
    (f"创建时间（{EXPORT_TIMEZONE_LABEL}）", "created_at", 22),
    (f"更新时间（{EXPORT_TIMEZONE_LABEL}）", "updated_at", 22),
)

EXPORT_API_DETAIL_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("请求头", "api_request_headers", 36),
    ("请求体", "api_request_body", 40),
    ("实际响应结果", "api_response", 40),
)

# 严重度与优先级反查表：支持 1–4 与对应中文标签。
_SEVERITY_BY_LABEL: dict[str, int] = {
    **{str(k): k for k in SEVERITY_LABELS},
    **{label: k for k, label in SEVERITY_LABELS.items()},
}
_PRIORITY_BY_LABEL: dict[str, int] = {
    **{str(k): k for k in PRIORITY_LABELS},
    **{label: k for k, label in PRIORITY_LABELS.items()},
}

_HEADER_FILL = PatternFill(start_color="E8F1FF", end_color="E8F1FF", fill_type="solid")
_HEADER_FONT = Font(bold=True)
_WRAP_ALIGNMENT = Alignment(vertical="top", wrap_text=True)


def _write_text_cell(ws, row_idx: int, col_idx: int, value: str | None) -> None:
    """显式按纯文本写入单元格，确保以等号或前导零开头的文本显示原文而非公式/数字。"""
    cell = ws.cell(row=row_idx, column=col_idx)
    cell.number_format = "@"
    if value is None or value == "":
        cell.value = None
        return
    cell.value = value
    # 强制设为字符串类型：防止 openpyxl 把 "=SUM(...)" 写成公式节点 <f>。
    cell.data_type = "s"
    cell.alignment = _WRAP_ALIGNMENT


def _format_export_time(value: datetime | None) -> str:
    """将数据库时间按 UTC+8 格式化为可读文本。"""
    if value is None:
        return ""
    if value.tzinfo is not None:
        localized = value.astimezone(EXPORT_TIMEZONE)
    else:
        localized = value
    return localized.strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_export_api_field(field: str, value: str | None) -> str | None:
    """导出接口详情前执行已验证的脱敏规则：请求头走头脱敏+自由文本掩码，请求体/响应走 JSON/文本双层掩码。"""
    if value is None or not value.strip():
        return value
    if field == "api_request_headers":
        return sanitize_text(mask_header_text(value))
    stripped = value.strip()
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        masked = sanitize_context(parsed)
        return json.dumps(masked, ensure_ascii=False)
    return sanitize_text(value)


def _cell_to_text(value: Any, *, preserve_multiline: bool) -> str:
    """将 Excel 单元格值转为字符串，保留前导零文本与单元格内换行。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        # Excel 常把纯数字输入存为 float（如 1.0），整数值去掉末尾 .0 避免破坏等级/编号。
        text = str(int(value)) if value.is_integer() else format(value, "g")
    elif isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(value, date):
        text = value.isoformat()
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip() if not preserve_multiline else text.strip()


def _parse_level(raw_value: Any, mapping: dict[str, int], *, error_message: str) -> tuple[int, str | None]:
    """解析严重度或优先级：空值沿用批量创建默认值 2，支持 1–4 与中文标签。"""
    if raw_value is None:
        return 2, None
    if isinstance(raw_value, bool):
        return 2, error_message
    if isinstance(raw_value, int):
        text = str(raw_value)
    elif isinstance(raw_value, float):
        if not raw_value.is_integer():
            return 2, error_message
        text = str(int(raw_value))
    else:
        text = str(raw_value).strip()
        if not text:
            return 2, None
    parsed = mapping.get(text)
    if parsed is None:
        return 2, error_message
    return parsed, None


def _open_safe_xlsx(content: bytes):
    """校验无宏 .xlsx 合法性、压缩/解压尺寸后打开只读工作簿。

    拒绝旧版 .xls/加密文件、含宏 .xlsm、损坏压缩包及超大解压包，
    防止不受信任的文件消耗服务端内存或触发解析漏洞。
    """
    if not content:
        raise ValueError("上传文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("文件超过 5 MiB 上限，请精简后重新上传")
    if content.startswith(_OLE2_MAGIC):
        raise ValueError("不支持旧版 .xls 或受密码保护的工作簿，请另存为无宏 .xlsx 文件")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise ValueError("工作簿压缩条目过多，无法安全解析")
            total_uncompressed = 0
            names_lower: set[str] = set()
            for entry in entries:
                total_uncompressed += entry.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("工作簿解压后超过 50 MiB 上限，无法安全解析")
                names_lower.add(entry.filename.lower())
            # 拒绝含宏工作簿：存在 vbaProject.bin 或 Content_Types 声明 macroEnabled。
            if any(name.endswith("vbaproject.bin") for name in names_lower):
                raise ValueError("不支持含宏工作簿（.xlsm），请另存为无宏 .xlsx 文件")
            if "[content_types].xml" in names_lower:
                ct_bytes = archive.read("[Content_Types].xml")
                if b"macroenabled" in ct_bytes.lower():
                    raise ValueError("不支持含宏工作簿（.xlsm），请另存为无宏 .xlsx 文件")
    except BadZipFile as exc:
        raise ValueError("文件格式不受支持或已损坏，请上传有效的无宏 .xlsx 文件") from exc
    return load_workbook(BytesIO(content), read_only=True, data_only=False)


def _canonical_content_digest(items: list[dict[str, Any]]) -> str:
    """计算标准化导入数据的 SHA-256 摘要（不含行号，确保相同内容文件命中一致摘要）。"""
    canonical = [
        {k: v for k, v in item.items() if k != "excel_row"}
        for item in items
    ]
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DefectExcelIOService:
    """缺陷 Excel 模板下载、导入预览、幂等确认与分批导出服务。"""

    def __init__(self) -> None:
        self._defects = DefectService()

    # ---------------------------------------------------------------- 模板下载

    def build_template_workbook(
        self, db: Session, *, project_id: int, actor: User
    ) -> tuple[bytes, str]:
        """生成空白缺陷导入模板（.xlsx），含「缺陷明细」与「填写说明」两张表。"""
        # 权限判定：需对目标项目具备写权限（不可见项目返回 404，只读成员返回 403）。
        project = get_project_or_404(db, project_id, actor)
        check_writable(db, project, actor)

        wb = Workbook()
        detail = wb.active
        detail.title = DETAIL_SHEET_NAME
        detail.freeze_panes = "A2"

        headers = [col[0] for col in IMPORT_COLUMNS]
        detail.append(headers)
        for col_idx, (_, _, width, text_format) in enumerate(IMPORT_COLUMNS, start=1):
            col_letter = get_column_letter(col_idx)
            detail.column_dimensions[col_letter].width = width
            header_cell = detail.cell(row=1, column=col_idx)
            header_cell.fill = _HEADER_FILL
            header_cell.font = _HEADER_FONT
            header_cell.alignment = Alignment(vertical="center")
            if text_format:
                # 预设文本格式 @，降低 Excel 把 001.02 改写成数字或日期的概率。
                for row_idx in range(2, MAX_IMPORT_ROWS + 2):
                    detail.cell(row=row_idx, column=col_idx).number_format = "@"

        last_col = get_column_letter(len(IMPORT_COLUMNS))
        detail.auto_filter.ref = f"A1:{last_col}{MAX_IMPORT_ROWS + 1}"

        # 下拉验证仅作录入辅助，最终合法性仍由服务端统一校验。
        validations = (
            ("B", '"前端,前后端,接口"'),
            ("G", '"低,中,高,严重"'),
            ("H", '"低,中,高,紧急"'),
            ("K", '"GET,POST,PUT,DELETE,PATCH,HEAD,OPTIONS"'),
        )
        for col_letter, formula in validations:
            dv = DataValidation(type="list", formula1=formula, allow_blank=True)
            detail.add_data_validation(dv)
            dv.add(f"{col_letter}2:{col_letter}{MAX_IMPORT_ROWS + 1}")

        guide = wb.create_sheet(GUIDE_SHEET_NAME)
        guide.column_dimensions["A"].width = 22
        guide.column_dimensions["B"].width = 48
        guide.column_dimensions["C"].width = 48
        guide_rows = [
            ["模板信息", "说明", "示例 / 备注"],
            ["模板版本", TEMPLATE_VERSION, f"目标项目：{project.name}（#{project.id}）"],
            ["工作表约定", f"请仅在「{DETAIL_SHEET_NAME}」填写待导入缺陷，首行中文表头按列名匹配，允许调换列顺序", "示例放在本说明页，避免误导入"],
            ["单次条数限制", f"每次导入 1–{MAX_IMPORT_ROWS} 条，自动跳过完全空白行，保留原始 Excel 行号", "仅支持无宏 .xlsx，最大 5 MiB"],
            ["导入模式", "首版仅创建新缺陷，新单统一进入「待确认」队列，报告人为当前登录人", "禁止包含公式单元格；带已有缺陷 ID 的行会被阻止导入"],
            ["", "", ""],
            ["列名", "填写规则与允许值", "说明"],
            ["标题", "必填，去首尾空格后 1–200 字", "同一项目允许重复标题，预览会提示文件内重复项"],
            ["前后端划分", "可空；支持：前端、前后端、接口（历史值「后端」自动映射为「接口」）", "留空表示未划分"],
            ["描述", "可空，最多 1000 字，支持单元格内换行", ""],
            ["复现步骤", "可空，支持单元格内换行", "建议按 1. 2. 3. 分行填写"],
            ["预期结果", "可空，最多 4000 字，支持单元格内换行", ""],
            ["实际结果", "可空，最多 4000 字，支持单元格内换行", ""],
            ["严重度", "可空；接受 1–4 或 低、中、高、严重（4=严重）", "留空默认 2（中）"],
            ["优先级", "可空；接受 1–4 或 低、中、高、紧急（4=紧急）", "留空默认 2（中）"],
            ["发现环境", "可空，最多 200 字，按文本读取", "如 staging / 001.02"],
            ["影响版本", "可空，最多 100 字，按文本读取", "如 001.02 / v2.3.0"],
            ["请求方法", "接口缺陷专用：GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS", "前后端划分非「接口」时填写将报错"],
            ["请求地址", "接口缺陷专用，最多 500 字", "前后端划分非「接口」时填写将报错"],
            ["请求头", "接口缺陷专用，最多 2000 字；落库自动脱敏敏感凭证", "前后端划分非「接口」时填写将报错"],
            ["请求体", "接口缺陷专用，最多 5000 字，支持带引号和换行的 JSON", "前后端划分非「接口」时填写将报错"],
            ["实际响应结果", "接口缺陷专用，最多 5000 字", "前后端划分非「接口」时填写将报错"],
            ["", "", ""],
            ["填写示例（请勿直接在此页导入，复制到「缺陷明细」使用）", "", ""],
            [
                "示例 1（前端缺陷）",
                "标题：登录按钮在窄屏下被遮挡 | 前后端划分：前端 | 严重度：高 | 优先级：紧急 | 发现环境：staging | 影响版本：001.02",
                "复现步骤：1. 打开登录页\n2. 调整宽度至 375px\n3. 观察底部按钮",
            ],
            [
                "示例 2（接口缺陷）",
                "标题：提交订单返回 500 | 前后端划分：接口 | 严重度：严重 | 优先级：4 | 请求方法：POST | 请求地址：/api/v1/orders",
                '请求体：{"sku": "A-01", "note": "含逗号,与\\"引号\\""}',
            ],
        ]
        for r_idx, row in enumerate(guide_rows, start=1):
            for c_idx, val in enumerate(row, start=1):
                _write_text_cell(guide, r_idx, c_idx, val)
                if r_idx in (1, 7, 24):
                    cell = guide.cell(row=r_idx, column=c_idx)
                    cell.fill = _HEADER_FILL
                    cell.font = _HEADER_FONT

        output = BytesIO()
        wb.save(output)
        filename = f"defect-import-template-project-{project.id}.xlsx"
        return output.getvalue(), filename

    # ---------------------------------------------------------------- 导入预览

    def preview_import(
        self,
        db: Session,
        *,
        project_id: int,
        file_name: str,
        content: bytes,
        actor: User,
    ) -> DefectImportPreviewResponse:
        """解析并校验上传工作簿；无任何错误时落库预览快照并签发 preview_token。"""
        # 权限判定：预览前先验证目标项目可见且可写。
        project = get_project_or_404(db, project_id, actor)
        check_writable(db, project, actor)

        clean_name = (file_name or "defects.xlsx").replace("\\", "/").split("/")[-1][:255] or "defects.xlsx"
        file_hash = hashlib.sha256(content).hexdigest()
        errors: list[DefectImportRowError] = []
        warnings: list[str] = []
        unknown_columns: list[str] = []
        ignored_system_columns: list[str] = []
        preview_items: list[DefectImportPreviewItem] = []
        normalized_payload: list[dict[str, Any]] = []

        if not clean_name.lower().endswith(".xlsx"):
            errors.append(DefectImportRowError(
                row=0, column="文件格式", message="仅支持无宏 .xlsx 工作簿，请转换后重新上传",
            ))
            return self._empty_preview(project.id, clean_name, file_hash, errors)

        workbook = None
        try:
            workbook = _open_safe_xlsx(content)
            if DETAIL_SHEET_NAME not in workbook.sheetnames:
                errors.append(DefectImportRowError(
                    row=0,
                    column="工作表",
                    message=f"工作簿缺少「{DETAIL_SHEET_NAME}」工作表，请使用标准模板",
                ))
                return self._empty_preview(project.id, clean_name, file_hash, errors)

            sheet = workbook[DETAIL_SHEET_NAME]
            max_col = sheet.max_column or 0
            max_row = sheet.max_row or 0
            if max_col > MAX_SHEET_COLUMNS:
                errors.append(DefectImportRowError(
                    row=0, column="工作表范围", message=f"工作表列数（{max_col}）超过上限 {MAX_SHEET_COLUMNS}",
                ))
                return self._empty_preview(project.id, clean_name, file_hash, errors)
            if max_row > MAX_SCAN_ROWS:
                errors.append(DefectImportRowError(
                    row=0,
                    column="工作表范围",
                    message=f"工作表行数（{max_row}）超过最大扫描范围 {MAX_SCAN_ROWS}，请清理多余空行后重试",
                ))
                return self._empty_preview(project.id, clean_name, file_hash, errors)

            # 解析首行表头：按中文列名映射，拒绝公式表头、缺失必需表头和重复映射。
            header_rows = list(sheet.iter_rows(min_row=1, max_row=1, values_only=False))
            if not header_rows:
                errors.append(DefectImportRowError(row=1, column="表头", message="首行表头为空"))
                return self._empty_preview(project.id, clean_name, file_hash, errors)

            header_cells = header_rows[0]
            col_map: dict[int, tuple[str, str]] = {}  # 0-based col_idx -> (field_key, raw_header)
            seen_fields: dict[str, str] = {}
            seen_raw_headers: set[str] = set()
            header_names_by_idx: dict[int, str] = {}

            for idx, cell in enumerate(header_cells):
                col_label = f"第 {idx + 1} 列"
                if cell.data_type == "f":
                    errors.append(DefectImportRowError(
                        row=1, column=col_label, message="表头不允许使用公式单元格，请转换为纯文本",
                    ))
                    continue
                raw_header = _cell_to_text(cell.value, preserve_multiline=False)
                if not raw_header:
                    continue
                header_names_by_idx[idx] = raw_header
                if raw_header in seen_raw_headers:
                    errors.append(DefectImportRowError(
                        row=1, column=raw_header, message=f"表头「{raw_header}」重复出现，请去重后再上传",
                    ))
                    continue
                seen_raw_headers.add(raw_header)

                field_key = HEADER_TO_FIELD.get(raw_header)
                if field_key is None:
                    unknown_columns.append(raw_header)
                    continue
                if field_key in seen_fields:
                    errors.append(DefectImportRowError(
                        row=1,
                        column=raw_header,
                        message=f"表头「{raw_header}」与「{seen_fields[field_key]}」重复映射到同一字段，请保留其一",
                    ))
                    continue
                seen_fields[field_key] = raw_header
                col_map[idx] = (field_key, raw_header)
                if field_key in READONLY_SYSTEM_FIELDS:
                    ignored_system_columns.append(raw_header)

            if "title" not in seen_fields:
                errors.append(DefectImportRowError(
                    row=1, column="标题", message="缺少必需表头「标题」，请使用标准模板",
                ))
            if unknown_columns:
                warnings.append("存在未识别的列，导入时将忽略：" + "、".join(unknown_columns))
            if ignored_system_columns:
                warnings.append(
                    "检测到导出只读系统列（"
                    + "、".join(ignored_system_columns)
                    + "），系统字段不参与写入；请确保「缺陷 ID」列为空，所有记录均将作为新缺陷创建"
                )
            if errors:
                return self._empty_preview(
                    project.id,
                    clean_name,
                    file_hash,
                    errors,
                    unknown_columns=unknown_columns,
                    ignored_system_columns=ignored_system_columns,
                    warnings=warnings,
                )

            # 逐行解析数据，跳过完全空白行并保留原始 Excel 行号。
            non_empty_count = 0
            for excel_row, row_cells in enumerate(sheet.iter_rows(min_row=2, values_only=False), start=2):
                is_blank = True
                for cell in row_cells:
                    if cell.data_type == "f":
                        is_blank = False
                        break
                    if cell.value is not None and str(cell.value).strip() != "":
                        is_blank = False
                        break
                if is_blank:
                    continue

                non_empty_count += 1
                if non_empty_count > MAX_IMPORT_ROWS:
                    continue

                row_errors_before = len(errors)
                # 先检测当前行任意单元格是否包含公式（包括未知列，杜绝隐藏公式绕过）。
                for idx, cell in enumerate(row_cells):
                    if cell.data_type == "f":
                        col_name = header_names_by_idx.get(idx) or f"第 {idx + 1} 列"
                        errors.append(DefectImportRowError(
                            row=excel_row,
                            column=col_name,
                            message="不支持公式单元格，请先转换为纯文本或值",
                        ))

                row_values: dict[str, Any] = {}
                for idx, (field_key, _raw_header) in col_map.items():
                    cell = row_cells[idx] if idx < len(row_cells) else None
                    row_values[field_key] = None if (cell is None or cell.data_type == "f") else cell.value

                # 含已有缺陷 ID 的行阻止作为新单导入，防止把导出文件误当成更新文件。
                bug_id_text = _cell_to_text(row_values.get("__bug_id__"), preserve_multiline=False)
                if bug_id_text:
                    errors.append(DefectImportRowError(
                        row=excel_row,
                        column="缺陷 ID",
                        message="含已有缺陷 ID，不能作为新单导入；如需复制为新单请清空「缺陷 ID」列",
                    ))

                title = _cell_to_text(row_values.get("title"), preserve_multiline=False)
                if not title:
                    errors.append(DefectImportRowError(
                        row=excel_row, column="标题", message="标题不能为空，请输入 1–200 字",
                    ))
                elif len(title) > FIELD_MAX_LENGTHS["title"]:
                    errors.append(DefectImportRowError(
                        row=excel_row, column="标题", message="标题长度不能超过 200 字",
                    ))

                raw_category = _cell_to_text(row_values.get("category"), preserve_multiline=False)
                category: str | None = None
                if raw_category:
                    normalized_cat = normalize_bug_category(raw_category)
                    if normalized_cat not in BUG_CATEGORIES:
                        errors.append(DefectImportRowError(
                            row=excel_row,
                            column="前后端划分",
                            message="请输入「前端」「前后端」或「接口」（历史值「后端」会自动映射为「接口」）",
                        ))
                    else:
                        category = normalized_cat

                severity, sev_err = _parse_level(
                    row_values.get("severity"),
                    _SEVERITY_BY_LABEL,
                    error_message="请输入 1–4 或低、中、高、严重",
                )
                if sev_err:
                    errors.append(DefectImportRowError(row=excel_row, column="严重度", message=sev_err))

                priority, pri_err = _parse_level(
                    row_values.get("priority"),
                    _PRIORITY_BY_LABEL,
                    error_message="请输入 1–4 或低、中、高、紧急",
                )
                if pri_err:
                    errors.append(DefectImportRowError(row=excel_row, column="优先级", message=pri_err))

                text_fields: dict[str, str | None] = {}
                for col_header, field_key, _, _ in IMPORT_COLUMNS:
                    if field_key in ("title", "category", "severity", "priority", "api_method"):
                        continue
                    text = _cell_to_text(
                        row_values.get(field_key),
                        preserve_multiline=field_key in MULTILINE_FIELDS,
                    )
                    if text and len(text) > FIELD_MAX_LENGTHS[field_key]:
                        errors.append(DefectImportRowError(
                            row=excel_row,
                            column=col_header,
                            message=f"内容长度不能超过 {FIELD_MAX_LENGTHS[field_key]} 字",
                        ))
                    text_fields[field_key] = text or None

                raw_api_method = _cell_to_text(row_values.get("api_method"), preserve_multiline=False)
                api_method: str | None = None
                if raw_api_method:
                    upper_method = raw_api_method.upper()
                    if upper_method not in API_METHODS:
                        errors.append(DefectImportRowError(
                            row=excel_row,
                            column="请求方法",
                            message="请输入 GET、POST、PUT、DELETE、PATCH、HEAD 或 OPTIONS",
                        ))
                    else:
                        api_method = upper_method

                # 接口专用字段冲突检查：分类非「接口」但填写了接口专用列时逐列报错，避免静默丢弃。
                populated_api_cols: list[str] = []
                if raw_api_method:
                    populated_api_cols.append(API_ONLY_FIELDS["api_method"])
                for api_field in ("api_url", "api_request_headers", "api_request_body", "api_response"):
                    if text_fields.get(api_field):
                        populated_api_cols.append(API_ONLY_FIELDS[api_field])
                if populated_api_cols and category != "接口":
                    for col_name in populated_api_cols:
                        errors.append(DefectImportRowError(
                            row=excel_row,
                            column=col_name,
                            message="仅前后端划分为「接口」时允许填写接口专用字段，请修改划分或清空该列",
                        ))

                row_valid = len(errors) == row_errors_before
                item = DefectImportPreviewItem(
                    excel_row=excel_row,
                    action="create",
                    title=title,
                    category=category,  # type: ignore[arg-type]
                    description=text_fields["description"],
                    steps_to_reproduce=text_fields["steps_to_reproduce"],
                    expected_result=text_fields["expected_result"],
                    actual_result=text_fields["actual_result"],
                    severity=severity,  # type: ignore[arg-type]
                    priority=priority,  # type: ignore[arg-type]
                    environment=text_fields["environment"],
                    affected_version=text_fields["affected_version"],
                    api_method=api_method,  # type: ignore[arg-type]
                    api_url=text_fields["api_url"],
                    api_request_headers=text_fields["api_request_headers"],
                    api_request_body=text_fields["api_request_body"],
                    api_response=text_fields["api_response"],
                    valid=row_valid,
                )
                preview_items.append(item)
                if row_valid:
                    normalized_payload.append(item.model_dump(exclude={"action", "valid"}))

            if non_empty_count == 0:
                errors.append(DefectImportRowError(
                    row=0,
                    column=DETAIL_SHEET_NAME,
                    message=f"「{DETAIL_SHEET_NAME}」工作表中没有可导入的缺陷行",
                ))
            elif non_empty_count > MAX_IMPORT_ROWS:
                errors.append(DefectImportRowError(
                    row=0,
                    column=DETAIL_SHEET_NAME,
                    message=f"每次最多导入 {MAX_IMPORT_ROWS} 条缺陷，当前文件共 {non_empty_count} 条，请拆分后重新上传",
                ))
        except (OSError, ValueError, KeyError, TypeError, BadZipFile, InvalidFileException) as exc:
            errors.append(DefectImportRowError(row=0, column="工作簿", message=f"无法解析 Excel：{exc}"))
            return self._empty_preview(project.id, clean_name, file_hash, errors)
        finally:
            if workbook is not None:
                workbook.close()

        # 检查文件内重复标题与重复内容（仅提示，不阻断导入）。
        duplicate_warnings = self._detect_file_duplicates(preview_items)
        content_digest = _canonical_content_digest(normalized_payload) if normalized_payload else ""
        recent_batch = (
            self._find_recent_matching_batch(db, project_id=project.id, content_digest=content_digest)
            if content_digest
            else None
        )
        if recent_batch is not None:
            warnings.append(
                f"检测到与历史批次 #{recent_batch.batch_id} 相同的导入内容"
                f"（上次新建 {recent_batch.created_count} 条），如需再次新建请在确认前显式勾选"
            )

        preview_token: str | None = None
        expires_at: datetime | None = None
        if not errors and normalized_payload:
            preview_token = str(uuid.uuid4())
            expires_at = datetime.now() + timedelta(minutes=PREVIEW_TTL_MINUTES)
            batch = DefectImportBatch(
                preview_token=preview_token,
                project_id=project.id,
                created_by=actor.id,
                status="PREVIEW",
                file_name=clean_name,
                file_hash=file_hash,
                content_digest=content_digest,
                row_count=len(normalized_payload),
                payload_json=normalized_payload,
                result_json=None,
                expires_at=expires_at,
            )
            db.add(batch)
            # 事务边界：保存有效预览快照，供确认阶段行锁校验与幂等提交。
            db.commit()

        return DefectImportPreviewResponse(
            project_id=project.id,
            template_version=TEMPLATE_VERSION,
            file_name=clean_name,
            file_hash=file_hash,
            content_digest=content_digest,
            preview_token=preview_token,
            expires_at=expires_at,
            total_rows=len(preview_items),
            valid_rows=sum(1 for item in preview_items if item.valid),
            unknown_columns=unknown_columns,
            ignored_system_columns=ignored_system_columns,
            warnings=warnings,
            duplicate_warnings=duplicate_warnings,
            recent_matching_batch=recent_batch,
            errors=errors,
            items=preview_items,
        )

    # ---------------------------------------------------------------- 确认导入

    def confirm_import(
        self,
        db: Session,
        *,
        body: DefectImportConfirmRequest,
        actor: User,
    ) -> DefectImportConfirmResponse:
        """确认导入：二次校验项目写权限，行锁防并发重复，单事务写入缺陷、活动、通知与回执。"""
        # 权限判定：确认阶段必须重新校验项目可见性与写权限（覆盖预览后权限变化）。
        project = get_project_or_404(db, body.project_id, actor)
        check_writable(db, project, actor)

        # 并发控制：行锁 + populate_existing 保证同一预览并发双点严格串行且读到最新已提交状态。
        batch = (
            db.query(DefectImportBatch)
            .filter(DefectImportBatch.preview_token == body.preview_token)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if batch is None or batch.project_id != project.id or batch.created_by != actor.id:
            raise not_found("导入预览不存在或已失效，请重新上传预览")

        if batch.status == "COMMITTED" and batch.result_json:
            # 同一预览的重试或并发第二请求直接返回已提交回执，绝不重复建单。
            receipt = dict(batch.result_json)
            receipt["replayed"] = True
            return DefectImportConfirmResponse(**receipt)

        if datetime.now() > batch.expires_at:
            raise bad_request("导入预览已过期，请重新上传文件并预览")

        rows = batch.payload_json or []
        if not rows or len(rows) > MAX_IMPORT_ROWS:
            raise bad_request("导入预览数据无效或超出单次上限，请重新上传预览")

        # 相同文件内容重传防误建：若同项目存在历史成功批次且未显式确认，返回 409。
        recent_batch = self._find_recent_matching_batch(
            db, project_id=project.id, content_digest=batch.content_digest, exclude_batch_id=batch.id
        )
        if recent_batch is not None and not body.confirm_duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": CODE_CONFLICT,
                    "message": (
                        f"检测到与历史批次 #{recent_batch.batch_id} 相同的导入内容"
                        f"（已新建 {recent_batch.created_count} 条），请确认是否仍要再次新建"
                    ),
                    "meta": {"recent_matching_batch": recent_batch.model_dump(mode="json")},
                },
            )

        try:
            bug_items = [
                BugBatchItem(**{k: v for k, v in row.items() if k != "excel_row"})
                for row in rows
            ]
            created_bugs = self._defects.create_bugs_in_transaction(
                db,
                project=project,
                items=bug_items,
                actor=actor,
                activity_detail={
                    "source": "excel_import",
                    "import_batch_id": batch.id,
                    "file_name": batch.file_name,
                },
            )
            created_items = [
                DefectImportCreatedItem(
                    excel_row=int(row["excel_row"]),
                    bug_id=bug.id,
                    title=bug.title,
                )
                for row, bug in zip(rows, created_bugs, strict=True)
            ]
            receipt_data = {
                "batch_id": batch.id,
                "preview_token": batch.preview_token,
                "project_id": project.id,
                "created_count": len(created_items),
                "replayed": False,
                "items": [item.model_dump() for item in created_items],
            }
            batch.status = "COMMITTED"
            batch.committed_at = datetime.now()
            batch.result_json = receipt_data
            # 事务边界：缺陷、活动、通知与导入回执在同一个数据库事务中原子提交。
            db.commit()
            return DefectImportConfirmResponse(**receipt_data)
        except Exception:
            # 失败整体回滚，避免留下部分缺陷或半提交回执。
            db.rollback()
            raise

    # ---------------------------------------------------------------- 导出 Excel

    def export_bugs(
        self,
        db: Session,
        *,
        body: DefectExportRequest,
        actor: User,
    ) -> tuple[bytes, str, int]:
        """按当前用户权限与筛选条件（或已勾选 ID）分批读取并导出无宏 .xlsx。"""
        # 权限判定：校验目标项目可见（viewer+），不可见项目按 404 隐藏存在性。
        project = get_project_or_404(db, body.project_id, actor)

        if body.mode == "selected":
            unique_ids = list(dict.fromkeys(bug_id for bug_id in body.bug_ids if bug_id > 0))
            if not unique_ids:
                raise bad_request("请先勾选需要导出的缺陷")
            if len(unique_ids) > MAX_EXPORT_ROWS:
                raise bad_request(f"单次最多导出 {MAX_EXPORT_ROWS} 条缺陷，请减少勾选数量后重试")
            base_query = db.query(Bug).filter(
                Bug.project_id == project.id,
                Bug.id.in_(unique_ids),
                # 草稿只对创建者可见，导出同样遵守此可见性边界。
                or_(Bug.is_draft.is_(False), Bug.reporter_id == actor.id),
            )
            matched_ids = {row_id for (row_id,) in base_query.with_entities(Bug.id).all()}
            missing_ids = [bug_id for bug_id in unique_ids if bug_id not in matched_ids]
            if missing_ids:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": CODE_CONFLICT,
                        "message": "部分已勾选缺陷已删除、移出当前项目或无权访问，请刷新列表后重新选择",
                        "meta": {"missing_ids": missing_ids},
                    },
                )
            total = len(unique_ids)
            ordered_query = base_query.order_by(*self._defects.list_order_columns(body.sort))
        else:
            filtered_query = self._defects.build_list_query(
                db,
                user=actor,
                project_id=project.id,
                category=body.category,
                status=body.status,
                severity=body.severity,
                priority=body.priority,
                affected_version=body.affected_version,
                status_group=body.status_group,
                mine=body.mine,
                include_archived=body.include_archived,
                include_drafts=body.include_drafts,
                view=body.view,
                updated_after=body.updated_after,
                updated_before=body.updated_before,
                keyword=body.keyword,
            )
            total = int(filtered_query.count())
            if total == 0:
                raise bad_request("当前筛选条件下没有可导出的缺陷")
            if total > MAX_EXPORT_ROWS:
                raise bad_request(
                    f"当前筛选结果共 {total} 条，超过单次导出上限 {MAX_EXPORT_ROWS} 条，请收窄筛选条件后重试"
                )
            ordered_query = filtered_query.order_by(*self._defects.list_order_columns(body.sort))

        columns = (
            EXPORT_BASE_COLUMNS + EXPORT_API_DETAIL_COLUMNS
            if body.include_api_details
            else EXPORT_BASE_COLUMNS
        )

        wb = Workbook()
        detail = wb.active
        detail.title = DETAIL_SHEET_NAME
        detail.freeze_panes = "A2"
        detail.append([col[0] for col in columns])
        for col_idx, (_, _, width) in enumerate(columns, start=1):
            col_letter = get_column_letter(col_idx)
            detail.column_dimensions[col_letter].width = width
            header_cell = detail.cell(row=1, column=col_idx)
            header_cell.fill = _HEADER_FILL
            header_cell.font = _HEADER_FONT
            header_cell.alignment = Alignment(vertical="center")

        # 分批读取数据库，并按批一次性加载报告人用户名，避免 N+1 查询与内存峰值暴涨。
        written = 0
        offset = 0
        while offset < total:
            batch_bugs = ordered_query.offset(offset).limit(EXPORT_BATCH_SIZE).all()
            if not batch_bugs:
                break
            reporter_ids = {bug.reporter_id for bug in batch_bugs if bug.reporter_id is not None}
            reporters = (
                {
                    user_row.id: user_row.username
                    for user_row in db.query(User).filter(User.id.in_(reporter_ids)).all()
                }
                if reporter_ids
                else {}
            )
            for bug in batch_bugs:
                row_values = self._serialize_bug_for_export(
                    bug,
                    reporter_username=reporters.get(bug.reporter_id) if bug.reporter_id else "",
                    include_api_details=body.include_api_details,
                )
                row_idx = written + 2
                for col_idx, (col_header, field_key, _) in enumerate(columns, start=1):
                    text_val = row_values[field_key]
                    if text_val and len(text_val) > EXCEL_CELL_MAX_LENGTH:
                        raise bad_request(
                            f"缺陷 #{bug.id} 的「{col_header}」长度为 {len(text_val)} 字，"
                            f"超过 Excel 单单元格上限（{EXCEL_CELL_MAX_LENGTH} 字），请缩短后重试"
                        )
                    _write_text_cell(detail, row_idx, col_idx, text_val)
                written += 1
            offset += len(batch_bugs)

        last_col = get_column_letter(len(columns))
        detail.auto_filter.ref = f"A1:{last_col}{max(written + 1, 2)}"

        # 附加导出说明页：记录模板版本、时间时区、字段范围与脱敏规则。
        guide = wb.create_sheet(GUIDE_SHEET_NAME)
        guide.column_dimensions["A"].width = 24
        guide.column_dimensions["B"].width = 68
        export_time = datetime.now(EXPORT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        scope_text = "已勾选缺陷" if body.mode == "selected" else "当前项目的筛选结果（全部页）"
        api_detail_note = (
            "已启用接口详情导出：请求头、请求体、实际响应结果均已按平台脱敏规则（mask_header_text / sanitize_context / sanitize_text）掩码处理敏感凭证"
            if body.include_api_details
            else "默认仅导出常规事实字段，已排除请求头、请求体、实际响应结果"
        )
        guide_rows = [
            ["说明项", "内容"],
            ["模板版本", TEMPLATE_VERSION],
            ["目标项目", f"{project.name}（#{project.id}）"],
            ["导出范围", f"{scope_text}，共 {written} 条"],
            ["导出时间与时区", f"{export_time}（{EXPORT_TIMEZONE_LABEL}，工作簿中所有时间列均采用 {EXPORT_TIMEZONE_LABEL}）"],
            ["字段与脱敏说明", api_detail_note],
            ["重新导入提示", "含「缺陷 ID」的行会被阻止作为新单导入；如需基于导出文件复制为新缺陷，请先清空「缺陷 ID」列，且当前状态/报告人/时间等系统列不会写入"],
            ["未包含内容", "附件文件、活动历史与公开分享凭证不进入工作簿"],
        ]
        for r_idx, row in enumerate(guide_rows, start=1):
            for c_idx, val in enumerate(row, start=1):
                _write_text_cell(guide, r_idx, c_idx, val)
                if r_idx == 1:
                    cell = guide.cell(row=r_idx, column=c_idx)
                    cell.fill = _HEADER_FILL
                    cell.font = _HEADER_FONT

        output = BytesIO()
        wb.save(output)
        timestamp_slug = datetime.now(EXPORT_TIMEZONE).strftime("%Y%m%d-%H%M%S")
        filename = f"defects-project-{project.id}-{timestamp_slug}.xlsx"
        return output.getvalue(), filename, written

    # ---------------------------------------------------------------- 内部辅助

    @staticmethod
    def _serialize_bug_for_export(
        bug: Bug,
        *,
        reporter_username: str,
        include_api_details: bool,
    ) -> dict[str, str]:
        """将单个 Bug 转为导出单元格文本映射，统一展示名、时区与脱敏口径。"""
        row = {
            "id": str(bug.id),
            "title": bug.title or "",
            "category": bug.category or "",
            "status_display": status_display(bug.status),
            "severity": SEVERITY_LABELS.get(bug.severity, str(bug.severity)),
            "priority": PRIORITY_LABELS.get(bug.priority, str(bug.priority)),
            "environment": bug.environment or "",
            "affected_version": bug.affected_version or "",
            "description": bug.description or "",
            "steps_to_reproduce": bug.steps_to_reproduce or "",
            "expected_result": bug.expected_result or "",
            "actual_result": bug.actual_result or "",
            "api_method": bug.api_method or "",
            "api_url": bug.api_url or "",
            "reporter_username": reporter_username,
            "created_at": _format_export_time(bug.created_at),
            "updated_at": _format_export_time(bug.updated_at),
        }
        if include_api_details:
            row["api_request_headers"] = _sanitize_export_api_field("api_request_headers", bug.api_request_headers) or ""
            row["api_request_body"] = _sanitize_export_api_field("api_request_body", bug.api_request_body) or ""
            row["api_response"] = _sanitize_export_api_field("api_response", bug.api_response) or ""
        return row

    @staticmethod
    def _detect_file_duplicates(
        items: list[DefectImportPreviewItem],
    ) -> list[DefectImportDuplicateWarning]:
        """检测文件内部相同标题与完全相同内容的行，生成非阻断提示。"""
        by_title: dict[str, list[int]] = defaultdict(list)
        by_content: dict[str, tuple[str, list[int]]] = {}
        for item in items:
            if not item.title:
                continue
            by_title[item.title].append(item.excel_row)
            key_payload = item.model_dump(exclude={"excel_row", "action", "valid"})
            content_key = json.dumps(key_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if content_key not in by_content:
                by_content[content_key] = (item.title, [item.excel_row])
            else:
                by_content[content_key][1].append(item.excel_row)

        result: list[DefectImportDuplicateWarning] = []
        exact_row_groups: set[tuple[int, ...]] = set()
        for title, rows in by_content.values():
            if len(rows) > 1:
                exact_row_groups.add(tuple(rows))
                row_text = "、".join(f"第 {r} 行" for r in rows)
                result.append(DefectImportDuplicateWarning(
                    kind="same_content",
                    title=title,
                    rows=rows,
                    message=f"{row_text} 的标题与字段内容完全相同（{title}），请确认是否重复录入",
                ))
        for title, rows in by_title.items():
            if len(rows) > 1 and tuple(rows) not in exact_row_groups:
                row_text = "、".join(f"第 {r} 行" for r in rows)
                result.append(DefectImportDuplicateWarning(
                    kind="same_title",
                    title=title,
                    rows=rows,
                    message=f"{row_text} 存在相同标题「{title}」，同一项目允许重复标题，可按需修改",
                ))
        return result

    @staticmethod
    def _find_recent_matching_batch(
        db: Session,
        *,
        project_id: int,
        content_digest: str,
        exclude_batch_id: int | None = None,
    ) -> DefectImportRecentBatch | None:
        """查找同项目最近一次提交成功的同内容导入批次。"""
        query = db.query(DefectImportBatch).filter(
            DefectImportBatch.project_id == project_id,
            DefectImportBatch.content_digest == content_digest,
            DefectImportBatch.status == "COMMITTED",
        )
        if exclude_batch_id is not None:
            query = query.filter(DefectImportBatch.id != exclude_batch_id)
        latest = query.order_by(DefectImportBatch.committed_at.desc(), DefectImportBatch.id.desc()).first()
        if latest is None:
            return None
        creator = db.get(User, latest.created_by) if latest.created_by else None
        return DefectImportRecentBatch(
            batch_id=latest.id,
            committed_at=latest.committed_at,
            created_count=latest.row_count,
            created_by_username=creator.username if creator else None,
            file_name=latest.file_name,
        )

    @staticmethod
    def _empty_preview(
        project_id: int,
        file_name: str,
        file_hash: str,
        errors: list[DefectImportRowError],
        *,
        unknown_columns: list[str] | None = None,
        ignored_system_columns: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> DefectImportPreviewResponse:
        """构造含阻断错误的预览响应（不签发 preview_token）。"""
        return DefectImportPreviewResponse(
            project_id=project_id,
            template_version=TEMPLATE_VERSION,
            file_name=file_name,
            file_hash=file_hash,
            content_digest="",
            preview_token=None,
            expires_at=None,
            total_rows=0,
            valid_rows=0,
            unknown_columns=unknown_columns or [],
            ignored_system_columns=ignored_system_columns or [],
            warnings=warnings or [],
            errors=errors,
            items=[],
        )


EXCEL_IO_SERVICE = DefectExcelIOService()
