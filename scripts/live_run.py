"""Load a brand from JSON, run it, wait, print metrics.

usage: BSI_KEY=bsi_... python scripts/live_run.py eval/run1.json
"""

import json
import os
import sys
import time

import httpx

spec = json.load(open(sys.argv[1]))
api = httpx.Client(
    base_url=os.environ.get("BSI_URL", "http://127.0.0.1:8000/v1"),
    headers={"Authorization": f"Bearer {os.environ['BSI_KEY']}"},
    timeout=30,
)


def post(path: str, body: object) -> dict:
    r = api.post(path, json=body)
    if r.is_error:
        print(r.status_code, r.text)
    r.raise_for_status()
    return r.json()


brand = post("/brands", {"name": spec["brand"], "aliases": spec["aliases"]})
base = f"/brands/{brand['id']}"
for host in spec["domains"]:
    post(f"{base}/domains", {"host": host})
for comp in spec["competitors"]:
    post(f"{base}/competitors", comp)
post(f"{base}/prompts", [{"text": t} for t in spec["prompts"]])
run = post(
    f"{base}/runs",
    {"samples": spec.get("samples", 3), "retry_failed": True},
)
print("brand", brand["id"], "job", run["job_id"], "enqueued", run["enqueued"])

while True:
    job = api.get(f"/jobs/{run['job_id']}").json()
    print({k: job[k] for k in ("status", "total", "done", "failed", "retry")})
    if job["status"] == "done":
        break
    time.sleep(10)

for path in ("metrics", "sov"):
    print(json.dumps(api.get(f"{base}/{path}").json(), indent=1, default=str))
