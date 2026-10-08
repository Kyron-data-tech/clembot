"""
app/editor/code_edit_parser.py

Parses natural-language voice commands into structured code-edit tokens that the
ActionRouter can execute directly on a file without an AI round-trip.

Token format (stored in AgentAction.text):
    REPLACE_IN_LINE:{line}:{old}::{new}   — replace first occurrence of <old> with <new> on line N
    REPLACE_ALL_IN_LINE:{line}:{old}::{new} — replace all occurrences on line N
    REPLACE_LINE:{line}::{new_text}       — overwrite entire line N
    DELETE_LINE:{line}                    — delete line N
    DELETE_LINES:{start}:{end}            — delete lines start..end (inclusive)
    INSERT_AFTER:{line}::{text}           — insert a new line after line N
    INSERT_BEFORE:{line}::{text}          — insert a new line before line N
    COMMENT_LINE:{line}                   — comment out line N (adds # / //)
    UNCOMMENT_LINE:{line}                 — remove leading comment char from line N
    RENAME_FUNC:{old}:{new}              — rename function (whole-file, already supported)
    ADD_TRY_EXCEPT:{line}                — wrap line N in try/except

The separator "::" is used between the line/params and the text payload to avoid
ambiguity when the text itself contains colons.
"""

import re
from dataclasses import dataclass
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParsedEditCommand:
    token: str          # The full token string for AgentAction.text
    line_number: int    # Primary line number (0 if not applicable)
    summary: str        # Human-readable description for TTS reply
    needs_confirmation: bool = False


# ---------------------------------------------------------------------------
# Spoken numbers parser
# ---------------------------------------------------------------------------

_WORD_NUMS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _parse_line_number(raw: str) -> Optional[int]:
    """
    Convert a spoken or digit line reference to an integer.
    Supports single digits ('6'), digit strings ('43'), single words ('six'),
    compound spoken numbers ('thirty six', 'forty three', 'twenty one', 'thirty-six'),
    and strings with leading line words ('line 6', 'inline 43', 'at line 10').
    """
    if not raw:
        return None
    raw = raw.strip().lower()
    # Strip any leading prepositions or line prefixes
    raw = re.sub(r'^(?:in\s*line|on\s*line|at\s*line|for\s*line|to\s*line|from\s*line|line|inline)\s*', '', raw).strip()
    raw = raw.replace('-', ' ')
    if raw.isdigit():
        return int(raw)

    words = [w for w in raw.split() if w != "and"]
    if not words:
        return None

    if len(words) == 1:
        return _WORD_NUMS.get(words[0])

    val = 0
    current = 0
    valid = False
    for w in words:
        if w.isdigit():
            current += int(w)
            valid = True
        elif w in _WORD_NUMS:
            num = _WORD_NUMS[w]
            if num >= 20 and current < 20 and current > 0:
                val += current
                current = num
            else:
                current += num
            valid = True
        elif w == "hundred":
            current = (current or 1) * 100
            valid = True
        elif w == "thousand":
            val += (current or 1) * 1000
            current = 0
            valid = True
        else:
            return None
    val += current
    return val if valid else None


def _clean_spoken_qualifier(text: str) -> str:
    """Strip trailing and leading spoken qualifiers like 'keyword', 'word', 'text', 'thing', 'value', quotes."""
    text = text.strip()
    text = re.sub(
        r'\s+(?:keyword|word|text|thing|value|variable|identifier|token|character|char|string)$',
        '', text, flags=re.IGNORECASE
    ).strip()
    text = re.sub(
        r'^(?:the\s+)?(?:keyword|word|text|variable|identifier|token|character|char|string)\s+',
        '', text, flags=re.IGNORECASE
    ).strip()
    return text.strip("'\"`")


