# GitHub Action

`slx-diff` ships as a composite action in `action.yml`.

The Action is designed for GitHub-native **review triage**, not as a replacement for native Simulink comparison or verification.

## Minimal pull-request workflow

```yaml
name: Review Simulink models

on:
  pull_request:
    paths:
      - "**/*.slx"

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: YOUR_GITHUB_USERNAME/slx-studio@v0.8.0
```

The Action uses the PR base/head SHAs supplied by GitHub. You can override them:

```yaml
- uses: YOUR_GITHUB_USERNAME/slx-studio@v0.8.0
  with:
    base: origin/main
    head: HEAD
```

## What the PR report contains

For every changed `.slx` model:

- semantic block/parameter/connection changes,
- highest static Review Priority,
- up to five Review Intelligence hotspots,
- downstream block count,
- affected Outport count,
- an explicit disclaimer that Review Priority is not a safety/stability/simulation result.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `base` | PR base SHA | Base ref/commit |
| `head` | PR head SHA / `github.sha` | Head ref/commit |
| `comment` | `true` | Upsert one PR review comment |
| `include-layout` | `false` | Include position/color/orientation changes |
| `fail-on-change` | `false` | Fail when semantic changes exist |

## Outputs

| Output | Meaning |
|---|---|
| `changed` | `true` when any semantic changes were found |
| `change-count` | Total semantic change count |
| `model-count` | Number of changed `.slx` models inspected |
| `review-priority` | Highest static priority: `high`, `medium`, `low`, or `none` |
| `high-review-count` | Number of high-priority review hotspots |
| `report-path` | Local path to the Markdown report |

The priority outputs are intended for triage and custom workflow logic. They are not formal safety gates.

## Fork pull requests

GitHub can restrict write permissions for `GITHUB_TOKEN` on pull requests from forks. `slx-diff` treats the PR comment as best-effort: the Job Summary is still generated even when the comment call is refused.

Do not switch to a privileged `pull_request_target` workflow that checks out and executes untrusted pull-request code merely to obtain comment permissions. If you build a privileged review flow, keep untrusted code/data handling isolated and follow GitHub's security guidance.

## Why one comment?

The Action writes an HTML marker into its review comment. On later pushes to the same pull request it finds that marker and updates the existing bot comment instead of creating a new comment on every run.
