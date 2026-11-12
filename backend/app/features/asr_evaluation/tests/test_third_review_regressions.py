"""本轮 ASR 修复的正确行为回归；只使用内存 SQLite 与合成状态。"""

from app.core.models.configuration import ModelConfiguration
from app.features.asr_evaluation.models import (
    AsrComparison, AsrContentReviewJob, AsrExperiment, AsrJob, AsrModelRun, AsrTranscriptSegment,
)
from app.features.asr_evaluation.services.comparison_service import list_experiments
from app.features.asr_evaluation.services.content_review_service import review_summary
from app.features.asr_evaluation.services.segments_service import list_transcript_segments
from app.features.asr_evaluation.tests.test_regressions import sandbox


def test_playback_locator_matches_server_order_with_sparse_indexes_nulls_duplicates_and_channels(sandbox):
    db, _, actor, _, _, _, job = sandbox
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    inserted = []
    for position in range(205):
        timed = position < 180
        row = AsrTranscriptSegment(
            model_run_id=run.id, segment_index=4001 - position * 7, text=f"片段-{position}",
            start_ms=(position % 5) * 1000 if timed else None,
            end_ms=(position % 5) * 1000 + 3000 if timed else None,
            channel=f"ch-{position % 2}",
        )
        db.add(row)
        inserted.append(row)
    db.commit()

    pages = [list_transcript_segments(db, run.id, actor, page=page, page_size=100)
             for page in (1, 2, 3)]
    assert [page["total"] for page in pages] == [205, 205, 205]
    assert len(pages[0]["items"]) == 100 and len(pages[1]["items"]) == 100 and len(pages[2]["items"]) == 5
    assert {item["channel"] for page in pages for item in page["items"]} == {"ch-0", "ch-1"}
    actual_page_by_id = {
        item["id"]: page_number
        for page_number, page in enumerate(pages, start=1)
        for item in page["items"]
    }
    for target in (inserted[0], inserted[73], inserted[179], inserted[180], inserted[204]):
        located = list_transcript_segments(
            db, run.id, actor, page_size=100, locate_segment_id=str(target.id),
        )
        assert located["located_page"] == actual_page_by_id[str(target.id)]
        page = list_transcript_segments(db, run.id, actor, page=located["located_page"], page_size=100)
        assert str(target.id) in {item["id"] for item in page["items"]}


def test_playback_window_page_size_returns_all_dense_and_overlapping_segments(sandbox):
    db, _, actor, _, _, _, job = sandbox
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    for index in range(251):
        start = (index % 40) * 100
        db.add(AsrTranscriptSegment(
            model_run_id=run.id, segment_index=900 - index * 3, text=f"重叠-{index}",
            start_ms=start, end_ms=7000 + (index % 5), channel=f"ch-{index % 2}",
        ))
    db.commit()
    result = list_transcript_segments(db, run.id, actor, start_ms=0, end_ms=5000, page_size=1000)
    assert result["total"] == 251
    assert len(result["items"]) == 251
    assert len({item["id"] for item in result["items"]}) == 251


def test_batch_review_summary_keeps_ab_review_active_until_terminal(sandbox):
    db, _, actor, _, _, _, job = sandbox
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    model = ModelConfiguration(
        domain_id="asr-test-review-model", label="合成评审模型", api_base="https://example.invalid/v1",
        model_name="synthetic-review", created_by=actor.id,
    )
    db.add(model)
    db.flush()
    review = AsrContentReviewJob(
        project_id=job["project_id"], job_id=job["id"], experiment_id=None,
        model_config_id=model.id, review_type="AB", run_ids=[run.id], primary_run_id=run.id,
        idempotency_key="ab-review-active-regression", input_version="test-v1", expected_runs=2,
        status="RUNNING", coverage_status="PARTIAL",
    )
    db.add(review)
    db.commit()
    first = review_summary(db, job["id"], actor)
    assert first["review_active"] == 0
    assert first["ab_active"] == 1
    review.status = "SUCCEEDED"
    db.commit()
    terminal = review_summary(db, job["id"], actor)
    assert terminal["ab_active"] == 0


def test_completed_asr_without_content_reviews_is_a_complete_summary(sandbox):
    db, _, actor, _, _, _, job = sandbox
    model_job = db.get(AsrJob, job["id"])
    model_job.status = "COMPLETED"
    for run in db.query(AsrModelRun).filter_by(job_id=job["id"]).all():
        run.status = "SUCCEEDED"
    db.commit()

    result = review_summary(db, job["id"], actor)
    assert result["planned_audio"] == 1
    assert result["asr_success_audio"] == 1
    assert result["review_denominator"] == 0
    assert result["review_active"] == 0
    assert result["ab_denominator"] == 0
    assert result["ab_active"] == 0


def test_experiment_reconciliation_maps_reason_and_blocks_ordinary_rerun(sandbox):
    db, _, actor, audio, _, parameters, job = sandbox
    comparison = AsrComparison(
        project_id=job["project_id"], job_id=job["id"], audio_id=audio.id,
        audio_version_id=None, version=1, status="INCOMPLETE", summary={},
    )
    db.add(comparison)
    db.flush()
    model_job = db.get(AsrJob, job["id"])
    model_job.status = "RECONCILIATION_REQUIRED"
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    run.status = "RECONCILIATION_REQUIRED"
    run.error_message = "提交状态待核实；请按幂等键核查服务端"
    experiment = AsrExperiment(
        project_id=job["project_id"], comparison_id=comparison.id,
        baseline_parameter_set_id=parameters.id, candidate_parameters={}, change_summary="合成复核",
        status="RUNNING", candidate_job_id=model_job.id, created_by=actor.id,
    )
    db.add(experiment)
    db.commit()

    result = list_experiments(db, job["project_id"], actor)
    candidate = next(item for item in result if item["id"] == experiment.id)
    assert candidate["candidate_job_status"] == "RECONCILIATION_REQUIRED"
    assert candidate["status"] == "RECONCILIATION_REQUIRED"
    assert "幂等键" in candidate["reconciliation_reason"]
    assert "人工决定" in candidate["reconciliation_action"]
