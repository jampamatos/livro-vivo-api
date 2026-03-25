from __future__ import annotations

import logging
import time
import uuid

from .request_context import reset_request_context, set_request_context, update_request_user_id


logger = logging.getLogger("livro_vivo.api")


class RequestContextMiddleware:
    """
    Injeta request_id no ciclo da request e registra falhas 4xx/5xx com contexto mínimo.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (request.headers.get("X-Request-ID") or uuid.uuid4().hex).strip() or uuid.uuid4().hex
        request.request_id = request_id
        started_at = time.monotonic()
        tokens = set_request_context(
            request_id=request_id,
            method=request.method,
            path=request.get_full_path(),
        )

        response = None
        try:
            response = self.get_response(request)
        except Exception:
            user = getattr(request, "user", None)
            user_id = getattr(user, "id", None) if user is not None and getattr(user, "is_authenticated", False) else None
            update_request_user_id(user_id)
            duration_ms = int((time.monotonic() - started_at) * 1000)
            logger.exception(
                "api_request_unhandled_exception",
                extra={
                    "status_code": 500,
                    "duration_ms": duration_ms,
                },
            )
            raise
        finally:
            if response is None:
                reset_request_context(tokens)

        duration_ms = int((time.monotonic() - started_at) * 1000)
        user = getattr(request, "user", None)
        user_id = getattr(user, "id", None) if user is not None and getattr(user, "is_authenticated", False) else None
        update_request_user_id(user_id)
        response["X-Request-ID"] = request_id
        response["X-Response-Time-ms"] = str(duration_ms)

        if response.status_code >= 500:
            logger.error(
                "api_request_failed",
                extra={
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        elif response.status_code >= 400:
            logger.warning(
                "api_request_client_error",
                extra={
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        reset_request_context(tokens)
        return response
