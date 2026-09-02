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

## Commit style

Conventional Commits are welcome but not required. Examples:

- `fix(parser): handle nested signal branches`
- `feat(cli): add git-ref comparison`
- `docs: add GitHub Actions example`
