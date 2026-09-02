# MATLAB bridge

The MATLAB bridge is the opt-in write/simulation layer behind:

```bash
slx-diff studio MODEL.slx
slx-diff apply MODEL.slx PATCH.json -o OUTPUT.slx
```

## Discovery

MATLAB is located in this order:

1. `--matlab /path/to/matlab`
2. `SLX_DIFF_MATLAB`
3. `matlab` on `PATH`

Check it with:

```bash
slx-diff matlab-status
```

## Apply flow

1. Python parses the exact source file.
2. Patch SHA/conflicts are validated without MATLAB.
3. A temporary JSON request and MATLAB runner are generated.
4. MATLAB is started with `-batch`.
5. MATLAB calls `load_system`.
6. Each operation is checked again with `get_param`.
7. MATLAB calls `set_param`.
8. `save_system` writes the requested output copy.
9. Optional `sim` runs against the patched in-memory model.
10. A JSON result is returned to Studio/CLI.

The source file is not the output target by default.

## Local server security

`slx-diff studio` is intentionally loopback-only in v0.6. The browser receives a cryptographically random session token and API requests must return it in `X-SLX-Studio-Token`. Request bodies are size-limited and parsed as JSON; patch operations are schema-validated before MATLAB is started.

This is not a sandbox for untrusted Simulink models. Loading or simulating a model in MATLAB can execute model callbacks or referenced code according to normal MATLAB/Simulink behavior. Only use the bridge with models you trust.

## Validation status

The Python bridge protocol and subprocess orchestration have automated tests using a fake MATLAB executable. The project build environment does not contain MATLAB, so real `set_param`/`save_system`/`sim` behavior still needs release-by-release validation on genuine Simulink models.
