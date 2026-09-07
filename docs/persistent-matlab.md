# Persistent MATLAB session (opt-in)

Use a single private MATLAB process for Command Window commands, workspace
variable edits, `.m` files, selected sections, and non-pausing debug probes:

```powershell
slx-studio . --matlab-session persistent --matlab E:\matlab2026\bin\matlab.exe
# Also supported by the CLI / local API launcher:
slx-diff serve . --matlab-session persistent
```

The default remains `--matlab-session batch`. This addition does not install
MATLAB Engine, open a network listener in MATLAB, or add a runtime dependency.
MATLAB still requires your own compatible installation and license. Keeping it
warm consumes MATLAB's normal memory and license resources until the server is
closed; this is not a smaller MATLAB runtime.

## What shares state

Command Window, the variable editor, Run, Run Section and the legacy `run-m` API
all use the same worker in persistent mode. Base variables, loaded functions'
`persistent` state and loaded Simulink libraries survive between requests.
Workspace/figure metadata is returned using the existing result schema.
Section/probe runs add the original source folder to the worker's MATLAB path
so that temporary instrumented copies can resolve sibling functions.

The graphical SLX write/simulation/sweep bridges still use independent batch
processes. They do **not** inherit this worker's variables or loaded models.
You can explicitly run `sim(...)` in the Command Window or a script when that
simulation must use live state. All authoritative SLX writes still use MATLAB
APIs; static ZIP/XML inspection never executes a worker.

## Lifecycle and failure semantics

- Startup is lazy: opening a workspace or querying session status does not
  consume a MATLAB session. One shared execution lock serializes MATLAB jobs.
- A MATLAB command error is returned without discarding a healthy worker.
  Any assignments performed before that error remain, as in MATLAB itself.
- Stop and timeout terminate the **owned process tree** on Windows (the launcher
  alone is insufficient) or the worker process group on POSIX. Unsaved models,
  variables and other in-memory state are lost. Server close terminates the
  idle worker too. It never attaches to or closes an existing user MATLAB session.
- A subsequent explicit execution creates a fresh worker and reports
  `session_reset: true`. Failed/interrupted commands are **never replayed**.
- There is no automatic switch to batch after failure: it could duplicate file
  writes or conceal loss of live state. Restart the app with `--matlab-session
  batch` to return to the established compatibility mode.
- Abrupt termination of the SLX Studio host by the OS is not a graceful close;
  orphan recovery after a host crash is not implemented in this first opt-in
  version. Normal close, Stop and timeout are covered by tests.

## Protocol and limits

The worker is bootstrapped once using `matlab -batch`. Its long-running function
polls a private temporary directory; UTF-8 JSON requests/results are published
with atomic renames. Control variables live in function scope, not the base
workspace used by user code. No workspace MAT checkpoint is saved/restored.

Output uses incremental pipe reads, including output without a trailing newline.
Private per-job end markers separate consecutive commands. Each output stream
retains at most 1 Mi characters; `output_truncated` makes clipping explicit.
Windows console decoding uses the system code page, separately from UTF-8 JSON.

Authenticated `GET /api/v1/workspace/session` reports backend, lifecycle state,
session ID and generation without starting MATLAB. Execution results add
`backend`, `session_id`, `session_generation`, `session_reset`, `state_lost` and
`output_truncated`; existing `ok`, `variables`, `figures` and `error` fields remain.
The Workbench labels persistent mode and warns on state loss or output clipping.

This is still user-authorized arbitrary MATLAB execution, **not a sandbox** and
not an interactive pausing debugger. MATLAB batch restrictions continue to apply
to commands requiring interactive input.

## Validation

```powershell
python -m pytest tests/test_persistent_session.py tests/test_worker_process.py -ra
$env:SLX_STUDIO_MATLAB = 'E:\matlab2026\bin\matlab.exe'
python -m pytest tests/test_persistent_matlab_integration.py -s -ra
```

Protocol tests use an explicitly identified Python worker double. Opt-in
acceptance uses real MATLAB R2026a and checks shared PID/state across commands,
files and sections; error recovery; Unicode output; non-newline streaming;
tracepoints; cancel/restart; timeout; deliberate exit without replay; cleanup of
temporary directories; and absence of owned MATLAB calculation processes after
close on Windows. Other MATLAB releases have not been validated for this mode.

Real Workbench HTTP acceptance also verifies Command Window → variable edit →
asynchronous `.m` execution in one worker. The Windows protocol CI job exercises
the launcher/child cancellation regression without requiring a MATLAB license.
This is HTTP/worker acceptance, not a packaged WebView UI end-to-end test.

The printed cold/warm timings are observations of those local smoke commands,
not a statistical benchmark or a promised speedup on arbitrary projects.

API references: [MATLAB batch startup](https://www.mathworks.com/help/matlab/ref/matlabwindows.html)
and [base-workspace evaluation](https://www.mathworks.com/help/matlab/ref/evalin.html).
