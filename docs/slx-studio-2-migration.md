# SLX Studio 2.0 migration charter

Status: **M0b–M4 accepted and shipped on `main` as `v2.0.0`**. Updated: 2026-09-09.
The user-facing objective is [SLX Studio 2.0 项目目标](../SLX_STUDIO_2_GOAL.md).
This document records the completed 2.0 migration and its explicit boundaries.

## 1. Verified starting point

The initial preparation branch was `codex/slx-studio-2-plan`, based on
`484fd69e96dd9dc4fbcba18d5bdac34836a42453` (`codex/persistent-matlab-session`).
The accepted integration branch was `codex/slx-studio-2-foundation`; its
required fixes are now consolidated on `main` and in the `v2.0.0` release.
That branch is retained as historical provenance, not as a second source of
truth. New work should branch from `main`.
The Python package and Electron desktop are versioned `2.0.0` for the release.

The historical feature PRs remain provenance references; the release branch
was validated as one coherent candidate. The Windows package/installer gates
and their limits are recorded in the [M3/M4 acceptance record](slx-studio-2-m3-m4.md).

| Existing implementation | Disposition |
| --- | --- |
| `src/slxdiff/parser.py`, canonical model, diff/review/context | Preserve and reuse; keep inspection non-executing |
| Workspace root guards, atomic writes, source hashes, history | Preserve; add new transport and UI regression coverage |
| `studio.html` (105,929 bytes), `workbench.html` (72,084 bytes) | Legacy compatibility UI; stop adding new platform architecture here |
| `desktop.py`, Workbench HTTP server, PyInstaller workflow | Remain runnable as the legacy compatibility path alongside the 2.0 desktop |
| `persistent.py`, `msession.py`, job managers, process-tree cleanup | Reuse through the Electron MATLAB runtime; do not implement a second independent session system |
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

These are historical preparation results, not the current suite size. On
2026-09-09, `python -m pytest -ra` on Windows with optional MATLAB integration
tests disabled reported **148 passed, 9 skipped**. Counts depend on the platform
and whether the licensed integration gates are enabled.

No MATLAB runtime code changed in this documentation update; MATLAB was not
rerun for it. Real-runtime evidence and its scope are recorded separately in
[the persistent-session guide](persistent-matlab.md) and the
[M3/M4 acceptance record](slx-studio-2-m3-m4.md).

### Current branch and release map

`main` is now the release source of truth:

```text
main (stable 2.0.0)
├── v2.0.0 release
├── codex/slx-studio-2-foundation (historical 2.0 integration branch)
└── future feature branches (branch from main)
```

Historical implementation PRs #9, #13, #15, #17 and #20 remain linked for
review provenance. Their accepted outcomes are included in `main`; an open
historical branch must not be mistaken for an unreleased feature.

M0b reviewed these branches, selected the required changes for one integration
branch, recorded provenance, resolved overlaps and reran the combined tests.
The resulting release is the only supported 2.0 baseline; use the historical
PRs for context rather than merging their branches again.

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

The integration branch was `codex/slx-studio-2-foundation`. It retains the
provenance of the indexing, cache, CLI validation and persistent-worker changes;
their accepted outcomes are now in `main`. Its historical M0b lightweight gate
was 131 passed and 8 deselected optional MATLAB tests; the current verification
snapshot is listed in section 1 above.

### M1 — Real Electron / Monaco editing slice (accepted and shipped)

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

Rollback: continue using existing `slx-studio` / `slx-diff studio` commands for
the legacy Workbench. The 2.0 Electron launch command is now supported in the
stable release and can be adopted workspace by workspace.

### M2 — Modular Workbench and Python service transport (accepted and shipped)

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

The M2 foundation adds `ConfigurationStore` (default < user < workspace,
workspace-write and sensitive-key guards), persisted user/workspace settings,
`ViewRegistry`, bounded `OutputService`/`ProblemsService`, and
`CustomEditorRegistry`. The renderer now uses a `WorkbenchContributionRegistry`
to activate, deactivate and reload the Explorer, Output and `.m`/`.slx` editor
contributions; registrations are disposed on deactivation and activation
failures cannot leak partial state. All file access continues through the typed
preload service. Selecting `.slx` shows parser-derived block/connection counts
in Output without executing MATLAB; structural `model/inspect` and `model/diff`
services reuse the Python core. The bounded static model viewport is included
in the shipped M3 workflow.
The private Python JSON-RPC adapter and backend supervisor are covered by split,
coalesced, malformed, crash and no-replay tests. The palette provides an
explicit backend restart command, including a guard against concurrent process
transitions. Problems navigation is covered by the static diagnostics panel.
Model inspection and diff responses now expose bounded cursors and totals, with
512-item and 2 MiB page limits, so large results do not need to fit in one 16 MiB
frame.

M2 is accepted on the exact code commit recorded in
`docs/slx-studio-2-m2-foundation.md` and is included in the 2.0.0 release.

The foundation's exact test and resource record is
[docs/slx-studio-2-m2-foundation.md](slx-studio-2-m2-foundation.md).

Rollback: switch the transport adapter/desktop entry, without reverting file formats.

### M3 — Model + code + simulation workflow (accepted and shipped)

The first M3 slices are implemented: the typed `model/viewport` service and Electron
custom editor provide bounded static SLX viewing with subsystem selection,
search, parameter inspection and page navigation; the same workbench now owns
the persistent MATLAB Command Window and `.m` run jobs. Validated in-place model
edits are routed through the existing MATLAB bridge and reload the viewport.
Exact Simulink rendering, Save As and graphical routing remain explicitly in
the legacy Workbench.

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

