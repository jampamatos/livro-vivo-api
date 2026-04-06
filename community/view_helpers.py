from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.utils import timezone

from accounts.roles import user_is_moderator_or_above

from .models import Comment, CommentLike, Post, PostFollow, PostLike, Report, ReportModerationAction
from .serializers import PostSerializer

User = get_user_model()


def build_post_queryset(*, request_user, category_id: str | None = None):
    queryset = Post.objects.select_related('author', 'author__profile', 'category').all()
    if request_user and request_user.is_authenticated:
        queryset = queryset.annotate(
            is_following=Exists(
                PostFollow.objects.filter(
                    post_id=OuterRef('pk'),
                    user_id=request_user.id,
                    is_active=True,
                )
            ),
            liked_by_me=Exists(
                PostLike.objects.filter(
                    post_id=OuterRef('pk'),
                    user_id=request_user.id,
                    is_active=True,
                )
            ),
        )

    if not user_is_moderator_or_above(request_user):
        queryset = queryset.filter(moderation_state=Post.ModerationState.ACTIVE)

    if category_id:
        queryset = queryset.filter(category_id=category_id)
    return queryset


def build_comment_queryset(*, request_user, post_id: str | None = None):
    queryset = Comment.objects.select_related('author', 'author__profile', 'post').all()
    if request_user and request_user.is_authenticated:
        queryset = queryset.annotate(
            liked_by_me=Exists(
                CommentLike.objects.filter(
                    comment_id=OuterRef('pk'),
                    user_id=request_user.id,
                    is_active=True,
                )
            )
        )
    if not user_is_moderator_or_above(request_user):
        queryset = queryset.filter(moderation_state=Comment.ModerationState.ACTIVE)
    if post_id:
        queryset = queryset.filter(post_id=post_id)
    return queryset


def build_report_queryset(*, status_filter: str = '', priority_filter: str = '', decision_filter: str = ''):
    queryset = (
        Report.objects
        .select_related("reporter", "post", "comment", "assigned_moderator", "moderated_by")
        .prefetch_related("moderation_actions__actor")
        .all()
    )

    if status_filter:
        queryset = queryset.filter(status=status_filter)
    if priority_filter:
        queryset = queryset.filter(priority=priority_filter)
    if decision_filter:
        queryset = queryset.filter(decision=decision_filter)
    return queryset


def build_mention_candidates(*, post: Post, request=None, query: str = '') -> list[dict[str, str | int | None]]:
    normalized_query = (query or '').strip().lower()
    participant_user_ids = set(
        Comment.objects.filter(post_id=post.id).values_list('author_id', flat=True).distinct()
    )
    participant_user_ids.add(post.author_id)

    users = User.objects.filter(id__in=participant_user_ids).select_related('profile').all()
    payload = []
    for user in users:
        display_name = PostSerializer._resolve_author_display(user)
        if normalized_query and normalized_query not in display_name.lower():
            continue
        avatar_url = PostSerializer._resolve_author_avatar_url(user)
        if avatar_url and avatar_url.startswith('/') and request is not None:
            avatar_url = request.build_absolute_uri(avatar_url)
        payload.append(
            {
                'id': user.id,
                'display_name': display_name,
                'avatar_url': avatar_url,
            }
        )

    payload.sort(key=lambda item: str(item['display_name']).lower())
    return payload[:20]


def parse_mention_user_ids(raw_value):
    if raw_value in (None, ''):
        return []
    if not isinstance(raw_value, list):
        from rest_framework.exceptions import ValidationError

        raise ValidationError({'mention_user_ids': 'Envie uma lista de IDs de usuários.'})

    normalized_ids = []
    for value in raw_value:
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            from rest_framework.exceptions import ValidationError

            raise ValidationError({'mention_user_ids': 'Todos os itens devem ser IDs numéricos.'})
        if user_id <= 0:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({'mention_user_ids': 'Todos os IDs devem ser maiores que zero.'})
        normalized_ids.append(user_id)
    return sorted(set(normalized_ids))


def report_update_snapshot(report: Report) -> dict[str, str | int | None]:
    return {
        "status": report.status,
        "priority": report.priority,
        "decision": report.decision,
        "assigned_moderator_id": report.assigned_moderator_id,
        "moderation_note": report.moderation_note,
    }


def register_report_update_audit(*, report: Report, before: dict[str, str | int | None], actor) -> None:
    status_changed = before["status"] != report.status
    priority_changed = before["priority"] != report.priority
    assigned_changed = before["assigned_moderator_id"] != report.assigned_moderator_id
    decision_changed = before["decision"] != report.decision
    note_changed = before["moderation_note"] != report.moderation_note

    if not any([status_changed, priority_changed, assigned_changed, decision_changed, note_changed]):
        return

    if status_changed:
        action_type = ReportModerationAction.ActionType.STATUS_CHANGED
    elif priority_changed:
        action_type = ReportModerationAction.ActionType.PRIORITY_CHANGED
    elif assigned_changed:
        action_type = ReportModerationAction.ActionType.ASSIGNED
    else:
        action_type = ReportModerationAction.ActionType.STATUS_CHANGED

    report.moderated_by = actor
    report.moderated_at = timezone.now()
    report.save(update_fields=["moderated_by", "moderated_at", "updated_at"])

    ReportModerationAction.objects.create(
        report=report,
        actor=actor,
        action_type=action_type,
        from_status=before["status"],
        to_status=report.status,
        from_priority=before["priority"],
        to_priority=report.priority,
        decision=report.decision,
        note=(report.moderation_note or "").strip(),
    )
