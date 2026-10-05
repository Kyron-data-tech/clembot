import argparse
import sys
import threading
import time
from pathlib import Path

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config.settings import settings
from app.core.models import AssistantState
from app.core.orchestrator import orchestrator
from app.ipc.server import ipc_server
from app.logging.logger import logger
from app.platform_layer import platform_adapter
from app.speech.engine_factory import create_speech_engine
from app.tts.voice_service import voice_service
from app.ui.main_window import ClembotMainWindow
from app.ui.tray import ClembotSystemTray


def validate_environment() -> None:
    """Verifies that the operating system matches the installed dependencies."""
    is_windows = sys.platform == "win32"
    is_macos = sys.platform == "darwin"

    if is_windows:
        try:
            import win32gui
        except ImportError:
            print("\n" + "=" * 65)
            print("[ERROR] Clembot is running on Windows, but Windows packages are missing!")
            print("It appears that requirements/macos.txt or base.txt was installed.")
            print("Please fix by running:")
            print("    pip install -r requirements/windows.txt")
            print("=" * 65 + "\n")
            sys.exit(1)

    elif is_macos:
        # Check permissions on macOS
        from app.platform_layer.macos.permissions import MacOSPermissions
        results = MacOSPermissions.check_all()
        missing = [name for name, ok, _ in results if not ok]
        if missing:
            print("\n" + MacOSPermissions.get_permission_guidance() + "\n")


def run_cli_loop():
    """Runs a lightweight CLI interactive loop for console testing."""
    plat_name = platform_adapter.get_platform_name()
    print("=" * 60)
    print(f"  CLEMBOT — {plat_name} (CLI Interactive Mode)")
    print("  Say or type: 'Clembot activate yourself' to start")
    print("  Say or type: 'Clembot deactivate' to sleep")
    print("  Type 'exit' to quit.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nYou > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                break
            orchestrator.handle_user_input(user_input)
        except (KeyboardInterrupt, EOFError):
            break


def main():
    validate_environment()

    parser = argparse.ArgumentParser(description="Clembot Voice Assistant")
    parser.add_argument("--cli", action="store_true", help="Run in CLI interactive mode without GUI")
    parser.add_argument("--push-to-talk", action="store_true", help="Enable Push-to-Talk mode only")
    parser.add_argument("--no-tray", action="store_true", help="Disable System Tray icon")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--provider", choices=["heuristic", "gemini", "ollama", "openai"], help="Override active AI provider")
    args = parser.parse_args()

    if args.debug:
        settings.debug = True

    if args.provider:
        settings.default_ai_provider = args.provider
        orchestrator.reload_ai_provider()

    logger.info(f"Starting Clembot v{settings.version} on {platform_adapter.get_platform_name()}...")

    # 1. Start Local IPC Server for VS Code Bridge
    ipc_server.start()

    # 2. Initialize Speech Recognition Engine (Google STT or Whisper, per settings)
    speech_engine = create_speech_engine()
    if not args.cli and not args.push_to_talk and settings.continuous_listening:
        speech_engine.start(
            on_error=lambda err: logger.warning(f"Speech error: {err}")
        )

    # 3. CLI Mode
    if args.cli:
        run_cli_loop()
        speech_engine.stop()
        voice_service.stop()
        logger.info("Clembot CLI session terminated.")
        return

    # 4. GUI Mode
    app = ClembotMainWindow(speech_engine=speech_engine)

    tray = None
    if not args.no_tray:
        def _show():
            app.after(0, lambda: (app.deiconify(), app.lift()))

        def _exit():
            speech_engine.stop()
            voice_service.stop()
            app.after(0, app.destroy)

        tray = ClembotSystemTray(on_show_window=_show, on_exit=_exit)
        tray.start()

    def _on_close():
        # Hide window to tray instead of quitting directly
        if tray and tray.icon:
            app.withdraw()
        else:
            speech_engine.stop()
            voice_service.stop()
            app.destroy()

    app.protocol("WM_DELETE_WINDOW", _on_close)

    logger.info("Clembot GUI launched.")
    app.mainloop()

    # Cleanup upon exit
    if tray:
        tray.stop()
    speech_engine.stop()
    voice_service.stop()
    logger.info("Clembot terminated cleanly.")


if __name__ == "__main__":
    main()
