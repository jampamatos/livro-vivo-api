from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.text import Truncator
from django.utils import timezone

from accounts.roles import user_is_moderator_or_above, user_is_owner_or_superuser
from config.admin_hierarchy import HierarchicalAdminMixin, admin_url

from .models import (
    Category,
    Comment,
    ModerationConfig,
    Post,
    Report,
    ReportModerationAction,
    UserModerationEvent,
    UserModerationStatus,
)
from .services import ban_user_from_app, register_report_remove_consequence


ACTIVE_REPORT_STATUSES = (
    Report.Status.OPEN,
    Report.Status.IN_REVIEW,
    Report.Status.ESCALATED,
)

def _merge_extra_context(extra_context, *, navigation_path):
    context = dict(extra_context or {})
    context["lv_navigation_path"] = navigation_path
    return context


def _nav_item(label: str, url: str | None = None):
    return {"label": label, "url": url}


class ReportModerationActionInline(admin.TabularInline):
    model = ReportModerationAction
    extra = 0
    can_delete = False
    fields = (
        "created_at",
        "action_type",
        "actor",
        "from_status",
        "to_status",
        "from_priority",
        "to_priority",
        "decision",
        "note",
    )
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False


class ReportAdminForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        if not self.instance.pk:
            return cleaned_data

        previous = Report.objects.filter(pk=self.instance.pk).values("status").first()
        if not previous:
            return cleaned_data

        next_status = cleaned_data.get("status")
        prev_status = previous.get("status")
        if next_status and prev_status and prev_status != next_status:
            probe = Report(status=prev_status)
            if not probe.can_transition_to(next_status):
                raise ValidationError({"status": f"Transição inválida de status: {prev_status} -> {next_status}."})

        decision = cleaned_data.get("decision") or ""
        moderation_note = (cleaned_data.get("moderation_note") or "").strip()
        if decision in {
            Report.Decision.REMOVE,
            Report.Decision.ESCALATE,
            Report.Decision.REJECT,
        } and not moderation_note:
            self.add_error("moderation_note", "Preencha a justificativa da moderação para esta decisão.")

        return cleaned_data


class ReportActionForm(ActionForm):
    confirm_sensitive_action = forms.BooleanField(
        label="Confirmo ação sensível (remover/banir)",
        required=False,
    )
    moderation_note = forms.CharField(
        label="Justificativa da ação",
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Motivo da decisão de moderação", "size": 48}),
    )


