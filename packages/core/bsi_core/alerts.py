"""Alerts (PRD F15, alerts only): changes worth telling the operator about.

Each detector reads rolling windows of stored answers, so nothing here can
fire from a single observation. `to` is a parameter everywhere so tests
are deterministic. Copy states what was observed and never promises.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import models as m
from .citations import EVIDENCE_CAP
from .competitors import visibility_changes
from .matching import is_owned
from .metrics import Filters, brand_deltas
from .recommend import _rival_domains

DROP_DAYS = 7
DROP_MIN_PTS = 0.15
SHIFT_DAYS = 14
SOURCE_DAYS = 7
# ponytail: the PRD wants "authority above threshold"; there is no
# authority score, so a count of citing answers stands in for it.
NEW_SOURCE_MIN_ANSWERS = 5


@dataclass(frozen=True)
class Candidate:
    type: str
    subject_key: str
    title: str
    detail: dict[str, Any]
    window_from: datetime
    window_to: datetime


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def drop_copy(pts: float, before: float, after: float) -> str:
    return (
        f"Mention rate fell {pts * 100:.1f} points over the last "
        f"{DROP_DAYS} days ({_pct(before)} to {_pct(after)})"
    )


def shift_copy(name: str, direction: str, n_prompts: int) -> str:
    how = "more" if direction == "up" else "less"
    return (
        f"{name} was named {how} often on {n_prompts} prompts over the "
        f"last {SHIFT_DAYS} days"
    )


def source_copy(domain: str, answers: int) -> str:
    return (
        f"{domain} was cited in {answers} answers, the first time in the "
        f"last {SOURCE_DAYS} days"
    )


def detect_mention_drop(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    d = brand_deltas(s, brand_id, Filters(), DROP_DAYS, to)
    if not d["comparable"]:
        return []
    delta = d["deltas"]["mention_rate"]
    # Rounded: 0.45 - 0.6 is -0.14999999999999997 in floats.
    if delta["label"] != "decrease" or round(delta["value"], 9) > -DROP_MIN_PTS:
        return []
    before, after = d["before"]["mention_rate"], d["after"]["mention_rate"]
    return [
        Candidate(
            "mention_drop",
            "mention_rate",
            drop_copy(-delta["value"], before["value"], after["value"]),
            {
                "before": before,
                "after": after,
                "delta": delta,
                "prompt_ids": [],
                "observation_ids": [],
            },
            d["after"]["from"],
            d["after"]["to"],
        )
    ]


def detect_competitor_shift(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    out = visibility_changes(s, brand_id, Filters(), SHIFT_DAYS, to)
    return [
        Candidate(
            "competitor_shift",
            f"{e['competitor_id']}:{e['direction']}",
            shift_copy(e["name"], e["direction"], len(e["prompts"])),
            {
                "competitor_id": e["competitor_id"],
                "name": e["name"],
                "direction": e["direction"],
                "before": e["before"],
                "after": e["after"],
                "delta": e["delta"],
                "prompt_ids": [p["prompt_id"] for p in e["prompts"]],
                "observation_ids": e["observation_ids"],
            },
            out["window"]["split"],
            out["window"]["to"],
        )
        for e in out["changes"]
    ]


# first_seen is over all answers before :to, so a domain cited a year ago
# is never "new"; the answer count is inside the window only.
_NEW_SOURCES = f"""
WITH first AS (
  SELECT c.domain, min(o.requested_at) AS first_seen
  FROM citation c JOIN observation o ON o.id = c.observation_id
  WHERE o.brand_id = :brand AND o.status = 'done' AND o.requested_at < :to
  GROUP BY c.domain)
SELECT f.domain, count(DISTINCT o.id) AS answers,
       (array_agg(DISTINCT o.id))[1:{EVIDENCE_CAP}] AS obs,
       (array_agg(DISTINCT o.prompt_id))[1:{EVIDENCE_CAP}] AS prompts
