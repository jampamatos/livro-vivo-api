from django.db import models
from django.utils import timezone


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

    file_url = models.URLField()
    file_name = models.CharField(max_length=255)
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

    def save(self, *args, **kwargs):
        self.tags = _normalize_tags(self.tags)
        self.file_sha256 = (self.file_sha256 or '').strip().lower()

        if self.status == PublicationStatus.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()

        return super().save(*args, **kwargs)
