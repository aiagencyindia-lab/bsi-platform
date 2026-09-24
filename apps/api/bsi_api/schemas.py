"""Response models shared across routers.

Moved out of routers/metrics.py, which had become a schemas module for
ops.py and labels.py as well as a router (both did `from .metrics import
Rate`). A pure move: FastAPI names schemas after the class, so the OpenAPI
document is unchanged.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from bsi_core.pages import normalize_url
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


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


class SentimentOut(BaseModel):
    positive: Rate
    negative: Rate
    index: float | None


class CitingDomainOut(BaseModel):
    domain: str
    answers: int
    owner: Literal["brand", "rival", "third_party"]


class ClusterPromptOut(BaseModel):
    prompt_id: uuid.UUID
    text: str
    n: int
    absent: int


class ClusterRivalOut(BaseModel):
    competitor_id: uuid.UUID
    name: str
    answers: int


class TopRivalOut(Rate):
    competitor_id: uuid.UUID
    name: str


class BriefEvidenceOut(BaseModel):
    prompt_ids: list[uuid.UUID]
    observation_ids: list[uuid.UUID]


class BriefOut(BaseModel):
    target_queries: list[str]
    prompts_total: int
    page_type: str
    structure: list[str]
    competitors: list[str]
    sources: list[CitingDomainOut]
    internal_links: list[str]
    evidence: BriefEvidenceOut
    note: str


class GapClusterOut(BaseModel):
    intent: str
    topic: str
    key: str
    prompts: list[ClusterPromptOut]
    n: int
    brand: Rate
    absent: int
    rival_absent: int
    reasons: dict[str, int]
    reason: str | None
    rivals: list[ClusterRivalOut]
    top_rival: TopRivalOut | None
    spread: float | None
    cited: Rate
    sources: list[CitingDomainOut]
    brand_urls: list[str]
    gap: bool
    brief: BriefOut | None


class ClustersOut(BaseModel):
    unlabelled: int
    gaps: int
    clusters: list[GapClusterOut]


class EntityMetricsOut(BaseModel):
    entity_id: uuid.UUID
    name: str
    type: Literal["brand", "competitor"]
    mention_rate: Rate
    recommendation_rate: RecRate
    citation_rate: Rate
    prompt_coverage: Rate
    sov: Rate
    avg_position: AvgPosition
    sentiment: SentimentOut
    citing_domains: list[CitingDomainOut]


class EntityWindowOut(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime
    entities: list[EntityMetricsOut]


class EntityDeltasOut(BaseModel):
    before: EntityWindowOut
    after: EntityWindowOut
    comparable: bool
    reason: str | None
    deltas: dict[uuid.UUID, dict[str, Delta]] | None


class ChangePromptOut(BaseModel):
    prompt_id: uuid.UUID
    text: str
    before: Rate
    after: Rate


class ChangeOut(BaseModel):
    competitor_id: uuid.UUID
    name: str
    direction: Literal["up", "down"]
    before: Rate
    after: Rate
    delta: Delta
    prompts: list[ChangePromptOut]
    engines: list[str]
    new_citing_domains: list[str]
    observation_ids: list[uuid.UUID]


class ChangeWindowOut(BaseModel):
    before_from: datetime
    split: datetime
    to: datetime


class ChangesOut(BaseModel):
    comparable: bool
    reason: str | None
    prompts: int
    window: ChangeWindowOut
    changes: list[ChangeOut]


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


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    type: str
    subject_key: str
    status: str
    dismiss_reason: str | None
    title: str
    body: str
    evidence: dict[str, Any]
    reach: float
    pressure: float
    feasibility: float
    priority: float
    created_at: datetime


class DismissIn(BaseModel):
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    recommendation_id: uuid.UUID | None
    title: str
    owner: str | None
    due_date: date | None
    status: str
    notes: str
    prompt_ids: list[uuid.UUID]
    done_at: datetime | None
    window_days: int | None
    impact_label: str | None
    impact: dict[str, Any] | None
    measures_impact: bool
    created_at: datetime


class RivalOut(BaseModel):
    name: str
    answers: int


class SourceOut(BaseModel):
    """One cited domain. `source_type` is a keyword heuristic."""

    domain: str
    owner: Literal["brand", "rival", "third_party"]
    source_type: Literal["vendor", "video", "community", "review", "other"]
    answers: int
    prompts: int
    first_seen: datetime
    last_seen: datetime
    brand_named: int
    rivals: list[RivalOut]
    gap: bool
    observation_ids: list[uuid.UUID]


class TaskPatch(BaseModel):
    # Fields defaulting to Field(None) reject an explicit null with a 422;
    # owner and due_date are the two that may be cleared.
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "done", "impact_measured"] = Field(
        None
    )
    title: str = Field(None, min_length=1, max_length=300)
    notes: str = Field(None, max_length=5000)
    owner: str | None = Field(None, max_length=200)
    due_date: date | None = None


class QueuedOut(BaseModel):
    job_id: uuid.UUID
    status_url: str
    status: str


class CheckOut(BaseModel):
    code: str
    ok: bool
    severity: Literal["high", "medium", "low"]
    observed: str
    expected: str
    url: str

    @field_validator("severity", mode="before")
    @classmethod
    def _known_severity(cls, v: object) -> object:
        # A stored severity outside the set (edited data, a future rename)
        # reads as low: the rule already skips it, the page must not 500.
        return v if v in ("high", "medium", "low") else "low"


class SiteAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    created_at: datetime
    fetches: int
    job_id: uuid.UUID | None
    checks: list[CheckOut]


class PageOptimizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    cluster_key: str = Field(min_length=1, max_length=500)

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        # Its ValueError becomes a 422 on body.url.
        return normalize_url(v)


class ComponentOut(BaseModel):
    code: str
    weight: int
    value: float
    points: float
    observed: str
    evidence: list[str]


class SuggestionOut(BaseModel):
    text: str
    urls: list[str]
    prompt_ids: list[str]
    observation_ids: list[str]


class SuggestionsOut(BaseModel):
    # Defaults so a row inserted without suggestions (fixtures, the
    # server default '{}') still renders; the runner always writes all four.
    add: list[SuggestionOut] = []
    remove: list[SuggestionOut] = []
    rewrite: list[SuggestionOut] = []
    evidence_to_add: list[SuggestionOut] = []


class PageAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    job_id: uuid.UUID | None
    url: str
    cluster_key: str
    status: int
    error: str | None
    weights_version: str
    score: int | None
    components: list[ComponentOut]
    suggestions: SuggestionsOut
    evidence: dict[str, Any]
    fetches: int
