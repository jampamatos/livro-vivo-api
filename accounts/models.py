from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Informações extras do usuário."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    full_name = models.CharField(max_length=150, blank=True)
    profession = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:
        return f"Profile(user_id={self.user_id})"


class NotificationPreference(models.Model):
    """Preferências de notificações do usuário."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences',
    )
    notifications_enabled = models.BooleanField(default=True)
    book_version_updates_enabled = models.BooleanField(default=True)
    new_content_updates_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self) -> str:
        return f"NotificationPreference(user_id={self.user_id})"


class NotificationEvent(models.Model):
    """Evento notificável produzido pelo domínio."""

    class EventType(models.TextChoices):
        BOOK_VERSION_PUBLISHED = 'book_version_published', 'Book version published'
        CONTENT_PUBLISHED = 'content_published', 'Content published'

    event_type = models.CharField(max_length=48, choices=EventType.choices)
    dedup_key = models.CharField(max_length=128, unique=True)
    title = models.CharField(max_length=200, blank=True, default='')
    body = models.TextField(blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"NotificationEvent(type={self.event_type}, dedup_key={self.dedup_key})"


class NotificationDispatch(models.Model):
    """Fila de despacho por usuário/canal para integração com FCM/APNs."""

    class Channel(models.TextChoices):
        PUSH = 'push', 'Push'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SKIPPED = 'skipped', 'Skipped'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'

    event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name='dispatches',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_dispatches',
    )
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.PUSH)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reason = models.CharField(max_length=160, blank=True, default='')
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'user', 'channel'],
                name='uniq_notification_dispatch_per_event_user_channel',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return (
            f"NotificationDispatch(event_id={self.event_id}, user_id={self.user_id}, "
            f"channel={self.channel}, status={self.status})"
        )
