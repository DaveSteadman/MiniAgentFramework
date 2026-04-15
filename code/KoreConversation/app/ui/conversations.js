// ====================================================================================================
// KoreConversation Debug UI - conversations.js
// ====================================================================================================
// Fetches data from the KoreConversation REST API (same origin, port 8700) and renders:
//   - Left sidebar: list of all conversations with key metadata
//   - Right pane:   selected conversation's full detail - metadata, background context,
//                   thread summary, scratchpad, messages, and events
//
// No external dependencies. Vanilla JS only.
// ====================================================================================================

"use strict";

// ====================================================================================================
// STATE
// ====================================================================================================

let _selectedId     = null;
let _autoInterval   = null;
let _allConversations = [];
let _dragStartX     = null;
let _dragStartW     = null;

// ====================================================================================================
// INIT
// ====================================================================================================

document.addEventListener("DOMContentLoaded", () => {
    loadStatus();
    loadConversations().then(() => {
        const saved = parseInt(localStorage.getItem("kc_selected_id"), 10);
        if (saved && !isNaN(saved)) { selectConversation(saved); }
    });
    initSplitter();

    document.getElementById("filter-status").addEventListener("change",  applyFilters);
    document.getElementById("filter-channel").addEventListener("change", applyFilters);

    // Start auto-refresh immediately.
    const chk = document.getElementById("chk-auto");
    chk.checked    = true;
    _autoInterval  = setInterval(refreshAll, 5000);
});

// ====================================================================================================
// STATUS
// ====================================================================================================

async function loadStatus() {
    try {
        const r = await fetch("/status");
        if (!r.ok) { throw new Error(`HTTP ${r.status}`); }
        const d = await r.json();

        document.getElementById("status-dot").className   = "dot on";
        document.getElementById("status-label").textContent = "connected";
        document.getElementById("version-chip").textContent = d.version || "";
    } catch {
        document.getElementById("status-dot").className   = "dot off";
        document.getElementById("status-label").textContent = "offline";
    }
}

// ====================================================================================================
// CONVERSATION LIST
// ====================================================================================================

async function loadConversations() {
    try {
        const r = await fetch("/conversations?limit=500");
        if (!r.ok) { throw new Error(`HTTP ${r.status}`); }
        _allConversations = await r.json();
        applyFilters();
    } catch (e) {
        console.error("loadConversations:", e);
    }
    return _allConversations;
}

function applyFilters() {
    const statusFilter  = document.getElementById("filter-status").value;
    const channelFilter = document.getElementById("filter-channel").value;

    const filtered = _allConversations.filter(c => {
        if (statusFilter  && c.status       !== statusFilter)  return false;
        if (channelFilter && c.channel_type !== channelFilter) return false;
        return true;
    });

    renderConvList(filtered);
}

function renderConvList(conversations) {
    const el = document.getElementById("conv-list");
    document.getElementById("conv-count").textContent = conversations.length;

    if (conversations.length === 0) {
        el.innerHTML = "<div style='padding:12px;color:var(--text-dim);font-size:11px;'>No conversations.</div>";
        return;
    }

    // Sort by last_activity_at descending
    const sorted = [...conversations].sort((a, b) =>
        (b.last_activity_at || "").localeCompare(a.last_activity_at || "")
    );

    el.innerHTML = sorted.map(c => {
        const subject  = c.subject || "(no subject)";
        const selected = c.id === _selectedId ? " selected" : "";
        const ts       = formatDateTime(c.last_activity_at);
        return `
<div class="conv-item${selected}" onclick="selectConversation(${c.id})" data-id="${c.id}">
    <div class="conv-item-top">
        <span class="conv-id">#${c.id}</span>
        <span class="conv-subject">${escHtml(subject)}</span>
    </div>
    <div class="conv-item-mid">
        <span class="pill pill-${c.status}">${c.status}</span>
        <span class="pill pill-${c.profile}">${c.profile}</span>
        <span class="pill">${escHtml(c.channel_type)}</span>
    </div>
    <div class="conv-item-bot">${ts}</div>
</div>`;
    }).join("");
}

// ====================================================================================================
// CONVERSATION DETAIL
// ====================================================================================================

