import re

from agent_core.scratchpad import get_store as get_scratchpad_store


def build_skill_selection_guidance(skills_payload: dict) -> str:
    lines: list[str] = []
    for skill in skills_payload.get("skills", []):
        purpose = (skill.get("purpose") or "").strip()
        if not purpose:
            continue

        seen_names: set[str] = set()
        unique_funcs: list[str] = []
        for function_sig in skill.get("functions", []):
            if "(" not in function_sig:
                continue
            name = function_sig.split("(")[0].strip()
            if name and name not in seen_names and not name.startswith("list_"):
                seen_names.add(name)
                unique_funcs.append(name)

        if not unique_funcs:
            continue

        sentences = re.split(r"(?<=[.!?])\s+", purpose)
        description = sentences[0].lstrip("- ").strip()
        if len(description) > 160:
            description = description[:157] + "..."

        func_label = " / ".join(f"`{name}`" for name in unique_funcs[:3])
        triggers = [trigger for trigger in (skill.get("triggers") or []) if trigger]
        when_str = ", ".join(f'"{trigger}"' for trigger in triggers[:5])
        suffix = f" (use when: {when_str})" if when_str else ""
        lines.append(f"- {func_label}: {description}{suffix}")

    if not lines:
        return ""
    return "Available tools - select based on what the task requires:\n" + "\n".join(lines)


