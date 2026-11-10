# Phase 5 — Keyword Grouping, URL Mapping & Cannibalization Audit

## Role and delivery instruction
Continue and complete the five-phase **core** SEO Data Workspace application. Inspect the existing Phases 1–4 code, migrations and tests first. **Extend rather than rebuild**; keep all raw observations and approved page/metadata/architecture decisions. Deliver working source, migrations, tests, end-to-end demo data, updated guide, and exportable reports.

## Goal
Turn imported keyword rankings and page metadata into an editable ecommerce **keyword-to-page strategy**. Detect and investigate URLs appearing for the same keyword or intent without incorrectly calling all overlap harmful cannibalization. **No AI, crawler, or live Semrush/GSC/GA4 connections.**

## 1. Terminology and data model
Explicitly distinguish:
- **Keyword/query**: one searched phrase.
- **Keyword group**: related queries whose intent can normally be served by one page.
- **Topic cluster**: wider subject containing multiple keyword groups/pages.
- **Observed ranking URL**: page that appeared in imported Semrush or GSC query–page evidence.
- **Approved target URL**: page the SEO specialist chooses to target for the group.

Add persistent entities for TopicCluster, KeywordGroup, KeywordGroupMembership, PageTargetMapping, GroupingSuggestion, CannibalizationCase, CannibalizationEvidence, CaseDecision, and ReviewHistory. Use stable IDs and uniqueness constraints. Support proposed URLs that don't exist in page inventory yet; distinguish planned/new pages from existing pages. Preserve manual decisions and review history during imports.

## 2. Keyword group editor
- Create, rename, merge, split and archive keyword groups.
- Assign a primary keyword, supporting keywords, intent and topic cluster.
- Bulk assign keywords from filters, support undo/review for destructive grouping changes.
- Show unique aggregate keyword volume, opportunity score summary, best observed ranking pages, and group readiness.
- Permit multiple groups to share one target page intentionally; do not flag by default.

## 3. Rule-based clustering suggestions (no AI)
Implement deterministic, explainable suggestions using keyword normalization, token overlap, configurable synonyms (including women/ladies), word order, singular/plural, commercial/informational modifiers, search intent compatibility, and shared observed ranking URL evidence. Present **Strong / Moderate / Weak suggestion**, not fake calibrated probabilities. Show reason codes. A suggested group must never override an approved membership. Actions: Approve, Reassign, Split, Merge, Reject, Needs SERP Review. Acknowledge text heuristics can misclassify intent; no SERP-overlap evidence unless supplied in a file.

## 4. Page mapping workspace
List for each keyword group: primary keyword, topical cluster, intent, selected target page, page type (PLP/PDP/Editorial etc.), current observed ranking URLs, group search metrics, page metadata status from Phase 3, sitemap inclusion from Phase 2, and mapping review status. Allow assign existing page or create a **proposed page record**; allow one primary target per group with an approved state. Flag ambiguous/conflicting assignments. Show missing canonical/indexability signals but don't automatically choose URLs based only on current rank.

The Page Profile must show: architecture location, current/proposed SEO metadata, ranking keywords, keyword groups mapped to page, target keywords, known overlaps, and a concise list of manual action suggestions.

## 5. Cannibalization audits — separate signals
### A. Exact query multi-URL overlap
Within a comparable project/market/device/reporting period/source scope, count distinct observed ranking URLs per query; flag >1 for **Review**, not confirmed cannibalization. List each URL's observed position, GSC clicks/impressions when query–page data exists, and on-page type. Don't mix historic snapshots in one count or treat query-only GSC data as URL evidence.

### B. Approved group-to-target mapping conflict
Flag multiple *conflicting approved primary URLs* for a single group or inconsistent membership/target assignments. Distinguish intentional mapping of several distinct groups to one URL.

### C. Ranking URL versus approved target URL mismatch
Flag when a different URL ranks for a query assigned to an approved target group. Make sure date/source context is shown; mismatch alone is not confirmation of damage.

