from scoring.lead_quality import (
    ACTION_IGNORE,
    ACTION_INTEL,
    ACTION_NOW,
    ACTION_OBSERVE,
    ACTION_REVIEW,
    annotate_lead_quality,
)


def test_high_priority_bid_notice_becomes_immediate_action():
    row = {
        "title": "产业园企业展厅设计施工一体化项目招标公告",
        "announcement_type": "公开招标公告",
        "notice_stage": "可投公告",
        "priority": "高优先级",
        "relevance_score": 90,
        "bid_deadline": "2099-07-30 09:30",
        "budget": "1200万元",
        "contact_phone": "13800000000",
        "profile_project_type": "企业品牌展厅",
    }

    annotate_lead_quality(row)

    assert row["lead_action"] == ACTION_NOW
    assert row["lead_quality_score"] >= 70
    assert row["lead_risk_level"] == "低"
    assert "正式可投公告" in row["lead_reason"]


def test_intel_notice_goes_to_opportunity_pool():
    row = {
        "title": "低空经济展示中心采购意向公开",
        "announcement_type": "采购意向",
        "notice_stage": "情报参考",
        "priority": "中优先级",
        "relevance_score": 72,
        "bid_deadline": "",
        "profile_project_type": "科技主题展厅",
    }

    annotate_lead_quality(row)

    assert row["lead_action"] == ACTION_OBSERVE
    assert "前期/需求线索" in row["lead_reason"]


def test_closed_or_unrelated_notice_is_not_actionable():
    closed = {
        "title": "企业展厅项目中标公告",
        "announcement_type": "中标公告",
        "notice_stage": "中标结果",
        "priority": "高优先级",
        "relevance_score": 88,
        "bid_deadline": "2000-01-01 09:30",
        "profile_project_type": "企业品牌展厅",
    }
    unrelated = {
        "title": "博物馆消防系统采购公告",
        "announcement_type": "采购公告",
        "notice_stage": "无效",
        "priority": "可能无关",
        "relevance_score": 0,
    }

    annotate_lead_quality(closed)
    annotate_lead_quality(unrelated)

    assert closed["lead_action"] == ACTION_INTEL
    assert closed["lead_risk_level"] == "高"
    assert unrelated["lead_action"] == ACTION_IGNORE
    assert unrelated["lead_quality_score"] <= 25


def test_public_culture_bid_notice_cannot_become_immediate_action():
    row = {
        "title": "山东博物馆东夷文化展陈列布展项目公开招标公告",
        "summary": "项目包含展陈大纲、陈列布展和多媒体展项。",
        "announcement_type": "公开招标公告",
        "notice_stage": "可投公告",
        "priority": "高优先级",
        "relevance_score": 90,
        "bid_deadline": "2099-07-30 09:30",
        "budget": "1200万元",
        "contact_phone": "13800000000",
        "profile_project_type": "公共文化展陈",
    }

    annotate_lead_quality(row)

    assert row["lead_action"] == ACTION_REVIEW
    assert row["lead_quality_score"] < 70
    assert "公共文化/博物馆类" in row["lead_reason"]


def test_user_score_changes_lead_quality_direction():
    liked = {
        "title": "企业总部展厅设计施工一体化项目招标公告",
        "announcement_type": "公开招标公告",
        "notice_stage": "可投公告",
        "priority": "高优先级",
        "relevance_score": 70,
        "bid_deadline": "2099-07-30 09:30",
        "profile_project_type": "企业品牌展厅",
        "user_score": 10,
    }
    rejected = {
        **liked,
        "title": "展会展台搭建服务项目采购公告",
        "user_score": -5,
    }

    annotate_lead_quality(liked)
    annotate_lead_quality(rejected)

    assert liked["lead_quality_score"] >= 85
    assert "你的评分" in liked["lead_reason"]
    assert rejected["lead_action"] == ACTION_IGNORE
    assert rejected["lead_quality_score"] <= 20
