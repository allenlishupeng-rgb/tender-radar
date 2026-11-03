import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from config.settings import LOG_DIR
from database.models import Tender
from parsers.common import clean_text


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIR / "ai_classifier.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


PROJECT_TYPES = {"规划馆", "博物馆", "企业馆", "主题馆", "党建馆", "数字展厅", "多媒体展项", "其他"}
SUGGESTED_ACTIONS = {"立即跟进", "观察", "忽略"}


def compact_text(value: str, max_chars: int = 800) -> str:
    text = clean_text(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def build_classifier_payload(tender: Tender | dict[str, Any]) -> dict[str, Any]:
    data = asdict(tender) if isinstance(tender, Tender) else dict(tender)
    matched = data.get("matched_keywords") or []
    if isinstance(matched, str):
        matched_keywords = matched
    else:
        matched_keywords = "、".join(str(item) for item in matched[:20])

    return {
        "title": compact_text(data.get("title", ""), 160),
        "announcement_type": compact_text(data.get("announcement_type", ""), 80),
        "notice_stage": compact_text(data.get("notice_stage", ""), 40),
        "summary": compact_text(data.get("summary", ""), 800),
        "matched_keywords": compact_text(matched_keywords, 200),
        "budget": compact_text(data.get("budget", ""), 80),
        "region": compact_text(data.get("region", ""), 80),
    }


def normalize_classifier_result(result: dict[str, Any]) -> dict[str, Any]:
    adjustment = result.get("score_adjustment", 0)
    try:
        adjustment = int(adjustment)
    except Exception:
        adjustment = 0

    project_type = clean_text(str(result.get("project_type") or "其他"))
    if project_type not in PROJECT_TYPES:
        project_type = "其他"

    suggested_action = clean_text(str(result.get("suggested_action") or "观察"))
    if suggested_action not in SUGGESTED_ACTIONS:
        suggested_action = "观察"

    return {
        "is_relevant": bool(result.get("is_relevant", False)),
        "score_adjustment": max(-20, min(20, adjustment)),
        "reason": compact_text(str(result.get("reason") or ""), 120),
        "project_type": project_type,
        "suggested_action": suggested_action,
    }


def parse_json_response(text: str) -> dict[str, Any] | None:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        return normalize_classifier_result(json.loads(text[start : end + 1]))
    except Exception as exc:
        logger.exception("Failed to parse AI classifier response: %s", exc)
        return None


class AIRelevanceClassifier:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = client

    @property
    def enabled(self) -> bool:
        return bool(self.api_key or self.client)

    def classify(self, tender: Tender | dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        payload = build_classifier_payload(tender)
        prompt = (
            "你是展览展示、展馆设计、展陈布展、数字展厅、多媒体展项业务线索分类器。"
            "只根据输入的标题和摘要判断，不要假设未提供的信息。"
            "返回严格 JSON，不要 Markdown。JSON 字段必须是："
            'is_relevant, score_adjustment, reason, project_type, suggested_action。'
            "score_adjustment 只能是 -20 到 +20；project_type 只能是："
            "规划馆/博物馆/企业馆/主题馆/党建馆/数字展厅/多媒体展项/其他；"
            "suggested_action 只能是：立即跟进/观察/忽略。"
        )

        try:
            if self.client is None:
                self.client = self._build_client()
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
            content = response.choices[0].message.content or ""
            return parse_json_response(content)
        except Exception as exc:
            logger.exception("AI classifier request failed: %s", exc)
            return None

    def _build_client(self):
        try:
            from openai import OpenAI
        except Exception as exc:
            logger.warning("OpenAI package is not installed, AI classifier skipped: %s", exc)
            raise
        return OpenAI(api_key=self.api_key)


def apply_ai_classification(tender: Tender, classifier: AIRelevanceClassifier | None = None) -> Tender:
    classifier = classifier or AIRelevanceClassifier()
    result = classifier.classify(tender)
    if not result:
        return tender

    tender.ai_is_relevant = result["is_relevant"]
    tender.ai_score_adjustment = result["score_adjustment"]
    tender.ai_reason = result["reason"]
    tender.ai_project_type = result["project_type"]
    tender.ai_suggested_action = result["suggested_action"]
    tender.ai_classified = True
    return tender


def parse_fixture(path: Path) -> dict[str, Any] | None:
    return parse_json_response(path.read_text(encoding="utf-8"))
