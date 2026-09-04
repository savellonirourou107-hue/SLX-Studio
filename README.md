<div align="center">

# SLX Studio

### A lightweight editor for MATLAB `.m` scripts and Simulink `.slx` models.

**Edit code. Edit block diagrams. Run both through your local MATLAB installation.**

[中文](README.zh-CN.md) · [Installation](#installation) · [5-minute workflow](#the-5-minute-workflow) · [CLI](#cli-command-reference) · [M editor](#m-editor) · [SLX editor](#slx-editor) · [Desktop](#desktop-app) · [AI](#optional-ai-assistant)

</div>

![SLX Studio v1.0 Beta](docs/assets/slx-studio-v10-beta.png)

[![CI](https://github.com/savellonirourou107-hue/SLX-Studio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/savellonirourou107-hue/SLX-Studio/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

> **Status: v1.0.0 Beta 2.** SLX Studio is now a lightweight `.m` + `.slx` engineering IDE: multi-tab editing, section execution, a MATLAB Command Window with shared workspace state, editable workspace variables, cancellable script/Simulink/sweep jobs, MATLAB figures, SimulationOutput plots, parameter sweeps, crash-recovery drafts, project search and graphical SLX editing. MATLAB/Simulink is still required to execute `.m` files and to create, modify or simulate real `.slx` files.

## Why SLX Studio

SLX Studio is not trying to reproduce the full MATLAB desktop. It targets the small, frequent loop around a MATLAB/Simulink project:

```text
Project folder
├── controller.m   → edit → save → run → console + variables
└── controller.slx → edit diagram → save → simulate
```

The same lightweight workbench can move between code and block diagrams without making AI or Git tooling the primary interface.

## Installation

### Requirements

- Python 3.10 or newer.
- MATLAB and Simulink are optional for static `.slx` viewing, diff and review.
- A local MATLAB installation is required for running `.m`, creating or editing real `.slx` files, and simulation. MATLAB R2026a is the tested release for this beta.
- Windows users can run the packaged EXE without installing Python; MATLAB/Simulink is still required for execution and real model writes.

### Install from a clone

From the repository root:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Install the optional desktop WebView as well:

```bash
python -m pip install -e ".[desktop]"
```

Contributors can install the test and lint tools:

```bash
python -m pip install -e ".[dev]"
```

### Configure MATLAB (optional)

MATLAB is discovered in this order: an explicit `--matlab` argument, `SLX_DIFF_MATLAB`, then `matlab` on `PATH`.

```powershell
$env:SLX_DIFF_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
slx-diff matlab-status
```

The same setting can be supplied per launch:

```powershell
slx-studio . --matlab 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
```

Without MATLAB, `inspect`, `diff`, `review`, `context`, `view` and `html` remain available because they use the non-executing static parser.

## The 5-minute workflow

1. Open a project folder: `slx-studio .` (or `slx-diff studio .`).
2. Open an `.m` tab, save with `Ctrl/Cmd+S`, then press `F5` to run the file through MATLAB.
3. Use `Ctrl/Cmd+Enter` for the current `%%` section or selected code. Inspect the Console, Workspace Variables and Plots panels.
4. Open an `.slx` model. Drag blocks, edit exposed parameters, or connect an output port to an input port. Click **Apply in MATLAB** to write a real model.
5. Run a simulation or open **Sweep**. Use `Shift+F5` to stop a running script, simulation or sweep.

The Workbench keeps a session-scoped MATLAB workspace checkpoint. It is temporary, project-external and removed when the Workbench closes.

## CLI command reference

| Command | Use it for | Needs MATLAB? |
| --- | --- | --- |
| `slx-studio [PATH]` | Open the editor Workbench | Only for execution/write/simulation |
| `slx-diff studio [PATH]` | Start the Workbench from the engineering CLI | Only for execution/write/simulation |
| `slx-diff inspect MODEL.slx` | Export the canonical model JSON | No |
| `slx-diff diff OLD.slx NEW.slx` | Compare two models (`--format text\|markdown\|json`) | No |
| `slx-diff review OLD.slx NEW.slx` | Rank changed areas by static signal-flow impact | No |
| `slx-diff context OLD.slx NEW.slx` | Export compact agent context | No |
| `slx-diff view MODEL.slx` | Open a read-only visual model view | No |
| `slx-diff html OLD.slx NEW.slx -o report.html` | Write a standalone HTML diff report | No |
| `slx-diff run-m SCRIPT.m` | Run a script with captured output | Yes |
| `slx-diff apply MODEL.slx PATCH.json -o OUTPUT.slx` | Validate and apply a staged patch | Yes |
| `slx-diff serve PATH --token TOKEN` | Start the loopback REST API | Only for requested MATLAB jobs |

Run `slx-diff --help` or `slx-diff COMMAND --help` for the complete option list.

The simplest launch is still:

```bash
slx-studio .
```

Open a file directly when you already know what to inspect:

```bash
slx-studio controller.m
slx-studio controller.slx
```

The engineering CLI remains available:

```bash
slx-diff --version
slx-diff diff before.slx after.slx
```

## `.m` editor

The v1.0 Beta script editor supports a lightweight edit → run → inspect → iterate loop:

- multi-file tabs with dirty-state indicators,
- line numbers and lightweight MATLAB syntax highlighting,
- Ctrl/Cmd+S save, Shift+Ctrl/Cmd+S Save As and F5 whole-file run,
- **Ctrl/Cmd+Enter to run the current `%%` section or selection**, preserving source line numbers for errors,
- real cancellable background MATLAB jobs for `.m` execution,
- editor undo/redo and structured MATLAB error-line navigation,
- captured stdout/stderr plus a **Workspace Variables** panel,
- a MATLAB-style **Command Window** (`>>`) whose variables persist across background runs through a temporary session checkpoint,
- double-click editing for workspace variables using explicit MATLAB expressions,
- autosaved recovery drafts for dirty `.m` tabs, stored outside the project tree,
- embedded MATLAB Figure previews exported after execution,
- Quick Open (`Ctrl/Cmd+P`) and project-wide search (`Ctrl/Cmd+Shift+F`) across `.m` text and statically parsed `.slx` structure.

```text
controller.m *        analysis.m
────────────────────────────────────
  1  clear; clc
  2  Kp = 2.5;
  3  t = 0:0.01:5;
  4  y = 1-exp(-Kp*t);

Console                     Workspace Variables
MATLAB run complete         Kp  2.5   double 1x1
                            t   …     double 1x501
                            y   …     double 1x501
```

![SLX Studio v1.0 Beta MATLAB editor](docs/assets/slx-studio-v10-beta.png)

Script execution is always user-triggered. Connecting an AI provider does not grant it unrestricted MATLAB code execution.

## SLX editor

![SLX Studio graphical editor](docs/assets/slx-studio-v08-slx-editor.png)

SLX Studio parses a model for lightweight viewing without MATLAB. When a local MATLAB/Simulink installation is available, the same canvas becomes an editor.

### Editor interactions in v1.0 Beta

- select blocks and edit exposed parameters,
- **drag blocks** on the canvas and persist their Simulink `Position`,
- keep signal paths visually attached while a block moves,
- render explicit input/output ports inferred from existing connections and **drag a specific output port onto a specific input port** to create a signal connection,
- add common blocks through a searchable Block Palette,
- rename and delete blocks,
- remove signal connections,
- save the model and run a simulation,
- undo/redo structural and parameter edits as one Workbench history,
- double-click a Subsystem block to navigate into its child system when present,
- plot supported numeric `SimulationOutput` timeseries/Dataset signals in the Workbench/Studio after simulation.

SLX undo/redo uses temporary model snapshots plus SHA-256 conflict checks. If another application changes the model on disk, SLX Studio refuses to overwrite that external change with a stale undo.

### Compatibility boundary

SLX Studio does **not** directly rewrite private `.slx` ZIP/XML internals for real edits. It sends validated operations to MATLAB/Simulink:

```text
set_param     add_block      delete_block
add_line      delete_line    save_system
sim
```

This keeps the browser UI lightweight while MATLAB remains responsible for serializing and executing real Simulink models.

### Safe starter palette

The current catalog includes common blocks such as Inport, Outport, Step, Constant, Gain, Sum, Saturation, Integrator, Discrete-Time Integrator, Transfer Function, Unit Delay, Mux, Scope and To Workspace. The catalog is extensible without hard-coding every block into the UI.

## Run, plots, sweeps and project navigation

The v1.0 Beta Workbench adds the small IDE conveniences that matter during iteration:

```text
Ctrl+Enter       run current %% section / selection
F5               run current .m file
Shift+F5         stop the active .m / SLX / sweep MATLAB job
Ctrl+Shift+P     Command Palette
Ctrl+P           Quick Open
Ctrl+Shift+F     search .m text + .slx blocks/parameters/signals
Ctrl+Shift+S     Save As
```

MATLAB Figures are captured after script execution and shown beside Workspace Variables. Supported numeric Simulink `timeseries` and `Simulink.SimulationData.Dataset` outputs are reduced to bounded plot payloads and rendered locally.

### Command Window and shared workspace

Scripts, sections, Command Window commands and variable edits share a session-scoped MATLAB workspace checkpoint. SLX Studio does **not** keep a heavyweight MATLAB desktop session embedded; instead, each explicit run inherits the checkpoint and writes the resulting user variables back. The checkpoint lives in a temporary session directory and is discarded when the Workbench closes.

```text
Run controller.m       -> Kp = 2.5
Command: Kp = 3        -> Kp = 3
Edit variable Kp = 4   -> Kp = 4
Run next section       -> sees Kp = 4
```

### Parameter Sweep

Select a block in an SLX model and open **Sweep**. Values can be entered as `1:0.5:5`, `3:1`, or comma-separated values. The sweep runs multiple simulations in the background, restores the original parameter, and returns bounded curves plus convenience metrics.

```text
Controller/Kp · Gain
1 : 0.5 : 5
      ↓
9 simulations
      ↓
overlaid response curves + final/max/RMS/settling estimate
```

Sweep metrics are review/iteration aids, not formal control-system verification.

## Create files

From the Workbench toolbar:

```text
New .m    → create and edit a MATLAB script
New .slx  → ask local MATLAB to create a real blank Simulink model
```

A new SLX model can then be built graphically or from an optional validated AI blueprint.

## Desktop app

Install the optional desktop shell:

```bash
pip install -e ".[desktop]"
slx-studio
```

With `pywebview`, the Workbench opens as a desktop window; otherwise it can fall back to the system browser.

### Windows EXE

`.github/workflows/build-windows.yml` is configured to build both a portable app and an installer on `windows-latest` whenever a version tag is pushed:

```text
SLXStudio.exe
SLX-Studio-Setup-x64.exe
```

The installer is per-user and offers **opt-in** desktop shortcut plus `.m` / `.slx` file associations; those associations are not enabled silently. End users of either Windows artifact do not need Python installed. MATLAB/Simulink is still required for actual script execution and real SLX writes/simulation.

## Optional AI assistant

AI is a helper layer, not the product shell. Built-in BYOK presets include OpenAI, DeepSeek, Kimi/Moonshot, MiniMax, GLM/Zhipu, Qwen/Alibaba Model Studio and custom OpenAI-compatible endpoints.

For SLX work, agents receive structured model tools and validated blueprints rather than an unrestricted MATLAB shell. The local REST API is documented in [`docs/agent-api.md`](docs/agent-api.md).

## Optional Git and review tools

The original `slx-diff` capabilities remain available:

```bash
slx-diff diff before.slx after.slx
slx-diff review before.slx after.slx
slx-diff context before.slx after.slx
slx-diff git-diff --base main --head HEAD
```

They provide semantic SLX differences, static downstream review hints and compact agent context without starting MATLAB.

## Architecture

```text
┌────────────────────────────────────────────────┐
│                SLX Studio Workbench            │
│                                                │
│ Project tree   .m tabs          .slx canvas    │
│                editor           inspector       │
│                console          block palette   │
│                variables        undo / redo     │
└───────────────────┬──────────────────┬─────────┘
                    │                  │
               text save/run      structured edits
                    │                  │
                    └────────┬─────────┘
                             ▼
                      local Python bridge
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
         optional AI APIs            local MATLAB
         structured tools          run / edit / sim
```

## Safety boundary

- Static SLX parsing/viewing does not execute MATLAB.
- Running an `.m` script executes user code and is explicitly user-triggered.
- Real SLX writes/simulation require MATLAB and can inherit behavior from models MATLAB loads.
- Workspace file APIs are restricted to the selected project root.
- SLX edits use source/version checks instead of blindly overwriting the file.
- AI keys are not written into project files by SLX Studio.

See [`SECURITY.md`](SECURITY.md).

## Current limitations

v1.0 Beta is intentionally a small engineering editor, not a full MATLAB replacement.

- No full MATLAB language server, debugger, breakpoints or profiler yet.
- Workspace Variables supports explicit expression-based editing, but it is not yet a full spreadsheet-style array editor.
- Script, SLX simulation and parameter-sweep jobs are cancellable; Command Window commands are currently synchronous requests and are not independently stoppable.
- MATLAB stdout/stderr is collected when a job completes rather than streamed live.
- SLX editing now renders explicit ports found in the model, but dynamic/conditional port semantics and advanced Simulink object types need broader adapters.
- Static parsing reports `metadata.unsupported_features` for Stateflow, masks, variants, library links, model references, bus/data-type metadata, dynamic/conditional ports and BlockTypes outside the conservative catalog. Such structures remain visible for review, but are not claimed to be fully editable or semantically complete.
- When a structure is reported as unsupported or only partially parsed, return to MATLAB/Simulink for authoritative parameter, port, compile, simulation and save validation. Static graph output is never a stability, safety or robustness proof.
- Optional real MATLAB R2026a integration tests are enabled only when `SLX_STUDIO_MATLAB` or `SLX_DIFF_MATLAB` is explicitly set. GitHub-hosted CI does not include MATLAB; `.github/workflows/matlab-self-hosted.yml` is a manual self-hosted template.
- The included Windows workflow builds `SLXStudio.exe` plus `SLX-Studio-Setup-x64.exe`. The current `main` build has passed the GitHub Actions smoke checks; this development environment itself is not Windows, so local interactive launch is not claimed here.

## Troubleshooting

**The editor opens, but Run/Apply/Simulation is unavailable.** Run `slx-diff matlab-status`. If MATLAB is installed outside `PATH`, set `SLX_DIFF_MATLAB` or pass `--matlab` explicitly. The static parser and diff commands do not need MATLAB.

**A model opens with an unsupported-feature warning.** Treat the canonical graph as a review view only. Confirm parameters, ports, compilation, simulation and saving in MATLAB/Simulink before relying on the result. See [`SECURITY.md`](SECURITY.md) and [`docs/architecture.md`](docs/architecture.md).

**The desktop window falls back to a browser.** Install the optional `desktop` extra. If the native WebView still cannot initialize, the fallback browser is intentional and uses the same loopback server.

**The API returns HTTP 400.** Check that the request body is a JSON object, the token is present, and values use the documented types. The server rejects malformed input without starting MATLAB; unexpected failures are returned as a generic HTTP 500.

## Development

```bash
python -m pytest -ra
python -m pytest --collect-only -q
python -m ruff check .
python -m ruff format --check .
```

The v1.0 Beta regression suite currently contains 80 collected tests (including one opt-in MATLAB integration test; it is skipped unless an explicit MATLAB path is configured). The Python suite covers XML/archive hardening, REST schema errors, SLX parsing/diff/review, patching, AI blueprints/providers, workspace isolation, section execution, cancellable MATLAB jobs, shared command-session checkpoints, workspace recovery, parameter sweeps and metrics, Figure payloads, SimulationOutput series extraction, project search, Save As, structured model edits/history, multi-port UI contracts and Workbench HTTP APIs.

For a licensed MATLAB R2026a + Simulink installation, run the real-runtime check explicitly:

```powershell
$env:SLX_STUDIO_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
python -m pytest -ra -m matlab_integration
```

This check exercises `set_param`, `add_block`, `delete_block`, `add_line`, `delete_line`, `save_system`, `sim`, Figure export and the workspace checkpoint. It complements, and does not replace, the fake-MATLAB protocol tests.

More focused usage notes and examples are available in [`docs/studio.md`](docs/studio.md), [`docs/agent-api.md`](docs/agent-api.md) and [`examples/README.md`](examples/README.md).

## License

MIT. MATLAB and Simulink are products of MathWorks and are not bundled with this project.
