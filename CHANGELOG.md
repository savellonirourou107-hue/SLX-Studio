# Changelog

## 1.0.0b2 - 2026-09-02

- Hardened Simulink path handling for literal `/` and newline-containing block names across parsing, navigation, rename and edit paths.
- Added stale recovery-draft detection when `.m` files change externally.
- Made failed simulation-after-edit results report disk changes so the Workbench refreshes and preserves undo history.
- Restricted automatic AI/Blueprint parameter writes to safe allowlisted values and rejected callback/code/function-call payloads.
- Serialized script, Command Window, simulation, sweep and Agent MATLAB execution through one shared gate, including cancellation while queued.
- Made structural model writes transactional by backing up original SLX bytes, saving under the real model name and restoring atomically on failure.
- Fixed shared MATLAB workspace semantics to restore/execute/snapshot the base workspace via `assignin` / `evalin` / `save -struct`.
- Added fallback discovery of standard Windows MATLAB install locations when MATLAB is not on `PATH`.
- Added desktop browser fallback when the embedded WebView cannot initialize.
- Tightened provider presets and Kimi environment-variable compatibility.
- Restricted Sweep values and Simulation Stop Time convenience inputs to bounded finite numeric scalars.
- Expanded adversarial regression coverage from 53 to 69 tests and added `docs/BETA2_SELF_TEST.md`.

## 1.0.0b1 - 2026-09-02

- Added a MATLAB-style Command Window to the Workbench with project-scoped shared workspace state persisted through a temporary session checkpoint.
- Added explicit Workspace Variable editing via MATLAB expressions.
- Added `.m` recovery drafts/autosave stored in the user state directory rather than the project/Git tree.
- Added Recent Projects state and surfaced recent workspace metadata in the Workbench welcome view.
- Added a keyboard Command Palette (`Ctrl/Cmd+Shift+P`).
- Added deterministic Simulink Parameter Sweep jobs with `start/status/stop`, original-parameter restoration, overlaid curves and bounded convenience metrics.
- Added cancellable Workbench-managed SLX simulation jobs and routed graphical Studio simulation requests through the parent job manager.
- Unified Stop dispatch across `.m`, SLX simulation and sweep jobs.
- Added Workbench block-selection messaging so selected SLX parameters can prefill Sweep configuration.
- Added session-aware script runner checkpoints so `.m` files/sections and Command Window operations can share variables without embedding a heavyweight MATLAB desktop session.
- Added a v1.0 Beta standalone Workbench demo and updated bilingual product documentation.
- Expanded regression coverage to 53 tests.

## 0.9.0 - 2026-09-02

- Added Ctrl/Cmd+Enter execution for the current MATLAB `%%` section or selected code with source-line error mapping.
- Reworked `.m` execution into managed background MATLAB jobs with start/status/stop APIs and real process cancellation.
- Added MATLAB Figure capture and embedded plot previews in the Workbench.
- Added bounded numeric curve extraction from `Simulink.SimulationOutput`, including direct `timeseries` and `Simulink.SimulationData.Dataset` values.
- Added Workspace/Plots tabs shared by script and model runs.
- Added Ctrl/Cmd+P Quick Open and Ctrl/Cmd+Shift+F project search across `.m` text plus statically parsed `.slx` blocks, parameters and signals.
- Added Save As for `.m` and `.slx` project files.
- Added explicit multi-port rendering/drag-connect semantics inferred from model connections.
- Added double-click Subsystem navigation into matching child systems.
- Added a v0.9 run/plots standalone demo and browser smoke validation.
- Expanded regression coverage to 46 tests.

## 0.8.0 - 2026-09-02

- Added multi-file Workbench tabs for `.m` and `.slx`, including dirty-state tracking and editor keyboard shortcuts.
- Added lightweight MATLAB syntax highlighting, editor undo/redo, structured error-line navigation and workspace-variable metadata after `.m` execution.
- Added persistent graphical SLX block dragging backed by conflict-checked `Position` edits through MATLAB.
- Added live wire-following while blocks move and direct output-port → input-port drag connections.
- Replaced the basic add-block dropdown with a searchable Block Palette.
- Added session-scoped SLX undo/redo using temporary model snapshots plus SHA-256 protection against external model changes.
- Unified structural edits and Inspector parameter patches into the same Workbench model history.
- Added Workbench run-state messaging and richer console/variable panels.
- Added v0.8 rendered Workbench/SLX-editor demos and regression coverage; suite expanded to 38 tests.

## 0.7.0 - 2026-09-02

- Repositioned **SLX Studio** as a lightweight `.m` + `.slx` editor rather than a review-first tool.
- Added the Workbench shell with project file tree, unified console and English / 中文 UI.
- Added editable `.m` files with line numbers, Ctrl/Cmd+S, F5/Run and MATLAB `-batch` execution with captured stdout/stderr.
- Added `slx-studio` desktop entry point and optional pywebview desktop shell.
- Added Windows `SLXStudio.exe` build workflow using GitHub Actions + PyInstaller.
- Added new `.m` and new `.slx` creation from the Workbench.
- Added structural SLX edit protocol with source SHA-256 conflict binding.
- Added MATLAB-backed add block, rename block, delete block, add line and delete line operations.
- Added graphical SLX editor actions for `+ Block`, Rename, Connect, Delete, Remove connection, Save Model and Run Simulation.
- Kept AI providers, semantic diff, Review Intelligence and GitHub review as optional secondary capabilities.
- Added workspace path traversal protection and atomic `.m` saves.
- Expanded regression coverage to 33 tests.

