"""验证缺陷来源的原子创建、权限边界、幂等和删除行为。"""
from app.features.security_testing.models.finding import SecurityFinding
from app.features.test_management.models.execution import CaseExecution, TestRun as RunEntity
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tests.conftest import DEFAULT_PASSWORD, unique
from tests.test_15_test_executor import _create_project


def test_defect_source_creation_and_boundaries(api, admin, db):
    """失败结果只能关联同项目缺陷；重复请求不产生第二条缺陷。"""
    project_id = _create_project(api, admin)
    other_project = _create_project(api, admin)
    run = RunEntity(project_id=project_id, status="FAILED")
    db.add(run)
    db.flush()
    execution = CaseExecution(test_run_id=run.id, status="FAILED")
    db.add(execution)
    db.commit()
    body = {"source_type": "CASE_EXECUTION", "source_id": execution.id, "request_key": unique("link"), "bug": {"project_id": project_id, "title": "人工确认的结果"}}
    created = api.post("/bugs/sources", username=admin, json=body)
    assert created.status_code == 200, created.text
    link = created.json()
    again = api.post("/bugs/sources", username=admin, json=body)
    assert again.status_code == 200 and again.json()["id"] == link["id"]
    assert api.get(f"/bugs/{link['bug_id']}/sources", username=admin).json()[0]["case_execution_id"] == execution.id
    assert api.get("/bugs/sources", username=admin, params={"source_type": "CASE_EXECUTION", "source_id": execution.id}).json()[0]["bug_id"] == link["bug_id"]

    cross_bug = api.post("/bugs", username=admin, json={"project_id": other_project, "title": "其他项目"}).json()
    cross = api.post("/bugs/sources", username=admin, json={"source_type": "CASE_EXECUTION", "source_id": execution.id, "bug_id": cross_bug["id"], "request_key": unique("link")})
    assert cross.status_code == 404
    changed = api.post("/bugs/sources", username=admin, json={**body, "bug": {"project_id": project_id, "title": "不同内容"}})
    assert changed.status_code == 409

    assert api.delete(f"/bugs/{link['bug_id']}", username=admin).status_code == 204
    assert api.get("/bugs/sources", username=admin, params={"source_type": "CASE_EXECUTION", "source_id": execution.id}).json() == []


def test_security_finding_source_is_manual_and_private(api, admin, db):
    """关联疑似问题不改变其状态，项目外用户无法读取或写入。"""
    project_id = _create_project(api, admin)
    finding = SecurityFinding(project_id=project_id, mutation_type="TEST", title="疑似问题", description="待人工核对", fingerprint=unique("fingerprint"), status="OPEN")
    db.add(finding)
    db.commit()
    outsider = unique("outsider")
    assert api.register(outsider).status_code == 201
    api.login(outsider, DEFAULT_PASSWORD)
    params = {"source_type": "SECURITY_FINDING", "source_id": finding.id}
    assert api.get("/bugs/sources", username=outsider, params=params).status_code == 404
    body = {**params, "request_key": unique("finding"), "bug": {"project_id": project_id, "title": "需核对"}}
    assert api.post("/bugs/sources", username=outsider, json=body).status_code == 404
    response = api.post("/bugs/sources", username=admin, json=body)
    assert response.status_code == 200, response.text
    db.refresh(finding)
    assert finding.status == "OPEN" and finding.bug_id is None
    db.delete(finding)
    db.commit()
    assert api.get(f"/bugs/{response.json()['bug_id']}/sources", username=admin).json() == []


def test_concurrent_defect_creation_replays_same_request_key_once(api, admin, db):
    """两个数据库会话并发提交同一缺陷意图，只返回一个持久化来源与缺陷。"""
    from app.core.database.session import SessionLocal
    from app.core.models.identity import User
    from app.features.defects.models.bug import Bug
    from app.features.defects.models.source_link import DefectSourceLink
    from app.features.defects.schemas import DefectSourceRequest
    from app.features.defects.services.source_service import DefectSourceService

    project_id = _create_project(api, admin)
    run = RunEntity(project_id=project_id, status="FAILED")
    db.add(run)
    db.flush()
    execution = CaseExecution(test_run_id=run.id, status="FAILED")
    db.add(execution)
    db.commit()
    request_key = unique("concurrent-defect")
    body = DefectSourceRequest(
        source_type="CASE_EXECUTION",
        source_id=execution.id,
        request_key=request_key,
        bug={"project_id": project_id, "title": "并发只创建一次"},
    )
    barrier = Barrier(2)

    def link_once():
        with SessionLocal() as session:
            actor = session.query(User).filter_by(username=admin).one()
            barrier.wait(timeout=10)
            link = DefectSourceService().link(session, body, actor)
            return link.id, link.bug_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: link_once(), range(2)))
    assert results[0] == results[1]
    assert db.query(DefectSourceLink).filter_by(project_id=project_id, request_key=request_key).count() == 1
    assert db.query(Bug).filter_by(project_id=project_id, title="并发只创建一次").count() == 1
