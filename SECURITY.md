# Security Policy

Please do not open public issues for vulnerabilities that could cause arbitrary code execution, unsafe archive handling, denial of service, unintended disclosure, or unsafe local-bridge behavior.

Until a dedicated private reporting channel is configured, contact the repository owner through the email listed on their GitHub profile and include `SLX Studio security` in the subject.

## Core parser threat model

A pull request can contain an untrusted `.slx` package. The dependency-free parser therefore treats model content as data, not executable input.

The core parser:

- does not start MATLAB or Simulink,
- does not execute callbacks or scripts,
- does not extract ZIP members to disk,
- limits archive entry count and uncompressed XML sizes,
- rejects XML DTD/entity declarations,
- invokes Git without `shell=True`.

These are defense-in-depth measures, not a claim that parsing arbitrary hostile files is risk-free. Please report crashes or resource-exhaustion cases with the smallest safe reproducer you can provide.

## MATLAB and script execution threat model

`slx-studio`, `slx-diff run-m`, model saves and simulation are **explicit execution paths**. Loading or simulating a Simulink model can run model callbacks, referenced code, initialization scripts, or other behavior according to normal MATLAB/Simulink semantics.

Therefore:

- only use the MATLAB bridge with models you trust,
- the live HTTP bridge is loopback-only,
- each Studio session uses a random token required on API requests,
- request bodies are size-limited and JSON/schema validated,
- patches are bound to a source SHA-256 and checked against `before` parameter values,
- MATLAB checks each current parameter again with `get_param` before calling `set_param`,
- the standalone patch CLI can write to a separate output, while the Workbench **Save Model** action intentionally edits the selected workspace model in place, as a normal editor would; source-hash and before-value checks are used to detect stale edits before MATLAB is launched.

The local bridge is not a sandbox and should not be exposed to a LAN or the public Internet.


## Workspace editor boundary

The Workbench intentionally has stronger powers than the read-only parser.

- Workspace file APIs are constrained to the selected root and reject path traversal.
- The text editor currently writes only `.m` files and uses atomic replacement.
- Running an `.m` file executes arbitrary code contained in that file. This is a user-triggered editor action, not a sandbox.
- The Command Window executes the exact MATLAB command entered by the user. Its temporary workspace checkpoint is session-scoped and stored outside the project tree.
- Workspace variable edits evaluate the explicit MATLAB expression entered by the user; they are not a restricted numeric parser.
- Parameter Sweep and SLX Simulation jobs load and simulate the selected model and therefore have the same callback/code-execution risks as normal Simulink execution. Stop terminates the spawned MATLAB process but is not a security sandbox.
- Dirty `.m` recovery drafts are stored under the SLX Studio user-state directory (or `SLX_STUDIO_STATE_DIR`), not in the project, and may contain unsaved source code. Protect the user profile accordingly.
- Creating or structurally editing a real `.slx` requires MATLAB and is performed through validated operations rather than direct ZIP/XML rewriting.
- AI tools do not automatically receive the user-triggered `.m` execution action.

Only open and run projects you trust.

## GitHub Action permissions

The example workflow requests `contents: read` and `pull-requests: write` only. PR commenting is best-effort because GitHub may downgrade token permissions for fork pull requests.

Do not use a privileged `pull_request_target` workflow to execute or trust unreviewed pull-request code solely to obtain comment permissions.

## AI provider boundary

Live Studio can proxy BYOK requests to a user-selected AI provider. Provider credentials are treated as transient request data:

- API keys are not written to project files or embedded into generated Studio HTML;
- a key can instead be supplied through the provider-specific environment variable of the `slx-diff` process;
- switching provider presets in the browser clears the currently typed key to reduce accidental cross-provider credential disclosure;
- provider error messages may be surfaced to the local browser for debugging, but request Authorization headers are never included in Agent traces;
- model-derived summaries, block parameters, blueprint/tool results and the user's prompt may be sent to the selected provider as part of the tool-calling conversation.

If model content is confidential and must not leave the machine, use the static/no-provider features or point the Custom provider at a trusted localhost OpenAI-compatible endpoint.

The provider proxy intentionally accepts arbitrary HTTPS endpoints because BYOK/custom gateways are a supported feature. Plain HTTP is restricted to localhost. The live Studio server itself remains loopback-only and should not be exposed publicly.
