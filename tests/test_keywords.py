import json


def import_csv(client, project_id: str, source: str, name: str, content: bytes, reporting_date: str | None = None):
    data = {"source": source}
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
        json={"mapping": staged["suggested_mapping"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return staged, confirmed.json()


def test_semrush_multiple_urls_score_once_and_preserve_metric_history(client, project):
    first = b"Keyword,Volume,KD %,Position,Intent,URL,Database,Device,Date\nrunning shoes,12000,62,7,Commercial,https://shop.example.com/shoes,UK,Desktop,2026-10-01\nrunning shoes,12000,62,12,Commercial,https://shop.example.com/sale-shoes,UK,Desktop,2026-10-01\ntrail shoes,0,,45,Transactional,,UK,Mobile,2026-10-01\n"
    import_csv(client, project["id"], "semrush", "semrush-october.csv", first)
    rows = client.get(f"/api/projects/{project['id']}/keywords").json()
    assert len(rows) == 2
    running = next(item for item in rows if item["keyword"] == "running shoes")
    assert running["volume"] == 12000
    assert running["best_semrush_position"] == 7
    assert running["rank_band"] == "Quick Win"
    assert running["ranking_url_count"] == 2
    assert running["opportunity"]["provisional"] is True
    trail = next(item for item in rows if item["keyword"] == "trail shoes")
    assert trail["volume"] == 0
    assert trail["keyword_difficulty"] is None

    second = b"Keyword,Volume,KD %,Position,Intent,URL,Database,Device,Date\nrunning shoes,14000,58,4,Commercial,https://shop.example.com/shoes,UK,Desktop,2026-11-01\n"
    import_csv(client, project["id"], "semrush", "semrush-november.csv", second)
    detail = client.get(f"/api/projects/{project['id']}/keywords/{running['id']}").json()
    assert [item["volume"] for item in detail["metric_history"]] == [14000, 12000]
    assert [item["position"] for item in detail["ranking_history"]] == [4, 7, 12]
    assert detail["metric_history"][0]["source"] == "semrush-november.csv"


def test_keyword_research_reports_every_current_url_and_manual_saved_keywords(client, project):
    first_page = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/sale-shoes", "page_type": "PLP"})
    semrush = b"Keyword,Volume,KD %,Position,Intent,URL,Date\nrunning shoes,1000,45,5,Commercial,https://shop.example.com/shoes,2026-11-01\nrunning shoes,1000,45,9,Commercial,https://shop.example.com/sale-shoes,2026-11-01\n"
    import_csv(client, project["id"], "semrush", "positions.csv", semrush)
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    group = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    client.put(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/target", json={"page_id": first_page["id"], "status": "suggested"})

    keyword = client.get(f"/api/projects/{project['id']}/keywords").json()[0]
    assert keyword["associated_url_count"] == 2
    assert keyword["assigned_url_count"] == 1
    assert {item["url"] for item in keyword["url_associations"]} == {"https://shop.example.com/shoes", "https://shop.example.com/sale-shoes"}
    mapped = next(item for item in keyword["url_associations"] if item["url"] == "https://shop.example.com/shoes")
    assert mapped["mapped"] is True
    assert mapped["semrush"] is True
    assert mapped["mapping_statuses"] == ["suggested"]

    saved = client.post(f"/api/projects/{project['id']}/keywords", json={"entries": [{"keyword": "shoe care guide", "volume": 320, "keyword_difficulty": 27}, {"keyword": "running shoes", "volume": 1100}]})
    assert saved.status_code == 201, saved.text
    assert saved.json()["created"] == 1
    rows = client.get(f"/api/projects/{project['id']}/keywords").json()
    manual = next(item for item in rows if item["keyword"] == "shoe care guide")
    assert manual["volume"] == 320
    assert manual["keyword_difficulty"] == 27
    assert manual["associated_url_count"] == 0
    assert manual["assigned_url_count"] == 0
    assert len([item for item in rows if item["keyword"] == "running shoes"]) == 1

    edited = client.patch(f"/api/projects/{project['id']}/keywords/{manual['id']}/details", json={"keyword": "shoe care advice", "volume": 450, "keyword_difficulty": 31.5, "intents": ["Informational", "Commercial"]})
    assert edited.status_code == 200, edited.text
    assert edited.json()["keyword"] == "shoe care advice"
    assert edited.json()["volume"] == 450
    assert edited.json()["keyword_difficulty"] == 31.5
    assert edited.json()["intents"] == ["Informational", "Commercial"]

    deleted = client.delete(f"/api/projects/{project['id']}/keywords/{manual['id']}")
    assert deleted.status_code == 200, deleted.text
    assert manual["id"] not in {item["id"] for item in client.get(f"/api/projects/{project['id']}/keywords").json()}


def test_delete_keyword_removes_empty_mapping_group_and_dependent_evidence(client, project):
    client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"})
    import_csv(client, project["id"], "semrush", "positions.csv", b"Keyword,Volume,Position,Intent,URL,Date\nrunning shoes,1000,5,Commercial,https://shop.example.com/shoes,2026-11-01\n")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    keyword = client.get(f"/api/projects/{project['id']}/keywords").json()[0]
    assert len(client.get(f"/api/projects/{project['id']}/strategy/groups").json()) == 1
    deleted = client.delete(f"/api/projects/{project['id']}/keywords/{keyword['id']}")
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/projects/{project['id']}/keywords").json() == []
    assert client.get(f"/api/projects/{project['id']}/strategy/groups").json() == []


def test_gsc_query_only_never_infers_page_and_query_page_remains_separate(client, project):
    page = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    query_only = b"Top queries,Clicks,Impressions,CTR,Position,Start Date,End Date\nrunning shoes,40,1000,4%,8.2,2026-10-01,2026-10-31\n"
    staged, report = import_csv(client, project["id"], "gsc", "gsc-queries.csv", query_only)
    assert report["warnings"][-1].startswith("Query-only GSC")
    rows = client.get(f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/rows").json()
    assert rows[0]["page_id"] is None
    assert rows[0]["normalized_data"]["aggregation_type"] == "query_only"

    query_page = b"Query,Page,Clicks,Impressions,CTR,Average Position,Start Date,End Date\nrunning shoes,https://shop.example.com/shoes,25,600,4.17%,6.5,2026-11-01,2026-11-30\n"
    import_csv(client, project["id"], "gsc", "gsc-query-pages.csv", query_page)
    keyword = client.get(f"/api/projects/{project['id']}/keywords").json()[0]
    detail = client.get(f"/api/projects/{project['id']}/keywords/{keyword['id']}").json()
    assert {item["aggregation_type"] for item in detail["gsc_history"]} == {"query_only", "query_page"}
    linked = next(item for item in detail["gsc_history"] if item["aggregation_type"] == "query_page")
    assert linked["page_id"] == page["id"]
    assert linked["average_position"] == 6.5


def test_ga4_path_join_channel_warning_relevance_and_bundle_round_trip(client, project):
    page = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    ga4 = b"Landing page,Sessions,Engaged sessions,Key events,Revenue,Start Date,End Date\n/shoes,120,90,8,349.5,2026-10-01,2026-10-31\n/missing,20,5,0,,2026-10-01,2026-10-31\n"
    staged, report = import_csv(client, project["id"], "ga4", "ga4-landing-pages.csv", ga4)
    assert report["warnings"][-1].startswith("No channel filter")
    rows = client.get(f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/rows").json()
    matched = next(item for item in rows if item["raw_data"]["Landing page"] == "/shoes")
    assert matched["page_id"] == page["id"]
    assert matched["normalized_data"]["matched"] is True

    semrush = b"Keyword,Volume,KD %,Position,Intent,URL,Date\nrunning shoes,1000,50,8,Commercial,https://shop.example.com/shoes,2026-10-31\n"
    import_csv(client, project["id"], "semrush", "positions.csv", semrush)
    keyword = client.get(f"/api/projects/{project['id']}/keywords").json()[0]
    before = keyword["opportunity"]["score"]
    reviewed = client.patch(f"/api/projects/{project['id']}/keywords/{keyword['id']}/relevance", json={"product_relevance": 90, "relevance_status": "reviewed", "relevance_notes": "Strong PLP fit"})
    assert reviewed.status_code == 200
    refreshed = client.get(f"/api/projects/{project['id']}/keywords").json()[0]
    assert refreshed["opportunity"]["provisional"] is False
    assert refreshed["opportunity"]["score"] != before
    page_context = client.get(f"/api/projects/{project['id']}/keywords/pages/{page['id']}/opportunities").json()
    assert page_context["keywords"][0]["keyword"] == "running shoes"
    assert page_context["ga4_history"][0]["sessions"] == 120
    assert "overlap" in page_context["volume_warning"]

    bundle = client.get(f"/api/projects/{project['id']}/export").json()
    assert len(bundle["keywords"]) == 1
    assert len(bundle["ga4_page_performance"]) == 2
    restored = client.post("/api/projects/import", files={"file": ("phase4.seo-project.json", json.dumps(bundle).encode(), "application/json")})
    assert restored.status_code == 201, restored.text
    restored_rows = client.get(f"/api/projects/{restored.json()['id']}/keywords").json()
    assert restored_rows[0]["product_relevance"] == 90


def test_dashboard_uses_observed_health_and_latest_organic_performance(client, project):
    crawl = b"Address,Page Type,Status Code,Content Type,Indexability,Title 1\nhttps://shop.example.com/shoes,PLP,200,text/html,Indexable,\nhttps://shop.example.com/private,Other,200,text/html,Non-Indexable,Private page\n"
    import_csv(client, project["id"], "screaming_frog", "crawl.csv", crawl)

    gsc = b"Query,Page,Clicks,Impressions,CTR,Average Position,Start Date,End Date\nrunning shoes,https://shop.example.com/shoes,10,100,10%,5,2026-10-01,2026-10-31\nshoe shop,https://shop.example.com/shoes,30,300,10%,9,2026-10-01,2026-10-31\n"
    import_csv(client, project["id"], "gsc", "gsc.csv", gsc)
    ga4 = b"Landing page,Sessions,Session default channel group,Start Date,End Date\n/shoes,120,Organic Search,2026-10-01,2026-10-31\n/shoes,90,Paid Search,2026-10-01,2026-10-31\n"
    import_csv(client, project["id"], "ga4", "ga4.csv", ga4)

    dashboard = client.get(f"/api/projects/{project['id']}/dashboard").json()
    assert dashboard["total_pages"] == 2
    assert dashboard["indexable_pages"] == 1
    assert dashboard["non_indexable_pages"] == 1
    assert dashboard["indexability_observed_pages"] == 2
    assert dashboard["critical_on_page_issues"] == 1
    assert dashboard["critical_issue_count"] >= 1
    assert dashboard["organic_sessions"] == 120
    assert dashboard["organic_clicks"] == 40
    assert dashboard["organic_impressions"] == 400
    assert dashboard["average_position"] == 8
    assert dashboard["gsc_period_start"] == "2026-10-01"
    assert dashboard["ga4_period_end"] == "2026-10-31"


def test_dashboard_does_not_label_unscoped_ga4_sessions_as_organic(client, project):
    ga4 = b"Landing page,Sessions,Start Date,End Date\n/shoes,120,2026-10-01,2026-10-31\n"
    import_csv(client, project["id"], "ga4", "unscoped-ga4.csv", ga4)
    dashboard = client.get(f"/api/projects/{project['id']}/dashboard").json()
    assert dashboard["organic_sessions"] is None
    assert dashboard["ga4_period_start"] is None
