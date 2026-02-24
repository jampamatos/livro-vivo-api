from django.contrib import admin

from .models import CaseLaw

@admin.register(CaseLaw)
class CaseLawAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'court',
        'case_number',
        'decision_date',
        'anchors_count',
        'updated_at',
    )
    list_filter = (
        'court',
        'decision_date',
    )
    search_fields = (
        'court',
        'case_number',
        'ementa_plain',
    )
    ordering = ('-decision_date', '-updated_at')
    readonly_fields = ('ementa_plain', 'created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': (
                'court',
                'case_number',
                'decision_date',
                'url',
                'anchors',
                'tags',
            )
        }),
        ('Conteúdo', {
            'fields': ('ementa_rich', 'ementa_plain'),
        }),
        ('Metadados', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def anchors_count(self, obj):
        anchors = obj.anchors if isinstance(obj.anchors, list) else []
        return len(anchors)

    anchors_count.short_description = 'Anchors'
