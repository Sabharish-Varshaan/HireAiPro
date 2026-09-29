"""Demo-day warm-up: loads BGE-M3 + the reranker in the running API and Celery
worker so the first real request doesn't wait ~15 s. Infrastructure only.

    cd backend && .venv/bin/python scripts/warm_demo_models.py --email admin@example.com

Models still unload after MODEL_IDLE_UNLOAD_SECONDS; for a presentation start
the stack with MODEL_IDLE_UNLOAD_SECONDS=1200 (docs/MEMORY_PROFILE.md).
"""
import argparse
import getpass
import json
import os
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("--api", default="http://localhost:8020/api/v1")
p.add_argument("--email", required=True, help="platform admin account")
a = p.parse_args()
pw = os.environ.get("HIREAI_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")


def post(path, body=None, token=None):
    req = urllib.request.Request(a.api + path, method="POST", data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


tok = post("/auth/login", {"email": a.email, "password": pw})["access_token"]
print(json.dumps(post("/admin/ops/warm-models", token=tok), indent=2))