async function selectConversation(id) {
    _selectedId = id;
    localStorage.setItem("kc_selected_id", id);

    // Highlight in sidebar
    document.querySelectorAll(".conv-item").forEach(el => {
        el.classList.toggle("selected", parseInt(el.dataset.id) === id);
    });

    document.getElementById("detail-empty").hidden = true;
    document.getElementById("detail").hidden        = false;

    try {
        const [convR, msgsR, evtsR] = await Promise.all([
            fetch(`/conversations/${id}`),
            fetch(`/conversations/${id}/messages?limit=1000`),
            fetch(`/events?conversation_id=${id}&limit=200`),
        ]);

        const conv  = convR.ok  ? await convR.json()  : null;
        const msgs  = msgsR.ok  ? await msgsR.json()  : [];
        const evts  = evtsR.ok  ? await evtsR.json()  : [];

        if (conv) {
            renderMeta(conv);
            renderBackground(conv.background_context || "");
            renderSummary(conv.thread_summary || "");
            renderScratchpad(conv.scratchpad);
        }
        renderMessages(msgs);
        renderEvents(evts);

    } catch (e) {
        console.error("selectConversation:", e);
    }
}

// ====================================================================================================
// META TABLE
// ====================================================================================================

function renderMeta(conv) {
    const rows = [
        ["id",              conv.id],
        ["status",          pill(conv.status,       `pill-${conv.status}`)],
        ["channel_type",    escHtml(conv.channel_type || "-")],
        ["profile",         pill(conv.profile,      `pill-${conv.profile}`)],
        ["subject",         escHtml(conv.subject || "(none)")],
        ["turn_count",      conv.turn_count ?? 0],
        ["token_estimate",  (conv.token_estimate ?? 0).toLocaleString()],
        ["last_activity_at",formatDateTime(conv.last_activity_at)],
        ["created_at",      formatDateTime(conv.created_at)],
        ["updated_at",      formatDateTime(conv.updated_at)],
    ];
    document.getElementById("meta-table").innerHTML =
        rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
}

// ====================================================================================================
// BACKGROUND CONTEXT
// ====================================================================================================

function renderBackground(text) {
    document.getElementById("bg-empty").hidden = text.length > 0;
    document.getElementById("bg-text").textContent = text;
}

// ====================================================================================================
// THREAD SUMMARY
// ====================================================================================================

function renderSummary(text) {
    document.getElementById("summary-empty").hidden = text.length > 0;
    document.getElementById("summary-text").textContent = text;
}

// ====================================================================================================
// SCRATCHPAD
// ====================================================================================================

function renderScratchpad(scratchpad) {
    let data = scratchpad;
    if (typeof data === "string") {
        try { data = JSON.parse(data); } catch { data = {}; }
    }
    data = data || {};
    const keys = Object.keys(data);
    document.getElementById("scratchpad-empty").hidden = keys.length > 0;

    if (keys.length === 0) {
        document.getElementById("scratchpad-table").innerHTML = "";
        return;
    }

    document.getElementById("scratchpad-table").innerHTML = keys.map(k =>
        `<tr><td>${escHtml(k)}</td><td>${escHtml(String(data[k]))}</td></tr>`
    ).join("");
}

// ====================================================================================================
// MESSAGES
// ====================================================================================================

async function reloadMessages() {
    if (_selectedId === null) return;
    try {
        const r    = await fetch(`/conversations/${_selectedId}/messages?limit=1000`);
        const msgs = r.ok ? await r.json() : [];
        renderMessages(msgs);
    } catch (e) {
        console.error("reloadMessages:", e);
    }
}

function renderMessages(msgs) {
    const showSummarised = document.getElementById("chk-summarised").checked;
    const visible        = showSummarised ? msgs : msgs.filter(m => !m.summarised);

    document.getElementById("msg-count").textContent = msgs.length;

    if (visible.length === 0) {
        document.getElementById("messages-body").innerHTML =
            "<div style='padding:10px;color:var(--text-dim);font-size:11px;'>No messages.</div>";
        return;
    }

    document.getElementById("messages-body").innerHTML = visible.map(m => {
        const summarisedClass = m.summarised ? " summarised-row" : "";
        const ts = formatDateTime(m.created_at);
        return `
<div class="msg-row${summarisedClass}">
    <span class="msg-id">#${m.id}</span>
    <span>
        ${pill(m.direction, `pill-${m.direction}`)}
    </span>
    <span class="msg-content">${escHtml(m.content)}</span>
    <span class="msg-time">${ts}</span>
    <span class="msg-flags">
        ${pill(m.status)}
        ${m.summarised ? '<span class="pill" style="color:var(--text-dim)">summ</span>' : ""}
    </span>
</div>`;
    }).join("");
}

