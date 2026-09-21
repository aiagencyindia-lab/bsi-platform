"""Impact: did a finished task's prompts move?

Marking a task done opens a window on its prompts. When it closes, the
mention rate over the window_days before done_at is compared with the
window_days after, through brand_deltas - the same Newcombe interval and
the same refusal of mixed pipeline versions the dashboard uses. What it
finds is an association: anything else that changed in those weeks is
mixed in.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models as m
from .db import tenant_session
from .metrics import Filters, brand_deltas

LABELS = {
    "increase": "improved",
    "decrease": "declined",
    "no significant change": "no_change",
    "insufficient data": "insufficient_data",
}


def measure(s: Session, task: m.Task) -> tuple[str, dict[str, Any]]:
    """The impact label and what it rests on. Call in the tenant session."""
    if task.done_at is None or task.window_days is None:
        raise ValueError("a task has a window only once it is done")
    days = task.window_days
    out = brand_deltas(
        s,
        task.brand_id,
        Filters(prompt_ids=list(task.prompt_ids) or None),
        days,
        task.done_at + timedelta(days=days),
    )
    payload: dict[str, Any] = {"metric": "mention_rate", "window_days": days}
    for side in ("before", "after"):
        payload[side] = {
            "from": out[side]["from"].isoformat(),
            "to": out[side]["to"].isoformat(),
            **out[side]["mention_rate"],
        }
    if not out["comparable"]:
        return "not_comparable", {
            **payload,
            "delta": None,
            "reason": out["reason"],
        }
    delta = out["deltas"]["mention_rate"]
    return LABELS[delta["label"]], {**payload, "delta": delta, "reason": None}


def close_window(org_id: uuid.UUID, task_id: uuid.UUID) -> str | None:
    """Measure one task whose window has closed; returns its label, or
    None if it was not due. Locks the row, so two workers cannot both
    measure it."""
    with tenant_session(org_id) as s:
        task = s.get(m.Task, task_id, with_for_update=True)
        if (
            task is None
            or task.status != "done"
            or not task.measures_impact
            or task.done_at is None
            or task.window_days is None
        ):
            return None
        now = s.scalars(select(func.now())).one()
        if task.done_at + timedelta(days=task.window_days) > now:
            return None
        label, payload = measure(s, task)
        task.impact_label, task.impact = label, payload
        task.status = "impact_measured"
        return label
