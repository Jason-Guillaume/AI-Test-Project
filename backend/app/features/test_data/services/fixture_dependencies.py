"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.test_data.models.fixture import Fixture, FixtureDependency
from app.features.test_data.services.fixture_references import assert_dependency_allowed
from app.features.test_data.services.fixture_validation import raise_cycle
from app.features.test_data.services.fixture_validation import raise_not_found


def add_manual_dependency(db: Session, fixture: Fixture, dep_id: int) -> None:
    """写入一条手动依赖边：校验存在性、归属与自依赖。"""
    target = db.get(Fixture, dep_id)
    if target is None:
        raise_not_found(f"依赖的 Fixture {dep_id} 不存在")
    assert_dependency_allowed(fixture, target)
    add_dependency_row(db, fixture.id, target.id)


def check_cycles(db: Session, start_ids: set[int]) -> None:
    """检查`cycles`。"""
    path = find_cycle(db, start_ids)
    if path is not None:
        raise_cycle(cycle_message(db, path))


def find_cycle(db: Session, start_ids: set[int], *, max_nodes: int = 256) -> list[int] | None:
    """在依赖图上从 start_ids 出发做 DFS，返回一条环路径（首尾重复）。

    依赖边只可能因当前 Fixture 的出边变更而新增成环，所以从变更方出发
    即可覆盖全部新增环。
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {}
    counter = 0
    result: list[int] | None = None

    def successors(fixture_id: int) -> list[int]:
        """获取当前节点的后继节点。"""
        return [
            row[0]
            for row in db.query(FixtureDependency.depends_on_fixture_id)
            .filter(FixtureDependency.fixture_id == fixture_id)
            .order_by(FixtureDependency.sort, FixtureDependency.id)
            .all()
        ]

    def dfs(start: int) -> None:
        """按深度优先顺序遍历依赖节点。"""
        nonlocal result, counter
        stack: list[tuple[int, list[int]]] = [(start, successors(start))]
        color[start] = GRAY
        while stack:
            node, succ = stack[-1]
            if not succ:
                color[node] = BLACK
                stack.pop()
                continue
            nxt = succ.pop()
            state = color.get(nxt, WHITE)
            if state == GRAY:
                # 栈底→栈顶是当前 DFS 路径；nxt 是路径中某个 GRAY 节点，
                # node → nxt 这条回边把 nxt..node 这段接成环。
                # 取栈中 nxt 及其之后（到 node）的节点，再补回 nxt，得到
                # 首尾重复的环序列，例如 C → A → B → C。
                frames = [s[0] for s in stack]
                start_idx = frames.index(nxt)
                result = frames[start_idx:] + [nxt]
                return
            if state == WHITE:
                counter += 1
                if counter > max_nodes:
                    return
                color[nxt] = GRAY
                stack.append((nxt, successors(nxt)))

    for sid in sorted(start_ids):
        if result is not None:
            break
        if color.get(sid, WHITE) != WHITE:
            continue
        dfs(sid)
    return result


def cycle_message(db: Session, path_ids: list[int]) -> list[str]:
    """环路径转 key 列表（首尾重复），交由 raise_cycle 用「 → 」拼接展示。

    返回 list 而非已拼接字符串：raise_cycle 会对入参做 join，若这里先 join 成
    单个字符串，raise_cycle 再 join 会把字符串按字符拆开（C_NODE → C → _ → N …）。
    """
    keys: list[str] = []
    for fid in path_ids:
        row = db.get(Fixture, fid)
        keys.append(row.fixture_key if row else str(fid))
    return keys


def add_dependency_row(db: Session, fixture_id: int, target_id: int) -> None:
    """写入一条依赖边（幂等：已存在则跳过）。"""
    exists = db.query(FixtureDependency).filter(
        FixtureDependency.fixture_id == fixture_id,
        FixtureDependency.depends_on_fixture_id == target_id,
    ).first()
    if exists is None:
        db.add(FixtureDependency(fixture_id=fixture_id, depends_on_fixture_id=target_id, sort=0))


def reconcile_step_edges(
    db: Session,
    fixture_id: int,
    old_step_targets: set[int],
    new_step_targets: set[int],
) -> None:
    """按「步骤派生」口径调整依赖边：步骤派生的边跟随步骤重建，手动边保留。"""
    existing = {
        row[0]
        for row in db.query(FixtureDependency.depends_on_fixture_id)
        .filter(FixtureDependency.fixture_id == fixture_id)
        .all()
    }
    to_delete = (old_step_targets & existing) - new_step_targets
    to_add = new_step_targets - existing
    for target_id in to_delete:
        db.query(FixtureDependency).filter(
            FixtureDependency.fixture_id == fixture_id,
            FixtureDependency.depends_on_fixture_id == target_id,
        ).delete(synchronize_session=False)
    for target_id in to_add:
        add_dependency_row(db, fixture_id, target_id)
    if to_delete or to_add:
        db.flush()
