# PyInstaller spec — single-file macOS binary for claude-qte.
# Build:  pyinstaller --clean --noconfirm claude_qte.spec
# Output: dist/claude-qte

block_cipher = None

a = Analysis(
    ['src/claude_qte/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'claude_qte',
        'claude_qte.cli',
        'claude_qte.server',
        'claude_qte.popup',
        'claude_qte.tui',
        'claude_qte.hook',
        'claude_qte.wrapper',
        'claude_qte.installer',
        'claude_qte.settings',
        'claude_qte._runtime',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
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
    name='claude-qte',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
