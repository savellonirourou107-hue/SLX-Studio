# Agent instructions

- Keep the core parser dependency-free unless a dependency clearly improves compatibility or security.
- Never execute callbacks or embedded code while inspecting an SLX package.
- Add a regression test for each newly supported XML shape.
- Preserve JSON backward compatibility within a minor release when practical.
- Treat MathWorks native comparison as complementary; do not claim parity without evidence.

## SLX Studio 2.0 migration

- For platform/refactor work, read `SLX_STUDIO_2_GOAL.md` and `docs/slx-studio-2-migration.md` first.
- Preserve `src/slxdiff`, the dependency-free CLI, legacy entry points and their tests during the staged desktop migration.
- Distinguish planned architecture from implemented features; an open PR, mock UI or built executable is not release or end-to-end evidence.
- Do not automatically merge existing PRs, force-push `main`, move release tags or publish a new release as part of refactor preparation.
