# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# PageAssess skill for MiniAgentFramework.
#
# Fetches a URL and classifies it as an "article", "index", or "mixed" page using lightweight
# heuristics - no LLM call is made.  Returns a structured assessment including:
#   - page_type    : "article", "index", or "mixed"
#   - word_count   : deduped prose words extracted
#   - link_count   : article-candidate links found in the content area
#   - prose_preview: first 100 words of prose
#   - article_links: up to max_links links, filtered/ranked by topic relevance
#
# Primary public function:
#   assess_page(url, topic="", max_links=10)
#     -> Returns a dict - never raises; returns {"error": "..."} on failure.
#
# This skill does NOT write any files to disk.
#
# Related modules:
#   - WebMine skill     -- mine_url / mine_search to persist content
#   - WebExtract skill  -- fetch prose text from a known article URL (ephemeral, no save)
#   - webpage_utils.py  -- HTTP fetch utility (shared)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import re
import urllib.error
import urllib.parse
from html.parser import HTMLParser

from webpage_utils import fetch_html as _fetch_html

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SPACE_RE = re.compile(r"\s+")
_WORD_RE  = re.compile(r"\b\w{3,}\b")

# Tags whose entire subtree should be discarded (no prose, no useful links).
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "meta", "link",
    "button", "svg", "picture", "iframe",
})

# Tags that also carry navigation noise - pruned from the content container.
_NAV_SKIP_TAGS = frozenset({
    "nav", "header", "footer", "aside", "form",
})

# Tags that introduce paragraph breaks.
_BLOCK_TAGS = frozenset({
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "pre",
    "div", "section", "article", "main",
})

# Attribute substrings that identify noisy layout containers (bs4 path).
_NOISE_HINTS = frozenset({
    "nav", "menu", "header", "footer", "breadcrumb", "cookie", "consent",
    "signin", "login", "register", "newsletter", "share", "social",
    "advert", "ads", "sidebar", "related", "subscribe",
})

# Classification thresholds
_ARTICLE_MIN_WORDS = 300   # minimum prose words to qualify as article
_INDEX_MAX_WORDS   = 150   # pages below this word count are always treated as index
_ARTICLE_MAX_RATIO = 4.0   # max links-per-100-words for article classification
_INDEX_MIN_RATIO   = 7.0   # links-per-100-words above this → index

MAX_LINKS_CAP  = 20
PREVIEW_WORDS  = 100
DEFAULT_TIMEOUT = 15


