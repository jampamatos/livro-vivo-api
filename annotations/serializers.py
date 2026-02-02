from rest_framework import serializers
from .models import Annotation

class AnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Annotation
        fields = [
            'id',
            'book_version',
            'page_number',
            'rects_normalizados',
            'note',
            'color',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']