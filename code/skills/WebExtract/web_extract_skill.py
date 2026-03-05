# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebExtract skill for the MiniAgentFramework.
#
# Fetches a web page by URL and extracts readable prose text, stripping all HTML markup, navigation,
# scripts, headers, footers, and other noise. Returns clean text suitable for an LLM to synthesize
# or summarize.
#
# Uses BeautifulSoup for high-quality content extraction (installed as a project dependency).
# Falls back gracefully to a stdlib-only html.parser extractor if BeautifulSoup is unavailable.
#
# Typical planner usage:
#   1. WebSearch returns a list of results with URLs.
#   2. WebExtract fetches the most relevant URL and returns readable content.
#   3. The final LLM call synthesizes an answer from that content.
#
# Related modules:
#   - skills/WebSearch/web_search_skill.py -- upstream skill that produces URLs to extract
#   - main.py                              -- orchestration entry point
#   - skills_catalog_builder.py            -- reads skill.md to build the catalog
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

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

# Tags whose entire content (including children) should be discarded.
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "meta", "link", "nav",
    "header", "footer", "aside", "form", "button", "svg",
    "picture", "iframe", "figure",
})

# Tags that introduce paragraph breaks in the extracted text.
_BLOCK_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "pre",
    "div", "section", "article", "main",
})

# Class/id hint substrings for noisy sidebar/navigation containers (bs4 path).
_NOISE_HINTS = frozenset({
    "nav", "menu", "header", "footer", "breadcrumb", "cookie", "consent",
    "signin", "login", "register", "newsletter", "share", "social",
    "advert", "ads", "sidebar", "related", "subscribe",
})

MAX_WORDS_CAP     = 800
DEFAULT_MAX_WORDS = 400
DEFAULT_TIMEOUT   = 15


# ====================================================================================================
# MARK: STDLIB FALLBACK EXTRACTOR
# ====================================================================================================
class _FallbackExtractor(HTMLParser):
    """Pure-stdlib HTML → clean text extractor used when BeautifulSoup is unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth  = 0
        self._in_body     = False
        self._buf: list[str] = []
        self._paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "body":
            self._in_body = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BLOCK_TAGS:
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
        return " ".join(self._paragraphs)


# ====================================================================================================
# MARK: BEAUTIFULSOUP EXTRACTOR
# ====================================================================================================
def _attrs_lower(tag) -> str:
    """Concatenate id, class, role attrs for noise-hint matching."""
    parts = []
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
    """Remove script/style/nav/etc. and heuristically noisy containers in-place."""
    for tag in list(soup.find_all(list(_SKIP_TAGS))):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        attr_text = _attrs_lower(tag)
        if any(hint in attr_text for hint in _NOISE_HINTS):
            tag.decompose()


# ----------------------------------------------------------------------------------------------------
def _extract_paragraphs_bs4(container) -> str:
    paragraphs = []
    for p in container.find_all("p"):
        text = _SPACE_RE.sub(" ", p.get_text(" ", strip=True)).strip()
        if len(text.split()) >= 8:
            paragraphs.append(text)
    return " ".join(paragraphs)


# ----------------------------------------------------------------------------------------------------
def _extract_with_bs4(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    # Try semantic containers first: <article>, <main>, [role=main]
    for selector in ["article", "main", "[role='main']"]:
        container = soup.select_one(selector)
        if container:
            _prune_noise_bs4(container)
            para_text = _extract_paragraphs_bs4(container)
            if len(para_text.split()) >= 60:
                return para_text

    # Fall back to full-page paragraph extraction
    _prune_noise_bs4(soup)
    para_text = _extract_paragraphs_bs4(soup)
    if para_text:
        return para_text

    # Last resort: all visible text
    return _SPACE_RE.sub(" ", soup.get_text(separator=" ", strip=True)).strip()


# ====================================================================================================
# MARK: HTTP FETCH
# ====================================================================================================
def _fetch_page_html(url: str, timeout: float) -> tuple[str, str]:
    """Fetch a URL and return (html_text, final_url)."""
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
# MARK: INTERNAL EXTRACTION DISPATCHER
# ====================================================================================================
def _extract_text(html_text: str) -> str:
    if _BS4_AVAILABLE:
        return _extract_with_bs4(html_text)

    extractor = _FallbackExtractor()
    try:
        extractor.feed(html_text)
    except Exception:
        pass
    return extractor.get_text()


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def fetch_page_text(
    url: str,
    max_words: int = DEFAULT_MAX_WORDS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> str:
    """Fetch a web page and return its clean readable text, stripped of all HTML markup.

    Removes navigation, scripts, advertisements, and other non-content elements.
    Returns up to max_words words of body prose suitable for LLM consumption.
    Returns a descriptive error string on network/parse failure — never raises.
    """
    if not url or not url.strip():
        return "Error: url cannot be empty."

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return f"Error: unsupported URL scheme '{parsed.scheme}'. Only http and https are supported."

    max_words       = max(50, min(int(max_words),       MAX_WORDS_CAP))
    timeout_seconds = max(5,  min(int(timeout_seconds), 60))

    try:
        html_text, _ = _fetch_page_html(url.strip(), timeout=float(timeout_seconds))
    except urllib.error.HTTPError as exc:
        return f"Error fetching page: HTTP {exc.code} — {url}"
    except urllib.error.URLError as exc:
        return f"Error fetching page: {exc.reason} — {url}"
    except Exception as exc:
        return f"Error fetching page: {exc} — {url}"

    text = _extract_text(html_text)

    if not text.strip():
        return f"Could not extract readable text from: {url}"

    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]) + " ...[truncated]"

    return text
