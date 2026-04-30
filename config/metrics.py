from __future__ import annotations

from prometheus_client import Counter, Histogram


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
