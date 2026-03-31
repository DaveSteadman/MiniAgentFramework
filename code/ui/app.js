// ============================================================
// MiniAgentFramework Web UI - app.js
// Vanilla JS - no build step, no dependencies.
// ============================================================

// ====================================================================================================
// MARK: CONFIG
// ====================================================================================================
const API_BASE          = "";           // same origin
const SESSION_ID        = "web_" + Date.now();
const POLL_OLLAMA_MS    = 10_000;
const POLL_QUEUE_MS     = 3_000;
const POLL_TIMELINE_MS  = 30_000;
const POLL_LATEST_LOG_MS = 1_000;
const MAX_QUEUE_ITEMS   = 10;
const MAX_LOG_LINES     = 500;
const MAX_CHAT_MESSAGES = 200;

// CSS class name constants used by toggleWrap.
const CSS_NOWRAP      = "nowrap";
const CSS_WRAP_ACTIVE = "wrap-active";

// ====================================================================================================
// MARK: STATE
// ====================================================================================================
let _logLines       = [];
let _logEventSource = null;
let _inputHistory   = [];     // loaded from server on init, mirrors chathistory.json
let _historyIdx        = -1;     // -1 = not browsing history
let _ollamaReachable   = true;   // updated by refreshOllamaStatus; used in submitPrompt
let _timelineRefreshTimer = null;
let _queueResizeObserver  = null;
let _currentLogPath       = "";

// ====================================================================================================
// MARK: DOM REFS
// ====================================================================================================
const $ = id => document.getElementById(id);

const dom = {
    ollamaDot:    () => $("ollama-dot"),
    ollamaHost:   () => $("ollama-host"),
    ollamaModel:  () => $("ollama-model"),
    ollamaCtx:    () => $("ollama-ctx"),
    versionChip:  () => $("version-chip"),
    timeline:     () => $("timeline-ticker"),
    timelineQueue: () => $("timeline-queue"),
    log:          () => $("log-body"),
    chat:         () => $("chat-body"),
    input:        () => $("chat-input"),
    sendBtn:      () => $("send-btn"),
};

// ====================================================================================================
// MARK: FETCH HELPERS
// ====================================================================================================

async function apiFetch(path, opts) {
    try {
        const res = await fetch(API_BASE + path, opts);
        if (!res.ok) {
            const txt = await res.text().catch(() => "");
            console.warn("API error", path, res.status, txt);
            return null;
        }
        return await res.json();
    } catch (e) {
        console.warn("fetch failed", path, e.message);
        return null;
    }
}

// ====================================================================================================
// MARK: OLLAMA STATUS
// ====================================================================================================

async function refreshOllamaStatus() {
    const data = await apiFetch("/status/ollama");
    if (!data) {
        dom.ollamaHost().textContent  = "unreachable";
        dom.ollamaModel().textContent = "";
        dom.ollamaCtx().textContent   = "";
        dom.ollamaDot().className = "off";
        _ollamaReachable = false;
        return;
    }
    // Update text BEFORE dot so the two are never mismatched.
    const rows  = data.rows || [];
    const first = rows[0] || {};
    // Strip tag suffix from model name for display (e.g. "llama3.1:8b" -> "llama3.1:8b" kept as-is,
    // but strip size annotation if present like "llama3.1:8b-q4" stays; just trim whitespace).
    const modelName = (first.name || "").trim();
    const ctxVal    = data.num_ctx ? data.num_ctx.toLocaleString() + " ctx" : "";
    // Additional per-row detail: size and processor.
    const detail    = [first.size, first.processor].filter(Boolean).join("  ");
    dom.ollamaHost().textContent  = data.host  || "";
    dom.ollamaModel().textContent = modelName  || data.model || "";
    dom.ollamaCtx().textContent   = ctxVal;
    dom.ollamaDot().className = "on";
    _ollamaReachable = true;
}

// ====================================================================================================
// MARK: QUEUE STATUS
// ====================================================================================================

async function refreshQueue() {
    const data = await apiFetch("/queue");
    if (!data) return;
    _renderTimelineQueue(data);
    _scheduleTimelineRefresh();
}

// ----------------------------------------------------------------------------------------------------
async function refreshVersion() {
    const data = await apiFetch("/version");
    if (!data) return;
    dom.versionChip().textContent = "v" + data.version;
}

