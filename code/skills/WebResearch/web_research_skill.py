# ==================================================================================================== #
# MARK: OVERVIEW
# ==================================================================================================== #
# ResearchTraverse skill for MiniAgentFramework.
#
# Generic multi-page web research primitive:
# - searches DuckDuckGo
# - fetches candidate pages
# - extracts readable text
# - scores relevance against the user query
# - optionally follows promising links discovered inside fetched pages
# - returns a compact summary plus a larger evidence bundle
#
# Built to reduce tool-call thrash and keep bulky evidence out of the main thread.
# ==================================================================================================== #

import html as _html
import re
import urllib.parse
from collections import deque

from webpage_utils import fetch_html as _fetch_html
from webpage_utils import extract_content as _extract_content
from webpage_utils import truncate_to_words as _truncate_to_words

from skills.WebSearch.web_search_skill import search_web


# ==================================================================================================== #
# MARK: CONSTANTS
# ==================================================================================================== #

_MAX_SEARCH_RESULTS_CAP          = 10
_MAX_PAGES_CAP                   = 12
_MAX_HOPS_CAP                    = 2
_TIMEOUT_SECONDS_CAP             = 30
_MAX_WORDS_PER_PAGE_CAP          = 1200
_MAX_EVIDENCE_QUOTES_CAP         = 8

_URL_RE                          = re.compile(r'https?://[^\s<>"\')]+', re.IGNORECASE)
_HREF_RE                         = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_SPACE_RE                        = re.compile(r"\s+")
_NON_WORD_RE                     = re.compile(r"[^a-z0-9\s]+", re.IGNORECASE)

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "by", "with", "from", "at",
    "is", "are", "was", "were", "be", "been", "being", "what", "which", "who", "when", "where",
    "how", "why", "this", "that", "these", "those", "about", "into", "than", "then", "it",
}


# ==================================================================================================== #
# MARK: TEXT HELPERS
# ==================================================================================================== #

def _clean_text(text: str) -> str:
    text = _html.unescape(text or "")
    text = _NON_WORD_RE.sub(" ", text.lower())
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _query_terms(query: str) -> list[str]:
    tokens = [t for t in _clean_text(query).split() if len(t) >= 3 and t not in _STOPWORDS]
    seen = set()
    result = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return parts


