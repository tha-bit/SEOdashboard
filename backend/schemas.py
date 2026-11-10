from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    site_url: str = Field(min_length=4)
    locale: str | None = None
    market: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None
    preferences: dict[str, Any] | None = None


class ProjectOut(ORMModel):
    id: str
    name: str
    site_url: str
    locale: str | None
    market: str | None
    archived: bool
    preferences: dict[str, Any]
    created_at: datetime


class PageOut(ORMModel):
    id: str
    project_id: str
    original_url: str
    normalized_url: str
    page_type: str
    http_status: int | None
    http_status_text: str | None
    indexability: str | None
    indexability_status: str | None
    content_type: str | None
    url_path: str | None
    sitemap_included: bool | None
    architecture_section: str | None
    architecture_notes: str | None
    source: str
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    imported_sitemap_occurrences: int = 0
    in_imported_sitemap: bool = False


class ManualPageCreate(BaseModel):
    url: str
    page_type: str = "Unknown"


class BulkTypeUpdate(BaseModel):
    page_ids: list[str]
    page_type: str


class BulkSitemapUpdate(BaseModel):
    page_ids: list[str]
    included: bool | None


class ArchitecturePageUpdate(BaseModel):
    architecture_section: str | None = None
    architecture_notes: str | None = None


class RelationshipCreate(BaseModel):
    parent_page_id: str
    child_page_id: str
    relationship_type: str = "primary_parent"
    status: str = "approved"
    notes: str | None = None


class BulkProposalApproval(BaseModel):
    relationship_ids: list[str] = Field(default_factory=list, max_length=10_000)
    approve_all: bool = False


class HierarchyExportRequest(BaseModel):
    scopes: list[str] = Field(min_length=1, max_length=250)


class OnPageRecommendationUpdate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    review_status: str = "draft"
    notes: str | None = None
    reviewer: str | None = Field(default=None, max_length=160)


class OnPageBulkReviewUpdate(BaseModel):
    page_ids: list[str] = Field(min_length=1, max_length=10_000)
    review_status: str


class OnPageIssueUpdate(BaseModel):
    status: str
    reason: str | None = None


class IssueSolutionCreate(BaseModel):
    issue_key: str = Field(min_length=1, max_length=2048)
    source: str = Field(min_length=1, max_length=40)
    workflow_status: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=20_000)
    owner: str | None = Field(default=None, max_length=160)
    target_date: date | None = None
    verification_notes: str | None = Field(default=None, max_length=20_000)
    data: dict[str, Any] = Field(default_factory=dict)


class OnPageThresholdUpdate(BaseModel):
    title_min: int = Field(ge=0, le=500)
    title_max: int = Field(ge=1, le=500)
    description_min: int = Field(ge=0, le=2_000)
    description_max: int = Field(ge=1, le=2_000)


class ConfirmImport(BaseModel):
    mapping: dict[str, str]
    duplicate_strategy: str = "update_observations"
    headers_verified: bool = False


class ImportOut(ORMModel):
    id: str
    project_id: str
    file_name: str
    source: str
    checksum: str
    status: str
    imported_at: datetime
    reporting_date: date | None
    row_count: int
    imported_count: int
    skipped_count: int
    error_count: int
    mapping: dict
    warnings: list
