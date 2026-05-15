"""Path bootstrap for scripts/agents/tests/.

`agents.py` and its sibling modules (`state.py`, `scoring.py`, `tools/…`) are
loaded as top-level modules — not as a package — because that is how
`scripts/agents/cli.py` and the backend test suite already exercise them.
Putting `scripts/agents/` on sys.path here mirrors the convention in
backend/tests/test_agent_planner.py, so a single `import agents as
agent_module` from any test file in this directory just works.
"""

import os
import sys

_AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)
