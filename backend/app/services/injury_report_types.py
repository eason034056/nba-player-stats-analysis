"""Tagged results for one injury-report fetch.

``tag`` is ``stored``, ``missing``, ``blocked``, or ``error``. Callers
match on ``tag`` instead of catching an exception or checking a bool.
A missing file (HTTP 403) is not an error. A block pauses the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Stored:
    """A PDF is on disk. ``from_cache`` is true when this run did not call the network."""

    tag: Literal["stored"]
    url: str
    path: Path
    sidecar_path: Path
    sha256: str
    fetched_at: str
    last_modified_raw: str | None
    last_modified_utc: str | None
    content_length: int
    from_cache: bool


@dataclass(frozen=True)
class Missing:
    """The CDN returned 403. The file is recorded as missing and is not retried in this run."""

    tag: Literal["missing"]
    url: str
    status: int
    checked_at: str
    sidecar_path: Path
    from_cache: bool


@dataclass(frozen=True)
class Blocked:
    """The response looks like a block. The run pauses. Nothing after this URL is requested."""

    tag: Literal["blocked"]
    url: str
    reason: str


@dataclass(frozen=True)
class Failed:
    """A timeout, 429, or 5xx that ended in a pause. ``kind`` is ``timeout`` or ``http``."""

    tag: Literal["error"]
    url: str
    kind: str
    status: int | None


FetchResult = Stored | Missing | Blocked | Failed


@dataclass(frozen=True)
class RunReport:
    """What one fetch run did.

    ``paused`` is true when a block or a streak of retryable failures
    stopped the run early. ``requests_made`` counts HTTP calls, including
    retries. A cache hit is not a request.
    """

    results: tuple[FetchResult, ...]
    paused: bool
    requests_made: int
