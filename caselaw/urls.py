from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .views import CaseLawViewSet

router = DefaultRouter()
router.register(r'caselaw', CaseLawViewSet, basename='caselaw')

urlpatterns = [
    path('',include(router.urls)),
]