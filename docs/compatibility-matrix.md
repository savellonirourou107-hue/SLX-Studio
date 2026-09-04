# MATLAB/Simulink compatibility matrix

This is a deliberately small, evidence-based matrix. It records what has been
actually exercised and leaves unknown releases as `NOT_EVALUATED`; it is not a
claim of full Simulink compatibility.

## Current records

| Evidence class | Release | Status | What is covered |
| --- | --- | --- | --- |
| Static parser | N/A | `PASS` | Bounded ZIP/XML parsing, diff, review, context and API contracts using synthetic fixtures |
| Fake MATLAB | N/A | `PASS` | Subprocess protocol, cancellation, workspace checkpoint and bridge errors |
| Real MATLAB + Simulink | R2026a | `PASS` | Reduced block/line edits, `save_system`, `sim`, Figure export and workspace checkpoint |
| Real MATLAB + Simulink | R2025b and earlier | `NOT_EVALUATED` | No reviewed real-runtime result yet |

The machine-readable source is [`compatibility-matrix.json`](compatibility-matrix.json). A test validates its schema and prevents an unqualified release from being represented as verified.

## Reproduce the R2026a record

On a machine with a licensed MATLAB R2026a + Simulink installation:

```powershell
$env:SLX_STUDIO_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
python -m pytest -ra -m matlab_integration
```

The test creates a reduced model in a temporary directory and exercises the
bridge through the normal user-facing runner. It does not modify a project
model and does not accept a fake MATLAB executable for this evidence class.

## Adding a release record

1. Run the same reduced test on the target MATLAB/Simulink release.
2. Record the exact release, commit, command, test name and result.
3. Keep proprietary models and credentials out of the repository; add a reduced fixture or describe the structure instead.
4. Use `PASS` only for the exercised scope. Use `PARTIAL` when a known gap remains and `NOT_EVALUATED` when no result exists.
5. Update the table and the self-test report together.

## Compatibility boundary

MATLAB/Simulink remains authoritative for compilation, callbacks, parameter
semantics, dynamic ports, simulation and serialization. Static output and a
single successful integration test are useful evidence, but neither is a
stability, safety, robustness or physical-flight proof.
