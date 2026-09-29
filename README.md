# Clembot — Windows Voice Assistant

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue?logo=windows)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/Tests-353%20passing-brightgreen)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

**Control your entire Windows PC with your voice — open apps, edit code, manage files, control browsers, and more.**

</div>

---

## What is Clembot?

**Clembot** is a production-grade, local-first voice assistant built exclusively for **Windows 10 and Windows 11**. It understands natural speech (including Hinglish), routes commands through a zero-latency deterministic engine for common tasks, and falls back to an AI reasoning layer (Gemini / Ollama / OpenAI) for complex or ambiguous requests.

It ships with a full VS Code integration, browser context-awareness (Chrome & Brave), surgical AST-level code patching, multi-turn conversational memory, and a modern Windows GUI.

---

## Key Features

| Feature | Detail |
|---|---|
| 🎙 **Wake Word** | *"Clembot activate"* / *"Clembot deactivate"* — fuzzy phonetic matching tolerates mishearings |
| ⚡ **Zero-Latency Router** | 100+ commands resolved instantly offline with no API call |
| 🧠 **AI Planner** | Gemini, Ollama (Qwen/Llama), OpenAI — structured Pydantic action plans with 1-retry self-correction |
| 🗣 **Speech Normalizer** | Strips fillers, corrects homophones — *"post grey sql"* → `postgresql`, *"pi charm"* → `pycharm` |
| 🌐 **Browser Control** | Chrome & Brave tab management — guarded: commands only fire when the browser is actually visible |
| 💻 **VS Code Integration** | Bidirectional TypeScript extension over local IPC (port 25362) for precise cursor nav & edits |
| 🔧 **Code Patch Engine** | AST-aware surgical code patching with unified diff preview, `.bak` backups, and full undo |
| 📁 **File System** | Desktop, Downloads, Documents, OneDrive, drive roots — COM-based Explorer tab detection |
| 🗑 **Safe Deletes** | All deletions go to Windows Recycle Bin via `Send2Trash` — never silent, always recoverable |
| 🪟 **Window Manager** | Snap left/right/center, minimize, maximize, close — targets the correct pre-command window |
| 📦 **App Catalog** | Start Menu + UWP + Registry + known install paths — finds Chrome/Brave even if not in PATH |
| 💬 **Hinglish Support** | Detects Hindi/English mix and routes to AI reasoning layer automatically |
| 🔍 **Self-Check** | `python -m app.doctor` verifies all 12 critical subsystems before you speak a word |
| 🛡 **Safety Layer** | Blocks system paths, dangerous commands (`format c:`), confirms destructive folder deletes |

---

## Supported Voice Commands

### Activation
```
"Clembot activate yourself"         → Wake assistant
"Clembot deactivate"                → Sleep mode
"Hey Clembot, open my Downloads"    → Activate + immediate command
```

### Files & Folders
```
"Open Downloads"                    → Opens Windows Downloads folder
"Open Desktop"                      → Opens Desktop in Explorer
"Create a folder called Projects on Desktop"
"Create a file called notes.txt"
"Rename notes.txt to college_notes.txt"
"Move resume from Downloads to Documents"
"Delete college_notes.txt"          → Moves to Recycle Bin (recoverable)
"Find all Python files in my project"
```

### Applications
```
"Open Chrome"                       → Launches Chrome (or activates if running)
"Open Brave"                        → Launches Brave Browser
"Open VS Code"                      → Launches / focuses Visual Studio Code
"Open Notepad"                      → Opens Notepad
"Close Chrome"                      → Closes Chrome gracefully
"Close it" / "Close this"          → Closes the currently active window
"Switch to VS Code"                 → Brings VS Code to foreground
```

### Window & System Control
```
"Minimize this window"              → Minimizes active app
"Maximize this window"              → Maximizes active app
"Snap window left"                  → Snaps to left half of screen
"Snap window right"                 → Snaps to right half of screen
"Center window"                     → Centers window at 70% size
"Show desktop"                      → Win+D
"Take a screenshot"                 → Saves to Pictures/Screenshots
"Volume up" / "Volume down" / "Mute"
```

### Browser Control (Chrome & Brave)
> Commands only execute when the browser is actually visible on screen.

```
"Open a new tab"                    → Ctrl+T in active browser
"In Chrome open a new tab"          → Targets Chrome specifically
"Open tab number 4"                 → Switches to tab 4 (validates tab exists)
"Fourth tab"                        → Switches to tab 4
"Show search history"               → Opens Ctrl+H browser history
"Show downloads folder"             → Opens Ctrl+J browser downloads tab
"In Brave show downloads folder"
"Close tab"                         → Closes current browser tab
"Next tab" / "Previous tab"        → Tab navigation
"Reload"                            → Reloads current page
"Bookmark this page"               → Ctrl+D
"Open incognito"                    → Opens private window
"Zoom in" / "Zoom out" / "Reset zoom"
```

### Web Search
```
"Search Google for Python tutorials"
"Search YouTube for Django REST API"
"Open GitHub"
"Open https://github.com"
```

