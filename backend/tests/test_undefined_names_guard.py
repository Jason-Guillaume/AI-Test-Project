"""未定义名字守护：缺失的导入只会在运行到对应分支时以 NameError 暴露，这里在测试阶段提前拦截。"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
GUARDED_MODULES = (
    "app/features/defects/services/share_service.py",
    "app/orchestration/tasks/runtime/worker.py",
    "app/features/asr_evaluation/runtime/funasr_worker.py",
)
MODULE_NAMES = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__"}


def _unbound_names(path: Path) -> list[tuple[int, str]]:
    """返回文件里被读取、却从未被导入、定义或赋值的名字，附带行号。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            bound.update(arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs])
            bound.update(arg.arg for arg in (args.vararg, args.kwarg) if arg is not None)
    return sorted(
        {
            (node.lineno, node.id)
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id not in bound
            and node.id not in MODULE_NAMES
        }
    )


@pytest.mark.parametrize("relative_path", GUARDED_MODULES)
def test_guarded_module_reads_only_bound_names(relative_path):
    """被守护的模块里，每个被读取的名字都必须有导入、定义或赋值。"""
    assert _unbound_names(BACKEND_DIR / relative_path) == []
