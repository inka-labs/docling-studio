"""Run one of the Docling CLIs by its module, the same on every system (no reliance on the console
scripts' location or on PATH):

    python -m docling_studio.runcli docling.cli.main convert paper.pdf --to md
"""

import importlib
import sys

from .introspect import APPS


def main() -> None:
    module = sys.argv[1]
    if module not in APPS.values():
        sys.exit(f"Not a Docling CLI: {module}")
    program = next(p for p, m in APPS.items() if m == module)
    sys.argv = [program, *sys.argv[2:]]
    importlib.import_module(module).app()


if __name__ == "__main__":
    main()
