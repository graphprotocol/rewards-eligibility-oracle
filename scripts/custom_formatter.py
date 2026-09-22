#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import ast
import sys
from pathlib import Path


class PythonFormatter:

    def __init__(self, source_code: str):
        self.source_lines = source_code.splitlines()
        self.tree = ast.parse(source_code)
        self.node_parents = {
            child: parent for parent in ast.walk(self.tree) for child in ast.iter_child_nodes(parent)
        }
        self.disabled_ranges = self._find_disabled_ranges()


    def _find_disabled_ranges(self):
        ranges = []
        in_disabled_block = False
        start_line = 0
        for i, line in enumerate(self.source_lines):
            if "# fmt: off" in line:
                in_disabled_block = True
                start_line = i + 1
            elif "# fmt: on" in line:
                if in_disabled_block:
                    ranges.append((start_line, i + 1))
                in_disabled_block = False
        return ranges


    def _is_in_disabled_range(self, lineno):
        for start, end in self.disabled_ranges:
            if start <= lineno <= end:
                return True
        return False


    def get_node_start_line(self, node):
        if node.decorator_list:
            return node.decorator_list[0].lineno
        return node.lineno


    def is_method(self, node) -> bool:
        return isinstance(self.node_parents.get(node), ast.ClassDef)


    def _definitions_by_start_line(self):
        """Return every class and function definition, keyed by the line its first decorator or header sits on."""
        nodes = {}
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nodes[self.get_node_start_line(node)] = node
        return nodes


    def _required_blank_lines(self, node) -> int:
        """Return how many blank lines should sit above a definition."""
        if isinstance(node, ast.ClassDef):
            return 2
        if self.is_method(node) and node.name == "__init__":
            return 1
        return 2


    @staticmethod
    def _previous_code_line_index(lines, start_index) -> int:
        """Return the index of the nearest non-blank line above start_index, or -1 at the start of the file."""
        i = start_index - 1
        while i > 0 and not lines[i].strip():
            i -= 1
        return max(i, -1)


    @staticmethod
    def _pad_blank_lines(lines, start_index, previous_code_index, num_blank_lines):
        """Ensure at least num_blank_lines blank lines sit between the previous code line and start_index."""
        existing_blank_lines = sum(
            1 for k in range(start_index - 1, previous_code_index, -1) if not lines[k].strip()
        )
        if existing_blank_lines >= num_blank_lines:
            return

        del lines[previous_code_index + 1 : start_index]
        for _ in range(num_blank_lines):
            lines.insert(previous_code_index + 1, "")


    def format(self) -> str:
        lines = list(self.source_lines)

        # Walk definitions bottom-up so inserting lines above one never shifts the ones still to process
        sorted_nodes = sorted(self._definitions_by_start_line().items(), key=lambda x: x[0], reverse=True)
        for lineno, node in sorted_nodes:
            # Skip formatting if node is inside a "fmt: off" block
            if self._is_in_disabled_range(lineno):
                continue

            start_index = lineno - 1
            previous_code_index = self._previous_code_line_index(lines, start_index)

            # A definition that is the first thing in the file needs no blank lines above it
            if previous_code_index == -1:
                continue

            self._pad_blank_lines(lines, start_index, previous_code_index, self._required_blank_lines(node))

        result = "\n".join(line.rstrip() for line in lines)
        if result:
            result = result.strip() + "\n"

        return result


def main():
    parser = argparse.ArgumentParser(description="Python custom formatter.")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.files:
        try:
            source = path.read_text()
            # Skip empty files
            if not source.strip():
                continue
            formatter = PythonFormatter(source)
            formatted_source = formatter.format()
            path.write_text(formatted_source)
            print(f"Formatted {path}")
        except Exception as e:
            print(f"Could not format {path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
