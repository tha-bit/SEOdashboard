from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GA4PagePerformance, GSCQueryPagePerformance, ImportBatch, Keyword, KeywordMetricsSnapshot, Page, Project, RankingObservation
from ..services.keywords import current_keyword_rows, score_settings

router = APIRouter(prefix="/api/projects/{project_id}/keywords", tags=["keywords"])


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


class RelevanceUpdate(BaseModel):
    product_relevance: float | None = Field(default=None, ge=0, le=100)
    relevance_status: str = "reviewed"
    relevance_notes: str | None = Field(default=None, max_length=10_000)


class ScoringUpdate(BaseModel):
    weights: dict[str, float]
    intent_scores: dict[str, float]


@router.get("")
def keyword_explorer(project_id: str, db: Session = Depends(get_db)):
    return current_keyword_rows(db, project_or_404(db, project_id))


@router.get("/summary")
def keyword_summary(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    rows = current_keyword_rows(db, project)
    semrush_count = db.scalar(select(func.count(func.distinct(RankingObservation.keyword_id))).where(RankingObservation.project_id == project_id, RankingObservation.provider == "semrush")) or 0
    gsc_count = db.scalar(select(func.count(func.distinct(GSCQueryPagePerformance.keyword_id))).where(GSCQueryPagePerformance.project_id == project_id)) or 0
    unresolved_rankings = db.scalar(select(func.count(RankingObservation.id)).where(RankingObservation.project_id == project_id, RankingObservation.ranking_url.is_not(None), RankingObservation.page_id.is_(None))) or 0
    unresolved_ga4 = db.scalar(select(func.count(GA4PagePerformance.id)).where(GA4PagePerformance.project_id == project_id, GA4PagePerformance.page_id.is_(None))) or 0
    return {
        "unique_keywords": len(rows),
        "semrush_keywords": semrush_count,
        "gsc_keywords": gsc_count,
        "quick_wins": sum(item["rank_band"] == "Quick Win" for item in rows),
        "commercial_opportunities": sum(str(item.get("intent") or "").casefold() in {"commercial", "transactional"} and item["opportunity"]["band"] in {"High", "Medium"} for item in rows),
        "missing_url_joins": unresolved_rankings + unresolved_ga4,
        "position_distribution": {label: sum(item["rank_band"] == label for item in rows) for label in ("Winner", "Quick Win", "Striking Distance", "Long-Term", "Not Ranking")},
        "source_coverage": {"semrush": semrush_count, "gsc": gsc_count, "ga4_pages": db.scalar(select(func.count(func.distinct(GA4PagePerformance.page_id))).where(GA4PagePerformance.project_id == project_id, GA4PagePerformance.page_id.is_not(None))) or 0},
    }


@router.get("/settings")
def keyword_settings(project_id: str, db: Session = Depends(get_db)):
    return score_settings(project_or_404(db, project_id))


@router.patch("/settings")
def update_keyword_settings(project_id: str, payload: ScoringUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    expected = {"traffic", "intent", "feasibility", "relevance"}
    if set(payload.weights) != expected or any(value < 0 for value in payload.weights.values()) or sum(payload.weights.values()) <= 0:
        raise HTTPException(422, "Provide non-negative weights for traffic, intent, feasibility and relevance")
    preferences = dict(project.preferences or {})
    preferences["keyword_scoring"] = {"weights": payload.weights, "intent_scores": payload.intent_scores}
    project.preferences = preferences
    db.commit()
    return score_settings(project)


@router.patch("/{keyword_id}/relevance")
def update_relevance(project_id: str, keyword_id: str, payload: RelevanceUpdate, db: Session = Depends(get_db)):
    keyword = db.get(Keyword, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(404, "Keyword not found")
    keyword.product_relevance = payload.product_relevance
    keyword.relevance_status = "needs_review" if payload.product_relevance is None else payload.relevance_status
    keyword.relevance_notes = payload.relevance_notes
    db.commit()
    return {"id": keyword.id, "product_relevance": keyword.product_relevance, "relevance_status": keyword.relevance_status, "relevance_notes": keyword.relevance_notes}


@router.get("/export")
def export_keywords(project_id: str, db: Session = Depends(get_db)):
    rows = current_keyword_rows(db, project_or_404(db, project_id))
    output = io.StringIO()
    fields = ["Keyword", "Market", "Volume", "KD", "Intent", "Best Semrush Position", "Rank Band", "Ranking URLs", "GSC Clicks", "GSC Impressions", "Product Relevance", "Opportunity Score", "Opportunity Band", "Provisional"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in rows:
        writer.writerow({"Keyword": item["keyword"], "Market": item["market"], "Volume": item["volume"], "KD": item["keyword_difficulty"], "Intent": item["intent"], "Best Semrush Position": item["best_semrush_position"], "Rank Band": item["rank_band"], "Ranking URLs": " | ".join(item["ranking_urls"]), "GSC Clicks": item["gsc_clicks"], "GSC Impressions": item["gsc_impressions"], "Product Relevance": item["product_relevance"], "Opportunity Score": item["opportunity"]["score"], "Opportunity Band": item["opportunity"]["band"], "Provisional": item["opportunity"]["provisional"]})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=keyword-opportunities.csv"})


@router.get("/{keyword_id}")
def keyword_detail(project_id: str, keyword_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    keyword = db.get(Keyword, keyword_id)
    if not keyword or keyword.project_id != project_id:
        raise HTTPException(404, "Keyword not found")
    current = next(item for item in current_keyword_rows(db, project) if item["id"] == keyword_id)
    metrics = db.scalars(select(KeywordMetricsSnapshot).where(KeywordMetricsSnapshot.project_id == project_id, KeywordMetricsSnapshot.keyword_id == keyword_id).order_by(KeywordMetricsSnapshot.observed_on.desc(), KeywordMetricsSnapshot.observed_at.desc())).all()
    rankings = db.scalars(select(RankingObservation).where(RankingObservation.project_id == project_id, RankingObservation.keyword_id == keyword_id).order_by(RankingObservation.observed_on.desc(), RankingObservation.observed_at.desc())).all()
    gsc = db.scalars(select(GSCQueryPagePerformance).where(GSCQueryPagePerformance.project_id == project_id, GSCQueryPagePerformance.keyword_id == keyword_id).order_by(GSCQueryPagePerformance.period_end.desc(), GSCQueryPagePerformance.observed_at.desc())).all()
    page_ids = {item.page_id for item in rankings if item.page_id} | {item.page_id for item in gsc if item.page_id}
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.id.in_(page_ids))).all()} if page_ids else {}
    ga4 = db.scalars(select(GA4PagePerformance).where(GA4PagePerformance.project_id == project_id, GA4PagePerformance.page_id.in_(page_ids)).order_by(GA4PagePerformance.period_end.desc(), GA4PagePerformance.observed_at.desc())).all() if page_ids else []
    batches = {item.id: item for item in db.scalars(select(ImportBatch).where(ImportBatch.project_id == project_id)).all()}
    return {
        **current,
        "relevance_notes": keyword.relevance_notes,
        "metric_history": [{"id": item.id, "date": item.observed_on, "observed_at": item.observed_at, "source": batches[item.import_batch_id].file_name if item.import_batch_id in batches else item.provider, "market": item.market, "device": item.device, "volume": item.volume, "keyword_difficulty": item.keyword_difficulty, "intent": item.intent, "supplied_fields": item.supplied_fields} for item in metrics],
        "ranking_history": [{"id": item.id, "provider": item.provider, "date": item.observed_on, "observed_at": item.observed_at, "source": batches[item.import_batch_id].file_name if item.import_batch_id in batches else item.provider, "position": item.position, "url": item.ranking_url, "page_id": item.page_id, "page_type": pages[item.page_id].page_type if item.page_id in pages else None, "market": item.market, "device": item.device} for item in rankings],
        "gsc_history": [{"id": item.id, "period_start": item.period_start, "period_end": item.period_end, "observed_at": item.observed_at, "source": batches[item.import_batch_id].file_name if item.import_batch_id in batches else "GSC", "aggregation_type": item.aggregation_type, "page_url": item.page_url, "page_id": item.page_id, "clicks": item.clicks, "impressions": item.impressions, "ctr": item.ctr, "average_position": item.average_position, "search_type": item.search_type, "country": item.country, "device": item.device} for item in gsc],
        "ga4_page_context": [{"id": item.id, "period_start": item.period_start, "period_end": item.period_end, "landing_page": item.landing_page, "page_id": item.page_id, "page_type": pages[item.page_id].page_type if item.page_id in pages else None, "sessions": item.sessions, "engaged_sessions": item.engaged_sessions, "conversions": item.conversions, "purchases": item.purchases, "revenue": item.revenue, "channel_filter": item.channel_filter, "attribution_scope": item.attribution_scope} for item in ga4],
    }


@router.get("/pages/{page_id}/opportunities")
def page_keyword_opportunities(project_id: str, page_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    page = db.get(Page, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Page not found")
    keyword_ids = set(db.scalars(select(RankingObservation.keyword_id).where(RankingObservation.project_id == project_id, RankingObservation.page_id == page_id)).all()) | set(db.scalars(select(GSCQueryPagePerformance.keyword_id).where(GSCQueryPagePerformance.project_id == project_id, GSCQueryPagePerformance.page_id == page_id)).all())
    rows = [item for item in current_keyword_rows(db, project) if item["id"] in keyword_ids]
    ga4 = db.scalars(select(GA4PagePerformance).where(GA4PagePerformance.project_id == project_id, GA4PagePerformance.page_id == page_id).order_by(GA4PagePerformance.period_end.desc(), GA4PagePerformance.observed_at.desc())).all()
    return {"page": {"id": page.id, "url": page.original_url, "page_type": page.page_type}, "keywords": rows, "volume_reach": sum({item["id"]: item["volume"] or 0 for item in rows}.values()), "volume_warning": "Distinct keyword volumes are estimates and can overlap; this is not actual traffic.", "ga4_history": [{"period_start": item.period_start, "period_end": item.period_end, "sessions": item.sessions, "engaged_sessions": item.engaged_sessions, "conversions": item.conversions, "purchases": item.purchases, "revenue": item.revenue, "channel_filter": item.channel_filter} for item in ga4]}
