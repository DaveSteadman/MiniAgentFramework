# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebSearch skill for the MiniAgentFramework.
#
# Searches DuckDuckGo HTML (no API key required) and returns structured result lists.
# All network I/O uses Python stdlib (urllib) so there are no mandatory third-party dependencies.
#
# Searches DuckDuckGo HTML using a single-file skill pattern with a clean, model-callable function surface.
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
import urllib.parse

from webpage_utils import fetch_html as _fetch_html


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DDG_URL      = "https://duckduckgo.com/html/?q={q}"
_DDG_PAGE_URL = "https://duckduckgo.com/html/?q={q}&s={s}&dc={dc}"  # pagination (best-effort GET)

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

MAX_RESULTS_CAP          = 10
TIMEOUT_SECONDS_CAP      = 30
MAX_CHARS_PER_RESULT_CAP = 2000
DEFAULT_MAX_RESULTS      = 5
DEFAULT_TIMEOUT          = 15
DEFAULT_MAX_CHARS        = 500


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

            if not title or not url or url.startswith("/") or _is_ddg_ad(url):
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
    max_results     = max(1, min(int(effective_max),   MAX_RESULTS_CAP))
    timeout_seconds = max(5, min(int(timeout_seconds), TIMEOUT_SECONDS_CAP))
    offset          = max(0, int(offset))

    encoded     = urllib.parse.quote_plus(query.strip())
    if offset > 0:
        search_url = _DDG_PAGE_URL.format(q=encoded, s=offset, dc=offset + 1)
    else:
        search_url = _DDG_URL.format(q=encoded)

    try:
        html_text, _ = _fetch_html(search_url, timeout=float(timeout_seconds))
    except Exception as exc:
        return [{"rank": 0, "title": "Search failed", "url": "", "snippet": str(exc)}]

    results = _extract_ddg_results(html_text, max_results)

    if not results:
        return [{"rank": 0, "title": "No results", "url": "", "snippet": f"DuckDuckGo returned no results for: {query}"}]

    return results


# ----------------------------------------------------------------------------------------------------
def search_web_text(
    query: str = "",
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    max_chars_per_result: int = DEFAULT_MAX_CHARS,
    offset: int = 0,
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
    results = search_web(query=query, max_results=int(effective_max), timeout_seconds=timeout_seconds, offset=offset)

    char_cap = max(0, min(int(max_chars_per_result), MAX_CHARS_PER_RESULT_CAP)) if max_chars_per_result > 0 else 0

    lines = [f"Web search results for: {query}", ""]
    for r in results:
        rank    = r.get("rank", "?")
        title   = r.get("title", "")
        url     = r.get("url",   "")
        snippet = r.get("snippet", "")

        if char_cap and len(snippet) > char_cap:
            snippet = snippet[:char_cap] + "..."

        lines.append(f"[{rank}] {title}")
        if url:
            lines.append(f"    {url}")
        if snippet:
            lines.append(f"    {snippet}")
        lines.append("")

    return "\n".join(lines).strip()
