# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebResearch (Mine stage) skill for MiniAgentFramework.
#
# Gen3 web mining skill — fetches single URLs or runs DuckDuckGo searches, formats the
# retrieved content as structured Markdown, and writes files into the 01-Mine stage of the
# web research workspace managed by webresearch_utils.py.
#
# HTTP fetching and HTML extraction are provided by code/webpage_utils.py, which is
# loaded by the same importlib-based skill loader as the skill files themselves.
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
#   - webpage_utils.py     -- HTTP fetch, HTML extraction, text utilities (shared)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import html as _html
import re
import urllib.parse
from datetime import date as _date, datetime as _datetime
from pathlib import Path

from webpage_utils import fetch_html as _fetch_html
from webpage_utils import extract_content as _extract_content
from webpage_utils import truncate_to_words as _truncate_to_words
from prompt_tokens import resolve_tokens as _resolve_query_tokens
from webresearch_utils import STAGE_MINE
from webresearch_utils import create_item_dir
from webresearch_utils import next_item_number
from webresearch_utils import _make_slug as _webresearch_make_slug

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_SPACE_RE = re.compile(r"\s+")

# Domains to never fetch in a research context (social/media-hosting/platform sites
# that rarely contain mineable long-form articles and frequently pollute search results).
_BLOCKED_RESEARCH_DOMAINS = frozenset({
    "youtube.com", "youtu.be",
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "tiktok.com", "linkedin.com", "pinterest.com", "snapchat.com",
    "twitch.tv", "vimeo.com", "dailymotion.com",
    "reddit.com", "tumblr.com",
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

MAX_WORDS_CAP    = 4000
DEFAULT_TIMEOUT  = 15


# ====================================================================================================
# MARK: DOMAIN AND RELEVANCE FILTERS
# ====================================================================================================
def _is_blocked_domain(url: str) -> bool:
    """Return True if the URL belongs to a blocked social/platform domain.

    Blocked domains are never fetched during research crawls — they rarely contain
    long-form articles and frequently pollute DuckDuckGo results.
    """
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host in _BLOCKED_RESEARCH_DOMAINS or any(
            host.endswith("." + d) for d in _BLOCKED_RESEARCH_DOMAINS
        )
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------------
_RELEVANCE_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "about",
    "what", "when", "will", "have", "news", "latest",
})

def _is_topically_relevant(title: str, body: str, query: str, min_matches: int = 2) -> bool:
    """Check that extracted content shares significant vocabulary with the query.

    Tokenises the query into words of length >= 4 that are not stopwords, then counts
    how many appear (case-insensitive) in title+body.  Pages that share fewer than
    min_matches query terms are treated as off-topic and should be skipped.
    """
    tokens = [
        w.lower() for w in re.split(r"\W+", query)
        if len(w) >= 4 and w.lower() not in _RELEVANCE_STOPWORDS
    ]
    if not tokens:
        return True  # Cannot evaluate; allow through.
    text = (title + " " + body).lower()
    matches = sum(1 for tok in tokens if tok in text)
    return matches >= min(min_matches, len(tokens))


