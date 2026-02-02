import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    """Endpoint simples de healthcheck."""
    return JsonResponse({
        'status': 'ok',
        'version': os.getenv('APP_VERSION', 'dev'),
    })

urlpatterns = [
    path('health/', health),
    path('admin/', admin.site.urls),

    path('', include('accounts.urls')),
    path('', include('annotations.urls')),
    path('', include('library.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
