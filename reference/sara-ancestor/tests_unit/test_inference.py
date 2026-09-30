import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from tools.inference import ModelInference
from tools.llm_providers import (
    ALPINE_BASE_URL,
    AnthropicProvider,
    OpenAIProvider,
    SwissGPTProvider,
    get_provider,
)

PROMPTS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "prompts", "prompts_abstract.json"
)


def make_openai_mock(content: str):
    """Build a mock openai.OpenAI client returning a chat completion with `content`."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = content
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.chat.completions.create.return_value = mock_response
    return mock_client_cls


class TestModelInferenceBackwardCompat(unittest.TestCase):
    """The existing DHEM_abstract.py call site omits `provider` and must keep
    targeting OpenAI by default."""

    def test_default_provider_is_openai(self):
        with patch("openai.OpenAI", make_openai_mock("irrelevant")):
            inference = ModelInference(
                prompts_path=PROMPTS_PATH,
                dataset=["abstract text"],
                token="fake-token",
                prompt_type="gpt_abstract",
            )
        self.assertEqual(inference.provider_name, "openai")
        self.assertIsInstance(inference._provider, OpenAIProvider)


class TestOpenAIProvider(unittest.TestCase):
    def test_complete_returns_text(self):
        with patch("openai.OpenAI", make_openai_mock("Reasoning line\nXXX")):
            provider = OpenAIProvider(api_key="fake-token")
            result = provider.complete("system prompt", "user prompt", "gpt-4o")
        self.assertEqual(result, "Reasoning line\nXXX")


class TestSwissGPTProvider(unittest.TestCase):
    def test_uses_alpine_base_url(self):
        mock_client_cls = make_openai_mock("ok")
        with patch("openai.OpenAI", mock_client_cls):
            SwissGPTProvider(api_key="fake-token")
        mock_client_cls.assert_called_once_with(
            api_key="fake-token", base_url=ALPINE_BASE_URL
        )


class TestAnthropicProvider(unittest.TestCase):
    def test_missing_package_raises_clear_error(self):
        # The 'anthropic' package is not a dependency of this repo; verify the
        # error message guides the user to install it rather than a bare
        # ModuleNotFoundError.
        with self.assertRaises(ImportError) as ctx:
            AnthropicProvider(api_key="fake-token")
        self.assertIn("pip install anthropic", str(ctx.exception))

    def test_complete_uses_top_level_system_param(self):
        fake_anthropic = types.ModuleType("anthropic")

        mock_response = MagicMock()
        mock_response.content[0].text = "Reasoning line\nXXX"
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        fake_anthropic.Anthropic = MagicMock(return_value=mock_client)
        fake_anthropic.APIConnectionError = Exception

        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            provider = AnthropicProvider(api_key="fake-token")
            result = provider.complete("system prompt", "user prompt", "claude-sonnet-5")

        mock_client.messages.create.assert_called_once_with(
            model="claude-sonnet-5",
            system="system prompt",
            max_tokens=1024,
            messages=[{"role": "user", "content": "user prompt"}],
        )
        self.assertEqual(result, "Reasoning line\nXXX")


class TestGetProvider(unittest.TestCase):
    def test_unknown_provider_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_provider("does-not-exist", "fake-token")


class TestResponseToDataframe(unittest.TestCase):
    def test_parses_plain_text_responses(self):
        with patch("openai.OpenAI", make_openai_mock("irrelevant")):
            inference = ModelInference(
                prompts_path=PROMPTS_PATH,
                dataset=["abstract one", "abstract two"],
                token="fake-token",
                prompt_type="gpt_abstract",
            )

        responses = ["Some reasoning.\nXXX", "Other reasoning.\nYYY"]
        df = inference.response_to_dataframe(responses)

        self.assertEqual(list(df["label"]), [0, 1])
        self.assertEqual(df.loc[0, "reasoning"], "Some reasoning.")
        self.assertEqual(df.loc[0, "decision"], "XXX")

    def test_skips_none_responses(self):
        with patch("openai.OpenAI", make_openai_mock("irrelevant")):
            inference = ModelInference(
                prompts_path=PROMPTS_PATH,
                dataset=["abstract one", "abstract two"],
                token="fake-token",
                prompt_type="gpt_abstract",
            )

        df = inference.response_to_dataframe(["Reasoning.\nXXX", None])
        self.assertEqual(len(df), 1)


class TestSystemPromptDataTypeBug(unittest.TestCase):
    """Regression guard for the fixed `type` builtin vs `self.data_type` bug."""

    def test_system_prompt_mentions_data_type_not_builtin(self):
        captured = {}

        def fake_complete(system_prompt, user_prompt, model):
            captured["system_prompt"] = system_prompt
            return "Reasoning.\nXXX"

        with patch("openai.OpenAI", make_openai_mock("irrelevant")):
            inference = ModelInference(
                prompts_path=PROMPTS_PATH,
                dataset=["abstract text"],
                token="fake-token",
                prompt_type="gpt_abstract",
                data_type="abstracts",
            )
        inference._provider.complete = fake_complete

        inference.llm_inference(objectives=["obj"], inclusion_criteria=["inc"], exclusion_criteria=["exc"])

        self.assertIn("abstracts", captured["system_prompt"])
        self.assertNotIn("<class", captured["system_prompt"])


if __name__ == "__main__":
    unittest.main()
