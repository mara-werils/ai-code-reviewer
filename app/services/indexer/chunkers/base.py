from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class CodeChunk(BaseModel):
    file_path: str
    chunk_type: str  # function, class, method, module_imports, module_top_level, markdown_section
    identifier: str | None = None
    language: str
    start_line: int
    end_line: int
    content: str
    metadata: dict[str, object] = {}


@runtime_checkable
class Chunker(Protocol):
    language: str

    def chunk(self, file_path: str, content: str) -> list[CodeChunk]: ...
