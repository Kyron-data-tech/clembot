import re
import threading
import time
from typing import List, Optional

from app.ai.factory import AIProviderFactory
from app.commands.fast_router import FastCommandRouter
from app.commands.router import ActionRouter
from app.config.settings import settings
from app.context.context_manager import WindowsContextManager
from app.core.event_bus import event_bus
from app.core.models import (
    ActionResult,
    AgentAction,
    AgentPlan,
    AssistantState,
    ConfirmationRequest,
    ScreenContext,
)
from app.ai.language_detector import language_detector
from app.logging.logger import logger
from app.memory.conversation import ConversationalMemory
from app.security.guard import security_guard
from app.speech.normalizer import speech_normalizer
from app.speech.wake_word import WakeWordDetector
from app.tts.voice_service import voice_service


class AssistantOrchestrator:
    """
    Master assistant controller coordinating speech, context, fast routing, AI planning,
    security confirmations, action dispatching, and conversational memory.
    """

    def __init__(self):
        self.state = AssistantState.LISTENING if settings.active_on_startup else AssistantState.IDLE
        self.wake_detector = WakeWordDetector()
        self.fast_router = FastCommandRouter()
        self.ai_provider = AIProviderFactory.get_provider()
        self.context_manager = WindowsContextManager()
        self.memory = ConversationalMemory()
        self.router = ActionRouter()

        self.pending_confirmation: Optional[ConfirmationRequest] = None
        self._lock = threading.RLock()

        # Command deduplication / debounce tracking
        self._last_command_text: str = ""
        self._last_command_time: float = 0.0
        self._dedup_window_sec: float = 1.5

        # Wire event bus
        event_bus.subscribe("speech_recognized", self.handle_user_input)
        event_bus.subscribe("settings_updated", lambda _: self.reload_ai_provider())

    def reload_ai_provider(self) -> None:
        """Dynamically reloads the active AI provider when configuration updates."""
        with self._lock:
            self.ai_provider = AIProviderFactory.get_provider()
            logger.info(f"Active AI Provider updated to: {self.ai_provider.__class__.__name__}")

    def has_active_llm(self) -> bool:
        """Returns True if a cloud or local LLM (Gemini/Ollama) is active and available."""
        from app.ai.local_heuristic import LocalHeuristicPlanner
        return not isinstance(self.ai_provider, LocalHeuristicPlanner) and self.ai_provider.is_available()

    def set_state(self, new_state: AssistantState) -> None:
        with self._lock:
            old_state = self.state
            self.state = new_state
            logger.info(f"State transition: {old_state} -> {new_state}")
            event_bus.emit("assistant_state_changed", new_state.value)

    def activate(self) -> str:
        """Explicitly activates the assistant."""
        with self._lock:
            self.set_state(AssistantState.LISTENING)
            msg = "Clembot is activated and listening."
            voice_service.speak(msg)
            return msg

    def deactivate(self) -> str:
        """Explicitly deactivates the assistant."""
        with self._lock:
            self.set_state(AssistantState.IDLE)
            self.pending_confirmation = None
            msg = "Clembot deactivated. Say 'Clembot activate yourself' when you need me."
            voice_service.speak(msg)
            return msg

    def handle_user_input(self, text: str) -> None:
        """Main entry point for incoming user speech or text input."""
        raw_text = text.strip()
        if not raw_text:
            return

        with self._lock:
            # Normalize spoken phonetic variations (clemburt, clem ber, clembur -> clembot)
            cleaned = self.wake_detector.normalize_spoken_name(raw_text)

            # Deduplication to prevent double execution within 1.5s
            norm_check = re.sub(r'[^\w\s]', '', cleaned.lower()).strip()
            now = time.time()
            if norm_check and norm_check == self._last_command_text and (now - self._last_command_time) < self._dedup_window_sec:
                logger.info(f"Ignored duplicate command within {self._dedup_window_sec}s: \"{cleaned}\"")
                return

            self._last_command_text = norm_check
            self._last_command_time = now

            logger.info(f"User Input: \"{cleaned}\" (Current State: {self.state.value})")
            event_bus.emit("transcript_updated", f"You: {cleaned}")

            # 1. Check Activation Phrase
            is_wake, command_remainder = self.wake_detector.check_activation(cleaned)
            if is_wake:
                self.set_state(AssistantState.LISTENING)
                if not command_remainder:
                    msg = "Clembot activated. How can I help you?"
                    self._reply_and_record(msg)
                    return
                cleaned = command_remainder

            # 2. Check Deactivation Phrase
            if self.wake_detector.check_deactivation(cleaned):
                self.deactivate()
                return

            # If currently deactivated/sleeping, ignore ambient chatter until activated
            if self.state == AssistantState.IDLE:
                logger.debug("Ignored input because Clembot is deactivated (IDLE).")
                return

            # 3. Check Awaiting Confirmation State
            if self.state == AssistantState.AWAITING_CONFIRMATION and self.pending_confirmation:
                self._handle_confirmation_response(cleaned)
                return

            # 4. Strip any leading wake words like "Hey Clembot" if still present
            cleaned = self.wake_detector.strip_wake_phrase(cleaned)
            if not cleaned:
                self._reply_and_record("Yes, I'm listening.")
                return

            # 5. Process Regular Command
            self.process_command(cleaned)

    def process_command(self, raw_command: str) -> None:
        """Processes a validated user command."""
        # Snapshot the foreground window RIGHT NOW — before we steal focus —
        # so close/minimize/maximize act on the user's app, not Clembot.
        try:
            import win32gui as _w32
            _hwnd = _w32.GetForegroundWindow()
            _title = _w32.GetWindowText(_hwnd) if _hwnd else ""
            # Only store if it's a real user window (not the desktop / taskbar)
            if _hwnd and _title and "clembot" not in _title.lower():
                self.router.windows.last_user_hwnd = _hwnd
                self.router.windows.last_user_title = _title
        except Exception:
            pass

        self.set_state(AssistantState.PROCESSING)
        self.memory.add_user_turn(raw_command)

        # Normalize spoken fillers and homophones
        normalized_cmd = speech_normalizer.normalize_command(raw_command)

        # A. Resolve contextual memory references ("that file", "that function", "undo that")
        resolved_command = self.memory.resolve_contextual_references(normalized_cmd)
        if resolved_command != raw_command:
            logger.info(f"Normalized/Resolved command: \"{resolved_command}\"")

        # A1. Direct undo shortcut — resolve_contextual_references returns literal "undo"
        if resolved_command.strip().lower() == "undo":
            from app.editor.code_patch_engine import code_patch_engine
            last_file = getattr(self.memory, 'last_file', None)
            success, msg = code_patch_engine.undo_last_patch(last_file)
            if success:
                # Reload the reverted file in VS Code so the editor reflects the restored code
                reverted_path = getattr(code_patch_engine, 'last_reverted_path', None) or last_file
                if reverted_path:
                    try:
                        self.router.vscode.open_file(reverted_path)
                    except Exception:
                        pass
            self._reply_and_record(msg)
            self.set_state(AssistantState.LISTENING)
            return

        # B. Check for non-English / Hinglish phrasing
        is_hinglish = language_detector.is_hinglish(normalized_cmd)
        has_llm = self.has_active_llm()

        plan = None
        if not is_hinglish:
            # Fast Command Router (Deterministic, 0ms latency)
            plan = self.fast_router.plan_for_command(resolved_command, llm_active=has_llm)
        else:
            logger.info(f"Hinglish / non-English query detected: '{normalized_cmd}'. Routing directly to AI reasoning.")

        # C. AI Planning Layer (LLM reasoning or open-ended speech)
        if not plan:
            self.set_state(AssistantState.PROCESSING)
            context = self.context_manager.capture_context()
            context.recent_history = self.memory.get_recent_history(limit=6)

            # Inject conversational code context from memory
            mem_ctx = self.memory.get_memory_context_dict()
            if mem_ctx.get("last_file"):
                context.last_modified_file = mem_ctx.get("last_file")
            if mem_ctx.get("last_symbol"):
                context.last_modified_symbol = mem_ctx.get("last_symbol")
            if mem_ctx.get("last_patch_summary"):
                context.last_edit_summary = mem_ctx.get("last_patch_summary")

            # Inject focused code snippet (lines around cursor)
            self._inject_code_snippet(context)

            plan = self.ai_provider.plan(resolved_command, context)

        # D. Execute Plan
        self._dispatch_plan(plan)

    def _inject_code_snippet(self, context: ScreenContext) -> None:
        """Injects focused code context (lines around cursor) into ScreenContext for richer LLM prompts."""
        try:
            if context.vscode_file:
                from pathlib import Path
                p = Path(context.vscode_file)
                if p.is_file():
                    raw = p.read_bytes()
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = raw.decode("cp1252", errors="replace")
                    lines = text.splitlines()
                    cursor = max(1, context.vscode_line or 1)
                    start = max(0, cursor - 20)
                    end = min(len(lines), cursor + 20)
                    snippet_lines = [f"{i + 1 + start}: {ln}" for i, ln in enumerate(lines[start:end])]
                    context.focused_code_snippet = "\n".join(snippet_lines)
        except Exception as e:
            logger.debug(f"Could not inject code snippet: {e}")

    def _dispatch_plan(self, plan: AgentPlan) -> None:
        """Validates safety and dispatches planned actions."""
        if not plan.actions:
            self._reply_and_record(plan.reply or "I understood, but had no actions to take.")
            self.set_state(AssistantState.LISTENING)
            return

        # Check safety policy on all actions
        for action in plan.actions:
            requires_confirmation, conf_request = security_guard.evaluate_action_risk(action)
            if requires_confirmation and conf_request:
                self.pending_confirmation = conf_request
                self.set_state(AssistantState.AWAITING_CONFIRMATION)
                event_bus.emit("confirmation_requested", conf_request.model_dump())
                self._reply_and_record(conf_request.prompt)
                return

        # Safe to execute immediately
        self._execute_actions(plan.actions, plan.reply)

    def _execute_actions(self, actions: List[AgentAction], default_reply: str) -> None:
        """Executes actions sequentially and returns consolidated feedback."""
        self.set_state(AssistantState.EXECUTING)
        replies = []
        base_dir = self.memory.last_folder

        for action in actions:
            result = self.router.execute(action, context_base=base_dir)
            event_bus.emit("action_executed", result.model_dump())
            if result.message:
                replies.append(result.message)

            # Record successful code patches in conversational memory
            if result.success and action.type == "vscode_patch":
                from pathlib import Path
                patch_file = Path(action.path) if getattr(action, 'path', None) else getattr(self.memory, 'last_file', None)
                if patch_file:
                    self.memory.record_code_patch(
                        file_path=patch_file,
                        explanation=getattr(action, 'instruction', None) or result.message or "",
                        symbol_name=getattr(action, 'symbol', None),
                    )
                    self.memory.last_file = patch_file

            # Track last opened/edited file
            if result.success and action.type in ("vscode_open_file", "vscode_edit", "vscode_read_line"):
                if getattr(action, 'path', None):
                    from pathlib import Path
                    self.memory.last_file = Path(action.path)

            # Record errors for conversational follow-up ("why did it fail?")
            if not result.success and result.error:
                self.memory.record_error(result.error)

        final_reply = " ".join(replies) if replies else default_reply
        self._reply_and_record(final_reply)
        self.set_state(AssistantState.LISTENING)

    def _handle_confirmation_response(self, response_text: str) -> None:
        """Handles user spoken response to a pending confirmation."""
        norm = response_text.lower().strip()
        positive = ["confirm", "yes", "do it", "sure", "proceed", "okay", "ok", "apply", "delete", "run",
                    "haan", "theek", "bilkul", "kar do"]
        negative = ["cancel", "no", "stop", "never mind", "dont", "do not", "abort", "nahi", "mat karo"]

        if any(w in norm for w in positive):
            req = self.pending_confirmation
            self.pending_confirmation = None
            event_bus.emit("confirmation_resolved", {"id": req.id, "approved": True})
            self._execute_actions(req.actions, "Confirmed. Applying changes now.")

        elif any(w in norm for w in negative):
            req = self.pending_confirmation
            self.pending_confirmation = None
            event_bus.emit("confirmation_resolved", {"id": req.id, "approved": False})
            self._reply_and_record("Cancelled. No changes were made.")
            self.set_state(AssistantState.LISTENING)

        else:
            self._reply_and_record("Please say confirm to proceed, or cancel to abort.")

    @staticmethod
    def _strip_markdown_for_voice(reply: str) -> str:
        """Strips markdown symbols that sound unnatural via TTS."""
        if not reply:
            return reply
        reply = re.sub(r'```[^`]*```', '', reply, flags=re.DOTALL)
        reply = re.sub(r'`[^`]+`', lambda m: m.group(0).strip('`'), reply)
        reply = re.sub(r'\*\*(.+?)\*\*', r'\1', reply)
        reply = re.sub(r'\*(.+?)\*', r'\1', reply)
        reply = re.sub(r'__(.+?)__', r'\1', reply)
        reply = re.sub(r'_(.+?)_', r'\1', reply)
        reply = re.sub(r'^#+\s*', '', reply, flags=re.MULTILINE)
        reply = re.sub(r'^\s*[-*•]\s+', '', reply, flags=re.MULTILINE)
        reply = re.sub(r'^\s*\d+\.\s+', '', reply, flags=re.MULTILINE)
        reply = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', reply)
        reply = re.sub(r'\n{3,}', '\n\n', reply)
        return reply.strip()

    def _reply_and_record(self, reply: str) -> None:
        """Speaks the reply (with markdown stripped) and logs it in conversational history."""
        clean_reply = self._strip_markdown_for_voice(reply)
        logger.info(f"Clembot Reply: \"{clean_reply}\"")
        self.memory.add_clembot_turn(clean_reply)
        event_bus.emit("clembot_replied", clean_reply)
        voice_service.speak(clean_reply)


# Global orchestrator singleton
orchestrator = AssistantOrchestrator()

