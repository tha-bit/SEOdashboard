from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    GA4PagePerformance,
    GSCQueryPagePerformance,
    ImportBatch,
    ImportRow,
    Keyword,
    KeywordMetricsSnapshot,
    Page,
    Project,
    RankingObservation,
)
from .urls import normalize_url


KEYWORD_PRESETS: dict[str, dict[str, list[str]]] = {
    "semrush": {
        "keyword": ["Keyword", "Phrase", "Search Term"],
        "volume": ["Volume", "Search Volume"],
        "keyword_difficulty": ["KD %", "KD%", "Keyword Difficulty", "Difficulty"],
        "position": ["Position", "Pos."],
        "intent": ["Intent", "Search Intent"],
        "ranking_url": ["URL", "Ranking URL", "Landing Page"],
        "serp_features": ["SERP Features", "SERP Feature"],
        "market": ["Database", "Country", "Market"],
        "device": ["Device"],
        "snapshot_date": ["Date", "Export Date", "Snapshot Date"],
    },
    "gsc": {
        "keyword": ["Top queries", "Query", "Queries"],
        "page_url": ["Top pages", "Page", "Landing Page"],
        "clicks": ["Clicks"],
        "impressions": ["Impressions"],
        "ctr": ["CTR"],
        "average_position": ["Position", "Average Position"],
        "search_type": ["Search type", "Search Type"],
        "country": ["Country"],
        "device": ["Device"],
        "period_start": ["Start Date", "Date Start", "Period Start"],
        "period_end": ["End Date", "Date End", "Period End"],
    },
    "ga4": {
        "landing_page": ["Landing page", "Landing page + query string", "Page path and screen class", "Page path"],
        "sessions": ["Sessions"],
        "engaged_sessions": ["Engaged sessions"],
        "conversions": ["Conversions", "Key events"],
        "purchases": ["Ecommerce purchases", "Purchases"],
        "revenue": ["Total revenue", "Purchase revenue", "Revenue"],
        "period_start": ["Start Date", "Date Start", "Period Start"],
        "period_end": ["End Date", "Date End", "Period End"],
        "attribution_scope": ["Attribution scope", "Report scope"],
        "channel_filter": ["Session default channel group", "Channel", "Traffic filter"],
    },
}

DEFAULT_WEIGHTS = {"traffic": 30.0, "intent": 30.0, "feasibility": 25.0, "relevance": 15.0}
DEFAULT_INTENT_SCORES = {"transactional": 100.0, "commercial": 85.0, "mixed": 65.0, "informational": 35.0, "navigational": 25.0}
DEFAULT_RANK_BANDS = {"winner": [1, 3], "quick_win": [4, 15], "striking_distance": [16, 30], "long_term": [31, None]}


