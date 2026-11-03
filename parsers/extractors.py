import re
from datetime import date, datetime, timedelta, timezone

from parsers.common import clean_text


PHONE_PATTERN = re.compile(
    r"(?:\+?86[-\s]?)?(?:1[3-9]\d{9}|0\d{2,3}[-\s]?\d{7,8})"
)
LABEL_STOP_WORDS = [
    "联系电话",
    "联系方式",
    "联系人",
    "项目联系人",
    "采购人",
    "采购单位",
    "招标人",
    "代理机构",
    "采购代理机构",
    "项目编号",
    "采购编号",
    "招标编号",
    "预算金额",
    "最高限价",
    "投标截止时间",
    "开标时间",
]
INVALID_PROJECT_NO_MARKERS = [
    "项目名称",
    "项目名",
    "项目概况",
    "采购项目",
    "招标项目",
    "联系方式",
    "联系人",
    "采购人",
    "招标人",
    "代理机构",
]

MIN_ACTIONABLE_DAYS_LEFT = 20
PREPARATION_DAYS = 10
IDEAL_DEADLINE_MIN_DAYS = 20
IDEAL_DEADLINE_MAX_DAYS = 30


def extract_phone(text: str) -> str:
    normalized = clean_text(text)
    matches = PHONE_PATTERN.findall(normalized)
    return "、".join(dict.fromkeys(matches[:5]))


def extract_after_label(text: str, labels: list[str], max_len: int = 120) -> str:
    normalized = clean_text(text).replace("：", ":")
    for label in labels:
        marker = f"{label}:"
        if marker in normalized:
            value = clean_labeled_value(normalized.split(marker, 1)[1][:max_len], current_label=label)
            return value
        match = re.search(rf"{re.escape(label)}\s+([^\s|,，;；。]+)", normalized)
        if match:
            return clean_labeled_value(match.group(1), current_label=label)
    return ""


def clean_labeled_value(value: str, current_label: str = "") -> str:
    cleaned = clean_text(value).strip("|,，;；:：。")
    cleaned = re.sub(r"^[>/>\\]+", "", cleaned).strip()
    for stop_word in LABEL_STOP_WORDS:
        if stop_word == current_label:
            continue
        for marker in (f" {stop_word}", f"{stop_word}:", f"{stop_word}："):
            if marker in cleaned:
                cleaned = cleaned.split(marker, 1)[0].strip()
    cleaned = re.split(r"[|,，;；。]", cleaned, maxsplit=1)[0].strip()
    if " " in cleaned:
        cleaned = cleaned.split(" ", 1)[0].strip()
    return cleaned.strip("|,，;；:：。")


def extract_contact_person(text: str) -> str:
    return extract_after_label(text, ["联系人", "项目联系人", "采购项目联系人", "招标联系人"], 80)


def extract_deadline(text: str) -> str:
    labels = [
        "投标截止时间",
        "投标文件递交截止时间",
        "递交投标文件截止时间",
        "提交投标文件截止时间",
        "响应文件提交截止时间",
        "提交响应文件截止时间",
        "响应截止时间",
        "递交截止时间",
        "文件递交截止时间",
        "投标文件接收截止时间",
        "响应文件开启时间",
        "开标时间",
    ]
    normalized = normalize_date_digits(clean_text(text).replace("：", ":"))
    # Tables commonly split the submission heading and the deadline label.
    # Require submission context; never accept an unrelated bare date or a
    # document-purchase/registration deadline.
    contextual = re.search(
        r"(?:投标|响应|应答)文件(?:的)?(?:提交|递交|接收)\s*[:：|\s]*"
        r"(?:截止时间|截止日期)\s*[:：|\s]*([^。；;]{1,90})",
        normalized,
    )
    if contextual:
        match = find_date_match(contextual.group(1))
        if match:
            return clean_text(match.group(0))
    prose = re.search(
        r"(?:投标|响应|应答)文件(?:递交|提交)(?:的)?截止(?:时间|日期)(?:为|是)?\s*[:：]?\s*([^。；;]{1,80})",
        normalized,
    )
    if prose:
        match = find_date_match(prose.group(1))
        if match:
            return clean_text(match.group(0))
    for label in labels:
        marker = f"{label}:"
        if marker in normalized:
            snippet = re.split(r"[。；;]|(?:报名|获取招标文件|获取采购文件|合同履行期限|工期)\s*[:：]", normalized.split(marker, 1)[1][:80], maxsplit=1)[0]
            match = find_date_match(snippet)
            return clean_text(match.group(0)) if match else clean_text(snippet).split("。")[0]
        match = re.search(
            rf"{re.escape(label)}\s+(\d{{4}}\s*[-年/.]\s*\d{{1,2}}\s*[-月/.]\s*\d{{1,2}}\s*[日号]?(?:\s*\d{{1,2}}\s*[:：时点]\s*\d{{0,2}})?)",
            normalized,
        )
        if match:
            return clean_text(match.group(1))
    # CCGP introductory sentence: 并于 DATE 前提交响应文件.
    submission = re.search(r"并于\s*([^。；;]{1,65}?)\s*(?:前|之前)(?:递交|提交)(?:投标|响应|应答)文件", normalized)
    if submission:
        match = find_date_match(submission.group(1))
        if match:
            return clean_text(match.group(0))
    return ""


