# SLX Studio 2.0 M2 foundation evidence

Status: **foundation implemented; M2 acceptance remains open.** Evidence is
from commit `d1030da` on `codex/slx-studio-2-foundation`, Windows 11
(`10.0.26200`, x64), 2026-09-08 local time.

## Implemented

- `ConfigurationStore` enforces a schema and default < user < workspace
  precedence. Workspace writes must be explicitly allowed; sensitive runtime
  choices cannot be replaced by a project setting.
- `ViewRegistry`, bounded `OutputService` and `ProblemsService` provide the
  first Workbench contribution contracts with disposable listeners.
- `CustomEditorRegistry` provides extension matching and priority. The desktop
  registers the MATLAB text editor; `.slx` deliberately reports an unavailable
  M3 viewport rather than showing a fake canvas.
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
python -m pytest -m "not matlab_integration" -ra   136 passed, 8 deselected
python -m ruff check .                              All checks passed
python -m ruff format --check .                     71 files already formatted
npm run typecheck                                   passed
npm run test:platform                               6 passed
npm run check:desktop                               passed (real Electron)
```

The real desktop test opens generated `.m`/`.slx` fixtures, exercises the
configuration and explicit unsupported-model boundary, and repeats the full
M1 workflow including recovery and 100 disposal cycles. It does not start
MATLAB, execute callbacks, parse a real model, or claim M3 behavior.

The exact `npm run measure:desktop` run at this commit reported:

```text
median fresh-process → editor accepts input: 666.975 ms
maximum:                                      703.48 ms
maximum Electron private memory at ready:    277.25 MiB
owned process-tree private memory at 30 s:    263.07 MiB
```

The raw report is the ignored local file
`output/measurements/desktop-m2-foundation.json`; it records the generated
fixture, OS, Node/Electron versions, warm-cache/instrumentation caveats and the
owned process tree. These are local observations, not release guarantees.

## Still required to close M2

Settings persistence and user/workspace file loading, Problems navigation,
parser/diff services over the typed protocol, backend restart controls, and a
real Workbench contribution lifecycle are still outstanding. Existing Python
CLI/REST and the accepted M1 desktop slice remain the rollback paths.
