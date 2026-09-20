"""Response models shared across routers.

Moved out of routers/metrics.py, which had become a schemas module for
ops.py and labels.py as well as a router (both did `from .metrics import
Rate`). A pure move: FastAPI names schemas after the class, so the OpenAPI
document is unchanged.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Rate(BaseModel):
    value: float | None
    n: int
    ci_low: float
    ci_high: float


class RecRate(Rate):
    experimental: bool


class AvgPosition(BaseModel):
    value: float | None
    n_mentioned: int


class FiltersOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # a Filters dataclass
    engine: str | None
    locale_id: uuid.UUID | None
    date_from: datetime | None
    date_to: datetime | None
    prompt_ids: list[uuid.UUID] | None


class Window(BaseModel):
    mention_rate: Rate
    recommendation_rate: RecRate
    citation_rate: Rate
    prompt_coverage: Rate
    sov: Rate
    avg_position: AvgPosition
    n_failed: int
    pipeline_versions: list[str]
    pipeline_version: str
    computed_at: datetime


class MetricsOut(Window):
    filters: FiltersOut


class DeltaWindow(Window):
    from_: datetime = Field(alias="from")
    to: datetime


class Delta(BaseModel):
    value: float | None
    ci_low: float | None
    ci_high: float | None
    label: Literal[
        "increase", "decrease", "no significant change", "insufficient data"
    ]


class DeltasOut(BaseModel):
    before: DeltaWindow
    after: DeltaWindow
    comparable: bool
    reason: str | None
    deltas: dict[str, Delta] | None


class SovEntity(BaseModel):
    entity_id: uuid.UUID
    name: str
    type: Literal["brand", "competitor"]
    mentions: int
    share: float | None
    ci_low: float
    ci_high: float


class SovOut(BaseModel):
    filters: FiltersOut
    entities: list[SovEntity]
    n_failed: int
    pipeline_version: str
    computed_at: datetime


class EntityRate(Rate):
    entity_id: uuid.UUID
    name: str
    type: Literal["brand", "competitor"]


class PromptMetricsOut(BaseModel):
    prompt_id: uuid.UUID
    text: str
    intent: str | None
    topic: str | None
    n: int
    brand: EntityRate
    entities: list[EntityRate]
    top_competitor: EntityRate | None
    spread: float | None
    # Projections, not measurements: they hold the observed rates fixed.
    needs_samples: int | None
    needs_days: int | None
    separated: bool
