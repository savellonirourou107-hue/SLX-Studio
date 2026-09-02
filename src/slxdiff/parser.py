from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .model import Block, Line, Model
from .slx_path import escape_component

_SYSTEM_DIR = "simulink/systems/"
_ROOT_CANDIDATES = (
    "simulink/systems/system_root.xml",
    "simulink/blockdiagram.xml",
)
_ENDPOINT_RE = re.compile(r"^(?P<sid>[^#]+)#(?P<kind>in|out):(?P<port>\d+)$")
_MAX_XML_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_XML_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 20_000


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, tag: str):
    for child in list(element):
        if _local(child.tag) == tag:
            yield child


def _text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _direct_params(element: ET.Element) -> dict[str, str]:
    params: dict[str, str] = {}
    for child in _children(element, "P"):
        name = child.attrib.get("Name")
        if name:
            params[name] = _text(child)
    return params


def _system_element(root: ET.Element) -> ET.Element | None:
    if _local(root.tag) == "System":
        return root
    for elem in root.iter():
        if _local(elem.tag) == "System":
            return elem
    return None


def _system_ref(block: ET.Element) -> tuple[str | None, ET.Element | None]:
    for child in _children(block, "System"):
        ref = child.attrib.get("Ref") or child.attrib.get("ref")
        return ref, child if not ref else None
    return None, None


def _normalize_name(name: str) -> str:
    return name.replace("\n", " ").strip()


def _resolve_endpoint(raw: str, sid_to_path: dict[str, str]) -> str:
    raw = raw.strip()
    match = _ENDPOINT_RE.match(raw)
    if not match:
        return raw
    sid = match.group("sid")
    kind = match.group("kind")
    port = match.group("port")
    block = sid_to_path.get(sid, f"SID:{sid}")
    return f"{block}:{kind}{port}"


def _line_name(line: ET.Element) -> str:
    params = _direct_params(line)
    return params.get("Name", "")


def _line_destinations(line: ET.Element) -> list[str]:
    destinations: list[str] = []
    for child in list(line):
        tag = _local(child.tag)
        if tag == "P" and child.attrib.get("Name") == "Dst":
            value = _text(child)
            if value:
                destinations.append(value)
        elif tag == "Branch":
            destinations.extend(_branch_destinations(child))
    return destinations


def _branch_destinations(branch: ET.Element) -> list[str]:
    destinations: list[str] = []
    for child in list(branch):
        tag = _local(child.tag)
        if tag == "P" and child.attrib.get("Name") == "Dst":
            value = _text(child)
            if value:
                destinations.append(value)
        elif tag == "Branch":
            destinations.extend(_branch_destinations(child))
    return destinations


def _source(line: ET.Element) -> str:
    for child in _children(line, "P"):
        if child.attrib.get("Name") == "Src":
            return _text(child)
    return ""