### D. Related-page intent review
Flag pages with strongly overlapping approved group intent and similar targets; provide evidence, but do not mark all pages in a broad topic cluster as conflicting. Duplicate titles/H1s from Screaming Frog are optional diagnostic context, not proof of cannibalization.

### E. Historical corroboration when snapshots exist
When multiple comparable periods were imported, display change/alternation patterns, not automatic causal claims. With one snapshot, say 'History unavailable'. Never fabricate position volatility.

## 6. Cannibalization investigation workspace
For each case show:
- Query or group, case type, detection date and current status.
- All involved URLs and page types.
- Position and performance evidence by source and date.
- Intended primary URL and current metadata/canonical/indexability context.
- Evidence/reason codes, explicit unknowns, and notes.
- Reviewer, review date, preferred URL, proposed action, status and audit history.

Statuses: New, Needs Investigation, Harmless Overlap, Likely Cannibalization, Confirmed (manual only), Resolved, Reopened. Proposed actions: Keep Both; Differentiate Intent; Optimise Preferred Page; Improve Internal Links; Consolidate After Review; Consider Redirect; Review Canonical; No Action. **Never perform a redirect/canonical update, website edit, or publish an XML sitemap from this local app.**

Persistent case deduplication: repeated scans update existing cases instead of creating duplicates; manually dismissed cases should not constantly reappear unless relevant evidence changes. Save resolution history and reopen with explanation when evidence changes.

## 7. Dashboard and lightweight action queue
Core dashboard now shows unmapped keywords/groups, pages with approved mapping, high-priority groups, exact-query multi-URL overlaps, conflicting mappings, target mismatches, cases needing review, and resolved cases. Include clickable drilldowns. Add **review/action queue** (not a full task-management system) that surfaces page to optimise, query/group, issue reason, priority, selected target, action and review state. Export a Page Map, Keyword Map, Cannibalization Audit, and Review Queue as XLSX/CSV.

## 8. Navigation and UX
Sidebar: Dashboard, Pages, Site Architecture, On-Page SEO, Keyword Research, **Keyword Groups**, **Page Mapping**, **Cannibalization Audit**, Imports, Settings. Prefer page-level exploration over many disconnected tables. Allow bulk edits, filter persistence, one-click jump from issue to page/query and back, source timestamps and explanatory tooltips. Label imported fact vs heuristic suggestion vs user-approved decision.

## 9. Testing and scenarios
End-to-end fixtures must include:
1. Several similar queries correctly proposed for one PLP.
2. 'best' informational/commercial guide suggestion separate from transactional PLP.
3. A query ranking via three distinct URLs in same snapshot.
4. A single URL ranking for many queries (not cannibalization by itself).
5. Two groups in same broad topic mapped to different pages (legitimate).
6. Target URL mismatch without confirmed harm.
7. Same query in different import periods (not same-snapshot overlap).
8. GSC query-only report (no inferred URL).
9. Approved mapping preserved after Semrush import refresh.
10. Repeated audit scan without duplicate cases; resolved/reopened lifecycle.
11. Proposed page not yet in sitemap.
12. Duplicate metadata used only as supporting evidence.

Test source/period filters, distinct URL counts, project separation, missing data, export accuracy, migrations and no regression in Phases 1–4.

## Acceptance criteria
Using only imported Screaming Frog, GSC, GA4 and Semrush files, a user can maintain a site inventory and visual sitemap, record current/proposed on-page metadata, prioritise keywords, review grouping suggestions, approve keyword-to-page mapping, see exact-query multi-URL overlaps, investigate and resolve potential cannibalization, and export an actionable report. Core features work locally with **no AI and no mandatory online connection**.

## Final handoff
Include install/run instructions, schema/ER diagram, precise import-field guide by source, sample data, test report, clear known limitations (no crawl, no automatic SERP verification, no direct site edits), and upgrade path for future optional competitor analysis and performance tracking—**do not implement those advanced modules now**.
