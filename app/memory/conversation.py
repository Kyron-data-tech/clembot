"""
app/memory/conversation.py

Multi-turn Conversational Memory for Clembot.
Tracks entities, active workspace, files, functions/symbols, code patches,
and resolves conversational references ("it", "that", "this file", "undo that").
"""

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ConversationTurn:
    timestamp: datetime
    speaker: str  # "user" or "clembot"
    text: str
    intent: Optional[str] = None
    target_path: Optional[str] = None
    target_app: Optional[str] = None
    target_file: Optional[str] = None
    target_symbol: Optional[str] = None


# Pre-compiled undo pattern — called on every command, avoid re.compile() per call
_UNDO_RE = re.compile(
    r'\b(?:'
    r'undo(?:\s+(?:that|this|it))?'
    r'|undo\s+(?:the\s+|that\s+|this\s+|my\s+)?(?:last\s+|previous\s+)?(?:code\s+)?(?:change|edit|modification)s?'
    r'|revert(?:\s+(?:that|this|it))?'
    r'|revert\s+(?:the\s+|that\s+|this\s+|my\s+)?(?:last\s+|previous\s+)?(?:code\s+)?(?:change|edit|modification)s?'
    r'|change\s+it\s+back'
    r'|take\s+it\s+back'
    r'|put\s+it\s+back'
    r'|pehle\s+jaisa\s+kar\s*do'
    r'|jo\s+abhi\s+change\s+kiya\s+tha(?:\s+usko)?\s+undo\s+karo'
    r'|jo\s+change\s+kiya\s+tha(?:\s+usko)?\s+undo\s+karo'
    r'|pichh?la\s+change\s+undo\s+karo'
    r'|edit\s+undo\s+karo'
    r'|code\s+(?:change\s+)?undo\s+karo'
    r')\b',
    re.IGNORECASE
)


