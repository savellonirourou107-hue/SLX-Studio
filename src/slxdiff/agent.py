from __future__ import annotations

import json
import math
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .blueprint import (
    BLOCK_CATALOG,
    BLUEPRINT_SCHEMA_VERSION,
    ModelBlueprint,
    blueprint_from_dict,
    blueprint_tool_schema,
    catalog_payload,
    validate_automatic_parameter_value,
)
from .matlab_bridge import build_blueprint_with_matlab, find_matlab
from .model import Model
from .parser import parse_slx
from .patching import PATCH_SCHEMA_VERSION, PatchDocument, PatchOperation

_MAX_PROVIDER_RESPONSE = 8 * 1024 * 1024
_MAX_AGENT_STEPS = 10
_MAX_PROMPT_CHARS = 50_000


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    label_zh: str
    kind: str
    base_url: str
    default_model: str
    models: tuple[str, ...] = ()
    api_key_env: str = ""
    api_key_env_aliases: tuple[str, ...] = ()
    region: str = ""
    note: str = ""
    note_zh: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "label_zh": self.label_zh,
            "kind": self.kind,
            "default_base_url": self.base_url,
            "default_model": self.default_model,
            "models": list(self.models),
            "api_key_env": self.api_key_env,
            "api_key_env_aliases": list(self.api_key_env_aliases),
            "region": self.region,
            "note": self.note,
            "note_zh": self.note_zh,
        }


_PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="openai",
        label="OpenAI",
        label_zh="OpenAI",
        kind="openai_responses",
        base_url="https://api.openai.com/v1",
        default_model="",
        api_key_env="OPENAI_API_KEY",
        region="global",
        note="Uses the Responses API and SLX Studio function tools.",
        note_zh="使用 Responses API 与 SLX Studio 函数工具。",
    ),
    ProviderPreset(
        id="deepseek",
        label="DeepSeek",
        label_zh="DeepSeek 深度求索",
        kind="openai_compatible_chat",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        models=("deepseek-v4-flash", "deepseek-v4-pro"),
        api_key_env="DEEPSEEK_API_KEY",
        region="cn/global",
        note="Official OpenAI-compatible endpoint; tool calls are supported.",
        note_zh="官方 OpenAI 兼容接口，支持工具调用。",
    ),
    ProviderPreset(
        id="kimi",
        label="Kimi / Moonshot (China)",
        label_zh="Kimi / 月之暗面（中国）",
        kind="openai_compatible_chat",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k3",
        models=("kimi-k3", "kimi-k2.7-code-highspeed", "kimi-k2.6"),
        api_key_env="KIMI_API_KEY",
        api_key_env_aliases=("MOONSHOT_API_KEY",),
        region="cn",
        note="Moonshot OpenAI-compatible endpoint. Kimi K3 is the current flagship model.",
        note_zh="月之暗面 OpenAI 兼容接口；Kimi K3 为当前旗舰模型。",
    ),
    ProviderPreset(
        id="minimax",
        label="MiniMax (China)",
        label_zh="MiniMax 稀宇（中国）",
        kind="openai_compatible_chat",
        base_url="https://api.minimaxi.com/v1",
        default_model="MiniMax-M2.7",
        models=("MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5"),
        api_key_env="MINIMAX_API_KEY",
        region="cn",
        note="Official China OpenAI-compatible endpoint. The preset lists models currently documented for that compatibility endpoint; other enabled model IDs can be entered manually.",
        note_zh="官方中国区 OpenAI 兼容接口。预设仅列入该兼容接口文档明确支持的模型；账号已开通的其他模型 ID 可手动填写。",
    ),
    ProviderPreset(
        id="glm",
        label="GLM / Zhipu (China)",
        label_zh="GLM / 智谱（中国）",
        kind="openai_compatible_chat",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5.2",
        models=("glm-5.2", "glm-5.1", "glm-5-turbo"),
        api_key_env="ZAI_API_KEY",
        region="cn",
        note="Zhipu OpenAI-compatible endpoint with function tools.",
        note_zh="智谱 OpenAI 兼容接口，支持函数工具调用。",
    ),
    ProviderPreset(
        id="qwen",
        label="Qwen / Alibaba Model Studio (China)",
        label_zh="Qwen / 阿里云百炼（中国）",
        kind="openai_compatible_chat",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.7-plus",
        models=("qwen3.7-plus", "qwen3.7-flash", "qwen3.7-max"),
        api_key_env="DASHSCOPE_API_KEY",
        region="cn",
        note="Shared Beijing OpenAI-compatible endpoint. Workspace-specific endpoints can be entered manually.",
        note_zh="北京区共享 OpenAI 兼容接口；生产环境也可手动填写业务空间专属 Base URL。",
    ),
    ProviderPreset(
        id="custom",
        label="Custom OpenAI-compatible",
        label_zh="自定义 OpenAI 兼容接口",
        kind="openai_compatible_chat",
        base_url="",
        default_model="",
        region="custom",
        note="Any HTTPS OpenAI-compatible Chat Completions endpoint, or localhost over HTTP.",
        note_zh="任意 HTTPS OpenAI Chat Completions 兼容接口；本机服务也可使用 HTTP。",
    ),
)
_PROVIDER_BY_ID = {item.id: item for item in _PROVIDER_PRESETS}


