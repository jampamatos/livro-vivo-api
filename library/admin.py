from django import forms
from django.contrib import admin
from django.utils.html import format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator

from .models import (
    ALLOWED_CHAPTER_TAGS,
    Book,
    BookChapter,
    BookVersion,
    PageText,
    sanitize_chapter_html,
)


class BookChapterAdminForm(forms.ModelForm):
    class Meta:
        model = BookChapter
        fields = '__all__'
        widgets = {
            'content_rich': forms.Textarea(
                attrs={
                    'rows': 18,
                    'class': 'vLargeTextField js-rich-chapter-editor-source',
                }
            ),
        }

    class Media:
        css = {
            'all': ('library/admin/chapter_rich_editor.css',),
        }
        js = ('library/admin/chapter_rich_editor.js',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_tags = ', '.join(sorted(ALLOWED_CHAPTER_TAGS))
        self.fields['content_rich'].help_text = (
            'Use o editor para estruturar o capítulo com headings, listas e links. '
            f'Tags permitidas: {allowed_tags}.'
        )


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'status', 'created_at', 'updated_at')
    search_fields = ('title',)
    list_filter = ('status',)


class BookChapterInline(admin.StackedInline):
    model = BookChapter
    form = BookChapterAdminForm
    extra = 0
    show_change_link = True
    ordering = ('order', 'id')
    fields = ('order', 'title', 'slug', 'content_rich', 'content_preview', 'content_plain')
    readonly_fields = ('content_preview', 'content_plain')

    @admin.display(description='Preview')
    def content_preview(self, obj):
        if not obj.pk or not obj.content_rich:
            return '-'

        safe_html = sanitize_chapter_html(obj.content_rich)
        return format_html(
            '<div style="max-width: 54rem; max-height: 14rem; overflow: auto;">{}</div>',
            mark_safe(safe_html),
        )


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
    form = BookChapterAdminForm
    list_display = ('id', 'book_version', 'order', 'title', 'slug', 'content_preview_compact', 'updated_at')
    list_editable = ('order',)
    list_display_links = ('id', 'book_version', 'title')
    search_fields = ('book_version__book__title', 'book_version__version', 'title', 'slug', 'content_rich', 'content_plain')
    list_filter = ('book_version__book',)
    ordering = ('book_version', 'order', 'id')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('content_preview', 'content_plain', 'created_at', 'updated_at')
    fields = (
        'book_version',
        'order',
        'title',
        'slug',
        'content_rich',
        'content_preview',
        'content_plain',
        'created_at',
        'updated_at',
    )

    @admin.display(description='Preview')
    def content_preview(self, obj):
        if not obj.pk or not obj.content_rich:
            return '-'

        safe_html = sanitize_chapter_html(obj.content_rich)
        return format_html(
            '<div style="max-width: 54rem; max-height: 18rem; overflow: auto;">{}</div>',
            mark_safe(safe_html),
        )

    @admin.display(description='Resumo')
    def content_preview_compact(self, obj):
        if not obj.content_rich:
            return '-'
        text = strip_tags(sanitize_chapter_html(obj.content_rich))
        return Truncator(text).chars(80)
