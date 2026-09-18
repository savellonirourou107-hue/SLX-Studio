# Create-only MATLAB file workflows

This source change implements a **subset of Gate A** in `studio-maturity.md`:
new `.m` files and **Save Copy As**. It does not implement source-renaming Save As,
file deletion, directory creation, session restore, or Simulink model Save As.

## Using it

Open a workspace, then use **File: New MATLAB File…** in the Command Palette or
**File > New MATLAB File…** in the native menu. Enter a workspace-relative `.m`
path. The existing parent directory must already exist. Confirming creates an
empty UTF-8 file, refreshes Explorer, and opens a normal versioned editor. Opening
the dialog, pressing Escape, or choosing Cancel does not write a file.

With a MATLAB text tab selected, use **File: Save Copy As…** or **File > Save Copy
As…**. A buffer snapshot is captured when the dialog opens, including unsaved text,
BOM choice and the editor's newline sequence. The default suggestion adds `-copy`
to its name. After confirmation the copy opens in another tab, while the original
remains open with its original base hash, dirty state, undo history and recovery
record. Saving a copy is **not** saving the original. Later typing is not included
in an already captured snapshot. A buffer whose source has been deleted can still
be copied to a new name without re-reading or recreating the missing source.

A mixed-newline file is intentionally rejected by Save Copy As: Monaco may have
normalized its in-memory representation, so copying it must not silently change
the original byte layout. This is separate from ordinary UTF-8/LF or CRLF support.

## Safety and failure behavior

- **No overwrite:** existing files, directories, links and dangling links cause a
  conflict. An open text-buffer path is also protected, even when its disk file
  was deleted. Open-buffer collisions are checked case-insensitively to avoid
  ambiguous aliases on case-insensitive workspaces.
- **Workspace scope:** absolute paths, traversal, ambiguous components, hidden or
  ignored parent folders, Windows device names/stream syntax, and unsafe filename
  characters are rejected. Parent symlinks and Windows reparse points are rejected.
  Only `.m` leaf files in an existing workspace directory can be created.
- **Complete bytes or no destination:** the backend writes and fsyncs a temporary
  file in the destination directory, revalidates the path, then publishes it with
  a create-only hard link. A competing creator cannot be overwritten. The temporary
  name is removed afterward. The destination retains the temporary file's private
  creation permissions; this feature does not copy source ACLs or executable bits.
- **Fail closed:** a filesystem that cannot perform this hard-link operation is
  not supported by this path. There is no truncating-write or overwriting-rename
  fallback. This is not a guarantee of power-loss durability, an OS-level sandbox,
  or protection against a hostile same-user process swapping parent directories
  between checks. If cleanup fails after successful publication, the response
  contains a warning rather than falsely reporting that the file was not created.
- **Bounded and explicit:** requests retain the existing text byte limit and strict
  UTF-8/BOM validation. One creation dialog/write is active at a time; its input and
  buttons are disabled during submission. No automatic write retries are made.
  If transport is lost after submission, a destination may already exist; inspect
  it before choosing another name. A later duplicate request never overwrites it.
- **Context binding:** Electron checks the originating frame and the expected
  workspace root. It rejects creation during a workspace/backend transition and
  holds the backend stable during an accepted create request. The controller blocks
  ordinary workspace changes while its workflow is active and ignores stale
  completion/open results after workspace changes.
- **Visible outcomes:** validation/creation failures remain in the dialog. After
  successful creation, an Explorer refresh or editor-open failure is reported as
  such and does not resubmit the write. Copy creation does not execute MATLAB,
  callbacks, a shell, extensions, or project startup code.

## Implementation and compatibility

The flow is `FileCreationController -> DesktopServices -> allowlisted preload IPC
-> Electron validation -> document/create -> Python documents.create_document`.
The renderer never receives raw filesystem or arbitrary RPC access. The additive
`document.create` capability is advertised in protocol version 1. Existing document
read/save contracts, CLI and REST paths remain unchanged; Python's core gains no
mandatory dependency. The workspace search index is invalidated after creation.

This change is developed on top of PR #36's tested document lifecycle, in a separate
branch/stacked PR. It does not merge that PR, change `main`, publish a release, or
move a tag. Review the base PR first; after its authorized merge, retarget this PR
to `main` and rerun combined checks.

## Validation

`tests/test_document_creation.py` checks actual filesystem and RPC behavior:
Unicode/BOM/CRLF, empty-file save integration, unsafe paths, symlink/junction
parents, existing destinations, byte limits, write/publication faults, concurrent
creators, temporary cleanup warnings, index invalidation, and an unstarted runtime.
These tests run in the Linux Python matrix and the Windows regression job.

`test-file-creation.mjs` uses controlled DOM/service doubles for cancellation,
workspace generations, duplicate submits, immutable snapshots and post-publication
failures. `test-documents.mjs` additionally checks non-mutating buffer snapshots.
These contracts do not replace desktop acceptance.

`npm run test:files` launches actual Electron/Monaco and the Python backend. It
checks both command/menu paths, real on-disk contents, source dirty-state retention,
recovery of a deleted source, duplicate targets, mixed-newline rejection, foreign
frames and malformed/stale-root IPC. It verifies MATLAB remains stopped and saves
`output/playwright/desktop-save-copy.png`. CI retains it with the existing desktop
evidence. Run under `xvfb-run -a` on headless Linux, keeping Chromium sandboxing on.

Exact commit IDs, results, skipped optional environments and CI/artifact links
belong in the PR's evidence record. No MATLAB numerical or installer acceptance
is implied by these file-workflow checks.
