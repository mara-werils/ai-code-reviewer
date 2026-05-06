from pathlib import Path

from app.services.indexer.walker import walk_repository

SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"


class TestWalker:
    def test_walks_sample_repo(self) -> None:
        files = walk_repository(SAMPLE_REPO)
        paths = {f[0] for f in files}
        languages = {f[2] for f in files}

        assert "main.py" in paths
        assert "utils.js" in paths
        assert "README.md" in paths
        assert "python" in languages
        assert "javascript" in languages
        assert "markdown" in languages

    def test_returns_content(self) -> None:
        files = walk_repository(SAMPLE_REPO)
        py_files = [(p, c, lang) for p, c, lang in files if p == "main.py"]
        assert len(py_files) == 1
        assert "class AppConfig" in py_files[0][1]
