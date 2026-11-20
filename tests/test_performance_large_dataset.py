import io
import time
from fastapi.testclient import TestClient


def test_pages_pagination_sizes_and_controls(client: TestClient, project: dict):
    # Create 120 pages to test 25, 50, and 100 rows per page
    for i in range(1, 121):
        ptype = "PDP" if i % 2 == 0 else "PLP"
        res = client.post(
            f"/api/projects/{project['id']}/pages",
            json={"url": f"https://shop.example.com/items/product-{i}", "page_type": ptype},
        )
        assert res.status_code == 201

    # 1. Default page size (25)
    p25 = client.get(f"/api/projects/{project['id']}/pages?page_size=25&page=1").json()
    assert p25["total"] == 120
    assert len(p25["items"]) == 25
    assert p25["page"] == 1
    assert p25["page_size"] == 25

    # Page 2 with 25
    p25_p2 = client.get(f"/api/projects/{project['id']}/pages?page_size=25&page=2").json()
    assert len(p25_p2["items"]) == 25
    assert p25_p2["items"][0]["id"] != p25["items"][0]["id"]

    # 2. 50 rows per page
    p50 = client.get(f"/api/projects/{project['id']}/pages?page_size=50&page=1").json()
    assert p50["total"] == 120
    assert len(p50["items"]) == 50
    assert p50["page"] == 1
    assert p50["page_size"] == 50

    p50_p2 = client.get(f"/api/projects/{project['id']}/pages?page_size=50&page=2").json()
    assert len(p50_p2["items"]) == 50

    p50_p3 = client.get(f"/api/projects/{project['id']}/pages?page_size=50&page=3").json()
    assert len(p50_p3["items"]) == 20  # 120 - 100 = 20 remaining

    # 3. 100 rows per page
    p100 = client.get(f"/api/projects/{project['id']}/pages?page_size=100&page=1").json()
    assert p100["total"] == 120
    assert len(p100["items"]) == 100
    assert p100["page"] == 1
    assert p100["page_size"] == 100

    p100_p2 = client.get(f"/api/projects/{project['id']}/pages?page_size=100&page=2").json()
    assert len(p100_p2["items"]) == 20

    # 4. Filter preservation with page size
    filtered_p50 = client.get(f"/api/projects/{project['id']}/pages?page_types=PDP&page_size=50&page=1").json()
    assert filtered_p50["total"] == 60
    assert len(filtered_p50["items"]) == 50
    assert all(item["page_type"] == "PDP" for item in filtered_p50["items"])


