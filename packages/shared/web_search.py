"""Web search providers for Ask augment and Education auto-discovery.

Providers:
- fixture: offline deterministic results (tests / demo)
- brave: Brave Search API (BRAVE_SEARCH_API_KEY)
- bing: Bing Web Search API (BING_SEARCH_API_KEY)
- duckduckgo: HTML lite search (live only; results still filterable)

Education mode always filters to official allowlisted hosts unless
allow_hosts_only=False (Ask general mode).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from shared.config import get_settings
from shared.edu_official import _allow_hosts
from shared.errors import AppError, ErrorCode


@dataclass(frozen=True)
class WebHit:
    title: str
    url: str
    snippet: str
    provider: str
    score: float = 0.0


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def filter_allowlisted(hits: list[WebHit], *, allow_hosts: set[str] | None = None) -> list[WebHit]:
    hosts = allow_hosts if allow_hosts is not None else _allow_hosts()
    out: list[WebHit] = []
    for h in hits:
        parsed = urlparse(h.url)
        if parsed.scheme == "fixture":
            out.append(h)
            continue
        host = (parsed.hostname or "").lower()
        if host in hosts or (host.startswith("www.") and host[4:] in hosts):
            out.append(h)
            continue
        if any(host.endswith("." + ah.lstrip(".")) for ah in hosts if "." in ah):
            out.append(h)
    return out


def _fixture_hits(query: str, *, education: bool) -> list[WebHit]:
    q = (query or "").lower()
    hits: list[WebHit] = []
    if any(k in q for k in ("语文", "chinese", "记叙", "文言")):
        hits.append(
            WebHit(
                title="智慧教育公开样例·初中语文七年级",
                url="fixture://smartedu-chinese-g7",
                snippet="国家智慧教育平台公开资源结构样例：记叙文与文言文基础教程及练习题。",
                provider="fixture",
                score=0.92,
            )
        )
    if any(k in q for k in ("数学", "math", "有理数", "方程", "课标")) or not hits:
        hits.append(
            WebHit(
                title="课标公开样例·初中数学七年级",
                url="fixture://moe-math-g7",
                snippet="教育部课标公开纲要结构化样例：有理数、整式、一元一次方程教程与公开样例题。",
                provider="fixture",
                score=0.95,
            )
        )
        hits.append(
            WebHit(
                title="教育部基础教育课程教材信息（公开页）",
                url="https://www.moe.gov.cn/jyb_xwfb/",
                snippet="教育部官网公开新闻与政策栏目（需 live 模式拉取正文）。",
                provider="fixture",
                score=0.7,
            )
        )
    if education:
        return filter_allowlisted(hits) or hits[:1]
    return hits


def _brave_search(query: str, *, count: int) -> list[WebHit]:
    settings = get_settings()
    key = (settings.brave_search_api_key or "").strip()
    if not key:
        raise AppError(ErrorCode.VALIDATION_ERROR, "BRAVE_SEARCH_API_KEY not configured", status_code=400)
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": key,
        "User-Agent": "AtriumKB-WebSearch/1.0",
    }
    params = {"q": query, "count": max(1, min(count, 20))}
    try:
        with httpx.Client(timeout=settings.web_search_timeout_seconds) as client:
            resp = client.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"brave search failed: {exc}", status_code=502) from exc
    hits: list[WebHit] = []
    for i, item in enumerate((data.get("web") or {}).get("results") or []):
        url = str(item.get("url") or "")
        if not url:
            continue
        hits.append(
            WebHit(
                title=str(item.get("title") or url)[:300],
                url=url,
                snippet=str(item.get("description") or "")[:500],
                provider="brave",
                score=max(0.1, 1.0 - i * 0.05),
            )
        )
    return hits


def _bing_search(query: str, *, count: int) -> list[WebHit]:
    settings = get_settings()
    key = (settings.bing_search_api_key or "").strip()
    if not key:
        raise AppError(ErrorCode.VALIDATION_ERROR, "BING_SEARCH_API_KEY not configured", status_code=400)
    headers = {"Ocp-Apim-Subscription-Key": key, "User-Agent": "AtriumKB-WebSearch/1.0"}
    params = {"q": query, "count": max(1, min(count, 20)), "mkt": "zh-CN", "textDecorations": False}
    endpoint = (settings.bing_search_endpoint or "https://api.bing.microsoft.com/v7.0/search").rstrip("/")
    try:
        with httpx.Client(timeout=settings.web_search_timeout_seconds) as client:
            resp = client.get(endpoint, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"bing search failed: {exc}", status_code=502) from exc
    hits: list[WebHit] = []
    for i, item in enumerate((data.get("webPages") or {}).get("value") or []):
        url = str(item.get("url") or "")
        if not url:
            continue
        hits.append(
            WebHit(
                title=str(item.get("name") or url)[:300],
                url=url,
                snippet=str(item.get("snippet") or "")[:500],
                provider="bing",
                score=max(0.1, 1.0 - i * 0.05),
            )
        )
    return hits


def _unwrap_ddg_link(href: str) -> str:
    # DuckDuckGo HTML wraps links as //duckduckgo.com/l/?uddg=<urlencoded>
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def _duckduckgo_search(query: str, *, count: int) -> list[WebHit]:
    settings = get_settings()
    headers = {"User-Agent": "AtriumKB-WebSearch/1.0"}
    try:
        with httpx.Client(timeout=settings.web_search_timeout_seconds, follow_redirects=True) as client:
            resp = client.get("https://html.duckduckgo.com/html/", params={"q": query}, headers=headers)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as exc:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"duckduckgo search failed: {exc}", status_code=502) from exc

    hits: list[WebHit] = []
    # result blocks
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
        html,
        flags=re.I | re.S,
    ):
        url = _unwrap_ddg_link(m.group(1))
        title = re.sub(r"<[^>]+>", "", m.group(2))
        snippet = re.sub(r"<[^>]+>", "", m.group(3))
        title = re.sub(r"\s+", " ", title).strip()
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not url.startswith("http"):
            continue
        hits.append(
            WebHit(
                title=title[:300] or url,
                url=url,
                snippet=snippet[:500],
                provider="duckduckgo",
                score=max(0.1, 1.0 - len(hits) * 0.05),
            )
        )
        if len(hits) >= count:
            break
    return hits


def build_education_query(
    *,
    query: str,
    subject: str | None = None,
    stage: str | None = None,
    grade: int | None = None,
) -> str:
    parts = [query.strip()]
    if subject:
        parts.append(subject)
    if stage == "junior":
        parts.append("初中")
    elif stage == "primary":
        parts.append("小学")
    if grade:
        parts.append(f"{grade}年级")
    parts.append("教程 OR 试题 OR 课标 site:moe.gov.cn OR site:smartedu.cn OR site:neea.edu.cn")
    return " ".join(p for p in parts if p)


def web_search(
    query: str,
    *,
    limit: int = 5,
    education: bool = False,
    provider: str | None = None,
) -> list[WebHit]:
    settings = get_settings()
    if not settings.web_search_enabled:
        raise AppError(ErrorCode.FORBIDDEN, "web search disabled (WEB_SEARCH_ENABLED=false)", status_code=403)
    q = (query or "").strip()
    if not q:
        raise AppError(ErrorCode.VALIDATION_ERROR, "query required", status_code=400)
    count = max(1, min(limit, 20))
    prov = (provider or settings.web_search_provider or "fixture").strip().lower()

    if prov == "fixture" or settings.web_search_mode == "fixture":
        hits = _fixture_hits(q, education=education)
        return hits[:count]

    if settings.web_search_mode != "live":
        raise AppError(
            ErrorCode.FORBIDDEN,
            "live web search disabled; set WEB_SEARCH_MODE=live",
            status_code=403,
        )

    if prov == "brave":
        hits = _brave_search(q, count=count * 2 if education else count)
    elif prov == "bing":
        hits = _bing_search(q, count=count * 2 if education else count)
    elif prov in {"duckduckgo", "ddg"}:
        hits = _duckduckgo_search(q, count=count * 3 if education else count)
    else:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"unsupported web search provider: {prov}",
            status_code=400,
            details={"supported": ["fixture", "brave", "bing", "duckduckgo"]},
        )

    if education:
        hits = filter_allowlisted(hits)
    return hits[:count]


def serialize_web_context(hits: list[WebHit]) -> list[str]:
    blocks: list[str] = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[联网{i}] {h.title}\n来源: {h.url}\n{h.snippet}")
    return blocks


def web_hits_to_dict(hits: list[WebHit]) -> list[dict[str, Any]]:
    hosts = _allow_hosts()
    out: list[dict[str, Any]] = []
    for h in hits:
        parsed = urlparse(h.url)
        host = (parsed.hostname or "").lower()
        allowlisted = parsed.scheme == "fixture" or host in hosts or (
            host.startswith("www.") and host[4:] in hosts
        )
        out.append(
            {
                "title": h.title,
                "url": h.url,
                "snippet": h.snippet,
                "provider": h.provider,
                "score": h.score,
                "host": host or parsed.netloc,
                "allowlisted": allowlisted,
            }
        )
    return out
