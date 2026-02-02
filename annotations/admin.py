from django.contrib import admin

from .models import Annotation


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'book_version', 'page_number', 'color', 'updated_at')
    list_filter = ('color', 'book_version')
    search_fields = ('note',)
