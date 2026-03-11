from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from .models import PublicationStatus, TemplatePiece


class TemplatePieceAdminForm(forms.ModelForm):
    class Meta:
        model = TemplatePiece
        fields = '__all__'
        help_texts = {
            'file_upload': 'Recomendado: envie o arquivo diretamente aqui.',
            'file_url': 'Alternativa ao upload: URL remota do arquivo (https://...).',
        }

    def clean(self):
        cleaned_data = super().clean()

        for field_name in self.fields:
            if field_name in cleaned_data:
                setattr(self.instance, field_name, cleaned_data[field_name])

        try:
            self.instance.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                for field_name, messages in exc.message_dict.items():
                    if isinstance(messages, str):
                        messages = [messages]
                    for message in messages:
                        if field_name in self.fields:
                            self.add_error(field_name, message)
                        else:
                            self.add_error(None, message)
            else:
                for message in exc.messages:
                    self.add_error(None, message)

        return cleaned_data


class TemplatePieceActionForm(ActionForm):
    confirm_sensitive_action = forms.BooleanField(
        label='Confirmo ação sensível (publicar/arquivar)',
        required=False,
    )


@admin.register(TemplatePiece)
class TemplatePieceAdmin(admin.ModelAdmin):
    form = TemplatePieceAdminForm
    action_form = TemplatePieceActionForm

    @admin.display(description='Fonte')
    def file_source(self, obj):
        return 'Upload' if obj.file_upload else 'URL remota'

    list_display = (
        'title',
        'template_code',
        'version',
        'file_source',
        'category',
        'status',
        'file_name',
        'published_at',
        'updated_at',
    )
    list_filter = ('status', 'category', 'updated_at', 'published_at', 'created_at')
    search_fields = ('title', 'template_code', 'version', 'description', 'changelog', 'file_name')
    ordering = ('template_code', '-created_at', '-updated_at')
    readonly_fields = (
        'file_name',
        'file_mime_type',
        'file_size_bytes',
        'file_sha256',
        'created_at',
        'updated_at',
        'publication_guardrails',
    )
    prepopulated_fields = {'slug': ('title',)}

    fieldsets = (
        (
            'Dados da peça',
            {
                'fields': (
                    'title',
                    'slug',
                    'template_code',
                    'version',
                    'category',
                    'status',
                    'published_at',
                    'publication_guardrails',
                    'description',
                    'changelog',
                    'tags',
                ),
            },
        ),
        (
            'Arquivo',
            {
                'description': (
                    'Escolha apenas uma opção: upload de arquivo (recomendado) '
                    'ou URL remota. Os metadados são preenchidos automaticamente.'
                ),
                'fields': (
                    'file_upload',
                    'file_url',
                ),
            },
        ),
        (
            'Metadados automáticos',
            {
                'fields': (
                    'file_name',
                    'file_mime_type',
                    'file_size_bytes',
                    'file_sha256',
                ),
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )
    actions = ['mark_published', 'mark_archived']

    @admin.display(description='Guardrails de publicação')
    def publication_guardrails(self, obj):
        return (
            'Publicação em massa exige confirmação. '
            'A versão só pode ser publicada com changelog preenchido.'
        )

    def _is_sensitive_action_confirmed(self, request):
        return str(request.POST.get('confirm_sensitive_action', '')).lower() in {'1', 'true', 'on', 'yes'}

    @admin.action(description='Publicar selecionadas (ação sensível)')
    def mark_published(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para publicar peças em massa.',
                level=messages.ERROR,
            )
            return

        publishable_ids = []
        skipped_missing_changelog = 0
        skipped_already_published = 0
        for piece in queryset:
            if piece.status == PublicationStatus.PUBLISHED:
                skipped_already_published += 1
                continue
            if not (piece.changelog or '').strip():
                skipped_missing_changelog += 1
                continue
            publishable_ids.append(piece.id)

        if publishable_ids:
            now = timezone.now()
            TemplatePiece.objects.filter(id__in=publishable_ids).update(
                status=PublicationStatus.PUBLISHED,
                published_at=now,
                updated_at=now,
            )
            self.message_user(
                request,
                f'{len(publishable_ids)} peça(s) publicada(s).',
                level=messages.SUCCESS,
            )
        if skipped_missing_changelog:
            self.message_user(
                request,
                f'{skipped_missing_changelog} peça(s) ignorada(s) por changelog vazio.',
                level=messages.WARNING,
            )
        if skipped_already_published:
            self.message_user(
                request,
                f'{skipped_already_published} peça(s) já estavam publicadas.',
                level=messages.INFO,
            )

    @admin.action(description='Arquivar selecionadas (ação sensível)')
    def mark_archived(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                'Confirme a ação sensível para arquivar peças em massa.',
                level=messages.ERROR,
            )
            return

        archived_ids = list(
            queryset.exclude(status=PublicationStatus.ARCHIVED).values_list('id', flat=True)
        )
        skipped = queryset.count() - len(archived_ids)
        if archived_ids:
            now = timezone.now()
            TemplatePiece.objects.filter(id__in=archived_ids).update(
                status=PublicationStatus.ARCHIVED,
                updated_at=now,
            )
            self.message_user(
                request,
                f'{len(archived_ids)} peça(s) arquivada(s).',
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f'{skipped} peça(s) já estavam arquivadas.',
                level=messages.INFO,
            )
