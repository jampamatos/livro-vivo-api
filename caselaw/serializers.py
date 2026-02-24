from rest_framework import serializers

from .models import CaseLaw


class CaseLawSerializer(serializers.ModelSerializer):
    def validate_tags(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('tags deve ser uma lista.')
        return [str(tag).strip() for tag in value if str(tag).strip()]

    def validate_anchors(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('anchors deve ser uma lista.')
        for item in value:
            if not isinstance(item, (dict, str)):
                raise serializers.ValidationError('cada anchor deve ser objeto ou texto.')
        return value

    class Meta:
        model = CaseLaw
        fields = (
            'id',
            'court',
            'case_number',
            'decision_date',
            'ementa_rich',
            'ementa_plain',
            'url',
            'anchors',
            'tags',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'ementa_plain',
            'created_at',
            'updated_at',
        )
