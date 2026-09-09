# SLX Studio 2.0 M1 evidence

Status: **M1 first editing slice accepted locally; M2 platform work remains.**
This is an opt-in development desktop, not a 2.0 release or a MATLAB IDE parity
claim. Evidence was collected on Windows 11 (`10.0.26200`, x64) from commit
`438efe7` on `codex/slx-studio-2-foundation`, 2026-09-08 local time.

## What was exercised

`npm run build` produced the local Electron bundle. `npm run test:desktop` then
launched the actual Electron executable with a generated E-drive workspace and
executed these UI actions through the renderer:

- two real `.m` files, including a Unicode BOM/CRLF file, opened as independent
  Monaco models and switched without losing edits;
- Undo, Redo, Find, Replace All, Ctrl+S, the application File → Save menu and
  the Command Palette all reached the same typed save service;
- external modification was detected and left the disk version untouched;
- dirty-tab Cancel/Discard and dirty-window Cancel were exercised;
- recovery draft persisted across an application restart;
- a foreign BrowserWindow was rejected by the main-process IPC sender check;
- 100 open/close cycles left zero Monaco models;
- the renderer had no `process`, `require` or raw `ipcRenderer` surface.

The test also verifies the normal Python backend response reports
`matlab_started: false`. No MATLAB process is launched by this slice. The
workspace only contains generated fixtures; this is not Simulink behavior
coverage.

## Automated gates

```text
python -m pytest -m "not matlab_integration" -ra   131 passed, 8 deselected
python -m ruff check .                              All checks passed
python -m ruff format --check .                     69 files already formatted
npm run typecheck                                   passed
npm run test:platform                               4 passed
npm run test:desktop                                passed (real Electron)
```

The Python tests include root escape, symlink/Junction, malformed framing,
Unicode, read-only/deleted/oversized files, atomic-write failure, pagination,
RPC notifications and a real stdio subprocess. `test:platform` adds split and
coalesced UTF-8 frames, response-size bounds, command validation, pending-request
backpressure and an owned backend crash with no replay.

## Initial resource observation

The reproducible command `npm run measure:desktop` used ten fresh Electron
processes and a generated one-line `.m` workspace. The first run was sampled
again 30 seconds after editor readiness. The OS disk cache was not flushed,
Playwright instrumentation was present, and antivirus context was not
controlled; these are observations, not a performance guarantee.

```text
median fresh-process → editor accepts input: 674.97 ms
maximum:                                      709.80 ms
maximum Electron private memory at ready:    274.70 MiB
owned process-tree private memory at 30 s:    259.09 MiB
```

The 30-second process-tree total includes the owned Python RPC child and
Electron descendants, excludes MATLAB (not started), and excludes unrelated
processes. The raw JSON is intentionally ignored and may be overwritten by a
later foundation measurement. The current renderer/electron JavaScript and
CSS bundle is about 3.4 MiB; the unpacked Electron runtime is about 368 MiB and
is not a distributable installer. A compressed Windows artifact and clean
install/uninstall measurement are deliberately deferred to M4 packaging.

## Boundaries and rollback

This slice provides MATLAB syntax tokenization only. It does not provide a
MATLAB LSP, semantic diagnostics, `.slx` custom editor, simulation, terminal,
interactive debugger, profiler, remote execution, extension host or
Marketplace. Existing Python CLI, REST/legacy HTML and MATLAB bridge remain the
rollback path. The next work is the modular Workbench/configuration and the
service contract needed before connecting the existing persistent MATLAB worker.