class ConversationalMemory:
    """
    Maintains short-term conversational context and resolves pronouns and directional references.
    Examples:
      - "there" -> last visited folder
      - "this file" / "that file" -> last touched file
      - "that function" -> last inspected/modified symbol
      - "undo that" / "change it back" -> trigger undo of last code patch
      - "the other file" -> previous file in history
    """

    def __init__(self, max_history: int = 25):
        self.history: deque[ConversationTurn] = deque(maxlen=max_history)
        self.max_history = max_history

        # Entity tracking
        self.last_workspace: Optional[Path] = None
        self.last_folder: Optional[Path] = None
        self.last_file: Optional[Path] = None
        self.last_app: Optional[str] = None
        self.last_symbol: Optional[str] = None
        self.last_action_type: Optional[str] = None
        self.last_error_message: Optional[str] = None

        # Code editing tracking
        self.last_code_patch: Optional[Dict[str, Any]] = None
        self.recent_modified_files: List[Path] = []
        self.undo_stack: List[Dict[str, Any]] = []

    def add_user_turn(self, text: str) -> None:
        turn = ConversationTurn(
            timestamp=datetime.now(),
            speaker="user",
            text=text
        )
        self.history.append(turn)  # deque auto-evicts oldest when maxlen exceeded

    def add_clembot_turn(
        self,
        text: str,
        intent: Optional[str] = None,
        target_path: Optional[str] = None,
        target_app: Optional[str] = None,
        target_file: Optional[str] = None,
        target_symbol: Optional[str] = None
    ) -> None:
        turn = ConversationTurn(
            timestamp=datetime.now(),
            speaker="clembot",
            text=text,
            intent=intent,
            target_path=target_path,
            target_app=target_app,
            target_file=target_file,
            target_symbol=target_symbol
        )
        self.history.append(turn)  # deque auto-evicts oldest when maxlen exceeded

        # Update cached entity references
        if target_path:
            p = Path(target_path)
            if p.is_dir():
                self.last_folder = p
            else:
                self.last_file = p
                self.last_folder = p.parent

        if target_file:
            self.last_file = Path(target_file)
            if self.last_file.parent:
                self.last_folder = self.last_file.parent

        if target_app:
            self.last_app = target_app

        if target_symbol:
            self.last_symbol = target_symbol

    def record_code_patch(
        self,
        file_path: Path,
        explanation: str,
        diff: Optional[str] = None,
        symbol_name: Optional[str] = None
    ) -> None:
        """Records a successful code modification for multi-turn reference and undo."""
        patch_info = {
            "file": file_path,
            "explanation": explanation,
            "diff": diff,
            "symbol": symbol_name or self.last_symbol,
            "timestamp": datetime.now()
        }
        self.last_code_patch = patch_info
        self.last_file = file_path
        if symbol_name:
            self.last_symbol = symbol_name
        self.undo_stack.append(patch_info)

        if file_path not in self.recent_modified_files:
            self.recent_modified_files.append(file_path)

    def record_error(self, error_msg: str) -> None:
        """Records an execution error message for conversational diagnosis ("why did it fail?")."""
        self.last_error_message = error_msg

    def resolve_contextual_references(self, command: str) -> str:
        """
        Replaces contextual references like 'there', 'that folder', 'that file',
        'that function', 'undo that' with the concrete entities from memory.
        """
        resolved = command

        # 1. Direct undo commands (pre-compiled pattern at module level)
        if _UNDO_RE.search(command):
            return "undo"

        # 2. Resolve "there" or "in there" to the last visited folder
        if self.last_folder:
            folder_str = str(self.last_folder)
            resolved = re.sub(r'\b(?:in\s+)?there\b', lambda m: f"in {folder_str}", resolved, flags=re.IGNORECASE)
            resolved = re.sub(r'\bthat\s+folder\b', lambda m: f"folder {folder_str}", resolved, flags=re.IGNORECASE)

        # 3. Resolve "this file", "that file", "same file"
        if self.last_file:
            file_str = str(self.last_file)
            resolved = re.sub(r'\b(?:this|that|same)\s+file\b', lambda m: f"file {file_str}", resolved, flags=re.IGNORECASE)
            # Replace " it " with full file path when referencing an operation
            resolved = re.sub(r'\b(delete|open|close|rename|copy|move|run|inspect|clean|format)\s+it\b', lambda m: f"{m.group(1)} {file_str}", resolved, flags=re.IGNORECASE)

        # 4. Resolve "the other file"
        if len(self.recent_modified_files) >= 2 and self.last_file:
            other_file = [f for f in self.recent_modified_files if f != self.last_file][-1]
            resolved = re.sub(r'\bthe\s+other\s+file\b', lambda m: f"file {other_file}", resolved, flags=re.IGNORECASE)

        # 5. Resolve "that function", "this function", "same function"
        if self.last_symbol:
            sym = self.last_symbol
            resolved = re.sub(r'\b(?:this|that|same)\s+function\b', lambda m: f"function {sym}", resolved, flags=re.IGNORECASE)
            resolved = re.sub(r'\b(?:this|that|same)\s+symbol\b', lambda m: f"symbol {sym}", resolved, flags=re.IGNORECASE)

        return resolved

    def get_recent_history(self, limit: int = 6) -> List[Dict[str, str]]:
        """Returns recent conversation turns formatted for LLM context."""
        recent = list(self.history)[-limit:] if len(self.history) > limit else list(self.history)
        return [{"role": "user" if t.speaker == "user" else "assistant", "content": t.text} for t in recent]

    def get_memory_context_dict(self) -> Dict[str, Any]:
        """Provides a structured dictionary of recent memory for prompt building."""
        return {
            "last_workspace": str(self.last_workspace) if self.last_workspace else None,
            "last_file": str(self.last_file) if self.last_file else None,
            "last_symbol": self.last_symbol,
            "last_error": self.last_error_message,
            "last_patch_summary": self.last_code_patch.get("explanation") if self.last_code_patch else None,
            "recent_files": [str(f) for f in self.recent_modified_files[-3:]]
        }

    def clear(self) -> None:
        self.history.clear()
        self.last_workspace = None
        self.last_folder = None
        self.last_file = None
        self.last_app = None
        self.last_symbol = None
        self.last_action_type = None
        self.last_error_message = None
        self.last_code_patch = None
        self.recent_modified_files.clear()
        self.undo_stack.clear()
