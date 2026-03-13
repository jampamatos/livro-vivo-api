from __future__ import annotations

from accounts.models import NotificationEvent
from accounts.services import enqueue_notification_event, get_active_subscription_user_ids
from django.db.models import Q
from django.utils import timezone

from .models import (
    Comment,
    CommentLike,
    ModerationConfig,
    Post,
    PostFollow,
    PostLike,
    Report,
    UserModerationEvent,
    UserModerationStatus,
)


def _count_removed_reports_for_user(user) -> int:
    return (
        Report.objects
        .filter(status=Report.Status.RESOLVED, decision=Report.Decision.REMOVE)
        .filter(Q(post__author=user) | Q(comment__author=user))
        .distinct()
        .count()
    )


def _issue_warning_if_threshold_reached(*, user, actor=None, report: Report | None = None, note: str = ''):
    status = UserModerationStatus.load_for_user(user)
    config = ModerationConfig.load()

    removed_reports_total = _count_removed_reports_for_user(user)
    warning_target = removed_reports_total // max(config.reports_per_warning, 1)
    warning_cap = max(config.max_warnings_before_ban, 1)
    next_warning_target = min(warning_target, warning_cap)

    if next_warning_target <= status.warnings_issued:
        if config.auto_ban_on_threshold and status.warnings_issued >= warning_cap and not status.is_banned:
            ban_user_from_app(
                user=user,
                actor=actor,
                reason='Auto ban after moderation warning threshold.',
                report=report,
            )
        return status

    now = timezone.now()
    status.warnings_issued = next_warning_target
    status.last_warning_at = now
    status.pending_login_message = config.render_warning_message(
        warning_number=status.warnings_issued,
        removed_reports_total=removed_reports_total,
    )
    status.pending_login_message_level = UserModerationStatus.PendingLevel.WARNING
    status.pending_login_message_created_at = now
    status.save(
        update_fields=[
            'warnings_issued',
            'last_warning_at',
            'pending_login_message',
            'pending_login_message_level',
            'pending_login_message_created_at',
            'updated_at',
        ]
    )

    UserModerationEvent.objects.create(
        user=user,
        actor=actor,
        report=report,
        action_type=UserModerationEvent.ActionType.WARNING_ISSUED,
        warning_number=status.warnings_issued,
        removed_reports_total=removed_reports_total,
        note=note or '',
    )

    if config.auto_ban_on_threshold and status.warnings_issued >= warning_cap and not status.is_banned:
        ban_user_from_app(
            user=user,
            actor=actor,
            reason='Auto ban after moderation warning threshold.',
            report=report,
        )

    return status


def register_report_remove_consequence(*, report: Report, actor=None, note: str = ''):
    target_user = report.target_author()
    if target_user is None:
        return None
    return _issue_warning_if_threshold_reached(user=target_user, actor=actor, report=report, note=note)


def get_effective_ban_scope(status: UserModerationStatus | None) -> str | None:
    if status is None or not status.is_banned:
        return None
    config = ModerationConfig.load()
    return config.ban_scope


def _apply_ban_scope_effects(*, user, target_scope: str, now=None):
    if target_scope == UserModerationStatus.BanScope.APP_WIDE:
        if user.is_active:
            user.is_active = False
            user.save(update_fields=['is_active'])
        return

    if not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])


def sync_user_activity_with_moderation(user):
    try:
        status = user.moderation_status
    except UserModerationStatus.DoesNotExist:
        return user

    effective_scope = get_effective_ban_scope(status)
    should_be_active = effective_scope != UserModerationStatus.BanScope.APP_WIDE
    if user.is_active != should_be_active:
        user.is_active = should_be_active
        user.save(update_fields=['is_active'])

    return user


