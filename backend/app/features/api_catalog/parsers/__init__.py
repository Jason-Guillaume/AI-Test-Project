"""外部格式解析器：cURL / OpenAPI / Swagger / Postman → InternalApiSchema。

所有 parser 只输出 InternalApiSchema（统一中间表示），不含模块归属判定
（交给 ModuleResolver）与入库逻辑（交给 import_service）。
"""

from app.features.api_catalog.parsers.curl_parser import parse_curl
from app.features.api_catalog.parsers.document_parser import parse_api_document
from app.features.api_catalog.parsers.openapi_parser import parse_openapi
from app.features.api_catalog.parsers.postman_parser import parse_postman

__all__ = ["parse_api_document", "parse_curl", "parse_openapi", "parse_postman"]
