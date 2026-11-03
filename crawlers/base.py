import time
import urllib.robotparser
from dataclasses import asdict
from urllib.parse import urlparse

import requests
from requests import Response

from config.settings import REQUEST_INTERVAL_SECONDS, REQUEST_TIMEOUT, USER_AGENT
from crawlers.errors import friendly_error_message
from database.models import Tender
from parsers.extractors import annotate_deadline_fields
from scoring.rules import priority_from_score, score_tender


class BaseCrawler:
    name = "base"

    def __init__(
        self,
        keywords: dict,
        source_config: dict | None = None,
        request_interval: int = REQUEST_INTERVAL_SECONDS,
    ):
        self.keywords = keywords
        self.source_config = source_config or {}
        self.request_interval = request_interval
        self.session = requests.Session()
        # Some government platforms reject or break through system proxy settings.
        # The tool is local-only and should request public pages directly.
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.last_error = ""
        self.execution_deadline: float | None = None
        self.request_count = 0
        self._response_cache = {}

    def remaining_seconds(self) -> float:
        if self.execution_deadline is None:
            return float("inf")
        return max(0.0, self.execution_deadline - time.monotonic())

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        if robots_url not in self._robots_cache:
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    if self.remaining_seconds() <= 0:
                        return False
                    resp = session.get(robots_url, timeout=min(self.request_timeout(REQUEST_TIMEOUT), self.remaining_seconds()), headers={"User-Agent": USER_AGENT})
                if resp.status_code != 200:
                    self._robots_cache[robots_url] = None
                else:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(resp.text.splitlines())
                    self._robots_cache[robots_url] = rp
            except Exception:
                # robots.txt unavailable is treated as allowed, but requests remain rate-limited.
                self._robots_cache[robots_url] = None
        rp = self._robots_cache[robots_url]
        if rp is None:
            return True
        return rp.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> requests.Response | None:
        if url in self._response_cache:
            return self._response_cache[url]
        if not self.can_fetch(url):
            self.last_error = f"robots.txt 不允许访问：{url}"
            return None
        if self.remaining_seconds() <= self.request_interval:
            self.last_error = "单来源运行超时，详情补全停止"
            return None
        time.sleep(self.request_interval)
        try:
            resp = self.request_with_retries("GET", url, timeout=self.request_timeout(REQUEST_TIMEOUT))
        except Exception as exc:
            self.last_error = friendly_error_message(exc)
            raise
        if resp.status_code != 200:
            self.last_error = f"HTTP {resp.status_code}：{url}"
            return None
        if len(self._response_cache) < 100:
            self._response_cache[url] = resp
        return resp

    def request_with_retries(self, method: str, url: str, retries: int = 2, **kwargs) -> Response:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            if self.remaining_seconds() <= 0:
                raise requests.Timeout("单来源总运行超时")
            if attempt:
                time.sleep(min(self.request_interval * attempt, 8, self.remaining_seconds()))
            try:
                remaining = self.remaining_seconds()
                if remaining <= 0:
                    raise requests.Timeout("单来源总运行超时")
                request_kwargs = dict(kwargs)
                timeout = request_kwargs.get("timeout", REQUEST_TIMEOUT)
                if isinstance(timeout, tuple):
                    request_kwargs["timeout"] = tuple(min(float(value), remaining) for value in timeout)
                else:
                    request_kwargs["timeout"] = min(float(timeout), remaining)
                self.request_count += 1
                return self.session.request(method, url, **request_kwargs)
            except requests.RequestException as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise RuntimeError("请求失败")

    def config_int(self, key: str, default: int) -> int:
        raw_value = self.source_config.get(key, default)
        try:
            return int(raw_value or default)
        except (TypeError, ValueError):
            return default

    def source_result_limit(self, default: int = 50) -> int:
        raw_value = self.source_config.get(
            "result_limit",
            self.source_config.get("max_results", self.source_config.get("max_items", default)),
        )
        try:
            value = int(raw_value or default)
        except (TypeError, ValueError):
            value = default
        return max(value, 1)

    def source_deadline(self, default_seconds: int = 45) -> float:
        seconds = max(self.config_int("source_timeout_seconds", default_seconds), 1)
        local_deadline = time.monotonic() + seconds
        return min(local_deadline, self.execution_deadline) if self.execution_deadline is not None else local_deadline

    def source_timed_out(self, deadline: float) -> bool:
        if time.monotonic() < deadline:
            return False
        self.last_error = self.last_error or "单来源运行超时，已切换下一个来源"
        return True

    def source_should_stop(self, results: list, deadline: float, result_limit: int | None = None) -> bool:
        limit = result_limit or self.source_result_limit()
        return len(results) >= limit or self.source_timed_out(deadline)

    def request_timeout(self, default: int = REQUEST_TIMEOUT) -> int:
        return max(self.config_int("request_timeout", default), 1)

    def close(self) -> None:
        self.session.close()

    def search(self, query: str, days: int = 7) -> list[Tender]:
        raise NotImplementedError

    def apply_scoring(self, tender: Tender) -> Tender:
        scored = score_tender(asdict(tender), self.keywords)
        weight = float(self.source_config.get("source_weight", 1) or 1)
        if 0 < weight < 1 and scored.get("relevance_score", 0) > 0:
            scored["relevance_score"] = max(1, int(round(int(scored.get("relevance_score") or 0) * weight)))
            scored["priority"] = priority_from_score(scored["relevance_score"])
        return annotate_deadline_fields(Tender(**scored))
