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
let _logLive              = true;   // when false, refreshLatestLogFile() is suppressed
let _logScrollGuard       = false;  // true while a programmatic file load is settling
let _onLatestFile         = true;   // true only when the newest log file is showing

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
    dom.versionChip().textContent = data.version;
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
// MARK: PANEL SPLITTERS
// ====================================================================================================
// Sizes are stored as fractions [0..1] of available track space in localStorage.
// On drag, pixel values are computed from the current container size and applied to
// grid-template-columns / grid-template-rows.  On window resize the stored fractions
// are reapplied so ratios are preserved.
//
// Grid column layout (indices 0-4):  timeline | spl-v1 | log | spl-v2 | chat
// Grid row layout (indices 0-2):     panels   | spl-h1 | input
// Splitter tracks are fixed at 5px - only the panel tracks are sized by fractions.

const SPLITTER_KEY     = "maf_layout_v1";
const SPLITTER_V_PX    = 5;   // width of each vertical splitter track
const SPLITTER_H_PX    = 5;   // height of the horizontal splitter track
const TIMELINE_MIN_PX  = 120;
const INPUT_MIN_PX     = 60;
const COL_MIN_PX       = 80;

const DEFAULT_FRACS = {
    // Column fractions for [timeline, log, chat] - must sum to 1.0
    cols: [0.16, 0.42, 0.42],
    // Row fractions for [panels, input] - must sum to 1.0
    rows: [0.82, 0.18],
};

// ----------------------------------------------------------------------------------------------------

function _loadLayoutFracs() {
    try {
        const raw = localStorage.getItem(SPLITTER_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (parsed.cols && parsed.rows) return parsed;
        }
    } catch (_) { /* ignore */ }
    return null;
}

function _saveLayoutFracs(fracs) {
    try { localStorage.setItem(SPLITTER_KEY, JSON.stringify(fracs)); } catch (_) { /* ignore */ }
}

function _getCurrentFracs() {
    return _loadLayoutFracs() || DEFAULT_FRACS;
}

// ----------------------------------------------------------------------------------------------------

function _applyGrid(fracs) {
    const grid   = $("main-grid");
    if (!grid) return;

    // Available width = container width minus two splitter tracks and padding.
    const totalW = grid.clientWidth;
    const padH   = 2 * parseFloat(getComputedStyle(grid).paddingLeft || "8");
    const availW = totalW - padH - 2 * SPLITTER_V_PX;

    const [cTl, cLog, cChat] = fracs.cols;
    const tlPx   = Math.max(TIMELINE_MIN_PX, Math.round(cTl  * availW));
    const logPx  = Math.max(COL_MIN_PX,      Math.round(cLog * availW));
    // chat gets the remainder so tracks always fill exactly
    const chatPx = Math.max(COL_MIN_PX,      availW - tlPx - logPx);

    const totalH = grid.clientHeight;
    const padV   = 2 * parseFloat(getComputedStyle(grid).paddingTop || "8");
    const availH = totalH - padV - SPLITTER_H_PX;

    const [rPanel, rInput] = fracs.rows;
    const inputPx  = Math.max(INPUT_MIN_PX, Math.round(rInput * availH));
    const panelsPx = Math.max(COL_MIN_PX,   availH - inputPx);

    grid.style.gridTemplateColumns = `${tlPx}px ${SPLITTER_V_PX}px ${logPx}px ${SPLITTER_V_PX}px ${chatPx}px`;
    grid.style.gridTemplateRows    = `${panelsPx}px ${SPLITTER_H_PX}px ${inputPx}px`;
}

// ----------------------------------------------------------------------------------------------------

function _fracFromPx(px, availPx, minPx) {
    return Math.max(minPx / availPx, Math.min(1.0, px / availPx));
}

