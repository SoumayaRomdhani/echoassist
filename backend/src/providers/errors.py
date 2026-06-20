"""Provider-layer exceptions."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for any provider-layer failure."""


class ProviderConfigError(ProviderError):
    """Raised when a provider is selected but mis-configured (e.g. missing API key)."""
