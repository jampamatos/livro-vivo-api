from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import include, path
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import admin_navigation  # noqa: F401
import logging


logger = logging.getLogger("livro_vivo.api")


@require_GET
def health(_request):
    """Healthcheck simples de vida."""
    return JsonResponse(
        {
            'status': 'ok',
            'app': 'livro-vivo-api',
            'version': settings.APP_VERSION,
        }
    )


@require_GET
def readiness(_request):
    """Readiness básico para deploy/observabilidade."""
    checks = {}
    http_status = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        checks['database'] = 'ok'
    except Exception:
        checks['database'] = 'error'
        http_status = 503

    try:
        cache_key = 'healthcheck:readyz'
        cache.set(cache_key, 'ok', timeout=10)
        checks['cache'] = 'ok' if cache.get(cache_key) == 'ok' else 'error'
        if checks['cache'] != 'ok':
            http_status = 503
    except Exception:
        checks['cache'] = 'error'
        http_status = 503

    if http_status != 200:
        logger.warning(
            'api_readiness_degraded',
            extra={'checks': checks},
        )

    return JsonResponse(
        {
            'status': 'ok' if http_status == 200 else 'degraded',
            'app': 'livro-vivo-api',
            'checks': checks,
            'version': settings.APP_VERSION,
        },
        status=http_status,
    )


@require_GET
def metrics(request):
    """Endpoint Prometheus para scrape interno do Alloy."""
    if not settings.METRICS_ENABLED:
        raise Http404()

    configured_token = settings.METRICS_BEARER_TOKEN
    if configured_token:
        authorization = (request.headers.get('Authorization') or '').strip()
        expected = f'Bearer {configured_token}'
        if not constant_time_compare(authorization, expected):
            return HttpResponse(status=403)

    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)

urlpatterns = [
    path('health/', health),
    path('healthz/', health),
    path('readyz/', readiness),
    path('metrics/', metrics),
    path('admin/', admin.site.urls),

    path('', include('accounts.urls')),
    path('', include('annotations.urls')),
    path('', include('caselaw.urls')),
    path('', include('community.urls')),
    path('', include('courses.urls')),
    path('', include('library.urls')),
    path('', include('search.urls')),
    path('', include('templates_bank.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
