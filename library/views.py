import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection
from django.db.models import F, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from entitlements.models import Entitlement
from entitlements.services import entitled_book_ids, user_has_book_entitlement, user_has_subscription
from .models import (
    CHAPTER_SEARCH_CONFIG,
    Book,
    BookChapter,
    BookVersion,
    PageText,
    chapter_search_vector,
)
from .permissions import HasActiveBookEntitlement
from .serializers import (
    BookSerializer,
    BookVersionSerializer,
    ChapterBySlugResponseSerializer,
    ChapterSummaryResponseSerializer,
    CurrentBookVersionResponseSerializer,
    PageTextSerializer,
    SearchResultSerializer,
)

logger = logging.getLogger(__name__)
DOWNLOAD_URL_TOKEN_PARAM = 'dl_token'
DOWNLOAD_URL_SIGNING_SALT = 'library.book-version-download.v1'


def _download_url_max_age_seconds() -> int:
    try:
        return max(1, int(getattr(settings, 'LIBRARY_DOWNLOAD_URL_TTL_SECONDS', 300)))
    except (TypeError, ValueError):
        return 300


def _append_query_param(url: str, key: str, value: str) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = value
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _build_download_token(*, user_id: int, book_id: int, version_id: int) -> str:
    payload = {'u': int(user_id), 'b': int(book_id), 'v': int(version_id)}
    return signing.dumps(payload, salt=DOWNLOAD_URL_SIGNING_SALT, compress=True)


def _load_download_token_payload(
    raw_token: str | None,
) -> dict | None:
    if not raw_token:
        return None

    try:
        payload = signing.loads(
            raw_token,
            salt=DOWNLOAD_URL_SIGNING_SALT,
            max_age=_download_url_max_age_seconds(),
        )
    except signing.BadSignature:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        token_user_id = int(payload.get('u'))
        token_book_id = int(payload.get('b'))
        token_version_id = int(payload.get('v'))
    except (TypeError, ValueError):
        return None

    return {'user_id': token_user_id, 'book_id': token_book_id, 'version_id': token_version_id}


def _user_has_active_download_scope(user_id: int, book_id: int) -> bool:
    User = get_user_model()
    user = User.objects.filter(pk=user_id).only('id', 'is_staff').first()
    if not user:
        return False
    if user.is_staff:
        return True

    now = timezone.now()
    has_any_active_entitlement = (
        Entitlement.objects
        .filter(user_id=user_id, status=Entitlement.Status.ACTIVE)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exists()
    )
    if not has_any_active_entitlement:
        return False

    return user_has_subscription(user) or user_has_book_entitlement(user, book_id)


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

    permission_classes = [HasActiveBookEntitlement]

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

    permission_classes = [HasActiveBookEntitlement]

    def get(self, request, book_id: int):
        book = get_object_or_404(Book, pk=book_id)

        if not request.user.is_staff and book.status != Book.Status.PUBLISHED:
            raise NotFound()

        qs = BookVersion.objects.filter(book=book).order_by('-created_at')

        if not request.user.is_staff:
            qs = qs.filter(status=BookVersion.Status.PUBLISHED)

        data = BookVersionSerializer(qs, many=True).data
        return Response({'book': BookSerializer(book).data, 'versions': data})


def _get_visible_book_for_user(*, user, book_id: int) -> Book:
    book = get_object_or_404(Book, pk=book_id)
    if not user.is_staff and book.status != Book.Status.PUBLISHED:
        raise NotFound()
    return book


def _get_current_visible_version_for_user(*, user, book: Book) -> BookVersion:
    qs = BookVersion.objects.filter(book=book)
    if not user.is_staff:
        qs = qs.filter(status=BookVersion.Status.PUBLISHED)
    current = qs.order_by('-created_at').first()
    if not current:
        raise NotFound()
    return current


