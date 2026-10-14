#!/bin/sh
cd "$(dirname "$0")"
./.venv/bin/python -I -m pytest tests/test_tmp_audit.py -q -s > /tmp/audit_out.txt 2>&1
grep -E "REBUILT|CASE_PROMPT|STATE2|REGEN|GEN_CASES|EXEC_EXIST|FRESH_CONFIRM|passed|failed" /tmp/audit_out.txt | head -40
