import json


def import_csv(client, project_id: str, content: bytes, name: str = "semrush.csv"):
    staged_response = client.post(f"/api/projects/{project_id}/imports/stage", data={"source": "semrush"}, files={"file": (name, content, "text/csv")})
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    response = client.post(f"/api/projects/{project_id}/imports/{staged['batch']['id']}/confirm", json={"mapping": staged["suggested_mapping"]})
    assert response.status_code == 200, response.text


def import_screaming_frog(client, project_id: str, content: bytes, name: str = "crawl.csv"):
    staged_response = client.post(f"/api/projects/{project_id}/imports/stage", data={"source": "screaming_frog"}, files={"file": (name, content, "text/csv")})
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    response = client.post(f"/api/projects/{project_id}/imports/{staged['batch']['id']}/confirm", json={"mapping": staged["suggested_mapping"], "headers_verified": staged["requires_header_verification"]})
    assert response.status_code == 200, response.text


def import_performance_source(client, project_id: str, source: str, content: bytes, name: str):
    staged_response = client.post(f"/api/projects/{project_id}/imports/stage", data={"source": source}, files={"file": (name, content, "text/csv")})
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    response = client.post(f"/api/projects/{project_id}/imports/{staged['batch']['id']}/confirm", json={"mapping": staged["suggested_mapping"]})
    assert response.status_code == 200, response.text


def test_deterministic_assignments_separate_intent_and_require_approval(client, project):
    client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/women/shoes", "page_type": "PLP"})
    content = b"Keyword,Volume,KD %,Position,Intent,URL,Date\nwomens shoes,3000,45,4,Commercial,https://shop.example.com/women/shoes,2026-11-01\nladies shoe,1800,40,7,Transactional,https://shop.example.com/women/shoes,2026-11-01\nbest shoes guide,900,35,12,Informational,https://shop.example.com/blog/best-shoes,2026-11-01\n"
    import_csv(client, project["id"], content)
    generated = client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate").json()
    assert generated["groups_created"] == 2
    groups = client.get(f"/api/projects/{project['id']}/strategy/groups").json()
    commercial = next(group for group in groups if group["keyword_count"] == 2)
    informational = next(group for group in groups if group["keyword_count"] == 1)
    assert commercial["target"]["url"] == "https://shop.example.com/women/shoes"
    assert commercial["target"]["status"] == "suggested"
    assert commercial["status"] == "suggested"
    assert informational["intent"] == "informational"
    assert client.post(f"/api/projects/{project['id']}/strategy/groups/{commercial['id']}/approve?reviewer=Alex").status_code == 200
    assert client.put(f"/api/projects/{project['id']}/strategy/groups/{commercial['id']}/target", json={"page_id": commercial["target"]["page_id"], "status": "approved", "reviewer": "Alex", "rationale": "Primary category page"}).status_code == 200
    summary = client.get(f"/api/projects/{project['id']}/strategy/summary").json()
    assert summary["mapped_keywords"] == 2
    assert summary["approved_targets"] == 1


