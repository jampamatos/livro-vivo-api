from django.db.models import F, Max
from django.db.models.functions import Coalesce

from rest_framework import filters
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.viewsets import ModelViewSet

from .models import Category, Post, Comment, Report
from .permissions import IsOwnerOrStaff, IsStaffOrReadOnlyAuthed
from .serializers import CategorySerializer, PostSerializer, CommentSerializer, ReportSerializer

class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsStaffOrReadOnlyAuthed]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'slug', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

class PostViewSet(ModelViewSet):
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'body']
    ordering_fields = ['created_at', 'updated_at', 'last_activity']
    ordering = ['-last_activity', '-created_at']

    def get_queryset(self):
        qs = (
            Post.objects.select_related('author', 'category')
            .annotate(last_activity=Coalesce(Max('comments__created_at'), F('created_at')))
            .all()
        )
        category_id = self.request.query_params.get('category')
        if category_id:
            qs = qs.filter(category_id=category_id)
        return qs
    
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
    
class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]
    filter_backends =  [filters.OrderingFilter]
    ordering_fields = ['created_at']
    ordering = ['created_at']

    def get_queryset(self):
        qs = Comment.objects.select_related('author', 'post').all()
        post_id = self.request.query_params.get('post')
        if post_id:
            qs = qs.filter(post_id=post_id)
        return qs
    
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

class ReportViewSet(ModelViewSet):
    serializer_class = ReportSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["reason", "reporter__username", "post__title", "comment__body"]
    ordering_fields = ["created_at", "updated_at", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Report.objects.select_related("reporter", "post", "comment").all()

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated()]
        # list/retrieve/update/delete só staff (via IsAdminUser)
        return [IsAuthenticated(), IsAdminUser()]

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)
