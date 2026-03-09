from django.urls import path

from .views import GlobalSearchView


urlpatterns = [
    path('search/global/', GlobalSearchView.as_view(), name='global-search'),
]
