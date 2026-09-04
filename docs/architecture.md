# Architecture

SLX Studio is split into a lightweight editor shell and explicit execution bridges.

## Workbench

```text
workspace folder
├── *.m   -> text editor -> atomic save -> MATLAB -batch -> Console
└── *.slx -> safe parser -> canonical graph -> graphical editor
                                      |
                                      +-> structured edit intent
                                      +-> optional AI tools
                                      +-> optional Git/review tools
```

The Workbench owns file navigation, text editing, the graphical canvas, Inspector and Console. Workspace APIs are constrained to the selected root.

## SLX read path

1. Open `.slx` as a ZIP package.
2. Apply archive/XML safety limits.
3. Locate Simulink system XML.
4. Normalize blocks, parameters and signal endpoints.
5. Record conservative `metadata.unsupported_features` diagnostics for structures that are only partially understood (for example Stateflow, masks, variants, links, model references, bus metadata and dynamic ports).
6. Render the canonical graph without starting MATLAB.

This read path powers viewing, diff, review and AI context.

## SLX write path

The browser does not directly serialize private SLX internals.

Parameter edits are staged with source SHA-256 and before-value checks. Structural edits use a separate validated edit document.

Supported v0.8 structural operations include:

```text
add_block
rename_block
delete_block
add_line
delete_line
move_block
```

After validation, the MATLAB bridge translates those operations into MATLAB/Simulink programmatic APIs and calls `save_system`.

```text
Studio edit intent
      |
Python validation
      |
source hash / conflict checks
      |
MATLAB bridge
      |
add_block / set_param / delete_block / add_line / delete_line / Position
      |
save_system
```

## Workbench history

SLX edits use a session-scoped snapshot history. Before and after each accepted structural or parameter edit, the Workbench records a temporary model snapshot and source hash. Undo/redo refuses to overwrite the file if another program changed the model on disk after the history record was created.

## `.m` execution path

`.m` files are normal text files. Save uses atomic file replacement. Run is explicitly user-triggered and invokes:

```text
matlab -batch "cd(...); run(...)"
```

stdout and stderr are captured into the Workbench Console. The runner also writes a structured result envelope containing safe workspace-variable metadata and MATLAB error file/line information when available.

Running `.m` code is arbitrary code execution by definition and is not treated as a sandboxed action.

## Desktop shell

`slx-studio` starts the loopback Workbench server. With pywebview installed it opens inside a desktop WebView; otherwise it opens the system browser.

The Windows CI workflow bundles the package and UI into `SLXStudio.exe` with PyInstaller.

## Optional AI layer

AI providers consume a constrained tool surface for model inspection, structure analysis, staged edits and validated blueprints. They do not automatically inherit the user-triggered `.m` execution capability.

## Optional Git/review layer

The original semantic diff pipeline remains dependency-light and non-executing:

```text
before/after SLX -> canonical graphs -> semantic diff -> review intelligence -> Git/AI context
```

This is useful, but it is a secondary capability of the editor rather than the primary product boundary.

## Compatibility and validation boundary

The parser's canonical graph is intentionally smaller than the full Simulink
object model. Unsupported-feature metadata is advisory: it prevents callers
from mistaking a partial view for a complete semantic model. MATLAB/Simulink
R2026a remains authoritative for `set_param`, structural edits, compilation,
simulation, figure export and `save_system`. The optional
`tests/test_matlab_r2026a_integration.py` entry point is skipped unless the
caller explicitly configures `SLX_STUDIO_MATLAB` or `SLX_DIFF_MATLAB`.
