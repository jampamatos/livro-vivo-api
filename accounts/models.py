from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Informações extras do usuário."""

    class Role(models.TextChoices):
        MEMBER = 'member', 'Membro'
        MODERATOR = 'moderator', 'Moderador'
        OWNER = 'owner', 'Dono'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    full_name = models.CharField(max_length=150, blank=True)
    profession = models.CharField(max_length=120, blank=True)
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.role in {self.Role.MODERATOR, self.Role.OWNER} and not self.user.is_staff:
            self.user.is_staff = True
            self.user.save(update_fields=['is_staff'])

    def __str__(self) -> str:
        return f"Profile(user_id={self.user_id})"


class DataPrivacyRequest(models.Model):
    """Registro auditável de solicitações LGPD do próprio usuário."""

    class RequestType(models.TextChoices):
        EXPORT = 'export', 'Export'
        ERASURE = 'erasure', 'Erasure'

    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Requested'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='data_privacy_requests',
    )
    request_type = models.CharField(max_length=16, choices=RequestType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    retention_policy = models.TextField(blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return (
            f"DataPrivacyRequest(user_id={self.user_id}, "
            f"type={self.request_type}, status={self.status})"
        )


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
    community_interaction_updates_enabled = models.BooleanField(default=True)
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
        COURSE_CONTENT_PUBLISHED = 'course_content_published', 'Course content published'
        CASELAW_PUBLISHED = 'caselaw_published', 'Caselaw published'
        COMMUNITY_INTERACTION = 'community_interaction', 'Community interaction'

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
        IN_APP = 'in_app', 'In-app'

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
    acknowledged_at = models.DateTimeField(null=True, blank=True)
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


class PushDevice(models.Model):
    """Dispositivo registrado para recebimento de push via Expo."""

    class Platform(models.TextChoices):
        ANDROID = 'android', 'Android'
        IOS = 'ios', 'iOS'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_devices',
    )
    platform = models.CharField(max_length=16, choices=Platform.choices)
    expo_push_token = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    disabled_reason = models.CharField(max_length=160, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen_at', '-created_at']

    def __str__(self) -> str:
        return f"PushDevice(user_id={self.user_id}, platform={self.platform}, active={self.is_active})"
