from __future__ import annotations


class DirectSourceError(RuntimeError):
    """Raised when a non-PDF source cannot be fetched or parsed."""
