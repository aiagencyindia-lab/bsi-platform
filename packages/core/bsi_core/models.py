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
    "fix_crawlability",
    "fix_entity",
    "optimize_page",
    "respond_to_rival_content",
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
ALERT_TYPES = (
    "mention_drop",
    "competitor_shift",
    "new_source",
    "serp_drop",
)
REPORT_TYPES = ("cmo", "seo", "content", "pr", "agency")
REPORT_CADENCES = ("off", "weekly", "monthly")
RUN_SOURCES = ("scheduled", "manual")
PRODUCT_SOURCES = ("csv", "feed")
RULE_CHECKS = ("pass", "adjusted", "review")
SERP_KINDS = ("brand", "reviews")


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
    # Null = never refreshed, which due_recommendation_refreshes() treats
    # as due. Stamped by the worker's weekly pass, not by on-demand
    # generation: an operator's click should not defer the next pass.
    recs_refreshed_at: Mapped[datetime | None] = mapped_column(TSZ)
    # Null = never scanned, which due_alert_scans() treats as due.
    alerts_scanned_at: Mapped[datetime | None] = mapped_column(TSZ)
    # One HTTPS URL each new alert is POSTed to; null = no delivery.
    webhook_url: Mapped[str | None]
    # Shared with the receiver; read only by the worker when it signs a
    # delivery. Null = unsigned. Never returned by the API.
    webhook_secret: Mapped[str | None]

    @property
    def has_webhook_secret(self) -> bool:
        return self.webhook_secret is not None

    # Agency-report branding; all optional. Copied into the document at
    # build time, so the public route never reads this row.
    report_logo_url: Mapped[str | None]
    report_accent: Mapped[str | None]
    report_prepared_by: Mapped[str | None]


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
    # False where mention rate is not what the task can move (confirming a
    # competitor, taking samples): no window is opened or measured.
    measures_impact: Mapped[bool] = mapped_column(server_default="true")
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


class Alert(Tenant, Base):
    """A change worth telling the operator about, found by the daily scan
    over rolling windows. Never raised from a single observation.

    Delivery state lives on the row: attempts, the next attempt time and
    the last error. next_attempt_at NULL = not for delivery (no webhook at
    scan time, delivered, or given up).
    """

    __tablename__ = "alert"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    type: Mapped[str]
    # mention_rate | <competitor_id>:<up|down> | <domain>
    # | <kind>:<country>:<language> (serp_drop)
    subject_key: Mapped[str]
    title: Mapped[str]
    detail: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    window_from: Mapped[datetime] = mapped_column(TSZ)
    window_to: Mapped[datetime] = mapped_column(TSZ)
    delivered_at: Mapped[datetime | None] = mapped_column(TSZ)
    delivery_attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(TSZ)
    last_error: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(_in("type", ALERT_TYPES), name="ck_alert_type"),
        # Dedupe looks up (brand, type, subject) and reads window_to.
        Index(
            "ix_alert_subject", "brand_id", "type", "subject_key", "window_to"
        ),
        # The list reads a brand's alerts by creation time.
        Index("ix_alert_list", "brand_id", "created_at"),
        Index(
            "ix_alert_due",
            "next_attempt_at",
            postgresql_where=text(
                "delivered_at IS NULL AND next_attempt_at IS NOT NULL"
            ),
        ),
    )


class Report(Tenant, Base):
    """The definition: one row per (brand, type), created lazily.
    generated_at is stamped by the worker's scheduled pass only; a manual
    run must not defer the next scheduled one."""

    __tablename__ = "report"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    type: Mapped[str]
    cadence: Mapped[str] = mapped_column(server_default="off")
    generated_at: Mapped[datetime | None] = mapped_column(TSZ)
    __table_args__ = (
        CheckConstraint(_in("type", REPORT_TYPES), name="ck_report_type"),
        CheckConstraint(
            _in("cadence", REPORT_CADENCES), name="ck_report_cadence"
        ),
        UniqueConstraint("brand_id", "type", name="uq_report_brand_type"),
    )


class ReportRun(Tenant, Base):
    """One rendered report. `document` is the whole content, frozen at
    generation; the HTML page and the PDF only render it."""

    __tablename__ = "report_run"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report.id"))
    type: Mapped[str]
    source: Mapped[str]
    period_from: Mapped[datetime] = mapped_column(TSZ)
    period_to: Mapped[datetime] = mapped_column(TSZ)
    # The prior period is [compare_from, period_from).
    compare_from: Mapped[datetime] = mapped_column(TSZ)
    document: Mapped[dict[str, Any]]
    methodology_version: Mapped[str]
    # NULL = link revoked (or never shared).
    share_token: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(_in("type", REPORT_TYPES), name="ck_report_run_type"),
        CheckConstraint(
            _in("source", RUN_SOURCES), name="ck_report_run_source"
        ),
        Index("ix_report_run_list", "brand_id", "created_at"),
        Index(
            "ix_report_run_token",
            "share_token",
            unique=True,
            postgresql_where=text("share_token IS NOT NULL"),
        ),
    )


