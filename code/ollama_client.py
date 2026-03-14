# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# HTTP client and server-management utilities for Ollama inference services.
#
# Supports local Ollama, LAN-hosted Ollama machines, and Ollama Cloud. The active host
# and optional API key are configured once at startup via configure_host(); all subsequent
# calls use the configured values without requiring callers to thread them through.
#
# Provides a thin layer over Ollama's REST API, covering:
#   - Host configuration and connectivity checking.
#   - Health-checking and auto-starting the local Ollama process (local only).
#   - Listing installed models and resolving short aliases to fully-qualified model tags.
#   - Parsing `ollama ps` output to report real-time model runtime status (local only).
#   - Sending prompt/completion requests and surfacing actionable error messages.
#
# Related modules:
#   - main.py                   -- calls configure_host(), ensure_ollama_running(), model utilities
#   - planner_engine.py         -- uses call_ollama_extended for planner LLM calls
#   - skills_catalog_builder.py -- uses call_ollama for optional LLM skill summarisation
#   - system_check.py           -- uses model listing and call_ollama for diagnostics
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
DEFAULT_OLLAMA_HOST   = "http://localhost:11434"
OLLAMA_CLOUD_HOST     = "https://api.ollama.com"
_DEFAULT_LLM_TIMEOUT: int = 300   # seconds; updated at runtime by /timeout slash command

# Active host and optional API key - set once at startup via configure_host().
# Default to local Ollama; overridden by --ollama-host / OLLAMA_HOST env var.
_active_host:    str        = DEFAULT_OLLAMA_HOST
_active_api_key: str | None = None


def get_llm_timeout() -> int:
    """Return the current default LLM generation timeout in seconds."""
    return _DEFAULT_LLM_TIMEOUT


def set_llm_timeout(seconds: int) -> None:
    """Update the default LLM generation timeout used by all call_ollama_extended calls."""
    global _DEFAULT_LLM_TIMEOUT
    _DEFAULT_LLM_TIMEOUT = seconds


# ----------------------------------------------------------------------------------------------------
_llm_call_log_fn = None   # optional (str) -> None; set via register_llm_call_logger


def register_llm_call_logger(fn) -> None:
    """Register a callback invoked before every call_ollama_extended call.

    The callback receives a single formatted string describing the call so it can
    be written to whatever log sink the caller controls.
    """
    global _llm_call_log_fn
    _llm_call_log_fn = fn


# ====================================================================================================
# MARK: CONFIGURATION
# ====================================================================================================
def configure_host(host: str, api_key: str | None = None) -> None:
    """Set the active Ollama host and optional API key for all subsequent LLM calls.

    - Local Ollama (default): http://localhost:11434  - no API key needed.
    - LAN machine:            http://<ip>:11434       - no API key needed.
    - Ollama Cloud:           https://api.ollama.com  - requires an API key.

    Stored as module-level state; mirrors the pattern used by set_llm_timeout().
    """
    global _active_host, _active_api_key
    _active_host    = host.rstrip("/")
    _active_api_key = api_key or None


# ----------------------------------------------------------------------------------------------------
def get_active_host() -> str:
    """Return the currently configured Ollama host URL."""
    return _active_host


# ----------------------------------------------------------------------------------------------------
def get_active_api_key() -> str | None:
    """Return the currently configured Ollama API key, or None for local/LAN hosts."""
    return _active_api_key


# ----------------------------------------------------------------------------------------------------
def _is_local_host(host: str) -> bool:
    return "localhost" in host or "127.0.0.1" in host or "0.0.0.0" in host


# ====================================================================================================
# MARK: DATA TYPES
# ====================================================================================================
@dataclass
class OllamaCallResult:
    """Structured return from call_ollama_extended, including token usage and throughput."""
    response:               str
    prompt_tokens:          int
    completion_tokens:      int
    total_tokens:           int
    eval_duration_ns:       int = 0   # nanoseconds the model spent generating completion tokens
    prompt_eval_duration_ns: int = 0  # nanoseconds the model spent evaluating the prompt

    @property
    def tokens_per_second(self) -> float:
        """Completion token generation rate (tok/s). Returns 0.0 when timing is unavailable."""
        if self.eval_duration_ns <= 0 or self.completion_tokens <= 0:
            return 0.0
        return self.completion_tokens / (self.eval_duration_ns / 1_000_000_000)


# ====================================================================================================
# MARK: CORE HTTP + OLLAMA UTILITIES
# ====================================================================================================
def _request_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 10.0) -> dict:
    request_data = None
    headers      = {}

    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if _active_api_key:
        headers["Authorization"] = f"Bearer {_active_api_key}"

    request = urllib.request.Request(
        url=url,
        data=request_data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw_body = response.read().decode("utf-8")

    return json.loads(raw_body)


# ----------------------------------------------------------------------------------------------------
def is_ollama_running(host: str | None = None) -> bool:
    host = host or _active_host
    try:
        _request_json(url=f"{host.rstrip('/')}/api/tags", timeout=3.0)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------------
def start_ollama_server() -> None:
    # Build platform-specific flags to fully detach the server process from this parent.
    creation_flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation_flags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "'ollama' executable not found on PATH. "
            "Please install Ollama (https://ollama.com) and ensure it is on your PATH."
        ) from None


