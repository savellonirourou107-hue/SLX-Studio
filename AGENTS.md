# Agent instructions

- Keep the core parser dependency-free unless a dependency clearly improves compatibility or security.
- Never execute callbacks or embedded code while inspecting an SLX package.
- Add a regression test for each newly supported XML shape.
- Preserve JSON backward compatibility within a minor release when practical.
- Treat MathWorks native comparison as complementary; do not claim parity without evidence.
