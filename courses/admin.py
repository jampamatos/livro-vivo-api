from django import forms
from django.contrib import admin
from django.utils.html import format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from tinymce.widgets import TinyMCE

from library.models import ALLOWED_CHAPTER_TAGS, sanitize_chapter_html
from .models import CourseAsset, CoursePost, LiveEvent


COURSE_POST_WORDLIKE_MCE_ATTRS = {
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


class CoursePostAdminForm(forms.ModelForm):
    class Meta:
        model = CoursePost
        fields = '__all__'
        widgets = {
            'content_rich': TinyMCE(
                attrs={
                    'rows': 18,
                    'class': 'vLargeTextField',
                },
                mce_attrs=COURSE_POST_WORDLIKE_MCE_ATTRS,
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
            'Use o editor para estruturar o conteúdo com headings, listas e links. '
            f'Tags permitidas: {allowed_tags}.'
        )


class LiveEventAdminForm(forms.ModelForm):
    class Meta:
        model = LiveEvent
        fields = '__all__'
        widgets = {
            'description': TinyMCE(
                attrs={
                    'rows': 12,
                    'class': 'vLargeTextField',
                },
                mce_attrs=COURSE_POST_WORDLIKE_MCE_ATTRS,
            ),
        }

    class Media:
        css = {
            'all': ('library/admin/chapter_rich_editor.css',),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_tags = ', '.join(sorted(ALLOWED_CHAPTER_TAGS))
        self.fields['description'].help_text = (
            'Use o editor para estruturar a descrição da live com headings, listas e links. '
            f'Tags permitidas: {allowed_tags}.'
        )


@admin.register(CoursePost)
class CoursePostAdmin(admin.ModelAdmin):
    form = CoursePostAdminForm
    list_display = (
        'title',
        'post_type',
        'status',
        'content_preview_compact',
        'published_at',
        'updated_at',
    )
    list_filter = ('status', 'post_type', 'published_at', 'updated_at')
    search_fields = ('title', 'author_name', 'excerpt', 'content_rich')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('-published_at', '-updated_at', '-created_at')
    readonly_fields = ('content_preview', 'content_plain', 'created_at', 'updated_at')
    fields = (
        'title',
        'slug',
        'author_name',
        'excerpt',
        'post_type',
        'tags',
        'status',
        'published_at',
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


@admin.register(CourseAsset)
class CourseAssetAdmin(admin.ModelAdmin):
    list_display = ('title', 'asset_type', 'status', 'post', 'published_at', 'updated_at')
    list_filter = ('status', 'asset_type', 'published_at', 'updated_at')
    search_fields = ('title', 'description')
    ordering = ('-published_at', '-updated_at', '-created_at')


@admin.register(LiveEvent)
class LiveEventAdmin(admin.ModelAdmin):
    form = LiveEventAdminForm
    list_display = ('title', 'event_type', 'status', 'description_preview_compact', 'starts_at', 'updated_at')
    list_filter = ('status', 'event_type', 'starts_at', 'updated_at')
    search_fields = ('title', 'description')
    ordering = ('-starts_at', '-updated_at', '-created_at')
    readonly_fields = ('description_preview', 'created_at', 'updated_at')
    fields = (
        'post',
        'title',
        'description',
        'description_preview',
        'event_type',
        'status',
        'starts_at',
        'ends_at',
        'meeting_url',
        'recording_url',
        'created_at',
        'updated_at',
    )

    @admin.display(description='Preview')
    def description_preview(self, obj):
        if not obj.pk or not obj.description:
            return '-'
        safe_html = sanitize_chapter_html(obj.description)
        return format_html(
            '<div class="lv-rich-editor-preview" style="max-width: 54rem; max-height: 14rem; overflow: auto;">{}</div>',
            mark_safe(safe_html),
        )

    @admin.display(description='Resumo')
    def description_preview_compact(self, obj):
        if not obj.description:
            return '-'
        text = strip_tags(sanitize_chapter_html(obj.description))
        return Truncator(text).chars(80)
