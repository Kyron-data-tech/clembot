# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# Clembot — macOS PyInstaller Specification File
# Packages Clembot.app for macOS (Apple Silicon arm64 / Intel)
# Bundles Info.plist with system permission descriptions:
#   - NSMicrophoneUsageDescription
#   - NSAppleEventsUsageDescription
#   - NSScreenCaptureUsageDescription
# Excludes Windows platform layer and Windows-specific modules.
# =============================================================================

import os
import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Collect package data
customtkinter_datas = collect_data_files('customtkinter')

added_files = [
    ('.env.example', '.'),
] + customtkinter_datas

a = Analysis(
    ['../../app/main.py'],
    pathex=['../..'],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'app.platform_layer.macos',
        'app.platform_layer.macos.adapter',
        'app.platform_layer.macos.applescript',
        'app.platform_layer.macos.apps',
        'app.platform_layer.macos.browser',
        'app.platform_layer.macos.system',
        'app.platform_layer.macos.tts',
        'app.platform_layer.macos.permissions',
        'app.platform_layer.macos.window_mgr',
        'customtkinter',
        'send2trash',
        'pyautogui',
        'fastapi',
        'uvicorn',
        'pydantic',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'app.platform_layer.windows',
        'app.platform_layer.windows.adapter',
        'win32gui',
        'win32con',
        'win32api',
        'win32process',
        'comtypes',
        'uiautomation',
        'pycaw',
        'pystray',
        'pyttsx3',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Clembot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64' if 'arm' in sys.platform.lower() or sys.byteorder == 'little' else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Clembot',
)

app = BUNDLE(
    coll,
    name='Clembot.app',
    icon=None,
    bundle_identifier='com.clembot.assistant',
    info_plist={
        'CFBundleName': 'Clembot',
        'CFBundleDisplayName': 'Clembot Voice Assistant',
        'CFBundleIdentifier': 'com.clembot.assistant',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': 'True',
        'NSMicrophoneUsageDescription': 'Clembot requires microphone access to listen for spoken voice commands.',
        'NSAppleEventsUsageDescription': 'Clembot requires Apple Events automation permissions to switch browser tabs in Google Chrome and Brave Browser, and control macOS applications.',
        'NSScreenCaptureUsageDescription': 'Clembot requires screen recording access to inspect display context for code editing and screen reading.',
    },
)
