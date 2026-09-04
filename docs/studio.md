# SLX Studio Workbench

SLX Studio is a lightweight, local-first workbench for the tight iteration loop around MATLAB `.m` scripts and Simulink `.slx` models. Static inspection works without MATLAB; execution, real model writes and simulation are delegated to a trusted local MATLAB installation.

## Start the Workbench

Install the package from the repository root:

```bash
python -m pip install -e .
```

For an embedded desktop window, install the optional WebView extra:

```bash
python -m pip install -e ".[desktop]"
```

Then choose one of these equivalent launchers:

```bash
slx-studio .                 # desktop shell / browser fallback
slx-diff studio .            # engineering CLI launcher
slx-diff serve . --port 8765 # loopback API only, no browser
```

The path may be a workspace folder, a `.m` file or an `.slx` file. `slx-studio` opens a file picker when no path is supplied. Use `--browser` with the desktop launcher or `--no-browser` with `slx-diff studio` when you want to control how the UI is opened.

## Configure MATLAB

MATLAB is discovered from `--matlab`, then `SLX_DIFF_MATLAB`, then `PATH`:

```powershell
$env:SLX_DIFF_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
slx-diff matlab-status
```

The command must report `available: true` before Run, Apply in MATLAB, New `.slx` or Simulation can succeed. The repository's real-runtime integration check is opt-in:

```powershell
python -m pytest -ra -m matlab_integration
```

It is skipped when neither `SLX_STUDIO_MATLAB` nor `SLX_DIFF_MATLAB` is configured. GitHub-hosted runners do not include MATLAB; `.github/workflows/matlab-self-hosted.yml` is a manual self-hosted template.

## `.m` workflow

1. Open a script from the project tree.
2. Edit and save with `Ctrl/Cmd+S`.
3. Press `F5` or **Run** to execute the saved file through MATLAB.
4. Use `Ctrl/Cmd+Enter` for the current `%%` section or selection.
5. Inspect captured stdout/stderr, structured error locations, Workspace Variables and exported MATLAB Figures.

Scripts, sections, Command Window commands and explicit variable edits share a temporary session checkpoint. The checkpoint is stored outside the project and removed when the Workbench closes. Running `.m` is arbitrary MATLAB code execution by design and is always user-triggered.

## `.slx` workflow

The static parser renders blocks, parameters and signal connections without starting MATLAB. With MATLAB available, the canvas can:

- edit exposed parameters and block positions;
- add, rename and delete catalog blocks;
- create a line by dragging a specific output port to an input port;
- delete connections;
- save the model and run a simulation;
- group parameter and structural changes into undo/redo history with SHA-256 external-change protection;
- navigate into nested Subsystems when their child system is present.

Click **Apply in MATLAB** to commit staged changes. The browser never rewrites private SLX ZIP/XML internals; validated intent is translated to MATLAB/Simulink calls (`set_param`, `add_block`, `delete_block`, `add_line`, `delete_line`, `save_system`, `sim`).

If the model reports `metadata.unsupported_features`, use the view for orientation and review only. Stateflow, Mask, Variant, Library Link, Model Reference, Bus/Data Type metadata, specialized toolbox blocks and dynamic/conditional ports require authoritative MATLAB/Simulink validation.

## Diff, review and reports without MATLAB

```bash
slx-diff inspect controller.slx
slx-diff diff before.slx after.slx --format markdown
slx-diff review before.slx after.slx
slx-diff context before.slx after.slx -o agent-context.json
slx-diff view before.slx after.slx
slx-diff html before.slx after.slx -o review.html
slx-diff doctor .
```

These commands parse bounded SLX ZIP/XML packages and do not execute callbacks, scripts or MATLAB code. `doctor` additionally checks the Python/package version, workspace path, optional MATLAB discovery and (for an `.slx` path) static parsing. The output is a semantic review aid, not a stability, safety or robustness proof.

## Parameter sweeps and stopping jobs

Select a supported block, open **Sweep**, enter bounded numeric values such as `1:0.5:5` or `1,2,3`, and start the run. The original parameter is restored after the sweep. `Shift+F5` stops the active script, simulation or sweep job. Command Window requests are synchronous and cannot currently be stopped independently.

## AI and REST API

AI providers are optional BYOK helpers. They receive constrained inspection, review and validated edit tools, not an unrestricted MATLAB shell. Start the loopback API with:

```bash
slx-diff serve controller.slx --port 8765 --token dev-token
```

Every request must include `X-SLX-Studio-Token: dev-token`. See [`agent-api.md`](agent-api.md) for request schemas, error behavior and the compatibility boundary.

## Demo models

The scripts in [`examples/README.md`](../examples/README.md) create genuine Simulink files through MATLAB. They are useful for checking the end-to-end edit, save and simulation path without changing an existing project.

## Trust boundary

Only open trusted workspaces in MATLAB. Loading, saving or simulating a model can execute normal MATLAB/Simulink callbacks and referenced code. Static parsing is non-executing, but it is intentionally conservative and does not replace MATLAB's compiler, simulator or model semantics.
