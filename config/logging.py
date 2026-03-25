import json
import logging
from datetime import datetime, timezone

from .request_context import get_request_context

LOG_RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "request_id",
    "request_method",
    "request_path",
    "request_user_id",
    "stack_info",
    "thread",
    "threadName",
}


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


class JsonFormatter(logging.Formatter):
    """Formatter simples de logs estruturados em JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        request_id = getattr(record, "request_id", None)
        if request_id and request_id != "-":
            payload["request_id"] = request_id

        request_method = getattr(record, "request_method", None)
        if request_method and request_method != "-":
            payload["request_method"] = request_method

        request_path = getattr(record, "request_path", None)
        if request_path and request_path != "-":
            payload["request_path"] = request_path

        request_user_id = getattr(record, "request_user_id", None)
        if request_user_id and request_user_id != "-":
            payload["request_user_id"] = request_user_id

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in LOG_RESERVED_ATTRS and not key.startswith("_")
        }
        if extras:
            payload["extra"] = {key: _json_safe(value) for key, value in extras.items()}

        return json.dumps(payload, ensure_ascii=True)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        record.request_id = context["request_id"]
        record.request_method = context["request_method"]
        record.request_path = context["request_path"]
        record.request_user_id = context["request_user_id"]
        return True


def _normalize_profile(value: str | None, *, debug: bool) -> str:
    profile = (value or '').strip().lower()
    if profile in {'dev', 'development', 'local'}:
        return 'dev'
    if profile in {'prod', 'production', 'stage', 'staging'}:
        return 'prod'
    return 'dev' if debug else 'prod'


def _normalize_level(value: str | None, *, default: str) -> str:
    allowed = {'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET'}
    normalized = (value or '').strip().upper()
    if normalized in allowed:
        return normalized
    return default


def build_logging_config(
    *,
    debug: bool,
    profile: str | None = None,
    root_level: str | None = None,
    django_level: str | None = None,
    include_request_logs: bool = True,
    structured: bool | None = None,
):
    resolved_profile = _normalize_profile(profile, debug=debug)

    default_root_level = 'DEBUG' if resolved_profile == 'dev' and debug else 'INFO'
    default_django_level = 'INFO' if resolved_profile == 'dev' else 'WARNING'

    resolved_root_level = _normalize_level(root_level, default=default_root_level)
    resolved_django_level = _normalize_level(django_level, default=default_django_level)

    request_level_default = 'INFO' if resolved_profile == 'dev' and include_request_logs else 'WARNING'
    resolved_request_level = _normalize_level(None, default=request_level_default)

    if structured is None:
        structured = resolved_profile == 'prod'

    formatter_name = 'json' if structured else 'console'

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "config.logging.RequestContextFilter",
            },
        },
        "formatters": {
            "console": {
                "format": "%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s",
            },
            "json": {
                "()": "config.logging.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": formatter_name,
                "filters": ["request_context"],
            },
        },
        "root": {
            "handlers": ["console"],
            "level": resolved_root_level,
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": resolved_django_level,
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console"],
                "level": "ERROR",
                "propagate": False,
            },
            "django.server": {
                "handlers": ["console"],
                "level": resolved_request_level,
                "propagate": False,
            },
            "livro_vivo": {
                "handlers": ["console"],
                "level": resolved_root_level,
                "propagate": False,
            },
        },
    }
