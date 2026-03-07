# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebResearch (Mine stage) skill for MiniAgentFramework.
#
# Gen3 web mining skill — fetches single URLs or runs DuckDuckGo searches, formats the
# retrieved content as structured Markdown, and writes files into the 01-Mine stage of the
# web research workspace managed by webresearch_utils.py.
#
# This skill is intentionally self-contained: HTTP fetching and HTML extraction are
# implemented here directly (no dependency on sibling skill modules) so the file can be
# loaded by the framework's dynamic importlib loader without path-resolution complications.
#
# Primary public functions:
#   mine_url(url, domain, slug=None, max_words=600)
#     -> Fetches a URL, extracts readable text, saves source.md in 01-Mine
#   mine_search(query, domain, max_results=5)
#     -> Runs a DuckDuckGo search, saves results.md in 01-Mine
#
# Both functions return:
#   - Confirmation string "Saved: <path>"  on success.
#   - Error string starting with "Error:"  on failure — never raises.
#
# Related modules:
#   - webresearch_utils.py -- path management for the three-stage research area
#   - workspace_utils.py   -- workspace root (consumed transitively via webresearch_utils)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as _date
from html.parser import HTMLParser

from webresearch_utils import STAGE_MINE
from webresearch_utils import create_item_dir

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection":      "close",
}

_SPACE_RE = re.compile(r"\s+")

# Tags whose entire subtree should be discarded during extraction.
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "meta", "link", "nav",
    "header", "footer", "aside", "form", "button", "svg",
    "picture", "iframe", "figure",
})

# Tags that delimit paragraph boundaries in the extracted text.
_BLOCK_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "pre",
    "div", "section", "article", "main",
})

# Attribute substrings that identify noisy layout containers (bs4 path only).
_NOISE_HINTS = frozenset({
    "nav", "menu", "header", "footer", "breadcrumb", "cookie", "consent",
    "signin", "login", "register", "newsletter", "share", "social",
    "advert", "ads", "sidebar", "related", "subscribe",
})

# DuckDuckGo HTML search endpoint and result extraction patterns.
_DDG_URL     = "https://duckduckgo.com/html/?q={q}"
_REDIRECT_RE = re.compile(r"/l/\?uddg=([^&\"'>]+)")
_ANCHOR_RE   = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE  = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE      = re.compile(r"<[^>]+>")
_TITLE_RE    = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

MAX_WORDS_CAP    = 1200
DEFAULT_TIMEOUT  = 15


