from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError as DjangoValidationError

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


@admin.register(TemplatePiece)
class TemplatePieceAdmin(admin.ModelAdmin):
    form = TemplatePieceAdminForm

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
        'updated_at',
    )
    list_filter = ('status', 'category', 'updated_at', 'published_at')
    search_fields = ('title', 'template_code', 'version', 'description', 'changelog', 'file_name')
    ordering = ('template_code', '-created_at', '-updated_at')
    readonly_fields = ('file_name', 'file_mime_type', 'file_size_bytes', 'file_sha256', 'created_at', 'updated_at')
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

    @admin.action(description='Marcar selecionadas como publicadas')
    def mark_published(self, request, queryset):
        queryset.update(status=PublicationStatus.PUBLISHED)

    @admin.action(description='Marcar selecionadas como arquivadas')
    def mark_archived(self, request, queryset):
        queryset.update(status=PublicationStatus.ARCHIVED)
