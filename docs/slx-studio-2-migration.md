# SLX Studio 2.0 migration charter

Status: **M0b integration and M1 editing slice accepted locally; M2 in progress**. Updated: 2026-09-08.
The user-facing objective is [SLX Studio 2.0 项目目标](../SLX_STUDIO_2_GOAL.md).
This document defines future implementation, not features available in the beta.

## 1. Verified starting point

The initial preparation branch was `codex/slx-studio-2-plan`, based on
`484fd69e96dd9dc4fbcba18d5bdac34836a42453` (`codex/persistent-matlab-session`).
The accepted integration and M1 branch is now
`codex/slx-studio-2-foundation`, with the required fixes cherry-picked and no
existing GitHub PR merged.
The Python package is still `1.0.0b3`; no version bump or release is part of this charter.

On 2026-09-07, GitHub `main` still points to
`c7d3e6a8c4a98eb159c01deef8c5fa4f9a9cb3da`.
The persistent-worker change is [PR #20](https://github.com/savellonirourou107-hue/SLX-Studio/pull/20),
which remains open and targets the debug-foundation branch, not `main`.
Its [CI](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/34123616793)
and [Windows build](https://github.com/savellonirourou107-hue/SLX-Studio/actions/runs/34123617171)
completed successfully for `484fd69`. The Windows workflow checks EXE/installer
creation, not an interactive installed desktop workflow.

| Existing implementation | Disposition |
| --- | --- |
| `src/slxdiff/parser.py`, canonical model, diff/review/context | Preserve and reuse; keep inspection non-executing |
| Workspace root guards, atomic writes, source hashes, history | Preserve; add new transport and UI regression coverage |
| `studio.html` (105,929 bytes), `workbench.html` (72,084 bytes) | Legacy compatibility UI; stop adding new platform architecture here |
| `desktop.py`, Workbench HTTP server, PyInstaller workflow | Remain runnable until a replacement passes its acceptance gate |
| `persistent.py`, `msession.py`, job managers, process-tree cleanup | Reuse; do not implement a second independent MATLAB session system |
| Graphical SLX write/simulation/sweep bridges | Still batch-based; shared-session migration is unfinished |
| Existing MATLAB debug probes | Non-pausing only; no interactive debugger claim |

The historical preparation validation before integration was:

```text
python -m pytest -m "not matlab_integration" -ra
100 passed, 8 deselected in 14.43s
python -m ruff check .
All checks passed
python -m ruff format --check .
62 files already formatted
```

No MATLAB runtime code changed during preparation, so real MATLAB acceptance
was not rerun for this documentation-only step. Prior R2026a validation is
described in [the persistent-session guide](persistent-matlab.md); it is not
evidence for a future Electron application.

### Existing branch dependencies

These are observed PR relationships, not merge approval:

```text
main
├── #15 Command Window stream
│   └── #17 non-pausing debug probes
│       └── #20 persistent MATLAB  ← preparation base
├── #7 startup performance
│   └── #12 workspace index
│       └── #18 index hardening
├── #13 validated XML cache
└── #9 CLI patch validation
```

M0b must review these branches, select the required changes for an integration
branch, record commit provenance, resolve overlaps and rerun combined tests.
In particular, do not lose indexing/caching fixes by assuming they are already
in the persistent-worker branch. Integration-branch work is separate from
merging GitHub PRs into `main`. Recheck this snapshot before acting on it.

## 2. Decisions and amendments to the proposal

1. **Adopt Electron + TypeScript + Monaco, incrementally.** The desktop is a
   separate opt-in application during migration. Existing Python CLI users do
   not acquire an Electron/Node runtime dependency.
2. **Preserve Python in `src/slxdiff`.** Do not move it to `python/slxdiff` just
   to match a diagram. Such a move would affect imports, packaging and CI without
   delivering the first editing workflow.
3. **Commands and service boundaries start with M1**, not after building a large
   new UI. A typed in-process adapter may precede JSON-RPC, but components must
   not accumulate direct REST calls.
4. **Persistent MATLAB is an integration priority, not a greenfield feature.**
   M3 extends #20 after preserving its timeout, cancellation and no-replay semantics.
5. **Monaco is an editor, not the whole VS Code platform.** We must supply
   Workbench, contributions and MATLAB language capabilities. VS Code extension
   compatibility is not part of this migration. See the [Monaco FAQ](https://github.com/microsoft/monaco-editor#faq).
6. **Extension Host is a responsiveness boundary, not a security sandbox.**
   Third-party Node extensions execute with OS-user privileges unless a real
   additional isolation mechanism is implemented. Initial activation is limited
   to trusted, explicitly installed local extensions.
7. **No shell without a real workflow.** Nonfunctional Run, Debug, AI and
   Marketplace screens do not count toward a milestone. Do not imply a
   MATLAB semantic service exists when only syntax highlighting is available.

The layered core and contribution direction is informed by
[VS Code source organization](https://github.com/microsoft/vscode/wiki/source-code-organization).
Its separation of editor, workbench and application code is a reference, not
a requirement to replicate its entire codebase or internal dependency framework.

## 3. Target boundaries

```text
Electron main (window lifecycle, trusted workspace, owned processes)
  ├── restricted preload API
  │     └── TypeScript renderer / Workbench
  │           ├── Editor registry → Monaco text editor / SLX custom editor
  │           ├── Command registry → palette / menus / shortcuts / buttons
  │           └── Typed services → panels / diagnostics / configuration
  ├── backend supervisor → JSON-RPC over private stdio → Python services
  │                                                    └── MATLAB worker
  └── extension supervisor → Node Extension Host → declared contributions
```

The renderer does not get raw filesystem, shell, IPC or process-spawning APIs.
The canonical SLX model crosses a typed protocol; canvas components never read
or write ZIP members. Model writes still follow validated intent → MATLAB APIs.

### Proposed layout; create directories only when they contain real work

```text
apps/desktop/
  electron/                 main, preload, process lifecycle
  renderer/                 entry point, composition, styles
packages/
  core/                     events, disposable resources, service contracts
  workbench/                activity bar, tabs, panels, status bar
  editor/                   Monaco lifecycle and custom editor registry
  commands/                 command IDs, enablement, keybinding dispatch
  configuration/            defaults/user/workspace schema and precedence
  protocol/                 shared schemas, version/capability contracts
  extensions/               contribution API and host protocol
extensions/
  matlab/                   command, variables, diagnostics, figure contributions
  simulink/                 model editor, inspector, simulation contributions
src/slxdiff/                existing Python core and engineering services
tests/                     existing Python tests plus integration fixtures
```

Do not add empty packages, a heavy DI framework, remote backends, or an online
registry to satisfy the diagram. Initially use TypeScript and native DOM;
introduce another UI library only with a documented maintainability benefit.

### Core contracts

| Contract | Responsibilities and acceptance boundary |
| --- | --- |
| File / Workspace | Root-scoped access, lazy listing, change detection, atomic save, external-change conflicts |
| Editor | Stable URI → model mapping, dirty state, undo/redo, view state, disposal; never rebuild text models on each tab switch |
| Commands | One handler per ID, enablement, argument validation, disposal; palette/button/shortcut share the handler |
| Configuration | Schema, defaults < user < workspace; sensitive execution settings remain user-controlled |
| Diagnostics | File/range/severity/source, Problems navigation; syntax tokens are not semantic diagnostics |
| Tasks / MATLAB | Explicit job identity, bounded stream events, status, cancellation, session loss/restart information |
| Simulation | Model version, configuration, run identity, signals and result provenance; no hidden execution on open |
| Extensions | Declarative manifest, version checks, lazy activation, registered commands/views/editors, deactivate/dispose |

Planned `.m`, `.slx`, `.mat`, `.fig` and `.csv` editors use one editor registry.
Only `.m` and `.slx` are required for the initial core gate. MAT/FIG parsing or
execution requires its own safe design; never evaluate serialized content merely
because the UI displays a file tab.

## 4. Protocol and security design gates

The desktop uses a small allowlisted preload API. Electron main verifies the
originating window/frame and validates each payload before a privileged action.
Use sandboxed renderers, context isolation, no renderer Node integration and
a restrictive CSP. Bundle Monaco and workers locally; do not fix loading errors
by turning off `webSecurity` or fetching executable UI code from a CDN.
Serve packaged assets using a constrained application protocol. These choices
follow [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security).

Opening an untrusted project permits static inspection, not execution of
MATLAB, tasks, shell commands, AI tools or workspace-supplied extensions.
Workspace settings cannot silently replace Python/MATLAB executables, add
startup commands or override trust. Secrets stay out of workspace JSON, logs
and RPC payloads unless a specifically authorized operation requires them.

Adopt [JSON-RPC 2.0](https://www.jsonrpc.org/specification) as the envelope, with
version/capability negotiation and structured errors. For the initial local
transport, use bounded UTF-8 messages over private subprocess stdio. Define
length framing, maximum bytes, cancellation, notifications, shutdown and
backpressure in a protocol contract before integrating the renderer.
Do not claim RPC alone provides authentication, cancellation or remote support.

Protocol tests must cover split/coalesced frames, malformed/oversized messages,
Unicode paths, unknown methods, notifications, backend crashes and request-ID
correlation. stdout carries protocol only; diagnostics go to bounded stderr.
Large model/results data must be paginated or referenced, not copied into an
unbounded JSON event. Never expose arbitrary Python attribute/method execution.

First-party extensions run out of the renderer, and activation is demand-driven,
as described in [Extension Host](https://code.visualstudio.com/api/advanced-topics/extension-host)
and [Activation Events](https://code.visualstudio.com/api/references/activation-events).
Registering declarative UI does not automatically activate an extension.
An extension crash or busy loop must not freeze the editor; the host must be
terminable, show failure state, release contributions and allow explicit restart.
A shared host may lose multiple active extensions on restart: do not promise
per-extension process isolation without implementing it.

Before accepting `.slxext` packages, implement archive traversal/symlink/size
guards, manifest/API-version checks and explicit installation consent. Disable
install scripts and automatic activation from repositories. Capability labels
are disclosure and routing, not an OS-level sandbox for Node code.

## 5. Phased delivery and acceptance

### M0a — Charter and known baseline (prepared)

Deliverables: objective, current-state evidence, retained functionality, branch
dependency map, architecture boundaries and acceptance gates. No desktop
replacement or new runtime dependency is introduced by this documentation step.

### M0b — Integration baseline (accepted)

- Review the open branch chains and integrate required fixes in a dedicated branch.
- Preserve provenance and existing release/PR branches; do not force-push them.
- Run the full lightweight Python gate against the combined result.
- If integration changes MATLAB execution, rerun the real R2026a suite.
- Inventory security behavior and old-UI workflows to prevent silent migration losses.

The integration branch is `codex/slx-studio-2-foundation`. It retains the
provenance of the indexing, cache, CLI validation and persistent-worker changes
without merging their GitHub PRs into `main`. The combined lightweight gate is
131 passed and 8 deselected optional MATLAB tests.

### M1 — Real Electron / Monaco editing slice (accepted locally)

Deliver: an opt-in Electron app, offline Monaco assets/workers, Explorer,
multi-file tabs, a simple status area, Commands and minimal typed services.
No fake MATLAB/Debug results or embedded full legacy page as a claimed rewrite.

Acceptance:

- Open a real workspace, browse lazily, open two `.m` files and switch without losing edits.
- Undo/redo and find/replace operate on the correct model; closing a tab disposes it.
- Ctrl+S, a menu action and Command Palette invoke the same save handler.
- Save preserves Unicode, line endings and final newline where intended; a file
  changed externally is not overwritten without an explicit conflict decision.
- Closing a dirty tab/window offers save/discard/cancel; drafts and failure paths
  are tested, including read-only targets, deleted files and disk-write failures.
- Renderer cannot access Node or submit an arbitrary IPC channel/path; tests
  exercise workspace escape, symlinks/junctions, malformed payloads and foreign frames.
- Electron actually launches and these actions execute in automation; a browser
  mockup or successful build is not enough. No MATLAB process is launched.
- Record initial startup/memory/package measurements using the protocol below.

The implementation and actual Electron evidence are recorded in
[docs/slx-studio-2-m1-evidence.md](slx-studio-2-m1-evidence.md), from commit
`438efe7`. The evidence is local development coverage, not Windows installer or
real MATLAB coverage.

Rollback: continue using existing `slx-studio` / `slx-diff studio` commands.
Keep the new launch command separately named until the migration is accepted.

### M2 — Modular Workbench and Python service transport (foundation in progress)

Deliver: workbench contributions, Settings, Problems/Output panel contracts,
custom editor registration, JSON-RPC Python adapter and backend supervisor.

Acceptance:

- Existing workspace/parser/diff behavior is reachable through typed services
  without duplicating Python business rules in TypeScript.
- UI components do not call ad hoc HTTP endpoints or privileged IPC directly.
- Service/command/setting registries reject invalid or duplicate registrations
  and release listeners; default/user/workspace precedence is tested.
- Protocol fault tests, backend start/stop/restart and bounded output all pass;
  failed side-effecting operations are not retried automatically.
- Python CLI and legacy REST regression tests remain green; startup does not
  require a MATLAB installation, full recursive scan, extension host or network.

The current M2 foundation adds `ConfigurationStore` (default < user < workspace,
workspace-write and sensitive-key guards), `ViewRegistry`, bounded
`OutputService`/`ProblemsService`, and `CustomEditorRegistry`. The renderer now
uses the registries for the Explorer, Output and `.m` text contributions, while
all file access continues through the typed preload service. `.slx` reports that
no desktop editor is registered yet instead of presenting a mock viewport.
The private Python JSON-RPC adapter and backend supervisor are covered by split,
coalesced, malformed, crash and no-replay tests. This is not yet the full
Workbench, settings persistence, Problems navigation or parser/diff service
surface required to close M2.

Rollback: switch the transport adapter/desktop entry, without reverting file formats.

### M3 — Model + code + simulation workflow

Deliver: SLX Custom Editor split into viewport/selection/rendering/outline/inspector
components; MATLAB service and panels backed by the existing persistent worker;
diagnostic navigation, variables, figures and simulation provenance.

Acceptance:

- Code and SLX tabs coexist. Static SLX open does not execute MATLAB or callbacks.
- The existing supported model edit, save, conflict, undo/redo and simulation
  workflows pass through the new UI using real R2026a and isolated test models.
- Command Window → variable edit → file/section Run share one owned MATLAB
  session. Graphical simulation sharing is either implemented and tested or
  explicitly shown as independent; do not claim the M3 shared-session gate
  complete while an essential route still silently uses another workspace.
- Non-newline output streams without waiting for completion; buffers are bounded.
- Stop/timeout/close/crash terminate only owned descendants, disclose lost
  state and never replay commands. A host-crash test is required before making
  persistent execution the default in the new desktop.
- Large synthetic fixtures and a permissible real model are tested for viewport
  responsiveness and unsupported-feature warnings; synthetic success is not
  broad Simulink compatibility evidence. If no permissible real model is
  available, report that coverage gap instead of substituting a synthetic claim.

Rollback: expose an explicit legacy/batch choice, retaining lifecycle warnings.

### M4 — Extension platform and first installable 2.0 core

Deliver: small versioned Extension API, private Node host protocol, local trusted
extension loading and first-party MATLAB/Simulink contributions. Extend built-in
functionality rather than turning core into MATLAB/AI/Control-specific branches.

Acceptance:

- A sample extension contributes a real command, view and custom editor;
  removal/deactivation releases all registrations and event subscriptions.
- No activation or host process until an activation event requires it.
- A throwing or non-responsive extension cannot block editing and saving;
  failure attribution, disabling and explicit host restart are exercised.
- Invalid/traversing archives, incompatible API versions and untrusted workspace
  auto-activation are rejected. Document that Node extensions are trusted code.
- First-party MATLAB/Simulink workflows retain M3 functionality through the API.
- Windows packaging includes required Python/UI assets without bundling MATLAB;
  EXE launch, installation, close/reopen and clean uninstall are tested.
- Re-run legacy Python, protocol, Electron UI and real-MATLAB gates on the exact
  candidate commit. Publish measured limits and known gaps, not parity claims.

Only completion of M0b–M4 closes the core migration goal. Marketplace, full LSP,
interactive pausing debugger/profiler, remote execution, a general PTY terminal,
and additional Control/Git/AI extensions are subsequent scoped deliverables.
The existing non-pausing probes remain correctly named throughout.

## 6. Resource budgets and measurement protocol

These are **initial design targets, not measurements or guaranteed performance**.
The first M1 measurements may motivate a documented design revision; do not
silently raise a budget or relabel a warm/cache-assisted result as cold startup.

| Metric | Initial target / gate |
| --- | --- |
| Python core mandatory runtime dependencies | Remain zero |
| Empty desktop before engineering/extension activation | Zero MATLAB workers, zero extension hosts, zero remote requests |
| Fresh-process launch → editor accepts input | 10 runs: median ≤ 3 s, maximum ≤ 5 s on the recorded local SSD reference machine |
| Idle desktop private memory, 30 s after ready | ≤ 350 MiB across owned processes, excluding MATLAB but including Python if running |
| Windows desktop compressed artifact | ≤ 250 MiB; report installed footprint separately |
| Repeated editor open/close | No monotonic retained model/listener/worker growth over 100 cycles |
| Large workspaces / models | Bounded traversal, pagination, cancellable tasks; report counts, bytes and omitted/unsupported content |

Record OS, hardware, exact commit, release/debug mode, Electron/Node/Python/MATLAB
versions, antivirus context, cache state, workspace contents and raw observations.
Measure renderer, Electron/GPU/utility processes, Python and MATLAB separately
as well as the owned total. “Fresh process” does not mean a cleared OS disk cache.
Editor readiness must be an input/round-trip observation, not just window creation.

Use generated, deterministic workspaces with 1k/10k/100k entries and static
models with 1k/10k blocks to detect scaling and limits. Keep large fixtures and
outputs outside Git; record their generator, seed and hashes. Do not open or
upload unrelated private projects for benchmark coverage.

Control analyses and simulations must report parameters, solver/toolbox context,
model hash and run identity. A responsive UI is not evidence of correct control
analysis or simulation results.

## 7. Test and publication policy

Keep four evidence classes separate: pure unit/protocol tests, real MATLAB
process tests, actual Electron UI tests, and Windows packaging/install tests.
Mocks must be identified; skipped optional tests must remain visible in reports.

For each implementation slice, attach changed files, reproduction, tests, exact
commit, performance observations, compatibility risks and a rollback route.
Fix genuine failures before progressing. Do not bundle unrelated PRs or claim
an open stacked branch has shipped to `main`.

The current preparation request creates no GitHub Issue, PR, tag or release and
does not merge existing PRs. Publication and release operations remain explicit
follow-up actions. Local objective and migration documents can be reviewed now.
