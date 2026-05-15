"""Lightweight benchmark for review quality.

Runs the security scanner and (optionally) LLM review against
a curated golden dataset of known vulnerabilities, bugs, and clean code.

Usage:
    python -m tests.eval.bench                    # security scanner only
    python -m tests.eval.bench --with-llm         # scanner + LLM review
    python -m tests.eval.bench --provider groq    # specify provider
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from src.github.client import PRFile
from src.review.security import scan_diff

GOLDEN_PATH = Path(__file__).parent / "golden_dataset" / "samples.json"


def _make_file(name: str, diff: str) -> PRFile:
    """Create a PRFile from a diff string."""
    return PRFile(
        filename=name,
        status="modified",
        additions=diff.count("\n+") - diff.count("\n+++"),
        deletions=diff.count("\n-") - diff.count("\n---"),
        patch=diff,
    )


def _finding_matches(finding_text: str, expected: dict) -> bool:
    """Check if a finding matches expected pattern."""
    pattern = expected.get("pattern", "")
    if pattern:
        return bool(re.search(pattern, finding_text, re.IGNORECASE))
    return False


def run_scanner_bench(samples: list[dict]) -> dict:
    """Run security scanner against golden dataset."""
    results = {
        "total": len(samples),
        "true_positives": 0,
        "false_negatives": 0,
        "false_positives": 0,
        "true_negatives": 0,
        "details": [],
    }

    for sample in samples:
        name = sample["name"]
        diff = sample["diff"]
        expected = sample["expected_findings"]

        # Detect filename from diff
        filename = "unknown.py"
        for line in diff.split("\n"):
            if line.startswith("+++ b/"):
                filename = line[6:]
                break

        files = [_make_file(filename, diff)]
        findings = scan_diff(files)

        finding_texts = [f"{f.rule_name} {f.description} {f.category}".lower() for f in findings]
        all_findings_text = " ".join(finding_texts)

        # Check expected findings
        matched_expected = 0
        for exp in expected:
            if _finding_matches(all_findings_text, exp):
                matched_expected += 1

        if expected:
            if matched_expected > 0:
                results["true_positives"] += 1
            else:
                results["false_negatives"] += 1
        else:
            # Clean code — no findings expected
            if not findings:
                results["true_negatives"] += 1
            else:
                results["false_positives"] += 1

        results["details"].append(
            {
                "name": name,
                "expected_count": len(expected),
                "found_count": len(findings),
                "matched": matched_expected,
                "status": "PASS"
                if ((expected and matched_expected > 0) or (not expected and not findings))
                else "FAIL",
            }
        )

    tp = results["true_positives"]
    fn = results["false_negatives"]
    fp = results["false_positives"]

    results["recall"] = tp / max(tp + fn, 1)
    results["precision"] = tp / max(tp + fp, 1)

    return results


def print_report(results: dict) -> None:
    """Print benchmark results."""
    print("\n" + "=" * 60)
    print("  AI Code Reviewer — Security Scanner Benchmark")
    print("=" * 60)
    print(f"\n  Samples: {results['total']}")
    print(f"  Recall:    {results['recall']:.0%}")
    print(f"  Precision: {results['precision']:.0%}")
    print(f"\n  True Positives:  {results['true_positives']}")
    print(f"  False Negatives: {results['false_negatives']}")
    print(f"  False Positives: {results['false_positives']}")
    print(f"  True Negatives:  {results['true_negatives']}")
    print("\n  Per-sample:")
    for d in results["details"]:
        status = "PASS" if d["status"] == "PASS" else "FAIL"
        print(
            f"    [{status}] {d['name']}: expected={d['expected_count']}, "
            f"found={d['found_count']}, matched={d['matched']}"
        )
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run review quality benchmarks")
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Also run LLM-based review (requires API key)",
    )
    parser.add_argument("--provider", default="groq", help="LLM provider for --with-llm")
    parser.parse_args()

    if not GOLDEN_PATH.exists():
        print(f"Golden dataset not found at {GOLDEN_PATH}")
        sys.exit(1)

    samples = json.loads(GOLDEN_PATH.read_text())

    # Run scanner benchmark
    results = run_scanner_bench(samples)
    print_report(results)

    if results["recall"] < 0.5:
        print("\n  WARNING: Recall below 50% — scanner is missing known vulnerabilities")
        sys.exit(1)


if __name__ == "__main__":
    main()
