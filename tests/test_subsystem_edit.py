"""Static, non-executing validation of bounded hierarchical model edits."""

from dataclasses import replace

import pytest

from slxdiff.blueprint import BLOCK_CATALOG, blueprint_from_dict, blueprint_tool_schema, catalog_payload
from slxdiff.model import Block, Model
from slxdiff.model_edit import edit_document_from_dict, validate_edit_document
from slxdiff.patching import sha256_file


def add(kind, name, parent="", **parameters):
    return {"op": "add_block", "block_type": kind, "name": name, "parent": parent, "parameters": parameters}


def line(src, dst, system="", **ports):
    return {"op": "add_line", "system_path": system, "src_path": src, "dst_path": dst, **ports}


def subsystem_ops():
    return [
        add("subsystem", "Controller"),
        add("inport", "In1", "Controller", Port="1"),
        add("gain", "Gain", "Controller", Gain="2"),
        add("outport", "Out1", "Controller", Port="1"),
        line("Controller/In1", "Controller/Gain", "Controller"),
        line("Controller/Gain", "Controller/Out1", "Controller"),
    ]


def document(path, model, operations):
    return edit_document_from_dict(
        {
            "schema_version": "0.1",
            "model_name": model.name,
            "source_sha256": sha256_file(path),
            "operations": operations,
        }
    )


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.slx"
    path.write_bytes(b"unit fixture; not a real MATLAB model")
    root = Block("root", "1", "RootGain", "Gain", "RootGain", {"Gain": "1"})
    return path, Model("source", {root.key: root})


def validate(source, operations):
    path, model = source
    validate_edit_document(document(path, model, operations), model, source_path=path)


def test_subsystem_creation_and_internal_lines_share_a_distinct_system(source):
    validate(source, subsystem_ops())
    # Previously the first child inherited its parent's system ID.
    with pytest.raises(ValueError, match="same Simulink system"):
        validate(source, subsystem_ops() + [line("RootGain", "Controller/Gain")])


@pytest.mark.parametrize("context", ["", "Controller", "missing"])
def test_nested_lines_require_exact_immediate_parent(source, context):
    operations = [
        add("subsystem", "Controller"),
        add("subsystem", "Inner", "Controller"),
        add("gain", "A", "Controller/Inner"),
        add("gain", "B", "Controller/Inner"),
    ]
    validate(source, operations + [line("Controller/Inner/A", "Controller/Inner/B", "Controller/Inner")])
    with pytest.raises(ValueError, match="context|no longer exists"):
        validate(source, operations + [line("Controller/Inner/A", "Controller/Inner/B", context)])


@pytest.mark.parametrize("parent", ["missing", "RootGain"])
def test_invalid_parent_is_rejected_before_matlab(source, parent):
    with pytest.raises(ValueError, match="no longer exists|must be a Subsystem"):
        validate(source, [add("gain", "Child", parent)])


def test_duplicate_child_rejected(source):
    with pytest.raises(ValueError, match="already exists"):
        validate(source, subsystem_ops() + [add("gain", "Gain", "Controller")])


def test_empty_existing_subsystem_does_not_reuse_root_identity(source):
    _, model = source
    empty = Block("root", "2", "Empty", "SubSystem", "Empty")
    model.blocks[empty.key] = empty
    validate(
        source, [add("gain", "A", "Empty"), add("gain", "B", "Empty"), line("Empty/A", "Empty/B", "Empty")]
    )
    with pytest.raises(ValueError, match="same Simulink system"):
        validate(source, [add("gain", "A", "Empty"), line("RootGain", "Empty/A")])


def test_rename_delete_and_recreate_keep_virtual_systems_consistent(source):
    rename = {"op": "rename_block", "block_path": "Controller", "new_name": "Renamed"}
    ops = subsystem_ops() + [rename, add("subsystem", "Controller"), add("gain", "Other", "Controller")]
    with pytest.raises(ValueError, match="same Simulink system"):
        validate(source, ops + [line("Renamed/Gain", "Controller/Other", "Renamed")])
    validate(
        source,
        ops
        + [
            {
                "op": "delete_line",
                **{k: v for k, v in line("Renamed/In1", "Renamed/Gain", "Renamed").items() if k != "op"},
            },
            line("Renamed/In1", "Renamed/Gain", "Renamed"),
            {"op": "delete_block", "block_path": "Controller"},
            add("subsystem", "Controller"),
            add("gain", "Other", "Controller"),
        ],
    )
    with pytest.raises(ValueError, match="no longer exists"):
        validate(
            source,
            ops
            + [
                {"op": "delete_block", "block_path": "Renamed"},
                line("Renamed/In1", "Renamed/Gain", "Renamed"),
            ],
        )


