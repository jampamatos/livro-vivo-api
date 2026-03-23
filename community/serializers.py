from django.contrib.auth import get_user_model

from rest_framework import serializers
from .models import Category, Post, Comment, Report, ReportModerationAction
from accounts.roles import user_is_moderator_or_above

User = get_user_model()

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'created_at', 'updated_at']

class MentionCandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)

class PostSerializer(serializers.ModelSerializer):
    author_display = serializers.SerializerMethodField(read_only=True)
    author_avatar_url = serializers.SerializerMethodField(read_only=True)
    is_following = serializers.SerializerMethodField(read_only=True)
    likes_count = serializers.SerializerMethodField(read_only=True)
    liked_by_me = serializers.SerializerMethodField(read_only=True)
    comments_count = serializers.SerializerMethodField(read_only=True)
    last_comment_at = serializers.SerializerMethodField(read_only=True)
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
            'author_avatar_url',
            'category',
            'category_id',
            'title',
            'body',
            'moderation_state',
            'moderated_by',
            'moderated_at',
            'moderation_note',
            'is_following',
            'likes_count',
            'liked_by_me',
            'comments_count',
            'last_comment_at',
            'last_activity',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'author',
            'category',
            'moderation_state',
            'moderated_by',
            'moderated_at',
            'moderation_note',
            'created_at',
            'updated_at',
        ]
    
    @staticmethod
    def _humanize_identifier(value: str) -> str:
        normalized = (value or '').strip()
        if not normalized:
            return ''
        normalized = normalized.replace('.', ' ').replace('_', ' ').replace('-', ' ')
        parts = [part for part in normalized.split() if part]
        if not parts:
            return ''
        return ' '.join(part[:1].upper() + part[1:] for part in parts)

    @staticmethod
    def _resolve_author_display(author) -> str:
        profile = getattr(author, 'profile', None)
        full_name = (getattr(profile, 'full_name', '') or '').strip()
        if full_name:
            return full_name

        first_last = f"{(author.first_name or '').strip()} {(author.last_name or '').strip()}".strip()
        if first_last:
            return first_last

        username = (author.username or '').strip()
        if username:
            if '@' in username:
                username = username.split('@', 1)[0].strip()
            username = PostSerializer._humanize_identifier(username)
            if username:
                return username

        email = (author.email or '').strip()
        if email:
            email_local = email.split('@', 1)[0].strip()
            email_local = PostSerializer._humanize_identifier(email_local)
            if email_local:
                return email_local

        return 'Usuario'

    @staticmethod
    def _resolve_author_avatar_url(author):
        profile = getattr(author, 'profile', None)
        if not profile:
            return None

        for attr_name in ('avatar', 'avatar_url', 'photo_url', 'image_url'):
            raw_value = getattr(profile, attr_name, None)
            if not raw_value:
                continue
            if hasattr(raw_value, 'url'):
                try:
                    return raw_value.url
                except Exception:  # pragma: no cover
                    continue
            value_str = str(raw_value).strip()
            if value_str:
                return value_str
        return None

    def get_author_display(self, obj) -> str:
        return self._resolve_author_display(obj.author)

    def get_author_avatar_url(self, obj):
        avatar_url = self._resolve_author_avatar_url(obj.author)
        request = self.context.get('request')
        if avatar_url and request and avatar_url.startswith('/'):
            return request.build_absolute_uri(avatar_url)
        return avatar_url

    def get_is_following(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        annotated = getattr(obj, 'is_following', None)
        if annotated is not None:
            return bool(annotated)
        return obj.follows.filter(user=user, is_active=True).exists()

    def get_likes_count(self, obj) -> int:
        annotated = getattr(obj, 'likes_count', None)
        if annotated is not None:
            return int(annotated)
        return obj.likes.filter(is_active=True).count()

    def get_liked_by_me(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        annotated = getattr(obj, 'liked_by_me', None)
        if annotated is not None:
            return bool(annotated)
        return obj.likes.filter(user=user, is_active=True).exists()

    def get_comments_count(self, obj) -> int:
        annotated = getattr(obj, 'comments_count', None)
        if annotated is not None:
            return int(annotated)

        request = self.context.get('request')
        user = getattr(request, 'user', None)
        comments = obj.comments.all()
        if not user_is_moderator_or_above(user):
            comments = comments.filter(moderation_state=Comment.ModerationState.ACTIVE)
        return comments.count()

    def get_last_comment_at(self, obj):
        annotated = getattr(obj, 'last_comment_at', None)
        if annotated is not None:
            return annotated

        request = self.context.get('request')
        user = getattr(request, 'user', None)
        comments = obj.comments.all()
        if not user_is_moderator_or_above(user):
            comments = comments.filter(moderation_state=Comment.ModerationState.ACTIVE)
        latest = comments.order_by('-created_at').values_list('created_at', flat=True).first()
        return latest

class CommentSerializer(serializers.ModelSerializer):
    author_display = serializers.SerializerMethodField(read_only=True)
    author_avatar_url = serializers.SerializerMethodField(read_only=True)
    likes_count = serializers.SerializerMethodField(read_only=True)
    liked_by_me = serializers.SerializerMethodField(read_only=True)
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
            'author_avatar_url',
            'body',
            'moderation_state',
            'moderated_by',
            'moderated_at',
            'moderation_note',
            'likes_count',
            'liked_by_me',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'post',
            'author',
            'moderation_state',
            'moderated_by',
            'moderated_at',
            'moderation_note',
            'created_at',
            'updated_at',
        ]
    
    def get_author_display(self, obj) -> str:
        return PostSerializer._resolve_author_display(obj.author)

    def get_author_avatar_url(self, obj):
        avatar_url = PostSerializer._resolve_author_avatar_url(obj.author)
        request = self.context.get('request')
        if avatar_url and request and avatar_url.startswith('/'):
            return request.build_absolute_uri(avatar_url)
        return avatar_url

    def get_likes_count(self, obj) -> int:
        annotated = getattr(obj, 'likes_count', None)
        if annotated is not None:
            return int(annotated)
        return obj.likes.filter(is_active=True).count()

    def get_liked_by_me(self, obj) -> bool:
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        annotated = getattr(obj, 'liked_by_me', None)
        if annotated is not None:
            return bool(annotated)
        return obj.likes.filter(user=user, is_active=True).exists()

class ReportSerializer(serializers.ModelSerializer):
    reporter = serializers.PrimaryKeyRelatedField(read_only=True)
    reporter_display = serializers.CharField(source='reporter.username', read_only=True)
    assigned_moderator_display = serializers.CharField(source='assigned_moderator.username', read_only=True)
    moderated_by_display = serializers.CharField(source='moderated_by.username', read_only=True)
    moderation_actions = serializers.SerializerMethodField(read_only=True)

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
    assigned_moderator_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='assigned_moderator',
        write_only=True,
        required=False,
        allow_null=True,
    )

    def get_moderation_actions(self, obj):
        actions_qs = (
            ReportModerationAction.objects
            .select_related('actor')
            .filter(report_id=obj.id)
            .order_by('-created_at')[:20]
        )
        return ReportModerationActionSerializer(actions_qs, many=True).data

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
            'priority',
            'decision',
            'assigned_moderator',
            'assigned_moderator_id',
            'assigned_moderator_display',
            'moderated_by',
            'moderated_by_display',
            'moderated_at',
            'moderation_note',
            'moderation_actions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'reporter',
            'reporter_display',
            'post',
            'comment',
            'assigned_moderator',
            'moderated_by',
            'moderated_by_display',
            'moderated_at',
            'moderation_actions',
            'created_at',
            'updated_at',
        ]

    def validate(self, attrs):
        request = self.context.get('request')
        is_staff = bool(request and request.user and request.user.is_staff)

        if self.instance is not None and ('post' in attrs or 'comment' in attrs):
            raise serializers.ValidationError("Não é permitido alterar o alvo de um report existente.")

        # Em updates parciais (PATCH), allow mudar status/razão sem reenviar alvo.
        if self.instance is not None and ('post' not in attrs and 'comment' not in attrs):
            next_status = attrs.get('status')
            if next_status and not self.instance.can_transition_to(next_status):
                raise serializers.ValidationError(
                    {'status': f'Transição inválida de status: {self.instance.status} -> {next_status}.'}
                )
            return attrs

        post = attrs.get('post')
        comment = attrs.get('comment')

        if (post is None and comment is None) or (post is not None and comment is not None):
            raise serializers.ValidationError("Informe exatamente um alvo: post_id OU comment_id.")

        # Usuário final só cria report inicial. Campos sensíveis são controlados pelo staff.
        if self.instance is None and not is_staff:
            attrs['status'] = Report.Status.OPEN
            attrs['priority'] = Report.Priority.MEDIUM
            attrs['decision'] = ''
            attrs['assigned_moderator'] = None
            attrs['moderation_note'] = ''

        return attrs


class ReportModerationActionSerializer(serializers.ModelSerializer):
    actor_display = serializers.CharField(source='actor.username', read_only=True)

    class Meta:
        model = ReportModerationAction
        fields = [
            'id',
            'action_type',
            'actor',
            'actor_display',
            'from_status',
            'to_status',
            'from_priority',
            'to_priority',
            'decision',
            'note',
            'created_at',
        ]
        read_only_fields = fields
