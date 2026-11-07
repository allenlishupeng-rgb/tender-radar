from pathlib import Path

import yaml


MAINLAND_REGIONS = [
    "北京",
    "天津",
    "河北",
    "山西",
    "内蒙古",
    "辽宁",
    "吉林",
    "黑龙江",
    "上海",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "广西",
    "海南",
    "重庆",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
]


def load_sources_config():
    return yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))


def test_enabled_sources_cover_mainland_regions_and_bingtuan():
    sources = load_sources_config()["sources"]
    enabled_names = [source["name"] for source in sources if source.get("enabled", True)]

    assert all(any(region in name for name in enabled_names) for region in MAINLAND_REGIONS)
    assert any("兵团" in name for name in enabled_names)


def test_ccgp_default_regions_cover_mainland_regions():
    sources = load_sources_config()["sources"]
    ccgp = next(source for source in sources if source["crawler"] == "ccgp_public")
    defaults = ccgp["default_target_regions"]
    target_regions = ccgp["target_regions"]

    nationwide = next((item for item in target_regions if item.get("name") == "全国"), None)
    assert "全国" in defaults or all(region in defaults for region in MAINLAND_REGIONS)
    if "全国" in defaults:
        assert nationwide is not None
        assert nationwide.get("display_zone", "") == ""
        assert nationwide.get("zone_id", "") == ""
    assert all(
        any(region in item.get("name", "") or region in item.get("display_zone", "") for item in target_regions)
        for region in MAINLAND_REGIONS
    )
