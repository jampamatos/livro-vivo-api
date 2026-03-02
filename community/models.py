from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
    
    def __str__(self) -> str:
        return self.name

class Post(models.Model):
    class ModerationState(models.TextChoices):
        ACTIVE = 'active', 'Active'
        UNDER_REVIEW = 'under_review', 'Under review'
        REMOVED = 'removed', 'Removed'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_posts'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts',
    )

    title = models.CharField(max_length=200)
    body = models.TextField()
    moderation_state = models.CharField(
        max_length=16,
        choices=ModerationState.choices,
        default=ModerationState.ACTIVE,
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_moderated_posts',
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title

class Comment(models.Model):
    class ModerationState(models.TextChoices):
        ACTIVE = 'active', 'Active'
        UNDER_REVIEW = 'under_review', 'Under review'
        REMOVED = 'removed', 'Removed'

    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_comments'
    )
    body = models.TextField()
    moderation_state = models.CharField(
        max_length=16,
        choices=ModerationState.choices,
        default=ModerationState.ACTIVE,
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_moderated_comments',
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
    
    def __str__(self) -> str:
        return f"Comment #{self.pk} on Post #{self.post_id}"

class Report(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_REVIEW = 'in_review', 'In review'
        RESOLVED = 'resolved', 'Resolved'
        ESCALATED = 'escalated', 'Escalated'
        REJECTED = 'rejected', 'Rejected'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    class Decision(models.TextChoices):
        APPROVE = 'approve', 'Approve'
        REMOVE = 'remove', 'Remove'
        ESCALATE = 'escalate', 'Escalate'
        REJECT = 'reject', 'Reject'

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_reports'
    )

    post = models.ForeignKey(
        'Post',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reports',
    )
    comment = models.ForeignKey(
        'Comment',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reports',
    )

    reason = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM)
    decision = models.CharField(max_length=16, choices=Decision.choices, blank=True, default='')
    assigned_moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_assigned_reports',
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_moderated_reports',
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                check=(
                    (Q(post__isnull=False) & Q(comment__isnull=True)) |
                    (Q(post__isnull=True) & Q(comment__isnull=False))
                ),
                name='community_report_exactly_one_target',
            )
        ]

    @classmethod
    def allowed_status_transitions(cls):
        return {
            cls.Status.OPEN: {cls.Status.IN_REVIEW, cls.Status.RESOLVED, cls.Status.ESCALATED, cls.Status.REJECTED},
            cls.Status.IN_REVIEW: {cls.Status.RESOLVED, cls.Status.ESCALATED, cls.Status.REJECTED},
            cls.Status.ESCALATED: {cls.Status.IN_REVIEW, cls.Status.RESOLVED, cls.Status.REJECTED},
            cls.Status.RESOLVED: set(),
            cls.Status.REJECTED: set(),
        }

    def can_transition_to(self, new_status: str) -> bool:
        if new_status == self.status:
            return True
        return new_status in self.allowed_status_transitions().get(self.status, set())

    def _target_instance(self):
        return self.comment if self.comment_id else self.post

    def target_author(self):
        target = self._target_instance()
        if target is None:
            return None
        return getattr(target, 'author', None)

    def apply_decision_to_target(self, *, actor, decision: str, note: str = ''):
        target = self._target_instance()
        if target is None:
            return

        if decision == self.Decision.APPROVE:
            next_state = target.ModerationState.ACTIVE
        elif decision == self.Decision.REMOVE:
            next_state = target.ModerationState.REMOVED
        elif decision == self.Decision.ESCALATE:
            next_state = target.ModerationState.UNDER_REVIEW
        else:
            return

        update_fields = []
        if target.moderation_state != next_state:
            target.moderation_state = next_state
            update_fields.append('moderation_state')

        target.moderated_by = actor
        target.moderated_at = timezone.now()
        update_fields.extend(['moderated_by', 'moderated_at', 'updated_at'])

        normalized_note = (note or '').strip()
        if normalized_note:
            target.moderation_note = normalized_note
            update_fields.append('moderation_note')

        target.save(update_fields=list(dict.fromkeys(update_fields)))

    def register_staff_moderation(
        self,
        *,
        actor,
        action_type: str,
        next_status: str | None = None,
        next_priority: str | None = None,
        decision: str | None = None,
        note: str = '',
    ):
        from_status = self.status
        from_priority = self.priority

        if next_status and not self.can_transition_to(next_status):
            raise ValueError(f'Invalid report status transition: {self.status} -> {next_status}')

        changed_fields = []

        if next_status and next_status != self.status:
            self.status = next_status
            changed_fields.append('status')

        if next_priority and next_priority != self.priority:
            self.priority = next_priority
            changed_fields.append('priority')

        if decision is not None and decision != self.decision:
            self.decision = decision
            changed_fields.append('decision')

        normalized_note = (note or '').strip()
        if normalized_note:
            self.moderation_note = normalized_note
            changed_fields.append('moderation_note')

        if not changed_fields:
            return False

        self.moderated_by = actor
        self.moderated_at = timezone.now()
        changed_fields.extend(['moderated_by', 'moderated_at', 'updated_at'])

        self.save(update_fields=list(dict.fromkeys(changed_fields)))

        self.apply_decision_to_target(actor=actor, decision=self.decision, note=normalized_note)

        ReportModerationAction.objects.create(
            report=self,
            actor=actor,
            action_type=action_type,
            from_status=from_status,
            to_status=self.status,
            from_priority=from_priority,
            to_priority=self.priority,
            decision=self.decision,
            note=normalized_note,
        )

        if self.status == self.Status.RESOLVED and self.decision == self.Decision.REMOVE:
            from .services import register_report_remove_consequence

            register_report_remove_consequence(report=self, actor=actor, note=normalized_note)
        return True
    
    def __str__(self) -> str:
        target = f"Post #{self.post_id}" if self.post else f"Comment #{self.comment_id}"
        return f"Report #{self.pk} ({self.status}) - {target}"


