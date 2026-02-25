from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import NotificationDispatch, NotificationEvent, NotificationPreference
from entitlements.models import Subscription
from .models import BookChapter, BookVersion


def enqueue_book_version_publication_notifications(
    *,
    book_version: BookVersion,
) -> NotificationEvent | None:
    """Cria evento notificável e fila de dispatch para publicação de versão."""
    if not getattr(settings, 'NOTIFICATIONS_ENABLED', True):
        return None
    if not book_version or not book_version.pk:
        return None
    if book_version.status != BookVersion.Status.PUBLISHED:
        return None

    dedup_key = f'book-version-published:{book_version.id}'
    event, created = NotificationEvent.objects.get_or_create(
        dedup_key=dedup_key,
        defaults={
            'event_type': NotificationEvent.EventType.BOOK_VERSION_PUBLISHED,
            'title': f'Nova versão publicada: {book_version.book.title}',
            'body': (book_version.changelog or '').strip(),
            'payload': {
                'book_id': book_version.book_id,
                'book_title': book_version.book.title,
                'book_version_id': book_version.id,
                'version': book_version.version,
                'published_at': book_version.published_at.isoformat() if book_version.published_at else None,
            },
        },
    )
    if not created:
        return event

    now = timezone.now()
    subscribed_user_ids = list(
        Subscription.objects.filter(status=Subscription.Status.ACTIVE)
        .filter(Q(started_at__isnull=True) | Q(started_at__lte=now))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list('user_id', flat=True)
        .distinct()
    )
    if not subscribed_user_ids:
        return event

    preference_by_user_id = {
        preference.user_id: preference
        for preference in NotificationPreference.objects.filter(user_id__in=subscribed_user_ids)
    }

    for user_id in subscribed_user_ids:
        preference = preference_by_user_id.get(user_id)
        notifications_enabled = (
            preference.notifications_enabled if preference is not None else True
        )
        book_updates_enabled = (
            preference.book_version_updates_enabled if preference is not None else True
        )
        push_enabled = preference.push_enabled if preference is not None else True

        status = NotificationDispatch.Status.PENDING
        reason = ''
        if not notifications_enabled:
            status = NotificationDispatch.Status.SKIPPED
            reason = 'notifications_disabled'
        elif not book_updates_enabled:
            status = NotificationDispatch.Status.SKIPPED
            reason = 'book_updates_disabled'
        elif not push_enabled:
            status = NotificationDispatch.Status.SKIPPED
            reason = 'push_disabled'

        NotificationDispatch.objects.get_or_create(
            event=event,
            user_id=user_id,
            channel=NotificationDispatch.Channel.PUSH,
            defaults={
                'status': status,
                'reason': reason,
            },
        )

    return event


def create_preloaded_book_version(
    *,
    source_version: BookVersion,
    new_version: str,
    changelog: str,
    status: str = BookVersion.Status.DRAFT,
    published_at: date | None = None,
) -> BookVersion:
    normalized_version = (new_version or '').strip()
    normalized_changelog = (changelog or '').strip()

    if not source_version or not source_version.pk:
        raise ValueError('Source version is required.')
    if not normalized_version:
        raise ValueError('New version identifier is required.')
    if not normalized_changelog:
        raise ValueError('Changelog is required.')
    if status not in BookVersion.Status.values:
        raise ValueError('Invalid target status.')
    if status == BookVersion.Status.PUBLISHED and not normalized_changelog:
        raise ValueError('Changelog is required when publishing a version.')

    with transaction.atomic():
        created_version = BookVersion.objects.create(
            book=source_version.book,
            version=normalized_version,
            changelog=normalized_changelog,
            status=status,
            published_at=published_at if status == BookVersion.Status.PUBLISHED else None,
        )

        source_chapters = source_version.chapters.order_by('order', 'id')
        for chapter in source_chapters:
            BookChapter.objects.create(
                book_version=created_version,
                title=chapter.title,
                slug=chapter.slug,
                order=chapter.order,
                content_rich=chapter.content_rich,
            )

        if created_version.status == BookVersion.Status.PUBLISHED:
            enqueue_book_version_publication_notifications(book_version=created_version)

    return created_version
