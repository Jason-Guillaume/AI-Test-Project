"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Literal


ApiStatus = Literal["ACTIVE", "DRAFT", "DEPRECATED", "DEVELOPING", "MOCK"]


ApiSourceType = Literal["MANUAL", "CURL", "OPENAPI", "SWAGGER", "POSTMAN", "APIFOX"]


ParamLocation = Literal["PATH", "QUERY", "HEADER", "COOKIE", "BODY"]


BodyType = Literal["none", "json", "form", "multipart", "raw"]


RelationType = Literal["PRECONDITION", "OUTPUT_INPUT", "FOLLOW_UP"]


ChangeType = Literal[
    "CREATED",
    "UPDATED",
    "PARAM_ADDED",
    "PARAM_REMOVED",
    "PARAM_TYPE_CHANGED",
    "REQUIRED_CHANGED",
    "RESPONSE_CHANGED",
    "MODULE_CHANGED",
]


ImportClassification = Literal["NEW", "EXISTING", "CHANGED", "UNCHANGED"]


API_STATUSES = {"ACTIVE", "DRAFT", "DEPRECATED", "DEVELOPING", "MOCK"}


API_SOURCE_TYPES = {"MANUAL", "CURL", "OPENAPI", "SWAGGER", "POSTMAN", "APIFOX"}


PARAM_LOCATIONS = {"PATH", "QUERY", "HEADER", "COOKIE", "BODY"}


BODY_TYPES = {"none", "json", "form", "multipart", "raw"}


RELATION_TYPES = {"PRECONDITION", "OUTPUT_INPUT", "FOLLOW_UP"}


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
