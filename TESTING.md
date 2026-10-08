# Clembot Testing Guide

This document outlines the testing procedures for verifying all components of the **Clembot Windows Voice Assistant**, including automated unit tests and manual voice testing scenarios.

---

## 1. Automated Unit Tests

Clembot includes a comprehensive automated test suite of **537 tests** covering filesystem operations, path resolution, fast command routing, safety policies, conversational memory, code intelligence, wake word detection, speech normalization, AI planning, friendly errors, screen interaction & reading, VS Code full access, FAQ training set conformity, event bus guards, and more.

### Running Automated Tests
Open Windows PowerShell, macOS Terminal, or Command Prompt in the repository root and run:

```bash
python -m unittest discover -s tests -v
```

### Test Modules Overview

| Test Module | What it Tests |
|---|---|
| `tests/test_wake_word.py` | Activation ("Clembot activate yourself"), deactivation, phonetic variants ("clemburt", "clem ber", "clembur"). |
| `tests/test_normalizer.py` | Homophone map ("post grey sql" → "postgresql"), filler stripping, fuzzy confidence matching. |
| `tests/test_fast_router.py` | Instant offline matching for window management, folders, apps, web search, and line jumps. |
| `tests/test_screen_interaction.py` | Whole screen reading, visual element grounding, clicking, double clicking, right clicking, selecting, and opening displayed items. |
| `tests/test_screen_reader.py` | Display capture, binary vision thresholding, compression under 100 KB, OCR and Gemini vision integration. |
| `tests/test_vscode_full_access.py` | Full VS Code programmatic access: jumping to lines, reading code, deleting lines, inserting text, commenting, duplicating, and diffing. |
| `tests/test_faq_training.py` | Complete Windows & macOS FAQ training set verification (195 examples), sub-15-word response limits, intent/slot schema mapping. |
| `tests/test_shell_targets.py` | Windows shell targets (File Explorer, This PC, Recycle Bin), `open_file` → `open_app` fallback. |
| `tests/test_filesystem.py` | Folder and file creation, renaming, copying, moving, directory listing, and item counting. |
| `tests/test_paths.py` | Dynamic Windows Known Folders resolution (Desktop, Downloads, Documents) and available drives (`C:\`). |
| `tests/test_safety.py` | Security guard protection for `C:\Windows`, dangerous root deletions, and confirmation triggers. |
| `tests/test_memory.py` | Conversational context resolution ("there" → last folder, "it" → last file). |
| `tests/test_code_intelligence.py` | AST function range detection, unified diff generation, function renaming, exception block wrapping, and `.bak` backups. |
| `tests/test_app_resolver.py` | Fuzzy app lookup, Start Menu / UWP / process-name matching, persistent cache round-trip. |
| `tests/test_ai_planner.py` | Gemini/Ollama Pydantic-validated plan parsing, unknown-action rejection, retry self-correction. |
| `tests/test_llm_providers.py` | Mock Gemini/Ollama provider integration, fast router with LLM active flag. |
| `tests/test_conversational_mode.py` | Hinglish detection and AI bypass routing. |
| `tests/test_friendly_errors.py` | FileNotFoundError → spoken suggestions, permission error messages, timeout messages. |
| `tests/test_dedup_and_fallback.py` | Orchestrator 1.5 s dedup window; web-search fallback for unknown queries. |
| `tests/test_doctor.py` | `python -m app.doctor` health-check invocation (mocked subsystems). |
| `tests/test_event_bus_guard.py` | Duplicate-subscription prevention, thread-safe concurrent subscribe/emit, resilience to crashing handlers. |

---

## 2. Manual Testing Scenarios

When performing manual verification, Clembot can be tested using either **voice commands** or the **bottom text entry box** in the GUI.

### Scenario A: Activation & Deactivation Lifecycle
1. Start Clembot (`python -m app.main`).
2. Verify the status badge displays `LISTENING`.
3. Say: *"Clembot deactivate"*.
   - **Expected**: Clembot responds *"Clembot deactivated. Say 'Clembot activate yourself' when you need me."* Status changes to `IDLE`.
4. Say: *"Open Downloads"*.
   - **Expected**: Ignored because assistant is in sleep mode.
5. Say: *"Clembot activate yourself"*.
   - **Expected**: Clembot wakes up, status changes to `LISTENING`, and responds *"Clembot is activated and listening."*

---

### Scenario B: File System & Directory Listing
1. Say: *"Open Downloads"*.
   - **Expected**: Windows File Explorer opens your Downloads folder.
2. Say: *"What files are in Downloads?"*
   - **Expected**: Clembot counts the items and responds: *"Downloads contains X files and Y folders..."*
3. Say: *"Create a folder called ClembotTest on Desktop"*.
   - **Expected**: A folder named `ClembotTest` appears on your Desktop. Clembot confirms: *"Done. Created folder 'ClembotTest'..."*
4. Say: *"Create a file called sample.txt"*.
   - **Expected**: `sample.txt` is created inside the active test folder.

---

### Scenario C: File Safety & Windows Recycle Bin
1. Say: *"Delete the ClembotTest folder on Desktop"*.
   - **Expected**: If the folder has multiple items, Clembot halts and asks: *"ClembotTest contains X items. Do you really want me to delete this folder?"*
2. Say: *"Confirm"*.
   - **Expected**: The folder is sent to the Windows **Recycle Bin** (not permanently deleted). You can open your Windows Recycle Bin and see the restored item.

---

### Scenario D: Application & Window Management
1. Say: *"Open Notepad"*.
   - **Expected**: Notepad launches or comes to the foreground.
2. Say: *"Minimize the current window"*.
   - **Expected**: Notepad minimizes to the taskbar.
3. Say: *"Open Chrome"* (or *"Open Edge"*).
   - **Expected**: The browser opens.
4. Say: *"Snap window left"*.
   - **Expected**: The browser window resizes to occupy the left 50% of your screen.
5. Say: *"Show desktop"*.
   - **Expected**: All windows minimize, showing your desktop.

---

### Scenario E: Web & Media Control
1. Say: *"Search Google for Python Django tutorials"*.
   - **Expected**: Browser opens with Google search results for the query.
2. Say: *"Search YouTube for Python DSA"*.
   - **Expected**: YouTube search results open.
3. Say: *"Take a screenshot"*.
   - **Expected**: A full-screen screenshot is saved to your `Pictures/Screenshots` folder, and Clembot speaks the filename.
4. Say: *"Volume up"* / *"Volume down"* / *"Mute"*.
   - **Expected**: Windows master volume responds accordingly.

---

### Scenario F: VS Code & Code Editing
1. Open a Python file (e.g. `test_code.py`) in VS Code with the following content:
   ```python
   def calculate_total(items):
       return sum(items)
   ```
2. Say: *"Go to line 1"*.
   - **Expected**: Cursor in VS Code jumps to line 1.
3. Say: *"Change the function name calculate_total to calculate_price"*.
   - **Expected**:
     - Clembot displays an interactive Code Diff banner in the GUI showing:
       ```diff
       -def calculate_total(items):
       +def calculate_price(items):
       ```
     - Clembot speaks: *"Review the diff and say confirm to apply."*
4. Say: *"Confirm"*.
   - **Expected**: The edit is applied to the file, and a backup (`test_code.py.bak`) is created automatically.
