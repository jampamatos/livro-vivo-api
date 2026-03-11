from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from annotations.models import Annotation
from library.models import BookChapter, BookVersion


def _build_excerpt(annotation: Annotation) -> str:
    if (annotation.excerpt or '').strip():
        return annotation.excerpt.strip()

    source_plain = annotation.chapter.content_plain or ''
    if not source_plain:
        return ''

    start = max(0, annotation.start_offset)
    end = max(start, annotation.end_offset)
    return source_plain[start:end].strip()


def _clamp_offsets(*, source_start: int, source_end: int, target_plain: str) -> tuple[int, int]:
    text_len = len(target_plain or '')
    if text_len == 0:
        return (0, 0)

    start = max(0, min(source_start, text_len - 1))
    end = max(start + 1, min(source_end, text_len))
    if end <= start:
        end = min(text_len, start + 1)
    return (start, end)


def _resolve_target_chapter(
    *,
    source_chapter: BookChapter,
    target_by_slug: dict[str, BookChapter],
    target_by_order: dict[int, BookChapter],
) -> BookChapter | None:
    by_slug = target_by_slug.get(source_chapter.slug)
    if by_slug:
        return by_slug
    return target_by_order.get(source_chapter.order)


def _compute_target_range(
    *,
    annotation: Annotation,
    target_chapter: BookChapter,
) -> tuple[int, int, str, bool]:
    target_plain = target_chapter.content_plain or ''
    excerpt = _build_excerpt(annotation)

    if excerpt and target_plain:
        idx = target_plain.find(excerpt)
        if idx < 0:
            idx = target_plain.lower().find(excerpt.lower())
        if idx >= 0:
            start = idx
            end = min(len(target_plain), idx + len(excerpt))
            if len(target_plain) > 0 and end <= start:
                end = min(len(target_plain), start + 1)
            normalized_excerpt = (target_plain[start:end] or excerpt).strip()
            return (start, end, normalized_excerpt, True)

    start, end = _clamp_offsets(
        source_start=annotation.start_offset,
        source_end=annotation.end_offset,
        target_plain=target_plain,
    )
    normalized_excerpt = (target_plain[start:end] or excerpt).strip()
    return (start, end, normalized_excerpt, False)


class Command(BaseCommand):
    help = (
        'Migra anotacoes de uma versao de livro para outra versao do mesmo livro, '
        'mapeando capitulos por slug (fallback por order).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--from-version-id',
            type=int,
            required=True,
            help='ID da versao de origem das anotacoes.',
        )
        parser.add_argument(
            '--to-version-id',
            type=int,
            required=True,
            help='ID da versao de destino das anotacoes.',
        )
        parser.add_argument(
            '--user-id',
            action='append',
            type=int,
            default=[],
            help='Filtra migracao para um usuario especifico. Pode repetir o parametro.',
        )
        parser.add_argument(
            '--move',
            action='store_true',
            help='Remove anotacoes da versao antiga apos copiar (somente sucesso/duplicadas).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula a migracao sem persistir mudancas.',
        )

    def handle(self, *args, **options):
        from_version = BookVersion.objects.select_related('book').filter(
            id=options['from_version_id']
        ).first()
        if not from_version:
            raise CommandError('Versao de origem nao encontrada.')

        to_version = BookVersion.objects.select_related('book').filter(
            id=options['to_version_id']
        ).first()
        if not to_version:
            raise CommandError('Versao de destino nao encontrada.')

        if from_version.id == to_version.id:
            raise CommandError('Origem e destino nao podem ser a mesma versao.')

        if from_version.book_id != to_version.book_id:
            raise CommandError('Origem e destino precisam pertencer ao mesmo livro.')

        source_qs = Annotation.objects.filter(book_version=from_version).select_related('chapter')
        if options['user_id']:
            source_qs = source_qs.filter(user_id__in=options['user_id'])

        source_annotations = list(source_qs.order_by('id'))
        if not source_annotations:
            self.stdout.write(self.style.WARNING('Nenhuma anotacao para migrar com os filtros informados.'))
            return

        target_chapters = list(to_version.chapters.all())
        target_by_slug = {chapter.slug: chapter for chapter in target_chapters}
        target_by_order = {chapter.order: chapter for chapter in target_chapters}

        existing_keys = set(
            Annotation.objects.filter(book_version=to_version).values_list(
                'user_id',
                'chapter_id',
                'start_offset',
                'end_offset',
                'excerpt',
                'note',
                'color',
            )
        )

        created_count = 0
        moved_count = 0
        duplicate_count = 0
        skipped_missing_chapter = 0
        matched_by_excerpt = 0
        matched_by_offsets = 0
        planned_objects: list[Annotation] = []
        source_ids_to_delete: list[int] = []

        for source in source_annotations:
            target_chapter = _resolve_target_chapter(
                source_chapter=source.chapter,
                target_by_slug=target_by_slug,
                target_by_order=target_by_order,
            )
            if not target_chapter:
                skipped_missing_chapter += 1
                continue

            start, end, excerpt, excerpt_matched = _compute_target_range(
                annotation=source,
                target_chapter=target_chapter,
            )
            if excerpt_matched:
                matched_by_excerpt += 1
            else:
                matched_by_offsets += 1

            dedup_key = (
                source.user_id,
                target_chapter.id,
                start,
                end,
                excerpt,
                source.note,
                source.color,
            )
            if dedup_key in existing_keys:
                duplicate_count += 1
                if options['move']:
                    source_ids_to_delete.append(source.id)
                continue

            planned_objects.append(
                Annotation(
                    user_id=source.user_id,
                    book_version=to_version,
                    chapter=target_chapter,
                    selector=source.selector or {},
                    start_offset=start,
                    end_offset=end,
                    excerpt=excerpt,
                    note=source.note,
                    color=source.color,
                )
            )
            existing_keys.add(dedup_key)
            created_count += 1
            if options['move']:
                source_ids_to_delete.append(source.id)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY-RUN: nenhuma alteracao foi persistida.'))
        else:
            with transaction.atomic():
                if planned_objects:
                    Annotation.objects.bulk_create(planned_objects, batch_size=500)
                if source_ids_to_delete:
                    moved_count = Annotation.objects.filter(id__in=source_ids_to_delete).delete()[0]

        self.stdout.write(
            self.style.SUCCESS(
                (
                    'Migracao de anotacoes concluida: '
                    f'book_id={from_version.book_id} '
                    f'from_version_id={from_version.id} '
                    f'to_version_id={to_version.id} '
                    f'source={len(source_annotations)} '
                    f'created={created_count} '
                    f'duplicates={duplicate_count} '
                    f'skipped_missing_chapter={skipped_missing_chapter} '
                    f'matched_by_excerpt={matched_by_excerpt} '
                    f'matched_by_offsets={matched_by_offsets} '
                    f'moved={moved_count if not options["dry_run"] else 0} '
                    f'dry_run={bool(options["dry_run"])}'
                )
            )
        )
