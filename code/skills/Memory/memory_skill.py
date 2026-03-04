# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# Memory skill module for the MiniAgentFramework.
#
# Stores environment-specific facts extracted from user prompts in a plain text file and supports
# lightweight relevance-based recall for later prompts.
#
# Related modules:
#   - main.py                   -- calls recall/store helpers during orchestration
#   - skills_catalog_builder.py -- reads skill.md to build the catalog entry
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import re
from datetime import datetime
from pathlib import Path


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
MEMORY_STORE_PATH = Path(__file__).resolve().parent / "memory_store.txt"

ENVIRONMENT_HINT_PATTERNS = [
    re.compile(r"[A-Za-z]:\\\\[^\s,;]+"),
    re.compile(r"(?:^|\s)(?:\./|\.\./)[^\s,;]+"),
    re.compile(r"(?:^|\s)/(?:[^\s/]+/)+[^\s/]*"),
    re.compile(r"\b\d+\.\d+(?:\.\d+)?\b"),
    re.compile(r"\b(?:gpt|llama|ollama|python|windows|linux|macos|repo|workspace|project|folder|path|model|version)\b", re.IGNORECASE),
]

ENVIRONMENT_KEYWORDS = {
    "workspace",
    "repo",
    "repository",
    "project",
    "folder",
    "directory",
    "path",
    "machine",
    "local",
    "installed",
    "running",
    "model",
    "models",
    "version",
    "python",
    "ollama",
    "windows",
    "linux",
    "macos",
    "framework",
}

GENERAL_KNOWLEDGE_HINTS = {
    "capital",
    "planet",
    "photosynthesis",
    "einstein",
    "history",
    "define",
    "explain",
}


# ====================================================================================================
# MARK: HELPERS
# ====================================================================================================
def _utc_now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------------------------------
def _ensure_store_file() -> None:
    if MEMORY_STORE_PATH.exists():
        return

    MEMORY_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_STORE_PATH.write_text(
        "# MiniAgentFramework memory store\n"
        "# Format: <timestamp>|<fact>\n",
        encoding="utf-8",
    )


# ----------------------------------------------------------------------------------------------------
def _normalize_fact(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\s:/._\\-]", "", lowered)
    return lowered


# ----------------------------------------------------------------------------------------------------
def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_\\./:-]+", text.lower()) if len(token) >= 3}


# ----------------------------------------------------------------------------------------------------
def _read_memory_rows() -> list[tuple[str, str]]:
    _ensure_store_file()
    rows = []
    for raw_line in MEMORY_STORE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            continue
        timestamp, fact = line.split("|", maxsplit=1)
        rows.append((timestamp.strip(), fact.strip()))
    return rows


# ----------------------------------------------------------------------------------------------------
def _is_environment_specific_fact(candidate: str) -> bool:
    normalized = candidate.strip()
    if not normalized:
        return False

    lowered = normalized.lower()
    if "?" in lowered:
        return False

    if any(token in lowered for token in GENERAL_KNOWLEDGE_HINTS):
        return False

    has_keyword = any(keyword in lowered for keyword in ENVIRONMENT_KEYWORDS)
    has_pattern = any(pattern.search(normalized) for pattern in ENVIRONMENT_HINT_PATTERNS)
    has_assertion_verb = bool(re.search(r"\b(is|are|uses|using|has|have|located|runs|running|installed|set to)\b", lowered))

    return (has_keyword or has_pattern) and has_assertion_verb


# ----------------------------------------------------------------------------------------------------
def _extract_candidate_segments(user_prompt: str) -> list[str]:
    # Split on hard separators but avoid breaking decimal/version tokens and relative paths (./, ../).
    split_segments = re.split(r"[\n\r;]+|(?<![\d./])\.(?![\d./])", user_prompt)
    normalized_segments = []

    for segment in split_segments:
        cleaned = segment.strip(" -\t")
        if not cleaned:
            continue
        cleaned = re.sub(r"\s+", " ", cleaned)
        normalized_segments.append(cleaned)

    return normalized_segments


# ====================================================================================================
# MARK: PUBLIC SKILL API
# ====================================================================================================
def extract_environment_facts(user_prompt: str) -> list[str]:
    candidates = _extract_candidate_segments(user_prompt=user_prompt)

    facts = []
    seen = set()
    for candidate in candidates:
        if not _is_environment_specific_fact(candidate):
            continue

        normalized = _normalize_fact(candidate)
        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        facts.append(candidate)

    return facts


# ----------------------------------------------------------------------------------------------------
def store_prompt_memories(user_prompt: str) -> str:
    facts = extract_environment_facts(user_prompt=user_prompt)
    if not facts:
        _ensure_store_file()
        return "No new environment-specific facts detected in prompt."

    existing_rows = _read_memory_rows()
    existing_keys = {_normalize_fact(fact) for _, fact in existing_rows}

    added_count = 0
    timestamp = _utc_now_iso()

    with MEMORY_STORE_PATH.open("a", encoding="utf-8") as memory_file:
        for fact in facts:
            normalized = _normalize_fact(fact)
            if normalized in existing_keys:
                continue

            memory_file.write(f"{timestamp}|{fact}\n")
            existing_keys.add(normalized)
            added_count += 1

    if added_count == 0:
        return "No new memories were stored (all detected facts already existed)."

    return f"Stored {added_count} new memory fact(s)."


# ----------------------------------------------------------------------------------------------------
def recall_relevant_memories(user_prompt: str, limit: int = 5, min_score: float = 0.25) -> str:
    rows = _read_memory_rows()
    if not rows:
        return "No memories stored yet."

    query_tokens = _tokenize(user_prompt)
    if not query_tokens:
        return "No memories recalled (query had no meaningful tokens)."

    scored_rows = []
    for timestamp, fact in rows:
        fact_tokens = _tokenize(fact)
        if not fact_tokens:
            continue

        overlap = query_tokens & fact_tokens
        if not overlap:
            continue

        score = len(overlap) / max(len(query_tokens), 1)
        if score < min_score and user_prompt.lower() not in fact.lower() and fact.lower() not in user_prompt.lower():
            continue

        scored_rows.append((score, timestamp, fact))

    if not scored_rows:
        return "No relevant memories matched this prompt."

    scored_rows.sort(key=lambda item: (-item[0], item[1]))
    selected = scored_rows[: max(limit, 1)]

    lines = ["Relevant memories:"]
    for score, timestamp, fact in selected:
        lines.append(f"- ({score:.2f}) {fact} [stored: {timestamp}]")

    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------------
def get_memory_store_text() -> str:
    _ensure_store_file()
    return MEMORY_STORE_PATH.read_text(encoding="utf-8")
