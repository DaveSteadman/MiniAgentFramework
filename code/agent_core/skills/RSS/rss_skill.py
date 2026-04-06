# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# RSS skill for the MiniAgentFramework.
#
# Provides search and retrieval of ingested RSS/news entries from a running MiniFeed server.
# MiniFeed is a separate background service that handles all RSS fetching, deduplication, and
# full-text indexing. This skill is a pure REST consumer - it never touches RSS feeds directly.
#
# Six public functions are exposed:
#   rss_list_domains()                      -- list all domains and their entry counts
#   rss_list_feeds()                        -- list all configured feeds (even empty domains)
#   rss_search(query, limit, fetch_full)    -- full-text search across all domains, optionally with body text
#   rss_get_recent(hours, limit)            -- entries ingested within the last N hours, all domains
#   rss_get_entries(domain, limit, offset)  -- paginated recent entries for one domain
#   rss_get_entry(domain, entry_id)         -- full entry record including body text
#
# Configuration:
#   Set "minifeedurl" in default.json (repo root), e.g. "http://localhost:8100".
#   If the key is absent or the server is unreachable all functions return a human-readable
#   error string - they never raise.
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

from utils.workspace_utils import get_workspace_root


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
_DEFAULTS_PATH       = get_workspace_root() / "default.json"
_CONFIG_KEY          = "minifeedurl"
_DEFAULT_TIMEOUT     = 10

DEFAULT_SEARCH_LIMIT = 20
DEFAULT_ENTRY_LIMIT  = 20
MAX_LIMIT_CAP        = 100


# ====================================================================================================
# MARK: CONFIG
# ====================================================================================================
# Config is read once on first call and cached for the lifetime of the process.
# A threading lock ensures only one thread performs the cold read.

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
# MARK: HTTP HELPER
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def _parse_error_detail(exc: urllib.error.HTTPError) -> str:
    # FastAPI serialises errors as {"detail": "..."}. Try to surface that string
    # so the agent gets a useful message rather than just the numeric status code.
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
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from MiniFeed: {_parse_error_detail(exc)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniFeed unreachable: {exc.reason}") from exc


# ====================================================================================================
# MARK: PUBLIC FUNCTIONS
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
def rss_list_domains() -> list[dict] | str:
    """Return all domains known to MiniFeed with their entry counts."""
    base = _get_base_url()
    if not base:
        return f'MiniFeed not configured. Add "{_CONFIG_KEY}" to default.json.'
    try:
        data = _get_json(f"{base}/api/domains")
        if not data:
            return "No domains found. MiniFeed may not have ingested any feeds yet."
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def rss_list_feeds() -> list[dict] | str:
    """Return all configured feeds, including those whose domain has no entries yet.

    Each feed includes id, domain, name, url, and update_rate (minutes).
    Use this to see what is being tracked even before ingestion has run.
    """
    base = _get_base_url()
    if not base:
        return f'MiniFeed not configured. Add "{_CONFIG_KEY}" to default.json.'
    try:
        data = _get_json(f"{base}/api/feeds")
        if data is None:
            return "No feeds configured in MiniFeed."
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def rss_search(
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    fetch_full: bool = False,
) -> list[dict] | str:
    """Full-text search across RSS entry headlines and page text.

    Searches all domains. Set `fetch_full=True` to include page_text in each
    result (costs more bandwidth but saves a follow-up rss_get_entry call).
    """
    base = _get_base_url()
    if not base:
        return f'MiniFeed not configured. Add "{_CONFIG_KEY}" to default.json.'
    if not query or not query.strip():
        return "A search query is required."
    limit      = min(max(1, int(limit)), MAX_LIMIT_CAP)
    fetch_full = str(fetch_full).lower() not in ("false", "0", "")
    params: dict[str, str | int] = {"q": query.strip(), "limit": limit}
    if fetch_full:
        params["full"] = "true"
    url = f"{base}/api/search?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
        if not data:
            return f'No results found for "{query}".'
        # Strip the raw URL so the model cannot pass it to fetch_page_text.
        # Article body text is already stored in MiniFeed - use rss_get_entry(domain, id) instead.
        if isinstance(data, list):
            for entry in data:
                entry.pop("url", None)
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def rss_get_recent(
    hours: float = 24.0,
    limit: int = DEFAULT_ENTRY_LIMIT,
) -> list[dict] | str:
    """Return entries ingested within the last N hours, newest first.

    Searches all domains. Each entry includes id, feed_name, headline,
    published, ingested_at, and domain fields.
    Use rss_get_entry(domain, id) to retrieve the article body text.
    """
    base = _get_base_url()
    if not base:
        return f'MiniFeed not configured. Add "{_CONFIG_KEY}" to default.json.'
    hours  = float(hours)
    limit  = int(limit)
    if hours <= 0:
        return "hours must be greater than 0."
    limit  = min(max(1, limit), MAX_LIMIT_CAP)
    params: dict[str, int | float] = {"hours": hours, "limit": limit}
    url = f"{base}/api/recent?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
        if not data:
            return f'No entries found in the last {hours} hours.'
        # Strip the raw URL so the model cannot pass it to fetch_page_text.
        # Article body text is already stored in MiniFeed - use rss_get_entry(domain, id) instead.
        if isinstance(data, list):
            for entry in data:
                entry.pop("url", None)
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def rss_get_entries(
    domain: str,
    limit: int = DEFAULT_ENTRY_LIMIT,
    offset: int = 0,
) -> list[dict] | str:
    """Return recent entries for a domain, newest first.

    Each entry includes id, feed_name, headline, url, published, ingested_at,
    metadata, and page_text. Use `offset` for pagination.
    """
    base = _get_base_url()
    if not base:
        return f'MiniFeed not configured. Add "{_CONFIG_KEY}" to default.json.'
    if not domain or not str(domain).strip():
        return "A domain name is required."
    limit  = min(max(1, int(limit)), MAX_LIMIT_CAP)
    offset = max(0, int(offset))
    params = urllib.parse.urlencode({"limit": limit, "offset": offset})
    url    = f"{base}/api/domains/{urllib.parse.quote(domain.strip())}/entries?{params}"
    try:
        data = _get_json(url)
        if not data:
            return f'No entries found for domain "{domain}".'
        return data
    except RuntimeError as exc:
        return str(exc)


# ----------------------------------------------------------------------------------------------------
def rss_get_entry(domain: str, entry_id: int) -> dict | str:
    """Fetch a single RSS entry by domain and numeric ID.

    Returns the full record including page_text (the article body already
    scraped and stored by MiniFeed). Use page_text directly for summarisation
    - do NOT call fetch_page_text on the entry URL.
    Returns an error string on failure.
    """
    base = _get_base_url()
    if not base:
        return f'MiniFeed not configured. Add "{_CONFIG_KEY}" to default.json.'
    if not domain or not str(domain).strip():
        return "A domain name is required."
    url = f"{base}/api/domains/{urllib.parse.quote(str(domain).strip())}/entries/{int(entry_id)}"
    try:
        data = _get_json(url)
        if not data:
            return f'Entry {entry_id} not found in domain "{domain}".'
        # Strip the raw URL - page_text already contains the article body.
        # There is no need to call fetch_page_text on this URL.
        if isinstance(data, dict):
            data.pop("url", None)
        return data
    except RuntimeError as exc:
        return str(exc)