def provider_catalog_payload() -> list[dict[str, Any]]:
    return [item.to_dict() for item in _PROVIDER_PRESETS]


@dataclass(frozen=True)
class ProviderConfig:
    kind: str
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 60.0
    provider_id: str = "custom"


@dataclass
class AgentRunResult:
    text: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    blueprint: ModelBlueprint | None = None
    patch: PatchDocument | None = None
    build_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "text": self.text,
            "trace": self.trace,
            "blueprint": self.blueprint.to_dict() if self.blueprint else None,
            "patch": self.patch.to_dict() if self.patch else None,
            "build_result": self.build_result,
        }


def provider_from_dict(payload: dict[str, Any]) -> ProviderConfig:
    if not isinstance(payload, dict):
        raise TypeError("provider must be an object")

    raw_provider_id = payload.get("provider_id", payload.get("id", "custom"))
    if not isinstance(raw_provider_id, str):
        raise TypeError("provider_id must be a string")
    provider_id = raw_provider_id.strip() or "custom"
    preset = _PROVIDER_BY_ID.get(provider_id)
    if preset is None:
        raise ValueError(f"unknown provider preset {provider_id!r}")

    raw_kind = payload.get("kind", preset.kind)
    if not isinstance(raw_kind, str):
        raise TypeError("provider kind must be a string")
    kind = raw_kind.strip()
    if kind not in {"openai_responses", "openai_compatible_chat"}:
        raise ValueError("provider kind must be openai_responses or openai_compatible_chat")
    if provider_id != "custom":
        kind = preset.kind

    raw_base_url = payload.get("base_url", "")
    if not isinstance(raw_base_url, str):
        raise TypeError("provider base_url must be a string")
    base_url = raw_base_url.strip() or preset.base_url
    if not base_url:
        base_url = "https://api.openai.com/v1" if kind == "openai_responses" else ""
    if not base_url:
        raise ValueError("provider base_url is required")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("provider base_url must be an http(s) URL without embedded credentials")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("plain HTTP provider endpoints are allowed only on localhost")

    raw_model = payload.get("model", "")
    if not isinstance(raw_model, str):
        raise TypeError("provider model must be a string")
    model = raw_model.strip() or preset.default_model
    if not model or len(model) > 256:
        raise ValueError("provider model is required")

    raw_api_key = payload.get("api_key", "")
    if not isinstance(raw_api_key, str):
        raise TypeError("provider api_key must be a string")
    api_key = raw_api_key
    if not api_key:
        for env_name in (preset.api_key_env, *preset.api_key_env_aliases):
            if env_name:
                api_key = os.environ.get(env_name, "")
                if api_key:
                    break
    if len(api_key) > 8192 or "\r" in api_key or "\n" in api_key:
        raise ValueError("invalid API key")

    raw_timeout = payload.get("timeout", 60.0)
    if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float, str)):
        raise TypeError("provider timeout must be numeric")
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("provider timeout must be numeric") from exc
    if not math.isfinite(timeout) or not (1 <= timeout <= 180):
        raise ValueError("provider timeout must be between 1 and 180 seconds")
    return ProviderConfig(
        kind=kind,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
        timeout=timeout,
        provider_id=provider_id,
    )


def _provider_url(config: ProviderConfig) -> str:
    suffix = "/responses" if config.kind == "openai_responses" else "/chat/completions"
    if config.base_url.endswith(suffix):
        return config.base_url
    return config.base_url + suffix


