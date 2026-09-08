# SLX Studio 2.0 M3/M4 core acceptance

Status: **implemented on `codex/slx-studio-2-foundation`; local gates are
green except the Inno Setup installer compile, which is exercised by the
Windows Actions job.** This is a development-branch acceptance record, not a
`main` merge or release claim.

## M3 runtime and model workflow

The Electron workbench now reuses `PersistentMatlabSession` for both Command
Window jobs and `.m` file/section jobs. The runtime is lazy: static `.slx`
inspection, tab creation and `matlab/status` do not launch MATLAB. A command or
script run is explicit and returns a bounded job identity, incremental
stdout/stderr offsets, variables, exported figures, tracepoint events,
diagnostics, cancellation and `state_lost`/session-reset information. Command
and script jobs share one worker and execution lock; a second active job is
rejected instead of racing the MATLAB base workspace.

`Simulink: Apply Validated Model Edit…` accepts the existing versioned edit JSON
contract. The Python service validates model hash, operation schema and block
semantics, then calls `apply_model_edit_with_matlab`; it never rewrites private
SLX ZIP/XML members. The edit is currently an in-place MATLAB batch operation,
and the static viewport reloads after success. Save As and graphical routing
remain in the legacy Workbench until their own UI contract is migrated.

## M4 extension and packaging workflow

`ExtensionHostManager` discovers only explicit trusted application extensions
under `extensions/`. Manifests are capped at 64 KiB, require API version `1`,
use directory-matching IDs, reject traversal/link targets and validate all
declared command/view/editor contributions. Activation is demand-driven and
spawns a private Node host with a bounded JSON-line protocol. Host failures,
timeouts and exits are attributed to the extension; deactivation waits for the
owned process and releases pending requests. These extensions are trusted Node
code with the OS user's privileges, not a security sandbox.

`extensions/sample.hello` contributes a command, sidebar view and `.slxpreview`
custom editor. The real Electron test activates it explicitly, executes its
command, observes the view, then deactivates it and verifies the view is gone.
Workspace-supplied extensions are not scanned or auto-activated.

The Windows packaging path copies the tested Electron runtime into
`release/SLXStudio-win32-x64`, places the built app, pure Python source and
first-party extensions under `resources/app`, and leaves MATLAB external. The
existing PyInstaller/Inno path remains intact. A second Inno script and
`build-windows.yml` job create `SLX-Studio-2-Setup-x64.exe`; the portable EXE is
launched by Playwright in the local package smoke test. Inno Setup is not
installed on the development machine, so installer compilation is a CI-only
step and is not reported as locally compiled.

## Gates

The final candidate must report these classes separately:

```text
python -m pytest -m 'not matlab_integration' -o addopts= -ra
python -m ruff check .
python -m ruff format --check .
npm run check:desktop
npm run test:package
$env:SLX_STUDIO_MATLAB = 'E:\\matlab2026\\bin\\matlab.exe'
python -m pytest tests/test_matlab_r2026a_integration.py tests/test_persistent_matlab_integration.py -o addopts= -ra
```

Pure Python/fake-worker tests prove protocol and lifecycle behavior only. The
R2026a suite proves the owned MATLAB worker and validated bridge on this host;
it is not a claim of broad Simulink release parity. Electron tests prove the
actual packaged/development renderer and IPC boundary. The Windows Action
proves the Inno installer and clean artifact paths on `windows-latest`.

## Deliberate follow-ups

The core migration is complete without pretending to include a full MATLAB
LSP, pausing debugger, profiler, general PTY terminal, remote execution,
Marketplace or exact Simulink graphical parity. Those are separate, scoped
extensions. Existing Python CLI/REST, legacy Workbench and non-pausing probes
remain supported rollback paths.
