from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .model import Block, Line, Model

BLUEPRINT_SCHEMA_VERSION = "0.1"
_MAX_BLOCKS = 250
_MAX_CONNECTIONS = 800
_MAX_PARAMETERS_PER_BLOCK = 40
_MAX_VALUE_CHARS = 4096
_MODEL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_SAFE_EXPR_RE = re.compile(r"^[A-Za-z0-9_+\-*/^.,;:\[\]() \t]+$")
_MATLAB_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_FUNCTION_CALL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*\(")
_DANGEROUS_IDENTIFIERS = frozenset({
    "eval", "evalin", "feval", "system", "unix", "dos", "winopen", "web",
    "delete", "fopen", "fprintf", "javaaddpath", "py", "perl", "clear",
})
_NUMERIC_PARAMETERS = frozenset({
    "Port", "SampleTime", "Time", "Before", "After", "Value", "Gain",
    "UpperLimit", "LowerLimit", "InitialCondition", "UpperSaturationLimit",
    "LowerSaturationLimit", "Numerator", "Denominator", "AbsoluteTolerance",
    "gainval", "NumInputPorts", "MaxDataPoints", "Decimation",
})
_SAFE_OUT_TYPES = frozenset({
    "double", "single", "int8", "uint8", "int16", "uint16", "int32", "uint32",
    "int64", "uint64", "boolean", "Inherit: Same as input",
    "Inherit: Inherit via internal rule", "Inherit: Inherit via back propagation",
})


@dataclass(frozen=True)
class BlockSpec:
    key: str
    library: str
    block_type: str
    parameters: frozenset[str]
    description: str


BLOCK_CATALOG: dict[str, BlockSpec] = {
    "inport": BlockSpec("inport", "simulink/Ports & Subsystems/In1", "Inport", frozenset({"Port", "SampleTime"}), "Model input port"),
    "outport": BlockSpec("outport", "simulink/Ports & Subsystems/Out1", "Outport", frozenset({"Port"}), "Model output port"),
    "step": BlockSpec("step", "simulink/Sources/Step", "Step", frozenset({"Time", "Before", "After", "SampleTime"}), "Step source"),
    "constant": BlockSpec("constant", "simulink/Sources/Constant", "Constant", frozenset({"Value", "SampleTime", "OutDataTypeStr"}), "Constant source"),
    "gain": BlockSpec("gain", "simulink/Math Operations/Gain", "Gain", frozenset({"Gain", "Multiplication", "SampleTime", "OutDataTypeStr"}), "Gain block"),
    "sum": BlockSpec("sum", "simulink/Math Operations/Sum", "Sum", frozenset({"Inputs", "IconShape", "OutDataTypeStr"}), "Sum/add block"),
    "saturation": BlockSpec("saturation", "simulink/Discontinuities/Saturation", "Saturate", frozenset({"UpperLimit", "LowerLimit", "OutDataTypeStr"}), "Saturation limits"),
    "integrator": BlockSpec("integrator", "simulink/Continuous/Integrator", "Integrator", frozenset({"InitialCondition", "LimitOutput", "UpperSaturationLimit", "LowerSaturationLimit"}), "Continuous integrator"),
    "transfer_fcn": BlockSpec("transfer_fcn", "simulink/Continuous/Transfer Fcn", "TransferFcn", frozenset({"Numerator", "Denominator", "AbsoluteTolerance"}), "Continuous transfer function"),
    "unit_delay": BlockSpec("unit_delay", "simulink/Discrete/Unit Delay", "UnitDelay", frozenset({"InitialCondition", "SampleTime", "OutDataTypeStr"}), "Discrete unit delay"),
    "discrete_integrator": BlockSpec("discrete_integrator", "simulink/Discrete/Discrete-Time Integrator", "DiscreteIntegrator", frozenset({"IntegratorMethod", "gainval", "SampleTime", "InitialCondition", "LimitOutput", "UpperSaturationLimit", "LowerSaturationLimit"}), "Discrete-time integrator"),
    "mux": BlockSpec("mux", "simulink/Signal Routing/Mux", "Mux", frozenset({"Inputs", "DisplayOption"}), "Signal multiplexer"),
    "scope": BlockSpec("scope", "simulink/Sinks/Scope", "Scope", frozenset({"NumInputPorts"}), "Scope sink"),
    "to_workspace": BlockSpec("to_workspace", "simulink/Sinks/To Workspace", "ToWorkspace", frozenset({"VariableName", "MaxDataPoints", "Decimation", "Save2DSignal", "SampleTime"}), "Log a signal to the workspace"),
}

_ALLOWED_MODEL_PARAMETERS = frozenset({"StopTime", "Solver", "SolverType", "FixedStep"})


@dataclass(frozen=True)
class BlueprintBlock:
    id: str
    type: str
    name: str
    position: tuple[int, int, int, int]
    parameters: Mapping[str, str]


@dataclass(frozen=True)
class BlueprintConnection:
    src: str
    dst: str
    src_port: int = 1
    dst_port: int = 1
    name: str = ""


@dataclass(frozen=True)
class ModelBlueprint:
    schema_version: str
    model_name: str
    blocks: tuple[BlueprintBlock, ...]
    connections: tuple[BlueprintConnection, ...]
    model_parameters: Mapping[str, str]
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": "slx-model-blueprint",
            "model_name": self.model_name,
            "description": self.description,
            "blocks": [
                {
                    "id": item.id,
                    "type": item.type,
                    "name": item.name,
                    "position": list(item.position),
                    "parameters": dict(item.parameters),
                }
                for item in self.blocks
            ],
            "connections": [asdict(item) for item in self.connections],
            "model_parameters": dict(self.model_parameters),
        }


