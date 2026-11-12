from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class PageType(str, enum.Enum):
    DRAFT = "Draft"
    HOMEPAGE = "Homepage"
    PLP = "PLP"
    PDP = "PDP"
    EDITORIAL = "Editorial"
    BRAND = "Brand"
    LANDING = "Landing"
    ASSET = "Asset"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    site_url: Mapped[str] = mapped_column(String(2048))
    locale: Mapped[str | None] = mapped_column(String(40))
    market: Mapped[str | None] = mapped_column(String(80))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict] = mapped_column(JSON, default=lambda: {"trailing_slash": "remove", "remove_tracking": True})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    pages: Mapped[list["Page"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("project_id", "normalized_url", name="uq_project_normalized_url"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    original_url: Mapped[str] = mapped_column(String(4096))
    normalized_url: Mapped[str] = mapped_column(String(4096))
    page_type: Mapped[str] = mapped_column(String(30), default=PageType.UNKNOWN.value, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    http_status_text: Mapped[str | None] = mapped_column(String(255))
    indexability: Mapped[str | None] = mapped_column(String(120))
    indexability_status: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(255))
    url_path: Mapped[str | None] = mapped_column(String(2048))
    sitemap_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    architecture_section: Mapped[str | None] = mapped_column(String(255))
    architecture_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), default="manual")
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    project: Mapped[Project] = relationship(back_populates="pages")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(80))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="staged")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reporting_date: Mapped[date | None] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class ImportRow(Base):
    __tablename__ = "import_rows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw_data: Mapped[dict] = mapped_column(JSON)
    normalized_data: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(30), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"))


class PageCrawlChange(Base):
    __tablename__ = "page_crawl_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    source_label: Mapped[str] = mapped_column(String(512))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)


# Reserved schemas for later phases. Kept deliberately minimal and not exposed by the API.
class PageRelationship(Base):
    __tablename__ = "page_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"))
    target_page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"))
    relationship_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="approved")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SitemapDocument(Base):
    __tablename__ = "sitemap_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(512))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    document_type: Mapped[str] = mapped_column(String(30))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    referenced_files: Mapped[list] = mapped_column(JSON, default=list)
    unresolved_references: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class SitemapEntry(Base):
    __tablename__ = "sitemap_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("sitemap_documents.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    loc: Mapped[str] = mapped_column(String(4096))
    normalized_url: Mapped[str | None] = mapped_column(String(4096), index=True)
    lastmod: Mapped[str | None] = mapped_column(String(80))
    changefreq: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str | None] = mapped_column(String(30))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    issue: Mapped[str | None] = mapped_column(Text)


class PageMetadataObservation(Base):
    __tablename__ = "page_metadata_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    source_label: Mapped[str] = mapped_column(String(255), default="Screaming Frog")
    reporting_date: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    supplied_fields: Mapped[list] = mapped_column(JSON, default=list)
    source_columns: Mapped[dict] = mapped_column(JSON, default=dict)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PageMetadataRecommendation(Base):
    __tablename__ = "page_metadata_recommendations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(40), default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    implemented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PageMetadataChange(Base):
    __tablename__ = "page_metadata_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id"), index=True)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("page_metadata_recommendations.id"), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewer: Mapped[str | None] = mapped_column(String(160))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)


class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("project_id", "normalized_phrase", "market", "language", name="uq_keyword_scope"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    text: Mapped[str] = mapped_column(String(1000), index=True)
    locale: Mapped[str | None] = mapped_column(String(40))
    normalized_phrase: Mapped[str] = mapped_column(String(1000), index=True, default="")
    market: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(40), default="")
    product_relevance: Mapped[float | None] = mapped_column(Float)
    relevance_status: Mapped[str] = mapped_column(String(40), default="needs_review")
    relevance_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class KeywordMetricsSnapshot(Base):
    __tablename__ = "keyword_metrics_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    keyword_id: Mapped[str] = mapped_column(ForeignKey("keywords.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="semrush", index=True)
    observed_on: Mapped[date | None] = mapped_column(Date, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    market: Mapped[str] = mapped_column(String(80), default="")
    device: Mapped[str] = mapped_column(String(40), default="")
    volume: Mapped[int | None] = mapped_column(Integer)
    keyword_difficulty: Mapped[float | None] = mapped_column(Float)
    intent: Mapped[str | None] = mapped_column(String(80))
    serp_features: Mapped[list] = mapped_column(JSON, default=list)
    supplied_fields: Mapped[list] = mapped_column(JSON, default=list)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)