def extract_project_no(text: str) -> str:
    value = extract_after_label(text, ["项目编号", "采购编号", "招标编号", "标段编号"], 80)
    return value if is_valid_project_no(value) else ""


def is_valid_project_no(value: str) -> bool:
    cleaned = clean_text(value).strip()
    if not cleaned:
        return False
    if len(cleaned) > 80:
        return False
    if any(marker in cleaned for marker in INVALID_PROJECT_NO_MARKERS):
        return False
    return bool(re.search(r"\d", cleaned))


def build_important_info(text: str, max_chars: int = 500) -> str:
    normalized = clean_text(text)
    keepers = []
    keywords = [
        "联系人",
        "联系电话",
        "联系方式",
        "招标人",
        "采购人",
        "代理机构",
        "预算金额",
        "最高限价",
        "合同估算价",
        "投标截止时间",
        "开标时间",
        "项目编号",
        "招标编号",
    ]
    for sentence in re.split(r"[。；;]", normalized):
        if any(keyword in sentence for keyword in keywords):
            keepers.append(clean_text(sentence).strip())
    value = "；".join(dict.fromkeys(item for item in keepers if item))
    if not value:
        value = normalized[:max_chars]
    return value[:max_chars]


def normalize_date_digits(text: str) -> str:
    """Repair dates where OCR/page text inserts spaces inside digits."""
    return re.sub(r"(?<=\d)\s+(?=\d)", "", text or "")


def _safe_iso_date(year: str | int, month: str | int, day: str | int) -> str:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return ""


def find_date_match(text: str):
    normalized = normalize_date_digits(text)
    normalized = re.sub(
        r"(\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2})(\d{1,2}\s*[:：]\s*\d{1,2})",
        r"\1 \2",
        normalized,
    )
    patterns = [
        r"\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}(?:\s*\d{1,2}\s*[:：]\s*\d{1,2})?",
        r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]?(?:\s*\d{1,2}\s*[:：时点]\s*\d{0,2})?",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match
    return None


def normalize_publish_date(text: str) -> str:
    value = normalize_date_digits(clean_text(text))
    if not value:
        return ""
    for match in re.finditer(r"(\d{4})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})", value):
        normalized = _safe_iso_date(match.group(1), match.group(2), match.group(3))
        if normalized:
            return normalized
    for match in re.finditer(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", value):
        normalized = _safe_iso_date(match.group(1), match.group(2), match.group(3))
        if normalized:
            return normalized
    for match in re.finditer(r"(\d{1,2})[-月/](\d{1,2})", value):
        normalized = _safe_iso_date(date.today().year, match.group(1), match.group(2))
        if normalized:
            return normalized
    return ""


def normalize_deadline_date(text: str) -> str:
    value = normalize_date_digits(clean_text(text))
    if not value:
        return ""
    match = re.search(r"(\d{4})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})", value)
    if not match:
        return ""
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return ""


def radar_today() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def deadline_days_left(deadline_date: str, today: date | None = None) -> int | None:
    if not deadline_date:
        return None
    today = today or radar_today()
    try:
        deadline = datetime.strptime(deadline_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (deadline - today).days


def tender_status_from_days(days_left: int | None) -> str:
    if days_left is None:
        return "待核验"
    if days_left < 0:
        return "已截止"
    if days_left < MIN_ACTIONABLE_DAYS_LEFT:
        return "时间不足"
    if days_left < IDEAL_DEADLINE_MIN_DAYS:
        return "紧急跟进"
    if days_left <= IDEAL_DEADLINE_MAX_DAYS:
        return "理想窗口"
    if days_left <= 45:
        return "正常跟进"
    return "观察"


def annotate_deadline_fields(item, today: date | None = None):
    raw_deadline = (
        (item.get("bid_deadline", "") or item.get("bid_deadline_date", ""))
        if isinstance(item, dict)
        else (getattr(item, "bid_deadline", "") or getattr(item, "bid_deadline_date", ""))
    )
    deadline_date = normalize_deadline_date(raw_deadline)
    days_left = deadline_days_left(deadline_date, today=today)
    status = tender_status_from_days(days_left)
    if isinstance(item, dict):
        item["bid_deadline_date"] = deadline_date
        item["days_left"] = days_left
        item["tender_status"] = status
        item["design_days_left"] = None if days_left is None else max(0, days_left - PREPARATION_DAYS)
    else:
        item.bid_deadline_date = deadline_date
        item.days_left = days_left
        item.tender_status = status
    return item


def is_open_for_tendering(item, today: date | None = None) -> bool:
    annotated = annotate_deadline_fields(dict(item) if isinstance(item, dict) else item, today=today)
    status = annotated.get("tender_status") if isinstance(annotated, dict) else annotated.tender_status
    days_left = annotated.get("days_left") if isinstance(annotated, dict) else annotated.days_left
    if days_left is None:
        return False
    return int(days_left) >= MIN_ACTIONABLE_DAYS_LEFT
