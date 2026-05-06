
from app.services.indexer.chunkers.markdown import MarkdownChunker
from app.services.indexer.chunkers.python_ast import PythonChunker


class TestPythonChunker:
    def setup_method(self) -> None:
        self.chunker = PythonChunker()

    def test_simple_function(self) -> None:
        code = '''def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
        chunks = self.chunker.chunk("test.py", code)
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        assert len(func_chunks) == 1
        assert func_chunks[0].identifier == "hello"
        assert func_chunks[0].start_line == 1
        assert func_chunks[0].end_line == 3

    def test_class_with_methods(self) -> None:
        code = '''class Calculator:
    """A simple calculator."""

    def __init__(self, value: int = 0):
        self.value = value

    def add(self, n: int) -> "Calculator":
        self.value += n
        return self

    def subtract(self, n: int) -> "Calculator":
        self.value -= n
        return self
'''
        chunks = self.chunker.chunk("calc.py", code)

        class_chunks = [c for c in chunks if c.chunk_type == "class"]
        assert len(class_chunks) == 1
        assert class_chunks[0].identifier == "Calculator"

        method_chunks = [c for c in chunks if c.chunk_type == "method"]
        method_names = {c.identifier for c in method_chunks}
        assert method_names == {"__init__", "add", "subtract"}

        for mc in method_chunks:
            assert mc.metadata.get("parent_class") == "Calculator"

    def test_decorated_function(self) -> None:
        code = '''@app.route("/api")
@login_required
def api_endpoint():
    return {"status": "ok"}
'''
        chunks = self.chunker.chunk("routes.py", code)
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        assert len(func_chunks) == 1
        assert func_chunks[0].identifier == "api_endpoint"
        assert func_chunks[0].start_line == 1  # Includes decorators
        assert "@app.route" in func_chunks[0].content

    def test_async_function(self) -> None:
        code = '''async def fetch_data(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return resp.json()
'''
        chunks = self.chunker.chunk("fetch.py", code)
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        assert len(func_chunks) == 1
        assert func_chunks[0].metadata.get("is_async") is True

    def test_imports(self) -> None:
        code = '''import os
from pathlib import Path
from typing import Optional

def main():
    pass
'''
        chunks = self.chunker.chunk("main.py", code)
        import_chunks = [c for c in chunks if c.chunk_type == "module_imports"]
        assert len(import_chunks) == 1
        assert "import os" in import_chunks[0].content

    def test_syntax_error_fallback(self) -> None:
        code = "def broken(:\n  pass"
        chunks = self.chunker.chunk("broken.py", code)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "module_top_level"


class TestMarkdownChunker:
    def setup_method(self) -> None:
        self.chunker = MarkdownChunker()

    def test_sections(self) -> None:
        content = """# Title

Some intro text.

## Installation

Run `pip install`.

## Usage

Import and use.

### Advanced Usage

More details here.
"""
        chunks = self.chunker.chunk("README.md", content)
        identifiers = [c.identifier for c in chunks]
        assert "Title" in identifiers
        assert "Installation" in identifiers
        assert "Usage" in identifiers
        assert "Advanced Usage" in identifiers

    def test_no_headers(self) -> None:
        content = "Just plain text\nwith no headers."
        chunks = self.chunker.chunk("notes.md", content)
        assert len(chunks) == 1
        assert chunks[0].identifier is None

    def test_heading_levels(self) -> None:
        content = """# H1

Text

## H2

Text

### H3

Text
"""
        chunks = self.chunker.chunk("doc.md", content)
        levels = {c.identifier: c.metadata.get("heading_level") for c in chunks}
        assert levels["H1"] == 1
        assert levels["H2"] == 2
        assert levels["H3"] == 3
