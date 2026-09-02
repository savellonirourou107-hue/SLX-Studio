from __future__ import annotations

import argparse
import os
from pathlib import Path

from slxdiff.gitdiff import compare_git_refs
from slxdiff.render import render_git_markdown


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-layout", action="store_true")
    args = parser.parse_args()

    diffs = compare_git_refs(args.base, args.head, cwd=args.repo, include_layout=args.include_layout)
    report = render_git_markdown(diffs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report + "\n", encoding="utf-8")

    change_count = sum(item.result.change_count for item in diffs)
    changed = any(item.result.changed for item in diffs)
    priorities = [item.review.max_priority for item in diffs if item.result.changed]
    review_priority = "high" if "high" in priorities else "medium" if "medium" in priorities else "low" if priorities else "none"
    high_review_count = sum(1 for item in diffs for hotspot in item.review.items if hotspot.priority == "high")

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
            handle.write(f"change-count={change_count}\n")
            handle.write(f"model-count={len(diffs)}\n")
            handle.write(f"review-priority={review_priority}\n")
            handle.write(f"high-review-count={high_review_count}\n")
            handle.write(f"report-path={output.resolve()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