def _text(value: Any, *, field: str, max_chars: int = _MAX_VALUE_CHARS) -> str:
    if not isinstance(value, str):
        raise TypeError(f"blueprint field {field!r} must be a string")
    if len(value) > max_chars:
        raise ValueError(f"blueprint field {field!r} is too large")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"blueprint field {field!r} contains a forbidden control character")
    return value



def _safe_numeric_expression(value: str, *, field: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"blueprint field {field!r} must be non-empty")
    if not _SAFE_EXPR_RE.fullmatch(text):
        raise ValueError(f"blueprint field {field!r} contains syntax not allowed in automatic blueprints")
    if _FUNCTION_CALL_RE.search(text):
        raise ValueError(f"blueprint field {field!r} may not call MATLAB functions")
    identifiers = {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}
    if identifiers & _DANGEROUS_IDENTIFIERS:
        raise ValueError(f"blueprint field {field!r} contains a forbidden MATLAB identifier")
    # Do not allow object/property access; decimal points and element-wise operators remain valid.
    if re.search(r"[A-Za-z_][A-Za-z0-9_]*\s*\.[A-Za-z_]", text):
        raise ValueError(f"blueprint field {field!r} may not access MATLAB object properties")
    return text


def _safe_config_text(value: str, *, field: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"blueprint field {field!r} must be non-empty")
    if any(ch in text for ch in ("'", '"', ";", "!", "@", "`", "{", "}")):
        raise ValueError(f"blueprint field {field!r} contains unsafe configuration syntax")
    return text


def validate_automatic_parameter_value(block_type: str, name: str, value: str) -> str:
    field = f"parameter {name}"
    if name == "VariableName":
        if not _MATLAB_IDENTIFIER_RE.fullmatch(value.strip()):
            raise ValueError("To Workspace VariableName must be a MATLAB identifier")
        return value.strip()
    if name == "OutDataTypeStr":
        text = value.strip()
        if text not in _SAFE_OUT_TYPES:
            raise ValueError("automatic blueprints only allow simple built-in/inherited output data types")
        return text
    if name == "Inputs" and block_type == "sum":
        text = value.strip()
        if not re.fullmatch(r"[+\-|]{1,64}", text):
            raise ValueError("Sum Inputs must contain only '+', '-', or '|' characters")
        return text
    if name == "Inputs" and block_type == "mux":
        return _safe_numeric_expression(value, field=field)
    if name in _NUMERIC_PARAMETERS:
        return _safe_numeric_expression(value, field=field)
    return _safe_config_text(value, field=field)


