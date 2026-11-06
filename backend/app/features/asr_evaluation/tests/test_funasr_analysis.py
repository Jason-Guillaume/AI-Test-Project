"""合成数据，仅检验参数与计算原语，不表示真实 FunASR 已联调。"""
import math
import pytest
from fastapi import HTTPException
from app.features.asr_evaluation.providers.generic_json import read_json_pointer, render_template
from app.features.asr_evaluation.services.assets_service import _validate_parameters
from app.features.asr_evaluation.services.funasr_analysis import (
    aggregate_cer, build_request, character_error_counts, effective_parameter_hash, mapped_text,
)


def test_missing_nullable_and_false_values():
    defs = [{'path': '/x', 'value_type': 'integer', 'nullable': True},
            {'path': '/flag', 'value_type': 'boolean'}]
    _validate_parameters({'x': None, 'flag': False}, defs)
    with pytest.raises(HTTPException):
        _validate_parameters({'flag': False}, defs)
    _validate_parameters({'flag': False}, [{**defs[0], 'required': False}, defs[1]])
    missing = object()
    assert read_json_pointer({'x': None}, '/x', missing=missing) is None
    assert read_json_pointer({}, '/x', missing=missing) is missing
    assert render_template({'n': '{{p.n}}', 'b': '{{p.b}}'}, {'p': {'n': None, 'b': False}}) == {'n': None, 'b': False}


def test_funasr_whitelist_bounds_and_hash():
    assert build_request({'preset_spk_num': None, 'merge_vad': False, 'hotword': ''}, 'sample') == {
        'audio': 'sample', 'preset_spk_num': None, 'merge_vad': False, 'hotword': ''}
    for value in [0, -0.01, math.nan, math.inf, True]:
        with pytest.raises(HTTPException):
            build_request({'speaker_merge_threshold': value}, 'sample')
    with pytest.raises(ValueError):
        build_request({'parameters': {}}, 'sample')
    assert effective_parameter_hash({'merge_length_s': 4}) == effective_parameter_hash({'merge_length_s': 7})
    assert effective_parameter_hash({'merge_vad': True, 'merge_length_s': 4}) != effective_parameter_hash({'merge_vad': True, 'merge_length_s': 7})
    assert effective_parameter_hash({'preset_spk_num': 1, 'speaker_merge_threshold': 0.5}) == effective_parameter_hash({'preset_spk_num': 1, 'speaker_merge_threshold': 0.8})


def test_cer_and_mapping():
    one = character_error_counts('你好', '你号啊')
    assert (one['substitutions'], one['insertions'], one['deletions'], one['cer']) == (1, 1, 0, 1)
    empty = character_error_counts('', '啊')
    assert empty['cer'] is None and empty['empty_reference_insertions'] == 1
    result = aggregate_cer([one, empty])
    assert result['macro_cer'] == result['micro_cer'] == 1
    assert result['empty_reference_insertions'] == 1
    assert mapped_text({'result': ''}, '/result') == ''
    with pytest.raises(ValueError):
        mapped_text({'result': None}, '/result')
    with pytest.raises(ValueError):
        mapped_text({}, '/result')


def test_explicit_mapping_and_deterministic_markdown():
    from app.features.asr_evaluation.services.funasr_analysis import normalize_document
    from app.features.asr_evaluation.services.evaluation_markdown_service import render_markdown
    fixture = {'full': '甲乙', 'items': [{'body': '甲', 'begin': 0, 'end': 1, 'spk': 'A'},
                                         {'body': '乙！', 'begin': 1, 'end': 2, 'spk': 'B'}]}
    mapping = {'text_source': 'full', 'text_pointer': '/full', 'segments_pointer': '/items',
               'segment_text_pointer': '/body', 'start_pointer': '/begin', 'end_pointer': '/end',
               'speaker_pointer': '/spk', 'time_unit': 's'}
    result = normalize_document(fixture, mapping, source='ground_truth', audio_version_id=8)
    assert result['transcript'] == '甲乙' and result['segments'][0]['end_ms'] == 1000
    assert result['warnings'] and render_markdown(result) == render_markdown(result)
    assert '甲乙' in render_markdown(result).decode()
    with pytest.raises(ValueError):
        normalize_document(fixture, {**mapping, 'time_unit': None}, source='ground_truth', audio_version_id=8)
    with pytest.raises(ValueError):
        normalize_document(fixture, {**mapping, 'text_pointer': '/missing'}, source='ground_truth', audio_version_id=8)


def test_candidate_rejects_inactive_duplicate_and_outside_policy():
    from app.features.asr_evaluation.services.funasr_analysis import validate_candidate
    base = {'merge_vad': False, 'merge_length_s': 5, 'speech_noise_thres': 0.5}
    allowed = {'/merge_vad': {}, '/merge_length_s': {'minimum': 4, 'maximum': 10},
               '/speech_noise_thres': {'minimum': 0.4, 'maximum': 0.8}}
    changes = [{'path': '/merge_length_s', 'old_value': 5, 'new_value': 6}]
    with pytest.raises(ValueError):
        validate_candidate(base, changes, allowed=allowed, previous_hashes=set())
    result = validate_candidate(base, [{'path': '/merge_vad', 'old_value': False, 'new_value': True}, *changes],
                                allowed=allowed, previous_hashes=set())
    assert result['merge_length_s'] == 6 and result['merge_vad']
    with pytest.raises(HTTPException):
        validate_candidate(base, [{'path': '/speech_noise_thres', 'old_value': 0.5, 'new_value': 0.9}], allowed=allowed, previous_hashes=set())
    with pytest.raises(ValueError):
        validate_candidate(base, [{'path': '/speech_noise_thres', 'old_value': 0.5, 'new_value': 0.6}], allowed=allowed,
                           previous_hashes={effective_parameter_hash({**base, 'speech_noise_thres': 0.6})})


def test_night_window_crosses_midnight_in_shanghai():
    from datetime import datetime, timezone
    from app.features.asr_evaluation.services.funasr_analysis import is_in_night_window
    assert is_in_night_window(datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc), '23:00', '07:00')
    assert is_in_night_window(datetime(2026, 11, 6, 22, 59, tzinfo=timezone.utc), '23:00', '07:00')
    assert not is_in_night_window(datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc), '23:00', '07:00')
    with pytest.raises(ValueError):
        is_in_night_window(datetime(2026, 11, 6), '23:00', '07:00')


def test_best_round_requires_complete_comparable_samples():
    from app.features.asr_evaluation.services.funasr_analysis import select_best_round
    def row(ref, hyp, status='SUCCEEDED'):
        return {'status': status, 'review_status': 'SUCCEEDED', 'metrics': character_error_counts(ref, hyp)}
    baseline = {'samples': {'1': row('你好', '你错'), '2': row('测试', '测是')}}
    improved = {'samples': {'1': row('你好', '你好'), '2': row('测试', '测试')}}
    assert select_best_round(baseline=baseline, candidate=improved, min_improvement=0.01, max_sample_degradation=0.1)['accepted']
    degraded = {'samples': {'1': row('你好', '你好'), '2': row('测试', '错错')}}
    assert not select_best_round(baseline=baseline, candidate=degraded, min_improvement=0, max_sample_degradation=0.1)['accepted']
    with pytest.raises(ValueError):
        select_best_round(baseline=baseline, candidate={'samples': {'1': improved['samples']['1']}}, min_improvement=0, max_sample_degradation=0.1)
