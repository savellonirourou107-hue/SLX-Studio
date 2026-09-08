# SLX Studio 2.0 M3 static model viewport

Status: **first M3 slice implemented locally; full M3 remains open.** This
record describes the bounded viewer in commit `c6f31eb` on
`codex/slx-studio-2-foundation`.

## What changed

- `model/viewport` is a typed, root-scoped Python JSON-RPC method. It reuses the
  dependency-free SLX parser and never imports MATLAB, executes callbacks or
  writes the archive.
- A page contains at most 160 blocks and 512 connections. Search is performed
  by the backend over block name, path, type and SID; the renderer retains only
  the current page. Follow-up pages carry the source SHA-256 and fail closed if
  the file changed.
- The Electron custom editor has `.m` and multiple `.slx` tabs in one workbench,
  a subsystem selector, bounded outline search, static parameter inspector,
  keyboard and pointer zoom/pan, Fit, and previous/next block pages.
- Position metadata is validated before SVG use. Missing or unsafe positions use
  a clearly marked deterministic fallback grid. SVG labels and parameters are
  inserted as text nodes, not HTML, and parameter display is capped.

## Acceptance evidence

```text
python -m pytest tests/test_documents_rpc.py -o addopts= -ra  26 passed
python -m pytest tests -m 'not matlab_integration' -o addopts= -ra  138 passed, 8 deselected
node --test scripts/test-platform.mjs                              10 passed
npm run build                                                       passed
npm run test:desktop                                                passed
```

The real Electron run generated a 1,000-block/999-connection SLX fixture and
verified that only 160 block buttons are present, the second page starts at
161, search narrows the outline, and text/model tabs coexist. The same run kept
the existing 100 Monaco open/close disposal cycle green. The Python viewport
test also verifies a SHA-256 mismatch rejects a stale page.

The optional real MATLAB R2026a suite was run separately with
`E:\matlab2026\bin\matlab.exe`: **3 passed in 59.28s**. It validates the existing
MATLAB edit/simulation/figure, command-stream/cancel and tracepoint paths; it
does not claim that the new Electron viewport drives MATLAB.

The final desktop startup measurement at commit
`3e898b593307493f347607bfd464b57f42ad12ca` reported a 684.995 ms median and
708.03 ms maximum readiness, 279.43 MiB maximum Electron private memory at
readiness, and 255.73 MiB owned private memory at 30 seconds. It is a warm-cache
startup fixture and does not include opening the 1,000-block viewport.

## Known boundaries

- Layout is an approximate static topology view. It does not claim exact
  Simulink routing, mask rendering, dynamic port semantics or graphical parity.
- Connections whose endpoints are outside the current block page are counted as
  omitted and are not drawn. A large subsystem remains intentionally paginated.
- There is no model write, simulation, variable panel, figure panel, command
  window or shared MATLAB session in this slice. Those are still M3 work and
  must use the existing owned MATLAB worker when implemented.
- This is local branch evidence only. No `main` merge, tag, release or Windows
  installer claim is made.

## Rollback

Close `.slx` model tabs and continue using the existing `slx-studio` /
`slx-diff studio` Workbench for model edits and simulation. Reverting commit
`c6f31eb` returns the M2 static-summary path without changing SLX files.
