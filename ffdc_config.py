"""Small, dependency-free helpers for parsing service configuration.

Keeping environment parsing here gives the HTTP application one place to
define defaults and makes configuration behavior easy to test without
importing the 14k-line server module.
"""

import os
from pathlib import Path


def env_int(name, default, *, minimum=None, maximum=None):
    """Return an integer environment value, falling back to *default*.

    A malformed deployment variable should not prevent the service from
    starting. Bounds are applied after parsing so queue and worker settings
    cannot become negative or unreasonably large by accident.
    """
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None and str(raw).strip() else int(default)
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def env_float(name, default, *, minimum=None, maximum=None):
    """Return a bounded floating-point environment value."""
    raw = os.environ.get(name)
    try:
        value = float(raw) if raw is not None and str(raw).strip() else float(default)
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


def env_path(name, default):
    """Return a non-empty environment path or the supplied default."""
    raw = os.environ.get(name)
    return Path(str(raw).strip()) if raw and str(raw).strip() else Path(default)


def env_url(name, default):
    """Return a trimmed URL without a trailing slash."""
    raw = os.environ.get(name, default)
    return str(raw or default).strip().rstrip("/")
