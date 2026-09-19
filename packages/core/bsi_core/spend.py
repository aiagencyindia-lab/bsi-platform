"""Live-spend guard. Scripts that call paid APIs check before each call."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from .config import get_settings
from .db import owner_engine


class SpendCapReached(RuntimeError):
    pass


_LOCK = threading.Lock()
# Reservations are per-process; one live script runs at a time.
_reserved = 0  # micros checked but not yet recorded, in this process


def _ledger(path: Path | None) -> Path:
    return path or Path(get_settings().raw_store_dir) / "spend_ledger.jsonl"


def record(
    kind: str, micros: int, ledger: Path | None = None, release: int = 0
) -> None:
    global _reserved
    with _LOCK:
        _reserved = max(0, _reserved - release)
        path = _ledger(ledger)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "micros": micros,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def ledger_micros(ledger: Path | None = None) -> int:
    path = _ledger(ledger)
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(
        int(json.loads(line)["micros"]) for line in lines if line.strip()
    )


_DB_SPEND = text(
    "SELECT coalesce(sum(o.cost_micros), 0) + coalesce(sum(e.cost_micros), 0) "
    "FROM observation o LEFT JOIN extraction e ON e.observation_id = o.id "
    "WHERE o.created_at >= :since"
)


def db_micros(since: datetime) -> int:
    with owner_engine().connect() as c:
        return int(c.execute(_DB_SPEND, {"since": since}).scalar_one())


def check(next_micros: int, ledger: Path | None = None) -> int:
    """Raise before a call that could cross the cap; return what remains."""
    global _reserved
    settings = get_settings()
    cap = round(settings.spend_cap_usd * 1_000_000)
    with _LOCK:
        spent = ledger_micros(ledger) + db_micros(settings.spend_since)
        if spent + _reserved + next_micros > cap:
            raise SpendCapReached(
                f"spent ${spent / 1e6:.2f} + next ${next_micros / 1e6:.3f} "
                f"> cap ${cap / 1e6:.2f}"
            )
        _reserved += next_micros
        return cap - spent - _reserved
