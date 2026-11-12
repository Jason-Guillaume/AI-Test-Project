from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Import the service package first; it is the application's normal import order
# and prevents package initialization from re-entering the parser modules.
from app.features.api_catalog.services import ImportService as _ImportService  # noqa: F401
from app.features.api_catalog.models.api_response import ApiResponse
from app.features.api_catalog.parsers.openapi_parser import parse_openapi
from app.features.api_catalog.schemas.internal import InternalResponse
from app.features.api_catalog.schemas.requests import ApiResponseIn
from app.features.api_catalog.schemas.response_keys import InvalidResponseKey
from app.features.api_catalog.services.request_store import replace_responses
from app.features.api_catalog.services.response_mapper import response_to_internal
from app.features.security_testing.zap.openapi_export import _responses_to_openapi


def test_openapi_keeps_exact_range_and_default_responses():
    parsed = parse_openapi("""
openapi: 3.0.3
info: {title: response key fixture, version: '1'}
paths:
  /health:
    get:
      responses:
        '200': {description: exact response}
        '2XX': {description: range response}
        default: {description: fallback response}
""")

    responses = parsed[0].responses
    assert [(item.response_key, item.status_code, item.description) for item in responses] == [
        ("200", 200, "exact response"),
        ("2XX", None, "range response"),
        ("default", None, "fallback response"),
    ]
    assert ApiResponseIn(status_code=201).response_key == "201"
    assert ApiResponseIn(response_key="default").status_code is None
    assert InternalResponse(status_code=200).response_key == "200"


def test_response_keys_round_trip_through_storage_and_detail_mapping():
    engine = create_engine("sqlite://")
    ApiResponse.__table__.create(engine)
    with Session(engine) as db:
        replace_responses(db, 11, [
            ApiResponseIn(response_key="200", description="exact"),
            ApiResponseIn(response_key="2XX", description="range"),
            ApiResponseIn(response_key="default", description="fallback"),
        ])
        db.commit()
        rows = db.query(ApiResponse).order_by(ApiResponse.sort).all()

    assert [(row.response_key, row.status_code, row.description) for row in rows] == [
        ("200", 200, "exact"), ("2XX", None, "range"), ("default", None, "fallback"),
    ]
    assert [(response_to_internal(row).response_key, response_to_internal(row).description) for row in rows] == [
        ("200", "exact"), ("2XX", "range"), ("default", "fallback"),
    ]


def test_security_openapi_export_keeps_range_default_and_descriptions():
    exported = _responses_to_openapi([
        SimpleNamespace(response_key="200", status_code=200, description="exact", schema_json=None, example_json=None),
        SimpleNamespace(response_key="2XX", status_code=None, description="range", schema_json=None, example_json=None),
        SimpleNamespace(response_key="default", status_code=None, description="fallback", schema_json=None, example_json=None),
    ])

    assert list(exported) == ["200", "2XX", "default"]
    assert [exported[key]["description"] for key in exported] == ["exact", "range", "fallback"]


@pytest.mark.parametrize("bad_key", ["0", "600", "banana"])
def test_openapi_invalid_response_key_identifies_operation(bad_key: str):
    document = f"""
openapi: 3.0.3
info: {{title: invalid response fixture, version: '1'}}
paths:
  /health:
    get:
      responses:
        '{bad_key}': {{description: invalid}}
"""
    with pytest.raises(InvalidResponseKey, match=r"GET /health responses"):
        parse_openapi(document)
