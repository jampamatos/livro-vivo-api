from django.contrib import admin
from django.db.models import Count, Q

from .models import Category, Post, Comment, Report

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "target", "reporter", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("reason", "reporter__email", "reporter__username", "post__title", "comment__body")
    ordering = ("-created_at",)

    def target(self, obj: Report):
        if obj.post_id:
            return f"Post #{obj.post_id} — {obj.post.title}"
        return f"Comment #{obj.comment_id} — Post #{obj.comment.post_id}"
    target.short_description = "Target"

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "category", "open_reports", "created_at")
    search_fields = ("title", "body", "author__email")
    list_filter = ("category", "created_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_open_reports=Count("reports", filter=Q(reports__status=Report.Status.OPEN)))

    def open_reports(self, obj: Post):
        return getattr(obj, "_open_reports", 0)
    open_reports.short_description = "Reports (open)"
    open_reports.admin_order_field = "_open_reports"

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "open_reports", "created_at")
    search_fields = ("body", "author__email")
    list_filter = ("created_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_open_reports=Count("reports", filter=Q(reports__status=Report.Status.OPEN)))

    def open_reports(self, obj: Comment):
        return getattr(obj, "_open_reports", 0)
    open_reports.short_description = "Reports (open)"
    open_reports.admin_order_field = "_open_reports"

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_at', 'updated_at')
    search_fields = ('name', 'slug')