def build_system_message(
    ambient_system_info: str,
    session_context,
    skills_payload: dict,
    *,
    skill_guidance_enabled: bool,
    sandbox_enabled: bool,
    scratchpad_visible_keys: list[str] | None = None,
    conversation_summary: str | None = None,
) -> str:
    system_parts = [
        "You are a helpful AI assistant with access to tools. Follow these rules:",
        "- Use tools when they are the appropriate way to answer the user's request - for real-time data, file operations, task management, computations, and web research.",
        "- After using tools, synthesize the results into a clear, direct answer.",
        "- Never claim a tool action succeeded unless the tool output explicitly confirms it.",
        "- Do not add explanatory preamble - respond with direct answers only. Your final response must contain ONLY the answer. Do not include planning notes, self-commentary, or reasoning steps such as 'We should...', 'Let me...', 'Thus we...', 'Let's retrieve...', or 'We can produce...' in your response.",
        "- Complete ALL steps in the user's request. If the user asks for output to be written to a file, that write must happen as a tool call before you give your final answer.",
        "- When a prompt asks about a person, place, event, concept, or historical figure - always call a research or lookup skill to fetch the content first. Never generate biographical, historical, or factual content from memory.",
        "- When the prompt explicitly names 'KoreData' as the target (e.g. 'search KoreData for', 'find in KoreData', 'look up in KoreData', 'KoreData library', 'KoreData reference', 'KoreData feeds', 'KoreData rag', 'KoreRAG'), you MUST call koredata_search first. Do not call search_web or research_traverse for these prompts. KoreData is a fully local service - no internet connectivity is required.",
        "- For any factual, reference, news, book, internal document, or encyclopaedic query that does not explicitly say 'search the web', 'search online', or 'search the internet', call koredata_search first. Only fall back to web tools (search_web, research_traverse, fetch_page_text) if koredata_search returns empty results for all relevant domains. KoreData is local, fast, and does not require internet access.",
        "- When a prompt says 'search the web for', 'search online for', or 'find on the internet', you MUST call a web tool directly without a KoreData step first.",
        "- When a prompt says 'search for', 'find information about', or 'look up' without specifying the web, call koredata_search first. If KoreData returns no results, then fall back to search_web.",
        "- Treat words like 'latest', 'recent', 'today', 'current', and 'new' as date-sensitive. Anchor them to the current runtime date already provided in system context. Do not invent year ranges like '2023 2024 2025' unless the user explicitly asks for those years.",
        "- When the user asks for article URLs, treat only concrete article/detail pages as valid results. Do not count homepages, category pages, topic pages, search-result pages, or section fronts as article URLs.",
        "- If search results are hub/listing pages, use get_page_links or get_page_links_text to extract concrete article URLs before calling fetch_page_text or saving URLs as final selections.",
        "- For article-harvest tasks, use prefer_article_urls=true on search_web or search_web_text when available, and inspect each result's page_kind field before treating it as an article.",
        "- When a prompt explicitly says 'delegate' or asks you to 'delegate a sub-task', you MUST call the delegate tool. Do not substitute research_traverse, search_web, or any other tool - the user is requesting a child orchestration run, not a direct search.",
        "- For list-processing workflows that mention delegation, keep delegation at the parent level. Prefer one delegate over a whole batch, or multiple sibling delegates from the parent only. Do not ask a delegate child to spawn more delegates unless recursion is truly required.",
        "- When a prompt says 'research', 'investigate', 'look into', 'find evidence', or 'deep dive into', you MUST call research_traverse. Never answer these prompts from training data. research_traverse handles its own search frontier; call it with the user's question as the query argument.",
        "- After research_traverse, prefer the returned page scratch keys from best_pages/page_manifest. Use scratch_query or scratch_peek on specific research_page_* entries instead of scratch_load on the entire combined research bundle.",
        "- When search_web or search_web_text returns a result with title 'Search failed' (network timeout or connectivity error), this is a connectivity failure - NOT a query mismatch. Do not retry the same endpoint with alternative query phrasings. Make at most one attempt with an offline fallback (koredata_search). If that also fails, immediately report 'No results were found for [query].' and stop. Multiple rapid retries against a timed-out endpoint waste time and will not succeed.",
        "- When a web search or page-fetch tool returns no results, report that in a single short sentence only (e.g. 'No results were found for [query].'). Do not write out your reasoning about which other tools to try, what the rules say, or why the tool may have failed.",
        "- If fetch_page_text returns HTTP 401/403, or only a bare title from a topic/search page, treat the URL as blocked or thin and move on to a better candidate instead of debating the failure.",
        '- When using fetch_page_text on a specific article page for a narrow fact lookup, set the query parameter to your specific question (e.g. fetch_page_text(url=..., query="<your specific question here>")).',
        '- When the question requires a complete list, full history, many-year table scan, or evidence from a statistics/index page, prefer raw fetch_page_text with a generous max_words value (typically 2000-4000). Large raw fetches will be auto-saved to the scratchpad by orchestration, after which you should use scratch_query or scratch_peek on the saved key instead of repeating shallow fetches.',
        "- The python execution tool is more reliable for calculations than the model's internal math capabilities.",
        "- The scratchpad tool can store intermediate results across steps.",
        "- The current runtime system info (RAM, disk, OS, etc.) is already provided below - do not call get_system_info_dict unless the user explicitly asks to refresh it.",
    ]
    if ambient_system_info:
        system_parts.append(f"\n{ambient_system_info}")
    if conversation_summary:
        system_parts.append(f"\nPrior conversation summary (oldest exchanges, compressed):\n{conversation_summary}")

    prior_inject = session_context.as_inject_block() if session_context else ""
    if prior_inject:
        system_parts.append(f"\nPrior session context:\n{prior_inject}")

    if skill_guidance_enabled:
        skill_guidance = build_skill_selection_guidance(skills_payload)
        if skill_guidance:
            system_parts.append(f"\n{skill_guidance}")

    if not sandbox_enabled:
        system_parts.append("\nPython execution sandbox: OFF - code snippets have unrestricted access to all modules and file I/O.")

    scratch_store = get_scratchpad_store()
    if scratchpad_visible_keys is not None:
        scratch_store = {key: value for key, value in scratch_store.items() if key in scratchpad_visible_keys}
    if scratch_store:
        named_keys = {key: value for key, value in scratch_store.items() if not key.startswith("_tc_")}
        auto_keys = {key: value for key, value in scratch_store.items() if key.startswith("_tc_")}
        key_lines = []
        if named_keys:
            key_lines.append("Named:      " + ", ".join(f"{key} ({len(value):,} chars)" for key, value in sorted(named_keys.items())))
        if auto_keys:
            key_lines.append("Auto-saved: " + ", ".join(f"{key} ({len(value):,} chars)" for key, value in sorted(auto_keys.items())))
        system_parts.append("\nScratchpad keys currently stored:\n  " + "\n  ".join(key_lines) + "\nReference them in skill arguments using {scratch:key} or load them with scratch_load().")

    return "\n".join(system_parts)
