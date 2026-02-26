from __future__ import annotations


class ArxivRateLimitError(Exception):
    """arXiv returned 429 or cooldown is active."""


class ArxivClientValidationError(ValueError):
    """arXiv client inputs are invalid."""


class ArxivParseError(ValueError):
    """arXiv API payload could not be parsed."""
