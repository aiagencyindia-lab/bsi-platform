"""Record one real grounded answer: record_fixture.py "<prompt>" <name>"""

import json
import sys
from pathlib import Path

from bsi_core.providers.gemini import GeminiGroundingAdapter

prompt, name = sys.argv[1], sys.argv[2]
result = GeminiGroundingAdapter().query(prompt, "IN", "en")
if result.kind != "ok":
    sys.exit(f"{result.kind}: {result.error}")
out = Path("tests/fixtures") / f"gemini_{name}.json"
out.write_text(json.dumps(result.raw, indent=1), encoding="utf-8")
print(out, "cost_micros:", result.cost_micros)
