class PRReviewerError(Exception):
    """Base exception for PR Reviewer Agent."""


class WebhookValidationError(PRReviewerError):
    """Invalid webhook signature."""


class GitHubAuthError(PRReviewerError):
    """Failed to authenticate with GitHub."""


class IndexingError(PRReviewerError):
    """Error during repository indexing."""


class ReviewError(PRReviewerError):
    """Error during PR review."""


class CostLimitExceededError(PRReviewerError):
    """Review cost exceeded the configured limit."""


class RetrievalError(PRReviewerError):
    """Error during code retrieval."""
