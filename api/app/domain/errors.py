"""Domain errors. The API layer maps each class to one HTTP status (see app/api/errors.py)."""


class DomainError(Exception):
    """Base class of every error that is part of the API contract."""


class NotFoundError(DomainError):
    """A referenced net or job does not exist."""


class InvalidRequestError(DomainError):
    """The request is well-formed JSON but cannot be honoured (e.g. unknown engine)."""


class InvalidNetError(InvalidRequestError):
    """A net is not valid; ``location`` points at the fault (a JSON pointer, or a line for PNML)."""

    def __init__(self, message: str, *, location: str | None = None) -> None:  # noqa: PLR0917 - exception message
        """Create the error with its message and, when known, where the fault is."""
        super().__init__(message if location is None else f"{message} (at {location})")
        self.reason = message
        self.location = location


class PayloadTooLargeError(DomainError):
    """The uploaded payload exceeds the configured limit."""


class PnmlError(InvalidNetError):
    """The PNML document is not valid XML or does not describe a usable net."""


class InvalidFormulaError(InvalidRequestError):
    """A formula cannot be used on the net; ``location`` is a JSON pointer into the request."""

    def __init__(self, message: str, *, location: str) -> None:  # noqa: PLR0917 - exception message
        """Create the error with its message and the pointer to the fault."""
        super().__init__(f"{message} (at {location})")
        self.reason = message
        self.location = location


class UnsupportedMediaTypeError(DomainError):
    """The request body has a media type the endpoint does not accept (HTTP 415)."""


class NotAcceptableError(DomainError):
    """The endpoint cannot produce any of the media types the client accepts (HTTP 406)."""


class FormulaSyntaxError(InvalidRequestError):
    """Formula text cannot be parsed; ``position`` is the offset of the fault in the text."""

    def __init__(self, message: str, *, position: int) -> None:  # noqa: PLR0917 - exception message
        """Create the error with its message and the offset of the fault."""
        super().__init__(f"{message} (at offset {position})")
        self.reason = message
        self.position = position


class ConflictError(DomainError):
    """The request conflicts with the current state of a resource (HTTP 409)."""
