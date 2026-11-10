# Phase 2 — Sitemap, Visual Site Architecture & Page Routing

## Role and delivery instruction
You are continuing the **existing, running** SEO Data Workspace from Phase 1. Inspect the repository, schema, migrations, tests, and imports before coding. **Extend, do not rebuild**. Preserve previously imported pages and stable page IDs. Implement and test this phase completely; deliver working code and updated documentation.

## Product constraints
Local-first, no AI, no crawler, no cloud dependencies, no external APIs. Sources are manually entered data and imported files, especially **Screaming Frog exports** and user-provided sitemap XML. Do not claim that a sitemap reveals every internal link or that URL path hierarchy equals navigational hierarchy.

## Goal
Enable a user to create, import, edit, export, and visually explore a website sitemap and its **planned architecture**, linked to PLP, PDP, Editorial, and other page records.

## 1. Sitemap workspace
- Import **XML sitemaps and sitemap indexes from files**, including nested indexes provided as separate local files or ZIP archives. No automatic URL fetching. Show unresolved references requiring another local file.
- Validate XML structure and parse `<loc>`, optional `<lastmod>`, and sitemap-index relationships. Do not invent change frequency or priority values; treat them as legacy optional metadata if included.
- Create an **editable sitemap inclusion flag** on each page. Support bulk include/exclude, site/locale filtering, and validate that nominated sitemap URLs are expected canonical, eligible, and indexable when data is available. Flag unverified eligibility instead of assuming.
- Generate standards-compliant XML sitemap file(s) and sitemap index if necessary; enforce applicable sitemap URL/count/size limits, escaping, scope and absolute URL formatting. Export to local files without publishing to the website.
- Distinguish **Imported XML Sitemap**, **Proposed XML Sitemap**, and **Site Page Inventory**. They are not interchangeable.

## 2. Page routing & architecture
Add explicit `PageRelationship` entities with relationship type and direction:
- Primary parent/child (editorial taxonomy or navigation hierarchy)
- Breadcrumb parent (where applicable)
- Optional declared navigation/internal link relation (only if imported evidence exists)

Store one chosen primary parent per page where logical; detect cycles and orphans. Allow pages without parents. Do not automatically infer actual internal links from URL path alone. Offer heuristic **proposed parent** based on URL path and page type, with approve/override flow; show the evidence for each proposal.

Include page attributes: route/path, page type (PLP/PDP/Editorial/etc.), architecture section, depth (based on approved relationships), parent, inclusion status, and notes. Distinguish site path depth from hierarchy depth.

## 3. Visual sitemap
Build an interactive collapsible tree (or graph/tree toggle if feasible) driven by approved relationships. Features: expand/collapse, zoom/pan if diagram, select node to open page detail, search URL/title, filter by page type, colour/legend by PLP/PDP/Editorial, show orphan pages separately, export diagram as SVG/PNG if practical, and export adjacency list as CSV. Handle thousands of pages without trying to render the entire tree simultaneously (progressive expansion or virtualization).

## 4. Architecture quality checks
Flag, with explanatory labels:
- Orphan **in the manually defined hierarchy** (not proof of actual crawl orphan).
- Duplicate proposed parent assignments.
- Circular parent relationships.
- Unmapped/unknown page types.
- Sitemap-listed pages marked non-indexable or redirected when such data exists.
- Proposed sitemap URLs outside the project domain or malformed.
- Missing declared parent on deep PLP/PDP sections (heuristic only).

Do not confuse page routing with 301 redirects or assume URL location determines product category. No live link inspection.

## 5. Workspace and UI
Navigation: Dashboard, Pages, **Site Architecture**, Imports, Settings. Site Architecture subviews: Inventory / Sitemap XML / Hierarchy Map / Issues. Include counts, filters, node detail drawer, inline parent selection, bulk sitemap flag editing, and clear status indicators. Keep PLP/PDP/Editorial lists readily accessible within Pages.

## 6. Imports and merge behavior
Additional Screaming Frog site-structure or crawl exports may be imported via the Phase 1 adapter if columns are available. Only create actual link edges from explicit source/target link records, not from a generic URL list. On re-import, keep user-approved parent relationships and sitemap decisions unless the user explicitly requests a reset. Show conflicts as review items.

## 7. Data integrity and tests
Migrate existing DB without data loss. Test nested sitemap indexes (local bundle), malformed XML, duplicate locs, relative/absolute path handling, same URL appearing in sitemap and inventory, over-limit splitting, hierarchy cycles, orphans, bulk operations, preservation of approved parent relationships after re-import, and large-tree rendering strategy. Test generated XML parses and adheres to limits.

## Acceptance criteria
Users can import sitemap files, maintain a proposed sitemap, export valid XML, classify/organize pages, assign or approve parent relationships, view a fast interactive sitemap hierarchy, and see architecture warnings—all without network calls or AI. Phase 1 remains fully functional.

## Handoff for Phase 3
Document relationships between pages, sitemap membership, page type, and hierarchy; API endpoints and migration details. Next phase attaches imported/current SEO metadata and user-proposed metadata to each page.