def _post_json(config: ProviderConfig, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    request = urllib.request.Request(_provider_url(config), data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            raw = response.read(_MAX_PROVIDER_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", errors="replace")
        raise RuntimeError(f"AI provider returned HTTP {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI provider connection failed: {exc.reason}") from exc
    if len(raw) > _MAX_PROVIDER_RESPONSE:
        raise RuntimeError("AI provider response is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("AI provider returned a non-object JSON response")  # noqa: TRY004 - protocol error from provider
    return payload


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": parameters}


class ToolRuntime:
    def __init__(
        self,
        model_path: str | Path | None,
        *,
        matlab: str | None = None,
        build_output: str | Path | None = None,
        allow_build: bool = False,
        execution_lock: threading.RLock | None = None,
    ):
        self.model_path = Path(model_path).resolve() if model_path else None
        self.model: Model | None = parse_slx(self.model_path) if self.model_path else None
        self.matlab = matlab
        self.build_output = Path(build_output).resolve() if build_output else None
        self.allow_build = allow_build
        self.execution_lock = execution_lock or threading.RLock()
        self.staged: dict[tuple[str, str], PatchOperation] = {}
        self.blueprint: ModelBlueprint | None = None
        self.build_result: dict[str, Any] | None = None

    def definitions(self) -> list[dict[str, Any]]:
        defs = [
            _tool(
                "get_capabilities",
                "Return the safe SLX Studio tool and block catalog available to this agent.",
                {"type": "object", "properties": {}, "additionalProperties": False},
            ),
            _tool(
                "get_model_summary",
                "Summarize the currently loaded Simulink model without executing it.",
                {"type": "object", "properties": {}, "additionalProperties": False},
            ),
            _tool(
                "analyze_model_structure",
                "Return deterministic static graph structure: sources, sinks, disconnected blocks, fan-out hotspots, outports and feedback components. This does not compile or simulate the model.",
                {"type": "object", "properties": {}, "additionalProperties": False},
            ),
            _tool(
                "list_blocks",
                "List model blocks. Optionally filter by text in name/path/type.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
            _tool(
                "get_block",
                "Inspect one block by exact path.",
                {
                    "type": "object",
                    "properties": {"block_path": {"type": "string"}},
                    "required": ["block_path"],
                    "additionalProperties": False,
                },
            ),
            _tool(
                "get_downstream",
                "Return deterministic static downstream signal-flow reach from one block.",
                {
                    "type": "object",
                    "properties": {"block_path": {"type": "string"}},
                    "required": ["block_path"],
                    "additionalProperties": False,
                },
            ),
            _tool(
                "stage_parameter_edit",
                "Stage a conservative conflict-detecting parameter edit for a supported block. This does not modify the SLX file and rejects callback/code-like values.",
                {
                    "type": "object",
                    "properties": {
                        "block_path": {"type": "string"},
                        "parameter": {"type": "string"},
                        "after": {"type": "string"},
                    },
                    "required": ["block_path", "parameter", "after"],
                    "additionalProperties": False,
                },
            ),
            _tool(
                "submit_blueprint",
                "Submit a complete safe model blueprint for validation and visual preview. Use this to design a new model.",
                blueprint_tool_schema(),
            ),
        ]
        if self.allow_build:
            defs.append(
                _tool(
                    "build_blueprint",
                    "Build the last validated blueprint through the restricted MATLAB bridge. No arbitrary MATLAB code is accepted.",
                    {"type": "object", "properties": {}, "additionalProperties": False},
                )
            )
        return defs

    def _require_model(self) -> Model:
        if self.model is None:
            raise ValueError("no SLX model is loaded; design a new model with submit_blueprint instead")
        return self.model

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise TypeError("tool arguments must be an object")
        if name == "get_capabilities":
            matlab = find_matlab(self.matlab)
            return {
                "blueprint_schema_version": BLUEPRINT_SCHEMA_VERSION,
                "patch_schema_version": PATCH_SCHEMA_VERSION,
                "block_catalog": catalog_payload(),
                "matlab": {"available": matlab.available, "detail": matlab.detail},
                "build_enabled": self.allow_build,
                "security": {"arbitrary_matlab_execution": False, "blueprint_validation_required": True},
                "model": {
                    "loaded": self.model is not None,
                    "unsupported_features": list(self.model.metadata.get("unsupported_features", []))
                    if self.model is not None
                    else [],
                },
            }
        if name == "get_model_summary":
            model = self._require_model()
            return {
                "name": model.name,
                "sha256": model.metadata.get("sha256", ""),
                "block_count": len(model.blocks),
                "connection_count": len(model.lines),
                "block_types": _counts(block.block_type for block in model.blocks.values()),
                "unsupported_features": list(model.metadata.get("unsupported_features", [])),
            }
        if name == "analyze_model_structure":
            return _analyze_structure(self._require_model())
        if name == "list_blocks":
            model = self._require_model()
            query = str(arguments.get("query", "")).strip().lower()
            items = []
            for block in sorted(model.blocks.values(), key=lambda item: item.path.lower()):
                haystack = f"{block.path} {block.name} {block.block_type}".lower()
                if query and query not in haystack:
                    continue
                items.append({"path": block.path, "type": block.block_type, "sid": block.sid})
                if len(items) >= 200:
                    break
            return {"blocks": items, "truncated": len(items) >= 200}
        if name == "get_block":
            model = self._require_model()
            path = str(arguments.get("block_path", ""))
            block = next((item for item in model.blocks.values() if item.path == path), None)
            if block is None:
                raise ValueError(f"block not found: {path}")
            return {
                "path": block.path,
                "name": block.name,
                "type": block.block_type,
                "sid": block.sid,
                "parameters": dict(block.parameters),
            }
        if name == "get_downstream":
            model = self._require_model()
            path = str(arguments.get("block_path", ""))
            if not any(item.path == path for item in model.blocks.values()):
                raise ValueError(f"block not found: {path}")
            downstream = _downstream(model, path)
            outports = [
                block.path
                for block in model.blocks.values()
                if block.path in downstream and block.block_type == "Outport"
            ]
            return {"block_path": path, "downstream": downstream, "affected_outports": sorted(outports)}
        if name == "stage_parameter_edit":
            model = self._require_model()
            path = str(arguments.get("block_path", ""))
            parameter = str(arguments.get("parameter", ""))
            after = str(arguments.get("after", ""))
            if len(after) > 100_000:
                raise ValueError("parameter value is too large")
            block = next((item for item in model.blocks.values() if item.path == path), None)
            if block is None:
                raise ValueError(f"block not found: {path}")
            if parameter not in block.parameters:
                raise ValueError(f"parameter {parameter!r} is not exposed for block {path!r}")
            catalog_key = next(
                (
                    key
                    for key, spec in BLOCK_CATALOG.items()
                    if spec.block_type == block.block_type and parameter in spec.parameters
                ),
                None,
            )
            if catalog_key is None:
                raise ValueError(
                    f"automatic agent edits do not allow parameter {parameter!r} on block type {block.block_type!r}"
                )
            after = validate_automatic_parameter_value(catalog_key, parameter, after)
            before = str(block.parameters[parameter])
            op = PatchOperation("set_param", path, parameter, before, after, block.sid, block.system_id)
            self.staged[(path, parameter)] = op
            return {
                "staged": True,
                "block_path": path,
                "parameter": parameter,
                "before": before,
                "after": after,
            }
        if name == "submit_blueprint":
            document = blueprint_from_dict(arguments)
            self.blueprint = document
            return {
                "valid": True,
                "model_name": document.model_name,
                "blocks": len(document.blocks),
                "connections": len(document.connections),
                "blueprint": document.to_dict(),
            }
        if name == "build_blueprint":
            if not self.allow_build:
                raise ValueError("automatic MATLAB build is not enabled for this agent run")
            if self.blueprint is None:
                raise ValueError("submit_blueprint must be called before build_blueprint")
            if self.build_output is None:
                root = self.model_path.parent if self.model_path else Path.cwd()
                output = root / f"{self.blueprint.model_name}.slx"
            elif self.build_output.suffix.lower() == ".slx":
                output = self.build_output
            else:
                output = self.build_output / f"{self.blueprint.model_name}.slx"
            with self.execution_lock:
                self.build_result = build_blueprint_with_matlab(
                    self.blueprint, output_path=output, matlab=self.matlab
                )
            return self.build_result
        raise ValueError(f"unknown tool {name!r}")

    def patch_document(self) -> PatchDocument | None:
        if not self.staged or self.model is None:
            return None
        return PatchDocument(
            schema_version=PATCH_SCHEMA_VERSION,
            model_name=self.model.name,
            source_sha256=self.model.metadata.get("sha256", ""),
            operations=tuple(self.staged.values()),
        )


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))


def _endpoint_path(value: str) -> str:
    match = re.match(r"^(.*):(in|out)\d+$", value)
    return match.group(1) if match else value


def _downstream(model: Model, start: str) -> list[str]:
    adjacency: dict[str, set[str]] = {}
    for line in model.lines:
        adjacency.setdefault(_endpoint_path(line.src), set()).add(_endpoint_path(line.dst))
    visited: set[str] = set()
    queue = sorted(adjacency.get(start, set()))
    while queue and len(visited) < 1000:
        item = queue.pop(0)
        if item in visited:
            continue
        visited.add(item)
        queue.extend(sorted(adjacency.get(item, set()) - visited))
    return sorted(visited)


def _analyze_structure(model: Model) -> dict[str, Any]:
    block_paths = {block.path for block in model.blocks.values()}
    by_path = {block.path: block for block in model.blocks.values()}
    adjacency: dict[str, set[str]] = {path: set() for path in block_paths}
    reverse: dict[str, set[str]] = {path: set() for path in block_paths}
    for line in model.lines:
        src = _endpoint_path(line.src)
        dst = _endpoint_path(line.dst)
        if src in block_paths and dst in block_paths:
            adjacency[src].add(dst)
            reverse[dst].add(src)

    sources = sorted(path for path in block_paths if not reverse[path] and adjacency[path])
    sinks = sorted(path for path in block_paths if reverse[path] and not adjacency[path])
    disconnected = sorted(path for path in block_paths if not reverse[path] and not adjacency[path])
    outports = sorted(block.path for block in model.blocks.values() if block.block_type == "Outport")
    fanout = sorted(
        (
            {"block_path": path, "fanout": len(targets)}
            for path, targets in adjacency.items()
            if len(targets) > 1
        ),
        key=lambda item: (-item["fanout"], item["block_path"]),
    )[:20]

    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(adjacency[node]):
            if nxt not in indices:
                strongconnect(nxt)
                lowlink[node] = min(lowlink[node], lowlink[nxt])
            elif nxt in on_stack:
                lowlink[node] = min(lowlink[node], indices[nxt])
        if lowlink[node] == indices[node]:
            component: list[str] = []
            while stack:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            component.sort()
            if len(component) > 1 or (len(component) == 1 and node in adjacency[node]):
                components.append(component)

    for path in sorted(block_paths):
        if path not in indices:
            strongconnect(path)
    components.sort(key=lambda item: (item[0] if item else "", len(item)))

    return {
        "analysis_kind": "static_signal_graph",
        "disclaimer": "Structural graph analysis only; no model compile, simulation, stability or safety conclusion.",
        "block_count": len(block_paths),
        "connection_count": len(model.lines),
        "source_blocks": sources[:100],
        "sink_blocks": sinks[:100],
        "disconnected_blocks": disconnected[:100],
        "outports": outports[:100],
        "high_fanout": fanout,
        "feedback_components": components[:50],
        "block_types": _counts(block.block_type for block in by_path.values()),
        "unsupported_features": list(model.metadata.get("unsupported_features", [])),
    }


def _system_prompt(runtime: ToolRuntime, *, language: str) -> str:
    lang = "Chinese" if language.lower().startswith("zh") else "English"
    return f"""You are the SLX Studio engineering agent. Respond in {lang}.
Use the provided tools instead of inventing model facts. The loaded SLX is never executed by read tools.
For a new model, call get_capabilities first, then submit_blueprint with only catalog block types and allowed parameters.
For an existing-model edit, stage_parameter_edit only; do not claim the SLX was changed unless a build/apply tool actually succeeded.
Review-priority or signal-flow reach is a static heuristic, not proof of stability, safety, or correctness.
Never request or emit arbitrary MATLAB code, shell commands, callbacks, scripts, or raw SLX XML.
If automatic build is enabled you may call build_blueprint only after a successful submit_blueprint.
Be concise but explain the architecture or analysis result and identify what still requires simulation/validation."""


def run_agent(
    provider: ProviderConfig,
    prompt: str,
    *,
    model_path: str | Path | None,
    matlab: str | None = None,
    build_output: str | Path | None = None,
    allow_build: bool = False,
    language: str = "en",
    execution_lock: threading.RLock | None = None,
) -> AgentRunResult:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("agent prompt is required")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ValueError("agent prompt is too large")
    runtime = ToolRuntime(
        model_path,
        matlab=matlab,
        build_output=build_output,
        allow_build=allow_build,
        execution_lock=execution_lock,
    )
    result = AgentRunResult()
    definitions = runtime.definitions()
    if provider.kind == "openai_responses":
        _run_responses(provider, prompt, runtime, definitions, result, language=language)
    else:
        _run_chat(provider, prompt, runtime, definitions, result, language=language)
    result.blueprint = runtime.blueprint
    result.patch = runtime.patch_document()
    result.build_result = runtime.build_result
    return result


def _run_responses(
    config: ProviderConfig,
    prompt: str,
    runtime: ToolRuntime,
    definitions: list[dict[str, Any]],
    result: AgentRunResult,
    *,
    language: str,
) -> None:
    tools = [{"type": "function", **definition} for definition in definitions]
    body: dict[str, Any] = {
        "model": config.model,
        "instructions": _system_prompt(runtime, language=language),
        "input": prompt,
        "tools": tools,
        "tool_choice": "auto",
    }
    for _ in range(_MAX_AGENT_STEPS):
        response = _post_json(config, body)
        calls = []
        text_parts: list[str] = []
        for item in response.get("output", []) if isinstance(response.get("output"), list) else []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                raw_args = item.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"AI provider emitted invalid tool arguments for {item.get('name')}"
                    ) from exc
                calls.append((str(item.get("call_id", "")), str(item.get("name", "")), args))
            if item.get("type") == "message":
                for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                    if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                        text_parts.append(str(content.get("text", "")))
        if not calls:
            result.text = (
                "\n".join(part for part in text_parts if part).strip()
                or str(response.get("output_text", "")).strip()
            )
            return
        outputs = []
        for call_id, name, args in calls:
            try:
                tool_result = runtime.call(name, args if isinstance(args, dict) else {})
                trace = {
                    "tool": name,
                    "ok": True,
                    "arguments": _redacted_args(name, args),
                    "result": tool_result,
                }
            except (ValueError, RuntimeError) as exc:
                tool_result = {"ok": False, "error": str(exc)}
                trace = {
                    "tool": name,
                    "ok": False,
                    "arguments": _redacted_args(name, args),
                    "error": str(exc),
                }
            result.trace.append(trace)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(tool_result, ensure_ascii=False),
                }
            )
        body = {
            "model": config.model,
            "previous_response_id": response.get("id"),
            "input": outputs,
            "tools": tools,
            "tool_choice": "auto",
        }
    raise RuntimeError("AI agent exceeded the maximum tool-call steps")