function _queueItemLabel(item) {
    if (item.label) return item.label.length > 40 ? item.label.slice(0, 40) + "..." : item.label;
    if (item.kind && item.kind !== "api_chat") return item.name;
    return item.name.slice(-8);  // last 8 chars of run_id as fallback
}

function _renderTimelineQueue(queueData) {
    const el           = dom.timelineQueue();
    if (!el) return;
    const nextPrompts  = queueData.next_prompts || [];
    const queuedTotal  = queueData.queued_prompt_count !== undefined ? String(queueData.queued_prompt_count) : "?";
    const previewLimit = queueData.next_prompts_limit !== undefined ? queueData.next_prompts_limit : MAX_QUEUE_ITEMS;
    el.innerHTML       = "";
    if (queuedTotal === "0" && nextPrompts.length === 0) return;

    const totalRow = document.createElement("div");
    totalRow.className   = "tl-sep";
    totalRow.textContent = "Queued prompts: " + queuedTotal;
    el.appendChild(totalRow);

    for (const item of nextPrompts) {
        const row = document.createElement("div");
        row.className   = item.state === "active" ? "tl-q-active" : "tl-q-pending";
        row.textContent = item.state === "active"
            ? "\u25B6 " + _queueItemLabel(item)
            : "  \u00B7 " + _queueItemLabel(item);
        el.appendChild(row);
    }
}

// ----------------------------------------------------------------------------------------------------
function _scheduleTimelineRefresh() {
    clearTimeout(_timelineRefreshTimer);
    _timelineRefreshTimer = setTimeout(() => {
        refreshTimeline();
    }, 50);
}

// ====================================================================================================
// MARK: TIMELINE
// ====================================================================================================

// Row height matches .tl-row: font-size 11px * line-height 1.55 = ~17px.
const TL_ROW_H = 17;

function _buildTimelineRow(slot, activeTask) {
    const row = document.createElement("div");
    row.className = "tl-row" + (slot.is_now ? " tl-now" : "");
    if (slot.task_name && slot.task_name === activeTask) row.classList.add("tl-active");

    const marker = document.createElement("span");
    marker.className   = "tl-marker";
    marker.textContent = slot.is_now ? "\u25BA" : " ";

    const time = document.createElement("span");
    time.className   = "tl-time";
    time.textContent = slot.hhmm;

    row.appendChild(marker);
    row.appendChild(time);

    if (slot.task_name) {
        const task = document.createElement("span");
        task.className   = "tl-task";
        task.textContent = slot.task_name;
        row.appendChild(task);
    }
    return row;
}

async function refreshTimeline() {
    const data = await apiFetch("/timeline");
    if (!data) return;
    const slots      = data.slots || [];
    const activeTask = data.active_task || null;
    const el         = dom.timeline();

    // Find the NOW slot.
    const nowIdx = slots.findIndex(s => s.is_now);
    if (nowIdx < 0) { el.innerHTML = ""; return; }

    // Calculate how many rows fit in the available height, then slice the window
    // so NOW sits at the vertical midpoint - exactly like the TUI's h//2 logic.
    // Use the measured height when available, otherwise fall back to a safe default.
    const availH = el.offsetHeight > 0 ? el.offsetHeight - 8 : 300;  // 8px = 4px top+bottom padding
    const nRows  = Math.max(1, Math.floor(availH / TL_ROW_H));
    const half   = Math.floor(nRows / 2);
    const start  = Math.max(0, nowIdx - half);
    const end    = Math.min(slots.length, start + nRows);
    const visible = slots.slice(start, end);

    el.innerHTML = "";
    for (const slot of visible) {
        el.appendChild(_buildTimelineRow(slot, activeTask));
    }
}

// ====================================================================================================
// MARK: WRAP TOGGLE
// ====================================================================================================

function toggleWrap(bodyId, btnId) {
    const body = $(bodyId);
    const btn  = $(btnId);
    if (!body || !btn) return;
    const nowrapOn = body.classList.toggle(CSS_NOWRAP);
    // Button is lit (wrap-active) when wrapping is ON, dim when nowrap is ON.
    btn.classList.toggle(CSS_WRAP_ACTIVE, !nowrapOn);
    // Scroll to bottom when returning to wrap mode so content is visible.
    if (!nowrapOn) body.scrollTop = body.scrollHeight;
}