def _position(value: Any, *, field: str) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value):
        raise ValueError(f"blueprint field {field!r} must be [left, top, right, bottom]")
    nums = tuple(round(float(x)) for x in value)
    left, top, right, bottom = nums
    if not (-100_000 <= left < right <= 100_000 and -100_000 <= top < bottom <= 100_000):
        raise ValueError(f"blueprint field {field!r} contains an invalid block position")
    if right - left > 5000 or bottom - top > 5000:
        raise ValueError(f"blueprint field {field!r} is unreasonably large")
    return nums


def _params(value: Any, *, block_type: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("block parameters must be an object")
    if len(value) > _MAX_PARAMETERS_PER_BLOCK:
        raise ValueError("block contains too many parameters")
    allowed = BLOCK_CATALOG[block_type].parameters
    result: dict[str, str] = {}
    for key, raw in value.items():
        name = _text(key, field="parameter name", max_chars=128)
        if name not in allowed:
            raise ValueError(f"parameter {name!r} is not allowed for blueprint block type {block_type!r}")
        raw_text = _text(raw, field=f"parameter {name}")
        result[name] = validate_automatic_parameter_value(block_type, name, raw_text)
    return result


def blueprint_from_dict(payload: dict[str, Any]) -> ModelBlueprint:
    if not isinstance(payload, dict):
        raise TypeError("blueprint must be a JSON object")
    version = _text(payload.get("schema_version", ""), field="schema_version", max_chars=32)
    if version != BLUEPRINT_SCHEMA_VERSION:
        raise ValueError(f"unsupported blueprint schema {version!r}; expected {BLUEPRINT_SCHEMA_VERSION!r}")
    model_name = _text(payload.get("model_name", ""), field="model_name", max_chars=63)
    if not _MODEL_NAME_RE.fullmatch(model_name):
        raise ValueError("model_name must start with a letter and contain only letters, digits, or underscores")
    description = _text(payload.get("description", ""), field="description", max_chars=4000)

    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("blueprint blocks must be a non-empty array")
    if len(raw_blocks) > _MAX_BLOCKS:
        raise ValueError("blueprint contains too many blocks")

    blocks: list[BlueprintBlock] = []
    ids: set[str] = set()
    names: set[str] = set()
    for index, raw in enumerate(raw_blocks):
        if not isinstance(raw, dict):
            raise TypeError(f"blueprint block {index} must be an object")
        block_id = _text(raw.get("id", ""), field=f"blocks[{index}].id", max_chars=64)
        if not _ID_RE.fullmatch(block_id):
            raise ValueError(f"invalid block id {block_id!r}")
        if block_id in ids:
            raise ValueError(f"duplicate block id {block_id!r}")
        ids.add(block_id)
        block_type = _text(raw.get("type", ""), field=f"blocks[{index}].type", max_chars=64)
        if block_type not in BLOCK_CATALOG:
            raise ValueError(f"unsupported blueprint block type {block_type!r}")
        name = _text(raw.get("name", ""), field=f"blocks[{index}].name", max_chars=128).strip()
        if not name or "/" in name:
            raise ValueError(f"block name {name!r} must be non-empty and may not contain '/'")
        if name in names:
            raise ValueError(f"duplicate block name {name!r}")
        names.add(name)
        blocks.append(
            BlueprintBlock(
                id=block_id,
                type=block_type,
                name=name,
                position=_position(raw.get("position"), field=f"blocks[{index}].position"),
                parameters=_params(raw.get("parameters", {}), block_type=block_type),
            )
        )

    raw_connections = payload.get("connections", [])
    if not isinstance(raw_connections, list):
        raise TypeError("blueprint connections must be an array")
    if len(raw_connections) > _MAX_CONNECTIONS:
        raise ValueError("blueprint contains too many connections")
    connections: list[BlueprintConnection] = []
    seen_connections: set[tuple[str, int, str, int]] = set()
    for index, raw in enumerate(raw_connections):
        if not isinstance(raw, dict):
            raise TypeError(f"blueprint connection {index} must be an object")
        src = _text(raw.get("src", ""), field=f"connections[{index}].src", max_chars=64)
        dst = _text(raw.get("dst", ""), field=f"connections[{index}].dst", max_chars=64)
        if src not in ids or dst not in ids:
            raise ValueError(f"connection {index} references an unknown block id")
        src_port = raw.get("src_port", 1)
        dst_port = raw.get("dst_port", 1)
        if not isinstance(src_port, int) or isinstance(src_port, bool) or not (1 <= src_port <= 64):
            raise ValueError(f"connection {index} has an invalid src_port")
        if not isinstance(dst_port, int) or isinstance(dst_port, bool) or not (1 <= dst_port <= 64):
            raise ValueError(f"connection {index} has an invalid dst_port")
        key = (src, src_port, dst, dst_port)
        if key in seen_connections:
            raise ValueError(f"duplicate connection {src}:{src_port} -> {dst}:{dst_port}")
        seen_connections.add(key)
        connections.append(
            BlueprintConnection(
                src=src,
                dst=dst,
                src_port=src_port,
                dst_port=dst_port,
                name=_text(raw.get("name", ""), field=f"connections[{index}].name", max_chars=256),
            )
        )

    raw_model_parameters = payload.get("model_parameters", {})
    if not isinstance(raw_model_parameters, dict):
        raise TypeError("model_parameters must be an object")
    model_parameters: dict[str, str] = {}
    for key, value in raw_model_parameters.items():
        name = _text(key, field="model parameter name", max_chars=128)
        if name not in _ALLOWED_MODEL_PARAMETERS:
            raise ValueError(f"model parameter {name!r} is not allowed in blueprints")
        raw_text = _text(value, field=f"model parameter {name}")
        if name in {"StopTime", "FixedStep"}:
            model_parameters[name] = _safe_numeric_expression(raw_text, field=f"model parameter {name}")
        else:
            model_parameters[name] = _safe_config_text(raw_text, field=f"model parameter {name}")

    return ModelBlueprint(
        schema_version=version,
        model_name=model_name,
        blocks=tuple(blocks),
        connections=tuple(connections),
        model_parameters=model_parameters,
        description=description,
    )


def blueprint_to_model(blueprint: ModelBlueprint) -> Model:
    """Create an in-memory preview model without MATLAB or SLX serialization."""
    model = Model(name=blueprint.model_name)
    id_to_path: dict[str, str] = {}
    for index, item in enumerate(blueprint.blocks, start=1):
        spec = BLOCK_CATALOG[item.type]
        sid = str(index)
        params = dict(item.parameters)
        params["Position"] = "[" + " ".join(str(v) for v in item.position) + "]"
        params["SLXStudioBlockType"] = item.type
        id_to_path[item.id] = item.name
        model.blocks[("system_root", sid)] = Block(
            system_id="system_root",
            sid=sid,
            name=item.name,
            block_type=spec.block_type,
            path=item.name,
            parameters=params,
        )
    for item in blueprint.connections:
        model.lines.add(
            Line(
                system_id="system_root",
                src=f"{id_to_path[item.src]}:out{item.src_port}",
                dst=f"{id_to_path[item.dst]}:in{item.dst_port}",
                name=item.name,
            )
        )
    model.metadata.update({"source": "blueprint", "blueprint_schema": blueprint.schema_version})
    return model


def catalog_payload() -> dict[str, Any]:
    return {
        key: {
            "key": spec.key,
            "block_type": spec.block_type,
            "description": spec.description,
            "parameters": sorted(spec.parameters),
        }
        for key, spec in sorted(BLOCK_CATALOG.items())
    }


def blueprint_tool_schema() -> dict[str, Any]:
    """JSON Schema used by LLM function calling. Validation is still enforced server-side."""
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": [BLUEPRINT_SCHEMA_VERSION]},
            "model_name": {"type": "string", "description": "MATLAB-safe model name"},
            "description": {"type": "string"},
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": sorted(BLOCK_CATALOG)},
                        "name": {"type": "string"},
                        "position": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                        "parameters": {"type": "object", "additionalProperties": {"type": "string"}},
                    },
                    "required": ["id", "type", "name", "position", "parameters"],
                    "additionalProperties": False,
                },
            },
            "connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string"},
                        "dst": {"type": "string"},
                        "src_port": {"type": "integer", "minimum": 1, "maximum": 64},
                        "dst_port": {"type": "integer", "minimum": 1, "maximum": 64},
                        "name": {"type": "string"},
                    },
                    "required": ["src", "dst"],
                    "additionalProperties": False,
                },
            },
            "model_parameters": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["schema_version", "model_name", "blocks", "connections"],
        "additionalProperties": False,
    }