class UserModerationActionForm(ActionForm):
    confirm_sensitive_action = forms.BooleanField(
        label="Confirmo ação sensível (banimento)",
        required=False,
    )
    ban_reason = forms.CharField(
        label="Motivo do banimento",
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Informe o motivo do banimento", "size": 48}),
    )

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    form = ReportAdminForm
    action_form = ReportActionForm
    list_display = (
        "id",
        "status",
        "priority",
        "decision",
        "target",
        "reporter",
        "assigned_moderator",
        "moderated_by",
        "created_at",
    )
    list_filter = ("status", "priority", "decision", "assigned_moderator", "created_at", "moderated_at")
    search_fields = ("reason", "reporter__email", "reporter__username", "post__title", "comment__body")
    ordering = ("status", "-created_at")
    readonly_fields = ("moderated_by", "moderated_at", "created_at", "updated_at")
    inlines = [ReportModerationActionInline]
    actions = (
        "mark_in_review",
        "approve_reports",
        "remove_reports",
        "escalate_reports",
        "reject_reports",
        "ban_report_authors",
    )
    fieldsets = (
        (
            "Dados da denúncia",
            {
                "fields": (
                    "reporter",
                    "post",
                    "comment",
                    "reason",
                    "status",
                    "priority",
                    "decision",
                    "assigned_moderator",
                )
            },
        ),
        (
            "Auditoria de moderação",
            {
                "fields": (
                    "moderated_by",
                    "moderated_at",
                    "moderation_note",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def has_module_permission(self, request):
        return user_is_moderator_or_above(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    def has_change_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    def _resolve_action_type_from_changes(self, *, form, report: Report):
        if report.decision == Report.Decision.REMOVE:
            return ReportModerationAction.ActionType.REMOVED
        if report.decision == Report.Decision.APPROVE:
            return ReportModerationAction.ActionType.APPROVED
        if report.decision == Report.Decision.ESCALATE:
            return ReportModerationAction.ActionType.ESCALATED
        if report.decision == Report.Decision.REJECT:
            return ReportModerationAction.ActionType.REJECTED
        if "priority" in form.changed_data:
            return ReportModerationAction.ActionType.PRIORITY_CHANGED
        if "assigned_moderator" in form.changed_data:
            return ReportModerationAction.ActionType.ASSIGNED
        return ReportModerationAction.ActionType.STATUS_CHANGED

    def save_model(self, request, obj, form, change):
        if not change or not obj.pk:
            super().save_model(request, obj, form, change)
            return

        previous = Report.objects.get(pk=obj.pk)
        moderation_changed = any(
            field in form.changed_data
            for field in ("status", "priority", "decision", "moderation_note", "assigned_moderator")
        )

        super().save_model(request, obj, form, change)

        if not moderation_changed:
            return

        obj.moderated_by = request.user
        obj.moderated_at = timezone.now()
        obj.save(update_fields=["moderated_by", "moderated_at", "updated_at"])

        obj.apply_decision_to_target(actor=request.user, decision=obj.decision, note=obj.moderation_note)
        if obj.status == Report.Status.RESOLVED and obj.decision == Report.Decision.REMOVE:
            register_report_remove_consequence(report=obj, actor=request.user, note=obj.moderation_note)

        ReportModerationAction.objects.create(
            report=obj,
            actor=request.user,
            action_type=self._resolve_action_type_from_changes(form=form, report=obj),
            from_status=previous.status,
            to_status=obj.status,
            from_priority=previous.priority,
            to_priority=obj.priority,
            decision=obj.decision,
            note=(obj.moderation_note or "").strip(),
        )

    def target(self, obj: Report):
        if obj.post_id:
            return f"Post #{obj.post_id} — {obj.post.title}"
        return f"Comentário #{obj.comment_id} — Post #{obj.comment.post_id}"
    target.short_description = "Alvo"

    def _apply_bulk_action(self, request, queryset, *, action_type, next_status, decision, label):
        moderation_note = (request.POST.get("moderation_note") or "").strip()
        processed = 0
        skipped = 0
        for report in queryset:
            try:
                changed = report.register_staff_moderation(
                    actor=request.user,
                    action_type=action_type,
                    next_status=next_status,
                    decision=decision,
                    note=moderation_note,
                )
                if changed:
                    processed += 1
                else:
                    skipped += 1
            except ValueError:
                skipped += 1
        if processed:
            self.message_user(request, f"{processed} denúncia(s) atualizada(s) para {label}.", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} denúncia(s) ignorada(s) por transição inválida.", level=messages.WARNING)

    def _is_sensitive_action_confirmed(self, request):
        return str(request.POST.get("confirm_sensitive_action", "")).lower() in {"1", "true", "on", "yes"}

    @admin.action(description="Mover para em revisão")
    def mark_in_review(self, request, queryset):
        self._apply_bulk_action(
            request,
            queryset,
            action_type=ReportModerationAction.ActionType.STATUS_CHANGED,
            next_status=Report.Status.IN_REVIEW,
            decision="",
            label="em revisão",
        )

    @admin.action(description="Aprovar conteúdo denunciado")
    def approve_reports(self, request, queryset):
        self._apply_bulk_action(
            request,
            queryset,
            action_type=ReportModerationAction.ActionType.APPROVED,
            next_status=Report.Status.RESOLVED,
            decision=Report.Decision.APPROVE,
            label="resolvido/aprovado",
        )

    @admin.action(description="Remover conteúdo denunciado")
    def remove_reports(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                "Confirme a ação sensível para remover conteúdos denunciados em massa.",
                level=messages.ERROR,
            )
            return
        if not (request.POST.get("moderation_note") or "").strip():
            self.message_user(
                request,
                "Informe uma justificativa de moderação para remover conteúdos.",
                level=messages.ERROR,
            )
            return
        self._apply_bulk_action(
            request,
            queryset,
            action_type=ReportModerationAction.ActionType.REMOVED,
            next_status=Report.Status.RESOLVED,
            decision=Report.Decision.REMOVE,
            label="resolvido/removido",
        )

    @admin.action(description="Escalar denúncia")
    def escalate_reports(self, request, queryset):
        self._apply_bulk_action(
            request,
            queryset,
            action_type=ReportModerationAction.ActionType.ESCALATED,
            next_status=Report.Status.ESCALATED,
            decision=Report.Decision.ESCALATE,
            label="escalado",
        )

    @admin.action(description="Rejeitar denúncia")
    def reject_reports(self, request, queryset):
        self._apply_bulk_action(
            request,
            queryset,
            action_type=ReportModerationAction.ActionType.REJECTED,
            next_status=Report.Status.REJECTED,
            decision=Report.Decision.REJECT,
            label="rejeitado",
        )

    @admin.action(description="Banir autor do conteúdo denunciado")
    def ban_report_authors(self, request, queryset):
        if not self._is_sensitive_action_confirmed(request):
            self.message_user(
                request,
                "Confirme a ação sensível para banir autores em massa.",
                level=messages.ERROR,
            )
            return
        moderation_note = (request.POST.get("moderation_note") or "").strip()
        if not moderation_note:
            self.message_user(
                request,
                "Informe uma justificativa de moderação para banimento.",
                level=messages.ERROR,
            )
            return

        processed = 0
        skipped = 0
        for report in queryset:
            target = report.target_author()
            if target is None:
                skipped += 1
                continue
            reason = f'{moderation_note} (denúncia #{report.id})'
            ban_user_from_app(user=target, actor=request.user, reason=reason, report=report)
            processed += 1
        if processed:
            self.message_user(request, f"{processed} usuário(s) banido(s).", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} denúncia(s) sem autor alvo.", level=messages.WARNING)

@admin.register(Post)
class PostAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    lv_request_initial_fields = {'category': ('category', 'category__id__exact')}
    list_display = ("title", "author", "moderation_state", "comments_count", "open_reports", "created_at")
    search_fields = ("title", "body", "author__email", "category__name")
    list_filter = ("category", "moderation_state", "created_at")
    readonly_fields = ("comments_panel", "created_at", "updated_at")
    fieldsets = (
        (
            "Dados do post",
            {
                "fields": (
                    "author",
                    "category",
                    "title",
                    "body",
                )
            },
        ),
        (
            "Comentários do post",
            {
                "fields": (
                    "comments_panel",
                )
            },
        ),
        (
            "Auditoria",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Moderação",
            {
                "fields": (
                    "moderation_state",
                    "moderated_by",
                    "moderated_at",
                    "moderation_note",
                )
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _comments_count=Count("comments", distinct=True),
            _open_reports=Count("reports", filter=Q(reports__status__in=ACTIVE_REPORT_STATUSES), distinct=True),
        )

    def comments_count(self, obj: Post):
        return getattr(obj, "_comments_count", 0)
    comments_count.short_description = "Comentários"
    comments_count.admin_order_field = "_comments_count"

    def open_reports(self, obj: Post):
        return getattr(obj, "_open_reports", 0)
    open_reports.short_description = "Denúncias abertas"
    open_reports.admin_order_field = "_open_reports"

    @admin.display(description="Comentários")
    def comments_panel(self, obj: Post):
        if not obj or not obj.pk:
            return format_html(
                '<div class="lv-empty-state">'
                '<p class="lv-empty-state__title">Salve o post para gerenciar comentários.</p>'
                '</div>'
            )

        comments = (
            obj.comments.select_related("author")
            .annotate(_open_reports=Count("reports", filter=Q(reports__status__in=ACTIVE_REPORT_STATUSES)))
            .order_by("-created_at", "-id")
        )
        comments_changelist_url = f"{reverse('admin:community_comment_changelist')}?post__id__exact={obj.id}"
        add_comment_url = f"{reverse('admin:community_comment_add')}?post={obj.id}"

        if not comments.exists():
            return format_html(
                '<div class="lv-empty-state">'
                '<p class="lv-empty-state__title">Este post ainda não possui comentários.</p>'
                '<p class="lv-empty-state__text">Use o botão abaixo para criar o primeiro comentário.</p>'
                "</div>"
                '<div class="lv-inline-actions"><a class="button" href="{}">Adicionar comentário</a></div>',
                add_comment_url,
            )

        rows = []
        for comment in comments:
            comment_url = reverse("admin:community_comment_change", args=[comment.id])
            comment_preview = Truncator((comment.body or "").strip()).chars(80) or "(Sem texto)"
            author_label = comment.author.email or comment.author.username or f"Usuário {comment.author_id}"
            rows.append(
                (
                    comment_url,
                    comment_preview,
                    author_label,
                    comment.get_moderation_state_display(),
                    getattr(comment, "_open_reports", 0),
                    timezone.localtime(comment.created_at).strftime("%d/%m/%Y %H:%M"),
                )
            )

        return format_html(
            '<div class="lv-inline-actions"><a class="button" href="{}">Ver lista completa de comentários</a></div>'
            '<table class="admin-comments-panel">'
            "<thead>"
            "<tr>"
            "<th>Comentário</th>"
            "<th>Autor</th>"
            "<th>Status de moderação</th>"
            "<th>Denúncias abertas</th>"
            "<th>Criado em</th>"
            "</tr>"
            "</thead>"
            "<tbody>{}</tbody>"
            "</table>",
            comments_changelist_url,
            format_html_join(
                "",
                "<tr>"
                '<td><a href="{}">{}</a></td>'
                "<td>{}</td>"
                "<td>{}</td>"
                "<td>{}</td>"
                "<td>{}</td>"
                "</tr>",
                rows,
            ),
        )

    def has_module_permission(self, request):
        return user_is_moderator_or_above(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    def has_add_permission(self, request):
        return user_is_owner_or_superuser(request.user)

    def has_change_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def has_delete_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def get_lv_parent_redirect_url(self, request, obj):
        if obj.category_id:
            return reverse('admin:community_category_change', args=[obj.category_id])
        return self._community_root_url()

    def get_lv_addanother_redirect_url(self, request, obj):
        if not obj.category_id:
            return None
        return admin_url('admin:community_post_add', params={'category': obj.category_id})

    def _community_root_url(self):
        return reverse("admin:community_category_changelist")

    def _build_post_changelist_url(self, category: Category | None):
        if not category:
            return reverse("admin:community_post_changelist")
        return f"{reverse('admin:community_post_changelist')}?category__id__exact={category.id}"

    def _get_category_from_request(self, request):
        category_id = request.GET.get("category__id__exact") or request.GET.get("category")
        if not category_id:
            return None
        try:
            return Category.objects.get(pk=category_id)
        except (Category.DoesNotExist, ValueError, TypeError):
            return None

    def changelist_view(self, request, extra_context=None):
        category = self._get_category_from_request(request)
        if category:
            path = [
                _nav_item("Comunidade", self._community_root_url()),
                _nav_item(category.name),
            ]
        else:
            path = [
                _nav_item("Comunidade", self._community_root_url()),
                _nav_item("Posts"),
            ]
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().changelist_view(request, extra_context=context)

    def add_view(self, request, form_url="", extra_context=None):
        category = self._get_category_from_request(request)
        path = [_nav_item("Comunidade", self._community_root_url())]
        if category:
            path.append(_nav_item(category.name, self._build_post_changelist_url(category)))
        else:
            path.append(_nav_item("Posts", reverse("admin:community_post_changelist")))
        path.append(_nav_item("Novo post"))
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().add_view(request, form_url=form_url, extra_context=context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        post_obj = self.get_object(request, object_id)
        category = getattr(post_obj, "category", None) if post_obj else None
        path = [_nav_item("Comunidade", self._community_root_url())]
        if category:
            path.append(_nav_item(category.name, self._build_post_changelist_url(category)))
        else:
            path.append(_nav_item("Sem categoria", reverse("admin:community_post_changelist")))
        if post_obj:
            path.append(_nav_item(post_obj.title))
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().change_view(request, object_id, form_url=form_url, extra_context=context)

@admin.register(Comment)
class CommentAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    lv_request_initial_fields = {'post': ('post', 'post__id__exact')}
    list_display = ("comment_preview", "author", "moderation_state", "open_reports", "created_at")
    search_fields = ("body", "author__email", "post__title")
    list_filter = ("moderation_state", "created_at",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Dados do comentário",
            {
                "fields": (
                    "post",
                    "author",
                    "body",
                )
            },
        ),
        (
            "Auditoria",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Moderação",
            {
                "fields": (
                    "moderation_state",
                    "moderated_by",
                    "moderated_at",
                    "moderation_note",
                )
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_open_reports=Count("reports", filter=Q(reports__status__in=ACTIVE_REPORT_STATUSES)))

    def open_reports(self, obj: Comment):
        return getattr(obj, "_open_reports", 0)
    open_reports.short_description = "Denúncias abertas"
    open_reports.admin_order_field = "_open_reports"

    @admin.display(description="Comentário")
    def comment_preview(self, obj: Comment):
        return Truncator((obj.body or "").strip()).chars(90) or "(Sem texto)"

    def has_module_permission(self, request):
        return user_is_moderator_or_above(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    def has_add_permission(self, request):
        return user_is_owner_or_superuser(request.user)

    def has_change_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def has_delete_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def get_lv_parent_redirect_url(self, request, obj):
        return reverse("admin:community_post_change", args=[obj.post_id])

    def get_lv_addanother_redirect_url(self, request, obj):
        return admin_url('admin:community_comment_add', params={'post': obj.post_id})

    def _community_root_url(self):
        return reverse("admin:community_category_changelist")

    def _build_post_changelist_url(self, category: Category | None):
        if not category:
            return reverse("admin:community_post_changelist")
        return f"{reverse('admin:community_post_changelist')}?category__id__exact={category.id}"

    def _get_post_from_request(self, request):
        post_id = request.GET.get("post__id__exact") or request.GET.get("post")
        if not post_id:
            return None
        try:
            return Post.objects.select_related("category").get(pk=post_id)
        except (Post.DoesNotExist, ValueError, TypeError):
            return None

    def changelist_view(self, request, extra_context=None):
        post_obj = self._get_post_from_request(request)
        path = [_nav_item("Comunidade", self._community_root_url())]
        if post_obj:
            category = post_obj.category
            if category:
                path.append(_nav_item(category.name, self._build_post_changelist_url(category)))
            path.append(_nav_item(post_obj.title, reverse("admin:community_post_change", args=[post_obj.id])))
            path.append(_nav_item("Comentários"))
        else:
            path.append(_nav_item("Comentários"))
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().changelist_view(request, extra_context=context)

    def add_view(self, request, form_url="", extra_context=None):
        post_obj = self._get_post_from_request(request)
        path = [_nav_item("Comunidade", self._community_root_url())]
        if post_obj:
            category = post_obj.category
            if category:
                path.append(_nav_item(category.name, self._build_post_changelist_url(category)))
            path.append(_nav_item(post_obj.title, reverse("admin:community_post_change", args=[post_obj.id])))
            path.append(_nav_item("Novo comentário"))
        else:
            path.append(_nav_item("Comentários", reverse("admin:community_comment_changelist")))
            path.append(_nav_item("Novo comentário"))
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().add_view(request, form_url=form_url, extra_context=context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        comment_obj = self.get_object(request, object_id)
        path = [_nav_item("Comunidade", self._community_root_url())]
        if comment_obj:
            post_obj = comment_obj.post
            category = post_obj.category
            if category:
                path.append(_nav_item(category.name, self._build_post_changelist_url(category)))
            path.append(_nav_item(post_obj.title, reverse("admin:community_post_change", args=[post_obj.id])))
            path.append(_nav_item(f"Comentário #{comment_obj.id}"))
        else:
            path.append(_nav_item("Comentários"))
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().change_view(request, object_id, form_url=form_url, extra_context=context)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("catalog_entry", "slug", "posts_count", "edit_category", "created_at", "updated_at")
    list_display_links = None
    search_fields = ('name', 'slug')
    readonly_fields = ("posts_panel_links", "created_at", "updated_at")
    fieldsets = (
        (
            "Dados da categoria",
            {
                "fields": (
                    "name",
                    "slug",
                    "description",
                )
            },
        ),
        (
            "Posts da categoria",
            {
                "fields": (
                    "posts_panel_links",
                )
            },
        ),
        (
            "Auditoria",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_posts_count=Count("posts", distinct=True))

    @admin.display(description="Categoria")
    def catalog_entry(self, obj: Category):
        url = f"{reverse('admin:community_post_changelist')}?category__id__exact={obj.id}"
        return format_html('<a href="{}">{}</a>', url, obj.name)

    @admin.display(description="Posts")
    def posts_count(self, obj: Category):
        return getattr(obj, "_posts_count", 0)

    @admin.display(description="Editar categoria")
    def edit_category(self, obj: Category):
        url = reverse("admin:community_category_change", args=[obj.id])
        return format_html('<a href="{}">Editar</a>', url)

    @admin.display(description="Ações")
    def posts_panel_links(self, obj: Category):
        if not obj or not obj.pk:
            return format_html(
                '<div class="lv-empty-state">'
                '<p class="lv-empty-state__title">Salve a categoria para acessar os posts.</p>'
                '</div>'
            )

        posts_url = f"{reverse('admin:community_post_changelist')}?category__id__exact={obj.id}"
        add_post_url = f"{reverse('admin:community_post_add')}?category={obj.id}"
        return format_html(
            '<div class="lv-inline-actions">'
            '<a class="button" href="{}">Abrir posts da categoria</a> '
            '<a class="button" href="{}">Criar novo post</a>'
            '</div>',
            posts_url,
            add_post_url,
        )

    def has_module_permission(self, request):
        return user_is_owner_or_superuser(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def has_add_permission(self, request):
        return user_is_owner_or_superuser(request.user)

    def has_change_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def has_delete_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def changelist_view(self, request, extra_context=None):
        path = [_nav_item("Comunidade")]
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().changelist_view(request, extra_context=context)

    def add_view(self, request, form_url="", extra_context=None):
        path = [_nav_item("Comunidade", reverse("admin:community_category_changelist")), _nav_item("Nova categoria")]
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().add_view(request, form_url=form_url, extra_context=context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        category = self.get_object(request, object_id)
        path = [_nav_item("Comunidade", reverse("admin:community_category_changelist"))]
        if category:
            path.append(_nav_item(category.name))
        context = _merge_extra_context(extra_context, navigation_path=path)
        return super().change_view(request, object_id, form_url=form_url, extra_context=context)


@admin.register(ReportModerationAction)
class ReportModerationActionAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "action_type", "actor", "from_status", "to_status", "created_at")
    list_filter = ("action_type", "from_status", "to_status", "created_at")
    search_fields = ("report__id", "actor__username", "note")
    ordering = ("-created_at",)
    readonly_fields = (
        "report",
        "action_type",
        "actor",
        "from_status",
        "to_status",
        "from_priority",
        "to_priority",
        "decision",
        "note",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return user_is_moderator_or_above(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)


@admin.register(ModerationConfig)
class ModerationConfigAdmin(admin.ModelAdmin):
    list_display = (
        'singleton_key',
        'reports_per_warning',
        'max_warnings_before_ban',
        'auto_ban_on_threshold',
        'ban_scope',
        'updated_at',
    )
    readonly_fields = ('singleton_key', 'updated_at')

    def has_module_permission(self, request):
        return user_is_owner_or_superuser(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def has_change_permission(self, request, obj=None):
        return user_is_owner_or_superuser(request.user)

    def has_add_permission(self, request):
        if not user_is_owner_or_superuser(request.user):
            return False
        return not ModerationConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserModerationStatus)
class UserModerationStatusAdmin(admin.ModelAdmin):
    action_form = UserModerationActionForm
    list_display = (
        'user',
        'warnings_issued',
        'is_banned',
        'ban_scope',
        'banned_at',
        'last_warning_at',
        'updated_at',
    )
    list_filter = ('is_banned', 'ban_scope', 'pending_login_message_level')
    search_fields = ('user__email', 'user__username', 'ban_reason')
    readonly_fields = ('warnings_issued', 'last_warning_at', 'pending_login_message_created_at', 'updated_at')
    actions = ('ban_selected_users',)

    def has_module_permission(self, request):
        return user_is_moderator_or_above(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    def has_change_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    @admin.action(description='Banir usuário(s) selecionado(s)')
    def ban_selected_users(self, request, queryset):
        if str(request.POST.get("confirm_sensitive_action", "")).lower() not in {"1", "true", "on", "yes"}:
            self.message_user(
                request,
                'Confirme a ação sensível para banir usuários em massa.',
                level=messages.ERROR,
            )
            return

        ban_reason = (request.POST.get("ban_reason") or "").strip()
        if not ban_reason:
            self.message_user(
                request,
                'Informe o motivo do banimento.',
                level=messages.ERROR,
            )
            return

        processed = 0
        for status_obj in queryset.select_related('user'):
            ban_user_from_app(
                user=status_obj.user,
                actor=request.user,
                reason=ban_reason,
            )
            processed += 1
        if processed:
            self.message_user(request, f'{processed} usuário(s) banido(s).', level=messages.SUCCESS)


@admin.register(UserModerationEvent)
class UserModerationEventAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'action_type',
        'warning_number',
        'removed_reports_total',
        'actor',
        'report',
        'created_at',
    )
    list_filter = ('action_type', 'created_at')
    search_fields = ('user__email', 'actor__email', 'note')
    ordering = ('-created_at',)
    readonly_fields = (
        'user',
        'actor',
        'report',
        'action_type',
        'warning_number',
        'removed_reports_total',
        'note',
        'created_at',
    )

    def has_module_permission(self, request):
        return user_is_moderator_or_above(request.user)

    def has_view_permission(self, request, obj=None):
        return user_is_moderator_or_above(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
