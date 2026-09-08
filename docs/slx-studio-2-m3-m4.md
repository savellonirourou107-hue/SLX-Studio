# SLX Studio 2.0 M3/M4 core acceptance

Status: **implementation and acceptance in progress on `codex/slx-studio-2-foundation`.**
Passing narrow local gates does not close the complete M3/M4 acceptance list.
This is a development-branch evidence record, not a
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

The core migration does not require a full MATLAB
LSP, pausing debugger, profiler, general PTY terminal, remote execution,
Marketplace or exact Simulink graphical parity. Those are separate, scoped
extensions. Existing Python CLI/REST, legacy Workbench and non-pausing probes
remain supported rollback paths.

## Completion audit (2026-09-09)

The original migration charter remains the acceptance authority. Remaining
work is not reclassified as follow-up solely because an earlier slice passes:

- Complete the new UI model edit/save/conflict/undo/redo/simulation workflow.
- Expose variable editing, section Run, exported figures and diagnostic range
  navigation in the workbench, and verify the shared session with real R2026a.
- Exercise extension hangs/crashes, explicit restart and real custom-editor
  disposal, including first-party engineering workflows through the API.
- Verify install, launch, save, close/reopen and clean uninstall on Windows.
- Re-run candidate-specific legacy, protocol, Electron, MATLAB and resource gates.

Windows run `34258530344` found an Electron 44 lazy-install packaging bug:
`npm ci` does not itself populate `electron/dist`. Packaging now resolves the
Electron entry point before copying; a lazy-runtime regression and an actual
installer lifecycle test cover that failure path. The failed run is not
installation-success evidence.

The packaging fix at `5fd9076` passed [Windows run 34259962084](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/34259962084).
Both Electron and legacy PyInstaller jobs succeeded. The Electron job actually
installed to an isolated runner directory, launched the installed application,
saved and reopened a file, executed the packaged extension, then uninstalled
and checked installed-file and uninstall-registry cleanup. This result applies
to that candidate only; subsequent changes must repeat the gate.

Extension lifecycle hardening additionally covers per-host pending requests,
concurrent activation coalescing, discovery preserving running/failure state,
parent-link rejection, bounded protocol output, timeout termination, explicit
restart and manifest-removal cleanup. `npm run test:extensions` opens a real
Electron workbench while a trusted test extension loops forever, saves a file
before the host timeout, verifies failure disposal, then explicitly restarts
the corrected extension. `SLX_STUDIO_EXTENSION_ROOT` is an optional launcher
environment override for an explicitly trusted directory; workspace settings
cannot set it and discovery never activates code.