class ReportModerationAction(models.Model):
    class ActionType(models.TextChoices):
        STATUS_CHANGED = 'status_changed', 'Status changed'
        APPROVED = 'approved', 'Approved'
        REMOVED = 'removed', 'Removed'
        ESCALATED = 'escalated', 'Escalated'
        REJECTED = 'rejected', 'Rejected'
        PRIORITY_CHANGED = 'priority_changed', 'Priority changed'
        ASSIGNED = 'assigned', 'Assigned'

    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name='moderation_actions',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_moderation_actions',
    )
    action_type = models.CharField(max_length=24, choices=ActionType.choices)
    from_status = models.CharField(max_length=16, choices=Report.Status.choices, blank=True, default='')
    to_status = models.CharField(max_length=16, choices=Report.Status.choices, blank=True, default='')
    from_priority = models.CharField(max_length=16, choices=Report.Priority.choices, blank=True, default='')
    to_priority = models.CharField(max_length=16, choices=Report.Priority.choices, blank=True, default='')
    decision = models.CharField(max_length=16, choices=Report.Decision.choices, blank=True, default='')
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'ReportAction #{self.pk} {self.action_type} for Report #{self.report_id}'


class ModerationConfig(models.Model):
    class BanScope(models.TextChoices):
        COMMUNITY_ONLY = 'community_only', 'Community only'
        APP_WIDE = 'app_wide', 'App wide'

    singleton_key = models.CharField(max_length=32, unique=True, default='default')
    reports_per_warning = models.PositiveIntegerField(default=3)
    max_warnings_before_ban = models.PositiveIntegerField(default=2)
    auto_ban_on_threshold = models.BooleanField(default=False)
    ban_scope = models.CharField(
        max_length=24,
        choices=BanScope.choices,
        default=BanScope.APP_WIDE,
    )
    warning_message_template = models.TextField(
        default=(
            'Recebemos {removed_reports_total} denúncia(s) procedentes em conteúdos da sua conta. '
            'Este é o aviso {warning_number} de {max_warnings_before_ban}.'
        )
    )
    ban_message_template = models.TextField(
        default=(
            'Sua conta foi suspensa por reincidência em violações da comunidade. '
            'Procure o suporte para revisão.'
        )
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Moderation config'
        verbose_name_plural = 'Moderation config'

    @classmethod
    def load(cls):
        config, _ = cls.objects.get_or_create(singleton_key='default')
        if config.reports_per_warning < 1:
            config.reports_per_warning = 1
            config.save(update_fields=['reports_per_warning', 'updated_at'])
        if config.max_warnings_before_ban < 1:
            config.max_warnings_before_ban = 1
            config.save(update_fields=['max_warnings_before_ban', 'updated_at'])
        return config

    def render_warning_message(self, *, warning_number: int, removed_reports_total: int) -> str:
        try:
            return self.warning_message_template.format(
                warning_number=warning_number,
                max_warnings_before_ban=self.max_warnings_before_ban,
                removed_reports_total=removed_reports_total,
                reports_per_warning=self.reports_per_warning,
            )
        except Exception:
            return (
                f'Recebemos {removed_reports_total} denúncia(s) procedentes em conteúdos da sua conta. '
                f'Este é o aviso {warning_number} de {self.max_warnings_before_ban}.'
            )

    def render_ban_message(self, *, ban_scope: str | None = None) -> str:
        message = (self.ban_message_template or '').strip()
        if message:
            return message
        if ban_scope == self.BanScope.COMMUNITY_ONLY:
            return (
                'Sua conta perdeu acesso à comunidade por reincidência em violações. '
                'Os demais módulos continuam disponíveis.'
            )
        return (
            'Sua conta foi suspensa por reincidência em violações da comunidade. '
            'Procure o suporte para revisão.'
        )

    def __str__(self) -> str:
        return 'Moderation config'


class UserModerationStatus(models.Model):
    class PendingLevel(models.TextChoices):
        INFO = 'info', 'Info'
        WARNING = 'warning', 'Warning'
        DANGER = 'danger', 'Danger'

    class BanScope(models.TextChoices):
        COMMUNITY_ONLY = 'community_only', 'Community only'
        APP_WIDE = 'app_wide', 'App wide'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='moderation_status',
    )
    warnings_issued = models.PositiveIntegerField(default=0)
    last_warning_at = models.DateTimeField(null=True, blank=True)
    is_banned = models.BooleanField(default=False)
    ban_scope = models.CharField(
        max_length=24,
        choices=BanScope.choices,
        default=BanScope.APP_WIDE,
    )
    banned_at = models.DateTimeField(null=True, blank=True)
    banned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_banned_users',
    )
    ban_reason = models.TextField(blank=True, default='')
    pending_login_message = models.TextField(blank=True, default='')
    pending_login_message_level = models.CharField(
        max_length=16,
        choices=PendingLevel.choices,
        default=PendingLevel.INFO,
    )
    pending_login_message_created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    @classmethod
    def load_for_user(cls, user):
        status, _ = cls.objects.get_or_create(user=user)
        return status

    def __str__(self) -> str:
        return f'UserModerationStatus(user_id={self.user_id}, warnings={self.warnings_issued}, banned={self.is_banned})'

    def denies_community_access(self) -> bool:
        return bool(self.is_banned)

    def denies_app_access(self) -> bool:
        return self.is_banned and self.ban_scope == self.BanScope.APP_WIDE


class UserModerationEvent(models.Model):
    class ActionType(models.TextChoices):
        WARNING_ISSUED = 'warning_issued', 'Warning issued'
        BAN_APPLIED = 'ban_applied', 'Ban applied'
        BAN_REVOKED = 'ban_revoked', 'Ban revoked'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='moderation_events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_moderation_events',
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_moderation_events',
    )
    action_type = models.CharField(max_length=24, choices=ActionType.choices)
    warning_number = models.PositiveIntegerField(null=True, blank=True)
    removed_reports_total = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'UserModerationEvent #{self.pk} {self.action_type} user={self.user_id}'
