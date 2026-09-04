## What changed?

<!-- Keep the change focused and describe the user-visible result. -->

## Why?

<!-- What problem or maintainer workflow does this solve? -->

## Parser/schema impact

- [ ] No parser/schema change
- [ ] Added/updated regression fixture
- [ ] JSON output change documented

## Validation

- [ ] `python -m pytest -ra`
- [ ] `python -m ruff check .`
- [ ] `python -m ruff format --check .`
- [ ] `python -m compileall -q src tests`
- [ ] Real MATLAB check run or intentionally skipped with the reason recorded

## Safety and compatibility

- [ ] No direct private `.slx` ZIP/XML writes were added
- [ ] No arbitrary MATLAB shell or callback execution was granted to AI tools
- [ ] JSON/API compatibility was preserved or documented
- [ ] Unsupported Simulink structures remain explicit rather than silently guessed
- [ ] Tests/docs/examples were updated where needed

## Checklist

- [ ] No confidential model content or credentials included
