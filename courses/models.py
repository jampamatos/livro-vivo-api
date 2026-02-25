import re
from html import unescape

from django.db import models
from django.utils import timezone


def _to_plain_text(value: str) -> str:
    if not value:
        return ''
    text = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    text = re.sub(r'</(p|h1|h2|h3|h4|h5|h6|li|blockquote)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s*\n\s*', '\n', text)
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(tag).strip() for tag in value if str(tag).strip()]


class PublicationStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    PUBLISHED = 'published', 'Published'
    ARCHIVED = 'archived', 'Archived'


class CoursePost(models.Model):
    class PostType(models.TextChoices):
        BLOG = 'blog', 'Blog'
        LESSON = 'lesson', 'Lesson'
        ANNOUNCEMENT = 'announcement', 'Announcement'

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    author_name = models.CharField(max_length=150, blank=True, default='')
    excerpt = models.TextField(blank=True, default='')
    content_rich = models.TextField(blank=True, default='')
    content_plain = models.TextField(blank=True, default='', editable=False)
    post_type = models.CharField(max_length=24, choices=PostType.choices, default=PostType.BLOG)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=PublicationStatus.choices, default=PublicationStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-updated_at', '-created_at']

    def __str__(self) -> str:
        return f'{self.title} ({self.status})'

    def save(self, *args, **kwargs):
        self.content_rich = self.content_rich or ''
        self.content_plain = _to_plain_text(self.content_rich)
        self.tags = _normalize_tags(self.tags)

        if self.status == PublicationStatus.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        return super().save(*args, **kwargs)


class CourseAsset(models.Model):
    class AssetType(models.TextChoices):
        PDF = 'pdf', 'PDF'
        CHECKLIST = 'checklist', 'Checklist'
        MODEL = 'model', 'Model'
        VIDEO = 'video', 'Video'
        LINK = 'link', 'Link'
        OTHER = 'other', 'Other'

    post = models.ForeignKey(
        CoursePost,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='assets',
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default='')
    asset_type = models.CharField(max_length=24, choices=AssetType.choices, default=AssetType.PDF)
    file_url = models.URLField(blank=True, default='')
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=PublicationStatus.choices, default=PublicationStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-updated_at', '-created_at']

    def __str__(self) -> str:
        return f'{self.title} ({self.asset_type})'

    def save(self, *args, **kwargs):
        self.tags = _normalize_tags(self.tags)
        if self.status == PublicationStatus.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        return super().save(*args, **kwargs)


class LiveEvent(models.Model):
    class EventType(models.TextChoices):
        LIVE_CLASS = 'live_class', 'Live class'
        MENTORING = 'mentoring', 'Mentoring'
        WEBINAR = 'webinar', 'Webinar'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SCHEDULED = 'scheduled', 'Scheduled'
        LIVE = 'live', 'Live'
        FINISHED = 'finished', 'Finished'
        CANCELED = 'canceled', 'Canceled'

    post = models.ForeignKey(
        CoursePost,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='live_events',
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default='')
    event_type = models.CharField(max_length=24, choices=EventType.choices, default=EventType.LIVE_CLASS)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    meeting_url = models.URLField(blank=True, default='')
    recording_url = models.URLField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-starts_at', '-updated_at', '-created_at']

    def __str__(self) -> str:
        return f'{self.title} ({self.status})'

# Create your models here.
