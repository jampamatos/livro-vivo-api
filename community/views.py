from django.contrib.auth import get_user_model

from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import ModelViewSet

from accounts.permissions import HasAcceptedRequiredLegalDocuments
from .models import Category, Comment, CommentLike, Post, PostFollow, PostLike, Report, ReportModerationAction
from .pagination import CommunityPagination
from .permissions import (
    IsModeratorOrAbove,
    IsNotCommunityBanned,
    IsOwnerOrStaff,
    IsStaffOrReadOnlyAuthed,
)
from .view_helpers import (
    build_comment_queryset,
    build_mention_candidates,
    build_post_queryset,
    build_report_queryset,
    parse_mention_user_ids,
    register_report_update_audit,
    report_update_snapshot,
)
from .services import (
    ban_user_from_app,
    deactivate_comment_like,
    deactivate_post_follow,
    deactivate_post_like,
    enqueue_comment_mention_notifications,
    enqueue_new_comment_notifications,
    ensure_comment_like,
    ensure_post_follow,
    ensure_post_like,
)
from .serializers import (
    CategorySerializer,
    MentionCandidateSerializer,
    PostSerializer,
    CommentSerializer,
    ReportSerializer,
)

User = get_user_model()

class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned, IsStaffOrReadOnlyAuthed]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'slug', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

class PostViewSet(ModelViewSet):
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned, IsOwnerOrStaff]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    pagination_class = CommunityPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'body']
    ordering_fields = ['created_at', 'updated_at', 'last_activity_at']
    ordering = ['-last_activity_at', '-created_at']

    def get_queryset(self):
        return build_post_queryset(
            request_user=self.request.user,
            category_id=self.request.query_params.get('category'),
        )
    
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(
        detail=True,
        methods=['post'],
        url_path='follow',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def follow(self, request, pk=None):
        post = self.get_object()
        ensure_post_follow(post=post, user=request.user)
        post.is_following = True
        serializer = self.get_serializer(post)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['post'],
        url_path='unfollow',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def unfollow(self, request, pk=None):
        post = self.get_object()
        deactivate_post_follow(post=post, user=request.user)
        post.is_following = False
        serializer = self.get_serializer(post)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['post'],
        url_path='like',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def like(self, request, pk=None):
        post = self.get_object()
        ensure_post_like(post=post, user=request.user)
        annotated_post = self.get_queryset().get(pk=post.pk)
        serializer = self.get_serializer(annotated_post)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['post'],
        url_path='unlike',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def unlike(self, request, pk=None):
        post = self.get_object()
        deactivate_post_like(post=post, user=request.user)
        annotated_post = self.get_queryset().get(pk=post.pk)
        serializer = self.get_serializer(annotated_post)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['get'],
        url_path='mention-candidates',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def mention_candidates(self, request, pk=None):
        post = self.get_object()
        serializer = MentionCandidateSerializer(
            build_mention_candidates(
                post=post,
                request=request,
                query=request.query_params.get('q'),
            ),
            many=True,
        )
        return Response(serializer.data)

class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned, IsOwnerOrStaff]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    pagination_class = CommunityPagination
    filter_backends =  [filters.OrderingFilter]
    ordering_fields = ['created_at']
    ordering = ['created_at']

    def get_queryset(self):
        return build_comment_queryset(
            request_user=self.request.user,
            post_id=self.request.query_params.get('post'),
        )

    def perform_create(self, serializer):
        mention_user_ids = parse_mention_user_ids(self.request.data.get('mention_user_ids'))
        comment = serializer.save(author=self.request.user)
        enqueue_new_comment_notifications(comment=comment)
        if mention_user_ids:
            enqueue_comment_mention_notifications(comment=comment, mentioned_user_ids=mention_user_ids)

    @action(
        detail=True,
        methods=['post'],
        url_path='like',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def like(self, request, pk=None):
        comment = self.get_object()
        ensure_comment_like(comment=comment, user=request.user)
        annotated_comment = self.get_queryset().get(pk=comment.pk)
        serializer = self.get_serializer(annotated_comment)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=['post'],
        url_path='unlike',
        permission_classes=[IsAuthenticated, HasAcceptedRequiredLegalDocuments, IsNotCommunityBanned],
    )
    def unlike(self, request, pk=None):
        comment = self.get_object()
        deactivate_comment_like(comment=comment, user=request.user)
        annotated_comment = self.get_queryset().get(pk=comment.pk)
        serializer = self.get_serializer(annotated_comment)
        return Response(serializer.data)

