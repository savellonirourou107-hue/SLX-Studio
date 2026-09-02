# SLX Studio Workbench

SLX Studio v0.8 is a lightweight editor for MATLAB `.m` scripts and Simulink `.slx` models.

## Start the Workbench

```bash
slx-studio .
```

or:

```bash
slx-diff studio .
```

The argument can be a workspace folder, a `.m` file, or a `.slx` file.

## `.m` workflow

- open from the file tree,
- edit plain UTF-8 text in multiple tabs,
- use line numbers and lightweight MATLAB syntax highlighting,
- `Ctrl/Cmd+S` to save and editor undo/redo,
- `F5` or **Run** to execute through local MATLAB,
- jump to structured MATLAB error lines,
- inspect stdout/stderr plus Workspace Variables after execution.

The runner uses MATLAB `-batch` and executes the saved file from its containing directory.

## `.slx` workflow

The graphical editor renders blocks and signal connections from the SLX package. With MATLAB available it supports:

- parameter edits,
- drag blocks and persist Simulink `Position`,
- drag output ports onto input ports to create connections,
- searchable Block Palette / Add Block,
- Rename Block / Delete Block,
- Remove connection,
- model-level Undo / Redo with external-change protection,
- Save Model / Run Simulation.

Real SLX serialization is delegated to MATLAB. The browser does not directly rewrite private SLX ZIP/XML structures.

## Creating files

Use **New .m** for a script or **New .slx** for a real empty Simulink model. Creating an SLX requires local MATLAB.

## English / 中文

Both the outer Workbench and the graphical SLX editor support English and Simplified Chinese.

## AI and Git tools

The existing AI provider gateway, semantic diff, Review Lens, Agent Context and GitHub Action remain available as optional tools. They are no longer the primary product positioning.

## Standalone viewing and diff

Read-only static viewing still works without MATLAB:

```bash
slx-diff view controller.slx
slx-diff view before.slx after.slx
slx-diff html before.slx after.slx -o review.html
```

## Desktop app

```bash
pip install -e ".[desktop]"
slx-studio
```

With pywebview installed, the Workbench opens in a desktop window. The repository's Windows workflow builds `SLXStudio.exe` with PyInstaller.

## Trust boundary

Running `.m`, loading/saving a model, or simulating can execute normal MATLAB/Simulink project behavior. Only run trusted workspaces. Static SLX parsing remains non-executing.
