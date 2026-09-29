#!/bin/bash
# Fixes "Internal Error ... No such file or directory @ rb_sysopen - /box/script.py" from Judge0.
# Cause: Judge0 names each sandbox after its submission id, and isolate 2.x only allows box ids 0-999 ("Sandbox ID out of range").
# After ~1000 executions on a long-lived local Judge0 every run fails. This clears Judge0's OWN execution log (its scratch database, container
# hireai_judge0_db) and restarts the id counter. HireAiPro keeps its results in its own database, so nothing of the app is touched.
set -euo pipefail
docker exec hireai_judge0_db psql -U judge0 -d judge0 -tAc "TRUNCATE submissions RESTART IDENTITY;"
echo "Judge0 submission ids reset. Verify:"
echo '  curl -s -X POST "localhost:2358/submissions?base64_encoded=false" -H "Content-Type: application/json" -d '"'"'{"source_code":"print(6*7)","language_id":71}'"'"
