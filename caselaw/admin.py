from django.contrib import admin

from .models import CaseLaw

@admin.register(CaseLaw)
class CaseLawAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'court',
        'case_number',
        'decision_date',
        'relevance',
        'updated_at',
    )
    list_filter = (
        'court',
        'decision_date',
        'relevance',
    )
    search_fields = (
        'court',
        'case_number',
        'summary',
    )
    ordering = ('-decision_date', '-updated_at')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': (
                'court',
                'case_number',
                'decision_date',
                'url',
                'relevance',
                'tags',
            )
        }),
        ('Conteúdo', {
            'fields': ('summary',),
        }),
        ('Metadados', {
            'fields': ('created_at', 'updated_at'),
        }),
    )