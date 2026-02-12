from pathlib import Path
from typing import Optional

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from entitlements.services import entitled_book_ids, user_has_subscription
from .models import Book, BookVersion, PageText
from .permissions import HasActiveBookEntitlement
from .serializers import (
    BookSerializer,
    BookVersionSerializer,
    PageTextSerializer,
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

        download_url = request.build_absolute_uri(
            reverse('book-version-download', kwargs={'book_id': book_id, 'version_id': version_id})
        )

        return Response({'url': download_url})


class BookVersionDownloadView(APIView):
    """Faz o streaming do PDF da versão solicitada."""

    permission_classes = [HasActiveBookEntitlement]

    def get(self, request, book_id: int, version_id: int):
        bv = get_object_or_404(BookVersion, pk=version_id, book_id=book_id)

        if not request.user.is_staff and bv.status != BookVersion.Status.PUBLISHED:
            raise NotFound()

        if not bv.pdf:
            raise Http404()

        # Pega só o nome do arquivo para o header.
        filename = Path(bv.pdf.name).name
        response = FileResponse(bv.pdf.open('rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class SearchView(APIView):
    """Busca simples por texto dentro de páginas (PageText)."""

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

        pts = PageText.objects.select_related('book_version', 'book_version__book')

        # Filtros de visibilidade (usuário comum só vê publicados)
        if not request.user.is_staff:
            pts = pts.filter(
                book_version__status=BookVersion.Status.PUBLISHED,
                book_version__book__status=Book.Status.PUBLISHED,
            )

        # escolhe escopo
        if book_version_id:
            try:
                bv_id = int(book_version_id)
            except ValueError:
                return Response({'detail': "'book_version_id' must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

            pts = pts.filter(book_version_id=bv_id)

        elif book_id_qp:
            try:
                b_id = int(book_id_qp)
            except ValueError:
                return Response({'detail': "'book_id' must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

            # MVP: busca no livro inteiro (todas as versões visíveis)
            pts = pts.filter(book_version__book_id=b_id)

        # Busca simples.
        qs = pts.filter(text__icontains=q).order_by('book_version_id', 'page_number')

        total = qs.count()
        page = qs[offset : offset + limit]

        results = []
        for row in page:
            bv = row.book_version
            b = bv.book
            results.append(
                {
                    'book_id': b.id,
                    'book_title': b.title,
                    'book_version_id': bv.id,
                    'version': bv.version,
                    'page_number': row.page_number,
                    'snippet': _make_snippet(row.text or '', q),
                }
            )

        data = {
            'q': q,
            'count': total,
            'limit': limit,
            'offset': offset,
            'results': SearchResultSerializer(results, many=True).data,
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
