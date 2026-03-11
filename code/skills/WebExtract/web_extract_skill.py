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
#   - webpage_utils.py                     -- HTTP fetch, HTML extraction, text utilities (shared)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import urllib.error
import urllib.parse

from webpage_utils import fetch_html as _fetch_html
from webpage_utils import extract_content as _extract_content
from webpage_utils import truncate_to_words as _truncate_to_words


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
MAX_WORDS_CAP     = 4000
DEFAULT_MAX_WORDS = 1000
DEFAULT_TIMEOUT   = 15


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
    Returns a descriptive error string on network/parse failure - never raises.
    """
    if not url or not url.strip():
        return "Error: url cannot be empty."

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return f"Error: unsupported URL scheme '{parsed.scheme}'. Only http and https are supported."

    max_words       = max(50, min(int(max_words),       MAX_WORDS_CAP))
    timeout_seconds = max(5,  min(int(timeout_seconds), 60))

    try:
        html_text, _ = _fetch_html(url.strip(), timeout=float(timeout_seconds))
    except urllib.error.HTTPError as exc:
        return f"Error fetching page: HTTP {exc.code} - {url}"
    except urllib.error.URLError as exc:
        return f"Error fetching page: {exc.reason} - {url}"
    except Exception as exc:
        return f"Error fetching page: {exc} - {url}"

    _, body = _extract_content(html_text)

    if not body.strip():
        return f"Could not extract readable text from: {url}"

    return _truncate_to_words(body, max_words)
