import json
import re
from typing import Any, Dict, List, Optional, Set
from pydantic import ValidationError

from app.config.settings import settings
from app.core.models import AgentAction, AgentPlan, ScreenContext
from app.logging.logger import logger


class AIPromptBuilder:
    """
    Constructs structured system instructions and context-rich prompts for AI models.
    Supports 9-category intent classification, Hinglish, multi-turn context,
    targeted semantic patch actions, and strict Pydantic schema validation.
    """

    VALID_ACTION_TYPES: Set[str] = {
        # File System
        "open_folder", "create_folder", "create_file", "rename_path",
        "move_path", "copy_path", "trash_path", "list_directory", "find_file",
        "open_recent_files", "open_latest_download", "reveal_in_file_manager", "quick_look", "open_file_with_app",
        # Windows & Apps
        "open_app", "close_app", "window_minimize", "window_maximize",
        "window_restore", "window_close", "window_snap_left", "window_snap_right",
        "window_center", "show_desktop",
        "switch_window", "switch_same_app_window", "task_view", "window_full_screen",
        "next_desktop", "prev_desktop",
        # Web & Browser
        "web_search", "open_url", "browser_new_tab", "browser_close_tab",
        "browser_next_tab", "browser_prev_tab", "browser_reload",
        "browser_reopen_tab", "browser_last_tab", "browser_new_window",
        "browser_switch_tab_number",   # amount = tab number (1-based)
        "browser_show_history",        # open Ctrl+H / Cmd+Y (search history)
        "browser_show_downloads",      # open Ctrl+J / Cmd+Opt+L (browser downloads)
        "browser_bookmark", "browser_bookmark_page", "browser_bookmarks_list",
        "browser_address_bar", "browser_find_in_page", "browser_clear_data",
        "browser_task_manager", "browser_go_back", "browser_go_forward",
        "browser_zoom_in", "browser_zoom_out", "browser_zoom_reset",
        "browser_incognito", "browser_open_incognito",
        # VS Code Navigation & IDE
        "vscode_jump_line", "vscode_open_file", "vscode_close_file", "vscode_read_line",
        "vscode_open_folder", "vscode_open_file_at_line", "vscode_diff",
        "vscode_open_current_window", "vscode_open_new_window", "vscode_quick_open",
        "vscode_command_palette", "vscode_terminal", "vscode_toggle_sidebar",
        "vscode_settings", "vscode_goto_symbol", "vscode_goto_definition",
        "vscode_format", "vscode_save_all", "vscode_search_project",
        "vscode_find_todo", "vscode_replace_all", "undo_last_edit",
        # VS Code Code Editing (token-based and semantic patch)
        "vscode_edit", "vscode_run_code", "vscode_undo",
        "vscode_patch",
        # VS Code Inspection
        "vscode_inspect", "vscode_find_symbols", "vscode_outline",
        # System & Clipboard & Screen Interaction
        "screenshot", "screen_read", "screen_read_all",
        "screen_click", "screen_double_click", "screen_right_click", "screen_select", "screen_open",
        "volume_up", "volume_down", "volume_mute",
        "copy", "paste", "clear_clipboard", "select_all", "undo", "redo", "save",
        # Conversational Q&A
        "answer_question",
    }

    SYSTEM_INSTRUCTION = """You are Clembot, an intelligent voice assistant on Windows 10/11.
You understand casual human speech, Hinglish (Hindi-English mix), and multi-turn conversation.
You can Control Windows, automate browsers, edit code precisely, and chat naturally.

=== INTENT CLASSIFICATION ===
Each user request maps to one of the 10 Clembot intents:
1. open_app        - Launch or close applications (Chrome, VS Code, Notepad, Safari, etc.)
2. open_file       - Open, preview, reveal, or open files with apps
3. open_folder     - Open directories, standard folders, recent files, trash/recycle bin
4. open_url        - Open website URLs or perform web/Google searches
5. browser_tab     - Switch, open, close, or reopen browser tabs
6. browser_page    - Page actions: history, downloads, bookmarks, address bar, zoom, reload, clear data
7. vscode_open     - Open project folders, jump to lines/columns, diffs, palette, terminal, symbols
8. vscode_edit     - Modify code lines, replace, delete, comment, format, semantic patches
9. window_switch   - Window switching (Alt+Tab, Cmd+Tab), task view, minimize, maximize, full screen
10. system         - System controls (volume, screenshots, clipboard, screen reading, chat)

=== VOICE / TTS OUTPUT RULES ===
- "reply" is spoken aloud via Text-to-Speech.
- CRITICAL: Keep replies short: under 15 words spoken response.
- NO markdown: no *, **, #, -, •, `, backtick code blocks, or emojis.
- Write naturally like spoken speech.
- Never read raw code blocks aloud.
- Say what action occurred in plain, brief words (e.g. "Opening Chrome.", "Line 20 replaced.", "New tab.").

=== CONVERSATIONAL BEHAVIOUR ===
- Treat every message as natural conversation, not a rigid command.
- Maintain context: "it", "this", "that", "same file", "that function", "undo that" refer to previous turns.
- Do NOT force every sentence into a desktop action.
- If the user is chatting or asking a question, reply naturally in "reply" with actions=[].
- If the user asks to "fix it", "make it async", "clean this up", understand from context what "it" refers to.
- If genuinely ambiguous AND the action is destructive, ask ONE short clarification question.
- Otherwise, make a reasonable inference and proceed.
- For Hinglish, respond naturally in Hinglish if the user spoke in Hinglish.

=== VOICE / TTS OUTPUT RULES ===
- "reply" is spoken aloud via Windows Text-to-Speech.
- Write naturally like spoken English (or Hinglish).
- NO markdown: no *, **, #, -, •, `, backtick code blocks, or emojis.
- Keep replies short: 1-3 sentences maximum.
- For code explanations: summarise verbally ("This function fetches user data from the database and returns it as a list.").
- Never read raw code aloud. Never speak JSON.
- For code changes: say what changed, not the code itself ("Done, I replaced the synchronous call with async/await.").

=== ACTION TYPES ===
Standard Windows/File/Browser actions:
  open_folder (path), create_folder (path), create_file (path, text)
  rename_path (path, destination), move_path (path, destination), copy_path (path, destination)
  trash_path (path), list_directory (path), find_file (query, scope)
  open_app (app), close_app (app)
  window_minimize, window_maximize, window_restore, window_close
  window_snap_left, window_snap_right, window_center, show_desktop
  web_search (query, scope), open_url (url)
  browser_new_tab [app=chrome|brave], browser_close_tab, browser_next_tab, browser_prev_tab
  browser_reopen_tab, browser_reload
  browser_switch_tab_number (amount=N, app=chrome|brave) — switch to tab N (only if browser is displayed)
  browser_show_history [app=chrome|brave]    — opens Ctrl+H search history (only if browser is displayed)
  browser_show_downloads [app=chrome|brave]  — opens Ctrl+J downloads tab (only if browser is displayed)
  browser_bookmark, browser_zoom_in, browser_zoom_out, browser_zoom_reset, browser_incognito
  screenshot             — saves a binary-thresholded screenshot (≤100 KB) to Pictures/Screenshots
  screen_read (query?)   — captures the screen and uses AI vision to describe / read what's visible
  screen_read_all        — comprehensive whole-screen reading (active apps, open files, interactive elements)
  screen_click (text)    — clicks on a displayed button, link, icon, or element matching text
  screen_double_click (text) — double clicks on a displayed file, folder, or icon
  screen_right_click (text)  — right clicks on a displayed item
  screen_select (text)   — selects or focuses an item, checkbox, or text on screen
  screen_open (text)     — opens a displayed file, folder, or application visible on screen
  volume_up, volume_down, volume_mute
  copy, paste, clear_clipboard, select_all, undo, redo, save


VS Code Navigation:
  vscode_jump_line (line_number)
  vscode_open_file (path)
  vscode_close_file (path) — close active file or specified file in VS Code
  vscode_read_line (line_number)

VS Code Code Inspection:
  vscode_inspect   — inspect active file / selection and explain it
  vscode_outline   — show/speak file structure (functions and classes)
  vscode_find_symbols (query, scope) — search workspace for a symbol, function, or API

VS Code Code Modification — TARGETED SEMANTIC PATCH (PREFERRED):
  vscode_patch — targeted code change without whole-file regeneration
    Required fields:
      "target_code"      - Exact or fuzzy code snippet to locate (copy from active file)
      "replacement_code" - The replacement code block (only the changed portion)
      "explanation"      - Spoken explanation of what changed
    Optional fields:
      "path"        - File path (omit to use active file)
      "symbol"      - Function or class name being changed
      "line_number" - Approximate line number hint
      "patch_action"- "replace" (default), "insert_before", "insert_after", "delete"

  CRITICAL: Use vscode_patch for ALL code modifications.
  NEVER return the entire file as "replacement_code".
  NEVER regenerate whole files.
  Only include the specific code block that needs to change.
  For renaming: use target_code=old_code_block, replacement_code=renamed_version.
  For adding imports: use patch_action="insert_before", target_code=first_import_line.
  For deleting code: use patch_action="delete", target_code=block_to_remove.

VS Code Execution:
  vscode_run_code — run current file
  vscode_undo     — undo last editor change

Conversational:
  answer_question (query or text) — for Q&A with no desktop action

=== MULTI-STEP TASKS ===
For complex requests like "Open the Django project, find the login view, add error handling, and run tests":
List each action sequentially. Keep reply describing all steps in one natural sentence.

=== HINGLISH EXAMPLES ===
"ye code galat hai isko fix karo" → code_mod: vscode_patch to fix the active code
"database query ko sahi karo" → code_mod: vscode_patch to fix the query
"jo abhi change kiya tha usko undo karo" → vscode_undo
"is function ko async bana do" → code_mod: vscode_patch to convert to async
"upar wali condition hata do" → code_mod: vscode_patch with patch_action="delete"
"mere project mein login ka code dhundo" → vscode_find_symbols query="login"
"batao ye error kyu aa raha hai" → code_inspection / answer_question explaining the error
"isko samjhao" → vscode_inspect to explain current file/selection

=== SCHEMA ===
Return a valid JSON object only — no markdown fences:
{
  "reply": "Spoken verbal response (no markdown)",
  "intent": "one of: conversation, windows_action, file_operation, browser_op, vscode_nav, code_inspection, code_mod, code_exec, multi_step",
  "actions": [
    {
      "type": "action type from the list above",
      "path": "optional file/folder path",
      "destination": "optional destination path",
      "app": "optional app name",
      "url": "optional URL",
      "query": "optional search query",
      "text": "optional text content",
      "instruction": "optional instruction",
      "line_number": null,
      "scope": "optional scope",
      "target_code": "exact snippet to find and replace (for vscode_patch)",
      "replacement_code": "replacement code block (for vscode_patch)",
      "symbol": "optional function/class name",
      "patch_action": "replace|insert_before|insert_after|delete"
    }
  ]
}
"""

    @classmethod
    def build_system_instruction(cls) -> str:
        try:
            from app.platform_layer.factory import platform_adapter
            platform_name = platform_adapter.get_platform_name()
        except Exception:
            platform_name = "Windows 10/11"

        instruction = cls.SYSTEM_INSTRUCTION
        if "macOS" in platform_name:
            instruction = instruction.replace("Windows 10/11", platform_name)
            instruction = instruction.replace("Control Windows", "Control macOS")
            instruction = instruction.replace("Windows Text-to-Speech", "macOS Text-to-Speech")
            instruction = instruction.replace("Standard Windows/File/Browser actions", "Standard macOS/File/Browser actions")
        return instruction

    @classmethod
    def build_user_prompt(cls, command: str, context: ScreenContext) -> str:
        """Assembles a context-rich user prompt including live desktop context, code context, and history."""
        sections = []

        # 1. Recent conversation history
        if context.recent_history:
            recent_turns = [
                f"{t.get('role', 'user').capitalize()}: {t.get('content', '')}"
                for t in context.recent_history[-6:]
            ]
            sections.append("Recent Conversation:\n" + "\n".join(recent_turns))

        # 2. Real-time Desktop Context
        try:
            from app.platform_layer.factory import platform_adapter
            plat_header = f"{platform_adapter.get_platform_name()} Desktop State"
        except Exception:
            plat_header = "Windows Desktop State"

        desktop_info = [
            f"- Active Window: {context.active_window_title or 'Unknown'} ({context.active_app or 'Unknown'})",
            f"- Focused File Explorer Path: {context.explorer_path or 'None'}",
        ]
        sections.append(f"{plat_header}:\n" + "\n".join(desktop_info))

        # 3. VS Code Context (rich code context for accurate edits)
        vscode_parts = []
        if context.vscode_file:
            vscode_parts.append(f"- Active File: {context.vscode_file}")
        if context.vscode_workspace:
            vscode_parts.append(f"- Workspace: {context.vscode_workspace}")
        if context.vscode_line:
            vscode_parts.append(f"- Cursor Line: {context.vscode_line}")
        if context.selected_text:
            # Truncate long selections to avoid token overflow
            sel = context.selected_text[:500]
            vscode_parts.append(f"- Selected Text:\n{sel}")
        if context.focused_code_snippet:
            snippet = context.focused_code_snippet[:800]
            vscode_parts.append(f"- Code Context (around cursor):\n{snippet}")
        if context.last_modified_file:
            vscode_parts.append(f"- Last Modified File: {context.last_modified_file}")
        if context.last_modified_symbol:
            vscode_parts.append(f"- Last Modified Symbol: {context.last_modified_symbol}")
        if context.last_edit_summary:
            vscode_parts.append(f"- Last Edit Summary: {context.last_edit_summary}")

        if vscode_parts:
            sections.append("VS Code / Editor Context:\n" + "\n".join(vscode_parts))

        # 4. Error context (helps "why is this failing?" questions)
        # (Would be injected from memory separately if available)

        # 5. User spoken input
        sections.append(f"User Spoken Command: \"{command}\"")

        return "\n\n".join(sections)

    @classmethod
    def build_code_context_prompt(cls, command: str, context: ScreenContext, code_content: str, file_path: str) -> str:
        """Builds a code-targeted prompt for patch generation with file content included."""
        # For patch generation, include the full relevant file (or first 200 lines)
        lines = code_content.splitlines()
        if len(lines) > 200:
            content_to_include = "\n".join(lines[:200]) + f"\n... [{len(lines) - 200} more lines, focusing on area around cursor]"
        else:
            content_to_include = code_content

        base = cls.build_user_prompt(command, context)
        code_section = f"\nFull File Content for {file_path}:\n```\n{content_to_include}\n```"
        return base + "\n\n" + code_section

    @classmethod
    def build_retry_prompt(cls, original_prompt: str, error_msg: str, invalid_output: str) -> str:
        """Constructs a targeted prompt asking the model to fix its invalid JSON output."""
        return (
            f"{original_prompt}\n\n"
            f"[SYSTEM FEEDBACK]: Your previous response could not be parsed: {error_msg}\n"
            f"Previous output was: {invalid_output[:400]}\n"
            f"Please respond with strictly valid JSON following the schema without markdown."
        )

    @classmethod
    def parse_and_validate(cls, raw_text: str) -> AgentPlan:
        """
        Parses and validates the raw LLM output into an AgentPlan.
        Validates against Pydantic schema and enforces allowed action types.
        Raises ValueError on parse failure.
        """
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            # If the output is pure conversational text, wrap it cleanly
            if "{" not in cleaned and "}" not in cleaned and len(cleaned) > 0:
                return AgentPlan(reply=cleaned, actions=[], intent="conversation")
            raise ValueError(f"Invalid JSON syntax from model: {e}")

        if not isinstance(data, dict):
            raise ValueError("Root response must be a JSON object.")

        reply = str(data.get("reply") or "")
        intent = data.get("intent", None)
        raw_actions = data.get("actions")
        if raw_actions is None:
            raw_actions = []

        if not isinstance(raw_actions, list):
            raise ValueError("'actions' field must be an array or null.")

        validated_actions: List[AgentAction] = []
        for i, a in enumerate(raw_actions):
            if not isinstance(a, dict):
                raise ValueError(f"Action at index {i} must be a dictionary.")

            # Sanitize LLM string representations for optional numeric or null fields
            if "line_number" in a and (a["line_number"] == "" or a["line_number"] == "none" or a["line_number"] == "null"):
                a["line_number"] = None

            act_type = str(a.get("type", "")).lower().strip()
            if not settings.allow_unknown_actions and act_type not in cls.VALID_ACTION_TYPES:
                logger.warning(f"Rejected unknown action type from LLM: '{act_type}'")
                continue

            try:
                action_obj = AgentAction(**a)
                validated_actions.append(action_obj)
            except ValidationError as ve:
                raise ValueError(f"Action validation failed at index {i}: {ve}")

        return AgentPlan(reply=reply, actions=validated_actions, intent=intent)


prompt_builder = AIPromptBuilder()