def normalize_phrase(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def suggested_keyword_mapping(columns: list[str], source: str) -> dict[str, str]:
    lowered = {column.strip().casefold(): column for column in columns}
    result: dict[str, str] = {}
    for semantic, aliases in KEYWORD_PRESETS.get(source, {}).items():
        for alias in aliases:
            if alias.casefold() in lowered:
                result[semantic] = lowered[alias.casefold()]
                break
    return result


def keyword_semantic_fields(source: str) -> list[dict[str, str]]:
    labels = {
        "keyword": "Keyword / query", "volume": "Search volume", "keyword_difficulty": "Keyword difficulty",
        "position": "Position", "intent": "Intent", "ranking_url": "Ranking URL", "serp_features": "SERP features",
        "market": "Market / database", "device": "Device", "snapshot_date": "Snapshot date", "page_url": "Page URL",
        "clicks": "Clicks", "impressions": "Impressions", "ctr": "CTR", "average_position": "Average position",
        "search_type": "Search type", "country": "Country", "period_start": "Period start", "period_end": "Period end",
        "landing_page": "Landing page / path", "sessions": "Sessions", "engaged_sessions": "Engaged sessions",
        "conversions": "Conversions / key events", "purchases": "Purchases", "revenue": "Revenue",
        "attribution_scope": "Attribution / report scope", "channel_filter": "Channel filter",
    }
    return [{"key": key, "label": labels[key]} for key in KEYWORD_PRESETS.get(source, {})]


def _number(value: Any) -> float | None:
    if value is None or str(value).strip().casefold() in {"", "nan", "n/a", "-", "—"}:
        return None
    cleaned = str(value).strip().replace(",", "").replace("%", "").replace("£", "").replace("$", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _date(value: Any, fallback: date | None = None) -> date | None:
    if value is None or not str(value).strip():
        return fallback
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return fallback


def _raw(row: ImportRow, mapping: dict[str, str], key: str) -> Any:
    column = mapping.get(key)
    return row.raw_data.get(column) if column else None


def _page_for_url(db: Session, project: Project, value: str | None) -> tuple[Page | None, str | None]:
    if not value or not str(value).strip():
        return None, None
    candidate = str(value).strip()
    if candidate.startswith("/"):
        candidate = urljoin(project.site_url.rstrip("/") + "/", candidate.lstrip("/"))
    try:
        normalized = normalize_url(candidate, project.preferences)
    except (ValueError, TypeError):
        return None, None
    return db.scalar(select(Page).where(Page.project_id == project.id, Page.normalized_url == normalized)), normalized


def _keyword(db: Session, project: Project, phrase: str, market: str = "", language: str = "") -> Keyword:
    normalized = normalize_phrase(phrase)
    item = db.scalar(select(Keyword).where(Keyword.project_id == project.id, Keyword.normalized_phrase == normalized, Keyword.market == market, Keyword.language == language))
    if item:
        return item
    item = Keyword(project_id=project.id, text=phrase.strip(), normalized_phrase=normalized, locale=project.locale, market=market, language=language)
    db.add(item)
    db.flush()
    return item


def confirm_keyword_import(db: Session, batch: ImportBatch, project: Project, mapping: dict[str, str]) -> ImportBatch:
    if batch.source in {"semrush", "gsc"} and not mapping.get("keyword"):
        raise HTTPException(422, "Map a source column to Keyword / query before importing")
    if batch.source == "ga4" and not mapping.get("landing_page"):
        raise HTTPException(422, "Map a source column to Landing page before importing")
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_number)).all()
    imported = errors = 0
    metric_keys: set[tuple[str, str, str, date | None]] = set()
    batch.mapping = mapping
    for row in rows:
        try:
            if batch.source == "semrush":
                phrase = str(_raw(row, mapping, "keyword") or "").strip()
                if not phrase:
                    raise ValueError("Keyword is empty")
                market = str(_raw(row, mapping, "market") or project.market or "").strip()
                device = str(_raw(row, mapping, "device") or "").strip()
                observed_on = _date(_raw(row, mapping, "snapshot_date"), batch.reporting_date)
                keyword = _keyword(db, project, phrase, market)
                metric_key = (keyword.id, market, device, observed_on)
                volume = _integer(_raw(row, mapping, "volume"))
                difficulty = _number(_raw(row, mapping, "keyword_difficulty"))
                intent = str(_raw(row, mapping, "intent") or "").strip() or None
                if metric_key not in metric_keys and any(mapping.get(key) for key in ("volume", "keyword_difficulty", "intent", "serp_features")):
                    features = [item.strip() for item in re.split(r"[,;|]", str(_raw(row, mapping, "serp_features") or "")) if item.strip()]
                    supplied = [key for key in ("volume", "keyword_difficulty", "intent", "serp_features") if mapping.get(key)]
                    db.add(KeywordMetricsSnapshot(project_id=project.id, keyword_id=keyword.id, import_batch_id=batch.id, observed_on=observed_on, observed_at=batch.imported_at, market=market, device=device, volume=volume, keyword_difficulty=difficulty, intent=intent, serp_features=features, supplied_fields=supplied, raw_data=row.raw_data))
                    metric_keys.add(metric_key)
                ranking_url = str(_raw(row, mapping, "ranking_url") or "").strip() or None
                page, _ = _page_for_url(db, project, ranking_url)
                position = _number(_raw(row, mapping, "position"))
                if mapping.get("position") or ranking_url:
                    db.add(RankingObservation(project_id=project.id, keyword_id=keyword.id, page_id=page.id if page else None, import_batch_id=batch.id, provider="semrush", ranking_url=ranking_url, position=position, observed_on=observed_on, observed_at=batch.imported_at, market=market, device=device, source_scope="organic positions", raw_data=row.raw_data, metrics={"position": position}))
                row.page_id = page.id if page else None
                row.normalized_data = {"keyword_id": keyword.id, "phrase": keyword.normalized_phrase, "market": market, "device": device, "position": position, "ranking_url": ranking_url}
            elif batch.source == "gsc":
                phrase = str(_raw(row, mapping, "keyword") or "").strip()
                if not phrase:
                    raise ValueError("Query is empty")
                country = str(_raw(row, mapping, "country") or project.market or "").strip()
                device = str(_raw(row, mapping, "device") or "").strip()
                keyword = _keyword(db, project, phrase, country)
                page_url = str(_raw(row, mapping, "page_url") or "").strip() or None
                page, _ = _page_for_url(db, project, page_url)
                ctr = _number(_raw(row, mapping, "ctr"))
                if ctr is not None and ctr > 1:
                    ctr /= 100
                performance = GSCQueryPagePerformance(project_id=project.id, keyword_id=keyword.id, page_id=page.id if page else None, import_batch_id=batch.id, page_url=page_url, aggregation_type="query_page" if mapping.get("page_url") else "query_only", period_start=_date(_raw(row, mapping, "period_start")), period_end=_date(_raw(row, mapping, "period_end"), batch.reporting_date), search_type=str(_raw(row, mapping, "search_type") or "web").strip(), country=country, device=device, clicks=_number(_raw(row, mapping, "clicks")), impressions=_number(_raw(row, mapping, "impressions")), ctr=ctr, average_position=_number(_raw(row, mapping, "average_position")), observed_at=batch.imported_at, raw_data=row.raw_data)
                db.add(performance)
                row.page_id = page.id if page else None
                row.normalized_data = {"keyword_id": keyword.id, "aggregation_type": performance.aggregation_type, "page_url": page_url, "country": country, "device": device}
            else:
                landing_page = str(_raw(row, mapping, "landing_page") or "").strip()
                if not landing_page:
                    raise ValueError("Landing page is empty")
                page, normalized = _page_for_url(db, project, landing_page)
                channel = str(_raw(row, mapping, "channel_filter") or "").strip() or None
                db.add(GA4PagePerformance(project_id=project.id, page_id=page.id if page else None, import_batch_id=batch.id, landing_page=landing_page, normalized_url=normalized, period_start=_date(_raw(row, mapping, "period_start")), period_end=_date(_raw(row, mapping, "period_end"), batch.reporting_date), attribution_scope=str(_raw(row, mapping, "attribution_scope") or "").strip() or None, channel_filter=channel, sessions=_number(_raw(row, mapping, "sessions")), engaged_sessions=_number(_raw(row, mapping, "engaged_sessions")), conversions=_number(_raw(row, mapping, "conversions")), purchases=_number(_raw(row, mapping, "purchases")), revenue=_number(_raw(row, mapping, "revenue")), observed_at=batch.imported_at, raw_data=row.raw_data))
                row.page_id = page.id if page else None
                row.normalized_data = {"landing_page": landing_page, "normalized_url": normalized, "matched": bool(page), "channel_filter": channel}
            row.validation_status = "imported"
            imported += 1
        except ValueError as exc:
            row.validation_status = "error"
            row.error_message = str(exc)
            errors += 1
    batch.imported_count = imported
    batch.error_count = errors
    batch.status = "completed_with_errors" if errors else "completed"
    if batch.source == "gsc" and not mapping.get("page_url"):
        batch.warnings = [*batch.warnings, "Query-only GSC import: no ranking URL or query-to-page relationship was inferred."]
    if batch.source == "ga4" and not mapping.get("channel_filter"):
        batch.warnings = [*batch.warnings, "No channel filter was supplied; sessions are not labelled as organic."]
    db.commit()
    return batch


