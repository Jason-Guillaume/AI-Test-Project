from scripts.docker_compose import database_url_for_compose


def test_loopback_database_targets_compose_postgres_service():
    value = "postgresql+psycopg://platform:p%40ss@127.0.0.1:55432/testplatform_dev?sslmode=disable"

    assert database_url_for_compose(value) == (
        "postgresql+psycopg://platform:p%40ss@postgres:5432/testplatform_dev?sslmode=disable"
    )


def test_explicit_external_database_host_is_preserved():
    value = "postgresql+psycopg://platform:secret@host.docker.internal:5432/testplatform_dev"

    assert database_url_for_compose(value) == value
