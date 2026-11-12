from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    AuditCase,
    ActivityCategory,
    CannibalizationCase,
    CannibalizationEvidence,
    CaseDecision,
    GA4PagePerformance,
    GSCQueryPagePerformance,
    ImportBatch,
    ImportRow,
    IssueSolution,
    IssueSnapshot,
    IssueSnapshotRun,
    Keyword,
    KeywordGroup,
    KeywordGroupMembership,
    KeywordMetricsSnapshot,
    Page,
    PageCrawlChange,
    PageMetadataChange,
    PageMetadataObservation,
    PageMetadataRecommendation,
    PageRelationship,
    Project,
    RankingObservation,
    ReviewHistory,
    SEOActivity,
    GroupingSuggestion,
    SitemapDocument,
    SitemapEntry,
    TargetMapping,
    TopicCluster,
    uid,
)

BUNDLE_FORMAT = "seo-data-workspace-project"
BUNDLE_VERSION = 1


def _iso(value):
    return value.isoformat() if value else None


def export_project_bundle(db: Session, project: Project) -> dict[str, Any]:
    pages = db.scalars(select(Page).where(Page.project_id == project.id).order_by(Page.created_at)).all()
    batches = db.scalars(select(ImportBatch).where(ImportBatch.project_id == project.id).order_by(ImportBatch.imported_at)).all()
    batch_ids = [batch.id for batch in batches]
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id.in_(batch_ids)).order_by(ImportRow.batch_id, ImportRow.row_number)).all() if batch_ids else []
    crawl_changes = db.scalars(select(PageCrawlChange).where(PageCrawlChange.project_id == project.id).order_by(PageCrawlChange.observed_at)).all()
    relationships = db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id).order_by(PageRelationship.created_at)).all()
    sitemap_documents = db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project.id).order_by(SitemapDocument.imported_at)).all()
    sitemap_document_ids = [document.id for document in sitemap_documents]
    sitemap_entries = db.scalars(select(SitemapEntry).where(SitemapEntry.document_id.in_(sitemap_document_ids)).order_by(SitemapEntry.document_id, SitemapEntry.id)).all() if sitemap_document_ids else []
    metadata_observations = db.scalars(select(PageMetadataObservation).where(PageMetadataObservation.project_id == project.id).order_by(PageMetadataObservation.observed_at)).all()
    metadata_recommendations = db.scalars(select(PageMetadataRecommendation).where(PageMetadataRecommendation.project_id == project.id).order_by(PageMetadataRecommendation.created_at)).all()
    recommendation_ids = [item.id for item in metadata_recommendations]
    metadata_changes = db.scalars(select(PageMetadataChange).where(PageMetadataChange.recommendation_id.in_(recommendation_ids)).order_by(PageMetadataChange.changed_at)).all() if recommendation_ids else []
    audit_cases = db.scalars(select(AuditCase).where(AuditCase.project_id == project.id)).all()
    issue_solutions = db.scalars(select(IssueSolution).where(IssueSolution.project_id == project.id).order_by(IssueSolution.created_at)).all()
    keywords = db.scalars(select(Keyword).where(Keyword.project_id == project.id).order_by(Keyword.created_at)).all()
    keyword_metrics = db.scalars(select(KeywordMetricsSnapshot).where(KeywordMetricsSnapshot.project_id == project.id).order_by(KeywordMetricsSnapshot.observed_at)).all()
    rankings = db.scalars(select(RankingObservation).where(RankingObservation.project_id == project.id).order_by(RankingObservation.observed_at)).all()
    gsc_performance = db.scalars(select(GSCQueryPagePerformance).where(GSCQueryPagePerformance.project_id == project.id).order_by(GSCQueryPagePerformance.observed_at)).all()
    ga4_performance = db.scalars(select(GA4PagePerformance).where(GA4PagePerformance.project_id == project.id).order_by(GA4PagePerformance.observed_at)).all()
    topic_clusters = db.scalars(select(TopicCluster).where(TopicCluster.project_id == project.id)).all()
    keyword_groups = db.scalars(select(KeywordGroup).where(KeywordGroup.project_id == project.id)).all()
    group_memberships = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project.id)).all()
    grouping_suggestions = db.scalars(select(GroupingSuggestion).where(GroupingSuggestion.project_id == project.id)).all()
    target_mappings = db.scalars(select(TargetMapping).where(TargetMapping.project_id == project.id)).all()
    cannibalization_cases = db.scalars(select(CannibalizationCase).where(CannibalizationCase.project_id == project.id)).all()
    cannibalization_evidence = db.scalars(select(CannibalizationEvidence).where(CannibalizationEvidence.project_id == project.id)).all()
    case_decisions = db.scalars(select(CaseDecision).where(CaseDecision.project_id == project.id)).all()
    review_history = db.scalars(select(ReviewHistory).where(ReviewHistory.project_id == project.id)).all()
    activity_categories = db.scalars(select(ActivityCategory).where(ActivityCategory.project_id == project.id).order_by(ActivityCategory.created_at)).all()
    issue_snapshots = db.scalars(select(IssueSnapshot).where(IssueSnapshot.project_id == project.id).order_by(IssueSnapshot.observed_at)).all()
    issue_snapshot_runs = db.scalars(select(IssueSnapshotRun).where(IssueSnapshotRun.project_id == project.id).order_by(IssueSnapshotRun.observed_at)).all()
    seo_activities = db.scalars(select(SEOActivity).where(SEOActivity.project_id == project.id).order_by(SEOActivity.occurred_at)).all()
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(),
        "project": {
            "source_id": project.id,
            "name": project.name,
            "site_url": project.site_url,
            "locale": project.locale,
            "market": project.market,
            "archived": project.archived,
            "preferences": project.preferences,
            "created_at": _iso(project.created_at),
            "updated_at": _iso(project.updated_at),
        },
        "pages": [
            {
                "source_id": page.id,
                "original_url": page.original_url,
                "normalized_url": page.normalized_url,
                "page_type": page.page_type,
                "http_status": page.http_status,
                "http_status_text": page.http_status_text,
                "indexability": page.indexability,
                "indexability_status": page.indexability_status,
                "content_type": page.content_type,
                "url_path": page.url_path,
                "sitemap_included": page.sitemap_included,
                "architecture_section": page.architecture_section,
                "architecture_notes": page.architecture_notes,
                "source": page.source,
                "last_observed_at": _iso(page.last_observed_at),
                "created_at": _iso(page.created_at),
                "updated_at": _iso(page.updated_at),
            }
            for page in pages
        ],
        "import_batches": [
            {
                "source_id": batch.id,
                "file_name": batch.file_name,
                "source": batch.source,
                "checksum": batch.checksum,
                "status": batch.status,
                "imported_at": _iso(batch.imported_at),
                "reporting_date": _iso(batch.reporting_date),
                "row_count": batch.row_count,
                "imported_count": batch.imported_count,
                "skipped_count": batch.skipped_count,
                "error_count": batch.error_count,
                "mapping": batch.mapping,
                "warnings": batch.warnings,
            }
            for batch in batches
        ],
        "import_rows": [
            {
                "source_id": row.id,
                "batch_source_id": row.batch_id,
                "row_number": row.row_number,
                "raw_data": row.raw_data,
                "normalized_data": row.normalized_data,
                "validation_status": row.validation_status,
                "error_message": row.error_message,
                "page_source_id": row.page_id,
            }
            for row in rows
        ],
        "page_crawl_changes": [
            {
                "source_id": item.id,
                "page_source_id": item.page_id,
                "batch_source_id": item.import_batch_id,
                "observed_at": _iso(item.observed_at),
                "source_label": item.source_label,
                "changes": item.changes,
            }
            for item in crawl_changes
        ],
        "page_relationships": [
            {
                "source_id": relationship.id,
                "source_page_source_id": relationship.source_page_id,
                "target_page_source_id": relationship.target_page_id,
                "relationship_type": relationship.relationship_type,
                "status": relationship.status,
                "evidence": relationship.evidence,
                "notes": relationship.notes,
                "created_at": _iso(relationship.created_at),
            }
            for relationship in relationships
        ],
        "sitemap_documents": [
            {
                "source_id": document.id,
                "file_name": document.file_name,
                "checksum": document.checksum,
                "document_type": document.document_type,
                "imported_at": _iso(document.imported_at),
                "referenced_files": document.referenced_files,
                "unresolved_references": document.unresolved_references,
                "warnings": document.warnings,
            }
            for document in sitemap_documents
        ],
        "sitemap_entries": [
            {
                "source_id": entry.id,
                "document_source_id": entry.document_id,
                "page_source_id": entry.page_id,
                "loc": entry.loc,
                "normalized_url": entry.normalized_url,
                "lastmod": entry.lastmod,
                "changefreq": entry.changefreq,
                "priority": entry.priority,
                "valid": entry.valid,
                "issue": entry.issue,
            }
            for entry in sitemap_entries
        ],
        "page_metadata_observations": [
            {"source_id": item.id, "page_source_id": item.page_id, "batch_source_id": item.import_batch_id, "source_label": item.source_label, "reporting_date": _iso(item.reporting_date), "observed_at": _iso(item.observed_at), "supplied_fields": item.supplied_fields, "source_columns": item.source_columns, "data": item.data}
            for item in metadata_observations
        ],
        "page_metadata_recommendations": [
            {"source_id": item.id, "page_source_id": item.page_id, "data": item.data, "approved": item.approved, "review_status": item.review_status, "notes": item.notes, "reviewer": item.reviewer, "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at), "implemented_at": _iso(item.implemented_at)}
            for item in metadata_recommendations
        ],
        "page_metadata_changes": [
            {"source_id": item.id, "page_source_id": item.page_id, "recommendation_source_id": item.recommendation_id, "changed_at": _iso(item.changed_at), "reviewer": item.reviewer, "changes": item.changes}
            for item in metadata_changes
        ],
        "on_page_audit_cases": [
            {"source_id": item.id, "page_source_id": item.page_id, "issue_key": item.issue_key, "case_type": item.case_type, "status": item.status, "reason": item.reason, "updated_at": _iso(item.updated_at), "evidence": item.evidence}
            for item in audit_cases if item.case_type == "on_page_issue"
        ],
        "issue_solutions": [
            {"source_id": item.id, "page_source_id": item.page_id, "issue_key": item.issue_key, "issue_source": item.issue_source, "issue_type": item.issue_type, "issue_label": item.issue_label, "workflow_status": item.workflow_status, "action": item.action, "summary": item.summary, "owner": item.owner, "target_date": _iso(item.target_date), "verification_notes": item.verification_notes, "issue_snapshot": item.issue_snapshot, "solution_data": item.solution_data, "created_at": _iso(item.created_at)}
            for item in issue_solutions
        ],
        "keywords": [{"source_id": item.id, "text": item.text, "locale": item.locale, "normalized_phrase": item.normalized_phrase, "market": item.market, "language": item.language, "product_relevance": item.product_relevance, "relevance_status": item.relevance_status, "relevance_notes": item.relevance_notes, "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)} for item in keywords],
        "keyword_metrics_snapshots": [{"source_id": item.id, "keyword_source_id": item.keyword_id, "batch_source_id": item.import_batch_id, "provider": item.provider, "observed_on": _iso(item.observed_on), "observed_at": _iso(item.observed_at), "market": item.market, "device": item.device, "volume": item.volume, "keyword_difficulty": item.keyword_difficulty, "intent": item.intent, "serp_features": item.serp_features, "supplied_fields": item.supplied_fields, "raw_data": item.raw_data} for item in keyword_metrics],
        "ranking_observations": [{"source_id": item.id, "keyword_source_id": item.keyword_id, "page_source_id": item.page_id, "batch_source_id": item.import_batch_id, "provider": item.provider, "ranking_url": item.ranking_url, "position": item.position, "observed_on": _iso(item.observed_on), "observed_at": _iso(item.observed_at), "market": item.market, "device": item.device, "source_scope": item.source_scope, "raw_data": item.raw_data, "metrics": item.metrics} for item in rankings],
        "gsc_query_page_performance": [{"source_id": item.id, "keyword_source_id": item.keyword_id, "page_source_id": item.page_id, "batch_source_id": item.import_batch_id, "page_url": item.page_url, "aggregation_type": item.aggregation_type, "period_start": _iso(item.period_start), "period_end": _iso(item.period_end), "search_type": item.search_type, "country": item.country, "device": item.device, "clicks": item.clicks, "impressions": item.impressions, "ctr": item.ctr, "average_position": item.average_position, "observed_at": _iso(item.observed_at), "raw_data": item.raw_data} for item in gsc_performance],
        "ga4_page_performance": [{"source_id": item.id, "page_source_id": item.page_id, "batch_source_id": item.import_batch_id, "landing_page": item.landing_page, "normalized_url": item.normalized_url, "period_start": _iso(item.period_start), "period_end": _iso(item.period_end), "attribution_scope": item.attribution_scope, "channel_filter": item.channel_filter, "sessions": item.sessions, "engaged_sessions": item.engaged_sessions, "conversions": item.conversions, "purchases": item.purchases, "revenue": item.revenue, "observed_at": _iso(item.observed_at), "raw_data": item.raw_data} for item in ga4_performance],
        "topic_clusters": [{"source_id": item.id, "name": item.name, "description": item.description, "archived": item.archived, "created_at": _iso(item.created_at)} for item in topic_clusters],
        "keyword_groups": [{"source_id": item.id, "topic_cluster_source_id": item.topic_cluster_id, "primary_keyword_source_id": item.primary_keyword_id, "name": item.name, "intent": item.intent, "status": item.status, "archived": item.archived, "rule_data": item.rule_data, "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)} for item in keyword_groups],
        "keyword_group_memberships": [{"source_id": item.id, "group_source_id": item.group_id, "keyword_source_id": item.keyword_id, "role": item.role, "status": item.status, "source": item.source, "reason_codes": item.reason_codes, "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)} for item in group_memberships],
        "grouping_suggestions": [{"source_id": item.id, "keyword_source_id": item.keyword_id, "group_source_id": item.suggested_group_id, "suggested_group_key": item.suggested_group_key, "strength": item.strength, "reason_codes": item.reason_codes, "evidence": item.evidence, "status": item.status, "created_at": _iso(item.created_at), "reviewed_at": _iso(item.reviewed_at)} for item in grouping_suggestions],
        "target_mappings": [{"source_id": item.id, "keyword_source_id": item.keyword_id, "group_source_id": item.group_id, "page_source_id": item.page_id, "proposed_url": item.proposed_url, "planned_page": item.planned_page, "planned_action": item.planned_action, "status": item.status, "confidence": item.confidence, "reason_codes": item.reason_codes, "rationale": item.rationale, "approved_by": item.approved_by, "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)} for item in target_mappings],
        "cannibalization_cases": [{"source_id": item.id, "case_key": item.case_key, "case_type": item.case_type, "keyword_source_id": item.keyword_id, "group_source_id": item.group_id, "status": item.status, "priority": item.priority, "title": item.title, "detected_at": _iso(item.detected_at), "last_seen_at": _iso(item.last_seen_at), "evidence_hash": item.evidence_hash, "evidence": item.evidence, "unknowns": item.unknowns, "notes": item.notes} for item in cannibalization_cases],
        "cannibalization_evidence": [{"source_id": item.id, "case_source_id": item.case_id, "evidence_type": item.evidence_type, "source": item.source, "observed_on": _iso(item.observed_on), "data": item.data, "created_at": _iso(item.created_at)} for item in cannibalization_evidence],
        "case_decisions": [{"source_id": item.id, "case_source_id": item.case_id, "status": item.status, "action": item.action, "preferred_page_source_id": item.preferred_page_id, "preferred_url": item.preferred_url, "reviewer": item.reviewer, "notes": item.notes, "decided_at": _iso(item.decided_at)} for item in case_decisions],
        "review_history": [{"source_id": item.id, "entity_type": item.entity_type, "entity_source_id": item.entity_id, "action": item.action, "reviewer": item.reviewer, "before_data": item.before_data, "after_data": item.after_data, "reason": item.reason, "created_at": _iso(item.created_at)} for item in review_history],
        "activity_categories": [{"source_id": item.id, "name": item.name, "color": item.color, "created_at": _iso(item.created_at)} for item in activity_categories],
        "issue_snapshots": [{"source_id": item.id, "batch_source_id": item.import_batch_id, "page_source_id": item.page_id, "issue_key": item.issue_key, "issue_source": item.issue_source, "issue_type": item.issue_type, "category": item.category, "severity": item.severity, "label": item.label, "url": item.url, "detail": item.detail, "evidence": item.evidence, "observed_on": _iso(item.observed_on), "observed_at": _iso(item.observed_at)} for item in issue_snapshots],
        "issue_snapshot_runs": [{"source_id": item.id, "batch_source_id": item.import_batch_id, "observed_on": _iso(item.observed_on), "observed_at": _iso(item.observed_at), "outstanding_count": item.outstanding_count, "new_count": item.new_count, "resolved_count": item.resolved_count, "baseline": item.baseline} for item in issue_snapshot_runs],
        "seo_activities": [{"source_id": item.id, "category_source_id": item.category_id, "page_source_id": item.page_id, "batch_source_id": item.import_batch_id, "recommendation_source_id": item.recommendation_id, "solution_source_id": item.issue_solution_id, "related_activity_source_id": item.related_activity_id, "event_key": item.event_key, "source": item.source, "section": item.section, "action_type": item.action_type, "status": item.status, "title": item.title, "notes": item.notes, "url": item.url, "issue_key": item.issue_key, "issue_type": item.issue_type, "before_data": item.before_data, "after_data": item.after_data, "activity_metadata": item.activity_metadata, "occurred_at": _iso(item.occurred_at), "created_at": _iso(item.created_at)} for item in seo_activities],
    }


def _datetime(value: str | None, default=None):
    if not value:
        return default
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid date-time in project bundle: {value}") from exc


def _date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid reporting date in project bundle: {value}") from exc


def import_project_bundle(db: Session, bundle: dict[str, Any]) -> Project:
    if bundle.get("format") != BUNDLE_FORMAT or bundle.get("version") != BUNDLE_VERSION:
        raise HTTPException(422, "This is not a supported SEO Data Workspace project bundle")
    source_project = bundle.get("project")
    if not isinstance(source_project, dict) or not source_project.get("name") or not source_project.get("site_url"):
        raise HTTPException(422, "Project bundle is missing required project details")
    collection_names = ("pages", "import_batches", "import_rows", "page_crawl_changes", "page_relationships", "sitemap_documents", "sitemap_entries", "page_metadata_observations", "page_metadata_recommendations", "page_metadata_changes", "on_page_audit_cases", "issue_solutions", "keywords", "keyword_metrics_snapshots", "ranking_observations", "gsc_query_page_performance", "ga4_page_performance", "topic_clusters", "keyword_groups", "keyword_group_memberships", "grouping_suggestions", "target_mappings", "cannibalization_cases", "cannibalization_evidence", "case_decisions", "review_history", "activity_categories", "issue_snapshots", "issue_snapshot_runs", "seo_activities")
    if any(not isinstance(bundle.get(name, []), list) for name in collection_names):
        raise HTTPException(422, "Project bundle contains invalid record collections")
    try:
        project = Project(
            name=str(source_project["name"]),
            site_url=str(source_project["site_url"]),
            locale=source_project.get("locale"),
            market=source_project.get("market"),
            archived=False,
            preferences=source_project.get("preferences") or {"trailing_slash": "remove", "remove_tracking": True},
        )
        db.add(project)
        db.flush()
        page_ids: dict[str, str] = {}
        seen_identities: set[str] = set()
        for item in bundle.get("pages", []):
            normalized_url = str(item.get("normalized_url") or "")
            if not normalized_url or normalized_url in seen_identities:
                raise HTTPException(422, "Project bundle contains a missing or duplicate normalized URL")
            seen_identities.add(normalized_url)
            page = Page(
                project_id=project.id,
                original_url=str(item.get("original_url") or normalized_url),
                normalized_url=normalized_url,
                page_type="PDP" if item.get("page_type") == "Product Pages" else str(item.get("page_type") or "Unknown"),
                http_status=item.get("http_status"),
                http_status_text=item.get("http_status_text"),
                indexability=item.get("indexability"),
                indexability_status=item.get("indexability_status"),
                content_type=item.get("content_type"),
                url_path=item.get("url_path"),
                sitemap_included=item.get("sitemap_included"),
                architecture_section=item.get("architecture_section"),
                architecture_notes=item.get("architecture_notes"),
                source=str(item.get("source") or "project_bundle"),
                last_observed_at=_datetime(item.get("last_observed_at")) or datetime.now().astimezone(),
            )
            db.add(page)
            db.flush()
            if item.get("source_id"):
                page_ids[str(item["source_id"])] = page.id
        batch_ids: dict[str, str] = {}
        for item in bundle.get("import_batches", []):
            batch = ImportBatch(
                project_id=project.id,
                file_name=str(item.get("file_name") or "restored-import"),
                source=str(item.get("source") or "project_bundle"),
                checksum=str(item.get("checksum") or "restored"),
                status=str(item.get("status") or "completed"),
                imported_at=_datetime(item.get("imported_at")) or datetime.now().astimezone(),
                reporting_date=_date(item.get("reporting_date")),
                row_count=int(item.get("row_count") or 0),
                imported_count=int(item.get("imported_count") or 0),
                skipped_count=int(item.get("skipped_count") or 0),
                error_count=int(item.get("error_count") or 0),
                mapping=item.get("mapping") or {},
                warnings=item.get("warnings") or [],
            )
            db.add(batch)
            db.flush()
            if item.get("source_id"):
                batch_ids[str(item["source_id"])] = batch.id
        for item in bundle.get("import_rows", []):
            batch_id = batch_ids.get(str(item.get("batch_source_id")))
            if not batch_id:
                raise HTTPException(422, "Project bundle contains an import row without its batch")
            page_id = page_ids.get(str(item.get("page_source_id"))) if item.get("page_source_id") else None
            db.add(ImportRow(
                batch_id=batch_id,
                row_number=int(item.get("row_number") or 0),
                raw_data=item.get("raw_data") or {},
                normalized_data=item.get("normalized_data") or {},
                validation_status=str(item.get("validation_status") or "pending"),
                error_message=item.get("error_message"),
                page_id=page_id,
            ))
        for item in bundle.get("page_crawl_changes", []):
            page_id = page_ids.get(str(item.get("page_source_id")))
            if not page_id:
                raise HTTPException(422, "Project bundle contains a crawl change without its page")
            db.add(PageCrawlChange(
                project_id=project.id,
                page_id=page_id,
                import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None,
                observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(),
                source_label=str(item.get("source_label") or "Restored crawl observation"),
                changes=item.get("changes") or {},
            ))
        document_ids: dict[str, str] = {}
        for item in bundle.get("sitemap_documents", []):
            document = SitemapDocument(
                project_id=project.id,
                file_name=str(item.get("file_name") or "restored-sitemap.xml"),
                checksum=str(item.get("checksum") or "restored"),
                document_type=str(item.get("document_type") or "urlset"),
                imported_at=_datetime(item.get("imported_at")) or datetime.now().astimezone(),
                referenced_files=item.get("referenced_files") or [],
                unresolved_references=item.get("unresolved_references") or [],
                warnings=item.get("warnings") or [],
            )
            db.add(document)
            db.flush()
            if item.get("source_id"):
                document_ids[str(item["source_id"])] = document.id
        for item in bundle.get("sitemap_entries", []):
            document_id = document_ids.get(str(item.get("document_source_id")))
            if not document_id:
                raise HTTPException(422, "Project bundle contains a sitemap entry without its document")
            page_id = page_ids.get(str(item.get("page_source_id"))) if item.get("page_source_id") else None
            db.add(SitemapEntry(
                project_id=project.id,
                document_id=document_id,
                page_id=page_id,
                loc=str(item.get("loc") or ""),
                normalized_url=item.get("normalized_url"),
                lastmod=item.get("lastmod"),
                changefreq=item.get("changefreq"),
                priority=item.get("priority"),
                valid=bool(item.get("valid", True)),
                issue=item.get("issue"),
            ))
        for item in bundle.get("page_relationships", []):
            source_page_id = page_ids.get(str(item.get("source_page_source_id")))
            target_page_id = page_ids.get(str(item.get("target_page_source_id")))
            if not source_page_id or not target_page_id:
                raise HTTPException(422, "Project bundle contains a relationship without both pages")
            db.add(PageRelationship(
                project_id=project.id,
                source_page_id=source_page_id,
                target_page_id=target_page_id,
                relationship_type=str(item.get("relationship_type") or "primary_parent"),
                status=str(item.get("status") or "approved"),
                evidence=item.get("evidence") or {},
                notes=item.get("notes"),
                created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(),
            ))
        observation_ids: dict[str, str] = {}
        for item in bundle.get("page_metadata_observations", []):
            page_id = page_ids.get(str(item.get("page_source_id")))
            if not page_id:
                raise HTTPException(422, "Project bundle contains a metadata observation without its page")
            observation = PageMetadataObservation(
                project_id=project.id,
                page_id=page_id,
                import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None,
                source_label=str(item.get("source_label") or "Restored metadata observation"),
                reporting_date=_date(item.get("reporting_date")),
                observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(),
                supplied_fields=item.get("supplied_fields") or [],
                source_columns=item.get("source_columns") or {},
                data=item.get("data") or {},
            )
            db.add(observation); db.flush()
            if item.get("source_id"):
                observation_ids[str(item["source_id"])] = observation.id
        recommendation_ids: dict[str, str] = {}
        for item in bundle.get("page_metadata_recommendations", []):
            page_id = page_ids.get(str(item.get("page_source_id")))
            if not page_id:
                raise HTTPException(422, "Project bundle contains a metadata recommendation without its page")
            recommendation = PageMetadataRecommendation(
                project_id=project.id, page_id=page_id, data=item.get("data") or {}, approved=bool(item.get("approved", False)),
                review_status=str(item.get("review_status") or "draft"), notes=item.get("notes"), reviewer=item.get("reviewer"),
                created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(), updated_at=_datetime(item.get("updated_at")) or datetime.now().astimezone(), implemented_at=_datetime(item.get("implemented_at")),
            )
            db.add(recommendation); db.flush()
            if item.get("source_id"):
                recommendation_ids[str(item["source_id"])] = recommendation.id
        for item in bundle.get("page_metadata_changes", []):
            page_id = page_ids.get(str(item.get("page_source_id")))
            recommendation_id = recommendation_ids.get(str(item.get("recommendation_source_id")))
            if not page_id or not recommendation_id:
                raise HTTPException(422, "Project bundle contains a metadata change without its page or recommendation")
            db.add(PageMetadataChange(project_id=project.id, page_id=page_id, recommendation_id=recommendation_id, changed_at=_datetime(item.get("changed_at")) or datetime.now().astimezone(), reviewer=item.get("reviewer"), changes=item.get("changes") or {}))
        for item in bundle.get("on_page_audit_cases", []):
            old_page_id = str(item.get("page_source_id")) if item.get("page_source_id") else None
            page_id = page_ids.get(old_page_id) if old_page_id else None
            issue_key = str(item.get("issue_key") or "")
            if old_page_id and page_id:
                issue_key = issue_key.replace(f":{old_page_id}", f":{page_id}", 1)
            db.add(AuditCase(project_id=project.id, page_id=page_id, issue_key=issue_key or None, case_type="on_page_issue", status=str(item.get("status") or "open"), reason=item.get("reason"), updated_at=_datetime(item.get("updated_at")) or datetime.now().astimezone(), evidence=item.get("evidence") or {}))
        solution_ids: dict[str, str] = {}
        for item in bundle.get("issue_solutions", []):
            old_page_id = str(item.get("page_source_id")) if item.get("page_source_id") else None
            page_id = page_ids.get(old_page_id) if old_page_id else None
            if old_page_id and not page_id:
                raise HTTPException(422, "Project bundle contains an issue solution without its page")
            issue_key = str(item.get("issue_key") or "")
            if old_page_id and page_id:
                issue_key = issue_key.replace(f":{old_page_id}", f":{page_id}", 1)
            solution = IssueSolution(
                project_id=project.id,
                page_id=page_id,
                issue_key=issue_key,
                issue_source=str(item.get("issue_source") or "on_page"),
                issue_type=str(item.get("issue_type") or "restored_issue"),
                issue_label=str(item.get("issue_label") or "Restored issue"),
                workflow_status=str(item.get("workflow_status") or "proposed"),
                action=str(item.get("action") or "other"),
                summary=str(item.get("summary") or "Restored solution log entry"),
                owner=item.get("owner"),
                target_date=_date(item.get("target_date")),
                verification_notes=item.get("verification_notes"),
                issue_snapshot=item.get("issue_snapshot") or {},
                solution_data=item.get("solution_data") or {},
                created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(),
            )
            db.add(solution); db.flush()
            if item.get("source_id"): solution_ids[str(item["source_id"])] = solution.id
        keyword_ids: dict[str, str] = {}
        for item in bundle.get("keywords", []):
            keyword = Keyword(project_id=project.id, text=str(item.get("text") or ""), locale=item.get("locale"), normalized_phrase=str(item.get("normalized_phrase") or str(item.get("text") or "").strip().casefold()), market=str(item.get("market") or ""), language=str(item.get("language") or ""), product_relevance=item.get("product_relevance"), relevance_status=str(item.get("relevance_status") or "needs_review"), relevance_notes=item.get("relevance_notes"), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(), updated_at=_datetime(item.get("updated_at")) or datetime.now().astimezone())
            db.add(keyword); db.flush()
            if item.get("source_id"):
                keyword_ids[str(item["source_id"])] = keyword.id
        for item in bundle.get("keyword_metrics_snapshots", []):
            keyword_id = keyword_ids.get(str(item.get("keyword_source_id")))
            if not keyword_id:
                raise HTTPException(422, "Project bundle contains keyword metrics without its keyword")
            db.add(KeywordMetricsSnapshot(project_id=project.id, keyword_id=keyword_id, import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None, provider=str(item.get("provider") or "semrush"), observed_on=_date(item.get("observed_on")), observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(), market=str(item.get("market") or ""), device=str(item.get("device") or ""), volume=item.get("volume"), keyword_difficulty=item.get("keyword_difficulty"), intent=item.get("intent"), serp_features=item.get("serp_features") or [], supplied_fields=item.get("supplied_fields") or [], raw_data=item.get("raw_data") or {}))
        for item in bundle.get("ranking_observations", []):
            keyword_id = keyword_ids.get(str(item.get("keyword_source_id")))
            if not keyword_id:
                raise HTTPException(422, "Project bundle contains a ranking without its keyword")
            db.add(RankingObservation(project_id=project.id, keyword_id=keyword_id, page_id=page_ids.get(str(item.get("page_source_id"))) if item.get("page_source_id") else None, import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None, provider=str(item.get("provider") or "semrush"), ranking_url=item.get("ranking_url"), position=item.get("position"), observed_on=_date(item.get("observed_on")), observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(), market=str(item.get("market") or ""), device=str(item.get("device") or ""), source_scope=item.get("source_scope"), raw_data=item.get("raw_data") or {}, metrics=item.get("metrics") or {}))
        for item in bundle.get("gsc_query_page_performance", []):
            keyword_id = keyword_ids.get(str(item.get("keyword_source_id")))
            if not keyword_id:
                raise HTTPException(422, "Project bundle contains GSC performance without its keyword")
            db.add(GSCQueryPagePerformance(project_id=project.id, keyword_id=keyword_id, page_id=page_ids.get(str(item.get("page_source_id"))) if item.get("page_source_id") else None, import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None, page_url=item.get("page_url"), aggregation_type=str(item.get("aggregation_type") or "query_only"), period_start=_date(item.get("period_start")), period_end=_date(item.get("period_end")), search_type=str(item.get("search_type") or "web"), country=str(item.get("country") or ""), device=str(item.get("device") or ""), clicks=item.get("clicks"), impressions=item.get("impressions"), ctr=item.get("ctr"), average_position=item.get("average_position"), observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(), raw_data=item.get("raw_data") or {}))
        for item in bundle.get("ga4_page_performance", []):
            db.add(GA4PagePerformance(project_id=project.id, page_id=page_ids.get(str(item.get("page_source_id"))) if item.get("page_source_id") else None, import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None, landing_page=str(item.get("landing_page") or ""), normalized_url=item.get("normalized_url"), period_start=_date(item.get("period_start")), period_end=_date(item.get("period_end")), attribution_scope=item.get("attribution_scope"), channel_filter=item.get("channel_filter"), sessions=item.get("sessions"), engaged_sessions=item.get("engaged_sessions"), conversions=item.get("conversions"), purchases=item.get("purchases"), revenue=item.get("revenue"), observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(), raw_data=item.get("raw_data") or {}))
        cluster_ids: dict[str, str] = {}
        for item in bundle.get("topic_clusters", []):
            cluster = TopicCluster(project_id=project.id, name=str(item.get("name") or "Restored cluster"), description=item.get("description"), archived=bool(item.get("archived", False)), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone())
            db.add(cluster); db.flush()
            if item.get("source_id"): cluster_ids[str(item["source_id"])] = cluster.id
        group_ids: dict[str, str] = {}
        for item in bundle.get("keyword_groups", []):
            group = KeywordGroup(project_id=project.id, name=str(item.get("name") or "Restored group"), topic_cluster_id=cluster_ids.get(str(item.get("topic_cluster_source_id"))) if item.get("topic_cluster_source_id") else None, primary_keyword_id=keyword_ids.get(str(item.get("primary_keyword_source_id"))) if item.get("primary_keyword_source_id") else None, intent=item.get("intent"), status=str(item.get("status") or "suggested"), archived=bool(item.get("archived", False)), rule_data=item.get("rule_data") or {}, created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(), updated_at=_datetime(item.get("updated_at")) or datetime.now().astimezone())
            db.add(group); db.flush()
            if item.get("source_id"): group_ids[str(item["source_id"])] = group.id
        for item in bundle.get("keyword_group_memberships", []):
            db.add(KeywordGroupMembership(project_id=project.id, group_id=group_ids[str(item.get("group_source_id"))], keyword_id=keyword_ids[str(item.get("keyword_source_id"))], role=str(item.get("role") or "supporting"), status=str(item.get("status") or "suggested"), source=str(item.get("source") or "project_bundle"), reason_codes=item.get("reason_codes") or [], created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(), updated_at=_datetime(item.get("updated_at")) or datetime.now().astimezone()))
        for item in bundle.get("grouping_suggestions", []):
            db.add(GroupingSuggestion(project_id=project.id, keyword_id=keyword_ids[str(item.get("keyword_source_id"))], suggested_group_id=group_ids.get(str(item.get("group_source_id"))) if item.get("group_source_id") else None, suggested_group_key=str(item.get("suggested_group_key") or "restored"), strength=str(item.get("strength") or "weak"), reason_codes=item.get("reason_codes") or [], evidence=item.get("evidence") or {}, status=str(item.get("status") or "pending"), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(), reviewed_at=_datetime(item.get("reviewed_at"))))
        mapping_ids: dict[str, str] = {}
        for item in bundle.get("target_mappings", []):
            mapping = TargetMapping(project_id=project.id, keyword_id=keyword_ids.get(str(item.get("keyword_source_id"))) if item.get("keyword_source_id") else None, group_id=group_ids.get(str(item.get("group_source_id"))) if item.get("group_source_id") else None, page_id=page_ids.get(str(item.get("page_source_id"))) if item.get("page_source_id") else None, proposed_url=item.get("proposed_url"), planned_page=bool(item.get("planned_page", False)), planned_action=str(item.get("planned_action") or ("create_new" if item.get("planned_page") else "optimize_existing")), status=str(item.get("status") or "suggested"), confidence=item.get("confidence"), reason_codes=item.get("reason_codes") or [], rationale=item.get("rationale"), approved_by=item.get("approved_by"), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone(), updated_at=_datetime(item.get("updated_at")) or datetime.now().astimezone())
            db.add(mapping); db.flush()
            if item.get("source_id"): mapping_ids[str(item["source_id"])] = mapping.id
        case_ids: dict[str, str] = {}
        for item in bundle.get("cannibalization_cases", []):
            case = CannibalizationCase(project_id=project.id, case_key=str(item.get("case_key") or item.get("source_id") or "restored"), case_type=str(item.get("case_type") or "restored_signal"), keyword_id=keyword_ids.get(str(item.get("keyword_source_id"))) if item.get("keyword_source_id") else None, group_id=group_ids.get(str(item.get("group_source_id"))) if item.get("group_source_id") else None, status=str(item.get("status") or "new"), priority=str(item.get("priority") or "review"), title=str(item.get("title") or "Restored case"), detected_at=_datetime(item.get("detected_at")) or datetime.now().astimezone(), last_seen_at=_datetime(item.get("last_seen_at")) or datetime.now().astimezone(), evidence_hash=str(item.get("evidence_hash") or "restored"), evidence=item.get("evidence") or {}, unknowns=item.get("unknowns") or [], notes=item.get("notes"))
            db.add(case); db.flush()
            if item.get("source_id"): case_ids[str(item["source_id"])] = case.id
        for item in bundle.get("cannibalization_evidence", []):
            db.add(CannibalizationEvidence(project_id=project.id, case_id=case_ids[str(item.get("case_source_id"))], evidence_type=str(item.get("evidence_type") or "restored"), source=str(item.get("source") or "project_bundle"), observed_on=_date(item.get("observed_on")), data=item.get("data") or {}, created_at=_datetime(item.get("created_at")) or datetime.now().astimezone()))
        for item in bundle.get("case_decisions", []):
            db.add(CaseDecision(project_id=project.id, case_id=case_ids[str(item.get("case_source_id"))], status=str(item.get("status") or "needs_investigation"), action=str(item.get("action") or "Review restored evidence"), preferred_page_id=page_ids.get(str(item.get("preferred_page_source_id"))) if item.get("preferred_page_source_id") else None, preferred_url=item.get("preferred_url"), reviewer=item.get("reviewer"), notes=item.get("notes"), decided_at=_datetime(item.get("decided_at")) or datetime.now().astimezone()))
        entity_maps = {"keyword_group": group_ids, "target_mapping": mapping_ids, "cannibalization_case": case_ids}
        for item in bundle.get("review_history", []):
            source_entity_id = str(item.get("entity_source_id") or "")
            entity_type = str(item.get("entity_type") or "restored")
            entity_id = entity_maps.get(entity_type, {}).get(source_entity_id, source_entity_id)
            db.add(ReviewHistory(project_id=project.id, entity_type=entity_type, entity_id=entity_id, action=str(item.get("action") or "restored"), reviewer=item.get("reviewer"), before_data=item.get("before_data") or {}, after_data=item.get("after_data") or {}, reason=item.get("reason"), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone()))
        category_ids: dict[str, str] = {}
        for item in bundle.get("activity_categories", []):
            category = ActivityCategory(project_id=project.id, name=str(item.get("name") or "Restored category"), color=str(item.get("color") or "blue"), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone())
            db.add(category); db.flush()
            if item.get("source_id"): category_ids[str(item["source_id"])] = category.id
        for item in bundle.get("issue_snapshots", []):
            old_page_id = str(item.get("page_source_id")) if item.get("page_source_id") else None
            page_id = page_ids.get(old_page_id) if old_page_id else None
            issue_key = str(item.get("issue_key") or "restored_issue")
            if old_page_id and page_id: issue_key = issue_key.replace(f":{old_page_id}", f":{page_id}", 1)
            db.add(IssueSnapshot(project_id=project.id, import_batch_id=batch_ids[str(item.get("batch_source_id"))], page_id=page_id, issue_key=issue_key, issue_source=str(item.get("issue_source") or "on_page"), issue_type=str(item.get("issue_type") or "restored_issue"), category=str(item.get("category") or "General"), severity=str(item.get("severity") or "review"), label=str(item.get("label") or "Restored issue"), url=item.get("url"), detail=item.get("detail"), evidence=item.get("evidence") or {}, observed_on=_date(item.get("observed_on")) or date.today(), observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone()))
        for item in bundle.get("issue_snapshot_runs", []):
            db.add(IssueSnapshotRun(project_id=project.id, import_batch_id=batch_ids[str(item.get("batch_source_id"))], observed_on=_date(item.get("observed_on")) or date.today(), observed_at=_datetime(item.get("observed_at")) or datetime.now().astimezone(), outstanding_count=int(item.get("outstanding_count") or 0), new_count=int(item.get("new_count") or 0), resolved_count=int(item.get("resolved_count") or 0), baseline=bool(item.get("baseline", False))))
        activity_ids: dict[str, str] = {}
        pending_related: list[tuple[SEOActivity, str]] = []
        for item in bundle.get("seo_activities", []):
            old_page_id = str(item.get("page_source_id")) if item.get("page_source_id") else None
            page_id = page_ids.get(old_page_id) if old_page_id else None
            issue_key = item.get("issue_key")
            if issue_key and old_page_id and page_id: issue_key = str(issue_key).replace(f":{old_page_id}", f":{page_id}", 1)
            activity = SEOActivity(project_id=project.id, category_id=category_ids.get(str(item.get("category_source_id"))) if item.get("category_source_id") else None, page_id=page_id, import_batch_id=batch_ids.get(str(item.get("batch_source_id"))) if item.get("batch_source_id") else None, recommendation_id=recommendation_ids.get(str(item.get("recommendation_source_id"))) if item.get("recommendation_source_id") else None, issue_solution_id=solution_ids.get(str(item.get("solution_source_id"))) if item.get("solution_source_id") else None, event_key=str(item.get("event_key") or item.get("source_id") or uid()), source=str(item.get("source") or "restored"), section=str(item.get("section") or "general"), action_type=str(item.get("action_type") or "restored_activity"), status=str(item.get("status") or "completed"), title=str(item.get("title") or "Restored activity"), notes=item.get("notes"), url=item.get("url"), issue_key=issue_key, issue_type=item.get("issue_type"), before_data=item.get("before_data") or {}, after_data=item.get("after_data") or {}, activity_metadata=item.get("activity_metadata") or {}, occurred_at=_datetime(item.get("occurred_at")) or datetime.now().astimezone(), created_at=_datetime(item.get("created_at")) or datetime.now().astimezone())
            db.add(activity); db.flush()
            if item.get("source_id"): activity_ids[str(item["source_id"])] = activity.id
            if item.get("related_activity_source_id"): pending_related.append((activity, str(item["related_activity_source_id"])))
        for activity, source_related_id in pending_related:
            activity.related_activity_id = activity_ids.get(source_related_id)
        db.commit()
        db.refresh(project)
        return project
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(422, f"Could not import project bundle: {exc}") from exc


def delete_project_records(db: Session, project: Project) -> dict[str, int]:
    page_count = db.query(Page).filter(Page.project_id == project.id).count()
    batch_ids = list(db.scalars(select(ImportBatch.id).where(ImportBatch.project_id == project.id)))
    if batch_ids:
        db.execute(delete(ImportRow).where(ImportRow.batch_id.in_(batch_ids)))
    db.execute(delete(SitemapEntry).where(SitemapEntry.project_id == project.id))
    db.execute(delete(SitemapDocument).where(SitemapDocument.project_id == project.id))
    # Delete future-phase dependants before their parent Page/Keyword records.
    db.execute(delete(SEOActivity).where(SEOActivity.project_id == project.id))
    db.execute(delete(IssueSnapshot).where(IssueSnapshot.project_id == project.id))
    db.execute(delete(IssueSnapshotRun).where(IssueSnapshotRun.project_id == project.id))
    db.execute(delete(ActivityCategory).where(ActivityCategory.project_id == project.id))
    db.execute(delete(PageCrawlChange).where(PageCrawlChange.project_id == project.id))
    db.execute(delete(PageMetadataChange).where(PageMetadataChange.project_id == project.id))
    db.execute(delete(IssueSolution).where(IssueSolution.project_id == project.id))
    for model in (ReviewHistory, CaseDecision, CannibalizationEvidence, CannibalizationCase, TargetMapping, GroupingSuggestion, KeywordGroupMembership, GA4PagePerformance, GSCQueryPagePerformance, RankingObservation, KeywordMetricsSnapshot, PageMetadataRecommendation, PageMetadataObservation, PageRelationship, AuditCase, KeywordGroup, TopicCluster):
        db.execute(delete(model).where(model.project_id == project.id))
    db.execute(delete(Keyword).where(Keyword.project_id == project.id))
    db.execute(delete(ImportBatch).where(ImportBatch.project_id == project.id))
    db.execute(delete(Page).where(Page.project_id == project.id))
    db.execute(delete(Project).where(Project.id == project.id))
    db.commit()
    return {"pages_deleted": page_count, "imports_deleted": len(batch_ids)}
