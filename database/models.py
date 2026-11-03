from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Tender:
    title: str
    announcement_type: str = ""
    publish_date: str = ""
    region: str = ""
    purchaser: str = ""
    agency: str = ""
    budget: str = ""
    project_no: str = ""
    contact_person: str = ""
    contact_phone: str = ""
    bid_deadline: str = ""
    bid_deadline_date: str = ""
    days_left: Optional[int] = None
    tender_status: str = "待核验"
    notice_stage: str = "情报参考"
    important_info: str = ""
    source_url: str = ""
    summary: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    relevance_score: int = 0
    priority: str = "可能无关"
    profile_project_type: str = ""
    profile_client_type: str = ""
    profile_reason: str = ""
    ai_is_relevant: bool | None = None
    ai_score_adjustment: int = 0
    ai_reason: str = ""
    ai_project_type: str = ""
    ai_suggested_action: str = ""
    ai_classified: bool = False
    is_read: bool = False
    remark: str = ""
    feedback_label: str = ""
    user_score: int | None = None
    user_score_updated_at: str = ""
    source_name: str = ""
    review_bucket: str = "主结果"
