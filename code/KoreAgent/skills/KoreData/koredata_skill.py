# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# KoreData skill for the MiniAgentFramework.
#
# Provides unified search and full-content retrieval across three local KoreData services via the
# KoreDataGateway. All requests go through the gateway - the agent never calls child services
# directly.
#
# Three child services are accessible:
#   KoreFeeds     - repackaged RSS feed archive            (proxied at /feeds/*)
#   KoreReference - local encyclopedia (Wikipedia clone)   (proxied at /reference/*)
#   KoreLibrary   - local book repository                  (proxied at /library/*)
#   KoreRAG       - FTS5-indexed internal user documents   (proxied at /rag/*)
#
# Six public functions:
#   koredata_search(query, domains, since, until, limit) -- unified search across services
#   koredata_get_article(title)                          -- full KoreReference article by title
#   koredata_get_entry(domain, entry_id)                 -- full KoreFeed entry by domain + ID
#   koredata_get_book(book_id)                           -- full KoreLibrary book by ID
#   koredata_get_chunk(chunk_id)                         -- full KoreRAG chunk by ID
#   koredata_status()                                    -- gateway and child service health check
#
# Configuration:
#   Set "koredataurl" in default.json (repo root), e.g. "http://localhost:8200".
#   If absent, all functions return a descriptive error string - they never raise.
#
# Related modules:
#   - workspace_utils.py         -- get_workspace_root() for config loading
#   - skills_catalog_builder.py  -- reads skill.md to build the catalog
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from KoreAgent.utils.workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DEFAULTS_PATH   = get_workspace_root() / "default.json"
_CONFIG_KEY      = "koredataurl"
_DEFAULT_TIMEOUT = 10

DEFAULT_LIMIT    = 20
MAX_LIMIT        = 100


# ====================================================================================================
# MARK: CONFIG
# ====================================================================================================
# Loaded once on first call and then cached for the process lifetime.

_UNSET           = object()
_config_lock     = threading.Lock()
_cached_base_url: object = _UNSET


# ----------------------------------------------------------------------------------------------------
def _get_base_url() -> str | None:
    global _cached_base_url
    with _config_lock:
        if _cached_base_url is not _UNSET:
            return _cached_base_url  # type: ignore[return-value]
        try:
            raw  = _DEFAULTS_PATH.read_text(encoding="utf-8")
            cfg  = json.loads(raw)
            url  = cfg.get(_CONFIG_KEY, "").strip().rstrip("/")
            _cached_base_url = url if url else None
        except Exception:
            _cached_base_url = None
        return _cached_base_url  # type: ignore[return-value]


# ====================================================================================================
# MARK: HTTP HELPERS
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def _parse_error_detail(exc: urllib.error.HTTPError) -> str:
    # FastAPI returns {"detail": "..."} on errors - surface that string for the agent.
    try:
        body = exc.read().decode("utf-8")
        data = json.loads(body)
        return str(data.get("detail", exc.code))
    except Exception:
        return str(exc.code)


# ----------------------------------------------------------------------------------------------------
def _get_json(url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict | list | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            if not raw:
                return None
            return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"KoreDataGateway returned non-JSON response: {exc}") from exc
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from KoreDataGateway: {_parse_error_detail(exc)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"KoreDataGateway unreachable: {exc.reason}") from exc


# ----------------------------------------------------------------------------------------------------
def _post_json(url: str, payload: dict, timeout: int = _DEFAULT_TIMEOUT) -> dict | list | None:
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url,
        data    = body,
        headers = {"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            if not raw:
                return None
            return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"KoreDataGateway returned non-JSON response: {exc}") from exc
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from KoreDataGateway: {_parse_error_detail(exc)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"KoreDataGateway unreachable: {exc.reason}") from exc


