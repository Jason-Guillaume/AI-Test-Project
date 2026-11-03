"""Reproduce model-center candidate rerun on synthetic in-memory data only."""
import json
from fastapi import HTTPException
from app.platform.model_configuration.tests.test_model_center import center_sandbox, _asr_resource
from app.platform.model_configuration.services.model_center_service import create_resource
from app.features.asr_evaluation.models import AsrAudio, AsrModelRun, AsrComparison, AsrExperiment, AsrJob
from app.core.security.crypto import encrypt_secret
from app.features.asr_evaluation.schemas import JobCreate, ExperimentCreate
from app.features.asr_evaluation.services.job_service import create_job
from app.features.asr_evaluation.services.comparison_service import record_run_result, create_experiment, run_experiment

generator = center_sandbox.__wrapped__()
db, admin, owner_a, owner_b, project_a, project_b = next(generator)
try:
    audio=AsrAudio(project_id=project_a.id,name='synthetic-audit',url_ciphertext=encrypt_secret('https://audio.example.invalid/a.wav'),url_display='https://audio.example.invalid/a.wav',created_by=admin.id)
    db.add(audio)
    db.commit()
    slots=[]
    for i, slot in enumerate(['TEST','REFERENCE_A','REFERENCE_B']):
        body=_asr_resource([project_a.id])
        body.display_name=f'synthetic-model-{i}'
        resource=create_resource(db,body,admin)
        rev=resource['current_revision']
        slots.append({'slot':slot,'resource_id':resource['id'],'revision_id':rev['id'],'profile_id':rev['profiles'][0]['id']})
    job=create_job(db,JobCreate(project_id=project_a.id,audio_ids=[audio.id],model_slots=slots),admin)
    runs=db.query(AsrModelRun).filter_by(job_id=job['id']).all()
    for run in runs:
        record_run_result(db,run.id,status='SUCCEEDED',transcript='合成文本。',segments=[])
    comparison=db.query(AsrComparison).filter_by(job_id=job['id']).one()
    experiment=create_experiment(db,ExperimentCreate(comparison_id=comparison.id,candidate_parameters={'language':'en'},change_summary='synthetic-audit'),admin)
    try:
        rerun=run_experiment(db,experiment['id'],admin)
        print(json.dumps({'result':'unexpected-success','candidate_job_id':rerun['job']['id']}))
    except HTTPException as error:
        print(json.dumps({'result':'reproduced','baseline_job_status':db.get(AsrJob,job['id']).status,'comparison_created':True,'experiment_created':True,'rerun_http_status':error.status_code,'rerun_error':error.detail,'experiment_status_after_failure':db.get(AsrExperiment,experiment['id']).status},ensure_ascii=False,indent=2))
finally:
    db.close()
    db.get_bind().dispose()
    generator.close()
