from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from .models import TemplatePiece


class TemplatePieceSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        data['file_url'] = instance.resolved_file_url(request=request)
        return data

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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance or TemplatePiece()

        for field_name, value in attrs.items():
            setattr(instance, field_name, value)

        try:
            instance.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError({'non_field_errors': exc.messages})

        attrs['file_name'] = instance.file_name
        attrs['file_mime_type'] = instance.file_mime_type
        attrs['file_size_bytes'] = instance.file_size_bytes
        attrs['file_sha256'] = instance.file_sha256

        if instance.file_upload:
            attrs['file_url'] = ''

        return attrs

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
            'file_upload',
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
        extra_kwargs = {
            'file_url': {'required': False, 'allow_blank': True},
            'file_upload': {'required': False, 'allow_null': True, 'write_only': True},
            'file_name': {'required': False, 'allow_blank': True},
            'file_mime_type': {'required': False, 'allow_blank': True},
            'file_size_bytes': {'required': False},
            'file_sha256': {'required': False, 'allow_blank': True},
        }
