# Roadmap

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
- [ ] Compatibility test matrix across supported MATLAB releases
- [x] Crash recovery / autosave
- [ ] More Simulink libraries and multi-port semantics
- [ ] Subsystem create/open/edit workflow
- [ ] Model references and library links
- [ ] Stable plugin interfaces for block catalogs, AI providers and analysis tools

## Optional AI layer

- [x] OpenAI / DeepSeek / Kimi / MiniMax / GLM / Qwen / custom endpoints
- [x] Structured model tools and validated blueprints
- [ ] `.m` code assistant with explicit diff preview before applying edits
- [ ] MCP server for external coding agents
- [ ] Local Ollama / LM Studio presets
- [ ] Provider capability discovery

## Optional Git / review layer

- [x] Semantic SLX diff
- [x] Git-ref model comparison
- [x] Review Intelligence / blast radius
- [x] Agent Context
- [x] GitHub Action
- [ ] Review notes anchored to model SIDs
- [ ] Three-way model edit conflict UI

## Advanced Simulink compatibility

- [ ] Stateflow
- [ ] Masks
- [ ] Variant systems
- [ ] Library links
- [ ] Model references
- [ ] Bus/data type metadata
- [ ] Specialized toolbox blocks
