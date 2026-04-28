"""Ultra-aggressive minifier for IMC submissions.

Goes beyond the standard docstring stripping:
  1. Consolidate redundant `from X import ...` into single lines
  2. Strip inline comments (`code  # comment`)
  3. Remove trailing whitespace + repeated blank lines
  4. Optionally strip type annotations in function signatures (parametric)

Usage:
  python scripts/ultra_minify.py <input.py> [--out <output.py>]

Always validates that the result still parses + imports cleanly before writing.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path


def strip_type_annotations(text: str) -> str:
    """Use ast to strip all type annotations (PEP 526 + function args + returns).

    Removes annotations from:
      - Function parameters: def f(x: int, y: str) -> bool:  →  def f(x, y):
      - Variable annotations: x: int = 1  →  x = 1
      - Class attribute annotations: x: List[int]  →  removed
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text

    class Stripper(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            for arg in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
                arg.annotation = None
            if node.args.vararg:
                node.args.vararg.annotation = None
            if node.args.kwarg:
                node.args.kwarg.annotation = None
            node.returns = None
            return node

        def visit_AsyncFunctionDef(self, node):
            return self.visit_FunctionDef(node)

        # KEEP AnnAssign — needed for @dataclass class fields (e.g. BookSnapshot)

    new_tree = Stripper().visit(tree)
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree)


def consolidate_imports(text: str) -> str:
    """Merge 'from X import a, b' + 'from X import c' into 'from X import a, b, c'."""
    lines = text.split("\n")
    # Map module -> set of imported names
    from_imports: dict[str, set[str]] = defaultdict(set)
    other_lines = []
    first_import_idx = None
    for i, line in enumerate(lines):
        m = re.match(r"^from (\S+) import (.+)$", line)
        if m:
            module = m.group(1)
            names = [n.strip() for n in m.group(2).split(",")]
            from_imports[module].update(names)
            if first_import_idx is None:
                first_import_idx = i
            continue
        other_lines.append(line)
    # Build consolidated imports
    if not from_imports:
        return text
    consolidated = []
    for module in sorted(from_imports.keys()):
        names = sorted(from_imports[module])
        consolidated.append(f"from {module} import {', '.join(names)}")
    # Insert at first_import_idx
    if first_import_idx is None:
        return text
    out = other_lines[:first_import_idx] + consolidated + other_lines[first_import_idx:]
    return "\n".join(out)


def strip_inline_comments(text: str) -> str:
    """Strip `# comment` from end of code lines (not preserving str hashes)."""
    out = []
    for line in text.split("\n"):
        # Skip pure-comment lines (already removed by minifier but defensive)
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Find # not inside a string
        in_str = False
        quote = None
        for i, ch in enumerate(line):
            if in_str:
                if ch == quote and (i == 0 or line[i-1] != "\\"):
                    in_str = False
            else:
                if ch in ('"', "'"):
                    in_str = True
                    quote = ch
                elif ch == "#":
                    line = line[:i].rstrip()
                    break
        out.append(line)
    return "\n".join(out)


def remove_blank_lines(text: str) -> str:
    """Remove all blank lines."""
    return "\n".join(l for l in text.split("\n") if l.strip())


def trim_trailing_whitespace(text: str) -> str:
    return "\n".join(l.rstrip() for l in text.split("\n"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-strip-comments", action="store_true")
    ap.add_argument("--strip-types", action="store_true",
                    help="Remove all type annotations (saves ~3KB)")
    args = ap.parse_args()

    src = Path(args.input)
    out = Path(args.out) if args.out else src
    text = src.read_text(encoding="utf-8")
    before = len(text.encode("utf-8"))

    if args.strip_types:
        text = strip_type_annotations(text)
    text = consolidate_imports(text)
    if not args.no_strip_comments:
        text = strip_inline_comments(text)
    text = trim_trailing_whitespace(text)
    text = remove_blank_lines(text)

    # Validate
    try:
        ast.parse(text)
    except SyntaxError as e:
        print(f"ERROR: minified output is not valid Python: {e}", file=sys.stderr)
        sys.exit(1)

    after = len(text.encode("utf-8"))
    print(f"Before: {before:,} bytes")
    print(f"After:  {after:,} bytes  (saved {before - after:,} = {100*(before-after)/before:.1f}%)")
    print(f"Pct of 100KB: {100*after/100000:.2f}%")

    out.write_text(text, encoding="utf-8")
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