// ====================================================================================================
// MARK: LOG STREAM (SSE)
// ====================================================================================================

function _logLineClass(text) {
    if (!text) return "";
    const t = text.trim();
    if (t.startsWith("=") && t.endsWith("=")) return "section";
    if (t.includes("[SCHEDULER]"))             return "sched";
    if (/error|exception|failed/i.test(t))     return "error";
    if (/completed|success/i.test(t))          return "success";
    return "";
}

function appendLogLine(text) {
    const el    = dom.log();
    const shouldStick = _isLogNearBottom();
    const div   = document.createElement("div");
    div.className = "log-line " + _logLineClass(text);
    div.textContent = text;
    el.appendChild(div);
    _logLines.push(div);
    // Trim excess.
    while (_logLines.length > MAX_LOG_LINES) {
        const old = _logLines.shift();
        old.remove();
    }
    if (shouldStick) {
        el.scrollTop = el.scrollHeight;
    }
}

function clearLogLines() {
    _logLines = [];
    dom.log().innerHTML = "";
}

function _displayLogPath(path) {
    if (!path) return "";
    const normalized = path.replace(/\\/g, "/");
    const logsIdx    = normalized.lastIndexOf("/logs/");
    return logsIdx >= 0
        ? "controldata/logs" + normalized.slice(logsIdx + 5)
        : normalized.split("/").slice(-2).join("/");
}

function _isLogNearBottom() {
    const el = dom.log();
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    return remaining <= 12;
}

function _setLogPanelTitle(path) {
    const titleEl = $("log-panel-title");
    if (!titleEl) return;
    const displayPath = _displayLogPath(path);
    titleEl.textContent = displayPath ? "Log: " + displayPath : "Log";
}

function _setChatMessageMeta(wrap, meta) {
    if (!wrap || !meta) return;
    let metaEl = wrap.querySelector(".msg-meta");
    if (!metaEl) {
        metaEl = document.createElement("div");
        metaEl.className = "msg-meta";
        wrap.appendChild(metaEl);
    }
    metaEl.textContent = meta;
}

function startLogStream() {
    if (_logEventSource) _logEventSource.close();
    _currentLogPath = "";
    _logEventSource = new EventSource(API_BASE + "/logs/stream");
    _logEventSource.onmessage = e => {
        try {
            const data = JSON.parse(e.data);
            if (data.path) {
                _currentLogPath = data.path;
                _setLogPanelTitle(data.path);
            }
            if (data.text !== undefined) appendLogLine(data.text);
        } catch { appendLogLine(e.data); }
    };
    _logEventSource.onerror = () => {
        // Reconnect after a short wait.
        setTimeout(startLogStream, 3000);
    };
}

// ----------------------------------------------------------------------------------------------------

function _switchLogStream(path) {
    if (!path) return;
    _currentLogPath = path;
    _setLogPanelTitle(path);

    clearLogLines();
    if (_logEventSource) {
        _logEventSource.close();
        _logEventSource = null;
    }
    _logEventSource = new EventSource(API_BASE + "/logs/file?path=" + encodeURIComponent(path));
    _logEventSource.onmessage = e => {
        try {
            const data = JSON.parse(e.data);
            if (data.path) {
                _currentLogPath = data.path;
                _setLogPanelTitle(data.path);
            }
            if (data.text !== undefined) appendLogLine(data.text);
        } catch { appendLogLine(e.data); }
    };
    _logEventSource.onerror = () => {
        // Let the latest-log poller reopen the active file if this connection drops.
        _currentLogPath = "";
    };
}

async function refreshLatestLogFile() {
    const data = await apiFetch("/logs/latest");
    if (!data || !data.path) return;
    if (data.path === _currentLogPath) return;
    _switchLogStream(data.path);
}

// ====================================================================================================
// MARK: CHAT
// ====================================================================================================

