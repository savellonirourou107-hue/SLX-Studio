# Architecture

This document describes the **current SLX Studio 2.0 architecture on `main`**.
The historical migration rationale and acceptance gates remain in the
[2.0 migration charter](slx-studio-2-migration.md), while the
[project goal](../SLX_STUDIO_2_GOAL.md) defines product boundaries.

SLX Studio is a Model + Code + Simulation-first engineering IDE with a
TypeScript/Electron desktop and a dependency-light Python engineering core.
The legacy pywebview/browser Workbench remains a compatibility path; new
platform architecture belongs in the Electron workbench.

## Layered runtime

```text
Electron main process
  ├── restricted preload API
  │     └── renderer / Workbench
  │           ├── Monaco text editors
  │           ├── SLX custom editor
  │           ├── Commands / Settings / Problems / Output
  │           └── trusted first-party extension contributions
  ├── private framed JSON-RPC over stdio
  │     └── Python `src/slxdiff` backend
  │           ├── static SLX parser / diff / validation
  │           ├── workspace and document services
  │           └── explicit MATLAB runtime/model jobs
  └── separate Node extension host
```

The renderer has no raw Node.js, filesystem, shell, or arbitrary IPC access.
Electron validates the sender and payload of privileged requests. Python is
started only after a workspace is opened; MATLAB remains explicit and opt-in.

## Code and workspace path

Text documents are opened through root-scoped backend services and represented
by managed Monaco models. Save uses conflict detection and atomic replacement.
Dirty state, draft recovery, Undo/Redo, tab lifetime, and external-change
handling are owned by the desktop editor layer rather than ad hoc DOM state.
Dirty checks use Monaco alternative-version IDs instead of serializing whole
buffers during cursor/tab renders; an asynchronous save records the exact editor
version it wrote so typing that continues during the save remains dirty.

Workspace settings follow `default < user < workspace` precedence. Sensitive
runtime configuration is not workspace-writable. Directory listing, document
reads, model inspection, and writes are constrained to the selected workspace.

Ctrl+P workspace search is backed by the Python session-scoped `WorkspaceIndex`.
The index contains only visible MATLAB/Simulink files, ignores links and generated
directories, bounds depth/file counts and lazily caches searchable document/model
content. Search never starts MATLAB. Text hits navigate to a line in Monaco;
static Simulink block hits reopen the bounded viewport at the indexed subsystem
and exact block. Explorer Refresh explicitly invalidates the search index so
new/deleted files are discovered without a persistent database or disk-wide scan.

## SLX static read path

1. Open `.slx` as a ZIP package.
2. Apply archive entry, aggregate XML, and per-member size limits.
3. Reject DTD/entity declarations before XML parsing.
4. Locate Simulink system XML and normalize blocks, parameters, subsystems, and signal endpoints.
5. Record conservative `metadata.unsupported_features` diagnostics for partially understood structures.
6. Return bounded/paginated canonical data to the renderer without starting MATLAB.

Static inspection powers model viewing, semantic diff, review, agent context,
and safe navigation. It does **not** execute callbacks or embedded code and is
not claimed to be equivalent to Simulink's own rendering or object model.

## SLX write path

The desktop never rewrites private SLX XML directly. User-approved edits flow
through validated intent and the MATLAB/Simulink programmatic APIs:

```text
explicit edit intent
  -> Python validation
  -> source SHA-256 / before-value conflict checks
  -> isolated MATLAB/Simulink operation
  -> official API calls (`set_param`, block/line operations, `save_system`)
  -> reload canonical model
```

Plain Subsystem editing is supported within the validated transaction boundary
covered by the 2026-09-16 acceptance record. Complex masks, variants, library
links, model references, Stateflow, specialized blocks, and dynamic semantics
remain compatibility work rather than inferred support.

## MATLAB execution

MATLAB execution is arbitrary user-code execution by definition and is never
triggered by merely opening a project or model. The desktop uses the existing
project-scoped persistent worker for Command Window and `.m` runs, with bounded
stdout/stderr deltas, cancellation, structured result metadata, and explicit
session-loss reporting. Side-effecting requests are not replayed after failure.

Graphical model edits/simulation use validated model jobs and preserve source
hash checks. Real MATLAB/Simulink remains authoritative for programmatic edits,
compilation, simulation, figure export, and saving.

## Desktop transport and failure isolation

The Python transport uses JSON-RPC 2.0 messages framed by `Content-Length` over
private stdio. Frames, headers, concurrent requests, result pages, and queued
write bytes are bounded. Malformed framing, oversized messages, process crashes,
and timeouts fail pending work rather than silently retrying it.

The Node extension host is a responsiveness boundary, not an OS security
sandbox. Trusted extensions activate lazily, run outside the renderer, expose a
small declarative contribution surface, and can be terminated/restarted without
freezing the editor. Third-party distribution requires separate trust and
installation hardening before it can be treated as a general marketplace.

## Security invariants

- `contextIsolation: true`, renderer sandboxing, no renderer Node integration.
- Local packaged assets only; navigation/window creation/webviews are denied.
- Workspace-root guards and symlink/junction checks on privileged file paths.
- No static `.slx` inspection callback execution.
- No implicit MATLAB start, task execution, AI network request, or extension activation on open.
- Bounded RPC, process output, settings files, archive parsing, and UI result pages.
- Secrets and runtime executable paths are not trusted from workspace settings.

See [SECURITY.md](../SECURITY.md) and the migration charter for the threat model
and explicit non-goals.

## Testing and release evidence

Validation is deliberately split by boundary:

- Python unit/regression tests and Ruff checks.
- TypeScript type checking and Node platform/protocol tests.
- Real Electron interaction tests.
- Optional real MATLAB/Simulink R2026a integration tests.
- Windows portable package and installer acceptance.

A skipped licensed-runtime test is not counted as a pass. The latest verified
Subsystem/MATLAB editor-assistance evidence is recorded in
[2026-09-16 acceptance](2026-09-16-acceptance.md). Compatibility claims remain
narrower than the full Simulink feature set and must expand through reproducible
fixtures and real-runtime evidence.
