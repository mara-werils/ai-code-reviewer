"""Run evaluation locally on a golden dataset.

Usage:
    python -m scripts.run_eval_locally --repo owner/name --limit 5
"""

import argparse
import asyncio
import json
from pathlib import Path

EVAL_DIR = Path(__file__).parent.parent / "tests" / "eval"
GOLDEN_DIR = EVAL_DIR / "golden_dataset"


async def main(repo: str, limit: int) -> None:
    # Find golden dataset files for this repo
    repo_prefix = repo.replace("/", "_")
    files = sorted(GOLDEN_DIR.glob(f"{repo_prefix}_*.json"))

    if not files:
        print(f"No golden dataset files found for {repo}")
        print(f"Run: python -m scripts.build_golden_dataset --repo {repo}")
        return

    files = files[:limit]
    print(f"Running eval on {len(files)} PRs from {repo}")

    results = []
    for f in files:
        data = json.loads(f.read_text())
        print(f"\n--- PR #{data['pr_number']}: {data['title']} ---")
        # TODO: Run agent on this PR and compare with human comments
        results.append({
            "pr_number": data["pr_number"],
            "title": data["title"],
            "human_comments": len(data.get("human_review_comments", [])),
            "status": "pending",
        })

    # Generate report
    report_path = EVAL_DIR / "report.md"
    with open(report_path, "w") as f:
        f.write("# Evaluation Report\n\n")
        f.write(f"Repository: {repo}\n")
        f.write(f"PRs evaluated: {len(results)}\n\n")
        f.write("| PR | Title | Human Comments | Agent Comments | Recall | Precision |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in results:
            f.write(f"| #{r['pr_number']} | {r['title'][:40]} | {r['human_comments']} | - | - | - |\n")
        f.write("\n*Run with full agent to populate results.*\n")

    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.repo, args.limit))