def parse_voice_edit(command: str) -> Optional[ParsedEditCommand]:
    """
    Attempts to parse a voice edit command.
    Returns a ParsedEditCommand on success, None if the command is not
    a recognised deterministic edit (caller should fall back to AI / heuristic).
    """
    cmd = command.strip()
    if not cmd:
        return None

    # Line prefix regex capturing 1 or 2 words (e.g. "36", "thirty six", "forty-three")
    # Matches "in line 36", "line 36", "inline 43", "on line 10", "at line 5", "for line 9"
    LP = r'^(?:(?:in|on|at|for|from)?\s*(?:line|inline)\s*|inline\s*)(\w+(?:[\s-]+\w+)?)\s+'

    # 1. DELETE LINE(S)
    # delete lines N to M / N through M / N and M
    m = re.search(
        r'^(?:delete|remove|erase|drop|get\s+rid\s+of)\s+(?:the\s+)?lines?\s+(\w+(?:[\s-]+\w+)?)\s+(?:to|through|and|-)\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m:
        s = _parse_line_number(m.group(1))
        e = _parse_line_number(m.group(2))
        if s and e:
            return ParsedEditCommand(
                token=f"DELETE_LINES:{s}:{e}",
                line_number=s,
                summary=f"Lines {s} to {e} deleted.",
                needs_confirmation=True
            )

    # delete line N / remove line N / drop line N / get rid of line N / delete this line / delete current line
    m = re.search(
        r'^(?:delete|remove|erase|drop|get\s+rid\s+of)\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$',
        cmd, re.IGNORECASE
    )
    if not m:
        m = re.search(LP + r'(?:delete|remove|erase|drop|get\s+rid\s+of)[.!?]*$', cmd, re.IGNORECASE)
    if m:
        raw_ln = m.group(1) if m.lastindex else None
        if raw_ln and raw_ln.lower() in ("this", "current"):
            return ParsedEditCommand(
                token="DELETE_LINE:0",
                line_number=0,
                summary="Line deleted.",
                needs_confirmation=True
            )
        if not raw_ln:
            if re.search(r'\b(?:this|current)\s+line\b', cmd, re.IGNORECASE):
                return ParsedEditCommand(
                    token="DELETE_LINE:0",
                    line_number=0,
                    summary="Line deleted.",
                    needs_confirmation=True
                )
            ln = None
        else:
            ln = _parse_line_number(raw_ln)
        if ln:
            return ParsedEditCommand(
                token=f"DELETE_LINE:{ln}",
                line_number=ln,
                summary=f"Line {ln} deleted.",
                needs_confirmation=True
            )

    # 2. COMMENT / UNCOMMENT LINE
    m = re.search(
        r'^(?:comment\s+out|comment)\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$',
        cmd, re.IGNORECASE
    )
    if not m:
        m = re.search(LP + r'(?:comment\s+out|comment)[.!?]*$', cmd, re.IGNORECASE)
    if m:
        raw_ln = m.group(1) if m.lastindex else None
        if not raw_ln or raw_ln.lower() in ("this", "the", "current"):
            return ParsedEditCommand(
                token="COMMENT_LINE:0",
                line_number=0,
                summary="Line commented."
            )
        ln = _parse_line_number(raw_ln)
        if ln:
            return ParsedEditCommand(
                token=f"COMMENT_LINE:{ln}",
                line_number=ln,
                summary=f"Line {ln} commented."
            )

    m = re.search(
        r'^(?:uncomment\s+out|uncomment)\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$',
        cmd, re.IGNORECASE
    )
    if not m:
        m = re.search(LP + r'(?:uncomment\s+out|uncomment)[.!?]*$', cmd, re.IGNORECASE)
    if m:
        raw_ln = m.group(1) if m.lastindex else None
        if not raw_ln or raw_ln.lower() in ("this", "the", "current"):
            return ParsedEditCommand(
                token="UNCOMMENT_LINE:0",
                line_number=0,
                summary="Line uncommented."
            )
        ln = _parse_line_number(raw_ln)
        if ln:
            return ParsedEditCommand(
                token=f"UNCOMMENT_LINE:{ln}",
                line_number=ln,
                summary=f"Line {ln} uncommented."
            )

    # 3. WORD / TOKEN REPLACEMENT IN LINE (Paraphrases & Restatements)
    # Verbs: replace, change, swap, substitute, switch, update, modify
    # Connectors: with, to, by, from, into, for, as
    VERBS = r'(?:replace|change|swap|substitute|switch|update|modify)'
    CONNS = r'(?:with|to|by|from|into|for|as)'

    # 3a. Inverted: replace from <old> with/to <new>
    # e.g. "in line 36 replace from with to what", "line 36 replace from foo to bar"
    m = re.search(LP + r'(?:replace|change|swap)\s+from\s+(.+?)\s+(?:to|with|into)\s+(.+?)[.!?]*$', cmd, re.IGNORECASE)
    if m:
        ln = _parse_line_number(m.group(1))
        old = _clean_spoken_qualifier(m.group(2))
        new = m.group(3).strip().rstrip('.!?')
        if ln and old and new:
            return ParsedEditCommand(
                token=f"REPLACE_IN_LINE:{ln}:{old}::{new}",
                line_number=ln,
                summary=f"Replacing '{old}' with '{new}' on line {ln}."
            )

    # 3b. Inverted: replace with <new> from <old>
    # e.g. "in line 36 replace with what from with"
    m = re.search(LP + r'replace\s+with\s+(.+?)\s+from\s+(.+?)[.!?]*$', cmd, re.IGNORECASE)
    if m:
        ln = _parse_line_number(m.group(1))
        new = m.group(2).strip().rstrip('.!?')
        old = _clean_spoken_qualifier(m.group(3))
        if ln and old and new:
            return ParsedEditCommand(
                token=f"REPLACE_IN_LINE:{ln}:{old}::{new}",
                line_number=ln,
                summary=f"Replacing '{old}' with '{new}' on line {ln}."
            )

    # 3c. Leading line reference: [in] line N <verb> [the] <old> <connector> <new>
    # e.g. "in line 36 replace with from what"
    #      "inline 43 replace I with J"
    #      "line 36 swap foo and bar"
    #      "at line 36 substitute with by what"
    #      "on line 10 change x to y"
    m = re.search(LP + VERBS + r'\s+(?:the\s+)?(.+?)\s+' + CONNS + r'\s+(.+?)[.!?]*$', cmd, re.IGNORECASE)
    if m:
        ln = _parse_line_number(m.group(1))
        old = _clean_spoken_qualifier(m.group(2))
        new = m.group(3).strip().rstrip('.!?')

        # Check safety fallback if old refers to entire line
        if old.lower() in ("content", "the content", "code", "the code", "text", "the text", "everything", "the line", "whole line", "entire line"):
            if ln and new:
                return ParsedEditCommand(
                    token=f"REPLACE_LINE:{ln}::{new}",
                    line_number=ln,
                    summary=f"Replacing line {ln} with: {new}"
                )

        if ln and old and new:
            return ParsedEditCommand(
                token=f"REPLACE_IN_LINE:{ln}:{old}::{new}",
                line_number=ln,
                summary=f"Replaced on line {ln}."
            )

    # 3d. Post-position line reference: <verb> [the] <old> <connector> <new> [in/on/at] line N
    # e.g. "replace I with J on line 43"
    #      "replace with from what in line 36"
    #      "change foo to bar at line 10"
    m = re.search(
        r'^' + VERBS + r'\s+(?:the\s+)?(.+?)\s+' + CONNS + r'\s+(.+?)\s+(?:in|on|at|for|from)?\s*(?:line|inline)\s*(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m:
        old = _clean_spoken_qualifier(m.group(1))
        new = m.group(2).strip().rstrip('.!?')
        ln = _parse_line_number(m.group(3))

        if old.lower() in ("content", "the content", "code", "the code", "text", "the text", "everything", "the line", "whole line", "entire line"):
            if ln and new:
                return ParsedEditCommand(
                    token=f"REPLACE_LINE:{ln}::{new}",
                    line_number=ln,
                    summary=f"Line {ln} replaced."
                )

        if ln and old and new:
            return ParsedEditCommand(
                token=f"REPLACE_IN_LINE:{ln}:{old}::{new}",
                line_number=ln,
                summary=f"Replaced on line {ln}."
            )

    # 4. REPLACE ENTIRE LINE (Paraphrases & Rewordings)
    # Examples:
    # "replace line 20 with x = 5"
    # "change line 12 in config.py to DEBUG = True"
    # "make line 12 say DEBUG = True"
    # "on line 12 put DEBUG = True"
    # "change line 12 to DEBUG = True"
    # "update line 12 to DEBUG = True"
    # "fix line 12 with DEBUG = True"
    # "put x = 5 on line 20"
    m_file_line = re.search(
        r'^(?:change|replace|update|fix|modify)\s+line\s+(\w+(?:[\s-]+\w+)?)\s+in\s+([^\s]+\.[a-zA-Z0-9]{1,6})\s+(?:to|with|as)\s+(.+?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_file_line:
        ln = _parse_line_number(m_file_line.group(1))
        new_text = m_file_line.group(3).strip().rstrip('.!?')
        if ln and new_text:
            return ParsedEditCommand(
                token=f"REPLACE_LINE:{ln}::{new_text}",
                line_number=ln,
                summary=f"Line {ln} replaced."
            )

    line_replace_patterns = [
        # make line N say <text> / make line N <text>
        r'^make\s+line\s+(\w+(?:[\s-]+\w+)?)\s+(?:say\s+|be\s+)?(.+?)[.!?]*$',
        # on/in/at line N put/write/add/set <text>
        r'^(?:on|in|at)\s+line\s+(\w+(?:[\s-]+\w+)?)\s+(?:put|write|add|set)\s+(.+?)[.!?]*$',
        # on line N make it <text> / on line N make line say <text>
        r'^(?:on|in|at)\s+line\s+(\w+(?:[\s-]+\w+)?)\s+make\s+(?:it\s+|line\s+)?(?:say\s+|be\s+)?(.+?)[.!?]*$',
        # update/fix/modify line N with/to <text>
        r'^(?:update|fix|modify)\s+line\s+(\w+(?:[\s-]+\w+)?)\s+(?:with|to|as)\s+(.+?)[.!?]*$',
        # replace/change/overwrite/rewrite/set [entire/whole] line N with/to/as ...
        r'^(?:replace|rewrite|overwrite|set|change)\s+(?:(?:the\s+)?(?:entire|whole)\s+)?line\s+(\w+(?:[\s-]+\w+)?)\s+(?:with|to|as)\s+(.+?)[.!?]*$',
        # change/replace the content in/of line N to/with/as ...
        r'^(?:change|replace|rewrite|set|update)\s+(?:the\s+)?(?:content|code|text)\s+(?:in|of|at|on|for)\s+line\s+(\w+(?:[\s-]+\w+)?)\s+(?:to|with|as)\s+(.+?)[.!?]*$',
        # [in] line N change/replace [the] [whole line / content / code / text] to/with/as ...
        LP + r'(?:change|replace|rewrite|set|update|overwrite)\s+(?:the\s+)?(?:(?:whole|entire)\s+line|(?:content|code|text))\s+(?:to|with|as)\s+(.+?)[.!?]*$',
        # [in] line N change/set/replace/overwrite/rewrite [it] to/with/as ...
        LP + r'(?:change|set|replace|overwrite|rewrite)\s+(?:it\s+)?(?:to|with|as)\s+(.+?)[.!?]*$',
        # [in] line N make it ...
        LP + r'make\s+(?:it\s+)?(.+?)[.!?]*$',
        # put <new_text> in/on/at line N
        r'^put\s+(.+?)\s+(?:in|on|at)\s+line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
    ]
    for pat in line_replace_patterns:
        m = re.search(pat, cmd, re.IGNORECASE)
        if m:
            if pat.startswith('^put'):
                new_text = m.group(1).strip().rstrip('.!?')
                ln = _parse_line_number(m.group(2))
            else:
                ln = _parse_line_number(m.group(1))
                new_text = m.group(2).strip().rstrip('.!?')
            if ln and new_text:
                return ParsedEditCommand(
                    token=f"REPLACE_LINE:{ln}::{new_text}",
                    line_number=ln,
                    summary=f"Line {ln} replaced."
                )

    # 5. INSERT BLANK / NEW LINE BELOW OR ABOVE
    # "Insert a new line below line 8" / "Add a new line below line 8"
    m_new_below = re.search(
        r'^(?:insert|add)\s+(?:a\s+)?(?:new\s+)?line\s+(?:below|after)\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_new_below:
        ln = _parse_line_number(m_new_below.group(1))
        if ln:
            return ParsedEditCommand(
                token=f"INSERT_AFTER:{ln}::",
                line_number=ln,
                summary="New line added."
            )

    # "Insert a new line above line 8" / "Add a new line above line 8"
    m_new_above = re.search(
        r'^(?:insert|add)\s+(?:a\s+)?(?:new\s+)?line\s+(?:above|before)\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_new_above:
        ln = _parse_line_number(m_new_above.group(1))
        if ln:
            return ParsedEditCommand(
                token=f"INSERT_BEFORE:{ln}::",
                line_number=ln,
                summary="New line added."
            )

    # "Add text at the end of line 9"
    m_add_end = re.search(
        r'^(?:add|insert|append)\s+(.+?)\s+at\s+(?:the\s+)?end\s+of\s+line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_add_end:
        text = m_add_end.group(1).strip().rstrip('.!?')
        ln = _parse_line_number(m_add_end.group(2))
        if ln and text:
            return ParsedEditCommand(
                token=f"APPEND_TO_LINE:{ln}::{text}",
                line_number=ln,
                summary="Added."
            )

    # ADD TRY-EXCEPT (check before generic add at line)
    m_try = re.search(
        r'^(?:add\s+(?:a\s+)?try\s*(?:except|catch)|wrap\s+.*?in\s+(?:a\s+)?(?:try|error\s+handling)).*?(?:at\s+line\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_try:
        ln = _parse_line_number(m_try.group(1)) if m_try.group(1) else 1
        return ParsedEditCommand(
            token=f"ADD_TRY_EXCEPT:{ln}",
            line_number=ln,
            summary=f"Wrapping line {ln} in a try-except block."
        )

    # "Add import os at line 1" / "Add <text> at line N"
    m_add_at_line = re.search(
        r'^(?:insert|add)\s+(.+?)\s+at\s+line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_add_at_line:
        text = m_add_at_line.group(1).strip().rstrip('.!?')
        ln = _parse_line_number(m_add_at_line.group(2))
        if ln and text:
            summary = "Import added." if "import" in text.lower() else "New line added."
            return ParsedEditCommand(
                token=f"INSERT_BEFORE:{ln}::{text}",
                line_number=ln,
                summary=summary
            )

    # 6. INSERT AFTER LINE (with content)
    # "insert print hello after line 5"
    m_after_normal = re.search(
        r'^(?:insert|add)\s+(?:a\s+)?(?:new\s+)?(?:line\s+)?(.+?)\s+after\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_after_normal:
        raw_text = m_after_normal.group(1)
        raw_ln = m_after_normal.group(2)
    else:
        m_after_inv1 = re.search(
            r'^(?:after\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?))\s+(?:add|insert)\s+(?:a\s+)?(?:new\s+line\s+)?(?:saying\s+|with\s+)?(.+?)[.!?]*$',
            cmd, re.IGNORECASE
        )
        if m_after_inv1:
            raw_ln = m_after_inv1.group(1)
            raw_text = m_after_inv1.group(2)
        else:
            m_after_inv2 = re.search(
                r'^(?:insert|add)\s+after\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)\s*(?::|\s+saying|\s+with)?\s+(.+?)[.!?]*$',
                cmd, re.IGNORECASE
            )
            if m_after_inv2:
                raw_ln = m_after_inv2.group(1)
                raw_text = m_after_inv2.group(2)
            else:
                raw_ln = None
                raw_text = None

    if raw_ln and raw_text:
        text = re.sub(r'^(?:saying|with\s*:)\s*', '', raw_text.strip(), flags=re.IGNORECASE).strip().rstrip('.!?')
        ln = _parse_line_number(raw_ln)
        if ln and text:
            return ParsedEditCommand(
                token=f"INSERT_AFTER:{ln}::{text}",
                line_number=ln,
                summary="New line added."
            )

    # 7. INSERT BEFORE LINE (with content)
    m_before_normal = re.search(
        r'^(?:insert|add)\s+(?:a\s+)?(?:new\s+)?(?:line\s+)?(.+?)\s+before\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$',
        cmd, re.IGNORECASE
    )
    if m_before_normal:
        raw_text = m_before_normal.group(1)
        raw_ln = m_before_normal.group(2)
    else:
        m_before_inv1 = re.search(
            r'^(?:before\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?))\s+(?:add|insert)\s+(?:a\s+)?(?:new\s+line\s+)?(?:saying\s+|with\s+)?(.+?)[.!?]*$',
            cmd, re.IGNORECASE
        )
        if m_before_inv1:
            raw_ln = m_before_inv1.group(1)
            raw_text = m_before_inv1.group(2)
        else:
            m_before_inv2 = re.search(
                r'^(?:insert|add)\s+before\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)\s*(?::|\s+saying|\s+with)?\s+(.+?)[.!?]*$',
                cmd, re.IGNORECASE
            )
            if m_before_inv2:
                raw_ln = m_before_inv2.group(1)
                raw_text = m_before_inv2.group(2)
            else:
                raw_ln = None
                raw_text = None

    if raw_ln and raw_text:
        text = re.sub(r'^(?:saying|with\s*:)\s*', '', raw_text.strip(), flags=re.IGNORECASE).strip().rstrip('.!?')
        ln = _parse_line_number(raw_ln)
        if ln and text:
            return ParsedEditCommand(
                token=f"INSERT_BEFORE:{ln}::{text}",
                line_number=ln,
                summary="New line added."
            )

    # 8. LINE REORGANIZATION & MANIPULATION
    # "Duplicate line 25" / "Duplicate this line" / "Duplicate line"
    m_dup = re.search(r'^(?:duplicate|clone)\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$', cmd, re.IGNORECASE)
    if m_dup:
        raw_ln = m_dup.group(1) if m_dup.lastindex else None
        if not raw_ln or raw_ln.lower() in ("this", "the", "current"):
            return ParsedEditCommand(token="DUPLICATE_LINE:0", line_number=0, summary="Line duplicated.")
        ln = _parse_line_number(raw_ln)
        if ln:
            return ParsedEditCommand(token=f"DUPLICATE_LINE:{ln}", line_number=ln, summary="Line duplicated.")

    # "Move line 40 up / down" / "Move line up" / "Move this line up"
    m_move = re.search(r'^move\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?\s+(up|down)[.!?]*$', cmd, re.IGNORECASE)
    if m_move:
        raw_ln = m_move.group(1) if m_move.group(1) else None
        direction = m_move.group(2).lower()
        if not raw_ln or raw_ln.lower() in ("this", "the", "current"):
            tok = "MOVE_LINE_UP:0" if direction == "up" else "MOVE_LINE_DOWN:0"
            return ParsedEditCommand(token=tok, line_number=0, summary="Line moved.")
        ln = _parse_line_number(raw_ln)
        if ln:
            tok = f"MOVE_LINE_UP:{ln}" if direction == "up" else f"MOVE_LINE_DOWN:{ln}"
            return ParsedEditCommand(token=tok, line_number=ln, summary="Line moved.")

    # "Indent line 12" / "Outdent line 12"
    m_indent = re.search(r'^(indent|outdent)\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$', cmd, re.IGNORECASE)
    if m_indent:
        act = m_indent.group(1).lower()
        raw_ln = m_indent.group(2) if m_indent.lastindex >= 2 else None
        ln = _parse_line_number(raw_ln) if raw_ln else 0
        tok = f"INDENT_LINE:{ln}" if act == "indent" else f"OUTDENT_LINE:{ln}"
        rep = "Indented." if act == "indent" else "Outdented."
        return ParsedEditCommand(token=tok, line_number=ln, summary=rep)

    # "Select line 18" / "Select this line" / "Select line"
    m_sel = re.search(r'^select\s+(?:the\s+|this\s+|current\s+)?line(?:\s+(\w+(?:[\s-]+\w+)?))?[.!?]*$', cmd, re.IGNORECASE)
    if m_sel:
        raw_ln = m_sel.group(1) if m_sel.lastindex else None
        if not raw_ln or raw_ln.lower() in ("this", "the", "current"):
            return ParsedEditCommand(token="SELECT_LINE:0", line_number=0, summary="Line selected.")
        ln = _parse_line_number(raw_ln)
        if ln:
            return ParsedEditCommand(token=f"SELECT_LINE:{ln}", line_number=ln, summary="Line 18 selected." if ln == 18 else f"Line {ln} selected.")

    # "Copy line 18"
    m_copy = re.search(r'^copy\s+(?:the\s+)?line\s+(\w+(?:[\s-]+\w+)?)[.!?]*$', cmd, re.IGNORECASE)
    if m_copy:
        ln = _parse_line_number(m_copy.group(1))
        if ln:
            return ParsedEditCommand(token=f"COPY_LINE:{ln}", line_number=ln, summary="Copied.")

    # 9. REFACTORING & WHOLE-FILE ACTIONS
    # "Rename variable x to total"
    m_ren_var = re.search(r'^(?:rename|change)\s+(?:the\s+)?(?:variable|var)\s+(\w+)\s+to\s+(\w+)[.!?]*$', cmd, re.IGNORECASE)
    if m_ren_var:
        return ParsedEditCommand(token=f"RENAME_VAR:{m_ren_var.group(1)}:{m_ren_var.group(2)}", line_number=0, summary="Renamed.")

    # "Rename function foo to bar"
    m_ren_fn = re.search(r'^(?:rename|change)\s+(?:the\s+)?function(?:\s+name)?\s+(\w+)\s+to\s+(\w+)[.!?]*$', cmd, re.IGNORECASE)
    if m_ren_fn:
        return ParsedEditCommand(token=f"RENAME_FUNC:{m_ren_fn.group(1)}:{m_ren_fn.group(2)}", line_number=0, summary="Renamed.")

    # "Format the file"
    if re.search(r'^format\s+(?:the\s+)?(?:file|document|code)[.!?]*$', cmd, re.IGNORECASE):
        return ParsedEditCommand(token="FORMAT_FILE", line_number=0, summary="Formatted.")

    # "Find todo" / "Find in file"
    m_find = re.search(r'^(?:find|search\s+for)\s+(.+?)(?:\s+in\s+(?:the\s+)?file)?[.!?]*$', cmd, re.IGNORECASE)
    if m_find and not cmd.lower().startswith(("find file", "find my", "search for file", "search for my")):
        q = m_find.group(1).strip().rstrip('.!?')
        return ParsedEditCommand(token=f"FIND_IN_FILE:{q}", line_number=0, summary="Find open.")

    # "Replace all"
    if cmd.lower().strip(".!? ") in ["replace all", "find and replace"]:
        return ParsedEditCommand(token="REPLACE_ALL", line_number=0, summary="Find open.")

    return None
