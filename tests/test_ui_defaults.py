from pathlib import Path


APP_SOURCE = Path("ui/app.py").read_text(encoding="utf-8")


def test_source_scope_defaults_to_wide_scan():
    assert "[SOURCE_SCOPE_BALANCED, SOURCE_SCOPE_CORE, SOURCE_SCOPE_WIDE]," in APP_SOURCE
    assert "index=2,\n        help=\"均衡拓源" in APP_SOURCE


def test_workbench_view_defaults_to_all_inventory():
    assert 'st.selectbox("工作台视图", [VIEW_ACTION, VIEW_INTEL, VIEW_ALL], index=2)' in APP_SOURCE


def test_interactive_search_defaults_to_thirty_days():
    assert '"时间范围",\n        [7, 14, DEFAULT_INTERACTIVE_SEARCH_DAYS],\n        index=2,' in APP_SOURCE
