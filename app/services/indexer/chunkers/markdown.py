import re

from app.services.indexer.chunkers.base import CodeChunk


class MarkdownChunker:
    language = "markdown"

    def chunk(self, file_path: str, content: str) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        lines = content.split("\n")

        current_header: str | None = None
        current_level: int = 0
        current_start: int = 1
        current_lines: list[str] = []

        for i, line in enumerate(lines, 1):
            header_match = re.match(r"^(#{1,3})\s+(.+)$", line)

            if header_match:
                # Save previous section
                if current_lines:
                    section_content = "\n".join(current_lines).strip()
                    if section_content:
                        chunks.append(
                            CodeChunk(
                                file_path=file_path,
                                chunk_type="markdown_section",
                                identifier=current_header,
                                language=self.language,
                                start_line=current_start,
                                end_line=i - 1,
                                content=section_content,
                                metadata={"heading_level": current_level},
                            )
                        )

                current_header = header_match.group(2).strip()
                current_level = len(header_match.group(1))
                current_start = i
                current_lines = [line]
            else:
                current_lines.append(line)

        # Save last section
        if current_lines:
            section_content = "\n".join(current_lines).strip()
            if section_content:
                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        chunk_type="markdown_section",
                        identifier=current_header,
                        language=self.language,
                        start_line=current_start,
                        end_line=len(lines),
                        content=section_content,
                        metadata={"heading_level": current_level},
                    )
                )

        return chunks