def _safe_xml(archive: zipfile.ZipFile, member: str) -> bytes:
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise ValueError(f"SLX member not found: {member}") from exc
    if info.file_size > _MAX_XML_MEMBER_BYTES:
        raise ValueError(f"SLX XML member is too large to inspect safely: {member}")
    data = archive.read(info)
    upper = data[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError(f"SLX XML member contains a forbidden DTD/entity declaration: {member}")
    return data


def _parse_archive(archive: zipfile.ZipFile, *, model_name: str, source: str) -> Model:
    infos = archive.infolist()
    if len(infos) > _MAX_ARCHIVE_ENTRIES:
        raise ValueError("SLX package contains too many archive entries")

    xml_bytes = sum(info.file_size for info in infos if info.filename.lower().endswith(".xml"))
    if xml_bytes > _MAX_ARCHIVE_XML_BYTES:
        raise ValueError("SLX package contains too much uncompressed XML to inspect safely")

    names = {info.filename for info in infos}
    root_name = next((candidate for candidate in _ROOT_CANDIDATES if candidate in names), None)
    if root_name is None:
        candidates = sorted(name for name in names if name.startswith(_SYSTEM_DIR) and name.endswith(".xml"))
        if not candidates:
            raise ValueError(f"{source} contains no Simulink system XML")
        root_name = candidates[0]

    model = Model(name=model_name)
    visited: set[str] = set()

    def parse_system_file(member: str, system_path: str, inline: ET.Element | None = None) -> None:
        system_id = Path(member).stem if inline is None else f"{Path(member).stem}@{system_path}"
        visit_key = f"{member}|{system_path}"
        if visit_key in visited:
            return
        visited.add(visit_key)

        if inline is not None:
            system = inline
        else:
            try:
                root = ET.fromstring(_safe_xml(archive, member))
            except ET.ParseError as exc:
                raise ValueError(f"invalid XML in SLX member {member}: {exc}") from exc
            system = _system_element(root)
            if system is None:
                return

        sid_to_path: dict[str, str] = {}
        blocks = list(_children(system, "Block"))

        for block in blocks:
            sid = block.attrib.get("SID", "")
            raw_name = block.attrib.get("Name", "")
            fallback = f"SID_{sid or 'unknown'}"
            name = _normalize_name(raw_name) or raw_name or fallback
            block_type = block.attrib.get("BlockType", "Unknown")
            path_name = escape_component(raw_name or fallback)
            block_path = f"{system_path}/{path_name}" if system_path else path_name
            if sid:
                sid_to_path[sid] = block_path
                model.blocks[(system_id, sid)] = Block(
                    system_id=system_id,
                    sid=sid,
                    name=name,
                    block_type=block_type,
                    path=block_path,
                    parameters=_direct_params(block),
                )

        for line in _children(system, "Line"):
            src_raw = _source(line)
            if not src_raw:
                continue
            src = _resolve_endpoint(src_raw, sid_to_path)
            for dst_raw in _line_destinations(line):
                model.lines.add(
                    Line(
                        system_id=system_id,
                        src=src,
                        dst=_resolve_endpoint(dst_raw, sid_to_path),
                        name=_line_name(line),
                    )
                )

        for block in blocks:
            sid = block.attrib.get("SID", "")
            raw_name = block.attrib.get("Name", "")
            fallback = f"SID_{sid or 'unknown'}"
            name = _normalize_name(raw_name) or raw_name or fallback
            path_name = escape_component(raw_name or fallback)
            block_path = f"{system_path}/{path_name}" if system_path else path_name
            ref, inline_system = _system_ref(block)
            if ref:
                member_name = ref if ref.endswith(".xml") else f"{_SYSTEM_DIR}{ref}.xml"
                if member_name in names:
                    parse_system_file(member_name, block_path)
            elif inline_system is not None:
                parse_system_file(member, block_path, inline=inline_system)

    parse_system_file(root_name, "")
    model.metadata["source"] = source
    return model


def parse_slx(path: str | Path) -> Model:
    """Parse an SLX file into a compact, diff-friendly semantic model."""
    slx_path = Path(path)
    if not slx_path.exists():
        raise FileNotFoundError(slx_path)
    if not zipfile.is_zipfile(slx_path):
        raise ValueError(f"{slx_path} is not a valid SLX/ZIP package")
    digest = hashlib.sha256()
    with slx_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    with zipfile.ZipFile(slx_path) as archive:
        model = _parse_archive(archive, model_name=slx_path.stem, source=str(slx_path))
    model.metadata["sha256"] = digest.hexdigest()
    return model


def parse_slx_bytes(data: bytes, *, name: str = "model") -> Model:
    """Parse SLX bytes, useful for Git blobs and services that do not use temp files."""
    stream = io.BytesIO(data)
    if not zipfile.is_zipfile(stream):
        raise ValueError(f"{name} is not a valid SLX/ZIP package")
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        model = _parse_archive(archive, model_name=Path(name).stem, source=name)
    model.metadata["sha256"] = hashlib.sha256(data).hexdigest()
    return model
