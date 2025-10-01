# Python Style Guidelines

This document defines the coding style guidelines for Python code in this repository. These guidelines should be followed to maintain consistency and readability across the codebase.

## Core Style Guidelines

### 1. Comments Before Logical Blocks

Add descriptive comments above logical blocks when the purpose needs clarification or when explaining complex operations and error handling.

### 2. Blank Lines Before Comments (Except After Docstrings)

Include a blank line before each comment that is before a logical block, except when the comment directly follows a function's docstring.

### 3. Blank Lines After Logical Sections Complete

After a logical block completes (end of loops, after appending to lists, etc.), include a blank line before the next comment/section. This helps improve readability of the code.

### 4. Comments Describe "What" Not "How"

Comments should describe what the code accomplishes rather than implementation details.

### 5. Spacing Within Control Structures

Inside try/except blocks and if/else statements, include a blank line after each branch's code block completes.

### 6. Comments for Primary and Fallback Logic

Both the main execution path and fallback/error handling should have descriptive comments when their purpose isn't immediately self-evident.

### 7. Comments for Final Actions

Simple operations at the end of functions should have descriptive comments when the purpose needs clarification.

### 8. Two Blank Lines Between Functions/Methods/Classes

Two blank lines before all function/method/class definitions, whether top-level or nested.

### 9. Compress long comments, don't truncate

When comments exceed the 115-character line limit, compress them by removing unnecessary articles and prepositions while preserving full meaning, rather than truncating important information.

### 10. Code clarity not guideline following perfection

The code is more important than the style guidelines

## Integration with Code Formatting Tools

These style guidelines work in conjunction with automated formatting tools:

- **Ruff**: Handles basic formatting, import sorting, and linting
- **Custom formatter**: Applies additional spacing rules via `scripts/ruff_check_format_assets.sh`

Always run the formatting script before committing:

```bash
./scripts/ruff_check_format_assets.sh
```
