import re
from pathlib import Path
from typing import Optional
from app.ai.base import AIProvider
from app.core.models import AgentAction, AgentPlan, ScreenContext
from app.logging.logger import logger


class LocalHeuristicPlanner(AIProvider):
    """
    Offline heuristic natural language parser.
    Understands complex conversational phrasing, relative instructions, and code edits
    without making external API requests.
    """

    def is_available(self) -> bool:
        return True

    def plan(self, command: str, context: ScreenContext) -> AgentPlan:
        lower = command.lower().strip()

        # 0. Deterministic voice edit parser delegation
        from app.editor.code_edit_parser import parse_voice_edit
        parsed = parse_voice_edit(command)
        if parsed:
            return AgentPlan(
                reply=parsed.summary,
                actions=[
                    AgentAction(
                        type="vscode_edit",
                        instruction=parsed.summary,
                        text=parsed.token,
                        line_number=parsed.line_number or None
                    )
                ]
            )

        # 1. Code modification requests
        # e.g. "Edit line 25 in app.py and change the function name calculate_total to calculate_price"
        rename_func = re.search(r'change\s+(?:the\s+)?function\s+(?:name\s+)?([a-zA-Z0-9_]+)\s+to\s+([a-zA-Z0-9_]+)', lower)
        if rename_func:
            old_name = rename_func.group(1).strip()
            new_name = rename_func.group(2).strip()
            return AgentPlan(
                reply=f"Changing function name '{old_name}' to '{new_name}'.",
                actions=[
                    AgentAction(
                        type="vscode_edit",
                        instruction=f"Rename function {old_name} to {new_name}",
                        text=f"RENAME_FUNC:{old_name}:{new_name}"
                    )
                ]
            )

        # e.g. "At line 30, add a try except block around the database call"
        try_except = re.search(r'(?:at|on|around)\s+line\s+(\d+).*?(?:add|wrap).*?(?:try\s+except|exception\s+handling)', lower)
        if try_except:
            line_num = int(try_except.group(1))
            return AgentPlan(
                reply=f"Adding try-except error handling around line {line_num}.",
                actions=[
                    AgentAction(
                        type="vscode_edit",
                        line_number=line_num,
                        instruction=f"Add try-except block at line {line_num}",
                        text="ADD_TRY_EXCEPT"
                    )
                ]
            )

        # e.g. "Add error handling to this function"
        if "error handling" in lower or "try except" in lower:
            return AgentPlan(
                reply="Adding error handling to the active function.",
                actions=[
                    AgentAction(
                        type="vscode_edit",
                        instruction="Add try except error handling",
                        text="ADD_TRY_EXCEPT"
                    )
                ]
            )

        # 2. Conversational file operations:
        # e.g. "Can you make a folder named college stuff on my desktop?"
        make_folder = re.search(r'(?:can\s+you\s+)?(?:make|create)\s+(?:a\s+)?folder\s+(?:named|called)\s+(.*?)\s+on\s+(?:my\s+)?(desktop|downloads|documents)', lower)
        if make_folder:
            name = make_folder.group(1).strip()
            dest = make_folder.group(2).strip()
            full_path = f"{name} on {dest}"
            return AgentPlan(
                reply=f"Creating folder '{name}' on your {dest.capitalize()}.",
                actions=[AgentAction(type="create_folder", path=full_path)]
            )

        # e.g. "Move the resume from Downloads to Documents"
        move_complex = re.search(r'move\s+(?:the\s+)?(.*?)\s+from\s+(.*?)\s+to\s+(.*?)$', lower)
        if move_complex:
            item = move_complex.group(1).strip()
            src = move_complex.group(2).strip()
            dst = move_complex.group(3).strip()
            return AgentPlan(
                reply=f"Moving {item} from {src} to {dst}.",
                actions=[AgentAction(type="move_path", path=f"{item} in {src}", destination=dst)]
            )

        # e.g. "Move all Python files to the project folder"
        move_all_py = re.search(r'move\s+all\s+python\s+files\s+to\s+(.*?)$', lower)
        if move_all_py:
            dst = move_all_py.group(1).strip()
            return AgentPlan(
                reply=f"Moving Python files to {dst}.",
                actions=[AgentAction(type="move_path", path="*.py", destination=dst)]
            )

        # 3. Contextual queries:
        # e.g. "Open the PDF there" (resolved by memory to folder, or active explorer)
        open_pdf_there = re.search(r'open\s+(?:the\s+)?(pdf|document|file)\s+(?:in\s+)?(.*?)$', lower)
        if open_pdf_there:
            ext = open_pdf_there.group(1).strip()
            loc = open_pdf_there.group(2).strip()
            return AgentPlan(
                reply=f"Searching for {ext} in {loc}.",
                actions=[AgentAction(type="find_file", query=f"*.{ext}", scope=loc)]
            )

        # Save file — catches "save the file main.py", "save main.py", "save this file"
        save_m = re.search(r'^save\b', lower)
        if save_m:
            return AgentPlan(
                reply="Saving the active file.",
                actions=[AgentAction(type="save")]
            )

        # Open in VS Code — catches "open calc.py in vscode", "open practical in vscode", "open folder practical in vscode"
        open_in_vscode_m = re.search(r'^(?:open|launch|start)\s+(.*?)\s+(?:in|inside|on)\s+vs\s*code[.!?]*$', lower) or \
                           re.search(r'^(?:open|launch|start)\s+(?:in|inside|on)\s+vs\s*code\s+(.*?)[.!?]*$', lower)
        if open_in_vscode_m:
            target = open_in_vscode_m.group(1).strip().strip("'\" ")
            clean_tgt = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', target, flags=re.IGNORECASE).strip()
            clean_tgt = re.sub(r'\s+(?:folder|directory|project|workspace|file)$', '', clean_tgt, flags=re.IGNORECASE).strip() or target
            clean_tgt = clean_tgt.strip("'\" ")
            display_name = clean_tgt
            target_path = clean_tgt
            try:
                from app.platform_layer.factory import platform_adapter
                resolved = platform_adapter.resolve_spoken_path(clean_tgt)
                if resolved and resolved.exists():
                    display_name = resolved.name
                elif "\\" in clean_tgt or "/" in clean_tgt:
                    display_name = Path(clean_tgt).name or clean_tgt
                elif clean_tgt.split():
                    display_name = clean_tgt.split()[-1]
            except Exception:
                display_name = Path(clean_tgt).name or clean_tgt
            return AgentPlan(
                reply=f"Opening {display_name} in VS Code.",
                actions=[AgentAction(type="vscode_open_file", path=target_path)]
            )

        # Open a folder or project: "open folder practical", "open project practical", "open directory practical"
        open_folder_m = re.search(r'^(?:open|show)\s+(?:the\s+)?(?:folder|directory|project|workspace)\s+(?:called\s+|named\s+)?(.*?)[.!?]*$', lower) or \
                        re.search(r'^(?:open|show)\s+(?:the\s+)?(.*?)\s+(?:folder|directory|project|workspace)[.!?]*$', lower)
        if open_folder_m:
            target_f = open_folder_m.group(1).strip().strip("'\" ")
            clean_f = re.sub(r'^(?:(?:the|my)\s+)?(?:folder|directory|project|workspace)\s+', '', target_f, flags=re.IGNORECASE).strip() or target_f
            clean_f = clean_f.strip("'\" ")
            display_name = clean_f
            target_path = clean_f
            try:
                from app.platform_layer.factory import platform_adapter
                resolved = platform_adapter.resolve_spoken_path(clean_f)
                if resolved and resolved.exists():
                    display_name = resolved.name
                elif "\\" in clean_f or "/" in clean_f:
                    display_name = Path(clean_f).name or clean_f
                elif clean_f.split():
                    display_name = clean_f.split()[-1]
            except Exception:
                display_name = Path(clean_f).name or clean_f
            return AgentPlan(
                reply=f"Opening folder {display_name}.",
                actions=[AgentAction(type="open_folder", path=target_path)]
            )

        # Open a specific file by name — catches "open file main.py", "open notes.txt"
        open_file_m = re.search(
            r'^(?:open|launch|start)\s+(?:(?:the|my)\s+)?(?:file\s+)?([^\s].+?\.[a-zA-Z0-9]{1,6})\s*$',
            lower
        )
        if open_file_m:
            fname = open_file_m.group(1).strip()
            return AgentPlan(
                reply=f"Opening {fname}.",
                actions=[AgentAction(type="open_file", path=fname)]
            )

        # Show / read line: e.g. "show line 36", "read line 12", "shoreline 22", "what's on line 5"
        show_line_m = re.search(r'\b(?:show(?:\s+me)?|read(?:\s+me)?|shoreline|showline|sureline|display|view|what(?:\'s|\s+is)\s+(?:on|at))\s+(?:line\s+)?([a-zA-Z0-9\s-]+?)(?:\s+in\s+([^\s]+\.[a-zA-Z0-9]{1,6}))?[.!?]*$', lower)
        if show_line_m:
            from app.editor.code_edit_parser import _parse_line_number
            ln = _parse_line_number(show_line_m.group(1).strip())
            target_f = show_line_m.group(2).strip() if show_line_m.group(2) else None
            if ln:
                verb_reply = "Showing" if re.search(r'\b(?:show|display|view|shoreline|showline)\b', lower) else "Reading"
                file_hint = f" of {target_f}" if target_f else ""
                return AgentPlan(
                    reply=f"{verb_reply} line {ln}{file_hint}.",
                    actions=[AgentAction(type="vscode_read_line", line_number=ln, path=target_f)]
                )

        # Jump / navigate line: e.g. "go to line 25", "jump to line 40"
        jump_line_m = re.search(r'\b(?:go\s+to|jump\s+to|navigate\s+to)\s+line\s+([a-zA-Z0-9\s-]+?)[.!?]*$', lower)
        if jump_line_m:
            from app.editor.code_edit_parser import _parse_line_number
            ln = _parse_line_number(jump_line_m.group(1).strip())
            if ln:
                return AgentPlan(
                    reply=f"Going to line {ln}.",
                    actions=[AgentAction(type="vscode_jump_line", line_number=ln)]
                )

        # Guard: If command has coding or editor intent (e.g. line numbers, edit verbs),
        # DO NOT fall back to Google Search.
        code_markers = [
            r'\bline\s*\d+\b',
            r'\binline\s*\d+\b',
            r'\bshoreline\b',
            r'\bshowline\b',
            r'\bsureline\b',
            r'\bline\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\b',
            r'\b(?:replace|overwrite|rewrite|delete\s+line|remove\s+line|comment\s+line|uncomment\s+line|insert\s+after|insert\s+before)\b',
        ]
        if any(re.search(pat, lower) for pat in code_markers):
            logger.info(f"Local heuristic detected unparsed code edit attempt: '{command}'. Preventing web search fallback.")
            line_m = re.search(r'\b(?:line|inline)\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\b', lower)
            line_hint = f" on line {line_m.group(1)}" if line_m else ""
            return AgentPlan(
                reply=f"I heard a code edit command{line_hint}, but couldn't parse the target text. For example, say: 'in line 36 replace old with new' or 'line 36 replace with new content'.",
                actions=[]
            )

        # Default fallback to web search on Google
        logger.info(f"Local heuristic falling back to web search for: '{command}'")
        search_query = re.sub(r'^(?:can\s+you\s+|please\s+|tell\s+me\s+)?', '', command, flags=re.IGNORECASE).strip()
        if not search_query:
            search_query = command.strip()

        return AgentPlan(
            reply=f"Searching the web for '{search_query}'.",
            actions=[AgentAction(type="web_search", query=search_query, scope="google")]
        )