def test_large_dataset_8000_pages_performance_and_caching(client: TestClient, project: dict):
    # Generate 8,500 URLs in Screaming Frog crawl format
    num_rows = 8500
    csv_lines = [
        "Address,Status Code,Status,Indexability,Indexability Status,Content Type,Title 1,Meta Description 1"
    ]
    for i in range(1, num_rows + 1):
        if i <= 5000:
            url = f"https://shop.example.com/products/item-{i}"
            status = 200
            status_text = "OK"
            indexability = "Indexable"
            indexability_status = ""
            content_type = "text/html; charset=UTF-8"
        elif i <= 7000:
            url = f"https://shop.example.com/categories/cat-{i}"
            status = 200
            status_text = "OK"
            indexability = "Indexable"
            indexability_status = ""
            content_type = "text/html; charset=UTF-8"
        elif i <= 8000:
            url = f"https://shop.example.com/blog/article-{i}"
            status = 200
            status_text = "OK"
            indexability = "Indexable"
            indexability_status = ""
            content_type = "text/html; charset=UTF-8"
        else:
            url = f"https://shop.example.com/assets/file-{i}.pdf"
            status = 200
            status_text = "OK"
            indexability = "Non-Indexable"
            indexability_status = "Non-HTML"
            content_type = "application/pdf"

        csv_lines.append(f"{url},{status},{status_text},{indexability},{indexability_status},{content_type},Title {i},Description {i}")

    csv_data = "\n".join(csv_lines).encode("utf-8")

    # Stage import
    stage_start = time.time()
    staged = client.post(
        f"/api/projects/{project['id']}/imports/stage",
        data={"source": "screaming_frog"},
        files={"file": ("crawl_8500.csv", io.BytesIO(csv_data), "text/csv")},
    )
    assert staged.status_code == 201, staged.text
    stage_payload = staged.json()
    batch_id = stage_payload["batch"]["id"]
    mapping = stage_payload["suggested_mapping"]
    mapping["address"] = "Address"
    mapping["http_status"] = "Status Code"
    mapping["http_status_text"] = "Status"
    mapping["indexability"] = "Indexability"
    mapping["indexability_status"] = "Indexability Status"
    mapping["content_type"] = "Content Type"
    mapping["title_1"] = "Title 1"
    mapping["meta_description_1"] = "Meta Description 1"

    # Confirm import - measure time (should complete in seconds, not freeze)
    confirm_start = time.time()
    confirm_res = client.post(
        f"/api/projects/{project['id']}/imports/{batch_id}/confirm",
        json={"mapping": mapping, "duplicate_strategy": "update_observations"},
    )
    confirm_duration = time.time() - confirm_start
    assert confirm_res.status_code == 200, confirm_res.text
    assert confirm_res.json()["imported_count"] == num_rows
    # Importing 8500 rows should take under 15 seconds with batch optimization
    assert confirm_duration < 15.0, f"Import took too long: {confirm_duration:.2f}s"

    # Query /pages with page_size=25, 50, 100 and measure response time (< 500ms)
    query_start = time.time()
    p25 = client.get(f"/api/projects/{project['id']}/pages?page_size=25&page=1")
    q25_duration = time.time() - query_start
    assert p25.status_code == 200
    assert p25.json()["total"] == num_rows
    assert len(p25.json()["items"]) == 25
    assert q25_duration < 1.0, f"Query page_size=25 took too long: {q25_duration:.2f}s"

    query_start = time.time()
    p50 = client.get(f"/api/projects/{project['id']}/pages?page_size=50&page=1")
    q50_duration = time.time() - query_start
    assert p50.status_code == 200
    assert len(p50.json()["items"]) == 50
    assert q50_duration < 1.0, f"Query page_size=50 took too long: {q50_duration:.2f}s"

    query_start = time.time()
    p100 = client.get(f"/api/projects/{project['id']}/pages?page_size=100&page=1")
    q100_duration = time.time() - query_start
    assert p100.status_code == 200
    assert len(p100.json()["items"]) == 100
    assert q100_duration < 1.0, f"Query page_size=100 took too long: {q100_duration:.2f}s"

    # Search URL filtering
    search_res = client.get(f"/api/projects/{project['id']}/pages?url_operator=contains&url_value=item-42&page_size=25")
    assert search_res.status_code == 200
    assert search_res.json()["total"] > 0
    assert all("item-42" in item["original_url"] for item in search_res.json()["items"])

    # Bulk type assignment on first 50 items
    first_50_ids = [item["id"] for item in p50.json()["items"]]
    bulk_start = time.time()
    bulk_res = client.patch(f"/api/projects/{project['id']}/pages/bulk-type", json={"page_ids": first_50_ids, "page_type": "PDP"})
    bulk_duration = time.time() - bulk_start
    assert bulk_res.status_code == 200
    assert bulk_res.json()["updated"] == 50
    assert bulk_duration < 1.0

    # In-memory cache test for architecture_issues
    # First call calculates and caches
    arch1_start = time.time()
    arch1 = client.get(f"/api/projects/{project['id']}/architecture/summary")
    arch1_duration = time.time() - arch1_start
    assert arch1.status_code == 200

    # Second call uses cache and returns near-instantly (< 100ms)
    arch2_start = time.time()
    arch2 = client.get(f"/api/projects/{project['id']}/architecture/summary")
    arch2_duration = time.time() - arch2_start
    assert arch2.status_code == 200
    assert arch2_duration < 0.2, f"Cached architecture summary took too long: {arch2_duration:.2f}s"

    # Manual override invalidates cache
    one_id = first_50_ids[0]
    override_res = client.patch(
        f"/api/projects/{project['id']}/pages/{one_id}/manual-overrides",
        json={"values": {"http_status": 404, "http_status_text": "Not Found"}},
    )
    assert override_res.status_code == 200
    assert override_res.json()["effective"]["http_status"] == 404

    # Recalculates and updates issues
    arch3 = client.get(f"/api/projects/{project['id']}/architecture/issues")
    assert arch3.status_code == 200
    # The 404 page should now be in architecture issues
    has_404_issue = any(issue["type"] == "http_4xx" and issue.get("page_id") == one_id for issue in arch3.json())
    assert has_404_issue, "Cache invalidation failed: 404 manual override not reflected in issues"
