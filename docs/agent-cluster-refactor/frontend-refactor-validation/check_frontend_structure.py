#!/usr/bin/env python3
"""Small stdlib-only check for frontend import cycles and layer direction."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3] / 'frontend' / 'src'
FILES = [p for p in ROOT.rglob('*') if p.is_file() and p.suffix in {'.ts', '.tsx', '.mjs'} and not p.name.endswith('.d.ts')]
GRAPHS: dict[Path, set[Path]] = {}
IMPORT = re.compile(r"(?:from\s*|import\s*)['\"]([^'\"]+)['\"]")

def resolve(source: Path, spec: str) -> Path | None:
    if spec.startswith('@/'):
        base = ROOT / spec[2:]
    elif spec.startswith('.'):
        base = source.parent / spec
    else:
        return None
    candidates = [base, *[Path(str(base) + ext) for ext in ('.ts', '.tsx', '.mjs')], base / 'index.ts', base / 'index.tsx', base / 'index.mjs']
    return next((path.resolve() for path in candidates if path.is_file()), None)

for source in FILES:
    resolved_source = source.resolve()
    for spec in IMPORT.findall(source.read_text(errors='ignore')):
        target = resolve(source, spec)
        if target:
            GRAPHS.setdefault(resolved_source, set()).add(target)

state: dict[Path, int] = {}
stack: list[Path] = []
cycles: set[tuple[str, ...]] = set()
def visit(node: Path) -> None:
    state[node] = 1
    stack.append(node)
    for target in GRAPHS.get(node, ()):
        if state.get(target) == 1:
            cycle = stack[stack.index(target):]
            cycles.add(tuple(sorted(p.relative_to(ROOT.resolve()).as_posix() for p in cycle)))
        elif state.get(target, 0) == 0:
            visit(target)
    stack.pop()
    state[node] = 2

for file in FILES:
    if not state.get(file.resolve()):
        visit(file.resolve())

violations = []
for source, targets in GRAPHS.items():
    source_rel = source.relative_to(ROOT.resolve()).as_posix()
    for target in targets:
        target_rel = target.relative_to(ROOT.resolve()).as_posix()
        if source_rel.startswith('shared/') and target_rel.startswith(('features/', 'pages/', 'app/', 'widgets/')):
            violations.append(f'{source_rel} -> {target_rel}')
        if source_rel.startswith('features/') and target_rel.startswith('pages/'):
            violations.append(f'{source_rel} -> {target_rel}')

lines = [f'sources={len(FILES)} importEdges={sum(map(len, GRAPHS.values()))} cycles={len(cycles)} sharedLayerViolations={len(violations)} featureToPageViolations={sum("features/" in x and "pages/" in x for x in violations)}']
lines += [f'CYCLE: {" -> ".join(cycle)}' for cycle in sorted(cycles)]
lines += [f'LAYER: {item}' for item in sorted(violations)]
result = '\n'.join(lines) + '\n'
print(result, end='')
(Path(__file__).resolve().parent / 'frontend-structure-current.txt').write_text(result)
if cycles or violations:
    raise SystemExit(1)
