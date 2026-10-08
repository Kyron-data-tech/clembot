# Clembot — Cross-Platform Voice Assistant

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/Tests-537%20passing-brightgreen)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

**Control your entire PC with your voice — open apps, edit code, manage files, switch browser tabs, and more.**

</div>

---

## What is Clembot?

**Clembot** is a production-grade, local-first voice assistant for **Windows 10/11** and **macOS (Apple Silicon M3/M4 arm64)**. It understands natural speech (including Hinglish), routes commands through a zero-latency deterministic engine for common tasks, and falls back to an AI reasoning layer (Gemini / Ollama / OpenAI) for complex or ambiguous requests.

It ships with full VS Code integration, browser context-awareness (Chrome & Brave), screen reading & binary-thresholded vision, surgical AST-level code patching, multi-turn conversational memory, and a modern GUI.

---

## Key Features

| Feature | Detail |
|---|---|
| 🎙️ **Wake Word** | *"Clembot activate"* / *"Clembot deactivate"* — fuzzy phonetic matching tolerates mishearings |
| ⚡ **Zero-Latency Router** | 100+ commands resolved instantly offline with no API call |
| 🧠 **AI Planner** | Gemini, Ollama (Qwen/Llama), OpenAI — structured Pydantic action plans with 1-retry self-correction |
| 👁️ **Screen Vision & OCR** | Captures display, binary-thresholds to separate text from background, compresses to <100 KB |
| 🗣️ **Speech Normalizer** | Strips fillers, corrects homophones — *"post grey sql"* → `postgresql`, *"pi charm"* → `pycharm` |
| 🌐 **Browser Control** | Chrome & Brave tab management via AppleScript (macOS) and UIAutomation (Windows) |
| 💻 **VS Code Integration** | Bidirectional TypeScript extension over local IPC (port 25362) for precise cursor nav & edits |
| ✂️ **Code Patch Engine** | AST-aware surgical code patching with unified diff preview, `.bak` backups, and full undo |
| 📂 **File System** | Desktop, Downloads, Documents, OneDrive — COM-based (Windows) / mdfind+Spotlight (macOS) |
| 🗑️ **Safe Deletes** | All deletions go to Recycle Bin / macOS Trash via `send2trash` — always recoverable |
| 🪟 **Window Manager** | Snap left/right/center, minimize, maximize, close |
| 🔍 **App Catalog** | Start Menu + UWP + Registry (Windows) / mdfind + fuzzy match (macOS) |
| 🇮🇳 **Hinglish Support** | Detects Hindi/English mix and routes to AI reasoning layer automatically |
| 🩺 **Self-Check** | `python -m app.doctor` verifies all 12 critical subsystems before you speak a word |
| 🛡️ **Safety Layer** | Blocks system paths, dangerous commands (`format c:`, `rm -rf /`), confirms destructive deletes |

---

## Platform Support

| Feature | Windows 10/11 | macOS (arm64 / Intel) |
|---|:---:|:---:|
| Voice recognition | ✅ | ✅ |
| Open apps / files / folders | ✅ | ✅ |
| Browser tab switching (Chrome & Brave) | ✅ UIAutomation | ✅ AppleScript |
| Window management (snap/minimize/maximize) | ✅ | ✅ |
| Volume control | ✅ SAPI/PyCaw | ✅ AppleScript |
| TTS (offline) | ✅ SAPI5/pyttsx3 | ✅ `/usr/bin/say` |
| VS Code integration | ✅ | ✅ |
| Code patching by voice | ✅ | ✅ |
| Screen reading / vision | ✅ | ✅ |
| GUI tray icon | ✅ | ✅ (menu bar) |
| Microphone permissions check | ✅ | ✅ guided setup |

---

## Quick Start

### Windows

