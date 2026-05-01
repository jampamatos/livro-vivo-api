from __future__ import annotations

from prometheus_client import Counter, Histogram


MAX_LABEL_VALUE_LENGTH = 80
UNKNOWN_LABEL_VALUE = 'unknown'

REQUESTS_TOTAL = Counter(
    'livro_vivo_api_http_requests_total',
    'Total de respostas HTTP emitidas pela API.',
    ['method', 'route', 'status'],
)

REQUEST_DURATION_SECONDS = Histogram(
    'livro_vivo_api_http_request_duration_seconds',
    'Duracao das requests HTTP da API em segundos.',
    ['method', 'route'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

DOMAIN_EVENTS_TOTAL = Counter(
    'livro_vivo_api_domain_events_total',
    'Total de eventos criticos de dominio emitidos pela API.',
    ['event', 'result', 'source'],
)


def _normalize_label_value(value, *, default: str = UNKNOWN_LABEL_VALUE) -> str:
    label = str(value or '').strip().lower()
    if not label:
        return default
    return label[:MAX_LABEL_VALUE_LENGTH]


def build_route_label(request) -> str:
    resolver_match = getattr(request, 'resolver_match', None)
    route = (getattr(resolver_match, 'route', '') or '').strip()
    if route:
        return '/' + route.lstrip('/')
    return 'unmatched'


def should_record_request_metrics(request) -> bool:
    return getattr(request, 'path', '') != '/metrics/'


def record_request_metrics(*, request, status_code: int, duration_seconds: float) -> None:
    if not should_record_request_metrics(request):
        return

    method = getattr(request, 'method', 'UNKNOWN') or 'UNKNOWN'
    route = build_route_label(request)
    status = str(status_code)

    REQUESTS_TOTAL.labels(method=method, route=route, status=status).inc()
    REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(duration_seconds)


def record_domain_event(*, event: str, result: str = 'success', source: str = 'api') -> None:
    DOMAIN_EVENTS_TOTAL.labels(
        event=_normalize_label_value(event),
        result=_normalize_label_value(result),
        source=_normalize_label_value(source),
    ).inc()
