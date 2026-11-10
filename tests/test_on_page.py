import csv
import io


def import_screaming_frog(client, project_id, name, content, reporting_date=None):
    data = {"source": "screaming_frog"}
    if reporting_date:
        data["reporting_date"] = reporting_date
    staged_response = client.post(
        f"/api/projects/{project_id}/imports/stage",
        data=data,
        files={"file": (name, content, "text/csv")},
    )
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    confirmed = client.post(
        f"/api/projects/{project_id}/imports/{staged['batch']['id']}/confirm",
        json={"mapping": staged["suggested_mapping"], "headers_verified": staged["requires_header_verification"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return staged, confirmed.json()


def test_metadata_import_provenance_field_states_and_deterministic_issues(client, project):
    content = b"""Address,Page Type,Status Code,Status,Indexability,Content Type,Title 1,Title 1 Length,Meta Description 1,H1-1,H1-2,Canonical Link Element 1,Meta Robots 1,X-Robots-Tag 1
https://shop.example.com/category,PLP,200,OK,Indexable,text/html,Shared title,12,Shared description,Category heading,Second heading,https://shop.example.com/redirect,index follow,
https://shop.example.com/product,PDP,200,OK,Indexable,text/html,Shared title,12,Shared description,Product heading,,https://shop.example.com/product,index follow,
https://shop.example.com/redirect,Other,301,Moved Permanently,Non-Indexable,text/html,Redirect page,13,Redirect description,Redirect heading,,https://shop.example.com/redirect,noindex,
https://shop.example.com/empty,Editorial,200,OK,Indexable,text/html,,0,,, ,https://shop.example.com/empty,noindex,
"""
    staged, _ = import_screaming_frog(client, project["id"], "internal-html.csv", content, "2026-11-01")
    page_rows = client.get(f"/api/projects/{project['id']}/on-page/pages?page_size=100").json()
    assert page_rows["total"] == 4
    typed_rows = client.get(
        f"/api/projects/{project['id']}/on-page/pages?page_size=100",
        params=[("page_types", "PLP"), ("page_types", "PDP")],
    ).json()
    assert typed_rows["total"] == 2
    assert {item["page_type"] for item in typed_rows["items"]} == {"PLP", "PDP"}
    category = next(item for item in page_rows["items"] if item["url"].endswith("/category"))
    assert category["current"]["h1"] == ["Category heading", "Second heading"]
    assert category["field_states"]["title"] == "present"
    empty = next(item for item in page_rows["items"] if item["url"].endswith("/empty"))
    assert empty["field_states"]["title"] == "empty"
    detail = client.get(f"/api/projects/{project['id']}/on-page/pages/{category['id']}").json()
    assert detail["provenance"]["title"]["batch_id"] == staged["batch"]["id"]
    assert detail["provenance"]["title"]["reporting_date"] == "2026-11-01"
    assert detail["provenance"]["title"]["source"].endswith("internal-html.csv")

    client.patch(
        f"/api/projects/{project['id']}/architecture/inventory/bulk-sitemap",
        json={"page_ids": [empty["id"]], "included": True},
    )
    issues = client.get(f"/api/projects/{project['id']}/on-page/issues?status=All").json()
    issue_types = {item["type"] for item in issues}
    assert {"multiple_h1", "duplicate_title", "duplicate_description", "canonical_target_redirected", "missing_title", "noindex_sitemap_conflict"} <= issue_types
    nofollow_only = [item for item in issues if item["type"] == "noindex_sitemap_conflict" and item["url"].endswith("/category")]
    assert not nofollow_only
    issue_filtered = client.get(
        f"/api/projects/{project['id']}/on-page/pages?page_size=100",
        params=[("issue_types", "multiple_h1"), ("issue_types", "missing_title")],
    ).json()
    assert {item["url"].rsplit("/", 1)[-1] for item in issue_filtered["items"]} == {"category", "empty"}

    central = client.get(f"/api/projects/{project['id']}/issues").json()
    assert {item["source"] for item in central} == {"site_architecture", "on_page"}
    central_multiple_h1 = next(item for item in central if item["type"] == "multiple_h1")
    assert central_multiple_h1["source_label"] == "On-Page SEO"
    assert central_multiple_h1["category"] == "Content metadata"
    assert central_multiple_h1["source_severity"] == "review"
    assert central_multiple_h1["severity"] == "warning"

    architecture_issue = next(item for item in central if item["source"] == "site_architecture")
    architecture_solution = client.post(
        f"/api/projects/{project['id']}/issue-solutions",
        json={"issue_key": architecture_issue["issue_key"], "source": "site_architecture", "workflow_status": "in_progress", "action": "sitemap_change", "summary": "Remove the non-indexable URL from the proposed sitemap.", "owner": "Technical SEO", "target_date": "2026-11-15", "data": {"sitemap_decision": "exclude", "expected_indexability": "Non-Indexable"}},
    )
    assert architecture_solution.status_code == 201, architecture_solution.text
    on_page_solution = client.post(
        f"/api/projects/{project['id']}/issue-solutions",
        json={"issue_key": central_multiple_h1["issue_key"], "source": "on_page", "workflow_status": "proposed", "action": "content_update", "summary": "Retain one descriptive primary heading.", "data": {"recommended_h1": "Category heading", "expected_validation_result": "One H1"}},
    )
    assert on_page_solution.status_code == 201, on_page_solution.text
    saved_evidence = on_page_solution.json()["issue_snapshot"]["on_page_current"]
    assert saved_evidence["current"]["h1"] == ["Category heading", "Second heading"]
    assert saved_evidence["current"]["title"] == "Shared title"
    assert saved_evidence["field_states"]["h1"] == "present"
    assert saved_evidence["last_observed_at"]
    solution_log = client.get(f"/api/projects/{project['id']}/issue-solutions").json()
    assert len(solution_log) == 2
    assert {item["source"] for item in solution_log} == {"site_architecture", "on_page"}
    refreshed_central = client.get(f"/api/projects/{project['id']}/issues").json()
    refreshed_multiple_h1 = next(item for item in refreshed_central if item["issue_key"] == central_multiple_h1["issue_key"])
    assert refreshed_multiple_h1["solution_count"] == 1
    assert refreshed_multiple_h1["latest_solution"]["data"]["recommended_h1"] == "Category heading"

    central_csv = client.get(f"/api/projects/{project['id']}/issues.csv")
    assert central_csv.status_code == 200
    central_rows = list(csv.DictReader(io.StringIO(central_csv.text)))
    assert {row["Source"] for row in central_rows} == {"Site Architecture", "On-Page SEO"}
    solution_csv = client.get(f"/api/projects/{project['id']}/issue-solutions.csv")
    assert solution_csv.status_code == 200
    assert {row["Source"] for row in csv.DictReader(io.StringIO(solution_csv.text))} == {"site_architecture", "on_page"}


def test_recommendation_survives_new_crawl_and_records_change_history(client, project):
    first = b"Address,Title 1,Meta Description 1,H1-1\nhttps://shop.example.com/page,Old title,Old description,Old heading\n"
    import_screaming_frog(client, project["id"], "crawl-one.csv", first)
    page = client.get(f"/api/projects/{project['id']}/on-page/pages?page_size=100").json()["items"][0]
    saved = client.put(
        f"/api/projects/{project['id']}/on-page/pages/{page['id']}/recommendation",
        json={"data": {"h1": ["Recommended heading"], "title": "Recommended title", "meta_description": "Recommended description", "canonical_url": "https://shop.example.com/page", "hreflang": [{"language": "en-GB", "target": "https://shop.example.com/page"}]}, "review_status": "approved", "notes": "Ready for implementation", "reviewer": "SEO lead"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["review_status"] == "approved"

    second = b"Address,Title 1,Meta Description 1,H1-1\nhttps://shop.example.com/page,New observed title,New observed description,New observed heading\n"
    import_screaming_frog(client, project["id"], "crawl-two.csv", second)
    detail = client.get(f"/api/projects/{project['id']}/on-page/pages/{page['id']}").json()
    assert detail["current"]["title"] == "New observed title"
    assert detail["recommendation"]["data"]["title"] == "Recommended title"
    assert detail["recommendation"]["review_status"] == "approved"
    assert len(detail["change_history"]) == 1
    assert detail["observation_count"] == 2


def test_solution_follow_up_remains_available_after_issue_disappears(client, project):
    page = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/unclassified", "page_type": "Unknown"}).json()
    issue = next(item for item in client.get(f"/api/projects/{project['id']}/issues").json() if item["type"] == "unknown_page_type")
    first = client.post(f"/api/projects/{project['id']}/issue-solutions", json={"issue_key": issue["issue_key"], "source": "site_architecture", "workflow_status": "proposed", "action": "classification_change", "summary": "Classify the page after stakeholder review.", "data": {"proposed_page_type": "Editorial"}})
    assert first.status_code == 201, first.text
    changed = client.patch(f"/api/projects/{project['id']}/pages/bulk-type", json={"page_ids": [page["id"]], "page_type": "Editorial"})
    assert changed.status_code == 200
    assert all(item["issue_key"] != issue["issue_key"] for item in client.get(f"/api/projects/{project['id']}/issues").json())
    follow_up = client.post(f"/api/projects/{project['id']}/issue-solutions", json={"issue_key": issue["issue_key"], "source": "site_architecture", "workflow_status": "verified", "action": "classification_change", "summary": "Classification confirmed and the issue no longer appears.", "verification_notes": "Verified in the current inventory", "data": {"proposed_page_type": "Editorial"}})
    assert follow_up.status_code == 201, follow_up.text
    history = client.get(f"/api/projects/{project['id']}/issue-solutions?issue_key={issue['issue_key']}").json()
    assert [item["workflow_status"] for item in history] == ["verified", "proposed"]


def test_separate_hreflang_export_merges_rows_and_flags_missing_reciprocal(client, project):
    internal = b"Address,Title 1\nhttps://shop.example.com/en,English page\nhttps://shop.example.com/fr,French page\n"
    import_screaming_frog(client, project["id"], "internal.csv", internal)
    hreflang = b"From,Hreflang,To\nhttps://shop.example.com/en,en-GB,https://shop.example.com/en\nhttps://shop.example.com/en,fr-FR,https://shop.example.com/fr\nhttps://shop.example.com/fr,fr-FR,https://shop.example.com/fr\n"
    _, report = import_screaming_frog(client, project["id"], "hreflang.csv", hreflang)
    assert report["imported_count"] == 3
    pages = client.get(f"/api/projects/{project['id']}/on-page/pages?page_size=100").json()["items"]
    english = next(item for item in pages if item["url"].endswith("/en"))
    assert english["current"]["title"] == "English page"
    assert len(english["current"]["hreflang"]) == 2
    issues = client.get(f"/api/projects/{project['id']}/on-page/issues").json()
    reciprocal = next(item for item in issues if item["type"] == "hreflang_missing_reciprocal" and item["url"].endswith("/en"))
    dismissed = client.patch(
        f"/api/projects/{project['id']}/on-page/issues/{reciprocal['issue_key']}",
        json={"status": "dismissed", "reason": "French locale export is intentionally one-way during migration"},
    )
    assert dismissed.status_code == 200
    all_issues = client.get(f"/api/projects/{project['id']}/on-page/issues?status=All").json()
    refreshed = next(item for item in all_issues if item["issue_key"] == reciprocal["issue_key"])
    assert refreshed["status"] == "dismissed"
    assert "intentionally" in refreshed["reason"]


def test_on_page_export_thresholds_dashboard_project_isolation_and_bundle_round_trip(client, project):
    content = b"Address,Page Type,Title 1,Meta Description 1,H1-1\nhttps://shop.example.com/list,PLP,Short,Description,List heading\n"
    import_screaming_frog(client, project["id"], "metadata.csv", content)
    page = client.get(f"/api/projects/{project['id']}/on-page/pages?page_size=100").json()["items"][0]
    client.put(f"/api/projects/{project['id']}/on-page/pages/{page['id']}/recommendation", json={"data": {"title": "Better list title"}, "review_status": "review", "notes": "Review with merchandising"})
    issue = client.get(f"/api/projects/{project['id']}/issues").json()[0]
    solution = client.post(f"/api/projects/{project['id']}/issue-solutions", json={"issue_key": issue["issue_key"], "source": issue["source"], "workflow_status": "implemented", "action": "content_update" if issue["source"] == "on_page" else "classification_change", "summary": "Implementation recorded for reporting.", "verification_notes": "Recheck in the next crawl", "data": {"recommended_title": "Better list title"}})
    assert solution.status_code == 201, solution.text

    settings = client.patch(f"/api/projects/{project['id']}/on-page/settings", json={"title_min": 5, "title_max": 70, "description_min": 10, "description_max": 180})
    assert settings.status_code == 200
    dashboard = client.get(f"/api/projects/{project['id']}/dashboard").json()
    assert dashboard["pages_with_metadata"] == 1
    assert dashboard["outstanding_optimisations"] >= 1
    exported = client.get(f"/api/projects/{project['id']}/on-page/export")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert rows[0]["Current Title"] == "Short"
    assert rows[0]["Proposed Title"] == "Better list title"

    second = client.post("/api/projects", json={"name": "Second", "site_url": "https://second.example.com"}).json()
    assert client.get(f"/api/projects/{second['id']}/on-page/pages").json()["total"] == 0
    downloaded = client.get(f"/api/projects/{project['id']}/export")
    bundle = downloaded.json()
    assert len(bundle["page_metadata_observations"]) == 1
    assert len(bundle["page_metadata_recommendations"]) == 1
    assert len(bundle["page_metadata_changes"]) == 1
    assert len(bundle["issue_solutions"]) == 1
    restored = client.post("/api/projects/import", files={"file": ("phase3.seo-project.json", downloaded.content, "application/json")})
    assert restored.status_code == 201, restored.text
    restored_pages = client.get(f"/api/projects/{restored.json()['id']}/on-page/pages?page_size=100").json()
    assert restored_pages["total"] == 1
    assert restored_pages["items"][0]["recommendation"]["data"]["title"] == "Better list title"
    restored_solutions = client.get(f"/api/projects/{restored.json()['id']}/issue-solutions").json()
    assert len(restored_solutions) == 1
    assert restored_solutions[0]["summary"] == "Implementation recorded for reporting."
