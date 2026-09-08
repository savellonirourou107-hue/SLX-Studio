# SLX Studio 2.0 development desktop

This is a separately launched Electron preview on the
`codex/slx-studio-2-foundation` branch. It does not replace the Python CLI or
legacy Workbench. The current real workflow is `.m` editing; `.slx` viewport,
MATLAB execution and extensions are still migration work.

## Run from source

Requirements: Node.js 22.12+ and Python 3.10+. The Python core has no mandatory
runtime dependencies; no MATLAB installation is needed for this desktop slice.
From the repository root in PowerShell 7:

```powershell
$env:npm_config_cache = 'E:\CodexData\cache\npm'
$env:ELECTRON_CACHE = 'E:\CodexData\cache\electron'
$env:SLX_DESKTOP_STATE_DIR = 'E:\CodexData\Temp\slx-studio-2-state'
$env:SLX_STUDIO_PYTHON = (Get-Command python).Source
npm ci
npm run build
npm run desktop -- 'E:\path\to\project'
```

Omit the final path to choose a folder from the app. A `.m` file path also opens
its containing workspace and initial editor. The state directory contains
Chromium state and recovery drafts; it is not the source workspace.

## Current workflow

Open a `.m` file from Explorer. Each tab retains a separate Monaco model,
Undo/Redo history and view position. Ctrl+S, File → Save and the Command Palette
use the same service. Changes to the disk version cause a conflict instead of
an unconditional overwrite. Reload from Disk is explicit. Dirty tab/window
close offers Save, Discard or Cancel, and recovery drafts can be restored after
restart. Mixed/legacy line endings open read-only to avoid silent conversion.

The `Settings: Show Effective Configuration` command displays the current
schema-backed configuration. Settings persistence and interactive settings UI
are not implemented yet. The `.slx` contribution currently reports its migration
boundary; it is not a working model viewport.

## Developer gates

```powershell
npm run check:desktop
python -m pytest -m 'not matlab_integration' -ra
python -m ruff check .
python -m ruff format --check .
npm run measure:desktop
```

`check:desktop` stops at the first failing gate. It includes actual Electron
launch and interaction, not a browser mock. The test and measurement fixtures
are generated under the configured temporary directory. Measurements and
screenshots live under ignored `output/` subdirectories. See
[M1 evidence](slx-studio-2-m1-evidence.md) for scope and caveats.

## Rollback and boundaries

Continue using `slx-studio` / `slx-diff studio` for the legacy Workbench and
existing MATLAB/Simulink workflows. No release tag, main-branch replacement,
Windows installer or VS Code extension compatibility is implied by this preview.
