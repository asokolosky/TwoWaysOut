#!/usr/bin/env python3
"""Check TwoWaysOut copy against the citation and content rules.

Usage:
    .venv/bin/python .kiro/skills/massachusetts-fire-safety-sources/scripts/check_citations.py [files...]

With no arguments, scans app/content/, app/templates/, and the analyzer services. Files outside
app/ are ignored. Exits 1 if anything is flagged. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TARGETS = [
    "app/content",
    "app/templates",
    "app/services/analyzer.py",
    "app/services/rules_analyzer.py",
    "app/services/building_questions.py",
]
EXTENSIONS = {".py", ".html", ".jinja", ".j2", ".txt", ".md"}
GUIDANCE_IDS = ("umass_off_campus", "amherst_fire", "dfs_college", "nfpa_construction")

URL = re.compile(r"https?://\S+")
SECTION_PATTERNS = [
    re.compile(r"\b\d{3}\s*CMR\b", re.I),
    re.compile(r"\bCMR\s*\d", re.I),
    re.compile(r"§"),
    re.compile(r"\b410\.\d{3}\b"),
    re.compile(r"\bsection\s+\d", re.I),
    re.compile(r"\bM\.?\s?G\.?\s?L\.?\s+c(h|\.)", re.I),
]
SAFE_CLAIMS = [
    re.compile(r"\bup to code\b", re.I),
    re.compile(r"\b(unit|apartment|building|home|rental|place) is (safe|compliant|up to code)\b", re.I),
    re.compile(r"\bmeets (the )?(fire )?code\b", re.I),
    re.compile(r"\bfully compliant\b", re.I),
]
NEGATION = re.compile(r"\b(never|not|no)\b|n't\b", re.I)
GUIDANCE_REQUIRED = re.compile(
    r'source_id\s*=\s*"(' + "|".join(GUIDANCE_IDS) + r')"\s*,\s*relation\s*=\s*"required_by"'
)


def iter_files(args: list[str]):
    targets = args or DEFAULT_TARGETS
    for t in targets:
        p = Path(t)
        if not p.is_absolute():
            p = ROOT / p
        p = p.resolve()
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            continue
        if rel.parts[:1] != ("app",):
            continue
        if p.is_dir():
            # Skip symlinks so a link inside app/ can't make the checker read (and print) a file
            # elsewhere, such as .env.
            yield from (
                f for f in sorted(p.rglob("*"))
                if not f.is_symlink() and f.is_file() and f.suffix in EXTENSIONS
                and f.resolve().is_relative_to(ROOT / "app")
            )
        elif p.is_file() and p.suffix in EXTENSIONS:
            yield p


def check_file(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    for n, line in enumerate(text.splitlines(), 1):
        # Regex definitions (e.g. the analyzer's own section-number detector) aren't copy.
        if "re.compile(" in line or "citation-check: ignore" in line:
            continue
        stripped = URL.sub("", line)
        for pat in SECTION_PATTERNS:
            if pat.search(stripped):
                findings.append(f"{rel}:{n}: section-number citation: {line.strip()[:120]}")
                break
        if "\u2014" in line:
            findings.append(f"{rel}:{n}: em dash in copy: {line.strip()[:120]}")
        if not NEGATION.search(stripped):
            for pat in SAFE_CLAIMS:
                if pat.search(stripped):
                    findings.append(f"{rel}:{n}: implies a unit is safe or compliant: {line.strip()[:120]}")
                    break
    for m in GUIDANCE_REQUIRED.finditer(text):
        n = text.count("\n", 0, m.start()) + 1
        findings.append(f'{rel}:{n}: "{m.group(1)}" is guidance and cannot be required_by')
    return findings


def main(argv: list[str]) -> int:
    findings = []
    files = list(iter_files(argv))
    for f in files:
        findings.extend(check_file(f))
    if findings:
        print("Citation/content rule findings:")
        print("\n".join(findings))
        print("See .kiro/skills/massachusetts-fire-safety-sources/SKILL.md")
        return 1
    print(f"Citation check passed ({len(files)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
