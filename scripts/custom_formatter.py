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


    def format(self) -> str:
        lines = list(self.source_lines)

        # Work from the bottom of the file up, so padding a definition never moves one still to be handled
        for lineno, node in sorted(self._definition_nodes().items(), key=lambda x: x[0], reverse=True):
            if not self._is_in_disabled_range(lineno):
                self._pad_blank_lines_above(lines, lineno - 1, self._required_blank_lines(node))

        result = "\n".join(line.rstrip() for line in lines)
        if result:
            result = result.strip() + "\n"

        return result


    def _definition_nodes(self) -> dict:
        """Map the first line of every function and class definition, decorators included, to its node."""
        nodes = {}
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nodes[self.get_node_start_line(node)] = node
        return nodes


    def _required_blank_lines(self, node) -> int:
        """An __init__ method gets 1 blank line above it; every other function, method and class gets 2."""
        is_function = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        if is_function and self.is_method(node) and node.name == "__init__":
            return 1
        return 2


    @staticmethod
    def _pad_blank_lines_above(lines: list, start_index: int, required: int) -> None:
        """Grow the gap above the line at start_index to `required` blank lines; a bigger gap is left alone."""
        # Walk up past the blank lines to the nearest line with content
        i = start_index - 1
        while i > 0 and not lines[i].strip():
            i -= 1

        # A definition on the very first line of the file has nothing above it to pad
        if i < 0:
            return

        if start_index - 1 - i < required:
            lines[i + 1 : start_index] = [""] * required


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
