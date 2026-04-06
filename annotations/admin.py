from django.db.models import Count

from django.contrib import admin

from .models import Annotation


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    change_list_template = 'admin/annotations/annotation/change_list.html'
    list_display = (
        'user',
        'book_version',
        'chapter',
        'start_offset',
        'end_offset',
        'color',
        'updated_at',
    )
    list_filter = ('user', 'color', 'book_version', 'chapter')
    search_fields = ('user__email', 'note', 'excerpt', 'chapter__title', 'chapter__slug')

    USER_FILTER_PARAM = 'user__id__exact'

    def _is_changelist_request(self, request):
        resolver_match = getattr(request, 'resolver_match', None)
        if not resolver_match:
            return False
        expected_name = f'{self.model._meta.app_label}_{self.model._meta.model_name}_changelist'
        return resolver_match.url_name == expected_name

    def _group_mode_enabled(self, request):
        if not self._is_changelist_request(request):
            return False
        if request.GET.get('q'):
            return False
        return self.USER_FILTER_PARAM not in request.GET

    def _annotation_user_groups(self, request):
        queryset = super().get_queryset(request)
        grouped = (
            queryset.values('user_id', 'user__email', 'user__username')
            .annotate(total=Count('id'))
            .order_by('user__email', 'user__username', 'user_id')
        )
        groups = []
        for row in grouped:
            label = row['user__email'] or row['user__username'] or f"Usuário #{row['user_id']}"
            groups.append(
                {
                    'user_id': row['user_id'],
                    'label': label,
                    'total': row['total'],
                }
            )
        return groups

    def get_queryset(self, request):
        queryset = (
            super()
            .get_queryset(request)
            .select_related('user', 'book_version', 'chapter')
        )
        if self._group_mode_enabled(request):
            return queryset.none()
        return queryset

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        if self._group_mode_enabled(request):
            extra_context.update(
                {
                    'annotation_group_by_user': True,
                    'annotation_user_groups': self._annotation_user_groups(request),
                    'annotation_user_filter_param': self.USER_FILTER_PARAM,
                }
            )
        return super().changelist_view(request, extra_context=extra_context)
