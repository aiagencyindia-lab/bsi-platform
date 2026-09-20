"""Brand wizard: create a brand, suggest competitors and prompts, review.

usage: BSI_KEY=bsi_... uv run python scripts/wizard.py eval/run1.json \
           [--category "kids footwear"] [--count 50] [--activate 50]

The spec is a live_run.py file; only name, aliases, domains and (if
present) category are read. Suggestions replace its prompt and
competitor lists, which is the point of the wizard.
"""

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

POLL_SECONDS = 3
TIMEOUT_SECONDS = 180


def post(api: httpx.Client, path: str, body: Any = None) -> dict[str, Any]:
    r = api.post(path, json=body)
    if r.is_error:
        print(r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()
    return r.json()


def get(api: httpx.Client, path: str, **params: Any) -> Any:
    r = api.get(path, params=params)
    r.raise_for_status()
    return r.json()


def patch(api: httpx.Client, path: str, body: Any) -> dict[str, Any]:
    r = api.patch(path, json=body)
    if r.is_error:
        print(r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()
    return r.json()


def wait_for(
    api: httpx.Client, jobs: dict[str, str], started: float
) -> dict[str, Any]:
    """Poll every job until it leaves queued/running, or time runs out."""
    done: dict[str, Any] = {}
    while (
        len(done) < len(jobs) and time.monotonic() - started < TIMEOUT_SECONDS
    ):
        for label, job_id in jobs.items():
            if label in done:
                continue
            job = get(api, f"/jobs/{job_id}")
            if job["status"] not in ("queued", "running"):
                job["seconds"] = round(time.monotonic() - started, 2)
                done[label] = job
                print(
                    f"  {label}: {job['status']} in {job['seconds']}s, "
                    f"cost {job['cost_micros']} micros "
                    f"{job['error'] or ''}".rstrip()
                )
        if len(done) < len(jobs):
            time.sleep(POLL_SECONDS)
    for label, job_id in jobs.items():
        if label not in done:
            print(f"  {label}: still running after {TIMEOUT_SECONDS}s")
            done[label] = get(api, f"/jobs/{job_id}")
    return done


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("spec")
    p.add_argument("--category", default=None)
    p.add_argument("--count", type=int, default=50)
    p.add_argument(
        "--activate",
        type=int,
        default=0,
        help="activate this many suggested prompts",
    )
    p.add_argument("--brand", default=None, help="skip creation; use this id")
    a = p.parse_args()

    spec = json.load(open(a.spec))
    api = httpx.Client(
        base_url=os.environ.get("BSI_URL", "http://127.0.0.1:8000/v1"),
        headers={"Authorization": f"Bearer {os.environ['BSI_KEY']}"},
        timeout=30,
    )

    if a.brand:
        brand_id = a.brand
    else:
        brand = post(
            api,
            "/brands",
            {
                "name": spec["brand"],
                "aliases": spec.get("aliases", []),
                "category": a.category or spec.get("category"),
            },
        )
        brand_id = brand["id"]
        for host in spec.get("domains", []):
            post(api, f"/brands/{brand_id}/domains", {"host": host})
    base = f"/brands/{brand_id}"
    print(f"brand {brand_id} ({a.category or spec.get('category')})")

    started = time.monotonic()
    competitor_job = post(api, f"{base}/competitors/suggest")
    prompt_job = post(api, f"{base}/prompts/suggest", {"count": a.count})
    print(
        f"jobs: competitors {competitor_job['job_id']} "
        f"prompts {prompt_job['job_id']}"
    )
    wait_for(
        api,
        {
            "competitors": competitor_job["job_id"],
            "prompts": prompt_job["job_id"],
        },
        started,
    )

    print("== suggested competitors")
    for c in get(api, f"{base}/competitors", status="suggested"):
        print(f"  {c['evidence']}/3 {c['name']} {','.join(c['domains'])}")

    suggested = get(api, f"{base}/prompts", status="suggested")
    print(f"== suggested prompts ({len(suggested)})")
    for row in suggested:
        print(f"  [{row['intent']}/{row['topic']}] {row['text']}")

    print("== clusters")
    for cluster in get(api, f"{base}/clusters"):
        print(
            f"  {cluster['intent']}/{cluster['topic']}: "
            f"active {cluster['active']} suggested {cluster['suggested']} "
            f"paused {cluster['paused']}"
        )

    ids = [row["id"] for row in suggested]
    if ids:
        # A no-op bulk patch: every bulk response carries the preview, so
        # this reads it without changing a status.
        preview = patch(
            api, f"{base}/prompts", {"ids": ids, "status": "suggested"}
        )
        print("== cost preview", json.dumps(preview["cost_preview"]))
    if a.activate and ids:
        out = patch(
            api,
            f"{base}/prompts",
            {"ids": ids[: a.activate], "status": "active"},
        )
        print(
            f"== activated {out['updated']}",
            json.dumps(out["cost_preview"]),
        )


if __name__ == "__main__":
    main()
