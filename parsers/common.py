import re
from html import unescape

from bs4 import BeautifulSoup

try:
    import trafilatura
except ImportError:  # pragma: no cover - optional parser enhancement
    trafilatura = None


TAG_LIKE_PATTERN = re.compile(r"</?[a-zA-Z][^<>]{0,500}>")
BROKEN_TAG_FRAGMENT_PATTERN = re.compile(r"</?[a-zA-Z][\w:-]*[^<>]{0,300}(?=$|\s*\.\.\.)")
RESIDUAL_TAG_START_PATTERN = re.compile(r"</?[a-zA-Z][\w:-]*(?=\s|$)")
TAG_ATTRIBUTE_PATTERN = re.compile(
    r"\b(?:id|class|style|title|data-[\w:-]+)\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s]+)",
    re.IGNORECASE,
)


def strip_html_fragments(text: str) -> str:
    value = unescape(str(text or "")).replace("\xa0", " ")
    for _ in range(2):
        if not TAG_LIKE_PATTERN.search(value):
            break
        soup = BeautifulSoup(value, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.extract()
        next_value = unescape(soup.get_text(" ")).replace("\xa0", " ")
        if next_value == value:
            break
        value = next_value
    value = TAG_LIKE_PATTERN.sub(" ", value)
    value = BROKEN_TAG_FRAGMENT_PATTERN.sub(" ", value)
    value = TAG_ATTRIBUTE_PATTERN.sub(" ", value)
    value = RESIDUAL_TAG_START_PATTERN.sub(" ", value)
    return value


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", strip_html_fragments(text)).strip()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    visible_text = clean_text(soup.get_text(" "))
    if trafilatura is not None:
        extracted = trafilatura.extract(
            str(html or ""),
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if extracted:
            article_text = clean_text(extracted)
            if visible_text and visible_text not in article_text:
                return clean_text(f"{article_text} {visible_text}")
            return article_text
    return visible_text


def summarize(text: str, max_chars: int = 220) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