def _run_chat(
    config: ProviderConfig,
    prompt: str,
    runtime: ToolRuntime,
    definitions: list[dict[str, Any]],
    result: AgentRunResult,
    *,
    language: str,
) -> None:
    tools = [{"type": "function", "function": definition} for definition in definitions]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(runtime, language=language)},
        {"role": "user", "content": prompt},
    ]
    for _ in range(_MAX_AGENT_STEPS):
        response = _post_json(
            config, {"model": config.model, "messages": messages, "tools": tools, "tool_choice": "auto"}
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("AI provider returned no chat completion choice")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("AI provider returned an invalid chat message")  # noqa: TRY004 - protocol error from provider
        calls = message.get("tool_calls") or []
        if not calls:
            result.text = str(message.get("content") or "").strip()
            return
        messages.append(message)
        for call in calls:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = str(function.get("name", ""))
            raw_args = function.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"AI provider emitted invalid tool arguments for {name}") from exc
            try:
                tool_result = runtime.call(name, args if isinstance(args, dict) else {})
                trace = {
                    "tool": name,
                    "ok": True,
                    "arguments": _redacted_args(name, args),
                    "result": tool_result,
                }
            except (ValueError, RuntimeError) as exc:
                tool_result = {"ok": False, "error": str(exc)}
                trace = {
                    "tool": name,
                    "ok": False,
                    "arguments": _redacted_args(name, args),
                    "error": str(exc),
                }
            result.trace.append(trace)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id", "")),
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )
    raise RuntimeError("AI agent exceeded the maximum tool-call steps")


def _redacted_args(name: str, args: Any) -> Any:
    # Tool arguments never contain provider credentials; cap large blueprints in traces.
    if name in {"submit_blueprint"} and isinstance(args, dict):
        return {
            "model_name": args.get("model_name"),
            "blocks": len(args.get("blocks", [])) if isinstance(args.get("blocks"), list) else None,
            "connections": len(args.get("connections", []))
            if isinstance(args.get("connections"), list)
            else None,
        }
    return args
