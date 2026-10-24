#!/usr/bin/env python3
"""PreToolUse guard: ask the user before the agent writes or deletes sensitive files.

Reads the hook's JSON payload from stdin, finds any file paths in the tool input, and if one is
sensitive prints a permissionDecision "ask" so the user confirms first. Never prints file
contents. Stdlib only.
"""

from __future__ import annotations

import json
import re
import sys

PATH_KEYS = {"path", "targetFile", "target_file", "file_path", "filePath", "sourcePath", "destinationPath"}

# (pattern on a workspace-relative path, reason shown to the user)
SENSITIVE = [
    (re.compile(r"(^|/)\.env(\.(?!example$)[^/]*)?$"), "secrets file (.env)"),
    (re.compile(r"(^|/)data/raw/"), "raw Boston data (contains owner names)"),
    (re.compile(r"(^|/)data/[^/]*\.sqlite[^/]*$"), "app or Boston database"),
    (re.compile(r"(^|/)\.kiro/steering/project-rules\.md$"), "project privacy and content rules"),
    (re.compile(r"(^|/)app/content/sources\.py$"), "the fixed citation sources"),
    (re.compile(r"(^|/)app/content/copy\.py$"), "required exact strings (disclaimer, ranking statement)"),
    (re.compile(r"(^|/)docker/entrypoint\.sh$|(^|/)render\.yaml$|(^|/)Dockerfile$"), "deploy config"),
]


def find_paths(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in PATH_KEYS and isinstance(v, str):
                yield v
            else:
                yield from find_paths(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from find_paths(v)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # can't parse; don't block
    reasons = []
    for p in find_paths(payload):
        norm = p.replace("\\", "/")
        for pat, why in SENSITIVE:
            if pat.search(norm):
                reasons.append(f"{norm.rsplit('/', 1)[-1]}: {why}")
                break
    if reasons:
        print(json.dumps({
            "hookSpecificOutput": {
                "permissionDecision": "ask",
                "permissionDecisionReason": "Sensitive TwoWaysOut file. " + "; ".join(reasons),
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
