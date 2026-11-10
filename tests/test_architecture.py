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
    assert rows[0].keys() == {"Category", "Severity", "Issue Type", "Label", "URL", "Detail"}
