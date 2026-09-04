from __future__ import annotations

import json
from pathlib import Path

MATRIX_PATH = Path(__file__).parents[1] / "docs" / "compatibility-matrix.json"
ALLOWED_STATUSES = {"PASS", "PARTIAL", "NOT_EVALUATED"}
REQUIRED_FIELDS = {
    "id",
    "evidence_class",
    "status",
    "verified_commit",
    "matlab_release",
    "simulink_release",
    "test",
    "command",
    "scope",
    "limitations",
}


def test_compatibility_matrix_is_explicit_and_machine_readable() -> None:
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert payload["records"]
    assert len({record["id"] for record in payload["records"]}) == len(payload["records"])
    for record in payload["records"]:
        assert REQUIRED_FIELDS <= record.keys()
        assert record["status"] in ALLOWED_STATUSES
        assert record["scope"] and record["limitations"]
        if record["status"] == "PASS":
            assert record["verified_commit"]
        if record["evidence_class"] == "real_matlab" and record["status"] == "PASS":
            assert record["matlab_release"]
            assert record["test"]
            assert record["command"]


def test_r2026a_record_points_to_the_opt_in_integration_test() -> None:
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    record = next(item for item in payload["records"] if item["id"] == "matlab-r2026a-core-bridge")
    assert record["status"] == "PASS"
    assert record["matlab_release"] == "R2026a"
    assert Path(__file__).with_name("test_matlab_r2026a_integration.py").exists()