// ====================================================================================================
// EVENTS
// ====================================================================================================

function renderEvents(evts) {
    document.getElementById("evt-count").textContent = evts.length;

    if (evts.length === 0) {
        document.getElementById("events-body").innerHTML =
            "<div style='padding:10px;color:var(--text-dim);font-size:11px;'>No events.</div>";
        return;
    }

    const hdr = `
<table class="evt-table">
<thead>
<tr>
    <th>#</th>
    <th>type</th>
    <th>status</th>
    <th>priority</th>
    <th>claimed_by</th>
    <th>created_at</th>
    <th>completed_at</th>
    <th>payload</th>
</tr>
</thead>
<tbody>
`;
    const rows = evts.map(e => {
        let payload = "";
        try {
            const p = typeof e.payload === "string" ? JSON.parse(e.payload) : e.payload;
            if (p && Object.keys(p).length > 0) {
                payload = escHtml(JSON.stringify(p, null, 2));
            }
        } catch { /* ignore */ }
        return `
<tr>
    <td class="mono">${e.id}</td>
    <td>${escHtml(e.event_type)}</td>
    <td>${pill(e.status, `pill-${e.status}`)}</td>
    <td>${e.priority ?? 0}</td>
    <td style="color:var(--text-dim);font-size:10px;">${escHtml(e.claimed_by || "-")}</td>
    <td style="color:var(--text-dim);font-size:10px;white-space:nowrap;">${formatDateTime(e.created_at)}</td>
    <td style="color:var(--text-dim);font-size:10px;white-space:nowrap;">${formatDateTime(e.completed_at)}</td>
    <td><pre style="font-size:10px;color:var(--text-dim);white-space:pre-wrap;">${payload}</pre></td>
</tr>`;
    }).join("");

    document.getElementById("events-body").innerHTML = hdr + rows + "</tbody></table>";
}

// ====================================================================================================
// REFRESH
// ====================================================================================================

async function refreshAll() {
    await loadStatus();
    await loadConversations();
    if (_selectedId !== null) {
        await selectConversation(_selectedId);
    }
}

function toggleAuto() {
    const on = document.getElementById("chk-auto").checked;
    if (on) {
        _autoInterval = setInterval(refreshAll, 5000);
    } else {
        clearInterval(_autoInterval);
        _autoInterval = null;
    }
}

// ====================================================================================================
// DRAG SPLITTER
// ====================================================================================================

function initSplitter() {
    const splitter = document.getElementById("splitter");
    const sidebar  = document.getElementById("sidebar");
    const grid     = document.getElementById("main-grid");

    splitter.addEventListener("mousedown", e => {
        _dragStartX = e.clientX;
        _dragStartW = sidebar.getBoundingClientRect().width;
        document.body.style.userSelect = "none";
        document.body.style.cursor     = "col-resize";
    });

    document.addEventListener("mousemove", e => {
        if (_dragStartX === null) return;
        const delta = e.clientX - _dragStartX;
        const newW  = Math.max(160, Math.min(600, _dragStartW + delta));
        grid.style.gridTemplateColumns = `${newW}px 4px 1fr`;
        document.documentElement.style.setProperty("--sidebar-w", `${newW}px`);
    });

    document.addEventListener("mouseup", () => {
        if (_dragStartX === null) return;
        _dragStartX = null;
        _dragStartW = null;
        document.body.style.userSelect = "";
        document.body.style.cursor     = "";
    });
}

// ====================================================================================================
// HELPERS
// ====================================================================================================

function escHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function pill(text, cls) {
    return `<span class="pill ${cls || ""}">${escHtml(text)}</span>`;
}

function formatDateTime(iso) {
    if (!iso) return "-";
    try {
        const d    = new Date(iso);
        const date = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
        const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        return `${date} ${time}`;
    } catch {
        return iso;
    }
}
