#!/bin/sh
set -eu

# The checked-in local .env points at localhost; inside Compose the database
# is reachable through its service name on the project network.
DATABASE_URL="$(python - <<'PY'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
if url.host in {"127.0.0.1", "localhost"}:
    url = url.set(host="postgres", port=5432)
print(url.render_as_string(hide_password=False))
PY
)"
export DATABASE_URL

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    python -m alembic upgrade head
fi

exec "$@"