def test_escaped_slash_in_sibling_name_is_not_treated_as_a_descendant(source):
    _, model = source
    sibling = Block("root", "2", "Controller/Other", "Gain", "Controller//Other")
    model.blocks[sibling.key] = sibling
    validate(
        source,
        [
            add("subsystem", "Controller"),
            {"op": "delete_block", "block_path": "Controller"},
            line("RootGain", "Controller//Other"),
        ],
    )


def test_canonical_types_come_from_catalog(source, monkeypatch):
    from slxdiff import model_edit

    seen = []

    def record(**kwargs):
        seen.append(kwargs["block_type"])
        return Block(**kwargs)

    monkeypatch.setattr(model_edit, "Block", record)
    keys = ["transfer_fcn", "unit_delay", "discrete_integrator", "to_workspace", "saturation", "subsystem"]
    validate(source, [add(key, f"Block{i}") for i, key in enumerate(keys)])
    assert seen == [BLOCK_CATALOG[key].block_type for key in keys]


def test_subsystem_catalog_is_model_edit_only():
    assert "subsystem" not in catalog_payload()
    assert catalog_payload(capability="model_edit")["subsystem"]["container"] is True
    assert (
        "subsystem"
        not in blueprint_tool_schema()["properties"]["blocks"]["items"]["properties"]["type"]["enum"]
    )
    with pytest.raises(ValueError, match="unsupported blueprint"):
        blueprint_from_dict(
            {"schema_version": "0.1", "model_name": "example", "blocks": [{"id": "a", "type": "subsystem"}]}
        )


@pytest.mark.parametrize("boundary", ["preview", "build"])
def test_typed_blueprint_cannot_bypass_catalog_capability(tmp_path, monkeypatch, boundary):
    from slxdiff import matlab_bridge
    from slxdiff.blueprint import blueprint_to_model

    valid = blueprint_from_dict(
        {
            "schema_version": "0.1",
            "model_name": "example",
            "blocks": [{"id": "a", "type": "gain", "name": "Gain", "position": [0, 0, 30, 30]}],
        }
    )
    invalid = replace(valid, blocks=(replace(valid.blocks[0], type="subsystem"),))

    def forbidden(*args, **kwargs):
        pytest.fail("unsupported Blueprint must not launch MATLAB")

    monkeypatch.setattr(matlab_bridge, "_run_blueprint_matlab_request", forbidden)
    with pytest.raises(ValueError, match="unsupported blueprint"):
        if boundary == "preview":
            blueprint_to_model(invalid)
        else:
            matlab_bridge.build_blueprint_with_matlab(invalid, output_path=tmp_path / "example.slx")


def test_stale_hash_rejected(source):
    path, model = source
    edit = document(path, model, subsystem_ops())
    path.write_bytes(b"external modification")
    with pytest.raises(ValueError, match="changed on disk"):
        validate_edit_document(edit, model, source_path=path)


@pytest.mark.parametrize("kind", ["Inport", "Outport", "BusSelector"])
def test_invalid_port_directions_and_dynamic_semantics_fail_early(source, kind):
    _, model = source
    block = Block("root", "2", "Special", kind, "Special")
    model.blocks[block.key] = block
    op = line("RootGain", "Special") if kind == "Inport" else line("Special", "RootGain")
    with pytest.raises(ValueError, match="MATLAB further validation"):
        validate(source, [op])


def test_known_port_range_rejected_before_matlab(source):
    with pytest.raises(ValueError, match="declared port range"):
        validate(
            source, subsystem_ops() + [line("Controller/In1", "Controller/Gain", "Controller", dst_port=2)]
        )


def test_empty_subsystem_is_navigable_in_both_workbenches(tmp_path):
    import zipfile

    from slxdiff.model_view import model_viewport
    from slxdiff.parser import parse_slx
    from slxdiff.studio import model_payload, render_studio_html

    path = tmp_path / "empty.slx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "simulink/systems/system_root.xml",
            '<System><Block BlockType="SubSystem" Name="Empty" SID="1"><System/></Block></System>',
        )
    model = parse_slx(path)
    systems = model_payload(model)["systems"]
    empty = next(system for system in systems if system["path"] == "Empty")
    assert empty["block_count"] == 0
    assert systems[0]["path"] == ""
    viewport = model_viewport(tmp_path, path.name, system_id=empty["id"])
    assert viewport["blocks"] == [] and viewport["system_blocks"] == 0
    html = render_studio_html(model)
    assert "if(system&&typeof system.path==='string')return system.path" in html
