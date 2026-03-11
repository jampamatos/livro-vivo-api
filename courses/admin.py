from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.utils.html import format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils import timezone
from tinymce.widgets import TinyMCE

from library.models import ALLOWED_CHAPTER_TAGS, sanitize_chapter_html
from .models import CourseAsset, CoursePost, LiveEvent, PublicationStatus


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


class CoursesBulkActionForm(ActionForm):
    confirm_sensitive_action = forms.BooleanField(
        label='Confirmo ação sensível (publicar/arquivar/cancelar)',
        required=False,
    )


@admin.register(CoursePost)
class CoursePostAdmin(admin.ModelAdmin):
    form = CoursePostAdminForm
    action_form = CoursesBulkActionForm
    list_display = (
        'title',
        'author_name',
        'post_type',
        'status',
        'content_preview_compact',
        'published_at',
        'updated_at',
    )
    list_filter = ('status', 'post_type', 'published_at', 'updated_at', 'created_at')
    search_fields = ('title', 'author_name', 'excerpt', 'content_rich')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('-published_at', '-updated_at', '-created_at')
    readonly_fields = ('content_preview', 'content_plain', 'created_at', 'updated_at', 'publication_guardrails')
    actions = ('publish_selected_posts', 'archive_selected_posts')
    fieldsets = (
        (
            'Dados do conteúdo',
            {
                'fields': (
                    'title',
                    'slug',
                    'author_name',
                    'excerpt',
                    'post_type',
                    'tags',
                )
            },
        ),
        (
            'Conteúdo em edição',
            {
                'fields': (
                    'content_rich',
                    'content_preview',
                    'content_plain',
                )
            },
        ),
        (
            'Publicação',
            {
                'fields': (
                    'status',
                    'published_at',
                    'publication_guardrails',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )

    @admin.display(description='Guardrails operacionais')
    def publication_guardrails(self, obj):
        return format_html(
            '<ul style="margin: 0; padding-left: 1.2rem;">'
            '<li>Publicar envia notificações para usuários elegíveis.</li>'
            '<li>Use publicação em massa somente com confirmação explícita.</li>'
            '<li>Arquivar remove destaque sem apagar histórico.</li>'
            '</ul>'
        )

    def _is_sensitive_action_confirmed(self, request):
        return str(request.POST.get('confirm_sensitive_action', '')).lower() in {'1', 'true', 'on', 'yes'}

    @admin.action(description='Publicar posts selecionados (ação sensível)')
    def publish_selected_posts(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para publicar posts em massa.',
                level=messages.ERROR,
            )
            return

        published = 0
        skipped = 0
        now = timezone.now()
        for post in queryset:
            if post.status == PublicationStatus.PUBLISHED:
                skipped += 1
                continue
            post.status = PublicationStatus.PUBLISHED
            if post.published_at is None:
                post.published_at = now
            post.save()
            published += 1

        if published:
            self.message_user(request, f'{published} post(s) publicado(s).', level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} post(s) já estavam publicados.', level=messages.INFO)

    @admin.action(description='Arquivar posts selecionados (ação sensível)')
    def archive_selected_posts(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para arquivar posts em massa.',
                level=messages.ERROR,
            )
            return

        archived = 0
        skipped = 0
        for post in queryset:
            if post.status == PublicationStatus.ARCHIVED:
                skipped += 1
                continue
            post.status = PublicationStatus.ARCHIVED
            post.save(update_fields=['status', 'updated_at'])
            archived += 1

        if archived:
            self.message_user(request, f'{archived} post(s) arquivado(s).', level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} post(s) já estavam arquivados.', level=messages.INFO)

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
    action_form = CoursesBulkActionForm
    list_display = ('title', 'asset_type', 'status', 'post', 'published_at', 'updated_at')
    list_filter = ('status', 'asset_type', 'published_at', 'updated_at', 'created_at')
    search_fields = ('title', 'description')
    ordering = ('-published_at', '-updated_at', '-created_at')
    readonly_fields = ('created_at', 'updated_at')
    actions = ('publish_selected_assets', 'archive_selected_assets')
    fieldsets = (
        (
            'Dados do material',
            {
                'fields': (
                    'title',
                    'description',
                    'asset_type',
                    'post',
                    'tags',
                )
            },
        ),
        (
            'Publicação',
            {
                'fields': (
                    'status',
                    'published_at',
                    'file_url',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )

    def _is_sensitive_action_confirmed(self, request):
        return str(request.POST.get('confirm_sensitive_action', '')).lower() in {'1', 'true', 'on', 'yes'}

    @admin.action(description='Publicar materiais selecionados (ação sensível)')
    def publish_selected_assets(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para publicar materiais em massa.',
                level=messages.ERROR,
            )
            return

        published = 0
        skipped = 0
        now = timezone.now()
        for asset in queryset:
            if asset.status == PublicationStatus.PUBLISHED:
                skipped += 1
                continue
            asset.status = PublicationStatus.PUBLISHED
            if asset.published_at is None:
                asset.published_at = now
            asset.save()
            published += 1

        if published:
            self.message_user(request, f'{published} material(is) publicado(s).', level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} material(is) já publicados.', level=messages.INFO)

    @admin.action(description='Arquivar materiais selecionados (ação sensível)')
    def archive_selected_assets(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para arquivar materiais em massa.',
                level=messages.ERROR,
            )
            return

        archived = 0
        skipped = 0
        for asset in queryset:
            if asset.status == PublicationStatus.ARCHIVED:
                skipped += 1
                continue
            asset.status = PublicationStatus.ARCHIVED
            asset.save(update_fields=['status', 'updated_at'])
            archived += 1

        if archived:
            self.message_user(request, f'{archived} material(is) arquivado(s).', level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} material(is) já arquivados.', level=messages.INFO)


@admin.register(LiveEvent)
class LiveEventAdmin(admin.ModelAdmin):
    form = LiveEventAdminForm
    action_form = CoursesBulkActionForm
    list_display = ('title', 'post', 'event_type', 'status', 'description_preview_compact', 'starts_at', 'updated_at')
    list_filter = ('status', 'event_type', 'starts_at', 'updated_at', 'created_at')
    search_fields = ('title', 'description')
    ordering = ('-starts_at', '-updated_at', '-created_at')
    readonly_fields = ('description_preview', 'created_at', 'updated_at')
    actions = ('cancel_selected_events',)
    fieldsets = (
        (
            'Dados da live',
            {
                'fields': (
                    'post',
                    'title',
                    'event_type',
                    'status',
                )
            },
        ),
        (
            'Janela do evento',
            {
                'fields': (
                    'starts_at',
                    'ends_at',
                )
            },
        ),
        (
            'Conteúdo e links',
            {
                'fields': (
                    'description',
                    'description_preview',
                    'meeting_url',
                    'recording_url',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )

    def _is_sensitive_action_confirmed(self, request):
        return str(request.POST.get('confirm_sensitive_action', '')).lower() in {'1', 'true', 'on', 'yes'}

    @admin.action(description='Cancelar lives selecionadas (ação sensível)')
    def cancel_selected_events(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para cancelar lives em massa.',
                level=messages.ERROR,
            )
            return

        canceled = 0
        skipped = 0
        for event in queryset:
            if event.status == LiveEvent.Status.CANCELED:
                skipped += 1
                continue
            event.status = LiveEvent.Status.CANCELED
            event.save(update_fields=['status', 'updated_at'])
            canceled += 1

        if canceled:
            self.message_user(request, f'{canceled} live(s) cancelada(s).', level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f'{skipped} live(s) já estavam canceladas.', level=messages.INFO)

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
