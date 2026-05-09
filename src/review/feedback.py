"""Self-learning feedback system.

Tracks which AI review comments were accepted vs rejected by the team.
Uses this history to calibrate future reviews — injecting learned patterns
into the system prompt.

Storage: JSON file per repo at `.pr-reviewer-feedback.json` in the repo root.
This works without a database and persists across reviews via commits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Max feedback entries to keep (oldest are evicted)
_MAX_ENTRIES = 200

# Max entries to include in the prompt context
_MAX_PROMPT_ENTRIES = 30


@dataclass
class FeedbackEntry:
    """A single feedback signal on an AI review comment."""

    # What the AI said
    comment_body: str
    severity: str
    file_path: str
    category: str  # e.g., "security", "performance", "design", "correctness"

    # Developer response
    outcome: str  # "accepted", "rejected", "resolved", "dismissed"
    developer_reply: str = ""

    # Context
    pr_number: int = 0
    timestamp: str = ""
    language: str = ""


@dataclass
class FeedbackStore:
    """Per-repo feedback history."""

    repo: str = ""
    entries: list[FeedbackEntry] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=lambda: {
        "total": 0,
        "accepted": 0,
        "rejected": 0,
    })

    def add(self, entry: FeedbackEntry) -> None:
        """Add a feedback entry and update stats."""
        if not entry.timestamp:
            entry.timestamp = datetime.now(UTC).isoformat()

        self.entries.append(entry)
        self.stats["total"] = self.stats.get("total", 0) + 1
        self.stats[entry.outcome] = self.stats.get(entry.outcome, 0) + 1

        # Evict oldest if over limit
        if len(self.entries) > _MAX_ENTRIES:
            self.entries = self.entries[-_MAX_ENTRIES:]

    @property
    def acceptance_rate(self) -> float:
        """Calculate what % of comments were accepted."""
        total = self.stats.get("total", 0)
        if total == 0:
            return 0.0
        accepted = self.stats.get("accepted", 0) + self.stats.get("resolved", 0)
        return accepted / total


def load_feedback(path: Path | None = None) -> FeedbackStore:
    """Load feedback from .pr-reviewer-feedback.json.

    Args:
        path: Path to feedback file. Defaults to .pr-reviewer-feedback.json in CWD.

    Returns:
        FeedbackStore (empty if file doesn't exist).
    """
    if path is None:
        path = Path(".pr-reviewer-feedback.json")

    if not path.exists():
        return FeedbackStore()

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load feedback from {path}: {e}")
        return FeedbackStore()

    entries = []
    for item in data.get("entries", []):
        entries.append(FeedbackEntry(
            comment_body=item.get("comment_body", ""),
            severity=item.get("severity", ""),
            file_path=item.get("file_path", ""),
            category=item.get("category", ""),
            outcome=item.get("outcome", ""),
            developer_reply=item.get("developer_reply", ""),
            pr_number=item.get("pr_number", 0),
            timestamp=item.get("timestamp", ""),
            language=item.get("language", ""),
        ))

    return FeedbackStore(
        repo=data.get("repo", ""),
        entries=entries,
        stats=data.get("stats", {"total": 0, "accepted": 0, "rejected": 0}),
    )


def save_feedback(store: FeedbackStore, path: Path | None = None) -> None:
    """Save feedback to .pr-reviewer-feedback.json."""
    if path is None:
        path = Path(".pr-reviewer-feedback.json")

    data = {
        "repo": store.repo,
        "stats": store.stats,
        "entries": [asdict(e) for e in store.entries],
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(store.entries)} feedback entries to {path}")


def build_learning_prompt(store: FeedbackStore) -> str:
    """Build a learning context section for the system prompt.

    Analyzes feedback history to generate rules like:
    - "This team prefers X over Y"
    - "Don't flag Z — the team consistently dismisses these"
    - "Focus more on A — the team values these comments"

    Returns:
        A string to append to the system prompt, or empty if no feedback.
    """
    if not store.entries:
        return ""

    # Analyze patterns
    rejected = [e for e in store.entries if e.outcome in ("rejected", "dismissed")]
    accepted = [e for e in store.entries if e.outcome in ("accepted", "resolved")]

    if not rejected and not accepted:
        return ""

    parts = [
        "\n## Team Feedback (learned from past reviews)",
        "",
        f"Based on {store.stats.get('total', 0)} past comments "
        f"(acceptance rate: {store.acceptance_rate:.0%}):",
        "",
    ]

    # Patterns the team rejects
    if rejected:
        rejected_categories = _count_field(rejected, "category")
        rejected_severities = _count_field(rejected, "severity")

        parts.append("### Comments this team tends to DISMISS (be cautious with these):")
        for cat, count in _top_n(rejected_categories, 5):
            parts.append(f"- {cat}: dismissed {count} times")

        # If low-severity comments are mostly rejected, note it
        info_rejected = rejected_severities.get("info", 0) + rejected_severities.get("suggestion", 0)
        if info_rejected > len(rejected) * 0.5:
            parts.append("- **This team prefers fewer, higher-impact comments. Skip INFO/SUGGESTION level issues.**")

        # Include specific rejected examples (most recent)
        recent_rejected = rejected[-5:]
        if recent_rejected:
            parts.append("")
            parts.append("Recent dismissed examples:")
            for e in recent_rejected:
                body_short = e.comment_body[:120].replace("\n", " ")
                parts.append(f'- `{e.file_path}`: "{body_short}..."')
                if e.developer_reply:
                    reply_short = e.developer_reply[:100].replace("\n", " ")
                    parts.append(f'  Developer said: "{reply_short}"')

    # Patterns the team values
    if accepted:
        accepted_categories = _count_field(accepted, "category")

        parts.append("")
        parts.append("### Comments this team VALUES (focus more on these):")
        for cat, count in _top_n(accepted_categories, 5):
            parts.append(f"- {cat}: accepted {count} times")

    parts.append("")
    return "\n".join(parts)


def collect_feedback_from_reactions(
    review_comments: list[dict],
    bot_username: str,
) -> list[FeedbackEntry]:
    """Analyze review comments to determine which were accepted/rejected.

    Heuristics:
    - Comment has 👍 or ❤️ reaction → accepted
    - Comment has 👎 or 😕 reaction → rejected
    - Comment was replied to with disagreement keywords → rejected
    - Comment thread was resolved → accepted
    """
    entries: list[FeedbackEntry] = []
    bot_comments = [
        c for c in review_comments
        if _is_bot_comment(c, bot_username)
    ]

    # Build reply map: bot_comment_id → list of replies
    reply_map: dict[int, list[dict]] = {}
    for c in review_comments:
        reply_to = c.get("in_reply_to_id")
        if reply_to:
            reply_map.setdefault(reply_to, []).append(c)

    for bc in bot_comments:
        comment_id = bc["id"]
        body = bc.get("body", "")
        path = bc.get("path", "")

        # Determine severity from body
        severity = _extract_severity(body)
        category = _extract_category(body)

        # Check reactions
        reactions = bc.get("reactions", {})
        thumbs_up = reactions.get("+1", 0) + reactions.get("heart", 0)
        thumbs_down = reactions.get("-1", 0) + reactions.get("confused", 0)

        # Check replies for disagreement
        replies = reply_map.get(comment_id, [])
        has_disagreement = any(
            _is_disagreement(r.get("body", ""))
            for r in replies
            if not _is_bot_comment(r, bot_username)
        )

        # Determine outcome
        if thumbs_down > 0 or has_disagreement:
            outcome = "rejected"
        elif thumbs_up > 0:
            outcome = "accepted"
        else:
            # No signal — skip
            continue

        developer_reply = ""
        if replies:
            human_replies = [r for r in replies if not _is_bot_comment(r, bot_username)]
            if human_replies:
                developer_reply = human_replies[-1].get("body", "")

        entries.append(FeedbackEntry(
            comment_body=body[:300],
            severity=severity,
            file_path=path,
            category=category,
            outcome=outcome,
            developer_reply=developer_reply[:200],
        ))

    return entries


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_bot_comment(comment: dict, bot_username: str) -> bool:
    user = comment.get("user", {}).get("login", "")
    if user == bot_username or user.endswith("[bot]"):
        return True
    body = comment.get("body", "")
    return any(m in body for m in ("[CRITICAL]", "[WARNING]", "[SUGGESTION]", "[INFO]"))


def _extract_severity(body: str) -> str:
    if "[CRITICAL]" in body:
        return "critical"
    if "[WARNING]" in body:
        return "warning"
    if "[SUGGESTION]" in body:
        return "suggestion"
    return "info"


def _extract_category(body: str) -> str:
    """Try to categorize the comment based on keywords."""
    lower = body.lower()
    categories = {
        "security": ("injection", "xss", "ssrf", "secret", "credential", "auth", "csrf"),
        "performance": ("n+1", "performance", "slow", "index", "cache", "memory", "leak"),
        "correctness": ("bug", "null", "none", "error", "exception", "race", "deadlock"),
        "design": ("coupling", "abstraction", "pattern", "refactor", "solid", "dry"),
        "testing": ("test", "coverage", "mock", "assert"),
    }
    for cat, keywords in categories.items():
        if any(kw in lower for kw in keywords):
            return cat
    return "general"


_DISAGREEMENT_KEYWORDS = (
    "disagree", "don't think", "not necessary", "not needed",
    "won't fix", "by design", "intentional", "false positive",
    "this is fine", "already handled", "not an issue", "nit",
)


def _is_disagreement(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _DISAGREEMENT_KEYWORDS)


def _count_field(entries: list[FeedbackEntry], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        val = getattr(e, field, "")
        if val:
            counts[val] = counts.get(val, 0) + 1
    return counts


def _top_n(counts: dict[str, int], n: int) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:n]