### VS Code & Code Editing
```
"Open app.py"
"Go to line 25"
"Jump to line 50"
"Change the function name calculate_total to calculate_price"
"At line 30, add a try except block around the database call"
"Run this Python program"
"Undo code change"                  → Reverts last patch from .bak backup
```

---

## Architecture

```
                        ┌─────────────────────────┐
                        │     Microphone Audio     │
                        └────────────┬────────────┘
                                     │ PCM audio
                                     ▼
                        ┌─────────────────────────┐
                        │   Speech Recognition    │  Google Cloud / Whisper (local)
                        │  Wake: "Clembot activate"│
                        └────────────┬────────────┘
                                     │ Normalized text
                                     ▼
                        ┌─────────────────────────┐
                        │    Speech Normalizer    │  Homophones, fillers, user aliases
                        │  + Conversational Memory│  (undo refs, "that file", "it")
                        └────────────┬────────────┘
                                     │
               ┌─────────────────────┴─────────────────────┐
               ▼                                           ▼
  ┌────────────────────────┐                ┌──────────────────────────┐
  │   FastCommandRouter    │                │     AI Intent Planner    │
  │   (Instant, Offline)   │                │  Gemini / Ollama / OpenAI│
  │  100+ commands, 0ms    │                │  Hinglish / open-ended   │
  └────────────┬───────────┘                └──────────────┬───────────┘
               │                                           │
               └─────────────────────┬─────────────────────┘
                                     │ AgentPlan (Pydantic)
                                     ▼
                        ┌─────────────────────────┐
                        │   Safety & Policy Layer  │  Blocks system paths,
                        │   Confirmation Queue     │  confirms destructive ops,
                        └────────────┬────────────┘  diff preview on code edits
                                     │ Approved actions
                                     ▼
                        ┌─────────────────────────┐
                        │      Action Router       │
                        └──┬──────┬──────┬──┬─────┘
                           │      │      │  │
              ┌────────────┘   ┌──┘   ┌──┘  └─────────────┐
              ▼                ▼      ▼                     ▼
     ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐
     │  FileSystem  │  │  Windows │  │ Browser  │  │  VS Code IPC   │
     │  (Send2Trash │  │ AppCatalog│  │Controller│  │  TypeScript    │
     │   KnownDirs) │  │ Win32gui │  │Chrome/   │  │  Extension     │
     │              │  │ WinMgr   │  │Brave     │  │  :25362        │
     └──────────────┘  └──────────┘  └──────────┘  └────────────────┘
```

---

## Project Structure

```
voiceps/
├── app/
│   ├── main.py                      # Entry point (GUI / CLI / Tray modes)
│   ├── doctor.py                    # System self-check (12 subsystems)
│   ├── ai/
│   │   ├── base.py                  # AIProvider abstract base
│   │   ├── factory.py               # Provider factory with fallback chain
│   │   ├── gemini_provider.py       # Google Gemini API provider
│   │   ├── ollama_provider.py       # Local Ollama (Qwen / Llama)
│   │   ├── openai_provider.py       # OpenAI API provider
│   │   ├── local_heuristic.py       # 100% offline rule-based NLP planner
│   │   ├── language_detector.py     # Hindi/Hinglish detection
│   │   └── prompt_builder.py        # System prompt + action type registry
│   ├── commands/
│   │   ├── fast_router.py           # Deterministic 0-ms command router (700+ lines)
│   │   ├── router.py                # Action dispatcher to subsystems
│   │   └── friendly_errors.py       # User-facing error messages
│   ├── speech/
│   │   ├── engine.py                # Continuous listen + push-to-talk
│   │   ├── engine_factory.py        # STT provider selector
│   │   ├── wake_word.py             # Fuzzy phonetic wake-word detector
│   │   ├── normalizer.py            # Homophone + filler word normalizer
│   │   └── whisper_engine.py        # Local faster-whisper STT engine
│   ├── browser/
│   │   └── controller.py            # Chrome & Brave context-aware tab control
│   ├── editor/
│   │   ├── vscode_adapter.py        # VS Code IPC client + file fallback
│   │   ├── code_patch_engine.py     # Patch apply / undo / .bak management
│   │   ├── code_intelligence.py     # AST inspection + unified diff engine
│   │   ├── code_edit_parser.py      # Voice edit intent parser
│   │   └── generic_adapter.py       # Generic text editor adapter
│   ├── windows/
│   │   ├── apps.py                  # App Catalog: Start Menu / UWP / Registry / known paths
│   │   ├── window_manager.py        # Win32 snap, minimize, maximize, close (pre-command snapshot)
│   │   └── system.py                # Volume control + screenshot
│   ├── filesystem/
│   │   ├── paths.py                 # Windows Known Folders + COM Explorer resolver
│   │   ├── service.py               # Safe file ops + Send2Trash Recycle Bin
│   │   └── search.py                # Bounded user file search
│   ├── core/
│   │   ├── models.py                # AgentPlan, AgentAction, ScreenContext (Pydantic)
│   │   ├── event_bus.py             # Thread-safe pub/sub dispatcher
│   │   └── orchestrator.py          # Master state machine + foreground window snapshot
│   ├── ai/                          # (see above)
│   ├── ipc/
│   │   └── server.py                # FastAPI local IPC on 127.0.0.1:25362
│   ├── memory/
│   │   └── conversation.py          # Multi-turn memory + contextual reference resolver
│   ├── security/
│   │   └── guard.py                 # Path validator + dangerous command blocker
│   ├── context/
│   │   └── context_manager.py       # Real-time desktop state inspector
│   ├── automation/
│   │   └── input_adapter.py         # Controlled keyboard/mouse automation
│   ├── clipboard/
│   │   └── manager.py               # Windows clipboard integration
│   ├── tts/
│   │   ├── sapi_engine.py           # Offline SAPI 5 via pyttsx3
│   │   └── voice_service.py         # Async non-blocking TTS queue
│   ├── config/
│   │   └── settings.py              # Pydantic settings + .env loader
│   ├── logging/
│   │   └── logger.py                # Structured logging with credential scrubbing
│   └── ui/
│       ├── main_window.py           # Modern GUI: waveform, transcripts, diff preview
│       ├── settings_dialog.py       # Audio / AI / Safety settings
│       ├── tray.py                  # Windows System Tray manager
│       └── theme.py                 # Fluent dark/light design system
├── vscode-extension/                # TypeScript VS Code extension (IPC bridge)
│   ├── src/extension.ts
│   ├── package.json
│   └── tsconfig.json
├── tests/                           # 353 passing unit tests
├── scripts/
│   └── build_exe.py                 # PyInstaller .exe builder
├── run_clembot.bat                  # One-click Windows launcher
├── requirements.txt                 # Python dependencies
├── .env.example                     # Configuration template
├── INSTALLATION.md                  # Step-by-step setup guide
└── TESTING.md                       # Test instructions
```

