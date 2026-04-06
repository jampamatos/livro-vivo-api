from __future__ import annotations

from django.db import transaction
from django.utils.text import Truncator

from accounts.models import NotificationEvent
from accounts.services import enqueue_notification_event, get_active_subscription_user_ids
from entitlements.models import Subscription

from .models import CourseAsset, CoursePost, LiveEvent, PublicationStatus


def _eligible_professional_user_ids() -> list[int]:
    return get_active_subscription_user_ids(tiers=[Subscription.Tier.PROFESSIONAL])


def _compact_text(value: str, *, length: int = 160) -> str:
    return Truncator((value or '').strip()).chars(length)


def enqueue_course_post_publication_notifications(*, course_post: CoursePost) -> NotificationEvent | None:
    if not course_post or not course_post.pk or course_post.status != PublicationStatus.PUBLISHED:
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
        dedup_key=f'course-post-published:{course_post.pk}',
        title=f'Novo conteúdo do curso: {course_post.title}',
        body=_compact_text(course_post.excerpt or course_post.content_plain),
        payload={
            'resource_type': 'course_post',
            'course_post_id': course_post.pk,
            'title': course_post.title,
            'slug': course_post.slug,
            'post_type': course_post.post_type,
            'published_at': course_post.published_at.isoformat() if course_post.published_at else None,
        },
        recipient_user_ids=_eligible_professional_user_ids(),
        preference_field='new_content_updates_enabled',
        preference_disabled_reason='new_content_disabled',
    )


def schedule_course_post_publication_notifications(*, course_post: CoursePost) -> None:
    transaction.on_commit(
        lambda: enqueue_course_post_publication_notifications(course_post=course_post)
    )


def enqueue_course_asset_publication_notifications(*, course_asset: CourseAsset) -> NotificationEvent | None:
    if not course_asset or not course_asset.pk or course_asset.status != PublicationStatus.PUBLISHED:
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
        dedup_key=f'course-asset-published:{course_asset.pk}',
        title=f'Novo material do curso: {course_asset.title}',
        body=_compact_text(course_asset.description),
        payload={
            'resource_type': 'course_asset',
            'course_asset_id': course_asset.pk,
            'course_post_id': course_asset.post_id,
            'title': course_asset.title,
            'asset_type': course_asset.asset_type,
            'published_at': course_asset.published_at.isoformat() if course_asset.published_at else None,
            'file_url': course_asset.file_url,
        },
        recipient_user_ids=_eligible_professional_user_ids(),
        preference_field='new_content_updates_enabled',
        preference_disabled_reason='new_content_disabled',
    )


def schedule_course_asset_publication_notifications(*, course_asset: CourseAsset) -> None:
    transaction.on_commit(
        lambda: enqueue_course_asset_publication_notifications(course_asset=course_asset)
    )


def enqueue_live_event_notifications(*, live_event: LiveEvent) -> NotificationEvent | None:
    notifiable_statuses = {
        LiveEvent.Status.SCHEDULED,
        LiveEvent.Status.LIVE,
        LiveEvent.Status.FINISHED,
    }
    if not live_event or not live_event.pk or live_event.status not in notifiable_statuses:
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
        dedup_key=f'course-live-announced:{live_event.pk}',
        title=f'Nova live do curso: {live_event.title}',
        body=_compact_text(live_event.description or live_event.get_status_display()),
        payload={
            'resource_type': 'live_event',
            'live_event_id': live_event.pk,
            'course_post_id': live_event.post_id,
            'title': live_event.title,
            'event_type': live_event.event_type,
            'status': live_event.status,
            'starts_at': live_event.starts_at.isoformat() if live_event.starts_at else None,
            'meeting_url': live_event.meeting_url,
            'recording_url': live_event.recording_url,
        },
        recipient_user_ids=_eligible_professional_user_ids(),
        preference_field='new_content_updates_enabled',
        preference_disabled_reason='new_content_disabled',
    )


def schedule_live_event_notifications(*, live_event: LiveEvent) -> None:
    transaction.on_commit(
        lambda: enqueue_live_event_notifications(live_event=live_event)
    )
