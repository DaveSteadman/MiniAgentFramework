import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = REPO_ROOT / "code"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from agent_core.skill_executor import execute_tool_call
from agent_core.orchestration import _build_system_message
from agent_core.orchestration import _normalize_tool_request
from agent_core.scratchpad import scratch_clear
from agent_core.scratchpad import scratch_load
from agent_core.scratchpad import scratch_query
from agent_core.scratchpad import scratch_save
from agent_core.skills_catalog_builder import build_tool_definitions
from agent_core.skills_catalog_builder import load_skills_payload
from agent_core.skills.FileAccess.file_access_skill import write_file
from agent_core.skills.WebFetch.web_fetch_skill import fetch_page_text
from agent_core.skills.WebResearch.web_research_skill import research_traverse
from agent_core.skills.SystemInfo.system_info_skill import get_system_info_string


class RegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.skills_payload = load_skills_payload(CODE_DIR / "agent_core" / "skills" / "skills_summary.md")
        scratch_clear()

    def tearDown(self) -> None:
        scratch_clear()

    def test_write_file_writes_system_info_csv(self) -> None:
        output_path = REPO_ROOT / "data" / "test_systemstats_regression.csv"

        if output_path.exists():
            output_path.unlink()

        try:
            result = write_file("test_systemstats_regression.csv", get_system_info_string())
            self.assertEqual(result, "Wrote data/test_systemstats_regression.csv")
            self.assertTrue(output_path.exists())

            content = output_path.read_text(encoding="utf-8")
            self.assertIn("os=", content)
            self.assertIn("python=", content)
        finally:
            if output_path.exists():
                output_path.unlink()

    def test_execute_tool_call_runs_datetime(self) -> None:
        result = execute_tool_call(
            tool_name="get_datetime_data",
            arguments={},
            skills_payload=self.skills_payload,
        )
        self.assertEqual(result["function"], "get_datetime_data")
        self.assertIsNotNone(result["result"])
        self.assertNotIn("error", str(result["result"]).lower())

    def test_build_tool_definitions_has_entries(self) -> None:
        tool_defs = build_tool_definitions(self.skills_payload)
        self.assertGreater(len(tool_defs), 0)
        for tool in tool_defs:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("parameters", tool["function"])
            self.assertEqual(tool["function"]["parameters"]["type"], "object")

    def test_normalize_tool_request_rewrites_assistant_delegate_wrapper(self) -> None:
        func_name, arguments, note = _normalize_tool_request(
            "assistant",
            {
                "name": "delegate",
                "arguments": {
                    "task": "Find the latest advancements in quantum computing and provide a concise summary.",
                    "max_iterations": 3,
                },
            },
        )

        self.assertEqual(func_name, "delegate")
        self.assertIn("prompt", arguments)
        self.assertNotIn("task", arguments)
        self.assertEqual(arguments["prompt"], "Find the latest advancements in quantum computing and provide a concise summary.")
        self.assertEqual(arguments["max_iterations"], 3)
        self.assertIn("assistant(...) -> delegate(...)", note or "")

    def test_fetch_page_text_query_mode_falls_back_to_raw_page_text(self) -> None:
        html_text = "<html><body>unused</body></html>"
        body_text = (
            "# BBC News\n\n"
            "### First headline from the page\n\n"
            "A paragraph with enough words to survive extraction and give the caller usable page content.\n\n"
            "### Second headline from the page\n\n"
            "Another paragraph with enough words to survive extraction and keep the page useful."
        )

        with patch("agent_core.skills.WebFetch.web_fetch_skill._fetch_html", return_value=(html_text, "https://www.bbc.co.uk/news")):
            with patch("agent_core.skills.WebFetch.web_fetch_skill._extract_content", return_value=("BBC News", body_text)):
                with patch("agent_core.skills.WebFetch.web_fetch_skill._get_active_model", return_value="gpt-oss:20b"):
                    with patch("agent_core.skills.WebFetch.web_fetch_skill._get_active_num_ctx", return_value=131072):
                        with patch(
                            "agent_core.skills.WebFetch.web_fetch_skill._call_llm_chat",
                            return_value=SimpleNamespace(response="Not found on this page."),
                        ):
                            result = fetch_page_text(
                                url="https://news.bbc.co.uk",
                                max_words=400,
                                timeout_seconds=30,
                                query="headlines",
                            )

        self.assertIn("# BBC News", result)
        self.assertIn("### First headline from the page", result)
        self.assertIn("### Second headline from the page", result)
        self.assertNotEqual(result.strip(), "Not found on this page.")

    def test_fetch_page_text_query_miss_returns_large_raw_fallback(self) -> None:
        html_text = "<html><body>unused</body></html>"
        long_body = " ".join(f"word{i}" for i in range(3000))

        with patch("agent_core.skills.WebFetch.web_fetch_skill._fetch_html", return_value=(html_text, "https://example.com/stats")):
            with patch("agent_core.skills.WebFetch.web_fetch_skill._extract_content", return_value=("Stats Page", long_body)):
                with patch("agent_core.skills.WebFetch.web_fetch_skill._get_active_model", return_value="gpt-oss:20b"):
                    with patch("agent_core.skills.WebFetch.web_fetch_skill._get_active_num_ctx", return_value=131072):
                        with patch(
                            "agent_core.skills.WebFetch.web_fetch_skill._call_llm_chat",
                            return_value=SimpleNamespace(response="Not found on this page."),
                        ):
                            result = fetch_page_text(
                                url="https://example.com/stats",
                                max_words=400,
                                timeout_seconds=30,
                                query="list all historical winners",
                            )

        body_words = result.split()[3:]
        self.assertEqual(result.split()[0:2], ["#", "Stats"])
        self.assertGreaterEqual(len(body_words), 2500)

    def test_system_prompt_steers_exhaustive_fetches_into_scratchpad(self) -> None:
        system_message = _build_system_message("", None, {"skills": []})

        self.assertIn("complete list, full history, many-year table scan", system_message)
        self.assertIn("auto-saved to the scratchpad", system_message)
        self.assertIn("scratch_query or scratch_peek", system_message)

    def test_system_prompt_steers_research_traverse_to_page_keys(self) -> None:
        system_message = _build_system_message("", None, {"skills": []})

        self.assertIn("page scratch keys", system_message)
        self.assertIn("research_page_*", system_message)
        self.assertIn("instead of scratch_load on the entire combined research bundle", system_message)

    def test_research_traverse_saves_page_level_scratchpad_artifacts(self) -> None:
        search_results = [
            {
                "rank": 1,
                "title": "Example results page",
                "url": "https://example.com/results",
                "snippet": "Detailed results page.",
            }
        ]
        html_text = "<html><body><p>unused</p></body></html>"
        body_text = "Williams won at Imola in 1981 and 1982."

        with patch("agent_core.skills.WebResearch.web_research_skill.search_web", return_value=search_results):
            with patch("agent_core.skills.WebResearch.web_research_skill._fetch_html", return_value=(html_text, "https://example.com/results")):
                with patch("agent_core.skills.WebResearch.web_research_skill._extract_content", return_value=("Example Results", body_text)):
                    with patch("agent_core.skills.WebResearch.web_research_skill._extract_urls_from_html", return_value=[]):
                        with patch("agent_core.skills.WebResearch.web_research_skill._llm_reextract_evidence", return_value=["Williams won at Imola in 1981 and 1982."]):
                            result = research_traverse("Williams Imola wins", max_pages=1, max_search_results=1)

        self.assertEqual(result["visited_count"], 1)
        self.assertEqual(len(result["best_pages"]), 1)
        self.assertEqual(len(result["page_manifest"]), 1)
        scratch_key = result["best_pages"][0]["scratch_key"]
        self.assertEqual(scratch_key, result["page_manifest"][0]["scratch_key"])
        self.assertTrue(scratch_key.startswith("research_page_"))
        saved_page = scratch_load(scratch_key)
        self.assertIn("RESEARCH QUERY: Williams Imola wins", saved_page)
        self.assertIn("TITLE: Example Results", saved_page)
        self.assertIn("URL: https://example.com/results", saved_page)
        self.assertIn("PAGE EXTRACT:", saved_page)
        self.assertIn("Williams won at Imola in 1981 and 1982.", saved_page)
        self.assertIn(f"SCRATCH_KEY: {scratch_key}", result["full_report"])
        self.assertNotIn("EXTRACT:", result["full_report"])

    def test_scratch_query_rejects_exhaustive_answers_from_search_results(self) -> None:
        search_results = (
            "Web search results for: Williams F1 wins at Imola\n\n"
            "[1] Imola - Wins - Stats F1\n"
            "    https://www.statsf1.com/en/circuit-imola/stats-victoire.aspx\n"
            "    Wins, pole positions, fastest laps, podiums, points.\n\n"
            "[2] Williams at Imola - Lights Out\n"
            "    https://www.lightsoutblog.com/f1-team-form-imola/\n"
            "    Williams scored in all of the last six San Marino Grands Prix.\n"
        )
        scratch_save("search_block", search_results)

        with patch("agent_core.ollama_client.call_llm_chat") as llm_call:
            result = scratch_query("search_block", "list all the Williams F1 team wins at Imola")

        self.assertEqual(result, "Not found in content.")
        llm_call.assert_not_called()

    def test_scratch_query_prompt_forbids_outside_knowledge(self) -> None:
        scratch_save("race_rows", "1992 Ayrton Senna\n1993 Ayrton Senna")

        with patch("agent_core.ollama_client.get_active_model", return_value="gpt-oss:20b"):
            with patch("agent_core.ollama_client.get_active_num_ctx", return_value=131072):
                with patch(
                    "agent_core.ollama_client.call_llm_chat",
                    return_value=SimpleNamespace(response="1992 Ayrton Senna\n1993 Ayrton Senna"),
                ) as llm_call:
                    result = scratch_query("race_rows", "list all rows")

        self.assertEqual(result, "1992 Ayrton Senna\n1993 Ayrton Senna")
        system_prompt = llm_call.call_args.kwargs["messages"][0]["content"]
        self.assertIn("never use outside knowledge", system_prompt)
        self.assertIn("Search result snippets, headlines, and summaries are not authoritative", system_prompt)
        self.assertIn("respond with exactly: Not found in content.", system_prompt)

if __name__ == "__main__":
    unittest.main()