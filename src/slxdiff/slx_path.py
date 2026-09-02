from __future__ import annotations


def escape_component(name: str) -> str:
    """Escape one Simulink path component (literal '/' becomes '//')."""
    return str(name).replace("/", "//")


def unescape_component(name: str) -> str:
    """Unescape one canonical Simulink path component for display."""
    return str(name).replace("//", "/")


def separator_indexes(path: str) -> list[int]:
    """Return indexes of hierarchy separators, ignoring escaped '//' pairs."""
    text = str(path)
    indexes: list[int] = []
    i = 0
    while i < len(text):
        if text[i] == "/":
            if i + 1 < len(text) and text[i + 1] == "/":
                i += 2
                continue
            indexes.append(i)
        i += 1
    return indexes


def parent_path(path: str) -> str:
    """Return the canonical parent Simulink path without corrupting escaped slashes."""
    text = str(path)
    indexes = separator_indexes(text)
    return text[: indexes[-1]] if indexes else ""


def basename(path: str) -> str:
    """Return the display basename of a canonical Simulink path."""
    text = str(path)
    indexes = separator_indexes(text)
    component = text[indexes[-1] + 1 :] if indexes else text
    return unescape_component(component)


def split_path(path: str) -> list[str]:
    """Split a canonical Simulink path into unescaped display components."""
    text = str(path)
    indexes = separator_indexes(text)
    if not indexes:
        return [unescape_component(text)] if text else []
    parts: list[str] = []
    start = 0
    for index in indexes:
        parts.append(unescape_component(text[start:index]))
        start = index + 1
    parts.append(unescape_component(text[start:]))
    return parts


def join_path(parent: str, name: str) -> str:
    component = escape_component(name)
    return f"{parent}/{component}" if parent else component


def relative_to_system(block_path: str, system_path: str) -> str:
    if not system_path:
        return block_path
    prefix = f"{system_path}/"
    if not block_path.startswith(prefix):
        raise ValueError(f"block {block_path!r} is not inside system {system_path!r}")
    return block_path[len(prefix) :]
