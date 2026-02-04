from rest_framework import serializers

from .models import CaseLaw

class CaseLawSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaseLaw
        fields = (
            'id',
            'court',
            'case_number',
            'decision_date',
            'summary',
            'url',
            'tags',
            'relevance',
            'created_at',
            'updated_at',
        )