class RankingObservation(Base):
    __tablename__ = "ranking_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    keyword_id: Mapped[str] = mapped_column(ForeignKey("keywords.id"))
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"))
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="semrush", index=True)
    ranking_url: Mapped[str | None] = mapped_column(String(4096))
    position: Mapped[float | None] = mapped_column(Float)
    observed_on: Mapped[date | None] = mapped_column(Date, index=True)
    market: Mapped[str] = mapped_column(String(80), default="")
    device: Mapped[str] = mapped_column(String(40), default="")
    source_scope: Mapped[str | None] = mapped_column(String(120))
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class GSCQueryPagePerformance(Base):
    __tablename__ = "gsc_query_page_performance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    keyword_id: Mapped[str] = mapped_column(ForeignKey("keywords.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    page_url: Mapped[str | None] = mapped_column(String(4096))
    aggregation_type: Mapped[str] = mapped_column(String(40), default="query_only")
    period_start: Mapped[date | None] = mapped_column(Date, index=True)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    search_type: Mapped[str] = mapped_column(String(40), default="web")
    country: Mapped[str] = mapped_column(String(80), default="")
    device: Mapped[str] = mapped_column(String(40), default="")
    clicks: Mapped[float | None] = mapped_column(Float)
    impressions: Mapped[float | None] = mapped_column(Float)
    ctr: Mapped[float | None] = mapped_column(Float)
    average_position: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)


class GA4PagePerformance(Base):
    __tablename__ = "ga4_page_performance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    landing_page: Mapped[str] = mapped_column(String(4096))
    normalized_url: Mapped[str | None] = mapped_column(String(4096), index=True)
    period_start: Mapped[date | None] = mapped_column(Date, index=True)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    attribution_scope: Mapped[str | None] = mapped_column(String(255))
    channel_filter: Mapped[str | None] = mapped_column(String(255))
    sessions: Mapped[float | None] = mapped_column(Float)
    engaged_sessions: Mapped[float | None] = mapped_column(Float)
    conversions: Mapped[float | None] = mapped_column(Float)
    purchases: Mapped[float | None] = mapped_column(Float)
    revenue: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)


