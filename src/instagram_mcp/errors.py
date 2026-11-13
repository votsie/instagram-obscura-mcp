"""Errors with no secret-bearing transport diagnostics."""


class InstagramMcpError(Exception):
    pass


class ProtocolError(InstagramMcpError):
    pass


class LoginRequired(InstagramMcpError):
    pass
