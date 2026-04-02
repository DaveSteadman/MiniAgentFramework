# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebSearch skill for the MiniAgentFramework.
#
# Searches DuckDuckGo Lite (lite.duckduckgo.com) - no API key, no JavaScript required.
# Uses Python stdlib (urllib) only; no mandatory third-party dependencies.
# Returns structured result lists suitable for direct LLM consumption.
#
# Related modules:
#   - main.py                          -- orchestration entry point
#   - skills/WebFetch/                 -- companion skill to fetch + extract page content
#   - skills_catalog_builder.py        -- reads skill.md to build the catalog
#   - webpage_utils.py                 -- HTTP fetch utility (shared)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import re
import time
import urllib.parse

from utils.webpage_utils import fetch_html as _fetch_html


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DDG_URL      = "https://lite.duckduckgo.com/lite/?q={q}"
_DDG_PAGE_URL = "https://lite.duckduckgo.com/lite/?q={q}&s={s}&dc={dc}"  # pagination (best-effort GET)

# DDG wraps outbound links in an internal redirect; decode to extract the real destination URL.
_REDIRECT_RE = re.compile(r"/l/\?uddg=([^&\"'>]+)")

# DuckDuckGo Lite result block patterns.
# Lite uses single-quoted attributes and puts href before class:
#   <a rel="nofollow" href="//duckduckgo.com/l/?uddg=..." class='result-link'>Title</a>
_ANCHOR_RE  = re.compile(
    r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]+class=[\"']result-link[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r"class=[\"']result-snippet[\"'][^>]*>(.*?)</(?:a|div|td)>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

MAX_RESULTS_CAP          = 10
TIMEOUT_SECONDS_CAP      = 30
MAX_CHARS_PER_RESULT_CAP = 2000
DEFAULT_MAX_RESULTS      = 5
DEFAULT_TIMEOUT          = 15
DEFAULT_MAX_CHARS        = 500
_SEARCH_PAGE_SIZE        = 30
_ARTICLE_SCAN_PAGES      = 3

_HUB_PATH_MARKERS = (
    "/category/",
    "/categories/",
    "/topic/",
    "/topics/",
    "/section/",
    "/sections/",
    "/tag/",
    "/tags/",
    "/archive",
    "/archives",
    "/latest",
    "/trending",
)
_SEARCH_PATH_MARKERS = (
    "/search",
    "/topics/",
)
_SEARCH_QUERY_KEYS = frozenset({"q", "query", "search", "text", "keyword", "keywords"})
_DATE_PATH_RE = re.compile(r"/(?:19|20)\d{2}/\d{1,2}/\d{1,2}/")


# ====================================================================================================
# MARK: INTERNAL HELPERS
# ====================================================================================================
def _strip_html(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = _html.unescape(cleaned)
    return _SPACE_RE.sub(" ", cleaned).strip()


# ----------------------------------------------------------------------------------------------------
def _decode_ddg_url(href: str) -> str:
    """Unwrap DuckDuckGo's /l/?uddg= redirect layer to get the real destination URL."""
    match = _REDIRECT_RE.search(href)
    if match:
        try:
            return urllib.parse.unquote(match.group(1))
        except Exception:
            return href
    return href


# ----------------------------------------------------------------------------------------------------
def _is_ddg_ad(url: str) -> bool:
    """Return True if a decoded URL is still a DuckDuckGo tracking/ad URL.

    DuckDuckGo ads use a /y.js?ad_domain=... href instead of the /l/?uddg= organic
    redirect.  The decoder does not recognise this format so the raw tracking URL
    passes through unchanged - these should be excluded from results.
    """
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return host == "duckduckgo.com" or host.endswith(".duckduckgo.com")
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------------
def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


# ----------------------------------------------------------------------------------------------------
def _classify_result_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "other"

    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query_keys = {k.lower() for k in urllib.parse.parse_qs(parsed.query).keys()}

    if not path or path == "/":
        return "homepage"

    if host.startswith("news.google.") and "/topics/" in path:
        return "search-results"

    if any(marker in path for marker in _SEARCH_PATH_MARKERS) and query_keys.intersection(_SEARCH_QUERY_KEYS):
        return "search-results"

    if any(marker in path for marker in _HUB_PATH_MARKERS):
        return "hub"

    parts = [part for part in path.split("/") if part]
    last_part = parts[-1] if parts else ""

    if _DATE_PATH_RE.search(path):
        return "article"

    if "/news/" in path:
        if "-" in last_part or re.search(r"\d", last_part):
            return "article"
        return "hub"

    if len(parts) >= 3 and "-" in last_part and len(last_part) >= 12:
        return "article"

    return "other"


# ----------------------------------------------------------------------------------------------------
def _result_kind_priority(page_kind: str) -> int:
    if page_kind == "article":
        return 0
    if page_kind == "other":
        return 1
    if page_kind == "hub":
        return 2
    if page_kind == "homepage":
        return 3
    if page_kind == "search-results":
        return 4
    return 5


# ----------------------------------------------------------------------------------------------------
def _annotate_results(results: list[dict]) -> list[dict]:
    annotated: list[dict] = []
    for result in results:
        enriched = dict(result)
        enriched["page_kind"] = _classify_result_url(str(result.get("url", "")))
        annotated.append(enriched)
    return annotated


# ====================================================================================================
# MARK: DDG RESULT EXTRACTION
# ====================================================================================================
def _extract_ddg_results(html_text: str, max_results: int) -> list[dict]:
    results  = []
    anchors  = list(_ANCHOR_RE.finditer(html_text))
    snippets = list(_SNIPPET_RE.finditer(html_text))

    for index, anchor in enumerate(anchors):
        if len(results) >= max_results:
            break
        try:
            href  = anchor.group(1)
            title = _strip_html(anchor.group(2))
            url   = _decode_ddg_url(href)

            if not title or not url or url.startswith("/") or url.startswith("//") or _is_ddg_ad(url):
                continue

            snippet = _strip_html(snippets[index].group(1)) if index < len(snippets) else ""

            results.append({
                "rank":    len(results) + 1,
                "title":   title,
                "url":     url,
                "snippet": snippet,
            })
        except Exception:
            continue

    return results


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def search_web(
    query: str = "",
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    offset: int = 0,
    prefer_article_urls: bool = False,
    # Accept common aliases that models often use instead of the canonical names:
    num_results: int | None = None,
    limit: int | None = None,
    n: int | None = None,
    **kwargs,
) -> list[dict]:
    """Search DuckDuckGo and return a structured list of results.

    Returns a list of dicts: [{"rank": int, "title": str, "url": str, "snippet": str}, ...]
    Returns a single error-entry dict on network or parse failure - never raises.

    offset: skip this many results (multiples of 30 recommended). Uses a GET-based paging
    request - results may vary by query. Use offset=0 (default) unless the first page
    returned no useful results.
    """
    # Absorb query aliases the model may send instead of 'query'.
    if not query:
        for alias in ("search_query", "q", "text", "keywords", "search", "term"):
            if alias in kwargs:
                query = str(kwargs[alias])
                break

    if not query or not query.strip():
        return [{"rank": 0, "title": "Error", "url": "", "snippet": "query cannot be empty"}]

    # Resolve whichever count alias the model used, preferring the canonical name.
    effective_max   = num_results if num_results is not None else (limit if limit is not None else (n if n is not None else max_results))
    max_results         = max(1, min(int(effective_max),   MAX_RESULTS_CAP))
    timeout_seconds     = max(5, min(int(timeout_seconds), TIMEOUT_SECONDS_CAP))
    offset              = max(0, int(offset))
    prefer_article_urls = _coerce_bool(prefer_article_urls or kwargs.get("article_only") or kwargs.get("prefer_articles"))

    encoded = urllib.parse.quote_plus(query.strip())
    seen_urls: set[str] = set()
    collected_results: list[dict] = []
    pages_to_scan = _ARTICLE_SCAN_PAGES if prefer_article_urls else 1

    for page_index in range(pages_to_scan):
        current_offset = offset + (page_index * _SEARCH_PAGE_SIZE)
        if current_offset > 0:
            search_url = _DDG_PAGE_URL.format(q=encoded, s=current_offset, dc=current_offset + 1)
        else:
            search_url = _DDG_URL.format(q=encoded)

        try:
            html_text, _ = _fetch_html(search_url, timeout=float(timeout_seconds))
        except Exception as exc:
            return [{"rank": 0, "title": "Search failed", "url": "", "snippet": str(exc)}]

        page_results = _annotate_results(_extract_ddg_results(html_text, max_results))
        for result in page_results:
            url = str(result.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected_results.append(result)

        # Throttle between successive calls to avoid rate-limiting on rapid multi-query tasks.
        # Always sleep - including on empty results - to prevent rapid-fire requests when DDG
        # is returning a rate-limit/CAPTCHA page (which has no result-link elements).
        time.sleep(2.0)

        if not prefer_article_urls:
            break

        article_count = sum(1 for item in collected_results if item.get("page_kind") == "article")
        if article_count >= max_results:
            break

    if not collected_results:
        return [{"rank": 0, "title": "No results", "url": "", "snippet": f"DuckDuckGo returned no results for: {query}"}]

    if prefer_article_urls:
        collected_results = sorted(
            collected_results,
            key=lambda item: (_result_kind_priority(str(item.get("page_kind", "other"))), int(item.get("rank", 999))),
        )

    final_results = []
    for index, result in enumerate(collected_results[:max_results], start=1):
        enriched = dict(result)
        enriched["rank"] = index
        final_results.append(enriched)

    return final_results


# ----------------------------------------------------------------------------------------------------
def search_web_text(
    query: str = "",
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    max_chars_per_result: int = DEFAULT_MAX_CHARS,
    offset: int = 0,
    prefer_article_urls: bool = False,
    # Accept common aliases:
    num_results: int | None = None,
    limit: int | None = None,
    n: int | None = None,
    **kwargs,
) -> str:
    """Search DuckDuckGo and return a plain-text formatted result block for LLM consumption.

    Each result is formatted as:
        [1] Title
            https://example.com
            Snippet text describing the result.

    max_chars_per_result caps the snippet length per result to limit token consumption.
    Set to 0 to disable truncation.
    """
    if not query:
        for alias in ("search_query", "q", "text", "keywords", "search", "term"):
            if alias in kwargs:
                query = str(kwargs[alias])
                break

    effective_max = num_results if num_results is not None else (limit if limit is not None else (n if n is not None else max_results))
    results = search_web(
        query=query,
        max_results=int(effective_max),
        timeout_seconds=int(timeout_seconds),
        offset=int(offset),
        prefer_article_urls=prefer_article_urls or kwargs.get("article_only") or kwargs.get("prefer_articles"),
    )

    char_cap = max(0, min(int(max_chars_per_result), MAX_CHARS_PER_RESULT_CAP)) if int(max_chars_per_result) > 0 else 0

    lines = [f"Web search results for: {query}", ""]
    for r in results:
        rank    = r.get("rank", "?")
        title   = r.get("title", "")
        url     = r.get("url",   "")
        snippet = r.get("snippet", "")
        page_kind = str(r.get("page_kind", "")).strip()

        if char_cap and len(snippet) > char_cap:
            snippet = snippet[:char_cap] + "..."

        kind_suffix = f" [{page_kind}]" if page_kind else ""
        lines.append(f"[{rank}] {title}{kind_suffix}")
        if url:
            lines.append(f"    {url}")
        if snippet:
            lines.append(f"    {snippet}")
        lines.append("")

    return "\n".join(lines).strip()
