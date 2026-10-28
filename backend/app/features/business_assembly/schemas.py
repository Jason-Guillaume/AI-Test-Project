"""业务组装任务、草稿修订与确认保存契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AssemblyTaskCreate(BaseModel):
    """创建不绑定测试环境的业务组装任务。"""

    title: str | None = Field(default=None, max_length=200)
    goal: str = Field(min_length=3, max_length=8000)
    document_version_ids: list[int] = Field(min_length=1, max_length=10)
    request_key: str = Field(min_length=1, max_length=100)


class SourceEvidence(BaseModel):
    """业务字段的原文依据或待确认推断。"""

    document_version_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    locator: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)
    claim_type: Literal["EXPLICIT", "INFERRED"] = "EXPLICIT"


class AssemblyPrecondition(BaseModel):
    """业务动作前置条件草稿。"""

    type: Literal["VARIABLE", "STATE", "BUSINESS", "TEXT"]
    target: str = Field(min_length=1, max_length=200)
    operator: Literal["EQ", "NE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS"] = "EQ"
    expected_value: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=500)
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=10)


class AssemblyVariable(BaseModel):
    """动作输入或输出变量草稿。"""

    direction: Literal["INPUT", "OUTPUT"]
    name: str = Field(min_length=1, max_length=100)
    data_type: Literal["STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"] = "STRING"
    required: bool = False
    description: str | None = Field(default=None, max_length=500)
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=10)


class AssemblyState(BaseModel):
    """业务实体前后状态草稿。"""

    entity: str = Field(min_length=1, max_length=100)
    pre_state: str | None = Field(default=None, max_length=50)
    post_state: str | None = Field(default=None, max_length=50)
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=10)


class AssemblyApiCandidate(BaseModel):
    """仅引用真实接口目录 ID；字段映射必须附带文档依据或保持空缺。"""

    api_id: int = Field(gt=0)
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    reason: str = Field(default="", max_length=500)
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=10)


class AssemblyAction(BaseModel):
    """顺序动作草稿，执行器当前只支持 NORMAL。"""

    action_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    action_type: Literal["NORMAL"] = "NORMAL"
    preconditions: list[AssemblyPrecondition] = Field(default_factory=list, max_length=30)
    input_variables: list[AssemblyVariable] = Field(default_factory=list, max_length=50)
    output_variables: list[AssemblyVariable] = Field(default_factory=list, max_length=50)
    states: list[AssemblyState] = Field(default_factory=list, max_length=20)
    api_candidate: AssemblyApiCandidate | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=20)


class AssemblyVariableRef(BaseModel):
    """流程内输出到输入的变量引用。"""

    source_action_key: str = Field(min_length=1, max_length=100)
    source_variable: str = Field(min_length=1, max_length=100)
    target_action_key: str = Field(min_length=1, max_length=100)
    target_variable: str = Field(min_length=1, max_length=100)


class AssemblyRule(BaseModel):
    """仅供人工阅读的业务规则。"""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    rule_type: Literal["GENERAL", "CONSTRAINT", "PRECONDITION"] = "GENERAL"
    expression: str | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list, max_length=20)


class AssemblyFlow(BaseModel):
    """一个待保存的业务流程。"""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    actions: list[AssemblyAction] = Field(min_length=1, max_length=100)
    variable_refs: list[AssemblyVariableRef] = Field(default_factory=list, max_length=200)
    rules: list[AssemblyRule] = Field(default_factory=list, max_length=100)


class BusinessAssemblyDraftContent(BaseModel):
    """版本化草稿 JSON；服务端重新校验引用和来源。"""

    domain_name: str = Field(min_length=1, max_length=100)
    domain_description: str | None = Field(default=None, max_length=500)
    flows: list[AssemblyFlow] = Field(min_length=1, max_length=20)
    coverage: dict[str, Any] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list, max_length=200)
    unsupported_elements: list[str] = Field(default_factory=list, max_length=100)


class DraftUpdate(BaseModel):
    """用期望修订号保存人工修改，防止覆盖并发编辑。"""

    expected_revision: int = Field(ge=1)
    content: BusinessAssemblyDraftContent


class DraftValidateRequest(BaseModel):
    """校验一个确定的修订号。"""

    revision: int = Field(ge=1)


class DraftApplyRequest(BaseModel):
    """原子确认保存选中的流程。"""

    revision: int = Field(ge=1)
    flow_indexes: list[int] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=100)


class BusinessAssemblyDraftResponse(BaseModel):
    """草稿当前修订与来源任务。"""

    id: int
    project_id: int
    task_id: int | None = None
    task_run_id: int | None = None
    source_version_ids: list[int]
    current_revision: int
    status: str
    content: BusinessAssemblyDraftContent
    validation: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessAssemblyValidationResponse(BaseModel):
    """可保存与可执行状态彼此独立。"""

    revision: int
    can_save: bool
    can_execute: bool
    errors: list[str]
    warnings: list[str]


class BusinessAssemblyApplyResponse(BaseModel):
    """同一事务创建的业务流程回执。"""

    draft_id: int
    revision: int
    domain_id: int
    flow_ids: list[int]
    replayed: bool = False
