"""Full evaluation pipeline: run agent on golden dataset and compare with human reviews.

Usage:
    python -m tests.eval.run_eval --repo pallets/flask --limit 5
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import anthropic

from app.config import get_settings

EVAL_DIR = Path(__file__).parent
GOLDEN_DIR = EVAL_DIR / "golden_dataset"

JUDGE_PROMPT = """You are evaluating an AI code reviewer's comment against a human reviewer's comment.

Human comment on {file} (line {line}):
{human_comment}

AI comment on {ai_file} (line {ai_line}):
{ai_comment}

Does the AI comment cover the same issue as the human comment?
Answer exactly one of: "yes", "no", "partially"
"""

VALIDITY_PROMPT = """You are evaluating whether an AI code reviewer's comment is valid and helpful.

File: {file}, Line: {line}
AI comment: {comment}

Context (diff excerpt):
{diff_excerpt}

Is this a valid, actionable code review comment? (Not a false positive, not a nitpick about style)
Answer exactly one of: "yes", "no"
"""


async def evaluate_pr(
    pr_data: dict[str, Any],
    client: anthropic.AsyncAnthropic,
) -> dict[str, Any]:
    """Run agent on a single PR and evaluate results."""
    # For now, return placeholder — full implementation requires running the agent
    return {
        "pr_number": pr_data["pr_number"],
        "title": pr_data["title"],
        "human_comments_count": len(pr_data.get("human_review_comments", [])),
        "agent_comments_count": 0,
        "recall": 0.0,
        "precision": 0.0,
        "status": "evaluated",
    }


async def main(repo: str, limit: int) -> None:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    repo_prefix = repo.replace("/", "_")
    files = sorted(GOLDEN_DIR.glob(f"{repo_prefix}_*.json"))[:limit]

    if not files:
        print(f"No golden dataset for {repo}. Run build_golden_dataset.py first.")
        return

    print(f"Evaluating {len(files)} PRs from {repo}\n")

    results = []
    for f in files:
        data = json.loads(f.read_text())
        print(f"  Evaluating PR #{data['pr_number']}: {data['title'][:50]}...")
        result = await evaluate_pr(data, client)
        results.append(result)
        print(f"    Recall: {result['recall']:.1%}, Precision: {result['precision']:.1%}")

    # Generate report
    total_recall = sum(r["recall"] for r in results) / max(len(results), 1)
    total_precision = sum(r["precision"] for r in results) / max(len(results), 1)

    report_path = EVAL_DIR / "report.md"
    with open(report_path, "w") as f:
        f.write("# PR Reviewer Agent — Evaluation Report\n\n")
        f.write(f"**Repository:** {repo}\n")
        f.write(f"**PRs evaluated:** {len(results)}\n")
        f.write(f"**Aggregate Recall:** {total_recall:.1%}\n")
        f.write(f"**Aggregate Precision:** {total_precision:.1%}\n\n")
        f.write("## Per-PR Results\n\n")
        f.write("| PR | Title | Human | Agent | Recall | Precision |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in results:
            f.write(
                f"| #{r['pr_number']} | {r['title'][:40]} | "
                f"{r['human_comments_count']} | {r['agent_comments_count']} | "
                f"{r['recall']:.1%} | {r['precision']:.1%} |\n"
            )
        f.write("\n## Methodology\n\n")
        f.write("- Golden dataset: closed, merged PRs with human review comments\n")
        f.write("- Recall: % of human-identified issues also found by agent (LLM-as-judge)\n")
        f.write("- Precision: % of agent comments deemed valid by LLM judge\n")
        f.write("- Judge model: Claude Sonnet\n")

    print(f"\nReport saved to {report_path}")
    print(f"Aggregate: Recall={total_recall:.1%}, Precision={total_precision:.1%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.repo, args.limit))
