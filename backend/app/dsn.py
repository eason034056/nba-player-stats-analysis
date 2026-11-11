"""Mask passwords in database URLs before they are printed or logged."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")
_KEYWORD_PASSWORD = re.compile(r"(?i)(\bpassword=)(\S+)")


def mask_database_url(url: str | None) -> str:
    """Replace the password in a database URL with ``***``.

    The scheme, username, host, port, path, and query stay in place, so an
    ``sslmode=verify-full&sslrootcert=...`` query is unchanged. A URL with no
    password is returned unchanged. ``None`` and ``""`` return ``""``.

    Args:
        url: A libpq or Redis URL, for example
            ``postgresql://user:secret@host:5432/db?sslmode=verify-full``.

    Returns:
        The same URL with the password replaced by ``***``.
    """
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme or parts.password is None:
        return _KEYWORD_PASSWORD.sub(r"\1***", url)

    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    username = quote(parts.username or "", safe="")
    netloc = f"{username}:***"
    if hostname:
        netloc = f"{netloc}@{hostname}"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redact_secrets(text: str | None, secrets: tuple[str, ...] = ()) -> str:
    """Mask URL passwords and known secret strings inside a log message.

    Args:
        text: Exception or log text. It may contain a full DSN.
        secrets: Extra secret values to replace. Passwords shorter than 4
            characters are ignored here so a one-character password cannot
            blank out the rest of the message. Those short passwords are still
            masked when they appear inside a URL.

    Returns:
        The text with passwords replaced by ``***``.
    """
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = ""
        while raw and raw[-1] in ".,);":
            suffix = raw[-1] + suffix
            raw = raw[:-1]
        return mask_database_url(raw) + suffix

    masked = _KEYWORD_PASSWORD.sub(r"\1***", _URL_IN_TEXT.sub(_replace, text))
    for secret in secrets:
        if secret and secret != "***" and len(secret) >= 4:
            masked = masked.replace(secret, "***")
    return masked