```powershell
# 1. Clone
git clone https://github.com/your-username/clembot.git
cd clembot

# 2. Create venv & install
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements/windows.txt

# 3. Configure
copy .env.example .env
# Edit .env — add your GEMINI_API_KEY

# 4. Run health check
python -m app.doctor

# 5. Launch
python -m app.main
```

Or use the automated installer:

```powershell
.\scripts\install_windows.ps1
```

### macOS (Apple Silicon M3/M4 — arm64)

```bash
# 0. Prerequisites (one-time)
brew install portaudio          # Required for PyAudio microphone input

# 1. Clone
git clone https://github.com/your-username/clembot.git
cd clembot

# 2. Create venv & install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements/macos.txt

# 3. Configure
cp .env.example .env
# Edit .env — add your GEMINI_API_KEY

# 4. Run health check
python -m app.doctor

# 5. Launch
python -m app.main --cli      # CLI mode (no GUI on macOS yet)
```

Or use the automated installer:

```bash
bash scripts/install_macos.sh
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your keys:

```env
# Required — at least one AI provider
GEMINI_API_KEY=your_gemini_key_here

# Optional
OPENAI_API_KEY=your_openai_key_here
OLLAMA_BASE_URL=http://localhost:11434

# Speech
CLEMBOT_STT_ENGINE=google          # google | whisper
CLEMBOT_TTS_RATE=175
CLEMBOT_TTS_VOLUME=1.0

# Behaviour
CLEMBOT_DEFAULT_AI_PROVIDER=gemini # gemini | ollama | openai | heuristic
CLEMBOT_CONTINUOUS_LISTENING=true
```

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
"Open Downloads"
"Open Desktop"
"Create a folder called Projects on Desktop"
"Create a file called notes.txt"
"Rename notes.txt to college_notes.txt"
"Move resume from Downloads to Documents"
"Delete college_notes.txt"          → Moves to Recycle Bin / Trash (recoverable)
"Find all Python files in my project"
```

### Applications
```
"Open Chrome"                       → Launch or activate Chrome
"Open Brave"
"Open VS Code"
"Close Chrome"
"Switch to VS Code"
```

### Browser (Chrome & Brave)
```
"New tab"
"Close tab"
"Go to tab 3"
"Next tab" / "Previous tab"
"Open YouTube"
"Search YouTube for lo-fi music"
"Open GitHub"
"Reopen closed tab"
"Bookmark this page"
"Go incognito"
```

### Window & System
```
"Snap left" / "Snap right" / "Snap center"
"Minimize" / "Maximize" / "Restore" / "Close window"
"Show desktop"
"Volume up" / "Volume down" / "Mute"
"Take a screenshot"
"Read my screen"                    → AI describes what's visible
```

### VS Code & Code Editing
```
"Jump to line 42"
"Open file utils.py"
"Next file" / "Previous file"
"Read this file"
"Change the function name from foo to bar"
"Add a docstring to the calculate function"
"Fix the syntax error on line 12"
"Run this file"
"Undo last change"
```

### Clipboard
```
"Copy" / "Paste" / "Select all"
"Copy [text] to clipboard"
"Clear clipboard"
```

---

## Project Structure

