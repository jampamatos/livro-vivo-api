import re
from typing import Optional

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import HasAcceptedRequiredLegalDocuments
from entitlements.services import entitled_book_ids, user_has_subscription
from .models import (
    CHAPTER_SEARCH_CONFIG,
    Book,
    BookChapter,
    BookVersion,
    chapter_search_vector,
)
from .permissions import HasActiveBookEntitlement
from .serializers import (
    BookSerializer,
    BookVersionSerializer,
    ChapterBySlugResponseSerializer,
    ChapterSummaryResponseSerializer,
    CurrentBookVersionResponseSerializer,
    SearchResultSerializer,
)

def _parse_int_or_default(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _make_snippet(text: str, q: str, window: int = 140) -> str:
    """Gera um trecho contextual da busca, com destaque aproximado do termo."""
    if not text:
        return ''

    lower_text = text.lower()
    lower_q = q.lower()

    idx = lower_text.find(lower_q)
    if idx == -1:
        # Fallback: começo do texto.
        snippet = text[: (window * 2)].strip()
        return (snippet + '...') if len(text) > len(snippet) else snippet

    before = min(40, window)
    after = (window * 2) - before

    start = max(0, idx - before)
    end = min(len(text), idx + len(q) + after)

    snippet = text[start:end].strip()
    if start > 0:
        snippet = '...' + snippet
    if end < len(text):
        snippet = snippet + '...'
    return snippet


def _find_occurrences(text: str, q: str) -> list[tuple[int, int]]:
    if not text or not q:
        return []
    pattern = re.compile(re.escape(q), flags=re.IGNORECASE)
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def _cluster_occurrences(
    occurrences: list[tuple[int, int]],
    *,
    merge_gap: int = 24,
    max_clusters: int = 8,
) -> list[tuple[int, int]]:
    """
    Agrupa ocorrências próximas em um único intervalo.
    Evita explosão de resultados quando a palavra aparece muito colada.
    """
    if not occurrences:
        return []

    clusters: list[list[int]] = []
    for start, end in occurrences:
        if not clusters:
            clusters.append([start, end])
            continue

        last_start, last_end = clusters[-1]
        if start - last_end <= merge_gap:
            clusters[-1][1] = max(last_end, end)
        else:
            clusters.append([start, end])

    return [(start, end) for start, end in clusters[:max_clusters]]


def _make_snippet_from_offsets(text: str, start: int, end: int, context: int = 120) -> str:
    if not text:
        return ''
    left = max(0, start - context)
    right = min(len(text), end + context)
    snippet = text[left:right].strip()
    if left > 0:
        snippet = '...' + snippet
    if right < len(text):
        snippet += '...'
    return snippet


class BookListView(APIView):
    """Lista livros visíveis ao usuário."""

    permission_classes = [HasAcceptedRequiredLegalDocuments, HasActiveBookEntitlement]

    def get(self, request):
        qs = Book.objects.all().order_by('-updated_at')

        # staff vê tudo
        if request.user.is_staff:
            data = BookSerializer(qs, many=True).data
            return Response({'books': data})
        
        # usuário comum vê apenas livros publicados
        qs = qs.filter(status=Book.Status.PUBLISHED)

        # subscription vê todos os livros publicados
        if user_has_subscription(request.user):
            data = BookSerializer(qs, many=True).data
            return Response({'books': data})
        
        # sem subscription, filtra por entitlement explícito do book
        allowed_ids = entitled_book_ids(request.user)
        qs = qs.filter(id__in=allowed_ids)

        data = BookSerializer(qs, many=True).data
        return Response({'books': data})


class BookVersionListView(APIView):
    """Lista versões de um livro visível."""

    permission_classes = [HasAcceptedRequiredLegalDocuments, HasActiveBookEntitlement]

    def get(self, request, book_id: int):
        book = get_object_or_404(Book, pk=book_id)

        if book.status != Book.Status.PUBLISHED:
            raise NotFound()

        qs = (
            BookVersion.objects
            .filter(book=book, status=BookVersion.Status.PUBLISHED)
            .order_by('-published_at', '-created_at', '-id')
        )

        data = BookVersionSerializer(qs, many=True).data
        return Response({'book': BookSerializer(book).data, 'versions': data})


def _get_visible_book_for_user(*, user, book_id: int) -> Book:
    book = get_object_or_404(Book, pk=book_id)
    if book.status != Book.Status.PUBLISHED:
        raise NotFound()
    return book


def _get_current_visible_version_for_user(*, user, book: Book) -> BookVersion:
    qs = BookVersion.objects.filter(book=book, status=BookVersion.Status.PUBLISHED)
    current = qs.order_by('-published_at', '-created_at', '-id').first()
    if not current:
        raise NotFound()
    return current


class CurrentBookVersionView(APIView):
    """Retorna a versão atual (chapter-first) de um livro."""

    permission_classes = [HasAcceptedRequiredLegalDocuments, HasActiveBookEntitlement]

    def get(self, request, book_id: int):
        book = _get_visible_book_for_user(user=request.user, book_id=book_id)
        current = _get_current_visible_version_for_user(user=request.user, book=book)
        payload = {
            'book': book,
            'version': current,
        }
        return Response(CurrentBookVersionResponseSerializer(payload).data)


class CurrentBookChapterSummaryView(APIView):
    """Retorna sumário de capítulos da versão atual (chapter-first)."""

    permission_classes = [HasAcceptedRequiredLegalDocuments, HasActiveBookEntitlement]

    def get(self, request, book_id: int):
        book = _get_visible_book_for_user(user=request.user, book_id=book_id)
        current = _get_current_visible_version_for_user(user=request.user, book=book)
        chapters_qs = current.chapters.order_by('order', 'id')
        payload = {
            'book_id': book.id,
            'book_title': book.title,
            'book_version_id': current.id,
            'version': current.version,
            'chapters': chapters_qs,
        }
        return Response(ChapterSummaryResponseSerializer(payload).data)


class CurrentBookChapterBySlugView(APIView):
    """Retorna um capítulo da versão atual por slug (chapter-first)."""

    permission_classes = [HasAcceptedRequiredLegalDocuments, HasActiveBookEntitlement]

    def get(self, request, book_id: int, chapter_slug: str):
        book = _get_visible_book_for_user(user=request.user, book_id=book_id)
        current = _get_current_visible_version_for_user(user=request.user, book=book)

        chapter = get_object_or_404(
            BookChapter.objects.filter(book_version=current),
            slug=chapter_slug,
        )
        previous_chapter = (
            current.chapters
            .filter(order__lt=chapter.order)
            .order_by('-order', '-id')
            .only('slug')
            .first()
        )
        next_chapter = (
            current.chapters
            .filter(order__gt=chapter.order)
            .order_by('order', 'id')
            .only('slug')
            .first()
        )

        payload = {
            'book_id': book.id,
            'book_title': book.title,
            'book_version_id': current.id,
            'version': current.version,
            'chapter': chapter,
            'previous_slug': previous_chapter.slug if previous_chapter else None,
            'next_slug': next_chapter.slug if next_chapter else None,
        }
        return Response(ChapterBySlugResponseSerializer(payload).data)


class SearchView(APIView):
    """Busca por capítulos com FTS em Postgres e fallback para SQLite."""

    permission_classes = [HasAcceptedRequiredLegalDocuments, HasActiveBookEntitlement]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'library_search'

    def get(self, request, book_id: Optional[int] = None):
        q = (request.query_params.get('q') or '').strip()
        book_version_id = request.query_params.get('book_version_id')

        # book_id pode vir do path (/books/<id>/search/) ou da querystring (/search/?book_id=...)
        book_id_qp = request.query_params.get('book_id')
        if book_id is not None:
            book_id_qp = str(book_id)

        # Paginação simples.
        limit = _parse_int_or_default(request.query_params.get('limit', 20), 20)
        offset = _parse_int_or_default(request.query_params.get('offset', 0), 0)

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        if not q:
            return Response({'detail': "Query param 'q' is required."}, status=status.HTTP_400_BAD_REQUEST)

        if len(q) < 2:
            return Response({'detail': "Query param 'q' must have at least 2 character"}, status=status.HTTP_400_BAD_REQUEST)

        if not book_version_id and not book_id_qp:
            return Response(
                {'detail': "Provide either 'book_version' or 'book_id'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        chapters = BookChapter.objects.select_related('book_version', 'book_version__book')

        # Filtros de visibilidade (usuário comum só vê publicados)
        if not request.user.is_staff:
            chapters = chapters.filter(
                book_version__status=BookVersion.Status.PUBLISHED,
                book_version__book__status=Book.Status.PUBLISHED,
            )

        # escolhe escopo
        if book_version_id:
            try:
                bv_id = int(book_version_id)
            except ValueError:
                return Response({'detail': "'book_version_id' must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

            chapters = chapters.filter(book_version_id=bv_id)

        elif book_id_qp:
            try:
                b_id = int(book_id_qp)
            except ValueError:
                return Response({'detail': "'book_id' must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

            chapters = chapters.filter(book_version__book_id=b_id)

        if connection.vendor == 'postgresql':
            query = SearchQuery(
                q,
                config=CHAPTER_SEARCH_CONFIG,
                search_type='websearch',
            )
            qs = (
                chapters
                .annotate(search_vector=chapter_search_vector())
                .filter(search_vector=query)
                .annotate(
                    rank=SearchRank(F('search_vector'), query),
                )
                .order_by('-rank', 'book_version_id', 'order', 'id')
            )
        else:
            qs = (
                chapters
                .filter(Q(title__icontains=q) | Q(content_plain__icontains=q))
                .order_by('book_version_id', 'order', 'id')
            )

        results = []
        for row in qs:
            bv = row.book_version
            b = bv.book
            chapter_text = row.content_plain or ''
            occurrences = _cluster_occurrences(_find_occurrences(chapter_text, q))

            if not occurrences:
                occurrences = [(0, 0)]

            for occurrence_idx, (match_start, match_end) in enumerate(occurrences, start=1):
                snippet = (
                    _make_snippet_from_offsets(chapter_text, match_start, match_end)
                    if match_end > match_start
                    else _make_snippet(chapter_text, q)
                )
                results.append(
                    {
                        'book_id': b.id,
                        'book_title': b.title,
                        'book_version_id': bv.id,
                        'version': bv.version,
                        'chapter_id': row.id,
                        'chapter_slug': row.slug,
                        'chapter_title': row.title,
                        'chapter_order': row.order,
                        'occurrence': occurrence_idx,
                        'match_start': match_start,
                        'match_end': match_end,
                        'snippet': snippet,
                    }
                )

        total = len(results)
        page = results[offset : offset + limit]

        data = {
            'q': q,
            'count': total,
            'limit': limit,
            'offset': offset,
            'results': SearchResultSerializer(page, many=True).data,
        }

        return Response(data)
