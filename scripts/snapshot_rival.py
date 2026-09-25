"""Snapshot competitor domains, read-only: nothing is stored.

usage: uv run python scripts/snapshot_rival.py <host> [<host> ...]
No model spend; real HTTP fetches to the named hosts."""

import json
import sys
import time
from functools import partial

from bsi_core.crawl import PAUSE_SECONDS, SITEMAP_CAP_BYTES, http_fetch
from bsi_core.rivals import snapshot_domain

SITEMAP_FETCH = partial(http_fetch, cap=SITEMAP_CAP_BYTES, raw=True)

if len(sys.argv) < 2:
    sys.exit(__doc__)
for host in sys.argv[1:]:
    start = time.monotonic()
    snap = snapshot_domain(
        host,
        http_fetch,
        set(),
        pause=PAUSE_SECONDS,
        sitemap_fetch=SITEMAP_FETCH,
    )
    seconds = round(time.monotonic() - start, 1)
    print(
        json.dumps(
            {
                "host": host,
                "urls": len(snap.urls),
                "complete": snap.complete,
                "errors": snap.errors,
                "fetches": snap.fetches,
                "seconds": seconds,
                "skipped": len(snap.skipped),
                "pages": snap.pages,
                "domain_types": snap.domain_types,
            },
            indent=2,
        )
    )
