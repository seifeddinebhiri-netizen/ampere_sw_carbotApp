"""Domain errors.

This file is the whole point of the layering. Services raise THESE, never
HTTPException. Routers catch them and choose a status code.

Why it matters: a service that raises HTTPException can only ever be called from
HTTP. Keep it clean and the same service works from a CLI, a test, a background
worker, or a future gRPC layer -- unchanged.
"""


class DomainError(Exception):
    """Base for everything below, so a router can catch broadly if it wants."""


class EmailAlreadyRegistered(DomainError):
    pass


class InvalidCredentials(DomainError):
    pass


class InvalidToken(DomainError):
    """Missing, expired, tampered, or revoked."""


class NoVehicleForUser(DomainError):
    pass


class CarTimeout(DomainError):
    """The car did not answer in time.

    Read this carefully: it means WE DON'T KNOW whether the command executed.
    It does not mean failure. The router must not report it as one.
    """


class CarRejected(DomainError):
    """The car answered, and said no. Different from a timeout: here we know."""