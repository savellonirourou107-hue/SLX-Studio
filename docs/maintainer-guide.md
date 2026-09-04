# Maintainer guide

This guide keeps SLX Studio maintainable without turning it into a heavyweight service. The project is deliberately dependency-free at runtime; CI, MATLAB and GitHub are used only at the boundaries where they add confidence.

## Issue triage

1. Reproduce the report with the smallest safe `.m` or synthetic `.slx` fixture.
2. Classify it as parser safety, static compatibility, Workbench/API, MATLAB bridge, packaging or documentation.
3. Never request proprietary models, credentials or generated code in a public issue. An anonymized fixture or a redacted error is enough.
4. Add a regression test before changing a parser or API contract.
5. If the structure is outside the conservative parser catalog, keep it visible and add `metadata.unsupported_features` rather than silently guessing semantics.

## Pull-request gate

Run these commands from the repository root:

```bash
python -m pytest -ra
python -m ruff check .
python -m ruff format --check .
python -m compileall -q src tests
```

The default suite intentionally skips the MATLAB integration test when no
explicit executable is configured. With MATLAB R2026a + Simulink available:

```powershell
$env:SLX_STUDIO_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
python -m pytest -ra -m matlab_integration
```

That test is evidence for the covered bridge path only (`set_param`, block and
line edits, `save_system`, `sim`, Figure export and the workspace checkpoint).
It does not claim complete compatibility with Stateflow, masks, variants,
library links, model references, buses or specialized toolbox blocks.

## Release checklist

- Confirm `main` is green across Python 3.10–3.14.
- Run the real MATLAB check when the release is expected to change MATLAB-facing code.
- Trigger **Build Windows desktop** and confirm both the portable EXE and Inno Setup installer smoke checks.
- Update `CHANGELOG.md`, bilingual README test counts and the compatibility notes.
- Build release assets from the final verified commit. Do not move an existing annotated tag; use a new version for a new release.
- Record the commit, test evidence and known limitations in `docs/BETA2_SELF_TEST.md` or the next release report.

## Security checklist

- Keep static parsing non-executing and bounded.
- Do not add `shell=True`, arbitrary MATLAB source generation or direct private SLX ZIP/XML writes.
- Keep the local bridge loopback-only and token-protected.
- Treat `.m` execution, model loading and simulation as explicit user actions on trusted workspaces.
- Use the private contact path in [`SECURITY.md`](../SECURITY.md) for vulnerabilities; do not publish a working exploit in an issue.

## Evidence boundary

Static graph output is a review aid, not a proof of flight safety, stability,
robustness or physical behavior. A successful fake-MATLAB protocol test proves
the subprocess contract, not MATLAB semantics. A real MATLAB test proves only
the exercised model and release. Keep those evidence classes separate in issue,
PR and release notes.
