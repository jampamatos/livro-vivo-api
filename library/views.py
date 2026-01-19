from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Book, BookVersion
from .serializers import BookSerializer, BookVersionSerializer

class BookListView(APIView):
    def get(self, request):
        books = Book.objects.all().order_by('-updated_at')
        data = BookSerializer(books, many=True).data
        return Response({'books': data})
    
class BookVersionListView(APIView):
    def get(self, request, book_id: int):
        book = get_object_or_404(Book, pk=book_id)
        versions = BookVersion.objects.filter(book=book).order_by('-created_at')
        data = BookVersionSerializer(versions, many=True).data
        return Response({'book': BookSerializer(book).data, 'versions':data})