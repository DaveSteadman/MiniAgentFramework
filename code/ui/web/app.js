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
const MAX_LOG_LINES     = 500;
const MAX_CHAT_MESSAGES = 200;

// ====================================================================================================
// MARK: STATE
// ====================================================================================================
let _logLines    = [];
let _activeRunId  = null;
let _runEventSource = null;
let _logEventSource = null;
let _inputHistory = [];      // loaded from server on init, mirrors chathistory.json
let _historyIdx   = -1;      // -1 = not browsing history

// ====================================================================================================
// MARK: DOM REFS
// ====================================================================================================
const $ = id => document.getElementById(id);

const dom = {
    ollamaDot:    () => $("ollama-dot"),
    ollamaHost:   () => $("ollama-host"),
    ollamaModel:  () => $("ollama-model"),
    ollamaCtx:    () => $("ollama-ctx"),
    queueBadge:   () => $("queue-badge-count"),
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
    dom.ollamaModel().textContent = modelName  || (rows.length === 0 ? "no model loaded" : "");
    dom.ollamaCtx().textContent   = ctxVal;
    dom.ollamaDot().className = "on";
}

// ====================================================================================================
// MARK: QUEUE STATUS
// ====================================================================================================

async function refreshQueue() {
    const data = await apiFetch("/queue");
    if (!data) return;
    const pending = (data.pending || []).length;
    const active  = data.active ? 1 : 0;
    const total   = pending + active;
    const badge   = dom.queueBadge();
    badge.textContent = total;
    badge.classList.toggle("visible", total > 0);
    _renderTimelineQueue(data);
}

function _renderTimelineQueue(queueData) {
    const el      = dom.timelineQueue();
    if (!el) return;
    const active  = queueData.active;
    const pending = queueData.pending || [];
    el.innerHTML  = "";
    if (!active && pending.length === 0) return;

    const sep = document.createElement("div");
    sep.className   = "tl-sep";
    sep.textContent = "Queue";
    el.appendChild(sep);

    if (active) {
        const row = document.createElement("div");
        row.className   = "tl-q-active";
        row.textContent = "\u25B6 " + (active.name || "?");
        el.appendChild(row);
    }
    for (const item of pending) {
        const row = document.createElement("div");
        row.className   = "tl-q-pending";
        row.textContent = "  \u00B7 " + (item.name || "?");
        el.appendChild(row);
    }
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
    const nowrapOn = body.classList.toggle("nowrap");
    // Button is lit (wrap-active) when wrapping is ON, dim when nowrap is ON.
    btn.classList.toggle("wrap-active", !nowrapOn);
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
    el.scrollTop = el.scrollHeight;
}

function startLogStream() {
    if (_logEventSource) _logEventSource.close();
    _logEventSource = new EventSource(API_BASE + "/logs/stream");
    _logEventSource.onmessage = e => {
        try {
            const data = JSON.parse(e.data);
            if (data.text !== undefined) appendLogLine(data.text);
        } catch { appendLogLine(e.data); }
    };
    _logEventSource.onerror = () => {
        // Reconnect after a short wait.
        setTimeout(startLogStream, 3000);
    };
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

function appendThinking() {
    const el   = dom.chat();
    const wrap = document.createElement("div");
    wrap.className = "chat-thinking";
    wrap.id        = "thinking-indicator";
    wrap.textContent = "thinking...";
    el.appendChild(wrap);
    el.scrollTop = el.scrollHeight;
    return wrap;
}

function removeThinking() {
    const el = $("thinking-indicator");
    if (el) el.remove();
}

// ====================================================================================================
// MARK: RUN STREAM (SSE per prompt)
// ====================================================================================================

function listenRun(runId) {
    if (_runEventSource) _runEventSource.close();
    _runEventSource = new EventSource(API_BASE + "/runs/" + encodeURIComponent(runId) + "/stream");

    _runEventSource.onmessage = e => {
        try {
            const ev = JSON.parse(e.data);
            if (ev.type === "start") {
                appendThinking();
            } else if (ev.type === "response") {
                removeThinking();
                const meta = ev.tokens ? ev.tokens.toLocaleString() + " ctx" + (ev.tps && ev.tps !== "0" ? " | " + ev.tps + " tok/s" : "") : "";
                appendChatMessage("agent", ev.response, meta);
                setInputEnabled(true);
            } else if (ev.type === "error") {
                removeThinking();
                appendChatMessage("agent", "[Error: " + ev.message + "]");
                setInputEnabled(true);
            } else if (ev.type === "done") {
                _runEventSource.close();
                _runEventSource = null;
                _activeRunId    = null;
                setInputEnabled(true);
            }
        } catch (err) {
            console.warn("run event parse error", err);
        }
    };

    _runEventSource.onerror = () => {
        removeThinking();
        _runEventSource.close();
        _runEventSource = null;
        _activeRunId    = null;
        setInputEnabled(true);
    };
}

// ====================================================================================================
// MARK: SUBMIT PROMPT
// ====================================================================================================

function setInputEnabled(enabled) {
    dom.input().disabled  = !enabled;
    dom.sendBtn().disabled = !enabled;
}

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

async function submitPrompt() {
    const text = dom.input().value.trim();
    if (!text) return;
    dom.input().value = "";
    _pushHistory(text);
    _historyIdx = -1;  // reset browsing position after submit
    // Input stays enabled - user can queue further prompts while one is in flight.

    appendChatMessage("user", text);

    const data = await apiFetch("/sessions/" + encodeURIComponent(SESSION_ID) + "/prompt", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ prompt: text }),
    });

    if (!data) {
        appendChatMessage("agent", "[Error: could not reach API]");
        return;
    }

    _activeRunId = data.run_id;
    listenRun(_activeRunId);
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
    refreshOllamaStatus();
    refreshQueue();
    refreshTimeline();

    setInterval(refreshOllamaStatus, POLL_OLLAMA_MS);
    setInterval(refreshQueue,        POLL_QUEUE_MS);
    setInterval(refreshTimeline,     POLL_TIMELINE_MS);
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

    // Start live log stream.
    startLogStream();

    // Start polling for status, queue, and tasks.
    startPolling();
}

document.addEventListener("DOMContentLoaded", init);
