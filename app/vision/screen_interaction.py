"""
app/vision/screen_interaction.py

Comprehensive Screen Reading, Visual Grounding, and UI Interaction Service for Clembot.
Allows Clembot to:
1. Read and describe the entire screen (active windows, text, layout, interactive elements).
2. Ground user references to on-screen elements (buttons, inputs, links, list items, files, icons).
3. Click, double-click, right-click, select, or open any displayed item on screen by voice.
4. Support multi-turn conversational grounding ("what's on my screen?" -> "click the second one").
"""

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.logging.logger import logger
from app.windows.screen_reader import ScreenReader

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None  # type: ignore[assignment]


@dataclass
class UIElement:
    name: str
    control_type: str      # button, edit, link, item, checkbox, tab, window, text, document
    x: int                 # center x pixel coordinate
    y: int                 # center y pixel coordinate
    width: int = 0
    height: int = 0
    window_title: str = ""
    raw_control: Any = None


class ScreenInteractionService:
    """
    Zero-latency, multi-tier screen reader and visual grounding engine for Clembot.
    Enables voice commands to inspect the full display and interact with anything on screen.
    """

    def __init__(self):
        self.last_elements: List[UIElement] = []
        self.last_screen_summary: str = ""
        self.last_capture_time: float = 0.0

    # -------------------------------------------------------------------------
    # 1. Inspect Visible Elements (Accessibility & UI Automation)
    # -------------------------------------------------------------------------

    def get_visible_elements(self, max_elements: int = 40) -> List[UIElement]:
        """
        Discovers visible interactive controls on screen using native OS Accessibility / UI Automation.
        Windows uses UIAutomation / Win32. macOS uses AppleScript System Events / AXUIElement.
        """
        elements: List[UIElement] = []

        if sys.platform == "win32":
            elements = self._get_windows_elements(max_elements=max_elements)
        elif sys.platform == "darwin":
            elements = self._get_macos_elements(max_elements=max_elements)

        self.last_elements = elements
        return elements

    def _get_windows_elements(self, max_elements: int = 40) -> List[UIElement]:
        elements: List[UIElement] = []
        try:
            import uiautomation as auto

            # 1. Query foreground window first
            fg = auto.GetForegroundControl()
            active_windows = [fg] if fg else []

            # 2. Also check top-level windows from desktop root
            root = auto.GetRootControl()
            if root:
                for child in root.GetChildren():
                    if child and child.ControlTypeName == "WindowControl" and child.Name:
                        rect = child.BoundingRectangle
                        if rect and (rect.right - rect.left > 100) and (rect.bottom - rect.top > 100):
                            if not any(w and getattr(w, "NativeWindowHandle", None) == child.NativeWindowHandle for w in active_windows):
                                active_windows.append(child)
                            if len(active_windows) >= 4:
                                break

            seen_keys = set()
            for win in active_windows:
                if not win:
                    continue
                win_title = win.Name or "Window"

                # Walk interesting interactive controls inside window
                interactive_types = {
                    "ButtonControl": "button",
                    "EditControl": "text input",
                    "HyperlinkControl": "link",
                    "ListItemControl": "item",
                    "DataItemControl": "item",
                    "TreeItemControl": "item",
                    "TabItemControl": "tab",
                    "CheckBoxControl": "checkbox",
                    "RadioButtonControl": "radio button",
                    "MenuItemControl": "menu item",
                    "DocumentControl": "document",
                }

                def _scan_control(ctrl, depth=0):
                    if depth > 4 or len(elements) >= max_elements:
                        return
                    try:
                        c_type = ctrl.ControlTypeName
                        name = (ctrl.Name or "").strip()
                        rect = ctrl.BoundingRectangle

                        if name and c_type in interactive_types and rect:
                            w = rect.right - rect.left
                            h = rect.bottom - rect.top
                            if w > 4 and h > 4:
                                cx = (rect.left + rect.right) // 2
                                cy = (rect.top + rect.bottom) // 2
                                key = (name.lower(), cx // 20, cy // 20)
                                if key not in seen_keys:
                                    seen_keys.add(key)
                                    elements.append(UIElement(
                                        name=name,
                                        control_type=interactive_types.get(c_type, "control"),
                                        x=cx,
                                        y=cy,
                                        width=w,
                                        height=h,
                                        window_title=win_title,
                                        raw_control=ctrl,
                                    ))

                        for ch in ctrl.GetChildren():
                            _scan_control(ch, depth + 1)
                    except Exception:
                        pass

                _scan_control(win, depth=0)
                if len(elements) >= max_elements:
                    break

        except Exception as e:
            logger.debug(f"UIAutomation element discovery encountered: {e}")

        return elements

    def _get_macos_elements(self, max_elements: int = 40) -> List[UIElement]:
        """Discovers active controls on macOS via System Events."""
        elements: List[UIElement] = []
        try:
            import subprocess
            script = """
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
                set elemList to {}
                try
                    tell frontApp
                        set uiElems to entire contents of front window
                        repeat with e in uiElems
                            try
                                set eRole to role of e
                                set eTitle to title of e
                                if eTitle is not missing value and eTitle is not "" then
                                    set ePos to position of e
                                    set eSize to size of e
                                    set end of elemList to {appName, eTitle, eRole, item 1 of ePos, item 2 of ePos, item 1 of eSize, item 2 of eSize}
                                end if
                            end try
                        end repeat
                    end tell
                end try
                return elemList
            end tell
            """
            proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3.0)
            if proc.returncode == 0 and proc.stdout.strip():
                # Parse returned records
                lines = proc.stdout.strip().split(", ")
                # Format: appName, title, role, x, y, w, h
                i = 0
                while i + 6 < len(lines) and len(elements) < max_elements:
                    win_app = lines[i]
                    title = lines[i + 1]
                    role = lines[i + 2].replace("AX", "").lower()
                    try:
                        x = int(lines[i + 3])
                        y = int(lines[i + 4])
                        w = int(lines[i + 5])
                        h = int(lines[i + 6])
                        elements.append(UIElement(
                            name=title,
                            control_type=role,
                            x=x + w // 2,
                            y=y + h // 2,
                            width=w,
                            height=h,
                            window_title=win_app,
                        ))
                    except (ValueError, IndexError):
                        pass
                    i += 7
        except Exception as e:
            logger.debug(f"macOS UI element query encountered: {e}")

        return elements

    # -------------------------------------------------------------------------
    # 2. Read Whole Screen (AI Vision + Local Accessibility Synthesis)
    # -------------------------------------------------------------------------

    def read_whole_screen(self, prompt: Optional[str] = None) -> Tuple[str, List[UIElement]]:
        """
        Captures and reads the whole screen aloud:
        1. Queries native UI element hierarchy and active windows.
        2. Tries Gemini Vision for rich multimodal visual comprehension.
        3. If offline / no API key, provides a comprehensive local spoken overview
           listing active windows, visible documents, and actionable items.
        """
        elements = self.get_visible_elements(max_elements=30)
        self.last_capture_time = time.time()

        # 1. Try Gemini Vision if configured
        from app.config.settings import settings
        if settings.gemini_api_key and settings.gemini_api_key.strip():
            vision_prompt = prompt or (
                "Describe what is displayed across the whole screen. "
                "Mention open windows, active software, main text or files shown, "
                "and what the user can click or open. Keep your response under 3 concise sentences."
            )
            ai_desc = ScreenReader.describe_with_ai(prompt=vision_prompt)
            if ai_desc and not ai_desc.startswith("Could not capture") and not ai_desc.startswith("I captured the screen but could not"):
                self.last_screen_summary = ai_desc
                return ai_desc, elements

        # 2. Local Intelligent Fallback
        summary = self._synthesize_local_screen_description(elements)
        self.last_screen_summary = summary
        return summary, elements

    def _synthesize_local_screen_description(self, elements: List[UIElement]) -> str:
        """Constructs a natural spoken summary of the screen without external API calls."""
        from app.platform_layer import platform_adapter

        focused = platform_adapter.get_focused_window()
        active_title = focused.get("title", "")
        active_app = focused.get("app", "")

        parts = []
        if active_app or active_title:
            app_desc = active_app or "an application"
            if active_title and active_title.lower() != app_desc.lower():
                parts.append(f"You have {app_desc} open showing '{active_title}'.")
            else:
                parts.append(f"You have {app_desc} open.")
        else:
            parts.append("Your desktop is currently displayed.")

        # Highlight key buttons and actionable items
        buttons = [e.name for e in elements if e.control_type in ("button", "link", "tab")][:4]
        items = [e.name for e in elements if e.control_type in ("item", "document")][:4]

        if items:
            parts.append(f"Visible items include: {', '.join(items)}.")
        elif buttons:
            parts.append(f"Visible controls include: {', '.join(buttons)}.")

        parts.append("Tell me what you would like to select or open.")
        return " ".join(parts)

    # -------------------------------------------------------------------------
    # 3. Locate Element On Screen
    # -------------------------------------------------------------------------

    def locate_element(self, target: str) -> Optional[UIElement]:
        """
        Locates the coordinates of a target element on screen.
        Supports:
        - Exact and fuzzy name matching (e.g. "submit", "Save", "report.pdf")
        - Ordinal references ("first one", "second item", "last button")
        - AI Vision coordinate grounding fallback when local accessibility cannot find it.
        """
        clean_target = target.strip().lower()
        clean_target = re.sub(r'^(?:the\s+|on\s+|at\s+)?(?:button|link|icon|tab|file|item|checkbox)\s+', '', clean_target)
        clean_target = re.sub(r'\s+(?:button|link|icon|tab|file|item|checkbox)$', '', clean_target)
        clean_target = clean_target.strip("'\" ")

        # Refresh elements if empty or stale (>10 seconds)
        if not self.last_elements or (time.time() - self.last_capture_time > 10.0):
            self.get_visible_elements()

        # A. Ordinal Index Check ("first one", "second button", "third file", etc.)
        ordinal_map = {
            "first": 0, "1st": 0, "one": 0,
            "second": 1, "2nd": 1, "two": 1,
            "third": 2, "3rd": 2, "three": 2,
            "fourth": 3, "4th": 3, "four": 3,
            "fifth": 4, "5th": 4, "five": 4,
            "last": -1, "final": -1,
        }
        for word, idx in ordinal_map.items():
            if re.search(rf'\b{word}\b', clean_target) and self.last_elements:
                if 0 <= idx < len(self.last_elements):
                    return self.last_elements[idx]
                elif idx == -1:
                    return self.last_elements[-1]

        # B. Exact Substring Match
        for elem in self.last_elements:
            elem_lower = elem.name.lower()
            if clean_target == elem_lower or clean_target in elem_lower or elem_lower in clean_target:
                return elem

        # C. Fuzzy Match via rapidfuzz
        if fuzz and self.last_elements:
            best_elem = None
            best_score = 0
            for elem in self.last_elements:
                score = fuzz.partial_ratio(clean_target, elem.name.lower())
                if score > best_score:
                    best_score = score
                    best_elem = elem
            if best_score >= 70 and best_elem:
                return best_elem

        # D. Multimodal AI Vision Grounding Fallback (Gemini Coordinate Bounding Box)
        vision_elem = self._locate_via_ai_vision(clean_target)
        if vision_elem:
            return vision_elem

        return None

    def _locate_via_ai_vision(self, target: str) -> Optional[UIElement]:
        """Asks Gemini Vision to ground the bounding box [ymin, xmin, ymax, xmax] of `target` on screen."""
        from app.config.settings import settings
        if not (settings.gemini_api_key and settings.gemini_api_key.strip()):
            return None

        try:
            import json
            from google.genai import types as gtypes
            raw = ScreenReader.capture_raw()
            orig_w, orig_h = raw.size
            data, w, h, _ = ScreenReader.compress(raw)

            client = ScreenReader._get_gemini_client()
            prompt = (
                f"Locate the screen element matching '{target}' on this screenshot. "
                "Respond ONLY with a valid JSON object in this format: "
                '{"found": true, "box_2d": [ymin, xmin, ymax, xmax], "label": "name"} '
                "Coordinates must be normalized integers from 0 to 1000. If not found, return {\"found\": false}."
            )
            response = client.models.generate_content(
                model=settings.ai_model_name,
                contents=[
                    gtypes.Part.from_bytes(data=data, mime_type="image/png"),
                    gtypes.Part.from_text(text=prompt),
                ],
                config=gtypes.GenerateContentConfig(temperature=0.1),
            )
            raw_text = (response.text or "").strip()
            # Extract JSON block
            m = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if m:
                payload = json.loads(m.group(0))
                if payload.get("found") and "box_2d" in payload:
                    ymin, xmin, ymax, xmax = payload["box_2d"]
                    # Map from 1000x1000 normalized space to original display pixels
                    cx = int(((xmin + xmax) / 2000.0) * orig_w)
                    cy = int(((ymin + ymax) / 2000.0) * orig_h)
                    pw = int(((xmax - xmin) / 1000.0) * orig_w)
                    ph = int(((ymax - ymin) / 1000.0) * orig_h)
                    label = payload.get("label", target)
                    return UIElement(
                        name=label,
                        control_type="element",
                        x=cx,
                        y=cy,
                        width=pw,
                        height=ph,
                    )
        except Exception as e:
            logger.debug(f"AI Vision grounding encountered: {e}")

        return None

    # -------------------------------------------------------------------------
    # 4. Actions: Click, Double Click, Select, Open
    # -------------------------------------------------------------------------

    def click_element(self, target: str, click_type: str = "single") -> Tuple[bool, str]:
        """Clicks, double-clicks, or right-clicks on the requested displayed element."""
        elem = self.locate_element(target)
        if not elem:
            return False, f"I couldn't locate '{target}' on the screen. Try saying: Read whole screen."

        try:
            # If native UIAutomation control has Invoke pattern, use it for 100% precision
            if click_type == "single" and elem.raw_control:
                try:
                    if hasattr(elem.raw_control, "Click"):
                        elem.raw_control.Click()
                        return True, f"Clicked on '{elem.name}'."
                except Exception:
                    pass

            # Otherwise, move mouse and click at exact screen coordinates
            import pyautogui
            pyautogui.moveTo(elem.x, elem.y, duration=0.15)
            if click_type == "double":
                pyautogui.doubleClick(elem.x, elem.y)
                return True, f"Double-clicked on '{elem.name}'."
            elif click_type == "right":
                pyautogui.rightClick(elem.x, elem.y)
                return True, f"Right-clicked on '{elem.name}'."
            else:
                pyautogui.click(elem.x, elem.y)
                return True, f"Clicked on '{elem.name}'."

        except Exception as e:
            logger.error(f"Error clicking element '{target}': {e}")
            return False, f"Could not click on '{target}': {e}"

    def select_element(self, target: str) -> Tuple[bool, str]:
        """Selects or focuses an element on the screen."""
        elem = self.locate_element(target)
        if not elem:
            return False, f"Could not find '{target}' on the screen to select."

        try:
            if elem.raw_control and hasattr(elem.raw_control, "SetFocus"):
                try:
                    elem.raw_control.SetFocus()
                    return True, f"Selected '{elem.name}'."
                except Exception:
                    pass

            import pyautogui
            pyautogui.click(elem.x, elem.y)
            return True, f"Selected '{elem.name}'."
        except Exception as e:
            return False, f"Could not select '{target}': {e}"

    def open_displayed_item(self, target: str) -> Tuple[bool, str]:
        """
        Opens a displayed file, folder, link, or app visible on screen:
        1. If it's a visible icon or item, double-clicks it on screen.
        2. If it's a link, single-clicks it.
        3. Fallback: uses the platform adapter to open the file or app by name.
        """
        elem = self.locate_element(target)
        if elem:
            if elem.control_type == "link":
                return self.click_element(target, click_type="single")
            else:
                return self.click_element(target, click_type="double")

        # Fallback to standard platform opening if target matches a file or app
        from app.platform_layer import platform_adapter
        try:
            resolved = platform_adapter.resolve_spoken_path(target)
            if resolved and resolved.exists():
                platform_adapter.open_path(resolved)
                return True, f"Opening '{resolved.name}'."
        except Exception:
            pass

        return False, f"Could not find or open '{target}' on the screen."


# Global singleton instance
screen_interaction = ScreenInteractionService()
