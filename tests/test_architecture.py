import csv
import io
import zipfile
from xml.etree import ElementTree as ET

import pytest
from fastapi import HTTPException

from backend.services.sitemaps import MAX_URLS, generate_sitemap_files


NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def add_page(client, project_id: str, path: str, page_type: str = "Unknown"):
    response = client.post(
        f"/api/projects/{project_id}/pages",
        json={"url": f"https://shop.example.com{path}", "page_type": page_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_local_nested_sitemap_bundle_preserves_duplicates_and_matches_inventory(client, project):
    existing = add_page(client, project["id"], "/products", "PLP")
    index = f'''<?xml version="1.0"?>
    <sitemapindex xmlns="{NS}"><sitemap><loc>https://shop.example.com/maps/products.xml</loc></sitemap><sitemap><loc>https://shop.example.com/maps/missing.xml</loc></sitemap></sitemapindex>'''.encode()
    urls = f'''<?xml version="1.0"?>
    <urlset xmlns="{NS}">
      <url><loc>https://shop.example.com/products</loc><lastmod>2026-11-01</lastmod></url>
      <url><loc>https://shop.example.com/products</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
      <url><loc>https://shop.example.com/products/boot</loc><lastmod>not-a-date</lastmod></url>
    </urlset>'''.encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("maps/index.xml", index)
        bundle.writestr("maps/products.xml", urls)

    response = client.post(
        f"/api/projects/{project['id']}/architecture/sitemaps/import",
        files=[("files", ("sitemaps.zip", archive.getvalue(), "application/zip"))],
    )
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["documents"] == 2
    assert report["entries"] == 3
    assert report["matched_pages"] == 2
    assert report["created_pages"] == 1
    assert report["duplicate_locs"] == 1
    assert report["unresolved_references"] == ["https://shop.example.com/maps/missing.xml"]

    inventory = client.get(f"/api/projects/{project['id']}/architecture/inventory?page_size=100").json()
    matched = next(item for item in inventory["items"] if item["id"] == existing["id"])
    assert matched["imported_sitemap_occurrences"] == 2
    assert matched["sitemap_included"] is None
    detail = client.get(f"/api/projects/{project['id']}/pages/{existing['id']}").json()
    assert detail["in_imported_sitemap"] is True
    assert detail["imported_sitemap_occurrences"] == 2
    issues = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    assert any(issue["type"] == "unresolved_sitemap_reference" for issue in issues)
    assert any("lastmod" in issue["detail"] for issue in issues)


def test_technical_issue_rules_priority_override_and_sitemap_removal(client, project):
    canonical = add_page(client, project["id"], "/preferred", "PLP")
    page = add_page(client, project["id"], "/legacy", "PDP")
    assert client.patch(
        f"/api/projects/{project['id']}/pages/{canonical['id']}/manual-overrides",
        json={"values": {"http_status": 200, "indexability": "Indexable", "content_type": "text/html", "canonical_url": canonical["original_url"]}},
    ).status_code == 200
    assert client.patch(
        f"/api/projects/{project['id']}/pages/{page['id']}/manual-overrides",
        json={"values": {"http_status": 302, "indexability": "Indexable", "content_type": "text/html", "canonical_url": canonical["original_url"], "redirect_uri": canonical["original_url"]}},
    ).status_code == 200

    sitemap = f'<urlset xmlns="{NS}"><url><loc>{page["original_url"]}</loc></url></urlset>'.encode()
    imported = client.post(
        f"/api/projects/{project['id']}/architecture/sitemaps/import",
        files=[("files", ("legacy.xml", sitemap, "application/xml"))],
    )
    assert imported.status_code == 201, imported.text
    issues = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    issue_types = {item["type"] for item in issues if item.get("page_id") == page["id"]}
    assert {"redirect_302", "indexable_non_canonical", "sitemap_non_canonical"} <= issue_types
    sitemap_issue = next(item for item in client.get(f"/api/projects/{project['id']}/issues").json() if item["type"] == "sitemap_non_canonical")
    assert sitemap_issue["priority"] == "high"
    changed = client.patch(
        f"/api/projects/{project['id']}/issues/{sitemap_issue['issue_key']}/priority",
        json={"priority": "low"},
    )
    assert changed.status_code == 200, changed.text
    refreshed = next(item for item in client.get(f"/api/projects/{project['id']}/issues").json() if item["issue_key"] == sitemap_issue["issue_key"])
    assert refreshed["priority"] == "low"

    documents = client.get(f"/api/projects/{project['id']}/architecture/sitemaps").json()
    removed = client.delete(f"/api/projects/{project['id']}/architecture/sitemaps/{documents[0]['id']}")
    assert removed.status_code == 200
    assert removed.json()["entries_removed"] == 1
    assert client.get(f"/api/projects/{project['id']}/architecture/sitemaps").json() == []
    assert client.get(f"/api/projects/{project['id']}/pages/{page['id']}").status_code == 200


def test_issue_priority_catalog_defaults_and_page_override_precedence(client, project):
    page = add_page(client, project["id"], "/priority-review", "Unknown")
    settings_url = f"/api/projects/{project['id']}/issues/priority-settings"
    settings = client.get(settings_url)
    assert settings.status_code == 200, settings.text
    rows = settings.json()
    assert {row["source"] for row in rows} == {"site_architecture", "on_page"}
    assert next(row for row in rows if row["source"] == "site_architecture" and row["type"] == "http_5xx")["priority"] == "critical"

    changed = client.patch(f"{settings_url}/site_architecture/unknown_page_type", json={"priority": "critical"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["customized"] is True
    issue = next(item for item in client.get(f"/api/projects/{project['id']}/architecture/issues").json() if item["type"] == "unknown_page_type" and item["page_id"] == page["id"])
    assert issue["priority"] == "critical"
    central = next(item for item in client.get(f"/api/projects/{project['id']}/issues").json() if item["issue_key"] == issue["issue_key"])
    assert central["priority"] == "critical"

    override = client.patch(f"/api/projects/{project['id']}/issues/{issue['issue_key']}/priority", json={"priority": "low"})
    assert override.status_code == 200, override.text
    assert client.patch(f"{settings_url}/site_architecture/unknown_page_type", json={"priority": "high"}).status_code == 200
    issue_after_default_change = next(item for item in client.get(f"/api/projects/{project['id']}/architecture/issues").json() if item["issue_key"] == issue["issue_key"])
    assert issue_after_default_change["priority"] == "low"

    reset = client.delete(settings_url)
    assert reset.status_code == 200, reset.text
    restored = next(row for row in client.get(settings_url).json() if row["source"] == "site_architecture" and row["type"] == "unknown_page_type")
    assert restored["priority"] == "medium"
    assert restored["customized"] is False
    preserved_override = next(item for item in client.get(f"/api/projects/{project['id']}/architecture/issues").json() if item["issue_key"] == issue["issue_key"])
    assert preserved_override["priority"] == "low"


def test_issue_type_enable_disable_toggle(client, project):
    page = add_page(client, project["id"], "/disable-review", "Unknown")
    settings_url = f"/api/projects/{project['id']}/issues/priority-settings"
    issues_url = f"/api/projects/{project['id']}/issues"

    # Verify initial active state
    settings = client.get(settings_url).json()
    unknown_type = next(row for row in settings if row["source"] == "site_architecture" and row["type"] == "unknown_page_type")
    assert unknown_type["disabled"] is False

    initial_issues = client.get(issues_url).json()
    assert any(item["type"] == "unknown_page_type" and item["page_id"] == page["id"] for item in initial_issues)

    # Disable the issue type
    disabled_resp = client.patch(f"{settings_url}/site_architecture/unknown_page_type", json={"disabled": True})
    assert disabled_resp.status_code == 200, disabled_resp.text
    assert disabled_resp.json()["disabled"] is True

    # Check settings reflects disabled
    updated_settings = client.get(settings_url).json()
    assert next(row for row in updated_settings if row["source"] == "site_architecture" and row["type"] == "unknown_page_type")["disabled"] is True

    # Issue must now be excluded from detection
    issues_after_disable = client.get(issues_url).json()
    assert not any(item["type"] == "unknown_page_type" and item["page_id"] == page["id"] for item in issues_after_disable)

    # Re-enable the issue type
    enabled_resp = client.patch(f"{settings_url}/site_architecture/unknown_page_type", json={"disabled": False})
    assert enabled_resp.status_code == 200, enabled_resp.text
    assert enabled_resp.json()["disabled"] is False

    # Issue is detected again
    issues_after_enable = client.get(issues_url).json()
    assert any(item["type"] == "unknown_page_type" and item["page_id"] == page["id"] for item in issues_after_enable)


def test_malformed_xml_is_rejected(client, project):
    response = client.post(
        f"/api/projects/{project['id']}/architecture/sitemaps/import",
        files=[("files", ("broken.xml", b"<urlset><url>", "application/xml"))],
    )
    assert response.status_code == 422
    assert "Malformed XML" in response.json()["detail"]


def test_sitemap_generation_splits_and_uses_absolute_index_locations():
    urls = [f"https://shop.example.com/item-{number}" for number in range(5)]
    files = generate_sitemap_files(urls, max_urls=2, index_base_url="https://shop.example.com/sitemaps/")
    assert set(files) == {"sitemap-index.xml", "sitemap-1.xml", "sitemap-2.xml", "sitemap-3.xml"}
    index = ET.fromstring(files["sitemap-index.xml"])
    locations = [node.text for node in index.findall(f"{{{NS}}}sitemap/{{{NS}}}loc")]
    assert locations == [
        "https://shop.example.com/sitemaps/sitemap-1.xml",
        "https://shop.example.com/sitemaps/sitemap-2.xml",
        "https://shop.example.com/sitemaps/sitemap-3.xml",
    ]
    emitted = []
    for name, content in files.items():
        if name == "sitemap-index.xml":
            continue
        root = ET.fromstring(content)
        part = [node.text for node in root.findall(f"{{{NS}}}url/{{{NS}}}loc")]
        assert len(part) <= 2
        emitted.extend(part)
    assert emitted == urls
    assert MAX_URLS == 50_000
    with pytest.raises(HTTPException):
        generate_sitemap_files(["https://shop.example.com/a-very-long-route"], max_bytes=20)


def test_bulk_sitemap_decisions_export_valid_xml_and_flag_unverified(client, project):
    first = add_page(client, project["id"], "/one", "Editorial")
    second = add_page(client, project["id"], "/two", "PDP")
    endpoint = f"/api/projects/{project['id']}/architecture/inventory/bulk-sitemap"
    response = client.patch(endpoint, json={"page_ids": [first["id"], second["id"]], "included": True})
    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert len(response.json()["review_issues"]) == 2

    exported = client.get(f"/api/projects/{project['id']}/architecture/sitemaps/export")
    assert exported.status_code == 200
    root = ET.fromstring(exported.content)
    assert root.tag == f"{{{NS}}}urlset"
    assert {node.text for node in root.findall(f"{{{NS}}}url/{{{NS}}}loc")} == {
        "https://shop.example.com/one", "https://shop.example.com/two"
    }

    reset = client.patch(endpoint, json={"page_ids": [second["id"]], "included": None})
    assert reset.status_code == 200
    inventory = client.get(f"/api/projects/{project['id']}/architecture/inventory?inclusion=unreviewed").json()
    assert any(item["id"] == second["id"] for item in inventory["items"])


def test_relationship_proposals_cycles_orphans_and_progressive_tree(client, project):
    root = add_page(client, project["id"], "/", "Homepage")
    category = add_page(client, project["id"], "/shoes", "PLP")
    product = add_page(client, project["id"], "/shoes/boot", "PDP")
    orphan = add_page(client, project["id"], "/editorial/story", "Editorial")

    proposed = client.post(f"/api/projects/{project['id']}/architecture/relationships/propose")
    assert proposed.status_code == 200
    proposals = client.get(f"/api/projects/{project['id']}/architecture/relationships/proposals").json()
    product_proposal = next(item for item in proposals if item["child_id"] == product["id"])
    assert product_proposal["parent_id"] == category["id"]
    assert product_proposal["evidence"]["method"] == "url_path_prefix"
    assert "heuristic" in product_proposal["evidence"]["warning"]
    assert client.post(f"/api/projects/{project['id']}/architecture/relationships/{product_proposal['id']}/approve").status_code == 200

    parent_payload = {"parent_page_id": root["id"], "child_page_id": category["id"], "relationship_type": "primary_parent", "status": "approved"}
    assert client.post(f"/api/projects/{project['id']}/architecture/relationships", json=parent_payload).status_code == 201
    cycle_payload = {"parent_page_id": product["id"], "child_page_id": root["id"], "relationship_type": "primary_parent", "status": "approved"}
    cycle = client.post(f"/api/projects/{project['id']}/architecture/relationships", json=cycle_payload)
    assert cycle.status_code == 422
    assert "circular" in cycle.json()["detail"]

    roots = client.get(f"/api/projects/{project['id']}/architecture/tree").json()
    assert [item["id"] for item in roots] == [root["id"]]
    assert roots[0]["child_count"] == 1
    first_level = client.get(f"/api/projects/{project['id']}/architecture/tree?parent_id={root['id']}").json()
    assert [item["id"] for item in first_level] == [category["id"]]
    sections = client.get(f"/api/projects/{project['id']}/architecture/tree?mode=sections").json()
    assert [item["id"] for item in sections] == [category["id"]]
    scopes = client.get(f"/api/projects/{project['id']}/architecture/tree/scopes").json()
    assert any(item["path_prefix"] == "/shoes" and item["page_count"] == 2 for item in scopes)
    shoe_scope = next(item["value"] for item in scopes if item["path_prefix"] == "/shoes")
    scoped = client.get(f"/api/projects/{project['id']}/architecture/tree", params={"scope": shoe_scope}).json()
    assert [item["id"] for item in scoped] == [category["id"]]
    orphans = client.get(f"/api/projects/{project['id']}/architecture/tree?orphans=true").json()
    assert any(item["id"] == orphan["id"] for item in orphans)


def test_bulk_approval_handles_complete_proposal_set_and_keeps_hosts_separate(client, project):
    root = add_page(client, project["id"], "/", "Homepage")
    section = add_page(client, project["id"], "/phones", "PLP")
    item = add_page(client, project["id"], "/phones/model", "PDP")
    other_root = client.post(
        f"/api/projects/{project['id']}/pages",
        json={"url": "https://support.example.com/", "page_type": "Homepage"},
    ).json()
    other_child = client.post(
        f"/api/projects/{project['id']}/pages",
        json={"url": "https://support.example.com/help", "page_type": "Editorial"},
    ).json()
    generated = client.post(f"/api/projects/{project['id']}/architecture/relationships/propose")
    assert generated.status_code == 200
    assert generated.json()["proposals_created"] == 3
    proposals = client.get(f"/api/projects/{project['id']}/architecture/relationships/proposals?limit=100").json()
    by_child = {proposal["child_id"]: proposal for proposal in proposals}
    assert by_child[section["id"]]["parent_id"] == root["id"]
    assert by_child[item["id"]]["parent_id"] == section["id"]
    assert by_child[other_child["id"]]["parent_id"] == other_root["id"]

    approved = client.post(
        f"/api/projects/{project['id']}/architecture/relationships/proposals/approve-bulk",
        json={"approve_all": True, "relationship_ids": []},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json() == {"requested": 3, "approved": 3, "skipped_existing_parent": 0, "skipped_cycles": 0}
    assert client.get(f"/api/projects/{project['id']}/architecture/relationships/proposals/stats").json()["total"] == 0
    sections_view = client.get(f"/api/projects/{project['id']}/architecture/tree?mode=sections").json()
    assert {node["id"] for node in sections_view} == {section["id"], other_child["id"]}


def test_phase_one_reimport_preserves_approved_parent_and_sitemap_decision(client, project):
    parent = add_page(client, project["id"], "/catalog", "PLP")
    child = add_page(client, project["id"], "/catalog/item", "PDP")
    relationship = client.post(
        f"/api/projects/{project['id']}/architecture/relationships",
        json={"parent_page_id": parent["id"], "child_page_id": child["id"], "relationship_type": "primary_parent", "status": "approved"},
    )
    assert relationship.status_code == 201
    client.patch(
        f"/api/projects/{project['id']}/architecture/inventory/bulk-sitemap",
        json={"page_ids": [child["id"]], "included": True},
    )
    csv_data = b"Address,Status Code,Status,Indexability,Indexability Status\nhttps://shop.example.com/catalog/item,200,OK,Indexable,\n"
    staged = client.post(
        f"/api/projects/{project['id']}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": ("reimport.csv", csv_data, "text/csv")},
    ).json()
    confirmed = client.post(
        f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/confirm",
        json={"mapping": staged["suggested_mapping"]},
    )
    assert confirmed.status_code == 200
    inventory = client.get(f"/api/projects/{project['id']}/architecture/inventory?page_size=100").json()
    item = next(item for item in inventory["items"] if item["id"] == child["id"])
    assert item["parent_id"] == parent["id"]
    assert item["sitemap_included"] is True
    assert item["http_status"] == 200


def test_project_bundle_round_trip_includes_phase_two_records(client, project):
    parent = add_page(client, project["id"], "/section", "PLP")
    child = add_page(client, project["id"], "/section/item", "PDP")
    client.patch(f"/api/projects/{project['id']}/architecture/inventory/{child['id']}", json={"architecture_section": "Shop", "architecture_notes": "Primary item"})
    client.patch(f"/api/projects/{project['id']}/architecture/inventory/bulk-sitemap", json={"page_ids": [child["id"]], "included": True})
    client.post(f"/api/projects/{project['id']}/architecture/relationships", json={"parent_page_id": parent["id"], "child_page_id": child["id"], "relationship_type": "primary_parent", "status": "approved"})
    sitemap = f'<urlset xmlns="{NS}"><url><loc>https://shop.example.com/section/item</loc></url></urlset>'.encode()
    client.post(f"/api/projects/{project['id']}/architecture/sitemaps/import", files=[("files", ("sitemap.xml", sitemap, "application/xml"))])

    downloaded = client.get(f"/api/projects/{project['id']}/export")
    bundle = downloaded.json()
    assert len(bundle["page_relationships"]) == 1
    assert len(bundle["sitemap_documents"]) == 1
    assert len(bundle["sitemap_entries"]) == 1
    restored_response = client.post("/api/projects/import", files={"file": ("restored.seo-project.json", downloaded.content, "application/json")})
    assert restored_response.status_code == 201, restored_response.text
    restored = restored_response.json()
    inventory = client.get(f"/api/projects/{restored['id']}/architecture/inventory?page_size=100").json()
    restored_child = next(item for item in inventory["items"] if item["route"] == "/section/item")
    assert restored_child["section"] == "Shop"
    assert restored_child["notes"] == "Primary item"
    assert restored_child["sitemap_included"] is True
    assert restored_child["parent_url"].endswith("/section")
    assert restored_child["imported_sitemap_occurrences"] == 1


def test_sitemap_inventory_filters_asset_type_and_imported_membership(client, project):
    csv_data = b"""Address,Content Type,Status Code,Status,Indexability,Indexability Status
https://shop.example.com/good,text/html; charset=utf-8,200,OK,Indexable,
https://shop.example.com/private,text/html; charset=utf-8,200,OK,Non-Indexable,noindex
https://shop.example.com/old,text/html; charset=utf-8,301,Moved Permanently,Non-Indexable,Redirected
https://shop.example.com/assets/site.css,text/css,200,OK,Non-Indexable,Non-HTML
https://shop.example.com/images/logo.svg,image/svg+xml,200,OK,Non-Indexable,Non-HTML
"""
    staged_response = client.post(
        f"/api/projects/{project['id']}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": ("sitemap-filter.csv", csv_data, "text/csv")},
    )
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    confirmed = client.post(
        f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/confirm",
        json={"mapping": staged["suggested_mapping"]},
    )
    assert confirmed.status_code == 200, confirmed.text

    pages = client.get(f"/api/projects/{project['id']}/pages?page_size=100").json()["items"]
    assert {page["original_url"] for page in pages if page["page_type"] == "Asset"} == {
        "https://shop.example.com/assets/site.css",
        "https://shop.example.com/images/logo.svg",
    }
    sitemap = f'''<urlset xmlns="{NS}">
      <url><loc>https://shop.example.com/good</loc></url>
      <url><loc>https://shop.example.com/private</loc></url>
      <url><loc>https://shop.example.com/old</loc></url>
    </urlset>'''.encode()
    imported = client.post(
        f"/api/projects/{project['id']}/architecture/sitemaps/import",
        files=[("files", ("existing.xml", sitemap, "application/xml"))],
    )
    assert imported.status_code == 201, imported.text

    base = f"/api/projects/{project['id']}/architecture/inventory"
    assert client.get(base, params={"content_group": "asset"}).json()["total"] == 2
    assert client.get(base, params={"indexability": "non_indexable"}).json()["total"] == 4
    assert client.get(base, params={"status_group": "redirect"}).json()["total"] == 1
    assert client.get(base, params={"imported_sitemap": "listed"}).json()["total"] == 3
    assert client.get(base, params={"inclusions": "__filter_none__"}).json()["total"] == 0
    assert client.get(base, params={"content_groups": "__filter_none__"}).json()["total"] == 0
    multi_content = client.get(base, params=[("content_groups", "html"), ("content_groups", "asset")]).json()
    assert multi_content["total"] == 5
    multi_status = client.get(base, params=[("status_groups", "ok"), ("status_groups", "redirect")]).json()
    assert multi_status["total"] == 5
    multi_types = client.get(base, params=[("page_types", "Unknown"), ("page_types", "Asset")]).json()
    assert multi_types["total"] == 5
    eligible = client.get(base, params={"search": "/good"}).json()["items"][0]
    assert eligible["sitemap_eligibility"] == "eligible"
    asset = client.get(base, params={"search": "site.css"}).json()["items"][0]
    assert asset["sitemap_eligibility"] == "exclude"

    refreshed_pages = client.get(f"/api/projects/{project['id']}/pages?page_size=100").json()["items"]
    listed = next(page for page in refreshed_pages if page["original_url"].endswith("/good"))
    assert listed["in_imported_sitemap"] is True
    assert listed["imported_sitemap_occurrences"] == 1
    dashboard = client.get(f"/api/projects/{project['id']}/dashboard").json()
    assert dashboard["imported_sitemap_pages"] == 3
    issues = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    assert any(issue["type"] == "sitemap_non_indexable" and issue["url"].endswith("/private") for issue in issues)
    assert any(issue["type"] == "sitemap_redirect_or_error" and issue["url"].endswith("/old") for issue in issues)


def test_hierarchy_svg_single_and_multi_map_exports_and_categorized_issue_csv(client, project):
    root = add_page(client, project["id"], "/", "Homepage")
    shoes = add_page(client, project["id"], "/shoes", "PLP")
    boot = add_page(client, project["id"], "/shoes/boot", "PDP")
    editorial = add_page(client, project["id"], "/editorial", "Editorial")
    add_page(client, project["id"], "/uncategorized", "Unknown")
    for parent, child in ((root, shoes), (shoes, boot), (root, editorial)):
        response = client.post(
            f"/api/projects/{project['id']}/architecture/relationships",
            json={"parent_page_id": parent["id"], "child_page_id": child["id"], "relationship_type": "primary_parent", "status": "approved"},
        )
        assert response.status_code == 201, response.text

    single = client.post(
        f"/api/projects/{project['id']}/architecture/tree/export",
        json={"scopes": ["shop.example.com|/shoes"]},
    )
    assert single.status_code == 200, single.text
    assert single.headers["content-type"].startswith("image/svg+xml")
    assert "shop.example.com-shoes-hierarchy.svg" in single.headers["content-disposition"]
    svg = ET.fromstring(single.content)
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert b"/shoes/boot" in single.content

    multiple = client.post(
        f"/api/projects/{project['id']}/architecture/tree/export",
        json={"scopes": ["shop.example.com|/shoes", "shop.example.com|/editorial"]},
    )
    assert multiple.status_code == 200, multiple.text
    assert multiple.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(multiple.content)) as archive:
        assert set(archive.namelist()) == {
            "shop.example.com-shoes-hierarchy.svg",
            "shop.example.com-editorial-hierarchy.svg",
        }

    issues = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    assert issues
    assert {issue["category"] for issue in issues} <= {"Sitemap", "Hierarchy", "Page classification", "Inventory evidence"}
    exported = client.get(f"/api/projects/{project['id']}/architecture/issues.csv")
    assert exported.status_code == 200
    assert "architecture-issues.csv" in exported.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert rows
    assert set(rows[0]) == {
        "Category", "Severity", "Priority", "Issue Type", "Label", "URL", "Detail",
        "Recommendation",
        "Page Type", "Content Type", "Status Code", "Status", "Indexability",
        "Indexability Status", "Canonical URL", "Canonical Status", "Redirect Destination", "Redirect Type",
        "Sitemap URL or Name", "Proposed Sitemap", "Imported Sitemap Occurrences",
        "Architecture Section", "Path Depth", "Hierarchy Depth", "Approved Parent URL",
        "Source URL", "Destination URL", "Anchor Text", "Link Position", "Affected Link Count",
    }

    individual = client.get(
        f"/api/projects/{project['id']}/architecture/issues.csv",
        params={"issue_type": "unknown_page_type", "severities": "warning", "search": "uncategorized"},
    )
    assert individual.status_code == 200
    assert "architecture-unknown-page-type-issues.csv" in individual.headers["content-disposition"]
    individual_rows = list(csv.DictReader(io.StringIO(individual.text)))
    assert len(individual_rows) == 1
    assert individual_rows[0]["Issue Type"] == "unknown_page_type"
    assert individual_rows[0]["Severity"] == "warning"
    assert individual_rows[0]["URL"].endswith("/uncategorized")
    assert individual_rows[0]["Page Type"] == "Unknown"
    assert individual_rows[0]["Path Depth"] == "1"

    filtered_out = client.get(
        f"/api/projects/{project['id']}/architecture/issues.csv",
        params={"issue_type": "unknown_page_type", "severities": "error"},
    )
    assert filtered_out.status_code == 200
    assert list(csv.DictReader(io.StringIO(filtered_out.text))) == []


def _import_csv_helper(client, project_id, source, name, content):
    staged = client.post(f"/api/projects/{project_id}/imports/stage", data={"source": source}, files={"file": (name, content, "text/csv")})
    assert staged.status_code == 201, staged.text
    body = staged.json()
    confirmed = client.post(f"/api/projects/{project_id}/imports/{body['batch']['id']}/confirm", json={"mapping": body["suggested_mapping"], "headers_verified": True, "complete_snapshot": False})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_sitemap_asset_pages_and_missing_sitemap_exclusion(client, project):
    # 1. Import a sitemap file so has_imported_sitemap is True
    xml = f'''<?xml version="1.0"?>
    <urlset xmlns="{NS}">
      <url><loc>https://shop.example.com/sitemap-listed</loc></url>
      <url><loc>https://shop.example.com/assets/catalog.pdf</loc></url>
    </urlset>'''.encode()
    sitemap_import = client.post(
        f"/api/projects/{project['id']}/architecture/sitemaps/import",
        files=[("files", ("sitemap.xml", xml, "application/xml"))],
    )
    assert sitemap_import.status_code == 201

    # 2. Import inventory with:
    # - HTML page not in sitemap -> triggers indexable_missing_sitemap
    # - PDF asset not in sitemap -> should NOT trigger indexable_missing_sitemap!
    # - Image asset not in sitemap -> should NOT trigger indexable_missing_sitemap!
    # - PDF asset in sitemap -> triggers sitemap_asset_page ("Asset Pages in Sitemap")
    inventory = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type\n"
        "https://shop.example.com/html-missing,200,OK,Indexable,text/html,PDP\n"
        "https://shop.example.com/manual.pdf,200,OK,Indexable,application/pdf,Asset\n"
        "https://shop.example.com/images/hero.jpg,200,OK,Indexable,image/jpeg,Asset\n"
        "https://shop.example.com/assets/catalog.pdf,200,OK,Indexable,application/pdf,Asset\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "inventory.csv", inventory)

    issues = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    missing_issues = [i for i in issues if i["type"] == "indexable_missing_sitemap"]
    missing_urls = [i["url"] for i in missing_issues]
    assert "https://shop.example.com/html-missing" in missing_urls
    # Assets must be automatically excluded from indexable_missing_sitemap
    assert "https://shop.example.com/manual.pdf" not in missing_urls
    assert "https://shop.example.com/images/hero.jpg" not in missing_urls
    assert "https://shop.example.com/assets/catalog.pdf" not in missing_urls

    # Asset listed in sitemap must trigger sitemap_asset_page ("Asset Pages in Sitemap")
    asset_sitemap_issues = [i for i in issues if i["type"] == "sitemap_asset_page"]
    assert len(asset_sitemap_issues) == 1
    assert asset_sitemap_issues[0]["label"] == "Asset Pages in Sitemap"
    assert asset_sitemap_issues[0]["category"] == "Sitemap"
    assert asset_sitemap_issues[0]["url"] == "https://shop.example.com/assets/catalog.pdf"


def test_synchronise_canonical_and_indexability_changes(client, project):
    inventory = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type,Canonical Link Element 1\n"
        "https://shop.example.com/page-a,200,OK,Non-Indexable,text/html,PDP,https://shop.example.com/page-a\n"
        "https://shop.example.com/page-b,200,OK,Indexable,text/html,PDP,https://shop.example.com/page-target\n"
        "https://shop.example.com/page-source,200,OK,Indexable,text/html,PDP,https://shop.example.com/page-target\n"
        "https://shop.example.com/page-target,200,OK,Non-Indexable,text/html,PDP,https://shop.example.com/page-target\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "crawl.csv", inventory)

    # Set sitemap inclusion on page-a and page-b
    pages = client.get(f"/api/projects/{project['id']}/pages").json()["items"]
    page_a = next(p for p in pages if p["original_url"].endswith("/page-a"))
    page_b = next(p for p in pages if p["original_url"].endswith("/page-b"))
    page_source = next(p for p in pages if p["original_url"].endswith("/page-source"))
    page_target = next(p for p in pages if p["original_url"].endswith("/page-target"))

    # Include page-a and page-b in sitemap
    client.patch(f"/api/projects/{project['id']}/pages/{page_a['id']}/manual-overrides", json={"values": {"sitemap_included": True}})
    client.patch(f"/api/projects/{project['id']}/pages/{page_b['id']}/manual-overrides", json={"values": {"sitemap_included": True}})

    # Verify initial issues:
    # 1. page-a: sitemap_non_indexable (since in sitemap and non-indexable)
    # 2. page-b: sitemap_non_canonical (since in sitemap and points to page-target)
    # 3. page-source on-page: canonical_target_non_indexable (since target is non-indexable)
    arch_issues = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    assert any(i["type"] == "sitemap_non_indexable" and i["page_id"] == page_a["id"] for i in arch_issues)
    assert any(i["type"] == "sitemap_non_canonical" and i["page_id"] == page_b["id"] for i in arch_issues)

    on_page_issues = client.get(f"/api/projects/{project['id']}/on-page/issues?status=All").json()
    assert any(i["type"] == "canonical_target_non_indexable" and i["page_id"] == page_source["id"] for i in on_page_issues)

    # Example 1: Manually change page-a to Indexable -> sitemap_non_indexable must immediately vanish
    client.patch(f"/api/projects/{project['id']}/pages/{page_a['id']}/manual-overrides", json={"values": {"indexability": "Indexable"}})
    arch_issues_after = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    assert not any(i["type"] == "sitemap_non_indexable" and i["page_id"] == page_a["id"] for i in arch_issues_after)

    # Example 2: Manually change page-b canonical to self-canonical -> sitemap_non_canonical must vanish
    client.patch(f"/api/projects/{project['id']}/pages/{page_b['id']}/manual-overrides", json={"values": {"canonical_url": page_b["original_url"]}})
    arch_issues_after2 = client.get(f"/api/projects/{project['id']}/architecture/issues").json()
    assert not any(i["type"] == "sitemap_non_canonical" and i["page_id"] == page_b["id"] for i in arch_issues_after2)

    # Example 3: Manually change target page indexability to Indexable -> canonical_target_non_indexable must vanish
    client.patch(f"/api/projects/{project['id']}/pages/{page_target['id']}/manual-overrides", json={"values": {"indexability": "Indexable"}})
    on_page_after = client.get(f"/api/projects/{project['id']}/on-page/issues?status=All").json()
    assert not any(i["type"] == "canonical_target_non_indexable" and i["page_id"] == page_source["id"] for i in on_page_after)


def test_crawl_discrepancy_detection_and_preservation(client, project):
    inventory1 = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type\n"
        "https://shop.example.com/product-1,200,OK,Indexable,text/html,PDP\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "crawl1.csv", inventory1)

    pages = client.get(f"/api/projects/{project['id']}/pages").json()["items"]
    page1 = pages[0]
    # Set manual override to Indexable (matches initial crawl)
    client.patch(f"/api/projects/{project['id']}/pages/{page1['id']}/manual-overrides", json={"values": {"indexability": "Indexable"}})

    page_detail = client.get(f"/api/projects/{project['id']}/pages/{page1['id']}").json()
    assert page_detail["effective"]["indexability"] == "Indexable"
    assert not page_detail["effective"]["has_discrepancy"]

    # New crawl arrives with Non-Indexable (contradicting the manual override)
    inventory2 = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type\n"
        "https://shop.example.com/product-1,200,OK,Non-Indexable,text/html,PDP\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "crawl2.csv", inventory2)

    page_detail_after = client.get(f"/api/projects/{project['id']}/pages/{page1['id']}").json()
    # 1. Raw DB column preserves original imported Screaming Frog data
    assert page_detail_after["indexability"] == "Non-Indexable"
    # 2. Manual override is preserved and takes precedence in effective data
    assert page_detail_after["manual_overrides"]["indexability"] == "Indexable"
    assert page_detail_after["effective"]["indexability"] == "Indexable"
    # 3. Discrepancy is clearly identified
    assert page_detail_after["effective"]["has_discrepancy"] is True
    assert len(page_detail_after["effective"]["discrepancies"]) == 1
    assert page_detail_after["effective"]["discrepancies"][0]["field"] == "indexability"


def test_inventory_csv_export_filtered_and_columns(client, project):
    # Setup inventory with multiple pages
    inventory = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type,Canonical Link Element 1,Redirect URL\n"
        "https://shop.example.com/shoes,200,OK,Indexable,text/html,PLP,https://shop.example.com/shoes,\n"
        "https://shop.example.com/boot-1,200,OK,Indexable,text/html,PDP,https://shop.example.com/boot-1,\n"
        "https://shop.example.com/boot-2,200,OK,Non-Indexable,text/html,PDP,https://shop.example.com/boot-2,\n"
        "https://shop.example.com/old-shoes,301,Moved Permanently,Non-Indexable,text/html,Other,,https://shop.example.com/shoes\n"
        "https://shop.example.com/broken-page,404,Not Found,Non-Indexable,text/html,Utility,,\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "inventory-crawl.csv", inventory)

    pages = client.get(f"/api/projects/{project['id']}/pages").json()["items"]
    shoes = next(p for p in pages if p["original_url"].endswith("/shoes"))
    boot1 = next(p for p in pages if p["original_url"].endswith("/boot-1"))
    # Include shoes and boot1 in sitemap
    client.patch(
        f"/api/projects/{project['id']}/architecture/inventory/bulk-sitemap",
        json={"page_ids": [shoes["id"], boot1["id"]], "included": True},
    )

    # 1. Unfiltered export returns all matching pages
    resp_all = client.get(f"/api/projects/{project['id']}/architecture/inventory.csv")
    assert resp_all.status_code == 200
    assert "attachment; filename=\"architecture-inventory.csv\"" in resp_all.headers["content-disposition"]
    rows_all = list(csv.DictReader(io.StringIO(resp_all.text)))
    assert len(rows_all) == 5
    first_row = rows_all[0]
    assert "URL" in first_row
    assert "Route" in first_row
    assert "Page Type" in first_row
    assert "HTTP Status Code" in first_row
    assert "Indexability" in first_row
    assert "Proposed XML Sitemap" in first_row

    # 2. Filtered export by page_types (PDP only)
    resp_pdp = client.get(
        f"/api/projects/{project['id']}/architecture/inventory.csv",
        params=[("page_types", "PDP")],
    )
    assert resp_pdp.status_code == 200
    rows_pdp = list(csv.DictReader(io.StringIO(resp_pdp.text)))
    assert len(rows_pdp) == 2
    assert {r["Page Type"] for r in rows_pdp} == {"PDP"}

    # 3. Filtered export by search term
    resp_search = client.get(
        f"/api/projects/{project['id']}/architecture/inventory.csv",
        params={"search": "boot"},
    )
    assert resp_search.status_code == 200
    rows_search = list(csv.DictReader(io.StringIO(resp_search.text)))
    assert len(rows_search) == 2
    assert all("boot" in r["URL"] for r in rows_search)

    # 4. Respect selected columns
    resp_cols = client.get(
        f"/api/projects/{project['id']}/architecture/inventory.csv",
        params=[("columns", "route"), ("columns", "page_type"), ("columns", "proposed_sitemap")],
    )
    assert resp_cols.status_code == 200
    rows_cols = list(csv.DictReader(io.StringIO(resp_cols.text)))
    assert set(rows_cols[0].keys()) == {"URL", "Route", "Page Type", "Proposed XML Sitemap"}


def test_sitemap_proposed_and_imported_csv_exports(client, project):
    inventory = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type\n"
        "https://shop.example.com/shoes,200,OK,Indexable,text/html,PLP\n"
        "https://shop.example.com/boot-1,200,OK,Indexable,text/html,PDP\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "inventory.csv", inventory)

    pages = client.get(f"/api/projects/{project['id']}/pages").json()["items"]
    shoes = next(p for p in pages if p["original_url"].endswith("/shoes"))
    client.patch(
        f"/api/projects/{project['id']}/architecture/inventory/bulk-sitemap",
        json={"page_ids": [shoes["id"]], "included": True},
    )

    # Proposed sitemap CSV
    resp_prop = client.get(f"/api/projects/{project['id']}/architecture/sitemaps/proposed.csv")
    assert resp_prop.status_code == 200
    assert "proposed-sitemap.csv" in resp_prop.headers["content-disposition"]
    rows_prop = list(csv.DictReader(io.StringIO(resp_prop.text)))
    assert len(rows_prop) == 1
    assert rows_prop[0]["URL"] == "https://shop.example.com/shoes"
    assert rows_prop[0]["Proposed XML Sitemap"] == "Included"

    # Import sitemap XML
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://shop.example.com/shoes</loc><lastmod>2026-11-01</lastmod><changefreq>weekly</changefreq><priority>0.8</priority></url>
      <url><loc>https://shop.example.com/external-url</loc></url>
    </urlset>"""
    client.post(
        f"/api/projects/{project['id']}/architecture/sitemaps/import",
        files=[("files", ("sitemap.xml", xml, "application/xml"))],
    )

    # Imported sitemap CSV
    resp_imp = client.get(f"/api/projects/{project['id']}/architecture/sitemaps/imported.csv")
    assert resp_imp.status_code == 200
    assert "imported-sitemap-entries.csv" in resp_imp.headers["content-disposition"]
    rows_imp = list(csv.DictReader(io.StringIO(resp_imp.text)))
    assert len(rows_imp) == 2
    shoes_entry = next(r for r in rows_imp if r["Sitemap URL"].endswith("/shoes"))
    assert shoes_entry["Sitemap Document"] == "sitemap.xml"
    assert shoes_entry["Lastmod"] == "2026-11-01"
    assert shoes_entry["Priority"] == "0.8"


def test_issues_csv_complete_metrics_and_filters(client, project):
    inventory = (
        "Address,Status Code,Status,Indexability,Content Type,Page Type,Redirect URL,Canonical Link Element 1\n"
        "https://shop.example.com/error-page,404,Not Found,Non-Indexable,text/html,Utility,,\n"
        "https://shop.example.com/temp-redirect,302,Found,Non-Indexable,text/html,Other,https://shop.example.com/target,\n"
    )
    _import_csv_helper(client, project["id"], "screaming_frog", "crawl.csv", inventory)

    pages = client.get(f"/api/projects/{project['id']}/pages").json()["items"]
    error_page = next(p for p in pages if p["original_url"].endswith("/error-page"))
    patch_resp = client.patch(f"/api/projects/{project['id']}/pages/bulk-type", json={"page_ids": [error_page["id"]], "page_type": "Editorial"})
    assert patch_resp.status_code == 200

    # Central issues CSV
    resp = client.get(f"/api/projects/{project['id']}/issues.csv")
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows

    # Verify status code issue metrics
    error_issue = next(r for r in rows if r["Issue Type"] == "http_4xx")
    assert error_issue["Affected URL"] == "https://shop.example.com/error-page"
    assert error_issue["HTTP Status Code"] == "404"
    assert error_issue["Status Text"] == "Not Found"
    assert error_issue["Content Type"] == "text/html"
    assert error_issue["Page Type"] == "Editorial"
    assert error_issue["Recommendation"] != ""

    redirect_issue = next(r for r in rows if r["Issue Type"] == "redirect_302")
    assert redirect_issue["Redirect Destination"] == "https://shop.example.com/target"

    # Verify search and filter parameters on central issues CSV
    resp_filtered = client.get(
        f"/api/projects/{project['id']}/issues.csv",
        params={"search": "error-page"},
    )
    assert resp_filtered.status_code == 200
    filtered_rows = list(csv.DictReader(io.StringIO(resp_filtered.text)))
    assert len(filtered_rows) == 2
    assert all(r["Affected URL"] == "https://shop.example.com/error-page" for r in filtered_rows)

    resp_type = client.get(
        f"/api/projects/{project['id']}/issues.csv",
        params={"issue_type": "http_4xx"},
    )
    assert resp_type.status_code == 200
    type_rows = list(csv.DictReader(io.StringIO(resp_type.text)))
    assert len(type_rows) == 1
    assert type_rows[0]["Issue Type"] == "http_4xx"

