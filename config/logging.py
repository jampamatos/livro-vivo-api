import json
import logging
from datetime import datetime, timezone

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
        if request_id:
            payload["request_id"] = request_id

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in LOG_RESERVED_ATTRS and not key.startswith("_")
        }
        if extras:
            payload["extra"] = {key: _json_safe(value) for key, value in extras.items()}

        return json.dumps(payload, ensure_ascii=True)


def build_logging_config(*, debug: bool):
    root_level = "DEBUG" if debug else "INFO"
    django_level = "INFO" if debug else "WARNING"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "config.logging.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": root_level,
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": django_level,
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
            "livro_vivo": {
                "handlers": ["console"],
                "level": root_level,
                "propagate": False,
            },
        },
    }
