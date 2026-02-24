from django.contrib import admin

from .models import Annotation


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'book_version',
        'chapter',
        'start_offset',
        'end_offset',
        'color',
        'updated_at',
    )
    list_filter = ('color', 'book_version', 'chapter')
    search_fields = ('note', 'excerpt', 'chapter__title', 'chapter__slug')
