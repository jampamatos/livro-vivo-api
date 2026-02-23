from django.contrib import admin

from .models import Book, BookChapter, BookVersion, PageText


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'created_at', 'updated_at')
    search_fields = ('title',)
    list_filter = ('status',)


class BookChapterInline(admin.StackedInline):
    model = BookChapter
    extra = 0
    ordering = ('order', 'id')
    fields = ('order', 'title', 'slug', 'content_rich', 'content_plain')
    readonly_fields = ('content_plain',)


@admin.register(BookVersion)
class BookVersionAdmin(admin.ModelAdmin):
    list_display = ('id', 'book', 'version', 'status', 'published_at', 'created_at')
    search_fields = ('book__title', 'version')
    list_filter = ('status', 'book')
    inlines = [BookChapterInline]


@admin.register(PageText)
class PageTextAdmin(admin.ModelAdmin):
    list_display = ('id', 'book_version', 'page_number', 'created_at')
    search_fields = ('book_version__book__title', 'book_version__version', 'text')
    list_filter = ('book_version__book',)
    ordering = ('book_version', 'page_number')


@admin.register(BookChapter)
class BookChapterAdmin(admin.ModelAdmin):
    list_display = ('id', 'book_version', 'order', 'title', 'slug', 'updated_at')
    search_fields = ('book_version__book__title', 'book_version__version', 'title', 'slug', 'content_rich', 'content_plain')
    list_filter = ('book_version__book',)
    ordering = ('book_version', 'order', 'id')
    readonly_fields = ('content_plain', 'created_at', 'updated_at')