function appendChatMessage(role, text, meta) {
    const el    = dom.chat();
    const wrap  = document.createElement("div");
    wrap.className = "chat-msg " + role;

    const label = document.createElement("div");
    label.className = "msg-role";
    label.textContent = role === "user" ? "You" : "Agent";

    const body  = document.createElement("div");
    body.className = "msg-text";
    body.textContent = text;

    wrap.appendChild(label);
    wrap.appendChild(body);

    if (meta) {
        const m = document.createElement("div");
        m.className = "msg-meta";
        m.textContent = meta;
        wrap.appendChild(m);
    }

    el.appendChild(wrap);
    el.scrollTop = el.scrollHeight;
    return wrap;
}

function appendChatLine(wrap, text) {
    if (!wrap) return;
    const body = wrap.querySelector(".msg-text");
    if (!body) return;
    body.textContent = body.textContent ? body.textContent + "\n" + text : text;
    dom.chat().scrollTop = dom.chat().scrollHeight;
}

function appendThinking(runId) {
    const el   = dom.chat();
    const wrap = document.createElement("div");
    wrap.className = "chat-thinking";
    wrap.setAttribute("data-run-id", runId);
    wrap.textContent = "thinking...";
    el.appendChild(wrap);
    el.scrollTop = el.scrollHeight;
}

function removeThinking(runId) {
    const el = dom.chat().querySelector(".chat-thinking[data-run-id='" + runId + "']");
    if (el) el.remove();
}

// ====================================================================================================
// MARK: RUN STREAM (SSE per prompt)
// ====================================================================================================

function listenRun(runId) {
    // Each run gets its own EventSource so concurrent in-flight requests
    // do not cancel each other.
    const es = new EventSource(API_BASE + "/runs/" + encodeURIComponent(runId) + "/stream");
    const testTurnMessages = new Map();
    let progressWrap = null;

    es.onmessage = e => {
        try {
            const ev = JSON.parse(e.data);
            if (ev.type === "start") {
                appendChatMessage("user", ev.prompt);
                if (ev.prompt && ev.prompt.startsWith("/")) {
                    startLogStream();
                }
                appendThinking(runId);
            } else if (ev.type === "log_file") {
                _switchLogStream(ev.path);
            } else if (ev.type === "test_agent_response") {
                const wrap = appendChatMessage("agent", ev.response, "turn " + ev.turn);
                testTurnMessages.set(String(ev.turn), wrap);
            } else if (ev.type === "test_agent_metrics") {
                const wrap = testTurnMessages.get(String(ev.turn));
                const meta = "turn " + ev.turn + " | " + Number(ev.tokens).toLocaleString() + " ctx" + (ev.tps && ev.tps !== "0" ? " | " + ev.tps + " tok/s" : "");
                if (wrap) {
                    _setChatMessageMeta(wrap, meta);
                } else {
                    appendChatMessage("agent", "[Turn " + ev.turn + " metrics]", meta);
                }
            } else if (ev.type === "test_complete") {
                appendChatMessage("agent", ev.text);
            } else if (ev.type === "progress") {
                if (!progressWrap) {
                    progressWrap = appendChatMessage("agent", ev.text);
                } else {
                    appendChatLine(progressWrap, ev.text);
                }
            } else if (ev.type === "response") {
                removeThinking(runId);
                const meta = ev.tokens ? ev.tokens.toLocaleString() + " ctx" + (ev.tps && ev.tps !== "0" ? " | " + ev.tps + " tok/s" : "") : "";
                appendChatMessage("agent", ev.response, meta);
            } else if (ev.type === "error") {
                removeThinking(runId);
                appendChatMessage("agent", "[Error: " + ev.message + "]");
            } else if (ev.type === "done") {
                removeThinking(runId);
                es.close();
                refreshQueue();
            }
        } catch (err) {
            console.warn("run event parse error", err);
        }
    };

    es.onerror = () => {
        removeThinking(runId);
        es.close();
    };
}

// ====================================================================================================
// MARK: SUBMIT PROMPT
// ====================================================================================================

async function _loadHistory() {
    const data = await apiFetch("/history");
    if (data && Array.isArray(data.entries)) {
        _inputHistory = data.entries;
    }
}

async function _pushHistory(text) {
    // Optimistic local update so Up-arrow works immediately.
    if (_inputHistory[_inputHistory.length - 1] !== text) {
        _inputHistory.push(text);
        if (_inputHistory.length > 20) _inputHistory.shift();
    }
    // Persist to server (fire-and-forget; refresh local list from response).
    const data = await apiFetch("/history", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ text }),
    });
    if (data && Array.isArray(data.entries)) {
        _inputHistory = data.entries;
    }
}

