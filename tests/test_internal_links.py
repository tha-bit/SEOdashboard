def import_csv(client, project_id, source, name, content, *, complete=False):
    staged = client.post(f"/api/projects/{project_id}/imports/stage", data={"source": source}, files={"file": (name, content, "text/csv")})
    assert staged.status_code == 201, staged.text
    body = staged.json()
    confirmed = client.post(f"/api/projects/{project_id}/imports/{body['batch']['id']}/confirm", json={"mapping": body["suggested_mapping"], "headers_verified": True, "complete_snapshot": complete})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_inlinks_import_preserves_evidence_and_drives_analysis(client, project):
    inventory = "Address,Status Code,Status,Indexability,Content Type,Page Type,Crawl Depth,Inlinks\nhttps://shop.example.com/,200,OK,Indexable,text/html,PDP,0,12\nhttps://shop.example.com/products,200,OK,Indexable,text/html,PLP,2,4\nhttps://shop.example.com/missing,404,Not Found,Non-Indexable,text/html,PDP,1,1\nhttps://shop.example.com/redirect,301,Moved Permanently,Non-Indexable,text/html,PDP,1,0\nhttps://shop.example.com/uncollected,200,OK,Indexable,text/html,PDP,,\n"
    import_csv(client, project["id"], "screaming_frog", "crawl.csv", inventory)
    inlinks = "Type,Source,Destination,Anchor,Status Code,Status,Follow,Rel,Link Position,Link Origin\nHyperlink,https://shop.example.com/,https://shop.example.com/products,Products,200,OK,true,,Content,HTML\nHyperlink,https://shop.example.com/,https://shop.example.com/missing,click here,404,Not Found,true,,Content,HTML\nHyperlink,https://shop.example.com/,https://outside.example.org/,External,200,OK,true,,Footer,HTML\n"
    result = import_csv(client, project["id"], "screaming_frog_inlinks", "inlinks.csv", inlinks, complete=True)
    assert result["imported_count"] == 3
    assert result["skipped_count"] == 1

    summary = client.get(f"/api/projects/{project['id']}/architecture/internal-links/summary").json()
    assert summary["snapshot"]["internal_links"] == 2
    assert summary["snapshot"]["external_links"] == 1
    assert summary["snapshot"]["complete"] is True
    assert summary["broken_links"] == 1

    findings = client.get(f"/api/projects/{project['id']}/architecture/internal-links/findings").json()["items"]
    broken = next(item for item in findings if item["type"] == "broken_internal_link" and item["evidence"]["destination_url"].endswith("/missing"))
    assert broken["inlinks"] == 1
    assert broken["imported_inlinks"] == 1
    assert broken["internal_inlinks"] == 1
    assert broken["internal_inlinks_source"] == "screaming_frog"
    assert broken["crawl_depth"] == 1
    assert broken["page_status_code"] == 404
    assert broken["affected_link_count"] == 1
    weak_product = next(item for item in findings if item["type"] == "weakly_linked_page" and item["url"].endswith("/products"))
    assert weak_product["inlinks"] == 1
    assert weak_product["unique_sources"] == 1
    assert weak_product["imported_inlinks"] == 4
    assert weak_product["internal_inlinks"] == 4
    assert weak_product["internal_inlinks_source"] == "screaming_frog"
    assert weak_product["crawl_depth"] == 2
    assert any(item["type"] == "generic_anchor" for item in findings)
    assert any(item["type"] == "potential_orphan_page" for item in findings)
    assert all("outside.example.org" not in str(item.get("url")) for item in findings)

    internal_categories = {
        "Broken & Invalid Links",
        "Orphan & Weakly Linked Pages",
        "Architecture & Crawl Depth",
        "Anchor Text Issues",
        "Indexability & Canonical Conflicts",
        "Internal Linking Opportunities",
        "Link Distribution & Structural Patterns",
    }
    central = client.get(f"/api/projects/{project['id']}/issues").json()
    central_internal = [item for item in central if item["category"] in internal_categories]
    finding_keys = {item["issue_key"] for item in findings}
    assert len(finding_keys) == len(findings)
    assert {item["issue_key"] for item in central_internal} == finding_keys

    selected_finding = next(item for item in findings if item["type"] == "broken_internal_link")
    priority_change = client.patch(f"/api/projects/{project['id']}/issues/{selected_finding['issue_key']}/priority", json={"priority": "critical"})
    assert priority_change.status_code == 200, priority_change.text
    priority_findings = client.get(f"/api/projects/{project['id']}/architecture/internal-links/findings").json()["items"]
    priority_central = client.get(f"/api/projects/{project['id']}/issues").json()
    assert next(item for item in priority_findings if item["issue_key"] == selected_finding["issue_key"])["priority"] == "critical"
    assert next(item for item in priority_central if item["issue_key"] == selected_finding["issue_key"])["priority"] == "critical"
    solution = client.post(
        f"/api/projects/{project['id']}/issue-solutions",
        json={"issue_key": selected_finding["issue_key"], "source": "site_architecture", "workflow_status": "in_progress", "action": "other", "summary": "Review and replace the broken internal destination."},
    )
    assert solution.status_code == 201, solution.text
    refreshed_findings = client.get(f"/api/projects/{project['id']}/architecture/internal-links/findings").json()["items"]
    refreshed_central = client.get(f"/api/projects/{project['id']}/issues").json()
    assert next(item for item in refreshed_findings if item["issue_key"] == selected_finding["issue_key"])["status"] == "in_progress"
    assert next(item for item in refreshed_central if item["issue_key"] == selected_finding["issue_key"])["status"] == "in_progress"
    activity = client.get(f"/api/projects/{project['id']}/activity", params={"section": "site_architecture"}).json()["items"]
    assert any(item["action_type"] == "internal_link_issue_detected" for item in activity)

    pages = client.get(f"/api/projects/{project['id']}/pages?page_size=50").json()["items"]
    product = next(item for item in pages if item["original_url"].endswith("/products"))
    assert product["inlinks"] == 1
    assert product["internal_inlinks"] == 4
    assert product["internal_inlinks_source"] == "screaming_frog"
    assert product["unique_sources"] == 1
    assert product["crawl_depth"] == 2
    home = next(item for item in pages if item["original_url"] == "https://shop.example.com/")
    assert home["crawl_depth"] == 0
    redirect = next(item for item in pages if item["original_url"].endswith("/redirect"))
    assert redirect["http_status"] == 301
    assert redirect["internal_inlinks"] == 0
    uncollected = next(item for item in pages if item["original_url"].endswith("/uncollected"))
    assert uncollected["crawl_depth"] is None
    evidence = client.get(f"/api/projects/{project['id']}/architecture/internal-links/pages/{product['id']}").json()
    assert evidence["count"] == 1
    assert evidence["inlinks"][0]["anchor"] == "Products"

    # A later page crawl that does not supply link metrics must not erase the
    # most recent mapped Crawl Depth or Inlinks observations.
    metadata_only = "Address,Title 1\nhttps://shop.example.com/,Shop home\nhttps://shop.example.com/products,Products\n"
    import_csv(client, project["id"], "screaming_frog", "metadata-only.csv", metadata_only)
    retained = client.get(f"/api/projects/{project['id']}/architecture/internal-links/findings").json()["items"]
    retained_product = next(item for item in retained if item["type"] == "weakly_linked_page" and item["url"].endswith("/products"))
    assert retained_product["internal_inlinks"] == 4
    assert retained_product["internal_inlinks_source"] == "screaming_frog"
    assert retained_product["crawl_depth"] == 2
    csv_export = client.get(f"/api/projects/{project['id']}/architecture/internal-links/export.csv")
    assert csv_export.status_code == 200
    assert "internal_inlinks,internal_inlinks_source,unique_sources,crawl_depth" in csv_export.text.splitlines()[0]

    duplicate = import_csv(client, project["id"], "screaming_frog_inlinks", "same-again.csv", inlinks, complete=True)
    assert duplicate["imported_count"] == 0
    assert duplicate["skipped_count"] == 3

    exported = client.get(f"/api/projects/{project['id']}/export")
    restored = client.post("/api/projects/import", files={"file": ("internal-links.seo-project.json", exported.content, "application/json")})
    assert restored.status_code == 201, restored.text
    restored_summary = client.get(f"/api/projects/{restored.json()['id']}/architecture/internal-links/summary").json()
    assert restored_summary["snapshot"]["internal_links"] == 2


def test_inlinks_requires_source_and_destination_mapping(client, project):
    staged = client.post(f"/api/projects/{project['id']}/imports/stage", data={"source": "screaming_frog_inlinks"}, files={"file": ("partial.csv", "Source,Anchor\nhttps://shop.example.com/,Home\n", "text/csv")}).json()
    response = client.post(f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/confirm", json={"mapping": staged["suggested_mapping"], "headers_verified": True})
    assert response.status_code == 422
    assert "Destination URL" in response.json()["detail"]
