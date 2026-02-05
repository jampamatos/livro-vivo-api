from rest_framework import serializers
from .models import Category, Post, Comment, Report

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'created_at', 'updated_at']

class PostSerializer(serializers.ModelSerializer):
    author_display = serializers.SerializerMethodField(read_only=True)
    last_activity = serializers.DateTimeField(read_only=True)
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source='category',
        queryset=Category.objects.all(),
        allow_null = True,
        required = False,
        write_only=True,
    )

    class Meta:
        model = Post
        fields = [
            'id',
            'author',
            'author_display',
            'category',
            'category_id',
            'title',
            'body',
            'last_activity',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'author', 'created_at', 'updated_at', 'category']
    
    def get_author_display(self, obj) -> str:
        return str(obj.author)

class CommentSerializer(serializers.ModelSerializer):
    author_display = serializers.SerializerMethodField(read_only=True)
    post_id = serializers.PrimaryKeyRelatedField(
        source='post',
        queryset=Post.objects.all(),
        write_only=True,
    )

    class Meta:
        model = Comment
        fields = [
            'id',
            'post',
            'post_id',
            'author',
            'author_display',
            'body',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id','post', 'author', 'created_at', 'updated_at']
    
    def get_author_display(self, obj) -> str:
        return str(obj.author)

class ReportSerializer(serializers.ModelSerializer):
    reporter = serializers.PrimaryKeyRelatedField(read_only=True)
    reporter_display = serializers.CharField(source='reporter.username', read_only=True)

    post_id = serializers.PrimaryKeyRelatedField(
        queryset=Post.objects.all(),
        source='post',
        write_only=True,
        required=False,
        allow_null=True,
    )
    comment_id = serializers.PrimaryKeyRelatedField(
        queryset=Comment.objects.all(),
        source='comment',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Report
        fields = [
            'id',
            'reporter',
            'reporter_display',
            'post',
            'comment',
            'post_id',
            'comment_id',
            'reason',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'reporter', 'reporter_display', 'post', 'comment', 'created_at', 'updated_at']

    def validate(self, attrs):
        post = attrs.get('post')
        comment = attrs.get('comment')

        # Em updates parciais (PATCH), allow mudar status/razão sem reenviar alvo.
        if self.instance is not None and ('post' not in attrs and 'comment' not in attrs):
            return attrs

        if (post is None and comment is None) or (post is not None and comment is not None):
            raise serializers.ValidationError("Informe exatamente um alvo: post_id OU comment_id.")
        return attrs