class Product(Tenant, Base):
    """One catalogue item (PRD F16). The catalogue columns are upserted
    on (brand_id, external_id) by every import; the result columns are
    written only by a product_run job, so a re-import keeps them."""

    __tablename__ = "product"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    external_id: Mapped[str]
    title: Mapped[str]
    description: Mapped[str | None]
    attributes: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    url: Mapped[str | None]
    price: Mapped[str | None]
    category: Mapped[str | None]
    source: Mapped[str]
    imported_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    keyword: Mapped[str | None]
    keywords: Mapped[list[str] | None]
    missing_keywords: Mapped[list[str] | None]
    suggested_title: Mapped[str | None]
    suggested_bullets: Mapped[list[str] | None]
    rule_check: Mapped[str | None]
    # Original-title words the suggestion lost (plurals folded); set
    # whenever rule_check is "review" (slice 19).
    dropped_words: Mapped[list[str] | None]
    # The three keyword-prompt sample lists choose_keywords received
    # (after _clean), and the rewrite call's title before rule_check
    # (slice 25). Read with psql; not exposed by the API.
    keyword_samples: Mapped[list[list[str]] | None] = mapped_column(JSONB)
    raw_title: Mapped[str | None]
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    result_at: Mapped[datetime | None] = mapped_column(TSZ)
    __table_args__ = (
        CheckConstraint(
            _in("source", PRODUCT_SOURCES), name="ck_product_source"
        ),
        CheckConstraint(
            "rule_check IS NULL OR " + _in("rule_check", RULE_CHECKS),
            name="ck_product_rule_check",
        ),
        UniqueConstraint(
            "brand_id", "external_id", name="uq_product_brand_external"
        ),
        Index("ix_product_list", "brand_id", "title"),
    )


class KeywordSearch(Tenant, Base):
    """The cached comparison set for one (brand, keyword): the product
    titles that rank for it, from one grounded answer. Reused for
    SEARCH_TTL_DAYS. This is the seam a SERP provider would replace."""

    __tablename__ = "keyword_search"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    keyword: Mapped[str]
    query: Mapped[str]
    titles: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    model: Mapped[str] = mapped_column(server_default="")
    cost_micros: Mapped[int] = mapped_column(server_default="0")
    searched_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    error: Mapped[str | None]
    __table_args__ = (
        UniqueConstraint(
            "brand_id", "keyword", name="uq_keyword_search_brand_keyword"
        ),
    )


class SerpAudit(Tenant, Base):
    """Google's first page for one brand query in one locale (slice 37,
    PRD F09); the latest row per (kind, country, language) is what the
    Brand SERP tab reads. A failed query is stored too (error set)."""

    __tablename__ = "serp_audit"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    kind: Mapped[str]
    query: Mapped[str]
    country: Mapped[str]
    language: Mapped[str]
    device: Mapped[str] = mapped_column(server_default="desktop")
    results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    fetched_at: Mapped[datetime] = mapped_column(TSZ)
    cost_micros: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(_in("kind", SERP_KINDS), name="ck_serp_audit_kind"),
        Index("ix_serp_audit_brand_fetched", "brand_id", "fetched_at"),
    )


class SiteAudit(Tenant, Base):
    """One crawlability audit of one brand domain; the latest row per
    domain is what the Site tab and the fix_crawlability rule read."""

    __tablename__ = "site_audit"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    domain: Mapped[str]
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    fetches: Mapped[int] = mapped_column(server_default="0")
    __table_args__ = (
        Index("ix_site_audit_latest", "brand_id", "domain", "created_at"),
    )


class PageAudit(Tenant, Base):
    """One scoring of one URL against one gap cluster; the latest row per
    (cluster_key, url) is what the Pages tab and the optimize_page rule
    read. A failed fetch is stored too (score NULL, error set)."""

    __tablename__ = "page_audit"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    url: Mapped[str]
    cluster_key: Mapped[str]
    status: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None]
    weights_version: Mapped[str]
    score: Mapped[int | None]
    components: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    suggestions: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    fetches: Mapped[int] = mapped_column(server_default="0")
    __table_args__ = (
        Index(
            "ix_page_audit_latest",
            "brand_id",
            "cluster_key",
            "url",
            "created_at",
        ),
    )


class RivalCrawl(Tenant, Base):
    """One crawl of one competitor domain. `baseline`: no earlier crawl
    of the domain read URLs (a domain stays a baseline until one does);
    its pages and types never count as new. `types`: JSON-LD @type ->
    the first URL it was seen on, this crawl."""

    __tablename__ = "rival_crawl"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitor.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    domain: Mapped[str]
    baseline: Mapped[bool] = mapped_column(server_default="false")
    complete: Mapped[bool] = mapped_column(server_default="false")
    urls_seen: Mapped[int] = mapped_column(server_default="0")
    new_urls: Mapped[int] = mapped_column(server_default="0")
    fetches: Mapped[int] = mapped_column(server_default="0")
    errors: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    types: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    __table_args__ = (
        Index(
            "ix_rival_crawl_latest",
            "brand_id",
            "competitor_id",
            "domain",
            "created_at",
        ),
    )


class RivalPage(Tenant, Base):
    """One URL a competitor's sitemap listed; first and last seen."""

    __tablename__ = "rival_page"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitor.id", ondelete="CASCADE")
    )
    domain: Mapped[str]
    url: Mapped[str]
    first_seen_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TSZ, server_default=func.now()
    )
    baseline: Mapped[bool] = mapped_column(server_default="false")
    types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    __table_args__ = (
        UniqueConstraint("competitor_id", "url"),
        Index(
            "ix_rival_page_new", "brand_id", "competitor_id", "first_seen_at"
        ),
    )
