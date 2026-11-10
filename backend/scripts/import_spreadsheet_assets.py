"""把现有 Excel 测试点和用例、XMind 测试范围导入工作台测试资产。

用法（在 backend/ 目录下）：
    .venv/bin/python scripts/import_spreadsheet_assets.py

只写入当前 DATABASE_URL 指向的库。按目录归入已有项目：
方小集、方小址、兼职分发。不创建项目，不走知识库，不发站内通知。
同一项目里，优化版/重构版优先；已被新版本覆盖的旧文件整份跳过。
同一族内相同「编号 + 标题 + 模块路径」只保留先导入的一条。

用例必须挂到测试点上，否则测试资产树看不到。对不上测试点时，
挂到该用例文件自己的「未挂接」测试点。
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database.session import SessionLocal
from app.core.models.project import Project
# 这些表只被外键引用。不导入的话，flush 时 SQLAlchemy 找不到目标表。
from app.agents.models.session import AgentSession  # noqa: F401
from app.core.models.identity import User  # noqa: F401
from app.features.api_catalog.models.api_interface import ApiInterface  # noqa: F401
from app.features.business.models.business_action import BusinessAction  # noqa: F401
from app.features.business.models.business_flow import BusinessFlow  # noqa: F401
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_case_precondition import TestCasePrecondition
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.models.test_strategy import TestStrategy
from app.features.test_management.titles import optimize_case_title

SOURCE_ROOT = Path("/Users/a1/Desktop/xmind-测试用例汇总")
EXCEL_ROOT = SOURCE_ROOT / "excel"
XMIND_ROOT = SOURCE_ROOT / "测试范围"
ACTOR_ID = 1

# 表格目录对应工作台里已经建好的项目，不按表格里的内部代号另建项目。
FOLDER_PROJECT = {
    "AI混剪": "方小集",
    "PromoFlow后端": "方小集",
    "方小集前台": "方小集",
    "方小集后台": "方小集",
    "方小集脚本后台": "方小集",
    "选址AI": "方小址",
    "选址Genius": "方小址",
    "选址前端": "方小址",
    "选址后端": "方小址",
    "兼职分发": "兼职分发",
}

# 这些文件的内容已经包含在同项目的更新版本里，再导入会变成两套相同资产。
SKIP_FILES = {
    "PromoFlow后端/PromoFlow-业务接口测试用例-完整版.xlsx",
    "选址Genius/前端UI功能测试点-重构版.xlsx",
    "选址Genius/前端UI功能测试用例-重构版.xlsx",
    "选址AI/AI调用接口专项测试点.xlsx",
    "选址AI/AI调用接口专项测试用例.xlsx",
}

POINT_CODE_RE = re.compile(
    r"(?:[A-Z]{1,6}-POINT-\d+(?:-\d+)*|TP-[A-Z0-9]+(?:-[A-Z0-9]+)*)"
)
WS_RE = re.compile(r"[ \t]+")
STEP_SPLIT_RE = re.compile(r"\n+|；|;")


def clean(value) -> str:
    """把单元格收成去掉首尾空白的字符串。空单元格得到空串。"""
    if value is None:
        return ""
    return str(value).strip()


def clip(value: str, limit: int) -> str:
    """截断到数据库字段长度，避免写入时被拒。"""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def norm(value: str) -> str:
    """折叠空白后用于判重，不改变入库文本。"""
    return WS_RE.sub(" ", value).strip().lower()


def priority_of(value: str) -> str:
    """只接受 P0–P3，表格里的空优先级按 P1。"""
    matched = re.search(r"P[0-3]", value or "")
    return matched.group(0) if matched else "P1"


def category_of(name: str) -> str:
    """用文件名里的维度词选择策略类别，对不上时用功能策略。"""
    if any(word in name for word in ("安全", "ZAP", "SEC")):
        return "SECURITY"
    if any(word in name for word in ("权限", "鉴权")):
        return "PERMISSION"
    if "边界" in name:
        return "BOUNDARY"
    if "异常" in name:
        return "EXCEPTION"
    if "业务" in name:
        return "BUSINESS"
    return "FUNCTIONAL"


def target_of(filename: str) -> str:
    """按文件名判断被测对象。接口和业务要先于「后台」，避免后台接口被标成页面。"""
    if any(word in filename for word in ("接口", "Mock", "ZAP", "API")):
        return "API"
    if "业务" in filename:
        return "BUSINESS_FLOW"
    if any(word in filename for word in ("前端", "前台", "后台", "UI", "功能")):
        return "WEB"
    return "API"


def case_type_of(value: str, filename: str) -> str:
    """把表格里的用例类型收成平台枚举。认不出时按功能用例，原词留在描述里。"""
    text = f"{value} {filename}"
    if any(word in text for word in ("安全", "越权", "ZAP")):
        return "SECURITY"
    if any(word in text for word in ("权限", "鉴权", "角色")):
        return "PERMISSION"
    if "边界" in text:
        return "BOUNDARY"
    if any(word in text for word in ("异常", "负面")):
        return "NEGATIVE"
    if "业务" in text:
        return "BUSINESS"
    return "FUNCTIONAL"


def family_of(folder: str, filename: str) -> str:
    """同一份资产的新旧版本共用一个族，跨端文件不混在一起。"""
    if folder == "方小集前台" and "功能测试点" in filename:
        return "方小集前台-功能测试点"
    if folder == "方小集前台" and "功能测试用例" in filename:
        return "方小集前台-功能测试用例"
    if "后端接口测试点" in filename and folder in {"选址后端", "选址Genius"}:
        return "选址-后端接口测试点"
    return f"{folder}/{filename}"


def file_rank(path: Path) -> tuple:
    """优化版和重构版先入库，旧版只补它们没有的条目。"""
    name = path.name
    score = 0
    if "优化" in name or "重构" in name:
        score -= 2
    if "完整版" in name:
        score += 2
    return (score, str(path))


def is_machine_text(value: str) -> bool:
    """测试点名称列有时塞的是断言 JSON，不能直接当名称。"""
    text = value.lstrip()
    return text.startswith("{") or text.startswith("[") or text.startswith("{'")


def join_desc(parts: list[tuple[str, str]], limit: int = 1000) -> str | None:
    """把有内容的字段拼成描述。超长时截断，完整正文仍放在步骤或断言里。"""
    lines = [f"{label}：{text}" for label, text in parts if text]
    if not lines:
        return None
    return clip("\n".join(lines), limit)


def unique_name(base: str, used: set[str]) -> str:
    """项目内名称唯一。冲突时加序号，而不是覆盖已有资产。"""
    name = clip(re.sub(r"\s+", " ", base).strip() or "未命名", 200)
    if name not in used:
        used.add(name)
        return name
    for index in range(2, 100000):
        suffix = f"·{index}"
        candidate = name[: 200 - len(suffix)] + suffix
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError(f"无法为「{base}」分配唯一名称")


def load_sheet_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
    """读取除目录页以外的数据行。目录页只是索引，不入库。"""
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[tuple[str, dict[str, str]]] = []
    for sheet in workbook.sheetnames:
        if sheet == "目录":
            continue
        worksheet = workbook[sheet]
        iterator = worksheet.iter_rows(values_only=True)
        try:
            header = [clean(cell) for cell in next(iterator)]
        except StopIteration:
            continue
        for raw in iterator:
            if not raw or not any(cell is not None and str(cell).strip() for cell in raw):
                continue
            record = {
                header[index]: clean(raw[index])
                for index in range(min(len(header), len(raw)))
                if header[index]
            }
            rows.append((sheet, record))
    workbook.close()
    return rows


def point_display_name(record: dict[str, str]) -> str:
    """优先用编号加人类可读名称。名称是 JSON 时改用模块路径。"""
    code = record.get("测试点编号", "")
    title = record.get("测试点名称", "")
    path = record.get("模块路径") or record.get("三级模块") or record.get("一级模块") or ""
    if title and not is_machine_text(title):
        return f"{code} {title}".strip()
    if path:
        return path
    return title or "未命名测试点"


def split_steps(value: str) -> list[str]:
    """按换行和分号拆步骤。拆不开时整段作为一步。"""
    text = value.strip()
    if not text:
        return []
    parts = [part.strip() for part in STEP_SPLIT_RE.split(text) if part and part.strip()]
    return parts or [text]


class Importer:
    """一次运行的导入器。名称和判重集合只在本次进程内累积。"""

    def __init__(self, db: Session):
        self.db = db
        self.projects = {row.name: row.id for row in db.query(Project).all()}
        self.used_strategy: dict[int, set[str]] = {}
        self.used_point: dict[int, set[str]] = {}
        self.used_case: dict[int, set[str]] = {}
        # 只记录本次启动前就在库里的名称。本次新写入的重名仍加序号，重跑时才按原名跳过。
        self.existing_strategy: dict[int, set[str]] = {}
        self.existing_point: dict[int, set[str]] = {}
        self.existing_case: dict[int, set[str]] = {}
        self.seen_identity: set[tuple] = set()
        self.point_by_code: dict[tuple[int, str], int] = {}
        self.point_by_title: dict[tuple[int, str], int] = {}
        self.point_by_path: dict[tuple[int, str], int] = {}
        self.summary: dict[str, dict[str, int]] = {}
        self._load_existing_names()

    def _load_existing_names(self) -> None:
        """先占用库里已有名称，重复执行时不会把同名资产再插一遍。"""
        for project_id, name in self.db.query(TestStrategy.project_id, TestStrategy.name):
            self.used_strategy.setdefault(project_id, set()).add(name)
            self.existing_strategy.setdefault(project_id, set()).add(name)
        for project_id, name, point_id in self.db.query(TestPoint.project_id, TestPoint.name, TestPoint.id):
            self.used_point.setdefault(project_id, set()).add(name)
            self.existing_point.setdefault(project_id, set()).add(name)
            self.point_by_title[(project_id, norm(name))] = point_id
            # 重跑时测试点文件会整本跳过，编号只能从已保存的名称里还原，用例才挂得回去。
            matched = POINT_CODE_RE.search(name)
            if matched:
                self.point_by_code.setdefault((project_id, matched.group(0)), point_id)
        for project_id, name in self.db.query(TestCase.project_id, TestCase.name):
            self.used_case.setdefault(project_id, set()).add(name)
            self.existing_case.setdefault(project_id, set()).add(name)

    def project_id(self, folder: str) -> int:
        """目录必须能对应到已有项目，否则停止，避免写进错误项目。"""
        name = FOLDER_PROJECT[folder]
        if name not in self.projects:
            raise SystemExit(f"工作台中没有项目「{name}」，无法导入「{folder}」")
        return self.projects[name]

    def bump(self, project_name: str, key: str, count: int = 1) -> None:
        """累计每个项目的导入数量，供结束时打印。"""
        bucket = self.summary.setdefault(project_name, {})
        bucket[key] = bucket.get(key, 0) + count

    def remember_point(self, project_id: int, point_id: int, record: dict[str, str], stored_name: str) -> None:
        """建立编号、标题、模块路径三个索引，供后续用例挂接。"""
        code = record.get("测试点编号", "")
        if code:
            self.point_by_code[(project_id, code)] = point_id
        title = record.get("测试点名称", "")
        if title and not is_machine_text(title):
            self.point_by_title.setdefault((project_id, norm(title)), point_id)
        self.point_by_title.setdefault((project_id, norm(stored_name)), point_id)
        path = record.get("模块路径", "")
        if path:
            self.point_by_path.setdefault((project_id, norm(path)), point_id)

    def take_new_rows(self, project_name: str, folder: str, filename: str, rows: list[tuple[str, dict]]) -> list:
        """按族丢掉已经导入过的同一条。返回还需要入库的行。"""
        project_id = self.project_id(folder)
        family = family_of(folder, filename)
        fresh = []
        for sheet, record in rows:
            if "测试点名称" in record:
                title = record.get("测试点名称", "")
                code = record.get("测试点编号", "")
            else:
                title = record.get("用例标题", "")
                code = record.get("用例编号", "")
            identity = (project_id, family, norm(code), norm(title), norm(record.get("模块路径", "")))
            if identity in self.seen_identity:
                self.bump(project_name, "重复跳过")
                continue
            self.seen_identity.add(identity)
            fresh.append((sheet, record))
        return fresh

    def create_strategy(self, project_id: int, name: str, description: str, filename: str) -> TestStrategy:
        """新建一条策略。调用方负责提交事务。"""
        strategy = TestStrategy(
            project_id=project_id,
            name=unique_name(name, self.used_strategy.setdefault(project_id, set())),
            description=clip(description, 1000),
            category=category_of(filename),
            enabled=True,
            source_type="MANUAL",
            created_by=ACTOR_ID,
        )
        self.db.add(strategy)
        self.db.flush()
        return strategy

    def import_points(self, folder: str, path: Path) -> None:
        """导入一个测试点工作簿，整本文件使用一条策略。"""
        project_name = FOLDER_PROJECT[folder]
        project_id = self.project_id(folder)
        strategy_name = clip(f"{folder}·{path.stem}", 200)
        if strategy_name in self.existing_strategy.get(project_id, set()):
            print(f"跳过已导入测试点 {folder}/{path.name}")
            return
        rows = self.take_new_rows(project_name, folder, path.name, load_sheet_rows(path))
        if not rows:
            print(f"跳过空测试点 {folder}/{path.name}")
            return
        sample_project = next((record.get("所属项目", "") for _, record in rows if record.get("所属项目")), "")
        strategy = self.create_strategy(
            project_id,
            f"{folder}·{path.stem}",
            f"来源文件：{folder}/{path.name}\n表格项目代号：{sample_project}",
            path.name,
        )
        target = target_of(path.name)
        for sheet, record in rows:
            stored = unique_name(point_display_name(record), self.used_point.setdefault(project_id, set()))
            description = join_desc([
                ("条目类型", record.get("条目类型", "")),
                ("画布", record.get("画布", "")),
                ("模块路径", record.get("模块路径", "")),
                ("测试点描述", record.get("测试点描述", "")),
                ("检查项", record.get("检查项", "")),
                ("接口信息", record.get("接口信息", "")),
                ("关联用例", record.get("关联用例", "")),
                ("原始名称", record.get("测试点名称", "") if is_machine_text(record.get("测试点名称", "")) else ""),
                ("备注", record.get("备注", "")),
                ("工作表", sheet),
            ])
            point = TestPoint(
                project_id=project_id,
                strategy_id=strategy.id,
                name=stored,
                description=description,
                priority=priority_of(record.get("优先级", "")),
                target_type=target,
                status="DRAFT",
                source_type="MANUAL",
                created_by=ACTOR_ID,
            )
            self.db.add(point)
            self.db.flush()
            self.remember_point(project_id, point.id, record, stored)
            self.bump(project_name, "测试点")
        # 一个工作簿一个事务：失败时只回滚这一本，已提交的文件保留。
        self.db.commit()
        print(f"测试点 {folder}/{path.name} -> {project_name} {len(rows)} 条")

    def match_point(self, project_id: int, record: dict[str, str]) -> int | None:
        """按编号、关联测试点标题、模块路径依次挂到已导入的测试点。"""
        blob = " ".join(
            record.get(key, "")
            for key in ("关联测试点", "一级模块", "二级模块", "模块路径", "用例标题")
        )
        for code in POINT_CODE_RE.findall(blob):
            found = self.point_by_code.get((project_id, code))
            if found:
                return found
        related = record.get("关联测试点", "")
        if related:
            found = self.point_by_title.get((project_id, norm(related)))
            if found:
                return found
            for code in POINT_CODE_RE.findall(related):
                found = self.point_by_code.get((project_id, code))
                if found:
                    return found
        path = record.get("模块路径", "")
        if path:
            return self.point_by_path.get((project_id, norm(path)))
        return None

    def add_case_children(self, case_id: int, record: dict[str, str], target: str) -> None:
        """把前置条件、数据、步骤和预期结果写成用例子表，便于在详情里查看。"""
        precondition = record.get("前置条件", "")
        if precondition:
            self.db.add(TestCasePrecondition(
                test_case_id=case_id,
                type="TEXT",
                target="前置条件",
                operator="EQ",
                expected_value=precondition,
                description=clip(precondition, 500),
                sort=0,
            ))
        data_text = record.get("测试数据", "")
        if data_text:
            lines = [line.strip() for line in data_text.splitlines() if line.strip()] or [data_text]
            used_data_names: set[str] = set()
            for index, line in enumerate(lines[:30], start=1):
                name, _, value = line.partition("：")
                if not value:
                    name, _, value = line.partition(":")
                if not value:
                    name, value = f"数据{index}", line
                # 同一用例的数据项名称有唯一约束，重复键加序号。
                name = unique_name(clip(name, 80), used_data_names)
                self.db.add(TestCaseData(
                    test_case_id=case_id,
                    name=clip(name, 100),
                    value_type="STRING",
                    value=value,
                    source_type="STATIC",
                    required=False,
                    description=clip(line, 500),
                    sort=index,
                ))
        steps = split_steps(record.get("步骤描述", ""))
        request = {
            key: record.get(column, "")
            for key, column in (
                ("method", "请求方法"),
                ("path", "请求路径"),
                ("headers", "请求头"),
                ("query", "请求参数"),
                ("body", "请求体"),
            )
            if record.get(column, "")
        }
        if not steps and request:
            steps = ["按表格中的请求执行"]
        for index, step_text in enumerate(steps, start=1):
            config = {"detail": step_text}
            if index == 1 and request:
                config.update(request)
            self.db.add(TestStep(
                test_case_id=case_id,
                name=clip(step_text, 200),
                step_type="ACTION",
                target_type=target,
                sort=index,
                config_json=config,
            ))
        cleanup = record.get("清理与恢复", "")
        if cleanup:
            self.db.add(TestStep(
                test_case_id=case_id,
                name=clip(cleanup, 200),
                step_type="CLEANUP",
                target_type=target,
                sort=len(steps) + 1,
                config_json={"detail": cleanup},
            ))
        sort = 0
        for label, column in (("预期结果", "预期结果"), ("响应断言", "响应断言"), ("数据库校验", "数据库校验")):
            text = record.get(column, "")
            if not text:
                continue
            self.db.add(TestAssertion(
                test_case_id=case_id,
                assertion_type="CONTAINS",
                operator="EQ",
                expected_value=f"{label}：{text}",
                required=True,
                sort=sort,
            ))
            sort += 1

    def import_cases(self, folder: str, path: Path) -> None:
        """导入用例并挂到测试点。挂不上的集中放到本文件的未挂接点。"""
        project_name = FOLDER_PROJECT[folder]
        project_id = self.project_id(folder)
        strategy_name = clip(f"{folder}·{path.stem}", 200)
        if strategy_name in self.existing_strategy.get(project_id, set()):
            print(f"跳过已导入用例 {folder}/{path.name}")
            return
        rows = self.take_new_rows(project_name, folder, path.name, load_sheet_rows(path))
        if not rows:
            print(f"跳过空用例 {folder}/{path.name}")
            return
        target = target_of(path.name)
        linked: list[tuple[str, dict, int]] = []
        orphans: list[tuple[str, dict]] = []
        for sheet, record in rows:
            point_id = self.match_point(project_id, record)
            if point_id:
                linked.append((sheet, record, point_id))
            else:
                orphans.append((sheet, record))
        fallback_id = None
        if orphans:
            strategy = self.create_strategy(
                project_id,
                f"{folder}·{path.stem}",
                f"来源文件：{folder}/{path.name}\n这些用例在已导入的测试点里没有对应编号或模块路径。",
                path.name,
            )
            fallback_name = unique_name(
                f"{path.stem}·未挂接测试点",
                self.used_point.setdefault(project_id, set()),
            )
            fallback = TestPoint(
                project_id=project_id,
                strategy_id=strategy.id,
                name=fallback_name,
                description="导入时没有找到对应测试点，用例暂时挂在这里。",
                priority="P1",
                target_type=target,
                status="DRAFT",
                source_type="MANUAL",
                created_by=ACTOR_ID,
            )
            self.db.add(fallback)
            self.db.flush()
            fallback_id = fallback.id
            self.bump(project_name, "未挂接测试点")
        for sheet, record, point_id in linked:
            self._insert_case(project_id, project_name, point_id, sheet, record, target, path.name)
        for sheet, record in orphans:
            self._insert_case(project_id, project_name, fallback_id, sheet, record, target, path.name)
        self.db.commit()
        print(
            f"用例 {folder}/{path.name} -> {project_name} "
            f"挂接 {len(linked)}，未挂接 {len(orphans)}"
        )

    def _insert_case(self, project_id, project_name, point_id, sheet, record, target, filename) -> None:
        """写入一条用例及其子表。名称冲突时加序号。"""
        code = record.get("用例编号", "")
        title = record.get("用例标题", "") or record.get("模块路径", "") or "未命名用例"
        # 入库前先整理标题，避免 UNRESOLVED 和重复编号再写进名称。
        preferred = clip(optimize_case_title(f"{code} {title}".strip()), 200)
        if preferred in self.existing_case.get(project_id, set()):
            self.bump(project_name, "用例已存在")
            return
        stored = unique_name(preferred, self.used_case.setdefault(project_id, set()))
        description = join_desc([
            ("画布", record.get("画布", "")),
            ("模块路径", record.get("模块路径", "")),
            ("关联测试点", record.get("关联测试点", "")),
            ("用例类型", record.get("用例类型", "")),
            ("执行状态", record.get("执行状态", "")),
            ("自动化", record.get("自动化", "")),
            ("数据与副作用", record.get("数据与副作用", "")),
            ("备注", record.get("备注", "")),
            ("原始详情", record.get("原始详情", "")),
            ("工作表", sheet),
        ])
        case = TestCase(
            project_id=project_id,
            test_point_id=point_id,
            name=stored,
            description=description,
            priority=priority_of(record.get("优先级", "")),
            case_type=case_type_of(record.get("用例类型", ""), filename),
            target_type=target,
            status="DRAFT",
            enabled=True,
            revision=1,
            source_type="MANUAL",
            created_by=ACTOR_ID,
        )
        self.db.add(case)
        self.db.flush()
        self.add_case_children(case.id, record, target)
        self.bump(project_name, "用例")

    def import_xmind(self, path: Path, project_name: str) -> None:
        """把脑图每个节点写成该项目下的测试点，策略名用文件名。"""
        project_id = self.projects[project_name]
        strategy_name = clip(f"测试范围·{path.stem}", 200)
        if strategy_name in self.existing_strategy.get(project_id, set()):
            print(f"跳过已存在范围 {path.name}")
            return
        with zipfile.ZipFile(path) as package:
            sheets = json.loads(package.read("content.json"))
        nodes: list[tuple[str, str]] = []

        def walk(node: dict, ancestors: list[str]) -> None:
            title = clean(node.get("title"))
            path_titles = ancestors + ([title] if title else [])
            notes = node.get("notes") or {}
            note_text = ""
            if isinstance(notes, dict):
                plain = notes.get("plain")
                if isinstance(plain, dict):
                    note_text = clean(plain.get("content"))
                elif isinstance(plain, str):
                    note_text = clean(plain)
            if title:
                nodes.append((" / ".join(path_titles), note_text))
            for child in (node.get("children") or {}).get("attached") or []:
                walk(child, path_titles)

        for sheet in sheets if isinstance(sheets, list) else [sheets]:
            root = sheet.get("rootTopic") or sheet
            walk(root, [])
        if not nodes:
            print(f"跳过空范围 {path.name}")
            return
        strategy = self.create_strategy(
            project_id,
            strategy_name,
            f"来源脑图：{path.name}\n节点按大纲路径保存为测试点。",
            path.name,
        )
        for full_path, note in nodes:
            stored = unique_name(f"范围·{full_path}", self.used_point.setdefault(project_id, set()))
            point = TestPoint(
                project_id=project_id,
                strategy_id=strategy.id,
                name=stored,
                description=join_desc([("路径", full_path), ("备注", note)]),
                priority="P1",
                target_type="WEB" if any(word in path.name for word in ("前端", "前台")) else "API",
                status="DRAFT",
                source_type="MANUAL",
                created_by=ACTOR_ID,
            )
            self.db.add(point)
            self.bump(project_name, "范围节点")
        self.db.commit()
        print(f"范围 {path.name} -> {project_name} {len(nodes)} 个节点")


def xmind_project(filename: str) -> str:
    """按脑图文件名归入已有项目。"""
    if filename.startswith(("AI混剪", "PromoFlow", "方小集")):
        return "方小集"
    if filename.startswith("选址"):
        return "方小址"
    raise SystemExit(f"无法判断脑图所属项目：{filename}")


def main() -> None:
    """按测试点、用例、测试范围的顺序导入，保证用例能挂到已有测试点。"""
    excel_files = sorted(
        (path for path in EXCEL_ROOT.rglob("*.xlsx") if not path.name.startswith(".")),
        key=file_rank,
    )
    point_files = []
    case_files = []
    for path in excel_files:
        relative = f"{path.parent.name}/{path.name}"
        if relative in SKIP_FILES:
            print(f"跳过已覆盖文件 {relative}")
            continue
        if "测试点" in path.name:
            point_files.append(path)
        elif "用例" in path.name:
            case_files.append(path)
        else:
            raise SystemExit(f"无法判断文件是测试点还是用例：{relative}")

    db = SessionLocal()
    try:
        importer = Importer(db)
        for path in point_files:
            importer.import_points(path.parent.name, path)
        for path in case_files:
            importer.import_cases(path.parent.name, path)
        for path in sorted(XMIND_ROOT.glob("*.xmind")):
            importer.import_xmind(path, xmind_project(path.name))
        print("完成")
        for project_name, counts in importer.summary.items():
            detail = "，".join(f"{key} {value}" for key, value in counts.items())
            print(f"{project_name}：{detail}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
