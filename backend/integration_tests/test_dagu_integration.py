"""Env-gated live Dagu integration test suite (explicitly requires DAGU_INTEGRATION_ENABLED=true)."""
from __future__ import annotations

import os

import pytest

from app.features.automation_center.providers.dagu_client import DaguClient
from app.features.automation_center.providers.dagu_provider import DaguProvider


def _integration_enabled() -> bool:
    return os.getenv("DAGU_INTEGRATION_ENABLED", "").strip().lower() == "true"


@pytest.mark.skipif(
    not _integration_enabled(),
    reason="BLOCKED: 需要显式设置 DAGU_INTEGRATION_ENABLED=true 及受控隔离 Dagu 实例才允许联网执行",
)
def test_live_dagu_connectivity_and_dag_contract():
    base_url = (os.getenv("DAGU_BASE_URL") or "").strip()
    api_key = (os.getenv("DAGU_API_KEY") or "").strip()
    assert base_url and api_key, "DAGU_BASE_URL and DAGU_API_KEY must be set when enabled"

    client = DaguClient(
        base_url,
        api_key,
        allow_insecure_http=os.getenv("DAGU_ALLOW_INSECURE_HTTP", "").lower() == "true",
    )
    provider = DaguProvider(client)
    try:
        health = client.get_health()
        assert health.get("status") == "healthy"
        dags = provider.list_dags()
        assert isinstance(dags, list)
        dag_name = (os.getenv("DAGU_TEST_DAG_NAME") or "").strip()
        if dag_name:
            conn = provider.test_connection(dag_name)
            assert conn.ok is True
            runs = client.list_runs(dag_name, limit=5)
            assert isinstance(runs, list)
    finally:
        provider.close()
