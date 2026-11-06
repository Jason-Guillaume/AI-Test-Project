"""FunASR 参数、映射及 CER 计算原语；不假定远端响应结构。"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

from app.features.asr_evaluation.providers.generic_json import read_json_pointer
from app.features.asr_evaluation.services.assets_service import _validate_parameters

# 文档默认值是说明，不用于自动填充用户基线。
_ROWS = [
    ('target_rms_dbfs', 'number', -60, -1, -20, 'dBFS', True),
    ('max_gain_db', 'number', 0, 30, 12, 'dB', True),
    ('peak_limit_dbfs', 'number', -12, -0.1, -1, 'dBFS', True),
    ('noise_reduction_db', 'integer', 0, 30, 0, 'dB', True),
    ('max_single_segment_time', 'integer', 1000, 60000, 30000, 'ms', True),
    ('max_end_silence_time', 'integer', 200, 2000, 800, 'ms', True),
    ('speech_noise_thres', 'number', 0, 1, 0.5, None, True),
    ('batch_size_s', 'integer', 1, 600, 120, 's', False),
    ('batch_size_threshold_s', 'integer', 1, 60, 30, 's', False),
    ('merge_vad', 'boolean', None, None, False, None, True),
    ('merge_length_s', 'integer', 1, 30, 5, 's', True),
    ('preset_spk_num', 'integer', 1, 20, None, None, False),
    ('speaker_merge_threshold', 'number', None, 1, 0.78, None, False),
    ('hotword', 'string', None, None, '方小集 方小匠', None, False),
]
FUNASR_DEFINITIONS = [
    {'path': '/' + name, 'display_name': name, 'value_type': kind, 'minimum': lower,
     'maximum': upper, 'default': default, 'unit': unit, 'required': False,
     'nullable': name == 'preset_spk_num', 'tunable': tunable,
     'description': {
         'target_rms_dbfs': '目标响度；提高后更响，仍受最大增益和峰值限制。',
         'max_gain_db': '最大放大增益；提高可放大小声，也可能放大背景噪声。',
         'peak_limit_dbfs': '峰值上限；值越接近 0，允许的峰值越高。',
         'noise_reduction_db': '降噪强度；提高可能压低噪声，也可能损失轻声语音。',
         'max_single_segment_time': '单段最长时长；提高可减少强制切分。',
         'max_end_silence_time': '结尾静音容忍时长；提高更能保留停顿。',
         'speech_noise_thres': '语音噪声阈值；提高更严格，可能漏掉轻声语音。',
         'batch_size_s': '识别批次时长预算，不是录音总时长上限。',
         'batch_size_threshold_s': '批次中长片段触发结束的时长阈值。',
         'merge_vad': '是否合并 VAD 片段；开启可能跨越静音或说话人切换。',
         'merge_length_s': '合并片段的最长时长，仅 merge_vad=true 时生效。',
         'preset_spk_num': '固定说话人数；1 表示强制单人，null 表示服务端自动估计。',
         'speaker_merge_threshold': '自动人数模式下的说话人合并阈值。',
         'hotword': '空格分隔的热词；空字符串关闭热词。',
     }[name],
     'tuning_note': ('当前未实现说话人错误指标，自动搜索锁定。'
                     if name == 'speaker_merge_threshold' else None),
     'exclusive_minimum': 0 if name == 'speaker_merge_threshold' else None,
     'active_when': ({'path': '/merge_vad', 'equals': True} if name == 'merge_length_s' else
                     {'path': '/preset_spk_num', 'equals': None} if name == 'speaker_merge_threshold' else None)}
    for name, kind, lower, upper, default, unit, tunable in _ROWS
]
FUNASR_FIELDS = frozenset(row[0] for row in _ROWS)


def parameter_is_active(name: str, parameters: dict[str, Any]) -> bool:
    if name == 'merge_length_s':
        return parameters.get('merge_vad', False) is True
    if name == 'speaker_merge_threshold':
        return parameters.get('preset_spk_num') is None
    return True


def build_request(parameters: dict[str, Any], audio: str) -> dict[str, Any]:
    """校验顶层白名单，保留用户提供的 null/false/0，逐音频注入 audio。"""
    if not isinstance(parameters, dict) or set(parameters) - FUNASR_FIELDS:
        raise ValueError('存在未声明的 FunASR 参数')
    if not isinstance(audio, str) or not audio:
        raise ValueError('audio 必须是非空字符串')
    _validate_parameters(parameters, FUNASR_DEFINITIONS)
    return {'audio': audio, **parameters}


def effective_parameter_hash(parameters: dict[str, Any]) -> str:
    """哈希有效字段；缺省按服务文档默认值计算，但不改变原始快照。"""
    _validate_parameters(parameters, FUNASR_DEFINITIONS)
    if set(parameters) - FUNASR_FIELDS:
        raise ValueError('存在未声明的 FunASR 参数')
    effective = {d['path'][1:]: parameters.get(d['path'][1:], d['default'])
                 for d in FUNASR_DEFINITIONS if parameter_is_active(d['path'][1:], parameters)}
    return hashlib.sha256(json.dumps(effective, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def normalize_text(text: str, *, ignore_whitespace: bool = False,
                   ignore_punctuation: bool = False, casefold: bool = False) -> str:
    """仅使用显式规则；不在原始数据或 Markdown 中改写文本。"""
    if not isinstance(text, str):
        raise ValueError('文本必须是字符串')
    if casefold:
        text = text.casefold()
    return ''.join(c for c in text if not (ignore_whitespace and c.isspace())
                   and not (ignore_punctuation and unicodedata.category(c).startswith('P')))


def character_error_counts(reference: str, hypothesis: str) -> dict[str, Any]:
    """Levenshtein 字符对齐；固定同分优先级，保留插入、删除、替换计数。"""
    previous = [(j, 0, 0, j) for j in range(len(hypothesis) + 1)]
    for i, ref_char in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, hyp_char in enumerate(hypothesis, 1):
            cost, sub, delete, insert = previous[j - 1]
            diff = int(ref_char != hyp_char)
            candidates = [(cost + diff, sub + diff, delete, insert),
                          (previous[j][0] + 1, previous[j][1], previous[j][2] + 1, previous[j][3]),
                          (current[j - 1][0] + 1, current[j - 1][1], current[j - 1][2], current[j - 1][3] + 1)]
            current.append(min(candidates, key=lambda row: row[0]))
        previous = current
    errors, substitutions, deletions, insertions = previous[-1]
    return {'reference_characters': len(reference), 'substitutions': substitutions,
            'deletions': deletions, 'insertions': insertions, 'errors': errors,
            'cer': errors / len(reference) if reference else None,
            'empty_reference_insertions': insertions if not reference else 0}


def aggregate_cer(samples: list[dict[str, Any]]) -> dict[str, Any]:
    nonempty = [item for item in samples if item['reference_characters']]
    chars = sum(item['reference_characters'] for item in nonempty)
    # 空答案的插入独立报告，不混入有答案样本的微平均。
    return {'macro_cer': sum(item['cer'] for item in nonempty) / len(nonempty) if nonempty else None,
            'micro_cer': sum(item['errors'] for item in nonempty) / chars if chars else None,
            'empty_reference_insertions': sum(item['empty_reference_insertions'] for item in samples),
            'samples': len(samples), 'nonempty_samples': len(nonempty)}


def mapped_text(document: Any, pointer: str) -> str:
    """映射需由用户指定；区分缺失、null 和空字符串。"""
    missing = object()
    result = read_json_pointer(document, pointer, missing=missing)
    if result is missing:
        raise ValueError('映射路径不存在')
    if not isinstance(result, str):
        raise ValueError('映射路径必须指向文本')
    return result


def normalize_document(document: Any, mapping: dict[str, Any], *, source: str,
                       audio_version_id: int) -> dict[str, Any]:
    """按显式 JSON Pointer 映射规范化；片段字段路径相对于片段项。"""
    if source not in {'ground_truth', 'recognition'}:
        raise ValueError('来源类型无效')
    if not isinstance(mapping, dict) or mapping.get('text_source') not in {'full', 'segments'}:
        raise ValueError('须显式选择全文或片段作为计分文本')
    segments = []
    missing = object()
    segment_pointer = mapping.get('segments_pointer')
    if segment_pointer is not None:
        if not isinstance(segment_pointer, str):
            raise ValueError('片段路径必须是 JSON Pointer')
        rows = read_json_pointer(document, segment_pointer, missing=missing)
        if not isinstance(rows, list):
            raise ValueError('片段路径必须指向数组')
        text_pointer = mapping.get('segment_text_pointer')
        if not isinstance(text_pointer, str):
            raise ValueError('须指定相对于片段项的文本路径')
        for index, row in enumerate(rows):
            text = mapped_text(row, text_pointer)
            start, end = None, None
            start_pointer, end_pointer = mapping.get('start_pointer'), mapping.get('end_pointer')
            if (start_pointer is None) != (end_pointer is None):
                raise ValueError('开始和结束时间路径须同时配置')
            if start_pointer is not None:
                if not isinstance(start_pointer, str) or not isinstance(end_pointer, str):
                    raise ValueError('时间路径必须是 JSON Pointer')
                a = read_json_pointer(row, start_pointer, missing=missing)
                b = read_json_pointer(row, end_pointer, missing=missing)
                unit = mapping.get('time_unit')
                if (unit not in {'s', 'ms'} or isinstance(a, bool) or isinstance(b, bool)
                    or not isinstance(a, (int, float)) or not isinstance(b, (int, float))):
                    raise ValueError('时间值或单位无效')
                import math
                if ((isinstance(a, float) and not math.isfinite(a)) or
                    (isinstance(b, float) and not math.isfinite(b)) or a < 0 or b <= a):
                    raise ValueError('片段时间范围无效')
                factor = 1000 if unit == 's' else 1
                start, end = a * factor, b * factor
            speaker = None
            if mapping.get('speaker_pointer') is not None:
                if not isinstance(mapping['speaker_pointer'], str):
                    raise ValueError('说话人路径必须是 JSON Pointer')
                speaker = read_json_pointer(row, mapping['speaker_pointer'], missing=missing)
                if speaker is missing or speaker is not None and (isinstance(speaker, bool) or not isinstance(speaker, (str, int))):
                    raise ValueError('说话人映射无效')
            segments.append({'evidence_id': f'{source}:segment:{index + 1}', 'text': text,
                             'start_ms': start, 'end_ms': end, 'native_speaker_id': speaker,
                             'start_offset': None, 'end_offset': None})
    full_pointer = mapping.get('text_pointer')
    full_text = mapped_text(document, full_pointer) if isinstance(full_pointer, str) else None
    segment_text = ''.join(item['text'] for item in segments)
    text_source = mapping['text_source']
    if text_source == 'full' and full_text is None:
        raise ValueError('须指定全文路径')
    if text_source == 'segments' and segment_pointer is None:
        raise ValueError('须指定片段数组路径')
    warnings = []
    if full_text is not None and segment_pointer is not None and full_text != segment_text:
        warnings.append('全文与片段拼接不一致；计分使用显式选择的文本来源。')
    return {'run_id': source, 'audio_version_id': audio_version_id,
            'transcript': full_text if text_source == 'full' else segment_text,
            'segments': segments, 'text_source': text_source, 'warnings': warnings,
            'schema_version': 'funasr-normalized-1'}


def validate_candidate(base: dict[str, Any], changes: list[dict[str, Any]], *,
                       allowed: dict[str, dict[str, Any]], previous_hashes: set[str],
                       speaker_metrics_available: bool = False) -> dict[str, Any]:
    """校验结构化候选；调用者另行校验证据引用、审计与费用预算。"""
    if not 1 <= len(changes) <= 2:
        raise ValueError('每轮候选须修改一至两个参数')
    definitions = {d['path']: d for d in FUNASR_DEFINITIONS}
    result = dict(base)
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'path', 'old_value', 'new_value'}:
            raise ValueError('候选变更格式无效')
        path = change['path']
        if not isinstance(path, str) or path not in definitions or path not in allowed or path in seen:
            raise ValueError('候选包含未允许或重复的字段')
        seen.add(path)
        key = path[1:]
        if key not in base or type(base[key]) is not type(change['old_value']) or base[key] != change['old_value']:
            raise ValueError('候选旧值与基线不符或基线字段缺失')
        definition, policy, value = definitions[path], allowed[path], change['new_value']
        if not isinstance(policy, dict):
            raise ValueError('搜索策略无效')
        if not definition['tunable']:
            raise ValueError('该参数默认固定')
        if key == 'speaker_merge_threshold' and not speaker_metrics_available:
            raise ValueError('缺少可计算的说话人指标')
        if type(value) is type(base[key]) and value == base[key]:
            raise ValueError('候选没有修改参数')
        import math
        if set(policy) - {'minimum', 'maximum', 'choices'}:
            raise ValueError('搜索策略包含未知字段')
        for bound in ('minimum', 'maximum'):
            v = policy.get(bound)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or
                                  (isinstance(v, float) and not math.isfinite(v))):
                raise ValueError('搜索范围必须是有限数值')
        if policy.get('minimum') is not None and policy.get('maximum') is not None and policy['minimum'] > policy['maximum']:
            raise ValueError('搜索范围上下界倒置')
        if 'choices' in policy and not isinstance(policy['choices'], list):
            raise ValueError('候选选项必须是数组')
        bounds = dict(definition)
        for prop in ('minimum', 'maximum', 'choices'):
            if prop in policy and policy[prop] is not None:
                if prop == 'minimum' and definition['minimum'] is not None and policy[prop] < definition['minimum']:
                    raise ValueError('搜索范围超出 API 范围')
                if prop == 'maximum' and definition['maximum'] is not None and policy[prop] > definition['maximum']:
                    raise ValueError('搜索范围超出 API 范围')
                bounds[prop] = policy[prop]
        _validate_parameters({key: value}, [bounds])
        result[key] = value
    _validate_parameters(result, FUNASR_DEFINITIONS)
    if any(not parameter_is_active(path[1:], result) for path in seen):
        raise ValueError('候选修改了当前不生效的参数')
    digest = effective_parameter_hash(result)
    if digest == effective_parameter_hash(base) or digest in previous_hashes:
        raise ValueError('候选有效参数已出现')
    return result


def is_in_night_window(now: Any, start: str, end: str) -> bool:
    """在 Asia/Shanghai 判断半开窗口，包含跨午夜；相同时刻不视为全天。"""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError('当前时间必须包含时区')
    try:
        begin, finish = time.fromisoformat(start), time.fromisoformat(end)
    except ValueError as exc:
        raise ValueError('夜间窗口格式无效') from exc
    if begin.tzinfo or finish.tzinfo or begin == finish:
        raise ValueError('夜间窗口必须是不同的本地时间')
    local = now.astimezone(ZoneInfo('Asia/Shanghai')).time().replace(tzinfo=None)
    return begin <= local < finish if begin < finish else local >= begin or local < finish


def select_best_round(*, baseline: dict[str, Any], candidate: dict[str, Any],
                      min_improvement: float, max_sample_degradation: float) -> dict[str, Any]:
    """完整同集结果才可比较，按微平均改善及每样本退化上限决定。"""
    import math
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0
           for v in (min_improvement, max_sample_degradation)):
        raise ValueError('接受条件无效')
    left, right = baseline.get('samples'), candidate.get('samples')
    if not isinstance(left, dict) or not isinstance(right, dict) or not left or set(left) != set(right):
        raise ValueError('候选与基线必须完整覆盖相同样本')
    if any(not isinstance(row, dict) or row.get('status') != 'SUCCEEDED' or row.get('review_status') != 'SUCCEEDED'
           for row in list(left.values()) + list(right.values())):
        raise ValueError('识别和必要评审必须全部完成')
    degradations = {}
    for key in left:
        old, new = left[key]['metrics'], right[key]['metrics']
        if old['reference_characters'] != new['reference_characters']:
            raise ValueError('样本答案或评分规则不一致')
        if old['cer'] is not None and new['cer'] is not None:
            degradations[key] = new['cer'] - old['cer']
        elif old['cer'] is not None or new['cer'] is not None:
            raise ValueError('样本评分不可比较')
    old_score = aggregate_cer([row['metrics'] for row in left.values()])['micro_cer']
    new_score = aggregate_cer([row['metrics'] for row in right.values()])['micro_cer']
    if old_score is None or new_score is None:
        raise ValueError('没有可比较的非空标准答案')
    improvement = old_score - new_score
    accepted = improvement > 0 and improvement >= min_improvement and all(
        delta <= max_sample_degradation for delta in degradations.values())
    return {'accepted': accepted, 'baseline_micro_cer': old_score, 'candidate_micro_cer': new_score,
            'improvement': improvement, 'sample_degradation': degradations}
