from rest_framework import serializers


class GlobalSearchTargetSerializer(serializers.Serializer):
    route = serializers.CharField()
    params = serializers.JSONField(required=False, default=dict)


class GlobalSearchResultSerializer(serializers.Serializer):
    type = serializers.CharField()
    source = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField(required=False, allow_blank=True, default='')
    snippet = serializers.CharField(allow_blank=True)
    target = GlobalSearchTargetSerializer()
    metadata = serializers.JSONField(required=False, default=dict)
