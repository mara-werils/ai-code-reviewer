import ast

from app.services.indexer.chunkers.base import CodeChunk


class PythonChunker:
    language = "python"

    def chunk(self, file_path: str, content: str) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # If we can't parse, return whole file as one chunk
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

        lines = content.split("\n")
        source_lines = content.split("\n")

        # Collect imports
        import_lines: list[int] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                import_lines.extend(range(node.lineno, node.end_lineno + 1))  # type: ignore[arg-type]

        if import_lines:
            start = min(import_lines)
            end = max(import_lines)
            chunks.append(
                CodeChunk(
                    file_path=file_path,
                    chunk_type="module_imports",
                    identifier=None,
                    language=self.language,
                    start_line=start,
                    end_line=end,
                    content="\n".join(source_lines[start - 1 : end]),
                )
            )

        # Track line ranges covered by functions/classes
        covered_lines: set[int] = set(import_lines)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                chunk = self._extract_function(file_path, source_lines, node)
                chunks.append(chunk)
                covered_lines.update(range(node.lineno, node.end_lineno + 1))  # type: ignore[arg-type]

            elif isinstance(node, ast.ClassDef):
                class_chunks = self._extract_class(file_path, source_lines, node)
                chunks.extend(class_chunks)
                covered_lines.update(range(node.lineno, node.end_lineno + 1))  # type: ignore[arg-type]

        # Module-level code (not imports, not functions/classes)
        top_level_lines = []
        for i, line in enumerate(source_lines, 1):
            if i not in covered_lines and line.strip() and not line.strip().startswith("#"):
                top_level_lines.append(i)

        if top_level_lines:
            start = min(top_level_lines)
            end = max(top_level_lines)
            top_content = "\n".join(source_lines[start - 1 : end])
            if top_content.strip():
                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        chunk_type="module_top_level",
                        identifier=None,
                        language=self.language,
                        start_line=start,
                        end_line=end,
                        content=top_content,
                    )
                )

        return chunks

    def _extract_function(
        self,
        file_path: str,
        source_lines: list[str],
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> CodeChunk:
        start = node.lineno
        # Include decorators
        if node.decorator_list:
            start = node.decorator_list[0].lineno
        end = node.end_lineno or node.lineno

        content = "\n".join(source_lines[start - 1 : end])
        decorators = [self._get_decorator_name(d) for d in node.decorator_list]

        return CodeChunk(
            file_path=file_path,
            chunk_type="function",
            identifier=node.name,
            language=self.language,
            start_line=start,
            end_line=end,
            content=content,
            metadata={
                "decorators": decorators,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "args": [arg.arg for arg in node.args.args],
            },
        )

    def _extract_class(
        self,
        file_path: str,
        source_lines: list[str],
        node: ast.ClassDef,
    ) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []

        start = node.lineno
        if node.decorator_list:
            start = node.decorator_list[0].lineno
        end = node.end_lineno or node.lineno

        # Class-level chunk (signature + docstring + class vars, without method bodies)
        class_header_lines = []
        method_ranges: list[tuple[int, int]] = []

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_start = child.lineno
                if child.decorator_list:
                    child_start = child.decorator_list[0].lineno
                child_end = child.end_lineno or child.lineno
                method_ranges.append((child_start, child_end))

        # Build class header content (everything except method bodies)
        for i in range(start, end + 1):
            in_method = any(ms <= i <= me for ms, me in method_ranges)
            if not in_method:
                class_header_lines.append(source_lines[i - 1])

        decorators = [self._get_decorator_name(d) for d in node.decorator_list]
        bases = [ast.dump(b) for b in node.bases]

        chunks.append(
            CodeChunk(
                file_path=file_path,
                chunk_type="class",
                identifier=node.name,
                language=self.language,
                start_line=start,
                end_line=end,
                content="\n".join(class_header_lines),
                metadata={
                    "decorators": decorators,
                    "bases": bases,
                },
            )
        )

        # Individual methods
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_start = child.lineno
                if child.decorator_list:
                    method_start = child.decorator_list[0].lineno
                method_end = child.end_lineno or child.lineno

                method_content = "\n".join(source_lines[method_start - 1 : method_end])
                method_decorators = [self._get_decorator_name(d) for d in child.decorator_list]

                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        chunk_type="method",
                        identifier=child.name,
                        language=self.language,
                        start_line=method_start,
                        end_line=method_end,
                        content=method_content,
                        metadata={
                            "parent_class": node.name,
                            "decorators": method_decorators,
                            "is_async": isinstance(child, ast.AsyncFunctionDef),
                            "args": [arg.arg for arg in child.args.args],
                        },
                    )
                )

        return chunks

    @staticmethod
    def _get_decorator_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{ast.dump(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return PythonChunker._get_decorator_name(node.func)
        return ast.dump(node)
