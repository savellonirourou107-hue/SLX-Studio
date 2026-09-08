# SLX Studio 2.0 development desktop

This is a separately launched Electron preview on the
`codex/slx-studio-2-foundation` branch. It does not replace the Python CLI or
legacy Workbench. The current real workflow is `.m` editing plus a bounded,
read-only `.slx` model viewport. MATLAB execution, model writes, simulation
panels and extensions are still migration work.

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
schema-backed configuration. `Settings: Edit Configuration` persists the font
size and minimap settings through the typed service. User settings live in the
desktop state directory; workspace settings live in `.slx-studio/settings.json`.
Only registered, non-sensitive keys can be written, and saves use a file hash
to reject external changes. Selecting an `.slx` file invokes the Python parser via
the typed service boundary and opens the static model viewport. The viewport
supports subsystem selection, bounded block search, block parameter inspection,
zoom/pan and page navigation. It renders at most 160 blocks and 512 connections
per request, pins follow-up pages to the source SHA-256, and marks fallback
positions or omitted connections. Wires are intentionally approximate and the
view is read-only: the parser does not start MATLAB, execute callbacks or
rewrite private SLX XML. `model/diff` remains available to the desktop API for
typed structural comparisons.

Both settings files use this versioned JSON format (maximum 64 KiB):

```json
{
  "version": 1,
  "settings": { "editor.fontSize": 16, "editor.minimap": false }
}
```

Settings are read at startup, on workspace changes and through the settings
commands; there is no background file watcher yet. Invalid files/keys produce
visible warnings and do not grant execution trust. The dialog refuses to
overwrite invalid files, so unknown or damaged content is not silently removed.

`Backend: Restart Python Service` explicitly creates a fresh owned backend for
the current workspace while retaining open text models. Failed or pending
operations are never replayed automatically. This does not start MATLAB.

## Developer gates

```powershell
npm run check:desktop
python -m pytest -m 'not matlab_integration' -ra
python -m ruff check .
python -m ruff format --check .
npm run measure:desktop
```

To run the optional real MATLAB gate on this machine, set the executable
explicitly before invoking pytest:

```powershell
$env:SLX_STUDIO_MATLAB = 'E:\matlab2026\bin\matlab.exe'
python -m pytest tests/test_matlab_r2026a_integration.py -o addopts= -ra
```

`check:desktop` stops at the first failing gate. It includes actual Electron
launch and interaction, not a browser mock. The test and measurement fixtures
are generated under the configured temporary directory. Measurements and
screenshots live under ignored `output/` subdirectories. See
[M1 evidence](slx-studio-2-m1-evidence.md) for scope and caveats.

## Rollback and boundaries

Continue using `slx-studio` / `slx-diff studio` for model writes, simulation and
the legacy Workbench. No release tag, main-branch replacement, Windows installer
or VS Code extension compatibility is implied by this preview. The new viewport
is static and approximate; it is not evidence of Simulink rendering parity.
