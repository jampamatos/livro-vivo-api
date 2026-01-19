from django.contrib import admin
from .models import Book, BookVersion

@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'created_at', 'updated_at')
    search_fields = ('title',)
    list_filter = ('status',)

@admin.register(BookVersion)
class BookVersionAdmin(admin.ModelAdmin):
    list_display = ('id', 'book', 'version', 'status', 'published_at', 'created_at')
    search_fields = ('book__title', 'version')
    list_filter = ('status', 'book')