def score_settings(project: Project) -> dict[str, Any]:
    stored = (project.preferences or {}).get("keyword_scoring", {})
    weights = {**DEFAULT_WEIGHTS, **stored.get("weights", {})}
    total = sum(max(0.0, float(value)) for value in weights.values()) or 100.0
    weights = {key: max(0.0, float(value)) * 100 / total for key, value in weights.items()}
    return {"weights": weights, "intent_scores": {**DEFAULT_INTENT_SCORES, **stored.get("intent_scores", {})}, "rank_bands": stored.get("rank_bands", DEFAULT_RANK_BANDS)}


def rank_band(position: float | None) -> str:
    if position is None:
        return "Not Ranking"
    if position <= 3:
        return "Winner"
    if position <= 15:
        return "Quick Win"
    if position <= 30:
        return "Striking Distance"
    return "Long-Term"


def opportunity_components(keyword: Keyword, metric: KeywordMetricsSnapshot | None, position: float | None, max_volume: int, settings: dict[str, Any]) -> dict[str, Any]:
    volume = metric.volume if metric else None
    traffic = 100 * math.log1p(volume) / math.log1p(max_volume) if volume is not None and max_volume > 0 else (0.0 if volume == 0 else None)
    intent_name = (metric.intent or "").strip().casefold() if metric else ""
    intent = settings["intent_scores"].get(intent_name) if intent_name else None
    difficulty = metric.keyword_difficulty if metric else None
    base = 55.0 if position is not None and position <= 3 else 95.0 if position is not None and position <= 15 else 80.0 if position is not None and position <= 30 else 55.0 if position is not None else 40.0
    feasibility = base if difficulty is None else 0.6 * base + 0.4 * max(0.0, min(100.0, 100.0 - difficulty))
    relevance = keyword.product_relevance
    values = {"traffic": traffic, "intent": intent, "feasibility": feasibility, "relevance": relevance}
    available_weight = sum(settings["weights"][key] for key, value in values.items() if value is not None)
    score = sum(float(value) * settings["weights"][key] for key, value in values.items() if value is not None) / available_weight if available_weight else None
    return {
        "score": round(score, 1) if score is not None else None,
        "band": "Needs Review" if relevance is None else "High" if score is not None and score >= 75 else "Medium" if score is not None and score >= 50 else "Low",
        "rank_band": rank_band(position),
        "provisional": any(value is None for value in values.values()),
        "components": {key: None if value is None else round(float(value), 1) for key, value in values.items()},
        "weights_used": settings["weights"],
        "explanation": "Missing components are excluded and remaining weights are normalized; the score is provisional until product relevance is reviewed." if any(value is None for value in values.values()) else "All four weighted components are available.",
    }


