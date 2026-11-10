# Phase 1 — Application Foundation & Site Inventory

## Role and delivery instruction
You are a senior full-stack engineer, data architect, and ecommerce technical SEO specialist. **Implement** Phase 1 of a working application named **SEO Data Workspace**, not a mockup. This is the first phase of five. Do not implement later phases prematurely, but prepare the database for them. Deliver runnable source code, migrations, tests, sample import files, and precise setup instructions.

## Non-negotiable product decisions
- **Local-first; no AI model, AI API, cloud backend, SEO API, or mandatory network access.** The app runs on the user's machine and opens in their browser.
- **Import-only data acquisition**: users import exports from **Screaming Frog, Google Search Console (GSC), Google Analytics 4 (GA4), and Semrush**. **Do not build a website crawler, live integrations, authentication flows to those tools, or scheduled fetch jobs.** A sample-file adapter can be used for testing, not live fetching.
- English-language UI, professional and intuitive for an SEO specialist; designed for thousands of pages and keyword–URL observations.
- Never silently delete imported records, overwrite user decisions, or fabricate fields absent from source files.
- Use a central **Page entity** as the shared key across future sitemap, metadata, keyword, and cannibalization workflows.

## Architecture and technology
Preferred stack: React + TypeScript + Vite, Tailwind CSS, TanStack Table, Python + FastAPI, SQLite + SQLAlchemy + Alembic, pandas/openpyxl for import/export, and Recharts where useful. Use compatible, maintained library versions; document alternatives if necessary. Organize modules by domain, not one giant component or service. Bind backend to `127.0.0.1` by default and document how to run frontend and backend. Provide database backup and restore procedures.

## Scope for this phase
### 1. Project and site configuration
Support one or multiple projects, each with site/domain, optional locale/market, and reporting defaults. Persist configuration in SQLite. Scope all records by project. Provide create/rename/archive project operations.

### 2. Canonical page inventory (not canonical tags)
Create `Page` records with stable IDs, project ID, original URL, normalized URL identity, page type, status, source, and timestamps. Support these page types: Homepage, PLP (category/listing), PDP (product detail), Editorial, Brand, Landing, Other, Unknown. Provide bulk reclassification. Store URL identity separately from the *SEO canonical URL* field which comes in Phase 3. Treat path casing conservatively; normalize harmless differences such as URL fragments, optionally trailing slashes and tracking parameters according to documented project settings. Do not merge potentially distinct URLs without review.

### 3. File imports and provenance
Implement reusable CSV/XLSX import pipeline with:
- Upload → preview → map columns → validate → resolve duplicates → confirm → import report.
- Delimiter/encoding handling, sample rows, source preset selector, data-type conversion, timezone/reporting-period prompts where relevant.
- Store `ImportBatch` with file name, source, checksum, import time, reporting date/period, row counts, mapping configuration, and warnings.
- Preserve raw source rows (or import staging records) so imports can be audited. Transactional writes; clear row-level errors and safe rollback.
- **Phase 1 implemented source: Screaming Frog URL inventory exports**, including exports that contain Address/URL, status code, indexability, content type, and URL path (when provided). Import additional fields as staged/unmapped data for future phases; don't discard them.
- Allow basic **manual URL entry**, CSV URL list import, and XLSX URL list import.
- Treat GSC, GA4, Semrush as **planned import adapters**; establish stable import interface and sample mapping definitions, but do not claim these integrations are functional before their implementation in later phases.

### 4. Pages workspace
Searchable/filterable/sortable/paginated table: URL, page type, indexability if provided, HTTP status if provided, import source, last observed date. Multi-select, bulk page-type edit, page details panel, clear source provenance, export current filter results. Provide a separate tab/list view for PLP, PDP, Editorial (and All Pages) using filters, not duplicated records.

### 5. Initial dashboard and navigation
Sidebar: Dashboard, Pages, Imports, Settings; hide or clearly mark future modules as unavailable. Dashboard: total unique pages, counts by page type, imported pages, unknown types, latest import, import warnings. Dashboard must calculate real values, not hardcoded figures. Preserve a simple top navigation with project selector and hyperlinks to each area.

## Data architecture that MUST anticipate future phases
Separate entities/tables or clean schemas for `Project`, `Page`, `ImportBatch`, `ImportRow` or equivalent staging; prepare migrations for `PageRelationship`, `PageMetadataObservation`, `PageMetadataRecommendation`, `Keyword`, `RankingObservation`, `KeywordGroup`, `TargetMapping`, and `AuditCase` **without exposing imaginary functionality**. Stable IDs must survive future imports and re-imports; imported records must not be the sole source of truth for edited data. Document database relationships and uniqueness assumptions. Avoid coupling a keyword to one URL only.

## UX and operational requirements
Editable fields clearly distinguished from imported or computed fields. Freeze relevant table columns, sensible empty/loading/error states, keyboard-accessible controls, responsive widths, export CSV/XLSX, and durable project preferences. Provide concise in-app import guidance. No fake charts or hard-coded SEO performance numbers.

## Tests and required fixtures
Create representative Screaming Frog-style exports with PLP, PDP, Editorial pages; variants of URLs, duplicates, blank type, 301/404 URLs, and non-indexable pages. Test import validation, source preservation, duplicate handling, URL normalization without unsafe merges, project isolation, persistence, exports, and basic navigation. Run tests and report results; fix failures.

## Acceptance criteria
A user can create a project, import a Screaming Frog URL export (or URL CSV/XLSX), map columns, review errors, preserve/import unique page records, filter PLP/PDP/Editorial pages, bulk classify, export pages, quit/reopen without loss, and restore a backup. No AI, crawler, or external tool connection is needed.

## Handoff for Phase 2
Provide current database schema, import adapter contract, URL identity rules, test commands, implementation notes, and explicit known limitations. Phase 2 will add sitemap and site architecture using these same pages.