class KeywordGroup(Base):
    __tablename__ = "keyword_groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    topic_cluster_id: Mapped[str | None] = mapped_column(ForeignKey("topic_clusters.id"), index=True)
    primary_keyword_id: Mapped[str | None] = mapped_column(ForeignKey("keywords.id"), index=True)
    intent: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="suggested", index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rule_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TopicCluster(Base):
    __tablename__ = "topic_clusters"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_topic_cluster_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KeywordGroupMembership(Base):
    __tablename__ = "keyword_group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "keyword_id", name="uq_group_keyword_membership"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("keyword_groups.id"), index=True)
    keyword_id: Mapped[str] = mapped_column(ForeignKey("keywords.id"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="supporting")
    status: Mapped[str] = mapped_column(String(40), default="suggested", index=True)
    source: Mapped[str] = mapped_column(String(40), default="rule_based")
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class GroupingSuggestion(Base):
    __tablename__ = "grouping_suggestions"
    __table_args__ = (UniqueConstraint("project_id", "keyword_id", "suggested_group_key", name="uq_grouping_suggestion"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    keyword_id: Mapped[str] = mapped_column(ForeignKey("keywords.id"), index=True)
    suggested_group_id: Mapped[str | None] = mapped_column(ForeignKey("keyword_groups.id"), index=True)
    suggested_group_key: Mapped[str] = mapped_column(String(1000))
    strength: Mapped[str] = mapped_column(String(20), index=True)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TargetMapping(Base):
    __tablename__ = "target_mappings"
    __table_args__ = (UniqueConstraint("project_id", "group_id", name="uq_group_target_mapping"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    keyword_id: Mapped[str | None] = mapped_column(ForeignKey("keywords.id"))
    group_id: Mapped[str | None] = mapped_column(ForeignKey("keyword_groups.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    proposed_url: Mapped[str | None] = mapped_column(String(4096))
    planned_page: Mapped[bool] = mapped_column(Boolean, default=False)
    planned_action: Mapped[str] = mapped_column(String(40), default="optimize_existing")
    status: Mapped[str] = mapped_column(String(40), default="suggested")
    confidence: Mapped[str | None] = mapped_column(String(20))
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CannibalizationCase(Base):
    __tablename__ = "cannibalization_cases"
    __table_args__ = (UniqueConstraint("project_id", "case_key", name="uq_cannibalization_case_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    case_key: Mapped[str] = mapped_column(String(1500), index=True)
    case_type: Mapped[str] = mapped_column(String(80), index=True)
    keyword_id: Mapped[str | None] = mapped_column(ForeignKey("keywords.id"), index=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("keyword_groups.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="review", index=True)
    title: Mapped[str] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    unknowns: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class CannibalizationEvidence(Base):
    __tablename__ = "cannibalization_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cannibalization_cases.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(40))
    observed_on: Mapped[date | None] = mapped_column(Date)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CaseDecision(Base):
    __tablename__ = "case_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cannibalization_cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(120))
    preferred_page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"))
    preferred_url: Mapped[str | None] = mapped_column(String(4096))
    reviewer: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReviewHistory(Base):
    __tablename__ = "review_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(80))
    reviewer: Mapped[str | None] = mapped_column(String(160))
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditCase(Base):
    __tablename__ = "audit_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    issue_key: Mapped[str | None] = mapped_column(String(255), index=True)
    case_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="open")
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class IssueSolution(Base):
    __tablename__ = "issue_solutions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    issue_key: Mapped[str] = mapped_column(String(2048), index=True)
    issue_source: Mapped[str] = mapped_column(String(40), index=True)
    issue_type: Mapped[str] = mapped_column(String(255))
    issue_label: Mapped[str] = mapped_column(String(500))
    workflow_status: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(160))
    target_date: Mapped[date | None] = mapped_column(Date)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    issue_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    solution_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_activity_category_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    color: Mapped[str] = mapped_column(String(24), default="blue")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IssueSnapshot(Base):
    """An immutable issue observation tied to one completed crawl."""

    __tablename__ = "issue_snapshots"
    __table_args__ = (UniqueConstraint("project_id", "import_batch_id", "issue_key", name="uq_issue_snapshot_batch_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    issue_key: Mapped[str] = mapped_column(String(2048), index=True)
    issue_source: Mapped[str] = mapped_column(String(40), index=True)
    issue_type: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(255), default="General", index=True)
    severity: Mapped[str] = mapped_column(String(40), default="review")
    label: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(4096))
    detail: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_on: Mapped[date] = mapped_column(Date, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class IssueSnapshotRun(Base):
    __tablename__ = "issue_snapshot_runs"
    __table_args__ = (UniqueConstraint("project_id", "import_batch_id", name="uq_issue_snapshot_run_batch"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    observed_on: Mapped[date] = mapped_column(Date, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    outstanding_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)


class SEOActivity(Base):
    """Append-only human and system activity record."""

    __tablename__ = "seo_activities"
    __table_args__ = (UniqueConstraint("project_id", "event_key", name="uq_seo_activity_event_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("activity_categories.id"), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id"), index=True)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    recommendation_id: Mapped[str | None] = mapped_column(ForeignKey("page_metadata_recommendations.id"), index=True)
    issue_solution_id: Mapped[str | None] = mapped_column(ForeignKey("issue_solutions.id"), index=True)
    related_activity_id: Mapped[str | None] = mapped_column(ForeignKey("seo_activities.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    section: Mapped[str] = mapped_column(String(40), default="general", index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="in_progress", index=True)
    title: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(4096))
    issue_key: Mapped[str | None] = mapped_column(String(2048), index=True)
    issue_type: Mapped[str | None] = mapped_column(String(255), index=True)
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    activity_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
