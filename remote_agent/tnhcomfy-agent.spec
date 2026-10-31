# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the TNHFantasy Remote Agent standalone executable.

Build (Linux) — run it from ``remote_agent/``, not from the repository root:

    cd remote_agent
    pyinstaller --noconfirm --distpath ./dist --workpath ./build tnhfantasy-agent.spec

The ``cd`` is load-bearing, not a convenience. ``Analysis(["server.py"])`` below
resolves ``server.py`` against the *current working directory*, and there is no
``server.py`` at the repository root — invoking this spec from there fails with a
ModuleNotFoundError that reads like a broken spec rather than a wrong CWD. Every
documented and automated build does the ``cd``: ``remote_agent/README.md`` and
the ``working-directory: remote_agent`` in ``.github/workflows/
build-agent-binaries.yml``. This header previously documented the repo-root form,
which cannot work.

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
PROVIDER_CORE = os.path.join(REPO, "remote_agent", "provider_core")
REMOTE_AGENT = os.path.join(REPO, "remote_agent")


# provider_core must be importable both at *analysis* time and at *runtime*
# inside the bundle. Pathex lets PyInstaller find it during collection.
provider_root = os.path.dirname(PROVIDER_CORE)  # .../remote_agent  (parent so `import provider_core` resolves & auto-collects)
pathex = [provider_root, PROVIDER_CORE, REMOTE_AGENT]

# Ship the whole provider_core package (no package-relative data reads, but it
# contains .py modules imported via `from provider_core import ...`).
datas = [
    (PROVIDER_CORE, "provider_core"),
]

# provider_core/__init__.py eagerly imports submodules (http_client,
# logging, utils, downloads, validation, models). Explicit
# hiddenimports make collection robust regardless of whether PyInstaller's
# static scan traces every `from .x import` inside __init__.
hiddenimports = [
    "provider_core",
    "provider_core.utils",
    "provider_core.downloads",
    "provider_core.validation",
    "provider_core.models",
    "provider_core.http_client",
    "provider_core.logging",
    "provider_core.auth",
    "provider_core.responses",
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
    name="tnhfantasy-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression removed. It was `True` with nothing installing UPX:
    # build-agent-binaries.yml installs only build-requirements.txt and
    # requirements.txt on plain `ubuntu-22.04` / `windows-2022` runners, neither of
    # which ships UPX, so PyInstaller warned and shipped uncompressed — the flag
    # was a no-op on every published artifact. Worse, it made the artifact depend
    # on whether the machine building it happened to have UPX installed, and UPX
    # packing of PyInstaller bundles is a known source of binaries that build and
    # then fail to start. If you want it back, install UPX on every builder first
    # and say so here.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # shows uvicorn log lines — useful for a small agent daemon
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