class CurrentBookVersionView(APIView):
    """Retorna a versão atual (chapter-first) de um livro."""

    permission_classes = [HasActiveBookEntitlement]

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

    permission_classes = [HasActiveBookEntitlement]

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

    permission_classes = [HasActiveBookEntitlement]

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


class BookVersionDownloadUrlView(APIView):
    """Entrega URL absoluta para download do PDF da versão."""

    permission_classes = [HasActiveBookEntitlement]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'library_download_url'

    def get(self, request, book_id: int, version_id: int):
        bv = get_object_or_404(BookVersion, pk=version_id, book_id=book_id)

        if not request.user.is_staff and bv.status != BookVersion.Status.PUBLISHED:
            raise NotFound()

        if not bv.pdf:
            raise NotFound('PDF não está disponível para esta versão')

        base_download_url = request.build_absolute_uri(
            reverse('book-version-download', kwargs={'book_id': book_id, 'version_id': version_id})
        )
        signed_token = _build_download_token(
            user_id=request.user.id,
            book_id=book_id,
            version_id=version_id,
        )
        download_url = _append_query_param(
            base_download_url,
            DOWNLOAD_URL_TOKEN_PARAM,
            signed_token,
        )

        return Response({'url': download_url})


class BookVersionDownloadView(APIView):
    """Faz o streaming do PDF da versão solicitada."""

    permission_classes = [AllowAny]

    def get(self, request, book_id: int, version_id: int):
        raw_token = request.query_params.get(DOWNLOAD_URL_TOKEN_PARAM)
        payload = _load_download_token_payload(raw_token)
        authenticated_user_id = getattr(request.user, 'id', None)
        token_user_id = payload['user_id'] if payload else None
        if (
            not payload
            or payload['book_id'] != int(book_id)
            or payload['version_id'] != int(version_id)
            or (
                authenticated_user_id is not None
                and int(authenticated_user_id) != int(token_user_id)
            )
            or not _user_has_active_download_scope(payload['user_id'], book_id)
        ):
            logger.warning(
                'Rejected invalid/expired download token',
                extra={
                    'user_id': payload['user_id'] if payload else None,
                    'book_id': book_id,
                    'version_id': version_id,
                },
            )
            raise NotFound()

        bv = get_object_or_404(BookVersion, pk=version_id, book_id=book_id)

        if bv.status != BookVersion.Status.PUBLISHED:
            raise NotFound()

        if not bv.pdf:
            raise Http404()

        # Pega só o nome do arquivo para o header.
        filename = Path(bv.pdf.name).name
        response = FileResponse(bv.pdf.open('rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        logger.info(
            'Issued signed download response',
            extra={
                'user_id': payload['user_id'],
                'book_id': book_id,
                'version_id': version_id,
            },
        )
        return response


class SearchView(APIView):
    """Busca por capítulos com FTS em Postgres e fallback para SQLite."""

    permission_classes = [HasActiveBookEntitlement]
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
                        # Compat legado: page_number mapeado para ordem do capítulo.
                        'page_number': row.order,
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


class BookVersionPageTextView(APIView):
    """Retorna o texto de uma página específica de uma versão."""

    permission_classes = [HasActiveBookEntitlement]

    def get(self, request, book_id: int, version_id: int, page_number: int):
        if page_number < 1:
            return Response(
                {'detail': "'page_number' must be >= 1."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bv = get_object_or_404(
            BookVersion.objects.select_related('book'),
            pk=version_id,
            book_id=book_id,
        )

        # usuário comum só vê publicados
        if not request.user.is_staff:
            if bv.status != BookVersion.Status.PUBLISHED or bv.book.status != Book.Status.PUBLISHED:
                raise NotFound()

        pt = get_object_or_404(
            PageText,
            book_version=bv,
            page_number=page_number,
        )

        payload = {
            'book_id': bv.book_id,
            'book_title': bv.book.title,
            'book_version_id': bv.id,
            'version': bv.version,
            'page_number': pt.page_number,
            'text': pt.text or '',
        }

        return Response(PageTextSerializer(payload).data)
