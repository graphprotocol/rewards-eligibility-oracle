"""Tests for the custom formatter that sets the blank lines above functions and classes."""

import importlib.util
from pathlib import Path

import pytest

# The formatter is a standalone script rather than a package module, so load it from its path
_spec = importlib.util.spec_from_file_location(
    "custom_formatter", Path(__file__).resolve().parents[1] / "scripts" / "custom_formatter.py"
)
custom_formatter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(custom_formatter)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("import os\ndef f():\n    pass\n", "import os\n\n\ndef f():\n    pass\n"),
        (
            "class A:\n    x = 1\n    def __init__(self):\n        pass\n    def m(self):\n        pass\n",
            "class A:\n    x = 1\n\n    def __init__(self):\n        pass\n\n\n    def m(self):\n        pass\n",
        ),
        (
            "import x\n@decorator\ndef f():\n    pass\n@dec\nclass C:\n    pass\n",
            "import x\n\n\n@decorator\ndef f():\n    pass\n\n\n@dec\nclass C:\n    pass\n",
        ),
        ("x = 1\n\n\n\n\ndef f():\n    pass\n", "x = 1\n\n\n\n\ndef f():\n    pass\n"),
        (
            "x = 1\n# fmt: off\ndef a():\n    pass\n# fmt: on\ndef b():\n    pass\n",
            "x = 1\n# fmt: off\ndef a():\n    pass\n# fmt: on\n\n\ndef b():\n    pass\n",
        ),
        ("def f():\n    pass\n", "def f():\n    pass\n"),
        ("x = 1   \n\n\n", "x = 1\n"),
    ],
    ids=[
        "top_level_function_gets_2",
        "init_gets_1_other_methods_get_2",
        "blank_lines_go_above_decorators",
        "larger_gap_is_kept",
        "fmt_off_block_is_untouched",
        "definition_on_first_line_gets_none",
        "trailing_whitespace_is_trimmed",
    ],
)
def test_format_sets_blank_lines_above_definitions(source, expected):
    assert custom_formatter.PythonFormatter(source).format() == expected