```
clembot/
├── app/
│   ├── platform_layer/         # 🆕 Cross-platform abstraction layer
│   │   ├── base.py             #    Abstract PlatformAdapter interface
│   │   ├── factory.py          #    OS detection — loads only the right adapter
│   │   ├── windows/            #    Windows implementation (pywin32, UIAutomation)
│   │   └── macos/              #    macOS implementation (AppleScript, Spotlight)
│   │       ├── adapter.py
│   │       ├── apps.py         #    App catalog (mdfind + fuzzy matching)
│   │       ├── browser.py      #    AppleScript tab controller
│   │       ├── window_mgr.py
│   │       ├── system.py       #    Volume, clipboard, hotkeys
│   │       ├── tts.py          #    /usr/bin/say engine
│   │       └── permissions.py  #    macOS Privacy & Security checks
│   ├── commands/
│   │   └── router.py           # Action dispatcher (platform-agnostic)
│   ├── editor/
│   │   ├── vscode_adapter.py   # VS Code IPC + CLI integration
│   │   └── code_patch_engine.py
│   ├── browser/
│   │   └── controller.py       # Windows browser controller (UIAutomation)
│   ├── filesystem/             # Cross-platform file operations
│   ├── speech/                 # STT engine factory
│   ├── tts/                    # TTS engine factory
│   ├── ai/                     # Gemini / Ollama / OpenAI planners
│   ├── core/                   # Orchestrator, state machine, event bus
│   ├── ui/                     # CustomTkinter GUI + system tray
│   ├── security/               # Shell safety, path protection
│   └── doctor.py               # System health check
├── data/
│   └── faq_training_set.json   # 179 curated FAQ training examples (Windows & macOS)
├── requirements/
│   ├── base.txt                # Shared cross-platform deps
│   ├── windows.txt             # Windows-only deps (-r base.txt)
│   └── macos.txt               # macOS-only deps (-r base.txt)
├── scripts/
│   ├── install_windows.ps1     # Windows automated setup
│   ├── install_macos.sh        # macOS automated setup
│   └── generate_faq_data.py    # FAQ dataset generator
├── tests/                      # 487 passing unit tests
│   ├── test_faq_training.py    # FAQ training set & intent schema tests
│   ├── test_platform_macos.py  # macOS platform layer (78 tests, mock-based)
│   └── ...
├── vscode-extension/           # TypeScript VS Code extension
├── .env.example
└── README.md
```

---

## macOS Permissions

On first launch on macOS, you may be prompted to grant:

| Permission | Required For |
|---|---|
| **Microphone** | Voice recognition (STT) |
| **Accessibility** | Window focus, keyboard automation, hotkeys |
| **Automation** | AppleScript browser & app control |
| **Screen Recording** | Screen reading / vision feature |

Run `python -m app.doctor` to check all permissions and get step-by-step instructions for any that are missing.

---

## Running Tests

```bash
# All 537 tests (Windows or macOS — all mock-based, no real OS calls needed)
python -m unittest discover -s tests -v

# macOS platform layer only (78 tests)
python -m unittest tests.test_platform_macos -v

# Windows platform layer only
python -m unittest tests.test_platform_windows -v
```

---

## VS Code Extension

The extension provides a live IPC bridge between VS Code and Clembot:

```bash
cd vscode-extension
npm install
npm run compile
# Press F5 in VS Code to launch the Extension Development Host
```

Install the built `.vsix` via: `code --install-extension clembot-bridge.vsix`

---

## Doctor — Health Check

```bash
python -m app.doctor
```

Checks:
- Python version
- Microphone availability & permissions
- AI provider connectivity (Gemini / Ollama / OpenAI)
- TTS engine (SAPI5 on Windows, `/usr/bin/say` on macOS)
- Local IPC port availability
- VS Code extension reachability
- All critical modules importable

---

## Architecture

```
Voice Input (PyAudio / SpeechRecognition)
        ↓
Speech Normalizer (homophones, fillers, Hinglish)
        ↓
Wake Word Detector (fuzzy phonetic match)
        ↓
Fast Heuristic Router (100+ instant patterns)
        ↓  (on miss)
AI Planner (Gemini / Ollama / OpenAI)  →  Pydantic ActionPlan
        ↓
Action Router (platform-agnostic dispatcher)
        ↓
PlatformAdapter (Windows or macOS)
        ↓
Result + TTS Response
```

---

## Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Run the tests: `python -m unittest discover -s tests`
4. Commit: `git commit -m "feat: add my feature"`
5. Push & open a PR

Please keep Windows and macOS adapters in sync — any new OS-touching method added to one adapter must be added to the other and to `base.py`.

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
Made with ❤️ · Windows 10/11 & macOS Apple Silicon
</div>
