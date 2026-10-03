class DomainError(Exception):
    """Base exception for Manasuke domain errors."""


class DomainValidationError(DomainError):
    """Raised when domain data violates an invariant."""


class InvalidTimeRangeError(DomainValidationError):
    """Raised when a time interval is invalid."""


class InvalidMaterialRangeError(DomainValidationError):
    """Raised when a material range is invalid."""