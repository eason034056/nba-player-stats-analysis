#!/usr/bin/env python3
"""
visualize.py – Export a Mermaid diagram of the agent graph.

Usage:
  python visualize.py             # print to stdout
  python visualize.py -o graph.md # write to file
"""

import os
import sys

_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_AGENTS_DIR, "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from graph import export_mermaid


def main():
    mermaid = export_mermaid()

    if len(sys.argv) > 2 and sys.argv[1] == "-o":
        out = sys.argv[2]
        with open(out, "w") as f:
            f.write("```mermaid\n")
            f.write(mermaid)
            f.write("\n```\n")
        print(f"Written to {out}")
    else:
        print(mermaid)


if __name__ == "__main__":
    main()