---

## Quick Start

### Prerequisites
- **Windows 10 or Windows 11** (required — uses Win32 APIs)
- **Python 3.10+**  
- A working **microphone**

### 1. Clone & Install

```powershell
git clone https://github.com/<your-username>/Clembot.git
cd Clembot

# Create and activate virtual environment (recommended)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure

```powershell
copy .env.example .env
# Edit .env and add your API key (only needed if using Gemini/OpenAI)
```

Minimum `.env` for offline-only mode (no AI key needed):
```env
CLEMBOT_AI_PROVIDER=local
CLEMBOT_STT_PROVIDER=google
```

For Gemini AI:
```env
CLEMBOT_AI_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```

### 3. Run Self-Check

```powershell
.\venv\Scripts\python.exe -m app.doctor
```

### 4. Launch

```powershell
# Double-click the launcher:
run_clembot.bat

# Or run directly:
.\venv\Scripts\python.exe -m app.main

# CLI mode (no GUI):
.\venv\Scripts\python.exe -m app.main --cli
```

---

## VS Code Extension

The TypeScript extension connects VS Code to Clembot over `http://127.0.0.1:25362` for:
- Reading the active file and cursor position
- Jumping to specific lines
- Receiving surgical code edits from the AI

**Install the extension:**
```powershell
cd vscode-extension
npm install
npm run compile
# Then press F5 in VS Code to launch in Extension Development Host
```

---

## Configuration Reference (`.env`)

| Variable | Default | Description |
|---|---|---|
| `CLEMBOT_AI_PROVIDER` | `local` | `local` / `gemini` / `ollama` / `openai` |
| `CLEMBOT_STT_PROVIDER` | `google` | `google` (cloud) / `whisper` (local, no key needed) |
| `GEMINI_API_KEY` | — | Required if `AI_PROVIDER=gemini` |
| `OPENAI_API_KEY` | — | Required if `AI_PROVIDER=openai` |
| `OLLAMA_MODEL` | `qwen2.5` | Ollama model name |
| `CLEMBOT_SAFE_MODE` | `true` | Require confirmation before destructive actions |
| `CLEMBOT_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |

---

## Safety & Data Protection

1. **Recycle Bin Default** — all file/folder deletes use `Send2Trash`, never `os.remove`. Always recoverable.
2. **Deletion Confirmation** — folders with many items require explicit spoken confirmation.
3. **Protected System Paths** — `C:\Windows`, `C:\Program Files`, `C:\` root are blocked unconditionally.
4. **Dangerous Command Shield** — `format c:`, `rmdir /s /q c:\`, etc. are intercepted before execution.
5. **Code Diff Preview** — major code changes show a unified diff in the GUI before applying; automatic `.bak` backup created.
6. **Browser Guard** — browser tab commands (new tab, switch tab, history) only fire when Chrome or Brave is actually visible on screen — no accidental hotkeys.
7. **Window Snapshot** — close/minimize/maximize capture the foreground window *before* Clembot takes focus, so they always target your app, not Clembot itself.

---

## Running Tests

```powershell
# Using venv (recommended)
.\venv\Scripts\python.exe -m unittest discover -s tests -v

# Quick summary
.\venv\Scripts\python.exe -m unittest discover -s tests 2>&1 | Select-Object -Last 3
```

**353 tests, all passing.**

---

## License

MIT License. Built for Windows 10 & Windows 11.