## 0.6.0 - 2026-09-02

- Added a loopback-only **BYOK AI Model Gateway** for model analysis, staged edits and safe model design.
- Added `slx-diff studio --blank` for agent-driven model design without an existing SLX file.
- Added first-class provider presets for DeepSeek, Kimi/Moonshot, MiniMax, GLM/Zhipu and Qwen/Alibaba Model Studio, plus OpenAI and custom OpenAI-compatible endpoints.
- Added `GET /api/v1/providers` and provider metadata in `/api/v1/capabilities`.
- Added environment-variable API-key fallback and clear-on-provider-switch credential handling in Studio.
- Added a constrained `slx-model-blueprint` schema, block/parameter catalog, no-MATLAB validation and browser preview.
- Added safe Agent tools for capability discovery, deterministic structural graph analysis, model summary, block inspection, downstream reach, staged parameter edits and blueprint submission.
- Added an explicit restricted MATLAB blueprint build path; arbitrary MATLAB source is never accepted from the LLM.
- Added `/api/v1/agent/chat`, `/api/v1/tools/call`, `/api/v1/blueprints/validate` and `/api/v1/blueprints/build`.
- Hardened OpenAI-compatible tool argument parsing across providers.
- Added Agent API documentation and provider-registry regression tests.

## 0.5.0 - 2026-09-02

- Added English / Simplified Chinese switching across the full SLX Studio UI.
- Added explainable **Review Intelligence** with deterministic static review-priority scoring.
- Added downstream signal-flow blast-radius analysis and affected-Outport reporting, using both before/after topology for edits and rewires.
- Added a reviewer hotspot queue and impact-path highlighting in visual Diff mode.
- Added `slx-diff review OLD NEW` with text, Markdown and JSON renderers.
- Added `slx-diff context OLD NEW` for compact AI-agent change context.
- Added one-click Agent Context download from SLX Studio.
- Added Review Priority and top hotspots to GitHub PR reports.
- Added `review-priority` and `high-review-count` GitHub Action outputs.
- Added browser-level bilingual/impact-path regression checks and Review Intelligence tests.
- Added `slx-diff --version` and exported the Review Intelligence / Agent Context APIs from the package root.
- Repositioned the project around Git/PR/AI review rather than cloning MATLAB/Simulink.

## 0.4.0

- Turned SLX Studio from a read-only viewer into a staged parameter editor.
- Added portable `.slxpatch.json` documents with source SHA-256, before/after values, SID and system identity.
- Added preflight conflict detection so stale patches fail before MATLAB is launched.
- Added `slx-diff studio MODEL` with a loopback-only, token-protected local bridge.
- Added MATLAB discovery plus `slx-diff matlab-status`.
- Added `slx-diff apply MODEL PATCH -o OUTPUT` for non-interactive MATLAB-backed patch application.
- Added an opt-in simulation path using MATLAB `sim` and a Studio **Run Simulation** action.
- Added bridge subprocess/protocol tests using a fake MATLAB executable, plus browser-level editor interaction checks.
- Added SHA-256 metadata to canonical model inspection.

## 0.3.0

- Added **SLX Studio**, a self-contained browser visualization for `.slx` models.
- Added `slx-diff view MODEL [COMPARE]` for interactive model and visual diff viewing.
- Added `slx-diff html MODEL [COMPARE] -o report.html` for portable HTML review artifacts.
- Reuses stored block positions when available and falls back to automatic graph layout.
- Added model explorer, parameter inspector, search, pan/zoom/fit, Diff/Before/After modes, and SVG export.
- Added safe JSON embedding for untrusted model strings and Studio rendering tests.

## 0.2.0 - 2026-09-02

- Added `slx-diff git-diff --base ... --head ...` to discover and compare changed SLX files directly from Git history.
- Added a reusable composite GitHub Action that writes a Job Summary and upserts one PR review comment.
- Added support for added, removed, modified, copied, and renamed model paths in Git diffs.
- Added `parse_slx_bytes()` so Git blobs can be inspected without temporary files.
- Added an explicit JSON schema version to `inspect` output.
- Added archive/XML safety limits and rejection of DTD/entity declarations for untrusted PR inputs.
- Added a MATLAB/Simulink demo generator that creates genuine `.slx` files for end-to-end validation.
- Updated CI to current Node 24-based `checkout@v6` / `setup-python@v6` actions and Python 3.14 coverage.

## 0.1.0 - 2026-09-02

- Initial dependency-free SLX ZIP/XML parser.
- Semantic block and parameter comparison.
- Signal connection comparison, including branches.
- Text, Markdown, and JSON renderers.
- Layout-noise filtering with opt-in layout diffs.
- Canonical model inspection command.
- CI, tests, security and contribution docs.