function _initSplitterDrag(splitterId, axis) {
    // axis: "v" for vertical (resizes columns), "h" for horizontal (resizes rows).
    const el = $(splitterId);
    if (!el) return;

    el.addEventListener("mousedown", e => {
        e.preventDefault();
        const grid   = $("main-grid");
        const fracs  = _getCurrentFracs();
        const startX = e.clientX;
        const startY = e.clientY;
        el.classList.add("dragging");
        document.body.classList.add(axis === "h" ? "splitter-drag-h" : "splitter-drag");

        // Snapshot current pixel sizes from the computed style at drag start.
        const cs   = getComputedStyle(grid);
        const cols  = cs.gridTemplateColumns.split(" ").map(parseFloat);
        const rows  = cs.gridTemplateRows.split(" ").map(parseFloat);
        // cols: [tl, spl, log, spl, chat]   rows: [panels, spl, input]
        const startTl   = cols[0] || 200;
        const startLog  = cols[2] || 400;
        const startChat = cols[4] || 400;
        const startPanels = rows[0] || 500;
        const startInput  = rows[2] || 120;
        const padH = 2 * parseFloat(getComputedStyle(grid).paddingLeft || "8");
        const padV = 2 * parseFloat(getComputedStyle(grid).paddingTop  || "8");
        const availW = grid.clientWidth  - padH - 2 * SPLITTER_V_PX;
        const availH = grid.clientHeight - padV - SPLITTER_H_PX;

        function onMove(me) {
            const dx = me.clientX - startX;
            const dy = me.clientY - startY;
            const updated = { cols: [...fracs.cols], rows: [...fracs.rows] };

            if (axis === "v1") {
                // Drag between timeline and log.
                const newTl  = Math.max(TIMELINE_MIN_PX, startTl  + dx);
                const newLog = Math.max(COL_MIN_PX,      startLog  - dx);
                updated.cols = [
                    _fracFromPx(newTl,  availW, TIMELINE_MIN_PX),
                    _fracFromPx(newLog, availW, COL_MIN_PX),
                    _fracFromPx(startChat, availW, COL_MIN_PX),
                ];
            } else if (axis === "v2") {
                // Drag between log and chat.
                const newLog  = Math.max(COL_MIN_PX, startLog  + dx);
                const newChat = Math.max(COL_MIN_PX, startChat - dx);
                updated.cols = [
                    _fracFromPx(startTl,  availW, TIMELINE_MIN_PX),
                    _fracFromPx(newLog,   availW, COL_MIN_PX),
                    _fracFromPx(newChat,  availW, COL_MIN_PX),
                ];
            } else if (axis === "h") {
                // Drag between panels row and input row.
                const newPanels = Math.max(COL_MIN_PX,   startPanels + dy);
                const newInput  = Math.max(INPUT_MIN_PX, startInput  - dy);
                updated.rows = [
                    _fracFromPx(newPanels, availH, COL_MIN_PX),
                    _fracFromPx(newInput,  availH, INPUT_MIN_PX),
                ];
            }

            _saveLayoutFracs(updated);
            _applyGrid(updated);
        }

        function onUp() {
            el.classList.remove("dragging");
            document.body.classList.remove("splitter-drag", "splitter-drag-h");
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup",   onUp);
            refreshTimeline();
        }

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup",   onUp);
    });
}

// ----------------------------------------------------------------------------------------------------

function resetLayout() {
    localStorage.removeItem(SPLITTER_KEY);
    _applyGrid(DEFAULT_FRACS);
    refreshTimeline();
}

