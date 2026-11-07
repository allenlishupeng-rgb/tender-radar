from pathlib import Path

import pytest

from scoring.project_profile import HISTORICAL_PROFILE_PATH, PROJECT_CONTEXT_TERMS, PROJECT_DOWNRANK_TERMS, PROJECT_SEARCH_TERMS
from scripts.train_from_historical_projects import build_profile, load_rows


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / "data" / "historical_projects.csv").is_file(), reason="private historical CSV is not in the repository")
def test_historical_project_samples_train_profile():
    rows = load_rows(ROOT / "data" / "historical_projects.csv")
    profile = build_profile(rows)

    assert profile["sample_count"] >= 150
    assert profile["positive_sample_count"] >= 100
    assert "低空经济" in profile["search_terms"]
    assert "人工智能" in profile["search_terms"]
    assert "展示中心" in profile["venue_terms"]
    assert "排水" in profile["downrank_terms"]


@pytest.mark.skipif(not HISTORICAL_PROFILE_PATH.is_file(), reason="private historical profile is not in the public repository")
def test_project_profile_loads_historical_terms():
    assert "低空经济" in PROJECT_SEARCH_TERMS
    assert "博物馆" not in PROJECT_SEARCH_TERMS
    assert "科技馆" not in PROJECT_SEARCH_TERMS
    assert "基金小镇" in PROJECT_CONTEXT_TERMS
    assert "环境整治" in PROJECT_DOWNRANK_TERMS
