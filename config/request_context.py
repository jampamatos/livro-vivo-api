from __future__ import annotations

from contextvars import ContextVar, Token


_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_request_method: ContextVar[str] = ContextVar("request_method", default="-")
_request_path: ContextVar[str] = ContextVar("request_path", default="-")
_request_user_id: ContextVar[str] = ContextVar("request_user_id", default="-")


def set_request_context(
    *,
    request_id: str,
    method: str | None = None,
    path: str | None = None,
    user_id: str | int | None = None,
) -> dict[str, Token]:
    return {
        "request_id": _request_id.set(request_id or "-"),
        "request_method": _request_method.set(method or "-"),
        "request_path": _request_path.set(path or "-"),
        "request_user_id": _request_user_id.set(str(user_id) if user_id is not None else "-"),
    }


def update_request_user_id(user_id: str | int | None):
    _request_user_id.set(str(user_id) if user_id is not None else "-")


def reset_request_context(tokens: dict[str, Token] | None):
    if not tokens:
        return
    for key, token in tokens.items():
        if key == "request_id":
            _request_id.reset(token)
        elif key == "request_method":
            _request_method.reset(token)
        elif key == "request_path":
            _request_path.reset(token)
        elif key == "request_user_id":
            _request_user_id.reset(token)


def get_request_context() -> dict[str, str]:
    return {
        "request_id": _request_id.get(),
        "request_method": _request_method.get(),
        "request_path": _request_path.get(),
        "request_user_id": _request_user_id.get(),
    }
