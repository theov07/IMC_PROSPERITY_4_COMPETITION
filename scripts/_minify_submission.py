"""Minify a submission file by stripping docstrings and comments.

Preserves all executable code, reduces file size significantly.
"""
from __future__ import annotations
import ast
import sys
from pathlib import Path


def strip_docstrings_and_comments(source: str) -> str:
    """Remove all docstrings (module, class, function) and strip comment-only lines."""
    tree = ast.parse(source)

    # Collect (start_line, end_line) of every docstring (1-indexed, inclusive)
    docstring_lines: set[int] = set()

    def _collect_docs(node):
        # Check if first body statement is a string constant (docstring)
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            ds = body[0]
            for ln in range(ds.lineno, ds.end_lineno + 1):
                docstring_lines.add(ln)

    # Module-level
    _collect_docs(tree)
    # All classes and functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _collect_docs(node)

    src_lines = source.splitlines(keepends=True)
    out_lines = []
    prev_blank = False
    for i, line in enumerate(src_lines, 1):
        if i in docstring_lines:
            continue
        stripped = line.strip()
        # Remove pure comment lines
        if stripped.startswith("#"):
            continue
        # Strip ALL blank lines (aggressive)
        if stripped == "":
            continue
        # Remove trailing whitespace
        out_lines.append(line.rstrip() + "\n")
    return "".join(out_lines)


def main():
    if len(sys.argv) != 2:
        print("Usage: python _minify_submission.py <path_to_submission.py>")
        sys.exit(1)
    p = Path(sys.argv[1])
    src = p.read_text(encoding="utf-8")
    before = len(src.encode("utf-8"))
    minified = strip_docstrings_and_comments(src)
    # Validate: must still parse
    ast.parse(minified)
    after = len(minified.encode("utf-8"))
    out = p.with_stem(p.stem + "_minified")
    out.write_text(minified, encoding="utf-8")
    print(f"{p.name}: {before:,} -> {after:,} bytes ({100*(before-after)/before:.1f}% reduction)")
    print(f"Written: {out}")


if __name__ == "__main__":
    main()
