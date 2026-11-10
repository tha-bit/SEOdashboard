# SEO Data Workspace — Five Core Development Prompts

These five Markdown prompts are designed for **sequential use** with an AI coding tool. They describe a local-first ecommerce **on-page SEO strategy** application—not a spreadsheet.

## Data sources
- **Screaming Frog exports**: page inventory, status, on-page metadata, canonicals, robots, hreflang, and (where available) structural evidence.
- **Semrush exports**: keyword volume, difficulty, search intent, ranking position and ranking URL.
- **Google Search Console exports**: query and query–page clicks, impressions, CTR and average position.
- **Google Analytics 4 exports**: optional landing-page organic sessions and other page-level performance fields (only if included in the export).

No website crawler, AI connection, mandatory SEO provider API, or cloud service is required.

## Sequence
1. `01_foundation_site_inventory.md` — project setup, database, imports, URL/page inventory and PLP/PDP/Editorial lists.
2. `02_sitemap_site_architecture.md` — XML sitemap import/export, page routing, visual site architecture.
3. `03_on_page_seo_management.md` — current versus proposed metadata, Screaming Frog import, on-page validation.
4. `04_keyword_research_opportunity_scoring.md` — Semrush, GSC and GA4 file imports, keyword metrics, opportunity scoring.
5. `05_keyword_mapping_cannibalization.md` — rule-based grouping, URL mapping, multi-URL query detection and review.

## How to use
Paste **only the first phase** into your coding tool inside a persistent repository. After building, run the app and its tests with sample/real exports. Then paste the next phase **in the same project**. Never start a new app for each phase.

The prompts explicitly separate imported evidence, rule-based suggestions and manually approved SEO decisions. They also prevent duplicate keyword–URL rows from being mistaken for duplicate keyword opportunities and distinguish overlap warnings from confirmed cannibalization.