def current_keyword_rows(db: Session, project: Project) -> list[dict[str, Any]]:
    keywords = db.scalars(select(Keyword).where(Keyword.project_id == project.id).order_by(Keyword.text)).all()
    metrics = db.scalars(select(KeywordMetricsSnapshot).where(KeywordMetricsSnapshot.project_id == project.id).order_by(KeywordMetricsSnapshot.observed_on.desc(), KeywordMetricsSnapshot.observed_at.desc())).all()
    rankings = db.scalars(select(RankingObservation).where(RankingObservation.project_id == project.id, RankingObservation.provider == "semrush").order_by(RankingObservation.observed_on.desc(), RankingObservation.observed_at.desc())).all()
    gsc = db.scalars(select(GSCQueryPagePerformance).where(GSCQueryPagePerformance.project_id == project.id).order_by(GSCQueryPagePerformance.period_end.desc(), GSCQueryPagePerformance.observed_at.desc())).all()
    latest_metric: dict[str, KeywordMetricsSnapshot] = {}
    latest_rank_scope: dict[str, tuple[date | None, datetime]] = {}
    current_ranks: dict[str, list[RankingObservation]] = {}
    latest_gsc_scope: dict[str, tuple[str, date | None, datetime]] = {}
    current_gsc: dict[str, list[GSCQueryPagePerformance]] = {}
    for item in metrics:
        latest_metric.setdefault(item.keyword_id, item)
    for item in rankings:
        scope = (item.observed_on, item.observed_at)
        if item.keyword_id not in latest_rank_scope:
            latest_rank_scope[item.keyword_id] = scope
        if latest_rank_scope[item.keyword_id] == scope:
            current_ranks.setdefault(item.keyword_id, []).append(item)
    for item in gsc:
        scope = (item.aggregation_type, item.period_end, item.observed_at)
        if item.keyword_id not in latest_gsc_scope:
            latest_gsc_scope[item.keyword_id] = scope
        if latest_gsc_scope[item.keyword_id] == scope:
            current_gsc.setdefault(item.keyword_id, []).append(item)
    max_volume_by_market: dict[str, int] = {}
    for item in latest_metric.values():
        max_volume_by_market[item.market] = max(max_volume_by_market.get(item.market, 0), item.volume or 0)
    settings = score_settings(project)
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project.id)).all()}
    result = []
    for keyword in keywords:
        metric = latest_metric.get(keyword.id)
        rank_items = current_ranks.get(keyword.id, [])
        positions = [item.position for item in rank_items if item.position is not None]
        best_position = min(positions) if positions else None
        gsc_items = current_gsc.get(keyword.id, [])
        clicks = sum(item.clicks or 0 for item in gsc_items) if gsc_items else None
        impressions = sum(item.impressions or 0 for item in gsc_items) if gsc_items else None
        urls = []
        page_types = []
        for item in rank_items:
            url = item.ranking_url or (pages[item.page_id].original_url if item.page_id in pages else None)
            if url and url not in urls:
                urls.append(url)
            if item.page_id in pages and pages[item.page_id].page_type not in page_types:
                page_types.append(pages[item.page_id].page_type)
        comparable_market = metric.market if metric else keyword.market
        score = opportunity_components(keyword, metric, best_position, max_volume_by_market.get(comparable_market, 0), settings)
        result.append({"id": keyword.id, "keyword": keyword.text, "market": keyword.market, "language": keyword.language, "volume": metric.volume if metric else None, "keyword_difficulty": metric.keyword_difficulty if metric else None, "intent": metric.intent if metric else None, "metric_date": metric.observed_on if metric else None, "best_semrush_position": best_position, "rank_date": latest_rank_scope.get(keyword.id, (None, None))[0], "rank_band": score["rank_band"], "ranking_urls": urls, "ranking_url_count": len(urls), "ranking_page_types": page_types, "gsc_clicks": clicks, "gsc_impressions": impressions, "gsc_scope": latest_gsc_scope.get(keyword.id, (None, None, None))[0], "product_relevance": keyword.product_relevance, "relevance_status": keyword.relevance_status, "opportunity": score})
    return result
