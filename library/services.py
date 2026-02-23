from __future__ import annotations

from datetime import date

from django.db import transaction

from .models import BookChapter, BookVersion


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

    return created_version
