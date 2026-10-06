# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# Clembot — Windows PyInstaller Specification File
# Packages Clembot.exe for Windows 10/11 (x64)
# Excludes macOS platform layer and Apple-specific modules.
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
        'app.platform_layer.windows',
        'app.platform_layer.windows.adapter',
        'comtypes',
        'win32gui',
        'win32con',
        'win32api',
        'win32process',
        'pyttsx3.drivers.sapi5',
        'customtkinter',
        'pystray',
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
        'app.platform_layer.macos',
        'app.platform_layer.macos.adapter',
        'app.platform_layer.macos.applescript',
        'app.platform_layer.macos.apps',
        'app.platform_layer.macos.browser',
        'app.platform_layer.macos.system',
        'app.platform_layer.macos.tts',
        'app.platform_layer.macos.permissions',
        'app.platform_layer.macos.window_mgr',
        'pyobjc',
        'AppKit',
        'Foundation',
        'Quartz',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Clembot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