# ----------------------------------------------------------------------------------------------------
def _relevance_score(title: str, snippet: str, query: str) -> int:
    """Score a DDG result (title + snippet) against the query before any page fetch.

    Returns an integer match count — the number of significant query tokens
    (length >= 4, not in stopwords) that appear in title + snippet.
    Higher is more relevant.  Used to pre-sort DDG results so the most
    relevant URLs are fetched first.
    """
    tokens = [
        w.lower() for w in re.split(r"\W+", query)
        if len(w) >= 4 and w.lower() not in _RELEVANCE_STOPWORDS
    ]
    if not tokens:
        return 1  # Cannot evaluate; treat all as equally relevant.
    text = (title + " " + snippet).lower()
    return sum(1 for tok in tokens if tok in text)


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
def _is_ddg_ad(url: str) -> bool:
    """Return True if a decoded URL is still a DuckDuckGo tracking/ad URL.

    DuckDuckGo ads use a /y.js?ad_domain=... href instead of the /l/?uddg= organic
    redirect.  The decoder does not recognise this format so the raw tracking URL
    passes through unchanged — these should be excluded from results.
    """
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return host == "duckduckgo.com" or host.endswith(".duckduckgo.com")
    except Exception:
        return False


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
            if not title or not url or url.startswith("/") or _is_ddg_ad(url):
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
    now = _datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {title or url}",
        "",
        f"**Source URL:** {url}",
        f"**Mined:** {now}",
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
    now = _datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Search: {query}",
        "",
        f"**Query:** {query}",
        f"**Searched:** {now}",
        f"**Domain:** {domain}",
        f"**Results returned:** {len(results)}",
        "",
        "---",
        "",
        "## Results",
        "",
    ]
    for r in results:
        rank         = r.get("rank", "?")
        title        = r.get("title", "")
        url          = r.get("url", "")
        snippet      = r.get("snippet", "")
        content      = r.get("content", "")
        content_type = r.get("content_type", "")
        content_wc   = r.get("content_words", 0)
        lines.append(f"### [{rank}] {title}")
        if url:
            lines.append(f"- **URL:** {url}")
        if snippet:
            lines.append(f"- **Snippet:** {snippet}")
        if content:
            lines.append(f"\n**Extracted content ({content_wc} words):**\n")
            lines.append(content)
        elif content_type == "index":
            index_links = r.get("index_links", [])
            if index_links:
                lines.append("- *Index/listing page — article links discovered:*\n")
                for lnk in index_links:
                    lines.append(f"  - [{lnk.get('title', lnk.get('url', ''))}]({lnk.get('url', '')})")
            else:
                lines.append("- *Page type: index/listing — no article content extracted*")
        lines.append("")
    return "\n".join(lines)


