# Contributing

Thanks for helping make Simulink changes easier to review.

## Setup

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

## Parser changes

Every parser fix should include a minimal regression fixture. Prefer generating the ZIP/XML fixture inside the test so the repository stays small and contributors do not need MATLAB.

If a real model triggers a bug, please reduce or anonymize it before sharing. Do not publish proprietary models, credentials, generated code, or company-confidential parameter values.

## Pull requests

Keep changes focused. Explain:

1. what SLX structure was not handled,
2. how the parser now normalizes it,
3. which test proves the behavior,
4. whether JSON output compatibility changes.

Before opening a pull request, run the lightweight local gate:

```bash
python -m pytest -ra
python -m ruff check .
python -m ruff format --check .
python -m compileall -q src tests
```

If a change touches MATLAB/Simulink execution, also run the opt-in real-runtime
check when a licensed installation is available:

```powershell
$env:SLX_STUDIO_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
python -m pytest -ra -m matlab_integration
```

The [maintainer guide](docs/maintainer-guide.md) records issue triage, release,
security and MATLAB compatibility checks. The repository includes lightweight
Issue and pull-request templates under `.github/`.

## Commit style

Conventional Commits are welcome but not required. Examples:

- `fix(parser): handle nested signal branches`
- `feat(cli): add git-ref comparison`
- `docs: add GitHub Actions example`
