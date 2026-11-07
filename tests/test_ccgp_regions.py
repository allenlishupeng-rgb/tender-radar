from crawlers.ccgp_public import CcgpPublicCrawler
from config.settings import SOURCES_PATH
from crawlers.runner import load_yaml


def test_ccgp_uses_default_target_regions_when_no_region_filter():
    crawler = CcgpPublicCrawler(
        {},
        source_config={
            "target_regions": [
                {"name": "江苏", "display_zone": "江苏"},
                {"name": "上海", "display_zone": "上海"},
                {"name": "浙江", "display_zone": "浙江"},
                {"name": "湖北", "display_zone": "湖北"},
            ],
            "default_target_regions": ["江苏", "上海", "浙江"],
        },
    )

    selected = crawler.resolve_target_regions()

    assert [item["name"] for item in selected] == ["江苏", "上海", "浙江"]


def test_ccgp_region_filter_can_still_select_extended_region():
    crawler = CcgpPublicCrawler(
        {},
        source_config={
            "target_regions": [
                {"name": "江苏", "display_zone": "江苏"},
                {"name": "湖北", "display_zone": "湖北"},
            ],
            "default_target_regions": ["江苏"],
        },
    )

    selected = crawler.resolve_target_regions(["湖北"])

    assert [item["name"] for item in selected] == ["湖北"]


def test_ccgp_real_config_defaults_to_one_nationwide_search():
    source = next(
        item
        for item in load_yaml(SOURCES_PATH).get("sources", [])
        if item.get("crawler") == "ccgp_public"
    )
    crawler = CcgpPublicCrawler({}, source_config=source)

    selected = crawler.resolve_target_regions()

    assert [item["name"] for item in selected] == ["全国"]
    assert selected[0]["display_zone"] == ""
    assert source["max_terms"] >= 10
    assert source["detail_enrichment_limit"] < source["result_limit"]
    assert source["require_header_target"] is True
