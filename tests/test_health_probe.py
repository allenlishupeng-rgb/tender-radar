from scripts.check_source_health import trim_source_config


def test_health_probe_caps_work_without_changing_formal_search_config():
    source = {
        "max_pages": 5, "max_items": 100, "detail_enrichment_limit": 8,
        "request_timeout": 12, "source_timeout_seconds": 60,
    }
    probe = trim_source_config(source)
    assert probe["max_pages"] == 1
    assert probe["max_items"] == 8
    assert probe["detail_enrichment_limit"] == 2
    assert probe["request_timeout"] == 6
    assert probe["source_timeout_seconds"] == 20
    assert source["detail_enrichment_limit"] == 8
    assert source["source_timeout_seconds"] == 60


def test_health_probe_preserves_stricter_source_limits():
    probe = trim_source_config({"detail_enrichment_limit": 0, "request_timeout": 3, "source_timeout_seconds": 10})
    assert probe["detail_enrichment_limit"] == 0
    assert probe["request_timeout"] == 3
    assert probe["source_timeout_seconds"] == 10