# ====================================================================================================
# MARK: STDLIB FALLBACK HTML EXTRACTOR
# ====================================================================================================
class _FallbackExtractor(HTMLParser):
    """Pure-stdlib HTML-to-text extractor used when BeautifulSoup is unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_body    = False
        self._buf: list[str]        = []
        self._paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "body":
            self._in_body = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0 or not self._in_body:
            return
        cleaned = _SPACE_RE.sub(" ", data).strip()
        if cleaned:
            self._buf.append(cleaned)

    def _flush(self) -> None:
        text = " ".join(self._buf).strip()
        if len(text.split()) >= 5:
            self._paragraphs.append(text)
        self._buf = []

    def get_text(self) -> str:
        self._flush()
        return "\n\n".join(self._paragraphs)


# ====================================================================================================
# MARK: INTERNAL: HTTP FETCH
# ====================================================================================================
def _fetch_html(url: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Fetch a URL and return (html_text, final_url).  Raises on network error."""
    request = urllib.request.Request(url=url, headers=_HEADERS, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url    = response.url
        content_type = response.headers.get("Content-Type", "")
        charset = "utf-8"
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("charset="):
                charset = part[8:].strip() or "utf-8"
                break
        raw = response.read()
    try:
        return raw.decode(charset, errors="replace"), final_url
    except LookupError:
        return raw.decode("utf-8", errors="replace"), final_url


# ====================================================================================================
# MARK: INTERNAL: HTML → TEXT EXTRACTION
# ====================================================================================================
def _attrs_lower(tag) -> str:
    """Concatenate id, class, and role attribute values for noise-hint matching."""
    parts   = []
    tag_id  = tag.get("id")
    classes = tag.get("class")
    role    = tag.get("role")
    if tag_id:
        parts.append(str(tag_id).lower())
    if isinstance(classes, list):
        parts.extend(c.lower() for c in classes)
    elif classes:
        parts.append(str(classes).lower())
    if role:
        parts.append(str(role).lower())
    return " ".join(parts)


# ----------------------------------------------------------------------------------------------------
def _prune_noise_bs4(soup) -> None:
    """Remove known-noisy tags and heuristically identified layout containers in-place."""
    for tag in list(soup.find_all(list(_SKIP_TAGS))):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        if any(hint in _attrs_lower(tag) for hint in _NOISE_HINTS):
            tag.decompose()


# ----------------------------------------------------------------------------------------------------
def _extract_paragraphs_bs4(container) -> str:
    paragraphs = []
    for p in container.find_all("p"):
        text = _SPACE_RE.sub(" ", p.get_text(" ", strip=True)).strip()
        if len(text.split()) >= 8:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


# ----------------------------------------------------------------------------------------------------
def _extract_with_bs4(html_text: str) -> tuple[str, str]:
    """Return (page_title, body_text) using BeautifulSoup."""
    soup  = BeautifulSoup(html_text, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""

    # Prefer semantic containers for cleaner extraction.
    for selector in ["article", "main", "[role='main']"]:
        container = soup.select_one(selector)
        if container:
            _prune_noise_bs4(container)
            body = _extract_paragraphs_bs4(container)
            if len(body.split()) >= 60:
                return title, body

    # Fall back to full-page paragraph scan.
    _prune_noise_bs4(soup)
    body = _extract_paragraphs_bs4(soup)
    return title, body or _SPACE_RE.sub(" ", soup.get_text(separator=" ", strip=True)).strip()


# ----------------------------------------------------------------------------------------------------
def _extract_with_stdlib(html_text: str) -> tuple[str, str]:
    """Return (page_title, body_text) using stdlib HTMLParser only."""
    title_match = _TITLE_RE.search(html_text)
    title       = _html.unescape(_TAG_RE.sub("", title_match.group(1))).strip() if title_match else ""

    extractor = _FallbackExtractor()
    try:
        extractor.feed(html_text)
    except Exception:
        pass
    return title, extractor.get_text()


# ----------------------------------------------------------------------------------------------------
def _extract_content(html_text: str) -> tuple[str, str]:
    """Dispatch to the best available extractor. Returns (title, body_text)."""
    if _BS4_AVAILABLE:
        return _extract_with_bs4(html_text)
    return _extract_with_stdlib(html_text)


# ----------------------------------------------------------------------------------------------------
def _truncate_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n...[truncated]"


# ====================================================================================================
# MARK: INTERNAL: DUCKDUCKGO SEARCH
# ====================================================================================================
def _strip_html(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = _html.unescape(cleaned)
    return _SPACE_RE.sub(" ", cleaned).strip()


# ----------------------------------------------------------------------------------------------------
def _decode_ddg_url(href: str) -> str:
    """Unwrap DuckDuckGo's /l/?uddg= redirect to get the real destination URL."""
    match = _REDIRECT_RE.search(href)
    if match:
        try:
            return urllib.parse.unquote(match.group(1))
        except Exception:
            return href
    return href


# ----------------------------------------------------------------------------------------------------
def _ddg_search(query: str, max_results: int, timeout: int) -> list[dict]:
    """Run a DuckDuckGo HTML search and return a list of result dicts."""
    encoded    = urllib.parse.quote_plus(query.strip())
    search_url = _DDG_URL.format(q=encoded)
    html_text, _ = _fetch_html(search_url, timeout=float(timeout))

    results  = []
    anchors  = list(_ANCHOR_RE.finditer(html_text))
    snippets = list(_SNIPPET_RE.finditer(html_text))

    for idx, anchor in enumerate(anchors):
        if len(results) >= max_results:
            break
        try:
            href    = anchor.group(1)
            title   = _strip_html(anchor.group(2))
            url     = _decode_ddg_url(href)
            if not title or not url or url.startswith("/"):
                continue
            snippet = _strip_html(snippets[idx].group(1)) if idx < len(snippets) else ""
            results.append({"rank": len(results) + 1, "title": title, "url": url, "snippet": snippet})
        except Exception:
            continue

    return results


# ====================================================================================================
# MARK: INTERNAL: MARKDOWN FORMATTERS
# ====================================================================================================
def _format_source_md(title: str, url: str, domain: str, body: str) -> str:
    """Format a mined URL as a structured Markdown document."""
    today = _date.today().isoformat()
    lines = [
        f"# {title or url}",
        "",
        f"**Source URL:** {url}",
        f"**Mined:** {today}",
        f"**Domain:** {domain}",
        "",
        "---",
        "",
        "## Content",
        "",
        body,
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def _format_results_md(query: str, domain: str, results: list[dict]) -> str:
    """Format a list of search results as a structured Markdown document."""
    today = _date.today().isoformat()
    lines = [
        f"# Search: {query}",
        "",
        f"**Query:** {query}",
        f"**Searched:** {today}",
        f"**Domain:** {domain}",
        f"**Results returned:** {len(results)}",
        "",
        "---",
        "",
        "## Results",
        "",
    ]
    for r in results:
        rank    = r.get("rank", "?")
        title   = r.get("title", "")
        url     = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"### [{rank}] {title}")
        if url:
            lines.append(f"- **URL:** {url}")
        if snippet:
            lines.append(f"- **Snippet:** {snippet}")
        lines.append("")
    return "\n".join(lines)


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def mine_url(
    url: str,
    domain: str,
    slug: str | None = None,
    max_words: int = 600,
) -> str:
    """Fetch a URL, extract its readable content, and save it as source.md in the Mine stage.

    Saves to:  webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/source.md

    Returns a confirmation string "Saved: <path>" on success, or an "Error: ..." string
    on failure.  Never raises.
    """
    if not url or not url.strip():
        return "Error: url cannot be empty."

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return f"Error: unsupported URL scheme '{parsed.scheme}'. Only http and https are supported."

    max_words = max(50, min(int(max_words), MAX_WORDS_CAP))

    try:
        html_text, final_url = _fetch_html(url.strip())
    except Exception as exc:
        return f"Error: failed to fetch {url!r}: {exc}"

    try:
        title, body = _extract_content(html_text)
    except Exception as exc:
        return f"Error: failed to extract content from {url!r}: {exc}"

    body = _truncate_to_words(body, max_words)

    item_slug   = slug or title or url.split("/")[-1] or "page"
    item_dir    = create_item_dir(STAGE_MINE, domain, item_slug)
    output_path = item_dir / "source.md"

    try:
        output_path.write_text(_format_source_md(title, final_url, domain, body), encoding="utf-8")
    except Exception as exc:
        return f"Error: failed to write {output_path}: {exc}"

    return f"Saved: {output_path}"


# ----------------------------------------------------------------------------------------------------
def mine_search(
    query: str,
    domain: str,
    max_results: int = 5,
) -> str:
    """Run a DuckDuckGo search and save the result list as results.md in the Mine stage.

    Saves to:  webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-search-<query>/results.md

    Returns a confirmation string "Saved: <path>" on success, or an "Error: ..." string
    on failure.  Never raises.
    """
    if not query or not query.strip():
        return "Error: query cannot be empty."
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    max_results = max(1, min(int(max_results), 10))

    try:
        results = _ddg_search(query.strip(), max_results=max_results, timeout=DEFAULT_TIMEOUT)
    except Exception as exc:
        return f"Error: search failed for {query!r}: {exc}"

    if not results:
        results = [{"rank": 0, "title": "No results", "url": "", "snippet": f"DuckDuckGo returned no results for: {query}"}]

    item_dir    = create_item_dir(STAGE_MINE, domain, f"search-{query}")
    output_path = item_dir / "results.md"

    try:
        output_path.write_text(_format_results_md(query.strip(), domain, results), encoding="utf-8")
    except Exception as exc:
        return f"Error: failed to write {output_path}: {exc}"

    return f"Saved: {output_path}"
