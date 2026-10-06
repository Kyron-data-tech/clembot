import unittest
from unittest.mock import MagicMock, patch
from app.ai.gemini_provider import GeminiProvider
from app.ai.ollama_provider import OllamaProvider
from app.ai.openai_provider import OpenAIProvider
from app.commands.fast_router import FastCommandRouter
from app.config.settings import settings
from app.core.models import ScreenContext


class TestLLMProviders(unittest.TestCase):
    def test_fast_router_with_llm_active(self):
        router = FastCommandRouter()
        
        # When LLM is active, open-ended question passes through to LLM (returns None)
        plan_with_llm = router.plan_for_command("what is machine learning", llm_active=True)
        self.assertIsNone(plan_with_llm)

        # When LLM is not active (offline heuristic), question routes to browser web search
        plan_offline = router.plan_for_command("what is machine learning", llm_active=False)
        self.assertIsNotNone(plan_offline)
        self.assertEqual(plan_offline.actions[0].type, "web_search")

        # Explicit search always routes to web search regardless of LLM
        plan_search = router.plan_for_command("search google for python tutorials", llm_active=True)
        self.assertIsNotNone(plan_search)
        self.assertEqual(plan_search.actions[0].type, "web_search")

    def test_gemini_open_ended_speech_mock(self):
        provider = GeminiProvider()
        ctx = ScreenContext(recent_history=[{"role": "user", "content": "Hello Clembot"}])

        # Mock genai Client
        mock_response = MagicMock()
        mock_response.text = '{"reply": "Hello! I am ready to help you with anything on your PC.", "actions": []}'
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(settings, "gemini_api_key", "test-api-key"):
            plan = provider.plan("Hello, how are you?", ctx)
            self.assertEqual(plan.reply, "Hello! I am ready to help you with anything on your PC.")
            self.assertEqual(len(plan.actions), 0)

    def test_gemini_action_mock(self):
        provider = GeminiProvider()
        ctx = ScreenContext()

        mock_response = MagicMock()
        mock_response.text = '{"reply": "Opening Downloads.", "actions": [{"type": "open_folder", "path": "Downloads"}]}'

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(settings, "gemini_api_key", "test-api-key"):
            plan = provider.plan("Please open downloads folder", ctx)
            self.assertEqual(len(plan.actions), 1)
            self.assertEqual(plan.actions[0].type, "open_folder")

    def test_ollama_open_ended_speech_mock(self):
        provider = OllamaProvider()
        ctx = ScreenContext()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "content": '{"reply": "Artificial intelligence allows computers to learn from data.", "actions": []}'
            }
        }

        with patch("httpx.post", return_value=mock_resp):
            plan = provider.plan("Explain AI in one sentence", ctx)
            self.assertEqual(plan.reply, "Artificial intelligence allows computers to learn from data.")
            self.assertEqual(len(plan.actions), 0)

    def test_openai_open_ended_speech_mock(self):
        provider = OpenAIProvider()
        ctx = ScreenContext()

        mock_choice = MagicMock()
        mock_choice.message.content = '{"reply": "Hello from OpenAI!", "intent": "conversation", "actions": []}'
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        with patch("openai.OpenAI", return_value=mock_client), \
             patch.object(settings, "openai_api_key", "sk-test-key"):
            plan = provider.plan("hello", ctx)
            self.assertEqual(plan.reply, "Hello from OpenAI!")
            self.assertEqual(plan.intent, "conversation")
            self.assertEqual(len(plan.actions), 0)

    def test_openai_retry_on_validation_failure(self):
        provider = OpenAIProvider()
        ctx = ScreenContext()

        mock_invalid = MagicMock()
        mock_invalid.message.content = '{"reply": "bad", "actions": "not_a_list"}'
        mock_valid = MagicMock()
        mock_valid.message.content = '{"reply": "Fixed plan", "actions": [{"type": "open_app", "app": "calc"}]}'

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            MagicMock(choices=[mock_invalid]),
            MagicMock(choices=[mock_valid]),
        ]

        with patch("openai.OpenAI", return_value=mock_client), \
             patch.object(settings, "openai_api_key", "sk-test-key"):
            plan = provider.plan("open calculator", ctx)
            self.assertEqual(plan.reply, "Fixed plan")
            self.assertEqual(len(plan.actions), 1)
            self.assertEqual(plan.actions[0].app, "calc")
            self.assertEqual(mock_client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
