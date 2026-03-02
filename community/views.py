from django.db.models import F, Max
from django.db.models.functions import Coalesce
from django.utils import timezone

from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import ModelViewSet

from .models import Category, Post, Comment, Report, ReportModerationAction
from .permissions import (
    IsModeratorOrAbove,
    IsNotCommunityBanned,
    IsOwnerOrStaff,
    IsStaffOrReadOnlyAuthed,
)
from .services import ban_user_from_app, enqueue_new_comment_notifications
from .serializers import CategorySerializer, PostSerializer, CommentSerializer, ReportSerializer

from accounts.roles import user_is_moderator_or_above

class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsNotCommunityBanned, IsStaffOrReadOnlyAuthed]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'slug', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

class PostViewSet(ModelViewSet):
    serializer_class = PostSerializer
    permission_classes = [IsAuthenticated, IsNotCommunityBanned, IsOwnerOrStaff]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'body']
    ordering_fields = ['created_at', 'updated_at', 'last_activity']
    ordering = ['-last_activity', '-created_at']

    def get_queryset(self):
        qs = (
            Post.objects.select_related('author', 'category')
            .annotate(last_activity=Coalesce(Max('comments__created_at'), F('created_at')))
            .all()
        )

        if not user_is_moderator_or_above(self.request.user):
            qs = qs.filter(moderation_state=Post.ModerationState.ACTIVE)

        category_id = self.request.query_params.get('category')
        if category_id:
            qs = qs.filter(category_id=category_id)
        return qs
    
    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
    
class CommentViewSet(ModelViewSet):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, IsNotCommunityBanned, IsOwnerOrStaff]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    filter_backends =  [filters.OrderingFilter]
    ordering_fields = ['created_at']
    ordering = ['created_at']

    def get_queryset(self):
        qs = Comment.objects.select_related('author', 'post').all()
        if not user_is_moderator_or_above(self.request.user):
            qs = qs.filter(moderation_state=Comment.ModerationState.ACTIVE)
        post_id = self.request.query_params.get('post')
        if post_id:
            qs = qs.filter(post_id=post_id)
        return qs
    
    def perform_create(self, serializer):
        comment = serializer.save(author=self.request.user)
        enqueue_new_comment_notifications(comment=comment)

class ReportViewSet(ModelViewSet):
    serializer_class = ReportSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_api'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["reason", "reporter__username", "post__title", "comment__body"]
    ordering_fields = ["created_at", "updated_at", "moderated_at", "status", "priority"]
    ordering = ["status", "-created_at"]

    def get_queryset(self):
        qs = (
            Report.objects
            .select_related("reporter", "post", "comment", "assigned_moderator", "moderated_by")
            .prefetch_related("moderation_actions__actor")
            .all()
        )

        status_filter = (self.request.query_params.get("status") or "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)

        priority_filter = (self.request.query_params.get("priority") or "").strip()
        if priority_filter:
            qs = qs.filter(priority=priority_filter)

        decision_filter = (self.request.query_params.get("decision") or "").strip()
        if decision_filter:
            qs = qs.filter(decision=decision_filter)

        return qs

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsNotCommunityBanned()]
        return [IsAuthenticated(), IsModeratorOrAbove()]

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

    def _register_update_audit(self, report: Report, before: dict):
        status_changed = before["status"] != report.status
        priority_changed = before["priority"] != report.priority
        assigned_changed = before["assigned_moderator_id"] != report.assigned_moderator_id
        decision_changed = before["decision"] != report.decision
        note_changed = before["moderation_note"] != report.moderation_note

        if not any([status_changed, priority_changed, assigned_changed, decision_changed, note_changed]):
            return

        if status_changed:
            action_type = ReportModerationAction.ActionType.STATUS_CHANGED
        elif priority_changed:
            action_type = ReportModerationAction.ActionType.PRIORITY_CHANGED
        elif assigned_changed:
            action_type = ReportModerationAction.ActionType.ASSIGNED
        else:
            action_type = ReportModerationAction.ActionType.STATUS_CHANGED

        report.moderated_by = self.request.user
        report.moderated_at = timezone.now()
        report.save(update_fields=["moderated_by", "moderated_at", "updated_at"])

        ReportModerationAction.objects.create(
            report=report,
            actor=self.request.user,
            action_type=action_type,
            from_status=before["status"],
            to_status=report.status,
            from_priority=before["priority"],
            to_priority=report.priority,
            decision=report.decision,
            note=(report.moderation_note or "").strip(),
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        before = {
            "status": instance.status,
            "priority": instance.priority,
            "decision": instance.decision,
            "assigned_moderator_id": instance.assigned_moderator_id,
            "moderation_note": instance.moderation_note,
        }

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance.refresh_from_db()
        self._register_update_audit(instance, before)

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
