"""Tree-sitter based chunker for JS/TS/Go."""

import structlog

from app.services.indexer.chunkers.base import CodeChunk

logger = structlog.get_logger()

# Tree-sitter node types for each language
LANGUAGE_CONFIG: dict[str, dict[str, list[str]]] = {
    "javascript": {
        "function_types": [
            "function_declaration",
            "arrow_function",
            "function_expression",
        ],
        "class_types": ["class_declaration"],
        "method_types": ["method_definition"],
    },
    "typescript": {
        "function_types": [
            "function_declaration",
            "arrow_function",
            "function_expression",
        ],
        "class_types": ["class_declaration"],
        "method_types": ["method_definition"],
    },
    "go": {
        "function_types": ["function_declaration"],
        "class_types": ["type_declaration"],
        "method_types": ["method_declaration"],
    },
}


class TreeSitterChunker:
    def __init__(self, language: str) -> None:
        self.language = language
        self._parser = None
        self._ts_language = None

    def _ensure_parser(self) -> bool:
        if self._parser is not None:
            return True

        try:
            import tree_sitter as ts

            if self.language == "javascript":
                import tree_sitter_javascript as ts_js

                self._ts_language = ts.Language(ts_js.language())
            elif self.language == "typescript":
                import tree_sitter_typescript as ts_ts

                self._ts_language = ts.Language(ts_ts.language_typescript())
            else:
                logger.warning("tree_sitter_language_not_available", language=self.language)
                return False

            self._parser = ts.Parser(self._ts_language)
            return True
        except ImportError:
            logger.warning("tree_sitter_not_available", language=self.language)
            return False

    def chunk(self, file_path: str, content: str) -> list[CodeChunk]:
        if not self._ensure_parser():
            # Fallback: whole file as one chunk
            lines = content.split("\n")
            return [
                CodeChunk(
                    file_path=file_path,
                    chunk_type="module_top_level",
                    identifier=None,
                    language=self.language,
                    start_line=1,
                    end_line=len(lines),
                    content=content,
                )
            ]

        tree = self._parser.parse(content.encode("utf-8"))  # type: ignore[union-attr]
        root = tree.root_node
        chunks: list[CodeChunk] = []
        config = LANGUAGE_CONFIG.get(self.language, LANGUAGE_CONFIG["javascript"])

        self._walk_node(root, file_path, content, config, chunks, parent_class=None)
        return chunks

    def _walk_node(
        self,
        node: object,
        file_path: str,
        content: str,
        config: dict[str, list[str]],
        chunks: list[CodeChunk],
        parent_class: str | None,
    ) -> None:
        node_type = node.type  # type: ignore[attr-defined]

        if node_type in config["function_types"]:
            name = self._get_name(node)
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    chunk_type="function",
                    identifier=name,
                    language=self.language,
                    start_line=node.start_point[0] + 1,  # type: ignore[attr-defined]
                    end_line=node.end_point[0] + 1,  # type: ignore[attr-defined]
                    content=node.text.decode("utf-8"),  # type: ignore[attr-defined]
                    metadata={"parent_class": parent_class} if parent_class else {},
                )
            )
            return

        if node_type in config["class_types"]:
            class_name = self._get_name(node)
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    chunk_type="class",
                    identifier=class_name,
                    language=self.language,
                    start_line=node.start_point[0] + 1,  # type: ignore[attr-defined]
                    end_line=node.end_point[0] + 1,  # type: ignore[attr-defined]
                    content=node.text.decode("utf-8"),  # type: ignore[attr-defined]
                )
            )
            for child in node.children:  # type: ignore[attr-defined]
                self._walk_node(child, file_path, content, config, chunks, class_name)
            return

        if node_type in config["method_types"]:
            name = self._get_name(node)
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    chunk_type="method",
                    identifier=name,
                    language=self.language,
                    start_line=node.start_point[0] + 1,  # type: ignore[attr-defined]
                    end_line=node.end_point[0] + 1,  # type: ignore[attr-defined]
                    content=node.text.decode("utf-8"),  # type: ignore[attr-defined]
                    metadata={"parent_class": parent_class} if parent_class else {},
                )
            )
            return

        for child in node.children:  # type: ignore[attr-defined]
            self._walk_node(child, file_path, content, config, chunks, parent_class)

    @staticmethod
    def _get_name(node: object) -> str | None:
        for child in node.children:  # type: ignore[attr-defined]
            if child.type in ("identifier", "property_identifier", "type_identifier"):  # type: ignore[attr-defined]
                return child.text.decode("utf-8")  # type: ignore[attr-defined]
        return None
