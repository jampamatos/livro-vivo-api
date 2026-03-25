from rest_framework import serializers

from config.storage import build_media_reference

from .models import CourseAsset, CoursePost, LiveEvent


class CoursePostSerializer(serializers.ModelSerializer):
    def validate_tags(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('tags deve ser uma lista.')
        return [str(tag).strip() for tag in value if str(tag).strip()]

    class Meta:
        model = CoursePost
        fields = (
            'id',
            'title',
            'slug',
            'author_name',
            'excerpt',
            'content_rich',
            'content_plain',
            'post_type',
            'tags',
            'status',
            'published_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'content_plain',
            'created_at',
            'updated_at',
        )


class CourseAssetSerializer(serializers.ModelSerializer):
    post_id = serializers.PrimaryKeyRelatedField(
        source='post',
        queryset=CoursePost.objects.all(),
        allow_null=True,
        required=False,
        write_only=True,
    )
    post = serializers.PrimaryKeyRelatedField(read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        file_reference = build_media_reference(
            remote_url=instance.file_url,
            request=request,
        )
        data['file_url'] = file_reference['url']
        data['file_source'] = file_reference['source']
        data['file_storage_alias'] = file_reference['storage_alias']
        data['file_storage_backend'] = file_reference['storage_backend']
        data['file_storage_key'] = file_reference['storage_key']
        data['file_cache_control'] = file_reference['cache_control']
        return data

    def validate_tags(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('tags deve ser uma lista.')
        return [str(tag).strip() for tag in value if str(tag).strip()]

    class Meta:
        model = CourseAsset
        fields = (
            'id',
            'post',
            'post_id',
            'title',
            'description',
            'asset_type',
            'file_url',
            'tags',
            'status',
            'published_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'post',
            'created_at',
            'updated_at',
        )


class LiveEventSerializer(serializers.ModelSerializer):
    post_id = serializers.PrimaryKeyRelatedField(
        source='post',
        queryset=CoursePost.objects.all(),
        allow_null=True,
        required=False,
        write_only=True,
    )
    post = serializers.PrimaryKeyRelatedField(read_only=True)

    def validate(self, attrs):
        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts_at and ends_at and ends_at < starts_at:
            raise serializers.ValidationError('ends_at deve ser maior ou igual a starts_at.')
        return attrs

    class Meta:
        model = LiveEvent
        fields = (
            'id',
            'post',
            'post_id',
            'title',
            'description',
            'event_type',
            'status',
            'starts_at',
            'ends_at',
            'meeting_url',
            'recording_url',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'post',
            'created_at',
            'updated_at',
        )
