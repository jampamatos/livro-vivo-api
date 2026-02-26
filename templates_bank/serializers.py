from rest_framework import serializers

from .models import TemplatePiece


class TemplatePieceSerializer(serializers.ModelSerializer):
    def validate_tags(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('tags deve ser uma lista.')
        return [str(tag).strip() for tag in value if str(tag).strip()]

    def validate_file_sha256(self, value):
        normalized = (value or '').strip().lower()
        if normalized and len(normalized) != 64:
            raise serializers.ValidationError('file_sha256 deve ter 64 caracteres.')
        return normalized

    class Meta:
        model = TemplatePiece
        fields = (
            'id',
            'title',
            'slug',
            'template_code',
            'version',
            'changelog',
            'description',
            'category',
            'tags',
            'file_url',
            'file_name',
            'file_mime_type',
            'file_size_bytes',
            'file_sha256',
            'status',
            'published_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'created_at',
            'updated_at',
        )
