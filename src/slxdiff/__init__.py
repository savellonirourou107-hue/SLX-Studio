"""slx-diff: semantic diffs for Simulink models."""

from .diff import DiffResult, compare_models
from .context import build_agent_context
from .gitdiff import GitModelDiff, compare_git_refs
from .parser import parse_slx, parse_slx_bytes
from .review import ReviewReport, build_review_report

__all__ = [
    "DiffResult",
    "ReviewReport",
    "GitModelDiff",
    "build_agent_context",
    "build_review_report",
    "compare_git_refs",
    "compare_models",
    "parse_slx",
    "parse_slx_bytes",
]
__version__ = "1.0.0b2"
