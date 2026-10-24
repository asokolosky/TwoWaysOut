"""Run the sample listing (or a file) through the Claude analyzer and print the report.

Usage:
    python -m scripts.try_ai              # sample listing
    python -m scripts.try_ai listing.txt  # your own text

Needs ANTHROPIC_API_KEY in .env. Shows whether AI ran or the rule fallback was used.
"""

import logging
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.content.samples import SAMPLE_LISTING
from app.services.ai_client import get_ai_client
from app.services.analyzer import analyze_listing


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    settings = get_settings()
    client = get_ai_client(settings)
    if client is None:
        print("No ANTHROPIC_API_KEY set; the rule analyzer will be used.\n")

    text = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else SAMPLE_LISTING
    start = time.monotonic()
    report = analyze_listing(
        text, client=client, model=settings.anthropic_model, timeout=settings.ai_timeout_seconds
    )
    elapsed = time.monotonic() - start

    print(f"Analyzer: {report.analyzer}  ({elapsed:.1f}s, model {settings.anthropic_model})")
    if report.fallback_reason:
        print("Fallback:", report.fallback_reason, "(see WARNING above for the cause)")
    if report.extracted_address:
        print("Address found:", report.extracted_address)
    print("\nChecklist")
    for item in report.checklist:
        print(f"  {item.topic:13} {item.status.value:14} {item.evidence or ''}")
    print("\nFlags")
    for f in report.flags:
        print(f"  [{f.severity}] {f.message}")
    print("\nQuestions")
    for q in report.questions:
        print(f"  - {q.question}\n      {q.citation}")


if __name__ == "__main__":
    main()
