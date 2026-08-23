class DomainError(Exception):
    """Base class for typed product failures."""


class CapacityExhausted(DomainError):
    """The bounded active-study admission limit has been reached."""


class EntityNotFound(DomainError):
    """A referenced product entity does not exist."""


class InvalidTransition(DomainError):
    """A requested state transition violates the lifecycle contract."""


class AcceptedResultConflict(DomainError):
    """A different result was already accepted for the logical job."""
