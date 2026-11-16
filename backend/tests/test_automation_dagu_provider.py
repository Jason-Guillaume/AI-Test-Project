"""Dagu provider-to-platform status and execution contract coverage."""

from __future__ import annotations

from app.features.automation_center.providers.base import ProviderError
from app.features.automation_center.providers.dagu_provider import DaguProvider


class FakeDaguClient:
    """Small in-memory implementation of the REST operations used by DaguProvider."""

    def __init__(self):
        self.enqueued = []
        self.stopped = []
        self.dequeued = []
        self.run = {"dagRunId": "automation-17", "statusLabel": "queued"}

    def close(self):
        """Implement client cleanup without opening a socket."""

    def get_openapi(self):
        """Return a representative Dagu OpenAPI document."""
        return {"info": {"version": "1.3.0"}}

    def get_health(self):
        """Return the server version reported by the Dagu health endpoint."""
        return {"version": "1.3.1"}

    def list_dags(self):
        """Return one DAG visible to the API key."""
        return [{"fileName": "automation-pytest-allure", "description": "pytest"}]

    def get_dag_spec(self, name):
        """Return the requested DAG spec."""
        return {"name": name}

    def enqueue(self, name, params, run_id, queue):
        """Capture the parameters passed to Dagu and return its run identifier."""
        self.enqueued.append({"name": name, "params": params, "run_id": run_id, "queue": queue})
        return {"dagRunId": run_id, "statusLabel": "queued"}

    def get_run(self, name, run_id):
        """Return the configured fake run state."""
        return dict(self.run)

    def stop(self, name, run_id):
        """Capture a running DAG stop request."""
        self.stopped.append((name, run_id))

    def dequeue(self, name, run_id):
        """Capture a queued DAG dequeue request."""
        self.dequeued.append((name, run_id))

    def get_log(self, name, run_id, **kwargs):
        """Return one bounded log excerpt."""
        return "pytest output"

    def list_runs(self, name, *, limit):
        """Return a representative historical run."""
        return [{"dagRunId": "automation-17", "statusLabel": "succeeded"}]


def test_dagu_connection_reports_real_service_version_and_dag_access():
    client = FakeDaguClient()
    provider = DaguProvider(client)
    result = provider.test_connection("automation-pytest-allure")
    assert result.ok is True
    assert result.service_version == "1.3.1"
    assert result.sample_run_count == 1
    assert provider.list_dags()[0]["fileName"] == "automation-pytest-allure"


def test_dagu_trigger_uses_stable_id_and_filters_credentials_and_unknown_fields():
    client = FakeDaguClient()
    provider = DaguProvider(client)
    result = provider.trigger_run("automation-pytest-allure", {
        "execution_id": 17,
        "automation_project_id": 5,
        "integration_config_id": 4,
        "repository_url": "https://codeup.aliyun.com/team/repo.git",
        "branch": "main",
        "callback_key": "callback-key-must-not-cross",
        "callback_secret": "callback-secret-must-not-cross",
        "callback_url": "https://platform.example/callback",
        "dagu_api_key": "dagu-key-must-not-cross",
        "unexpected": "must-not-cross",
    })
    assert result.external_run_id == "automation-17"
    assert result.status == "PENDING"
    submitted = client.enqueued[0]
    assert submitted["run_id"] == "automation-17"
    assert submitted["queue"] == "automation-tests"
    assert submitted["params"]["branch"] == "main"
    assert not {"callback_key", "callback_secret", "callback_url", "dagu_api_key", "unexpected"} & set(submitted["params"])


def test_dagu_lifecycle_maps_status_logs_stop_and_queue_removal():
    client = FakeDaguClient()
    provider = DaguProvider(client)
    assert provider.get_run("automation-pytest-allure", "automation-17").status == "PENDING"
    assert provider.get_log("automation-pytest-allure", "automation-17") == "pytest output"
    assert provider.stop_run("automation-pytest-allure", "automation-17") is True
    assert client.dequeued == [("automation-pytest-allure", "automation-17")]

    client.run = {"dagRunId": "automation-17", "statusLabel": "running"}
    assert provider.stop_run("automation-pytest-allure", "automation-17") is True
    assert client.stopped == [("automation-pytest-allure", "automation-17")]

    for raw, expected in (("succeeded", "SUCCESS"), ("failed", "FAILED"), ("aborted", "FAILED"), ("partially_succeeded", "FAILED")):
        assert DaguProvider._from_payload({"statusLabel": raw}).status == expected
    assert provider.list_runs("automation-pytest-allure")[0].status == "SUCCESS"


def test_dagu_enqueue_conflict_recovers_the_existing_stable_run():
    class ConflictClient(FakeDaguClient):
        """Simulate an enqueue whose response was lost after Dagu accepted the run."""

        def enqueue(self, name, params, run_id, queue):
            """Raise the Dagu duplicate run response."""
            raise ProviderError("conflict", 409)

    result = DaguProvider(ConflictClient()).trigger_run("automation-pytest-allure", {"execution_id": 17})
    assert result.external_run_id == "automation-17"
