from pathlib import Path

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import NotFound

from .models import Book, BookVersion
from .serializers import BookSerializer, BookVersionSerializer
from .permissions import HasActiveBookEntitlement

class BookListView(APIView):
    permission_classes = [HasActiveBookEntitlement]

    def get(self, request):
        qs = Book.objects.all().order_by('-updated_at')

        if not request.user.is_staff:
            qs = qs.filter(status=Book.Status.PUBLISHED)

        data = BookSerializer(qs, many=True).data
        return Response({'books': data})
    
class BookVersionListView(APIView):
    permission_classes=[HasActiveBookEntitlement]

    def get(self, request, book_id: int):
        book = get_object_or_404(Book, pk=book_id)

        if not request.user.is_staff and book.status != Book.Status.PUBLISHED:
            raise NotFound()
        
        qs = BookVersion.objects.filter(book=book).order_by('-created_at')

        if not request.user.is_staff:
            qs = qs.filter(status=BookVersion.Status.PUBLISHED)

        data = BookVersionSerializer(qs, many=True).data
        return Response({'book': BookSerializer(book).data, 'versions':data})
    
class BookVersionDownloadUrlView(APIView):
    permission_classes = [HasActiveBookEntitlement]

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
    permission_classes = [HasActiveBookEntitlement]

    def get(self, request, book_id:int, version_id: int):
        bv = get_object_or_404(BookVersion, pk=version_id, book_id=book_id)

        if not request.user.is_staff and bv.status != BookVersion.Status.PUBLISHED:
            raise NotFound()
        
        if not bv.pdf:
            raise Http404()
        
        filename = Path(bv.pdf.name).name # pega só o nome do arquivo
        response = FileResponse(bv.pdf.open('rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response