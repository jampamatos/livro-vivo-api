from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.db import IntegrityError
from django.utils.html import format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils import timezone
from tinymce.widgets import TinyMCE

from .models import (
    ALLOWED_CHAPTER_TAGS,
    Book,
    BookChapter,
    BookVersion,
    sanitize_chapter_html,
)
from .services import (
    create_preloaded_book_version,
    enqueue_book_version_publication_notifications,
    suppress_book_chapter_notifications_for_versions,
)


BOOK_CHAPTER_WORDLIKE_MCE_ATTRS = {
    'height': 520,
    'menubar': False,
    'toolbar_mode': 'sliding',
    'branding': False,
    'browser_spellcheck': True,
    'plugins': 'lists link autoresize wordcount',
    'toolbar': 'undo redo | blocks | bold italic underline | bullist numlist | link removeformat',
    'block_formats': 'Parágrafo=p;Título 2=h2;Título 3=h3;Citação=blockquote',
    'valid_elements': 'p,br,strong,em,u,ul,ol,li,blockquote,h2,h3,a[href|title|target|rel]',
    'invalid_elements': 'script,style,img,iframe,video,audio,table,pre,code',
    'forced_root_block': 'p',
    'convert_urls': False,
    'elementpath': True,
    'content_style': (
        'body {'
        ' font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'
        ' font-size: 16px; line-height: 1.65; margin: 1rem; color: #111827; background: #ffffff;'
        '}'
        'p { margin: 0 0 0.9rem; }'
        'h2 { font-size: 1.6rem; line-height: 1.2; margin: 1.4rem 0 0.8rem; }'
        'h3 { font-size: 1.3rem; line-height: 1.25; margin: 1.2rem 0 0.6rem; }'
        'ul,ol { margin: 0 0 1rem; padding-left: 1.5rem; }'
        'li { margin: 0 0 0.4rem; }'
        'blockquote { margin: 0 0 1rem; padding-left: 0.75rem; border-left: 3px solid #cbd5e1; color: #475569; }'
        'a { color: #2563eb; text-decoration: underline; }'
    ),
}


class BookChapterAdminForm(forms.ModelForm):
    class Meta:
        model = BookChapter
        fields = '__all__'
        widgets = {
            'content_rich': TinyMCE(
                attrs={
                    'rows': 18,
                    'class': 'vLargeTextField',
                },
                mce_attrs=BOOK_CHAPTER_WORDLIKE_MCE_ATTRS,
            ),
        }

    class Media:
        css = {
            'all': ('library/admin/chapter_rich_editor.css',),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_tags = ', '.join(sorted(ALLOWED_CHAPTER_TAGS))
        self.fields['content_rich'].help_text = (
            'Use o editor para estruturar o capítulo com headings, listas e links. '
            f'Tags permitidas: {allowed_tags}.'
        )


class BookVersionAdminForm(forms.ModelForm):
    class Meta:
        model = BookVersion
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        changelog = (cleaned_data.get('changelog') or '').strip()
        if status == BookVersion.Status.PUBLISHED and not changelog:
            self.add_error('changelog', 'Changelog is required when publishing a version.')
        return cleaned_data


class BookVersionActionForm(ActionForm):
    new_version = forms.CharField(
        label='New version',
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={'placeholder': '2026.02.24', 'size': 16}),
    )
    new_changelog = forms.CharField(
        label='Changelog',
        required=False,
        max_length=400,
        widget=forms.TextInput(attrs={'placeholder': 'Resumo da nova publicação', 'size': 40}),
    )
    publish_now = forms.BooleanField(label='Publish now', required=False)


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
            '<div class="lv-rich-editor-preview" style="max-width: 54rem; max-height: 14rem; overflow: auto;">{}</div>',
            mark_safe(safe_html),
        )


@admin.register(BookVersion)
class BookVersionAdmin(admin.ModelAdmin):
    form = BookVersionAdminForm
    action_form = BookVersionActionForm
    list_display = ('id', 'book', 'version', 'status', 'published_at', 'created_at')
    search_fields = ('book__title', 'version')
    list_filter = ('status', 'book')
    inlines = [BookChapterInline]
    actions = ('create_preloaded_version',)

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change and obj.pk:
            previous_status = (
                BookVersion.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
            )

        super().save_model(request, obj, form, change)

        became_published = obj.status == BookVersion.Status.PUBLISHED and previous_status != BookVersion.Status.PUBLISHED
        request._suppress_chapter_notifications_for_version_ids = getattr(
            request,
            '_suppress_chapter_notifications_for_version_ids',
            set(),
        )
        if became_published:
            request._suppress_chapter_notifications_for_version_ids.add(obj.pk)
        if became_published:
            enqueue_book_version_publication_notifications(book_version=obj)

    def save_related(self, request, form, formsets, change):
        version_ids = tuple(
            getattr(request, '_suppress_chapter_notifications_for_version_ids', set())
        )
        if not version_ids:
            return super().save_related(request, form, formsets, change)

        with suppress_book_chapter_notifications_for_versions(*version_ids):
            return super().save_related(request, form, formsets, change)

    @admin.action(description='Create preloaded version from selected source')
    def create_preloaded_version(self, request, queryset):
        selected_count = queryset.count()
        if selected_count != 1:
            self.message_user(
                request,
                'Select exactly one source version to clone.',
                level=messages.ERROR,
            )
            return

        source_version = queryset.first()
        new_version = (request.POST.get('new_version') or '').strip()
        new_changelog = (request.POST.get('new_changelog') or '').strip()
        publish_now = request.POST.get('publish_now') == 'on'
        status = BookVersion.Status.PUBLISHED if publish_now else BookVersion.Status.DRAFT
        published_at = timezone.localdate() if publish_now else None

        try:
            cloned_version = create_preloaded_book_version(
                source_version=source_version,
                new_version=new_version,
                changelog=new_changelog,
                status=status,
                published_at=published_at,
            )
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        except IntegrityError:
            self.message_user(
                request,
                'Version identifier already exists for this book.',
                level=messages.ERROR,
            )
            return

        self.message_user(
            request,
            (
                f'Preloaded version "{cloned_version.version}" created from '
                f'"{source_version.version}" with {cloned_version.chapters.count()} chapter(s).'
            ),
            level=messages.SUCCESS,
        )


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
            '<div class="lv-rich-editor-preview" style="max-width: 54rem; max-height: 18rem; overflow: auto;">{}</div>',
            mark_safe(safe_html),
        )

    @admin.display(description='Resumo')
    def content_preview_compact(self, obj):
        if not obj.content_rich:
            return '-'
        text = strip_tags(sanitize_chapter_html(obj.content_rich))
        return Truncator(text).chars(80)
