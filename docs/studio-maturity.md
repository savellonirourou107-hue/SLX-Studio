# Studio maturity: acceptance gates, not a feature count

This is an engineering acceptance plan, not a declaration that every gate has
passed. It complements `SLX_STUDIO_2_GOAL.md` and `docs/slx-studio-2-migration.md`.
The reliable core remains a lightweight, local engineering workbench for MATLAB
text and Simulink models. Static inspection must stay useful without starting
MATLAB. Executing scripts, model callbacks, or trusted extensions remains explicit.
A menu entry, mock, screenshot, successful build, or version number is not proof
of full runtime or release acceptance.

## 1. Non-negotiable invariants

- Never silently replace newer editor text with an older asynchronous result.
  Save only marks the version actually written clean. Unknown dialog decisions
  never authorize discarding work. Save, reload and close run in document order.
- A saved version is reachable through undo. Dirty tracking stays constant-time
  rather than copying/comparing a complete buffer on every keystroke.
- Recovery is separate from saving. A clean tab with an unresolved recovery draft
  must not erase that unseen draft when closed. Newer edits during close cleanup
  keep the tab open and are persisted as the newer draft.
- Keep source-file encoding metadata, external-modification checks, workspace
  confinement, atomic writes, renderer isolation and explicit runtime activation.
  Mixed-line-ending files remain read-only until deliberate normalization exists.
- No feature may require deleting the legacy Python CLI, dependency-free parser,
  REST interface or legacy workbench. Do not execute SLX callbacks for inspection.
- Failure is visible and bounded. No automatic replay of failed writes or runtime
  commands. Extension failure must not prevent saving unrelated documents.

## 2. Reliability slice implemented by this change

`packages/editor/documents.ts` now serializes explicit operations per document;
checks versions before applying reload/recovery results; coalesces duplicate close
requests; retains edits made during close cleanup; invalidates pending opens at
close-all transitions; preserves unresolved recovery records; and creates explicit
save undo stops. This is not a general file-system transaction across applications.

`File: Save All` in the palette and `File > Save All` use the same service. It
visits the current text-document snapshot once, does not move focus, skips clean
files, and stops at the first error. Already-saved files are not rolled back.
Typing during a write stays dirty; the action does not claim an atomic multi-file
save or chase an indefinitely changing workspace. It does not save static SLX
viewports or make unimplemented model-edit buffers appear saved.

`test-documents.mjs` supplies 28 deterministic tests with controlled IO/editor
doubles. They cover stale reads, duplicate operations, save failure, close failure,
new edits during IO, recovery cancellation and Save All failure boundaries. These
are **unit contracts**, not a replacement for real Monaco/Electron acceptance.
The desktop suite additionally checks the actual saved undo boundary, palette and
native Save All, on-disk Unicode/BOM/CRLF preservation, renderer isolation, recovery
across restart, and 100 model open/close cycles.

CI also executes the existing real extension-lifecycle suite and retains desktop
screenshots on success or failure. Package integrity builds a source distribution
and wheel, checks metadata, installs outside the checkout, verifies CLI/resources,
and retains an exact source archive, revision and SHA-256 checksums. These hashes
identify artifacts; they are not a code-signing certificate or proof of byte-for-
byte reproducible builds on all operating systems.

## 3. Ordered next milestones

### Gate A: predictable daily workspace use

The [create-only file workflow slice](file-creation.md) implements new MATLAB files
and Save Copy As. Source-renaming Save As and the remaining items below are still
separate acceptance work; Save Copy As does not mark its source buffer saved.

Deliver recent workspaces, reopen-session state, explicit recovery management,
Save As, and safe file create/rename/delete. Existing folders must open without
conversion. An optional project manifest may describe entry scripts, models and
run profiles, but must not become a prerequisite for editing ordinary files.

Acceptance: cancel every dialog without side effects; resolve rename conflicts;
reject symlink/path escapes; retain dirty buffers after source deletion; invalidate
old search/open results on workspace change; restore Unicode paths and cursor
positions after a restart. A recovery/history design must distinguish the current
single per-file draft from versioned local history, with bounded retention and
explicit deletion. Do not describe the current draft store as a complete backup.

