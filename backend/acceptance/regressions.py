import os, subprocess
from urllib.parse import urlsplit,unquote
url=urlsplit(os.environ['DATABASE_URL']);env=os.environ.copy()
env.update(TEST_POSTGRES_HOST=url.hostname,TEST_POSTGRES_PORT=str(url.port or 5432),TEST_POSTGRES_USER=unquote(url.username),TEST_POSTGRES_PASSWORD=unquote(url.password))
result=subprocess.run(['pytest','-q','tests/test_05_isolation.py','tests/test_35_tasks.py','tests/test_36_agent_governance_details.py','app/knowledge/tests','app/platform/model_configuration/tests','app/tools/tests/test_case_generation.py','app/features/asr_evaluation/tests/test_regressions.py','--tb=short'],cwd='/app',env=env)
raise SystemExit(result.returncode)
