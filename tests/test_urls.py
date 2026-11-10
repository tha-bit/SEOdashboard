import pytest

from backend.services.urls import normalize_url


def test_normalization_removes_fragments_tracking_and_trailing_slash():
    assert normalize_url("HTTPS://Example.COM:443/Shoes/?utm_source=x&size=9#top") == "https://example.com/Shoes?size=9"


def test_path_case_is_preserved_to_avoid_unsafe_merges():
    assert normalize_url("https://example.com/Product") != normalize_url("https://example.com/product")


def test_query_values_remain_part_of_identity():
    assert normalize_url("https://example.com/shoes?size=8") != normalize_url("https://example.com/shoes?size=9")


def test_invalid_relative_url_rejected():
    with pytest.raises(ValueError):
        normalize_url("/only-a-path")

