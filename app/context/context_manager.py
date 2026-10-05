"""
app/context/context_manager.py

Captures real-time desktop context (focused window, active folder/Finder path,
VS Code file/workspace, and clipboard preview) via the PlatformAdapter abstraction layer.
"""

from typing import Optional

from app.core.models import ScreenContext
from app.logging.logger import logger
from app.platform_layer import platform_adapter


class ContextManager:
    """
    Captures real-time application context across Windows and macOS:
    focused window, process name, active Explorer/Finder folder, VS Code context, and clipboard.
    """

    def capture_context(self) -> ScreenContext:
        """Inspects current desktop state and returns a populated ScreenContext."""
        win_info = platform_adapter.get_focused_window()
        window_title = win_info.get("title", "")
        process_name = win_info.get("app") or "Unknown"
        hwnd = win_info.get("id", 0)
        pid = win_info.get("pid", 0)

        # Active File Explorer / Finder path
        active_folder_path = None
        try:
            active_folder = platform_adapter.get_active_folder()
            if active_folder:
                active_folder_path = str(active_folder)
        except Exception as e:
            logger.debug(f"Active folder detection skipped: {e}")

        # VS Code context — use VSCodeAdapter (IPC + workspace detection)
        vscode_file = None
        vscode_line = None
        vscode_workspace = None
        try:
            from app.editor.vscode_adapter import VSCodeAdapter
            from app.ipc.server import ipc_server
            adapter = VSCodeAdapter()
            active_vsc_file = adapter.get_active_file()
            if active_vsc_file:
                vscode_file = str(active_vsc_file)
            vscode_line = ipc_server.state.cursor_line or None
            ws = ipc_server.state.workspace_folder or adapter.get_workspace()
            vscode_workspace = str(ws) if ws else None
        except Exception as e:
            logger.debug(f"VS Code context detection failed: {e}")

        # Truncated clipboard preview
        clip = platform_adapter.get_clipboard_text()
        clip_preview = clip[:400] if clip else None

        context = ScreenContext(
            active_app=process_name,
            active_window_title=window_title,
            window_handle=hwnd,
            process_id=pid,
            explorer_path=active_folder_path,
            vscode_file=vscode_file,
            vscode_line=vscode_line,
            vscode_workspace=vscode_workspace,
            clipboard_text=clip_preview,
        )

        return context


# Backwards compatibility alias
WindowsContextManager = ContextManager