# ----------------------------------------------------------------------------------------------------
def ensure_ollama_running(
    host: str | None = None,
    start_if_needed: bool = True,
    wait_seconds: float = 20.0,
) -> None:
    host = host or _active_host
    if is_ollama_running(host=host):
        return

    if not start_if_needed or not _is_local_host(host):
        raise RuntimeError(f"Ollama is not reachable at {host}")

    start_ollama_server()
    # Poll until the server responds or the deadline expires, then raise if still unreachable.
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_ollama_running(host=host):
            return
        time.sleep(0.5)

    raise RuntimeError(f"Ollama did not become ready at {host} within {wait_seconds:.0f}s")


# ----------------------------------------------------------------------------------------------------
def list_ollama_models(host: str | None = None) -> list[str]:
    host   = host or _active_host
    body   = _request_json(url=f"{host.rstrip('/')}/api/tags", timeout=10.0)
    models = body.get("models", [])
    return [entry.get("model", "") for entry in models if entry.get("model")]


# ----------------------------------------------------------------------------------------------------
def get_ollama_ps_rows() -> list[dict[str, str]]:
    """Return currently running models as a list of dicts with at least a 'name' key.

    For local hosts: parses `ollama ps` subprocess output (preserves existing behaviour).
    For remote/cloud hosts: calls the /api/ps REST endpoint instead (same data, over HTTP).
    """
    if _is_local_host(_active_host):
        return _get_ollama_ps_rows_local()
    return _get_ollama_ps_rows_remote(_active_host)


