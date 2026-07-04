"""Typed error hierarchy for the datavibes SDK.

One home for every failure mode so callers (CLI, library users, tests) can
catch precise, well-named exceptions instead of bare ``Exception``.
"""


class DatavibesError(Exception):
    """Base class for every error raised by the SDK."""


class ConfigError(DatavibesError):
    """A ``dataset.yaml`` is missing, malformed, or violates an invariant."""


class UnknownStrategyError(DatavibesError):
    """A registry lookup failed; the message names the missing key."""


class DuplicateStrategyError(DatavibesError):
    """Two strategies tried to register under the same name."""


class SchemaValidationError(DatavibesError):
    """A processed row set does not conform to the declared schema."""


class SourceFetchError(DatavibesError):
    """A source could not fetch its records (network / decode failure)."""
