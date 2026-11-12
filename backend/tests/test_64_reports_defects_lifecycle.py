"""Reports and defects enter the shared recycle bin without deleting evidence."""

from tests.conftest import unique


def _project(api, admin):
    response = api.post("/projects", username=admin, json={"name": unique("evidence-lifecycle")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _trash_item(api, admin, project_id, resource_type, resource_id):
    response = api.get(
        "/recycle-bin", username=admin,
        params={"project_id": project_id, "resource_type": resource_type},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resource_id"] == str(resource_id))


def test_bug_delete_restores_source_links_and_blocks_evidence_purge(api, admin, db):
    from app.features.defects.models.source_link import DefectSourceLink
    from app.features.test_management.models.execution import CaseExecution, TestRun

    project_id = _project(api, admin)
    created = api.post(
        "/bugs", username=admin,
        json={"project_id": project_id, "title": unique("bug"), "severity": 2},
    )
    assert created.status_code == 201, created.text
    bug_id = created.json()["id"]
    run = TestRun(project_id=project_id, status="SUCCESS")
    db.add(run)
    db.flush()
    execution = CaseExecution(test_run_id=run.id, status="FAILED")
    db.add(execution)
    db.flush()
    db.add(DefectSourceLink(
        project_id=project_id, bug_id=bug_id, case_execution_id=execution.id,
        request_key=unique("bug-source"), request_digest="f" * 64,
    ))
    db.commit()

    assert api.delete(f"/bugs/{bug_id}", username=admin).status_code == 204
    assert api.get(f"/bugs/{bug_id}", username=admin).status_code == 404
    item = _trash_item(api, admin, project_id, "bug", bug_id)
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("来源追溯记录" in dependency for dependency in preview.json()["dependencies"])

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/bugs/{bug_id}", username=admin).status_code == 200
    assert api.get(f"/bugs/{bug_id}/sources", username=admin).json()[0]["case_execution_id"] == execution.id


def test_report_soft_delete_keeps_test_run_and_restores_original_report(api, admin, db):
    from app.features.reports.models.report import TestReport
    from app.features.test_management.models.execution import TestRun

    project_id = _project(api, admin)
    run = TestRun(project_id=project_id, status="SUCCESS")
    db.add(run)
    db.flush()
    report = TestReport(
        project_id=project_id, test_run_id=run.id,
        report_no=unique("RPT"), title=unique("报告"), status="COMPLETED",
    )
    db.add(report)
    db.commit()
    report_id, run_id = report.id, run.id

    deleted = api.delete(f"/reports/{report_id}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert api.get(f"/reports/{report_id}", username=admin).status_code == 404
    listed = api.get(f"/projects/{project_id}/reports", username=admin)
    assert listed.status_code == 200, listed.text
    assert all(item["id"] != report_id for item in listed.json()["items"])
    item = _trash_item(api, admin, project_id, "test_report", report_id)

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/reports/{report_id}", username=admin).status_code == 200
    assert api.get(f"/test-runs/{run_id}", username=admin).status_code == 200
