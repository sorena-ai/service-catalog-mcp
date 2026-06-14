class ClaudeCLIError(Exception):
    pass


class InsufficientBalanceError(ClaudeCLIError):
    pass


class APIError(ClaudeCLIError):
    pass