def ban_user_from_app(
    *,
    user,
    actor=None,
    reason: str = '',
    report: Report | None = None,
    ban_scope: str | None = None,
):
    status = UserModerationStatus.load_for_user(user)
    now = timezone.now()

    config = ModerationConfig.load()
    target_scope = ban_scope or config.ban_scope
    existing_scope = status.ban_scope if status.is_banned else None
    upgrading_scope = (
        status.is_banned
        and existing_scope == UserModerationStatus.BanScope.COMMUNITY_ONLY
        and target_scope == UserModerationStatus.BanScope.APP_WIDE
    )

    if status.is_banned and not upgrading_scope:
        return status

    normalized_reason = (reason or '').strip()
    if not normalized_reason:
        normalized_reason = 'Ban applied by moderation.'

    status.is_banned = True
    status.ban_scope = target_scope
    status.banned_at = now
    status.banned_by = actor
    status.ban_reason = normalized_reason
    status.pending_login_message = config.render_ban_message(ban_scope=target_scope)
    status.pending_login_message_level = UserModerationStatus.PendingLevel.DANGER
    status.pending_login_message_created_at = now
    status.save(
        update_fields=[
            'is_banned',
            'ban_scope',
            'banned_at',
            'banned_by',
            'ban_reason',
            'pending_login_message',
            'pending_login_message_level',
            'pending_login_message_created_at',
            'updated_at',
        ]
    )

    _apply_ban_scope_effects(user=user, target_scope=target_scope, now=now)

    UserModerationEvent.objects.create(
        user=user,
        actor=actor,
        report=report,
        action_type=UserModerationEvent.ActionType.BAN_APPLIED,
        removed_reports_total=_count_removed_reports_for_user(user),
        note=normalized_reason,
    )

    return status


def pull_pending_login_notice(user):
    try:
        status = user.moderation_status
    except UserModerationStatus.DoesNotExist:
        return None

    message = (status.pending_login_message or '').strip()
    if not message:
        return None

    payload = {
        'level': status.pending_login_message_level,
        'message': message,
        'created_at': status.pending_login_message_created_at,
    }
    status.pending_login_message = ''
    status.pending_login_message_level = UserModerationStatus.PendingLevel.INFO
    status.pending_login_message_created_at = None
    status.save(
        update_fields=[
            'pending_login_message',
            'pending_login_message_level',
            'pending_login_message_created_at',
            'updated_at',
        ]
    )
    return payload


def get_banned_login_message(user) -> str | None:
    try:
        status = user.moderation_status
    except UserModerationStatus.DoesNotExist:
        return None

    effective_scope = get_effective_ban_scope(status)
    if effective_scope != UserModerationStatus.BanScope.APP_WIDE:
        return None

    custom_reason = (status.ban_reason or '').strip()
    if custom_reason:
        return (
            'Sua conta foi suspensa pela moderação. '
            f'Motivo: {custom_reason}'
        )

    config = ModerationConfig.load()
    return config.render_ban_message(ban_scope=effective_scope)


def get_user_moderation_summary(user) -> dict:
    try:
        status = user.moderation_status
    except UserModerationStatus.DoesNotExist:
        return {
            'is_banned': False,
            'ban_scope': None,
            'community_access': True,
            'app_access': True,
            'warnings_issued': 0,
        }

    return {
        'is_banned': bool(status.is_banned),
        'ban_scope': get_effective_ban_scope(status),
        'community_access': not bool(status.is_banned),
        'app_access': get_effective_ban_scope(status) != UserModerationStatus.BanScope.APP_WIDE,
        'warnings_issued': status.warnings_issued,
    }


def user_is_banned_from_community(user) -> bool:
    try:
        status = user.moderation_status
    except UserModerationStatus.DoesNotExist:
        return False
    return bool(status.is_banned)


def ensure_post_follow(*, post: Post, user) -> PostFollow:
    follow, created = PostFollow.objects.get_or_create(
        post=post,
        user=user,
        defaults={'is_active': True},
    )
    if not created and not follow.is_active:
        follow.is_active = True
        follow.save(update_fields=['is_active', 'updated_at'])
    return follow


def deactivate_post_follow(*, post: Post, user) -> None:
    PostFollow.objects.filter(post=post, user=user, is_active=True).update(
        is_active=False,
        updated_at=timezone.now(),
    )


def ensure_post_like(*, post: Post, user) -> PostLike:
    like, created = PostLike.objects.get_or_create(
        post=post,
        user=user,
        defaults={'is_active': True},
    )
    if not created and not like.is_active:
        like.is_active = True
        like.save(update_fields=['is_active', 'updated_at'])
    return like


def deactivate_post_like(*, post: Post, user) -> None:
    PostLike.objects.filter(post=post, user=user, is_active=True).update(
        is_active=False,
        updated_at=timezone.now(),
    )


def ensure_comment_like(*, comment: Comment, user) -> CommentLike:
    like, created = CommentLike.objects.get_or_create(
        comment=comment,
        user=user,
        defaults={'is_active': True},
    )
    if not created and not like.is_active:
        like.is_active = True
        like.save(update_fields=['is_active', 'updated_at'])
    return like


