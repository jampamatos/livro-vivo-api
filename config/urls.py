from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_GET


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
    except Exception as exc:
        checks['database'] = f'error: {exc.__class__.__name__}'
        http_status = 503

    try:
        cache_key = 'healthcheck:readyz'
        cache.set(cache_key, 'ok', timeout=10)
        checks['cache'] = 'ok' if cache.get(cache_key) == 'ok' else 'error'
        if checks['cache'] != 'ok':
            http_status = 503
    except Exception as exc:
        checks['cache'] = f'error: {exc.__class__.__name__}'
        http_status = 503

    return JsonResponse(
        {
            'status': 'ok' if http_status == 200 else 'degraded',
            'checks': checks,
            'version': settings.APP_VERSION,
        },
        status=http_status,
    )

urlpatterns = [
    path('health/', health),
    path('healthz/', health),
    path('readyz/', readiness),
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