Evidence and test commands are recorded in
[M3/M4 core acceptance](slx-studio-2-m3-m4.md). Rollback remains the explicit
legacy/batch Workbench choice, retaining lifecycle warnings.

### M4 — Extension platform and first installable 2.0 core (accepted and shipped)

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
  release commit. Publish measured limits and known gaps, not parity claims.

The trusted local host, first-party sample extension and portable Electron
package are implemented. Inno Setup compilation is intentionally a Windows
Actions gate because Inno is not installed on the development machine. The
full acceptance record is [M3/M4 core acceptance](slx-studio-2-m3-m4.md).

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

The 2.0.0 GitHub Release is published and `main` is the supported stable line.
Future work should use a focused branch and PR based on `main`; do not revive
the historical integration branch as a parallel release line.

<a id="upgrade-to-2"></a>

## 8. 从 1.x / Beta 迁移到 2.0 / Migrating from 1.x / Beta to 2.0

### 中文

迁移采用增量方式：原有 Python CLI 和旧版 Workbench 入口保留，Electron
桌面提供新的 Model + Code + Simulation 工作流，不要求把旧工程转换成新格式。

1. **更新来源。** 先提交或备份本地未提交修改，再更新到默认 `main`，或下载
   [`v2.0.0` 正式版](https://github.com/savellonirourou107-hue/SLX-Studio/releases/tag/v2.0.0)。
   不必切回历史 `codex/slx-studio-2-foundation` 分支。
2. **保留现有 CLI。** `slx-diff diff`、`review`、`context` 和 `git-diff` 命令保持
   兼容；静态读取 `.slx` 不需要 MATLAB，现有脚本可继续使用。
3. **选择桌面入口。** 使用 Windows 2.0 便携包或安装包；源码方式需要 Node.js
   22.12+ 和 Python 3.10+，在仓库根目录执行 `npm ci`、`npm run build`，再执行
   `npm run desktop -- <workspace>`。Python 不在 PATH 时需设置 `SLX_STUDIO_PYTHON`，
   完整命令见[桌面使用说明](slx-studio-2-desktop.md#run-from-source)。
4. **显式配置 MATLAB。** Electron 识别 `SLX_STUDIO_MATLAB` 或 `SLX_DIFF_MATLAB`；
   仅在用户执行命令或脚本时启动持久 worker，打开文件不会启动 MATLAB。
   旧版 Workbench 使用 `--matlab` 或 `SLX_DIFF_MATLAB` 配置路径；
   `slx-diff studio <workspace> --matlab-session persistent` 显式启用持久会话，
   默认仍为 batch 模式。仿真在独立 batch 会话中运行，不共享 Command Window 变量。
5. **按能力选择回退路径。** 新桌面视口是只读静态预览；图形连线编辑、Save As 等
   尚未迁移的操作继续使用旧版 `slx-studio` / `slx-diff studio`。完整 MATLAB
   调试器、profiler、语义语言服务及 Simulink 原生编辑体验不在本版承诺范围内。

2.0 不直接改写 SLX 私有 XML，不会在打开工程时自动执行代码，也不会自动激活
工程内扩展。迁移关键工作流前请核对[兼容性矩阵](compatibility-matrix.md)和
[已知边界](slx-studio-2-m3-m4.md)。

### English

The migration is intentionally additive. Existing Python and legacy Workbench
entry points remain available, while the Electron desktop provides the 2.0
Model + Code + Simulation workflow.

1. **Update the source.** Commit or back up uncommitted work, then update to the
   default `main` branch or download
   the [`v2.0.0` release](https://github.com/savellonirourou107-hue/SLX-Studio/releases/tag/v2.0.0).
   There is no need to switch back to the historical integration branch.
2. **Keep using the CLI unchanged.** `slx-diff diff`, `review`, `context` and
   `git-diff` do not require MATLAB and remain compatible with existing scripts.
3. **Choose a desktop path.** Use the Windows 2.0 portable/installer package,
   or run the Electron desktop from source with Node.js 22.12+ and Python 3.10+:
   `npm ci`, `npm run build`, then `npm run desktop -- <workspace>` from the
   repository root. Set `SLX_STUDIO_PYTHON` if Python is not on PATH; see the
   [source launch guide](slx-studio-2-desktop.md#run-from-source) for full commands.
4. **Configure MATLAB explicitly when needed.** Electron accepts
   `SLX_STUDIO_MATLAB` or `SLX_DIFF_MATLAB` and starts its persistent worker only
   on an explicit command or script run, not on file open. The legacy Workbench
   accepts `--matlab` or `SLX_DIFF_MATLAB`; use
   `slx-diff studio <workspace> --matlab-session persistent` to opt in, with batch
   mode remaining its default. Simulation uses an independent batch session
   and does not share Command Window variables.
5. **Keep a fallback for unmigrated operations.** The new viewport is static
   and read-only. Graphical wiring and Save As remain in the legacy
   `slx-studio` / `slx-diff studio` path. A full MATLAB debugger, profiler,
   semantic language service and native Simulink editing parity are not part
   of this release's scope.

The 2.0 desktop does not rewrite private SLX XML, silently execute a
workspace, or auto-activate workspace extensions. Review the [compatibility
matrix](compatibility-matrix.md) and [known boundaries](slx-studio-2-m3-m4.md)
before moving a safety- or release-critical workflow.
