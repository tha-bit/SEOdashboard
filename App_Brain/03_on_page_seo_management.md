# Phase 3 — On-Page SEO Metadata Workspace

## Role and delivery instruction
Continue the existing SEO Data Workspace built in Phases 1–2. Inspect existing code, schema, tests, and sample exports. Extend without replacing the application, dropping tables, changing stable page IDs, or overwriting approved architecture. Deliver working code, migrations, tests and docs.

## Goal
Provide an organised **per-page on-page SEO workspace** with imported current metadata from **Screaming Frog** and separate manual recommended values. No crawler or live website fetch, AI, cloud services, or SEO APIs.

## 1. Screaming Frog metadata import
Expand the existing CSV/XLSX import system to map common Screaming Frog exports and variations, including:
- URL/address
- H1 (support **multiple H1s**, separate columns or list)
- Meta/page title and its optional pixel/character metrics
- Meta description and its optional metrics
- Canonical link element target
- Meta robots directives; optionally X-Robots-Tag if source provides it (track origin separately)
- Hreflang alternate language + target URL (can arrive in separate export)
- HTTP status, indexability flags/reasons, content type, crawl date when present

Do not assume a single Screaming Frog export contains all these fields. Support multiple file types, repeated columns, separate hreflang files, file previews, mapped columns, and a provenance label for each observation. Missing means unknown—not blank on the website.

## 2. Current vs proposed metadata
Create separately persisted structures:
- **Observed metadata** from imports (source batch, crawl/report date, fields actually supplied, original raw values).
- **Proposed metadata** edited by the user (H1, meta title, description, canonical target, robots directives, hreflang set, status, notes, approval state).
- Optional change log that tracks reviewer, timestamp and old/new values.

Never overwrite proposed metadata when another Screaming Frog export is imported. Never claim a proposed value is deployed on the live site. Optionally mark implemented only after manual confirmation or newer import verifies it.

## 3. On-Page SEO list and page detail
Create **On-Page SEO** sidebar section with searchable table showing URL, PLP/PDP/Editorial page type, H1/title/description status, canonical/robots/indexability status, hreflang status, import recency, review status, and notable issues.

Click a page to open a tabbed detail drawer or full view:
- Overview (URL, page type, architecture parent, sitemap inclusion)
- Headings & snippets (current and proposed H1/title/description)
- Indexing & canonicals (canonical URL, robots meta, X-Robots when available, indexability evidence)
- International SEO (hreflang language/region, reciprocal relations if data supports validation)
- Change history / recommendations

Bulk edit proposed fields when appropriate, but never silently bulk-change live observations. Export current-vs-proposed metadata and issues.

## 4. Deterministic on-page validation rules
Flag and explain—not automatically "fix":
- Missing or multiple observed H1s (only when H1 data was actually collected)
- Missing/duplicate titles and meta descriptions among imported pages (duplicate strings alone are review signals)
- Title/description length guidance with configurable thresholds, avoiding hard-coded character limits as Google rules
- Canonical target malformed, external, redirected, non-indexable, or non-sitemap when relevant evidence exists
- Robots `noindex` and potential conflict with sitemap inclusion
- Contradictions between robots directives, indexability data, and sitemap intent
- Hreflang invalid code format, duplicate language codes, nonexistent target in known inventory, missing self-reference/reciprocal where complete evidence exists
- Unexpected metadata gaps by page type

Severity options: Info / Review / High; an issue can be dismissed/resolved manually with reason. Do not equate robots meta `nofollow` with a blanket indexing prohibition. Clarify that HTML metadata from an export is a snapshot and may be outdated.

## 5. Dashboard and connections
Update dashboard: pages with metadata, metadata coverage by PLP/PDP/Editorial, canonical mismatches, noindex sitemap candidates, hreflang review count, outstanding optimisations. Link each issue to specific page. Show architecture parent and sitemap status from Phase 2 in every page profile; maintain a single page identity.

## 6. User experience
Simple current/recommended side-by-side editor with source and last-observed date; multi-value H1 and hreflang editor; input validation; autosave or explicit save with feedback; undo where practical; filters by page type and issue type; no decorative mock metrics. Support not-provided, explicitly empty, and present values distinctly.

## 7. Tests
Fixtures with separate Screaming Frog internal/HTML and hreflang exports, multiple H1s, missing columns, duplicate titles, canonical pointing to redirected page, noindex URL in sitemap, hreflang reciprocal and missing reciprocal examples, new crawl that conflicts with previously proposed metadata. Test provenance, review states, warning accuracy, merge logic, migration safety, export, project isolation.

## Acceptance criteria
User can import Screaming Frog metadata files, inspect current metadata per page, manually record recommended H1/meta/canonical/robots/hreflang values, see accurate warnings, export an optimisation sheet, and retain all edits on later imports. Existing site architecture remains intact. No crawling or external connection needed.

## Handoff for Phase 4
Provide stable page profile API, import adapter patterns, provenance schema, and validation framework. Phase 4 adds **Semrush rankings/keyword metrics, GSC query-page performance, and optional GA4 landing-page metrics**, all mapped to these same page IDs.
