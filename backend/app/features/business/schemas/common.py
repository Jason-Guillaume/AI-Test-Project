"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Literal


BUSINESS_DOMAIN_STATUSES = ("ACTIVE", "INACTIVE")


BusinessDomainStatus = Literal["ACTIVE", "INACTIVE"]


BUSINESS_FLOW_STATUSES = ("DRAFT", "ACTIVE", "DEPRECATED")


BusinessFlowStatus = Literal["DRAFT", "ACTIVE", "DEPRECATED"]


BUSINESS_ACTION_TYPES = ("NORMAL",)


BusinessActionType = Literal["NORMAL"]


BUSINESS_BINDING_TYPES = ("API", "WEB")


BusinessBindingType = Literal["API", "WEB"]


BUSINESS_PRECONDITION_TYPES = ("VARIABLE", "STATE", "BUSINESS", "TEXT")


BusinessPreconditionType = Literal["VARIABLE", "STATE", "BUSINESS", "TEXT"]


BUSINESS_PRECONDITION_OPERATORS = ("EQ", "NE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS")


BusinessPreconditionOperator = Literal["EQ", "NE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS"]


BUSINESS_VARIABLE_DIRECTIONS = ("INPUT", "OUTPUT")


BusinessVariableDirection = Literal["INPUT", "OUTPUT"]


BUSINESS_VARIABLE_DATA_TYPES = (
    "STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY",
)


BusinessVariableDataType = Literal[
    "STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"
]


BUSINESS_API_MAPPING_DIRECTIONS = ("INPUT", "OUTPUT")


BusinessApiMappingDirection = Literal["INPUT", "OUTPUT"]


BUSINESS_API_LOCATIONS = ("BODY", "HEADER", "QUERY", "PATH", "RESPONSE")


BusinessApiLocation = Literal["BODY", "HEADER", "QUERY", "PATH", "RESPONSE"]


BUSINESS_RULE_TYPES = ("GENERAL", "CONSTRAINT", "PRECONDITION")


BusinessRuleType = Literal["GENERAL", "CONSTRAINT", "PRECONDITION"]


FLOW_EXECUTION_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED")


FlowExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"]


ACTION_EXECUTION_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED")


ActionExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED"]
