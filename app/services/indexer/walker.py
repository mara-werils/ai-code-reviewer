import os
from pathlib import Path

import structlog

logger = structlog.get_logger()

SKIP_DIRS = {
    ".git",
    ".github",
    "node_modules",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    ".tox",
    ".next",
    ".nuxt",
    "coverage",
}

SKIP_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".o",
    ".a",
    ".lib",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".pdf",
    ".lock",
}

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "markdown",
}

MAX_FILE_SIZE = 1_000_000  # 1MB


def walk_repository(repo_path: str | Path) -> list[tuple[str, str, str]]:
    """Walk repository and return list of (relative_path, content, language)."""
    repo_path = Path(repo_path)
    files: list[tuple[str, str, str]] = []

    for root, dirs, filenames in os.walk(repo_path):
        # Filter out skip directories in-place
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in filenames:
            filepath = Path(root) / filename
            ext = filepath.suffix.lower()

            if ext in SKIP_EXTENSIONS:
                continue

            language = LANGUAGE_MAP.get(ext)
            if not language:
                continue

            try:
                size = filepath.stat().st_size
                if size > MAX_FILE_SIZE:
                    logger.debug("skip_large_file", path=str(filepath), size=size)
                    continue

                content = filepath.read_text(encoding="utf-8", errors="ignore")
                rel_path = str(filepath.relative_to(repo_path))
                files.append((rel_path, content, language))
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("skip_unreadable_file", path=str(filepath), error=str(e))
                continue

    logger.info("walk_complete", total_files=len(files))
    return files
