from rest_framework import serializers
from .models import Category, Post, Comment

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'created_at', 'updated_at']

class PostSerializer(serializers.ModelSerializer):
    author_display = serializers.SerializerMethodField(read_only=True)
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
