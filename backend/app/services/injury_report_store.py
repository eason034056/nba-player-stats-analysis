"""Local files for official injury-report PDFs.

Each success is a PDF plus a JSON sidecar in the same directory. A 403
is a sidecar only. The directory is gitignored. This module does not
upload to S3 and does not delete a PDF that was stored earlier.

Layout, under the root (``INJURY_PDF_DIR``, default ``/workspace/nba-injury-pdf``)::

    YYYY/MM/DD/Injury-Report_YYYY-MM-DD_HHPM.pdf
    YYYY/MM/DD/Injury-Report_YYYY-MM-DD_HHPM.pdf.json

The date in the path is the date in the filename, which is the Eastern
date of the report.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.services.injury_report_types import Missing, Stored

_NAME = re.compile(
    r"Injury-Report_\d{4}-\d{2}-\d{2}_\d{2}(?:_\d{2})?(?:AM|PM)\.pdf"
)


def utc_stamp(moment: datetime) -> str:
    """UTC timestamp with a ``Z`` suffix, to the second."""
    if moment.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename_from_url(url: str) -> str:
    """CDN object name. Refuses a URL whose last segment is not a report name."""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if _NAME.fullmatch(name) is None:
        raise ValueError(f"unexpected injury-report name: {name}")
    return name


class LocalInjuryReportStore:
    """Read and write one cache directory.

    ``root`` is created on the first write. ``get`` returns None when
    nothing has been recorded. ``had_success`` is true only when a PDF
    and a status-200 sidecar are both present.

    Use ``put_pdf`` after a 200 whose body starts with ``%PDF-``.
    Use ``put_missing`` after a 403 for a URL that was not stored before.
    Neither method deletes an existing PDF.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def paths_for(self, url: str) -> tuple[Path, Path]:
        """``(pdf_path, sidecar_path)`` for ``url``. The directories may not exist yet."""
        name = filename_from_url(url)
        # Injury-Report_YYYY-MM-DD_...
        year, month, day = name.split("_", 2)[1].split("-")
        directory = self.root / year / month / day
        pdf = directory / name
        return pdf, pdf.with_suffix(pdf.suffix + ".json")

    def _read_sidecar(self, url: str) -> dict[str, object] | None:
        _pdf, sidecar = self.paths_for(url)
        if not sidecar.is_file():
            return None
        loaded = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return None
        return loaded

    def had_success(self, url: str) -> bool:
        """True when this URL was stored as a PDF."""
        pdf, _sidecar = self.paths_for(url)
        body = self._read_sidecar(url)
        return body is not None and body.get("status") == 200 and pdf.is_file()

    def get(self, url: str) -> Stored | Missing | None:
        """The recorded result, or None if this URL has not been checked.

        A status-200 sidecar without the PDF is treated as absent so a
        half-written file is fetched again. ``from_cache`` is true.
        """
        pdf, sidecar = self.paths_for(url)
        body = self._read_sidecar(url)
        if body is None:
            return None
        status = body.get("status")
        if status == 403:
            checked = body.get("checked_at")
            if not isinstance(checked, str):
                return None
            return Missing(
                tag="missing",
                url=url,
                status=403,
                checked_at=checked,
                sidecar_path=sidecar,
                from_cache=True,
            )
        if status == 200 and pdf.is_file():
            raw = body.get("last_modified_raw")
            parsed = body.get("last_modified_utc")
            fetched = body.get("fetched_at")
            digest = body.get("sha256")
            length = body.get("content_length")
            if not isinstance(fetched, str) or not isinstance(digest, str):
                return None
            if not isinstance(length, int):
                return None
            return Stored(
                tag="stored",
                url=url,
                path=pdf,
                sidecar_path=sidecar,
                sha256=digest,
                fetched_at=fetched,
                last_modified_raw=raw if isinstance(raw, str) else None,
                last_modified_utc=parsed if isinstance(parsed, str) else None,
                content_length=length,
                from_cache=True,
            )
        return None

    def put_pdf(
        self,
        url: str,
        pdf_bytes: bytes,
        *,
        fetched_at: datetime,
        last_modified_raw: str | None,
        last_modified_utc: str | None,
    ) -> Stored:
        """Write the PDF, then the sidecar. A crash between the two leaves no 200 record."""
        pdf, sidecar = self.paths_for(url)
        pdf.parent.mkdir(parents=True, exist_ok=True)
        _replace(pdf, pdf_bytes)
        record = {
            "url": url,
            "status": 200,
            "last_modified_raw": last_modified_raw,
            "last_modified_utc": last_modified_utc,
            "fetched_at": utc_stamp(fetched_at),
            "content_length": len(pdf_bytes),
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        }
        _replace(sidecar, json.dumps(record, indent=2).encode("utf-8") + b"\n")
        stored = self.get(url)
        if not isinstance(stored, Stored):
            raise RuntimeError("stored pdf could not be read back")
        return Stored(
            tag="stored",
            url=stored.url,
            path=stored.path,
            sidecar_path=stored.sidecar_path,
            sha256=stored.sha256,
            fetched_at=stored.fetched_at,
            last_modified_raw=stored.last_modified_raw,
            last_modified_utc=stored.last_modified_utc,
            content_length=stored.content_length,
            from_cache=False,
        )

    def iter_stored(self) -> list[Stored]:
        """Every PDF this cache has stored, in path order.

        ``iter_stored`` reads ``*.pdf.json`` sidecars and returns the
        same ``Stored`` value ``get`` would return. A 403 sidecar, and
        a 200 sidecar whose PDF file is missing, are skipped. This
        method does not call the network and does not delete a file.

        Returns:
            Stored PDFs, oldest path first.
        """
        if not self.root.is_dir():
            return []
        found: list[Stored] = []
        for sidecar in sorted(self.root.rglob("*.pdf.json")):
            try:
                loaded = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(loaded, dict):
                continue
            url = loaded.get("url")
            if not isinstance(url, str):
                continue
            got = self.get(url)
            if isinstance(got, Stored):
                found.append(got)
        return found

    def put_missing(self, url: str, *, checked_at: datetime) -> Missing:
        """Record a 403. Does not create a PDF and does not delete one."""
        _pdf, sidecar = self.paths_for(url)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "url": url,
            "status": 403,
            "checked_at": utc_stamp(checked_at),
        }
        _replace(sidecar, json.dumps(record, indent=2).encode("utf-8") + b"\n")
        return Missing(
            tag="missing",
            url=url,
            status=403,
            checked_at=record["checked_at"],
            sidecar_path=sidecar,
            from_cache=False,
        )


def _replace(path: Path, data: bytes) -> None:
    """Write ``data`` to a sibling temp file, then rename it over ``path``."""
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, path)
