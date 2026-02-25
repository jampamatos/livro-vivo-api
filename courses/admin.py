from django.contrib import admin

from .models import CourseAsset, CoursePost, LiveEvent


@admin.register(CoursePost)
class CoursePostAdmin(admin.ModelAdmin):
    list_display = ('title', 'post_type', 'status', 'published_at', 'updated_at')
    list_filter = ('status', 'post_type', 'published_at', 'updated_at')
    search_fields = ('title', 'author_name', 'excerpt', 'content_rich')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('-published_at', '-updated_at', '-created_at')


@admin.register(CourseAsset)
class CourseAssetAdmin(admin.ModelAdmin):
    list_display = ('title', 'asset_type', 'status', 'post', 'published_at', 'updated_at')
    list_filter = ('status', 'asset_type', 'published_at', 'updated_at')
    search_fields = ('title', 'description')
    ordering = ('-published_at', '-updated_at', '-created_at')


@admin.register(LiveEvent)
class LiveEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'event_type', 'status', 'starts_at', 'updated_at')
    list_filter = ('status', 'event_type', 'starts_at', 'updated_at')
    search_fields = ('title', 'description')
    ordering = ('-starts_at', '-updated_at', '-created_at')

# Register your models here.
