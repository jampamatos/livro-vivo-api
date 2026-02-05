from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, PostViewSet, CommentViewSet

router = DefaultRouter()
router.register(r'community/categories', CategoryViewSet, basename='community-category')
router.register(r'community/posts', PostViewSet, basename='community-post')
router.register(r'community/comments', CommentViewSet, basename='community-comment')

urlpatterns = [
    path('', include(router.urls)),
]