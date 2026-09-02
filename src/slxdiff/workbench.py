from __future__ import annotations

import json
from importlib import resources


def render_workbench_html(payload: dict) -> str:
    template = resources.files("slxdiff").joinpath("workbench.html").read_text(encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return template.replace("__SLX_WORKBENCH_PAYLOAD__", encoded)
