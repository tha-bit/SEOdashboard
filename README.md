# SEO Data Workspace

A local-first ecommerce SEO inventory, architecture, on-page, keyword-research and keyword-mapping application. It retains imported evidence and review decisions separately, from staged Screaming Frog/Semrush/GSC/GA4 files through approved target pages and cannibalization decisions. No crawler, AI service, account, cloud backend, live SEO-provider connection, or automatic website deployment is included.

## Run locally

Requirements: Python 3.11+ and Node.js 20+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install
npm --prefix frontend install
npm run dev
```

Open `http://127.0.0.1:5173`. After the one-time installation, the single root command is:

```bash
source .venv/bin/activate && npm run dev
```

The API binds to `127.0.0.1:8000`; Vite binds to `127.0.0.1:5173` and proxies `/api`. API documentation is at `http://127.0.0.1:8000/docs`.

### Run the app again after closing it

Open Terminal and run:

```bash
cd "/Users/user/Documents/Page Mapper"
source .venv/bin/activate && npm run dev
```

Keep that Terminal window open while using the app, then open `http://127.0.0.1:5173` in your browser. Your saved projects and data remain in `data/seo_workspace.db` between sessions.

- If you only closed the browser tab, the app may still be running. Open `http://127.0.0.1:5173` again; you do not need to rerun the command.
- If you closed Terminal or stopped the app, use the command above to restart it.
- To stop the app safely, return to its Terminal window and press `Ctrl+C`.

## Tests and production build

```bash
source .venv/bin/activate
python -m pytest -q
npm run build
```

Use `sample_data/screaming_frog_inventory.csv` to exercise duplicates, invalid URLs, path-case variants, redirects, 404s, non-indexable pages and classification values. Use `sample_data/screaming_frog_on_page.csv` and `sample_data/screaming_frog_hreflang.csv` to exercise current metadata, explicit empty values, multiple H1s, and separate repeated-row hreflang evidence. Phase 4 fixtures are `semrush_keyword_positions.csv`, `gsc_query_only.csv`, `gsc_query_page_performance.csv`, and `ga4_landing_pages.csv`.

## Database and migrations

SQLite data is stored at `data/seo_workspace.db`. The API creates a new database on first launch. The matching Alembic foundation migration is included:

```bash
alembic upgrade head
```

Core relationships:

- `Project 1—N Page`; `(project_id, normalized_url)` is unique.
- `Project 1—N ImportBatch 1—N ImportRow`; every raw source row is retained.
- `ImportRow.page_id` links a staged row to the stable Page record it created or observed.
- `Page.sitemap_included` is the nullable user decision for the proposed sitemap; imported XML membership remains separate evidence in `SitemapEntry`.
- `Project 1—N SitemapDocument 1—N SitemapEntry`; entries may link to the same stable Page and duplicate `<loc>` occurrences are preserved.
- `PageRelationship` stores directional `primary_parent`, `breadcrumb_parent`, or `declared_navigation` relations with proposed/approved status and evidence. Approved primary-parent relationships determine hierarchy depth.
- `PageMetadataObservation` stores immutable supplied-field snapshots linked to Page and ImportBatch; `PageMetadataRecommendation` and `PageMetadataChange` store manual proposals and their history separately.
- Later-phase tables remain reserved for metadata observations/recommendations, keywords, ranking observations, groups, target mappings and audit cases.
- Keywords are deliberately separate from pages; future ranking observations and target mappings are join records, so no keyword is coupled to only one URL.

Imported observations do not own Page identity or manual classification. A re-import updates supplied observation fields but does not overwrite an existing page type.

## Sitemap and Site Architecture

Open **Site Architecture** for four connected views:

- **Inventory** combines routes, page types, independent path/hierarchy depths, approved or proposed parents, imported XML occurrences, sitemap eligibility, and bulk proposed-sitemap decisions. Multi-select checkbox filters isolate indexable/non-indexable pages, successful/redirect/error responses, HTML/assets/other content, and URLs that are listed or absent from uploaded XML files. Columns can be shown, hidden, and drag-resized, with a browser-local layout retained per project.
- **Sitemap XML** imports local `.xml` files or `.zip` bundles. Sitemap indexes resolve only against supplied local files; missing references are reported and are never fetched. Imported XML, the proposed export set, and the general Page inventory remain distinct.
- **Hierarchy Map** opens with extendable directory accordions instead of small directory cards or one universal `/` tree. Each accordion lazily loads its approved relationships. A focused host/directory can be downloaded as a standalone SVG hierarchy map; selecting several directory maps downloads their SVG files together in a ZIP. URL-path proposals are explicitly labelled heuristics and can be approved individually, as a selected batch, or as the complete pending set; existing parents and cycle risks are skipped. Orphans mean only “no approved parent in this manually defined hierarchy.”
- **Issues** groups cycles, hierarchy orphans, unknown types, unresolved references, malformed/imported URL evidence, and sitemap eligibility concerns by issue type, with the affected pages and evidence nested beneath each issue. The same data is available as a categorized CSV download.

