from scripts.generate_static_site import is_publishable_review_row, is_publishable_target_row


def test_review_candidate_is_separate_from_main_results():
    row = {
        "review_bucket": "待研判",
        "notice_stage": "可投公告",
        "priority": "低优先级",
        "tender_status": "正常跟进",
        "bid_deadline": "2099-12-31",
        "title": "产业展示中心建设项目",
        "purchaser": "某产业园公司",
    }

    assert is_publishable_review_row(row)
    assert not is_publishable_target_row(row)


def test_closed_review_candidate_stays_out_of_static_export():
    row = {
        "review_bucket": "待研判",
        "notice_stage": "可投公告",
        "tender_status": "已截止",
        "bid_deadline": "2020-01-01",
    }

    assert not is_publishable_review_row(row)
