"""用例设计草稿不是可执行脚本或已落库测试资产。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Module = Literal['api', 'web', 'security', 'asr', 'ai']
MODULE_LABELS = {'api': '接口', 'web': 'Web UI', 'security': '安全', 'asr': 'ASR', 'ai': 'AI 质量'}
MODULE_COVERAGE = {
    'api': '契约、必填/Null/默认值、边界、状态码、认证授权、幂等、分页、超时与错误恢复。',
    'web': '导航、表单校验、登录态、加载/空/失败状态、键盘可访问性、响应式、重复提交。只引用输入中存在的页面元素。',
    'security': '认证、角色/对象权限、租户隔离、敏感信息、会话生命周期、限流。仅设计授权环境的用例，不生成攻击脚本或真实载荷。',
    'asr': '人工标准答案与版本、CER/WER 口径、口音/噪声/静音/长音频/重叠语音、数字实体、时间戳、说话人、失败与延迟。模型一致不代表正确。',
    'ai': '输出格式、事实性、RAG 引用、无答案/冲突上下文、多轮一致性、提示词注入、数据隔离、工具权限、超时和成本。区分规则断言与人工语义评分。',
}
GENERATION_TOOL_KEYS = {f'case_generation.generate_{module}' for module in MODULE_LABELS}


def allowed_generation_tools(keys: list[str]) -> bool:
    return len(keys) == 1 and keys[0] in GENERATION_TOOL_KEYS


class DesignCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    priority: Literal['P0', 'P1', 'P2', 'P3']
    requirement: str = Field(min_length=1, max_length=2000)
    preconditions: list[str] = Field(max_length=20)
    test_data: list[str] = Field(max_length=20)
    steps: list[str] = Field(min_length=1, max_length=30)
    expected_results: list[str] = Field(min_length=1, max_length=30)
    coverage: list[str] = Field(min_length=1, max_length=20)
    needs_confirmation: list[str] = Field(default_factory=list, max_length=20)


class DesignResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cases: list[DesignCase] = Field(min_length=1, max_length=20)


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: int = Field(gt=0)
    requirements: str = Field(min_length=1, max_length=20000)
    modules: list[Module] = Field(min_length=1, max_length=5)
    cases_per_module: int = Field(default=5, ge=1, le=20)
    model_config_id: int | None = Field(default=None, gt=0)