The primary **Issues** navigation page provides a project-wide review queue that combines Site Architecture and On-Page SEO findings. Source tabs show all issues together or isolate either workspace; category and priority use aligned multi-select checkbox filters alongside text search, while affected-page detail remains inside foldable issue groups. The Site Architecture and On-Page issue tabs use the same checkbox pattern for severity and status, and the Solution Log uses it for workflow stage. On-page findings are organized into Content metadata, Canonical & robots, Hreflang, and Metadata evidence categories. Affected URLs are clickable throughout the central queue, source-specific issue tabs, and solution log: architecture and central records open a shared inventory-and-crawl drawer, while On-Page records open the full metadata profile. Each issue also links back to the relevant source workspace, and the combined queue can be downloaded as one CSV.

Every issue can also receive append-only solution log entries. The Site Architecture form records sitemap decisions, hierarchy or parent changes, classifications, expected response/indexability outcomes, structural sections, and supporting evidence. The On-Page form records proposed H1, title and description values with character counts, canonical and robots decisions, hreflang plans, and expected validation results. Both forms retain workflow stage, owner, target date, summary, verification evidence, the issue snapshot, and relevant page metrics at the time of logging. The separate **Solution log** view and CSV remain reportable even when a later crawl causes the original issue to disappear. Project bundle download and restore retain the full history.

Generated sitemap XML uses absolute same-domain URLs, escapes XML values, and splits at 50,000 URLs or 50 MB uncompressed per file. Multiple output files are downloaded with a standards-compliant sitemap index inside a ZIP. Files are only exported locally; the app never publishes them. Optional imported `changefreq` and `priority` values are retained as legacy source evidence but are not invented or added to proposed exports.

Phase 2 API routes are scoped under `/api/projects/{project_id}/architecture`: `summary`, `inventory`, `sitemaps`, `relationships`, `tree`, `tree/export`, `issues`, `issues.csv`, and `adjacency.csv`. Migration `0003_sitemap_site_architecture.py` adds nullable Page planning fields, relationship review metadata, and sitemap document/entry tables without replacing Page IDs. Migration `0004_asset_page_type_backfill.py` adds no new table: it conservatively reclassifies only obvious CSS, JavaScript, image, audio, video, font, and WebAssembly resources from `Unknown` to the `Asset` page type.

The Pages workspace keeps Screaming Frog response evidence in separate fields and displays it in source order: `Content Type`, numeric `Status Code`, response-text `Status`, `Indexability`, and explanatory `Indexability Status`. For readability, the UI derives a supplementary content label such as `(HTML)` from the MIME value while preserving the original imported content type. It also displays the `Asset` classification and a separate `Imported Sitemap` column, so uploaded-XML membership remains evidence rather than being confused with the user's proposed-sitemap decision. Page-type and classification-status filters use multi-select checkboxes and carry into metric exports, URL-only downloads, and clipboard copying; selected rows limit the URL actions when a selection exists. Table columns can be shown, hidden, and resized from the header, with a browser-local layout retained per project. The redundant `Product Pages` classification has been retired; migration `0009_remove_product_pages_type.py` safely maps existing records and compatible legacy imports to `PDP` without deleting URLs. The dashboard reports the distinct number of pages found in imported sitemaps.

Re-imports preserve an existing Page classification, sitemap decisions, architecture notes, recommendations, and stable Page ID. Only mapped crawl fields that are actually supplied update the latest Page evidence. When a supplied value differs from the stored value, migration `0007_page_crawl_change_history.py` records the previous value, new value, import file, and observation time. Both the Page drawer and the On-Page SEO URL History tab present each changed metric with its before and after values; the separate import provenance list identifies supplied fields without implying that every field changed. Project bundle download/restore retains the full crawl change history.

## On-Page SEO metadata workspace

Open **On-Page SEO** for a stable per-Page metadata profile. The list distinguishes `Present`, `Empty`, and `Not collected`; page-type, issue-type, and recommendation-state filters use multi-select checkboxes. Its columns can be shown, hidden, and drag-resized, with a browser-local layout retained per project. Each profile connects the same Page identity to its approved architecture parent and imported/proposed sitemap evidence.

On desktop, the primary sidebar can be collapsed to an icon rail and expanded again. The preference is retained locally, and the main workspace automatically uses the released width; the existing mobile bottom navigation remains unchanged.