def _get_ollama_ps_rows_local() -> list[dict[str, str]]:
    result = subprocess.run(
        ["ollama", "ps"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to run 'ollama ps': {result.stderr.strip()}")

    lines = [line.rstrip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return []

    # Parse the header line to derive column names, then split each data row by the same spacing.
    columns = [column.lower() for column in re.split(r"\s{2,}", lines[0].strip())]
    rows    = []

    for line in lines[1:]:
        values = re.split(r"\s{2,}", line.strip(), maxsplit=max(0, len(columns) - 1))
        if len(values) < len(columns):
            values += [""] * (len(columns) - len(values))

        row = dict(zip(columns, values))
        rows.append(row)

    return rows


def _get_ollama_ps_rows_remote(host: str) -> list[dict[str, str]]:
    """Call /api/ps on a remote Ollama host and normalise the response into the same row shape."""
    try:
        data   = _request_json(f"{host.rstrip('/')}/api/ps", timeout=10.0)
        models = data.get("models") or []
    except Exception:
        return []

    rows = []
    for m in models:
        details      = m.get("details") or {}
        size_bytes   = m.get("size", 0)
        size_gb      = f"{size_bytes / 1_073_741_824:.1f} GB" if size_bytes else ""
        size_vram    = m.get("size_vram", 0)
        vram_gb      = f"{size_vram / 1_073_741_824:.1f} GB" if size_vram else "0 B"
        rows.append({
            "name":       m.get("name", ""),
            "id":         m.get("digest", "")[:12],
            "size":       size_gb,
            "processor":  "100% GPU" if size_vram else "100% CPU",
            "vram":       vram_gb,
            "until":      m.get("expires_at", ""),
            "param_size": details.get("parameter_size", ""),
        })

    return rows


# ----------------------------------------------------------------------------------------------------
def get_running_model_row(model_name: str) -> dict[str, str] | None:
    rows             = get_ollama_ps_rows()
    running_names    = [row.get("name", "") for row in rows if row.get("name")]
    resolved_running = resolve_model_name(model_name, running_names)

    if not resolved_running:
        return None

    for row in rows:
        if row.get("name", "").lower() == resolved_running.lower():
            return row

    return None


# ----------------------------------------------------------------------------------------------------
def format_running_model_report(model_name: str) -> str:
    row = get_running_model_row(model_name)
    if row is None:
        return f"Model runtime status: {model_name} not currently loaded (ollama ps)."

    size      = row.get("size", "unknown")
    processor = row.get("processor", "unknown")
    context   = row.get("context", row.get("param_size", "unknown"))
    until     = row.get("until", "unknown")
    running   = row.get("name", model_name)

    return (
        f"Model runtime status: {running} | size={size} | processor={processor} "
        f"| context={context} | until={until}"
    )


# ----------------------------------------------------------------------------------------------------
def resolve_model_name(requested_model: str, available_models: list[str]) -> str | None:
    # Resolution order: (1) exact match, (2) base-name prefix (e.g. "llama3" → "llama3:8b"),
    # (3) tag suffix (e.g. "8b" → "llama3:8b"), (4) word-boundary token match (e.g. "20b").
    # Each step only returns a result when there is exactly one candidate, to avoid ambiguity.
    requested_lower = requested_model.lower().strip()
    if not requested_lower:
        return None

    # Exact full-name match (case-insensitive).
    for model_name in available_models:
        if model_name.lower() == requested_lower:
            return model_name

    # Match when the requested string is the base name part before a colon tag.
    exact_prefix_matches = [
        model_name
        for model_name in available_models
        if model_name.lower().startswith(f"{requested_lower}:")
    ]
    if len(exact_prefix_matches) == 1:
        return exact_prefix_matches[0]

    # Match when the requested string is the tag part after the colon.
    exact_suffix_matches = [
        model_name
        for model_name in available_models
        if model_name.lower().endswith(f":{requested_lower}")
    ]
    if len(exact_suffix_matches) == 1:
        return exact_suffix_matches[0]

    # Substring match as a last resort - only accepted when exactly one model matches.
    # Use word-boundary-aware matching so that "20b" doesn't match "120b" and vice-versa.
    # Hyphens are also treated as part of the name (e.g. "qwen3" must not match "qwen3-coder").
    token_matches = [
        model_name
        for model_name in available_models
        if re.search(rf"(?<![0-9]){re.escape(requested_lower)}(?![0-9a-z\-])", model_name.lower())
    ]
    if len(token_matches) == 1:
        return token_matches[0]

    return None


# ----------------------------------------------------------------------------------------------------
def stop_model(
    model_name: str,
    host: str | None = None,
) -> None:
    """Unload a model from VRAM immediately by sending keep_alive=0 to the generate endpoint.

    Ollama interprets a generate request with keep_alive=0 as an instruction to evict the
    model from memory as soon as the (empty) call completes.  Raises RuntimeError on failure.
    """
    host    = host or _active_host
    payload = {
        "model":      model_name,
        "prompt":     "",
        "keep_alive": 0,
        "stream":     False,
    }
    try:
        _request_json(
            url=f"{host.rstrip('/')}/api/generate",
            method="POST",
            payload=payload,
            timeout=30.0,
        )
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP error {error.code} stopping model: {error_body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Unable to reach Ollama at {host}: {error.reason}") from error


# ----------------------------------------------------------------------------------------------------
def call_ollama_extended(
    model_name: str,
    prompt: str,
    host: str | None = None,
    num_ctx: int | None = None,
    timeout: int | None = None,
) -> OllamaCallResult:
    """Call the Ollama generate endpoint and return the response with token usage counts.

    timeout defaults to the module-level _DEFAULT_LLM_TIMEOUT (set via set_llm_timeout()).
    """
    host = host or _active_host
    ensure_ollama_running(host=host, start_if_needed=True)

    if _llm_call_log_fn is not None:
        preview = prompt.replace("\n", " ")[:32]
        ctx_str = f"{num_ctx:,}" if num_ctx is not None else "default"
        try:
            _llm_call_log_fn(f"[LLM call] {model_name} | ctx={ctx_str} | {preview!r}")
        except Exception:
            pass

    options = {}
    if num_ctx is not None:
        options["num_ctx"] = num_ctx

    payload = {
        "model":  model_name,
        "prompt": prompt,
        "stream": False,
    }
    if options:
        payload["options"] = options

    effective_timeout = timeout if timeout is not None else _DEFAULT_LLM_TIMEOUT
    try:
        body = _request_json(
            url=f"{host.rstrip('/')}/api/generate",
            method="POST",
            payload=payload,
            timeout=effective_timeout,
        )
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        # Provide a helpful message listing installed models when the requested model is absent.
        if error.code == 404 and "not found" in error_body.lower():
            available_models = []
            try:
                available_models = list_ollama_models(host=host)
            except Exception:
                pass

            if available_models:
                available_text = ", ".join(available_models)
                raise RuntimeError(
                    f"Model '{model_name}' not found. Installed models: {available_text}"
                ) from error

        raise RuntimeError(f"Ollama HTTP error {error.code}: {error_body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Unable to reach Ollama at {host}: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Ollama returned a non-JSON response") from error

    if "response" not in body:
        raise RuntimeError(f"Ollama response missing 'response' field: {body}")

    prompt_tokens            = body.get("prompt_eval_count", 0)
    completion_tokens        = body.get("eval_count", 0)
    eval_duration_ns         = body.get("eval_duration", 0)
    prompt_eval_duration_ns  = body.get("prompt_eval_duration", 0)
    return OllamaCallResult(
        response=body["response"],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        eval_duration_ns=eval_duration_ns,
        prompt_eval_duration_ns=prompt_eval_duration_ns,
    )


# ----------------------------------------------------------------------------------------------------
def call_ollama(
    model_name: str,
    prompt: str,
    host: str | None = None,
    num_ctx: int | None = None,
) -> str:
    """Convenience wrapper - returns the response text only. See call_ollama_extended for token counts."""
    return call_ollama_extended(model_name=model_name, prompt=prompt, host=host, num_ctx=num_ctx).response
