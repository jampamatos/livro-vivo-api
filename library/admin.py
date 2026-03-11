from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join, strip_tags
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
    confirm_sensitive_action = forms.BooleanField(
        label='Confirmo ação sensível (publicar/arquivar)',
        required=False,
    )


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'current_version_label', 'updated_at')
    search_fields = ('title',)
    list_filter = ('status',)
    readonly_fields = (
        'current_version_label',
        'versions_pipeline_panel',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            'Dados do livro',
            {
                'fields': (
                    'title',
                    'description',
                    'status',
                )
            },
        ),
        (
            'Pipeline de versoes',
            {
                'fields': (
                    'current_version_label',
                    'versions_pipeline_panel',
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

    class Media:
        css = {
            'all': ('library/admin/book_version_pipeline.css',),
        }
        js = ('library/admin/book_version_pipeline.js',)

    def _get_current_version(self, obj: Book | None) -> BookVersion | None:
        if not obj or not obj.pk:
            return None
        published = (
            obj.versions.filter(status=BookVersion.Status.PUBLISHED)
            .order_by('-published_at', '-created_at', '-id')
            .first()
        )
        if published:
            return published
        return obj.versions.order_by('-created_at', '-id').first()

    @admin.display(description='Versao atual')
    def current_version_label(self, obj: Book):
        current = self._get_current_version(obj)
        if not current:
            return '-'
        url = reverse('admin:library_bookversion_change', args=[current.id])
        return format_html(
            '<a href="{}">{}</a> ({})',
            url,
            current.version,
            current.get_status_display(),
        )

    @admin.display(description='Controle de versoes')
    def versions_pipeline_panel(self, obj: Book):
        if not obj or not obj.pk:
            return 'Salve o livro para gerenciar versoes.'

        versions = obj.versions.order_by('-created_at', '-id')
        create_url = reverse('admin:library_book_create_version', args=[obj.id])

        if not versions.exists():
            return format_html(
                '<div class="lv-version-pipeline" data-create-url="{}">'
                '<p>Este livro ainda nao possui versoes.</p>'
                '<button type="button" class="button default lv-add-version-btn">Adicionar nova versao</button>'
                '<div class="lv-version-modal" id="lv-add-version-modal" hidden>'
                '<div class="lv-version-modal__card">'
                '<h3>Adicionar nova versao</h3>'
                '<label>Nome da versao</label>'
                '<input type="text" id="lv-new-version-name" placeholder="2026.03.11">'
                '<label>Changelog</label>'
                '<textarea id="lv-new-version-changelog" rows="4" placeholder="Resumo das mudancas"></textarea>'
                '<div class="lv-version-modal__actions">'
                '<button type="button" class="button default" id="lv-confirm-add-version">Criar rascunho</button>'
                '<button type="button" class="button" id="lv-cancel-add-version">Cancelar</button>'
                '</div>'
                '</div>'
                '</div>'
                '</div>',
                create_url,
            )

        status_badges = {
            BookVersion.Status.DRAFT: 'lv-status-badge lv-status-badge--draft',
            BookVersion.Status.PUBLISHED: 'lv-status-badge lv-status-badge--published',
            BookVersion.Status.ARCHIVED: 'lv-status-badge lv-status-badge--archived',
        }

        rows = []
        for version in versions:
            publish_url = reverse('admin:library_book_publish_version', args=[obj.id, version.id])
            chapters_url = f'{reverse("admin:library_bookchapter_changelist")}?book_version__id__exact={version.id}'
            add_chapter_url = f'{reverse("admin:library_bookchapter_add")}?book_version={version.id}'
            edit_version_url = reverse('admin:library_bookversion_change', args=[version.id])

            if version.status == BookVersion.Status.DRAFT:
                publish_cell = format_html(
                    '<button type="button" class="button default lv-publish-version-btn" '
                    'data-publish-url="{}" data-version-label="{}">Publicar</button>',
                    publish_url,
                    version.version,
                )
            else:
                publish_cell = version.published_at.isoformat() if version.published_at else '-'

            rows.append(
                (
                    version.version,
                    format_html(
                        '<span class="{}">{}</span>',
                        status_badges.get(version.status, 'lv-status-badge'),
                        version.get_status_display(),
                    ),
                    Truncator((version.changelog or '').strip()).chars(120) or '-',
                    publish_cell,
                    format_html(
                        '<a class="button" href="{}">Capitulos</a> '
                        '<a class="button" href="{}">Adicionar capitulo</a> '
                        '<a class="button" href="{}">Editar versao</a>',
                        chapters_url,
                        add_chapter_url,
                        edit_version_url,
                    ),
                )
            )

        return format_html(
            '<div class="lv-version-pipeline" data-create-url="{}">'
            '<div class="lv-version-pipeline__header">'
            '<button type="button" class="button default lv-add-version-btn">Adicionar nova versao</button>'
            '</div>'
            '<table class="lv-version-pipeline__table">'
            '<thead><tr>'
            '<th>Versao</th><th>Status</th><th>Changelog</th><th>Publicacao</th><th>Acoes</th>'
            '</tr></thead>'
            '<tbody>{}</tbody>'
            '</table>'
            '<div class="lv-version-modal" id="lv-add-version-modal" hidden>'
            '<div class="lv-version-modal__card">'
            '<h3>Adicionar nova versao</h3>'
            '<label>Nome da versao</label>'
            '<input type="text" id="lv-new-version-name" placeholder="2026.03.11">'
            '<label>Changelog</label>'
            '<textarea id="lv-new-version-changelog" rows="4" placeholder="Resumo das mudancas"></textarea>'
            '<div class="lv-version-modal__actions">'
            '<button type="button" class="button default" id="lv-confirm-add-version">Criar rascunho</button>'
            '<button type="button" class="button" id="lv-cancel-add-version">Cancelar</button>'
            '</div>'
            '</div>'
            '</div>'
            '<div class="lv-version-modal" id="lv-publish-version-modal" hidden>'
            '<div class="lv-version-modal__card">'
            '<h3>Confirmar publicacao</h3>'
            '<p id="lv-publish-version-message"></p>'
            '<p>Ao confirmar, esta versao vira publicada e as demais ficam arquivadas.</p>'
            '<div class="lv-version-modal__actions">'
            '<button type="button" class="button default" id="lv-confirm-publish-version">Sim, publicar</button>'
            '<button type="button" class="button" id="lv-cancel-publish-version">Cancelar</button>'
            '</div>'
            '</div>'
            '</div>'
            '</div>',
            create_url,
            format_html_join(
                '',
                '<tr><td><strong>{}</strong></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>',
                rows,
            ),
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:book_id>/versions/create/',
                self.admin_site.admin_view(self.create_version_view),
                name='library_book_create_version',
            ),
            path(
                '<path:book_id>/versions/<path:version_id>/publish/',
                self.admin_site.admin_view(self.publish_version_view),
                name='library_book_publish_version',
            ),
        ]
        return custom_urls + urls

    def _book_change_redirect(self, book_id):
        return redirect('admin:library_book_change', object_id=book_id)

    def create_version_view(self, request, book_id, *args, **kwargs):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        book = get_object_or_404(Book, pk=book_id)
        if not self.has_change_permission(request, obj=book):
            return self._book_change_redirect(book.id)

        version_name = (request.POST.get('version') or '').strip()
        changelog = (request.POST.get('changelog') or '').strip()
        if not version_name:
            self.message_user(request, 'Informe o nome da nova versao.', level=messages.ERROR)
            return self._book_change_redirect(book.id)
        if not changelog:
            self.message_user(request, 'Informe o changelog da nova versao.', level=messages.ERROR)
            return self._book_change_redirect(book.id)

        source_version = self._get_current_version(book)
        try:
            if source_version:
                created = create_preloaded_book_version(
                    source_version=source_version,
                    new_version=version_name,
                    changelog=changelog,
                    status=BookVersion.Status.DRAFT,
                    published_at=None,
                )
            else:
                created = BookVersion.objects.create(
                    book=book,
                    version=version_name,
                    changelog=changelog,
                    status=BookVersion.Status.DRAFT,
                )
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return self._book_change_redirect(book.id)
        except IntegrityError:
            self.message_user(
                request,
                'Ja existe uma versao com esse identificador para este livro.',
                level=messages.ERROR,
            )
            return self._book_change_redirect(book.id)

        self.message_user(
            request,
            f'Versao "{created.version}" criada em rascunho.',
            level=messages.SUCCESS,
        )
        return self._book_change_redirect(book.id)

    def publish_version_view(self, request, book_id, version_id, *args, **kwargs):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        book = get_object_or_404(Book, pk=book_id)
        version = get_object_or_404(BookVersion, pk=version_id, book=book)
        if not self.has_change_permission(request, obj=book):
            return self._book_change_redirect(book.id)

        if not (version.changelog or '').strip():
            self.message_user(
                request,
                'Nao e possivel publicar sem changelog. Atualize a versao antes de publicar.',
                level=messages.ERROR,
            )
            return self._book_change_redirect(book.id)

        with transaction.atomic():
            archived_count = (
                BookVersion.objects
                .filter(book=book)
                .exclude(pk=version.pk)
                .exclude(status=BookVersion.Status.ARCHIVED)
                .update(status=BookVersion.Status.ARCHIVED)
            )

            became_published = version.status != BookVersion.Status.PUBLISHED
            version.status = BookVersion.Status.PUBLISHED
            if version.published_at is None:
                version.published_at = timezone.localdate()
            version.save(update_fields=['status', 'published_at'])

            if book.status != Book.Status.PUBLISHED:
                book.status = Book.Status.PUBLISHED
                book.save(update_fields=['status'])

        if became_published:
            enqueue_book_version_publication_notifications(book_version=version)

        self.message_user(
            request,
            f'Versao "{version.version}" publicada com sucesso. {archived_count} versao(oes) arquivada(s).',
            level=messages.SUCCESS,
        )
        return self._book_change_redirect(book.id)


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
    list_display = ('book', 'version', 'status', 'chapters_count', 'published_at', 'created_at')
    search_fields = ('book__title', 'version')
    list_filter = ('status', 'book', 'published_at', 'created_at')
    inlines = [BookChapterInline]
    actions = ('create_preloaded_version', 'publish_selected_versions', 'archive_selected_versions')
    readonly_fields = ('created_at', 'publication_guardrails')
    fieldsets = (
        (
            'Dados da versão',
            {
                'fields': (
                    'book',
                    'version',
                    'changelog',
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
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_chapters_count=Count('chapters', distinct=True))

    @admin.display(description='Capítulos')
    def chapters_count(self, obj):
        return getattr(obj, '_chapters_count', 0)

    @admin.display(description='Guardrails de publicação')
    def publication_guardrails(self, obj):
        return format_html(
            '<ul style="margin: 0; padding-left: 1.2rem;">'
            '<li>Somente 1 versão publicada por livro.</li>'
            '<li>Publicação exige changelog preenchido.</li>'
            '<li>Ao publicar, as demais versões ficam arquivadas.</li>'
            '</ul>'
        )

    def _is_sensitive_action_confirmed(self, request):
        return str(request.POST.get('confirm_sensitive_action', '')).lower() in {'1', 'true', 'on', 'yes'}

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = BookVersion.Status.DRAFT
            obj.published_at = None

        previous_status = None
        if change and obj.pk:
            previous_status = (
                BookVersion.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
            )

        if obj.status == BookVersion.Status.PUBLISHED:
            (
                BookVersion.objects
                .filter(book=obj.book)
                .exclude(pk=obj.pk)
                .exclude(status=BookVersion.Status.ARCHIVED)
                .update(status=BookVersion.Status.ARCHIVED)
            )
            if obj.published_at is None:
                obj.published_at = timezone.localdate()

        super().save_model(request, obj, form, change)

        if obj.status == BookVersion.Status.PUBLISHED and obj.book.status != Book.Status.PUBLISHED:
            Book.objects.filter(pk=obj.book_id).update(status=Book.Status.PUBLISHED)
            obj.book.status = Book.Status.PUBLISHED

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
        status = BookVersion.Status.DRAFT
        published_at = None

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

    @admin.action(description='Publicar versão selecionada (ação sensível)')
    def publish_selected_versions(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para publicar versões em massa.',
                level=messages.ERROR,
            )
            return

        selected_count = queryset.count()
        if selected_count != 1:
            self.message_user(
                request,
                'Selecione exatamente 1 versão para publicar.',
                level=messages.ERROR,
            )
            return

        version = queryset.select_related('book').first()
        if not (version.changelog or '').strip():
            self.message_user(
                request,
                'Não é possível publicar sem changelog preenchido.',
                level=messages.ERROR,
            )
            return

        with transaction.atomic():
            archived_count = (
                BookVersion.objects
                .filter(book=version.book)
                .exclude(pk=version.pk)
                .exclude(status=BookVersion.Status.ARCHIVED)
                .update(status=BookVersion.Status.ARCHIVED)
            )

            became_published = version.status != BookVersion.Status.PUBLISHED
            version.status = BookVersion.Status.PUBLISHED
            if version.published_at is None:
                version.published_at = timezone.localdate()
            version.save(update_fields=['status', 'published_at'])

            if version.book.status != Book.Status.PUBLISHED:
                version.book.status = Book.Status.PUBLISHED
                version.book.save(update_fields=['status'])

        if became_published:
            enqueue_book_version_publication_notifications(book_version=version)

        self.message_user(
            request,
            (
                f'Versão "{version.version}" publicada com sucesso. '
                f'{archived_count} versão(ões) arquivada(s).'
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description='Arquivar versões selecionadas (ação sensível)')
    def archive_selected_versions(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para arquivar versões em massa.',
                level=messages.ERROR,
            )
            return

        archived = 0
        skipped_published = 0
        skipped_already_archived = 0
        for version in queryset.select_related('book'):
            if version.status == BookVersion.Status.ARCHIVED:
                skipped_already_archived += 1
                continue
            if version.status == BookVersion.Status.PUBLISHED:
                skipped_published += 1
                continue
            version.status = BookVersion.Status.ARCHIVED
            version.save(update_fields=['status'])
            archived += 1

        if archived:
            self.message_user(request, f'{archived} versão(ões) arquivada(s).', level=messages.SUCCESS)
        if skipped_published:
            self.message_user(
                request,
                (
                    f'{skipped_published} versão(ões) publicada(s) não foram arquivadas. '
                    'Publique outra versão primeiro.'
                ),
                level=messages.WARNING,
            )
        if skipped_already_archived:
            self.message_user(
                request,
                f'{skipped_already_archived} versão(ões) já estavam arquivadas.',
                level=messages.INFO,
            )


@admin.register(BookChapter)
class BookChapterAdmin(admin.ModelAdmin):
    form = BookChapterAdminForm
    list_display = ('book_version', 'order', 'title', 'slug', 'content_preview_compact', 'updated_at')
    list_editable = ('order',)
    list_display_links = ('book_version', 'title')
    search_fields = ('book_version__book__title', 'book_version__version', 'title', 'slug', 'content_rich', 'content_plain')
    list_filter = ('book_version__book', 'book_version')
    ordering = ('book_version', 'order', 'title')
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

    def has_module_permission(self, request):
        # A gestao de capitulos acontece pelo fluxo de Livro.
        return False

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