function initSplitters() {
    _initSplitterDrag("splitter-v1", "v1");
    _initSplitterDrag("splitter-v2", "v2");
    _initSplitterDrag("splitter-h1", "h");

    // Apply stored or default layout immediately.
    _applyGrid(_getCurrentFracs());

    // Reapply on window resize to preserve ratios.
    window.addEventListener("resize", () => {
        _applyGrid(_getCurrentFracs());
    });
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

let _prevLogWasSep = false;

function _logLineClass(text) {
    if (!text) return "";
    const t = text.trim();
    if (t.startsWith("=") && t.endsWith("=")) return "log-sep";
    if (_prevLogWasSep) {
        if (/^TOOL ROUND\s+\d+/i.test(t))  return "log-tool-round";
        return "log-title";
    }
    if (t.startsWith("[progress]"))            return "log-progress";
    if (t.startsWith("[thinking]") || t.startsWith("[/thinking]")) return "log-thinking";
    if (t.includes("[SCHEDULER]"))             return "sched";
    if (/error|exception|failed/i.test(t))     return "error";
    if (/completed|success/i.test(t))          return "success";
    return "";
}

function appendLogLine(text) {
    const el    = dom.log();
    const shouldStick = _isLogNearBottom();
    const div   = document.createElement("div");
    const t     = text ? text.trim() : "";
    div.className = "log-line " + _logLineClass(text);
    _prevLogWasSep = (t.startsWith("=") && t.endsWith("="));
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
    _prevLogWasSep = false;
    dom.log().innerHTML = "";
}

function _displayLogPath(path) {
    if (!path) return "";
    const normalized = path.replace(/\\/g, "/");
    return normalized.split("/").pop();
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

    // Suppress the scroll listener while we load new content.
    _logScrollGuard = true;
    clearTimeout(_switchLogStream._guardTimer);
    _switchLogStream._guardTimer = setTimeout(() => { _logScrollGuard = false; }, 800);

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
    if (!_logLive) return;
    const data = await apiFetch("/logs/latest");
    if (!data || !data.path) return;
    if (data.path === _currentLogPath) return;
    _switchLogStream(data.path);
}

// ----------------------------------------------------------------------------------------------------

function _setLiveBtn(on) {
    const btn = $("log-btn-live");
    if (!btn) return;
    btn.classList.toggle(CSS_WRAP_ACTIVE, on);
}

function toggleLogLive() {
    _logLive = !_logLive;
    _setLiveBtn(_logLive);
    if (_logLive) {
        // Snap back to latest file and resume auto-scroll.
        _onLatestFile = true;
        refreshLatestLogFile();
        const el = dom.log();
        el.scrollTop = el.scrollHeight;
    }
}

// ----------------------------------------------------------------------------------------------------

async function logNavStep(delta) {
    // delta: -1 = older (up), +1 = newer (down).
    const data = await apiFetch("/logs");
    if (!data || !data.log_dirs) return;

    // Flatten all files into a single chronological list (oldest first).
    const allFiles = [];
    const dirs = data.log_dirs.slice().reverse();   // /logs returns newest-first; reverse to oldest-first
    for (const d of dirs) {
        const files = d.files.slice().reverse();    // files also newest-first within a dir
        for (const f of files) {
            allFiles.push(d.date + "/" + f);
        }
    }

    // Find current position by matching the tail of _currentLogPath.
    const curTail = _currentLogPath.replace(/\\/g, "/").split("/logs/").pop() || "";
    let idx = allFiles.findIndex(p => p === curTail);
    if (idx < 0) idx = allFiles.length - 1;  // default to newest if unknown

    const next = allFiles[idx + delta];
    if (!next) return;  // already at boundary

    _onLatestFile = (idx + delta === allFiles.length - 1);

    // Navigating away from live stream - pause live mode.
    if (_logLive) {
        _logLive = false;
        _setLiveBtn(false);
    }

    const logsDir = _currentLogPath.replace(/\\/g, "/").split("/logs/")[0] + "/logs/";
    _switchLogStream(logsDir + next);
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
                // Only follow the new log file if live mode is active.
                if (_logLive) {
                    _switchLogStream(ev.path);
                }
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
    // Initialise drag-resize splitters and apply stored layout.
    initSplitters();

    // Load persisted input history from the server (shared with TUI).
    _loadHistory();

    // Wire up input events.
    dom.input().addEventListener("keydown", onInputKeydown);
    dom.sendBtn().addEventListener("click", submitPrompt);

    // Scroll controls live mode: up pauses it, bottom of active file re-engages it.
    dom.log().addEventListener("scroll", () => {
        if (_logScrollGuard) return;
        if (_isLogNearBottom()) {
            if (!_logLive && _onLatestFile) {
                _logLive = true;
                _setLiveBtn(true);
            }
        } else {
            if (_logLive) {
                _logLive = false;
                _setLiveBtn(false);
            }
        }
    });

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