Confirmed Screaming Frog imports create immutable `PageMetadataObservation` rows only for fields that were actually supplied. Observations retain the import batch, file label, optional crawl/report date, source columns, original values, and observation timestamp. Multiple files can contribute different latest fields; separate hreflang exports are aggregated from repeated source-page rows. A missing source column remains unknown, while a supplied empty cell remains explicitly empty.

`PageMetadataRecommendation` stores manual H1, title, description, canonical, robots, X-Robots and hreflang recommendations separately from imports. Review states are `draft`, `review`, `approved`, and manually confirmed `implemented`; none imply live deployment. Every save writes a `PageMetadataChange` history record, and later imports never overwrite recommendations.

Deterministic rules flag missing/multiple H1 evidence, empty and duplicate snippets, configurable length guidance, canonical target problems, noindex/sitemap conflicts, robots/indexability contradictions, hreflang format/target/self/reciprocal concerns, and uncollected expected fields. Issues use Info, Review, or High severity and can be dismissed or resolved only with a recorded reason. `nofollow` is not treated as a blanket indexing prohibition. The optimisation CSV exports current-versus-recommended values, review state, architecture/sitemap context, and issue types.

Phase 3 API routes are scoped under `/api/projects/{project_id}/on-page`: `summary`, `pages`, page `recommendation`, `issues`, `settings`, and `export`. Project-wide issue routes add the combined `issues`, `issues.csv`, append-only `issue-solutions`, and `issue-solutions.csv` reporting surfaces. Migration `0005_on_page_metadata_workspace.py` extends the reserved metadata and audit tables and adds recommendation history without changing Page IDs or approved architecture; migration `0008_issue_solution_history.py` adds durable solution logs for both issue sources.

## Keyword research and opportunity scoring

Open **Keyword Research** to compare uploaded Semrush, Google Search Console and optional GA4 exports. The explorer uses the same multi-select checkbox filters, one-open-filter behaviour, resizable columns and browser-local column preferences as the Pages workspace. It shows each unique keyword once for its market/language scope while retaining every observed ranking URL underneath it. The detail drawer separates Semrush rankings, Semrush volume/KD/intent snapshots, GSC query or query × page performance, and GA4 landing-page context into dated history tabs.

All Phase 4 imports use the existing preview, flexible column mapping and final-confirmation workflow. Semrush positions can exist without a URL and multiple URLs can rank for the same keyword. GSC query-only files never create query-to-page links; query-only and query × page periods are not blended. GA4 attaches to matched Pages through configurable project URL normalization and does not create keyword mappings. Sessions are only described as organic when the uploaded channel dimension says so. Raw rows, normalized joins, source files, periods, market and device dimensions remain auditable, and repeated imports append observations instead of overwriting history.

The default 0–100 opportunity model weights traffic potential 30%, intent 30%, ranking feasibility 25%, and manually reviewed product relevance 15%. Traffic uses logarithmic normalization within the current project scope. Rank and KD feasibility is explicitly heuristic; Semrush position is not blended with GSC average position. Missing components are excluded and remaining weights are normalized, so the UI marks the score provisional rather than silently treating missing data as zero or maximum relevance. Component weights and intent scores are editable per project, and each keyword explains the values and weights used.

Phase 4 API routes live under `/api/projects/{project_id}/keywords`: explorer rows, summary, settings, per-keyword evidence/history, relevance review, page opportunities, and CSV export. Migration `0010_keyword_research_opportunity.py` expands the reserved Keyword and RankingObservation records and adds source-specific keyword metrics, GSC performance and GA4 page-performance tables. Project bundle download/restore and permanent project deletion include these records.

## Keyword mapping and cannibalization review

Phase 5 adds three connected workspaces. **Keyword Groups** creates deterministic suggestions from normalized terms, configured synonym handling and intent families; informational modifiers remain separate from commercial groups. Suggestions include reason codes and require approval. **Page Mapping** proposes targets from the latest comparable Semrush ranking observations but always keeps observed URLs separate from intended targets. A reviewer can approve an existing inventory Page or save a planned URL. Approved groups and targets are never overwritten by later Semrush imports. **Cannibalization Audit** detects exact-query multi-URL observations only within a comparable provider/market/device/date/import scope, plus mismatches between current ranking evidence and an approved target. These are review signals—not automatic proof of harmful cannibalization.

All three lists use aligned checkbox filters, one-open-filter behaviour, resizable columns, configurable visibility and browser-local layouts. Group approvals support batch selection. Drawers expose members, evidence, reason codes, target rationale and append-only review history. Cannibalization decisions record status, action, preferred URL, reviewer and notes; changed evidence reopens a previously closed case. Keyword-map, page-map, audit and review-queue CSVs are available, and the dashboard links to the current mapping workload.

