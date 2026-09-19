"""Raw provider payloads. Local files now; Cloud Storage later."""

import json
import uuid
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from .config import get_settings


class RawStore(Protocol):
    def put(
        self,
        org_id: uuid.UUID,
        observation_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> str: ...

    def get(self, uri: str, org_id: uuid.UUID) -> dict[str, Any]: ...


class LocalRawStore:
    def __init__(self, base: str | None = None) -> None:
        self._base = Path(base or get_settings().raw_store_dir).resolve()

    def _org_root(self, org_id: uuid.UUID) -> Path:
        return self._base / "orgs" / str(org_id)

    def put(
        self,
        org_id: uuid.UUID,
        observation_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> str:
        path = self._org_root(org_id) / "raw" / f"{observation_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path.as_uri()

    def get(self, uri: str, org_id: uuid.UUID) -> dict[str, Any]:
        path = Path(unquote(urlparse(uri).path)).resolve()
        if not path.is_relative_to(self._org_root(org_id)):
            raise PermissionError("payload belongs to another organization")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return payload
