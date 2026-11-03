import json
import re


MOJIBAKE_MARKERS = (
    "\ufffd",
    "灞",
    "鐪",
    "甯",
    "鍏",
    "璧",
    "浜",
    "鎹",
    "妫",
    "绱",
    "槼",
    "窞",
    "矙",
)


def _badness(text: str) -> int:
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS) + text.count("?")


def repair_text(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    original_badness = _badness(text)
    if original_badness == 0:
        return text
    for encoding in ("gbk", "cp936"):
        try:
            fixed = text.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        if fixed and fixed != text and _badness(fixed) < original_badness:
            return fixed
    return text


def normalize_matched_keywords(value) -> str:
    if isinstance(value, list):
        return "、".join(repair_text(item) for item in value if item)
    if not value:
        return ""
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return "、".join(repair_text(item) for item in parsed if item)
    except Exception:
        pass
    return repair_text(value).strip("[]\"'")


def normalize_budget(value) -> str:
    text = repair_text(value).strip()
    if not text:
        return ""
    text = text.replace("人民币", "").replace("（", "(").replace("）", ")")
    text = text.replace("(人民币)", "")
    text = text.replace("()", "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(?<=\d)(呎|円|圓|圆)(?=$|[，,;；。])", "元", text)
    text = text.replace("￥", "")
    text = re.sub(r"^¥", "", text)

    match = re.fullmatch(r"([0-9][0-9,]*)(?:\.0+)?万元", text)
    if match:
        return f"{match.group(1)}万元"

    match = re.fullmatch(r"([0-9][0-9,]*)(?:\.0+)?元", text)
    if match:
        return f"{match.group(1)}元"

    match = re.fullmatch(r"([0-9][0-9,]*\.\d+)(万元|元)", text)
    if match:
        number = match.group(1).rstrip("0").rstrip(".")
        return f"{number}{match.group(2)}"

    return text
