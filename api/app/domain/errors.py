"""Domain errors. The API layer maps each class to one HTTP status (see app/api/errors.py)."""


class DomainError(Exception):
    """Base class of every error that is part of the API contract."""


class NotFoundError(DomainError):
    """A referenced net or job does not exist."""


class InvalidRequestError(DomainError):
    """The request is well-formed JSON but cannot be honoured (e.g. unknown engine)."""


class PayloadTooLargeError(DomainError):
    """The uploaded payload exceeds the configured limit."""


class PnmlError(InvalidRequestError):
    """The PNML document is not valid XML or does not describe a usable net."""
