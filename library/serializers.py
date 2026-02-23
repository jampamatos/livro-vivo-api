from rest_framework import serializers

from .models import Book, BookChapter, BookVersion


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


class BookChapterSerializer(serializers.ModelSerializer):
    """Serializer de capítulos nativos do livro."""

    class Meta:
        model = BookChapter
        fields = [
            'id',
            'book_version',
            'order',
            'title',
            'slug',
            'content_rich',
            'content_plain',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'content_plain', 'created_at', 'updated_at']


class BookChapterSummarySerializer(serializers.ModelSerializer):
    """Serializer resumido de capítulo para sumário."""

    class Meta:
        model = BookChapter
        fields = [
            'id',
            'order',
            'title',
            'slug',
            'updated_at',
        ]


class CurrentBookVersionResponseSerializer(serializers.Serializer):
    """Payload chapter-first da versão atual do livro."""

    book = BookSerializer()
    version = BookVersionSerializer()


class ChapterSummaryResponseSerializer(serializers.Serializer):
    """Payload chapter-first do sumário da versão atual."""

    book_id = serializers.IntegerField()
    book_title = serializers.CharField()
    book_version_id = serializers.IntegerField()
    version = serializers.CharField()
    chapters = BookChapterSummarySerializer(many=True)


class ChapterBySlugResponseSerializer(serializers.Serializer):
    """Payload chapter-first de capítulo por slug."""

    book_id = serializers.IntegerField()
    book_title = serializers.CharField()
    book_version_id = serializers.IntegerField()
    version = serializers.CharField()
    chapter = BookChapterSerializer()
    previous_slug = serializers.CharField(allow_null=True)
    next_slug = serializers.CharField(allow_null=True)


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
