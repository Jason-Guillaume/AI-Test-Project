"""Structural fingerprints should not depend on incidental list ordering."""
from app.features.api_catalog.schemas import InternalApiSchema, InternalParameter, InternalResponse
from app.features.api_catalog.services.hash import compute_source_hash


def test_hash_ignores_transport_order_but_preserves_explicit_sort():
    first = InternalParameter(name="a", location="QUERY")
    second = InternalParameter(name="b", location="QUERY")
    responses = [InternalResponse(status_code=200), InternalResponse(status_code=404)]
    original = InternalApiSchema(name="test", method="GET", path="/test", parameters=[first, second], responses=responses)
    reordered = original.model_copy(update={"parameters": [second, first], "responses": list(reversed(responses))})
    assert compute_source_hash(original) == compute_source_hash(reordered)
    changed_sort = original.model_copy(update={"parameters": [first.model_copy(update={"sort": 1}), second]})
    assert compute_source_hash(original) != compute_source_hash(changed_sort)