# ====================================================================================================
# MARK: PUBLIC FUNCTIONS
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def koredata_search(
    query:   str,
    domains: list[str] | None = None,
    since:   str | None       = None,
    until:   str | None       = None,
    limit:   int              = DEFAULT_LIMIT,
) -> dict | str:
    """Search across KoreData services (feeds, reference, library) via the unified gateway API.

    Returns a dict with 'query', 'domains_searched', and 'results' keys. Each key in 'results'
    maps to the matched domain's list of result dicts.  Use koredata_get_article, koredata_get_entry,
    or koredata_get_book to retrieve full content from results.
    """
    base = _get_base_url()
    if not base:
        return f'KoreDataGateway not configured. Add "{_CONFIG_KEY}" to default.json.'
    if not query or not query.strip():
        return "A search query is required."
    limit   = min(max(1, int(limit)), MAX_LIMIT)
    payload: dict = {"query": query.strip(), "limit": limit}
    if domains:
        # The LLM may pass domains as a JSON-encoded string e.g. '["library"]' rather than a list.
        # Parse it back to a list before iterating so we don't explode it character by character.
        if isinstance(domains, str):
            try:
                domains = json.loads(domains)
            except json.JSONDecodeError:
                domains = [domains]
        payload["domains"] = [str(d).strip().lower() for d in domains]
    if since:
        payload["since"] = str(since).strip()
    if until:
        payload["until"] = str(until).strip()
    try:
        data = _post_json(f"{base}/search", payload)
        if not data:
            return f'No results found for "{query}".'
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def koredata_get_article(title: str) -> dict | str:
    """Fetch a full KoreReference article by title.

    Pass the 'title' field exactly as returned by koredata_search results (e.g.
    'Arctic_sea_ice_decline').  Returns the article dict including body, sections, and links.
    Returns an error string on failure.
    """
    base = _get_base_url()
    if not base:
        return f'KoreDataGateway not configured. Add "{_CONFIG_KEY}" to default.json.'
    if not title or not str(title).strip():
        return "An article title is required."
    url = f"{base}/reference/{urllib.parse.quote(str(title).strip(), safe='')}"
    try:
        data = _get_json(url)
        if not data:
            return f'Article "{title}" not found.'
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def koredata_get_entry(domain: str, entry_id: int) -> dict | str:
    """Fetch a full KoreFeed entry by domain slug and entry ID.

    Pass the 'source' field as domain and the 'id' field as entry_id, both from a koredata_search
    feeds result.  Returns the full entry dict including page text.
    Returns an error string on failure.
    """
    base = _get_base_url()
    if not base:
        return f'KoreDataGateway not configured. Add "{_CONFIG_KEY}" to default.json.'
    if not domain or not str(domain).strip():
        return "A domain name is required."
    url = f"{base}/feeds/{urllib.parse.quote(str(domain).strip(), safe='')}/{int(entry_id)}"
    try:
        data = _get_json(url)
        if not data:
            return f'Entry {entry_id} not found in domain "{domain}".'
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def koredata_get_book(book_id: int) -> dict | str:
    """Fetch a full KoreLibrary book by its numeric ID.

    Pass the 'id' field from a koredata_search library result.
    Returns the full book dict including body text.
    Returns an error string on failure.
    """
    base = _get_base_url()
    if not base:
        return f'KoreDataGateway not configured. Add "{_CONFIG_KEY}" to default.json.'
    url = f"{base}/library/{int(book_id)}"
    try:
        data = _get_json(url)
        if not data:
            return f'Book {book_id} not found.'
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def koredata_get_chunk(chunk_id: int) -> dict | str:
    """Fetch a full KoreRAG chunk by its numeric ID.

    Pass the 'id' field from a koredata_search rag result.
    Returns the full chunk dict including decompressed content, title, source, and tags.
    Returns an error string on failure.
    """
    base = _get_base_url()
    if not base:
        return f'KoreDataGateway not configured. Add "{_CONFIG_KEY}" to default.json.'
    url = f"{base}/rag/{int(chunk_id)}"
    try:
        data = _get_json(url)
        if not data:
            return f'RAG chunk {chunk_id} not found.'
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def koredata_status() -> dict | str:
    """Return the gateway health status, including the state of each child service.

    Useful for diagnosing connectivity before a search when the gateway may not be running.
    Returns a dict with a 'children' key containing per-service health info.
    """
    base = _get_base_url()
    if not base:
        return f'KoreDataGateway not configured. Add "{_CONFIG_KEY}" to default.json.'
    try:
        data = _get_json(f"{base}/status")
        if not data:
            return "KoreDataGateway returned an empty status response."
        return data
    except RuntimeError as exc:
        return str(exc)
