from rest_framework import serializers
from .models import Book, BookVersion

class BookSerializer(serializers.ModelSerializer):
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