# ====================================================================================================
# MARK: INTERNAL: CONTENT PREVIEW FETCHER
# ====================================================================================================
_INDEX_LINK_RE  = re.compile(r'<a\s[^>]*href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)



def _extract_index_links_stdlib(html_text: str, base_url: str, max_links: int = 8) -> list[dict]:
    """Best-effort article link extraction from index pages when bs4 is not available."""
    seen:        set[str]   = set()
    results:     list[dict] = []
    base_host = urllib.parse.urlparse(base_url).netloc.lower()

    for m in _INDEX_LINK_RE.finditer(html_text):
        href   = m.group(1).strip()
        anchor = _SPACE_RE.sub(" ", _TAG_RE.sub("", _html.unescape(m.group(2)))).strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        # Only links that go deeper into the same domain (path must be longer than "/")
        if parsed.netloc.lower() != base_host or len(parsed.path) <= 1:
            continue
        url_key = parsed._replace(fragment="").geturl()
        if url_key in seen:
            continue
        seen.add(url_key)
        if len(anchor.split()) < 3:
            continue
        results.append({"title": anchor, "url": url_key})
        if len(results) >= max_links:
            break
    return results


def _extract_index_links_bs4(html_text: str, base_url: str, max_links: int = 8) -> list[dict]:
    """Article link extraction from index pages using BeautifulSoup."""
    soup = BeautifulSoup(html_text, "html.parser")
    # Remove noise containers
    for tag_name in ("nav", "header", "footer", "aside", "script", "style"):
        for tag in list(soup.find_all(tag_name)):
            tag.decompose()

    base_host = urllib.parse.urlparse(base_url).netloc.lower()
    seen:        set[str]   = set()
    results:     list[dict] = []

    # Prefer links inside <article>, <main>, <section> containers
    container = None
    for selector in ["article", "main", "[role='main']", "section"]:
        container = soup.select_one(selector)
        if container:
            break
    search_root = container or soup

    for a in search_root.find_all("a", href=True):
        href   = (a.get("href") or "").strip()
        anchor = _SPACE_RE.sub(" ", a.get_text(" ", strip=True)).strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != base_host or len(parsed.path) <= 1:
            continue
        url_key = parsed._replace(fragment="").geturl()
        if url_key in seen:
            continue
        seen.add(url_key)
        if len(anchor.split()) < 3:
            continue
        results.append({"title": anchor, "url": url_key})
        if len(results) >= max_links:
            break
    return results


def _fetch_content_preview(url: str, max_words: int = 200) -> tuple[int, str, list[dict]]:
    """Fetch url and return (word_count, prose_preview, article_links).

    Returns (0, '', []) on any error.

    Classification heuristic (mirrors PageAssess thresholds):
      - word_count < 250                              → index
      - len(article_links) >= 8 AND word_count < 500  → index (link-dense section page)
    Otherwise the page is treated as an article; prose_preview is returned and
    article_links will be empty.

    Index pages return up to 15 same-domain article-candidate links suitable for
    further mining; prose_preview will be empty.
    """
    if not url or not url.startswith(("http://", "https://")):
        return 0, "", []
    try:
        html_text, final_url = _fetch_html(url, timeout=10.0)
        _, body = _extract_content(html_text)
        words = body.split()
        word_count = len(words)

        # Always extract article links — needed for index pages AND for density check.
        if _BS4_AVAILABLE:
            article_links = _extract_index_links_bs4(html_text, final_url, max_links=15)
        else:
            article_links = _extract_index_links_stdlib(html_text, final_url, max_links=15)

        # Classify: thin pages or link-dense section pages are treated as indexes.
        is_index = word_count < 250 or (len(article_links) >= 8 and word_count < 500)

        if not is_index:
            preview = " ".join(words[:max_words])
            if word_count > max_words:
                preview += "\n\n...[truncated]"
            return word_count, preview, []

        return word_count, "", article_links
    except Exception:
        return 0, "", []


# ====================================================================================================
# MARK: INTERNAL: ARTICLE SAVER
# ====================================================================================================
def _save_article_in(
    parent_dir: "Path",
    title: str,
    url: str,
    domain: str,
    body: str,
    content_words: int,
) -> "str | None":
    """Save an article as a numbered sub-folder inside an existing parent directory.

    Used by mine_search_deep to group all articles under one query-level folder.
    Does not re-fetch — caller provides already-extracted title and body.
    Returns the saved absolute path string on success, None on any failure.
    """
    try:
        truncated   = _truncate_to_words(body, content_words)
        slug        = _webresearch_make_slug(title or url.split("/")[-1] or "article")
        seq         = next_item_number(parent_dir)
        item_dir    = parent_dir / f"{seq:03d}-{slug}"
        item_dir.mkdir(exist_ok=True)
        output_path = item_dir / "source.md"
        output_path.write_text(_format_source_md(title, url, domain, truncated), encoding="utf-8")
        return str(output_path)
    except Exception:
        return None


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def mine_url(
    url: str,
    domain: str,
    slug: str | None = None,
    max_words: int = 1200,
) -> str:
    """Fetch a URL, extract its readable content, and save it as source.md in the Mine stage.

    Saves to:  webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-<slug>/source.md

    Returns a confirmation string "Saved: <path>" on success, or an "Error: ..." string
    on failure.  Never raises.
    """
    if not url or not url.strip():
        return "Error: url cannot be empty."

    url    = _resolve_query_tokens(url.strip())
    parsed = urllib.parse.urlparse(url)
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
    fetch_content: bool = True,
    content_words: int = 600,
) -> str:
    """Run a DuckDuckGo search and save the result list as results.md in the Mine stage.

    When fetch_content=True (the default) each result URL is fetched and up to content_words
    words of extracted prose are embedded inline in the saved file.  Results that yield fewer
    than 250 extracted words, or that are link-dense section/listing pages, are treated as
    index pages — their article-candidate links are saved instead of prose.

    Saves to:  webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-search-<query>/results.md

    Returns a confirmation string "Saved: <path>" on success, or an "Error: ..." string
    on failure.  Never raises.
    """
    if not query or not query.strip():
        return "Error: query cannot be empty."
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    query       = _resolve_query_tokens(query.strip())
    max_results = max(1, min(int(max_results), 10))

    try:
        results = _ddg_search(query, max_results=max_results, timeout=DEFAULT_TIMEOUT)
    except Exception as exc:
        return f"Error: search failed for {query!r}: {exc}"

    if not results:
        results = [{"rank": 0, "title": "No results", "url": "", "snippet": f"DuckDuckGo returned no results for: {query}"}]

    if fetch_content:
        content_words = max(50, min(int(content_words), MAX_WORDS_CAP))
        for r in results:
            if not r.get("url"):
                continue
            word_count, preview, index_links = _fetch_content_preview(r["url"], max_words=content_words)
            if word_count >= 120:
                r["content"]       = preview
                r["content_words"] = word_count
                r["content_type"]  = "article"
            else:
                r["content_type"]  = "index"
                r["index_links"]   = index_links

    item_dir    = create_item_dir(STAGE_MINE, domain, f"search-{query}")
    output_path = item_dir / "results.md"

    try:
        output_path.write_text(_format_results_md(query.strip(), domain, results), encoding="utf-8")
    except Exception as exc:
        return f"Error: failed to write {output_path}: {exc}"

    return f"Saved: {output_path}"


