# SLX Studio Agent API (v1)

The live Studio server exposes a loopback-only REST API for external agents, IDE integrations and scripts.

Start a workspace:

```bash
slx-diff serve controller.slx --port 8765 --token dev-token
```

Or start from a blank model-design workspace:

```bash
slx-diff serve --blank --port 8765 --token dev-token
```

Every API request requires:

```text
X-SLX-Studio-Token: dev-token
```

The default server binds only to loopback. Do not expose it to a LAN or the public Internet.

## Provider registry

```http
GET /api/v1/providers
```

Returns built-in BYOK presets such as DeepSeek, Kimi, MiniMax, GLM, Qwen, OpenAI and Custom, including default Base URLs, suggested model IDs and environment-variable names.

Example:

```bash
curl -s http://127.0.0.1:8765/api/v1/providers \
  -H 'X-SLX-Studio-Token: dev-token'
```

Provider presets are defaults only. `base_url` and `model` can be overridden in an agent request.

## Capabilities and model

```http
GET /api/v1/capabilities
GET /api/v1/model
GET /api/v1/tools
```

`/capabilities` returns the safe block catalog, tool definitions, provider registry and MATLAB bridge status.
`/model` includes the parser's optional `metadata.unsupported_features` list when
Stateflow, masks, variants, links, model references, bus metadata, dynamic
ports or non-catalog BlockTypes are present.  This list is a warning that
authoritative validation must return to MATLAB/Simulink.

All JSON POST validation failures use a stable response shape and include the
correct `Content-Type`/`Content-Length` headers:

```json
{"ok": false, "error": "human-readable message"}
```

Malformed types, missing fields, invalid patch/edit/sweep values, oversized
request bodies and invalid tokens are rejected without disconnecting the
request. Unexpected internal failures return the same shape with HTTP 500 and
the generic message `internal server error`; implementation tracebacks are not
sent to clients.

## Run an agent

```http
POST /api/v1/agent/chat
```

DeepSeek example:

```bash
curl -s http://127.0.0.1:8765/api/v1/agent/chat \
  -H 'X-SLX-Studio-Token: dev-token' \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": {
      "provider_id": "deepseek",
      "model": "deepseek-v4-flash",
      "api_key": "YOUR_KEY"
    },
    "prompt": "Inspect this controller and explain the highest-priority structural review points.",
    "language": "en",
    "auto_build": false
  }'
```

Kimi, MiniMax, GLM and Qwen use the same request shape; change only `provider_id`, and optionally `model` / `base_url`.

If the relevant provider environment variable is already present in the `slx-diff` process (`DEEPSEEK_API_KEY`, `KIMI_API_KEY`, `MINIMAX_API_KEY`, `ZAI_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`), `api_key` can be omitted.

## Safe tool call

```http
POST /api/v1/tools/call
```

Example:

```json
{
  "name": "get_downstream",
  "arguments": {"block_path": "Controller/Kp"}
}
```

`analyze_model_structure` returns sources, sinks, disconnected blocks, fan-out hotspots, Outports and feedback strongly connected components as a static graph summary. It is not a stability or safety verdict.

Tools are intentionally narrower than arbitrary MATLAB execution. Read operations parse the SLX package without starting MATLAB. Edit tools create staged declarative intent rather than rewriting ZIP/XML directly.

## Validate a model blueprint

```http
POST /api/v1/blueprints/validate
```

A blueprint contains only catalog block types, allowed block parameters, positions, connections and a small allowlist of model settings. Validation returns a Studio-ready preview without MATLAB.

## Build a validated blueprint

```http
POST /api/v1/blueprints/build
```

This is an explicit MATLAB-backed write path. The server validates the blueprint again before invoking the restricted bridge. No raw MATLAB program is accepted by this endpoint.

## Security and data boundary

- The API binds to loopback only.
- A per-session token is required.
- Provider API keys are not persisted to project files.
- Changing Provider in the Studio UI clears the currently typed API key to avoid cross-provider credential leakage.
- Provider calls necessarily send the prompt plus model-derived tool results requested by the agent to the selected endpoint.
- Use a localhost OpenAI-compatible provider when engineering data must remain local.
- MATLAB build/apply/simulation is separate from static review and can execute normal model callbacks; only use it with trusted models.