class ReportViewSet(ModelViewSet):
    serializer_class = ReportSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["reason", "reporter__username", "post__title", "comment__body"]
    ordering_fields = ["created_at", "updated_at", "moderated_at", "status", "priority"]
    ordering = ["status", "-created_at"]

    def get_queryset(self):
        return build_report_queryset(
            status_filter=(self.request.query_params.get("status") or "").strip(),
            priority_filter=(self.request.query_params.get("priority") or "").strip(),
            decision_filter=(self.request.query_params.get("decision") or "").strip(),
        )

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), HasAcceptedRequiredLegalDocuments(), IsNotCommunityBanned()]
        return [IsAuthenticated(), HasAcceptedRequiredLegalDocuments(), IsModeratorOrAbove()]

    def perform_create(self, serializer):
        serializer.save(
            reporter=self.request.user,
            status=Report.Status.OPEN,
            priority=Report.Priority.MEDIUM,
            decision='',
            assigned_moderator=None,
            moderated_by=None,
            moderated_at=None,
            moderation_note='',
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        before = report_update_snapshot(instance)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance.refresh_from_db()
        register_report_update_audit(report=instance, before=before, actor=self.request.user)

        response_serializer = self.get_serializer(instance)
        return Response(response_serializer.data)

    def _decision_action(
        self,
        *,
        action_type: str,
        next_status: str,
        decision: str,
    ):
        report = self.get_object()
        note = (
            (self.request.data.get("note") or self.request.data.get("moderation_note") or "").strip()
        )

        try:
            changed = report.register_staff_moderation(
                actor=self.request.user,
                action_type=action_type,
                next_status=next_status,
                decision=decision,
                note=note,
            )
        except ValueError as exc:
            raise ValidationError({"status": str(exc)}) from exc

        if not changed:
            raise ValidationError({"status": "Nenhuma alteração aplicável para esta decisão no estado atual."})

        report.refresh_from_db()
        serializer = self.get_serializer(report)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._decision_action(
            action_type=ReportModerationAction.ActionType.APPROVED,
            next_status=Report.Status.RESOLVED,
            decision=Report.Decision.APPROVE,
        )

    @action(detail=True, methods=["post"], url_path="remove")
    def remove(self, request, pk=None):
        return self._decision_action(
            action_type=ReportModerationAction.ActionType.REMOVED,
            next_status=Report.Status.RESOLVED,
            decision=Report.Decision.REMOVE,
        )

    @action(detail=True, methods=["post"], url_path="escalate")
    def escalate(self, request, pk=None):
        return self._decision_action(
            action_type=ReportModerationAction.ActionType.ESCALATED,
            next_status=Report.Status.ESCALATED,
            decision=Report.Decision.ESCALATE,
        )

    @action(detail=True, methods=["post"], url_path="ban-author")
    def ban_author(self, request, pk=None):
        report = self.get_object()
        target = report.target_author()
        if target is None:
            raise ValidationError({"detail": "Não foi possível identificar o autor do conteúdo reportado."})

        note = ((request.data.get("note") or request.data.get("reason") or "").strip())
        status_obj = ban_user_from_app(user=target, actor=request.user, reason=note, report=report)

        payload = self.get_serializer(report).data
        payload["banned_user"] = {
            "id": target.id,
            "email": target.email,
            "is_banned": status_obj.is_banned,
            "banned_at": status_obj.banned_at,
        }
        return Response(payload)
