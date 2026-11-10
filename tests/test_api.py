import json
from pathlib import Path


FIXTURE = Path(__file__).parents[1] / "sample_data" / "screaming_frog_inventory.csv"


def stage(client, project_id: str):
    with FIXTURE.open("rb") as source:
        response = client.post(
            f"/api/projects/{project_id}/imports/stage",
            data={"source": "screaming_frog"},
            files={"file": (FIXTURE.name, source, "text/csv")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def test_full_import_preserves_source_and_handles_duplicates(client, project):
    staged = stage(client, project["id"])
    assert staged["batch"]["row_count"] == 9
    assert staged["suggested_mapping"]["address"] == "Address"
    response = client.post(
        f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/confirm",
        json={"mapping": staged["suggested_mapping"], "duplicate_strategy": "update_observations"},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["imported_count"] == 7
    assert report["skipped_count"] == 1
    assert report["error_count"] == 1

    pages = client.get(f"/api/projects/{project['id']}/pages?page_size=100").json()
    assert pages["total"] == 7
    missing = next(page for page in pages["items"] if page["http_status"] == 404)
    assert missing["content_type"] == "text/html; charset=utf-8"
    assert missing["http_status_text"] == "Not Found"
    assert missing["indexability"] == "Non-Indexable"
    assert missing["indexability_status"] == "Client Error"
    assert sum(page["page_type"] == "PLP" for page in pages["items"]) == 1

    rows = client.get(f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/rows").json()
    invalid = next(row for row in rows if row["raw_data"]["Address"] == "not-a-url")
    assert invalid["status"] == "error"
    assert invalid["raw_data"]["Title 1"] == "Bad row"
    imported = next(row for row in rows if row["status"] == "imported")
    assert imported["normalized_data"]["recognized_fields"]["title_1"]


def test_manual_pages_project_isolation_bulk_edit_and_export(client, project):
    second = client.post("/api/projects", json={"name": "Second", "site_url": "https://second.example.com"}).json()
    created = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/new", "page_type": "Unknown"})
    assert created.status_code == 201
    page_id = created.json()["id"]
    assert client.get(f"/api/projects/{second['id']}/pages").json()["total"] == 0

    changed = client.patch(f"/api/projects/{project['id']}/pages/bulk-type", json={"page_ids": [page_id], "page_type": "Landing"})
    assert changed.json() == {"updated": 1}
    filtered = client.get(f"/api/projects/{project['id']}/pages?page_type=Landing").json()
    assert filtered["total"] == 1

    exported = client.get(f"/api/projects/{project['id']}/pages-export?format=csv&page_type=Landing")
    assert exported.status_code == 200
    assert "https://shop.example.com/new" in exported.text
    assert "Normalized URL" in exported.text
    assert "Status Code,Status,Indexability,Indexability Status" in exported.text


def test_page_type_assignment_filters_and_retired_product_pages_label(client, project):
    unknown = client.post(
        f"/api/projects/{project['id']}/pages",
        json={"url": "https://shop.example.com/unclassified", "page_type": "Unknown"},
    ).json()
    product = client.post(
        f"/api/projects/{project['id']}/pages",
        json={"url": "https://shop.example.com/products/blue-shirt", "page_type": "PDP"},
    )
    assert product.status_code == 201
    retired = client.post(
        f"/api/projects/{project['id']}/pages",
        json={"url": "https://shop.example.com/products/old-label", "page_type": "Product Pages"},
    )
    assert retired.status_code == 422

    assigned = client.get(f"/api/projects/{project['id']}/pages?classification=assigned").json()
    assert assigned["total"] == 1
    assert assigned["items"][0]["page_type"] == "PDP"

    unassigned = client.get(f"/api/projects/{project['id']}/pages?classification=unassigned").json()
    assert unassigned["total"] == 1
    assert unassigned["items"][0]["id"] == unknown["id"]

    typed = client.get(f"/api/projects/{project['id']}/pages?page_type=PDP").json()
    assert typed["total"] == 1
    assert typed["items"][0]["original_url"].endswith("/products/blue-shirt")

    exported = client.get(f"/api/projects/{project['id']}/pages-export?classification=assigned")
    assert "https://shop.example.com/products/blue-shirt" in exported.text
    assert "https://shop.example.com/unclassified" not in exported.text

    changed = client.patch(
        f"/api/projects/{project['id']}/pages/bulk-type",
        json={"page_ids": [unknown["id"]], "page_type": "PDP"},
    )
    assert changed.json() == {"updated": 1}
    assert client.get(f"/api/projects/{project['id']}/pages?classification=unassigned").json()["total"] == 0


def test_multi_type_url_exports_and_selected_url_download(client, project):
    created = []
    for path, page_type in (("/category", "PLP"), ("/product", "PDP"), ("/unknown", "Unknown")):
        created.append(client.post(f"/api/projects/{project['id']}/pages", json={"url": f"https://shop.example.com{path}", "page_type": page_type}).json())

    filtered = client.get(
        f"/api/projects/{project['id']}/pages",
        params=[("page_types", "PLP"), ("page_types", "PDP")],
    ).json()
    assert filtered["total"] == 2
    assert {item["page_type"] for item in filtered["items"]} == {"PLP", "PDP"}

    urls = client.get(
        f"/api/projects/{project['id']}/pages-urls",
        params=[("page_types", "PLP"), ("page_types", "PDP")],
    ).json()
    assert urls["count"] == 2
    assert urls["urls"] == ["https://shop.example.com/category", "https://shop.example.com/product"]

    selected = client.get(
        f"/api/projects/{project['id']}/pages-urls",
        params=[("format", "txt"), ("page_ids", created[1]["id"])],
    )
    assert selected.status_code == 200
    assert selected.text == "https://shop.example.com/product\n"
    assert "page-urls.txt" in selected.headers["content-disposition"]


def test_reimport_preserves_page_type_and_logs_only_supplied_crawl_changes(client, project):
    page = client.post(
        f"/api/projects/{project['id']}/pages",
        json={"url": "https://shop.example.com/products/blue-shirt", "page_type": "PDP"},
    ).json()

    first_csv = b"Address,Status Code,Status,Indexability,Indexability Status,Content Type\nhttps://shop.example.com/products/blue-shirt,200,OK,Indexable,,text/html; charset=utf-8\n"
    first_stage = client.post(
        f"/api/projects/{project['id']}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": ("crawl-one.csv", first_csv, "text/csv")},
    ).json()
    first_confirm = client.post(
        f"/api/projects/{project['id']}/imports/{first_stage['batch']['id']}/confirm",
        json={"mapping": first_stage["suggested_mapping"]},
    )
    assert first_confirm.status_code == 200, first_confirm.text

    second_csv = b"Address,Status Code,Status\nhttps://shop.example.com/products/blue-shirt,301,Moved Permanently\n"
    second_stage = client.post(
        f"/api/projects/{project['id']}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": ("crawl-two.csv", second_csv, "text/csv")},
    ).json()
    second_confirm = client.post(
        f"/api/projects/{project['id']}/imports/{second_stage['batch']['id']}/confirm",
        json={"mapping": second_stage["suggested_mapping"]},
    )
    assert second_confirm.status_code == 200, second_confirm.text

    refreshed = client.get(f"/api/projects/{project['id']}/pages/{page['id']}").json()
    assert refreshed["page_type"] == "PDP"
    assert refreshed["http_status"] == 301
    assert refreshed["http_status_text"] == "Moved Permanently"
    assert refreshed["indexability"] == "Indexable"
    assert refreshed["content_type"] == "text/html; charset=utf-8"

    history = client.get(f"/api/projects/{project['id']}/pages/{page['id']}/changes").json()
    assert len(history) == 2
    assert history[0]["changes"] == {
        "http_status": {"label": "Status Code", "from": 200, "to": 301},
        "http_status_text": {"label": "Status", "from": "OK", "to": "Moved Permanently"},
    }
    assert history[0]["source_label"].startswith("crawl-two.csv")

    bundle = client.get(f"/api/projects/{project['id']}/export").json()
    assert len(bundle["page_crawl_changes"]) == 2
    restored = client.post(
        "/api/projects/import",
        files={"file": ("change-history.seo-project.json", json.dumps(bundle).encode(), "application/json")},
    ).json()
    restored_pages = client.get(f"/api/projects/{restored['id']}/pages?page_size=100").json()["items"]
    restored_page = next(item for item in restored_pages if item["normalized_url"].endswith("/products/blue-shirt"))
    restored_history = client.get(f"/api/projects/{restored['id']}/pages/{restored_page['id']}/changes").json()
    assert len(restored_history) == 2


def test_duplicate_manual_identity_is_not_silently_merged(client, project):
    payload = {"url": "https://shop.example.com/shoes/?utm_source=email", "page_type": "PLP"}
    assert client.post(f"/api/projects/{project['id']}/pages", json=payload).status_code == 201
    duplicate = client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/shoes", "page_type": "PLP"})
    assert duplicate.status_code == 409


def test_dashboard_uses_persisted_values(client, project):
    client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/", "page_type": "Homepage"})
    client.post(f"/api/projects/{project['id']}/pages", json={"url": "https://shop.example.com/unknown", "page_type": "Unknown"})
    result = client.get(f"/api/projects/{project['id']}/dashboard").json()
    assert result["total_pages"] == 2
    assert result["unknown_pages"] == 1
    assert result["by_type"]["Homepage"] == 1


def test_non_exact_screaming_frog_headers_require_explicit_verification(client, project):
    content = b"address,status code,Indexability\nhttps://shop.example.com/verified,200,Indexable\n"
    staged_response = client.post(
        f"/api/projects/{project['id']}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": ("variant.csv", content, "text/csv")},
    )
    assert staged_response.status_code == 201
    staged = staged_response.json()
    assert staged["requires_header_verification"] is True
    assert staged["suggested_mapping"]["address"] == "address"
    assert any(item["confidence"] == "possible" for item in staged["header_recognition"])

    endpoint = f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/confirm"
    rejected = client.post(endpoint, json={"mapping": staged["suggested_mapping"], "headers_verified": False})
    assert rejected.status_code == 422
    assert "verify" in rejected.json()["detail"].lower()

    accepted = client.post(endpoint, json={"mapping": staged["suggested_mapping"], "headers_verified": True})
    assert accepted.status_code == 200
    assert accepted.json()["imported_count"] == 1


def test_project_bundle_round_trip_archive_visibility_and_permanent_delete(client, project):
    staged = stage(client, project["id"])
    imported = client.post(
        f"/api/projects/{project['id']}/imports/{staged['batch']['id']}/confirm",
        json={"mapping": staged["suggested_mapping"]},
    )
    assert imported.status_code == 200

    downloaded = client.get(f"/api/projects/{project['id']}/export")
    assert downloaded.status_code == 200
    assert "seo-project.json" in downloaded.headers["content-disposition"]
    bundle = downloaded.json()
    assert bundle["format"] == "seo-data-workspace-project"
    assert len(bundle["pages"]) == 7
    assert len(bundle["import_rows"]) == 9

    restored_response = client.post(
        "/api/projects/import",
        files={"file": ("shop.seo-project.json", downloaded.content, "application/json")},
    )
    assert restored_response.status_code == 201, restored_response.text
    restored = restored_response.json()
    assert restored["id"] != project["id"]
    assert restored["archived"] is False
    assert client.get(f"/api/projects/{restored['id']}/pages?page_size=100").json()["total"] == 7
    restored_imports = client.get(f"/api/projects/{restored['id']}/imports").json()
    restored_rows = client.get(f"/api/projects/{restored['id']}/imports/{restored_imports[0]['id']}/rows").json()
    assert len(restored_rows) == 9
    assert restored_rows[0]["raw_data"]

    archived = client.patch(f"/api/projects/{restored['id']}", json={"archived": True})
    assert archived.status_code == 200
    assert all(item["id"] != restored["id"] for item in client.get("/api/projects").json())
    assert any(item["id"] == restored["id"] and item["archived"] for item in client.get("/api/projects?include_archived=true").json())

    rejected = client.delete(f"/api/projects/{restored['id']}?confirm_name=wrong")
    assert rejected.status_code == 422
    deleted = client.delete(f"/api/projects/{restored['id']}?confirm_name={restored['name']}")
    assert deleted.status_code == 200
    assert deleted.json()["pages_deleted"] == 7
    assert all(item["id"] != restored["id"] for item in client.get("/api/projects?include_archived=true").json())
    assert client.get(f"/api/projects/{project['id']}/pages?page_size=100").json()["total"] == 7
