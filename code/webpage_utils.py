# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Shared web utilities for MiniAgentFramework skills.
#
# Provides common HTTP fetching, HTML extraction, and text manipulation utilities used across
# the web skill modules (WebExtract, WebResearch, PageAssess, WebSearch).  Centralising these
# removes ~200 lines of near-identical code that was previously duplicated across skill files.
#
# Public API:
#   HTTP_HEADERS          -- standard browser-impersonation request headers
#   BS4_AVAILABLE         -- True if beautifulsoup4 is installed (checked once at import time)
#   SKIP_TAGS             -- HTML tags whose entire subtree is discarded during extraction
#   BLOCK_TAGS            -- HTML tags that produce paragraph boundaries in extracted text
#   NOISE_HINTS           -- attribute substrings that identify noisy layout containers
#   MIN_PARA_WORDS        -- minimum words per extracted paragraph; below this = boilerplate
#
#   fetch_html(url, timeout=15)         -> (html_text: str, final_url: str)
#   dedup_paragraphs(paragraphs)        -> list[str]
#   extract_content(html_text)          -> (page_title: str, body_text: str)
#   truncate_to_words(text, max_words)  -> str
#
# Related modules:
#   code/workspace_utils.py              -- workspace root path management
#   code/webresearch_utils.py            -- three-stage research workspace management
#   code/skills/WebExtract/              -- uses fetch_html, extract_content, truncate_to_words
#   code/skills/WebResearch/             -- uses fetch_html, extract_content, truncate_to_words
#   code/skills/PageAssess/              -- uses fetch_html
#   code/skills/WebSearch/               -- uses fetch_html
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
HTTP_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection":      "close",
}

_SPACE_RE = re.compile(r"\s+")
_TAG_RE   = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Tags whose entire subtree should be discarded during extraction.
SKIP_TAGS = frozenset({
    "script", "style", "noscript", "meta", "link", "nav",
    "header", "footer", "aside", "form", "button", "svg",
    "picture", "iframe", "figure",
})

# Tags that delimit paragraph boundaries in the extracted text.
BLOCK_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "pre",
    "div", "section", "article", "main",
})

# Attribute substrings that identify noisy layout containers (bs4 extraction path only).
NOISE_HINTS = frozenset({
    "nav", "menu", "header", "footer", "breadcrumb", "cookie", "consent",
    "signin", "login", "register", "newsletter", "share", "social",
    "advert", "ads", "sidebar", "related", "subscribe", "promo", "popup",
    "modal", "overlay", "banner", "paywall", "sticky", "tag-list", "tagslist",
    "byline", "dateline", "author-bio", "read-more", "more-articles",
    "pagination", "pager", "widget", "skip-link",
})

# Minimum words per extracted paragraph; shorter runs are treated as boilerplate.
MIN_PARA_WORDS = 15

_DEFAULT_TIMEOUT = 15


# ====================================================================================================
# MARK: HTTP FETCH
# ====================================================================================================
def fetch_html(url: str, timeout: float = _DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Fetch a URL and return (html_text, final_url).

    Handles charset detection from the Content-Type header.
    Raises on network error — never silently swallows exceptions.
    """
    request = urllib.request.Request(url=url, headers=HTTP_HEADERS, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url    = response.url
        content_type = response.headers.get("Content-Type", "")
        charset      = "utf-8"
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
# MARK: PARAGRAPH DEDUPLICATION
# ====================================================================================================
def dedup_paragraphs(paragraphs: list[str]) -> list[str]:
    """Remove near-duplicate paragraphs using the first 80 normalised characters as a key.

    Handles responsive-layout pages (e.g. BBC News) that repeat the same content blocks
    multiple times in the HTML for different viewport sizes.
    """
    seen:   set[str]  = set()
    result: list[str] = []
    for p in paragraphs:
        key = _SPACE_RE.sub(" ", p.lower().strip())[:80]
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


# ====================================================================================================
# MARK: STDLIB FALLBACK HTML EXTRACTOR
# ====================================================================================================
class _FallbackExtractor(HTMLParser):
    """Pure-stdlib HTML-to-text extractor used when BeautifulSoup is unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_body    = False
        self._buf:        list[str] = []
        self._paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "body":
            self._in_body = True
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0 or not self._in_body:
            return
        cleaned = _SPACE_RE.sub(" ", data).strip()
        if cleaned:
            self._buf.append(cleaned)

    def _flush(self) -> None:
        text = " ".join(self._buf).strip()
        if len(text.split()) >= MIN_PARA_WORDS:
            self._paragraphs.append(text)
        self._buf = []

    def get_text(self) -> str:
        self._flush()
        return "\n\n".join(dedup_paragraphs(self._paragraphs))


# ====================================================================================================
# MARK: BEAUTIFULSOUP EXTRACTOR
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


def _prune_noise_bs4(soup) -> None:
    """Remove known-noisy tags and heuristically identified layout containers in-place."""
    for tag in list(soup.find_all(list(SKIP_TAGS))):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        if any(hint in _attrs_lower(tag) for hint in NOISE_HINTS):
            tag.decompose()


def _extract_paragraphs_bs4(container) -> str:
    paragraphs = []
    for p in container.find_all("p"):
        text = _SPACE_RE.sub(" ", p.get_text(" ", strip=True)).strip()
        if len(text.split()) >= MIN_PARA_WORDS:
            paragraphs.append(text)
    return "\n\n".join(dedup_paragraphs(paragraphs))


def _extract_with_bs4(html_text: str) -> tuple[str, str]:
    """Return (page_title, body_text) using BeautifulSoup."""
    soup  = BeautifulSoup(html_text, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""

    # Prefer semantic containers for focused, cleaner extraction.
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


def _extract_with_stdlib(html_text: str) -> tuple[str, str]:
    """Return (page_title, body_text) using stdlib HTMLParser only."""
    title_match = _TITLE_RE.search(html_text)
    title       = _html.unescape(_TAG_RE.sub("", title_match.group(1))).strip() if title_match else ""
    extractor   = _FallbackExtractor()
    try:
        extractor.feed(html_text)
    except Exception:
        pass
    return title, extractor.get_text()


# ====================================================================================================
# MARK: PUBLIC: CONTENT EXTRACTION
# ====================================================================================================
def extract_content(html_text: str) -> tuple[str, str]:
    """Dispatch to the best available extractor and return (page_title, body_text).

    Uses BeautifulSoup when available; falls back to the stdlib html.parser extractor.
    """
    if BS4_AVAILABLE:
        return _extract_with_bs4(html_text)
    return _extract_with_stdlib(html_text)


# ====================================================================================================
# MARK: PUBLIC: TEXT UTILITIES
# ====================================================================================================
def truncate_to_words(text: str, max_words: int) -> str:
    """Return text truncated to at most max_words words, appending '...[truncated]' if cut."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n...[truncated]"