function submitPrompt() {
    const text = dom.input().value.trim();
    if (!text) return;

    // Slash commands run locally and don't need Ollama - always allow.
    // Real prompts are discarded with a message if Ollama is unreachable.
    const isSlash = text.startsWith("/");
    if (!isSlash && !_ollamaReachable) {
        appendChatMessage("agent", "[Ollama is unreachable - prompt discarded]");
        dom.input().value = "";
        return;
    }

    // Clear input and reset history cursor immediately so the user can keep typing.
    dom.input().value = "";
    _historyIdx = -1;

    // Dispatch immediately so the Python queue reflects the real prompt backlog.
    _dispatchPrompt(text);
}

async function _dispatchPrompt(text) {
    const data = await apiFetch("/sessions/" + encodeURIComponent(SESSION_ID) + "/prompt", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ prompt: text }),
    });

    // Persist history without blocking prompt submission into the Python queue.
    _pushHistory(text);

    // Refresh queue immediately so new entry appears without waiting for the poll interval.
    refreshQueue();

    if (!data) {
        appendChatMessage("user", text);
        appendChatMessage("agent", "[Error: could not reach API]");
        return;
    }

    listenRun(data.run_id);
}

// ====================================================================================================
// MARK: KEYBOARD HANDLER
// ====================================================================================================

function onInputKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitPrompt();
        return;
    }
    // CLI-style history navigation.
    if (e.key === "ArrowUp") {
        if (_inputHistory.length === 0) return;
        e.preventDefault();
        if (_historyIdx === -1) {
            // Starting to browse - save any current draft and go to most recent.
            _historyIdx = _inputHistory.length - 1;
        } else if (_historyIdx > 0) {
            _historyIdx--;
        }
        dom.input().value = _inputHistory[_historyIdx];
        // Move cursor to end of restored text.
        const el = dom.input();
        el.setSelectionRange(el.value.length, el.value.length);
        return;
    }
    if (e.key === "ArrowDown") {
        if (_historyIdx === -1) return;
        e.preventDefault();
        if (_historyIdx < _inputHistory.length - 1) {
            _historyIdx++;
            dom.input().value = _inputHistory[_historyIdx];
        } else {
            // Past the end of history - clear and stop browsing.
            _historyIdx = -1;
            dom.input().value = "";
        }
        const el = dom.input();
        el.setSelectionRange(el.value.length, el.value.length);
        return;
    }
}

// ====================================================================================================
// MARK: POLLING INTERVALS
// ====================================================================================================

function startPolling() {
    refreshVersion();
    refreshOllamaStatus();
    refreshQueue();
    refreshTimeline();
    refreshLatestLogFile();

    setInterval(refreshOllamaStatus, POLL_OLLAMA_MS);
    setInterval(refreshQueue,        POLL_QUEUE_MS);
    setInterval(refreshTimeline,     POLL_TIMELINE_MS);
    setInterval(refreshLatestLogFile, POLL_LATEST_LOG_MS);
}

// ====================================================================================================
// MARK: INIT
// ====================================================================================================

function init() {
    // Load persisted input history from the server (shared with TUI).
    _loadHistory();

    // Wire up input events.
    dom.input().addEventListener("keydown", onInputKeydown);
    dom.sendBtn().addEventListener("click", submitPrompt);

    // Recenter the schedule timeline whenever the queue subpanel changes height.
    if (window.ResizeObserver) {
        _queueResizeObserver = new ResizeObserver(() => {
            _scheduleTimelineRefresh();
        });
        _queueResizeObserver.observe(dom.timelineQueue());
    }

    // Redraw timeline on resize so the row window recentres correctly.
    let _resizeTimer = null;
    window.addEventListener("resize", () => {
        clearTimeout(_resizeTimer);
        _resizeTimer = setTimeout(refreshTimeline, 100);
    });

    // Start live log stream.
    startLogStream();

    // Start polling for status, queue, and tasks.
    startPolling();
}

document.addEventListener("DOMContentLoaded", init);
