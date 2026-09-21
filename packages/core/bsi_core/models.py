"""SQLAlchemy models. Table and column names follow PRD §7.2."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

INTENTS = (
    "informational",
    "commercial",
    "transactional",
    "comparison",
    "alternative",
    "recommendation",
    "problem-based",
    "industry-specific",
    "persona-specific",
    "geographic",
)

REC_STATUSES = ("recommended", "listed", "mentioned", "negative")

REC_TYPES = (
    "pursue_citation_source",
    "create_content",
    "add_competitor",
    "sample_more",
)
REC_STATES = ("open", "accepted", "dismissed")
TASK_STATUSES = ("open", "in_progress", "done", "impact_measured")
IMPACT_LABELS = (
    "improved",
    "no_change",
    "declined",
    "insufficient_data",
    # brand_deltas refuses windows with mixed pipeline versions; that is
    # not a shortage of data and must not be reported as one.
    "not_comparable",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


TSZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[type, Any]] = {
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


class Row:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(TSZ, server_default=func.now())


class Tenant(Row):
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id"), index=True
    )


class Organization(Row, Base):
    __tablename__ = "organization"
    name: Mapped[str]
    plan: Mapped[str] = mapped_column(server_default="starter")
    region: Mapped[str] = mapped_column(server_default="asia-south1")
    settings: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    daily_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    __table_args__ = (
        CheckConstraint("daily_budget_usd >= 0", name="ck_organization_budget"),
    )


class Workspace(Tenant, Base):
    __tablename__ = "workspace"
    name: Mapped[str]


class ApiKey(Tenant, Base):
    __tablename__ = "api_key"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace.id"))
    hashed_key: Mapped[str] = mapped_column(unique=True)
    scopes: Mapped[list[str]] = mapped_column(server_default="{}")
    last_used_at: Mapped[datetime | None] = mapped_column(TSZ)
    expires_at: Mapped[datetime | None] = mapped_column(TSZ)


class Brand(Tenant, Base):
    __tablename__ = "brand"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace.id"))
    name: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(server_default="{}")
    category: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="active")


class Domain(Tenant, Base):
    __tablename__ = "domain"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    host: Mapped[str]
    is_primary: Mapped[bool] = mapped_column(server_default="false")
    __table_args__ = (UniqueConstraint("brand_id", "host"),)


class Competitor(Tenant, Base):
    __tablename__ = "competitor"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    name: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(server_default="{}")
    domains: Mapped[list[str]] = mapped_column(server_default="{}")
    status: Mapped[str] = mapped_column(server_default="active")
    # How many of the three suggestion answers named this competitor.
    evidence: Mapped[int | None]
    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested', 'active')", name="ck_competitor_status"
        ),
    )


class Locale(Tenant, Base):
    __tablename__ = "locale"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    country: Mapped[str]
    language: Mapped[str]


class Prompt(Tenant, Base):
    __tablename__ = "prompt"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    locale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locale.id"))
    text: Mapped[str]
    source: Mapped[str] = mapped_column(server_default="manual")
    status: Mapped[str] = mapped_column(server_default="active")
    intent: Mapped[str | None]
    topic: Mapped[str | None]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    __table_args__ = (
        CheckConstraint(
            "intent IS NULL OR intent IN ("
            + ", ".join(f"'{i}'" for i in INTENTS)
            + ")",
            name="ck_prompt_intent",
        ),
        CheckConstraint(
            "status IN ('suggested', 'active', 'paused', 'archived')",
            name="ck_prompt_status",
        ),
        CheckConstraint(
            "source IN ('manual', 'generated')", name="ck_prompt_source"
        ),
    )


class Engine(Row, Base):
    __tablename__ = "engine"
    code: Mapped[str] = mapped_column(unique=True)
    provider: Mapped[str]
    default_model: Mapped[str]


class Job(Tenant, Base):
    __tablename__ = "job"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    kind: Mapped[str] = mapped_column(server_default="run")
    scheduled_slot: Mapped[datetime] = mapped_column(TSZ)
    # NULL for kind='run': those rows are driven by their observations.
    status: Mapped[str | None]
    params: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    error: Mapped[str | None]
    cost_micros: Mapped[int] = mapped_column(server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(TSZ)
    __table_args__ = (
        UniqueConstraint("brand_id", "kind", "scheduled_slot"),
        Index(
            "ix_job_queued",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        CheckConstraint(
            "status IS NULL OR status IN "
            "('queued', 'running', 'done', 'failed')",
            name="ck_job_status",
        ),
    )


class Schedule(Tenant, Base):
    __tablename__ = "schedule"
    brand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("brand.id"), unique=True
    )
    cadence: Mapped[str]
    hour_utc: Mapped[int]
    samples: Mapped[int] = mapped_column(server_default="2")
    status: Mapped[str] = mapped_column(server_default="active")
    next_run_at: Mapped[datetime] = mapped_column(TSZ)
    last_run_at: Mapped[datetime | None] = mapped_column(TSZ)
    last_result: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(
            "cadence IN ('daily', 'every_3_days', 'weekly')",
            name="ck_schedule_cadence",
        ),
        CheckConstraint("hour_utc BETWEEN 0 AND 23", name="ck_schedule_hour"),
        CheckConstraint("samples BETWEEN 1 AND 10", name="ck_schedule_samples"),
        CheckConstraint(
            "status IN ('active', 'paused')", name="ck_schedule_status"
        ),
    )


class Observation(Tenant, Base):
    __tablename__ = "observation"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id"))
    prompt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prompt.id"))
    engine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("engine.id"))
    locale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locale.id"))
    sample_index: Mapped[int]
    scheduled_slot: Mapped[datetime] = mapped_column(TSZ)
    status: Mapped[str] = mapped_column(server_default="queued")
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(TSZ)
    error: Mapped[str | None]
    model: Mapped[str | None]
    model_version: Mapped[str | None]
    params: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    raw_uri: Mapped[str | None]
    cost_micros: Mapped[int] = mapped_column(server_default="0")
    search_queries: Mapped[int | None]
    # Set at insert, overwritten when a worker claims the row.
    requested_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(TSZ)
    __table_args__ = (
        UniqueConstraint(
            "prompt_id", "engine_id", "scheduled_slot", "sample_index"
        ),
        Index(
            "ix_observation_lookup",
            "org_id",
            "brand_id",
            "prompt_id",
            "engine_id",
            "requested_at",
        ),
        Index("ix_observation_queue", "status", "next_attempt_at"),
        CheckConstraint(
            "status IN "
            "('queued', 'running', 'retry', 'fetched', 'done', 'failed')",
            name="ck_observation_status",
        ),
    )


class Extraction(Tenant, Base):
    __tablename__ = "extraction"
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation.id"), unique=True
    )
    pipeline_version: Mapped[str]
    model_used: Mapped[str]
    brand_mentioned: Mapped[bool]
    position: Mapped[int | None]
    rec_status: Mapped[str | None]
    sentiment: Mapped[str | None]
    sentiment_conf: Mapped[float | None]
    context: Mapped[str] = mapped_column(server_default="")
    absence_reason: Mapped[str | None]
    parsed: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    cost_micros: Mapped[int] = mapped_column(server_default="0")


class Mention(Tenant, Base):
    __tablename__ = "mention"
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation.id")
    )
    entity_type: Mapped[str]  # "brand" | "competitor"
    entity_id: Mapped[uuid.UUID]
    position: Mapped[int]
    rec_status: Mapped[str]
    sentiment: Mapped[str]
    evidence_sentence: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint("observation_id", "entity_id"),
        Index("ix_mention_entity", "org_id", "entity_id", "observation_id"),
    )


class Citation(Tenant, Base):
    __tablename__ = "citation"
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation.id")
    )
    url: Mapped[str]
    domain: Mapped[str]
    position: Mapped[int]
    is_brand_owned: Mapped[bool] = mapped_column(server_default="false")
    __table_args__ = (
        Index("ix_citation_domain", "org_id", "domain", "observation_id"),
    )


class RecLabel(Tenant, Base):
    """A hand label for one mention, to score the judge against."""

    __tablename__ = "rec_label"
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation.id")
    )
    entity_type: Mapped[str]
    entity_id: Mapped[uuid.UUID]
    label: Mapped[str]
    __table_args__ = (
        UniqueConstraint("observation_id", "entity_id"),
        CheckConstraint(
            "label IN (" + ", ".join(f"'{x}'" for x in REC_STATUSES) + ")",
            name="ck_rec_label_label",
        ),
    )


class Recommendation(Tenant, Base):
    """A suggested action, generated by rules from a brand's evidence."""

    __tablename__ = "recommendation"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    type: Mapped[str]
    # What it is about - a domain, a prompt id, a competitor id. With the
    # brand and type it is the identity that regeneration upserts on.
    subject_key: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="open")
    dismiss_reason: Mapped[str | None]
    title: Mapped[str]
    body: Mapped[str]
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    reach: Mapped[float]
    pressure: Mapped[float]
    feasibility: Mapped[float]
    priority: Mapped[float]
    __table_args__ = (
        UniqueConstraint("brand_id", "type", "subject_key"),
        CheckConstraint(_in("type", REC_TYPES), name="ck_recommendation_type"),
        CheckConstraint(
            _in("status", REC_STATES), name="ck_recommendation_status"
        ),
    )


class Task(Tenant, Base):
    """An accepted recommendation, followed through to a measured outcome."""

    __tablename__ = "task"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendation.id")
    )
    title: Mapped[str]
    owner: Mapped[str | None]  # free text: there are no user accounts yet
    due_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default="open")
    notes: Mapped[str] = mapped_column(server_default="")
    # The prompts the task is meant to move; empty means the whole brand.
    prompt_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default="{}"
    )
    done_at: Mapped[datetime | None] = mapped_column(TSZ)
    window_days: Mapped[int | None]
    impact_label: Mapped[str | None]
    impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("recommendation_id"),
        CheckConstraint(_in("status", TASK_STATUSES), name="ck_task_status"),
        CheckConstraint(
            "impact_label IS NULL OR " + _in("impact_label", IMPACT_LABELS),
            name="ck_task_impact_label",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress') "
            "OR (done_at IS NOT NULL AND window_days IS NOT NULL)",
            name="ck_task_done_has_window",
        ),
    )
