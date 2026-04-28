from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils import timezone

from config.storage import get_avatar_storage


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
    avatar = models.ImageField(storage=get_avatar_storage, upload_to='avatars/', blank=True, null=True)
    avatar_url = models.URLField(max_length=500, blank=True, default='')
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        should_be_staff = self.role in {self.Role.MODERATOR, self.Role.OWNER} or self.user.is_superuser
        if self.user.is_staff != should_be_staff:
            self.user.is_staff = should_be_staff
            self.user.save(update_fields=['is_staff'])

    def delete(self, *args, **kwargs):
        avatar_storage = self.avatar.storage if self.avatar and self.avatar.name else None
        avatar_name = self.avatar.name if self.avatar and self.avatar.name else ''
        super().delete(*args, **kwargs)
        if avatar_storage and avatar_name:
            avatar_storage.delete(avatar_name)

    def __str__(self) -> str:
        return self.full_name or self.user.email or self.user.username or f'Usuário #{self.user_id}'


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
        return f'Solicitação de privacidade #{self.pk or "nova"} ({self.get_status_display()})'


class ExternalIdentity(models.Model):
    """Identidade externa vinculada a um usuário local."""

    class Provider(models.TextChoices):
        GOOGLE = 'google', 'Google'
        LINKEDIN = 'linkedin', 'LinkedIn'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='external_identities',
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    provider_subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default='')
    email_verified = models.BooleanField(default=False)
    display_name = models.CharField(max_length=255, blank=True, default='')
    avatar_url = models.URLField(max_length=500, blank=True, default='')
    linked_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    provider_claims = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_subject'],
                name='uniq_external_identity_provider_subject',
            ),
            models.UniqueConstraint(
                fields=['user', 'provider'],
                name='uniq_external_identity_per_user_provider',
            ),
        ]
        ordering = ['provider', '-linked_at']

    def __str__(self) -> str:
        label = self.display_name or self.email or self.provider_subject
        return f'{self.get_provider_display()} - {label}'


class LegalDocumentVersion(models.Model):
    """Versão auditável de um documento jurídico exibido ao usuário."""

    class DocumentType(models.TextChoices):
        TERMS_OF_USE = 'terms_of_use', 'Terms of use'
        PRIVACY_POLICY = 'privacy_policy', 'Privacy policy'

    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    version = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    content_html = models.TextField()
    content_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    is_active = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    enforcement_starts_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['document_type', 'version'],
                name='uniq_legal_document_type_version',
            ),
            models.UniqueConstraint(
                fields=['document_type'],
                condition=models.Q(is_active=True),
                name='uniq_active_legal_document_per_type',
            ),
        ]
        ordering = ['document_type', '-published_at', '-created_at']

    @property
    def is_published(self) -> bool:
        return self.published_at is not None

    def _should_skip_active_constraint_validation(self, constraint) -> bool:
        return (
            self.is_active
            and getattr(constraint, 'name', '') == 'uniq_active_legal_document_per_type'
            and tuple(getattr(constraint, 'fields', ())) == ('document_type',)
        )

    def clean(self):
        if not self.pk:
            return

        previous = type(self).objects.filter(pk=self.pk).only(
            'document_type',
            'version',
            'title',
            'content_html',
            'published_at',
        ).first()
        if not previous or not previous.published_at:
            return

        immutable_field_names = ('document_type', 'version', 'title', 'content_html')
        changed_fields = [
            field_name
            for field_name in immutable_field_names
            if getattr(previous, field_name) != getattr(self, field_name)
        ]
        if changed_fields:
            raise ValidationError(
                {
                    field_name: 'Esta versão já foi publicada e não pode mais alterar o conteúdo auditável.'
                    for field_name in changed_fields
                }
            )

    def validate_constraints(self, exclude=None):
        constraints = self.get_constraints()
        using = router.db_for_write(self.__class__, instance=self)

        errors = {}
        for model_class, model_constraints in constraints:
            for constraint in model_constraints:
                if self._should_skip_active_constraint_validation(constraint):
                    continue
                try:
                    constraint.validate(model_class, self, exclude=exclude, using=using)
                except ValidationError as e:
                    if (
                        getattr(e, 'code', None) == 'unique'
                        and len(getattr(constraint, 'fields', ())) == 1
                    ):
                        errors.setdefault(constraint.fields[0], []).append(e)
                    else:
                        errors = e.update_error_dict(errors)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.content_sha256 = hashlib.sha256((self.content_html or '').encode('utf-8')).hexdigest()
        if self.is_active and self.published_at is None:
            self.published_at = timezone.now()
        if self.is_active and self.enforcement_starts_at is None:
            self.enforcement_starts_at = self.published_at or timezone.now()

        with transaction.atomic():
            if self.is_active:
                type(self).objects.filter(
                    document_type=self.document_type,
                    is_active=True,
                ).exclude(pk=self.pk).update(is_active=False)
            super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.get_document_type_display()} v{self.version}'


class UserLegalAcceptance(models.Model):
    """Aceite auditável de uma versão específica de documento legal."""

    class Source(models.TextChoices):
        LOGIN_GATE = 'login_gate', 'Login gate'
        ACCOUNT_SETTINGS = 'account_settings', 'Account settings'
        ADMIN = 'admin', 'Admin'

    class AppPlatform(models.TextChoices):
        WEB = 'web', 'Web'
        ANDROID = 'android', 'Android'
        IOS = 'ios', 'iOS'
        SYSTEM = 'system', 'System'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='legal_acceptances',
    )
    document = models.ForeignKey(
        LegalDocumentVersion,
        on_delete=models.PROTECT,
        related_name='acceptances',
    )
    accepted_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=32, choices=Source.choices, default=Source.LOGIN_GATE)
    app_platform = models.CharField(max_length=16, choices=AppPlatform.choices, default=AppPlatform.WEB)
    app_version = models.CharField(max_length=64, blank=True, default='')
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'document'],
                name='uniq_user_legal_acceptance_per_document',
            ),
        ]
        ordering = ['-accepted_at']

    def __str__(self) -> str:
        return f'{self.user} - {self.document}'


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
        return f'Preferências de notificação de usuário #{self.user_id}'


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
        return f'Evento de notificação #{self.pk or "novo"} ({self.get_event_type_display()})'


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
        return f'Envio de notificação #{self.pk or "novo"} ({self.get_status_display()})'


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
    installation_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    expo_push_token = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    disabled_reason = models.CharField(max_length=160, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen_at', '-created_at']

    def __str__(self) -> str:
        return f'Dispositivo push #{self.pk or "novo"} ({self.get_platform_display()})'