Phase 5 routes live under `/api/projects/{project_id}/strategy`: summary, deterministic suggestion generation, groups/memberships, target approval, review history, cannibalization scan/cases/decisions and CSV exports. Migration `0011_keyword_mapping_cannibalization.py` adds topic clusters, memberships, suggestions, targets, cases, evidence, decisions and review history. Project bundles retain all of these records with remapped IDs.

## URL identity rules

URL identity is not an SEO canonical tag. It lowercases scheme/host, removes fragments and default ports, sorts query parameters, removes configured tracking parameters, and can remove non-root trailing slashes. Path casing and non-tracking query values are preserved because they may identify distinct resources. Ambiguous identities return conflicts or staged duplicate statuses rather than silently merging records.

Project preferences control trailing slash and tracking-parameter behavior. Changing these rules affects future imports only; Phase 1 does not automatically rewrite existing identities.

## Import adapter contract

An adapter stages bytes into `ImportBatch` and immutable `ImportRow.raw_data`, reports detected columns/format, suggests semantic mappings, then validates and commits Pages transactionally on confirmation. Phase 1 implements:

- `screaming_frog`: Address/URL, status, indexability, content type, URL path and optional page type.
- `url_list`: CSV/XLSX with a mapped URL column and optional type.

All unmapped columns stay in `raw_data`. GSC, GA4 and Semrush are file-import adapters with preview and final confirmation; there are no fake live integrations.

The Screaming Frog adapter recognizes the initial SEO vocabulary documented in `screaming_frog_main_seo_columns.md`, including repeated H1 columns, titles/descriptions and optional metrics, robots and X-Robots directives, canonical evidence, crawl dates, response/indexability evidence, and separate `From`/`Hreflang`/`To` exports. Exact known aliases are labeled as exact. Case, spacing or close spelling variants are suggestions only: the import is blocked until the user reviews them and checks the header-verification confirmation. A separate final confirmation is always required before staged rows create Pages or metadata observations.

## Back up and restore

Download a consistent backup from Settings or run:

```bash
source .venv/bin/activate
python -m backend.backup backup backups/my-backup.db
```

Stop the app before restoring. The restore command checks SQLite integrity and expected tables, then preserves the current database beside it before replacement:

```bash
source .venv/bin/activate
python -m backend.backup restore backups/my-backup.db
```

For one-project portability, use **Projects → Download** or **Settings → Download this project**. The resulting `.seo-project.json` bundle contains project preferences, Pages, sitemap decisions and evidence, page relationships, import batches, mappings, warnings, and raw audit rows. Upload it from Projects or Settings to create a new active project with safely remapped IDs; it does not overwrite projects already in the database. The Projects tab lists active and archived projects and supports restore, archive, download, and typed-confirmation permanent deletion.

## Current limitations

- Page-type inference is intentionally narrow: obvious asset MIME types and extensions become `Asset`; other blank or ambiguous values remain `Unknown` until imported or edited. PDFs are not automatically treated as assets because they may be indexable sitemap candidates.
- Import preview samples ten rows; the full source is staged and audited. The UI displays the first six columns, while all columns are preserved.
- XLSX export is available from the API via `pages-export?format=xlsx`; the current UI shortcut downloads CSV.
- Project locale/market and identity preferences persist; only name and identity rules are editable in the current Settings UI.
- Restore is intentionally a stop-the-process CLI operation to avoid replacing an open SQLite file.
- Sitemap imports are local files only; the app intentionally does not fetch referenced sitemap URLs or publish generated files.
- Hierarchy maps use progressive tree expansion. SVG exports are generated per selected host/directory scope; multi-map downloads are packaged as a ZIP so the interface never has to render an entire large site at once.
- Generic URL inventory imports never create internal-link or navigation edges. Only user declarations and explicitly reviewed parent proposals are stored; future explicit source/target crawl adapters may add evidence-backed relationships.
- Metadata is imported only from supplied local files; the app does not crawl pages, verify deployment, or fetch canonical/hreflang targets.
- Hreflang reciprocal checks run only when both known pages have supplied hreflang evidence; absent evidence is not treated as proof of a missing live tag.
- Phase 4 can attach Semrush rankings, GSC query-page performance, and optional GA4 landing-page metrics to the same stable Page profile and import provenance patterns.
- Keyword grouping and target proposals are deterministic aids, not semantic or SERP-equivalence guarantees. Reviewers must approve strategy decisions, and the app does not edit the live site, redirects, canonicals or internal links.
