# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import json
import re
import subprocess
import time
import urllib.error
import urllib.request


# ====================================================================================================
# MARK: CONSTANTS
# ====================================================================================================
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


# ====================================================================================================
# MARK: CORE HTTP + OLLAMA UTILITIES
# ====================================================================================================
def _request_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 10.0) -> dict:
    request_data = None
    headers      = {}

    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        headers      = {"Content-Type": "application/json"}

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
def is_ollama_running(host: str = DEFAULT_OLLAMA_HOST) -> bool:
    try:
        _request_json(url=f"{host.rstrip('/')}/api/tags", timeout=3.0)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------------
def start_ollama_server() -> None:
    creation_flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation_flags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creation_flags,
    )


# ----------------------------------------------------------------------------------------------------
def ensure_ollama_running(
    host: str = DEFAULT_OLLAMA_HOST,
    start_if_needed: bool = True,
    wait_seconds: float = 20.0,
) -> None:
    if is_ollama_running(host=host):
        return

    if not start_if_needed:
        raise RuntimeError(f"Ollama is not reachable at {host}")

    start_ollama_server()
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_ollama_running(host=host):
            return
        time.sleep(0.5)

    raise RuntimeError(f"Ollama did not become ready at {host} within {wait_seconds:.0f}s")


# ----------------------------------------------------------------------------------------------------
def list_ollama_models(host: str = DEFAULT_OLLAMA_HOST) -> list[str]:
    body   = _request_json(url=f"{host.rstrip('/')}/api/tags", timeout=10.0)
    models = body.get("models", [])
    return [entry.get("model", "") for entry in models if entry.get("model")]


# ----------------------------------------------------------------------------------------------------
def get_ollama_ps_rows() -> list[dict[str, str]]:
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

    columns = [column.lower() for column in re.split(r"\s{2,}", lines[0].strip())]
    rows    = []

    for line in lines[1:]:
        values = re.split(r"\s{2,}", line.strip(), maxsplit=max(0, len(columns) - 1))
        if len(values) < len(columns):
            values += [""] * (len(columns) - len(values))

        row = dict(zip(columns, values))
        rows.append(row)

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
    context   = row.get("context", "unknown")
    until     = row.get("until", "unknown")
    running   = row.get("name", model_name)

    return (
        f"Model runtime status: {running} | size={size} | processor={processor} "
        f"| context={context} | until={until}"
    )


# ----------------------------------------------------------------------------------------------------
def resolve_model_name(requested_model: str, available_models: list[str]) -> str | None:
    requested_lower = requested_model.lower().strip()
    if not requested_lower:
        return None

    for model_name in available_models:
        if model_name.lower() == requested_lower:
            return model_name

    exact_prefix_matches = [
        model_name
        for model_name in available_models
        if model_name.lower().startswith(f"{requested_lower}:")
    ]
    if len(exact_prefix_matches) == 1:
        return exact_prefix_matches[0]

    exact_suffix_matches = [
        model_name
        for model_name in available_models
        if model_name.lower().endswith(f":{requested_lower}")
    ]
    if len(exact_suffix_matches) == 1:
        return exact_suffix_matches[0]

    token_matches = [
        model_name
        for model_name in available_models
        if requested_lower in model_name.lower()
    ]
    if len(token_matches) == 1:
        return token_matches[0]

    return None


# ----------------------------------------------------------------------------------------------------
def call_ollama(
    model_name: str,
    prompt: str,
    host: str = DEFAULT_OLLAMA_HOST,
    num_ctx: int | None = None,
) -> str:
    ensure_ollama_running(host=host, start_if_needed=True)

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

    try:
        body = _request_json(
            url=f"{host.rstrip('/')}/api/generate",
            method="POST",
            payload=payload,
            timeout=120,
        )
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
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

    return body["response"]
