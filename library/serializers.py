from rest_framework import serializers

from .models import Book, BookVersion


class BookSerializer(serializers.ModelSerializer):
    """Serializer para listagem de livros."""

    class Meta:
        model = Book
        fields = [
            'id',
            'title',
            'description',
            'status',
            'created_at',
            'updated_at',
        ]


class BookVersionSerializer(serializers.ModelSerializer):
    """Serializer para listagem de versões de livros."""

    class Meta:
        model = BookVersion
        fields = [
            'id',
            'book',
            'version',
            'published_at',
            'changelog',
            'status',
            'created_at',
        ]


class SearchResultSerializer(serializers.Serializer):
    """Serializer do payload de resultados de busca."""

    book_id = serializers.IntegerField()
    book_title = serializers.CharField()
    book_version_id = serializers.IntegerField()
    version = serializers.CharField()
    page_number = serializers.IntegerField()
    snippet = serializers.CharField()


class PageTextSerializer(serializers.Serializer):
    """Serializer do payload de texto de página."""

    book_id = serializers.IntegerField()
    book_title = serializers.CharField()
    book_version_id = serializers.IntegerField()
    version = serializers.CharField()
    page_number = serializers.IntegerField()
    text = serializers.CharField()
