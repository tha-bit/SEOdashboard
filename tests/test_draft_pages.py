def import_screaming_frog(client, project_id: str, content: bytes, name: str, duplicate_strategy: str = "update_observations"):
    staged_response = client.post(
        f"/api/projects/{project_id}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": (name, content, "text/csv")},
    )
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    confirmed = client.post(
        f"/api/projects/{project_id}/imports/{staged['batch']['id']}/confirm",
        json={
            "mapping": staged["suggested_mapping"],
            "headers_verified": staged["requires_header_verification"],
            "duplicate_strategy": duplicate_strategy,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_draft_page_is_plannable_hidden_from_live_inventory_and_promoted_in_place(client, project):
    created = client.post(
        f"/api/projects/{project['id']}/strategy/draft-pages",
        json={"url": "https://shop.example.com/future/category"},
    )
    assert created.status_code == 201, created.text
    draft = created.json()

    groups = client.get(f"/api/projects/{project['id']}/strategy/groups").json()
    group = next(item for item in groups if item["id"] == draft["group_id"])
    assert group["target"]["page_id"] == draft["page_id"]
    assert group["target"]["page_type"] == "Draft"
    assert group["target"]["planned_page"] is True
    assert group["target"]["planned_action"] == "create_new"

    pages = client.get(f"/api/projects/{project['id']}/pages", params={"page_size": 100}).json()
    architecture = client.get(f"/api/projects/{project['id']}/architecture/inventory", params={"page_size": 100}).json()
    on_page = client.get(
        f"/api/projects/{project['id']}/on-page/pages",
        params=[("page_types", "Draft"), ("page_size", 100)],
    ).json()
    assert pages["total"] == 0
    assert architecture["total"] == 0
    assert on_page["total"] == 1
    assert on_page["items"][0]["id"] == draft["page_id"]

    recommendation = {
        "data": {
            "title": "Future category title",
            "meta_description": "A planned description that must survive launch.",
            "h1": ["Future category"],
            "canonical_url": "https://shop.example.com/future/category",
        },
        "review_status": "approved",
        "notes": "Approved before launch",
        "reviewer": "SEO owner",
    }
    saved = client.put(
        f"/api/projects/{project['id']}/on-page/pages/{draft['page_id']}/recommendation",
        json=recommendation,
    )
    assert saved.status_code == 200, saved.text

    keywords = client.post(
        f"/api/projects/{project['id']}/strategy/groups/{draft['group_id']}/members/manual",
        json={
            "entries": [
                {"keyword": "future category", "volume": 1200},
                {"keyword": "new category products", "volume": 450},
            ],
            "first_as_primary": True,
        },
    )
    assert keywords.status_code == 200, keywords.text
    action = client.put(
        f"/api/projects/{project['id']}/strategy/groups/{draft['group_id']}/target",
        json={"page_id": draft["page_id"], "status": "approved", "planned_action": "leave_as_is"},
    )
    assert action.status_code == 200, action.text

    import_screaming_frog(
        client,
        project["id"],
        b"Address,Page Type,Status Code,Status,Content Type,Title 1\nhttps://shop.example.com/future/category/,PLP,301,Moved Permanently,text/html,Redirected title\n",
        "redirect.csv",
    )
    after_redirect = client.get(f"/api/projects/{project['id']}/on-page/pages/{draft['page_id']}").json()
    assert after_redirect["page_type"] == "Draft"

    import_screaming_frog(
        client,
        project["id"],
        b"Address,Page Type,Status Code,Status,Title 1\nhttps://shop.example.com/future/category/,PLP,200,OK,Incomplete crawl title\n",
        "incomplete.csv",
    )
    after_incomplete = client.get(f"/api/projects/{project['id']}/on-page/pages/{draft['page_id']}").json()
    assert after_incomplete["page_type"] == "Draft"

    import_screaming_frog(
        client,
        project["id"],
        b"Address,Page Type,Status Code,Status,Content Type,Indexability,Title 1,Meta Description 1,H1-1\nhttps://shop.example.com/future/category/,PLP,200,OK,text/html; charset=utf-8,Indexable,Live category title,Live category description,Live category H1\n",
        "live.csv",
        duplicate_strategy="skip",
    )

    live_pages = client.get(f"/api/projects/{project['id']}/pages", params={"page_size": 100}).json()
    live_architecture = client.get(f"/api/projects/{project['id']}/architecture/inventory", params={"page_size": 100}).json()
    detail = client.get(f"/api/projects/{project['id']}/on-page/pages/{draft['page_id']}").json()
    refreshed_group = next(item for item in client.get(f"/api/projects/{project['id']}/strategy/groups").json() if item["id"] == draft["group_id"])

    assert live_pages["total"] == 1
    assert live_pages["items"][0]["id"] == draft["page_id"]
    assert live_pages["items"][0]["page_type"] == "PLP"
    assert live_architecture["total"] == 1
    assert live_architecture["items"][0]["id"] == draft["page_id"]
    assert detail["page_type"] == "PLP"
    assert detail["current"]["title"] == "Live category title"
    assert detail["recommendation"]["data"]["title"] == "Future category title"
    assert detail["recommendation"]["data"]["h1"] == ["Future category"]
    assert refreshed_group["target"]["page_id"] == draft["page_id"]
    assert refreshed_group["target"]["page_type"] == "PLP"
    assert refreshed_group["target"]["planned_page"] is False
    assert refreshed_group["target"]["planned_action"] == "leave_as_is"
    assert {item["keyword"] for item in refreshed_group["members"]} == {"future category", "new category products"}
    changes = client.get(f"/api/projects/{project['id']}/pages/{draft['page_id']}/changes").json()
    assert changes[0]["changes"]["page_type"] == {"label": "Page Type", "from": "Draft", "to": "PLP"}


def test_draft_url_identity_respects_trailing_slash_but_not_distinct_queries(client, project):
    first = client.post(
        f"/api/projects/{project['id']}/strategy/draft-pages",
        json={"url": "https://shop.example.com/planned"},
    )
    assert first.status_code == 201
    trailing_duplicate = client.post(
        f"/api/projects/{project['id']}/strategy/draft-pages",
        json={"url": "https://shop.example.com/planned/"},
    )
    assert trailing_duplicate.status_code == 409
    query_variant = client.post(
        f"/api/projects/{project['id']}/strategy/draft-pages",
        json={"url": "https://shop.example.com/planned?variant=one"},
    )
    assert query_variant.status_code == 201
    assert query_variant.json()["page_id"] != first.json()["page_id"]


def test_successful_non_html_crawl_does_not_promote_draft(client, project):
    draft = client.post(
        f"/api/projects/{project['id']}/strategy/draft-pages",
        json={"url": "https://shop.example.com/future-feed"},
    ).json()
    import_screaming_frog(
        client,
        project["id"],
        b"Address,Status Code,Content Type\nhttps://shop.example.com/future-feed,200,application/json\n",
        "non-html.csv",
    )
    detail = client.get(f"/api/projects/{project['id']}/on-page/pages/{draft['page_id']}").json()
    assert detail["page_type"] == "Draft"
    assert client.get(f"/api/projects/{project['id']}/pages", params={"page_size": 100}).json()["total"] == 0
