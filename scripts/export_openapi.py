"""Write the API's OpenAPI document. usage: export_openapi.py OUT.json"""

import json
import sys
from pathlib import Path

from bsi_api.main import app

Path(sys.argv[1]).write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
)
