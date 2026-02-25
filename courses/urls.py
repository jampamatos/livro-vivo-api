from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .views import CourseAssetViewSet, CoursePostViewSet, LiveEventViewSet

router = DefaultRouter()
router.register(r'courses/posts', CoursePostViewSet, basename='course-post')
router.register(r'courses/assets', CourseAssetViewSet, basename='course-asset')
router.register(r'courses/lives', LiveEventViewSet, basename='live-event')

urlpatterns = [
    path('', include(router.urls)),
]