### Gate B: trustworthy code assistance

Keep the current lightweight lexical assistance clearly identified. Introduce a
real language-service adapter only with versioned diagnostics, request cancellation,
capability negotiation and a documented behavior when its runtime is absent.
Split renderer orchestration into independently disposable controllers as features
grow; do not replace the tested typed IPC boundary with a general-purpose bridge.

Acceptance: editing or switching tabs invalidates stale diagnostics; go-to-definition
and rename work across representative multi-file projects; incomplete code does not
freeze the editor; analysis never executes arbitrary project startup code. A paused
debugger must prove real pause/step/resume behavior; trace events alone are not one.

### Gate C: reproducible engineering experiments

Define named run configurations and an experiment record tying source/model hashes,
parameters, runtime/product versions, logs, units and output files to a run ID.
Provide bounded comparison of runs before building a large Control Lab interface.
Keep static model inspection, supported edits and actual simulation separate.

Acceptance: rerunning a documented fixture reproduces expected values within stated
numerical tolerances; cancellation terminates only owned workers; failed execution
cannot be labeled successful; variables and figure ownership remain consistent;
model edits survive reopen in the supported real Simulink version; external model
changes cause a conflict, not an overwrite. Validate controller-analysis tools
against independent reference calculations, including units and invalid inputs.

### Gate D: deliverable desktop product

Publish only after clean-machine installation, launch, upgrade and uninstall tests
for each advertised OS/architecture. Keep unsigned/portable/source-package claims
separate from signed installer claims. Document runtime discovery, missing-runtime
behavior, supported MATLAB/toolbox combinations and extension trust explicitly.

Acceptance: test the exact release artifact outside the source tree; preserve user
projects on upgrade/uninstall; record checksums and source revision; validate owned
process cleanup; document rollback and a security-reporting route. Neither a Linux
source-tree UI pass nor a Python wheel smoke test certifies a Windows/macOS installer.

### Gate E: measured performance and usability

Set budgets using measured baseline results on a stated machine, not invented
numbers. Exercise large text buffers, bounded model viewports, workspace search,
100 open/close cycles and long output streams. Track cold/warm startup, p50/p95
interaction latency, retained model/listener counts, and process memory separately.

Acceptance: no unbounded DOM/model growth, keyboard-accessible core flows, visible
progress/cancellation for slow work, actionable failures, and task completion by a
new user without developer tools. Treat accessibility and crash recovery as release
criteria rather than final cosmetic work.

## 4. Reproduce the checks

From a normal network-enabled development checkout with the documented Node/Python
versions, install the locked dependencies before running desktop checks:

```sh
python -m pip install -e '.[dev]'
python -m pytest -m 'not matlab_integration' -ra
ruff check .
ruff format --check .
npm ci
npm run typecheck
npm run test:platform
npm run build
npm run test:desktop
npm run test:extensions
```

Linux CI invokes each Electron test with `xvfb-run -a`. Keep Chromium sandboxing
and renderer isolation enabled; do not use `--no-sandbox` to make CI pass. The
Ubuntu runner's user-namespace setup is an environment prerequisite, not a change
to the application's security settings.

Run the existing licensed MATLAB, packaged-desktop and installer suites only in
the corresponding supported environments, following their current documentation.
A skipped MATLAB/Windows/installer test must be reported as skipped, not passed.
Record the commit SHA, OS, dependency/runtime versions, commands, passed/failed/
skipped counts, and links to CI logs/artifacts in the pull request or release.
Review each immutable commit's evidence rather than interpreting this document
as a permanently green status dashboard.

## 5. Boundaries of the current evidence

This change does not establish full MATLAB language-server support, a pausing
debugger, a complete Control Lab, a marketplace, unrestricted SLX round-trip editing,
or MATLAB/Simulink numerical parity. It does not add a licensed runtime or certify
new operating-system installers. Those claims require the separate gates above.

Keep further changes small and reviewable. Do not automatically merge other open
PRs, rewrite main, move published tags, or publish a release merely because this
reliability slice passes. A mature studio is a supported engineering workflow with
repeatable acceptance evidence, not a promise to add every feature at once.
