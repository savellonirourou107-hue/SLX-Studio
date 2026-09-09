# SLX Studio 2.0 M2 foundation evidence

Status: **M2 platform foundation accepted locally; M3 is next.** Evidence is
from commit `a495be6` (with the preceding foundation commits) on `codex/slx-studio-2-foundation`, Windows 11
(`10.0.26200`, x64), 2026-09-08 local time.

## Implemented

- `ConfigurationStore` enforces a schema and default < user < workspace
  precedence. Workspace writes must be explicitly allowed; sensitive runtime
  choices cannot be replaced by a project setting.
- `ViewRegistry`, bounded `OutputService` and `ProblemsService` provide the
  first Workbench contribution contracts with disposable listeners.
- `WorkbenchContributionRegistry` owns activation, concurrent activation
  coalescing, deactivation and failure cleanup for built-in contributions.
- `CustomEditorRegistry` provides extension matching and priority. The desktop
  registers the MATLAB text editor and a read-only `.slx` static-summary
  contribution rather than showing a fake canvas.
- The typed protocol exposes parser-backed `model/inspect` and `model/diff`
  calls. Static model inspection never starts MATLAB or executes callbacks.
- Model inspect/diff pages are cursor-based, bounded to 512 items and 2 MiB per
  result list, and include totals/next cursors for large-model clients.
- Versioned user/workspace settings are persisted with schema validation, file
  hashes, atomic replacement and a bounded 64 KiB format. The explicit Python
  backend restart command rejects concurrent transitions and never replays work.
- The renderer uses typed `DesktopServices` for workspace, document, save and
  recovery operations. It has no REST calls, raw filesystem API, Node runtime or
  arbitrary IPC channel.
- The Python stdio JSON-RPC adapter and bounded backend supervisor are exercised
  by malformed-frame, split/coalesced-frame, backpressure, crash and no-replay
  tests.
- Windows save handling retries a bounded transient sharing/permission failure,
  rechecking the source hash before every retry. Persistent errors and external
  changes remain fail-closed.

## Evidence

```text
python -m pytest tests -m "not matlab_integration" -o addopts= -ra  137 passed, 8 deselected
python -m ruff check .                              All checks passed
python -m ruff format --check src tests             43 files already formatted
npm run typecheck                                   passed
npm run test:platform                               9 passed
npm run check:desktop                               passed (real Electron)
```

The real desktop test opens generated `.m`/`.slx` fixtures, exercises the
parser-backed static summary and typed diff, persists a workspace setting,
restarts the owned Python backend, and repeats the full M1 workflow including
recovery and 100 disposal cycles. It does not start MATLAB, execute callbacks,
parse a real user model, or claim M3 behavior.

The exact `npm run measure:desktop` run at commit `a495be6ccf4d59fdf1225087bad674f7cc6d8cfe` reported:

```text
median fresh-process → editor accepts input: 676.785 ms
maximum:                                      734.17 ms
maximum Electron private memory at ready:    273.890625 MiB
owned process-tree private memory at 30 s:    253.62109375 MiB
```

The raw report is the ignored local file
`output/measurements/desktop-m2-foundation.json`; it records commit `a495be6`, the generated
fixture, OS, Node/Electron versions, warm-cache/instrumentation caveats and the
owned process tree. These are local observations, not release guarantees.

## M2 closure and rollback

The paginated model protocol and real Workbench contribution lifecycle are now
implemented and covered by Python, platform and Electron tests. Existing
Python CLI/REST and the accepted M1 desktop slice remain the rollback paths.
M2 is a local platform acceptance only; it does not claim a graphical Simulink
viewport, interactive MATLAB debugging or real-model compatibility.

## Static model service follow-up

The next slice connects the existing root-scoped Python parser and structural
diff to the allowlisted desktop API. Selecting `.slx` reports block/connection
counts in Output; it is not a graphical model editor. JSON responses are capped
at 16 MiB, with a structured error on overflow rather than an unbounded stream.

The actual Electron gate passed with a generated two-block, one-connection SLX
ZIP fixture and an identical-model diff request. It also reran the M1 workflow
and 100 editor disposal cycles. This is static ZIP/XML acceptance, not a
MATLAB-created model or broad Simulink compatibility claim. TypeScript checks
and platform tests passed; settings persistence is included in this follow-up
slice.

## Persisted settings and explicit restart follow-up

- A standalone `ConfigurationFiles` adapter reads versioned, bounded user and
  workspace JSON. Invalid keys are reported, never treated as execution settings.
- The settings dialog changes the actual Monaco font size/minimap without
  rebuilding its text model. Workspace overrides survive an application restart.
- Updates are serialized, SHA-256 checked and atomically replaced. Malformed
  files, oversized content and Windows junction targets fail closed.
- `Backend: Restart Python Service` replaces the owned Python process without
  replaying requests. Concurrent transitions are rejected; closing also cleans
  up a backend that is still starting.

Actual Electron coverage includes the settings dialog, live Monaco font-size
check, configuration after restart, explicit backend restart and concurrent
restart rejection, parser warnings in the Problems panel and click-through to
the registered model contribution, plus the full M1 regression path. The local settings dialog
screenshot is `output/playwright/desktop-settings.png` (ignored output).
