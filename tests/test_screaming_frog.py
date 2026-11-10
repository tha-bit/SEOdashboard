from backend.services.screaming_frog import recognize_headers, suggested_semantic_mapping


DOCUMENTED_HEADERS = [
    "Address", "Content Type", "Status Code", "Status", "Indexability", "Indexability Status",
    "Title 1", "Title 1 Length", "Title 1 Pixel Width", "Meta Description 1", "Meta Description 2",
    "Meta Description 1 Length", "Meta Description 1 Pixel Width", "Meta Description 2 Length",
    "Meta Description 2 Pixel Width", "Meta Keyword 1", "H1-1", "H1-1 Lenght", "H1-2",
    "H1-2 Lenght", "H2-1", "H2-2", "Word Count", "Text Ratio", "Canonical Link Element 1",
    "Meta Robots 1", "X-Robots-Tag 1", "Crawl Depth", "Inlinks", "Outlinks", "External Outlinks",
    "Link Score", "Response Time", "Redirect URI", "Redirect Type", "Language",
]


def test_every_documented_screaming_frog_header_is_recognized_exactly():
    recognition = recognize_headers(DOCUMENTED_HEADERS)
    assert len(recognition) == len(DOCUMENTED_HEADERS)
    assert all(item["confidence"] == "exact" for item in recognition)
    assert all(item["semantic_key"] for item in recognition)


def test_status_text_is_not_confused_with_numeric_status_code():
    mapping = suggested_semantic_mapping(recognize_headers(["Status", "Status Code"]))
    assert mapping["http_status_text"] == "Status"
    assert mapping["http_status"] == "Status Code"


def test_non_exact_header_is_only_a_possible_match():
    result = recognize_headers(["status code"])[0]
    assert result["semantic_key"] == "http_status"
    assert result["confidence"] == "possible"


def test_phase_three_hreflang_crawl_date_and_dynamic_h1_headers_are_exact():
    recognition = recognize_headers(["From", "Hreflang", "To", "Crawl Date", "H1-3"])
    mapping = suggested_semantic_mapping(recognition)
    assert all(item["confidence"] == "exact" for item in recognition)
    assert mapping == {
        "address": "From",
        "hreflang_language": "Hreflang",
        "hreflang_url": "To",
        "crawl_date": "Crawl Date",
        "h1_3": "H1-3",
    }
