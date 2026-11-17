"""Backwards-compatible place resolver shim.

The real work now lives in `services.geocoder` because a request may need to
count how many API calls it made. Code that only needs one lookup (admin,
tests, scripts) can still call `resolve(text)` here.
"""
from .geocoder import Place, Resolver


def resolve(text: str) -> Place:
    return Resolver().resolve(text)
