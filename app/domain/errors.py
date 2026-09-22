class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **details):
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(message)


def require(condition, code: str, message: str, status: int = 409, **details):
    if not condition:
        raise DomainError(code, message, status, **details)
