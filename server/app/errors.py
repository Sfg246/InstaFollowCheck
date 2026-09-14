from __future__ import annotations


class GatewayError(RuntimeError):
    """Normalized error returned by a FollowCheck data source."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 502,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after
