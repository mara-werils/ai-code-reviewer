"""Build golden dataset from closed PRs with review comments.

Usage:
    python -m scripts.build_golden_dataset --repo pallets/flask --count 20
"""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

GOLDEN_DIR = Path(__file__).parent.parent / "tests" / "eval" / "golden_dataset"


async def fetch_prs_with_reviews(repo: str, count: int, token: str | None = None) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers) as client:
        # Fetch closed, merged PRs
        resp = await client.get(
            f"/repos/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50},
        )
        resp.raise_for_status()
        prs = resp.json()

        saved = 0
        for pr in prs:
            if saved >= count:
                break

            if not pr.get("merged_at"):
                continue

            pr_number = pr["number"]

            # Fetch review comments
            comments_resp = await client.get(
                f"/repos/{repo}/pulls/{pr_number}/comments",
                params={"per_page": 100},
            )
            comments_resp.raise_for_status()
            comments = comments_resp.json()

            if not comments:
                continue

            # Fetch diff
            diff_resp = await client.get(
                f"/repos/{repo}/pulls/{pr_number}",
                headers={**headers, "Accept": "application/vnd.github.v3.diff"},
            )
            diff_text = diff_resp.text if diff_resp.status_code == 200 else ""

            # Build dataset entry
            entry = {
                "repo": repo,
                "pr_number": pr_number,
                "title": pr["title"],
                "body": pr.get("body", ""),
                "head_sha": pr["head"]["sha"],
                "base_sha": pr["base"]["sha"],
                "diff": diff_text[:50000],  # Cap diff size
                "human_review_comments": [
                    {
                        "file": c.get("path", ""),
                        "line": c.get("line"),
                        "body": c.get("body", ""),
                    }
                    for c in comments
                    if c.get("user", {}).get("type") != "Bot"
                ],
            }

            filename = f"{repo.replace('/', '_')}_{pr_number}.json"
            (GOLDEN_DIR / filename).write_text(json.dumps(entry, indent=2, ensure_ascii=False))
            saved += 1
            print(f"Saved PR #{pr_number} ({saved}/{count})")

    print(f"\nDone! Saved {saved} PRs to {GOLDEN_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="e.g. pallets/flask")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--token", help="GitHub PAT (optional, for rate limits)")
    args = parser.parse_args()
    asyncio.run(fetch_prs_with_reviews(args.repo, args.count, args.token))
