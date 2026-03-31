# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Kiwix skill for the MiniAgentFramework.
#
# Provides full-text search and article retrieval against a local Kiwix server (kiwix-serve).
# Kiwix hosts offline snapshots of Wikipedia, Project Gutenberg, and other reference libraries.
# Because all requests go to the LAN server there is no rate-limiting, no bot detection, and
# no internet dependency once the ZIM files are downloaded.
#
# Two public functions are exposed:
#   kiwix_search(query, max_results)     -- full-text search, returns ranked result list
#   kiwix_get_article(article_path, max_words) -- fetches and extracts text from an article
#
# Configuration:
#   Set "kiwix_url" in controldata/default.json, e.g. "http://192.168.1.33:8080".
#   If the key is absent or the server is unreachable all functions return a human-readable
#   error string - they never raise.
#
# Related modules:
#   - webpage_utils.py           -- extract_content() used for article text extraction
#   - workspace_utils.py         -- get_controldata_dir() for config loading
#   - skills_catalog_builder.py  -- reads skill.md to build the catalog
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import json
import re
import urllib.parse
import urllib.request

from webpage_utils import extract_content
from webpage_utils import HTTP_HEADERS
from workspace_utils import get_controldata_dir


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DEFAULTS_PATH = get_controldata_dir() / "default.json"

MAX_RESULTS_CAP = 20
DEFAULT_MAX_RESULTS = 5
DEFAULT_MAX_WORDS = 600
MAX_WORDS_CAP = 3000
DEFAULT_TIMEOUT = 15

# Kiwix search result HTML patterns.
# Result links:  <a href="/content/<book>/<Article_Title>">Title text</a>
# Snippets:      <cite>...text with <b>highlights</b>...</cite>
_RESULT_RE  = re.compile(
    r'<a\s+href="(/content/[^"]+)">\s*(.*?)\s*</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r"<cite>(.*?)</cite>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


# ====================================================================================================
# MARK: INTERNAL HELPERS
# ====================================================================================================
def _load_kiwix_url() -> str | None:
    try:
        raw = _DEFAULTS_PATH.read_text(encoding="utf-8")
        cfg = json.loads(raw)
        url = str(cfg.get("kiwix_url", "")).strip().rstrip("/")
        return url if url else None
    except Exception:
        return None


# ----------------------------------------------------------------------------------------------------
def _strip_tags(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = _html.unescape(cleaned)
    return _SPACE_RE.sub(" ", cleaned).strip()


# ----------------------------------------------------------------------------------------------------
def _kiwix_fetch(url: str, timeout: int) -> str:
    # Kiwix serves from a LAN address - use a stripped-down header set without the
    # browser UA because Kiwix does not require impersonation.
    headers = {
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Encoding": "identity",  # avoid gzip - we handle decoding ourselves
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def kiwix_search(
    query: str = "",
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> list[dict]:
    """Search the local Kiwix server and return a list of matching article references.

    Searches across all installed ZIM books (Wikipedia, Gutenberg, etc.).
    Each result contains: rank, title, article_path, snippet, book.

    article_path values can be passed directly to kiwix_get_article() to retrieve full text.

    Returns a single error-entry dict on failure - never raises.
    """
    kiwix_url = _load_kiwix_url()
    if not kiwix_url:
        return [{"rank": 0, "title": "Error", "article_path": "", "snippet": "kiwix_url not set in default.json", "book": ""}]

    query = str(query or "").strip()
    if not query:
        return [{"rank": 0, "title": "Error", "article_path": "", "snippet": "query cannot be empty", "book": ""}]

    max_results = max(1, min(int(max_results), MAX_RESULTS_CAP))
    timeout     = max(5, min(int(timeout), 60))

    encoded    = urllib.parse.quote_plus(query)
    search_url = f"{kiwix_url}/search?pattern={encoded}"

    try:
        html_text = _kiwix_fetch(search_url, timeout)
    except Exception as exc:
        return [{"rank": 0, "title": "Search failed", "article_path": "", "snippet": str(exc), "book": ""}]

    anchors  = list(_RESULT_RE.finditer(html_text))
    snippets = list(_SNIPPET_RE.finditer(html_text))

    results = []
    for index, anchor in enumerate(anchors):
        if len(results) >= max_results:
            break
        path  = anchor.group(1).strip()
        title = _strip_tags(anchor.group(2))
        if not path or not title:
            continue
        # Derive book name from path: /content/<book>/<article>
        parts = path.strip("/").split("/")
        book  = parts[1] if len(parts) >= 3 else ""

        snippet = _strip_tags(snippets[index].group(1)) if index < len(snippets) else ""
        # Kiwix snippets include trailing "......" - normalise to a single ellipsis.
        snippet = re.sub(r"\.{3,}", "...", snippet)

        results.append({
            "rank":         len(results) + 1,
            "title":        title,
            "article_path": path,
            "snippet":      snippet,
            "book":         book,
        })

    if not results:
        return [{"rank": 0, "title": "No results", "article_path": "", "snippet": f"Kiwix returned no results for: {query}", "book": ""}]

    return results


# ----------------------------------------------------------------------------------------------------
def kiwix_get_article(
    article_path: str = "",
    max_words: int = DEFAULT_MAX_WORDS,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> str:
    """Fetch and extract the text of a Kiwix article.

    article_path is the path returned by kiwix_search, e.g.:
        /content/wikipedia_en_all_maxi_2025-08/Python_(programming_language)

    Returns plain text (structured Markdown headings preserved) truncated to max_words.
    Returns an error string on failure - never raises.
    """
    kiwix_url = _load_kiwix_url()
    if not kiwix_url:
        return "Error: kiwix_url not set in default.json"

    article_path = str(article_path or "").strip()
    if not article_path:
        return "Error: article_path cannot be empty"

    max_words = max(50, min(int(max_words), MAX_WORDS_CAP))
    timeout   = max(5, min(int(timeout), 60))

    url = kiwix_url + article_path if article_path.startswith("/") else f"{kiwix_url}/{article_path}"

    try:
        html_text = _kiwix_fetch(url, timeout)
    except Exception as exc:
        return f"Failed to fetch article: {exc}"

    try:
        title, body = extract_content(html_text)
    except Exception as exc:
        return f"Failed to extract article text: {exc}"

    if not body.strip():
        return f"No text could be extracted from: {article_path}"

    words = body.split()
    if len(words) > max_words:
        body = " ".join(words[:max_words]) + " [...]"

    header = f"# {title}\n\n" if title else ""
    return f"{header}{body}"