FROM first f
JOIN citation c ON c.domain = f.domain
JOIN observation o ON o.id = c.observation_id
WHERE f.first_seen >= :from AND o.brand_id = :brand AND o.status = 'done'
  AND o.requested_at >= :from AND o.requested_at < :to
GROUP BY f.domain
HAVING count(DISTINCT o.id) >= :min
ORDER BY 2 DESC, 1"""


def detect_new_source(
    s: Session, brand_id: uuid.UUID, to: datetime
) -> list[Candidate]:
    start = to - timedelta(days=SOURCE_DAYS)
    # Without a full window of history before this one every cited domain
    # looks new (Run 1: 54 "new" sources); a few older answers only delay
    # the flood. So the earliest answer must be two windows back.
    if not s.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM observation WHERE brand_id = :brand "
            "AND status = 'done' AND requested_at <= :baseline)"
        ),
        {"brand": brand_id, "baseline": to - timedelta(days=2 * SOURCE_DAYS)},
    ):
        return []
    hosts = list(
        s.scalars(select(m.Domain.host).where(m.Domain.brand_id == brand_id))
    )
    rivals = _rival_domains(s, brand_id)
    rows = s.execute(
        text(_NEW_SOURCES),
        {
            "brand": brand_id,
            "from": start,
            "to": to,
            "min": NEW_SOURCE_MIN_ANSWERS,
        },
    ).all()
    return [
        Candidate(
            "new_source",
            r.domain,
            source_copy(r.domain, r.answers),
            {
                "domain": r.domain,
                "answers": r.answers,
                "prompt_ids": list(r.prompts),
                "observation_ids": list(r.obs),
            },
            start,
            to,
        )
        for r in rows
        if not is_owned(r.domain, hosts) and not is_owned(r.domain, rivals)
    ]


DETECTORS = (detect_mention_drop, detect_competitor_shift, detect_new_source)


def is_duplicate(s: Session, brand_id: uuid.UUID, c: Candidate) -> bool:
    """An alert for the same subject whose window ends after this one
    starts. Windows of a type have one length, so that is "younger than
    the window"."""
    return (
        s.execute(
            text(
                "SELECT 1 FROM alert WHERE brand_id = :b AND type = :t "
                "AND subject_key = :k AND window_to > :wf LIMIT 1"
            ),
            {
                "b": brand_id,
                "t": c.type,
                "k": c.subject_key,
                "wf": c.window_from,
            },
        ).first()
        is not None
    )


def scan(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    to: datetime,
    *,
    deliver: bool,
) -> list[m.Alert]:
    """Run every detector and store what is not a duplicate. `deliver`
    is whether the brand has a webhook now: an alert stored without one
    is never delivered later."""
    rows = []
    for detect in DETECTORS:
        for c in detect(s, brand_id, to):
            if is_duplicate(s, brand_id, c):
                continue
            rows.append(
                m.Alert(
                    org_id=org_id,
                    brand_id=brand_id,
                    type=c.type,
                    subject_key=c.subject_key,
                    title=c.title,
                    # UUIDs and rate dicts -> plain JSON for JSONB.
                    detail=json.loads(json.dumps(c.detail, default=str)),
                    window_from=c.window_from,
                    window_to=c.window_to,
                    next_attempt_at=func.now() if deliver else None,
                )
            )
    s.add_all(rows)
    s.flush()
    return rows


def payload(alert: Any, brand_name: str) -> dict[str, Any]:
    """The webhook body. `text` is what a Slack incoming webhook renders;
    the rest is for other consumers. Serialise with default=str."""
    return {
        "id": alert.id,
        "type": alert.type,
        "brand_id": alert.brand_id,
        "brand": brand_name,
        "title": alert.title,
        "text": alert.title,
        "subject_key": alert.subject_key,
        "window_from": alert.window_from,
        "window_to": alert.window_to,
        "created_at": alert.created_at,
        "detail": alert.detail,
    }
