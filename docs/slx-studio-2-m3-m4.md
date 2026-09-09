# SLX Studio 2.0 M3/M4 core acceptance

Status: **M3/M4 accepted for the `v2.0.0` release candidate.**
All candidate-specific local gates and the Windows Actions package/install
gate passed. The release keeps the documented lightweight scope and known
MATLAB/Simulink feature boundaries below.

## M3 runtime and model workflow

The Electron workbench now reuses `PersistentMatlabSession` for both Command
Window jobs and `.m` file/section jobs. The runtime is lazy: static `.slx`
inspection, tab creation and `matlab/status` do not launch MATLAB. A command or
script run is explicit and returns a bounded job identity, incremental
stdout/stderr offsets, variables, exported figures, tracepoint events,
diagnostics, cancellation and `state_lost`/session-reset information. Command
and script jobs share one worker and execution lock; a second active job is
rejected instead of racing the MATLAB base workspace.

The new model editor exposes parameter edits, validated JSON edits, undo/redo and
an explicit simulation action. Jobs are asynchronous: MATLAB writes an isolated
copy, the source SHA-256 is checked again, then a bounded atomic replacement and
disk-backed history record are committed. A failed history commit rolls back the
new bytes when the source is still our version. Simulation uses an independent
`SimulationInput` batch session, reports model hash/solver/release provenance,
and never modifies the source or shares Command Window variables. Save As and
graphical routing remain in the legacy Workbench until their own UI contract is
migrated.

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
`extensions/firstparty.matlab` and `extensions/firstparty.simulink` provide
first-party declarative commands; their actions route through the typed
renderer/preload services, so trusted Node extension code cannot spawn MATLAB or
access workspace files directly.
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
npm run measure:desktop
$env:SLX_STUDIO_MATLAB = 'E:\\matlab2026\\bin\\matlab.exe'
python -m pytest tests/test_matlab_r2026a_integration.py tests/test_persistent_matlab_integration.py -o addopts= -ra
```

Pure Python/fake-worker tests prove protocol and lifecycle behavior only. The
R2026a suite proves the owned MATLAB worker and validated bridge on this host;
it is not a claim of broad Simulink release parity. Electron tests prove the
actual packaged/development renderer and IPC boundary, including staged model
edit/undo/redo/simulation and backend-crash cleanup. The Windows Action proves
the Inno installer and clean artifact paths on `windows-latest`.

## Deliberate follow-ups

The core migration does not require a full MATLAB
LSP, pausing debugger, profiler, general PTY terminal, remote execution,
Marketplace or exact Simulink graphical parity. Those are separate, scoped
extensions. Existing Python CLI/REST, legacy Workbench and non-pausing probes
remain supported rollback paths.

## Completion audit (2026-09-09)

The original migration charter remains the acceptance authority. The full M3/M4
candidate gate is now closed for this development branch:

- Real R2026a Electron acceptance passed command streaming, variable editing,
  file/section Run in the shared persistent session, figure rendering,
  diagnostic line navigation, cancellation/no replay, backend crash cleanup,
  staged model edit/undo/redo, independent `SimulationInput` simulation and
  source-hash conflict protection.
- Extension acceptance passed lazy trusted-host activation, bounded output,
  hang/failure attribution, explicit restart, custom-editor tab disposal and
  first-party MATLAB/Simulink typed routes.
- Local gates passed: 148 Python tests (9 expected skips), `ruff check`,
  `ruff format --check`, TypeScript, 15 platform tests, development Electron,
  extension and packaged Electron tests, plus the 9-test real R2026a Python
  integration suite.
- Resource baseline passed: ten-run startup median 792 ms, worst 818 ms;
  ready-time Electron private memory 282 MiB and owned 30-second process-tree
  snapshot 262 MiB.
- GitHub [CI run 34269731398](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/34269731398)
  passed all Python versions and the Windows worker-ownership job.
- GitHub [Windows run 34269757508](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/34269757508)
  passed Electron portable/package/installer lifecycle and legacy
  PyInstaller EXE/installer jobs, including clean uninstall checks.

The installer compiler is intentionally a CI step because Inno Setup is not
installed on the development machine; CI is the authoritative installer build
and lifecycle evidence.

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
