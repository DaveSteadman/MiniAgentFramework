# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebSearch skill for the MiniAgentFramework.
#
# Searches DuckDuckGo HTML (no API key required) and returns structured result lists.
# All network I/O uses Python stdlib (urllib) so there are no mandatory third-party dependencies.
#
# Inspired by Gen2WebSearch from OpenClawTest (DaveSteadman), adapted to this framework's
# single-file skill pattern with a simplified, planner-friendly function surface.
#
# Related modules:
#   - main.py                          -- orchestration entry point
#   - skills/WebExtract/               -- companion skill to fetch + extract page content
#   - skills_catalog_builder.py        -- reads skill.md to build the catalog
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import re
import urllib.error
import urllib.parse
import urllib.request


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DDG_URL = "https://duckduckgo.com/html/?q={q}"

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection":      "close",
}

# DDG wraps outbound links in an internal redirect; decode to extract the real destination URL.
_REDIRECT_RE = re.compile(r"/l/\?uddg=([^&\"'>]+)")

# DuckDuckGo HTML result block patterns (same extraction approach as Gen2WebSearch reference).
_ANCHOR_RE  = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

MAX_RESULTS_CAP     = 10
TIMEOUT_SECONDS_CAP = 30
DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT     = 15


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
def _fetch_html(url: str, timeout: float) -> str:
    request = urllib.request.Request(url=url, headers=_HEADERS, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = "utf-8"
        content_type = response.headers.get("Content-Type", "")
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("charset="):
                charset = part[8:].strip() or "utf-8"
                break
        raw = response.read()
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


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

            if not title or not url or url.startswith("/"):
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
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Search DuckDuckGo and return a structured list of results.

    Returns a list of dicts: [{"rank": int, "title": str, "url": str, "snippet": str}, ...]
    Returns a single error-entry dict on network or parse failure — never raises.
    """
    if not query or not query.strip():
        return [{"rank": 0, "title": "Error", "url": "", "snippet": "query cannot be empty"}]

    max_results     = max(1, min(int(max_results),     MAX_RESULTS_CAP))
    timeout_seconds = max(5, min(int(timeout_seconds), TIMEOUT_SECONDS_CAP))

    encoded    = urllib.parse.quote_plus(query.strip())
    search_url = _DDG_URL.format(q=encoded)

    try:
        html_text = _fetch_html(search_url, timeout=float(timeout_seconds))
    except Exception as exc:
        return [{"rank": 0, "title": "Search failed", "url": "", "snippet": str(exc)}]

    results = _extract_ddg_results(html_text, max_results)

    if not results:
        return [{"rank": 0, "title": "No results", "url": "", "snippet": f"DuckDuckGo returned no results for: {query}"}]

    return results


# ----------------------------------------------------------------------------------------------------
def search_web_text(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> str:
    """Search DuckDuckGo and return a plain-text formatted result block for LLM consumption.

    Each result is formatted as:
        [1] Title
            https://example.com
            Snippet text describing the result.
    """
    results = search_web(query=query, max_results=max_results, timeout_seconds=timeout_seconds)

    lines = [f"Web search results for: {query}", ""]
    for r in results:
        rank    = r.get("rank", "?")
        title   = r.get("title", "")
        url     = r.get("url",   "")
        snippet = r.get("snippet", "")

        lines.append(f"[{rank}] {title}")
        if url:
            lines.append(f"    {url}")
        if snippet:
            lines.append(f"    {snippet}")
        lines.append("")

    return "\n".join(lines).strip()