# ----------------------------------------------------------------------------------------------------
def mine_search_deep(
    query: str,
    domain: str,
    max_results: int = 10,
    max_articles_per_result: int = 2,
    min_words: int = 250,
    content_words: int = 1500,
    target_articles: int = 5,
) -> str:
    """Search DDG and deeply mine each result into individual source.md files.

    Unlike mine_search (which saves a single results.md with embedded snippets), this
    function saves each discovered article as its own source.md file — the same rich
    format produced by mine_url, but driven entirely by a search query.

    All articles from a single call are grouped under one top-level folder:
      webresearch/01-Mine/<domain>/yyyy/mm/dd/NNN-deep-<query>/
    with each article in its own numbered sub-folder:
      NNN-deep-<query>/001-<title>/source.md
      NNN-deep-<query>/002-<title>/source.md

    For each DDG result URL:
      - Article page  (>= min_words prose, low link density):
          mined directly → saved as source.md
      - Index/section page (< min_words prose, or link-dense):
          up to max_articles_per_result child links are followed, each classified;
          article-quality children are mined and saved as source.md

    Processing stops early once target_articles articles have been saved.

    DDG results are pre-scored by title+snippet relevance and processed in relevance
    order, so setting max_results higher than target_articles (e.g. double) is cheap —
    no extra page fetches until candidates are actually needed.

    Returns a summary string listing every saved path.
    On failure returns a descriptive error string — never raises.
    """
    if not query or not query.strip():
        return "Error: query cannot be empty."
    if not domain or not domain.strip():
        return "Error: domain cannot be empty."

    query                   = _resolve_query_tokens(query.strip())
    max_results             = max(1, min(int(max_results),              20))
    max_articles_per_result = max(1, min(int(max_articles_per_result),   5))
    min_words               = max(100, min(int(min_words),             800))
    content_words           = max(200, min(int(content_words), MAX_WORDS_CAP))
    target_articles         = max(1, min(int(target_articles),          20))

    try:
        results = _ddg_search(query, max_results=max_results, timeout=DEFAULT_TIMEOUT)
    except Exception as exc:
        return f"Error: search failed for {query!r}: {exc}"

    if not results:
        return f"No results returned by DuckDuckGo for query: {query!r}"

    # Pre-sort DDG results by snippet+title relevance score (descending) so the most
    # relevant URLs are fetched first.  Blocked-domain results are pushed to the back.
    # This is free — no extra HTTP requests needed, only the already-returned snippets.
    results.sort(
        key=lambda r: (
            0 if _is_blocked_domain(r.get("url", "")) else 1,
            _relevance_score(r.get("title", ""), r.get("snippet", ""), query),
        ),
        reverse=True,
    )

    # Create one top-level query folder; all articles go under it as sub-folders.
    # Strip any YYYY-MM-DD date from the slug — the date is already encoded in the path.
    query_slug = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", query).strip()
    query_dir = create_item_dir(STAGE_MINE, domain, f"deep-{query_slug}")

    mined_paths:  list[str] = []
    fetch_errors: int       = 0
    skipped_domain: int     = 0
    skipped_relevance: int  = 0

    for r in results:
        if len(mined_paths) >= target_articles:
            break

        url = r.get("url", "")
        if not url:
            continue

        # Skip social/platform domains that rarely contain mineable articles.
        if _is_blocked_domain(url):
            skipped_domain += 1
            continue

        # Fetch and extract once per result URL — no double-fetching.
        try:
            html_text, final_url = _fetch_html(url, timeout=12.0)
        except Exception:
            fetch_errors += 1
            continue

        try:
            title, body = _extract_content(html_text)
        except Exception:
            fetch_errors += 1
            continue

        word_count = len(body.split())

        # Classify using the same dual heuristic as _fetch_content_preview.
        if _BS4_AVAILABLE:
            candidate_links = _extract_index_links_bs4(html_text, final_url, max_links=15)
        else:
            candidate_links = _extract_index_links_stdlib(html_text, final_url, max_links=15)

        is_index = word_count < min_words or (len(candidate_links) >= 8 and word_count < 500)

        if not is_index:
            if not _is_topically_relevant(title, body, query):
                skipped_relevance += 1
                continue
            path = _save_article_in(query_dir, title, final_url, domain, body, content_words)
            if path:
                mined_paths.append(path)
        else:
            # Follow child links from the index page.
            articles_found = 0
            for link in candidate_links:
                if articles_found >= max_articles_per_result:
                    break
                if len(mined_paths) >= target_articles:
                    break
                child_url = link.get("url", "")
                if not child_url:
                    continue
                if _is_blocked_domain(child_url):
                    skipped_domain += 1
                    continue
                try:
                    child_html, child_final_url = _fetch_html(child_url, timeout=12.0)
                    child_title, child_body     = _extract_content(child_html)
                    child_word_count            = len(child_body.split())

                    if _BS4_AVAILABLE:
                        child_links = _extract_index_links_bs4(child_html, child_final_url, max_links=15)
                    else:
                        child_links = _extract_index_links_stdlib(child_html, child_final_url, max_links=15)

                    child_is_index = (
                        child_word_count < min_words
                        or (len(child_links) >= 8 and child_word_count < 500)
                    )

                    if not child_is_index:
                        if not _is_topically_relevant(child_title, child_body, query):
                            skipped_relevance += 1
                            continue
                        path = _save_article_in(query_dir, child_title, child_final_url, domain, child_body, content_words)
                        if path:
                            mined_paths.append(path)
                            articles_found += 1
                except Exception:
                    continue

    if not mined_paths:
        detail = f" ({fetch_errors} fetch error(s))" if fetch_errors else ""
        return f"No articles found for query: {query!r} — searched {len(results)} result(s){detail}"

    lines = [f"Mined {len(mined_paths)} article(s) for: {query!r}"]
    lines.append(f"  Folder: {query_dir}")
    for p in mined_paths:
        lines.append(f"  Saved: {p}")
    if fetch_errors:
        lines.append(f"  ({fetch_errors} URL(s) could not be fetched)")
    if skipped_domain:
        lines.append(f"  ({skipped_domain} URL(s) skipped — blocked platform domain)")
    if skipped_relevance:
        lines.append(f"  ({skipped_relevance} URL(s) skipped — off-topic content)")
    return "\n".join(lines)
