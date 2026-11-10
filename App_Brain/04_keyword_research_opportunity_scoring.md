# Phase 4 — Keyword Research, Semrush/GSC/GA4 Imports & Opportunity Scoring

## Role and delivery instruction
Continue the functioning SEO Data Workspace from Phases 1–3. Do not rebuild. Inspect schema and all tests before implementation. Preserve page identities, sitemap decisions, metadata recommendations, and import provenance. Implement features in real code and demonstrate them with representative sample exports.

## Goal
Connect keyword and performance data to existing website pages; identify **qualified ecommerce organic traffic opportunities**, even when AOV, conversion rates, and revenue are unavailable. Operate from **uploaded exports only**—no Semrush/GSC/GA4 live API, AI, crawler or cloud integration.

## 1. Separate source import adapters
### Semrush keyword/position exports
Support configurable CSV/XLSX columns: keyword, volume, KD%, position, intent, URL/ranking landing page, optional SERP features, country/database, device, and export date. Semrush layouts differ across exports; include preview and flexible mapping. Preserve keyword–ranking-URL records and rank per snapshot. Missing URL is allowed; highlight mapping gaps.

### Google Search Console exports
Support query-level and **query × page** performance exports with clicks, impressions, CTR, average position, search type, country/device if exported, and date range. **Don't infer a ranking URL from a query-only GSC export.** Only create query–URL links when page data exists. Capture reporting period dimensions and GSC's average-position semantics. Never sum or blend incomparable GSC aggregations without warning.

### Google Analytics 4 exports
Support optional **landing page** and page path reports with sessions, engaged sessions, conversions/key events, purchases, and revenue *only where actually exported*. Store GA4 attribution/report scope and date range. **GA4 does not provide an inherent keyword-to-page mapping**; attach GA4 metrics at page/landing-page level, not per keyword. Match via configurable hostname/path canonicalization, with unresolved mappings in a review queue. Label channel/organic traffic filters explicitly; don't call all GA4 sessions organic.

For all sources, implement import preview, column mapping, staging, validation, audit trail, project/market/device/date dimensions, missing-value treatment, import history, and non-destructive refreshes. Preserve raw source values and normalized derived values.

## 2. Keyword and observation data model
Use `Keyword` keyed by project + normalized phrase (with optional market/language context). Maintain separate:
- `KeywordMetricsSnapshot` (Semrush volume/KD/intent by market/date)
- `RankingObservation` (keyword, URL/page when available, position, provider, snapshot, market/device)
- `GSCQueryPagePerformance` (query, page, clicks/impressions/CTR/average position, period/dimensions)
- `GA4PagePerformance` (page, organic sessions/etc., period/attribution filters)

Never enforce a single ranking URL per keyword. Do not merge different timeframes or source-specific positions into a single undifferentiated metric. Clearly label Semrush positions versus GSC average positions. Stable keys for re-import and history.

## 3. Keyword Explorer
Table with keyword, Semrush volume, KD, intent, current Semrush best position, all observed ranking URLs, GSC clicks/impressions (if available), optional GA4 landing-page context, and opportunity score. Filters by intent, keyword, ranking range, URL/page type, PLP/PDP/Editorial, opportunity band, import coverage. A keyword detail page shows source-by-source evidence and its associated URLs (with dates).

## 4. Transparent keyword opportunity score
Default weighted model (0–100):
- Traffic potential 30%
- Commercial/search intent 30%
- Ranking feasibility 25%
- Product relevance 15%

Default `TrafficScore = 100 * ln(1 + volume) / ln(1 + max_volume)` for comparable keywords in selected project/market. Handle missing and zero values differently. Intent values configurable (Transactional 100, Commercial 85, Mixed 65, Informational 35, Navigational 25), with contextual overrides. Feasibility is a **heuristic** using rank bands and KD; KD is not the probability of ranking. Product relevance manually scored (0–100) with an explicit "Needs Review" state; do not silently treat missing values as maximum fit. Weights editable per project and normalized. Missing optional sources should not unfairly zero a keyword. Explain each calculated component in the UI. Score **once per unique keyword for selected scope**, not once per ranking URL.

Rank bands: Winner 1–3, Quick Win 4–15, Striking Distance 16–30, Long-Term 31+, Not Ranking, Missing Data; configurable. Use best observed Semrush position within comparable selected snapshot for keyword classification, with source disclosed.

## 5. Page-level opportunity view
From each page, list its observed ranking keywords, source dates, keyword scores, GSC query/page data if available, and optional GA4 organic landing-page performance. Identify unassociated keywords and unresolved landing-page joins. Distinguish current ranking URL from future intended target URL (to be implemented in Phase 5). Aggregate distinct keyword metrics carefully; never sum duplicate keyword search volumes and label as actual traffic. Allow volume reach estimates with warning that related keywords can overlap.

## 6. Dashboard
Unique ranking keywords, position distribution, top quick-win keywords, commercial opportunities, data coverage by source, missing URL joins, organic clicks/impressions where compatible, GA4 organic landing page sessions (optional). Show selected period, source and market on every chart where important.

## 7. Tests
Fixtures for Semrush multiple URLs per same keyword, GSC query-only vs query-page, source rank discrepancies, period mismatch, GA4 path vs absolute URL, missing revenue/AOV, null vs zero, repeated imported batches, market/device distinctions, and duplicate keyword scoring. Test every normalizer, import, aggregation and scoring function; no inflated keyword counts.

## Acceptance criteria
Users import Semrush, GSC, and optional GA4 files; reconcile columns; browse keywords and their current ranking URLs; calculate and explain opportunity scores; filter priorities; inspect page-related keywords and organic metrics; export rankings and opportunities. All prior phases continue working. No live services or AI required.

## Handoff for Phase 5
Document keyword-level and URL-level data joins, source/time semantics, and score rules. Phase 5 adds **approved keyword groups and target URL mapping plus cannibalization audit**, preserving multiple observed ranking URLs and user decisions across import refreshes.
