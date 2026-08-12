# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the TNHComfy Remote Agent standalone executable.

Build (Linux):
    pyinstaller --workpath /tmp/tnh-agent-build --distpath dist --specpath . remote_agent/tnhcomfy-agent.spec

The frozen binary runs ``remote_agent/server.py`` as ``__main__`` (its own
``if __name__ == "__main__": uvicorn.run(...)`` block), so the entry point is
the agent server itself — no external Python required at runtime.
"""
import os
import sys

# Resolve the repository root from the spec file's directory (provided by
# PyInstaller as the absolute SPECPATH). This spec must be invoked with an
# absolute path (the GitHub Action and the docs below do this) so SPECPATH is
# absolute and the computed repo root is correct.
HERE = SPECPATH
REPO = os.path.dirname(HERE)            # repo root
PROVIDER_CORE = os.path.join(REPO, "provider_containers", "provider_core")
REMOTE_AGENT = os.path.join(REPO, "remote_agent")


# provider_core must be importable both at *analysis* time and at *runtime*
# inside the bundle. Pathex lets PyInstaller find it during collection.
provider_root = os.path.dirname(PROVIDER_CORE)  # .../provider_containers  (parent so `import provider_core` resolves & auto-collects)
pathex = [provider_root, PROVIDER_CORE, REMOTE_AGENT]

# Ship the whole provider_core package (no package-relative data reads, but it
# contains .py modules imported via `from provider_core import ...`).
datas = [
    (PROVIDER_CORE, "provider_core"),
]

# provider_core/__init__.py eagerly imports submodules (state, http_client,
# reconciliation, background, router, logging, utils, downloads, validation,
# models). Explicit hiddenimports make collection robust regardless of whether
# PyInstaller's static scan traces every `from .x import` inside __init__.
hiddenimports = [
    "provider_core",
    "provider_core.utils",
    "provider_core.downloads",
    "provider_core.reconciliation",
    "provider_core.validation",
    "provider_core.models",
    "provider_core.http_client",
    "provider_core.state",
    "provider_core.logging",
    "provider_core.background",
    "provider_core.router",
    "provider_core.base_client",
    "provider_core.deploy",
    "uvicorn",
    "uvicorn.main",
    "uvicorn.server",
    "uvicorn.config",
    "uvicorn.supervisors",
    "uvicorn._subprocess",
]

a = Analysis(
    ["server.py"],
    pathex=pathex,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="tnhcomfy-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # shows uvicorn log lines — useful for a small agent daemon
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
