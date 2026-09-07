# Workspace index hardening

This follow-up to PR #12 retains the session-scoped, dependency-free index.

- Refresh requests received during a build are coalesced into one follow-up
  build, including when the active build fails. Writes are no longer silently
  lost behind an in-progress scan.
- MATLAB source size limits apply to each search, before cache lookup. A
  restrictive request cannot poison the cache for later permissive requests.
- Search resolves indexed paths against the workspace boundary again before
  accessing content, and rejects file symlinks.

Regression coverage is isolated in `tests/test_workspace_index.py`. The
concurrency test uses synchronization events rather than depending on directory
scan speed. This is a correctness improvement, not a measured speedup claim.

Remaining limitations: discovery of external additions still requires Refresh;
there is no filesystem watcher, persistent database, or gitignore parser. Search
documents retain the existing 64-document cap. Persistent MATLAB sessions,
frontend modularization, desktop E2E, and Control Lab remain separate work.