def _sentenceish_chunks(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n\s*\n", text or "")
    return [p.strip() for p in parts if p and p.strip()]


# ==================================================================================================== #
# MARK: URL HELPERS
# ==================================================================================================== #

def _normalise_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path   = parsed.path or "/"
        query  = parsed.query
        if not scheme or not netloc:
            return ""
        rebuilt = urllib.parse.urlunparse((scheme, netloc, path, "", query, ""))
        return rebuilt
    except Exception:
        return ""


def _same_domain(url_a: str, url_b: str) -> bool:
    try:
        a = urllib.parse.urlparse(url_a).netloc.lower()
        b = urllib.parse.urlparse(url_b).netloc.lower()
        return bool(a) and bool(b) and a == b
    except Exception:
        return False


def _extract_links(html_text: str, base_url: str) -> list[str]:
    found = []

    for match in _HREF_RE.finditer(html_text or ""):
        href = (match.group(1) or "").strip()
        if not href:
            continue
        absolute = urllib.parse.urljoin(base_url, href)
        normalised = _normalise_url(absolute)
        if normalised.startswith("http://") or normalised.startswith("https://"):
            found.append(normalised)

    deduped = []
    seen = set()
    for url in found:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


# ==================================================================================================== #
# MARK: SCORING
# ==================================================================================================== #

def _score_text_against_query(query: str, title: str, body_text: str, url: str) -> tuple[float, list[str]]:
    terms = _query_terms(query)
    if not terms:
        return 0.0, []

    title_l = _clean_text(title)
    body_l  = _clean_text(body_text)
    url_l   = _clean_text(url)

    score = 0.0
    hits  = []

    for term in terms:
        term_score = 0.0

        if term in title_l:
            term_score += 4.0
            hits.append(term)

        if term in url_l:
            term_score += 2.0

        body_count = body_l.count(term)
        if body_count > 0:
            term_score += min(3.0, 0.5 * body_count)

        score += term_score

    if len(set(hits)) >= 2:
        score += 3.0

    if title_l and any(x in title_l for x in ("results", "report", "official", "history", "winners", "standings", "docs")):
        score += 1.0

    return score, sorted(set(hits))


def _best_evidence_snippets(query: str, body_text: str, max_items: int) -> list[str]:
    terms = _query_terms(query)
    chunks = _sentenceish_chunks(body_text)

    ranked = []
    for chunk in chunks:
        chunk_l = _clean_text(chunk)
        if len(chunk.split()) < 8:
            continue

        score = 0.0
        matched = 0
        for term in terms:
            if term in chunk_l:
                score += 1.0
                matched += 1

        if matched >= 2:
            score += 2.0

        if score > 0:
            ranked.append((score, chunk.strip()))

    ranked.sort(key=lambda x: x[0], reverse=True)

    out = []
    seen = set()
    for _, chunk in ranked:
        key = chunk[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk)
        if len(out) >= max_items:
            break
    return out


# ==================================================================================================== #
# MARK: FETCH + EXTRACT
# ==================================================================================================== #

def _fetch_extract_score(url: str, query: str, timeout_seconds: int, max_words_per_page: int, max_evidence_quotes: int = 3) -> dict:
    try:
        html_text, final_url = _fetch_html(url, timeout=float(timeout_seconds))
        page_title, body_text = _extract_content(html_text)
        body_text = _truncate_to_words(body_text, max_words_per_page)

        score, matched_terms = _score_text_against_query(
            query     = query,
            title     = page_title,
            body_text = body_text,
            url       = final_url,
        )

        evidence = _best_evidence_snippets(query, body_text, max_items=max_evidence_quotes)

        return {
            "ok"            : True,
            "url"           : final_url,
            "title"         : page_title or final_url,
            "score"         : round(score, 2),
            "matched_terms" : matched_terms,
            "evidence"      : evidence,
            "body_text"     : body_text,
            "discovered_urls": _extract_links(html_text, final_url),
            "error"         : "",
        }
    except Exception as exc:
        return {
            "ok"            : False,
            "url"           : url,
            "title"         : url,
            "score"         : 0.0,
            "matched_terms" : [],
            "evidence"      : [],
            "body_text"     : "",
            "discovered_urls": [],
            "error"         : str(exc),
        }


# ==================================================================================================== #
# MARK: PUBLIC SKILL API
# ==================================================================================================== #

def research_traverse(
    query: str,
    max_search_results: int           = 5,
    max_pages: int                    = 6,
    max_hops: int                     = 1,
    same_domain_only_for_hops: bool   = True,
    timeout_seconds: int              = 15,
    max_words_per_page: int           = 450,
    max_evidence_quotes: int          = 3,
) -> dict:
    """
    Search the web, examine multiple pages, optionally follow promising links, and
    return a compact evidence-oriented research bundle.

    This is a generic retrieval-depth skill. It is intentionally broader than a
    single-page extract and narrower than a full autonomous agent loop.
    """
    query = (query or "").strip()
    if not query:
        return {"summary": "Error: query cannot be empty", "answer_confidence": "low"}

    max_search_results = max(1, min(int(max_search_results), _MAX_SEARCH_RESULTS_CAP))
    max_pages          = max(1, min(int(max_pages), _MAX_PAGES_CAP))
    max_hops           = max(0, min(int(max_hops), _MAX_HOPS_CAP))
    timeout_seconds    = max(5, min(int(timeout_seconds), _TIMEOUT_SECONDS_CAP))
    max_words_per_page = max(80, min(int(max_words_per_page), _MAX_WORDS_PER_PAGE_CAP))
    max_evidence_quotes = max(1, min(int(max_evidence_quotes), _MAX_EVIDENCE_QUOTES_CAP))

    seed_results = search_web(
        query           = query,
        max_results     = max_search_results,
        timeout_seconds = timeout_seconds,
    )

    if not isinstance(seed_results, list) or not seed_results:
        return {
            "query": query,
            "summary": "Search returned no usable results.",
            "answer_confidence": "low",
            "visited_count": 0,
            "seed_results": seed_results,
            "best_pages": [],
            "exploration_log": [],
            "unvisited_candidates": [],
            "full_report": f"Research failed early for query: {query}",
        }

    frontier = deque()
    visited  = set()
    queued   = set()
    log      = []

    for result in seed_results:
        url = _normalise_url(str(result.get("url", "")))
        if not url:
            continue
        frontier.append((url, 0, "seed_search_result"))
        queued.add(url)

    useful_pages = []
    rejected_pages = []

    while frontier and len(visited) < max_pages:
        current_url, depth, reason = frontier.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)

        page = _fetch_extract_score(
            url                = current_url,
            query              = query,
            timeout_seconds    = timeout_seconds,
            max_words_per_page = max_words_per_page,
            max_evidence_quotes = max_evidence_quotes,
        )

        page["depth"] = depth
        page["reason"] = reason

        if page["ok"] and page["score"] > 0:
            useful_pages.append(page)
            status = "useful"
        else:
            rejected_pages.append(page)
            status = "rejected"

        log.append({
            "url"          : page["url"],
            "title"        : page["title"],
            "depth"        : depth,
            "reason"       : reason,
            "status"       : status,
            "score"        : page["score"],
            "matched_terms": page["matched_terms"],
            "error"        : page["error"],
        })

        if depth >= max_hops:
            continue

        if not page["ok"]:
            continue

        discovered_urls = page.get("discovered_urls", [])
        for child_url in discovered_urls:
            if child_url in visited or child_url in queued:
                continue

            if same_domain_only_for_hops and not _same_domain(page["url"], child_url):
                continue

            if len(queued) + len(visited) >= max_pages * 4:
                continue

            frontier.append((child_url, depth + 1, f"linked_from:{page['url']}"))
            queued.add(child_url)

    useful_pages.sort(key=lambda p: p.get("score", 0.0), reverse=True)

    best_pages = []
    for page in useful_pages[: min(5, len(useful_pages))]:
        best_pages.append({
            "title"         : page["title"],
            "url"           : page["url"],
            "score"         : page["score"],
            "depth"         : page["depth"],
            "matched_terms" : page["matched_terms"],
            "evidence"      : page["evidence"],
        })

    if useful_pages:
        top = useful_pages[:3]
        summary_lines = ["Top evidence found:"]
        for page in top:
            summary_lines.append(f"- {page['title']} [{page['score']}]")
            for ev in page["evidence"][:2]:
                summary_lines.append(f"  - {ev}")
        summary = "\n".join(summary_lines)

        top_score = useful_pages[0]["score"]
        confidence = "high" if top_score >= 10 else ("medium" if top_score >= 5 else "low")
    else:
        summary = "No strong evidence found across the visited pages."
        confidence = "low"

    full_report_lines = [
        f"Research query: {query}",
        f"Visited pages: {len(visited)}",
        f"Useful pages: {len(useful_pages)}",
        "",
        "==== BEST PAGES ====",
    ]

    for page in useful_pages[: min(8, len(useful_pages))]:
        full_report_lines.append(f"TITLE: {page['title']}")
        full_report_lines.append(f"URL:   {page['url']}")
        full_report_lines.append(f"SCORE: {page['score']}")
        if page["matched_terms"]:
            full_report_lines.append(f"MATCHED TERMS: {', '.join(page['matched_terms'])}")
        if page["evidence"]:
            full_report_lines.append("EVIDENCE:")
            for ev in page["evidence"]:
                full_report_lines.append(f"- {ev}")
        if page["body_text"]:
            full_report_lines.append("")
            full_report_lines.append("EXTRACT:")
            full_report_lines.append(page["body_text"])
        full_report_lines.append("")
        full_report_lines.append("----")
        full_report_lines.append("")

    unvisited_candidates = []
    while frontier and len(unvisited_candidates) < 20:
        url, depth, reason = frontier.popleft()
        unvisited_candidates.append({
            "url"   : url,
            "depth" : depth,
            "reason": reason,
        })

    return {
        "query"              : query,
        "summary"            : summary,
        "answer_confidence"  : confidence,
        "visited_count"      : len(visited),
        "seed_results"       : seed_results,
        "best_pages"         : best_pages,
        "exploration_log"    : log,
        "unvisited_candidates": unvisited_candidates,
        "full_report"        : "\n".join(full_report_lines).strip(),
    }