"""The three accounting assumptions, shared by the CLI and the report.

The wording is the contract for a run that has no sportsbook history.
When an odds file is loaded, the report still prints these sentences and
then says which picks they no longer cover.
"""

from __future__ import annotations

ASSUMPTION_A = (
    "The repo has no historical sportsbook lines, so hit rates are measured "
    "against a proxy line. The default proxy, MED20, is the x.5 line that "
    "splits the player's last 20 games closest to 50/50. The L10 alternative "
    "is also supported."
)
ASSUMPTION_B = "ROI assumes -110 on every bet."
ASSUMPTION_C = "CLV is not measured."


def assumption_lines() -> list[str]:
    """The three assumptions, already labeled (a), (b), and (c)."""
    return [
        f"(a) {ASSUMPTION_A}",
        f"(b) {ASSUMPTION_B}",
        f"(c) {ASSUMPTION_C}",
    ]
