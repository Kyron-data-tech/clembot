import unittest
from unittest.mock import MagicMock, patch
from app.ai.prompt_builder import AIPromptBuilder
from app.ai.gemini_provider import GeminiProvider
from app.config.settings import settings
from app.core.models import ScreenContext


class TestAIPlanner(unittest.TestCase):
    def setUp(self):
        self.builder = AIPromptBuilder()
        self.gemini = GeminiProvider()

    def test_prompt_builder_user_prompt(self):
        ctx = ScreenContext(
            active_app="Code.exe",
            active_window_title="main.py - voiceps",
            explorer_path="C:\\Users\\Test\\Downloads",
            vscode_file="F:\\intr\\voiceps\\app\\main.py",
            recent_history=[{"role": "user", "content": "open downloads"}]
        )
        prompt = self.builder.build_user_prompt("create folder AI", ctx)
        self.assertIn("main.py - voiceps", prompt)
        self.assertIn("Code.exe", prompt)
        self.assertIn("Downloads", prompt)
        self.assertIn("create folder AI", prompt)

    def test_parse_valid_plan(self):
        valid_json = """
        {
            "reply": "Creating folder AI and opening it.",
            "actions": [
                {"type": "create_folder", "path": "AI"},
                {"type": "open_folder", "path": "AI"}
            ]
        }
        """
        plan = self.builder.parse_and_validate(valid_json)
        self.assertEqual(plan.reply, "Creating folder AI and opening it.")
        self.assertEqual(len(plan.actions), 2)
        self.assertEqual(plan.actions[0].type, "create_folder")
        self.assertEqual(plan.actions[1].type, "open_folder")

    def test_unknown_action_rejection(self):
        settings.allow_unknown_actions = False
        json_with_unknown = """
        {
            "reply": "Running mystery command.",
            "actions": [
                {"type": "unknown_hack_command", "target": "system"},
                {"type": "open_app", "app": "notepad"}
            ]
        }
        """
        plan = self.builder.parse_and_validate(json_with_unknown)
        # unknown_hack_command should be filtered out
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].type, "open_app")

    def test_retry_prompt_format(self):
        retry = self.builder.build_retry_prompt(
            original_prompt="User: open app",
            error_msg="Missing actions array",
            invalid_output="bad output"
        )
        self.assertIn("SYSTEM FEEDBACK", retry)
        self.assertIn("Missing actions array", retry)
        self.assertIn("bad output", retry)

    def test_open_ended_conversational_text_fallback(self):
        raw_text = "The distance between Satna and Jabalpur is approximately 200 kilometers by road via NH30."
        plan = self.builder.parse_and_validate(raw_text)
        self.assertEqual(plan.reply, raw_text)
        self.assertEqual(len(plan.actions), 0)

    def test_gemini_retry_on_validation_failure(self):
        ctx = ScreenContext(active_app="explorer.exe", active_window_title="Downloads")

        # Mock first response as invalid JSON, second response as valid JSON
        mock_invalid_resp = MagicMock()
        mock_invalid_resp.text = '{"reply": "test", "actions": "invalid_not_a_list"}'

        mock_valid_resp = MagicMock()
        mock_valid_resp.text = '{"reply": "Success on retry", "actions": [{"type": "open_app", "app": "notepad"}]}'

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.models.generate_content.side_effect = [mock_invalid_resp, mock_valid_resp]

            plan = self.gemini.plan("open notepad", ctx)
            self.assertEqual(plan.reply, "Success on retry")
            self.assertEqual(len(plan.actions), 1)
            self.assertEqual(plan.actions[0].app, "notepad")
            self.assertEqual(mock_client.models.generate_content.call_count, 2)

    def test_parse_null_actions(self):
        json_null_actions = '{"reply": "I am fine, thank you!", "intent": "conversation", "actions": null}'
        plan = self.builder.parse_and_validate(json_null_actions)
        self.assertEqual(plan.reply, "I am fine, thank you!")
        self.assertEqual(plan.intent, "conversation")
        self.assertEqual(plan.actions, [])

    def test_parse_missing_actions(self):
        json_no_actions = '{"reply": "Here is an explanation of recursion.", "intent": "conversation"}'
        plan = self.builder.parse_and_validate(json_no_actions)
        self.assertEqual(plan.reply, "Here is an explanation of recursion.")
        self.assertEqual(plan.actions, [])

    def test_parse_line_number_sanitization(self):
        json_str_line = '{"reply": "Reading line", "actions": [{"type": "vscode_read_line", "line_number": ""}]}'
        plan = self.builder.parse_and_validate(json_str_line)
        self.assertEqual(len(plan.actions), 1)
        self.assertIsNone(plan.actions[0].line_number)

    def test_dynamic_system_instruction_mac_vs_win(self):
        with patch("app.platform_layer.factory.platform_adapter.get_platform_name", return_value="macOS (Apple Silicon arm64)"):
            instruction = self.builder.build_system_instruction()
            self.assertIn("macOS", instruction)
            self.assertIn("Control macOS", instruction)

        with patch("app.platform_layer.factory.platform_adapter.get_platform_name", return_value="Windows 10/11"):
            instruction_win = self.builder.build_system_instruction()
            self.assertIn("Windows 10/11", instruction_win)

    def test_gemini_candidate_parts_fallback(self):
        ctx = ScreenContext()
        mock_resp = MagicMock()
        # Simulate response.text raising an exception (e.g. safety warning in SDK)
        type(mock_resp).text = unittest.mock.PropertyMock(side_effect=ValueError("Response blocked or no text"))
        mock_part = MagicMock()
        mock_part.text = '{"reply": "Recovered from candidate parts", "actions": []}'
        mock_resp.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_resp

        with patch("google.genai.Client", return_value=mock_client), \
             patch.object(settings, "gemini_api_key", "test-api-key"):
            plan = self.gemini.plan("hello", ctx)
            self.assertEqual(plan.reply, "Recovered from candidate parts")
            self.assertEqual(plan.actions, [])


if __name__ == "__main__":
    unittest.main()