# ====================================================================================================
# MARK: PARAGRAPH DEDUPLICATION
# ====================================================================================================
def _dedup_paragraphs(paragraphs: list[str]) -> list[str]:
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
# MARK: STDLIB FALLBACK EXTRACTOR
# ====================================================================================================
class _FallbackExtractor(HTMLParser):
    """Pure-stdlib HTML → prose extractor used when BeautifulSoup is unavailable."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_body    = False
        self._buf:        list[str] = []
        self._paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "body":
            self._in_body = True
        if tag in _SKIP_TAGS or tag in _NAV_SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in _SKIP_TAGS or tag in _NAV_SKIP_TAGS:
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
        return "\n\n".join(_dedup_paragraphs(self._paragraphs))


# ====================================================================================================
# MARK: BEAUTIFULSOUP EXTRACTION
# ====================================================================================================
def _attrs_lower(tag) -> str:
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


def _prune_noise_bs4(container) -> None:
    """Remove known-noisy tags and heuristically identified layout containers in-place."""
    for tag_name in list(_SKIP_TAGS | _NAV_SKIP_TAGS):
        for tag in list(container.find_all(tag_name)):
            tag.decompose()
    for tag in list(container.find_all(True)):
        if not hasattr(tag, "attrs") or tag.attrs is None:
            continue
        if any(hint in _attrs_lower(tag) for hint in _NOISE_HINTS):
            tag.decompose()


def _extract_prose_bs4(html_text: str) -> tuple[str, str, object]:
    """Return (title, prose_text, content_container) using BeautifulSoup.

    The returned container is the pruned DOM node used for subsequent link extraction.
    Pruning is done in-place so link extraction only sees content-area links.
    """
    soup  = BeautifulSoup(html_text, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""

    container = None
    for selector in ["article", "main", "[role='main']"]:
        container = soup.select_one(selector)
        if container:
            break
    if container is None:
        container = soup.body or soup

    _prune_noise_bs4(container)

    paragraphs = []
    for p in container.find_all("p"):
        text = _SPACE_RE.sub(" ", p.get_text(" ", strip=True)).strip()
        if len(text.split()) >= 8:
            paragraphs.append(text)
    paragraphs = _dedup_paragraphs(paragraphs)
    prose = "\n\n".join(paragraphs)

    return title, prose, container


# ====================================================================================================
# MARK: LINK EXTRACTION
# ====================================================================================================
def _score_link(anchor_text: str, topic_tokens: set[str]) -> int:
    if not topic_tokens:
        return 0
    text_tokens = set(_WORD_RE.findall(anchor_text.lower()))
    return len(topic_tokens & text_tokens)


def _extract_links_bs4(container, base_url: str, topic: str, max_links: int) -> list[dict]:
    """Extract article-candidate links from a pruned BeautifulSoup container."""
    topic_tokens: set[str] = set(_WORD_RE.findall(topic.lower())) if topic.strip() else set()
    seen:        set[str]   = set()
    candidates:  list[dict] = []

    for a in container.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        url_key = parsed._replace(fragment="").geturl()
        if url_key in seen:
            continue
        seen.add(url_key)
        anchor = _SPACE_RE.sub(" ", a.get_text(" ", strip=True)).strip()
        if len(anchor.split()) < 2:
            continue
        score = _score_link(anchor, topic_tokens)
        candidates.append({"title": anchor, "url": url_key, "_score": score})

    if topic_tokens:
        candidates.sort(key=lambda x: x["_score"], reverse=True)
    return [{"title": c["title"], "url": c["url"]} for c in candidates[:max_links]]


# Stdlib fallback patterns for link extraction.
_LINK_RE      = re.compile(r'<a\s[^>]*href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _extract_links_stdlib(html_text: str, base_url: str, topic: str, max_links: int) -> list[dict]:
    """Extract article-candidate links using stdlib regex (BeautifulSoup not available)."""
    topic_tokens: set[str] = set(_WORD_RE.findall(topic.lower())) if topic.strip() else set()
    seen:        set[str]   = set()
    candidates:  list[dict] = []

    for m in _LINK_RE.finditer(html_text):
        href   = m.group(1).strip()
        anchor = _SPACE_RE.sub(" ", _TAG_STRIP_RE.sub("", _html.unescape(m.group(2)))).strip()
        if not href or href.startswith(("javascript:", "mailto:")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        url_key = parsed._replace(fragment="").geturl()
        if url_key in seen:
            continue
        seen.add(url_key)
        if len(anchor.split()) < 2:
            continue
        score = _score_link(anchor, topic_tokens)
        candidates.append({"title": anchor, "url": url_key, "_score": score})

    if topic_tokens:
        candidates.sort(key=lambda x: x["_score"], reverse=True)
    return [{"title": c["title"], "url": c["url"]} for c in candidates[:max_links]]


# ====================================================================================================
# MARK: PAGE CLASSIFICATION
# ====================================================================================================
def _classify_page(word_count: int, link_count: int) -> str:
    """Classify a page as 'article', 'index', or 'mixed' from prose word density.

    Thresholds (see module constants for tuning):
      article : word_count >= 300 and links-per-100-words <= 4.0
      index   : word_count < 150, or links-per-100-words >= 7.0
      mixed   : everything between those bounds
    """
    if word_count < _INDEX_MAX_WORDS:
        return "index"
    ratio = link_count / (word_count / 100.0)
    if word_count >= _ARTICLE_MIN_WORDS and ratio <= _ARTICLE_MAX_RATIO:
        return "article"
    if ratio >= _INDEX_MIN_RATIO:
        return "index"
    return "mixed"


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def assess_page(
    url: str,
    topic: str = "",
    max_links: int = 10,
) -> dict:
    """Fetch a URL and return a structured assessment of its page type and content.

    Returns a dict:
      url           -- final URL after redirects
      title         -- page <title> text
      page_type     -- "article", "index", or "mixed"
      word_count    -- deduped prose words extracted
      link_count    -- article-candidate links returned
      prose_preview -- first 100 words of extracted prose
      article_links -- list of {title, url} dicts filtered/ranked by topic

    On failure: returns {"error": "<description>"} - never raises.

    Planner guide for page_type:
      "article" -> call mine_url directly; the page has substantial content
      "index"   -> use article_links to find individual article URLs; mine those
      "mixed"   -> try mine_url; if word_count < 200, also follow article_links
    """
    if not url or not url.strip():
        return {"error": "url cannot be empty"}

    parsed_in = urllib.parse.urlparse(url.strip())
    if parsed_in.scheme not in ("http", "https"):
        return {"error": f"unsupported URL scheme '{parsed_in.scheme}'. Only http and https are supported."}

    max_links = max(1, min(int(max_links), MAX_LINKS_CAP))

    try:
        html_text, final_url = _fetch_html(url.strip())
    except Exception as exc:
        return {"error": f"failed to fetch {url!r}: {exc}"}

    try:
        if _BS4_AVAILABLE:
            title, prose, container = _extract_prose_bs4(html_text)
            article_links = _extract_links_bs4(container, final_url, topic, max_links)
        else:
            extractor = _FallbackExtractor()
            try:
                extractor.feed(html_text)
            except Exception:
                pass
            prose         = extractor.get_text()
            title         = ""
            article_links = _extract_links_stdlib(html_text, final_url, topic, max_links)
    except Exception as exc:
        return {"error": f"failed to extract content from {url!r}: {exc}"}

    word_count = len(prose.split())
    link_count = len(article_links)
    page_type  = _classify_page(word_count, link_count)

    preview_words = prose.split()[:PREVIEW_WORDS]
    prose_preview = " ".join(preview_words)
    if len(prose.split()) > PREVIEW_WORDS:
        prose_preview += " ..."

    return {
        "url":           final_url,
        "title":         title,
        "page_type":     page_type,
        "word_count":    word_count,
        "link_count":    link_count,
        "prose_preview": prose_preview,
        "article_links": article_links,
    }
