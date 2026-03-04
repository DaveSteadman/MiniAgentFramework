# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ollama_client import is_ollama_running
from ollama_client import resolve_model_name


# ====================================================================================================
# MARK: TESTS
# ====================================================================================================
class TestResolveModelName(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_exact_match_returns_model(self):
        available = ["gpt-oss:20b", "gpt-oss:120b"]
        result    = resolve_model_name("gpt-oss:20b", available)
        self.assertEqual(result, "gpt-oss:20b")

    # ----------------------------------------------------------------------------------------------------
    def test_exact_match_case_insensitive(self):
        available = ["GPT-OSS:20B"]
        result    = resolve_model_name("gpt-oss:20b", available)
        self.assertEqual(result, "GPT-OSS:20B")

    # ----------------------------------------------------------------------------------------------------
    def test_prefix_match_unique(self):
        # "20b" should resolve to a model that starts with "20b:"
        available = ["20b:latest"]
        result    = resolve_model_name("20b", available)
        self.assertEqual(result, "20b:latest")

    # ----------------------------------------------------------------------------------------------------
    def test_suffix_match_unique(self):
        # "20b" should resolve to a model that ends with ":20b"
        available = ["gpt-oss:20b"]
        result    = resolve_model_name("20b", available)
        self.assertEqual(result, "gpt-oss:20b")

    # ----------------------------------------------------------------------------------------------------
    def test_token_match_unique(self):
        available = ["myorg:20b-instruct"]
        result    = resolve_model_name("20b", available)
        self.assertEqual(result, "myorg:20b-instruct")

    # ----------------------------------------------------------------------------------------------------
    def test_ambiguous_suffix_returns_none(self):
        available = ["gpt-oss:20b", "llama:20b"]
        result    = resolve_model_name("20b", available)
        self.assertIsNone(result)

    # ----------------------------------------------------------------------------------------------------
    def test_no_match_returns_none(self):
        available = ["llama3:8b", "mistral:7b"]
        result    = resolve_model_name("20b", available)
        self.assertIsNone(result)

    # ----------------------------------------------------------------------------------------------------
    def test_empty_requested_returns_none(self):
        available = ["gpt-oss:20b"]
        result    = resolve_model_name("", available)
        self.assertIsNone(result)

    # ----------------------------------------------------------------------------------------------------
    def test_empty_available_returns_none(self):
        result = resolve_model_name("20b", [])
        self.assertIsNone(result)


# ====================================================================================================
# MARK: IS OLLAMA RUNNING
# ====================================================================================================
class TestIsOllamaRunning(unittest.TestCase):
    # ----------------------------------------------------------------------------------------------------
    def test_returns_false_when_server_unreachable(self):
        # Port 1 is reserved and should always refuse connections.
        result = is_ollama_running(host="http://127.0.0.1:1")
        self.assertFalse(result)

    # ----------------------------------------------------------------------------------------------------
    def test_returns_true_when_server_responds(self):
        mock_response = {"models": [{"model": "gpt-oss:20b"}]}
        with patch("ollama_client._request_json", return_value=mock_response):
            result = is_ollama_running(host="http://localhost:11434")
        self.assertTrue(result)


# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