def test_new_import_does_not_overwrite_approved_target(client, project):
    page = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    import_csv(client, project["id"], b"Keyword,Volume,Position,Intent,URL,Date\nrunning shoes,1000,5,Commercial,https://shop.example.com/shoes,2026-10-01\n")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    group = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    client.post(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/approve")
    client.put(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/target", json={"page_id": page["id"], "status": "approved", "reviewer": "Owner"})
    import_csv(client, project["id"], b"Keyword,Volume,Position,Intent,URL,Date\nrunning shoes,1200,2,Commercial,https://shop.example.com/sale,2026-11-01\n", "november.csv")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    refreshed = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    assert refreshed["target"]["url"] == "https://shop.example.com/shoes"
    assert refreshed["target"]["status"] == "approved"


def test_approved_membership_still_refreshes_unapproved_target_from_new_rankings(client, project):
    first = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    second = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/sale", "page_type": "PLP"}).json()
    import_csv(client, project["id"], b"Keyword,Volume,Position,Intent,URL,Date\nrunning shoes,1000,5,Commercial,https://shop.example.com/shoes,2026-10-01\n")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    group = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    client.post(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/approve")
    assert group["target"]["page_id"] == first["id"]
    assert group["target"]["status"] == "suggested"

    import_csv(client, project["id"], b"Keyword,Volume,Position,Intent,URL,Date\nrunning shoes,1200,2,Commercial,https://shop.example.com/sale,2026-11-01\n", "november.csv")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    refreshed = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    assert refreshed["status"] == "approved"
    assert refreshed["target"]["status"] == "suggested"
    assert refreshed["target"]["page_id"] == second["id"]
    assert refreshed["target"]["url"] == "https://shop.example.com/sale"


def test_page_mapping_persists_focus_action_metadata_and_feeds_mismatch_scan(client, project):
    import_screaming_frog(client, project["id"], b"Address,Page Type,Status Code,Indexability,Title 1,Meta Description 1,H1-1,Canonical Link Element 1,Meta Robots 1\nhttps://shop.example.com/shoes,PLP,200,Indexable,Running shoes,Shop running shoes,Running shoes,https://shop.example.com/shoes,index follow\n")
    import_csv(client, project["id"], b"Keyword,Volume,KD %,Position,Intent,URL,Database,Device,Date\nrunning shoes,1000,45,5,Commercial,https://shop.example.com/shoes,UK,Desktop,2026-10-01\ncheap running shoes,2500,62,9,Commercial,https://shop.example.com/shoes,UK,Desktop,2026-10-01\n")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    group = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    focus = next(member for member in group["members"] if member["keyword"] == "running shoes")
    page_id = group["target"]["page_id"]
    saved = client.put(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/target", json={"page_id": page_id, "status": "approved", "planned_action": "leave_as_is", "focus_keyword_id": focus["id"], "reviewer": "Alex"})
    assert saved.status_code == 200, saved.text

    refreshed = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    assert refreshed["primary_keyword_id"] == focus["id"]
    assert refreshed["target"]["planned_action"] == "leave_as_is"
    assert refreshed["target"]["metadata"]["title"] == "Running shoes"
    assert refreshed["target"]["metadata"]["h1"] == ["Running shoes"]
    assert {member["keyword"]: member["role"] for member in refreshed["members"]} == {"running shoes": "primary", "cheap running shoes": "supporting"}

    export = client.get(f"/api/projects/{project['id']}/strategy/exports/page-map")
    assert export.status_code == 200
    assert "Planned Action" in export.text
    assert "leave_as_is" in export.text
    assert "Running shoes" in export.text

    import_csv(client, project["id"], b"Keyword,Volume,KD %,Position,Intent,URL,Database,Device,Date\nrunning shoes,1000,45,4,Commercial,https://shop.example.com/sale,UK,Desktop,2026-11-01\n", "november.csv")
    scan = client.post(f"/api/projects/{project['id']}/strategy/cannibalization/scan")
    assert scan.status_code == 200
    cases = client.get(f"/api/projects/{project['id']}/strategy/cannibalization/cases").json()
    mismatch = next(item for item in cases if item["case_type"] == "ranking_target_mismatch")
    assert mismatch["evidence"]["approved_target"]["planned_action"] == "leave_as_is"
    assert mismatch["evidence"]["mismatches"][0]["ranking_url"] == "https://shop.example.com/sale"


def test_page_mapping_members_can_be_promoted_and_removed_without_deleting_keywords(client, project):
    import_csv(client, project["id"], b"Keyword,Volume,KD %,Position,Intent,URL,Date\nrunning shoes,1000,45,5,Commercial,https://shop.example.com/shoes,2026-11-01\ncheap running shoes,700,38,8,Commercial,https://shop.example.com/shoes,2026-11-01\n")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    group = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    supporting = next(member for member in group["members"] if member["id"] != group["primary_keyword_id"])

    promoted = client.post(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/members", json={"keyword_ids": [supporting["id"]], "role": "primary", "status": "approved", "reviewer": "Alex"})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["primary_keyword_id"] == supporting["id"]
    refreshed = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    assert {member["id"]: member["role"] for member in refreshed["members"]}[supporting["id"]] == "primary"
    assert sum(member["role"] == "primary" for member in refreshed["members"]) == 1

    removed = client.delete(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/members/{supporting['id']}?reviewer=Alex")
    assert removed.status_code == 200, removed.text
    assert removed.json()["remaining_members"] == 1
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    refreshed = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    assert supporting["id"] not in {member["id"] for member in refreshed["members"]}
    assert refreshed["primary_keyword_id"] == refreshed["members"][0]["id"]
    assert supporting["id"] in {keyword["id"] for keyword in client.get(f"/api/projects/{project['id']}/keywords").json()}
    history = client.get(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/history").json()
    assert any(item["action"] == "member_removed" for item in history)


def test_page_mapping_bulk_manual_keywords_reuse_existing_terms_and_record_volume(client, project):
    import_csv(client, project["id"], b"Keyword,Volume,KD %,Position,Intent,URL,Date\nrunning shoes,1000,45,5,Commercial,https://shop.example.com/shoes,2026-11-01\ncheap running shoes,700,38,8,Commercial,https://shop.example.com/shoes,2026-11-01\n")
    client.post(f"/api/projects/{project['id']}/strategy/suggestions/generate")
    group = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    existing = next(member for member in group["members"] if member["keyword"] == "running shoes")

    response = client.post(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/members/manual", json={"entries": [{"keyword": "blue running shoes", "volume": 450}, {"keyword": "running shoes", "volume": 1250}], "first_as_primary": True, "reviewer": "Alex"})
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1
    assert response.json()["updated"] == 2

    refreshed = client.get(f"/api/projects/{project['id']}/strategy/groups").json()[0]
    by_phrase = {member["keyword"]: member for member in refreshed["members"]}
    assert by_phrase["blue running shoes"]["role"] == "primary"
    assert by_phrase["blue running shoes"]["volume"] == 450
    assert by_phrase["running shoes"]["id"] == existing["id"]
    assert by_phrase["running shoes"]["volume"] == 1250
    assert len(client.get(f"/api/projects/{project['id']}/keywords").json()) == 3
    history = client.get(f"/api/projects/{project['id']}/strategy/groups/{group['id']}/history").json()
    assert any(item["action"] == "manual_keywords_assigned" for item in history)


def test_cannibalization_cases_decisions_exports_and_bundle_round_trip(client, project):
    content = b"Keyword,Volume,Position,Intent,URL,Database,Device,Date\nrunning shoes,1000,5,Commercial,https://shop.example.com/shoes,UK,Desktop,2026-11-01\nrunning shoes,1000,8,Commercial,https://shop.example.com/sale,UK,Desktop,2026-11-01\n"
    import_csv(client, project["id"], content)
    first = client.post(f"/api/projects/{project['id']}/strategy/cannibalization/scan").json()
    second = client.post(f"/api/projects/{project['id']}/strategy/cannibalization/scan").json()
    assert first["created"] == 1
    assert second["created"] == 0
    cases = client.get(f"/api/projects/{project['id']}/strategy/cannibalization/cases").json()
    assert len(cases) == 1
    assert cases[0]["case_type"] == "exact_query_multi_url"
    assert cases[0]["unknowns"]
    decision = client.post(f"/api/projects/{project['id']}/strategy/cannibalization/cases/{cases[0]['id']}/decision", json={"status": "resolved", "action": "Keep category as preferred", "preferred_url": "https://shop.example.com/shoes", "reviewer": "Alex", "notes": "Sale URL will be consolidated"})
    assert decision.status_code == 200
    assert decision.json()["decision_history"][0]["reviewer"] == "Alex"
    export = client.get(f"/api/projects/{project['id']}/strategy/exports/cannibalization")
    assert export.status_code == 200
    assert "Keep category as preferred" in export.text
    bundle = client.get(f"/api/projects/{project['id']}/export").json()
    restored = client.post("/api/projects/import", files={"file": ("strategy.seo-project.json", json.dumps(bundle).encode(), "application/json")})
    assert restored.status_code == 201, restored.text
    restored_cases = client.get(f"/api/projects/{restored.json()['id']}/strategy/cannibalization/cases").json()
    assert restored_cases[0]["status"] == "resolved"
    assert restored_cases[0]["decision_history"][0]["reviewer"] == "Alex"


def test_cannibalization_findings_join_keyword_gsc_and_ga4_metrics(client, project):
    first = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    second = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/sale", "page_type": "PLP"}).json()
    import_csv(client, project["id"], b"Keyword,Volume,Position,Intent,URL,Database,Device,Date\nrunning shoes,1000,5,Commercial,https://shop.example.com/shoes,UK,Desktop,2026-11-01\nrunning shoes,1000,8,Commercial,https://shop.example.com/sale,UK,Desktop,2026-11-01\n")
    import_performance_source(client, project["id"], "gsc", b"Query,Page,Clicks,Impressions,CTR,Position,Country,Device,Start Date,End Date\nrunning shoes,https://shop.example.com/shoes,820,12500,6.56%,4.2,UK,Desktop,2026-10-01,2026-10-31\nrunning shoes,https://shop.example.com/sale,145,5400,2.69%,9.8,UK,Desktop,2026-10-01,2026-10-31\n", "gsc.csv")
    import_performance_source(client, project["id"], "ga4", b"Landing page,Sessions,Engaged sessions,Conversions,Start Date,End Date\nhttps://shop.example.com/shoes,1400,900,80,2026-10-01,2026-10-31\nhttps://shop.example.com/sale,620,350,22,2026-10-01,2026-10-31\n", "ga4.csv")
    client.post(f"/api/projects/{project['id']}/strategy/cannibalization/scan")
    case = next(item for item in client.get(f"/api/projects/{project['id']}/strategy/cannibalization/cases").json() if item["case_type"] == "exact_query_multi_url")
    finding = case["findings"][0]
    assert finding["keyword"] == "running shoes"
    assert finding["search_volume"] == 1000
    assert finding["classification"] == "potential_cannibalization"
    by_url = {item["url"]: item for item in finding["urls"]}
    assert by_url["https://shop.example.com/shoes"]["page_id"] == first["id"]
    assert by_url["https://shop.example.com/shoes"]["gsc_clicks"] == 820
    assert by_url["https://shop.example.com/shoes"]["ga4_sessions"] == 1400
    assert by_url["https://shop.example.com/sale"]["page_id"] == second["id"]
    assert by_url["https://shop.example.com/sale"]["gsc_impressions"] == 5400


def test_multiple_approved_keyword_targets_are_labelled_as_overlap(client, project):
    first = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"}).json()
    second = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/running", "page_type": "PLP"}).json()
    import_csv(client, project["id"], b"Keyword,Volume,Intent,Database\nrunning shoes,1000,Commercial,UK\n")
    keyword_id = client.get(f"/api/projects/{project['id']}/keywords").json()[0]["id"]
    first_group = client.post(f"/api/projects/{project['id']}/strategy/groups", json={"name": "Shoes", "keyword_ids": [keyword_id], "intent": "Commercial"}).json()
    second_group = client.post(f"/api/projects/{project['id']}/strategy/groups", json={"name": "Running", "keyword_ids": [keyword_id], "intent": "Commercial"}).json()
    assert client.put(f"/api/projects/{project['id']}/strategy/groups/{first_group['id']}/target", json={"page_id": first["id"], "status": "approved", "reviewer": "Alex"}).status_code == 200
    assert client.put(f"/api/projects/{project['id']}/strategy/groups/{second_group['id']}/target", json={"page_id": second["id"], "status": "approved", "reviewer": "Alex"}).status_code == 200
    client.post(f"/api/projects/{project['id']}/strategy/cannibalization/scan")
    overlap = next(item for item in client.get(f"/api/projects/{project['id']}/strategy/cannibalization/cases").json() if item["case_type"] == "approved_keyword_multi_target")
    assert overlap["findings"][0]["classification"] == "keyword_overlap"
    assert {item["url"] for item in overlap["findings"][0]["urls"]} == {"https://shop.example.com/shoes", "https://shop.example.com/running"}
