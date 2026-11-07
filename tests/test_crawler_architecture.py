from crawlers import runner
from crawlers.ccgp_public import CcgpPublicCrawler
from crawlers.hebei_public import HebeiPublicCrawler
from crawlers.registry import CRAWLER_REGISTRY, get_crawler_class
from crawlers.shandong_public import ShandongPublicCrawler
from crawlers import source_health


def test_registry_owns_crawler_lookup():
    assert get_crawler_class("ccgp_public") is CcgpPublicCrawler
    assert CRAWLER_REGISTRY["ccgp_public"] is CcgpPublicCrawler
    assert get_crawler_class("hebei_public") is HebeiPublicCrawler
    assert get_crawler_class("shandong_public") is ShandongPublicCrawler


def test_runner_keeps_legacy_registry_export():
    assert runner.CRAWLER_REGISTRY is CRAWLER_REGISTRY


def test_runner_keeps_legacy_source_health_exports():
    assert runner.apply_source_failure_alerts is source_health.apply_source_failure_alerts
    assert runner.load_source_failure_state is source_health.load_source_failure_state
    assert runner.save_source_failure_state is source_health.save_source_failure_state
    assert runner.source_status_failed is source_health.source_status_failed
