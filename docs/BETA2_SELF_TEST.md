# v1.0.0 Beta 2 self-test / hardening report

Date: 2026-09-02

This report records the additional adversarial testing performed after v1.0.0 Beta 1. The goal was to find defects rather than to demonstrate only expected happy paths.

## What was exercised

- Full Python regression suite (69 tests).
- Python bytecode compilation of `src/` and `tests/`.
- Real parsing of synthetic SLX ZIP/XML packages, including Unicode, newlines, literal `/` in block names, malformed XML and archive-limit cases.
- Workspace sandbox checks for `..`, absolute paths and symlink escape attempts.
- Loopback HTTP API checks for missing/invalid tokens, malformed JSON and invalid paths.
- Background job start/status/stop semantics, including cancellation while waiting for the shared MATLAB execution gate.
- Fault injection around staged parameter writes, simulation failure and rollback/history refresh.
- AI Blueprint/edit validation with code-like and function-call payloads.
- Provider-registry construction and local mock OpenAI-compatible tool-call loops.
- Actual inline JavaScript extraction from `workbench.html` and `studio.html`, checked with Node.js syntax validation.
- GitHub Actions YAML parsing.
- Clean wheel build, clean-target installation, package-data presence and `slx-diff --version`.
- Windows installer configuration review, including optional (non-default-hijacking) `.m` / `.slx` Open-With registration.

## Defects found and fixed

1. **Literal slash in Simulink block names.** A block named `A/B` requires `A//B` in a Simulink block path. Parsing and edit/navigation code now use one canonical path helper everywhere.
2. **Stale recovery draft.** A recovery draft could be offered after the on-disk `.m` file had been changed externally. Recovery metadata is now checked against current disk state.
3. **Simulation failure after staged write.** A model could already be changed when simulation later failed, leaving the parent Workbench visually stale. The job result now reports that the model changed and the UI refreshes/history remains undoable.
4. **Over-permissive automatic AI parameter expressions.** Automatic Blueprint/edit paths could carry MATLAB function calls in parameter values. Agent-controlled writes now use catalog/parameter allowlists and reject callback/code/function-call payloads. The explicit user Command Window remains an execution surface by design.
5. **Incomplete `/` handling in rename/subsystem paths.** Fixed all edit/navigation layers, not only the parser.
6. **Concurrent MATLAB writers.** Script, Command Window, simulation, sweep and Agent build jobs could compete for project/session state. They now share one execution gate and queued cancellation is honored.
7. **Unsafe temporary model-name strategy.** A temporary `.slx` name used for transactional saving could itself be an invalid Simulink model name. Workbench model writes now back up the original bytes, save the real model name, then restore atomically on failure.
8. **Shared-workspace scope bug.** Loading a checkpoint in a MATLAB wrapper function does not make those variables equivalent to Command Window/base-workspace variables. Runners now explicitly restore/execute/snapshot the MATLAB base workspace via `assignin` / `evalin` and `save -struct`, avoiding internal-variable name collisions.
9. **MATLAB discovery for desktop users.** A normal Windows MATLAB installation may not be on `PATH`. Discovery now searches standard install locations as a fallback.
10. **Desktop WebView startup fragility.** If the embedded WebView cannot initialize, the desktop launcher now falls back to the system browser rather than exiting.
11. **Provider preset drift.** MiniMax/Qwen/Kimi presets were tightened against current official compatibility docs; Kimi accepts both the project `KIMI_API_KEY` convention and `MOONSHOT_API_KEY` alias.
12. **Sweep/StopTime expression leakage.** Parameter Sweep comma values and Simulation Stop Time could carry arbitrary expression text. The v1.0 convenience UI now accepts only bounded finite numeric scalars; arbitrary MATLAB expressions remain available only through explicit script/Command Window execution.

## What is *not* claimed as verified

The test container does **not** contain MATLAB or Simulink. Therefore Beta 2 does not claim that a real R2026a process executed every generated `set_param`, `save_system`, `sim`, `exportgraphics`, `assignin` or `evalin` command. Those paths are covered by protocol/fake-executable/fault-injection tests and by source generation checks, but the real MathWorks runtime boundary remains unexercised here.

Likewise, no paid third-party AI credentials were available. Provider endpoints/defaults were checked against current official documentation and the provider/tool-calling loop was tested against a local mock endpoint; no claim is made that every vendor account/region/plan accepts every optional model ID.

## Release gate result

Within the available environment, no known reproducible blocker remains after the Beta 2 fixes. The release should still be labeled **Beta**, not stable/RC, until at least one real MATLAB/Simulink compatibility matrix run is completed and the Windows GitHub Action produces/launches the actual portable EXE and installer.
