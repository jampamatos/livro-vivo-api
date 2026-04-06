from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
import logging

from django.conf import settings
from django.db import transaction
from django.utils.text import Truncator

from accounts.models import NotificationEvent
from accounts.services import enqueue_notification_event, get_active_subscription_user_ids
from .models import Book, BookChapter, BookVersion

logger = logging.getLogger('livro_vivo.notifications')
_suppressed_book_chapter_notification_version_ids: ContextVar[frozenset[int]] = ContextVar(
    'suppressed_book_chapter_notification_version_ids',
    default=frozenset(),
)


def _compact_text(value: str, *, length: int = 180) -> str:
    return Truncator((value or '').strip()).chars(length)


@contextmanager
def suppress_book_chapter_notifications_for_versions(*version_ids: int):
    normalized_ids = {int(version_id) for version_id in version_ids if version_id}
    if not normalized_ids:
        yield
        return

    current_ids = set(_suppressed_book_chapter_notification_version_ids.get())
    token = _suppressed_book_chapter_notification_version_ids.set(
        frozenset(current_ids | normalized_ids)
    )
    try:
        yield
    finally:
        _suppressed_book_chapter_notification_version_ids.reset(token)


def book_chapter_notifications_suppressed_for_version(*, version_id: int | None) -> bool:
    if not version_id:
        return False
    return int(version_id) in _suppressed_book_chapter_notification_version_ids.get()


def enqueue_book_version_publication_notifications(
    *,
    book_version: BookVersion,
) -> NotificationEvent | None:
    """Cria evento notificável e fila de dispatch para publicação de versão."""
    if not getattr(settings, 'NOTIFICATIONS_ENABLED', True):
        logger.info('book_version_notifications_skipped', extra={'reason': 'notifications_disabled_global'})
        return None
    if not book_version or not book_version.pk:
        logger.warning('book_version_notifications_skipped', extra={'reason': 'book_version_missing'})
        return None
    if book_version.status != BookVersion.Status.PUBLISHED:
        logger.info(
            'book_version_notifications_skipped',
            extra={
                'reason': 'book_version_not_published',
                'book_version_id': book_version.pk,
                'status': book_version.status,
            },
        )
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.BOOK_VERSION_PUBLISHED,
        dedup_key=f'book-version-published:{book_version.id}',
        title=f'Nova versão publicada: {book_version.book.title}',
        body=(book_version.changelog or '').strip(),
        payload={
            'book_id': book_version.book_id,
            'book_title': book_version.book.title,
            'book_version_id': book_version.id,
            'version': book_version.version,
            'published_at': book_version.published_at.isoformat() if book_version.published_at else None,
        },
        recipient_user_ids=get_active_subscription_user_ids(),
        preference_field='book_version_updates_enabled',
        preference_disabled_reason='book_updates_disabled',
    )


def enqueue_book_chapter_publication_notifications(
    *,
    book_chapter: BookChapter,
) -> NotificationEvent | None:
    if not getattr(settings, 'NOTIFICATIONS_ENABLED', True):
        logger.info('book_chapter_notifications_skipped', extra={'reason': 'notifications_disabled_global'})
        return None
    if not book_chapter or not book_chapter.pk:
        logger.warning('book_chapter_notifications_skipped', extra={'reason': 'book_chapter_missing'})
        return None

    book_version = book_chapter.book_version
    if book_version.status != BookVersion.Status.PUBLISHED:
        logger.info(
            'book_chapter_notifications_skipped',
            extra={
                'reason': 'book_version_not_published',
                'book_chapter_id': book_chapter.pk,
                'book_version_id': book_version.pk,
                'status': book_version.status,
            },
        )
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.CONTENT_PUBLISHED,
        dedup_key=f'book-chapter-published:{book_chapter.pk}',
        title=f'Novo capítulo disponível: {book_version.book.title}',
        body=_compact_text(f'{book_chapter.title}. {book_chapter.content_plain}'),
        payload={
            'resource_type': 'book_chapter',
            'book_id': book_version.book_id,
            'book_title': book_version.book.title,
            'book_version_id': book_version.pk,
            'book_version': book_version.version,
            'book_chapter_id': book_chapter.pk,
            'chapter_title': book_chapter.title,
            'chapter_slug': book_chapter.slug,
            'chapter_order': book_chapter.order,
            'created_at': book_chapter.created_at.isoformat() if book_chapter.created_at else None,
        },
        recipient_user_ids=get_active_subscription_user_ids(),
        preference_field='book_version_updates_enabled',
        preference_disabled_reason='book_updates_disabled',
    )


def schedule_book_version_publication_notifications(*, book_version: BookVersion) -> None:
    transaction.on_commit(
        lambda: enqueue_book_version_publication_notifications(book_version=book_version)
    )


def schedule_book_chapter_publication_notifications(*, book_chapter: BookChapter) -> None:
    transaction.on_commit(
        lambda: enqueue_book_chapter_publication_notifications(book_chapter=book_chapter)
    )


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
        if status == BookVersion.Status.PUBLISHED:
            (
                BookVersion.objects
                .filter(book=source_version.book)
                .exclude(status=BookVersion.Status.ARCHIVED)
                .update(status=BookVersion.Status.ARCHIVED)
            )

        created_version = BookVersion.objects.create(
            book=source_version.book,
            version=normalized_version,
            changelog=normalized_changelog,
            status=status,
            published_at=(
                published_at if status == BookVersion.Status.PUBLISHED else None
            ) or (date.today() if status == BookVersion.Status.PUBLISHED else None),
        )

        source_chapters = source_version.chapters.order_by('order', 'id')
        chapter_context = suppress_book_chapter_notifications_for_versions(created_version.id)
        with chapter_context:
            for chapter in source_chapters:
                BookChapter.objects.create(
                    book_version=created_version,
                    title=chapter.title,
                    slug=chapter.slug,
                    order=chapter.order,
                    content_rich=chapter.content_rich,
                )

        if created_version.status == BookVersion.Status.PUBLISHED:
            if created_version.book.status != Book.Status.PUBLISHED:
                created_version.book.status = Book.Status.PUBLISHED
                created_version.book.save(update_fields=['status'])
            schedule_book_version_publication_notifications(book_version=created_version)

    return created_version
