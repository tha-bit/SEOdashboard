def import_crawl(client, project_id: str, name: str, content: bytes, reporting_date: str):
    staged = client.post(
        f"/api/projects/{project_id}/imports/stage",
        data={"source": "screaming_frog", "reporting_date": reporting_date},
        files={"file": (name, content, "text/csv")},
    )
    assert staged.status_code == 201, staged.text
    body = staged.json()
    confirmed = client.post(
        f"/api/projects/{project_id}/imports/{body['batch']['id']}/confirm",
        json={"mapping": body["suggested_mapping"], "headers_verified": body["requires_header_verification"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return body["batch"]["id"]


def import_dataset(client, project_id: str, source: str, name: str, content: bytes, reporting_date: str):
    staged = client.post(f"/api/projects/{project_id}/imports/stage", data={"source": source, "reporting_date": reporting_date}, files={"file": (name, content, "text/csv")})
    assert staged.status_code == 201, staged.text
    body = staged.json()
    confirmed = client.post(f"/api/projects/{project_id}/imports/{body['batch']['id']}/confirm", json={"mapping": body["suggested_mapping"], "headers_verified": body["requires_header_verification"]})
    assert confirmed.status_code == 200, confirmed.text
    return body["batch"]["id"]


def test_manual_activity_categories_status_and_exports(client, project):
    category = client.post(f"/api/projects/{project['id']}/activity/categories", json={"name": "Q4 technical fixes", "color": "green"})
    assert category.status_code == 201, category.text
    created = client.post(
        f"/api/projects/{project['id']}/activity",
        json={"title": "Reviewed redirect plan", "notes": "Ready for development.", "section": "site_architecture", "status": "in_progress", "category_id": category.json()["id"], "occurred_at": "2026-11-05T12:00:00Z"},
    )
    assert created.status_code == 201, created.text
    changed = client.post(f"/api/projects/{project['id']}/activity/{created.json()['id']}/status", json={"status": "completed", "notes": "Released"})
    assert changed.status_code == 201, changed.text

    unchanged = client.post(f"/api/projects/{project['id']}/activity/{changed.json()['id']}/status", json={"status": "completed"})
    assert unchanged.status_code == 201, unchanged.text
    assert unchanged.json()["id"] == changed.json()["id"]

    rows = client.get(f"/api/projects/{project['id']}/activity").json()
    assert rows["total"] == 2
    assert {item["status"] for item in rows["items"]} == {"in_progress", "completed"}
    assert all(item["category"] == "Q4 technical fixes" for item in rows["items"])
    assert client.get(f"/api/projects/{project['id']}/activity/export.csv?status=completed").text.count("Reviewed redirect plan") == 1
    monthly = client.get(f"/api/projects/{project['id']}/activity/monthly?month=2026-11&compare=2026-10").json()
    assert monthly["current"]["total_activities"] == 2
    assert monthly["comparison"]["data_available"] is False

    exported = client.get(f"/api/projects/{project['id']}/export")
    restored = client.post("/api/projects/import", files={"file": ("activity-project.seo-project.json", exported.content, "application/json")})
    assert restored.status_code == 201, restored.text
    restored_rows = client.get(f"/api/projects/{restored.json()['id']}/activity").json()
    assert restored_rows["total"] == 2
    assert {item["category"] for item in restored_rows["items"]} == {"Q4 technical fixes"}


def test_recommendations_and_solutions_automatically_enter_activity_log(client, project):
    import_crawl(client, project["id"], "recommendation.csv", b"Address,Page Type,Title 1\nhttps://shop.example.com/page,Other,Existing title that is comfortably within guidance\n", "2026-11-01")
    page = client.get(f"/api/projects/{project['id']}/on-page/pages?page_size=100").json()["items"][0]
    recommendation = client.put(
        f"/api/projects/{project['id']}/on-page/pages/{page['id']}/recommendation",
        json={"data": {"title": "A recommended replacement title"}, "review_status": "draft", "notes": "Suggestion for review"},
    )
    assert recommendation.status_code == 200, recommendation.text
    activity = client.get(f"/api/projects/{project['id']}/activity?section=on_page").json()["items"]
    assert any(item["action_type"] == "recommendation_created" and item["recommendation_id"] == recommendation.json()["id"] for item in activity)
    assert next(item for item in activity if item["recommendation_id"] == recommendation.json()["id"])["status"] == "in_progress"

    issue = next(item for item in client.get(f"/api/projects/{project['id']}/issues").json() if item["source"] == "site_architecture")
    solution = client.post(
        f"/api/projects/{project['id']}/issue-solutions",
        json={"issue_key": issue["issue_key"], "source": "site_architecture", "workflow_status": "ignored", "action": "other", "summary": "Accepted for the current release."},
    )
    assert solution.status_code == 201, solution.text
    ignored = client.get(f"/api/projects/{project['id']}/activity?status=ignored").json()["items"]
    assert any(item["issue_solution_id"] == solution.json()["id"] for item in ignored)


def test_crawl_snapshots_detect_resolved_issues_and_ignore_duplicate_files(client, project):
    first = b"Address,Page Type,Status Code,Content Type,Title 1\nhttps://shop.example.com/page,Other,200,text/html,\n"
    second = b"Address,Page Type,Status Code,Content Type,Title 1\nhttps://shop.example.com/page,Other,200,text/html,A useful title that is comfortably within guidance\n"
    import_crawl(client, project["id"], "october.csv", first, "2026-10-10")
    october = client.get(f"/api/projects/{project['id']}/activity/monthly?month=2026-10").json()["current"]
    assert october["issues_resolved"] == 0
    assert october["outstanding_issues"] is not None

    import_crawl(client, project["id"], "november.csv", second, "2026-11-10")
    resolved = client.get(f"/api/projects/{project['id']}/activity?status=resolved").json()["items"]
    title_fix = next(item for item in resolved if item["issue_type"] == "missing_title")
    assert title_fix["before_data"]["present"] is True
    assert title_fix["after_data"]["present"] is False
    assert "proof of causation" not in (title_fix["notes"] or "")
    november = client.get(f"/api/projects/{project['id']}/activity/monthly?month=2026-11&compare=2026-10").json()
    assert november["current"]["issues_resolved"] >= 1
    assert november["current"]["outstanding_issues"] < november["comparison"]["outstanding_issues"]

    import_crawl(client, project["id"], "november-duplicate.csv", second, "2026-11-10")
    resolved_after_duplicate = client.get(f"/api/projects/{project['id']}/activity?status=resolved").json()["items"]
    assert sum(item["issue_type"] == "missing_title" for item in resolved_after_duplicate) == 1


def test_changed_status_is_used_for_pages_gsc_and_ga4(client, project):
    first = b"Address,Status Code,Status,Indexability,Content Type\nhttps://shop.example.com/page,200,OK,Indexable,text/html\n"
    second = b"Address,Status Code,Status,Indexability,Content Type\nhttps://shop.example.com/page,301,Moved Permanently,Non-Indexable,text/html\n"
    import_crawl(client, project["id"], "crawl-one.csv", first, "2026-10-01")
    import_crawl(client, project["id"], "crawl-two.csv", second, "2026-11-01")

    gsc = b"Query,Page,Clicks,Impressions,CTR,Position,Start Date,End Date\nmobile phones,https://shop.example.com/page,25,500,5%,4.2,2026-11-01,2026-11-30\n"
    ga4 = b"Landing page,Sessions,Engaged sessions,Conversions,Start Date,End Date,Channel\nhttps://shop.example.com/page,300,220,12,2026-11-01,2026-11-30,Organic Search\n"
    import_dataset(client, project["id"], "gsc", "gsc.csv", gsc, "2026-11-30")
    import_dataset(client, project["id"], "ga4", "ga4.csv", ga4, "2026-11-30")

    changed = client.get(f"/api/projects/{project['id']}/activity?status=changed").json()["items"]
    assert {item["section"] for item in changed} == {"pages", "performance"}
    assert {item["action_type"] for item in changed} >= {"page_metrics_changed", "gsc_data_changed", "ga4_data_changed"}
    assert all(item["status"] == "changed" for item in changed)


def test_activity_titles_are_concise_across_existing_status_chains(client, project):
    original = client.post(
        f"/api/projects/{project['id']}/activity",
        json={
            "title": "Status changed: Status changed: Crawl metric changed: https://shop.example.com/page",
            "section": "pages",
            "status": "changed",
            "action_type": "page_metrics_changed",
            "url": "https://shop.example.com/page",
            "before_data": {"http_status": 200, "indexability": "Indexable"},
            "after_data": {"http_status": 301, "indexability": "Non-Indexable"},
        },
    )
    assert original.status_code == 201, original.text
    first_status = client.post(f"/api/projects/{project['id']}/activity/{original.json()['id']}/status", json={"status": "in_progress"})
    second_status = client.post(f"/api/projects/{project['id']}/activity/{first_status.json()['id']}/status", json={"status": "completed"})
    assert second_status.status_code == 201, second_status.text

    rows = client.get(f"/api/projects/{project['id']}/activity").json()["items"]
    assert {item["title"] for item in rows} == {"HTTP status and Indexability changed · /page"}
    assert all("Status changed:" not in item["title"] for item in rows)
    assert all("Crawl metric changed:" not in item["title"] for item in rows)
    exported = client.get(f"/api/projects/{project['id']}/activity/export.csv")
    assert "Status changed: Status changed:" not in exported.text
    assert "HTTP status and Indexability changed" in exported.text
