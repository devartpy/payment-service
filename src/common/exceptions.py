"""Общий контракт ожидаемых ошибок приложения."""

from typing import Any


class ApplicationException(Exception):
    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 400,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.meta = meta or {}
        super().__init__(message)
