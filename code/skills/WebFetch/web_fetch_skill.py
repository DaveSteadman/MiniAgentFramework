# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# WebFetch skill for the MiniAgentFramework.
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
#   2. WebFetch fetches the most relevant URL and returns readable content.
#   3. The final LLM call synthesizes an answer from that content.
#
# Related modules:
#   - skills/WebSearch/web_search_skill.py -- upstream skill that produces candidate URLs
#   - main.py                              -- orchestration entry point
#   - skills_catalog_builder.py            -- reads skill.md to build the catalog
#   - webpage_utils.py                     -- HTTP fetch, HTML extraction, text utilities (shared)
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import urllib.error
import urllib.parse
from pathlib import Path

# Ensure code/ is on the path so ollama_client is importable when this skill is loaded dynamically.
_code_dir = str(Path(__file__).resolve().parents[2])
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

from ollama_client import call_llm_chat as _call_llm_chat
from ollama_client import get_active_model as _get_active_model
from ollama_client import get_active_num_ctx as _get_active_num_ctx
from webpage_utils import fetch_html as _fetch_html
from webpage_utils import extract_content as _extract_content
from webpage_utils import truncate_to_words as _truncate_to_words


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
MAX_WORDS_CAP     = 4000   # raw return (no query) - kept small to protect main context
QUERY_WORDS_CAP   = 10000  # query-mode - inner LLM handles it, main context only gets the extract
DEFAULT_MAX_WORDS = 1000
DEFAULT_TIMEOUT   = 15


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def fetch_page_text(
    url: str,
    max_words: int = DEFAULT_MAX_WORDS,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    query: str | None = None,
) -> str:
    """Fetch a web page and return its clean readable text, stripped of all HTML markup.

    Removes navigation, scripts, advertisements, and other non-content elements.
    Returns up to max_words words of body prose suitable for LLM consumption.
    Returns a descriptive error string on network/parse failure - never raises.

    When query is provided, the full page text is passed through an isolated LLM call that
    extracts only the information relevant to the query. The returned answer is compact and
    does not burden the caller's context window with raw page content.
    """
    if not url or not url.strip():
        return "Error: url cannot be empty."

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return f"Error: unsupported URL scheme '{parsed.scheme}'. Only http and https are supported."

    # When extracting for a specific query, fetch a larger cap so the inner LLM has
    # maximum material - complete list pages can be long. For raw return, respect the
    # caller-supplied max_words limit and the smaller cap.
    fetch_words     = QUERY_WORDS_CAP if query else max(50, min(int(max_words), MAX_WORDS_CAP))
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

    body = _truncate_to_words(body, fetch_words)

    if not query:
        return body

    # -- Isolated extraction call --
    # Run a throwaway LLM call in its own context so the full page text never enters the
    # main messages thread. Only the compact extracted answer is returned to the caller.
    model   = _get_active_model()
    num_ctx = _get_active_num_ctx()
    if not model:
        # No model registered yet - fall back to raw truncated text.
        return _truncate_to_words(body, max(50, min(int(max_words), MAX_WORDS_CAP)))

    inner_messages = [
        {
            "role":    "system",
            "content": (
                "You are a precise data extractor and filter. "
                "Read the question carefully, then apply TWO steps:\n"
                "1. FILTER: if the question targets a specific entity (a person, organisation, category, "
                "or value), include ONLY rows where the relevant column matches that entity exactly. "
                "Exclude every row that belongs to a different entity entirely.\n"
                "2. EXTRACT: from the matching rows, pull all relevant columns into a markdown table. "
                "Always retain the column that was used for filtering so the output is self-verifiable.\n"
                "Additional rules:\n"
                "- List every matching item individually - never group, compress, or summarise "
                "multiple items into ranges or counts.\n"
                "- If no rows match the filter, respond with exactly: Not found on this page."
            ),
        },
        {
            "role":    "user",
            "content": f"Question: {query}\n\nPage content:\n{body}",
        },
    ]

    try:
        result = _call_llm_chat(
            model_name=model,
            messages=inner_messages,
            tools=None,
            num_ctx=num_ctx,
        )
        extracted = (result.response or "").strip()
        return extracted if extracted else f"Could not extract relevant content from: {url}"
    except Exception as exc:
        return f"Error during extraction LLM call: {exc}"
