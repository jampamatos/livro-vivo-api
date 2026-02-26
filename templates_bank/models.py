from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .file_metadata import FileMetadata, extract_uploaded_file_metadata, fetch_remote_file_metadata


def _normalize_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(tag).strip() for tag in value if str(tag).strip()]


class PublicationStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PUBLISHED = 'published', 'Published'
    ARCHIVED = 'archived', 'Archived'


class TemplatePiece(models.Model):
    class Category(models.TextChoices):
        PETITION = 'petition', 'Petition'
        CONTRACT = 'contract', 'Contract'
        APPEAL = 'appeal', 'Appeal'
        MOTION = 'motion', 'Motion'
        ADMINISTRATIVE = 'administrative', 'Administrative'
        OTHER = 'other', 'Other'

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=250, unique=True)
    template_code = models.SlugField(max_length=120)
    version = models.CharField(max_length=32, default='1.0.0')
    changelog = models.TextField(blank=True, default='')
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=24, choices=Category.choices, default=Category.OTHER)
    tags = models.JSONField(default=list, blank=True)

    file_url = models.URLField(blank=True, default='')
    file_upload = models.FileField(upload_to='templates_bank/uploads/%Y/%m/%d', blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, default='')
    file_mime_type = models.CharField(max_length=120, blank=True, default='')
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    file_sha256 = models.CharField(max_length=64, blank=True, default='')

    status = models.CharField(max_length=16, choices=PublicationStatus.choices, default=PublicationStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['template_code', '-created_at', '-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['template_code', 'version'],
                name='uniq_template_piece_code_version',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.template_code} v{self.version} ({self.status})'

    def _metadata_is_complete(self) -> bool:
        return bool(
            (self.file_name or '').strip()
            and (self.file_mime_type or '').strip()
            and (self.file_sha256 or '').strip()
            and isinstance(self.file_size_bytes, int)
            and self.file_size_bytes >= 0
        )

    def _file_upload_name(self) -> str:
        if not self.file_upload:
            return ''
        return (getattr(self.file_upload, 'name', '') or '').strip()

    def _source_changed(self) -> bool:
        if not self.pk:
            return True

        previous = (
            TemplatePiece.objects
            .filter(pk=self.pk)
            .values('file_url', 'file_upload')
            .first()
        )
        if previous is None:
            return True

        previous_upload = (previous.get('file_upload') or '').strip()
        previous_url = (previous.get('file_url') or '').strip()

        return previous_upload != self._file_upload_name() or previous_url != (self.file_url or '').strip()

    def _resolve_metadata(self) -> FileMetadata:
        has_upload = bool(self.file_upload)
        has_remote_url = bool((self.file_url or '').strip())

        if has_upload and has_remote_url:
            raise ValidationError(
                {
                    'file_upload': 'Use apenas uma fonte de arquivo: upload ou URL remota.',
                    'file_url': 'Use apenas uma fonte de arquivo: upload ou URL remota.',
                }
            )

        if not has_upload and not has_remote_url:
            raise ValidationError(
                {
                    'file_upload': 'Envie um arquivo ou informe uma URL remota.',
                    'file_url': 'Envie um arquivo ou informe uma URL remota.',
                }
            )

        if has_upload:
            self.file_url = ''
            if self._metadata_is_complete() and self.pk and not self._source_changed():
                return FileMetadata(
                    file_name=(self.file_name or '').strip(),
                    file_mime_type=(self.file_mime_type or '').strip(),
                    file_size_bytes=int(self.file_size_bytes),
                    file_sha256=(self.file_sha256 or '').strip().lower(),
                )
            return extract_uploaded_file_metadata(self.file_upload)

        remote_timeout = int(getattr(settings, 'TEMPLATES_BANK_REMOTE_FILE_FETCH_TIMEOUT_SECONDS', 8))
        remote_max_bytes = int(getattr(settings, 'TEMPLATES_BANK_REMOTE_FILE_MAX_BYTES', 30 * 1024 * 1024))

        if self._metadata_is_complete() and (not self.pk or not self._source_changed()):
            return FileMetadata(
                file_name=(self.file_name or '').strip(),
                file_mime_type=(self.file_mime_type or '').strip(),
                file_size_bytes=int(self.file_size_bytes),
                file_sha256=(self.file_sha256 or '').strip().lower(),
            )

        return fetch_remote_file_metadata(
            self.file_url,
            timeout_seconds=max(remote_timeout, 1),
            max_bytes=max(remote_max_bytes, 1024),
        )

    def resolved_file_url(self, request=None) -> str:
        file_url = (self.file_url or '').strip()
        if self.file_upload:
            try:
                file_url = self.file_upload.url
            except Exception:
                file_url = ''

        if file_url and request is not None:
            return request.build_absolute_uri(file_url)
        return file_url

    def clean(self):
        super().clean()
        metadata = self._resolve_metadata()
        self.file_name = metadata.file_name
        self.file_mime_type = metadata.file_mime_type
        self.file_size_bytes = metadata.file_size_bytes
        self.file_sha256 = metadata.file_sha256

    def save(self, *args, **kwargs):
        self.tags = _normalize_tags(self.tags)
        self.clean()
        self.file_sha256 = (self.file_sha256 or '').strip().lower()

        if self.status == PublicationStatus.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()

        return super().save(*args, **kwargs)
