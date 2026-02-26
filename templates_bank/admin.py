from django.contrib import admin

from .models import PublicationStatus, TemplatePiece


@admin.register(TemplatePiece)
class TemplatePieceAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'template_code',
        'version',
        'category',
        'status',
        'file_name',
        'updated_at',
    )
    list_filter = ('status', 'category', 'updated_at', 'published_at')
    search_fields = ('title', 'template_code', 'version', 'description', 'changelog', 'file_name')
    ordering = ('template_code', '-created_at', '-updated_at')
    readonly_fields = ('created_at', 'updated_at')
    prepopulated_fields = {'slug': ('title',)}
    fields = (
        'title',
        'slug',
        'template_code',
        'version',
        'category',
        'status',
        'published_at',
        'description',
        'changelog',
        'tags',
        'file_url',
        'file_name',
        'file_mime_type',
        'file_size_bytes',
        'file_sha256',
        'created_at',
        'updated_at',
    )
    actions = ['mark_published', 'mark_archived']

    @admin.action(description='Marcar selecionadas como publicadas')
    def mark_published(self, request, queryset):
        queryset.update(status=PublicationStatus.PUBLISHED)

    @admin.action(description='Marcar selecionadas como arquivadas')
    def mark_archived(self, request, queryset):
        queryset.update(status=PublicationStatus.ARCHIVED)