def deactivate_comment_like(*, comment: Comment, user) -> None:
    CommentLike.objects.filter(comment=comment, user=user, is_active=True).update(
        is_active=False,
        updated_at=timezone.now(),
    )


def enqueue_new_comment_notifications(*, comment):
    if not comment or not comment.pk or not comment.post_id or not comment.author_id:
        return None

    active_user_ids = set(get_active_subscription_user_ids())
    if not active_user_ids:
        return None

    follower_user_ids = list(
        PostFollow.objects.filter(post_id=comment.post_id, is_active=True)
        .exclude(user_id=comment.author_id)
        .values_list('user_id', flat=True)
        .distinct()
    )
    if not follower_user_ids:
        return None

    banned_user_ids = set(
        UserModerationStatus.objects.filter(user_id__in=follower_user_ids, is_banned=True)
        .values_list('user_id', flat=True)
    )
    recipient_user_ids = [
        user_id
        for user_id in follower_user_ids
        if user_id in active_user_ids and user_id not in banned_user_ids
    ]
    if not recipient_user_ids:
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
        dedup_key=f'community-comment-created:{comment.pk}',
        title=f'Nova interação na comunidade: {comment.post.title}',
        body=(comment.body or '').strip()[:180],
        payload={
            'post_id': comment.post_id,
            'post_title': comment.post.title,
            'comment_id': comment.pk,
            'author_id': comment.author_id,
            'author_display': str(comment.author),
        },
        recipient_user_ids=recipient_user_ids,
        preference_field='community_interaction_updates_enabled',
        preference_disabled_reason='community_interactions_disabled',
    )


def _resolve_user_display(user) -> str:
    profile = getattr(user, 'profile', None)
    full_name = (getattr(profile, 'full_name', '') or '').strip()
    if full_name:
        return full_name

    first_last = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
    if first_last:
        return first_last

    username = (user.username or '').strip()
    if username:
        if '@' in username:
            username = username.split('@', 1)[0].strip()
        if username:
            return username

    email = (user.email or '').strip()
    if email:
        return email.split('@', 1)[0].strip() or f'usuario-{user.pk}'
    return f'usuario-{user.pk}'


def enqueue_comment_mention_notifications(*, comment, mentioned_user_ids):
    if not comment or not comment.pk or not comment.post_id or not comment.author_id:
        return None

    normalized_ids = sorted({int(user_id) for user_id in (mentioned_user_ids or []) if user_id})
    if not normalized_ids:
        return None

    participant_user_ids = set(
        Comment.objects.filter(post_id=comment.post_id).values_list('author_id', flat=True).distinct()
    )
    participant_user_ids.add(comment.post.author_id)

    candidate_user_ids = [
        user_id for user_id in normalized_ids if user_id in participant_user_ids and user_id != comment.author_id
    ]
    if not candidate_user_ids:
        return None

    active_user_ids = set(get_active_subscription_user_ids())
    if not active_user_ids:
        return None

    banned_user_ids = set(
        UserModerationStatus.objects.filter(user_id__in=candidate_user_ids, is_banned=True)
        .values_list('user_id', flat=True)
    )
    recipient_user_ids = [
        user_id
        for user_id in candidate_user_ids
        if user_id in active_user_ids and user_id not in banned_user_ids
    ]
    if not recipient_user_ids:
        return None

    author_display = _resolve_user_display(comment.author)
    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
        dedup_key=f'community-comment-mention:{comment.pk}',
        title=f'Você foi mencionado: {comment.post.title}',
        body=f'{author_display} mencionou você em um comentário.',
        payload={
            'post_id': comment.post_id,
            'post_title': comment.post.title,
            'comment_id': comment.pk,
            'author_id': comment.author_id,
            'author_display': author_display,
            'mention_user_ids': recipient_user_ids,
        },
        recipient_user_ids=recipient_user_ids,
        preference_field='community_interaction_updates_enabled',
        preference_disabled_reason='community_interactions_disabled',
    )


def sync_banned_users_with_config(config: ModerationConfig | None = None):
    config = config or ModerationConfig.load()
    banned_statuses = (
        UserModerationStatus.objects
        .select_related('user')
        .filter(is_banned=True)
    )
    for status in banned_statuses:
        changed_fields = []
        if status.ban_scope != config.ban_scope:
            status.ban_scope = config.ban_scope
            changed_fields.append('ban_scope')

        if changed_fields:
            status.save(update_fields=changed_fields + ['updated_at'])

        _apply_ban_scope_effects(
            user=status.user,
            target_scope=config.ban_scope,
        )
