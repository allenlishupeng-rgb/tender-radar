from database.models import Tender
from ai_classifier.relevance import (
    AIRelevanceClassifier,
    apply_ai_classification,
    build_classifier_payload,
    parse_json_response,
)
from crawlers.runner import apply_ai_to_candidates


def test_ai_classifier_skips_without_api_key():
    tender = Tender(title="某展陈设计项目", summary="包含多媒体展项")
    classifier = AIRelevanceClassifier(api_key="", client=None)

    result = apply_ai_classification(tender, classifier)

    assert result.ai_classified is False
    assert result.ai_reason == ""


def test_build_classifier_payload_keeps_summary_compact():
    tender = Tender(
        title="某规划馆展陈设计施工一体化项目招标公告",
        announcement_type="公开招标公告",
        summary="展陈设计" * 1000,
        matched_keywords=["规划馆", "展陈设计"],
        budget="1200万元",
        region="江苏省苏州市",
    )

    payload = build_classifier_payload(tender)

    assert payload["title"] == "某规划馆展陈设计施工一体化项目招标公告"
    assert len(payload["summary"]) <= 803
    assert payload["matched_keywords"] == "规划馆、展陈设计"


def test_parse_json_response_normalizes_output():
    parsed = parse_json_response(
        """
        {
          "is_relevant": true,
          "score_adjustment": 99,
          "reason": "标题和摘要都指向规划馆展陈设计。",
          "project_type": "规划馆",
          "suggested_action": "立即跟进"
        }
        """
    )

    assert parsed["is_relevant"] is True
    assert parsed["score_adjustment"] == 20
    assert parsed["project_type"] == "规划馆"
    assert parsed["suggested_action"] == "立即跟进"


class FakeClassifier:
    enabled = True

    def __init__(self):
        self.calls = []

    def classify(self, tender):
        self.calls.append(tender.title)
        return {
            "is_relevant": True,
            "score_adjustment": 8,
            "reason": "候选线索指向展厅设计施工。",
            "project_type": "企业馆",
            "suggested_action": "立即跟进",
        }


def test_apply_ai_to_candidates_skips_non_candidates():
    classifier = FakeClassifier()
    candidate = Tender(
        title="苏州企业展厅设计施工一体化项目招标公告",
        summary="包含展陈设计、数字展厅和布展施工。",
        source_url="https://example.com/candidate",
        source_name="测试来源",
        bid_deadline="2099年07月08日 09:30",
    )
    non_target = Tender(
        title="博物馆安保服务项目公开招标公告",
        summary="服务内容为保安和巡逻。",
        source_url="https://example.com/security",
        source_name="测试来源",
    )
    closed = Tender(
        title="产业园展厅设计施工一体化项目招标公告",
        summary="包含展陈设计和布展施工。",
        source_url="https://example.com/closed",
        source_name="测试来源",
        bid_deadline="2020年01月01日 09:30",
    )
    already_classified = Tender(
        title="数字展厅展陈设计项目招标公告",
        summary="包含多媒体展项。",
        source_url="https://example.com/classified",
        source_name="测试来源",
        ai_classified=True,
    )

    counts = apply_ai_to_candidates([candidate, non_target, closed, already_classified], classifier)

    assert counts == {"测试来源": 1}
    assert classifier.calls == ["苏州企业展厅设计施工一体化项目招标公告"]
    assert candidate.ai_classified is True
    assert non_target.ai_classified is False
    assert closed.ai_classified is False
