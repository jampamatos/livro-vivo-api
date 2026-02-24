from rest_framework import serializers

from .models import Annotation


class AnnotationSerializer(serializers.ModelSerializer):
    """Serializer para criação e leitura de anotações chapter-first."""

    class Meta:
        model = Annotation
        fields = [
            'id',
            'book_version',
            'chapter',
            'selector',
            'start_offset',
            'end_offset',
            'excerpt',
            'note',
            'color',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'book_version': {'required': True},
            'chapter': {'required': True},
            'start_offset': {'required': True},
            'end_offset': {'required': True},
        }

    def validate_selector(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('Selector deve ser um objeto JSON.')
        return value

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        book_version = attrs.get('book_version') or getattr(instance, 'book_version', None)
        chapter = attrs.get('chapter') or getattr(instance, 'chapter', None)
        start_offset = attrs.get('start_offset', getattr(instance, 'start_offset', None))
        end_offset = attrs.get('end_offset', getattr(instance, 'end_offset', None))
        offset_was_provided = 'start_offset' in attrs or 'end_offset' in attrs

        if chapter and book_version and chapter.book_version_id != book_version.id:
            raise serializers.ValidationError(
                {'chapter': 'Capítulo não pertence à versão do livro informada.'}
            )

        if start_offset is None or end_offset is None:
            return attrs

        if instance is None or offset_was_provided:
            if start_offset < 0:
                raise serializers.ValidationError({'start_offset': 'start_offset deve ser >= 0.'})

            if end_offset <= start_offset:
                raise serializers.ValidationError(
                    {'end_offset': 'end_offset deve ser maior que start_offset.'}
                )

        excerpt = attrs.get('excerpt')
        if (excerpt is None or excerpt == '') and chapter:
            content_plain = chapter.content_plain or ''
            if content_plain and start_offset < len(content_plain):
                clipped_end = min(end_offset, len(content_plain))
                attrs['excerpt'] = content_plain[start_offset:clipped_end].strip()

        return attrs
