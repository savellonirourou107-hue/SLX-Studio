# Roadmap

## Current direction — SLX Studio 2.x

**SLX Studio 2.0 is shipped on `main` and released as `v2.0.0`.** The current
focus is hardening the desktop platform, expanding verified Simulink/MATLAB
coverage, and adding engineering capabilities without weakening the static
inspection and explicit-execution boundaries.

The product direction remains a **Model + Code + Simulation-first IDE** built on
Electron/TypeScript/Monaco while retaining the dependency-light Python core.
See the [project goal](SLX_STUDIO_2_GOAL.md),
[migration charter](docs/slx-studio-2-migration.md), and
[current architecture](docs/architecture.md) for scope and acceptance rules.

- [x] M0a: record the goal, verified starting point and migration gates
- [x] M0b: review/integrate required open-branch fixes and validate the combined baseline
- [x] M1: real Electron + Monaco file-edit/save workflow with Commands and Services
- [x] M2: modular Workbench, configuration and Python JSON-RPC adapter
- [x] M3: SLX Custom Editor and shared MATLAB/model/simulation workflow
- [x] M4: lazy Extension Host, first-party extensions and Windows install acceptance

Full MATLAB LSP semantics, a pausing debugger/profiler, remote execution,
Marketplace, richer Terminal/Git/AI integration, and Control Lab remain
post-2.0 capabilities and must keep explicit capability boundaries.

## v0.8 — Make it feel like a small real IDE ✅

- [x] Multi-file `.m` / `.slx` tabs
- [x] `.m` editor undo / redo
- [x] SLX session undo / redo with external-change conflict protection
- [x] Persisted block dragging through Simulink `Position`
- [x] Live wire following while blocks move
- [x] Output-port → input-port drag connections
- [x] Searchable Block Palette
- [x] Lightweight MATLAB syntax highlighting
- [x] Structured MATLAB error-line navigation
- [x] Workspace Variables after script execution
- [x] Unified structural + parameter-edit model history

## v0.9 — Run, inspect and navigate like an engineering IDE ✅

- [x] Run selected `.m` section / current selection
- [x] Stop/cancel long `.m` MATLAB execution
- [x] MATLAB figure/result preview inside Workbench
- [x] Plot `SimulationOutput` signals directly in the SLX editor
- [x] Editable variable inspector for explicit MATLAB expressions
- [x] Project-wide `.m` / `.slx` search and file quick-open
- [x] Save As for `.m` and `.slx`
- [x] Recent workspaces and crash-recovery drafts
- [x] Keyboard command palette
- [x] Better subsystem navigation and explicit multi-port rendering
- [x] Stop/cancel an active SLX simulation
- [x] Parameter sweeps and overlaid response curves

## v1.0 Beta — Stable lightweight engineering editor

- [x] MATLAB-style Command Window with shared session workspace checkpoint
- [x] Workspace variable editing
- [x] `.m` autosave / crash recovery
- [x] Recent project metadata
- [x] Command Palette
- [x] Cancellable SLX simulations and parameter sweeps
- [x] Parameter sweep overlay + convenience metrics
- [x] Read-only `slx-diff doctor` environment/workspace diagnostics
- [x] Windows EXE + installer workflow with opt-in `.m` / `.slx` file associations (CI smoke-tested)
- [x] Compatibility matrix scaffold with a real R2026a core-bridge record
- [x] Model overview metadata, large-subsystem rendering guard and Workbench parse cache
- [x] Asynchronous session-scoped workspace index for large-project navigation
- [x] Crash recovery / autosave

## 2.x engineering priorities

- [x] Electron Ctrl+P workspace search/quick-open over the bounded session index
- [ ] Expand the compatibility matrix across supported MATLAB/Simulink releases
- [ ] Broaden verified Simulink libraries and multi-port semantics
- [x] Plain Subsystem navigation and validated edit transactions
- [ ] Complete Subsystem create/open/edit UX for broader real-world models
- [ ] Model references and library links
- [ ] Stateflow, masks, variants and bus/data-type metadata
- [ ] Extend persistent MATLAB ownership to more graphical simulation/sweep paths
- [ ] Recovery/ownership after unexpected host process termination
- [x] Modular TypeScript frontend separation
- [x] Packaged Windows Electron install/launch/reopen/uninstall acceptance
- [ ] Stable third-party plugin installation/trust boundary and distribution story
- [ ] Control Lab built around explicit experiments and control metrics
- [ ] Performance regression budget for large workspaces/models in CI or reproducible local gates

The initial persistent mode and its tested boundaries are described in
[the session guide](docs/persistent-matlab.md). Subsystem and lightweight MATLAB
editor-assistance evidence is in
[the 2026-09-16 acceptance record](docs/2026-09-16-acceptance.md).

## Optional AI layer

- [x] OpenAI / DeepSeek / Kimi / MiniMax / GLM / Qwen / custom endpoints
- [x] Structured model tools and validated blueprints
- [x] `.m` code assistant with explicit diff preview before applying edits
- [x] MCP server for external coding agents
- [ ] Local Ollama / LM Studio presets
- [ ] Provider capability discovery
- [ ] Explicit per-provider capability/permission UI in the 2.x desktop

## Optional Git / review layer

- [x] Semantic SLX diff
- [x] Git-ref model comparison
- [x] Review Intelligence / blast radius
- [x] Agent Context
- [x] GitHub Action
- [ ] Review notes anchored to model SIDs
- [ ] Three-way model edit conflict UI
- [x] Read-only Git status/diff workflow for changed `.m` / semantic `.slx` files in Electron
- [ ] Git stage/unstage/commit workflow with explicit write confirmation

## Control engineering

The Control Lab is intentionally **not yet implemented**. Its numerical and
backend contract is frozen first so the UI cannot imply unsupported analysis.
See [docs/control-lab-plan.md](docs/control-lab-plan.md) and Issue #6.

- [ ] Control Core M0 bounded SISO analysis kernels
- [ ] Real MATLAB differential validation and provenance
- [ ] Control Lab extension with Step/Bode/Nyquist/metrics
- [ ] Explicit SLX I/O + operating-point linearization
- [ ] State-space analysis, LQR/MPC and domain workflows after the core gates

## Advanced Simulink compatibility

- [ ] Stateflow
- [ ] Masks
- [ ] Variant systems
- [ ] Library links
- [ ] Model references
- [ ] Bus/data type metadata
- [ ] Specialized toolbox blocks
